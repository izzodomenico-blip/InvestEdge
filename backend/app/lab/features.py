"""Pipeline di feature causale a finestra limitata `features-v1` (spec SP1 §5.2-§5.3).

- Il valore alla riga i dipende solo dalle barre [i - W + 1, i], con W = FEATURE_WINDOWS[colonna];
  ogni riduzione lavora sulla propria finestra (sliding window), mai su somme cumulate dall'inizio serie.
- Prima di W barre il valore e NaN (warm-up).
- I ricorsivi (EMA, Wilder, Supertrend) sono troncati a L barre.
- Prezzi rettificati: O, H, L, C x adjusted_close / close; volume non rettificato.
- Divisioni per zero (serie piatte) danno NaN, come gli indicatori attuali.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from backend.app.lab.contracts import PERIODS_PER_YEAR, Timeframe

FEATURE_COLUMNS_V1: tuple[str, ...] = (
    "sma_20", "sma_50", "sma_200", "price_vs_sma50", "price_vs_sma200", "sma50_vs_sma200",
    "rsi_14", "macd_line", "macd_signal", "macd_histogram", "macd_line_pct", "macd_histogram_pct",
    "stochastic_k", "stochastic_d", "roc_12", "close_return_1d", "close_return_5d", "close_return_20d",
    "volatility_30d", "atr_14", "atr_14_pct", "plus_di", "minus_di", "adx_14", "supertrend_10_3",
    "bollinger_percent_b", "max_drawdown_252", "drawdown_60", "volume_ratio_20", "obv_ratio_20",
    "nearest_support", "nearest_resistance", "support_distance_pct", "resistance_distance_pct",
)

# Finestra di dipendenza W per colonna (spec §5.3). Le colonne `_pct` del MACD si attivano
# insieme al segnale (W 139) anche se `macd_line` e disponibile da 104 barre.
FEATURE_WINDOWS: Mapping[str, int] = MappingProxyType({
    "sma_20": 20, "sma_50": 50, "sma_200": 200,
    "price_vs_sma50": 50, "price_vs_sma200": 200, "sma50_vs_sma200": 200,
    "rsi_14": 101,
    "macd_line": 104, "macd_signal": 139, "macd_histogram": 139,
    "macd_line_pct": 139, "macd_histogram_pct": 139,
    "stochastic_k": 14, "stochastic_d": 16, "roc_12": 13,
    "close_return_1d": 2, "close_return_5d": 6, "close_return_20d": 21,
    "volatility_30d": 31, "atr_14": 15, "atr_14_pct": 15,
    "plus_di": 101, "minus_di": 101, "adx_14": 200, "supertrend_10_3": 110,
    "bollinger_percent_b": 20, "max_drawdown_252": 252, "drawdown_60": 60,
    "volume_ratio_20": 20, "obv_ratio_20": 21,
    "nearest_support": 180, "nearest_resistance": 180,
    "support_distance_pct": 180, "resistance_distance_pct": 180,
})

# Supporti e resistenze possono mancare anche dopo il warm-up (nessun pivot confermato).
NULLABLE_AFTER_WARMUP: frozenset[str] = frozenset(
    {"nearest_support", "nearest_resistance", "support_distance_pct", "resistance_distance_pct"}
)
MAX_FEATURE_WINDOW: int = 252

_RECURSIVE_LENGTH = 100  # L di Wilder (RSI, DI, ADX) e del Supertrend
_WILDER_ALPHA = 1 / 14
_SUPERTREND_ATR_PERIOD = 10
_SUPERTREND_MULTIPLIER = 3
_PIVOT_LOOKBACK = 180
_PIVOT_HALF_WIDTH = 2


def _rolling(values: np.ndarray, window: int, reducer: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """Applica `reducer` alle sole finestre complete di `window` valori; NaN altrove."""
    result = np.full(values.shape[0], np.nan)
    if values.shape[0] >= window:
        result[window - 1 :] = reducer(sliding_window_view(values, window))
    return result


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    return _rolling(values, window, lambda windows: windows.mean(axis=1))


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    return _rolling(values, window, lambda windows: windows.sum(axis=1))


def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
    return _rolling(values, window, lambda windows: windows.std(axis=1, ddof=1))


def _rolling_max(values: np.ndarray, window: int) -> np.ndarray:
    return _rolling(values, window, lambda windows: windows.max(axis=1))


def _rolling_min(values: np.ndarray, window: int) -> np.ndarray:
    return _rolling(values, window, lambda windows: windows.min(axis=1))


def _window_max_drawdown(windows: np.ndarray) -> np.ndarray:
    running_peak = np.maximum.accumulate(windows, axis=1)
    return (windows / running_peak - 1).min(axis=1)


def _lag(values: np.ndarray, periods: int) -> np.ndarray:
    result = np.full(values.shape[0], np.nan)
    if values.shape[0] > periods:
        result[periods:] = values[: values.shape[0] - periods]
    return result


def _divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denominator == 0, np.nan, numerator / denominator)


def truncated_ewm_mean(values: np.ndarray, alpha: float, length: int) -> np.ndarray:
    """Media esponenziale troncata: pesi (1 - alpha)^k, k = 0..length-1 (k = 0 sul valore corrente), normalizzati.

    NaN finche mancano `length` valori o se la finestra contiene un NaN.
    """
    if not 0 < alpha <= 1 or length < 1:
        raise ValueError("truncated_ewm_mean richiede 0 < alpha <= 1 e length >= 1.")
    weights = (1 - alpha) ** np.arange(length - 1, -1, -1, dtype=float)
    weights = weights / weights.sum()
    return _rolling(np.asarray(values, dtype=float), length, lambda windows: (windows * weights).sum(axis=1))


def _supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray, true_range: np.ndarray) -> np.ndarray:
    """Supertrend 10/3 con la macchina a stati attuale, ricalcolata da zero sulle ultime L barre di ogni riga."""
    size = close.shape[0]
    result = np.full(size, np.nan)
    first_row = _SUPERTREND_ATR_PERIOD + _RECURSIVE_LENGTH - 1
    if size <= first_row:
        return result
    atr = _rolling_mean(true_range, _SUPERTREND_ATR_PERIOD)
    hl2 = (high + low) / 2
    upper_band = hl2 + _SUPERTREND_MULTIPLIER * atr
    lower_band = hl2 - _SUPERTREND_MULTIPLIER * atr

    start = np.arange(first_row, size) - (_RECURSIVE_LENGTH - 1)
    final_upper = upper_band[start]
    final_lower = lower_band[start]
    bearish = ~(close[start] >= hl2[start])
    for step in range(1, _RECURSIVE_LENGTH):
        index = start + step
        previous_close = close[index - 1]
        final_upper = np.where(
            (upper_band[index] > final_upper) & (previous_close <= final_upper), final_upper, upper_band[index]
        )
        final_lower = np.where(
            (lower_band[index] < final_lower) & (previous_close >= final_lower), final_lower, lower_band[index]
        )
        bearish = np.where(bearish, ~(close[index] > final_upper), close[index] < final_lower)
    result[first_row:] = np.where(bearish, final_upper, final_lower)
    return result


def _confirmed_pivots(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Supporto e resistenza piu vicini fra i pivot +/-2 barre delle ultime 180, confermati (indice <= i - 2)."""
    size = close.shape[0]
    support = np.full(size, np.nan)
    resistance = np.full(size, np.nan)
    width = 2 * _PIVOT_HALF_WIDTH + 1
    if size < _PIVOT_LOOKBACK:
        return support, resistance

    centers = slice(_PIVOT_HALF_WIDTH, size - _PIVOT_HALF_WIDTH)
    pivot_highs = np.full(size, np.nan)
    pivot_lows = np.full(size, np.nan)
    is_pivot_high = high[centers] == sliding_window_view(high, width).max(axis=1)
    is_pivot_low = low[centers] == sliding_window_view(low, width).min(axis=1)
    pivot_highs[centers] = np.where(is_pivot_high, high[centers], np.nan)
    pivot_lows[centers] = np.where(is_pivot_low, low[centers], np.nan)

    # Riga i: pivot candidati negli indici [i - 177, i - 2], con le loro 2 barre per lato dentro la finestra.
    span = _PIVOT_LOOKBACK - 2 * _PIVOT_HALF_WIDTH
    first_row = _PIVOT_LOOKBACK - 1
    rows = slice(_PIVOT_HALF_WIDTH, size - first_row + _PIVOT_HALF_WIDTH)
    high_windows = sliding_window_view(pivot_highs, span)[rows]
    low_windows = sliding_window_view(pivot_lows, span)[rows]
    current = close[first_row:, None]
    with np.errstate(invalid="ignore"):
        resistance[first_row:] = np.fmin.reduce(np.where(high_windows >= current, high_windows, np.nan), axis=1)
        support[first_row:] = np.fmax.reduce(np.where(low_windows <= current, low_windows, np.nan), axis=1)
    return support, resistance


