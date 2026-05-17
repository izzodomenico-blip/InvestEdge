from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "investedge.db"))

    from backend.app.config import get_settings

    get_settings.cache_clear()

    from backend.scripts.seed_database import seed_database

    seed_database(reset=True)

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_assets_after_seed(client: TestClient) -> None:
    response = client.get("/assets")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert {asset["symbol"] for asset in data} >= {"AAPL", "BTC", "TLT"}
    assert data[0]["last_price"] is not None


def test_prices_for_symbol(client: TestClient) -> None:
    response = client.get("/prices/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert len(data["prices"]) >= 500
    assert {"date", "open", "high", "low", "close", "sma_50"} <= set(data["prices"][-1])


def test_signals_after_seed(client: TestClient) -> None:
    response = client.get("/signals")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert data[0]["signal"] in {"BUY", "HOLD", "REDUCE", "SELL"}
    assert 0 <= data[0]["score"] <= 100


def test_dashboard_after_seed(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["initialized"] is True
    assert data["assets_count"] == 25
    assert data["signals_count"] == 25
    assert data["price_points_count"] >= 14000
    assert data["latest_signals"]
