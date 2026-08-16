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
