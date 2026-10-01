from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.alpha_vantage_news import AlphaVantageNewsProvider
from backend.app.data_providers.base import MissingApiKey, ProviderError, RateLimitExceeded
from backend.app.data_providers.finnhub_news import FinnhubNewsProvider
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.data_providers.yahoo_news import YahooNewsProvider
from backend.app.database import SCHEMA, migrate_db
from backend.app.services.ml_dataset_service import MLDatasetService
from backend.app.services.news_engine import NewsEngine
from backend.app.services.sentiment_engine import aggregate_news_sentiment

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "market_data"
FINNHUB_KEY = "SENTINEL_FINNHUB_NEWS_KEY_98765"


def _fixture(name: str) -> object:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _json_response(payload: object, status_code: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(json.dumps(payload).encode()),
        headers={"content-type": "application/json", **headers},
    )


def _open(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize(
    *,
    mic: str | None = "XNAS",
    news_symbol: str | None = "AAPL",
    news_status: str = "VERIFIED",
    path: Path | None = None,
) -> sqlite3.Connection:
    connection = _open(path)
    connection.executescript(SCHEMA)
    migrate_db(connection)
    instrument_id = connection.execute(
        """
        INSERT INTO instruments (canonical_name, instrument_type, asset_class, source, source_date)
        VALUES ('Apple Inc.', 'STOCK', 'EQUITY', 'test', '2026-09-30')
        """
    ).lastrowid
    listing_id = connection.execute(
        """
        INSERT INTO instrument_listings (
            instrument_id, ticker, mic, venue_name, currency, timezone, source, source_date
        )
        VALUES (?, 'AAPL', ?, 'Nasdaq', 'USD', 'America/New_York', 'test', '2026-09-30')
        """,
        (instrument_id, mic),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO assets (symbol, name, asset_type, currency, risk_level, instrument_listing_id)
        VALUES ('AAPL', 'Apple Inc.', 'stock', 'USD', 'medium', ?)
        """,
        (listing_id,),
    )
    if news_symbol is not None:
        connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol, status,
                source, observed_at, verified_at, evidence_hash, version
            )
            VALUES ('finnhub', ?, 'NEWS', ?, ?, ?, 'test', '2026-09-30T00:00:00Z', ?, ?, 1)
            """,
            (
                listing_id,
                news_symbol,
                news_symbol.upper(),
                news_status,
                "2026-09-30T00:00:00Z" if news_status == "VERIFIED" else None,
                hashlib.sha256(b"news mapping").hexdigest(),
            ),
        )
    connection.commit()
    return connection


def _settings(**overrides: object):  # noqa: ANN202
    values: dict[str, object] = {"enable_real_news": True, "finnhub_api_key": FINNHUB_KEY}
    values.update(overrides)
    return replace(get_settings(), **values)


def _transport(handler, settings) -> SafeProviderTransport:  # noqa: ANN001
    return SafeProviderTransport(allowed_hosts={"finnhub.io"}, settings=settings).with_client(
        httpx.Client(transport=httpx.MockTransport(handler))
    )


def _finnhub(connection: sqlite3.Connection, handler, settings=None) -> FinnhubNewsProvider:  # noqa: ANN001
    settings = settings or _settings()
    return FinnhubNewsProvider(settings, connection, transport=_transport(handler, settings), sleeper=lambda _d: None)


def _article(title: str, *, url: str = "https://www.example.com/a", when: int | None = None) -> dict[str, object]:
    return {
        "headline": title,
        "summary": "Company raises guidance",
        "url": url,
        "source": "Reuters",
        "datetime": when if when is not None else int(datetime.now(UTC).timestamp()) - 3600,
    }


def test_finnhub_news_sends_key_only_in_header_and_never_persists_it(caplog: pytest.LogCaptureFixture) -> None:
    connection = _initialize()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json_response(_fixture("finnhub_company_news.json"))

    items, used_cache = _finnhub(connection, handler).get_news_for_symbol("AAPL")

    assert used_cache is False
    assert len(seen) == 1
    request = seen[0]
    assert (request.url.host, request.url.path) == ("finnhub.io", "/api/v1/company-news")
    assert set(request.url.params) == {"symbol", "from", "to"}
    assert request.headers["X-Finnhub-Token"] == FINNHUB_KEY
    assert FINNHUB_KEY not in str(request.url)
    persisted = "\n".join(
        str(value)
        for row in connection.execute(
            """
            SELECT cache_key, request_url_hash, response_json FROM api_cache
            UNION ALL SELECT reservation_id, request_fingerprint, operation FROM provider_request_log
            """
        )
        for value in row
        if value is not None
    )
    assert FINNHUB_KEY not in persisted
    assert FINNHUB_KEY not in caplog.text
    assert items and all(item["provider"] == "finnhub_news" for item in items)


def test_finnhub_news_without_key_fails_closed_before_transport() -> None:
    connection = _initialize()
    calls: list[str] = []

    provider = _finnhub(
        connection,
        lambda request: calls.append(str(request.url)) or _json_response([]),
        _settings(finnhub_api_key=None),
    )

    with pytest.raises(MissingApiKey):
        provider.get_news_for_symbol("AAPL")
    assert calls == []


@pytest.mark.parametrize("payload", [{"error": "invalid"}, "not-json-list", None])
def test_finnhub_news_rejects_non_list_payloads(payload: object) -> None:
    connection = _initialize()
    provider = _finnhub(connection, lambda _request: _json_response(payload))

    with pytest.raises(ProviderError) as exc_info:
        provider.get_news_for_symbol("AAPL")

    assert "INVALID_PAYLOAD" in str(exc_info.value)
    assert FINNHUB_KEY not in str(exc_info.value)


def test_finnhub_news_normalizes_at_most_50_valid_public_articles() -> None:
    connection = _initialize()
    now = int(datetime.now(UTC).timestamp())
    articles = [_article(f"Headline {index}", when=now - index * 60) for index in range(60)]
    articles[0]["url"] = "http://127.0.0.1/internal"
    articles[1]["url"] = "file:///etc/passwd"
    articles[2]["datetime"] = now + 86_400  # futuro
    articles[3]["datetime"] = "bad"
    articles[4]["headline"] = ""
    provider = _finnhub(connection, lambda _request: _json_response(articles))

    items, _cache = provider.get_news_for_symbol("AAPL")

    titles = {item["title"] for item in items}
    assert len(items) <= 50
    assert "Headline 2" not in titles and "Headline 3" not in titles
    by_title = {item["title"]: item for item in items}
    assert by_title["Headline 0"]["url"] is None
    assert by_title["Headline 1"]["url"] is None
    assert all(item["published_at"] for item in items)


def test_finnhub_news_rate_limit_sets_cooldown() -> None:
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"error": "slow"}, 429, **{"retry-after": "60"})

    provider = _finnhub(connection, handler)
    with pytest.raises(RateLimitExceeded):
        provider.get_news_for_symbol("AAPL")
    physical = calls
    with pytest.raises(RateLimitExceeded):
        provider.get_news_for_symbol("AAPL")

    assert physical >= 1
    assert calls == physical
    assert provider._budget_policy().minute_limit == 55


