"""Score unico `score-v1` (spec SP1 §5.5).

Stessa logica di `ScoringEngine.score_prices` e delle condizioni/sintesi di `TechnicalAnalysisService`
(sottopunteggi, pesi, soglie, segnale, rischio, confidenza, motivazioni), calcolata per riga sulle feature
`features-v1`. Sostituzioni di input: `max_drawdown` -> `max_drawdown_252`, `obv >= 0` -> `obv_ratio_20 >= 0`,
`volatility_annualized_30d` -> `volatility_30d`, `close` -> `close_adj`, supporti e resistenze dalle feature
confermate. Golden/death cross (riga precedente) non entrano nello score e restano fuori.

Input mancanti (None, NaN, non finiti) gestiti come oggi; `warmup_complete` dice se tutti gli input dello score
sono disponibili (supporti e resistenze possono mancare).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.app.lab.features import FEATURE_COLUMNS_V1, NULLABLE_AFTER_WARMUP
from backend.app.services.common import clamp, signal_from_score

SUBSCORE_COLUMNS: tuple[str, ...] = (
    "trend_score", "momentum_score", "volatility_score", "volume_score", "support_resistance_score", "risk_penalty",
)
# Colonne lette dalla formula. `close_adj` non e in FEATURE_COLUMNS_V1 ma e un input dello score.
SCORE_INPUT_COLUMNS: tuple[str, ...] = (
    "close_adj", "sma_50", "sma_200", "adx_14", "plus_di", "minus_di", "supertrend_10_3",
    "rsi_14", "macd_line", "macd_signal", "stochastic_k", "stochastic_d", "roc_12",
    "volatility_30d", "max_drawdown_252", "atr_14", "volume_ratio_20", "obv_ratio_20",
    "support_distance_pct", "resistance_distance_pct",
)
_WARMUP_COLUMNS = tuple(column for column in SCORE_INPUT_COLUMNS if column not in NULLABLE_AFTER_WARMUP)
_CONFIDENCE_COLUMNS = (
    "sma_50", "sma_200", "rsi_14", "macd_line", "macd_signal", "adx_14", "atr_14",
    "volume_ratio_20", "volatility_30d", "max_drawdown_252",
)


@dataclass(frozen=True)
class _Evaluation:
    values: dict[str, float | None]
    conditions: dict[str, bool]
    reasons: list[dict[str, str]]
    subscores: dict[str, float]
    score: float
    signal: str
    risk_level: str
    confidence: str


def _number(row: Mapping[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(row: Mapping[str, Any], name: str) -> float | None:
    number = _number(row, name)
    return None if number is None else round(number, 6)


def _conditions(values: dict[str, float | None]) -> dict[str, bool]:
    close = values["close_adj"]
    sma_50 = values["sma_50"]
    sma_200 = values["sma_200"]
    rsi = values["rsi_14"]
    macd = values["macd_line"]
    macd_signal = values["macd_signal"]
    volatility = values["volatility_30d"]
    support_distance = values["support_distance_pct"]
    resistance_distance = values["resistance_distance_pct"]
    return {
        "price_above_sma50": close is not None and sma_50 is not None and close > sma_50,
        "price_above_sma200": close is not None and sma_200 is not None and close > sma_200,
        "bullish_macd": macd is not None and macd_signal is not None and macd > macd_signal,
        "bearish_macd": macd is not None and macd_signal is not None and macd < macd_signal,
        "rsi_overbought": rsi is not None and rsi >= 70,
        "rsi_oversold": rsi is not None and rsi <= 30,
        "high_volatility": volatility is not None and volatility >= 0.45,
        "near_support": support_distance is not None and support_distance <= 3,
        "near_resistance": resistance_distance is not None and resistance_distance <= 3,
    }


def _risk_level(volatility: float | None, max_drawdown: float | None, asset_risk_level: str) -> str:
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


def _confidence(values: dict[str, float | None], conditions: dict[str, bool]) -> str:
    available_ratio = sum(1 for column in _CONFIDENCE_COLUMNS if values[column] is not None) / len(_CONFIDENCE_COLUMNS)
    directional_votes = [
        conditions["price_above_sma50"],
        conditions["price_above_sma200"],
        conditions["bullish_macd"],
        not conditions["high_volatility"],
    ]
    agreement = max(sum(1 for vote in directional_votes if vote), sum(1 for vote in directional_votes if not vote)) / len(
        directional_votes
    )
    if available_ratio >= 0.85 and agreement >= 0.70:
        return "HIGH"
    if available_ratio >= 0.60:
        return "MEDIUM"
    return "LOW"


def _evaluate(row: Mapping[str, Any], risk_level: str) -> _Evaluation:
    values = {column: _number(row, column) for column in SCORE_INPUT_COLUMNS}
    conditions = _conditions(values)
    reasons: list[dict[str, str]] = []

    def reason(kind: str, message: str) -> None:
        reasons.append({"type": kind, "message": message})

    close = values["close_adj"]
    sma_50 = values["sma_50"]
    sma_200 = values["sma_200"]

    trend_score = 0.0
    if sma_50 is None:
        reason("neutral", "SMA50 non disponibile")
    elif conditions["price_above_sma50"]:
        trend_score += 22
        reason("positive", "Prezzo sopra SMA50")
    else:
        reason("negative", "Prezzo sotto SMA50")

    if sma_200 is None:
        reason("neutral", "SMA200 non disponibile")
    elif conditions["price_above_sma200"]:
        trend_score += 22
        reason("positive", "Prezzo sopra SMA200")
    else:
        reason("negative", "Prezzo sotto SMA200")

    if sma_50 is not None and sma_200 is not None:
        if sma_50 > sma_200:
            trend_score += 20
            reason("positive", "SMA50 sopra SMA200")
        else:
            reason("negative", "SMA50 sotto SMA200")

    adx = values["adx_14"]
    if adx is not None:
        plus_di = values["plus_di"] if values["plus_di"] is not None else 0.0
        minus_di = values["minus_di"] if values["minus_di"] is not None else 0.0
        if adx >= 25 and plus_di > minus_di:
            trend_score += 18
            reason("positive", "ADX conferma trend rialzista")
        elif adx >= 25 and minus_di > plus_di:
            reason("negative", "ADX conferma pressione ribassista")
        else:
            trend_score += 8
            reason("neutral", "ADX indica trend poco direzionale")

    supertrend = values["supertrend_10_3"]
    if supertrend is not None and close is not None:
        if close > supertrend:
            trend_score += 18
            reason("positive", "Prezzo sopra Supertrend")
        else:
            reason("negative", "Prezzo sotto Supertrend")

    momentum_score = 0.0
    rsi = values["rsi_14"]
    if rsi is not None:
        if 40 <= rsi <= 65:
            momentum_score += 35
            reason("positive", "RSI in zona sana")
        elif 30 <= rsi < 40 or 65 < rsi <= 72:
            momentum_score += 20
            reason("neutral", "RSI in zona di attenzione")
        elif conditions["rsi_overbought"]:
            momentum_score += 8
            reason("negative", "RSI in ipercomprato")
        elif conditions["rsi_oversold"]:
            momentum_score += 12
            reason("negative", "RSI in ipervenduto")

    if conditions["bullish_macd"]:
        momentum_score += 30
        reason("positive", "MACD positivo")
    elif conditions["bearish_macd"]:
        momentum_score += 8
        reason("negative", "MACD sotto il segnale")

    stochastic_k = values["stochastic_k"]
    stochastic_d = values["stochastic_d"]
    if stochastic_k is not None and stochastic_d is not None:
        if stochastic_k > stochastic_d and stochastic_k < 80:
            momentum_score += 18
            reason("positive", "Stochastic favorevole senza eccessi")
        elif stochastic_k > 85:
            momentum_score += 6
            reason("negative", "Stochastic in area tirata")
        else:
            momentum_score += 10

    roc = values["roc_12"]
    if roc is not None:
        if roc > 0:
            momentum_score += 17
            reason("positive", "ROC 12 positivo")
        else:
            reason("negative", "ROC 12 negativo")

    volatility_score = 0.0
    volatility = values["volatility_30d"]
    max_drawdown = values["max_drawdown_252"]
    atr = values["atr_14"]
    if volatility is not None:
        if volatility < 0.20:
            volatility_score += 45
            reason("positive", "Volatilita bassa")
        elif volatility < 0.40:
            volatility_score += 32
            reason("neutral", "Volatilita moderata")
        else:
            volatility_score += 12
            reason("negative", "Volatilita elevata penalizza il punteggio")
    if max_drawdown is not None:
        if max_drawdown > -0.18:
            volatility_score += 35
            reason("positive", "Max drawdown contenuto")
        elif max_drawdown > -0.35:
            volatility_score += 22
            reason("neutral", "Max drawdown medio")
        else:
            volatility_score += 8
            reason("negative", "Max drawdown elevato")
    if atr is not None and close:
        atr_percent = atr / close
        volatility_score += 20 if atr_percent < 0.025 else 10 if atr_percent < 0.055 else 4

    volume_score = 45.0
    volume_ratio = values["volume_ratio_20"]
    if volume_ratio is not None:
        if 1.0 <= volume_ratio <= 2.5:
            volume_score += 35
            reason("positive", "Volume conferma il movimento")
        elif volume_ratio < 0.75:
            volume_score += 10
            reason("negative", "Volume sotto media")
        else:
            volume_score += 20
            reason("neutral", "Volume molto sopra media")
    obv_ratio = values["obv_ratio_20"]
    if obv_ratio is not None:
        volume_score += 20 if obv_ratio >= 0 else 8

    support_resistance_score = 50.0
    support_distance = values["support_distance_pct"]
    if support_distance is not None:
        if support_distance <= 3:
            support_resistance_score += 25
            reason("positive", "Prezzo vicino a supporto")
        elif support_distance <= 8:
            support_resistance_score += 12
    resistance_distance = values["resistance_distance_pct"]
    if resistance_distance is not None:
        if resistance_distance <= 3:
            support_resistance_score -= 25
            reason("negative", "Prezzo vicino a resistenza riduce il potenziale")
        elif resistance_distance <= 8:
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
    if conditions["near_resistance"]:
        risk_penalty += 8

    subscores = {
        "trend_score": round(clamp(trend_score), 2),
        "momentum_score": round(clamp(momentum_score), 2),
        "volatility_score": round(clamp(volatility_score), 2),
        "volume_score": round(clamp(volume_score), 2),
        "support_resistance_score": round(clamp(support_resistance_score), 2),
        "risk_penalty": round(clamp(risk_penalty), 2),
    }
    weighted_score = (
        subscores["trend_score"] * 0.30
        + subscores["momentum_score"] * 0.25
        + subscores["volatility_score"] * 0.15
        + subscores["volume_score"] * 0.10
        + subscores["support_resistance_score"] * 0.10
        - subscores["risk_penalty"] * 0.10
    )
    score = round(clamp(weighted_score), 2)
    return _Evaluation(
        values=values,
        conditions=conditions,
        reasons=reasons,
        subscores=subscores,
        score=score,
        signal=signal_from_score(score),
        risk_level=_risk_level(volatility, max_drawdown, risk_level),
        confidence=_confidence(values, conditions),
    )


def _trend_summary(values: dict[str, float | None], conditions: dict[str, bool]) -> str:
    if conditions["price_above_sma50"] and conditions["price_above_sma200"]:
        return "Trend positivo: prezzo sopra SMA50 e SMA200."
    if not conditions["price_above_sma50"] and not conditions["price_above_sma200"]:
        return "Trend debole: prezzo sotto le principali medie."
    if (values["adx_14"] or 0) >= 25:
        return "Trend direzionale presente secondo ADX."
    return "Trend misto o in fase laterale."


def _momentum_summary(values: dict[str, float | None], conditions: dict[str, bool]) -> str:
    rsi = values["rsi_14"]
    if conditions["bullish_macd"] and rsi is not None and 40 <= rsi <= 65:
        return "Momentum costruttivo: MACD positivo e RSI in zona sana."
    if conditions["rsi_overbought"]:
        return "Momentum forte ma RSI in ipercomprato."
    if conditions["rsi_oversold"]:
        return "Momentum debole ma RSI in ipervenduto."
    if conditions["bearish_macd"]:
        return "Momentum fragile: MACD sotto il segnale."
    return "Momentum neutrale."


def _volatility_summary(values: dict[str, float | None], conditions: dict[str, bool]) -> str:
    volatility = values["volatility_30d"]
    if conditions["high_volatility"]:
        return f"Volatilita elevata ({volatility * 100:.1f}%)." if volatility is not None else "Volatilita elevata."
    if volatility is not None:
        return f"Volatilita annualizzata 30 giorni pari a {volatility * 100:.1f}%."
    return "Volatilita non disponibile."


def _volume_summary(values: dict[str, float | None]) -> str:
    ratio = values["volume_ratio_20"]
    if ratio is None:
        return "Volume non disponibile."
    if ratio >= 1.5:
        return "Volume sopra la media, possibile partecipazione elevata."
    if ratio <= 0.7:
        return "Volume sotto la media, movimento meno confermato."
    return "Volume in linea con la media recente."


def _overall_bias(values: dict[str, float | None], conditions: dict[str, bool]) -> str:
    score = 0
    score += 1 if conditions["price_above_sma50"] else -1
    score += 1 if conditions["price_above_sma200"] else -1
    score += 1 if conditions["bullish_macd"] else -1 if conditions["bearish_macd"] else 0
    score += -1 if conditions["high_volatility"] else 0
    score += 1 if conditions["near_support"] else 0
    score += -1 if conditions["near_resistance"] else 0
    if (values["adx_14"] or 0) >= 25 and score > 0:
        score += 1
    if score >= 3:
        return "BULLISH"
    if score <= -3:
        return "BEARISH"
    return "NEUTRAL"


def explain(row: Mapping[str, Any], risk_level: str) -> dict[str, Any]:
    """Score, motivazioni, condizioni e sintesi di una riga di feature (chiavi di `score_prices` senza asset/simbolo)."""
    evaluation = _evaluate(row, risk_level)
    values = evaluation.values
    conditions = evaluation.conditions
    summaries = {
        "trend_summary": _trend_summary(values, conditions),
        "momentum_summary": _momentum_summary(values, conditions),
        "volatility_summary": _volatility_summary(values, conditions),
        "volume_summary": _volume_summary(values),
        "overall_technical_bias": _overall_bias(values, conditions),
    }
    technical_summary = (
        f"{evaluation.signal} con score {evaluation.score:.1f}/100, rischio {evaluation.risk_level} "
        f"e confidenza {evaluation.confidence}. "
        f"{summaries['trend_summary']} {summaries['momentum_summary']} {summaries['volatility_summary']}"
    )
    indicators = {column: value for column in FEATURE_COLUMNS_V1 if (value := _rounded(row, column)) is not None}
    return {
        "latest_close": _rounded(row, "close_adj"),
        "score": evaluation.score,
        "signal": evaluation.signal,
        "risk_level": evaluation.risk_level,
        "confidence": evaluation.confidence,
        "technical_summary": technical_summary,
        "reasons": evaluation.reasons,
        "subscores": evaluation.subscores,
        "indicators": indicators,
        "conditions": conditions,
        "support_resistance": {
            "nearest_support": _rounded(row, "nearest_support"),
            "nearest_resistance": _rounded(row, "nearest_resistance"),
            "support_distance_percent": _rounded(row, "support_distance_pct"),
            "resistance_distance_percent": _rounded(row, "resistance_distance_pct"),
        },
        "summaries": summaries,
    }


def score_frame(features: pd.DataFrame, risk_level: str) -> pd.DataFrame:
    """Score, segnale, confidenza, sottopunteggi e `warmup_complete` per ogni riga, con la stessa logica di `explain`."""
    evaluations = [_evaluate(record, risk_level) for record in features.to_dict("records")]
    frame = pd.DataFrame(
        {
            "score": [evaluation.score for evaluation in evaluations],
            "signal": [evaluation.signal for evaluation in evaluations],
            "confidence": [evaluation.confidence for evaluation in evaluations],
            **{column: [evaluation.subscores[column] for evaluation in evaluations] for column in SUBSCORE_COLUMNS},
        },
        index=features.index,
    )
    inputs = features.reindex(columns=list(_WARMUP_COLUMNS)).to_numpy(dtype=float)
    frame["warmup_complete"] = np.isfinite(inputs).all(axis=1)
    return frame
