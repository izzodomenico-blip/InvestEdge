"""Bounded public requests; credentials and transport URLs are never accepted."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from backend.app.intraday.contracts import MAX_NS, FeedProfile
from backend.app.models.schemas import AlpacaIdentityApplyIn, AlpacaIdentityPreviewIn

Ns = Annotated[int, Field(strict=True, ge=0, le=MAX_NS)]
Listing = Annotated[int, Field(strict=True, gt=0)]
Digest = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Capability = Literal['bars', 'updated_bars', 'quotes', 'news', 'status', 'luld', 'assets', 'calendar', 'corporate_actions', 'events']


class BoundedIn(BaseModel):
    model_config = {'extra': 'forbid', 'hide_input_in_errors': True}


class ProfileIn(BoundedIn):
    feed: Literal['iex', 'sip', 'delayed_sip']
    provider: Literal['alpaca'] = 'alpaca'
    required_capabilities: list[Capability] = Field(min_length=1, max_length=10)
    attested_capabilities: list[Capability] = Field(min_length=1, max_length=10)
    quote_conditions: list[Annotated[str, Field(pattern=r'^[A-Za-z0-9]{1,8}$')]] = Field(default_factory=list, max_length=100)
    delay_ns: Ns | None = None
    max_symbols: int = Field(strict=True, gt=0, le=10000)
    max_connections: int = Field(strict=True, gt=0, le=100)
    http_minute_limit: int = Field(strict=True, gt=0, le=1000000)
    http_daily_limit: int = Field(strict=True, gt=0, le=100000000)
    http_monthly_limit: int = Field(strict=True, gt=0, le=1000000000)
    max_frame_bytes: int = Field(strict=True, gt=0, le=16777216)
    max_queue_events: int = Field(strict=True, gt=0, le=1000000)
    max_archive_bytes: int = Field(strict=True, gt=0, le=2**63-1)
    version: Literal['intraday-profile-v1'] = 'intraday-profile-v1'

    def profile(self) -> FeedProfile:
        values = self.model_dump()
        for key in ('required_capabilities', 'attested_capabilities', 'quote_conditions'):
            values[key] = tuple(values[key])
        return FeedProfile(**values)


class ProfileRequest(BoundedIn):
    profile_id: Digest


class NamespaceIn(ProfileRequest):
    data_mode: Literal['REAL', 'DEMO'] = 'REAL'
    provenance: Literal['CAPTURED', 'HISTORICAL_CURRENT', 'SYNTHETIC'] = 'CAPTURED'
    replay_grade: Literal['STRICT_PIT', 'RESEARCH_ONLY'] = 'STRICT_PIT'

    @model_validator(mode='after')
    def namespace(self):
        if (self.data_mode == 'DEMO' and self.provenance != 'SYNTHETIC' or
            self.data_mode == 'REAL' and self.provenance == 'SYNTHETIC' or
            self.provenance != 'CAPTURED' and self.replay_grade != 'RESEARCH_ONLY'):
            raise ValueError('MODE_MISMATCH')
        return self


class MetadataRefreshIn(ProfileRequest):
    profile: ProfileIn | None = None
    start_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')

    @model_validator(mode='after')
    def period(self):
        delta = date.fromisoformat(self.end_date) - date.fromisoformat(self.start_date)
        if not 0 <= delta.days <= 366:
            raise ValueError('INVALID_REQUEST')
        return self


class IdentityPreviewIn(AlpacaIdentityPreviewIn):
    profile_id: Digest
    listing_id: Listing


class IdentityApplyIn(AlpacaIdentityApplyIn):
    profile_id: Digest
    listing_id: Listing


class PeriodIn(NamespaceIn):
    listing_ids: list[Listing] = Field(min_length=1, max_length=10000)
    start_at_ns: Ns
    end_at_ns: Ns

    @model_validator(mode='after')
    def period(self):
        if not 0 <= self.end_at_ns - self.start_at_ns <= 366 * 86400 * 10**9:
            raise ValueError('INVALID_REQUEST')
        self.listing_ids = sorted(set(self.listing_ids))
        return self


class BackfillIn(PeriodIn):
    data_mode: Literal['REAL'] = 'REAL'
    provenance: Literal['HISTORICAL_CURRENT'] = 'HISTORICAL_CURRENT'
    replay_grade: Literal['RESEARCH_ONLY'] = 'RESEARCH_ONLY'
    types: list[Literal['BAR', 'QUOTE', 'NEWS', 'CORPORATE_ACTION']] = Field(min_length=1, max_length=4)
    asof_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    max_pages: int = Field(100, strict=True, ge=1, le=1000)
    chunk_days: int = Field(7, strict=True, ge=1, le=7)

    @model_validator(mode='after')
    def types_and_date(self):
        date.fromisoformat(self.asof_date)
        self.types = sorted(set(self.types))
        return self


class SnapshotIn(PeriodIn):
    cutoff_ns: Ns
    policy_id: Literal['intraday-quality-v1'] = 'intraday-quality-v1'
    benchmarks: dict[Literal['market', 'sector'], Listing] = Field(default_factory=dict, max_length=2)

    @model_validator(mode='after')
    def benchmark_scope(self):
        if not self.start_at_ns < self.end_at_ns <= self.cutoff_ns:
            raise ValueError('INVALID_REQUEST')
        if any(item not in self.listing_ids for item in self.benchmarks.values()):
            raise ValueError('INVALID_REQUEST')
        return self


class QualityIn(NamespaceIn):
    snapshot_id: Listing


class CollectorStartIn(ProfileRequest):
    listing_ids: list[Listing] = Field(min_length=1, max_length=10000)
    benchmark_listing_ids: list[Listing] = Field(default_factory=list, max_length=2)

    @model_validator(mode='after')
    def listings(self):
        self.listing_ids = sorted(set(self.listing_ids))
        self.benchmark_listing_ids = sorted(set(self.benchmark_listing_ids))
        return self


class StatusAuthorityIn(BoundedIn):
    source: Literal['UTP_SNAPSHOT']
    contract_version: Literal['4.0']
    contract_sha256: Digest
    evidence_hash: Digest
    retention: Literal['ARCHIVE_ALLOWED']
    channel_bindings: list[tuple[Annotated[int, Field(strict=True, ge=1, le=6)], Annotated[str, Field(pattern=r'^[A-Za-z0-9_.:-]{1,128}$')]]] = Field(min_length=6, max_length=6)
    capture_sha256: Digest


class StatusCheckpointIn(ProfileRequest):
    capture_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')]
    authority: StatusAuthorityIn
    document: dict = Field(max_length=32)
