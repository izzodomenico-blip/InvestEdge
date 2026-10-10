"""Verdetti e report append-only, soltanto fixture locali e database temporanei."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import get_settings
from backend.app.lab.evidence import EvidenceThresholds, decide_verdict, evaluate_evidence, run_evidence
from backend.app.lab.stats import sharpe_daily
from backend.app.models import EvidenceIn
from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars
from tests.test_lab_harness import COSTS, evaluate, synthetic_inputs

NOW = datetime(2024, 1, 1, tzinfo=UTC)
THRESHOLDS = EvidenceThresholds(10, 252, 252, 2, 0.95)


def trial_sharpes(results):
    return [value for _, result in results if (value := sharpe_daily(result.daily_returns)) is not None]


def outcomes(inputs):
    return evaluate_evidence(
        inputs, [1], thresholds=THRESHOLDS, costs=COSTS, reference_capital_eur=10_000, trial_sharpes=trial_sharpes
    )


def test_constructed_signal_is_validato():
    result = outcomes(synthetic_inputs())[0]
    assert result.verdict == "VALIDATO"
    assert result.walk_forward["dsr"]["dsr"] >= 0.95
    assert result.walk_forward["oos_sessions"] >= 252


def test_random_signal_is_non_validato():
    assert outcomes(synthetic_inputs(predictive=False))[0].verdict == "NON_VALIDATO"


def test_short_sample_is_insufficiente():
    result = outcomes(synthetic_inputs(sessions=300))[0]
    assert result.verdict == "INSUFFICIENTE"
    assert result.walk_forward is None


def test_few_names_is_insufficiente():
    assert outcomes(synthetic_inputs(assets=8))[0].verdict == "INSUFFICIENTE"


@pytest.mark.parametrize("field", ["ic_mean", "t_nw", "spread_net"])
def test_verdict_fails_closed_on_nonfinite_metrics(field):
    harness = replace(evaluate(synthetic_inputs()), **{field: float("nan")})
    assert decide_verdict(harness, 600, 1, THRESHOLDS) == "NON_VALIDATO"


@pytest.mark.parametrize(
    "payload",
    [
        {"signal_name": "unknown"},
        {"horizons": [2]},
        {"horizons": []},
        {"symbols": [" "]},
        {"data_mode": "DEMO"},
        {"end_date": "2017-01-01"},
        {"start_date": "2024-02-30"},
        {"horizons": [True]},
    ],
)
def test_request_rejects_invalid_or_demo_configuration(payload):
    with pytest.raises(ValidationError):
        EvidenceIn.model_validate(
            {"signal_name": "score", "start_date": "2018-01-01", "end_date": "2024-01-01", **payload}
        )


@pytest.fixture
def real_db(lab_connection):
    for n in range(12):
        asset = insert_asset(lab_connection, f"E{n}")
        insert_bars(lab_connection, asset, synthetic_bars(400, 50 + n), real=True, provider="stooq")
    lab_connection.commit()
    return lab_connection


def request():
    return EvidenceIn(signal_name="score", start_date="2018-01-01", end_date="2020-01-01")


def test_reports_are_immutable(real_db):
    ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    assert len(ids) == 3
    for statement in (
        "UPDATE lab_evidence_reports SET verdict='VALIDATO' WHERE id=?",
        "DELETE FROM lab_evidence_reports WHERE id=?",
        "INSERT OR REPLACE INTO lab_evidence_reports SELECT * FROM lab_evidence_reports WHERE id=?",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            real_db.execute(statement, (ids[0],))
    assert real_db.execute("SELECT COUNT(*) FROM lab_evidence_reports").fetchone()[0] == 3


def test_saved_reports_survive_source_revision(real_db):
    ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    old = [tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (i,)).fetchone()) for i in ids]
    real_db.execute("UPDATE price_history SET open=open*1.1, high=high*1.1, low=low*1.1, close=close*1.1")
    real_db.commit()
    new_ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    for i, snapshot in zip(ids, old, strict=True):
        assert tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (i,)).fetchone()) == snapshot
    before = real_db.execute("SELECT fingerprint FROM lab_evidence_reports WHERE id=?", (ids[0],)).fetchone()[0]
    after = real_db.execute("SELECT fingerprint FROM lab_evidence_reports WHERE id=?", (new_ids[0],)).fetchone()[0]
    assert before != after


def test_evidence_refuses_demo_only_universe(client):
    response = client.post("/lab/evidence", json=request().model_dump())
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "LAB_NO_REAL_SERIES"


def test_evidence_api_reports_and_latest(real_db, monkeypatch):
    monkeypatch.setenv("LAB_JOBS_EXECUTOR", "inline")
    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    monkeypatch.setenv("ENABLE_ALERTS", "false")
    get_settings.cache_clear()
    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        response = client.post("/lab/evidence", json=request().model_dump())
        assert response.status_code == 202
        job = response.json()
        assert job["kind"] == "EVIDENCE"
        assert job["status"] == "SUCCEEDED"
        assert len(job["result"]["report_ids"]) == 3
        reports = client.get("/lab/evidence").json()
        assert len(reports) == 3
        assert {r["verdict"] for r in reports} == {"INSUFFICIENTE"}
        latest = client.get("/lab/evidence/latest").json()
        assert set(latest["horizons"]) == {"1", "5", "21"}
        assert latest["best"]["verdict"] == "INSUFFICIENTE"
        report = client.get(f"/lab/evidence/{job['result']['report_ids'][0]}").json()
        assert report["config"]["data_mode"] == "REAL"
        assert "survivorship_bias" in report["limits"]
        assert report["walk_forward"] is None
        assert len(report["fingerprint"]) == 64
        json.dumps(report, allow_nan=False)
        assert client.get("/lab/evidence/999999").status_code == 404
        assert "score" in client.get("/lab/signals").json()
        assert (
            client.post("/lab/evidence", json={**request().model_dump(), "signal_name": "invalid"}).status_code == 422
        )
        second_job = client.post("/lab/evidence", json=request().model_dump()).json()
        assert second_job["id"] != job["id"]
        assert second_job["result"]["report_ids"] != job["result"]["report_ids"]


def test_verdict_threshold_boundaries_and_missing_metrics():
    from backend.app.lab.harness import HarnessResult

    harness = HarnessResult(1, 252, 0.01, 0.1, 0.1, 0.6, 2, 10, 5, [0] * 5, 0.02, 0.01, 0.5, 0.2)
    assert decide_verdict(harness, 252, 0.95, THRESHOLDS) == "VALIDATO"
    for modified in (replace(harness, ic_dates=251), replace(harness, mean_names=9.999)):
        assert decide_verdict(modified, 252, 0.95, THRESHOLDS) == "INSUFFICIENTE"
    assert decide_verdict(harness, 251, 0.95, THRESHOLDS) == "INSUFFICIENTE"
    for modified in (
        replace(harness, ic_mean=0),
        replace(harness, t_nw=1.999),
        replace(harness, spread_net=0),
        replace(harness, t_nw=None),
    ):
        assert decide_verdict(modified, 252, 0.95, THRESHOLDS) == "NON_VALIDATO"
    for dsr in (None, float("nan"), float("inf"), 0.9499):
        assert decide_verdict(harness, 252, dsr, THRESHOLDS) == "NON_VALIDATO"


def test_all_horizons_use_one_family_snapshot_independent_of_order():
    inputs = synthetic_inputs(assets=10, sessions=280)
    calls = []

    def capture(results):
        calls.append(len(results))
        return trial_sharpes(results)

    kwargs = {
        "thresholds": THRESHOLDS,
        "costs": COSTS,
        "reference_capital_eur": 10_000,
        "trial_sharpes": capture,
        "is_sessions": 200,
        "oos_sessions": 80,
    }
    before = evaluate_evidence(inputs, [1, 5, 21], **kwargs)
    after = evaluate_evidence(inputs, [21, 5, 1], **kwargs)
    assert calls == [9, 9]
    assert before == after
    for result in before:
        wf = result.walk_forward
        assert wf["n_trials"] == 9
        assert wf["trial_sharpes"] == before[0].walk_forward["trial_sharpes"]
        assert wf["oos_sessions"] == 80
        assert wf["oos_observations"] == 79
        assert set(wf["oos_metrics"]) >= {
            "final_value_eur",
            "total_return_percent",
            "cagr",
            "max_drawdown",
            "profit_factor",
            "win_rate",
            "total_trades",
        }
        assert wf["units"]["oos_metrics.sharpe_ratio"] == "annualized_sqrt_252"


def test_demo_pure_evidence_is_rejected():
    from backend.app.lab.contracts import LabError

    with pytest.raises(LabError, match="LAB_EVIDENCE_REAL_ONLY"):
        evaluate_evidence(
            synthetic_inputs(sessions=20),
            [1],
            thresholds=THRESHOLDS,
            costs=COSTS,
            reference_capital_eur=10_000,
            trial_sharpes=trial_sharpes,
            data_mode="DEMO",
        )


def test_threshold_change_changes_new_fingerprint_without_changing_saved_report(real_db, monkeypatch):
    ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    before = tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (ids[0],)).fetchone())
    monkeypatch.setenv("LAB_MIN_DSR", "0.99")
    get_settings.cache_clear()
    new_ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    after = real_db.execute(
        "SELECT fingerprint, config_json FROM lab_evidence_reports WHERE id=?", (new_ids[0],)
    ).fetchone()
    assert json.loads(after[1])["thresholds"]["min_dsr"] == 0.99
    assert after[0] != before[-2]
    assert tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (ids[0],)).fetchone()) == before


def _stage_trial_without_expensive_simulation(monkeypatch):
    # Isola il confine transazionale dopo il calcolo; math/WF sono coperti con simulazioni vere sopra.
    import pandas as pd

    import backend.app.lab.evidence as module
    from backend.app.lab.evidence import EvidenceOutcome
    from backend.app.lab.harness import HarnessResult
    from backend.app.lab.simulator import SimulationResult
    from backend.app.lab.strategies import StrategyParams

    def computed(inputs, horizons, *, trial_sharpes, checkpoint, **kwargs):
        returns = pd.Series([0.01, -0.002, 0.015], index=inputs.calendar[1:4])
        simulation = SimulationResult(pd.DataFrame(), (), (), returns, {}, 0, 0)
        trial_sharpes([(StrategyParams("TOP_N_SCORE"), simulation)])
        checkpoint(1)
        harness = HarnessResult(1, 0, None, None, None, None, None, 0, 5, [None] * 5, None, None, None, None)
        return [EvidenceOutcome(h, "INSUFFICIENTE", replace(harness, horizon=h), None) for h in horizons]

    monkeypatch.setattr(module, "evaluate_evidence", computed)


def test_cancel_after_computation_leaves_no_trials_or_reports(real_db, monkeypatch):
    from backend.app.lab.jobs import JobCancelled

    _stage_trial_without_expensive_simulation(monkeypatch)

    def cancel(progress):
        if progress >= 0.95:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        run_evidence(real_db, request(), job_id=None, now=NOW, checkpoint=cancel)
    assert real_db.execute("SELECT COUNT(*) FROM lab_trials").fetchone()[0] == 0
    assert real_db.execute("SELECT COUNT(*) FROM lab_evidence_reports").fetchone()[0] == 0


def test_failed_second_report_rolls_back_trials_and_all_reports(real_db, monkeypatch):
    _stage_trial_without_expensive_simulation(monkeypatch)
    real_db.execute("""CREATE TRIGGER fail_second_report BEFORE INSERT ON lab_evidence_reports
                       WHEN NEW.horizon=5 BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
    real_db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        run_evidence(real_db, request(), job_id=None, now=NOW)
    assert real_db.execute("SELECT COUNT(*) FROM lab_trials").fetchone()[0] == 0
    assert real_db.execute("SELECT COUNT(*) FROM lab_evidence_reports").fetchone()[0] == 0


