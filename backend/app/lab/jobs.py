"""Job asincroni del laboratorio (spec SP1 §9).

- Coda nella tabella `lab_jobs`: un solo worker FIFO in un thread (`executor="thread"`) oppure esecuzione
  immediata nella stessa chiamata di `enqueue` (`executor="inline"`, usato nei test).
- Un job con lo stesso `kind` e `params_hash` gia QUEUED o RUNNING viene restituito invece di crearne un altro.
- Ogni operazione usa una propria connessione e transazioni brevi: mai una transazione aperta durante il calcolo.
- Annullamento cooperativo: QUEUED -> CANCELLED subito, RUNNING -> CANCELLED al successivo `raise_if_cancelled`.
- Esito: `LabError` -> FAILED con codice e messaggio del `LabError`; ogni altra eccezione -> FAILED `INTERNAL_ERROR`
  con un messaggio generico (mai il testo dell'eccezione); `JobCancelled` -> CANCELLED.
- All'avvio i job RUNNING rimasti da un'esecuzione precedente diventano INTERRUPTED (`recover_interrupted`).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal, get_args

from backend.app.config import get_settings
from backend.app.database import get_connection
from backend.app.lab.contracts import LabError
from backend.app.services.common import now_utc

JobKind = Literal["BACKTEST", "COMPARE", "WALK_FORWARD", "EVIDENCE", "FEATURE_REFRESH", "FX_BACKFILL", "ML_TRAIN"]
JobStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"]
JobExecutor = Literal["thread", "inline"]
JOB_KINDS: frozenset[str] = frozenset(get_args(JobKind))
INTERNAL_ERROR_CODE = "INTERNAL_ERROR"
INTERNAL_ERROR_MESSAGE = "Errore interno del job."

_COLUMNS = (
    "id, kind, status, params_json, progress, result_ref, result_json, error_code, error_message, "
    "cancel_requested, created_at, started_at, finished_at"
)
_POLL_SECONDS = 1.0
_STOP_TIMEOUT_SECONDS = 10.0


class JobCancelled(Exception):
    """Sollevata da `JobContext.raise_if_cancelled` quando e stato chiesto l'annullamento."""


class JobNotCancellable(LabError):
    def __init__(self) -> None:
        super().__init__("JOB_NOT_CANCELLABLE", "Il job e gia concluso e non puo essere annullato.")


class JobNotFound(LabError):
    def __init__(self) -> None:
        super().__init__("JOB_NOT_FOUND", "Job non trovato.")


@dataclass(frozen=True)
class JobRecord:
    id: int
    kind: JobKind
    status: JobStatus
    params: dict[str, Any]
    progress: float
    result_ref: str | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    cancel_requested: bool
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class JobOutcome:
    result_ref: str | None = None
    result: dict[str, Any] | None = None


class JobContext:
    """Avanzamento e annullamento del job in esecuzione, su una connessione dedicata."""

    def __init__(self, job_id: int, connection: sqlite3.Connection) -> None:
        self.job_id = job_id
        self._connection = connection

    def set_progress(self, value: float) -> None:
        progress = min(1.0, max(0.0, float(value)))
        self._connection.execute("UPDATE lab_jobs SET progress = ? WHERE id = ?", (progress, self.job_id))
        self._connection.commit()

    def raise_if_cancelled(self) -> None:
        row = self._connection.execute("SELECT cancel_requested FROM lab_jobs WHERE id = ?", (self.job_id,)).fetchone()
        if row is not None and row[0]:
            raise JobCancelled()


JobHandler = Callable[[JobContext, Mapping[str, Any]], JobOutcome]
_HANDLERS: dict[str, JobHandler] = {}


