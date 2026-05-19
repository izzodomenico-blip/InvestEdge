from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.data_providers.news_base import BaseNewsProvider


MOCK_HEADLINES: list[dict[str, Any]] = [
    {
        "title": "{symbol} reports earnings beat and raises guidance",
        "summary": "The company posted earnings above analyst expectations and raised forward guidance, citing strong revenue growth.",
        "source": "Demo Newswire",
        "sentiment_hint": "POSITIVE",
        "relevance": 92.0,
    },
    {
        "title": "Analysts deliver a fresh upgrade for {symbol}",
        "summary": "A major brokerage upgraded {symbol} after announcing a new partnership and a dividend increase.",
        "source": "Demo Markets",
        "sentiment_hint": "POSITIVE",
        "relevance": 78.0,
    },
    {
        "title": "{symbol} faces lawsuit over alleged regulatory risk",
        "summary": "A class action lawsuit accuses {symbol} of regulatory risk after an investigation into business practices.",
        "source": "Demo Wire",
        "sentiment_hint": "NEGATIVE",
        "relevance": 85.0,
    },
    {
        "title": "{symbol} announces buyback program",
        "summary": "The board approved a multi-year buyback supported by stable cash flow and approval from regulators.",
        "source": "Demo Press",
        "sentiment_hint": "POSITIVE",
        "relevance": 70.0,
    },
    {
        "title": "{symbol} guidance cut weighs on outlook",
        "summary": "Management cut guidance for the next quarter, citing revenue decline in core markets and a possible downgrade.",
        "source": "Demo Wire",
        "sentiment_hint": "NEGATIVE",
        "relevance": 88.0,
    },
    {
        "title": "Industry update keeps {symbol} unchanged",
        "summary": "Sector wide commentary mentions {symbol} without specific catalysts.",
        "source": "Demo Daily",
        "sentiment_hint": "NEUTRAL",
        "relevance": 30.0,
    },
]


class MockNewsProvider(BaseNewsProvider):
    provider_name = "mock_news"
    endpoint = "MOCK_NEWS"

    def api_key_configured(self) -> bool:
        return True

    def ensure_enabled(self) -> None:
        return None

    def check_rate_limit(self) -> None:
        return None

    def supports_symbol(self, symbol: str) -> bool:
        return bool(symbol)

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        normalized = self.normalize_news({"symbol": symbol}, symbol)
        return normalized, False

    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        symbol_upper = symbol.upper()
        seed = int(hashlib.sha256(symbol_upper.encode("utf-8")).hexdigest(), 16) % len(MOCK_HEADLINES)
        now = datetime.now(UTC).replace(tzinfo=None)
        normalized: list[dict[str, Any]] = []
        for index, template in enumerate(MOCK_HEADLINES):
            offset_hours = (index + 1) * 6 + (seed * 2)
            published_at = (now - timedelta(hours=offset_hours)).isoformat(timespec="seconds")
            title = template["title"].format(symbol=symbol_upper)
            summary = template["summary"].format(symbol=symbol_upper)
            sentiment_hint = template["sentiment_hint"]
            sentiment_score = 0.0
            if sentiment_hint == "POSITIVE":
                sentiment_score = 0.4 + (index % 3) * 0.1
            elif sentiment_hint == "NEGATIVE":
                sentiment_score = -0.4 - (index % 3) * 0.1
            relevance = float(template["relevance"])
            url = f"https://example.invalid/news/{symbol_upper}-{seed}-{index}"
            normalized.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "source": template["source"],
                    "published_at": published_at,
                    "sentiment_score": sentiment_score,
                    "sentiment_label_hint": sentiment_hint,
                    "relevance_score": relevance,
                    "raw": {"mock": True, "symbol": symbol_upper, "index": index},
                }
            )
        return normalized
