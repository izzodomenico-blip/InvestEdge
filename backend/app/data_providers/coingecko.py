from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from typing import Any

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

_COINGECKO_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CoinGeckoProvider(BaseMarketDataProvider):
    provider_name = "coingecko"
    capability = "EOD"
    eod_operation = "coingecko_market_chart"
    quote_operation = "coingecko_simple_price"
    base_url = "https://api.coingecko.com"
    quote_path = "/api/v3/simple/price"
    supported_quote_currencies = frozenset({"EUR", "USD"})
    attribution = "Powered by CoinGecko API"

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
        if settings.coingecko_api_key:
            minute_limit = min(settings.coingecko_demo_minute_limit, 90)
            monthly_limit = min(settings.coingecko_demo_monthly_limit, 9_000)
        else:
            minute_limit = min(settings.coingecko_keyless_minute_limit, 10)
            monthly_limit = min(settings.coingecko_keyless_monthly_limit, 1_000)
        self.policy = ProviderBudgetPolicy(
            minute_limit,
            None,
            monthly_limit,
            settings.provider_default_max_attempts,
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper
        self.last_fetch_used_cache = False

    def api_key_configured(self) -> bool:
        return True

    def availability(self) -> ProviderAvailability:
        if not self.settings.enable_real_data:
            return ProviderAvailability("DISABLED", "OPT_IN_DISABLED", None)
        return self.budget_manager.availability(
            self.connection,
            self.policy,
            self.provider_name,
            self._clock(),
        )

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.strip().lower() == "crypto"

    def fetch_daily(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        days: int,
        bypass_cache: bool = False,
    ) -> list[MarketObservationEnvelope]:
        if not self.settings.enable_real_data:
            raise RealDataDisabled("coingecko:EOD:OPT_IN_DISABLED")
        if isinstance(days, bool) or not 1 <= days <= 365:
            raise ProviderError("coingecko:EOD:INVALID_DAYS")

        listing_id = self._listing_int(listing, "id", "EOD")
        coingecko_id = self._coingecko_id(listing, "EOD")
        currency = self._currency(listing, "EOD")
        now = self._clock()
        response = self._request(
            listing_id=listing_id,
            capability="EOD",
            path=f"/api/v3/coins/{coingecko_id}/market_chart",
            params={"vs_currency": currency.lower(), "days": str(days)},
            cache_ttl_seconds=self.settings.coingecko_eod_cache_ttl_hours * 3600,
            now=now,
            bypass_cache=bypass_cache,
        )
        return self._market_chart_envelopes(
            listing_id,
            currency,
            now,
            response.payload,
        )

    def fetch_quote(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        now: datetime,
        bypass_cache: bool = False,
    ) -> MarketObservationEnvelope:
        if not self.settings.enable_real_data:
            raise RealDataDisabled("coingecko:QUOTE:OPT_IN_DISABLED")

        listing_id = self._listing_int(listing, "id", "QUOTE")
        coingecko_id = self._coingecko_id(listing, "QUOTE")
        currency = self._currency(listing, "QUOTE")
        response = self._request(
            listing_id=listing_id,
            capability="QUOTE",
            path=self.quote_path,
            params={
                "ids": coingecko_id,
                "vs_currencies": currency.lower(),
                "include_last_updated_at": "true",
            },
            cache_ttl_seconds=self.settings.coingecko_quote_cache_ttl_seconds,
            now=now,
            bypass_cache=bypass_cache,
        )
        return self._quote_envelope(
            listing_id,
            coingecko_id,
            currency,
            now,
            response.payload,
        )

    def get_daily_prices(
        self,
        symbol: str,
        force: bool = False,
    ) -> tuple[list[dict[str, Any]], bool]:
        del symbol, force
        raise ProviderError("coingecko:EOD:MISSING_COINGECKO_ID")

    def normalize_prices(
        self,
        raw_response: dict[str, Any],
        symbol: str,
    ) -> list[dict[str, Any]]:
        del raw_response, symbol
        return []

    def _request(
        self,
        *,
        listing_id: int,
        capability: str,
        path: str,
        params: Mapping[str, str],
        cache_ttl_seconds: int,
        now: datetime,
        bypass_cache: bool,
    ):  # noqa: ANN202
        headers = (
            {"x-cg-demo-api-key": self.settings.coingecko_api_key}
            if self.settings.coingecko_api_key
            else {}
        )
        try:
            response = self.transport.request(
                connection=self.connection,
                policy=self.policy,
                provider=self.provider_name,
                method="GET",
                base_url=self.base_url,
                path=path,
                headers=headers,
                params=params,
                json_body=None,
                operation=capability,
                cache_scope=f"listing:{listing_id}:{capability}",
                cache_ttl_seconds=cache_ttl_seconds,
                max_response_bytes=4 * 1024 * 1024,
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
        return response

    def _market_chart_envelopes(
        self,
        listing_id: int,
        currency: str,
        received_at: datetime,
        payload: object,
    ) -> list[MarketObservationEnvelope]:
        if not isinstance(payload, Mapping):
            return [
                self._rejection_envelope(
                    listing_id,
                    "EOD",
                    self.eod_operation,
                    received_at,
                    "MALFORMED_PAYLOAD",
                    payload,
                )
            ]
        prices = payload.get("prices")
        volumes = payload.get("total_volumes")
        if prices == [] and volumes == []:
            return [
                self._rejection_envelope(
                    listing_id,
                    "EOD",
                    self.eod_operation,
                    received_at,
                    "PROVIDER_NO_DATA",
                    payload,
                )
            ]
        if (
            not isinstance(prices, list)
            or not isinstance(volumes, list)
            or len(prices) != len(volumes)
            or not prices
        ):
            return [
                self._rejection_envelope(
                    listing_id,
                    "EOD",
                    self.eod_operation,
                    received_at,
                    "MALFORMED_PAYLOAD",
                    payload,
                )
            ]

        # Un campione chiude il periodo che termina al suo timestamp: il punto delle
        # 00:00 UTC chiude il giorno precedente (granularita daily CoinGecko). Il
        # giorno UTC in corso e incompleto e non diventa una barra EOD.
        current_day = received_at.astimezone(UTC).date()
        samples_by_day: dict[date, tuple[int, int, object, object]] = {}
        latest_observed_at: datetime | None = None
        for index, (price_item, volume_item) in enumerate(zip(prices, volumes, strict=True)):
            if (
                not isinstance(price_item, list)
                or len(price_item) < 2
                or not isinstance(volume_item, list)
                or len(volume_item) < 2
            ):
                return [
                    self._rejection_envelope(
                        listing_id,
                        "EOD",
                        self.eod_operation,
                        received_at,
                        "MALFORMED_PAYLOAD",
                        payload,
                    )
                ]
            timestamp_ms = self._integer_timestamp(price_item[0])
            volume_timestamp_ms = self._integer_timestamp(volume_item[0])
            observed_at = self._datetime_from_ms(timestamp_ms)
            if (
                timestamp_ms is None
                or volume_timestamp_ms != timestamp_ms
                or observed_at is None
            ):
                return [
                    self._rejection_envelope(
                        listing_id,
                        "EOD",
                        self.eod_operation,
                        received_at,
                        "MALFORMED_PAYLOAD",
                        payload,
                    )
                ]
            if latest_observed_at is None or observed_at > latest_observed_at:
                latest_observed_at = observed_at
            bar_day = (observed_at - timedelta(milliseconds=1)).date()
            if bar_day >= current_day:
                continue
            current = samples_by_day.get(bar_day)
            candidate = (
                timestamp_ms,
                index,
                price_item[1],
                volume_item[1],
            )
            if current is None or candidate[:2] >= current[:2]:
                samples_by_day[bar_day] = candidate

        # Un giorno e completo solo se il payload contiene il campione che lo chiude
        # (00:00 UTC del giorno dopo o successivo): un payload riletto dalla cache il
        # giorno dopo non completa la sessione parziale del download.
        samples_by_day = {
            bar_day: sample
            for bar_day, sample in samples_by_day.items()
            if latest_observed_at is not None
            and datetime.combine(bar_day + timedelta(days=1), day_time.min, tzinfo=UTC) <= latest_observed_at
        }

        if not samples_by_day:
            return [
                self._rejection_envelope(
                    listing_id,
                    "EOD",
                    self.eod_operation,
                    received_at,
                    "PROVIDER_NO_DATA",
                    payload,
                )
            ]

        envelopes: list[MarketObservationEnvelope] = []
        for bar_day in sorted(samples_by_day):
            timestamp_ms, _index, price, volume = samples_by_day[bar_day]
            envelopes.append(
                self._bar_envelope(
                    listing_id,
                    currency,
                    received_at,
                    timestamp_ms,
                    price,
                    volume,
                    datetime.combine(bar_day, day_time.min, tzinfo=UTC),
                )
            )
        return envelopes

    def _bar_envelope(
        self,
        listing_id: int,
        currency: str,
        received_at: datetime,
        timestamp_ms: int,
        price: object,
        volume: object,
        observed_at: datetime,
    ) -> MarketObservationEnvelope:
        selected_sample = {
            "timestamp_ms": timestamp_ms,
            "price": price,
            "volume": volume,
        }
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability="EOD",
            operation=self.eod_operation,
            received_at=received_at,
            provider_observed_at=observed_at,
            timezone="UTC",
            session="24X7",
            currency=currency,
            source_quality="eod",
            kind="BAR",
            raw_fields={
                "close": price,
                "adjusted_close": price,
                "volume": volume,
            },
            raw_payload_sha256=self._payload_hash(selected_sample),
        )

    def _quote_envelope(
        self,
        listing_id: int,
        coingecko_id: str,
        currency: str,
        received_at: datetime,
        payload: object,
    ) -> MarketObservationEnvelope:
        if not isinstance(payload, Mapping) or not payload:
            return self._rejection_envelope(
                listing_id,
                "QUOTE",
                self.quote_operation,
                received_at,
                "PROVIDER_NO_DATA",
                payload,
            )
        quote = payload.get(coingecko_id)
        if not isinstance(quote, Mapping):
            return self._rejection_envelope(
                listing_id,
                "QUOTE",
                self.quote_operation,
                received_at,
                "PROVIDER_NO_DATA",
                payload,
            )
        price_key = currency.lower()
        if price_key not in quote:
            return self._rejection_envelope(
                listing_id,
                "QUOTE",
                self.quote_operation,
                received_at,
                "MISSING_VALUE",
                payload,
            )
        observed_at = self._datetime_from_seconds(
            self._integer_timestamp(quote.get("last_updated_at"))
        )
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability="QUOTE",
            operation=self.quote_operation,
            received_at=received_at,
            provider_observed_at=observed_at,
            timezone="UTC",
            session="24X7",
            currency=currency,
            source_quality="delayed",
            kind="QUOTE",
            raw_fields={"last": quote[price_key]},
            raw_payload_sha256=self._payload_hash(payload),
        )

    def _rejection_envelope(
        self,
        listing_id: int,
        capability: str,
        operation: str,
        received_at: datetime,
        reason_code: str,
        payload: object,
    ) -> MarketObservationEnvelope:
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability=capability,
            operation=operation,
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

    def _coingecko_id(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        capability: str,
    ) -> str:
        value = str(self._listing_value(listing, "coingecko_id") or "").strip().lower()
        if not value:
            raise ProviderError(f"coingecko:{capability}:MISSING_COINGECKO_ID")
        if not _COINGECKO_ID_PATTERN.fullmatch(value):
            raise ProviderError(f"coingecko:{capability}:INVALID_COINGECKO_ID")
        return value

    def _currency(
        self,
        listing: Mapping[str, object] | sqlite3.Row,
        capability: str,
    ) -> str:
        value = str(self._listing_value(listing, "currency") or "").strip().upper()
        if value not in self.supported_quote_currencies:
            raise ProviderError(f"coingecko:{capability}:UNSUPPORTED_CURRENCY")
        return value

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
        capability: str,
    ) -> int:
        value = cls._listing_value(listing, key)
        if value is None:
            raise ProviderError(f"coingecko:{capability}:MISSING_{key.upper()}")
        return int(value)

    @staticmethod
    def _integer_timestamp(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            timestamp = int(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
        return timestamp if timestamp > 0 else None

    @staticmethod
    def _datetime_from_ms(value: int | None) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(value / 1000, UTC)
        except (OSError, OverflowError, ValueError):
            return None

    @staticmethod
    def _datetime_from_seconds(value: int | None) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(value, UTC)
        except (OSError, OverflowError, ValueError):
            return None

    @staticmethod
    def _payload_hash(payload: object) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
