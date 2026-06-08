from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.app.data_providers.base import ProviderError
from backend.app.data_providers.news_base import BaseNewsProvider
from backend.app.services.sentiment_engine import classify_sentiment

LOOKBACK_DAYS = 21


class FinnhubNewsProvider(BaseNewsProvider):
    provider_name = "finnhub_news"
    endpoint = "company-news"
    base_url = "https://finnhub.io/api/v1/company-news"

    def api_key_configured(self) -> bool:
        return bool(self.settings.finnhub_api_key)

    def _request_url(self, symbol: str) -> str:
        today = datetime.now(UTC).date()
        start = today - timedelta(days=LOOKBACK_DAYS)
        query = urlencode(
            {
                "symbol": symbol.upper(),
                "from": start.isoformat(),
                "to": today.isoformat(),
                "token": self.settings.finnhub_api_key or "",
            }
        )
        return f"{self.base_url}?{query}"

    def _fetch_list(self, request_url: str) -> list[dict[str, Any]]:
        self.ensure_enabled()
        self.check_rate_limit()
        with httpx.Client(timeout=20) as client:
            response = client.get(request_url)
            self.increment_usage()
            response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise ProviderError(str(payload.get("error")))
        if not isinstance(payload, list):
            raise ProviderError("Risposta news Finnhub non valida.")
        return payload

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        request_url = self._request_url(symbol)
        cached = self.get_from_cache(self.endpoint, symbol, request_url, force=force)
        if cached is not None:
            return self.normalize_news(cached, symbol), True

        articles = self._fetch_list(request_url)
        wrapped = {"articles": articles[:50]}
        self.save_to_cache(self.endpoint, symbol, request_url, wrapped)
        return self.normalize_news(wrapped, symbol), False

    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        articles = raw_response.get("articles")
        if not isinstance(articles, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in articles:
            if not isinstance(item, dict):
                continue
            title = str(item.get("headline") or "").strip()
            if not title:
                continue
            summary = str(item.get("summary") or "").strip()
            # Finnhub free non fornisce sentiment: lo stimiamo dal testo (euristica keyword).
            sentiment = classify_sentiment(f"{title} {summary}")
            normalized.append(
                {
                    "provider": self.provider_name,
                    "title": title,
                    "summary": summary,
                    "url": str(item.get("url") or "").strip() or None,
                    "source": str(item.get("source") or "Finnhub").strip(),
                    "published_at": self._published_at(item.get("datetime")),
                    "sentiment_score": float(sentiment["sentiment_score"]),
                    "sentiment_label": str(sentiment["sentiment_label"]),
                    "relevance_score": 75.0,  # news richiesta per ticker -> alta rilevanza
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
