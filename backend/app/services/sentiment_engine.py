from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

POSITIVE_KEYWORDS = [
    "earnings beat",
    "revenue growth",
    "raises guidance",
    "upgrade",
    "partnership",
    "approval",
    "buyback",
    "dividend increase",
]

NEGATIVE_KEYWORDS = [
    "earnings miss",
    "revenue decline",
    "lawsuit",
    "downgrade",
    "investigation",
    "recall",
    "bankruptcy",
    "guidance cut",
    "regulatory risk",
]


def _text(value: str | None) -> str:
    return (value or "").lower()


def _keyword_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _label_from_score(score: float) -> str:
    if score >= 0.15:
        return "POSITIVE"
    if score <= -0.15:
        return "NEGATIVE"
    return "NEUTRAL"


def classify_sentiment(text: str | None) -> dict[str, float | str]:
    clean = _text(text)
    positive_hits = _keyword_hits(clean, POSITIVE_KEYWORDS)
    negative_hits = _keyword_hits(clean, NEGATIVE_KEYWORDS)
    raw_score = (positive_hits * 0.32) - (negative_hits * 0.32)

    if positive_hits and not negative_hits:
        raw_score += 0.12
    if negative_hits and not positive_hits:
        raw_score -= 0.12

    score = max(-1.0, min(1.0, raw_score))
    label = _label_from_score(score)
    return {
        "sentiment_score": round(score, 3),
        "sentiment_label": label,
        "score": round(score, 3),
        "label": label,
    }


def estimate_impact(news_item: dict[str, Any]) -> str:
    text = _text(f"{news_item.get('title') or ''} {news_item.get('summary') or ''}")
    relevance = float(news_item.get("relevance_score") or 0)
    sentiment_score = abs(float(news_item.get("sentiment_score") or 0))
    keyword_hits = _keyword_hits(text, POSITIVE_KEYWORDS) + _keyword_hits(text, NEGATIVE_KEYWORDS)

    if relevance >= 80 and (sentiment_score >= 0.40 or keyword_hits >= 1):
        return "HIGH"
    if relevance >= 65 and sentiment_score >= 0.55:
        return "HIGH"
    if relevance >= 50 or sentiment_score >= 0.25 or keyword_hits >= 1:
        return "MEDIUM"
    return "LOW"


def aggregate_news_sentiment(
    connection: sqlite3.Connection,
    symbol: str,
    lookback_days: int = 7,
    limit_latest: int = 5,
) -> dict[str, Any]:
    cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=lookback_days)).isoformat(timespec="seconds")
    rows = connection.execute(
        """
        SELECT id, symbol, provider, title, summary, url, source, published_at,
            sentiment_score, sentiment_label, impact_level, relevance_score, raw_json, created_at, updated_at
        FROM news_items
        WHERE UPPER(symbol) = UPPER(?)
          AND (published_at IS NULL OR published_at >= ?)
        ORDER BY published_at DESC, created_at DESC, id DESC
        """,
        (symbol, cutoff),
    ).fetchall()

    scores = [float(row["sentiment_score"] or 0) for row in rows]
    average = round(sum(scores) / len(scores), 4) if scores else 0.0
    positive_count = sum(1 for row in rows if row["sentiment_label"] == "POSITIVE")
    negative_count = sum(1 for row in rows if row["sentiment_label"] == "NEGATIVE")
    neutral_count = sum(1 for row in rows if row["sentiment_label"] == "NEUTRAL")
    impact_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    impact_level = "LOW"
    for row in rows:
        candidate = row["impact_level"] or "LOW"
        if impact_rank.get(candidate, 1) > impact_rank[impact_level]:
            impact_level = candidate

    return {
        "symbol": symbol.upper(),
        "lookback_days": lookback_days,
        "news_count": len(rows),
        "average_sentiment_score": average,
        "sentiment_label": _label_from_score(average),
        "impact_level": impact_level,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
        "latest_news": [dict(row) for row in rows[:limit_latest]],
    }


@dataclass
class SentimentEngine:
    """Small deterministic keyword sentiment engine."""

    def score_text(self, text: str) -> dict[str, float | str]:
        return classify_sentiment(text)

    def estimate_impact(self, news_item: dict[str, Any]) -> str:
        return estimate_impact(news_item)

    def aggregate(self, connection: sqlite3.Connection, symbol: str, lookback_days: int = 7) -> dict[str, Any]:
        return aggregate_news_sentiment(connection, symbol, lookback_days)