def register_job_handler(kind: JobKind, handler: JobHandler) -> None:
    if kind not in JOB_KINDS:
        raise ValueError("Tipo di job non valido.")
    _HANDLERS[kind] = handler


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def _immediate(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    connection.commit()


def _record(row: sqlite3.Row | tuple[Any, ...]) -> JobRecord:
    (
        job_id, kind, status, params_json, progress, result_ref, result_json, error_code, error_message,
        cancel_requested, created_at, started_at, finished_at,
    ) = tuple(row)
    return JobRecord(
        id=int(job_id),
        kind=kind,
        status=status,
        params=json.loads(params_json),
        progress=float(progress),
        result_ref=result_ref,
        result=None if result_json is None else json.loads(result_json),
        error_code=error_code,
        error_message=error_message,
        cancel_requested=bool(cancel_requested),
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
    )


def _select(connection: sqlite3.Connection, job_id: int) -> JobRecord | None:
    row = connection.execute(f"SELECT {_COLUMNS} FROM lab_jobs WHERE id = ?", (job_id,)).fetchone()
    return None if row is None else _record(row)


class JobService:
    def __init__(self, executor: JobExecutor) -> None:
        if executor not in get_args(JobExecutor):
            raise ValueError("Esecutore dei job non valido.")
        self.executor = executor
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def enqueue(self, kind: JobKind, params: Mapping[str, Any]) -> JobRecord:
        """Accoda (o restituisce il job identico ancora aperto); in modalita inline lo esegue subito."""
        if kind not in JOB_KINDS or kind not in _HANDLERS:
            raise LabError("JOB_KIND_UNAVAILABLE", "Tipo di job non disponibile.")
        params_json = json.dumps(dict(params), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        params_hash = hashlib.sha256(params_json.encode("utf-8")).hexdigest()
        with _connection() as connection:
            with _immediate(connection):
                existing = connection.execute(
                    f"""
                    SELECT {_COLUMNS} FROM lab_jobs
                    WHERE kind = ? AND params_hash = ? AND status IN ('QUEUED', 'RUNNING')
                    ORDER BY id
                    LIMIT 1
                    """,
                    (kind, params_hash),
                ).fetchone()
                job_id = None
                if existing is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO lab_jobs (kind, status, params_json, params_hash, created_at)
                        VALUES (?, 'QUEUED', ?, ?, ?)
                        """,
                        (kind, params_json, params_hash, now_utc()),
                    )
                    job_id = int(cursor.lastrowid)
            if job_id is None:
                return _record(existing)
        if self.executor == "inline":
            if self._claim(job_id):
                self._execute(job_id)
        else:
            self._wake.set()
        record = self.get(job_id)
        assert record is not None
        return record

    def get(self, job_id: int) -> JobRecord | None:
        with _connection() as connection:
            return _select(connection, job_id)

    def list(self, *, limit: int = 20, status: JobStatus | None = None) -> list[JobRecord]:
        where = "WHERE status = ?" if status is not None else ""
        params: tuple[Any, ...] = (status, limit) if status is not None else (limit,)
        with _connection() as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM lab_jobs {where} ORDER BY created_at DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [_record(row) for row in rows]

    def cancel(self, job_id: int) -> JobRecord:
        with _connection() as connection:
            with _immediate(connection):
                record = _select(connection, job_id)
                if record is None:
                    raise JobNotFound()
                if record.status == "QUEUED":
                    connection.execute(
                        """
                        UPDATE lab_jobs SET status = 'CANCELLED', cancel_requested = 1, finished_at = ?
                        WHERE id = ?
                        """,
                        (now_utc(), job_id),
                    )
                elif record.status == "RUNNING":
                    connection.execute("UPDATE lab_jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
                else:
                    raise JobNotCancellable()
            cancelled = _select(connection, job_id)
        assert cancelled is not None
        return cancelled

    def recover_interrupted(self) -> int:
        """Job RUNNING rimasti da un'esecuzione precedente -> INTERRUPTED."""
        with _connection() as connection, _immediate(connection):
            cursor = connection.execute(
                "UPDATE lab_jobs SET status = 'INTERRUPTED', finished_at = ? WHERE status = 'RUNNING'",
                (now_utc(),),
            )
        return int(cursor.rowcount)

    def start(self) -> None:
        if self.executor == "inline":
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(target=self._worker, name="investedge-lab-jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is None:
            return
        self._stopping.set()
        self._wake.set()
        thread.join(timeout=_STOP_TIMEOUT_SECONDS)

    def _worker(self) -> None:
        while not self._stopping.is_set():
            try:
                job_id = self._claim_next()
                if job_id is not None:
                    self._execute(job_id)
                    continue
            except Exception:  # il worker resta vivo; un job rimasto RUNNING diventa INTERRUPTED al riavvio
                pass
            self._wake.wait(_POLL_SECONDS)
            self._wake.clear()

    def _claim_next(self) -> int | None:
        with _connection() as connection, _immediate(connection):
            row = connection.execute(
                "SELECT id FROM lab_jobs WHERE status = 'QUEUED' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if row is not None:
                connection.execute(
                    "UPDATE lab_jobs SET status = 'RUNNING', started_at = ? WHERE id = ?",
                    (now_utc(), row[0]),
                )
        return None if row is None else int(row[0])

    def _claim(self, job_id: int) -> bool:
        with _connection() as connection, _immediate(connection):
            cursor = connection.execute(
                "UPDATE lab_jobs SET status = 'RUNNING', started_at = ? WHERE id = ? AND status = 'QUEUED'",
                (now_utc(), job_id),
            )
        return cursor.rowcount == 1

    def _execute(self, job_id: int) -> None:
        with _connection() as connection:
            record = _select(connection, job_id)
            if record is None:
                return
            status: JobStatus = "SUCCEEDED"
            result_ref = result_json = error_code = error_message = None
            try:
                handler = _HANDLERS.get(record.kind)
                if handler is None:
                    raise LabError("JOB_KIND_UNAVAILABLE", "Tipo di job non disponibile.")
                outcome = handler(JobContext(job_id, connection), record.params)
                result_ref = outcome.result_ref
                if outcome.result is not None:
                    result_json = json.dumps(outcome.result, separators=(",", ":"), allow_nan=False)
            except JobCancelled:
                status = "CANCELLED"
            except LabError as exc:
                status, error_code, error_message = "FAILED", exc.code, exc.message
            except Exception:  # il testo dell'eccezione non esce mai dal job
                status, error_code, error_message = "FAILED", INTERNAL_ERROR_CODE, INTERNAL_ERROR_MESSAGE
            if status != "SUCCEEDED":
                result_ref = result_json = None
            if connection.in_transaction:
                connection.rollback()
            connection.execute(
                """
                UPDATE lab_jobs
                SET status = ?, progress = CASE WHEN ? = 'SUCCEEDED' THEN 1 ELSE progress END,
                    result_ref = ?, result_json = ?, error_code = ?, error_message = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, status, result_ref, result_json, error_code, error_message, now_utc(), job_id),
            )
            connection.commit()


_service: JobService | None = None
_service_lock = threading.Lock()


def get_job_service() -> JobService:
    """Servizio condiviso con l'esecutore configurato (`LAB_JOBS_EXECUTOR`)."""
    global _service
    executor = get_settings().lab_jobs_executor
    with _service_lock:
        if _service is None or _service.executor != executor:
            if _service is not None:
                _service.stop()
            _service = JobService(executor)
        return _service
