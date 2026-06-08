from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from backend.app.data_providers.base import ProviderError
from backend.app.data_providers.news_base import BaseNewsProvider


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_label(value: Any, score: float) -> str:
    label = str(value or "").upper()
    if "BULLISH" in label or label == "POSITIVE":
        return "POSITIVE"
    if "BEARISH" in label or label == "NEGATIVE":
        return "NEGATIVE"
    if score >= 0.15:
        return "POSITIVE"
    if score <= -0.15:
        return "NEGATIVE"
    return "NEUTRAL"


def _published_at(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return raw


class AlphaVantageNewsProvider(BaseNewsProvider):
    provider_name = "alpha_vantage_news"
    endpoint = "NEWS_SENTIMENT"
    base_url = "https://www.alphavantage.co/query"

    def api_key_configured(self) -> bool:
        return bool(self.settings.alpha_vantage_api_key)

    def _request_url(self, symbol: str) -> str:
        query = urlencode(
            {
                "function": self.endpoint,
                "tickers": symbol.upper(),
                "sort": "LATEST",
                "limit": "50",
                "apikey": self.settings.alpha_vantage_api_key or "",
            }
        )
        return f"{self.base_url}?{query}"

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(self.endpoint, symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_news(cached, symbol), True

        raw_response = self.fetch_json(request_url)
        if "Error Message" in raw_response:
            raise ProviderError("Alpha Vantage non riconosce il simbolo richiesto.")
        if "Note" in raw_response or "Information" in raw_response:
            raise ProviderError("Alpha Vantage ha risposto con un limite o un avviso provider.")

        self.save_to_cache(self.endpoint, symbol, request_url, raw_response)
        return self.normalize_news(raw_response, symbol), False

    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        feed = raw_response.get("feed")
        if not isinstance(feed, list):
            return []

        normalized: list[dict[str, Any]] = []
        symbol_upper = symbol.upper()
        for item in feed:
            if not isinstance(item, dict):
                continue

            ticker_sentiment = self._ticker_sentiment(item, symbol_upper)
            sentiment_score = _as_float(
                ticker_sentiment.get("ticker_sentiment_score")
                if ticker_sentiment
                else item.get("overall_sentiment_score"),
                0.0,
            )
            sentiment_label = _normalize_label(
                ticker_sentiment.get("ticker_sentiment_label")
                if ticker_sentiment
                else item.get("overall_sentiment_label"),
                sentiment_score,
            )
            relevance_score = _as_float(ticker_sentiment.get("relevance_score") if ticker_sentiment else 0.5, 0.5)
            if relevance_score <= 1:
                relevance_score *= 100

            title = str(item.get("title") or "").strip()
            if not title:
                continue

            normalized.append(
                {
                    "provider": self.provider_name,
                    "title": title,
                    "summary": str(item.get("summary") or "").strip(),
                    "url": str(item.get("url") or "").strip() or None,
                    "source": str(item.get("source") or "Alpha Vantage").strip(),
                    "published_at": _published_at(item.get("time_published")),
                    "sentiment_score": max(-1.0, min(1.0, sentiment_score)),
                    "sentiment_label": sentiment_label,
                    "relevance_score": max(0.0, min(100.0, relevance_score)),
                    "raw_json": item,
                }
            )
        return normalized

    def _ticker_sentiment(self, item: dict[str, Any], symbol: str) -> dict[str, Any]:
        values = item.get("ticker_sentiment")
        if not isinstance(values, list):
            return {}
        for candidate in values:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("ticker") or "").upper() == symbol:
                return candidate
        return {}
