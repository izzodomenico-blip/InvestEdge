from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from backend.app.lab.contracts import DataMode, Timeframe
from backend.app.lab.features import FEATURE_COLUMNS_V1
from backend.app.lab.jobs import JobKind, JobStatus
from backend.app.lab.score_v1 import SUBSCORE_COLUMNS

LAB_SIGNAL_NAMES = ("score", *SUBSCORE_COLUMNS, *FEATURE_COLUMNS_V1)


class JobOut(BaseModel):
    id: int
    kind: JobKind
    status: JobStatus
    params: dict[str, Any]
    progress: float
    result_ref: str | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    cancel_requested: bool
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class FeatureRefreshIn(BaseModel):
    asset_ids: list[int] | None = Field(default=None, min_length=1, max_length=1000)
    data_mode: DataMode | None = None


class FxBackfillIn(BaseModel):
    currencies: list[str] = Field(..., min_length=1, max_length=10)
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("start_date")
    @classmethod
    def _valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_name: str = Field(min_length=1, max_length=64)
    timeframe: Timeframe = "D"
    horizons: list[StrictInt] = Field(default_factory=lambda: [1, 5, 21], min_length=1, max_length=3)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    symbols: list[str] | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("signal_name")
    @classmethod
    def _signal(cls, value: str) -> str:
        if value not in LAB_SIGNAL_NAMES:
            raise ValueError("Segnale non disponibile nel laboratorio.")
        return value

    @field_validator("horizons")
    @classmethod
    def _horizons(cls, value: list[int]) -> list[int]:
        if any(horizon not in (1, 5, 21) for horizon in value):
            raise ValueError("Orizzonte non disponibile.")
        return sorted(set(value))

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(not symbol.strip() or len(symbol.strip()) > 64 for symbol in value):
            raise ValueError("Simbolo non valido.")
        return sorted({symbol.strip().upper() for symbol in value})

    @field_validator("start_date", "end_date")
    @classmethod
    def _date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def _period(self) -> EvidenceIn:
        if self.end_date < self.start_date:
            raise ValueError("La fine del periodo deve seguire l'inizio.")
        return self


class EvidenceSummaryOut(BaseModel):
    id: int
    job_id: int | None
    signal_name: str
    timeframe: Timeframe
    horizon: Literal[1, 5, 21]
    verdict: Literal["VALIDATO", "NON_VALIDATO", "INSUFFICIENTE"]
    fingerprint: str
    created_at: str


class EvidenceReportOut(EvidenceSummaryOut):
    metrics: dict[str, Any]
    walk_forward: dict[str, Any] | None
    config: dict[str, Any]
    universe: dict[str, Any]
    limits: dict[str, Any]


class EvidenceLatestOut(BaseModel):
    signal_name: str
    timeframe: Timeframe
    horizons: dict[str, EvidenceSummaryOut | None]
    best: EvidenceSummaryOut | None
