from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def universe_client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("universe") / "investedge_universe.db"
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


def test_universe_summary_after_seed(universe_client: TestClient) -> None:
    response = universe_client.get("/universe/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["core_count"] == 75
    assert 200 <= data["extended_count"] <= 300
    assert data["candidate_count"] >= 30
    assert data["watchlist_count"] >= 25
    assert data["priced_assets_count"] == 25


def test_import_universe_csv_endpoint(universe_client: TestClient) -> None:
    response = universe_client.post(
        "/universe/import",
        json={"file_name": "core_universe.csv", "universe_level": "CORE"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_rows"] == 75
    assert data["updated"] >= 75


def test_add_and_remove_watchlist(universe_client: TestClient) -> None:
    add_response = universe_client.post("/universe/SNOW/watchlist")
    remove_response = universe_client.delete("/universe/SNOW/watchlist")

    assert add_response.status_code == 200
    assert add_response.json()["is_watchlisted"] is True
    assert remove_response.status_code == 200
    assert remove_response.json()["is_watchlisted"] is False


def test_promote_universe_level(universe_client: TestClient) -> None:
    response = universe_client.post("/universe/SNOW/promote", json={"universe_level": "CORE"})

    assert response.status_code == 200
    assert response.json()["symbol"] == "SNOW"
    assert response.json()["universe_level"] == "CORE"


def test_refresh_candidates_are_limited(universe_client: TestClient) -> None:
    response = universe_client.get("/universe/refresh-candidates?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert 1 <= len(data) <= 5
    assert data[0]["refresh_priority"] >= data[-1]["refresh_priority"]


def test_refresh_all_uses_limited_universe_candidates(universe_client: TestClient) -> None:
    response = universe_client.post("/data/refresh-all")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["requested"] <= 10
    assert all(item["used_fallback"] for item in data["results"])


def test_ml_training_defaults_to_core_universe(universe_client: TestClient) -> None:
    response = universe_client.post(
        "/ml/train",
        json={
            "model_name": "Core default logistic",
            "model_type": "LOGISTIC_REGRESSION",
            "target_type": "POSITIVE_RETURN",
            "horizon_days": 14,
            "benchmark_symbol": "SPY",
            "test_size_time_percent": 25,
            "min_samples": 100,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["model_id"] > 0
    assert data["metrics"]["samples_count"] >= 100
    assert any("CORE_UNIVERSE" in warning for warning in data["warnings"])


def test_universe_does_not_call_real_apis(universe_client: TestClient) -> None:
    response = universe_client.get("/data/usage")

    assert response.status_code == 200
    assert all(item["calls_count"] == 0 for item in response.json())
