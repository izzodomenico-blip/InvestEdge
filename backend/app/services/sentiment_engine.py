from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any


POSITIVE_KEYWORDS: list[str] = [
    "earnings beat",
    "revenue growth",
    "raises guidance",
    "upgrade",
    "partnership",
    "approval",
    "buyback",
    "dividend increase",
]

NEGATIVE_KEYWORDS: list[str] = [
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

HIGH_IMPACT_KEYWORDS = {
    "bankruptcy",
    "earnings beat",
    "earnings miss",
    "raises guidance",
    "guidance cut",
    "lawsuit",
    "investigation",
    "regulatory risk",
    "buyback",
    "recall",
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return text.lower()


def classify_sentiment(text: str | None) -> dict[str, Any]:
    """Classify a free-text snippet into POSITIVE / NEGATIVE / NEUTRAL with score in [-1, 1].

    Heuristic only — keyword based, no machine learning.
    """
    normalized = _normalize_text(text)
    positive_hits = [keyword for keyword in POSITIVE_KEYWORDS if keyword in normalized]
    negative_hits = [keyword for keyword in NEGATIVE_KEYWORDS if keyword in normalized]

    if not positive_hits and not negative_hits:
        return {
            "sentiment_label": "NEUTRAL",
            "sentiment_score": 0.0,
            "positive_hits": [],
            "negative_hits": [],
        }

    pos_weight = sum(0.25 for _ in positive_hits)
    neg_weight = sum(0.25 for _ in negative_hits)
    raw_score = pos_weight - neg_weight
    score = _clamp(raw_score, -1.0, 1.0)
    label = "POSITIVE" if score > 0.05 else "NEGATIVE" if score < -0.05 else "NEUTRAL"
    return {
        "sentiment_label": label,
        "sentiment_score": round(score, 3),
        "positive_hits": positive_hits,
        "negative_hits": negative_hits,
    }


def estimate_impact(news_item: dict[str, Any]) -> dict[str, Any]:
    """Estimate impact_level (LOW/MEDIUM/HIGH) and relevance_score (0-100).

    Uses keyword strength, relevance signal if provided, and absolute sentiment.
    """
    text = " ".join(
        str(news_item.get(field) or "")
        for field in ("title", "summary")
    )
    classification = classify_sentiment(text)
    hits = classification["positive_hits"] + classification["negative_hits"]
    sentiment_score = float(news_item.get("sentiment_score") or classification["sentiment_score"] or 0.0)

    raw_relevance = news_item.get("relevance_score")
    try:
        relevance = float(raw_relevance) if raw_relevance is not None else None
    except (TypeError, ValueError):
        relevance = None

    keyword_score = 0.0
    high_impact_hit = False
    for hit in hits:
        keyword_score += 18.0
        if hit in HIGH_IMPACT_KEYWORDS:
            keyword_score += 14.0
            high_impact_hit = True

    if relevance is None:
        relevance = _clamp(keyword_score + abs(sentiment_score) * 60.0, 0.0, 100.0)
    else:
        relevance = _clamp(relevance, 0.0, 100.0)

    if high_impact_hit and (abs(sentiment_score) >= 0.5 or relevance >= 70.0):
        impact_level = "HIGH"
    elif hits or abs(sentiment_score) >= 0.35 or relevance >= 55.0:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    label_hint = news_item.get("sentiment_label_hint")
    if isinstance(label_hint, str) and label_hint in {"POSITIVE", "NEGATIVE", "NEUTRAL"}:
        sentiment_label = label_hint
    elif sentiment_score > 0.05:
        sentiment_label = "POSITIVE"
    elif sentiment_score < -0.05:
        sentiment_label = "NEGATIVE"
    else:
        sentiment_label = classification["sentiment_label"]

    return {
        "sentiment_label": sentiment_label,
        "sentiment_score": round(_clamp(sentiment_score, -1.0, 1.0), 3),
        "impact_level": impact_level,
        "relevance_score": round(relevance, 2),
        "keyword_hits": hits,
    }


def aggregate_news_sentiment(
    connection: sqlite3.Connection,
    symbol: str,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Aggregate news sentiment for a symbol across the lookback window."""
    threshold = (
        datetime.now(UTC).replace(tzinfo=None) - timedelta(days=max(1, lookback_days))
    ).isoformat(timespec="seconds")
    rows = connection.execute(
        """
        SELECT id, title, summary, sentiment_score, sentiment_label, impact_level, relevance_score,
               published_at, source, url
        FROM news_items
        WHERE UPPER(COALESCE(symbol, '')) = UPPER(?)
          AND COALESCE(published_at, created_at) >= ?
        ORDER BY COALESCE(published_at, created_at) DESC, id DESC
        LIMIT 200
        """,
        (symbol, threshold),
    ).fetchall()

    items = [dict(row) for row in rows]
    news_count = len(items)
    if news_count == 0:
        return {
            "symbol": symbol.upper(),
            "lookback_days": lookback_days,
            "news_count": 0,
            "average_sentiment_score": 0.0,
            "sentiment_label": "NEUTRAL",
            "impact_level": "LOW",
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "latest_news": [],
        }

    positive = sum(1 for item in items if (item.get("sentiment_label") or "") == "POSITIVE")
    negative = sum(1 for item in items if (item.get("sentiment_label") or "") == "NEGATIVE")
    neutral = news_count - positive - negative
    weighted_total = 0.0
    weight_sum = 0.0
    for item in items:
        try:
            score = float(item.get("sentiment_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            relevance = float(item.get("relevance_score") or 50.0)
        except (TypeError, ValueError):
            relevance = 50.0
        weight = max(10.0, relevance)
        weighted_total += score * weight
        weight_sum += weight
    average = weighted_total / weight_sum if weight_sum else 0.0

    if average > 0.1:
        label = "POSITIVE"
    elif average < -0.1:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"

    has_high = any(item.get("impact_level") == "HIGH" for item in items)
    has_medium = any(item.get("impact_level") == "MEDIUM" for item in items)
    if has_high:
        impact_level = "HIGH"
    elif has_medium:
        impact_level = "MEDIUM"
    else:
        impact_level = "LOW"

    latest = []
    for item in items[:5]:
        latest.append(
            {
                "id": item["id"],
                "title": item["title"],
                "summary": item["summary"],
                "url": item["url"],
                "source": item["source"],
                "published_at": item["published_at"],
                "sentiment_label": item["sentiment_label"] or "NEUTRAL",
                "sentiment_score": float(item.get("sentiment_score") or 0.0),
                "impact_level": item["impact_level"] or "LOW",
                "relevance_score": float(item.get("relevance_score") or 0.0),
            }
        )

    return {
        "symbol": symbol.upper(),
        "lookback_days": lookback_days,
        "news_count": news_count,
        "average_sentiment_score": round(_clamp(average, -1.0, 1.0), 3),
        "sentiment_label": label,
        "impact_level": impact_level,
        "positive_count": positive,
        "negative_count": negative,
        "neutral_count": neutral,
        "latest_news": latest,
    }


class SentimentEngine:
    """Backwards-compatible engine class that exposes the heuristic functions."""

    def classify(self, text: str | None) -> dict[str, Any]:
        return classify_sentiment(text)

    def estimate(self, news_item: dict[str, Any]) -> dict[str, Any]:
        return estimate_impact(news_item)

    def aggregate(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        lookback_days: int = 7,
    ) -> dict[str, Any]:
        return aggregate_news_sentiment(connection, symbol, lookback_days)

    def score_text(self, text: str) -> dict[str, Any]:
        classified = classify_sentiment(text)
        return {"label": classified["sentiment_label"], "score": classified["sentiment_score"]}
