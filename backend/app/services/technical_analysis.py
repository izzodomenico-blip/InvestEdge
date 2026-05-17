from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class TechnicalAnalysisService:
    """Placeholder for indicators such as SMA, RSI, MACD and volatility."""

    def calculate_indicators(self, prices: pd.DataFrame) -> dict[str, float]:
        if prices.empty:
            return {}
        return {}
