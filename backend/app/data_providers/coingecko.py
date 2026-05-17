from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from backend.app.data_providers.base import BaseMarketDataProvider, ProviderError


SYMBOL_TO_COIN_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
}


class CoinGeckoProvider(BaseMarketDataProvider):
    provider_name = "coingecko"
    endpoint = "market_chart"
    base_url = "https://api.coingecko.com/api/v3/coins"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.daily_limit = self.settings.coingecko_daily_limit

    def api_key_configured(self) -> bool:
        return bool(self.settings.coingecko_api_key)

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.lower() == "crypto"

    def _request_url(self, symbol: str) -> str:
        coin_id = SYMBOL_TO_COIN_ID.get(symbol.upper())
        if not coin_id:
            raise ProviderError("Crypto non mappata su CoinGecko.")
        query = urlencode({"vs_currency": "usd", "days": "max", "interval": "daily"})
        return f"{self.base_url}/{coin_id}/market_chart?{query}"

    def get_daily_prices(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(self.endpoint, symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_prices(cached, symbol), True

        headers = {"x-cg-demo-api-key": self.settings.coingecko_api_key or ""}
        raw_response = self.fetch_json(request_url, headers=headers)
        self.save_to_cache(self.endpoint, symbol, request_url, raw_response)
        return self.normalize_prices(raw_response, symbol), False

    def normalize_prices(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        prices_series = raw_response.get("prices")
        volumes_series = raw_response.get("total_volumes", [])
        if not isinstance(prices_series, list):
            return []

        volume_by_date: dict[str, float] = {}
        if isinstance(volumes_series, list):
            for item in volumes_series:
                if isinstance(item, list) and len(item) >= 2:
                    volume_by_date[self._date_from_ms(item[0])] = float(item[1] or 0)

        rows_by_date: dict[str, dict[str, Any]] = {}
        for item in prices_series:
            if not isinstance(item, list) or len(item) < 2:
                continue
            try:
                date_value = self._date_from_ms(item[0])
                close = float(item[1])
            except (TypeError, ValueError, OSError):
                continue

            existing = rows_by_date.get(date_value)
            if existing is None:
                rows_by_date[date_value] = {
                    "date": date_value,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adjusted_close": close,
                    "volume": volume_by_date.get(date_value, 0.0),
                    "source": "real",
                    "provider": self.provider_name,
                }
            else:
                existing["high"] = max(float(existing["high"]), close)
                existing["low"] = min(float(existing["low"]), close)
                existing["close"] = close
                existing["adjusted_close"] = close

        return [rows_by_date[key] for key in sorted(rows_by_date)]

    def _date_from_ms(self, timestamp_ms: object) -> str:
        return datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=timezone.utc).date().isoformat()
