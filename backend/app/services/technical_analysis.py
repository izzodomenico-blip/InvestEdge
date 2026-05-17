from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


def _safe_float(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return round(number, digits)


def _safe_bool(value: Any) -> bool:
    return bool(value) if value is not None and not pd.isna(value) else False


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


@dataclass
class TechnicalAnalysisService:
    """Advanced technical analysis engine built with pandas and numpy."""

    def _prepare_frame(self, prices: pd.DataFrame) -> pd.DataFrame:
        if prices is None or prices.empty:
            return pd.DataFrame()

        frame = prices.copy()
        if "date" not in frame.columns:
            frame["date"] = pd.date_range(end=pd.Timestamp.today().normalize(), periods=len(frame))
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")

        for column in ["open", "high", "low", "close", "adjusted_close", "volume"]:
            if column not in frame.columns:
                frame[column] = frame["close"] if "close" in frame.columns else np.nan
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = frame.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        frame["open"] = frame["open"].fillna(frame["close"])
        frame["high"] = frame["high"].fillna(frame[["open", "close"]].max(axis=1))
        frame["low"] = frame["low"].fillna(frame[["open", "close"]].min(axis=1))
        frame["adjusted_close"] = frame["adjusted_close"].fillna(frame["close"])
        frame["volume"] = frame["volume"].fillna(0)
        return frame

    def enrich_price_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        frame = self._prepare_frame(prices)
        if frame.empty:
            return frame

        close = frame["close"].astype(float)
        high = frame["high"].astype(float)
        low = frame["low"].astype(float)
        volume = frame["volume"].astype(float)

        for window in [10, 20, 50, 100, 200]:
            frame[f"sma_{window}"] = close.rolling(window=window, min_periods=window).mean()

        for span in [12, 26, 50, 200]:
            frame[f"ema_{span}"] = close.ewm(span=span, adjust=False, min_periods=1).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14, min_periods=14).mean()
        relative_strength = gain / loss.replace(0, np.nan)
        frame["rsi_14"] = 100 - (100 / (1 + relative_strength))
        frame.loc[(loss == 0) & (gain > 0), "rsi_14"] = 100
        frame.loc[(gain == 0) & (loss > 0), "rsi_14"] = 0

        frame["macd_line"] = frame["ema_12"] - frame["ema_26"]
        frame["macd_signal"] = frame["macd_line"].ewm(span=9, adjust=False, min_periods=1).mean()
        frame["macd_histogram"] = frame["macd_line"] - frame["macd_signal"]

        lowest_14 = low.rolling(window=14, min_periods=14).min()
        highest_14 = high.rolling(window=14, min_periods=14).max()
        frame["stochastic_k"] = _safe_divide((close - lowest_14) * 100, highest_14 - lowest_14)
        frame["stochastic_d"] = frame["stochastic_k"].rolling(window=3, min_periods=3).mean()

        typical_price = (high + low + close) / 3
        tp_sma_20 = typical_price.rolling(window=20, min_periods=20).mean()
        mean_deviation = typical_price.rolling(window=20, min_periods=20).apply(
            lambda values: float(np.mean(np.abs(values - np.mean(values)))),
            raw=True,
        )
        frame["cci_20"] = _safe_divide(typical_price - tp_sma_20, 0.015 * mean_deviation)
        frame["roc_12"] = close.pct_change(periods=12) * 100

        bb_middle = frame["sma_20"]
        bb_std = close.rolling(window=20, min_periods=20).std()
        frame["bollinger_middle"] = bb_middle
        frame["bollinger_upper"] = bb_middle + (2 * bb_std)
        frame["bollinger_lower"] = bb_middle - (2 * bb_std)
        frame["bollinger_bandwidth"] = _safe_divide(frame["bollinger_upper"] - frame["bollinger_lower"], bb_middle)
        frame["bollinger_percent_b"] = _safe_divide(close - frame["bollinger_lower"], frame["bollinger_upper"] - frame["bollinger_lower"])

        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        frame["atr_14"] = true_range.rolling(window=14, min_periods=14).mean()

        returns = close.pct_change()
        frame["volatility_annualized_30d"] = returns.rolling(window=30, min_periods=30).std() * np.sqrt(252)
        running_max = close.cummax()
        frame["drawdown"] = (close / running_max) - 1
        frame["max_drawdown"] = frame["drawdown"].cummin()

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index)
        atr_wilder = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        plus_di = 100 * _safe_divide(plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean(), atr_wilder)
        minus_di = 100 * _safe_divide(minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean(), atr_wilder)
        dx = 100 * _safe_divide((plus_di - minus_di).abs(), plus_di + minus_di)
        frame["plus_di"] = plus_di
        frame["minus_di"] = minus_di
        frame["adx_14"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

        frame["supertrend_10_3"] = self._calculate_supertrend(high, low, close, period=10, multiplier=3)

        tenkan_high = high.rolling(window=9, min_periods=9).max()
        tenkan_low = low.rolling(window=9, min_periods=9).min()
        kijun_high = high.rolling(window=26, min_periods=26).max()
        kijun_low = low.rolling(window=26, min_periods=26).min()
        span_b_high = high.rolling(window=52, min_periods=52).max()
        span_b_low = low.rolling(window=52, min_periods=52).min()
        frame["tenkan_sen"] = (tenkan_high + tenkan_low) / 2
        frame["kijun_sen"] = (kijun_high + kijun_low) / 2
        frame["senkou_span_a"] = ((frame["tenkan_sen"] + frame["kijun_sen"]) / 2).shift(26)
        frame["senkou_span_b"] = ((span_b_high + span_b_low) / 2).shift(26)
        frame["chikou_span"] = close.shift(-26)

        direction = np.sign(close.diff()).fillna(0)
        frame["obv"] = (direction * volume).cumsum()
        frame["volume_sma_20"] = volume.rolling(window=20, min_periods=20).mean()
        frame["volume_ratio_20"] = _safe_divide(volume, frame["volume_sma_20"])

        frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
        return frame

    def _calculate_supertrend(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int,
        multiplier: float,
    ) -> pd.Series:
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.rolling(window=period, min_periods=period).mean()
        hl2 = (high + low) / 2
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)

        final_upper = upper_band.copy()
        final_lower = lower_band.copy()
        supertrend = pd.Series(np.nan, index=close.index, dtype=float)

        for index in range(1, len(close)):
            if pd.isna(atr.iloc[index]):
                continue

            previous_index = index - 1
            if pd.notna(final_upper.iloc[previous_index]) and (
                upper_band.iloc[index] > final_upper.iloc[previous_index]
                and close.iloc[previous_index] <= final_upper.iloc[previous_index]
            ):
                final_upper.iloc[index] = final_upper.iloc[previous_index]

            if pd.notna(final_lower.iloc[previous_index]) and (
                lower_band.iloc[index] < final_lower.iloc[previous_index]
                and close.iloc[previous_index] >= final_lower.iloc[previous_index]
            ):
                final_lower.iloc[index] = final_lower.iloc[previous_index]

            previous_supertrend = supertrend.iloc[previous_index]
            if pd.isna(previous_supertrend):
                supertrend.iloc[index] = final_lower.iloc[index] if close.iloc[index] >= hl2.iloc[index] else final_upper.iloc[index]
            elif previous_supertrend == final_upper.iloc[previous_index]:
                supertrend.iloc[index] = final_lower.iloc[index] if close.iloc[index] > final_upper.iloc[index] else final_upper.iloc[index]
            else:
                supertrend.iloc[index] = final_upper.iloc[index] if close.iloc[index] < final_lower.iloc[index] else final_lower.iloc[index]

        return supertrend

    def detect_support_resistance(self, prices: pd.DataFrame) -> dict[str, float | None]:
        frame = self._prepare_frame(prices)
        if len(frame) < 5:
            return {
                "nearest_support": None,
                "nearest_resistance": None,
                "support_distance_percent": None,
                "resistance_distance_percent": None,
            }

        latest_close = float(frame["close"].iloc[-1])
        highs = frame["high"].tail(180).reset_index(drop=True)
        lows = frame["low"].tail(180).reset_index(drop=True)
        pivot_highs: list[float] = []
        pivot_lows: list[float] = []

        for index in range(2, len(highs) - 2):
            if highs.iloc[index] == highs.iloc[index - 2 : index + 3].max():
                pivot_highs.append(float(highs.iloc[index]))
            if lows.iloc[index] == lows.iloc[index - 2 : index + 3].min():
                pivot_lows.append(float(lows.iloc[index]))

        supports = [value for value in pivot_lows if value <= latest_close]
        resistances = [value for value in pivot_highs if value >= latest_close]
        nearest_support = max(supports) if supports else None
        nearest_resistance = min(resistances) if resistances else None

        support_distance = ((latest_close - nearest_support) / latest_close) * 100 if nearest_support and latest_close else None
        resistance_distance = ((nearest_resistance - latest_close) / latest_close) * 100 if nearest_resistance and latest_close else None

        return {
            "nearest_support": _safe_float(nearest_support),
            "nearest_resistance": _safe_float(nearest_resistance),
            "support_distance_percent": _safe_float(support_distance),
            "resistance_distance_percent": _safe_float(resistance_distance),
        }

    def calculate_indicators(self, prices: pd.DataFrame) -> dict[str, float]:
        enriched = self.enrich_price_history(prices)
        if enriched.empty:
            return {}

        latest = enriched.iloc[-1]
        fields = [
            "sma_10",
            "sma_20",
            "sma_50",
            "sma_100",
            "sma_200",
            "ema_12",
            "ema_26",
            "ema_50",
            "ema_200",
            "rsi_14",
            "macd_line",
            "macd_signal",
            "macd_histogram",
            "stochastic_k",
            "stochastic_d",
            "cci_20",
            "roc_12",
            "bollinger_upper",
            "bollinger_middle",
            "bollinger_lower",
            "bollinger_bandwidth",
            "bollinger_percent_b",
            "atr_14",
            "volatility_annualized_30d",
            "max_drawdown",
            "adx_14",
            "plus_di",
            "minus_di",
            "supertrend_10_3",
            "tenkan_sen",
            "kijun_sen",
            "senkou_span_a",
            "senkou_span_b",
            "chikou_span",
            "obv",
            "volume_sma_20",
            "volume_ratio_20",
        ]

        result: dict[str, float] = {"close": float(latest["close"])}
        for field in fields:
            value = _safe_float(latest.get(field))
            if value is not None:
                result[field] = value
        return result

    def calculate_full_technical_analysis(self, price_history: pd.DataFrame) -> dict[str, Any]:
        enriched = self.enrich_price_history(price_history)
        if enriched.empty:
            return {
                "latest_close": None,
                "indicators": {},
                "conditions": {},
                "support_resistance": self.detect_support_resistance(enriched),
                "trend_summary": "Dati insufficienti per valutare il trend.",
                "momentum_summary": "Dati insufficienti per valutare il momentum.",
                "volatility_summary": "Dati insufficienti per valutare la volatilita.",
                "volume_summary": "Dati insufficienti per valutare il volume.",
                "overall_technical_bias": "NEUTRAL",
            }

        latest = enriched.iloc[-1]
        previous = enriched.iloc[-2] if len(enriched) > 1 else latest
        indicators = self.calculate_indicators(enriched)
        support_resistance = self.detect_support_resistance(enriched)
        close = _safe_float(latest.get("close"))
        sma_50 = _safe_float(latest.get("sma_50"))
        sma_200 = _safe_float(latest.get("sma_200"))
        previous_sma_50 = _safe_float(previous.get("sma_50"))
        previous_sma_200 = _safe_float(previous.get("sma_200"))
        rsi = _safe_float(latest.get("rsi_14"))
        macd = _safe_float(latest.get("macd_line"))
        macd_signal = _safe_float(latest.get("macd_signal"))
        volatility = _safe_float(latest.get("volatility_annualized_30d"))

        conditions = {
            "golden_cross": _safe_bool(
                sma_50 is not None
                and sma_200 is not None
                and previous_sma_50 is not None
                and previous_sma_200 is not None
                and previous_sma_50 <= previous_sma_200
                and sma_50 > sma_200
            ),
            "death_cross": _safe_bool(
                sma_50 is not None
                and sma_200 is not None
                and previous_sma_50 is not None
                and previous_sma_200 is not None
                and previous_sma_50 >= previous_sma_200
                and sma_50 < sma_200
            ),
            "price_above_sma50": _safe_bool(close is not None and sma_50 is not None and close > sma_50),
            "price_above_sma200": _safe_bool(close is not None and sma_200 is not None and close > sma_200),
            "bullish_macd": _safe_bool(macd is not None and macd_signal is not None and macd > macd_signal),
            "bearish_macd": _safe_bool(macd is not None and macd_signal is not None and macd < macd_signal),
            "rsi_overbought": _safe_bool(rsi is not None and rsi >= 70),
            "rsi_oversold": _safe_bool(rsi is not None and rsi <= 30),
            "high_volatility": _safe_bool(volatility is not None and volatility >= 0.45),
            "near_support": _safe_bool(
                support_resistance["support_distance_percent"] is not None
                and support_resistance["support_distance_percent"] <= 3
            ),
            "near_resistance": _safe_bool(
                support_resistance["resistance_distance_percent"] is not None
                and support_resistance["resistance_distance_percent"] <= 3
            ),
        }

        trend_summary = self._trend_summary(conditions, indicators)
        momentum_summary = self._momentum_summary(indicators, conditions)
        volatility_summary = self._volatility_summary(indicators, conditions)
        volume_summary = self._volume_summary(indicators)
        overall_bias = self._overall_bias(conditions, indicators)

        return {
            "latest_close": close,
            "indicators": indicators,
            "conditions": conditions,
            "support_resistance": support_resistance,
            "trend_summary": trend_summary,
            "momentum_summary": momentum_summary,
            "volatility_summary": volatility_summary,
            "volume_summary": volume_summary,
            "overall_technical_bias": overall_bias,
        }

    def _trend_summary(self, conditions: dict[str, bool], indicators: dict[str, float]) -> str:
        if conditions.get("price_above_sma50") and conditions.get("price_above_sma200"):
            return "Trend positivo: prezzo sopra SMA50 e SMA200."
        if not conditions.get("price_above_sma50") and not conditions.get("price_above_sma200"):
            return "Trend debole: prezzo sotto le principali medie."
        if indicators.get("adx_14", 0) >= 25:
            return "Trend direzionale presente secondo ADX."
        return "Trend misto o in fase laterale."

    def _momentum_summary(self, indicators: dict[str, float], conditions: dict[str, bool]) -> str:
        rsi = indicators.get("rsi_14")
        if conditions.get("bullish_macd") and rsi is not None and 40 <= rsi <= 65:
            return "Momentum costruttivo: MACD positivo e RSI in zona sana."
        if conditions.get("rsi_overbought"):
            return "Momentum forte ma RSI in ipercomprato."
        if conditions.get("rsi_oversold"):
            return "Momentum debole ma RSI in ipervenduto."
        if conditions.get("bearish_macd"):
            return "Momentum fragile: MACD sotto il segnale."
        return "Momentum neutrale."

    def _volatility_summary(self, indicators: dict[str, float], conditions: dict[str, bool]) -> str:
        volatility = indicators.get("volatility_annualized_30d")
        if conditions.get("high_volatility"):
            return f"Volatilita elevata ({volatility * 100:.1f}%)." if volatility is not None else "Volatilita elevata."
        if volatility is not None:
            return f"Volatilita annualizzata 30 giorni pari a {volatility * 100:.1f}%."
        return "Volatilita non disponibile."

    def _volume_summary(self, indicators: dict[str, float]) -> str:
        ratio = indicators.get("volume_ratio_20")
        if ratio is None:
            return "Volume non disponibile."
        if ratio >= 1.5:
            return "Volume sopra la media, possibile partecipazione elevata."
        if ratio <= 0.7:
            return "Volume sotto la media, movimento meno confermato."
        return "Volume in linea con la media recente."

    def _overall_bias(self, conditions: dict[str, bool], indicators: dict[str, float]) -> str:
        score = 0
        score += 1 if conditions.get("price_above_sma50") else -1
        score += 1 if conditions.get("price_above_sma200") else -1
        score += 1 if conditions.get("bullish_macd") else -1 if conditions.get("bearish_macd") else 0
        score += -1 if conditions.get("high_volatility") else 0
        score += 1 if conditions.get("near_support") else 0
        score += -1 if conditions.get("near_resistance") else 0
        if indicators.get("adx_14", 0) >= 25 and score > 0:
            score += 1
        if score >= 3:
            return "BULLISH"
        if score <= -3:
            return "BEARISH"
        return "NEUTRAL"