def test_fx_revision_freezes_old_report_and_missing_bar_does_not_shift_entry(real_db):
    import numpy as np

    from backend.app.lab.evidence import _source_calendars
    from backend.app.lab.harness import forward_open_returns
    from backend.app.lab.universe import build_universe_inputs
    from tests.lab_fixtures import insert_fx

    asset = insert_asset(real_db, "USDTEST", currency="USD")
    bars = synthetic_bars(400, 77)
    insert_bars(real_db, asset, bars, real=True, provider="stooq")
    # Cambi validi nel passato, buco >7 giorni, poi ripresa.
    rows = [
        (str(day), 0.9)
        for day in bars["date"]
        if not (str(bars["date"].iloc[280]) <= day <= str(bars["date"].iloc[299]))
    ]
    insert_fx(real_db, "USD", rows)
    real_db.commit()
    inputs = build_universe_inputs(
        real_db,
        None,
        data_mode="REAL",
        signal_name="score",
        signal_timeframe="D",
        start=request().start_date,
        end=request().end_date,
        now=NOW,
    )
    _, labels_markets = _source_calendars(real_db, request(), inputs, lambda _: None)
    missing_dates = labels_markets[asset].bars.index.difference(inputs.markets[asset].bars.index)
    assert len(missing_dates) > 0
    missing = missing_dates[0]
    i = list(bars["date"]).index(missing)
    assert np.isnan(forward_open_returns(labels_markets, inputs.calendar, 1).at[bars["date"].iloc[i - 1], asset])
    ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    before = tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (ids[0],)).fetchone())
    real_db.execute("UPDATE fx_rates SET rate=.8 WHERE from_currency='USD'")
    real_db.commit()
    new_ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    assert tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (ids[0],)).fetchone()) == before
    assert (
        real_db.execute("SELECT fingerprint FROM lab_evidence_reports WHERE id=?", (new_ids[0],)).fetchone()[0]
        != before[-2]
    )


