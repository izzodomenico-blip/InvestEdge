from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from backend.app.lab.contracts import DataMode
from backend.app.lab.feature_store import FeatureStore
from backend.app.lab.series import load_series

FEATURE_COLUMNS = [
    "close_return_1d",
    "close_return_5d",
    "close_return_20d",
    "volatility_30d",
    "rsi_14",
    "macd_line_pct",
    "macd_histogram_pct",
    "price_vs_sma50",
    "price_vs_sma200",
    "sma50_vs_sma200",
    "atr_14_pct",
    "adx_14",
    "plus_di",
    "minus_di",
    "bollinger_percent_b",
    "max_drawdown_252",
    "drawdown_60",
    "volume_ratio_20",
    "obv_ratio_20",
    "stochastic_k",
    "stochastic_d",
    "roc_12",
    "support_distance_pct",
    "resistance_distance_pct",
    "score",
    "trend_score",
    "momentum_score",
    "volatility_score",
    "volume_score",
    "support_resistance_score",
    "risk_penalty",
]
_TARGET_COLUMNS = ["symbol", "date", "target", "target_date", "future_return"]
_DATASET_COLUMNS = [*_TARGET_COLUMNS, *FEATURE_COLUMNS]


def _normalized_temporal_dates(dataset: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    missing_columns = {"date", "target_date"}.difference(dataset.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Dataset ML privo delle colonne temporali richieste: {missing}.")

    feature_dates = pd.to_datetime(dataset["date"], errors="coerce", format="mixed", utc=True).dt.normalize()
    target_dates = pd.to_datetime(dataset["target_date"], errors="coerce", format="mixed", utc=True).dt.normalize()
    if bool(feature_dates.isna().any() or target_dates.isna().any()):
        raise ValueError("Dataset ML con date o target_date non valide.")
    return feature_dates, target_dates


def validate_split_no_lookahead(train: pd.DataFrame, test: pd.DataFrame) -> bool:
    if train.empty or test.empty:
        raise ValueError("Split train/test insufficiente dopo la purga temporale.")

    _, train_target_dates = _normalized_temporal_dates(train)
    test_feature_dates, _ = _normalized_temporal_dates(test)
    if train_target_dates.max() >= test_feature_dates.min():
        raise ValueError("Look-ahead bias rilevato: i target del train non precedono l'inizio del test.")
    return True


@dataclass
class MLDatasetService:
    feature_store: FeatureStore = field(default_factory=FeatureStore)

    @staticmethod
    def _asset_id(connection: sqlite3.Connection, symbol: str) -> int | None:
        rows = connection.execute("SELECT id FROM assets WHERE UPPER(symbol) = UPPER(?)", (symbol,)).fetchall()
        if len(rows) > 1:
            raise ValueError("Simbolo ambiguo: seleziona un asset univoco.")
        return int(rows[0][0]) if rows else None

    def build_ml_dataset(
        self, connection: sqlite3.Connection, symbols: list[str], horizon_days: int, target_type: str,
        benchmark_symbol: str = "SPY", data_mode: DataMode = "REAL",
    ) -> pd.DataFrame:
        moment = datetime.now(UTC)
        frames: list[pd.DataFrame] = []
        benchmark = None
        if target_type == "OUTPERFORM_BENCHMARK":
            benchmark = self.build_targets(connection, benchmark_symbol, horizon_days, data_mode=data_mode).rename(
                columns={"future_return": "benchmark_return", "target_date": "benchmark_target_date"})
            if benchmark.empty:
                return pd.DataFrame(columns=_DATASET_COLUMNS)
        for symbol in dict.fromkeys(item.strip().upper() for item in symbols):
            asset_id = self._asset_id(connection, symbol)
            if asset_id is None:
                continue
            self.feature_store.refresh_asset(connection, asset_id, data_mode, moment)
            features = self.feature_store.read_frame(connection, [asset_id], "D", data_mode, complete_only=True)
            targets = self.build_targets(connection, symbol, horizon_days, target_type, data_mode=data_mode)
            if features.empty or targets.empty:
                continue
            merged = targets.merge(features[["date", *FEATURE_COLUMNS]], on="date", how="inner")
            if benchmark is not None:
                merged = merged.merge(benchmark[["date", "benchmark_return", "benchmark_target_date"]],
                                      on="date", how="inner")
                merged["target"] = (merged["future_return"] > merged["benchmark_return"]).astype(int)
                # L'etichetta e osservabile solo quando entrambi gli endpoint sono disponibili.
                merged["target_date"] = merged[["target_date", "benchmark_target_date"]].max(axis=1)
            frames.append(merged[_DATASET_COLUMNS])
        if not frames:
            return pd.DataFrame(columns=_DATASET_COLUMNS)
        dataset = pd.concat(frames, ignore_index=True).replace([np.inf, -np.inf], np.nan)
        # Null della pipeline (es. nessun pivot) restano null: l'imputer e fit solo sul train.
        dataset = dataset.dropna(subset=["target", "future_return", "target_date"])
        dataset = dataset[dataset["target_date"] <= moment.date().isoformat()].copy()
        dataset["target"] = dataset["target"].astype(int)
        dataset = dataset.sort_values(["date", "symbol"]).reset_index(drop=True)
        self.validate_no_lookahead(dataset)
        return dataset

    def build_features_for_symbol(
        self, connection: sqlite3.Connection, symbol: str, data_mode: DataMode, as_of_date: str | None = None,
    ) -> dict[str, float]:
        asset_id = self._asset_id(connection, symbol)
        if asset_id is None:
            return {}
        moment = datetime.now(UTC)
        cutoff = min(as_of_date or moment.date().isoformat(), moment.date().isoformat())
        series = load_series(connection, asset_id, data_mode)
        if series is None:
            return {}
        dates = [str(day) for segment in series.segments for day in segment.bars["date"] if str(day) <= cutoff]
        if not dates:
            return {}
        self.feature_store.refresh_asset(connection, asset_id, data_mode, moment)
        # Non recuperare una riga completa vecchia quando l'ultimo segmento e ancora in warm-up.
        latest_date = max(dates)
        frame = self.feature_store.read_frame(connection, [asset_id], "D", data_mode,
                                              start=latest_date, end=latest_date, complete_only=True)
        if frame.empty:
            return {}
        latest = frame.iloc[-1]
        return {column: float(latest[column]) for column in FEATURE_COLUMNS if np.isfinite(latest[column])}

    def build_targets(
        self, connection: sqlite3.Connection, symbol: str, horizon_days: int,
        target_type: str = "POSITIVE_RETURN", data_mode: DataMode = "REAL",
    ) -> pd.DataFrame:
        if horizon_days < 1:
            raise ValueError("L'orizzonte ML deve essere positivo.")
        asset_id = self._asset_id(connection, symbol)
        series = load_series(connection, asset_id, data_mode) if asset_id is not None else None
        frames = []
        if series is not None:
            for segment in series.segments:
                frame = segment.bars[["date", "adjusted_close"]].copy().reset_index(drop=True)
                if len(frame) <= horizon_days:
                    continue
                frame["symbol"] = symbol.upper()
                close = frame["adjusted_close"]
                frame["target_date"] = frame["date"].shift(-horizon_days)
                frame["future_return"] = close.shift(-horizon_days) / close - 1
                if target_type == "DRAWDOWN_RISK":
                    future = pd.concat([close.shift(-offset) for offset in range(1, horizon_days + 1)], axis=1)
                    valid = (np.isfinite(future).all(axis=1) & (future > 0).all(axis=1)
                             & np.isfinite(close) & (close > 0))
                    frame["target"] = (future.min(axis=1) <= close * .92).astype(float).where(valid)
                else:
                    valid = np.isfinite(close) & (close > 0) & np.isfinite(close.shift(-horizon_days)) & (close.shift(-horizon_days) > 0)
                    frame["target"] = (frame["future_return"] > 0).astype(float).where(valid)
                frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
                    subset=["target", "target_date", "future_return"])
                frames.append(frame[_TARGET_COLUMNS])
        if not frames:
            return pd.DataFrame(columns=_TARGET_COLUMNS)
        result = pd.concat(frames, ignore_index=True)
        result["target"] = result["target"].astype(int)
        return result

    def split_train_test_time_based(
        self,
        dataset: pd.DataFrame,
        test_size_time_percent: float = 25,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if dataset.empty:
            return dataset.copy(), dataset.copy()
        feature_dates, target_dates = _normalized_temporal_dates(dataset)
        sorted_dates = sorted(feature_dates.unique())
        split_index = max(1, int(len(sorted_dates) * (1 - (test_size_time_percent / 100))))
        split_index = min(split_index, len(sorted_dates) - 1)
        split_date = sorted_dates[split_index]
        train = dataset[(feature_dates < split_date) & (target_dates < split_date)].copy()
        test = dataset[feature_dates >= split_date].copy()
        return train.reset_index(drop=True), test.reset_index(drop=True)

    def walk_forward_folds(
        self,
        dataset: pd.DataFrame,
        folds: int = 4,
    ) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        """Genera fold walk-forward a finestra espansiva (train passato, test futuro)."""
        if dataset.empty:
            return []
        feature_dates, target_dates = _normalized_temporal_dates(dataset)
        dates = sorted(feature_dates.unique())
        if len(dates) < (folds + 1) * 2:
            return []
        result: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        step = len(dates) // (folds + 1)
        for fold in range(1, folds + 1):
            train_end = step * fold
            test_end = step * (fold + 1) if fold < folds else len(dates)
            train_dates = set(dates[:train_end])
            test_dates = set(dates[train_end:test_end])
            test_start = dates[train_end]
            train = dataset[feature_dates.isin(train_dates) & (target_dates < test_start)]
            test = dataset[feature_dates.isin(test_dates)]
            if not train.empty and not test.empty:
                result.append((train.reset_index(drop=True), test.reset_index(drop=True)))
        return result

    def validate_no_lookahead(self, dataset: pd.DataFrame) -> bool:
        if dataset.empty or "target_date" not in dataset.columns:
            return True
        feature_dates, target_dates = _normalized_temporal_dates(dataset)
        if bool((target_dates <= feature_dates).any()):
            raise ValueError("Look-ahead bias rilevato: target_date non successiva alla feature date.")
        return True
