"""Historical identity intervals and fixed monthly liquidity rules; no strategies."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from .calendar import TradingCalendar
from .contracts import (
    DataContext,
    DataRecord,
    ResourceLimits,
    SwingError,
    canonical_hash,
    decimal_value,
    digest,
    identifier,
    integer,
    payload_fields,
    session_day,
    supersedes,
    working_budget,
)


@dataclass(frozen=True)
class RawBar:
    record: DataRecord
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal
    currency: str
    basis: str
    status: str

    @classmethod
    def from_record(cls, record: DataRecord) -> RawBar:
        data = record.data
        payload_fields(data, {"open", "high", "low", "close", "volume", "currency", "basis", "status"})
        if (
            record.kind not in ("DAILY", "MINUTE")
            or data["currency"] != "USD"
            or data["basis"] not in ("RAW", "SPLIT_ADJUSTED", "TOTAL_RETURN", "UNKNOWN")
            or data["status"] not in ("TRADED", "NO_TRADES", "HALT")
        ):
            raise SwingError("INVALID_CONTRACT")
        volume = decimal_value(data["volume"], nonnegative=True)
        prices = tuple(
            None if data[field] is None else decimal_value(data[field], positive=True)
            for field in ("open", "high", "low", "close")
        )
        if any(price is None for price in prices):
            if not all(price is None for price in prices) or data["status"] == "TRADED" or volume != 0:
                raise SwingError("INVALID_CONTRACT")
        else:
            opening, high, low, close = prices
            if data["status"] != "TRADED" or high < max(opening, close) or low > min(opening, close) or high < low:
                raise SwingError("INVALID_CONTRACT")
        if data["status"] != "TRADED" and volume != 0 or data["status"] == "TRADED" and volume == 0:
            raise SwingError("INVALID_CONTRACT")
        return cls(record, *prices, volume, data["currency"], data["basis"], data["status"])


@dataclass(frozen=True)
class ListingFact:
    record: DataRecord
    issuer_id: str
    class_id: str
    listing_id: str
    ticker: str
    valid_from: str
    valid_to: str | None
    listed_session: str
    delisted_session: str | None
    domicile: str | None
    security_type: str | None
    primary: bool
    venue: str
    currency: str
    source_hash: str

    @classmethod
    def from_record(cls, record: DataRecord) -> ListingFact:
        data = record.data
        expected = {
            "issuer_id",
            "class_id",
            "listing_id",
            "ticker",
            "valid_from",
            "valid_to",
            "listed_session",
            "delisted_session",
            "domicile",
            "security_type",
            "primary",
            "venue",
            "currency",
            "source_hash",
        }
        payload_fields(data, expected)
        if record.kind != "IDENTITY" or data["listing_id"] != record.key or type(data["primary"]) is not bool:
            raise SwingError("INVALID_CONTRACT")
        for name in ("issuer_id", "class_id", "listing_id", "ticker", "venue", "currency"):
            identifier(data[name])
        for name in ("domicile", "security_type"):
            if data[name] is not None:
                identifier(data[name])
        digest(data["source_hash"])
        for name in ("valid_from", "valid_to", "listed_session", "delisted_session"):
            if data[name] is not None:
                session_day(data[name])
        if (
            data["valid_to"] is not None
            and data["valid_to"] <= data["valid_from"]
            or data["delisted_session"] is not None
            and data["delisted_session"] < data["listed_session"]
        ):
            raise SwingError("INVALID_CONTRACT")
        return cls(record, **data)

    def active(self, day: str) -> bool:
        return (
            self.valid_from <= day
            and (self.valid_to is None or day < self.valid_to)
            and self.listed_session <= day
            and (self.delisted_session is None or day < self.delisted_session)
        )


def _facts_at(records, cutoff_ns, resources=ResourceLimits(2**63 - 1)):
    working_budget(resources)
    latest = {}
    retained = 0
    for number, record in enumerate(records):
        if number % 1000 == 0:
            working_budget(resources, retained)
        fact = ListingFact.from_record(record)
        if record.available_ns <= cutoff_ns:
            key = fact.listing_id, fact.valid_from
            previous = latest.get(key)
            if supersedes(record, None if previous is None else previous.record):
                if previous is None:
                    retained += 2048 + 4 * len(record.data_json)
                    if retained > resources.max_rss_bytes:
                        raise SwingError("RESOURCE_LIMIT")
                latest[key] = fact
    chains = {}
    for fact in latest.values():
        pair = fact.issuer_id, fact.class_id
        if fact.listing_id in chains and chains[fact.listing_id] != pair:
            raise SwingError("INSUFFICIENT_DATA")
        chains[fact.listing_id] = pair
    working_budget(resources, retained)
    return tuple(latest.values())


def resolve_ticker(records, ticker: str, day: str, cutoff_ns: int) -> ListingFact:
    identifier(ticker)
    session_day(day)
    integer(cutoff_ns)
    matches = [fact for fact in _facts_at(records, cutoff_ns) if fact.ticker == ticker and fact.active(day)]
    if len(matches) != 1:
        raise SwingError("INSUFFICIENT_DATA")
    return matches[0]


@dataclass(frozen=True)
class UniverseCandidate:
    listing_id: str
    issuer_id: str
    class_id: str
    included: bool
    reason: str
    adv20_usd: Decimal | None
    valid_sessions: int


@dataclass(frozen=True)
class MonthlyUniverse:
    session: str
    cutoff_ns: int
    selected: tuple[str, ...]
    candidates: tuple[UniverseCandidate, ...]
    daily_expected: int
    daily_observed: int
    coverage: Decimal
    state: str
    issues: tuple[str, ...]
    calendar_hash: str
    input_hash: str

    @property
    def universe_hash(self):
        return canonical_hash(asdict(self))


def _classification_reason(fact, on):
    if not fact.active(on):
        return "NOT_ACTIVE_ASOF"
    if fact.domicile is None:
        return "DOMICILE_UNKNOWN"
    if fact.security_type is None:
        return "CLASSIFICATION_UNKNOWN"
    if fact.domicile != "USA":
        return "NON_US_ISSUER"
    if fact.security_type != "COMMON_STOCK":
        return "NOT_COMMON_STOCK"
    if not fact.primary or fact.venue not in ("NYSE", "NASDAQ", "NYSE_AMERICAN") or fact.currency != "USD":
        return "LISTING_NOT_ELIGIBLE"
    return None


def build_monthly_universe(
    identity_records,
    daily_records,
    calendar: TradingCalendar,
    on: str,
    *,
    cutoff_ns: int,
    universe_basis="ASOF",
    context=DataContext("SYNTHETIC", "SYNTHETIC", "SYNTHETIC"),
    resources=ResourceLimits(2**63 - 1),
) -> MonthlyUniverse:
    integer(cutoff_ns)
    working_budget(resources)
    if universe_basis != "ASOF":
        raise SwingError("INSUFFICIENT_DATA")
    if not calendar.is_month_start(on, asof_ns=cutoff_ns):
        raise SwingError("INVALID_CONTRACT")
    previous = calendar.previous(on, 252, asof_ns=cutoff_ns)
    days = {session.day: session for session in previous}
    facts = _facts_at(identity_records, cutoff_ns, resources)
    by_listing = {}
    for fact in facts:
        current = by_listing.get(fact.listing_id)
        if current is None or fact.active(on) and not current.active(on):
            by_listing[fact.listing_id] = fact
        elif fact.active(on) and current.active(on):
            raise SwingError("INSUFFICIENT_DATA")
    prices = {}
    working = sum(2048 + 4 * len(fact.record.data_json) for fact in facts)
    for number, record in enumerate(daily_records):
        if number % 1000 == 0:
            working_budget(resources, working)
        if record.kind != "DAILY":
            raise SwingError("INVALID_CONTRACT")
        if (
            record.key not in by_listing
            or record.session not in days
            or max(record.event_ns, record.available_ns) > cutoff_ns
        ):
            continue
        bar = RawBar.from_record(record)
        key = record.key, record.session
        old = prices.get(key)
        if supersedes(record, None if old is None else old.record):
            if old is None:
                working += 1024 + 4 * len(record.data_json)
                if working > resources.max_rss_bytes:
                    raise SwingError("RESOURCE_LIMIT")
            prices[key] = bar
    working_budget(resources, working)
    candidates = []
    issues = set()
    observed = expected = 0
    input_refs = hashlib.sha256()
    for fact in sorted(by_listing.values(), key=lambda fact: fact.listing_id):
        input_refs.update(bytes.fromhex(fact.record.record_hash))
    with localcontext() as ctx:
        ctx.prec = 384
        ctx.rounding = ROUND_HALF_EVEN
        for listing_id, fact in sorted(by_listing.items()):
            reason = _classification_reason(fact, on)
            required = (
                tuple(s for s in previous if s.day >= fact.listed_session)
                if reason in (None, "DOMICILE_UNKNOWN", "CLASSIFICATION_UNKNOWN")
                else ()
            )
            observed_bars = [prices[(listing_id, s.day)] for s in required if (listing_id, s.day) in prices]
            expected += len(required)
            observed += len(observed_bars)
            for bar in observed_bars:
                input_refs.update(bytes.fromhex(bar.record.record_hash))
            adv = None
            valid = sum(bar.close is not None and bar.basis == "RAW" for bar in observed_bars)
            if reason in ("DOMICILE_UNKNOWN", "CLASSIFICATION_UNKNOWN"):
                issues.add(reason)
            elif reason is None:
                if len(required) < 252:
                    reason = "WARMUP_LT252"
                elif any(bar.basis != "RAW" for bar in observed_bars):
                    reason = "RAW_BASIS_REQUIRED"
                    issues.add(reason)
                elif len(observed_bars) != 252 or valid != 252:
                    reason = "REQUIRED_DAILY_GAP"
                    issues.add(reason)
                elif any(bar.record.event_ns != days[bar.record.session].close_ns for bar in observed_bars):
                    reason = "SESSION_TIME_MISMATCH"
                    issues.add(reason)
                else:
                    adv = sum((bar.close * bar.volume for bar in observed_bars[-20:]), Decimal(0)) / 20
                    if observed_bars[-1].close < 5:
                        reason = "PRICE_BELOW_5"
                    elif adv < 20_000_000:
                        reason = "ADV_BELOW_20M"
            candidates.append(
                UniverseCandidate(listing_id, fact.issuer_id, fact.class_id, False, reason or "ELIGIBLE", adv, valid)
            )
        eligible = sorted(
            (row for row in candidates if row.reason == "ELIGIBLE"), key=lambda row: (-row.adv20_usd, row.listing_id)
        )
        selected = tuple(row.listing_id for row in eligible[:500])
        selected_set = set(selected)
        candidates = tuple(
            UniverseCandidate(
                row.listing_id,
                row.issuer_id,
                row.class_id,
                row.listing_id in selected_set,
                "INCLUDED"
                if row.listing_id in selected_set
                else "OUTSIDE_TOP500"
                if row.reason == "ELIGIBLE"
                else row.reason,
                row.adv20_usd,
                row.valid_sessions,
            )
            for row in candidates
        )
        coverage = Decimal(observed) / expected if expected else Decimal(0)
        if len(eligible) < 100:
            issues.add("FEWER_THAN_100_ELIGIBLE")
        if coverage < Decimal("0.99"):
            issues.add("DAILY_COVERAGE_BELOW_99")
    state = (
        "INSUFFICIENTE"
        if issues
        else "READY_SYNTHETIC"
        if context.data_mode == "SYNTHETIC"
        else "LOCAL_UNIVERSE_CHECKED"
    )
    return MonthlyUniverse(
        on,
        cutoff_ns,
        selected,
        candidates,
        expected,
        observed,
        coverage,
        state,
        tuple(sorted(issues)),
        calendar.calendar_hash,
        input_refs.hexdigest(),
    )
