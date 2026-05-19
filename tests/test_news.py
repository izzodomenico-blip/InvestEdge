from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend.app.config import get_settings

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "investedge.db"))
    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    monkeypatch.setenv("ENABLE_REAL_NEWS", "false")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    monkeypatch.setenv("FRED_API_KEY", "")
    monkeypatch.setenv("NEWS_DAILY_LIMIT", "20")
    monkeypatch.setenv("NEWS_CACHE_TTL_HOURS", "6")
    monkeypatch.setenv("NEWS_SENTIMENT_WEIGHT", "5")
    get_settings.cache_clear()

    from backend.scripts.seed_database import seed_database

    seed_database(reset=True)

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_classify_sentiment_positive() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("Company announces earnings beat and raises guidance")
    assert result["sentiment_label"] == "POSITIVE"
    assert result["sentiment_score"] > 0
    assert "earnings beat" in result["positive_hits"]
    assert "raises guidance" in result["positive_hits"]


def test_classify_sentiment_negative() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("Major lawsuit and downgrade weigh on outlook")
    assert result["sentiment_label"] == "NEGATIVE"
    assert result["sentiment_score"] < 0
    assert "lawsuit" in result["negative_hits"]
    assert "downgrade" in result["negative_hits"]


def test_classify_sentiment_neutral_empty() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment(None)
    assert result["sentiment_label"] == "NEUTRAL"
    assert result["sentiment_score"] == 0.0


def test_estimate_impact_levels() -> None:
    from backend.app.services.sentiment_engine import estimate_impact

    high = estimate_impact(
        {
            "title": "Bankruptcy filing rocks {symbol}",
            "summary": "Investigation triggers regulatory risk concerns and lawsuit news.",
            "sentiment_score": -0.7,
        }
    )
    assert high["impact_level"] == "HIGH"
    assert high["sentiment_label"] == "NEGATIVE"

    medium = estimate_impact(
        {
            "title": "Partnership announcement",
            "summary": "The deal is moderately positive.",
            "sentiment_score": 0.35,
        }
    )
    assert medium["impact_level"] in {"MEDIUM", "HIGH"}

    low = estimate_impact(
        {
            "title": "Generic update",
            "summary": "",
            "sentiment_score": 0.0,
        }
    )
    assert low["impact_level"] == "LOW"
    assert low["sentiment_label"] == "NEUTRAL"


def test_news_status_endpoint(client: TestClient) -> None:
    response = client.get("/news/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enable_real_news"] is False
    assert {item["provider"] for item in data["provider_status"]} >= {"alpha_vantage_news", "mock_news"}
    assert data["daily_usage"]["daily_limit"] == 20
    assert "cache_status" in data


def test_news_refresh_with_real_disabled(client: TestClient) -> None:
    response = client.post("/news/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["used_fallback"] is True
    assert data["provider"] in {"mock_news", "alpha_vantage_news"}
    assert "News reali disattivate" in data["message"] or "demo" in data["message"].lower()


def test_news_fallback_when_api_key_missing(client: TestClient, monkeypatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    get_settings.cache_clear()

    response = client.post("/news/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["used_fallback"] is True
    assert "Provider news non configurato" in data["message"]

    monkeypatch.setenv("ENABLE_REAL_NEWS", "false")
    get_settings.cache_clear()


def test_news_for_symbol_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert all(item["symbol"] == "AAPL" for item in data)
    assert data
    assert {"title", "sentiment_label", "impact_level", "relevance_score"} <= set(data[0])


def test_news_list_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    client.post("/news/refresh/MSFT")
    response = client.get("/news?limit=20")

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    symbols = {item["symbol"] for item in data}
    assert symbols & {"AAPL", "MSFT"}


def test_news_sentiment_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news/sentiment/AAPL?lookback_days=14")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["lookback_days"] == 14
    assert data["news_count"] >= 1
    assert data["sentiment_label"] in {"POSITIVE", "NEGATIVE", "NEUTRAL"}
    assert data["impact_level"] in {"LOW", "MEDIUM", "HIGH"}


def test_news_dedup_does_not_duplicate(client: TestClient) -> None:
    from backend.app.database import db_session

    client.post("/news/refresh/AAPL")
    with db_session() as connection:
        before = connection.execute(
            "SELECT COUNT(*) AS c FROM news_items WHERE symbol = 'AAPL'"
        ).fetchone()["c"]
    client.post("/news/refresh/AAPL")
    client.post("/news/refresh/AAPL")
    with db_session() as connection:
        after = connection.execute(
            "SELECT COUNT(*) AS c FROM news_items WHERE symbol = 'AAPL'"
        ).fetchone()["c"]

    assert after == before


def test_news_refresh_unknown_symbol(client: TestClient) -> None:
    response = client.post("/news/refresh/ZZZZZ")
    assert response.status_code == 404


def test_dashboard_includes_news_fields(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert "high_impact_news" in data
    assert "market_sentiment" in data
    assert data["market_sentiment"]["news_count"] >= 1


def test_alpha_vantage_news_normalization() -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.alpha_vantage_news import AlphaVantageNewsProvider
    from backend.app.database import db_session

    get_settings.cache_clear()
    with db_session() as connection:
        provider = AlphaVantageNewsProvider(get_settings(), connection)
        sample = {
            "feed": [
                {
                    "title": "AAPL earnings beat lifts shares",
                    "summary": "AAPL posts revenue growth",
                    "url": "https://news.example/aapl-1",
                    "source": "Demo",
                    "time_published": "20260515T140000",
                    "overall_sentiment_score": 0.42,
                    "overall_sentiment_label": "Bullish",
                    "ticker_sentiment": [
                        {
                            "ticker": "AAPL",
                            "ticker_sentiment_score": "0.55",
                            "ticker_sentiment_label": "Somewhat-Bullish",
                            "relevance_score": "0.85",
                        }
                    ],
                }
            ]
        }
        normalized = provider.normalize_news(sample, "AAPL")

    assert normalized
    item = normalized[0]
    assert item["title"] == "AAPL earnings beat lifts shares"
    assert item["url"] == "https://news.example/aapl-1"
    assert item["published_at"] == "2026-05-15 14:00:00"
    assert pytest.approx(item["sentiment_score"], 0.01) == 0.55
    assert item["sentiment_label_hint"] == "POSITIVE"
    assert item["relevance_score"] == 85.0


def test_mock_news_provider_returns_items() -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.mock_news_provider import MockNewsProvider
    from backend.app.database import db_session

    get_settings.cache_clear()
    with db_session() as connection:
        provider = MockNewsProvider(get_settings(), connection)
        news, used_cache = provider.get_news_for_symbol("AAPL")

    assert used_cache is False
    assert len(news) >= 3
    assert all(item["title"] for item in news)
    assert any(item["sentiment_label_hint"] == "POSITIVE" for item in news)
    assert any(item["sentiment_label_hint"] == "NEGATIVE" for item in news)


def test_technical_analysis_keeps_technical_score_separate(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/technical-analysis/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert "technical_score" in data
    assert "news_score" in data
    assert "final_score" in data
    assert abs(float(data["news_score"])) <= 5.0
    assert 0.0 <= float(data["final_score"]) <= 100.0
