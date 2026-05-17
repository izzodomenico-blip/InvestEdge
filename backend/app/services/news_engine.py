from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NewsEngine:
    """Placeholder for authorized news API integration."""

    def latest(self, symbol: str | None = None) -> list[dict[str, object]]:
        return []
