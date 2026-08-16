from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.data_providers.base import ProviderError, RateLimitExceeded
from backend.app.data_providers.news_base import BaseNewsProvider
from backend.app.data_providers.transport import SafeProviderTransportError
from backend.app.services.provider_budget_service import ProviderBudgetExceeded
from backend.app.services.sentiment_engine import classify_sentiment

LOOKBACK_DAYS = 21


class FinnhubNewsProvider(BaseNewsProvider):
    provider_name = "finnhub_news"
    endpoint = "company-news"
    base_url = "https://finnhub.io"
    path = "/api/v1/company-news"

    def api_key_configured(self) -> bool:
        return bool(self.settings.finnhub_api_key)

    def _request_params(self, symbol: str) -> dict[str, str]:
        today = datetime.now(UTC).date()
        start = today - timedelta(days=LOOKBACK_DAYS)
        return {
            "symbol": symbol.upper(),
            "from": start.isoformat(),
            "to": today.isoformat(),
        }

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        self.ensure_enabled()
        try:
            response = self.transport.request(
                connection=self.connection,
                policy=self._budget_policy(),
                provider=self.provider_name,
                method="GET",
                base_url=self.base_url,
                path=self.path,
                headers={"X-Finnhub-Token": self.settings.finnhub_api_key or ""},
                params=self._request_params(symbol),
                json_body=None,
                operation=self.endpoint,
                cache_scope=self._cache_scope(self.endpoint, symbol),
                cache_ttl_seconds=self.settings.news_cache_ttl_hours * 3600,
                max_response_bytes=8 * 1024 * 1024,
                decoder="json",
                now=datetime.now(UTC),
                sleeper=time.sleep,
                bypass_cache=force,
            )
        except ProviderBudgetExceeded as exc:
            raise RateLimitExceeded(str(exc)) from None
        except SafeProviderTransportError as exc:
            raise ProviderError(str(exc)) from None
        if not isinstance(response.payload, list):
            raise ProviderError(f"{self.provider_name}:{self.endpoint}:INVALID_PAYLOAD")
        wrapped = {"articles": response.payload[:50]}
        return self.normalize_news(wrapped, symbol), response.from_cache

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
