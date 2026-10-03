from __future__ import annotations

from datetime import date

import pytest

from backend.app.lab.features import compute_features
from backend.app.lab.resample import resample_bars
from backend.app.lab.score_v1 import explain, score_frame
from tests.lab_fixtures import synthetic_bars

# Valori di riferimento catturati dalla formula attuale (ScoringEngine.score_prices con
# TechnicalAnalysisService.calculate_full_technical_analysis sostituita dall'analisi del caso), SP1 Task 3 Step 1.
GOLDEN_CASES: list[dict] = [
    {
        "name": "trend_rialzista_pieno",
        "risk_level": "low",
        "latest_close": 152.4,
        "indicators": {
            "close": 152.4, "sma_20": 148.1, "sma_50": 140.25, "sma_200": 120.8, "rsi_14": 58.3, "macd_line": 2.15,
            "macd_signal": 1.6, "macd_histogram": 0.55, "stochastic_k": 62.0, "stochastic_d": 55.5, "roc_12": 4.2,
            "bollinger_percent_b": 0.72, "atr_14": 2.9, "volatility_annualized_30d": 0.17, "max_drawdown": -0.12,
            "adx_14": 31.0, "plus_di": 28.0, "minus_di": 14.0, "supertrend_10_3": 145.0, "obv": 1250000.0,
            "volume_ratio_20": 1.35,
        },
        "support_resistance": {
            "nearest_support": 148.0, "nearest_resistance": None, "support_distance_percent": 2.887139,
            "resistance_distance_percent": None,
        },
        "expected": {
            "score": 87.5,
            "signal": "STRONG_BUY",
            "subscores": {
                "trend_score": 100.0, "momentum_score": 100.0, "volatility_score": 100.0, "volume_score": 100.0,
                "support_resistance_score": 75.0, "risk_penalty": 0.0,
            },
            "risk_level": "LOW",
            "confidence": "HIGH",
            "reason_messages": [
                "Prezzo sopra SMA50",
                "Prezzo sopra SMA200",
                "SMA50 sopra SMA200",
                "ADX conferma trend rialzista",
                "Prezzo sopra Supertrend",
                "RSI in zona sana",
                "MACD positivo",
                "Stochastic favorevole senza eccessi",
                "ROC 12 positivo",
                "Volatilita bassa",
                "Max drawdown contenuto",
                "Volume conferma il movimento",
                "Prezzo vicino a supporto",
            ],
        },
    },
    {
        "name": "trend_ribassista",
        "risk_level": "medium",
        "latest_close": 78.6,
        "indicators": {
            "close": 78.6, "sma_20": 80.2, "sma_50": 85.3, "sma_200": 92.1, "rsi_14": 28.0, "macd_line": -1.8,
            "macd_signal": -1.2, "macd_histogram": -0.6, "stochastic_k": 22.0, "stochastic_d": 25.0, "roc_12": -6.5,
            "bollinger_percent_b": 0.15, "atr_14": 2.4, "volatility_annualized_30d": 0.32, "max_drawdown": -0.28,
            "adx_14": 29.0, "plus_di": 12.0, "minus_di": 27.0, "supertrend_10_3": 83.0, "obv": -850000.0,
            "volume_ratio_20": 0.68,
        },
        "support_resistance": {
            "nearest_support": None, "nearest_resistance": 81.0, "support_distance_percent": None,
            "resistance_distance_percent": 3.053435,
        },
        "expected": {
            "score": 25.9,
            "signal": "SELL",
            "subscores": {
                "trend_score": 0.0, "momentum_score": 30.0, "volatility_score": 64.0, "volume_score": 63.0,
                "support_resistance_score": 40.0, "risk_penalty": 15.0,
            },
            "risk_level": "MEDIUM",
            "confidence": "HIGH",
            "reason_messages": [
                "Prezzo sotto SMA50",
                "Prezzo sotto SMA200",
                "SMA50 sotto SMA200",
                "ADX conferma pressione ribassista",
                "Prezzo sotto Supertrend",
                "RSI in ipervenduto",
                "MACD sotto il segnale",
                "ROC 12 negativo",
                "Volatilita moderata",
                "Max drawdown medio",
                "Volume sotto media",
            ],
        },
    },
    {
        "name": "laterale_rsi_70",
        "risk_level": "medium",
        "latest_close": 101.2,
        "indicators": {
            "close": 101.2, "sma_20": 100.9, "sma_50": 100.6, "sma_200": 100.9, "rsi_14": 70.0, "macd_line": 0.12,
            "macd_signal": 0.15, "macd_histogram": -0.03, "stochastic_k": 88.0, "stochastic_d": 84.0, "roc_12": 0.0,
            "bollinger_percent_b": 0.81, "atr_14": 1.1, "volatility_annualized_30d": 0.14, "max_drawdown": -0.09,
            "adx_14": 14.0, "plus_di": 18.0, "minus_di": 17.0, "supertrend_10_3": 99.5, "obv": 0.0,
            "volume_ratio_20": 1.0,
        },
        "support_resistance": {
            "nearest_support": 99.0, "nearest_resistance": 106.0, "support_distance_percent": 2.173913,
            "resistance_distance_percent": 4.743083,
        },
        "expected": {
            "score": 59.5,
            "signal": "HOLD",
            "subscores": {
                "trend_score": 70.0, "momentum_score": 34.0, "volatility_score": 100.0, "volume_score": 100.0,
                "support_resistance_score": 65.0, "risk_penalty": 15.0,
            },
            "risk_level": "LOW",
            "confidence": "HIGH",
            "reason_messages": [
                "Prezzo sopra SMA50",
                "Prezzo sopra SMA200",
                "SMA50 sotto SMA200",
                "ADX indica trend poco direzionale",
                "Prezzo sopra Supertrend",
                "RSI in zona di attenzione",
                "MACD sotto il segnale",
                "Stochastic in area tirata",
                "ROC 12 negativo",
                "Volatilita bassa",
                "Max drawdown contenuto",
                "Volume conferma il movimento",
                "Prezzo vicino a supporto",
            ],
        },
    },
    {
        "name": "volatilita_alta_drawdown_040",
        "risk_level": "high",
        "latest_close": 45.3,
        "indicators": {
            "close": 45.3, "sma_20": 46.5, "sma_50": 48.0, "sma_200": 41.2, "rsi_14": 47.0, "macd_line": 0.4,
            "macd_signal": 0.1, "macd_histogram": 0.3, "stochastic_k": 45.0, "stochastic_d": 50.0, "roc_12": 2.1,
            "bollinger_percent_b": 0.38, "atr_14": 2.8, "volatility_annualized_30d": 0.58, "max_drawdown": -0.4,
            "adx_14": 26.0, "plus_di": 21.0, "minus_di": 21.0, "supertrend_10_3": 47.0, "obv": -1.0,
            "volume_ratio_20": 2.9,
        },
        "support_resistance": {
            "nearest_support": 44.1, "nearest_resistance": None, "support_distance_percent": 2.649007,
            "resistance_distance_percent": None,
        },
        "expected": {
            "score": 48.4,
            "signal": "REDUCE",
            "subscores": {
                "trend_score": 50.0, "momentum_score": 92.0, "volatility_score": 24.0, "volume_score": 73.0,
                "support_resistance_score": 75.0, "risk_penalty": 80.0,
            },
            "risk_level": "HIGH",
            "confidence": "MEDIUM",
            "reason_messages": [
                "Prezzo sotto SMA50",
                "Prezzo sopra SMA200",
                "SMA50 sopra SMA200",
                "ADX indica trend poco direzionale",
                "Prezzo sotto Supertrend",
                "RSI in zona sana",
                "MACD positivo",
                "ROC 12 positivo",
                "Volatilita elevata penalizza il punteggio",
                "Max drawdown elevato",
                "Volume molto sopra media",
                "Prezzo vicino a supporto",
            ],
        },
    },
    {
        "name": "dati_parziali_senza_sma200",
        "risk_level": "high",
        "latest_close": 64.8,
        "indicators": {
            "close": 64.8, "sma_20": 63.0, "sma_50": 61.7, "rsi_14": 61.0, "macd_line": 0.9, "macd_signal": 0.7,
            "macd_histogram": 0.2, "stochastic_k": 70.0, "stochastic_d": 72.0, "roc_12": 3.0,
            "bollinger_percent_b": 0.66, "atr_14": 1.2, "volatility_annualized_30d": 0.16, "max_drawdown": -0.1,
            "adx_14": 22.0, "plus_di": 24.0, "minus_di": 15.0, "supertrend_10_3": 62.0, "obv": 0.0,
        },
        "support_resistance": {
            "nearest_support": 63.5, "nearest_resistance": 69.0, "support_distance_percent": 2.006173,
            "resistance_distance_percent": 6.481481,
        },
        "expected": {
            "score": 62.4,
            "signal": "HOLD",
            "subscores": {
                "trend_score": 48.0, "momentum_score": 92.0, "volatility_score": 100.0, "volume_score": 65.0,
                "support_resistance_score": 65.0, "risk_penalty": 30.0,
            },
            "risk_level": "MEDIUM",
            "confidence": "MEDIUM",
            "reason_messages": [
                "Prezzo sopra SMA50",
                "SMA200 non disponibile",
                "ADX indica trend poco direzionale",
                "Prezzo sopra Supertrend",
                "RSI in zona sana",
                "MACD positivo",
                "ROC 12 positivo",
                "Volatilita bassa",
                "Max drawdown contenuto",
                "Prezzo vicino a supporto",
            ],
        },
    },
    {
        "name": "vicino_a_resistenza",
        "risk_level": "very_high",
        "latest_close": 210.0,
        "indicators": {
            "close": 210.0, "sma_20": 206.0, "sma_50": 200.0, "sma_200": 180.0, "rsi_14": 74.0, "macd_line": 3.0,
            "macd_signal": 2.0, "macd_histogram": 1.0, "stochastic_k": 79.9, "stochastic_d": 70.0, "roc_12": 3.3,
            "bollinger_percent_b": 0.93, "atr_14": 4.0, "volatility_annualized_30d": 0.22, "max_drawdown": -0.47,
            "adx_14": 24.9, "plus_di": 30.0, "minus_di": 12.0, "supertrend_10_3": 205.0, "obv": 10.0,
            "volume_ratio_20": 2.5,
        },
        "support_resistance": {
            "nearest_support": None, "nearest_resistance": 212.5, "support_distance_percent": None,
            "resistance_distance_percent": 1.190476,
        },
        "expected": {
            "score": 58.95,
            "signal": "HOLD",
            "subscores": {
                "trend_score": 90.0, "momentum_score": 73.0, "volatility_score": 60.0, "volume_score": 100.0,
                "support_resistance_score": 25.0, "risk_penalty": 78.0,
            },
            "risk_level": "HIGH",
            "confidence": "HIGH",
            "reason_messages": [
                "Prezzo sopra SMA50",
                "Prezzo sopra SMA200",
                "SMA50 sopra SMA200",
                "ADX indica trend poco direzionale",
                "Prezzo sopra Supertrend",
                "RSI in ipercomprato",
                "MACD positivo",
                "Stochastic favorevole senza eccessi",
                "ROC 12 positivo",
                "Volatilita moderata",
                "Max drawdown elevato",
                "Volume conferma il movimento",
                "Prezzo vicino a resistenza riduce il potenziale",
            ],
        },
    },
]


