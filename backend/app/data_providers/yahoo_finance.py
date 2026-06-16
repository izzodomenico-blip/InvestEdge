from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from backend.app.data_providers.base import BaseMarketDataProvider, ProviderError

# Ticker Yahoo per gli ETF europei/UCITS (Alpha Vantage free copre solo i mercati USA).
# Con Yahoo otteniamo il TITOLO REALE nella SUA valuta: niente piu' proxy USA in dollari.
YAHOO_SYMBOLS = {
    "VWCE": "VWCE.DE",   # Vanguard FTSE All-World, Xetra, EUR
    "AGGH": "AGGH.MI",   # iShares Core Global Aggregate Bond, Borsa Italiana, EUR
    "IB01": "IB01.L",    # iShares $ Treasury Bond 0-1yr, London, USD
}

# Simboli senza un ticker Yahoo quotato pulito (es. indici di rendimento):
# restano dati simulati e vengono segnalati come tali in app.
NO_YAHOO_EQUIVALENT = {"BTP10Y"}

# Yahoo blocca lo User-Agent di default di urllib/httpx: serve un UA da browser.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


class YahooFinanceProvider(BaseMarketDataProvider):
    """Provider prezzi via endpoint pubblico Yahoo Finance (chart v8).

    Vantaggi rispetto ad Alpha Vantage free:
    - copre i ticker europei (VWCE, AGGH, IB01...) nella valuta nativa;
    - restituisce lo storico completo pluriennale (non solo 100 giorni);
    - non richiede API key.
    """

    provider_name = "yahoo_finance"
    endpoint = "chart"
    base_url = "https://query1.finance.yahoo.com/v8/finance/chart"
    # storico completo -> sovrascrive del tutto il seed (vedi MarketDataService)
    full_history = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.daily_limit = self.settings.yahoo_daily_limit
        self.history_range = self.settings.yahoo_history_range

    def api_key_configured(self) -> bool:
        # Yahoo Finance non richiede API key.
        return True

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.lower() in {"stock", "etf", "bond_etf"}

    def yahoo_ticker(self, symbol: str) -> str:
        normalized = symbol.upper()
        if normalized in NO_YAHOO_EQUIVALENT:
            raise ProviderError("Nessun ticker Yahoo per questo simbolo, uso dati locali.")
        return YAHOO_SYMBOLS.get(normalized, normalized)

    def _request_url(self, symbol: str) -> str:
        ticker = self.yahoo_ticker(symbol)
        query = urlencode({"range": self.history_range, "interval": "1d"})
        return f"{self.base_url}/{ticker}?{query}"

    def get_daily_prices(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(self.endpoint, symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_prices(cached, symbol), True

        raw_response = self.fetch_json(request_url, headers=BROWSER_HEADERS)
        chart = raw_response.get("chart") or {}
        if chart.get("error"):
            raise ProviderError("Yahoo non riconosce il simbolo richiesto.")
        self.save_to_cache(self.endpoint, symbol, request_url, raw_response)
        return self.normalize_prices(raw_response, symbol), False

    def normalize_prices(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        chart = raw_response.get("chart") or {}
        results = chart.get("result")
        if not isinstance(results, list) or not results:
            return []
        result = results[0] or {}
        timestamps = result.get("timestamp")
        indicators = result.get("indicators") or {}
        quote_list = indicators.get("quote") or []
        if not isinstance(timestamps, list) or not quote_list:
            return []

        quote = quote_list[0] or {}
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        adj_list = indicators.get("adjclose") or []
        adj = (adj_list[0] or {}).get("adjclose") if adj_list else None

        rows_by_date: dict[str, dict[str, Any]] = {}
        for index, timestamp in enumerate(timestamps):
            close = self._at(closes, index)
            if close is None:
                continue  # giorno senza dato valido (festivo / candela ancora aperta)
            try:
                date_value = datetime.fromtimestamp(float(timestamp), tz=UTC).date().isoformat()
                open_value = float(self._at(opens, index, close))
                high_value = float(self._at(highs, index, close))
                low_value = float(self._at(lows, index, close))
                close_value = float(close)
                adj_value = float(self._at(adj, index, close)) if adj is not None else close_value
                volume_value = float(self._at(volumes, index, 0) or 0)
            except (TypeError, ValueError, OSError):
                continue

            rows_by_date[date_value] = {
                "date": date_value,
                "open": open_value,
                "high": high_value,
                "low": low_value,
                "close": close_value,
                "adjusted_close": adj_value,
                "volume": volume_value,
                "source": "real",
                "provider": self.provider_name,
            }

        return [rows_by_date[key] for key in sorted(rows_by_date)]

    @staticmethod
    def _at(seq: object, index: int, default: Any = None) -> Any:
        if not isinstance(seq, list) or index >= len(seq):
            return default
        value = seq[index]
        return default if value is None else value
