from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from backend.app.data_providers.news_base import BaseNewsProvider
from backend.app.services.sentiment_engine import classify_sentiment

# Yahoo blocca lo User-Agent di default: serve un UA da browser (come per i prezzi).
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


class YahooNewsProvider(BaseNewsProvider):
    """News via endpoint pubblico Yahoo Finance (search).

    Vantaggi: nessuna API key, nessuna quota giornaliera (a differenza di Finnhub
    free, 20/giorno) -> news sempre fresche. Alimenta la stessa pipeline di
    sentiment che entra nei consigli del motore.

    Nota onesta: per i singoli titoli le news sono pertinenti; per ETF e crypto
    Yahoo restituisce news generiche di mercato (segnale debole, come da qualsiasi
    fonte). Per questo la rilevanza degli ETF/crypto e' tenuta piu' bassa.
    """

    provider_name = "yahoo_news"
    endpoint = "search-news"
    base_url = "https://query1.finance.yahoo.com/v1/finance/search"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # 0 = nessun limite giornaliero (Yahoo non pubblica quote).
        self.daily_limit = self.settings.yahoo_news_daily_limit

    def api_key_configured(self) -> bool:
        # Yahoo Finance non richiede API key.
        return True

    def _request_url(self, symbol: str) -> str:
        query = urlencode(
            {
                "q": symbol.upper(),
                "newsCount": 12,
                "quotesCount": 0,
                "enableFuzzyQuery": "false",
            }
        )
        return f"{self.base_url}?{query}"

    def _asset_type(self, symbol: str) -> str:
        row = self.connection.execute(
            "SELECT asset_type FROM assets WHERE UPPER(symbol) = UPPER(?) LIMIT 1",
            (symbol,),
        ).fetchone()
        return str(row["asset_type"]).lower() if row else "stock"

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(self.endpoint, symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_news(cached, symbol), True

        raw_response = self.fetch_json(request_url, headers=BROWSER_HEADERS)
        self.save_to_cache(self.endpoint, symbol, request_url, raw_response)
        return self.normalize_news(raw_response, symbol), False

    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        items = raw_response.get("news")
        if not isinstance(items, list):
            return []

        # ETF/crypto: news generiche -> rilevanza piu' bassa per non sovrastare il segnale tecnico.
        is_specific = self._asset_type(symbol) == "stock"
        relevance = 72.0 if is_specific else 45.0

        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            summary = str(item.get("summary") or "").strip()
            sentiment = classify_sentiment(f"{title} {summary}")
            normalized.append(
                {
                    "provider": self.provider_name,
                    "title": title,
                    "summary": summary,
                    "url": str(item.get("link") or "").strip() or None,
                    "source": str(item.get("publisher") or "Yahoo Finance").strip(),
                    "published_at": self._published_at(item.get("providerPublishTime")),
                    "sentiment_score": float(sentiment["sentiment_score"]),
                    "sentiment_label": str(sentiment["sentiment_label"]),
                    "relevance_score": relevance,
                    "raw_json": item,
                }
            )
        return normalized

    def _published_at(self, value: Any) -> str | None:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=UTC).replace(tzinfo=None).isoformat(timespec="seconds")
