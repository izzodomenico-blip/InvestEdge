from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_assets_endpoint_starts_empty_or_returns_list() -> None:
    with TestClient(app) as client:
        response = client.get("/assets")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
