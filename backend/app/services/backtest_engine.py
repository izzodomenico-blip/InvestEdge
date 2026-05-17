from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestEngine:
    """Placeholder for strategy simulation and historical performance metrics."""

    def run(self, prices: pd.DataFrame) -> dict[str, object]:
        return {
            "trades": [],
            "equity_curve": [],
            "metrics": {},
            "rows": int(len(prices)),
        }