def _row_from_legacy(case: dict) -> dict:
    indicators = case["indicators"]
    row = dict(indicators)
    row["close_adj"] = case["latest_close"]
    row["max_drawdown_252"] = indicators.get("max_drawdown")
    row["obv_ratio_20"] = None if indicators.get("obv") is None else (1.0 if indicators["obv"] >= 0 else -1.0)
    row["volatility_30d"] = indicators.get("volatility_annualized_30d")
    row["nearest_support"] = case["support_resistance"]["nearest_support"]
    row["nearest_resistance"] = case["support_resistance"]["nearest_resistance"]
    row["support_distance_pct"] = case["support_resistance"]["support_distance_percent"]
    row["resistance_distance_pct"] = case["support_resistance"]["resistance_distance_percent"]
    return row


@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_score_v1_reproduces_legacy_formula_on_identical_inputs(case: dict) -> None:
    result = explain(_row_from_legacy(case), case["risk_level"])
    assert result["score"] == case["expected"]["score"]
    assert result["signal"] == case["expected"]["signal"]
    assert result["subscores"] == case["expected"]["subscores"]
    assert result["confidence"] == case["expected"]["confidence"]
    assert result["risk_level"] == case["expected"]["risk_level"]
    assert [reason["message"] for reason in result["reasons"]] == case["expected"]["reason_messages"]


