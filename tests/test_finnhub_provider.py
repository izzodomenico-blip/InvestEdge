from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.base import (
    MissingApiKey,
    ProviderError,
    RateLimitExceeded,
)
from backend.app.data_providers.finnhub_quote import FinnhubQuoteProvider
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
SENTINEL = "SENTINEL_FINNHUB_QUOTE_HEADER_12345"


def _payload_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _quote_payload(**changes: object) -> dict[str, object]:
    payload = json.loads((FIXTURE_DIR / "finnhub_quote.json").read_text(encoding="utf-8"))
    payload.update(changes)
    return payload


def _json_response(
    payload: object,
    status_code: int = 200,
    **headers: str,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(json.dumps(payload, separators=(",", ":")).encode()),
        headers={"content-type": "application/json", **headers},
    )


def _open_connection(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(path) if path is not None else ":memory:",
        check_same_thread=False,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _initialize_connection(
    *,
    mic: str | None = "XNAS",
    mapped: bool = True,
    path: Path | None = None,
) -> tuple[sqlite3.Connection, int]:
    connection = _open_connection(path)
    connection.executescript(SCHEMA)
    migrate_db(connection)
    instrument_id = connection.execute(
        """
        INSERT INTO instruments (
            canonical_name, instrument_type, asset_class, source, source_date
        )
        VALUES ('Acme Corp', 'STOCK', 'EQUITY', 'test', '2026-08-17')
        """
    ).lastrowid
    listing_id = connection.execute(
        """
        INSERT INTO instrument_listings (
            instrument_id, ticker, mic, venue_name, currency, timezone,
            source, source_date
        )
        VALUES (?, 'ACME', ?, 'Test Venue', 'USD', 'America/New_York',
                'test', '2026-08-17')
        """,
        (instrument_id, mic),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO assets (
            symbol, name, asset_type, currency, risk_level, instrument_listing_id
        )
        VALUES ('ACME', 'Acme Corp', 'stock', 'USD', 'medium', ?)
        """,
        (listing_id,),
    )
    if mapped:
        connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash
            )
            VALUES (
                'finnhub', ?, 'QUOTE', 'ACME', 'ACME', 'VERIFIED',
                'test', ?, ?, ?
            )
            """,
            (
                listing_id,
                NOW.isoformat(),
                NOW.isoformat(),
                _payload_hash("finnhub mapping"),
            ),
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
         AND provider_symbol.provider = 'finnhub'
         AND provider_symbol.capability = 'QUOTE'
         AND provider_symbol.status = 'VERIFIED'
        WHERE listing.id = ?
        """,
        (listing_id,),
    ).fetchone()
    assert row is not None
    listing = dict(row)
    listing["session"] = "REGULAR"
    return listing


def _provider(
    connection: sqlite3.Connection,
    handler,  # noqa: ANN001
    *,
    key: str | None = SENTINEL,
    now: datetime = NOW,
) -> FinnhubQuoteProvider:
    settings = replace(
        get_settings(),
        enable_real_data=True,
        finnhub_api_key=key,
    )
    transport = SafeProviderTransport(
        allowed_hosts={"finnhub.io"},
        settings=settings,
        clock=lambda: now,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    return FinnhubQuoteProvider(
        settings,
        connection,
        transport=transport,
        clock=lambda: now,
        sleeper=lambda _delay: None,
    )


def _quote_envelope(
    listing_id: int,
    *,
    provider_observed_at: datetime,
    source_quality: str = "delayed",
    label: str = "quote fallback",
) -> MarketObservationEnvelope:
    return MarketObservationEnvelope(
        listing_id=listing_id,
        provider="finnhub",
        capability="QUOTE",
        operation="finnhub_quote",
        received_at=NOW,
        provider_observed_at=provider_observed_at,
        timezone="America/New_York",
        session="REGULAR",
        currency="USD",
        source_quality=source_quality,
        kind="QUOTE",
        raw_fields={"last": "225.50"},
        raw_payload_sha256=_payload_hash(label),
    )


def _eod_envelope(listing_id: int) -> MarketObservationEnvelope:
    return MarketObservationEnvelope(
        listing_id=listing_id,
        provider="stooq",
        capability="EOD",
        operation="stooq_daily",
        received_at=NOW,
        provider_observed_at=NOW - timedelta(hours=4),
        timezone="America/New_York",
        session="REGULAR",
        currency="USD",
        source_quality="eod",
        kind="BAR",
        raw_fields={"close": "220", "volume": "100"},
        raw_payload_sha256=_payload_hash("eod must not become quote fallback"),
    )


def test_us_quote_registry_requires_verified_mapping_and_allowlisted_mic() -> None:
    connection, listing_id = _initialize_connection()
    registry = ProviderRegistry(
        replace(get_settings(), enable_real_data=True, finnhub_api_key=SENTINEL),
        connection,
    )

    matches = registry.providers_for(connection, listing_id, "QUOTE")

    assert [asdict(match) for match in matches] == [
        {
            "provider": "finnhub",
            "capability": "QUOTE",
            "listing_id": listing_id,
            "provider_symbol": "ACME",
            "currency": "USD",
            "priority": 10,
        }
    ]
    connection.execute(
        "UPDATE instrument_listings SET mic = 'XLON' WHERE id = ?",
        (listing_id,),
    )
    assert registry.providers_for(connection, listing_id, "QUOTE") == ()
    connection.execute(
        "UPDATE instrument_listings SET mic = NULL WHERE id = ?",
        (listing_id,),
    )
    assert registry.providers_for(connection, listing_id, "QUOTE") == ()
    connection.close()


def test_us_quote_registry_rejects_missing_or_retired_mapping() -> None:
    connection, listing_id = _initialize_connection(mapped=False)
    registry = ProviderRegistry(
        replace(get_settings(), enable_real_data=True, finnhub_api_key=SENTINEL),
        connection,
    )

    assert registry.providers_for(connection, listing_id, "QUOTE") == ()
    connection.execute(
        """
        INSERT INTO provider_symbols (
            provider, listing_id, capability, provider_symbol, normalized_symbol,
            status, source, observed_at, evidence_hash
        )
        VALUES ('finnhub', ?, 'QUOTE', 'ACME', 'ACME', 'RETIRED',
                'test', ?, ?)
        """,
        (listing_id, NOW.isoformat(), _payload_hash("retired mapping")),
    )
    assert registry.providers_for(connection, listing_id, "QUOTE") == ()
    connection.close()


def test_finnhub_quote_uses_fixed_endpoint_symbol_param_and_header_only_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection, listing_id = _initialize_connection()
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["path"] = request.url.path
        observed["params"] = dict(request.url.params)
        observed["token"] = request.headers.get("x-finnhub-token")
        return _json_response(_quote_payload())

    provider = _provider(connection, handler)
    envelope = provider.fetch_quote(_listing(connection, listing_id), NOW)

    assert observed == {
        "url": "https://finnhub.io/api/v1/quote?symbol=ACME",
        "path": "/api/v1/quote",
        "params": {"symbol": "ACME"},
        "token": SENTINEL,
    }
    assert envelope.provider == "finnhub"
    assert envelope.capability == "QUOTE"
    persisted = "\n".join(
        str(value)
        for row in connection.execute(
            """
            SELECT cache_key, provider, endpoint, request_url_hash
            FROM api_cache
            UNION ALL
            SELECT reservation_id, provider, operation, request_fingerprint
            FROM provider_request_log
            """
        )
        for value in row
        if value is not None
    )
    assert SENTINEL not in str(observed["url"])
    assert SENTINEL not in persisted
    assert SENTINEL not in caplog.text
    connection.close()


def test_finnhub_quote_missing_key_disables_provider_without_transport() -> None:
    connection, listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(_quote_payload())

    provider = _provider(connection, handler, key=None)

    assert provider.api_key_configured() is False
    assert provider.availability().state == "DISABLED"
    assert provider.availability().reason_code == "MISSING_CREDENTIAL"
    with pytest.raises(MissingApiKey, match=r"finnhub:QUOTE:MISSING_CREDENTIAL"):
        provider.fetch_quote(_listing(connection, listing_id), NOW)
    assert calls == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE provider = 'finnhub'"
    ).fetchone()[0] == 0
    connection.close()


def test_finnhub_valid_quote_is_delayed_quote_and_never_projects_price_history() -> None:
    connection, listing_id = _initialize_connection()
    provider = _provider(
        connection,
        lambda _request: _json_response(_quote_payload()),
    )
    listing = _listing(connection, listing_id)

    envelope = provider.fetch_quote(listing, NOW)
    validated = MarketObservationService().validate(listing, envelope, NOW)
    ingest = MarketObservationService().ingest_batch(connection, [envelope], NOW)

    assert envelope.provider_observed_at == NOW - timedelta(minutes=1)
    assert envelope.source_quality == "delayed"
    assert envelope.kind == "QUOTE"
    assert envelope.raw_fields == {
        "last": 226.01,
        "quote_high": 228.7,
        "quote_low": 224.42,
        "quote_open": 228.2,
        "previous_close": 228.9,
    }
    assert isinstance(validated, ValidatedObservation)
    assert validated.observation.last == Decimal("226.01")
    assert validated.observation.open is None
    assert validated.observation.high is None
    assert validated.observation.low is None
    assert validated.observation.close is None
    assert ingest.accepted == 1
    assert ingest.projected_price_rows == 0
    assert connection.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 0
    stored = connection.execute(
        "SELECT kind, last, open, high, low, close FROM market_observations"
    ).fetchone()
    assert dict(stored) == {
        "kind": "QUOTE",
        "last": "226.01",
        "open": None,
        "high": None,
        "low": None,
        "close": None,
    }
    connection.close()


@pytest.mark.parametrize(
    ("payload", "expected_reason"),
    [
        (_quote_payload(t=0), "INVALID_TIMESTAMP"),
        (_quote_payload(c=0), "NON_POSITIVE"),
        (_quote_payload(t=1786982760), "FUTURE_TIMESTAMP"),
    ],
)
def test_finnhub_quote_timestamp_and_price_fail_through_shared_validator(
    payload: dict[str, object],
    expected_reason: str,
) -> None:
    connection, listing_id = _initialize_connection()
    provider = _provider(connection, lambda _request: _json_response(payload))
    listing = _listing(connection, listing_id)

    envelope = provider.fetch_quote(listing, NOW, bypass_cache=True)
    result = MarketObservationService().validate(listing, envelope, NOW)

    assert isinstance(result, ObservationRejection)
    assert result.reason_code == expected_reason
    connection.close()


def test_finnhub_no_data_rejection_is_resolved_only_by_later_valid_quote() -> None:
    connection, listing_id = _initialize_connection()
    payloads = [
        json.loads(
            (FIXTURE_DIR / "finnhub_quote_no_data.json").read_text(encoding="utf-8")
        ),
        _quote_payload(),
    ]
    provider = _provider(
        connection,
        lambda _request: _json_response(payloads.pop(0)),
    )
    listing = _listing(connection, listing_id)

    no_data = provider.fetch_quote(listing, NOW, bypass_cache=True)
    rejected = MarketObservationService().ingest_batch(connection, [no_data], NOW)
    connection.commit()
    rejection = connection.execute(
        """
        SELECT id, provider, capability, operation, reason_code
        FROM market_data_rejections
        """
    ).fetchone()
    eod = MarketObservationService().ingest_batch(
        connection,
        [_eod_envelope(listing_id)],
        NOW,
    )
    connection.commit()
    assert eod.accepted == 1
    assert connection.execute(
        """
        SELECT COUNT(*)
        FROM market_data_rejection_resolutions
        WHERE rejection_id = ?
        """,
        (rejection["id"],),
    ).fetchone()[0] == 0
    valid = provider.fetch_quote(listing, NOW, bypass_cache=True)
    accepted = MarketObservationService().ingest_batch(connection, [valid], NOW)

    assert rejected.rejected == 1
    assert dict(rejection) == {
        "id": rejection["id"],
        "provider": "finnhub",
        "capability": "QUOTE",
        "operation": "finnhub_quote",
        "reason_code": "PROVIDER_NO_DATA",
    }
    assert accepted.accepted == 1
    assert accepted.resolved_rejections == 1
    assert connection.execute(
        """
        SELECT COUNT(*)
        FROM market_data_rejection_resolutions
        WHERE rejection_id = ?
        """,
        (rejection["id"],),
    ).fetchone()[0] == 1
    connection.close()


def test_finnhub_quote_429_sets_cooldown_and_stops_after_governed_retries() -> None:
    connection, listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(
            {"error": "rate limited"},
            429,
            **{"retry-after": "60", "x-ratelimit-remaining": "0"},
        )

    provider = _provider(connection, handler)

    with pytest.raises(ProviderError, match=r"finnhub:QUOTE:RATE_LIMITED"):
        provider.fetch_quote(_listing(connection, listing_id), NOW, bypass_cache=True)

    availability = provider.availability()
    assert calls == 3
    assert availability.state == "COOLDOWN"
    assert availability.reason_code == "RATE_LIMITED"
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE provider = 'finnhub'"
    ).fetchone()[0] == 3
    connection.close()


def test_finnhub_quote_budget_is_55_physical_requests_per_minute() -> None:
    connection, listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(_quote_payload())

    provider = _provider(connection, handler)
    listing = _listing(connection, listing_id)

    assert provider.policy == ProviderBudgetPolicy(55, None, None, 3)
    for _ in range(55):
        provider.fetch_quote(listing, NOW, bypass_cache=True)
    with pytest.raises(RateLimitExceeded, match=r"finnhub:QUOTE:BUDGET_EXHAUSTED"):
        provider.fetch_quote(listing, NOW, bypass_cache=True)

    assert calls == 55
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'finnhub'"
    ).fetchone()[0] == 55
    connection.close()


def test_finnhub_quote_bypass_cache_preserves_fingerprint_quota_and_validation() -> None:
    connection, listing_id = _initialize_connection()
    payloads = [_quote_payload(), _quote_payload(c=226.5)]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(payloads.pop(0))

    provider = _provider(connection, handler)
    listing = _listing(connection, listing_id)

    first = provider.fetch_quote(listing, NOW)
    cached = provider.fetch_quote(listing, NOW)
    forced = provider.fetch_quote(listing, NOW, bypass_cache=True)
    refreshed = provider.fetch_quote(listing, NOW)

    assert calls == 2
    assert first.raw_fields["last"] == cached.raw_fields["last"] == 226.01
    assert forced.raw_fields["last"] == refreshed.raw_fields["last"] == 226.5
    assert isinstance(MarketObservationService().validate(listing, forced, NOW), ValidatedObservation)
    log = connection.execute(
        """
        SELECT COUNT(DISTINCT request_fingerprint) AS fingerprints,
               SUM(CASE WHEN outcome = 'SUCCEEDED' THEN 1 ELSE 0 END) AS succeeded
        FROM provider_request_log
        WHERE provider = 'finnhub'
        """
    ).fetchone()
    assert tuple(log) == (1, 2)
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'finnhub'"
    ).fetchone()[0] == 2
    connection.close()


def test_finnhub_quote_force_requests_remain_inflight_deduplicated(tmp_path: Path) -> None:
    database_path = tmp_path / "finnhub-inflight.db"
    setup, listing_id = _initialize_connection(path=database_path)
    setup.close()
    first_connection = _open_connection(database_path)
    second_connection = _open_connection(database_path)
    calls = 0
    started = threading.Event()
    release = threading.Event()

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=5)
        return _json_response(_quote_payload())

    settings = replace(get_settings(), enable_real_data=True, finnhub_api_key=SENTINEL)
    shared_transport = SafeProviderTransport(
        allowed_hosts={"finnhub.io"},
        settings=settings,
        clock=lambda: NOW,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    providers = [
        FinnhubQuoteProvider(
            settings,
            connection,
            transport=shared_transport,
            clock=lambda: NOW,
            sleeper=lambda _delay: None,
        )
        for connection in (first_connection, second_connection)
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            providers[0].fetch_quote,
            _listing(first_connection, listing_id),
            NOW,
            True,
        )
        assert started.wait(timeout=5)
        second = pool.submit(
            providers[1].fetch_quote,
            _listing(second_connection, listing_id),
            NOW,
            True,
        )
        release.set()
        envelopes = [first.result(timeout=5), second.result(timeout=5)]

    assert calls == 1
    assert envelopes[0].raw_fields == envelopes[1].raw_fields
    with _open_connection(database_path) as verification:
        assert verification.execute(
            "SELECT calls_count FROM api_usage WHERE provider = 'finnhub'"
        ).fetchone()[0] == 1
        assert verification.execute(
            "SELECT COUNT(*) FROM provider_request_log WHERE provider = 'finnhub'"
        ).fetchone()[0] == 1
    first_connection.close()
    second_connection.close()


def test_same_finnhub_payload_at_different_clocks_deduplicates_without_revision() -> None:
    connection, listing_id = _initialize_connection()
    listing = _listing(connection, listing_id)
    first_now = NOW
    later_now = NOW + timedelta(minutes=31)
    first_provider = _provider(
        connection,
        lambda _request: _json_response(_quote_payload()),
        now=first_now,
    )
    later_provider = _provider(
        connection,
        lambda _request: _json_response(_quote_payload()),
        now=later_now,
    )

    first = first_provider.fetch_quote(listing, first_now, bypass_cache=True)
    first_result = MarketObservationService().ingest_batch(connection, [first], first_now)
    connection.commit()
    later = later_provider.fetch_quote(listing, later_now, bypass_cache=True)
    later_validation = MarketObservationService().validate(listing, later, later_now)
    later_result = MarketObservationService().ingest_batch(connection, [later], later_now)

    assert first_result.accepted == 1
    assert isinstance(later_validation, ValidatedObservation)
    assert later_validation.effective_quality == "stale"
    assert later_result.duplicates == 1
    assert later_result.revisions == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM market_observations WHERE provider = 'finnhub'"
    ).fetchone()[0] == 1
    connection.close()


def test_market_data_service_ingests_finnhub_quote_without_price_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, listing_id = _initialize_connection()
    calls: list[dict[str, object]] = []

    def fetch_quote(self, listing, now, bypass_cache=False):  # noqa: ANN001, ANN202
        calls.append({"listing": dict(listing), "now": now, "bypass_cache": bypass_cache})
        return _quote_envelope(
            listing_id,
            provider_observed_at=now - timedelta(minutes=1),
            label="service valid quote",
        )

    monkeypatch.setattr(FinnhubQuoteProvider, "fetch_quote", fetch_quote)
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", SENTINEL)
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "ACME", force=True)
    finally:
        get_settings.cache_clear()

    assert result["provider"] == "finnhub"
    assert result["rows_inserted"] == 0
    assert result["rows_updated"] == 0
    assert result["used_fallback"] is False
    assert calls[0]["bypass_cache"] is True
    assert calls[0]["listing"]["provider_symbol"] == "ACME"
    assert calls[0]["listing"]["mic"] == "XNAS"
    assert connection.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 0
    assert connection.execute(
        "SELECT kind FROM market_observations WHERE provider = 'finnhub'"
    ).fetchone()[0] == "QUOTE"
    connection.close()


@pytest.mark.parametrize(
    "failure",
    [
        RateLimitExceeded("finnhub:QUOTE:BUDGET_EXHAUSTED"),
        ProviderError("finnhub:QUOTE:RETRY_EXHAUSTED"),
    ],
)
def test_us_quote_failure_falls_back_only_to_fresh_quote_same_listing(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    connection, listing_id = _initialize_connection()
    service_now = datetime.now(UTC)
    observation_service = MarketObservationService()
    observation_service.ingest_batch(
        connection,
        [
            _quote_envelope(
                listing_id,
                provider_observed_at=service_now - timedelta(minutes=2),
                label=f"fresh fallback {type(failure).__name__}",
            ),
            replace(
                _eod_envelope(listing_id),
                received_at=service_now,
                provider_observed_at=service_now - timedelta(hours=4),
            ),
        ],
        service_now,
    )
    connection.commit()

    def fail(self, listing, now, bypass_cache=False):  # noqa: ANN001, ANN202
        raise failure

    monkeypatch.setattr(FinnhubQuoteProvider, "fetch_quote", fail)
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", SENTINEL)
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "ACME")
    finally:
        get_settings.cache_clear()

    event = connection.execute(
        """
        SELECT observation.capability, event.requested_provider,
               event.actual_provider, event.fallback_reason
        FROM market_data_selection_events AS event
        JOIN market_observations AS observation
          ON observation.id = event.selected_observation_id
        ORDER BY event.id DESC
        LIMIT 1
        """
    ).fetchone()
    assert result["used_fallback"] is True
    assert dict(event) == {
        "capability": "QUOTE",
        "requested_provider": "finnhub",
        "actual_provider": "finnhub",
        "fallback_reason": "LAST_GOOD",
    }
    connection.close()


def test_missing_key_does_not_fallback_to_stale_quote_or_fresh_eod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, listing_id = _initialize_connection()
    service_now = datetime.now(UTC)
    eod = replace(
        _eod_envelope(listing_id),
        received_at=service_now,
        provider_observed_at=service_now - timedelta(hours=4),
    )
    MarketObservationService().ingest_batch(
        connection,
        [
            _quote_envelope(
                listing_id,
                provider_observed_at=service_now - timedelta(minutes=31),
                label="stale quote is forbidden fallback",
            ),
            eod,
        ],
        service_now,
    )
    connection.commit()
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", "")
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "ACME")
    finally:
        get_settings.cache_clear()

    assert result["provider"] == "finnhub"
    assert result["used_fallback"] is True
    assert connection.execute(
        "SELECT COUNT(*) FROM market_data_selection_events"
    ).fetchone()[0] == 0
    connection.close()


def test_finnhub_no_data_service_scope_persists_rejection_and_uses_fresh_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, listing_id = _initialize_connection()
    service_now = datetime.now(UTC)
    MarketObservationService().ingest_batch(
        connection,
        [
            _quote_envelope(
                listing_id,
                provider_observed_at=service_now - timedelta(minutes=2),
                label="fresh quote before no data",
            )
        ],
        service_now,
    )
    connection.commit()

    def no_data(self, listing, now, bypass_cache=False):  # noqa: ANN001, ANN202
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider="finnhub",
            capability="QUOTE",
            operation="finnhub_quote",
            received_at=now,
            provider_observed_at=None,
            timezone=None,
            session=None,
            currency=None,
            source_quality=None,
            kind=None,
            raw_fields={"reason_code": "PROVIDER_NO_DATA"},
            raw_payload_sha256=_payload_hash("service no data"),
        )

    monkeypatch.setattr(FinnhubQuoteProvider, "fetch_quote", no_data)
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", SENTINEL)
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "ACME")
    finally:
        get_settings.cache_clear()

    rejection = connection.execute(
        """
        SELECT provider, capability, operation, reason_code
        FROM market_data_rejections
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    assert result["used_fallback"] is True
    assert dict(rejection) == {
        "provider": "finnhub",
        "capability": "QUOTE",
        "operation": "finnhub_quote",
        "reason_code": "PROVIDER_NO_DATA",
    }
    assert connection.execute(
        "SELECT COUNT(*) FROM market_data_selection_events"
    ).fetchone()[0] == 1
    connection.close()
