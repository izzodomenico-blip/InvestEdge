from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.app.lab.contracts import DataMode
from backend.app.lab.jobs import JobKind, JobStatus


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
