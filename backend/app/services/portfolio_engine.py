from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PortfolioEngine:
    """Placeholder for allocation, weights and capital management logic."""

    def target_weights(self) -> dict[str, float]:
        return {
            "stock": 0.45,
            "etf": 0.30,
            "crypto": 0.05,
            "bond_etf": 0.20,
        }
