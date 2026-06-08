from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from backend.app.data_providers.base import BaseMarketDataProvider, ProviderError

SYMBOL_TO_SERIES_ID = {
    "DGS10": "DGS10",
    "DGS2": "DGS2",
    "FEDFUNDS": "FEDFUNDS",
    "BTP10Y": "DGS10",
}


class FredProvider(BaseMarketDataProvider):
    provider_name = "fred"
    endpoint = "series_observations"
    base_url = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.daily_limit = self.settings.fred_daily_limit

    def api_key_configured(self) -> bool:
        return bool(self.settings.fred_api_key)

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.lower() in {"macro", "bond_proxy"}

    def _series_id(self, symbol: str) -> str:
        normalized = symbol.upper()
        if normalized not in SYMBOL_TO_SERIES_ID:
            raise ProviderError("Serie FRED non configurata per questo simbolo.")
        return SYMBOL_TO_SERIES_ID[normalized]

    def _request_url(self, symbol: str) -> str:
        query = urlencode(
            {
                "series_id": self._series_id(symbol),
                "api_key": self.settings.fred_api_key or "",
                "file_type": "json",
                "sort_order": "asc",
            }
        )
        return f"{self.base_url}?{query}"

    def get_daily_prices(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(self.endpoint, symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_prices(cached, symbol), True

        raw_response = self.fetch_json(request_url)
        self.save_to_cache(self.endpoint, symbol, request_url, raw_response)
        return self.normalize_prices(raw_response, symbol), False

    def normalize_prices(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        observations = raw_response.get("observations")
        if not isinstance(observations, list):
            return []

        prices: list[dict[str, Any]] = []
        for item in observations:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if value in (None, "."):
                continue
            try:
                close = float(value)
            except (TypeError, ValueError):
                continue
            prices.append(
                {
                    "date": str(item.get("date")),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adjusted_close": close,
                    "volume": 0.0,
                    "source": "real",
                    "provider": self.provider_name,
                }
            )
        return sorted(prices, key=lambda item: item["date"])
