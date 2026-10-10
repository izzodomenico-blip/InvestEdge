"""Route dei job del laboratorio (spec SP1 §10): stato, annullamento, refresh feature e backfill BCE."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.config import get_settings
from backend.app.data_providers.ecb import normalize_ecb_currency
from backend.app.database import db_session
from backend.app.lab import handlers as _handlers  # noqa: F401 - registra gli handler dei job
from backend.app.lab.contracts import LabError, Timeframe
from backend.app.lab.evidence import latest_verdicts, precheck_evidence, report_from_row, summary_from_row
from backend.app.lab.jobs import JobNotCancellable, JobNotFound, JobRecord, JobStatus, get_job_service
from backend.app.models import FeatureRefreshIn, FxBackfillIn, JobOut
from backend.app.models.lab import (
    LAB_SIGNAL_NAMES,
    EvidenceIn,
    EvidenceLatestOut,
    EvidenceReportOut,
    EvidenceSummaryOut,
)

router = APIRouter()


def _job_out(record: JobRecord) -> JobOut:
    return JobOut(**asdict(record))


def _job_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"reason_code": "JOB_NOT_FOUND"})


@router.get("/lab/jobs", response_model=list[JobOut])
def list_lab_jobs(
    limit: int = Query(20, ge=1, le=100),
    job_status: JobStatus | None = Query(None, alias="status"),
) -> list[JobOut]:
    return [_job_out(record) for record in get_job_service().list(limit=limit, status=job_status)]


@router.get("/lab/jobs/{job_id}", response_model=JobOut)
def get_lab_job(job_id: int) -> JobOut:
    record = get_job_service().get(job_id)
    if record is None:
        raise _job_not_found()
    return _job_out(record)


@router.post("/lab/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_lab_job(job_id: int) -> JobOut:
    try:
        return _job_out(get_job_service().cancel(job_id))
    except JobNotFound:
        raise _job_not_found() from None
    except JobNotCancellable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason_code": exc.code, "message": exc.message},
        ) from None


@router.post("/lab/features/refresh", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_lab_features(payload: FeatureRefreshIn | None = None) -> JobOut:
    request = payload or FeatureRefreshIn()
    params = {
        "asset_ids": sorted(set(request.asset_ids)) if request.asset_ids is not None else None,
        "data_mode": request.data_mode,
    }
    return _job_out(get_job_service().enqueue("FEATURE_REFRESH", params))


@router.post("/data/fx/backfill", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def backfill_fx_history(payload: FxBackfillIn) -> JobOut:
    """Backfill storico BCE come job: una chiamata per valuta, solo con `ENABLE_REAL_DATA` attivo."""
    if not get_settings().enable_real_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason_code": "REAL_DATA_DISABLED",
                "message": "Dati reali disattivati: abilita ENABLE_REAL_DATA per il backfill dei cambi BCE.",
            },
        )
    try:
        currencies = list(dict.fromkeys(normalize_ecb_currency(currency) for currency in payload.currencies))
    except ValueError:
        raise HTTPException(status_code=422, detail="Valuta non supportata dai cambi di riferimento BCE.") from None
    start = date.fromisoformat(payload.start_date)
    if start > datetime.now(UTC).date():
        raise HTTPException(status_code=422, detail="La data di inizio non puo essere futura.")
    params = {"currencies": currencies, "start_date": start.isoformat()}
    return _job_out(get_job_service().enqueue("FX_BACKFILL", params))


def _validate_signal(signal_name: str | None) -> None:
    if signal_name is not None and signal_name not in LAB_SIGNAL_NAMES:
        raise HTTPException(status_code=422, detail="Segnale non disponibile nel laboratorio.")


@router.get("/lab/signals", response_model=list[str])
def list_lab_signals() -> list[str]:
    return list(LAB_SIGNAL_NAMES)


@router.post("/lab/evidence", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_lab_evidence(payload: EvidenceIn) -> JobOut:
    with db_session() as connection:
        try:
            precheck_evidence(connection, payload)
        except LabError as exc:
            raise HTTPException(status_code=409, detail={"reason_code": exc.code, "message": exc.message}) from None
    return _job_out(get_job_service().enqueue("EVIDENCE", payload.model_dump()))


@router.get("/lab/evidence", response_model=list[EvidenceSummaryOut])
def list_lab_evidence(
    signal_name: str | None = Query(None, max_length=64), timeframe: Timeframe | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> list[EvidenceSummaryOut]:
    _validate_signal(signal_name)
    with db_session() as connection:
        rows = connection.execute(
            """SELECT * FROM lab_evidence_reports
            WHERE (? IS NULL OR signal_name=?) AND (? IS NULL OR timeframe=?)
            ORDER BY created_at DESC, id DESC LIMIT ?""",
            (signal_name, signal_name, timeframe, timeframe, limit),
        ).fetchall()
    return [summary_from_row(row) for row in rows]


@router.get("/lab/evidence/latest", response_model=EvidenceLatestOut)
def latest_lab_evidence(
    signal_name: str = Query("score", max_length=64), timeframe: Timeframe = "D",
) -> EvidenceLatestOut:
    _validate_signal(signal_name)
    with db_session() as connection:
        horizons = latest_verdicts(connection, signal_name, timeframe)
    reports = [report for report in horizons.values() if report is not None]
    # Stesso verdetto: data piu recente, poi id maggiore.
    priority = {"VALIDATO": 2, "NON_VALIDATO": 1, "INSUFFICIENTE": 0}
    best = max(reports, key=lambda report: (priority[report["verdict"]], report["created_at"], report["id"]),
               default=None)
    return EvidenceLatestOut(signal_name=signal_name, timeframe=timeframe,
                             horizons={str(h): report for h, report in horizons.items()}, best=best)


@router.get("/lab/evidence/{report_id}", response_model=EvidenceReportOut)
def get_lab_evidence(report_id: int) -> EvidenceReportOut:
    with db_session() as connection:
        row = connection.execute("SELECT * FROM lab_evidence_reports WHERE id=?", (report_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"reason_code": "EVIDENCE_NOT_FOUND"})
    return report_from_row(row)
