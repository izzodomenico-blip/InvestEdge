from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from backend.app.models import MLTrainIn
from backend.app.services.ml_dataset_service import FEATURE_COLUMNS, MLDatasetService, validate_split_no_lookahead
from backend.app.services.ml_engine import MLEngine


def _daily_dataset(*, periods: int = 40, horizon_days: int = 5) -> pd.DataFrame:
    feature_dates = pd.date_range("2026-01-01", periods=periods, freq="D")
    return pd.DataFrame(
        {
            "symbol": "TEST",
            "date": feature_dates.strftime("%Y-%m-%d"),
            "target_date": (feature_dates + pd.to_timedelta(horizon_days, unit="D")).strftime("%Y-%m-%d"),
            "target": [index % 2 for index in range(periods)],
        }
    )


def _model_dataset() -> pd.DataFrame:
    dataset = _daily_dataset()
    for index, column in enumerate(FEATURE_COLUMNS, start=1):
        dataset[column] = float(index)
    return dataset


class _LeakyDatasetService:
    def __init__(self, dataset: pd.DataFrame) -> None:
        self.dataset = dataset

    def build_ml_dataset(self, **_kwargs) -> pd.DataFrame:
        return self.dataset.copy()

    def split_train_test_time_based(
        self,
        dataset: pd.DataFrame,
        _test_size_time_percent: float,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        return dataset.iloc[:30].copy(), dataset.iloc[30:].copy()

    def walk_forward_folds(
        self,
        dataset: pd.DataFrame,
        _folds: int,
    ) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        return [
            (dataset.iloc[:8].copy(), dataset.iloc[13:21].copy()),
            (dataset.iloc[:16].copy(), dataset.iloc[16:24].copy()),
        ]


class _UnexpectedFitModel:
    def fit(self, *_args, **_kwargs) -> None:
        pytest.fail("Il fit non deve iniziare su uno split con look-ahead.")


class _EngineWithFitGuard(MLEngine):
    def _build_model(self, _model_type: str) -> _UnexpectedFitModel:
        return _UnexpectedFitModel()


class _WalkForwardModel:
    classes_ = np.array([0, 1])

    def __init__(self, engine: _WalkForwardEngine) -> None:
        self.engine = engine
        self.named_steps = {"model": self}

    def fit(self, *_args, **_kwargs) -> None:
        self.engine.fit_calls += 1
        if self.engine.fit_calls > 1:
            pytest.fail("Il secondo fit non deve iniziare su un fold con look-ahead.")

    def predict(self, x_frame: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(x_frame), dtype=int)

    def predict_proba(self, x_frame: pd.DataFrame) -> np.ndarray:
        return np.full((len(x_frame), 2), 0.5)


class _WalkForwardEngine(MLEngine):
    def __init__(self, dataset_service: _LeakyDatasetService) -> None:
        super().__init__(dataset_service=dataset_service)
        self.fit_calls = 0

    def _build_model(self, _model_type: str) -> _WalkForwardModel:
        return _WalkForwardModel(self)


def test_time_split_purges_targets_observed_during_test_period() -> None:
    service = MLDatasetService()

    train, test = service.split_train_test_time_based(_daily_dataset(), test_size_time_percent=25)

    assert not train.empty
    assert not test.empty
    assert pd.to_datetime(train["target_date"]).max() < pd.to_datetime(test["date"]).min()


def test_each_walk_forward_fold_purges_targets_observed_during_test_period() -> None:
    service = MLDatasetService()

    fold_data = service.walk_forward_folds(_daily_dataset(), folds=4)

    assert len(fold_data) == 4
    for train, test in fold_data:
        assert pd.to_datetime(train["target_date"]).max() < pd.to_datetime(test["date"]).min()


@pytest.mark.parametrize("splitter_name", ["split_train_test_time_based", "walk_forward_folds"])
@pytest.mark.parametrize("column", ["date", "target_date"])
@pytest.mark.parametrize("invalid_value", [pd.NaT, "not-a-date"])
def test_temporal_splitters_reject_invalid_dates(
    splitter_name: str,
    column: str,
    invalid_value: object,
) -> None:
    service = MLDatasetService()
    dataset = _daily_dataset()
    dataset.loc[0, column] = invalid_value

    with pytest.raises(ValueError, match="date"):
        getattr(service, splitter_name)(dataset)


def test_split_validator_rejects_target_equal_to_first_test_date() -> None:
    train = pd.DataFrame({"date": ["2026-01-01"], "target_date": ["2026-01-05"]})
    test = pd.DataFrame({"date": ["2026-01-05"], "target_date": ["2026-01-10"]})

    with pytest.raises(ValueError, match="Look-ahead"):
        validate_split_no_lookahead(train, test)


def test_split_validator_compares_normalized_days() -> None:
    train = pd.DataFrame({"date": ["2026-01-01T12:00:00Z"], "target_date": ["2026-01-05T01:00:00Z"]})
    test = pd.DataFrame({"date": ["2026-01-05T23:00:00Z"], "target_date": ["2026-01-10T00:00:00Z"]})

    with pytest.raises(ValueError, match="Look-ahead"):
        validate_split_no_lookahead(train, test)


def test_split_validator_accepts_mixed_formats_and_timezones() -> None:
    train = pd.DataFrame(
        {
            "date": ["2026-01-01", "January 2, 2026"],
            "target_date": ["2026/01/03", pd.Timestamp("2026-01-04T00:00:00+01:00")],
        }
    )
    test = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-01-06T00:00:00-05:00")],
            "target_date": ["2026-01-10"],
        }
    )

    assert validate_split_no_lookahead(train, test) is True


