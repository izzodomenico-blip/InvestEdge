from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SentimentEngine:
    """Placeholder for rule-based or API-backed sentiment scoring."""

    def score_text(self, text: str) -> dict[str, float | str]:
        return {
            "label": "neutral",
            "score": 0.0,
        }
