from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backend.app.services.technical_analysis import TechnicalAnalysisService


@dataclass
class ScoringEngine:
    """BUY/HOLD/REDUCE/SELL scoring rules based on technical indicators."""

    technical_analysis: TechnicalAnalysisService = field(default_factory=TechnicalAnalysisService)

    def _signal_from_score(self, score: float) -> str:
        if score >= 75:
            return "BUY"
        if score >= 55:
            return "HOLD"
        if score >= 40:
            return "REDUCE"
        return "SELL"

    def score_prices(
        self,
        prices: pd.DataFrame,
        asset_id: int,
        symbol: str,
        risk_level: str,
    ) -> dict[str, object]:
        indicators = self.technical_analysis.calculate_indicators(prices)
        close = indicators.get("close")
        sma_50 = indicators.get("sma_50")
        sma_200 = indicators.get("sma_200")
        rsi_14 = indicators.get("rsi_14")
        macd_line = indicators.get("macd_line")
        macd_signal = indicators.get("macd_signal")
        volatility = indicators.get("volatility_annualized_30d")
        max_drawdown = indicators.get("max_drawdown")

        score = 0.0
        summary_parts: list[str] = []

        if close is not None and sma_50 is not None:
            if close > sma_50:
                score += 15
                summary_parts.append("prezzo sopra SMA50")
            else:
                summary_parts.append("prezzo sotto SMA50")

        if close is not None and sma_200 is not None:
            if close > sma_200:
                score += 15
                summary_parts.append("prezzo sopra SMA200")
            else:
                summary_parts.append("prezzo sotto SMA200")

        if sma_50 is not None and sma_200 is not None:
            if sma_50 > sma_200:
                score += 15
                summary_parts.append("SMA50 sopra SMA200")
            else:
                summary_parts.append("SMA50 sotto SMA200")

        if rsi_14 is not None:
            if 45 <= rsi_14 <= 65:
                score += 15
                summary_parts.append(f"RSI equilibrato ({rsi_14:.1f})")
            elif 35 <= rsi_14 <= 75:
                score += 10
                summary_parts.append(f"RSI gestibile ({rsi_14:.1f})")
            elif 25 <= rsi_14 <= 80:
                score += 5
                summary_parts.append(f"RSI in area di attenzione ({rsi_14:.1f})")
            else:
                summary_parts.append(f"RSI estremo ({rsi_14:.1f})")

        if macd_line is not None and macd_signal is not None:
            if macd_line > macd_signal:
                score += 15
                summary_parts.append("MACD positivo")
            else:
                score += 5
                summary_parts.append("MACD debole")

        if volatility is not None:
            if volatility < 0.20:
                score += 15
                summary_parts.append(f"volatilita bassa ({volatility * 100:.1f}%)")
            elif volatility < 0.35:
                score += 10
                summary_parts.append(f"volatilita moderata ({volatility * 100:.1f}%)")
            elif volatility < 0.55:
                score += 5
                summary_parts.append(f"volatilita elevata ({volatility * 100:.1f}%)")
            else:
                summary_parts.append(f"volatilita molto elevata ({volatility * 100:.1f}%)")

        if max_drawdown is not None:
            if max_drawdown > -0.15:
                score += 10
                summary_parts.append(f"drawdown contenuto ({max_drawdown * 100:.1f}%)")
            elif max_drawdown > -0.30:
                score += 6
                summary_parts.append(f"drawdown medio ({max_drawdown * 100:.1f}%)")
            elif max_drawdown > -0.50:
                score += 3
                summary_parts.append(f"drawdown alto ({max_drawdown * 100:.1f}%)")
            else:
                summary_parts.append(f"drawdown severo ({max_drawdown * 100:.1f}%)")

        final_score = round(max(0.0, min(score, 100.0)), 2)
        signal = self._signal_from_score(final_score)

        return {
            "asset_id": asset_id,
            "symbol": symbol,
            "score": final_score,
            "signal": signal,
            "risk_level": risk_level,
            "technical_summary": "; ".join(summary_parts) or "Indicatori insufficienti.",
            "indicators": indicators,
        }

    def score_asset(self, asset_id: int) -> dict[str, object]:
        return {
            "asset_id": asset_id,
            "signal": "HOLD",
            "score": 50.0,
            "rationale": "Scoring engine requires price data.",
        }
