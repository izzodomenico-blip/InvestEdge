from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from backend.app.data_providers.news_base import BaseNewsProvider


class NewsProviderMock(BaseNewsProvider):
    provider_name = "mock_news"
    endpoint = "MOCK_NEWS"

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        return self.normalize_news(self._mock_response(symbol), symbol), False

    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        feed = raw_response.get("feed")
        if not isinstance(feed, list):
            return []
        return [
            {
                "provider": self.provider_name,
                "title": str(item.get("title") or ""),
                "summary": str(item.get("summary") or ""),
                "url": item.get("url"),
                "source": str(item.get("source") or "InvestEdge Demo"),
                "published_at": str(item.get("published_at") or ""),
                "sentiment_score": float(item.get("sentiment_score", 0.0)),
                "sentiment_label": str(item.get("sentiment_label") or "NEUTRAL"),
                "relevance_score": float(item.get("relevance_score", 60.0)),
                "raw_json": item,
            }
            for item in feed
            if item.get("title")
        ]

    def _mock_response(self, symbol: str) -> dict[str, Any]:
        symbol_upper = symbol.upper()
        today = datetime.now(UTC).date()
        now = datetime.combine(today, time(hour=12)).replace(tzinfo=None)
        templates = [
            {
                "title": f"{symbol_upper} reports revenue growth as analysts review guidance",
                "summary": "Revenue growth and stable margins support a constructive but still monitored setup.",
                "sentiment_score": 0.42,
                "sentiment_label": "POSITIVE",
                "relevance_score": 82,
            },
            {
                "title": f"{symbol_upper} faces regulatory risk discussion in sector update",
                "summary": "Investors are watching regulatory risk and possible guidance cut headlines across peers.",
                "sentiment_score": -0.34,
                "sentiment_label": "NEGATIVE",
                "relevance_score": 68,
            },
            {
                "title": f"{symbol_upper} trades mixed while market waits for earnings",
                "summary": "",
                "sentiment_score": 0.02,
                "sentiment_label": "NEUTRAL",
                "relevance_score": 54,
            },
        ]
        return {
            "feed": [
                {
                    **item,
                    "source": "InvestEdge Demo",
                    "published_at": (now - timedelta(hours=index * 7)).isoformat(timespec="seconds"),
                    "url": f"https://example.com/investedge-demo/{symbol_upper.lower()}/{index}",
                }
                for index, item in enumerate(templates)
            ]
        }
