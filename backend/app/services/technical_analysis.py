from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TechnicalAnalysisService:
    """Technical indicators used by the seed and scoring engines."""

    def enrich_price_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        if prices.empty:
            return prices.copy()

        frame = prices.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").reset_index(drop=True)
        close = frame["close"].astype(float)

        frame["sma_20"] = close.rolling(window=20, min_periods=20).mean()
        frame["sma_50"] = close.rolling(window=50, min_periods=50).mean()
        frame["sma_200"] = close.rolling(window=200, min_periods=200).mean()
        frame["ema_12"] = close.ewm(span=12, adjust=False).mean()
        frame["ema_26"] = close.ewm(span=26, adjust=False).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14, min_periods=14).mean()
        relative_strength = gain / loss.replace(0, np.nan)
        frame["rsi_14"] = 100 - (100 / (1 + relative_strength))
        frame.loc[(loss == 0) & (gain > 0), "rsi_14"] = 100
        frame.loc[(gain == 0) & (loss > 0), "rsi_14"] = 0

        frame["macd_line"] = frame["ema_12"] - frame["ema_26"]
        frame["macd_signal"] = frame["macd_line"].ewm(span=9, adjust=False).mean()

        returns = close.pct_change()
        frame["volatility_annualized_30d"] = returns.rolling(window=30, min_periods=30).std() * np.sqrt(252)
        running_max = close.cummax()
        frame["drawdown"] = (close / running_max) - 1
        frame["max_drawdown"] = frame["drawdown"].cummin()
        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        return frame

    def calculate_indicators(self, prices: pd.DataFrame) -> dict[str, float]:
        enriched = self.enrich_price_history(prices)
        if enriched.empty:
            return {}

        latest = enriched.iloc[-1]
        fields = [
            "sma_20",
            "sma_50",
            "sma_200",
            "ema_12",
            "ema_26",
            "rsi_14",
            "macd_line",
            "macd_signal",
            "volatility_annualized_30d",
            "max_drawdown",
        ]

        result: dict[str, float] = {"close": float(latest["close"])}
        for field in fields:
            value = latest.get(field)
            if pd.notna(value):
                result[field] = float(value)
        return result
