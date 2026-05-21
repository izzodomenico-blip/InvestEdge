from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def ml_client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("ml") / "investedge_ml.db"
    tracked_env = [
        "INVESTEDGE_DB_PATH",
        "ENABLE_REAL_DATA",
        "ENABLE_REAL_NEWS",
        "ALPHA_VANTAGE_API_KEY",
        "COINGECKO_API_KEY",
        "FRED_API_KEY",
    ]
    old_env = {key: os.environ.get(key) for key in tracked_env}
    os.environ["INVESTEDGE_DB_PATH"] = str(db_path)
    os.environ["ENABLE_REAL_DATA"] = "false"
    os.environ["ENABLE_REAL_NEWS"] = "false"
    os.environ["ALPHA_VANTAGE_API_KEY"] = ""
    os.environ["COINGECKO_API_KEY"] = ""
    os.environ["FRED_API_KEY"] = ""

    from backend.app.config import get_settings

    get_settings.cache_clear()

    from backend.scripts.seed_database import seed_database

    seed_database(reset=True)

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()


@pytest.fixture()
def no_model_client(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "investedge_no_model.db"))
    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    monkeypatch.setenv("ENABLE_REAL_NEWS", "false")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    monkeypatch.setenv("FRED_API_KEY", "")

    from backend.app.config import get_settings

    get_settings.cache_clear()

    from backend.scripts.seed_database import seed_database

    seed_database(reset=True)

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


def _train_payload(model_type: str = "LOGISTIC_REGRESSION") -> dict[str, object]:
    return {
        "model_name": f"Test {model_type}",
        "model_type": model_type,
        "target_type": "POSITIVE_RETURN",
        "horizon_days": 14,
        "symbols": ["AAPL", "MSFT", "SPY", "QQQ"],
        "benchmark_symbol": "SPY",
        "test_size_time_percent": 25,
        "min_samples": 100,
    }


def test_build_dataset_without_lookahead(ml_client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.services.ml_dataset_service import FEATURE_COLUMNS, MLDatasetService

    with db_session() as connection:
        dataset = MLDatasetService().build_ml_dataset(
            connection,
            symbols=["AAPL", "MSFT"],
            horizon_days=7,
            target_type="POSITIVE_RETURN",
        )

    assert not dataset.empty
    assert {"symbol", "date", "target", "target_date", *FEATURE_COLUMNS} <= set(dataset.columns)
    assert (dataset["target_date"] > dataset["date"]).all()


def test_split_train_test_time_based(ml_client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.services.ml_dataset_service import MLDatasetService

    service = MLDatasetService()
    with db_session() as connection:
        dataset = service.build_ml_dataset(
            connection,
            symbols=["AAPL", "MSFT", "SPY"],
            horizon_days=14,
            target_type="POSITIVE_RETURN",
        )
        train, test = service.split_train_test_time_based(dataset, test_size_time_percent=25)

    assert not train.empty
    assert not test.empty
    assert train["date"].max() < test["date"].min()


def test_train_logistic_regression_with_seed_data(ml_client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.models import MLTrainIn
    from backend.app.services.ml_engine import MLEngine

    with db_session() as connection:
        result = MLEngine().train_model(connection, MLTrainIn(**_train_payload("LOGISTIC_REGRESSION")))

    assert result["model_id"] > 0
    assert result["metrics"]["samples_count"] >= 100
    assert "feature_importance" in result["metrics"]


def test_train_random_forest_with_seed_data(ml_client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.models import MLTrainIn
    from backend.app.services.ml_engine import MLEngine

    with db_session() as connection:
        result = MLEngine().train_model(connection, MLTrainIn(**_train_payload("RANDOM_FOREST")))

    assert result["model_id"] > 0
    assert result["metrics"]["samples_count"] >= 100
    assert result["metrics"]["feature_importance"]


def test_predict_with_saved_model(ml_client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.models import MLTrainIn
    from backend.app.services.ml_engine import MLEngine

    engine = MLEngine()
    with db_session() as connection:
        trained = engine.train_model(connection, MLTrainIn(**_train_payload("LOGISTIC_REGRESSION")))
        prediction = engine.predict_for_symbol(connection, "AAPL", trained["model_id"])

    assert prediction["symbol"] == "AAPL"
    assert prediction["model_id"] == trained["model_id"]
    assert prediction["confidence"] in {"LOW", "MEDIUM", "HIGH"}
    assert 0 <= prediction["probabilities"]["probability_positive"] <= 1


def test_ml_status_endpoint(no_model_client: TestClient) -> None:
    response = no_model_client.get("/ml/status")

    assert response.status_code == 200
    data = response.json()
    assert data["models_count"] == 0
    assert data["ml_ready"] is False
    assert "Nessun modello" in data["message"]


def test_ml_train_endpoint(ml_client: TestClient) -> None:
    response = ml_client.post("/ml/train", json=_train_payload("LOGISTIC_REGRESSION"))

    assert response.status_code == 200
    data = response.json()
    assert data["model_id"] > 0
    assert data["training_run"]["samples_count"] >= 100
    assert "close_return_1d" in data["features_used"]


def test_ml_models_endpoint(ml_client: TestClient) -> None:
    ml_client.post("/ml/train", json=_train_payload("RANDOM_FOREST"))
    response = ml_client.get("/ml/models")

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert {"id", "model_name", "model_type", "target_type", "metrics"} <= set(data[0])


def test_ml_predict_endpoint(ml_client: TestClient) -> None:
    train_response = ml_client.post("/ml/train", json=_train_payload("LOGISTIC_REGRESSION"))
    model_id = train_response.json()["model_id"]
    response = ml_client.post("/ml/predict/AAPL", json={"model_id": model_id})

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["model_id"] == model_id
    assert data["predicted_label"] in {"POSITIVE_RETURN", "NON_POSITIVE_RETURN"}


def test_ml_predict_without_model(no_model_client: TestClient) -> None:
    response = no_model_client.post("/ml/predict/AAPL", json={})

    assert response.status_code == 400
    assert "Nessun modello ML disponibile" in response.json()["detail"]


def test_ml_train_with_too_few_samples(ml_client: TestClient) -> None:
    payload = _train_payload("LOGISTIC_REGRESSION")
    payload["min_samples"] = 100000
    response = ml_client.post("/ml/train", json=payload)

    assert response.status_code == 400
    assert "Pochi dati" in response.json()["detail"]


def test_ml_does_not_call_real_apis(ml_client: TestClient) -> None:
    response = ml_client.get("/data/usage")

    assert response.status_code == 200
    assert all(item["calls_count"] == 0 for item in response.json())
