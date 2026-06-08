from __future__ import annotations

import pytest

from backend.app.services.common import (
    SCORE_BUY,
    SCORE_HOLD,
    SCORE_REDUCE,
    SCORE_STRONG_BUY,
    clamp,
    round_safe,
    signal_from_score,
)
from backend.app.services.risk_engine import RiskEngine

# ----------------------------- common.signal_from_score -----------------------------


@pytest.mark.parametrize(
    "score, expected",
    [
        (95.0, "STRONG_BUY"),
        (SCORE_STRONG_BUY, "STRONG_BUY"),
        (SCORE_STRONG_BUY - 0.01, "BUY"),
        (SCORE_BUY, "BUY"),
        (SCORE_BUY - 0.01, "HOLD"),
        (SCORE_HOLD, "HOLD"),
        (SCORE_HOLD - 0.01, "REDUCE"),
        (SCORE_REDUCE, "REDUCE"),
        (SCORE_REDUCE - 0.01, "SELL"),
        (0.0, "SELL"),
    ],
)
def test_signal_from_score_boundaries(score: float, expected: str) -> None:
    assert signal_from_score(score) == expected


# ----------------------------- common.round_safe -----------------------------


def test_round_safe_none_returns_zero() -> None:
    assert round_safe(None) == 0.0


def test_round_safe_non_finite_returns_zero() -> None:
    assert round_safe(float("inf")) == 0.0
    assert round_safe(float("-inf")) == 0.0
    assert round_safe(float("nan")) == 0.0


def test_round_safe_default_digits() -> None:
    assert round_safe(1.123456789) == 1.123457


def test_round_safe_custom_digits() -> None:
    assert round_safe(1.2345, 2) == 1.23


def test_round_safe_accepts_int() -> None:
    result = round_safe(7)
    assert result == 7.0
    assert isinstance(result, float)


# ----------------------------- common.clamp -----------------------------


def test_clamp_above_max() -> None:
    assert clamp(150.0) == 100.0


def test_clamp_below_min() -> None:
    assert clamp(-5.0) == 0.0


def test_clamp_within_range() -> None:
    assert clamp(42.0) == 42.0


def test_clamp_custom_bounds() -> None:
    assert clamp(5.0, 0.0, 10.0) == 5.0
    assert clamp(20.0, 0.0, 10.0) == 10.0


# ----------------------------- RiskEngine.evaluate_portfolio -----------------------------


def _settings(**overrides: float) -> dict[str, float]:
    base = {
        "max_single_asset_weight": 25.0,
        "max_asset_class_weight": 50.0,
        "crypto_max_weight": 15.0,
        "min_cash_weight": 2.0,
        "max_cash_weight": 35.0,
    }
    base.update(overrides)
    return base


def _codes(warnings: list[dict[str, str]]) -> set[str]:
    return {w["code"] for w in warnings}


def test_risk_no_warnings_when_total_value_zero() -> None:
    engine = RiskEngine()
    warnings = engine.evaluate_portfolio(
        cash=0.0,
        total_value=0.0,
        positions=[{"symbol": "AAPL", "weight_percent": 99.0}],
        allocation_by_asset_type={"stock": 99.0},
        settings=_settings(),
    )
    assert warnings == []


def test_risk_single_asset_concentration() -> None:
    engine = RiskEngine()
    warnings = engine.evaluate_portfolio(
        cash=10_000.0,
        total_value=100_000.0,
        positions=[{"symbol": "AAPL", "weight_percent": 30.0, "technical_signal": "BUY"}],
        allocation_by_asset_type={"stock": 30.0},
        settings=_settings(),
    )
    assert "SINGLE_ASSET_CONCENTRATION" in _codes(warnings)


def test_risk_asset_class_concentration() -> None:
    engine = RiskEngine()
    warnings = engine.evaluate_portfolio(
        cash=10_000.0,
        total_value=100_000.0,
        positions=[{"symbol": "AAPL", "weight_percent": 20.0, "technical_signal": "BUY"}],
        allocation_by_asset_type={"stock": 60.0},
        settings=_settings(),
    )
    assert "ASSET_CLASS_CONCENTRATION" in _codes(warnings)