def test_finnhub_news_cache_hit_and_force_refresh() -> None:
    connection = _initialize()
    payloads = [[_article("First")], [_article("Second")]]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(payloads[min(calls - 1, 1)])

    provider = _finnhub(connection, handler)
    first, first_cache = provider.get_news_for_symbol("AAPL")
    cached, cached_flag = provider.get_news_for_symbol("AAPL", force=False)
    forced, forced_flag = provider.get_news_for_symbol("AAPL", force=True)
    after, after_flag = provider.get_news_for_symbol("AAPL", force=False)

    assert (first_cache, cached_flag, forced_flag, after_flag) == (False, True, False, True)
    assert calls == 2
    assert [item["title"] for item in cached] == ["First"]
    assert [item["title"] for item in forced] == [item["title"] for item in after] == ["Second"]


def test_finnhub_news_concurrent_force_refreshes_are_coalesced(tmp_path: Path) -> None:
    database_path = tmp_path / "news-inflight.db"
    _initialize(path=database_path).close()
    connections = [_open(database_path), _open(database_path)]
    calls = 0
    started = threading.Event()
    release = threading.Event()

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=5)
        return _json_response([_article("Coalesced")])

    settings = _settings()
    shared = _transport(handler, settings)
    providers = [
        FinnhubNewsProvider(settings, connection, transport=shared, sleeper=lambda _d: None)
        for connection in connections
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(providers[0].get_news_for_symbol, "AAPL", True)
        assert started.wait(timeout=5)
        second = pool.submit(providers[1].get_news_for_symbol, "AAPL", True)
        time.sleep(0.3)
        release.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert calls == 1
    assert results[0][0][0]["title"] == results[1][0][0]["title"] == "Coalesced"
    for connection in connections:
        connection.close()


def test_alpha_and_yahoo_news_are_fail_closed_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _initialize()
    settings = _settings(alpha_vantage_api_key="SENTINEL_ALPHA_KEY")

    def forbidden(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("nessun URL o richiesta di rete ammessa")

    monkeypatch.setattr(AlphaVantageNewsProvider, "_request_url", forbidden, raising=False)
    monkeypatch.setattr(YahooNewsProvider, "fetch_json", forbidden)
    alpha = AlphaVantageNewsProvider(settings, connection)
    yahoo = YahooNewsProvider(settings, connection)

    assert (alpha.availability().state, alpha.availability().reason_code) == ("DISABLED", "SECRET_IN_QUERY_POLICY")
    assert (yahoo.availability().state, yahoo.availability().reason_code) == ("DISABLED", "NOT_PRIMARY_POLICY")
    with pytest.raises(ProviderError) as alpha_error:
        alpha.get_news_for_symbol("AAPL")
    with pytest.raises(ProviderError) as yahoo_error:
        yahoo.get_news_for_symbol("AAPL")
    assert "SECRET_IN_QUERY_POLICY" in str(alpha_error.value)
    assert "SENTINEL_ALPHA_KEY" not in str(alpha_error.value)
    assert "NOT_PRIMARY_POLICY" in str(yahoo_error.value)


@pytest.mark.parametrize(
    ("mic", "news_symbol", "news_status"),
    [(None, "AAPL", "VERIFIED"), ("XNAS", None, "VERIFIED"), ("XNAS", "AAPL", "RETIRED"), ("XETR", "AAPL", "VERIFIED")],
)
def test_news_engine_uses_finnhub_only_with_verified_symbol_and_supported_venue(
    monkeypatch: pytest.MonkeyPatch,
    mic: str | None,
    news_symbol: str | None,
    news_status: str,
) -> None:
    connection = _initialize(mic=mic, news_symbol=news_symbol, news_status=news_status)
    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", FINNHUB_KEY)
    get_settings.cache_clear()
    called: list[str] = []
    monkeypatch.setattr(
        FinnhubNewsProvider,
        "get_news_for_symbol",
        lambda self, symbol, force=False: called.append(symbol) or ([], False),
    )
    try:
        result = NewsEngine().refresh_news_for_symbol(connection, "AAPL")
    finally:
        get_settings.cache_clear()

    assert called == []
    assert result["provider"] == "mock_news"
    assert result["used_fallback"] is True


def test_news_engine_passes_verified_provider_symbol_and_force(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _initialize(news_symbol="AAPL.US")
    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", FINNHUB_KEY)
    get_settings.cache_clear()
    calls: list[tuple[str, bool]] = []

    def fake(self, symbol, force=False):  # noqa: ANN001, ANN202
        calls.append((symbol, force))
        return [], False

    monkeypatch.setattr(FinnhubNewsProvider, "get_news_for_symbol", fake)
    try:
        result = NewsEngine().refresh_news_for_symbol(connection, "AAPL", force=True)
    finally:
        get_settings.cache_clear()

    assert calls == [("AAPL.US", True)]
    assert result["provider"] == "finnhub_news"
    assert result["used_fallback"] is False


def _insert_news(connection: sqlite3.Connection, provider: str, score: float, url: str) -> None:
    connection.execute(
        """
        INSERT INTO news_items (
            asset_id, symbol, provider, title, summary, url, source, published_at,
            sentiment_score, sentiment_label, impact_level, relevance_score, raw_json,
            created_at, updated_at
        )
        VALUES (
            (SELECT id FROM assets WHERE symbol = 'AAPL'), 'AAPL', ?, ?, '', ?, 'src', ?,
            ?, ?, 'MEDIUM', 70, '{}', ?, ?
        )
        """,
        (
            provider,
            f"{provider} headline",
            url,
            datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
            score,
            "POSITIVE" if score > 0 else "NEGATIVE",
            datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
            datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        ),
    )


def test_demo_news_never_enter_sentiment_market_summary_or_ml_features() -> None:
    connection = _initialize()
    _insert_news(connection, "mock_news", 0.9, "https://example.com/demo")
    _insert_news(connection, "finnhub_news", -0.4, "https://example.com/real")

    summary = aggregate_news_sentiment(connection, "AAPL", lookback_days=7)
    market = NewsEngine().get_market_sentiment_summary(connection, lookback_days=7)
    features = MLDatasetService()._news_features(connection, "AAPL", datetime.now(UTC).date().isoformat())

    assert summary["news_count"] == 1
    assert summary["average_sentiment_score"] == -0.4
    assert market["news_count"] == 1
    assert features["news_sentiment_score_7d"] == -0.4
    assert features["news_positive_count_7d"] == 0


def test_provider_failure_fallback_to_demo_does_not_change_final_score(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _initialize()
    connection.execute(
        """
        INSERT INTO signals (asset_id, symbol, signal, score, technical_score, news_score, final_score, created_at)
        VALUES ((SELECT id FROM assets WHERE symbol = 'AAPL'), 'AAPL', 'HOLD', 60, 60, 0, 60, '2026-09-30T00:00:00')
        """
    )
    connection.commit()
    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", FINNHUB_KEY)
    get_settings.cache_clear()

    def failing(self, symbol, force=False):  # noqa: ANN001, ANN202
        raise ProviderError("finnhub_news:company-news:HTTP_503")

    monkeypatch.setattr(FinnhubNewsProvider, "get_news_for_symbol", failing)
    try:
        result = NewsEngine().refresh_news_for_symbol(connection, "AAPL")
    finally:
        get_settings.cache_clear()

    signal = connection.execute("SELECT news_score, final_score FROM signals").fetchone()
    assert result["used_fallback"] is True
    assert tuple(signal) == (0, 60)


def test_demo_news_publication_time_is_not_renewed_on_refresh() -> None:
    connection = _initialize()
    engine = NewsEngine()
    engine.refresh_news_for_symbol(connection, "AAPL")
    connection.execute(
        "UPDATE news_items SET published_at = '2026-01-01T12:00:00' WHERE provider = 'mock_news'"
    )
    engine.refresh_news_for_symbol(connection, "AAPL")

    dates = {row["published_at"] for row in connection.execute("SELECT published_at FROM news_items")}
    assert dates == {"2026-01-01T12:00:00"}
    assert aggregate_news_sentiment(connection, "AAPL", lookback_days=7)["news_count"] == 0


def test_demo_news_are_listed_but_labelled() -> None:
    connection = _initialize()
    NewsEngine().refresh_news_for_symbol(connection, "AAPL")

    items = NewsEngine().get_market_news(connection, symbol="AAPL")

    assert items and all(item["provider"] == "mock_news" for item in items)
    assert all(item["source"] == "InvestEdge Demo" for item in items)


def test_finnhub_empty_news_is_a_valid_empty_result() -> None:
    connection = _initialize()
    provider = _finnhub(connection, lambda _request: _json_response(_fixture("finnhub_company_news_empty.json")))

    items, used_cache = provider.get_news_for_symbol("AAPL")

    assert items == []
    assert used_cache is False


def test_news_refresh_all_reaches_finnhub_for_every_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regressione: le scritture news del primo simbolo restavano in transazione e il budget
    # rifiutava la chiamata Finnhub del secondo (TRANSPORT_FAILED -> fallback).
    import backend.app.data_providers.transport as transport_module

    connection = _initialize()
    instrument_id = connection.execute(
        """
        INSERT INTO instruments (canonical_name, instrument_type, asset_class, source, source_date)
        VALUES ('Microsoft Corp.', 'STOCK', 'EQUITY', 'test', '2026-10-01')
        """
    ).lastrowid
    listing_id = connection.execute(
        """
        INSERT INTO instrument_listings (instrument_id, ticker, mic, venue_name, currency, timezone, source, source_date)
        VALUES (?, 'MSFT', 'XNAS', 'Nasdaq', 'USD', 'America/New_York', 'test', '2026-10-01')
        """,
        (instrument_id,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO assets (symbol, name, asset_type, currency, risk_level, instrument_listing_id)
        VALUES ('MSFT', 'Microsoft Corp.', 'stock', 'USD', 'medium', ?)
        """,
        (listing_id,),
    )
    connection.execute(
        """
        INSERT INTO provider_symbols (
            provider, listing_id, capability, provider_symbol, normalized_symbol, status,
            source, observed_at, verified_at, evidence_hash, version
        )
        VALUES ('finnhub', ?, 'NEWS', 'MSFT', 'MSFT', 'VERIFIED', 'test',
                '2026-09-30T00:00:00Z', '2026-09-30T00:00:00Z', ?, 1)
        """,
        (listing_id, hashlib.sha256(b"msft news mapping").hexdigest()),
    )
    connection.commit()
    symbols_seen: list[str] = []
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        symbols_seen.append(request.url.params["symbol"])
        return _json_response([_article(f"{request.url.params['symbol']} news")])

    monkeypatch.setattr(
        transport_module.httpx,
        "Client",
        lambda *_args, **_kwargs: real_client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", FINNHUB_KEY)
    get_settings.cache_clear()
    try:
        result = NewsEngine().refresh_all_news(connection, limit=5)
    finally:
        get_settings.cache_clear()

    assert sorted(symbols_seen) == ["AAPL", "MSFT"]
    assert result["summary"]["updated"] == 2
    assert all(item["provider"] == "finnhub_news" for item in result["results"])