def test_evidence_preserves_r1_is_calendar_after_oos_warmup_revision(lab_connection, monkeypatch):
    monkeypatch.setenv("LAB_WF_IS_SESSIONS", "380")
    monkeypatch.setenv("LAB_WF_OOS_SESSIONS", "80")
    get_settings.cache_clear()
    anchor = synthetic_bars(700, 7)
    young = synthetic_bars(310, 8, start=str(anchor["date"].iloc[150]))
    anchor_id = insert_asset(lab_connection, "ANCHOR")
    young_id = insert_asset(lab_connection, "YOUNG")
    insert_bars(lab_connection, anchor_id, anchor.drop(index=264), real=True, provider="stooq")
    insert_bars(lab_connection, young_id, young, real=True, provider="stooq")
    lab_connection.commit()
    payload = EvidenceIn(
        signal_name="score",
        horizons=[1],
        start_date=str(anchor["date"].iloc[0]),
        end_date=str(anchor["date"].iloc[459]),
        symbols=["ANCHOR", "YOUNG"],
    )
    before_id = run_evidence(lab_connection, payload, job_id=None, now=NOW)[0]
    before = json.loads(
        lab_connection.execute(
            "SELECT walk_forward_json FROM lab_evidence_reports WHERE id=?", (before_id,)
        ).fetchone()[0]
    )
    factor = float(young["close"].iloc[229] / (2 * young["close"].iloc[230]))
    lab_connection.execute(
        "UPDATE price_history SET open=open*?1, high=high*?1, low=low*?1, close=close*?1, adjusted_close=adjusted_close*?1 "
        "WHERE asset_id=?2 AND date=?3",
        (factor, young_id, str(anchor["date"].iloc[380])),
    )
    lab_connection.commit()
    after_id = run_evidence(lab_connection, payload, job_id=None, now=NOW)[0]
    row = lab_connection.execute(
        "SELECT walk_forward_json, universe_json FROM lab_evidence_reports WHERE id=?", (after_id,)
    ).fetchone()
    after = json.loads(row[0])
    assert json.loads(row[1])["excluded"]["YOUNG"] == "NO_FEATURES"
    assert before["windows"][0]["is_end"] == str(anchor["date"].iloc[379])
    assert after["windows"][0] == before["windows"][0]


