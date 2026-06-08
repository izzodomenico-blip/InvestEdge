from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from backend.app.data_providers.base import BaseMarketDataProvider, ProviderError

# ETF europei non coperti dal piano free Alpha Vantage (solo mercati USA):
# li mappiamo sull'equivalente USA, che traccia lo stesso indice.
# I segnali (trend/RSI/momentum) sono validi; il prezzo assoluto e' quello del proxy USD.
PROXY_SYMBOLS = {
    "VWCE": "VT",     # FTSE All-World -> Vanguard Total World
    "AGGH": "BNDW",   # Global Aggregate Bond -> Vanguard Total World Bond
    "IB01": "SHV",    # US Treasury 0-1y -> iShares Short Treasury 0-1y
}


class AlphaVantageProvider(BaseMarketDataProvider):
    provider_name = "alpha_vantage"
    endpoint = "TIME_SERIES_DAILY"
    base_url = "https://www.alphavantage.co/query"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.daily_limit = self.settings.alpha_vantage_daily_limit

    def api_key_configured(self) -> bool:
        return bool(self.settings.alpha_vantage_api_key)

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.lower() in {"stock", "etf", "bond_etf"}

    def _request_url(self, symbol: str) -> str:
        upstream_symbol = PROXY_SYMBOLS.get(symbol.upper(), symbol.upper())
        query = urlencode(
            {
                "function": self.endpoint,
                "symbol": upstream_symbol,
                # "compact" = ultimi 100 giorni (free). "full" è premium su TIME_SERIES_DAILY.
                "outputsize": "compact",
                "apikey": self.settings.alpha_vantage_api_key or "",
            }
        )
        return f"{self.base_url}?{query}"

    def get_daily_prices(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(self.endpoint, symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_prices(cached, symbol), True

        raw_response = self.fetch_json(request_url)
        if "Error Message" in raw_response:
            raise ProviderError("Alpha Vantage non riconosce il simbolo richiesto.")
        if "Note" in raw_response or "Information" in raw_response:
            raise ProviderError("Alpha Vantage ha risposto con un limite o un avviso provider.")

        self.save_to_cache(self.endpoint, symbol, request_url, raw_response)
        return self.normalize_prices(raw_response, symbol), False

    def normalize_prices(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        series = raw_response.get("Time Series (Daily)")
        if not isinstance(series, dict):
            return []

        prices: list[dict[str, Any]] = []
        for date_value, values in series.items():
            if not isinstance(values, dict):
                continue
            try:
                prices.append(
                    {
                        "date": str(date_value),
                        "open": float(values.get("1. open")),
                        "high": float(values.get("2. high")),
                        "low": float(values.get("3. low")),
                        "close": float(values.get("4. close")),
                        "adjusted_close": float(
                            values.get("5. adjusted close") or values.get("4. close")
                        ),
                        "volume": float(values.get("6. volume") or values.get("5. volume") or 0),
                        "source": "real",
                        "provider": self.provider_name,
                    }
                )
            except (TypeError, ValueError):
                continue
        return sorted(prices, key=lambda item: item["date"])