def test_risk_crypto_overweight() -> None:
    engine = RiskEngine()
    warnings = engine.evaluate_portfolio(
        cash=10_000.0,
        total_value=100_000.0,
        positions=[{"symbol": "BTC", "weight_percent": 20.0, "technical_signal": "BUY"}],
        allocation_by_asset_type={"crypto": 20.0},
        settings=_settings(),
    )
    assert "CRYPTO_OVERWEIGHT" in _codes(warnings)


def test_risk_low_cash_warning() -> None:
    engine = RiskEngine()
    warnings = engine.evaluate_portfolio(
        cash=500.0,
        total_value=100_000.0,
        positions=[{"symbol": "AAPL", "weight_percent": 10.0, "technical_signal": "BUY"}],
        allocation_by_asset_type={"stock": 10.0},
        settings=_settings(),
    )
    assert "LOW_CASH" in _codes(warnings)


def test_risk_high_cash_info() -> None:
    engine = RiskEngine()
    warnings = engine.evaluate_portfolio(
        cash=50_000.0,
        total_value=100_000.0,
        positions=[{"symbol": "AAPL", "weight_percent": 10.0, "technical_signal": "BUY"}],
        allocation_by_asset_type={"stock": 10.0},
        settings=_settings(),
    )
    assert "HIGH_CASH" in _codes(warnings)


def test_risk_top_three_concentration() -> None:
    engine = RiskEngine()
    positions = [
        {"symbol": "A", "weight_percent": 24.0, "technical_signal": "BUY"},
        {"symbol": "B", "weight_percent": 24.0, "technical_signal": "BUY"},
        {"symbol": "C", "weight_percent": 24.0, "technical_signal": "BUY"},
        {"symbol": "D", "weight_percent": 5.0, "technical_signal": "BUY"},
    ]
    warnings = engine.evaluate_portfolio(
        cash=10_000.0,
        total_value=100_000.0,
        positions=positions,
        allocation_by_asset_type={"stock": 77.0},
        settings=_settings(max_single_asset_weight=30.0, max_asset_class_weight=90.0),
    )
    assert "TOP_THREE_CONCENTRATION" in _codes(warnings)


def test_risk_weak_signal_overweight() -> None:
    engine = RiskEngine()
    warnings = engine.evaluate_portfolio(
        cash=10_000.0,
        total_value=100_000.0,
        positions=[{"symbol": "TSLA", "weight_percent": 18.0, "technical_signal": "SELL"}],
        allocation_by_asset_type={"stock": 18.0},
        settings=_settings(),
    )
    assert "WEAK_SIGNAL_OVERWEIGHT" in _codes(warnings)


# ----------------------------- RiskEngine.final_recommendation -----------------------------


def test_final_recommendation_blocks_when_single_asset_too_concentrated() -> None:
    engine = RiskEngine()
    action, _ = engine.final_recommendation(
        technical_signal="BUY",
        technical_score=80.0,
        portfolio_weight=30.0,
        asset_type="stock",
        risk_level="medium",
        settings=_settings(),
        asset_class_weight=30.0,
    )
    assert action == "BLOCK_BUY_TOO_CONCENTRATED"


def test_final_recommendation_blocks_high_risk_without_strong_signal() -> None:
    engine = RiskEngine()
    action, _ = engine.final_recommendation(
        technical_signal="HOLD",
        technical_score=60.0,
        portfolio_weight=5.0,
        asset_type="crypto",
        risk_level="very_high",
        settings=_settings(),
        asset_class_weight=5.0,
    )
    assert action == "BLOCK_BUY_HIGH_RISK"


def test_final_recommendation_allows_buy_when_under_limits() -> None:
    engine = RiskEngine()
    action, _ = engine.final_recommendation(
        technical_signal="BUY",
        technical_score=75.0,
        portfolio_weight=5.0,
        asset_type="stock",
        risk_level="medium",
        settings=_settings(),
        asset_class_weight=10.0,
    )
    assert action == "BUY_ALLOWED"


def test_final_recommendation_sell_signal_passes_through() -> None:
    engine = RiskEngine()
    action, _ = engine.final_recommendation(
        technical_signal="SELL",
        technical_score=30.0,
        portfolio_weight=5.0,
        asset_type="stock",
        risk_level="low",
        settings=_settings(),
        asset_class_weight=10.0,
    )
    assert action == "SELL"