def test_repeat_evidence_keeps_trial_count_and_frozen_family(real_db, monkeypatch):
    from backend.app.lab.trials import family_trial_sharpes

    _stage_trial_without_expensive_simulation(monkeypatch)
    first = run_evidence(real_db, request(), job_id=None, now=NOW)
    second = run_evidence(real_db, request(), job_id=None, now=NOW)
    assert first != second
    assert len(family_trial_sharpes(real_db, "score|D")) == 1
    before = real_db.execute(
        "SELECT fingerprint, config_json FROM lab_evidence_reports WHERE id=?", (first[0],)
    ).fetchone()
    after = real_db.execute(
        "SELECT fingerprint, config_json FROM lab_evidence_reports WHERE id=?", (second[0],)
    ).fetchone()
    assert tuple(before) == tuple(after)


def test_schema_migration_is_repeatable_and_preserves_reports(real_db):
    from backend.app.database import init_db

    ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    init_db()
    init_db()
    assert real_db.execute("SELECT COUNT(*) FROM lab_evidence_reports").fetchone()[0] == len(ids)


def test_latest_prefers_validato_and_reads_only_persisted_data(real_db, monkeypatch):
    import backend.app.lab.evidence as module

    ids = run_evidence(real_db, request(), job_id=None, now=NOW)
    real_db.execute(
        """INSERT INTO lab_evidence_reports
        (job_id,signal_name,timeframe,horizon,verdict,metrics_json,walk_forward_json,
         config_json,universe_json,limits_json,fingerprint,created_at)
        SELECT job_id,signal_name,timeframe,5,'VALIDATO',metrics_json,walk_forward_json,
               config_json,universe_json,limits_json,fingerprint,created_at
        FROM lab_evidence_reports WHERE id=?""",
        (ids[1],),
    )
    real_db.commit()

    def no_recompute(*args, **kwargs):
        raise AssertionError("I GET non devono rileggere i dati di mercato.")

    monkeypatch.setattr(module, "build_universe_inputs", no_recompute)
    monkeypatch.setenv("LAB_JOBS_EXECUTOR", "inline")
    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    monkeypatch.setenv("ENABLE_ALERTS", "false")
    get_settings.cache_clear()
    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        latest = client.get("/lab/evidence/latest").json()
        assert latest["best"]["horizon"] == 5
        assert latest["best"]["verdict"] == "VALIDATO"
        assert client.get(f"/lab/evidence/{ids[0]}").status_code == 200
        assert len(client.get("/lab/evidence?timeframe=D&limit=1").json()) == 1
        assert client.get("/lab/evidence?timeframe=W").json() == []
        empty = client.get("/lab/evidence/latest?timeframe=M").json()
        assert empty["best"] is None and all(value is None for value in empty["horizons"].values())
        assert client.get("/lab/evidence?limit=101").status_code == 422
        assert client.get("/lab/evidence/latest?signal_name=invalid").status_code == 422


