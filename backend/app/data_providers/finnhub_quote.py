from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from backend.app.config import Settings
from backend.app.data_providers.base import (
    BaseMarketDataProvider,
    MissingApiKey,
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


class FinnhubQuoteProvider(BaseMarketDataProvider):
    provider_name = "finnhub"
    capability = "QUOTE"
    operation = "finnhub_quote"
    base_url = "https://finnhub.io"
    path = "/api/v1/quote"
    supported_mics = frozenset({"XNYS", "XNAS", "XASE", "ARCX", "BATS"})

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
        self.daily_limit = 0
        self.policy = ProviderBudgetPolicy(
            min(settings.finnhub_quote_minute_limit, 55),
            None,
            None,
            settings.provider_default_max_attempts,
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper
        self.last_fetch_used_cache = False

    def api_key_configured(self) -> bool:
        return bool(self.settings.finnhub_api_key)

    def availability(self) -> ProviderAvailability:
        if not self.settings.enable_real_data:
            return ProviderAvailability("DISABLED", "OPT_IN_DISABLED", None)
        if not self.api_key_configured():
            return ProviderAvailability("DISABLED", "MISSING_CREDENTIAL", None)
        return self.budget_manager.availability(
            self.connection,
            self.policy,
            self.provider_name,
            self._clock(),
        )

    def fetch_quote(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        now: datetime,
        bypass_cache: bool = False,
    ) -> MarketObservationEnvelope:
        if not self.settings.enable_real_data:
            raise RealDataDisabled("finnhub:QUOTE:OPT_IN_DISABLED")
        if not self.api_key_configured():
            raise MissingApiKey("finnhub:QUOTE:MISSING_CREDENTIAL")

        mic = str(self._listing_value(listing, "mic") or "").strip().upper()
        if mic not in self.supported_mics:
            raise ProviderError("finnhub:QUOTE:UNSUPPORTED_MIC")
        provider_symbol = str(
            self._listing_value(listing, "provider_symbol") or ""
        ).strip()
        if not provider_symbol:
            raise ProviderError("finnhub:QUOTE:MISSING_PROVIDER_SYMBOL")

        listing_id = self._listing_int(listing, "id")
        try:
            response = self.transport.request(
                connection=self.connection,
                policy=self.policy,
                provider=self.provider_name,
                method="GET",
                base_url=self.base_url,
                path=self.path,
                headers={"X-Finnhub-Token": self.settings.finnhub_api_key or ""},
                params={"symbol": provider_symbol},
                json_body=None,
                operation=self.capability,
                cache_scope=f"listing:{listing_id}:QUOTE",
                cache_ttl_seconds=self.settings.finnhub_quote_cache_ttl_seconds,
                max_response_bytes=64 * 1024,
                decoder="json",
                now=now,
                sleeper=self._sleeper,
                bypass_cache=bypass_cache,
            )
        except ProviderBudgetExceeded as exc:
            raise RateLimitExceeded(str(exc)) from None
        except SafeProviderTransportError as exc:
            raise ProviderError(str(exc)) from None

        self.last_fetch_used_cache = response.from_cache
        if not isinstance(response.payload, Mapping):
            return self._rejection_envelope(
                listing_id,
                now,
                "MALFORMED_PAYLOAD",
                response.payload,
            )
        payload = dict(response.payload)
        if self._is_no_data(payload):
            return self._rejection_envelope(
                listing_id,
                now,
                "PROVIDER_NO_DATA",
                payload,
            )
        return self._quote_envelope(listing, listing_id, payload, now)

    def get_daily_prices(
        self,
        symbol: str,
        force: bool = False,
    ) -> tuple[list[dict[str, Any]], bool]:
        del symbol, force
        raise ProviderError("finnhub:QUOTE:MISSING_LISTING")

    def normalize_prices(
        self,
        raw_response: dict[str, Any],
        symbol: str,
    ) -> list[dict[str, Any]]:
        del raw_response, symbol
        return []

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.lower() in {"stock", "etf"}

    def _quote_envelope(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        listing_id: int,
        payload: Mapping[str, object],
        received_at: datetime,
    ) -> MarketObservationEnvelope:
        observed_at = self._observed_at(payload.get("t"))
        raw_fields = {
            "last": payload.get("c"),
            "quote_high": payload.get("h"),
            "quote_low": payload.get("l"),
            "quote_open": payload.get("o"),
            "previous_close": payload.get("pc"),
        }
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability=self.capability,
            operation=self.operation,
            received_at=received_at,
            provider_observed_at=observed_at,
            timezone=str(self._listing_value(listing, "timezone") or "").strip(),
            session=str(self._listing_value(listing, "session") or "REGULAR")
            .strip()
            .upper(),
            currency=str(self._listing_value(listing, "currency") or "")
            .strip()
            .upper(),
            source_quality="delayed",
            kind="QUOTE",
            raw_fields=raw_fields,
            raw_payload_sha256=self._payload_hash(payload),
        )

    def _rejection_envelope(
        self,
        listing_id: int,
        received_at: datetime,
        reason_code: str,
        payload: object,
    ) -> MarketObservationEnvelope:
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability=self.capability,
            operation=self.operation,
            received_at=received_at,
            provider_observed_at=None,
            timezone=None,
            session=None,
            currency=None,
            source_quality=None,
            kind=None,
            raw_fields={"reason_code": reason_code},
            raw_payload_sha256=self._payload_hash(payload),
        )

    @staticmethod
    def _observed_at(value: object) -> datetime | None:
        if isinstance(value, bool):
            return None
        try:
            timestamp = int(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
        if timestamp <= 0:
            return None
        try:
            return datetime.fromtimestamp(timestamp, UTC)
        except (OSError, OverflowError, ValueError):
            return None

    @staticmethod
    def _is_no_data(payload: Mapping[str, object]) -> bool:
        required = ("c", "h", "l", "o", "pc", "t")
        try:
            return all(float(payload.get(field)) == 0 for field in required)
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _payload_hash(payload: object) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
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
            raise ProviderError(f"finnhub:QUOTE:MISSING_{key.upper()}")
        return int(value)
