"""Job asincroni del laboratorio (spec SP1 §9, §10)."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.lab import jobs
from backend.app.lab.contracts import LabError
from backend.app.lab.jobs import (
    JobCancelled,
    JobContext,
    JobNotCancellable,
    JobOutcome,
    JobRecord,
    JobService,
    register_job_handler,
)
from backend.app.services.fx_service import FxBackfillResult, FXService


@pytest.fixture()
def handlers(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Registro degli handler isolato per test: i registrati qui spariscono a fine test."""
    registry = dict(jobs._HANDLERS)
    monkeypatch.setattr(jobs, "_HANDLERS", registry)
    return registry


def _wait_for(service: JobService, job_id: int, statuses: set[str], timeout: float = 5.0) -> JobRecord:
    deadline = time.monotonic() + timeout
    while True:
        record = service.get(job_id)
        assert record is not None
        if record.status in statuses or time.monotonic() > deadline:
            return record
        time.sleep(0.02)


def test_inline_job_runs_and_stores_result(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    seen: list[tuple[int, dict]] = []

    def handler(context: JobContext, params) -> JobOutcome:  # noqa: ANN001
        seen.append((context.job_id, dict(params)))
        context.set_progress(0.5)
        context.raise_if_cancelled()
        return JobOutcome(result_ref="run-7", result={"value": params["x"] * 2})

    register_job_handler("EVIDENCE", handler)

    job = JobService("inline").enqueue("EVIDENCE", {"x": 21})

    assert job.status == "SUCCEEDED"
    assert (job.result_ref, job.result, job.progress) == ("run-7", {"value": 42}, 1.0)
    assert job.params == {"x": 21}
    assert job.error_code is None and job.error_message is None
    assert job.started_at is not None and job.finished_at is not None
    assert seen == [(job.id, {"x": 21})]
    assert JobService("inline").get(job.id) == job


def test_identical_open_job_is_deduplicated(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    register_job_handler("EVIDENCE", lambda context, params: JobOutcome())
    service = JobService("thread")  # worker non avviato: i job restano QUEUED

    first = service.enqueue("EVIDENCE", {"b": 1, "a": [1, 2]})
    second = service.enqueue("EVIDENCE", {"a": [1, 2], "b": 1})
    other = service.enqueue("EVIDENCE", {"a": [1, 2], "b": 2})

    assert second.id == first.id
    assert second.status == "QUEUED"
    assert other.id != first.id
    assert [job.id for job in service.list()] == [other.id, first.id]
    assert [job.id for job in service.list(status="QUEUED", limit=1)] == [other.id]


def test_cancel_queued_job(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    calls: list[int] = []
    register_job_handler("EVIDENCE", lambda context, params: calls.append(context.job_id) or JobOutcome())
    service = JobService("thread")
    job = service.enqueue("EVIDENCE", {"n": 1})

    cancelled = service.cancel(job.id)

    assert cancelled.status == "CANCELLED"
    assert cancelled.cancel_requested is True
    assert cancelled.finished_at is not None
    # Un job concluso non blocca un nuovo job identico.
    assert service.enqueue("EVIDENCE", {"n": 1}).id != job.id
    assert calls == []


def test_cancel_finished_job_raises_not_cancellable(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    register_job_handler("EVIDENCE", lambda context, params: JobOutcome())
    service = JobService("inline")
    job = service.enqueue("EVIDENCE", {})

    with pytest.raises(JobNotCancellable) as error:
        service.cancel(job.id)

    assert error.value.code == "JOB_NOT_CANCELLABLE"
    assert service.get(job.id).status == "SUCCEEDED"


def test_running_job_cancels_cooperatively(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    started = threading.Event()
    release = threading.Event()

    def handler(context: JobContext, params) -> JobOutcome:  # noqa: ANN001
        started.set()
        assert release.wait(5)
        context.raise_if_cancelled()
        return JobOutcome(result={"done": True})

    register_job_handler("EVIDENCE", handler)
    service = JobService("thread")
    service.start()
    try:
        job = service.enqueue("EVIDENCE", {})
        assert started.wait(5)
        assert service.get(job.id).status == "RUNNING"

        requested = service.cancel(job.id)
        assert (requested.status, requested.cancel_requested) == ("RUNNING", True)
        release.set()

        final = _wait_for(service, job.id, {"CANCELLED", "SUCCEEDED", "FAILED"})
    finally:
        release.set()
        service.stop()

    assert final.status == "CANCELLED"
    assert final.result is None
    assert final.finished_at is not None


def test_thread_worker_runs_jobs_in_fifo_order(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    order: list[int] = []
    register_job_handler("EVIDENCE", lambda context, params: order.append(params["n"]) or JobOutcome())
    service = JobService("thread")
    queued = [service.enqueue("EVIDENCE", {"n": n}).id for n in (1, 2, 3)]

    service.start()
    try:
        finals = [_wait_for(service, job_id, {"SUCCEEDED", "FAILED"}) for job_id in queued]
    finally:
        service.stop()

    assert [job.status for job in finals] == ["SUCCEEDED"] * 3
    assert order == [1, 2, 3]


def test_recover_interrupted_marks_running_jobs(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    register_job_handler("EVIDENCE", lambda context, params: JobOutcome())
    service = JobService("thread")
    running = service.enqueue("EVIDENCE", {"n": 1})
    queued = service.enqueue("EVIDENCE", {"n": 2})
    lab_connection.execute(
        "UPDATE lab_jobs SET status = 'RUNNING', started_at = '2024-01-10T12:00:00' WHERE id = ?", (running.id,)
    )
    lab_connection.commit()

    assert service.recover_interrupted() == 1

    interrupted = service.get(running.id)
    assert interrupted.status == "INTERRUPTED"
    assert interrupted.finished_at is not None
    assert service.get(queued.id).status == "QUEUED"
    assert service.recover_interrupted() == 0


def test_lab_error_is_reported_with_code(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    def handler(context: JobContext, params) -> JobOutcome:  # noqa: ANN001
        raise LabError("LAB_NO_REAL_SERIES", "Nessun asset con serie reale.")

    register_job_handler("EVIDENCE", handler)

    job = JobService("inline").enqueue("EVIDENCE", {})

    assert job.status == "FAILED"
    assert (job.error_code, job.error_message) == ("LAB_NO_REAL_SERIES", "Nessun asset con serie reale.")
    assert job.finished_at is not None


def test_unexpected_error_hides_exception_text(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    def handler(context: JobContext, params) -> JobOutcome:  # noqa: ANN001
        raise RuntimeError("secret-token-123")

    register_job_handler("EVIDENCE", handler)

    job = JobService("inline").enqueue("EVIDENCE", {})

    assert job.status == "FAILED"
    assert (job.error_code, job.error_message) == ("INTERNAL_ERROR", "Errore interno del job.")
    stored = lab_connection.execute("SELECT * FROM lab_jobs WHERE id = ?", (job.id,)).fetchone()
    assert "secret-token-123" not in repr(job)
    assert all("secret-token-123" not in str(value) for value in tuple(stored))


def test_job_cancelled_inside_handler_is_cancelled(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    def handler(context: JobContext, params) -> JobOutcome:  # noqa: ANN001
        raise JobCancelled()

    register_job_handler("EVIDENCE", handler)

    assert JobService("inline").enqueue("EVIDENCE", {}).status == "CANCELLED"


def test_unregistered_kind_is_refused_without_a_job(lab_connection: sqlite3.Connection, handlers: dict) -> None:
    handlers.pop("ML_TRAIN", None)

    with pytest.raises(LabError) as error:
        JobService("inline").enqueue("ML_TRAIN", {})

    assert error.value.code == "JOB_KIND_UNAVAILABLE"
    assert lab_connection.execute("SELECT COUNT(*) FROM lab_jobs").fetchone()[0] == 0


def test_lab_jobs_schema_dedupes_open_jobs_only(lab_connection: sqlite3.Connection) -> None:
    insert = (
        "INSERT INTO lab_jobs (kind, status, params_json, params_hash, created_at) "
        "VALUES ('EVIDENCE', ?, '{}', ?, '2024-01-10T12:00:00')"
    )
    digest = "a" * 64
    lab_connection.execute(insert, ("QUEUED", digest))
    with pytest.raises(sqlite3.IntegrityError):
        lab_connection.execute(insert, ("RUNNING", digest))
    lab_connection.execute(insert, ("SUCCEEDED", digest))
    lab_connection.execute(insert, ("FAILED", digest))
    with pytest.raises(sqlite3.IntegrityError):
        lab_connection.execute(insert, ("DONE", "b" * 64))
    with pytest.raises(sqlite3.IntegrityError):
        lab_connection.execute(insert, ("QUEUED", "short"))


# --- API -------------------------------------------------------------------------------------------------


def test_lab_job_routes_report_missing_and_not_cancellable_jobs(client: TestClient) -> None:
    assert client.get("/lab/jobs/999").status_code == 404
    assert client.post("/lab/jobs/999/cancel").status_code == 404
    assert client.get("/lab/jobs?limit=0").status_code == 422
    assert client.get("/lab/jobs?status=DONE").status_code == 422

    job = client.post("/lab/features/refresh", json={"asset_ids": [1], "data_mode": "REAL"}).json()
    response = client.post(f"/lab/jobs/{job['id']}/cancel")

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "JOB_NOT_CANCELLABLE"
    assert client.get(f"/lab/jobs/{job['id']}").json()["status"] == "SUCCEEDED"
    assert [item["id"] for item in client.get("/lab/jobs?limit=5").json()] == [job["id"]]


def test_feature_refresh_route_runs_job_with_counts(client: TestClient) -> None:
    from backend.app.database import db_session

    with db_session() as connection:
        asset_id = connection.execute("SELECT id FROM assets WHERE symbol = 'AAPL'").fetchone()[0]
        stored = connection.execute("SELECT COUNT(*) FROM features_daily WHERE asset_id = ?", (asset_id,)).fetchone()[0]

    response = client.post("/lab/features/refresh", json={"asset_ids": [asset_id, asset_id]})

    assert response.status_code == 202
    job = response.json()
    assert (job["kind"], job["status"], job["progress"]) == ("FEATURE_REFRESH", "SUCCEEDED", 1.0)
    assert job["params"] == {"asset_ids": [asset_id], "data_mode": None}
    result = job["result"]
    assert set(result) == {"assets", "inserted", "updated", "deleted", "unchanged"}
    assert result["assets"] == 1
    assert result["unchanged"] > 0
    with db_session() as connection:
        after = connection.execute("SELECT COUNT(*) FROM features_daily WHERE asset_id = ?", (asset_id,)).fetchone()[0]
    assert after == stored + result["inserted"] - result["deleted"]
    assert after == result["inserted"] + result["updated"] + result["unchanged"]


def test_fx_backfill_route_requires_real_data(client: TestClient) -> None:
    response = client.post("/data/fx/backfill", json={"currencies": ["USD"], "start_date": "2024-01-02"})

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "REAL_DATA_DISABLED"
    assert client.get("/lab/jobs").json() == []


def test_fx_backfill_route_enqueues_job_with_real_data(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    calls: list[tuple[str, date]] = []

    def fake_backfill(self, connection, currency, start, now=None):  # noqa: ANN001, ANN202
        assert not connection.in_transaction
        calls.append((currency, start))
        return FxBackfillResult(currency, 10, 2, "2024-01-02", "2024-01-15")

    monkeypatch.setattr(FXService, "backfill_history", fake_backfill)
    future = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    assert client.post("/data/fx/backfill", json={"currencies": ["XYZ"], "start_date": "2024-01-02"}).status_code == 422
    assert client.post("/data/fx/backfill", json={"currencies": ["USD"], "start_date": "2024-02-30"}).status_code == 422
    assert client.post("/data/fx/backfill", json={"currencies": ["USD"], "start_date": future}).status_code == 422
    assert client.post("/data/fx/backfill", json={"currencies": [], "start_date": "2024-01-02"}).status_code == 422
    assert calls == []

    response = client.post(
        "/data/fx/backfill", json={"currencies": ["usd", "GBP", "USD"], "start_date": "2024-01-02"}
    )

    assert response.status_code == 202
    job = response.json()
    assert (job["kind"], job["status"]) == ("FX_BACKFILL", "SUCCEEDED")
    assert job["params"] == {"currencies": ["USD", "GBP"], "start_date": "2024-01-02"}
    assert calls == [("USD", date(2024, 1, 2)), ("GBP", date(2024, 1, 2))]
    expected = {"inserted": 10, "existing": 2, "first_observed_at": "2024-01-02", "last_observed_at": "2024-01-15"}
    assert job["result"] == {"currencies": {"USD": expected, "GBP": expected}}


def test_stop_start_keeps_one_worker_and_does_not_interrupt_live_job(
    lab_connection: sqlite3.Connection, handlers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    calls = []

    def handler(context, params):
        calls.append(context.job_id)
        if params["block"]:
            entered.set()
            assert release.wait(5)
        return JobOutcome(result={"done": True})

    register_job_handler("EVIDENCE", handler)
    monkeypatch.setattr(jobs, "_STOP_TIMEOUT_SECONDS", 0.01)
    service = JobService("thread")
    first = service.enqueue("EVIDENCE", {"block": True})
    second = service.enqueue("EVIDENCE", {"block": False})
    service.start()
    assert entered.wait(5)
    worker = service._thread
    try:
        service.stop()
        assert worker is not None and worker.is_alive()
        assert service._thread is worker
        assert service.recover_interrupted() == 0
        assert service.get(first.id).status == "RUNNING"
        service.start()
        assert service._thread is worker
        release.set()
        assert _wait_for(service, second.id, {"SUCCEEDED"}).status == "SUCCEEDED"
        assert calls == [first.id, second.id]
    finally:
        release.set()
        service.stop()
        worker.join(timeout=5)
        assert not worker.is_alive()

def test_restart_after_worker_observes_stop_drains_queue(lab_connection, handlers, monkeypatch) -> None:
    entered, release, observed, allow_exit, restarted = (threading.Event() for _ in range(5))
    service = JobService("thread")
    original_is_set = service._stopping.is_set

    def paused_is_set():
        value = original_is_set()
        if value:
            observed.set()
            assert allow_exit.wait(5)
        return value

    def handler(context, params):
        if params["block"]:
            entered.set()
            assert release.wait(5)
        return JobOutcome()

    monkeypatch.setattr(service._stopping, "is_set", paused_is_set)
    monkeypatch.setattr(jobs, "_STOP_TIMEOUT_SECONDS", 0.01)
    register_job_handler("EVIDENCE", handler)
    service.enqueue("EVIDENCE", {"block": True})
    second = service.enqueue("EVIDENCE", {"block": False})
    service.start()
    assert entered.wait(5)
    old_worker = service._thread
    starter = threading.Thread(target=lambda: (service.start(), restarted.set()), daemon=True)
    try:
        service.stop()
        release.set()
        assert observed.wait(5)
        starter.start()
        # start cannot reuse a worker whose exit has already been decided.
        assert not restarted.wait(0.05)
        allow_exit.set()
        assert restarted.wait(5)
        assert _wait_for(service, second.id, {"SUCCEEDED"}).status == "SUCCEEDED"
    finally:
        release.set()
        allow_exit.set()
        starter.join(timeout=5)
        service.stop()
        old_worker.join(timeout=5)
