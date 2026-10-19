"""Explicit versioned sessions and available FX; no inferred holidays or clock."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from .contracts import (
    DataRecord,
    SwingError,
    canonical_hash,
    decimal_value,
    digest,
    integer,
    payload_fields,
    session_day,
    supersedes,
)

MINUTE_NS = 60_000_000_000
DAY_NS = 86400_000_000_000


def utc_datetime(ns: int) -> datetime:
    integer(ns)
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=ns // 1000)


@dataclass(frozen=True)
class Session:
    day: str
    open_ns: int
    close_ns: int
    available_ns: int

    def __post_init__(self):
        session_day(self.day)
        for value in (self.open_ns, self.close_ns, self.available_ns):
            integer(value)
        if self.open_ns >= self.close_ns or any(
            utc_datetime(ns).astimezone(ZoneInfo("America/New_York")).date().isoformat() != self.day
            for ns in (self.open_ns, self.close_ns)
        ):
            raise SwingError("INVALID_CONTRACT")

    @classmethod
    def from_record(cls, record: DataRecord) -> Session:
        data = record.data
        payload_fields(data, {"open_ns", "close_ns", "source_hash"})
        digest(data["source_hash"])
        if record.kind != "SESSION":
            raise SwingError("INVALID_CONTRACT")
        return cls(record.session, data["open_ns"], data["close_ns"], record.available_ns)


@dataclass(frozen=True)
class DecisionWindow:
    session: str
    information_ns: int
    decision_ns: int
    manual_start_ns: int
    manual_end_ns: int

    def italian_window(self) -> tuple[datetime, datetime]:
        zone = ZoneInfo("Europe/Rome")
        return utc_datetime(self.manual_start_ns).astimezone(zone), utc_datetime(self.manual_end_ns).astimezone(zone)


@dataclass(frozen=True)
class TradingCalendar:
    sessions: tuple[Session, ...]
    settlement_days: tuple[str, ...]
    source_hash: str

    def __post_init__(self):
        digest(self.source_hash)
        if (
            type(self.sessions) is not tuple
            or not self.sessions
            or len(self.sessions) > 10000
            or any(type(s) is not Session for s in self.sessions)
        ):
            raise SwingError("INVALID_CONTRACT")
        if tuple(s.day for s in self.sessions) != tuple(sorted({s.day for s in self.sessions})):
            raise SwingError("INVALID_CONTRACT")
        if any(left.close_ns >= right.open_ns for left, right in zip(self.sessions, self.sessions[1:], strict=False)):
            raise SwingError("INVALID_CONTRACT")
        if type(self.settlement_days) is not tuple or self.settlement_days != tuple(sorted(set(self.settlement_days))):
            raise SwingError("INVALID_CONTRACT")
        for day in self.settlement_days:
            session_day(day)

    @property
    def calendar_hash(self) -> str:
        return canonical_hash({"version": "swing-calendar-v1", **asdict(self)})

    def get(self, day: str, *, asof_ns: int) -> Session:
        session_day(day)
        integer(asof_ns)
        for session in self.sessions:
            if session.day == day and session.available_ns <= asof_ns:
                return session
        raise SwingError("INSUFFICIENT_DATA")

    def previous(self, day: str, count: int, *, asof_ns: int) -> tuple[Session, ...]:
        self.get(day, asof_ns=asof_ns)
        integer(count, positive=True)
        index = next(i for i, s in enumerate(self.sessions) if s.day == day)
        if index < count:
            raise SwingError("INSUFFICIENT_DATA")
        result = self.sessions[index - count : index]
        if any(s.available_ns > asof_ns or s.close_ns > asof_ns for s in result):
            raise SwingError("INSUFFICIENT_DATA")
        return result

    def is_month_start(self, day: str, *, asof_ns: int) -> bool:
        previous = self.previous(day, 1, asof_ns=asof_ns)[0]
        return previous.day[:7] != day[:7]

    def window(self, day: str, *, asof_ns: int) -> DecisionWindow:
        session = self.get(day, asof_ns=asof_ns)
        return DecisionWindow(
            day,
            session.close_ns - 55 * MINUTE_NS,
            session.close_ns - 40 * MINUTE_NS,
            session.close_ns - 45 * MINUTE_NS,
            session.close_ns - 10 * MINUTE_NS,
        )

    def settlement(self, day: str, *, lag: int = 1, asof_ns: int) -> str:
        session_day(day)
        integer(lag)
        integer(asof_ns)
        if max(session.available_ns for session in self.sessions) > asof_ns:
            raise SwingError("INSUFFICIENT_DATA")
        try:
            return self.settlement_days[self.settlement_days.index(day) + lag]
        except (ValueError, IndexError):
            raise SwingError("INSUFFICIENT_DATA") from None


@dataclass(frozen=True)
class FxFix:
    record: DataRecord
    eur_per_usd: Decimal

    @classmethod
    def from_record(cls, record: DataRecord) -> FxFix:
        data = record.data
        payload_fields(data, {"base", "quote", "eur_per_usd", "source_hash"})
        digest(data["source_hash"])
        if record.kind != "FX" or (data["base"], data["quote"]) != ("USD", "EUR"):
            raise SwingError("INVALID_CONTRACT")
        return cls(record, decimal_value(data["eur_per_usd"], positive=True))


def fx_at(records, cutoff_ns: int) -> FxFix:
    integer(cutoff_ns)
    latest = None
    for record in records:
        fix = FxFix.from_record(record)
        if max(record.event_ns, record.available_ns) <= cutoff_ns and (
            latest is None
            or record.event_ns > latest.record.event_ns
            or record.event_ns == latest.record.event_ns
            and supersedes(record, latest.record)
        ):
            latest = fix
    if latest is None or cutoff_ns - latest.record.event_ns > 7 * DAY_NS:
        raise SwingError("INSUFFICIENT_DATA")
    return latest