@pytest.mark.parametrize("cancel", [False, True])
def test_evidence_job_errors_and_cancellation_hide_internal_detail(real_db, monkeypatch, cancel):
    import backend.app.lab.handlers as handlers
    from backend.app.lab.jobs import JobCancelled

    def fail(*args, **kwargs):
        if cancel:
            raise JobCancelled()
        raise RuntimeError("internal-detail-to-hide")

    monkeypatch.setattr(handlers, "run_evidence", fail)
    monkeypatch.setenv("LAB_JOBS_EXECUTOR", "inline")
    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    monkeypatch.setenv("ENABLE_ALERTS", "false")
    get_settings.cache_clear()
    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        response = client.post("/lab/evidence", json=request().model_dump())
        assert response.status_code == 202
        job = response.json()
        assert job["status"] == ("CANCELLED" if cancel else "FAILED")
        assert job["result"] is None and job["result_ref"] is None
        assert "internal-detail-to-hide" not in response.text
        if not cancel:
            assert job["error_code"] == "INTERNAL_ERROR"
        assert client.get(f"/lab/jobs/{job['id']}").json()["status"] == job["status"]


def test_request_normalization_is_deterministic():
    payload = EvidenceIn(
        signal_name="score",
        timeframe="D",
        horizons=[21, 1, 1],
        symbols=[" b ", "A", "a"],
        start_date="2018-01-01",
        end_date="2020-01-01",
    )
    assert payload.horizons == [1, 21]
    assert payload.symbols == ["A", "B"]


def test_real_walk_forward_reports_freeze_one_distinct_trial_family(real_db, monkeypatch):
    from backend.app.lab.trials import family_trial_sharpes

    monkeypatch.setenv("LAB_WF_IS_SESSIONS", "300")
    monkeypatch.setenv("LAB_WF_OOS_SESSIONS", "100")
    get_settings.cache_clear()
    first = run_evidence(real_db, request(), job_id=None, now=NOW)
    snapshots = [
        tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (i,)).fetchone()) for i in first
    ]
    family = family_trial_sharpes(real_db, "score|D")
    assert len(family) == 9
    for i in first:
        row = real_db.execute(
            "SELECT walk_forward_json, config_json FROM lab_evidence_reports WHERE id=?", (i,)
        ).fetchone()
        wf, config = json.loads(row[0]), json.loads(row[1])
        assert wf["n_trials"] == 9
        assert sorted(wf["trial_sharpes"]) == sorted(family)
        assert len(config["family_trial_snapshot"]) == 9
        assert wf["oos_sessions"] == 100
        assert "final_value_eur" in wf["oos_metrics"]
    run_evidence(real_db, request(), job_id=None, now=NOW)
    assert len(family_trial_sharpes(real_db, "score|D")) == 9
    for i, old in zip(first, snapshots, strict=True):
        assert tuple(real_db.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (i,)).fetchone()) == old
