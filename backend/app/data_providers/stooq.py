from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from datetime import time as midnight
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.config import Settings
from backend.app.data_providers.base import (
    BaseMarketDataProvider,
    ProviderError,
    RateLimitExceeded,
    RealDataDisabled,
)
from backend.app.data_providers.transport import (
    SafeProviderTransport,
    SafeProviderTransportError,
)
from backend.app.models.market_data import MarketObservationEnvelope
from backend.app.services.provider_budget_service import (
    ProviderAvailability,
    ProviderBudgetExceeded,
    ProviderBudgetManager,
    ProviderBudgetPolicy,
)


class StooqProvider(BaseMarketDataProvider):
    provider_name = "stooq"
    capability = "EOD"
    operation = "stooq_daily"
    base_url = "https://stooq.com"
    path = "/q/d/l/"

    def __init__(
        self,
        settings: Settings,
        connection: sqlite3.Connection,
        transport: SafeProviderTransport | None = None,
        budget_manager: ProviderBudgetManager | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(settings, connection, transport, budget_manager)
        self.daily_limit = settings.stooq_daily_limit
        self.policy = ProviderBudgetPolicy(
            settings.stooq_minute_limit,
            settings.stooq_daily_limit,
            settings.stooq_monthly_limit,
            settings.provider_default_max_attempts,
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper
        self.last_fetch_used_cache = False

    def availability(self) -> ProviderAvailability:
        if not self.settings.enable_real_data or not self.settings.enable_stooq:
            return ProviderAvailability("DISABLED", "OPT_IN_DISABLED", None)
        return self.budget_manager.availability(
            self.connection,
            self.policy,
            self.provider_name,
            self._clock(),
        )

    def fetch_observations(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        start: date | None,
        end: date | None,
        bypass_cache: bool = False,
    ) -> list[MarketObservationEnvelope]:
        if not self.settings.enable_real_data or not self.settings.enable_stooq:
            raise RealDataDisabled("stooq:EOD:OPT_IN_DISABLED")

        provider_symbol = str(self._listing_value(listing, "provider_symbol") or "").strip()
        if not provider_symbol:
            raise ProviderError("stooq:EOD:MISSING_PROVIDER_SYMBOL")

        listing_id = self._listing_int(listing, "id")
        params = {"s": provider_symbol, "i": "d"}
        if start is not None:
            params["d1"] = start.strftime("%Y%m%d")
        if end is not None:
            params["d2"] = end.strftime("%Y%m%d")
        now = self._clock()
        try:
            response = self.transport.request(
                connection=self.connection,
                policy=self.policy,
                provider=self.provider_name,
                method="GET",
                base_url=self.base_url,
                path=self.path,
                headers={},
                params=params,
                json_body=None,
                operation=self.capability,
                cache_scope=f"listing:{listing_id}:EOD",
                cache_ttl_seconds=self.settings.stooq_cache_ttl_hours * 3600,
                max_response_bytes=4 * 1024 * 1024,
                decoder="csv",
                now=now,
                sleeper=self._sleeper,
                bypass_cache=bypass_cache,
            )
        except ProviderBudgetExceeded as exc:
            raise RateLimitExceeded(str(exc)) from None
        except SafeProviderTransportError as exc:
            if exc.code == "UNEXPECTED_CONTENT_TYPE":
                raise ProviderError("stooq:EOD:CONTENT_TYPE_REJECTED") from None
            raise ProviderError(str(exc)) from None

        self.last_fetch_used_cache = response.from_cache
        if not isinstance(response.payload, list):
            raise ProviderError("stooq:EOD:INVALID_PAYLOAD")
        if not response.payload:
            return []
        return [self._envelope(listing, row, now) for row in response.payload]

    def get_daily_prices(
        self,
        symbol: str,
        force: bool = False,
    ) -> tuple[list[dict[str, Any]], bool]:
        del symbol, force
        raise ProviderError("stooq:EOD:MISSING_PROVIDER_SYMBOL")

    def normalize_prices(
        self,
        raw_response: dict[str, Any],
        symbol: str,
    ) -> list[dict[str, Any]]:
        del raw_response, symbol
        return []

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.lower() in {"stock", "etf", "bond", "bond_etf", "etc", "etn"}

    def _envelope(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        row: object,
        received_at: datetime,
    ) -> MarketObservationEnvelope:
        listing_id = self._listing_int(listing, "id")
        timezone = str(self._listing_value(listing, "timezone") or "").strip()
        currency = str(self._listing_value(listing, "currency") or "").strip().upper()
        normalized = {
            str(key).strip().lower(): value
            for key, value in row.items()
        } if isinstance(row, Mapping) else {}
        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(normalized):
            return self._malformed_envelope(
                listing_id,
                timezone,
                currency,
                received_at,
                normalized,
            )

        observed_at = self._observed_at(normalized["date"], timezone)
        raw_fields = {
            "open": normalized["open"],
            "high": normalized["high"],
            "low": normalized["low"],
            "close": normalized["close"],
            "adjusted_close": normalized["close"],
            "volume": normalized["volume"],
        }
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability=self.capability,
            operation=self.operation,
            received_at=received_at,
            provider_observed_at=observed_at,
            timezone=timezone,
            session="REGULAR",
            currency=currency,
            source_quality="eod",
            kind="BAR",
            raw_fields=raw_fields,
            raw_payload_sha256=self._payload_hash(normalized),
        )

    def _malformed_envelope(
        self,
        listing_id: int,
        timezone: str,
        currency: str,
        received_at: datetime,
        row: Mapping[str, object],
    ) -> MarketObservationEnvelope:
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability=self.capability,
            operation=self.operation,
            received_at=received_at,
            provider_observed_at=received_at,
            timezone=timezone,
            session="REGULAR",
            currency=currency,
            source_quality="eod",
            kind="BAR",
            raw_fields={"reason_code": "MALFORMED_PAYLOAD"},
            raw_payload_sha256=self._payload_hash(row),
        )

    @staticmethod
    def _observed_at(value: object, timezone: str) -> datetime | None:
        try:
            observed_date = date.fromisoformat(str(value).strip())
            zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            return None
        return datetime.combine(observed_date, midnight.min, tzinfo=zone).astimezone(UTC)

    @staticmethod
    def _payload_hash(payload: Mapping[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _listing_value(
        listing: Mapping[str, object] | sqlite3.Row,
        key: str,
    ) -> object | None:
        try:
            return listing[key]
        except (IndexError, KeyError):
            return None

    @classmethod
    def _listing_int(
        cls,
        listing: Mapping[str, object] | sqlite3.Row,
        key: str,
    ) -> int:
        value = cls._listing_value(listing, key)
        if value is None:
            raise ProviderError(f"stooq:EOD:MISSING_{key.upper()}")
        return int(value)
