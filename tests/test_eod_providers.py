from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.base import ProviderError, RateLimitExceeded, RealDataDisabled
from backend.app.data_providers.provider_registry import ProviderRegistry
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import SCHEMA, migrate_db
from backend.app.models.market_data import (
    MarketObservationEnvelope,
    ObservationRejection,
    ValidatedObservation,
)
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.provider_budget_service import ProviderBudgetPolicy

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "market_data"
NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


def _payload_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _initialize_connection(
    *,
    instrument_type: str = "STOCK",
    asset_type: str = "stock",
    mapped: bool = True,
) -> tuple[sqlite3.Connection, int]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    migrate_db(connection)
    instrument_id = connection.execute(
        """
        INSERT INTO instruments (
            canonical_name, instrument_type, asset_class, source, source_date
        )
        VALUES ('Acme Corp', ?, 'EQUITY', 'test', '2026-08-17')
        """,
        (instrument_type,),
    ).lastrowid
    listing_id = connection.execute(
        """
        INSERT INTO instrument_listings (
            instrument_id, ticker, mic, venue_name, currency, timezone,
            source, source_date
        )
        VALUES (?, 'ACME', 'XNAS', 'Nasdaq', 'USD', 'America/New_York',
                'test', '2026-08-17')
        """,
        (instrument_id,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO assets (
            symbol, name, asset_type, currency, risk_level, instrument_listing_id
        )
        VALUES ('ACME', 'Acme Corp', ?, 'USD', 'medium', ?)
        """,
        (asset_type, listing_id),
    )
    if mapped:
        connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash
            )
            VALUES (
                'stooq', ?, 'EOD', 'acme.us', 'ACME.US', 'VERIFIED',
                'test', ?, ?, ?
            )
            """,
            (listing_id, NOW.isoformat(), NOW.isoformat(), _payload_hash("stooq mapping")),
        )
    connection.commit()
    return connection, int(listing_id)


def _listing(connection: sqlite3.Connection, listing_id: int) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT listing.*, instrument.instrument_type,
               provider_symbol.provider_symbol
        FROM instrument_listings AS listing
        JOIN instruments AS instrument ON instrument.id = listing.instrument_id
        LEFT JOIN provider_symbols AS provider_symbol
          ON provider_symbol.listing_id = listing.id
         AND provider_symbol.provider = 'stooq'
         AND provider_symbol.capability = 'EOD'
         AND provider_symbol.status = 'VERIFIED'
        WHERE listing.id = ?
        """,
        (listing_id,),
    ).fetchone()
    assert row is not None
    return dict(row)


def _csv_response(payload: bytes, content_type: str = "text/csv") -> httpx.Response:
    return httpx.Response(
        200,
        stream=httpx.ByteStream(payload),
        headers={"content-type": content_type},
    )


def _stooq_provider(
    connection: sqlite3.Connection,
    handler,  # noqa: ANN001
    *,
    enabled: bool = True,
    now: datetime = NOW,
):
    from backend.app.data_providers.stooq import StooqProvider

    settings = replace(
        get_settings(),
        enable_real_data=True,
        enable_stooq=enabled,
    )
    transport = SafeProviderTransport(
        allowed_hosts={"stooq.com"},
        clock=lambda: now,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    return StooqProvider(
        settings,
        connection,
        transport=transport,
        clock=lambda: now,
        sleeper=lambda _delay: None,
    )


def _daily_payload(close: str = "104.75") -> bytes:
    return (
        "Date,Open,High,Low,Close,Volume\n"
        f"2026-08-14,100.10,105.25,99.50,{close},1200\n"
    ).encode()


def test_eod_capability_registry_returns_only_verified_compatible_stooq_mapping() -> None:
    connection, listing_id = _initialize_connection()
    settings = replace(get_settings(), enable_real_data=True, enable_stooq=True)
    registry = ProviderRegistry(settings, connection)

    matches = registry.providers_for(connection, listing_id, "EOD")

    assert [asdict(match) for match in matches] == [
        {
            "provider": "stooq",
            "capability": "EOD",
            "listing_id": listing_id,
            "provider_symbol": "acme.us",
            "currency": "USD",
            "priority": 10,
        }
    ]
    assert registry.availability_for("yahoo_finance").state == "DISABLED"
    assert registry.availability_for("yahoo_finance").reason_code == "NOT_PRIMARY_POLICY"
    assert {match.provider for match in matches}.isdisjoint({"yahoo_finance", "alpha_vantage"})

    connection.execute(
        "UPDATE provider_symbols SET status = 'RETIRED' WHERE provider = 'stooq'"
    )
    assert registry.providers_for(connection, listing_id, "EOD") == ()
    connection.close()


def test_stooq_parses_fixture_with_fixed_https_host_path_and_validator_decimals() -> None:
    connection, listing_id = _initialize_connection()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _csv_response((FIXTURE_DIR / "stooq_daily.csv").read_bytes())

    provider = _stooq_provider(connection, handler)
    listing = _listing(connection, listing_id)

    envelopes = provider.fetch_observations(
        listing,
        date(2026, 8, 14),
        date(2026, 8, 15),
    )

    assert len(requests) == 1
    assert requests[0].url.scheme == "https"
    assert requests[0].url.host == "stooq.com"
    assert requests[0].url.path == "/q/d/l/"
    assert dict(requests[0].url.params) == {
        "s": "acme.us",
        "i": "d",
        "d1": "20260814",
        "d2": "20260815",
    }
    assert len(envelopes) == 2
    assert envelopes[0].raw_fields == {
        "open": "100.10",
        "high": "105.25",
        "low": "99.50",
        "close": "104.75",
        "adjusted_close": "104.75",
        "volume": "1200",
    }
    assert envelopes[0].provider_observed_at == datetime(2026, 8, 14, 4, tzinfo=UTC)
    assert envelopes[0].currency == "USD"
    assert envelopes[0].timezone == "America/New_York"
    assert envelopes[0].session == "REGULAR"
    assert envelopes[0].source_quality == "eod"
    assert envelopes[0].kind == "BAR"
    validated = MarketObservationService().validate(listing, envelopes[0], NOW)
    assert isinstance(validated, ValidatedObservation)
    assert validated.observation.open == Decimal("100.10")
    assert validated.observation.close == Decimal("104.75")
    assert validated.observation.volume == Decimal("1200")
    connection.close()


def test_stooq_never_turns_the_download_day_session_into_an_eod_bar() -> None:
    # NOW = lunedi 17/08 12:00 a New York: la riga del 17/08 e una seduta ancora aperta.
    connection, listing_id = _initialize_connection()
    payload = (
        b"Date,Open,High,Low,Close,Volume\n"
        b"2026-08-14,100.10,105.25,99.50,104.75,1200\n"
        b"2026-08-17,104.80,106.00,104.00,105.10,300\n"
    )
    listing = _listing(connection, listing_id)

    downloaded = _stooq_provider(connection, lambda _request: _csv_response(payload)).fetch_observations(
        listing, None, None
    )

    def offline(_request):  # noqa: ANN001, ANN202
        raise AssertionError("la seconda lettura deve usare la cache")

    next_day = datetime(2026, 8, 18, 14, 0, tzinfo=UTC)
    cached = _stooq_provider(connection, offline, now=next_day).fetch_observations(listing, None, None)

    expected = [datetime(2026, 8, 14, 4, tzinfo=UTC)]
    assert [item.provider_observed_at for item in downloaded] == expected
    assert [item.provider_observed_at for item in cached] == expected
    connection.close()


def test_stooq_empty_fixture_returns_no_observation() -> None:
    connection, listing_id = _initialize_connection()
    provider = _stooq_provider(
        connection,
        lambda _request: _csv_response((FIXTURE_DIR / "stooq_empty.csv").read_bytes()),
    )

    assert provider.fetch_observations(_listing(connection, listing_id), None, None) == []
    connection.close()


def test_stooq_missing_columns_becomes_validator_malformed_rejection() -> None:
    connection, listing_id = _initialize_connection()
    provider = _stooq_provider(
        connection,
        lambda _request: _csv_response((FIXTURE_DIR / "stooq_malformed.csv").read_bytes()),
    )
    listing = _listing(connection, listing_id)

    envelopes = provider.fetch_observations(listing, None, None)
    result = MarketObservationService().validate(listing, envelopes[0], NOW)

    assert len(envelopes) == 1
    assert isinstance(result, ObservationRejection)
    assert result.reason_code == "MALFORMED_PAYLOAD"
    connection.close()


def test_stooq_rejects_html_before_csv_parsing() -> None:
    connection, listing_id = _initialize_connection()
    provider = _stooq_provider(
        connection,
        lambda _request: _csv_response(b"<html>upstream error</html>", "text/html"),
    )

    with pytest.raises(ProviderError, match=r"stooq:EOD:CONTENT_TYPE_REJECTED"):
        provider.fetch_observations(_listing(connection, listing_id), None, None)
    connection.close()


def test_stooq_currency_divergence_is_rejected_without_mutating_listing() -> None:
    connection, listing_id = _initialize_connection()
    provider = _stooq_provider(
        connection,
        lambda _request: _csv_response(_daily_payload()),
    )
    listing = _listing(connection, listing_id)
    envelope = provider.fetch_observations(listing, None, None)[0]

    result = MarketObservationService().validate(
        listing,
        replace(envelope, currency="EUR"),
        NOW,
    )

    assert isinstance(result, ObservationRejection)
    assert result.reason_code == "CURRENCY_MISMATCH"
    assert connection.execute(
        "SELECT currency FROM instrument_listings WHERE id = ?", (listing_id,)
    ).fetchone()[0] == "USD"
    connection.close()


def test_stooq_requires_explicit_provider_symbol_without_ticker_heuristic() -> None:
    connection, listing_id = _initialize_connection(mapped=False)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _csv_response(_daily_payload())

    provider = _stooq_provider(connection, handler)
    listing = _listing(connection, listing_id)

    with pytest.raises(ProviderError, match=r"stooq:EOD:MISSING_PROVIDER_SYMBOL"):
        provider.fetch_observations(listing, None, None)
    assert calls == 0
    connection.close()


def test_stooq_opt_in_is_disabled_by_default_and_never_reaches_transport() -> None:
    connection, listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _csv_response(_daily_payload())

    provider = _stooq_provider(connection, handler, enabled=False)

    assert provider.availability().state == "DISABLED"
    assert provider.availability().reason_code == "OPT_IN_DISABLED"
    with pytest.raises(RealDataDisabled, match=r"stooq:EOD:OPT_IN_DISABLED"):
        provider.fetch_observations(_listing(connection, listing_id), None, None)
    assert calls == 0
    connection.close()


def test_stooq_budget_is_5_per_minute_100_per_day_and_1000_per_month() -> None:
    connection, listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _csv_response(_daily_payload())

    provider = _stooq_provider(connection, handler)
    listing = _listing(connection, listing_id)

    assert provider.policy == ProviderBudgetPolicy(5, 100, 1_000, 3)
    for _ in range(5):
        provider.fetch_observations(listing, None, None, bypass_cache=True)
    with pytest.raises(RateLimitExceeded, match=r"stooq:EOD:BUDGET_EXHAUSTED"):
        provider.fetch_observations(listing, None, None, bypass_cache=True)
    assert calls == 5
    connection.close()


def test_stooq_serves_valid_cache_after_budget_is_exhausted() -> None:
    connection, listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _csv_response(_daily_payload())

    provider = _stooq_provider(connection, handler)
    listing = _listing(connection, listing_id)

    provider.fetch_observations(listing, None, None)
    for _ in range(4):
        provider.fetch_observations(listing, None, None, bypass_cache=True)

    assert provider.availability().reason_code == "BUDGET_EXHAUSTED"
    cached = provider.fetch_observations(listing, None, None)

    assert len(cached) == 1
    assert provider.last_fetch_used_cache is True
    assert calls == 5
    connection.close()


def test_stooq_bypass_cache_only_forces_one_governed_request_and_refreshes_cache() -> None:
    connection, listing_id = _initialize_connection()
    payloads = [_daily_payload("104.75"), _daily_payload("104.90")]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _csv_response(payloads.pop(0))

    provider = _stooq_provider(connection, handler)
    listing = _listing(connection, listing_id)

    first = provider.fetch_observations(listing, None, None)
    assert provider.last_fetch_used_cache is False
    cached = provider.fetch_observations(listing, None, None)
    assert provider.last_fetch_used_cache is True
    forced = provider.fetch_observations(listing, None, None, bypass_cache=True)
    assert provider.last_fetch_used_cache is False
    refreshed_cache = provider.fetch_observations(listing, None, None)

    assert calls == 2
    assert first[0].raw_fields["close"] == cached[0].raw_fields["close"] == "104.75"
    assert forced[0].raw_fields["close"] == refreshed_cache[0].raw_fields["close"] == "104.90"
    assert isinstance(MarketObservationService().validate(listing, forced[0], NOW), ValidatedObservation)
    request_log = connection.execute(
        """
        SELECT COUNT(DISTINCT request_fingerprint),
               SUM(CASE WHEN outcome = 'SUCCEEDED' THEN 1 ELSE 0 END)
        FROM provider_request_log
        WHERE provider = 'stooq'
        """
    ).fetchone()
    assert tuple(request_log) == (1, 2)
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'stooq'"
    ).fetchone()[0] == 2
    connection.close()


def test_alpha_policy_disables_transport_even_when_key_is_configured() -> None:
    from backend.app.data_providers.alpha_vantage import AlphaVantageProvider

    connection, _listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    settings = replace(
        get_settings(),
        enable_real_data=True,
        alpha_vantage_api_key="TEST_ALPHA_SENTINEL_KEY",
    )
    transport = SafeProviderTransport(
        allowed_hosts={"www.alphavantage.co"}
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    provider = AlphaVantageProvider(settings, connection, transport=transport)

    assert provider.availability().state == "DISABLED"
    assert provider.availability().reason_code == "SECRET_IN_QUERY_POLICY"
    with pytest.raises(ProviderError, match=r"alpha_vantage:EOD:SECRET_IN_QUERY_POLICY"):
        provider.get_daily_prices("ACME")
    assert calls == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE provider = 'alpha_vantage'"
    ).fetchone()[0] == 0
    connection.close()


def test_compatible_fallback_records_selection_without_mutating_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
    from backend.app.data_providers.stooq import StooqProvider
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider

    connection, listing_id = _initialize_connection()
    original = MarketObservationEnvelope(
        listing_id=listing_id,
        provider="last_good",
        capability="EOD",
        operation="stooq_daily",
        received_at=NOW,
        provider_observed_at=NOW - timedelta(hours=1),
        timezone="America/New_York",
        session="REGULAR",
        currency="USD",
        source_quality="eod",
        kind="BAR",
        raw_fields={"close": "103.25", "volume": "100"},
        raw_payload_sha256=_payload_hash("last compatible"),
    )
    MarketObservationService().ingest_batch(connection, [original], NOW)
    connection.commit()
    before = dict(connection.execute("SELECT * FROM market_observations").fetchone())

    def budget_exhausted(self, listing, start, end, bypass_cache=False):  # noqa: ANN001, ANN202
        raise RateLimitExceeded("stooq:EOD:BUDGET_EXHAUSTED")

    def forbidden(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("Yahoo/Alpha non devono essere chiamati")

    monkeypatch.setattr(StooqProvider, "fetch_observations", budget_exhausted)
    monkeypatch.setattr(YahooFinanceProvider, "get_daily_prices", forbidden)
    monkeypatch.setattr(AlphaVantageProvider, "get_daily_prices", forbidden)
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("ENABLE_STOOQ", "true")
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "ACME")
    finally:
        get_settings.cache_clear()

    event = connection.execute(
        """
        SELECT selected_observation_id, requested_provider, actual_provider,
               fallback_reason
        FROM market_data_selection_events
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    after = dict(connection.execute("SELECT * FROM market_observations").fetchone())

    assert set(result) == {
        "symbol",
        "provider",
        "rows_inserted",
        "rows_updated",
        "used_cache",
        "used_fallback",
        "message",
    }
    assert result["provider"] == "stooq"
    assert result["used_fallback"] is True
    assert dict(event) == {
        "selected_observation_id": before["id"],
        "requested_provider": "stooq",
        "actual_provider": "last_good",
        "fallback_reason": "PROVIDER_FALLBACK",
    }
    assert after == before
    assert after["listing_id"] == listing_id
    assert after["currency"] == "USD"
    assert connection.execute("SELECT COUNT(*) FROM quality_assessments").fetchone()[0] == 1
    connection.close()
