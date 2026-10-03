from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.lab.features import (
    FEATURE_COLUMNS_V1,
    FEATURE_WINDOWS,
    NULLABLE_AFTER_WARMUP,
    compute_features,
    truncated_ewm_mean,
)
from tests.lab_fixtures import synthetic_bars


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_feature_value_does_not_change_when_future_bars_are_added(seed: int) -> None:
    bars = synthetic_bars(720, seed)
    full = compute_features(bars, "D").set_index("date")
    for cut in (300, 512, 719):
        partial = compute_features(bars.iloc[: cut + 1].reset_index(drop=True), "D").set_index("date")
        pd.testing.assert_frame_equal(
            partial[list(FEATURE_COLUMNS_V1)],
            full.loc[partial.index, list(FEATURE_COLUMNS_V1)],
            check_exact=False, rtol=1e-9, atol=1e-12,
        )


@pytest.mark.parametrize("seed", [7, 11])
def test_feature_value_depends_only_on_its_declared_window(seed: int) -> None:
    bars = synthetic_bars(720, seed)
    full = compute_features(bars, "D")
    row = 700
    for column in FEATURE_COLUMNS_V1:
        window = FEATURE_WINDOWS[column]
        start = row - window + 1
        trimmed = compute_features(bars.iloc[start : row + 1].reset_index(drop=True), "D")
        expected = full.loc[row, column]
        actual = trimmed.iloc[-1][column]
        if column not in NULLABLE_AFTER_WARMUP:
            assert np.isfinite(actual), f"{column}: warm-up oltre la finestra dichiarata {window}"
        if np.isnan(expected):
            assert np.isnan(actual), column
        else:
            assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12), column


def test_feature_is_nan_before_warmup() -> None:
    features = compute_features(synthetic_bars(300, 3), "D")
    for column in FEATURE_COLUMNS_V1:
        window = FEATURE_WINDOWS[column]
        if window > 1:
            assert features[column].iloc[: window - 1].isna().all(), column


def test_chikou_span_is_not_a_feature() -> None:
    assert "chikou_span" not in FEATURE_COLUMNS_V1
    assert "chikou_span" not in compute_features(synthetic_bars(260, 1), "D").columns


def _classic_wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).to_numpy()
    loss = (-delta.clip(upper=0)).to_numpy()
    avg_gain = np.full(len(close), np.nan)
    avg_loss = np.full(len(close), np.nan)
    avg_gain[period] = gain[1 : period + 1].mean()
    avg_loss[period] = loss[1 : period + 1].mean()
    for index in range(period + 1, len(close)):
        avg_gain[index] = (avg_gain[index - 1] * (period - 1) + gain[index]) / period
        avg_loss[index] = (avg_loss[index - 1] * (period - 1) + loss[index]) / period
    return pd.Series(100 - 100 / (1 + avg_gain / avg_loss), index=close.index)


def test_truncated_wilder_rsi_matches_classic_after_warmup() -> None:
    bars = synthetic_bars(1200, 5)
    features = compute_features(bars, "D")
    classic = _classic_wilder_rsi(bars["close"])
    assert (features["rsi_14"] - classic).iloc[400:].abs().max() < 0.1


def test_truncated_ewm_mean_uses_exactly_length_bars() -> None:
    values = np.arange(1.0, 11.0)
    result = truncated_ewm_mean(values, alpha=0.5, length=3)
    expected_last = (10 * 1.0 + 9 * 0.5 + 8 * 0.25) / 1.75
    assert np.isnan(result[:2]).all()
    assert result[-1] == pytest.approx(expected_last)


def test_obv_ratio_is_bounded_and_prices_are_adjusted() -> None:
    bars = synthetic_bars(400, 9)
    features = compute_features(bars, "D")
    ratio = features["obv_ratio_20"].dropna()
    assert ((ratio >= -1) & (ratio <= 1)).all()
    halved = bars.assign(adjusted_close=bars["close"] / 2)
    adjusted = compute_features(halved, "D")
    assert adjusted["sma_20"].iloc[-1] == pytest.approx(features["sma_20"].iloc[-1] / 2)
    assert adjusted["price_vs_sma50"].iloc[-1] == pytest.approx(features["price_vs_sma50"].iloc[-1])