def test_train_model_validates_holdout_before_fit() -> None:
    dataset = _model_dataset()
    engine = _EngineWithFitGuard(dataset_service=_LeakyDatasetService(dataset))
    config = MLTrainIn(
        model_name="Leak guard",
        symbols=["TEST"],
        horizon_days=5,
        min_samples=20,
        cv_folds=2,
    )

    with sqlite3.connect(":memory:") as connection, pytest.raises(ValueError, match="Look-ahead"):
        engine.train_model(connection, config)


def test_walk_forward_validates_each_fold_before_fit() -> None:
    dataset = _model_dataset()
    engine = _WalkForwardEngine(dataset_service=_LeakyDatasetService(dataset))

    with pytest.raises(ValueError, match="Look-ahead"):
        engine._walk_forward_cv(dataset, "HIST_GRADIENT_BOOSTING", folds=2)
    assert engine.fit_calls == 1


# SP1 Task 13: regressioni offline della pipeline ML condivisa.
def _ml_asset(connection, *, real=True, symbol="MLX", n=330, seed=21, provider=None):
    from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

    row = connection.execute("SELECT id FROM assets WHERE symbol = ?", (symbol,)).fetchone()
    asset_id = int(row[0]) if row else insert_asset(connection, symbol)
    bars = synthetic_bars(n, seed=seed)
    insert_bars(connection, asset_id, bars, real=real, provider=provider)
    connection.commit()
    return asset_id, bars


