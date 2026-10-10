"""Contratti puri intraday: nessun provider, socket, orologio implicito o trading."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import ClassVar

SCHEMA_VERSION = "intraday-v1"
MAX_NS = 2**63 - 1
FEEDS = ("iex", "sip", "delayed_sip")
CAPABILITIES = frozenset(
    ("bars", "updated_bars", "quotes", "news", "status", "luld", "assets", "calendar", "corporate_actions", "events")
)


class ReasonCode(StrEnum):
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    INVALID_JSON = "INVALID_JSON"
    INVALID_ENVELOPE = "INVALID_ENVELOPE"
    MODE_MISMATCH = "MODE_MISMATCH"
    PROFILE_INVALID = "PROFILE_INVALID"
    REAL_DATA_DISABLED = "REAL_DATA_DISABLED"
    FEED_NOT_ENTITLED = "FEED_NOT_ENTITLED"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    CALENDAR_MISSING = "CALENDAR_MISSING"
    CAPTURE_GAP = "CAPTURE_GAP"
    STATUS_BOOTSTRAP_UNAVAILABLE = "STATUS_BOOTSTRAP_UNAVAILABLE"
    SNAPSHOT_NOT_PIT = "SNAPSHOT_NOT_PIT"
    SNAPSHOT_INPUT_MISSING = "SNAPSHOT_INPUT_MISSING"
    COLLECTOR_ALREADY_OWNED = "COLLECTOR_ALREADY_OWNED"


class IntradayError(ValueError):
    """Solo reason code fisso; mai interpolare input o configurazione."""

    def __init__(self, code: ReasonCode):
        self.code = code.value
        super().__init__(self.code)


def _integer(value: object, *, positive: bool = False) -> None:
    if type(value) is not int or not (int(positive) <= value <= MAX_NS):
        raise IntradayError(ReasonCode.INVALID_TIMESTAMP)


def _text(value: object, *, identifier: bool = False) -> None:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise IntradayError(ReasonCode.INVALID_ENVELOPE)
    if identifier and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is None:
        raise IntradayError(ReasonCode.INVALID_ENVELOPE)


def _json_value(value: object) -> None:
    if value is None or type(value) in (bool, str):
        return
    if type(value) is int and math.isfinite(float(value)):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise IntradayError(ReasonCode.INVALID_JSON)
            _json_value(item)
        return
    raise IntradayError(ReasonCode.INVALID_JSON)


def canonical_json(value: object) -> str:
    try:
        if type(value) is not dict:
            raise IntradayError(ReasonCode.INVALID_JSON)
        _json_value(value)
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
        if len(result.encode("utf-8")) > 1_048_576:
            raise IntradayError(ReasonCode.INVALID_JSON)
        return result
    except (ValueError, TypeError, RecursionError, OverflowError, UnicodeError):
        raise IntradayError(ReasonCode.INVALID_JSON) from None


def _json_object(text: str) -> str:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise IntradayError(ReasonCode.INVALID_JSON)
            result[key] = value
        return result

    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > 1_048_576:
            raise IntradayError(ReasonCode.INVALID_JSON)
        return canonical_json(json.loads(text, object_pairs_hook=pairs))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise IntradayError(ReasonCode.INVALID_JSON) from None


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mode(data_mode: str, provenance: str, grade: str) -> None:
    if (
        data_mode not in ("REAL", "DEMO")
        or provenance not in ("CAPTURED", "HISTORICAL_CURRENT", "SYNTHETIC")
        or grade not in ("STRICT_PIT", "RESEARCH_ONLY")
    ):
        raise IntradayError(ReasonCode.MODE_MISMATCH)
    if (data_mode == "DEMO" and provenance != "SYNTHETIC") or (provenance != "CAPTURED" and grade != "RESEARCH_ONLY"):
        raise IntradayError(ReasonCode.MODE_MISMATCH)


@dataclass(frozen=True)
class EventEnvelope:
    provider: str
    feed: str
    profile_id: str
    data_mode: str
    provenance: str
    replay_grade: str
    kind: str
    listing_id: int | None
    logical_key: str
    capture_id: str
    ingest_sequence: int
    event_time_ns: int
    received_at_ns: int
    persisted_at_ns: int
    admitted_at_ns: int | None
    payload_json: str = field(repr=False)
    availability_floor_ns: int = 0
    source_event_id: str | None = None
    source_revision_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        _mode(self.data_mode, self.provenance, self.replay_grade)
        _text(self.provider, identifier=True)
        for text in (self.logical_key, self.capture_id):
            _text(text)
        for text in (self.source_event_id, self.source_revision_id):
            if text is not None:
                _text(text)
        if (
            self.feed not in FEEDS
            or not isinstance(self.profile_id, str)
            or re.fullmatch(r"[a-f0-9]{64}", self.profile_id) is None
        ):
            raise IntradayError(ReasonCode.INVALID_ENVELOPE)
        if self.kind not in ("BAR", "QUOTE", "STATUS", "LULD", "NEWS", "EVENT", "IDENTITY", "CALENDAR", "UNIVERSE"):
            raise IntradayError(ReasonCode.INVALID_ENVELOPE)
        if self.schema_version != SCHEMA_VERSION:
            raise IntradayError(ReasonCode.INVALID_ENVELOPE)
        for value in (self.event_time_ns, self.received_at_ns, self.persisted_at_ns, self.availability_floor_ns):
            _integer(value)
        _integer(self.ingest_sequence, positive=True)
        if self.listing_id is not None:
            _integer(self.listing_id, positive=True)
        if self.kind in ("BAR", "QUOTE", "STATUS", "LULD") and self.listing_id is None:
            raise IntradayError(ReasonCode.INVALID_ENVELOPE)
        if self.persisted_at_ns < self.received_at_ns:
            raise IntradayError(ReasonCode.INVALID_TIMESTAMP)
        if self.admitted_at_ns is not None:
            _integer(self.admitted_at_ns)
            if self.admitted_at_ns < self.persisted_at_ns:
                raise IntradayError(ReasonCode.INVALID_TIMESTAMP)
        object.__setattr__(self, "payload_json", _json_object(self.payload_json))

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json)

    @property
    def payload_hash(self) -> str:
        return _hash(self.payload_json)

    @property
    def available_at_ns(self) -> int | None:
        if self.admitted_at_ns is None:
            return None
        return max(self.received_at_ns, self.persisted_at_ns, self.admitted_at_ns, self.availability_floor_ns)

    def is_available_at(self, cutoff_ns: int) -> bool:
        _integer(cutoff_ns)
        return self.available_at_ns is not None and self.available_at_ns <= cutoff_ns

    def validate_at(self, captured_clock_ns: int, *, max_clock_skew_ns: int = 0) -> None:
        _integer(captured_clock_ns)
        _integer(max_clock_skew_ns)
        values = [self.received_at_ns, self.persisted_at_ns]
        if self.admitted_at_ns is not None:
            values.append(self.admitted_at_ns)
        if self.kind not in ("EVENT", "CALENDAR"):
            values.extend((self.event_time_ns, self.availability_floor_ns))
        if self.kind not in ("EVENT", "CALENDAR") and self.event_time_ns > self.received_at_ns + max_clock_skew_ns:
            raise IntradayError(ReasonCode.INVALID_TIMESTAMP)
        if any(value > captured_clock_ns + max_clock_skew_ns for value in values):
            raise IntradayError(ReasonCode.INVALID_TIMESTAMP)


@dataclass(frozen=True)
class FeedProfile:
    feed: str
    provider: str = "alpaca"
    required_capabilities: tuple[str, ...] = ("bars", "quotes", "news", "status")
    attested_capabilities: tuple[str, ...] = ()
    quote_conditions: tuple[str, ...] = ()
    delay_ns: int | None = None
    max_symbols: int = 0
    max_connections: int = 0
    http_minute_limit: int = 0
    http_daily_limit: int = 0
    http_monthly_limit: int = 0
    max_frame_bytes: int = 0
    max_queue_events: int = 0
    max_archive_bytes: int = 0
    version: str = "intraday-profile-v1"

    def __post_init__(self):
        try:
            _text(self.provider, identifier=True)
            if self.feed not in FEEDS or self.version != "intraday-profile-v1":
                raise ValueError
            expected_delay = 900_000_000_000 if self.feed == "delayed_sip" else 0
            if self.delay_ns is None:
                object.__setattr__(self, "delay_ns", expected_delay)
            elif type(self.delay_ns) is not int or self.delay_ns != expected_delay:
                raise ValueError
            for name in (
                "delay_ns",
                "max_symbols",
                "max_connections",
                "http_minute_limit",
                "http_daily_limit",
                "http_monthly_limit",
                "max_frame_bytes",
                "max_queue_events",
                "max_archive_bytes",
            ):
                _integer(getattr(self, name))
            for values in (self.required_capabilities, self.attested_capabilities, self.quote_conditions):
                if type(values) is not tuple or len(set(values)) != len(values):
                    raise ValueError
                for value in values:
                    _text(value)
            if (
                not self.required_capabilities
                or not set(self.required_capabilities) <= CAPABILITIES
                or not set(self.attested_capabilities) <= CAPABILITIES
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise IntradayError(ReasonCode.PROFILE_INVALID) from None

    @property
    def config_json(self) -> str:
        public = asdict(self)
        for key in ("required_capabilities", "attested_capabilities", "quote_conditions"):
            public[key] = list(public[key])
        return canonical_json(public)

    @property
    def profile_id(self) -> str:
        return _hash(self.config_json)

    @property
    def ready_for_capture(self) -> bool:
        return set(self.required_capabilities) <= set(self.attested_capabilities) and all(
            getattr(self, name) > 0
            for name in (
                "max_symbols",
                "max_connections",
                "http_minute_limit",
                "http_daily_limit",
                "http_monthly_limit",
                "max_frame_bytes",
                "max_queue_events",
                "max_archive_bytes",
            )
        )


@dataclass(frozen=True)
class QualityPolicy:
    """La v1 non ha override. Una revisione richiede nuovo contratto e nuovo digest."""

    version: ClassVar[str] = "intraday-quality-v1"
    min_sessions: int = field(default=20, init=False)
    min_listings: int = field(default=10, init=False)
    raw_coverage_min: float = field(default=0.99, init=False)
    usable_grid_min: float = field(default=0.90, init=False)
    min_usable_points: int = field(default=1, init=False)
    timeframes_minutes: tuple[int, ...] = field(default=(1, 5, 15), init=False)
    decision_delay_ns: int = field(default=10_000_000_000, init=False)
    quote_max_age_ns: int = field(default=2_000_000_000, init=False)
    bar_max_delay_ns: int = field(default=10_000_000_000, init=False)
    required_feed: str = field(default="sip", init=False)
    data_mode: str = field(default="REAL", init=False)
    provenance: str = field(default="CAPTURED", init=False)
    replay_grade: str = field(default="STRICT_PIT", init=False)

    @property
    def config_json(self) -> str:
        public = asdict(self)
        public["version"] = self.version
        public["timeframes_minutes"] = list(self.timeframes_minutes)
        public["grid_scope"] = "EACH_PLANNED_LISTING_SESSION_TIMEFRAME"
        public["excluded_points_in_denominator"] = True
        public["benchmark_included"] = True
        return canonical_json(public)

    @property
    def policy_hash(self) -> str:
        return _hash(self.config_json)