def compute_features(bars: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """Feature `features-v1` di un solo segmento ordinato per data.

    Input: date (YYYY-MM-DD), open, high, low, close, adjusted_close, volume.
    Output: date, close_adj e FEATURE_COLUMNS_V1, stesso numero di righe; NaN prima del warm-up.
    """
    raw_close = bars["close"].to_numpy(dtype=float)
    factor = bars["adjusted_close"].to_numpy(dtype=float) / raw_close
    high = bars["high"].to_numpy(dtype=float) * factor
    low = bars["low"].to_numpy(dtype=float) * factor
    close = raw_close * factor
    volume = bars["volume"].to_numpy(dtype=float)

    previous_close = _lag(close, 1)
    delta = close - previous_close
    returns = _divide(close, previous_close) - 1
    true_range = np.maximum(high - low, np.maximum(np.abs(high - previous_close), np.abs(low - previous_close)))

    sma_20 = _rolling_mean(close, 20)
    sma_50 = _rolling_mean(close, 50)
    sma_200 = _rolling_mean(close, 200)

    avg_gain = truncated_ewm_mean(np.clip(delta, 0, None), _WILDER_ALPHA, _RECURSIVE_LENGTH)
    avg_loss = truncated_ewm_mean(np.clip(-delta, 0, None), _WILDER_ALPHA, _RECURSIVE_LENGTH)
    rsi_14 = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, 100 - 100 / (1 + _divide(avg_gain, avg_loss)))

    macd_line = truncated_ewm_mean(close, 2 / 13, 48) - truncated_ewm_mean(close, 2 / 27, 104)
    macd_signal = truncated_ewm_mean(macd_line, 2 / 10, 36)
    macd_histogram = macd_line - macd_signal

    lowest_14 = _rolling_min(low, 14)
    stochastic_k = _divide((close - lowest_14) * 100, _rolling_max(high, 14) - lowest_14)

    atr_14 = _rolling_mean(true_range, 14)

    up_move = high - _lag(high, 1)
    down_move = _lag(low, 1) - low
    has_move = ~(np.isnan(up_move) | np.isnan(down_move))
    plus_dm = np.where(has_move, np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), np.nan)
    minus_dm = np.where(has_move, np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), np.nan)
    atr_wilder = truncated_ewm_mean(true_range, _WILDER_ALPHA, _RECURSIVE_LENGTH)
    plus_di = 100 * _divide(truncated_ewm_mean(plus_dm, _WILDER_ALPHA, _RECURSIVE_LENGTH), atr_wilder)
    minus_di = 100 * _divide(truncated_ewm_mean(minus_dm, _WILDER_ALPHA, _RECURSIVE_LENGTH), atr_wilder)
    dx = 100 * _divide(np.abs(plus_di - minus_di), plus_di + minus_di)

    std_20 = _rolling_std(close, 20)
    bollinger_upper = sma_20 + 2 * std_20
    bollinger_lower = sma_20 - 2 * std_20

    direction = np.sign(delta)
    nearest_support, nearest_resistance = _confirmed_pivots(high, low, close)

    columns: dict[str, np.ndarray] = {
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "price_vs_sma50": _divide(close, sma_50) - 1,
        "price_vs_sma200": _divide(close, sma_200) - 1,
        "sma50_vs_sma200": _divide(sma_50, sma_200) - 1,
        "rsi_14": rsi_14,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
        "macd_line_pct": _divide(macd_line, close),
        "macd_histogram_pct": _divide(macd_histogram, close),
        "stochastic_k": stochastic_k,
        "stochastic_d": _rolling_mean(stochastic_k, 3),
        "roc_12": (_divide(close, _lag(close, 12)) - 1) * 100,
        "close_return_1d": returns,
        "close_return_5d": _divide(close, _lag(close, 5)) - 1,
        "close_return_20d": _divide(close, _lag(close, 20)) - 1,
        "volatility_30d": _rolling_std(returns, 30) * np.sqrt(PERIODS_PER_YEAR[timeframe]),
        "atr_14": atr_14,
        "atr_14_pct": _divide(atr_14, close),
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx_14": truncated_ewm_mean(dx, _WILDER_ALPHA, _RECURSIVE_LENGTH),
        "supertrend_10_3": _supertrend(high, low, close, true_range),
        "bollinger_percent_b": _divide(close - bollinger_lower, bollinger_upper - bollinger_lower),
        "max_drawdown_252": _rolling(close, 252, _window_max_drawdown),
        "drawdown_60": _divide(close, _rolling_max(close, 60)) - 1,
        "volume_ratio_20": _divide(volume, _rolling_mean(volume, 20)),
        "obv_ratio_20": _divide(_rolling_sum(direction * volume, 20), _rolling_sum(volume, 20)),
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "support_distance_pct": _divide(close - nearest_support, close) * 100,
        "resistance_distance_pct": _divide(nearest_resistance - close, close) * 100,
    }

    frame = pd.DataFrame({"date": bars["date"].to_numpy(), "close_adj": close})
    for column in FEATURE_COLUMNS_V1:
        values = np.array(columns[column], dtype=float)
        values[: FEATURE_WINDOWS[column] - 1] = np.nan
        frame[column] = values
    return frame