def test_score_frame_matches_explain_row_by_row() -> None:
    features = compute_features(synthetic_bars(400, 2), "D")
    scored = score_frame(features, "medium")
    for index in (260, 300, 399):
        assert explain(features.iloc[index].to_dict(), "medium")["score"] == scored.loc[index, "score"]
    assert not scored.loc[:250, "warmup_complete"].any()
    assert scored.loc[260:, "warmup_complete"].all()


def test_weekly_bar_exists_only_after_period_end() -> None:
    daily = synthetic_bars(30, 1)  # lunedi 2018-01-01
    weekly = resample_bars(daily, "W", as_of=date(2018, 1, 12))
    assert list(weekly["date"]) == ["2018-01-07"]
    first_week = daily.iloc[:5]
    row = weekly.iloc[0]
    assert row["open"] == first_week["open"].iloc[0]
    assert row["high"] == first_week["high"].max()
    assert row["low"] == first_week["low"].min()
    assert row["close"] == first_week["close"].iloc[-1]
    assert row["volume"] == first_week["volume"].sum()


def test_monthly_bar_uses_calendar_month_end_and_crypto_weekends() -> None:
    daily = synthetic_bars(70, 4, start="2024-01-01", freq="D")
    monthly = resample_bars(daily, "M", as_of=date(2024, 3, 10))
    assert list(monthly["date"]) == ["2024-01-31", "2024-02-29"]
    weekly = resample_bars(daily, "W", as_of=date(2024, 1, 7))
    assert weekly.iloc[0]["close"] == daily.loc[daily["date"] == "2024-01-07", "close"].iloc[0]
