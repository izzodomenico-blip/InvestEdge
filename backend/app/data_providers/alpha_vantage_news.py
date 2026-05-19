from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from backend.app.data_providers.news_base import BaseNewsProvider, NewsProviderError


SENTIMENT_LABEL_MAP = {
    "bearish": "NEGATIVE",
    "somewhat-bearish": "NEGATIVE",
    "neutral": "NEUTRAL",
    "somewhat-bullish": "POSITIVE",
    "bullish": "POSITIVE",
}


class AlphaVantageNewsProvider(BaseNewsProvider):
    provider_name = "alpha_vantage_news"
    endpoint = "NEWS_SENTIMENT"
    base_url = "https://www.alphavantage.co/query"

    def api_key_configured(self) -> bool:
        return bool(self.settings.alpha_vantage_api_key)

    def supports_symbol(self, symbol: str) -> bool:
        return bool(symbol) and symbol.isascii()

    def _request_url(self, symbol: str) -> str:
        query = urlencode(
            {
                "function": self.endpoint,
                "tickers": symbol.upper(),
                "limit": "50",
                "apikey": self.settings.alpha_vantage_api_key or "",
            }
        )
        return f"{self.base_url}?{query}"

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_news(cached, symbol), True

        raw_response = self.fetch_json(request_url)
        if isinstance(raw_response, dict):
            if "Error Message" in raw_response:
                raise NewsProviderError("Alpha Vantage News non riconosce il simbolo richiesto.")
            if "Note" in raw_response or "Information" in raw_response:
                raise NewsProviderError("Alpha Vantage News ha risposto con un limite o un avviso provider.")

        self.save_to_cache(symbol, request_url, raw_response)
        return self.normalize_news(raw_response, symbol), False

    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        feed = raw_response.get("feed") if isinstance(raw_response, dict) else None
        if not isinstance(feed, list):
            return []

        symbol_upper = symbol.upper()
        normalized: list[dict[str, Any]] = []
        for entry in feed:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            url = str(entry.get("url") or "").strip() or None
            source = str(entry.get("source") or "").strip() or None
            summary = str(entry.get("summary") or "").strip()
            published_at = self._parse_time(entry.get("time_published"))
            ticker_sentiments = entry.get("ticker_sentiment")
            sentiment_score, relevance_score, label_hint = self._symbol_sentiment(ticker_sentiments, symbol_upper)
            if sentiment_score is None:
                try:
                    sentiment_score = float(entry.get("overall_sentiment_score") or 0.0)
                except (TypeError, ValueError):
                    sentiment_score = 0.0
            if label_hint is None:
                label_hint = SENTIMENT_LABEL_MAP.get(str(entry.get("overall_sentiment_label") or "").lower())

            normalized.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "source": source,
                    "published_at": published_at,
                    "sentiment_score": float(sentiment_score) if sentiment_score is not None else 0.0,
                    "sentiment_label_hint": label_hint,
                    "relevance_score": relevance_score,
                    "raw": entry,
                }
            )
        return normalized

    @staticmethod
    def _symbol_sentiment(
        ticker_sentiments: Any, symbol_upper: str
    ) -> tuple[float | None, float | None, str | None]:
        if not isinstance(ticker_sentiments, list):
            return None, None, None
        for item in ticker_sentiments:
            if not isinstance(item, dict):
                continue
            if str(item.get("ticker") or "").upper() != symbol_upper:
                continue
            try:
                score = float(item.get("ticker_sentiment_score"))
            except (TypeError, ValueError):
                score = None
            try:
                relevance = float(item.get("relevance_score"))
            except (TypeError, ValueError):
                relevance = None
            if relevance is not None:
                relevance = max(0.0, min(100.0, relevance * 100.0))
            label = SENTIMENT_LABEL_MAP.get(str(item.get("ticker_sentiment_label") or "").lower())
            return score, relevance, label
        return None, None, None

    @staticmethod
    def _parse_time(value: Any) -> str | None:
        if not value:
            return None
        text = str(value).strip()
        if len(text) >= 14 and text[:8].isdigit() and text[9:15].isdigit():
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]} {text[9:11]}:{text[11:13]}:{text[13:15]}"
        return text
