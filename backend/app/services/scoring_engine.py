from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.app.services.technical_analysis import TechnicalAnalysisService


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and pd.notna(value)


@dataclass
class ScoringEngine:
    """Explainable technical scoring engine."""

    technical_analysis: TechnicalAnalysisService = field(default_factory=TechnicalAnalysisService)

    def _signal_from_score(self, score: float) -> str:
        if score >= 80:
            return "STRONG_BUY"
        if score >= 70:
            return "BUY"
        if score >= 55:
            return "HOLD"
        if score >= 40:
            return "REDUCE"
        return "SELL"

    def _risk_level(self, volatility: float | None, max_drawdown: float | None, asset_risk_level: str) -> str:
        normalized = asset_risk_level.lower()
        if normalized in {"high", "very_high"}:
            baseline = "HIGH"
        elif normalized == "low":
            baseline = "LOW"
        else:
            baseline = "MEDIUM"

        if volatility is not None and volatility >= 0.55:
            return "HIGH"
        if max_drawdown is not None and max_drawdown <= -0.45:
            return "HIGH"
        if volatility is not None and volatility <= 0.18 and max_drawdown is not None and max_drawdown > -0.18:
            return "LOW" if baseline != "HIGH" else "MEDIUM"
        return baseline

    def _confidence(self, indicators: dict[str, float], conditions: dict[str, bool]) -> str:
        required = [
            "sma_50",
            "sma_200",
            "rsi_14",
            "macd_line",
            "macd_signal",
            "adx_14",
            "atr_14",
            "volume_ratio_20",
            "volatility_annualized_30d",
            "max_drawdown",
        ]
        available_ratio = sum(1 for field in required if field in indicators) / len(required)
        directional_votes = [
            conditions.get("price_above_sma50"),
            conditions.get("price_above_sma200"),
            conditions.get("bullish_macd"),
            not conditions.get("high_volatility"),
        ]
        agreement = max(sum(1 for vote in directional_votes if vote), sum(1 for vote in directional_votes if not vote)) / len(directional_votes)

        if available_ratio >= 0.85 and agreement >= 0.70:
            return "HIGH"
        if available_ratio >= 0.60:
            return "MEDIUM"
        return "LOW"

    def score_prices(
        self,
        prices: pd.DataFrame,
        asset_id: int,
        symbol: str,
        risk_level: str,
    ) -> dict[str, object]:
        analysis = self.technical_analysis.calculate_full_technical_analysis(prices)
        indicators = analysis["indicators"]
        conditions = analysis["conditions"]
        support_resistance = analysis["support_resistance"]
        reasons: list[dict[str, str]] = []

        trend_score = 0.0
        if indicators.get("sma_50") is None:
            reasons.append({"type": "neutral", "message": "SMA50 non disponibile"})
        elif conditions.get("price_above_sma50"):
            trend_score += 22
            reasons.append({"type": "positive", "message": "Prezzo sopra SMA50"})
        else:
            reasons.append({"type": "negative", "message": "Prezzo sotto SMA50"})

        if indicators.get("sma_200") is None:
            reasons.append({"type": "neutral", "message": "SMA200 non disponibile"})
        elif conditions.get("price_above_sma200"):
            trend_score += 22
            reasons.append({"type": "positive", "message": "Prezzo sopra SMA200"})
        else:
            reasons.append({"type": "negative", "message": "Prezzo sotto SMA200"})

        if indicators.get("sma_50") is not None and indicators.get("sma_200") is not None:
            if indicators["sma_50"] > indicators["sma_200"]:
                trend_score += 20
                reasons.append({"type": "positive", "message": "SMA50 sopra SMA200"})
            else:
                reasons.append({"type": "negative", "message": "SMA50 sotto SMA200"})

        if indicators.get("adx_14") is not None:
            if indicators["adx_14"] >= 25 and indicators.get("plus_di", 0) > indicators.get("minus_di", 0):
                trend_score += 18
                reasons.append({"type": "positive", "message": "ADX conferma trend rialzista"})
            elif indicators["adx_14"] >= 25 and indicators.get("minus_di", 0) > indicators.get("plus_di", 0):
                reasons.append({"type": "negative", "message": "ADX conferma pressione ribassista"})
            else:
                trend_score += 8
                reasons.append({"type": "neutral", "message": "ADX indica trend poco direzionale"})

        if indicators.get("supertrend_10_3") is not None and analysis["latest_close"] is not None:
            if analysis["latest_close"] > indicators["supertrend_10_3"]:
                trend_score += 18
                reasons.append({"type": "positive", "message": "Prezzo sopra Supertrend"})
            else:
                reasons.append({"type": "negative", "message": "Prezzo sotto Supertrend"})

        momentum_score = 0.0
        rsi = indicators.get("rsi_14")
        if rsi is not None:
            if 40 <= rsi <= 65:
                momentum_score += 35
                reasons.append({"type": "positive", "message": "RSI in zona sana"})
            elif 30 <= rsi < 40 or 65 < rsi <= 72:
                momentum_score += 20
                reasons.append({"type": "neutral", "message": "RSI in zona di attenzione"})
            elif conditions.get("rsi_overbought"):
                momentum_score += 8
                reasons.append({"type": "negative", "message": "RSI in ipercomprato"})
            elif conditions.get("rsi_oversold"):
                momentum_score += 12
                reasons.append({"type": "negative", "message": "RSI in ipervenduto"})

        if conditions.get("bullish_macd"):
            momentum_score += 30
            reasons.append({"type": "positive", "message": "MACD positivo"})
        elif conditions.get("bearish_macd"):
            momentum_score += 8
            reasons.append({"type": "negative", "message": "MACD sotto il segnale"})

        stochastic_k = indicators.get("stochastic_k")
        stochastic_d = indicators.get("stochastic_d")
        if stochastic_k is not None and stochastic_d is not None:
            if stochastic_k > stochastic_d and stochastic_k < 80:
                momentum_score += 18
                reasons.append({"type": "positive", "message": "Stochastic favorevole senza eccessi"})
            elif stochastic_k > 85:
                momentum_score += 6
                reasons.append({"type": "negative", "message": "Stochastic in area tirata"})
            else:
                momentum_score += 10

        if indicators.get("roc_12") is not None:
            if indicators["roc_12"] > 0:
                momentum_score += 17
                reasons.append({"type": "positive", "message": "ROC 12 positivo"})
            else:
                reasons.append({"type": "negative", "message": "ROC 12 negativo"})

        volatility_score = 0.0
        volatility = indicators.get("volatility_annualized_30d")
        max_drawdown = indicators.get("max_drawdown")
        atr = indicators.get("atr_14")
        latest_close = analysis["latest_close"]
        if volatility is not None:
            if volatility < 0.20:
                volatility_score += 45
                reasons.append({"type": "positive", "message": "Volatilita bassa"})
            elif volatility < 0.40:
                volatility_score += 32
                reasons.append({"type": "neutral", "message": "Volatilita moderata"})
            else:
                volatility_score += 12
                reasons.append({"type": "negative", "message": "Volatilita elevata penalizza il punteggio"})
        if max_drawdown is not None:
            if max_drawdown > -0.18:
                volatility_score += 35
                reasons.append({"type": "positive", "message": "Max drawdown contenuto"})
            elif max_drawdown > -0.35:
                volatility_score += 22
                reasons.append({"type": "neutral", "message": "Max drawdown medio"})
            else:
                volatility_score += 8
                reasons.append({"type": "negative", "message": "Max drawdown elevato"})
        if atr is not None and latest_close:
            atr_percent = atr / latest_close
            volatility_score += 20 if atr_percent < 0.025 else 10 if atr_percent < 0.055 else 4

        volume_score = 45.0
        volume_ratio = indicators.get("volume_ratio_20")
        if volume_ratio is not None:
            if 1.0 <= volume_ratio <= 2.5:
                volume_score += 35
                reasons.append({"type": "positive", "message": "Volume conferma il movimento"})
            elif volume_ratio < 0.75:
                volume_score += 10
                reasons.append({"type": "negative", "message": "Volume sotto media"})
            else:
                volume_score += 20
                reasons.append({"type": "neutral", "message": "Volume molto sopra media"})

        if indicators.get("obv") is not None:
            volume_score += 20 if indicators["obv"] >= 0 else 8

        support_resistance_score = 50.0
        if support_resistance.get("support_distance_percent") is not None:
            distance = support_resistance["support_distance_percent"]
            if distance <= 3:
                support_resistance_score += 25
                reasons.append({"type": "positive", "message": "Prezzo vicino a supporto"})
            elif distance <= 8:
                support_resistance_score += 12

        if support_resistance.get("resistance_distance_percent") is not None:
            distance = support_resistance["resistance_distance_percent"]
            if distance <= 3:
                support_resistance_score -= 25
                reasons.append({"type": "negative", "message": "Prezzo vicino a resistenza riduce il potenziale"})
            elif distance <= 8:
                support_resistance_score -= 10

        risk_penalty = 0.0
        normalized_asset_risk = risk_level.lower()
        if normalized_asset_risk == "very_high":
            risk_penalty += 45
        elif normalized_asset_risk == "high":
            risk_penalty += 30
        elif normalized_asset_risk == "medium":
            risk_penalty += 15

        if volatility is not None and volatility >= 0.45:
            risk_penalty += 25
        if max_drawdown is not None and max_drawdown <= -0.35:
            risk_penalty += 25
        if conditions.get("near_resistance"):
            risk_penalty += 8

        subscores = {
            "trend_score": round(_clamp(trend_score), 2),
            "momentum_score": round(_clamp(momentum_score), 2),
            "volatility_score": round(_clamp(volatility_score), 2),
            "volume_score": round(_clamp(volume_score), 2),
            "support_resistance_score": round(_clamp(support_resistance_score), 2),
            "risk_penalty": round(_clamp(risk_penalty), 2),
        }

        weighted_score = (
            subscores["trend_score"] * 0.30
            + subscores["momentum_score"] * 0.25
            + subscores["volatility_score"] * 0.15
            + subscores["volume_score"] * 0.10
            + subscores["support_resistance_score"] * 0.10
            - subscores["risk_penalty"] * 0.10
        )
        final_score = round(_clamp(weighted_score), 2)
        signal = self._signal_from_score(final_score)
        computed_risk = self._risk_level(
            volatility if _is_number(volatility) else None,
            max_drawdown if _is_number(max_drawdown) else None,
            risk_level,
        )
        confidence = self._confidence(indicators, conditions)
        technical_summary = self._summary(signal, analysis, final_score, computed_risk, confidence)

        return {
            "asset_id": asset_id,
            "symbol": symbol,
            "latest_close": latest_close,
            "score": final_score,
            "signal": signal,
            "risk_level": computed_risk,
            "confidence": confidence,
            "technical_summary": technical_summary,
            "reasons": reasons,
            "subscores": subscores,
            "indicators": indicators,
            "conditions": conditions,
            "support_resistance": support_resistance,
            "summaries": {
                "trend_summary": analysis["trend_summary"],
                "momentum_summary": analysis["momentum_summary"],
                "volatility_summary": analysis["volatility_summary"],
                "volume_summary": analysis["volume_summary"],
                "overall_technical_bias": analysis["overall_technical_bias"],
            },
        }

    def _summary(
        self,
        signal: str,
        analysis: dict[str, object],
        score: float,
        risk_level: str,
        confidence: str,
    ) -> str:
        return (
            f"{signal} con score {score:.1f}/100, rischio {risk_level} e confidenza {confidence}. "
            f"{analysis['trend_summary']} {analysis['momentum_summary']} {analysis['volatility_summary']}"
        )

    def score_asset(self, asset_id: int) -> dict[str, object]:
        return {
            "asset_id": asset_id,
            "signal": "HOLD",
            "score": 50.0,
            "risk_level": "MEDIUM",
            "confidence": "LOW",
            "technical_summary": "Scoring engine requires price data.",
            "reasons": [{"type": "neutral", "message": "Dati prezzo non disponibili"}],
            "subscores": {},
            "indicators": {},
        }
