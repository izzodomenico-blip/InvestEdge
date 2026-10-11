"""Governed read-only Alpaca REST pages and exact market-row decoding."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import cast

from backend.app.config import Settings
from backend.app.data_providers.base import ProviderError
from backend.app.data_providers.transport import ProviderResponse, SafeProviderTransport, SafeProviderTransportError
from backend.app.intraday.contracts import FeedProfile, IntradayError
from backend.app.intraday.profiles import (
    REST_CAPABILITIES,
    account_budget_policy,
    configuration_reason,
    public_profile,
)
from backend.app.services.provider_budget_service import (
    AvailabilityReason,
    ProviderAvailability,
    ProviderBudgetExceeded,
    ProviderBudgetManager,
)

ALPACA_HOSTS = frozenset({"data.alpaca.markets", "paper-api.alpaca.markets"})
_ROUTES = {
    "bars": ("data.alpaca.markets", "/v2/stocks/bars"),
    "quotes": ("data.alpaca.markets", "/v2/stocks/quotes"),
    "news": ("data.alpaca.markets", "/v1beta1/news"),
    "corporate_actions": ("data.alpaca.markets", "/v1/corporate-actions"),
    "assets": ("paper-api.alpaca.markets", "/v2/assets"),
    "calendar": ("paper-api.alpaca.markets", "/v2/calendar"),
}
_QUERY_KEYS = {
    "bars": {"symbols", "timeframe", "start", "end", "limit", "adjustment", "asof", "feed", "currency", "page_token", "sort"},
    "quotes": {"symbols", "start", "end", "limit", "asof", "feed", "currency", "page_token", "sort"},
    "news": {"symbols", "start", "end", "limit", "sort", "include_content", "exclude_contentless", "page_token"},
    "corporate_actions": {"symbols", "start", "end", "types", "limit", "page_token", "region", "data_quality", "sort"},
    "assets": {"status", "asset_class", "exchange", "attributes"},
    "calendar": {"start", "end", "date_type"},
}
_ROW_FIELDS = {
    "bars": frozenset({"t", "o", "h", "l", "c", "v", "n", "vw"}),
    "quotes": frozenset({"t", "bx", "bp", "bs", "ax", "ap", "as", "c", "z"}),
    "news": frozenset({"id", "headline", "author", "created_at", "updated_at", "url", "symbols", "summary", "source"}),
    "assets": frozenset({"id", "class", "exchange", "symbol", "name", "status", "tradable", "marginable",
                         "maintenance_margin_requirement", "shortable", "fractionable", "attributes", "cusip", "borrow_status",
                         "margin_requirement_long", "margin_requirement_short", "min_order_size",
                         "min_trade_increment", "price_increment"}),
    "calendar": frozenset({"date", "open", "close", "session_open", "session_close", "settlement_date"}),
}
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,31}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_+/=-]{1,2048}$")
_RFC3339 = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$")
_MAX_PAGE_BYTES = 16 * 1024 * 1024
_MAX_MARKET_PERIOD_NS = 7 * 86400 * 1_000_000_000


class AlpacaProviderError(ProviderError):
    def __init__(self, code: str):
        self.code = code
        self.reason_code = code
        super().__init__(f"alpaca:{code}")


def _ns(value: str) -> int:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value += "T00:00:00Z"
    match = _RFC3339.fullmatch(value)
    if match is None:
        raise ValueError
    day, clock, fraction, zone = match.groups()
    parsed = datetime.fromisoformat(f"{day}T{clock}{zone.replace('Z', '+00:00')}").astimezone(UTC)
    elapsed = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000_000 + int((fraction or "").ljust(9, "0"))


def _rows(value: object, fields: frozenset[str]) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError
    result = []
    for row in value:
        selected = {}
        for key, item in row.items():
            if key not in fields:
                continue
            if key == "stock_movements":
                item = _rows(item, frozenset({"symbol", "cusip", "isin", "new_rate", "source_rate"}))
            elif key in {"symbols", "c", "attributes"}:
                # 'c' is a numeric close in bars, a list of condition codes in quotes.
                if isinstance(item, list):
                    if any(not isinstance(element, str) for element in item):
                        raise ValueError
                elif key != "c":
                    raise ValueError
            elif isinstance(item, (dict, list)):
                raise ValueError
            if not isinstance(item, (str, int, float, bool, list, type(None))):
                raise ValueError
            selected[key] = item
        result.append(selected)
    return result


def _payload(capability: str, value: object) -> object:
    # Reject NaN/Infinity even in discarded fields before any persistence.
    json.dumps(value, allow_nan=False)
    if capability in {"assets", "calendar"}:
        return _rows(value, _ROW_FIELDS[capability])
    if not isinstance(value, dict):
        raise ValueError
    if capability in {"bars", "quotes", "news"} and "next_page_token" not in value:
        raise ValueError
    token = value.get("next_page_token")
    if token is not None and (not isinstance(token, str) or not _TOKEN.fullmatch(token)):
        raise ValueError
    key = "corporate_actions" if capability == "corporate_actions" else capability
    source = value[key]
    if capability in {"bars", "quotes"}:
        if not isinstance(source, dict) or len(source) > 30_000:
            raise ValueError
        selected = {}
        for symbol, rows in source.items():
            if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
                raise ValueError
            selected[symbol] = _rows(rows, _ROW_FIELDS[capability])
    elif capability == "news":
        from backend.app.data_providers.alpaca_news import plain_text
        selected = _rows(source, _ROW_FIELDS["news"])
        for row in selected:
            if "headline" in row:
                row["headline"] = plain_text(row["headline"], 8192)
            row.pop("summary", None)  # No summary/body storage right configured on generic REST transport.
    else:
        # Filled from the published corporate-action schema, never raw unbounded objects.
        if not isinstance(source, dict) or not set(source) <= set(_CORPORATE_FIELDS):
            raise ValueError
        selected = {kind: _rows(rows, _CORPORATE_FIELDS[kind])
                    for kind, rows in source.items() if kind in _CORPORATE_FIELDS}
    return {key: selected, "next_page_token": token}


_CORPORATE_ROW_FIELDS = frozenset({
    "id", "symbol", "currency", "cusip", "isin", "process_date", "ex_date", "effective_date",
    "payable_date", "record_date", "old_symbol", "old_cusip", "old_isin", "old_rate",
    "new_symbol", "new_cusip", "new_isin", "new_rate", "source_symbol", "source_cusip",
    "source_isin", "source_rate", "alternate_symbol", "alternate_cusip", "alternate_isin",
    "alternate_rate", "acquiree_symbol", "acquiree_cusip", "acquiree_isin", "acquiree_rate",
    "acquirer_symbol", "acquirer_cusip", "acquirer_isin", "acquirer_rate", "rate", "cash_rate",
    "special", "foreign", "sub_type", "due_bill_on_date", "due_bill_off_date",
    "due_bill_redemption_date", "expiration_date", "lottery_date", "lottery_type",
    "dividend_rate", "price", "results_publication_date", "long_term_rate", "short_term_rate", "stock_movements",
})
_CORPORATE_FIELDS = dict.fromkeys(("capital_gains_distributions", "cash_dividends", "cash_mergers", "forward_splits", "name_changes", "partial_calls", "redemptions", "reorganizations", "reverse_splits", "rights_distributions", "spin_offs", "stock_and_cash_mergers", "stock_dividends", "stock_mergers", "unit_splits", "worthless_removals"), _CORPORATE_ROW_FIELDS)


_CORPORATE_QUERY_TYPES = frozenset(kind[:-1] for kind in _CORPORATE_FIELDS)


class AlpacaMarketProvider:
    provider_name = "alpaca"

    def __init__(
        self, settings: Settings, connection: sqlite3.Connection, profile: FeedProfile, *,
        transport: SafeProviderTransport | None = None,
        budget_manager: ProviderBudgetManager | None = None,
        clock: Callable[[], datetime] | None = None, sleeper: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self.connection = connection
        self.profile = profile
        self.transport = transport or SafeProviderTransport(
            allowed_hosts=ALPACA_HOSTS, settings=settings, budget_manager=budget_manager,
        )
        if budget_manager is not None and self.transport.budget_manager is not budget_manager:
            self.transport = self.transport.with_budget_manager(budget_manager)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sleeper = sleeper
        self._authentication_failed = False
        self._denied_capabilities: set[str] = set()

    def public_profile(self) -> dict[str, object]:
        try:
            return public_profile(self.profile, settings=self.settings)
        except IntradayError:
            raise AlpacaProviderError("PROFILE_INVALID") from None

    def availability(self, capability: str) -> ProviderAvailability:
        reason = configuration_reason(self.settings, self.profile, capability)
        if reason is None and self._authentication_failed:
            reason = "AUTHENTICATION_FAILED"
        if reason is None and capability in self._denied_capabilities:
            reason = "FEED_NOT_ENTITLED"
        if reason is not None:
            return ProviderAvailability("DISABLED", cast(AvailabilityReason, reason), None)
        return self.transport.budget_manager.availability(
            self.connection, account_budget_policy(self.settings, self.profile), "alpaca", self.clock(),
        )

    def request_page(self, capability: str, params: Mapping[str, str], *, bypass_cache: bool = False) -> ProviderResponse:
        reason = configuration_reason(self.settings, self.profile, capability)
        if reason is not None:
            raise AlpacaProviderError(reason)
        if self._authentication_failed:
            raise AlpacaProviderError("AUTHENTICATION_FAILED")
        if capability in self._denied_capabilities:
            raise AlpacaProviderError("FEED_NOT_ENTITLED")
        now = self.clock()
        self._validate_params(capability, params, now)
        host, path = _ROUTES[capability]
        try:
            return self.transport.request(
                connection=self.connection, policy=account_budget_policy(self.settings, self.profile),
                provider="alpaca", method="GET", base_url=f"https://{host}", path=path,
                headers={"APCA-API-KEY-ID": self.settings.alpaca_api_key_id,
                         "APCA-API-SECRET-KEY": self.settings.alpaca_api_secret_key},
                params=params, json_body=None, operation=f"{capability.upper()}:{self.profile.profile_id}",
                cache_scope=f"intraday:{self.profile.profile_id}:{capability}",
                cache_ttl_seconds=60,
                max_response_bytes=min(_MAX_PAGE_BYTES, self.profile.max_frame_bytes, self.settings.alpaca_max_frame_bytes),
                decoder="json", now=now, sleeper=self.sleeper, bypass_cache=bypass_cache,
                payload_filter=lambda value: _payload(capability, value), request_clock=self.clock,
            )
        except ProviderBudgetExceeded as exc:
            raise AlpacaProviderError(exc.reason_code) from None
        except SafeProviderTransportError as exc:
            code = exc.code
            if code == "HTTP_401":
                self._authentication_failed = True
                code = "AUTHENTICATION_FAILED"
            elif code == "HTTP_403":
                self._denied_capabilities.add(capability)
                code = "FEED_NOT_ENTITLED"
            raise AlpacaProviderError(code) from None

    def get_bars_page(
        self, *, symbols: tuple[str, ...], start: str, end: str, asof: str,
        limit: int = 1000, page_token: str | None = None, bypass_cache: bool = False,
    ) -> ProviderResponse:
        return self._market_page("bars", symbols, start, end, asof, limit, page_token, bypass_cache)

    def get_quotes_page(
        self, *, symbols: tuple[str, ...], start: str, end: str, asof: str,
        limit: int = 1000, page_token: str | None = None, bypass_cache: bool = False,
    ) -> ProviderResponse:
        return self._market_page("quotes", symbols, start, end, asof, limit, page_token, bypass_cache)

    def _market_page(self, capability, symbols, start, end, asof, limit, token, bypass_cache):
        if type(symbols) is not tuple or not symbols or type(limit) is not int:
            raise AlpacaProviderError("INVALID_REQUEST")
        if any(not isinstance(symbol, str) for symbol in symbols):
            raise AlpacaProviderError("INVALID_REQUEST")
        params = {"symbols": ",".join(symbols), "start": start, "end": end, "asof": asof,
                  "limit": str(limit), "feed": "sip" if self.profile.feed == "delayed_sip" else self.profile.feed,
                  "currency": "USD", "sort": "asc"}
        if capability == "bars":
            params.update(timeframe="1Min", adjustment="raw")
        if token is not None:
            params["page_token"] = token
        return self.request_page(capability, params, bypass_cache=bypass_cache)

    def _validate_params(self, capability: str, params: Mapping[str, str], now: datetime) -> None:
        try:
            if capability not in REST_CAPABILITIES or not isinstance(params, Mapping):
                raise ValueError
            if not set(params) <= _QUERY_KEYS[capability]:
                raise ValueError
            if any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 2048 or
                   any(ord(c) < 32 for c in k + v) for k, v in params.items()):
                raise ValueError
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError
            if "symbols" in params:
                symbols = params["symbols"].split(",")
                if not symbols or len(symbols) != len(set(symbols)) or any(not _SYMBOL.fullmatch(s) for s in symbols):
                    raise ValueError
                if len(symbols) > min(self.profile.max_symbols, self.settings.alpaca_max_symbols):
                    raise ValueError
            if "page_token" in params and not _TOKEN.fullmatch(params["page_token"]):
                raise ValueError
            if "limit" in params:
                limit = int(params["limit"])
                max_limit = 50 if capability == "news" else 1000 if capability == "corporate_actions" else 10000
                if str(limit) != params["limit"] or not 1 <= limit <= max_limit:
                    raise ValueError
            if capability in {"bars", "quotes", "news", "corporate_actions"}:
                start, end = _ns(params["start"]), _ns(params["end"])
                if not 0 <= end - start <= _MAX_MARKET_PERIOD_NS:
                    raise ValueError
                latest = _ns(now.astimezone(UTC).isoformat().replace("+00:00", "Z"))
                if capability in {"bars", "quotes"} and self.profile.feed == "delayed_sip":
                    latest -= 900 * 1_000_000_000
                if end > latest:
                    raise ValueError
            if capability in {"bars", "quotes"}:
                if not {"symbols", "start", "end", "asof", "limit", "feed", "currency", "sort"} <= set(params):
                    raise ValueError
                wire_feed = "sip" if self.profile.feed == "delayed_sip" else self.profile.feed
                if params["feed"] != wire_feed or params["currency"] != "USD" or params["sort"] != "asc":
                    raise ValueError
                if date.fromisoformat(params["asof"]).isoformat() != params["asof"]:
                    raise ValueError
                if capability == "bars" and (params.get("timeframe") != "1Min" or params.get("adjustment") != "raw"):
                    raise ValueError
            elif capability == "corporate_actions":
                if any(date.fromisoformat(params[k]).isoformat() != params[k] for k in ("start", "end")):
                    raise ValueError
                if params.get("sort") != "asc" or params.get("region") != "us" or params.get("data_quality") != "complete":
                    raise ValueError
                if "limit" not in params or ("types" in params and not set(params["types"].split(",")) <= _CORPORATE_QUERY_TYPES):
                    raise ValueError
            elif capability == "assets":
                if params.get("status") not in {"active", "inactive", "all"} or params.get("asset_class") != "us_equity":
                    raise ValueError
            elif capability == "calendar":
                start, end = date.fromisoformat(params["start"]), date.fromisoformat(params["end"])
                if not timedelta(0) <= end - start <= timedelta(days=366):
                    raise ValueError
                if params.get("date_type", "TRADING") not in {"TRADING", "SETTLEMENT"}:
                    raise ValueError
            elif capability == "news":
                if params.get("sort") != "asc" or params.get("include_content") != "false" or "limit" not in params:
                    raise ValueError
        except (ValueError, TypeError, KeyError, OverflowError):
            raise AlpacaProviderError("INVALID_REQUEST") from None


def format_ns(value: int) -> str:
    """RFC3339 without converting the nanosecond remainder through datetime."""
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise AlpacaProviderError("INVALID_TIMESTAMP")
    seconds, nanos = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"


def decode_market_row(kind, row, *, source):
    """Keep whitelisted source values. REST size units have no attestation here.

    Stream documentation specifies round lots; neither path fabricates shares.
    Invalid economics are archived quarantined; malformed structures fail closed.
    """
    try:
        if kind not in {"BAR", "QUOTE"} or source not in {"REST", "STREAM"} or type(row) is not dict:
            raise ValueError
        fields = _ROW_FIELDS["bars" if kind == "BAR" else "quotes"]
        required = {"t", "o", "h", "l", "c", "v"} if kind == "BAR" else {"t", "bp", "ap", "bs", "as"}
        if not required <= set(row):
            raise ValueError
        selected = _rows([row], fields)[0]
        json.dumps(selected, allow_nan=False)
        at = _ns(selected["t"])
        if not 0 <= at <= 2**63 - 1:
            raise ValueError
        def number(value, positive=False):
            return type(value) in {int, float} and math.isfinite(value) and (value > 0 if positive else value >= 0)
        reason = None
        if kind == "BAR":
            if (at % _MINUTE_NS or not all(number(selected[key], True) for key in ("o", "h", "l", "c")) or
                    not number(selected["v"]) or not selected["l"] <= min(selected["o"], selected["c"]) <=
                    max(selected["o"], selected["c"]) <= selected["h"] or
                    (selected.get("vw") is not None and (not number(selected["vw"], True) or not selected["l"] <= selected["vw"] <= selected["h"])) or
                    (selected.get("n") is not None and (type(selected["n"]) is not int or selected["n"] < 0))):
                reason = "BAR_INVALID"
        else:
            if not all(number(selected[key], True) for key in ("bp", "ap")) or not all(number(selected[key]) for key in ("bs", "as")):
                reason = "QUOTE_INVALID"
            elif selected["bp"] > selected["ap"]:
                reason = "QUOTE_CROSSED"
            elif selected["bs"] == 0 or selected["as"] == 0:
                reason = "QUOTE_ZERO_SIZE"
            if "c" in selected and (type(selected["c"]) is not list or any(type(code) is not str for code in selected["c"])):
                raise ValueError
        return {"version": "alpaca-market-row-v1", "source": source, "currency": "USD", "adjustment": "raw",
                "raw": selected, "reason_code": reason,
                "size_unit": ("ROUND_LOTS" if source == "STREAM" else "SOURCE_UNATTESTED") if kind == "QUOTE" else "SHARES"}
    except (ValueError, TypeError, KeyError, OverflowError):
        raise AlpacaProviderError("MARKET_ROW_INVALID") from None


_MINUTE_NS = 60_000_000_000
