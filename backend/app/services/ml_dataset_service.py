from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.app.services.technical_analysis import TechnicalAnalysisService


FEATURE_COLUMNS = [
    "close_return_1d",
    "close_return_5d",
    "close_return_20d",
    "volatility_30d",
    "rsi_14",
    "macd_line",
    "macd_histogram",
    "price_vs_sma50",
    "price_vs_sma200",
    "sma50_vs_sma200",
    "atr_14",
    "adx_14",
    "bollinger_percent_b",
    "max_drawdown_recent",
    "volume_ratio",
    "technical_score",
    "trend_score",
    "momentum_score",
    "volatility_score",
    "volume_score",
    "support_resistance_score",
    "risk_penalty",
    "news_sentiment_score_7d",
    "news_positive_count_7d",
    "news_negative_count_7d",
    "news_high_impact_count_7d",
    "portfolio_weight",
    "current_recommendation_encoded",
]


@dataclass
class MLDatasetService:
    technical_analysis: TechnicalAnalysisService = field(default_factory=TechnicalAnalysisService)

    def build_ml_dataset(
        self,
        connection: sqlite3.Connection,
        symbols: list[str],
        horizon_days: int,
        target_type: str,
        benchmark_symbol: str = "SPY",
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        benchmark_targets = pd.DataFrame()
        if target_type == "OUTPERFORM_BENCHMARK":
            benchmark_targets = self.build_targets(connection, benchmark_symbol, horizon_days, "POSITIVE_RETURN")
            benchmark_targets = benchmark_targets[["date", "future_return"]].rename(
                columns={"future_return": "benchmark_future_return"}
            )

        for symbol in [item.upper() for item in symbols]:
            price_frame = self._price_frame(connection, symbol)
            if price_frame.empty:
                continue
            features = self._feature_frame(connection, symbol, price_frame, include_portfolio=False)
            targets = self.build_targets(connection, symbol, horizon_days, target_type)
            if targets.empty:
                continue
            merged = features.merge(targets, on=["symbol", "date"], how="inner")
            if target_type == "OUTPERFORM_BENCHMARK":
                merged = merged.merge(benchmark_targets, on="date", how="inner")
                merged["target"] = (merged["future_return"] > merged["benchmark_future_return"]).astype(int)
            frames.append(merged)

        if not frames:
            return pd.DataFrame(columns=["symbol", "date", "target", *FEATURE_COLUMNS])

        dataset = pd.concat(frames, ignore_index=True)
        dataset = dataset.replace([np.inf, -np.inf], np.nan)
        dataset = dataset.dropna(subset=["target", *FEATURE_COLUMNS])
        dataset["target"] = dataset["target"].astype(int)
        dataset = dataset.sort_values(["date", "symbol"]).reset_index(drop=True)
        self.validate_no_lookahead(dataset)
        return dataset

    def build_features_for_symbol(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        as_of_date: str | None = None,
    ) -> dict[str, float]:
        frame = self._price_frame(connection, symbol)
        if frame.empty:
            return {}
        if as_of_date:
            frame = frame[frame["date"] <= as_of_date].copy()
        if frame.empty:
            return {}
        features = self._feature_frame(connection, symbol.upper(), frame, include_portfolio=True)
        if features.empty:
            return {}
        latest = features.iloc[-1]
        return {column: float(latest[column]) for column in FEATURE_COLUMNS if column in latest and pd.notna(latest[column])}

    def build_targets(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        horizon_days: int,
        target_type: str = "POSITIVE_RETURN",
    ) -> pd.DataFrame:
        frame = self._price_frame(connection, symbol)
        if frame.empty or len(frame) <= horizon_days:
            return pd.DataFrame(columns=["symbol", "date", "target", "target_date", "future_return"])

        frame = frame[["symbol", "date", "close"]].copy().reset_index(drop=True)
        frame["future_close"] = frame["close"].shift(-horizon_days)
        frame["target_date"] = frame["date"].shift(-horizon_days)
        frame["future_return"] = (frame["future_close"] / frame["close"]) - 1

        if target_type == "DRAWDOWN_RISK":
            drawdown_targets: list[int | None] = []
            drawdown_values: list[float | None] = []
            for index, row in frame.iterrows():
                future_window = frame.iloc[index + 1 : index + horizon_days + 1]
                if len(future_window) < horizon_days:
                    drawdown_targets.append(None)
                    drawdown_values.append(None)
                    continue
                worst_return = (float(future_window["close"].min()) / float(row["close"])) - 1
                drawdown_values.append(worst_return)
                drawdown_targets.append(1 if worst_return <= -0.08 else 0)
            frame["target"] = drawdown_targets
            frame["future_drawdown"] = drawdown_values
        else:
            frame["target"] = (frame["future_return"] > 0).astype(float)

        frame = frame.dropna(subset=["target", "target_date", "future_return"])
        frame["target"] = frame["target"].astype(int)
        return frame[["symbol", "date", "target", "target_date", "future_return"]]

    def split_train_test_time_based(
        self,
        dataset: pd.DataFrame,
        test_size_time_percent: float = 25,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if dataset.empty:
            return dataset.copy(), dataset.copy()
        sorted_dates = sorted(dataset["date"].dropna().unique())
        split_index = max(1, int(len(sorted_dates) * (1 - (test_size_time_percent / 100))))
        split_index = min(split_index, len(sorted_dates) - 1)
        split_date = sorted_dates[split_index]
        train = dataset[dataset["date"] < split_date].copy()
        test = dataset[dataset["date"] >= split_date].copy()
        return train.reset_index(drop=True), test.reset_index(drop=True)

    def validate_no_lookahead(self, dataset: pd.DataFrame) -> bool:
        if dataset.empty:
            return True
        feature_dates = pd.to_datetime(dataset["date"], errors="coerce")
        target_dates = pd.to_datetime(dataset["target_date"], errors="coerce")
        if bool((target_dates <= feature_dates).any()):
            raise ValueError("Look-ahead bias rilevato: target_date non successiva alla feature date.")
        return True

    def _price_frame(self, connection: sqlite3.Connection, symbol: str) -> pd.DataFrame:
        rows = connection.execute(
            """
            SELECT a.symbol, ph.date, ph.open, ph.high, ph.low, ph.close, ph.adjusted_close, ph.volume
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE UPPER(a.symbol) = UPPER(?)
            ORDER BY ph.date ASC, ph.is_real_data DESC, ph.id ASC
            """,
            (symbol,),
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame([dict(row) for row in rows]).drop_duplicates(subset=["date"], keep="last")
        for column in ["open", "high", "low", "close", "adjusted_close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        return frame.dropna(subset=["date", "close"]).reset_index(drop=True)

    def _feature_frame(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        price_frame: pd.DataFrame,
        include_portfolio: bool,
    ) -> pd.DataFrame:
        enriched = self.technical_analysis.enrich_price_history(price_frame)
        if enriched.empty:
            return pd.DataFrame(columns=["symbol", "date", *FEATURE_COLUMNS])

        frame = enriched.copy()
        close = pd.to_numeric(frame["close"], errors="coerce")
        frame["symbol"] = symbol.upper()
        frame["close_return_1d"] = close.pct_change(1)
        frame["close_return_5d"] = close.pct_change(5)
        frame["close_return_20d"] = close.pct_change(20)
        frame["volatility_30d"] = frame.get("volatility_annualized_30d")
        frame["price_vs_sma50"] = (close / pd.to_numeric(frame.get("sma_50"), errors="coerce")) - 1
        frame["price_vs_sma200"] = (close / pd.to_numeric(frame.get("sma_200"), errors="coerce")) - 1
        frame["sma50_vs_sma200"] = (
            pd.to_numeric(frame.get("sma_50"), errors="coerce") / pd.to_numeric(frame.get("sma_200"), errors="coerce")
        ) - 1
        frame["max_drawdown_recent"] = close / close.rolling(window=60, min_periods=20).max() - 1
        frame["volume_ratio"] = frame.get("volume_ratio_20")
        frame["trend_score"] = self._trend_score(frame)
        frame["momentum_score"] = self._momentum_score(frame)
        frame["volatility_score"] = self._volatility_score(frame)
        frame["volume_score"] = self._volume_score(frame)
        frame["support_resistance_score"] = self._support_resistance_score(frame)
        frame["risk_penalty"] = self._risk_penalty(frame)
        frame["technical_score"] = (
            frame["trend_score"] * 0.30
            + frame["momentum_score"] * 0.25
            + frame["volatility_score"] * 0.15
            + frame["volume_score"] * 0.10
            + frame["support_resistance_score"] * 0.10
            - frame["risk_penalty"] * 0.10
        ).clip(0, 100)

        news_features = [self._news_features(connection, symbol, date_value) for date_value in frame["date"]]
        news_frame = pd.DataFrame(news_features)
        frame = pd.concat([frame.reset_index(drop=True), news_frame.reset_index(drop=True)], axis=1)

        if include_portfolio:
            portfolio_weight, recommendation = self._portfolio_features(connection, symbol)
        else:
            portfolio_weight, recommendation = 0.0, 0.0
        frame["portfolio_weight"] = portfolio_weight
        frame["current_recommendation_encoded"] = recommendation

        keep = ["symbol", "date", *FEATURE_COLUMNS]
        result = frame[keep].copy()
        result = result.replace([np.inf, -np.inf], np.nan)
        return result

    def _trend_score(self, frame: pd.DataFrame) -> pd.Series:
        score = pd.Series(30.0, index=frame.index)
        score += (frame["price_vs_sma50"] > 0).astype(float) * 25
        score += (frame["price_vs_sma200"] > 0).astype(float) * 25
        score += (frame["sma50_vs_sma200"] > 0).astype(float) * 20
        return score.clip(0, 100)

    def _momentum_score(self, frame: pd.DataFrame) -> pd.Series:
        rsi = pd.to_numeric(frame.get("rsi_14"), errors="coerce")
        macd_histogram = pd.to_numeric(frame.get("macd_histogram"), errors="coerce")
        score = pd.Series(45.0, index=frame.index)
        score += ((rsi >= 40) & (rsi <= 65)).astype(float) * 25
        score += (macd_histogram > 0).astype(float) * 20
        score += (pd.to_numeric(frame.get("roc_12"), errors="coerce") > 0).astype(float) * 10
        score -= ((rsi > 75) | (rsi < 25)).astype(float) * 20
        return score.clip(0, 100)

    def _volatility_score(self, frame: pd.DataFrame) -> pd.Series:
        volatility = pd.to_numeric(frame.get("volatility_annualized_30d"), errors="coerce").fillna(0.3)
        drawdown = pd.to_numeric(frame.get("max_drawdown_recent"), errors="coerce").fillna(-0.2)
        score = 100 - (volatility * 100) + (drawdown * 80)
        return score.clip(0, 100)

    def _volume_score(self, frame: pd.DataFrame) -> pd.Series:
        ratio = pd.to_numeric(frame.get("volume_ratio_20"), errors="coerce").fillna(1.0)
        score = 50 + ((ratio - 1).clip(-1, 1) * 25)
        return score.clip(0, 100)

    def _support_resistance_score(self, frame: pd.DataFrame) -> pd.Series:
        percent_b = pd.to_numeric(frame.get("bollinger_percent_b"), errors="coerce").fillna(0.5)
        score = 65 - ((percent_b - 0.5).abs() * 45)
        return score.clip(0, 100)

    def _risk_penalty(self, frame: pd.DataFrame) -> pd.Series:
        volatility = pd.to_numeric(frame.get("volatility_annualized_30d"), errors="coerce").fillna(0.25)
        drawdown = pd.to_numeric(frame.get("max_drawdown_recent"), errors="coerce").fillna(-0.15).abs()
        penalty = (volatility * 55) + (drawdown * 120)
        return penalty.clip(0, 100)

    def _news_features(self, connection: sqlite3.Connection, symbol: str, as_of_date: str) -> dict[str, float]:
        row = connection.execute(
            """
            SELECT
                COALESCE(AVG(sentiment_score), 0) AS sentiment,
                SUM(CASE WHEN sentiment_label = 'POSITIVE' THEN 1 ELSE 0 END) AS positive_count,
                SUM(CASE WHEN sentiment_label = 'NEGATIVE' THEN 1 ELSE 0 END) AS negative_count,
                SUM(CASE WHEN impact_level = 'HIGH' THEN 1 ELSE 0 END) AS high_impact_count
            FROM news_items
            WHERE UPPER(COALESCE(symbol, '')) = UPPER(?)
              AND date(COALESCE(published_at, created_at)) <= date(?)
              AND date(COALESCE(published_at, created_at)) > date(?, '-7 days')
            """,
            (symbol, as_of_date, as_of_date),
        ).fetchone()
        return {
            "news_sentiment_score_7d": float(row["sentiment"] or 0.0) if row else 0.0,
            "news_positive_count_7d": float(row["positive_count"] or 0.0) if row else 0.0,
            "news_negative_count_7d": float(row["negative_count"] or 0.0) if row else 0.0,
            "news_high_impact_count_7d": float(row["high_impact_count"] or 0.0) if row else 0.0,
        }

    def _portfolio_features(self, connection: sqlite3.Connection, symbol: str) -> tuple[float, float]:
        row = connection.execute(
            """
            SELECT weight_percent
            FROM portfolio_positions
            WHERE UPPER(symbol) = UPPER(?) AND quantity > 0
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        recommendation = connection.execute(
            """
            SELECT predicted_label
            FROM ml_predictions
            WHERE UPPER(symbol) = UPPER(?)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        encoded = self._encode_recommendation(recommendation["predicted_label"] if recommendation else None)
        return (float(row["weight_percent"] or 0.0) if row else 0.0, encoded)

    def _encode_recommendation(self, value: str | None) -> float:
        if not value:
            return 0.0
        normalized = value.upper()
        if "POSITIVE" in normalized or "OUTPERFORM" in normalized:
            return 1.0
        if "DRAWDOWN" in normalized or "UNDER" in normalized or "NON_" in normalized:
            return -1.0
        return 0.0