def test_dataset_columns_are_pipeline_v1_only(lab_connection):
    _ml_asset(lab_connection)
    dataset = MLDatasetService().build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN")
    expected = [
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
    assert expected == FEATURE_COLUMNS
    assert not dataset.empty
    assert set(dataset.columns) == {"symbol", "date", "target", "target_date", "future_return", *FEATURE_COLUMNS}
    assert not any(c.startswith("news_") for c in dataset.columns)


def test_ml_row_equals_features_daily_row(lab_connection):
    from backend.app.lab.feature_store import FeatureStore

    asset_id, _ = _ml_asset(lab_connection)
    service = MLDatasetService()
    dataset = service.build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN")
    saved = FeatureStore().read_frame(lab_connection, [asset_id], "D", "REAL").set_index("date")
    pd.testing.assert_frame_equal(dataset.set_index("date")[FEATURE_COLUMNS], saved.loc[dataset["date"], FEATURE_COLUMNS],
                                  check_names=False)
    day = str(dataset.iloc[-1]["date"])
    features = service.build_features_for_symbol(lab_connection, "MLX", "REAL", as_of_date=day)
    assert features["score"] == saved.loc[day, "score"]
    assert features["rsi_14"] == saved.loc[day, "rsi_14"]
    from datetime import UTC, datetime

    from backend.app.lab.universe import build_universe_inputs
    from backend.app.services.signals_service import recalculate_signal

    moment = datetime(2024, 1, 1, tzinfo=UTC)
    inputs = build_universe_inputs(
        lab_connection, ["MLX"], data_mode="REAL", signal_name="score", signal_timeframe="D",
        start=str(dataset["date"].min()), end=str(saved.index.max()), now=moment,
    )
    for row in dataset.itertuples():
        assert inputs.signals.loc[row.date, asset_id] == row.score == saved.loc[row.date, "score"]
    recalculate_signal(lab_connection, asset_id, now=moment)
    latest = str(saved.index.max())
    ui_score = lab_connection.execute("SELECT score FROM signals WHERE asset_id=?", (asset_id,)).fetchone()[0]
    ml_latest = service.build_features_for_symbol(lab_connection, "MLX", "REAL", as_of_date=latest)
    assert ui_score == inputs.signals.loc[latest, asset_id] == saved.loc[latest, "score"] == ml_latest["score"]


@pytest.mark.parametrize("target_type", ["POSITIVE_RETURN", "DRAWDOWN_RISK", "OUTPERFORM_BENCHMARK"])
def test_targets_do_not_cross_segments(lab_connection, target_type):
    from tests.lab_fixtures import insert_bars, synthetic_bars

    asset_id, bars = _ml_asset(lab_connection)
    second = synthetic_bars(40, seed=23, start="2021-01-01")
    insert_bars(lab_connection, asset_id, second, real=True, provider=None)
    _ml_asset(lab_connection, symbol="SPY")
    lab_connection.commit()
    dataset = MLDatasetService().build_ml_dataset(lab_connection, ["MLX"], 5, target_type)
    assert not dataset.empty
    assert dataset["date"].max() <= bars["date"].iloc[-6]
    assert dataset["target_date"].max() <= bars["date"].iloc[-1]


def test_features_and_targets_are_isolated_by_mode(lab_connection):
    from tests.lab_fixtures import insert_bars

    asset_id, real = _ml_asset(lab_connection)
    demo = real.copy()
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        demo[col] = 20000 / real[col]
    insert_bars(lab_connection, asset_id, demo, real=False, provider="seed")
    lab_connection.commit()
    service = MLDatasetService()
    real_ds = service.build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN", data_mode="REAL")
    demo_ds = service.build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN", data_mode="DEMO")
    assert real_ds["date"].tolist() == demo_ds["date"].tolist()
    np.testing.assert_array_equal(real_ds["target"], 1 - demo_ds["target"])
    assert service.build_features_for_symbol(lab_connection, "MLX", "REAL")["score"] != (
        service.build_features_for_symbol(lab_connection, "MLX", "DEMO")["score"])
    assert service.build_features_for_symbol(lab_connection, "MISSING", "DEMO") == {}


def test_current_prediction_never_reuses_pre_split_features(lab_connection):
    from tests.lab_fixtures import insert_bars, synthetic_bars

    asset_id, bars = _ml_asset(lab_connection)
    second = synthetic_bars(30, seed=23, start="2021-01-01")
    insert_bars(lab_connection, asset_id, second, real=True, provider=None)
    lab_connection.commit()
    service = MLDatasetService()
    assert service.build_features_for_symbol(lab_connection, "MLX", "REAL") == {}
    assert service.build_features_for_symbol(lab_connection, "MLX", "REAL", bars["date"].iloc[-1])


@pytest.mark.parametrize("closes, expected", [([100, 95, 92, 110], 1), ([100, 150, 130, 140], 0),
                                             ([100, 95, 92.00001, 110], 0), ([100, 95, 91.99999, 110], 1)])
def test_drawdown_target_definition_and_exact_boundary(lab_connection, closes, expected):
    from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

    bars = synthetic_bars(4, seed=22)
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        bars[col] = closes
    asset_id = insert_asset(lab_connection, "RISK")
    insert_bars(lab_connection, asset_id, bars, real=True, provider="coingecko")
    lab_connection.commit()
    target = MLDatasetService().build_targets(lab_connection, "RISK", 3, "DRAWDOWN_RISK", data_mode="REAL")
    assert target.iloc[0]["target"] == expected
    assert target.iloc[0]["future_return"] == pytest.approx(closes[-1] / closes[0] - 1)


def test_target_uses_adjusted_close(lab_connection, monkeypatch):
    import backend.app.lab.series as series
    monkeypatch.setattr(series, "PROVIDER_ADJUSTMENT_BASIS", {"adjusted-fixture": "SPLIT"})
    from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

    bars = synthetic_bars(3, seed=22)
    for col in ["open", "high", "low", "close"]:
        bars[col] = [100, 50, 51]
    bars["adjusted_close"] = [50, 50, 51]
    asset_id = insert_asset(lab_connection, "ADJ")
    insert_bars(lab_connection, asset_id, bars, real=True, provider="adjusted-fixture")
    lab_connection.commit()
    target = MLDatasetService().build_targets(lab_connection, "ADJ", 2, data_mode="REAL")
    assert target.iloc[0]["future_return"] == pytest.approx(.02)


def test_future_changes_do_not_change_past_features(lab_connection):
    _ml_asset(lab_connection, n=370)
    service = MLDatasetService()
    before = service.build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN")
    cutoff = before.iloc[40]["date"]
    lab_connection.execute(
        "UPDATE price_history SET open=open*1.01, high=high*1.01, low=low*1.01, close=close*1.01, "
        "adjusted_close=adjusted_close*1.01 WHERE date > ?", (cutoff,))
    lab_connection.commit()
    after = service.build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN")
    pd.testing.assert_frame_equal(before[before["date"] <= cutoff][FEATURE_COLUMNS],
                                  after[after["date"] <= cutoff][FEATURE_COLUMNS])


def test_nullable_pivots_keep_training_rows_and_safe_prediction(lab_connection):
    import json

    from tests.lab_fixtures import insert_bars

    asset_id, bars = _ml_asset(lab_connection, n=330)
    lab_connection.execute("DELETE FROM price_history WHERE asset_id = ?", (asset_id,))
    values = np.linspace(100, 200, len(bars))
    for col in ["open", "high", "low", "close", "adjusted_close"]:
        bars[col] = values
    insert_bars(lab_connection, asset_id, bars, real=True, provider=None)
    lab_connection.commit()
    service = MLDatasetService()
    dataset = service.build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN")
    assert len(dataset) == 330 - 251 - 5
    assert dataset[["support_distance_pct", "resistance_distance_pct"]].isna().all().all()
    features = service.build_features_for_symbol(lab_connection, "MLX", "REAL")
    assert "support_distance_pct" not in features
    json.dumps(features, allow_nan=False)


def test_unobserved_future_targets_are_excluded(lab_connection, monkeypatch):
    from datetime import UTC, datetime

    import backend.app.services.ml_dataset_service as dataset_module

    asset_id, bars = _ml_asset(lab_connection, n=340)
    cutoff = bars["date"].iloc[325]

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(cutoff).replace(tzinfo=UTC)

    monkeypatch.setattr(dataset_module, "datetime", FrozenDatetime)
    dataset = MLDatasetService().build_ml_dataset(lab_connection, ["MLX"], 5, "POSITIVE_RETURN")
    assert not dataset.empty
    assert dataset["target_date"].max() == cutoff
    assert dataset["date"].max() == bars["date"].iloc[320]


def test_benchmark_missing_in_selected_mode_produces_no_labels(lab_connection):
    _ml_asset(lab_connection)
    _ml_asset(lab_connection, real=False, symbol="SPY")
    dataset = MLDatasetService().build_ml_dataset(lab_connection, ["MLX"], 5, "OUTPERFORM_BENCHMARK")
    assert dataset.empty


def test_benchmark_target_date_controls_label_availability(lab_connection):
    from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

    for symbol, kind, freq in [("CRYP", "crypto", "D"), ("SPY", "etf", "B")]:
        asset_id = insert_asset(lab_connection, symbol, asset_type=kind)
        insert_bars(lab_connection, asset_id, synthetic_bars(380, seed=2, freq=freq), real=True, provider=None)
    lab_connection.commit()
    service = MLDatasetService()
    dataset = service.build_ml_dataset(lab_connection, ["CRYP"], 5, "OUTPERFORM_BENCHMARK")
    benchmarks = service.build_targets(lab_connection, "SPY", 5).set_index("date")
    assets = service.build_targets(lab_connection, "CRYP", 5).set_index("date")
    for row in dataset.itertuples():
        assert row.target_date == max(benchmarks.loc[row.date, "target_date"], assets.loc[row.date, "target_date"])


@pytest.mark.parametrize("model_type", ["LOGISTIC_REGRESSION", "RANDOM_FOREST"])
def test_imputer_preserves_all_feature_columns(model_type):
    x = pd.DataFrame({column: [np.nan] if column.endswith("distance_pct") else [1.] for column in FEATURE_COLUMNS})
    model = MLEngine()._build_model(model_type)
    result = model.named_steps["imputer"].fit_transform(x)
    assert result.shape[1] == len(FEATURE_COLUMNS)


def _train_fixture(connection):
    _ml_asset(connection, n=380)
    return MLTrainIn(model_name="Shared ML", model_type="LOGISTIC_REGRESSION",
                     symbols=["MLX"], horizon_days=5, min_samples=20, cv_folds=2)


@pytest.mark.parametrize("progress", [.45, .95])
def test_cancelled_training_leaves_no_model_or_run(lab_connection, progress):
    from backend.app.config import get_settings
    from backend.app.lab.jobs import JobCancelled

    config = _train_fixture(lab_connection)
    model_dir = get_settings().database_path.parent / "ml_models"

    def cancel(value):
        if value == progress:
            if value == .95:
                assert list(model_dir.glob("*.joblib")), "Il checkpoint deve seguire la serializzazione"
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        MLEngine().train_model(lab_connection, config, checkpoint=cancel)
    assert lab_connection.execute("SELECT COUNT(*) FROM ml_models").fetchone()[0] == 0
    assert lab_connection.execute("SELECT COUNT(*) FROM ml_training_runs").fetchone()[0] == 0
    assert not model_dir.exists() or not list(model_dir.iterdir())


def test_model_dump_does_not_hold_a_database_write_lock(lab_connection, monkeypatch):
    import joblib

    from backend.app.config import get_settings

    config = _train_fixture(lab_connection)
    original = joblib.dump

    def dump(bundle, filename):
        # Simula l'altra connessione usata da cancel/progress durante lo staging.
        with sqlite3.connect(get_settings().database_path, timeout=.05) as other:
            other.execute("UPDATE assets SET name=name WHERE symbol='MLX'")
        return original(bundle, filename)

    monkeypatch.setattr(joblib, "dump", dump)
    result = MLEngine().train_model(lab_connection, config)
    assert result["model_id"] > 0


@pytest.mark.parametrize("failure", ["dump", "insert"])
def test_failed_training_rolls_back_rows_and_files(lab_connection, monkeypatch, failure):
    import joblib

    from backend.app.config import get_settings

    config = _train_fixture(lab_connection)
    engine = MLEngine()

    def fail(*_args, **_kwargs):
        raise ValueError("fixture failure")

    if failure == "dump":
        monkeypatch.setattr(joblib, "dump", fail)
    else:
        monkeypatch.setattr(engine, "_insert_model", fail)
    with pytest.raises(ValueError, match="fixture failure"):
        engine.train_model(lab_connection, config)
    assert lab_connection.execute("SELECT COUNT(*) FROM ml_models").fetchone()[0] == 0
    assert lab_connection.execute("SELECT COUNT(*) FROM ml_training_runs").fetchone()[0] == 0
    model_dir = get_settings().database_path.parent / "ml_models"
    assert not model_dir.exists() or not list(model_dir.iterdir())


def test_legacy_model_migration_is_nullable_and_idempotent(lab_connection):
    from backend.app.database import migrate_db

    lab_connection.execute("ALTER TABLE ml_models DROP COLUMN pipeline_version")
    lab_connection.execute("ALTER TABLE ml_models DROP COLUMN data_mode")
    lab_connection.execute("INSERT INTO ml_models(model_name,model_type,target_type,horizon_days) "
                           "VALUES ('Legacy','LOGISTIC_REGRESSION','POSITIVE_RETURN',5)")
    migrate_db(lab_connection)
    migrate_db(lab_connection)
    row = lab_connection.execute("SELECT pipeline_version,data_mode FROM ml_models").fetchone()
    assert tuple(row) == (None, None)


def test_prediction_missing_features_are_nan_not_zero(lab_connection, monkeypatch):
    import json

    config = _train_fixture(lab_connection)
    engine = MLEngine()
    result = engine.train_model(lab_connection, config)
    monkeypatch.setattr(engine.dataset_service, "build_features_for_symbol", lambda *_args: {"score": 42.})

    def probabilities(_model, frame):
        assert frame.columns.tolist() == FEATURE_COLUMNS
        assert pd.isna(frame.iloc[0]["support_distance_pct"])
        assert pd.isna(frame.iloc[0]["rsi_14"])
        return np.array([.6])

    monkeypatch.setattr(engine, "_positive_probabilities", probabilities)
    prediction = engine.predict_for_symbol(lab_connection, "MLX", result["model_id"])
    assert prediction["features_snapshot"] == {"score": 42.}
    json.dumps(prediction, allow_nan=False)


def test_default_real_training_universe_excludes_demo_only_assets(lab_connection):
    _ml_asset(lab_connection, real=False, symbol="AAADEMO")
    _ml_asset(lab_connection, real=True, symbol="ZZREAL")
    symbols, _ = MLEngine()._resolve_training_symbols(lab_connection, MLTrainIn(model_name="Real"))
    assert symbols == ["ZZREAL"]


@pytest.mark.parametrize("invalid", [np.inf, -np.inf, 0.])
def test_drawdown_window_with_invalid_internal_close_has_no_label(lab_connection, invalid):
    from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

    bars = synthetic_bars(3, seed=22)
    for column in ["open", "high", "low", "close", "adjusted_close"]:
        bars[column] = [100., invalid, 110.]
    asset_id = insert_asset(lab_connection, "INVALID")
    insert_bars(lab_connection, asset_id, bars, real=True, provider="coingecko")
    lab_connection.commit()
    targets = MLDatasetService().build_targets(lab_connection, "INVALID", 2, "DRAWDOWN_RISK")
    assert targets.empty
