"""Known corporate-action terms; no fills, live ledger or invented recoveries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from zoneinfo import ZoneInfo

from .calendar import utc_datetime
from .contracts import (
    DataRecord,
    SwingError,
    decimal_value,
    digest,
    identifier,
    integer,
    payload_fields,
    session_day,
    supersedes,
)
from .universe import RawBar


@dataclass(frozen=True)
class CorporateAction:
    record: DataRecord
    action: str
    listing_id: str
    ex_session: str
    ratio: Decimal | None = None
    pay_session: str | None = None
    cash_per_share: Decimal | None = None
    currency: str | None = None
    withholding_rate: Decimal | None = None
    cost_per_share: Decimal | None = None
    new_listing_id: str | None = None
    share_ratio: Decimal | None = None
    old_ticker: str | None = None
    new_ticker: str | None = None

    @classmethod
    def from_record(cls, record: DataRecord) -> CorporateAction:
        data = record.data
        action = data.get("action")
        common = {"action", "listing_id", "ex_session", "source_hash"}
        fields = {
            "SPLIT": {"ratio"},
            "DIVIDEND": {"pay_session", "cash_per_share", "currency", "withholding_rate", "cost_per_share"},
            "RENAME": {"old_ticker", "new_ticker"},
            "DELISTING": {"cash_per_share", "currency", "new_listing_id", "share_ratio"},
            "MERGER": {"cash_per_share", "currency", "new_listing_id", "share_ratio"},
            "SPINOFF": {"cash_per_share", "currency", "new_listing_id", "share_ratio"},
            "HALT": set(),
            "REOPEN": set(),
        }
        if record.kind != "ACTION" or type(action) is not str or action not in fields:
            raise SwingError("INVALID_CONTRACT")
        payload_fields(data, common | fields[action])
        identifier(data["listing_id"])
        digest(data["source_hash"])
        if session_day(data["ex_session"]).isoformat() != record.session:
            raise SwingError("INVALID_CONTRACT")
        values = {name: value for name, value in data.items() if name != "source_hash"}
        for name in ("ratio", "cash_per_share", "share_ratio", "withholding_rate", "cost_per_share"):
            if name in values and values[name] is not None:
                values[name] = decimal_value(values[name], positive=name == "ratio", nonnegative=True)
        if "ratio" in values and values["ratio"] is None:
            raise SwingError("INVALID_CONTRACT")
        if (
            values.get("currency") not in (None, "USD")
            or values.get("withholding_rate") is not None
            and values["withholding_rate"] > 1
        ):
            raise SwingError("INVALID_CONTRACT")
        if values.get("pay_session") is not None and session_day(values["pay_session"]) < session_day(
            values["ex_session"]
        ):
            raise SwingError("INVALID_CONTRACT")
        for name in ("new_listing_id", "old_ticker", "new_ticker"):
            if values.get(name) is not None:
                identifier(values[name])
        if values.get("share_ratio") is not None and values["share_ratio"] > 0 and values["new_listing_id"] is None:
            raise SwingError("INVALID_CONTRACT")
        return cls(record=record, **values)


def _position_number(value):
    if type(value) is not Decimal or not value.is_finite() or value <= 0:
        raise SwingError("INVALID_CONTRACT")


@dataclass(frozen=True)
class AdjustedBar:
    source_hash: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal
    basis: str
    action_hashes: tuple[str, ...]


def _actions_at(actions, cutoff_ns):
    latest = {}
    for action in actions:
        if type(action) is not CorporateAction:
            raise SwingError("INVALID_CONTRACT")
        if action.record.available_ns <= cutoff_ns:
            previous = latest.get(action.record.key)
            if supersedes(action.record, None if previous is None else previous.record):
                latest[action.record.key] = action
    return tuple(sorted(latest.values(), key=lambda a: (a.record.event_ns, a.record.key)))


def split_adjust(bar: RawBar, actions, cutoff_ns: int) -> AdjustedBar:
    integer(cutoff_ns)
    if bar.basis != "RAW" or max(bar.record.event_ns, bar.record.available_ns) > cutoff_ns:
        raise SwingError("INSUFFICIENT_DATA")
    relevant = tuple(
        action
        for action in _actions_at(actions, cutoff_ns)
        if action.action == "SPLIT"
        and action.listing_id == bar.record.key
        and bar.record.session < action.ex_session
        and action.record.event_ns <= cutoff_ns
    )
    with localcontext() as ctx:
        ctx.prec = 384
        ctx.rounding = ROUND_HALF_EVEN
        factor = Decimal(1)
        for action in relevant:
            factor *= action.ratio
        return AdjustedBar(
            bar.record.record_hash,
            *(None if price is None else price / factor for price in (bar.open, bar.high, bar.low, bar.close)),
            bar.volume * factor,
            "SPLIT_ASOF",
            tuple(action.record.record_hash for action in relevant),
        )


def split_position(
    quantity: Decimal, stop: Decimal, action: CorporateAction, cutoff_ns: int
) -> tuple[Decimal, Decimal]:
    _position_number(quantity)
    _position_number(stop)
    integer(cutoff_ns)
    if action.action != "SPLIT" or max(action.record.event_ns, action.record.available_ns) > cutoff_ns:
        raise SwingError("INSUFFICIENT_DATA")
    with localcontext() as ctx:
        ctx.prec = 384
        ctx.rounding = ROUND_HALF_EVEN
        return quantity * action.ratio, stop / action.ratio


@dataclass(frozen=True)
class DividendCredit:
    source_hash: str
    ex_session: str
    pay_session: str | None
    available_ns: int
    gross: Decimal
    quantity: Decimal
    withholding_rate: Decimal | None
    cost_per_share: Decimal | None

    def cash_at(self, day: str, cutoff_ns: int) -> Decimal:
        session_day(day)
        integer(cutoff_ns)
        if session_day(day) > utc_datetime(cutoff_ns).astimezone(ZoneInfo("America/New_York")).date():
            raise SwingError("INSUFFICIENT_DATA")
        if day < self.ex_session:
            return Decimal(0)
        if self.pay_session is None or self.available_ns > cutoff_ns:
            raise SwingError("INSUFFICIENT_DATA")
        if day < self.pay_session:
            return Decimal(0)
        if self.withholding_rate is None or self.cost_per_share is None:
            raise SwingError("INSUFFICIENT_DATA")
        with localcontext() as ctx:
            ctx.prec = 384
            ctx.rounding = ROUND_HALF_EVEN
            return self.gross * (1 - self.withholding_rate) - self.quantity * self.cost_per_share


def dividend_credit(action: CorporateAction, quantity_before_ex: Decimal, *, basis: str) -> DividendCredit:
    _position_number(quantity_before_ex)
    if action.action != "DIVIDEND" or action.cash_per_share is None or action.currency != "USD" or basis != "RAW":
        raise SwingError("INSUFFICIENT_DATA")
    with localcontext() as ctx:
        ctx.prec = 384
        ctx.rounding = ROUND_HALF_EVEN
        return DividendCredit(
            action.record.record_hash,
            action.ex_session,
            action.pay_session,
            action.record.available_ns,
            quantity_before_ex * action.cash_per_share,
            quantity_before_ex,
            action.withholding_rate,
            action.cost_per_share,
        )


@dataclass(frozen=True)
class TerminalResolution:
    state: str
    source_hash: str
    cash_per_share: Decimal | None
    new_listing_id: str | None
    share_ratio: Decimal | None


def terminal_resolution(action: CorporateAction, cutoff_ns: int) -> TerminalResolution:
    integer(cutoff_ns)
    if action.action not in ("DELISTING", "MERGER", "SPINOFF"):
        raise SwingError("INVALID_CONTRACT")
    if (
        max(action.record.available_ns, action.record.event_ns) > cutoff_ns
        or action.cash_per_share is None
        or action.currency != "USD"
        or action.share_ratio is None
    ):
        return TerminalResolution("INSUFFICIENTE", action.record.record_hash, None, None, None)
    return TerminalResolution(
        "RESOLVED", action.record.record_hash, action.cash_per_share, action.new_listing_id, action.share_ratio
    )
