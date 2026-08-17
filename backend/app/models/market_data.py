from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from backend.app.services.provider_budget_service import ProviderCapability

ObservationKind = Literal["QUOTE", "BAR"]
SourceObservationQuality = Literal["realtime", "delayed", "eod", "reference"]
EffectiveObservationQuality = Literal[
    "realtime",
    "delayed",
    "eod",
    "reference",
    "stale",
]
ValidationStatus = Literal["VALID", "REJECTED"]
ValidationReason = Literal[
    "MISSING_PRICE",
    "NON_FINITE",
    "NON_POSITIVE",
    "CROSSED_QUOTE",
    "INVALID_OHLC",
    "NEGATIVE_VOLUME",
    "CURRENCY_MISMATCH",
    "INVALID_TIMESTAMP",
    "FUTURE_TIMESTAMP",
    "INVALID_TIMEZONE",
    "INVALID_DELAY",
    "MALFORMED_PAYLOAD",
    "PROVIDER_NO_DATA",
    "MISSING_VALUE",
]

ADAPTER_VALIDATION_REASONS: frozenset[ValidationReason] = frozenset(
    {"PROVIDER_NO_DATA", "MISSING_VALUE"}
)


@dataclass(frozen=True)
class MarketObservationEnvelope:
    listing_id: int
    provider: str
    capability: ProviderCapability
    operation: str
    received_at: datetime
    provider_observed_at: datetime | None
    timezone: str | None
    session: str | None
    currency: str | None
    source_quality: SourceObservationQuality | None
    kind: ObservationKind | None
    raw_fields: Mapping[str, object]
    raw_payload_sha256: str


@dataclass(frozen=True)
class MarketObservation:
    listing_id: int
    provider: str
    capability: ProviderCapability
    operation: str
    provider_observed_at: datetime
    ingested_at: datetime
    timezone: str
    session: str
    currency: str
    delay_seconds: int
    source_quality: SourceObservationQuality
    kind: ObservationKind
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    adjusted_close: Decimal | None = None
    volume: Decimal | None = None


@dataclass(frozen=True)
class ValidatedObservation:
    observation: MarketObservation
    effective_quality: EffectiveObservationQuality
    observation_hash: str


@dataclass(frozen=True)
class ObservationRejection:
    listing_id: int
    provider: str
    capability: ProviderCapability
    operation: str
    received_at: datetime
    reason_code: ValidationReason
    raw_payload_sha256: str


@dataclass(frozen=True)
class IngestResult:
    accepted: int
    rejected: int
    duplicates: int
    revisions: int
    resolved_rejections: int
    projected_price_rows: int


@dataclass(frozen=True)
class MarketDataSelection:
    selected_observation_id: int
    requested_provider: str
    actual_provider: str
    selected_at: datetime
    fallback_reason: str | None
