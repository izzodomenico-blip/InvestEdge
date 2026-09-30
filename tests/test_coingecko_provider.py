from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.base import ProviderError, RateLimitExceeded
from backend.app.data_providers.coingecko import CoinGeckoProvider
from backend.app.data_providers.provider_registry import ProviderRegistry
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import SCHEMA, migrate_db
from backend.app.models.market_data import (
    MarketObservationEnvelope,
    ObservationRejection,
    ValidatedObservation,
)
from backend.app.services.instrument_service import InstrumentService
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.market_observation_service import MarketObservationService

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "market_data"
NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)
DEMO_KEY = "SENTINEL_COINGECKO_DEMO_HEADER_12345"


def _payload_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _json_response(
    payload: object,
    status_code: int = 200,
    **headers: str,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(
            json.dumps(payload, separators=(",", ":"), allow_nan=True).encode()
        ),
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
    currency: str = "EUR",
    coingecko_id: str | None = "bitcoin",
    path: Path | None = None,
) -> tuple[sqlite3.Connection, int]:
    connection = _open_connection(path)
    connection.executescript(SCHEMA)
    migrate_db(connection)
    instrument_id = int(
        connection.execute(
            """
            INSERT INTO instruments (
                canonical_name, instrument_type, asset_class, source, source_date
            )
            VALUES ('Bitcoin', 'CRYPTO', 'CRYPTO', 'test', '2026-08-17')
            """
        ).lastrowid
    )
    listing_id = int(
        connection.execute(
            """
            INSERT INTO instrument_listings (
                instrument_id, ticker, mic, venue_name, currency, timezone,
                source, source_date
            )
            VALUES (?, 'BTC', NULL, NULL, ?, 'UTC', 'test', '2026-08-17')
            """,
            (instrument_id, currency),
        ).lastrowid
    )
    connection.execute(
        """
        INSERT INTO assets (
            symbol, name, asset_type, currency, risk_level, instrument_listing_id
        )
        VALUES ('BTC', 'Bitcoin', 'crypto', ?, 'very_high', ?)
        """,
        (currency, listing_id),
    )
    if coingecko_id is not None:
        identifier_id = int(
            connection.execute(
                """
                INSERT INTO instrument_identifiers (
                    scheme, normalized_value, scope, instrument_id, listing_id
                )
                VALUES ('COINGECKO_ID', ?, 'INSTRUMENT', ?, NULL)
                """,
                (coingecko_id, instrument_id),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO instrument_identifier_attestations (
                identifier_id, source, observed_at, evidence_hash
            )
            VALUES (?, 'test', ?, ?)
            """,
            (identifier_id, NOW.isoformat(), _payload_hash("coingecko identity")),
        )
    connection.commit()
    return connection, listing_id


def _listing(connection: sqlite3.Connection, listing_id: int) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT listing.*, instrument.instrument_type,
               identifier.normalized_value AS coingecko_id
        FROM instrument_listings AS listing
        JOIN instruments AS instrument ON instrument.id = listing.instrument_id
        LEFT JOIN instrument_identifiers AS identifier
          ON identifier.instrument_id = instrument.id
         AND identifier.scheme = 'COINGECKO_ID'
        WHERE listing.id = ?
        """,
        (listing_id,),
    ).fetchone()
    assert row is not None
    return dict(row)


def _provider(
    connection: sqlite3.Connection,
    handler,  # noqa: ANN001
    *,
    key: str | None = DEMO_KEY,
    now: datetime = NOW,
) -> CoinGeckoProvider:
    settings = replace(
        get_settings(),
        enable_real_data=True,
        coingecko_api_key=key,
    )
    transport = SafeProviderTransport(
        allowed_hosts={"api.coingecko.com"},
        settings=settings,
        clock=lambda: now,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    return CoinGeckoProvider(
        settings,
        connection,
        transport=transport,
        clock=lambda: now,
        sleeper=lambda _delay: None,
    )


def _eod_envelope(
    listing_id: int,
    *,
    provider: str = "coingecko",
    currency: str = "EUR",
    observed_at: datetime = NOW - timedelta(days=5),
    label: str = "coingecko stale fallback",
) -> MarketObservationEnvelope:
    return MarketObservationEnvelope(
        listing_id=listing_id,
        provider=provider,
        capability="EOD",
        operation="coingecko_market_chart",
        received_at=NOW,
        provider_observed_at=observed_at,
        timezone="UTC",
        session="24X7",
        currency=currency,
        source_quality="eod",
        kind="BAR",
        raw_fields={"close": "60000", "volume": "1000"},
        raw_payload_sha256=_payload_hash(label),
    )


def test_crypto_identity_registry_uses_explicit_coingecko_id_not_ticker() -> None:
    connection, listing_id = _initialize_connection(coingecko_id="bitcoin")
    registry = ProviderRegistry(
        replace(get_settings(), enable_real_data=True),
        connection,
    )

    eod = registry.providers_for(connection, listing_id, "EOD")
    quote = registry.providers_for(connection, listing_id, "QUOTE")

    assert [asdict(match) for match in eod] == [
        {
            "provider": "coingecko",
            "capability": "EOD",
            "listing_id": listing_id,
            "provider_symbol": "bitcoin",
            "currency": "EUR",
            "priority": 10,
        }
    ]
    assert quote[0].provider_symbol == "bitcoin"
    assert quote[0].provider_symbol != "BTC"
    connection.close()


def test_crypto_identity_registry_rejects_ticker_only_and_unsupported_currency() -> None:
    missing, missing_listing_id = _initialize_connection(coingecko_id=None)
    unsupported, unsupported_listing_id = _initialize_connection(currency="GBP")

    assert ProviderRegistry(get_settings(), missing).providers_for(
        missing, missing_listing_id, "EOD"
    ) == ()
    assert ProviderRegistry(get_settings(), unsupported).providers_for(
        unsupported, unsupported_listing_id, "QUOTE"
    ) == ()
    missing.close()
    unsupported.close()


def test_coingecko_daily_uses_fixed_id_endpoint_currency_and_demo_header_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection, listing_id = _initialize_connection()
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["path"] = request.url.path
        observed["params"] = dict(request.url.params)
        observed["key"] = request.headers.get("x-cg-demo-api-key")
        return _json_response(_fixture("coingecko_market_chart.json"))

    provider = _provider(connection, handler)
    envelopes = provider.fetch_daily(_listing(connection, listing_id), 2)

    assert observed == {
        "url": (
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=eur&days=2"
        ),
        "path": "/api/v3/coins/bitcoin/market_chart",
        "params": {"vs_currency": "eur", "days": "2"},
        "key": DEMO_KEY,
    }
    persisted = "\n".join(
        str(value)
        for row in connection.execute(
            """
            SELECT cache_key, provider, endpoint, request_url_hash FROM api_cache
            UNION ALL
            SELECT reservation_id, provider, operation, request_fingerprint
            FROM provider_request_log
            """
        )
        for value in row
        if value is not None
    )
    assert len(envelopes) == 2
    assert DEMO_KEY not in str(observed["url"])
    assert DEMO_KEY not in persisted
    assert DEMO_KEY not in caplog.text
    connection.close()


def test_coingecko_keyless_quote_sends_no_credential_or_secret_query() -> None:
    connection, listing_id = _initialize_connection(currency="USD")
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["key"] = request.headers.get("x-cg-demo-api-key")
        observed["params"] = dict(request.url.params)
        return _json_response(_fixture("coingecko_simple_price.json"))

    provider = _provider(connection, handler, key=None)
    envelope = provider.fetch_quote(_listing(connection, listing_id), NOW)

    assert observed == {
        "url": (
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin&vs_currencies=usd&include_last_updated_at=true"
        ),
        "key": None,
        "params": {
            "ids": "bitcoin",
            "vs_currencies": "usd",
            "include_last_updated_at": "true",
        },
    }
    assert envelope.raw_fields == {"last": 71890.12}
    assert envelope.currency == "USD"
    connection.close()


def test_coingecko_market_chart_ms_timestamp_and_same_day_samples_choose_last() -> None:
    # CoinGecko daily points at 00:00 UTC close the previous UTC day: the bar is
    # labelled with the completed day (Stooq convention: 00:00 of the bar date).
    connection, listing_id = _initialize_connection()
    provider = _provider(
        connection,
        lambda _request: _json_response(_fixture("coingecko_market_chart.json")),
    )
    listing = _listing(connection, listing_id)

    envelopes = provider.fetch_daily(listing, 2)
    results = [MarketObservationService().validate(listing, item, NOW) for item in envelopes]
    ingest = MarketObservationService().ingest_batch(connection, envelopes, NOW)

    assert [item.provider_observed_at for item in envelopes] == [
        datetime(2026, 8, 15, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    ]
    assert [item.raw_fields for item in envelopes] == [
        {"close": 61000.0, "adjusted_close": 61000.0, "volume": 1000000000.0},
        {"close": 61500.25, "adjusted_close": 61500.25, "volume": 1300000000.0},
    ]
    assert all(item.timezone == "UTC" and item.session == "24X7" for item in envelopes)
    assert all(isinstance(item, ValidatedObservation) for item in results)
    assert ingest.accepted == 2
    assert [
        tuple(row)
        for row in connection.execute("SELECT date, close FROM price_history ORDER BY date")
    ] == [("2026-08-15", 61000.0), ("2026-08-16", 61500.25)]
    connection.close()


def test_coingecko_market_chart_excludes_incomplete_current_utc_day() -> None:
    connection, listing_id = _initialize_connection()
    payload = {
        "prices": [[1786924800000, 61500.25], [1786978800000, 61800.0]],
        "total_volumes": [[1786924800000, 1300000000.0], [1786978800000, 900000000.0]],
    }
    provider = _provider(connection, lambda _request: _json_response(payload))
    listing = _listing(connection, listing_id)

    envelopes = provider.fetch_daily(listing, 2)

    assert [item.provider_observed_at for item in envelopes] == [
        datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    ]
    assert envelopes[0].raw_fields["close"] == 61500.25
    connection.close()


def test_coingecko_market_chart_with_only_current_day_is_provider_no_data() -> None:
    connection, listing_id = _initialize_connection()
    payload = {
        "prices": [[1786960800000, 61700.0], [1786978800000, 61800.0]],
        "total_volumes": [[1786960800000, 800000000.0], [1786978800000, 900000000.0]],
    }
    provider = _provider(connection, lambda _request: _json_response(payload))
    listing = _listing(connection, listing_id)

    envelopes = provider.fetch_daily(listing, 1)
    result = MarketObservationService().validate(listing, envelopes[0], NOW)

    assert len(envelopes) == 1
    assert isinstance(result, ObservationRejection)
    assert result.reason_code == "PROVIDER_NO_DATA"
    connection.close()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "prices": [[1786924800000, 61500.25]],
            "total_volumes": [],
        },
        {
            "prices": [[1786924800000, 61500.25]],
            "total_volumes": [[1786924801000, 1300000000.0]],
        },
    ],
)
def test_coingecko_market_chart_rejects_misaligned_arrays(
    payload: dict[str, object],
) -> None:
    connection, listing_id = _initialize_connection()
    provider = _provider(connection, lambda _request: _json_response(payload))
    listing = _listing(connection, listing_id)

    envelopes = provider.fetch_daily(listing, 1, bypass_cache=True)
    result = MarketObservationService().validate(listing, envelopes[0], NOW)

    assert len(envelopes) == 1
    assert isinstance(result, ObservationRejection)
    assert result.reason_code == "MALFORMED_PAYLOAD"
    connection.close()


def test_coingecko_empty_market_chart_is_provider_no_data() -> None:
    connection, listing_id = _initialize_connection()
    provider = _provider(
        connection,
        lambda _request: _json_response({"prices": [], "total_volumes": []}),
    )
    listing = _listing(connection, listing_id)

    envelopes = provider.fetch_daily(listing, 1)
    result = MarketObservationService().validate(listing, envelopes[0], NOW)

    assert isinstance(result, ObservationRejection)
    assert result.reason_code == "PROVIDER_NO_DATA"
    connection.close()


@pytest.mark.parametrize(
    ("price", "expected_reason"),
    [(0, "NON_POSITIVE"), (float("inf"), "NON_FINITE")],
)
def test_coingecko_quote_zero_and_nonfinite_fail_shared_validation(
    price: float,
    expected_reason: str,
) -> None:
    connection, listing_id = _initialize_connection()
    payload = {
        "bitcoin": {
            "eur": price,
            "last_updated_at": 1786982340,
        }
    }
    provider = _provider(connection, lambda _request: _json_response(payload))
    listing = _listing(connection, listing_id)

    envelope = provider.fetch_quote(listing, NOW, bypass_cache=True)
    result = MarketObservationService().validate(listing, envelope, NOW)

    assert isinstance(result, ObservationRejection)
    assert result.reason_code == expected_reason
    connection.close()


def test_coingecko_rejects_unsupported_listing_currency_before_transport() -> None:
    connection, listing_id = _initialize_connection(currency="GBP")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(_fixture("coingecko_simple_price.json"))

    provider = _provider(connection, handler)

    with pytest.raises(ProviderError, match=r"coingecko:QUOTE:UNSUPPORTED_CURRENCY"):
        provider.fetch_quote(_listing(connection, listing_id), NOW)

    assert calls == 0
    connection.close()


def test_coingecko_429_sets_cooldown_after_governed_retries() -> None:
    connection, listing_id = _initialize_connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(
            _fixture("coingecko_rate_limit.json"),
            429,
            **{"retry-after": "30", "x-ratelimit-remaining": "0"},
        )

    provider = _provider(connection, handler, key=None)

    with pytest.raises(RateLimitExceeded, match=r"coingecko:EOD:BUDGET_EXHAUSTED"):
        provider.fetch_daily(_listing(connection, listing_id), 1, bypass_cache=True)

    availability = provider.availability()
    assert calls == 1
    assert availability.state == "COOLDOWN"
    assert availability.reason_code == "RATE_LIMITED"
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE provider = 'coingecko'"
    ).fetchone()[0] == 1
    connection.close()


def test_coingecko_daily_bypass_cache_preserves_fingerprint_budget_and_validation() -> None:
    connection, listing_id = _initialize_connection()
    first_payload = _fixture("coingecko_market_chart.json")
    second_payload = _fixture("coingecko_market_chart.json")
    second_payload["prices"][-1][1] = 62000.0  # type: ignore[index]
    payloads = [first_payload, second_payload]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(payloads.pop(0))

    provider = _provider(connection, handler)
    listing = _listing(connection, listing_id)

    first = provider.fetch_daily(listing, 2)
    cached = provider.fetch_daily(listing, 2)
    forced = provider.fetch_daily(listing, 2, bypass_cache=True)
    refreshed = provider.fetch_daily(listing, 2)

    assert calls == 2
    assert first[-1].raw_fields["close"] == cached[-1].raw_fields["close"] == 61500.25
    assert forced[-1].raw_fields["close"] == refreshed[-1].raw_fields["close"] == 62000.0
    assert isinstance(MarketObservationService().validate(listing, forced[-1], NOW), ValidatedObservation)
    log = connection.execute(
        """
        SELECT COUNT(DISTINCT request_fingerprint),
               SUM(CASE WHEN outcome = 'SUCCEEDED' THEN 1 ELSE 0 END)
        FROM provider_request_log
        WHERE provider = 'coingecko'
        """
    ).fetchone()
    assert tuple(log) == (1, 2)
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'coingecko'"
    ).fetchone()[0] == 2
    connection.close()


def test_coingecko_quote_force_requests_remain_inflight_deduplicated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "coingecko-inflight.db"
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
        return _json_response(_fixture("coingecko_simple_price.json"))

    settings = replace(get_settings(), enable_real_data=True, coingecko_api_key=None)
    shared_transport = SafeProviderTransport(
        allowed_hosts={"api.coingecko.com"},
        settings=settings,
        clock=lambda: NOW,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    providers = [
        CoinGeckoProvider(
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
            "SELECT calls_count FROM api_usage WHERE provider = 'coingecko'"
        ).fetchone()[0] == 1
    first_connection.close()
    second_connection.close()


def test_curated_crypto_backfill_is_idempotent_and_does_not_invent_mic_or_isin() -> None:
    connection = _open_connection()
    connection.executescript(SCHEMA)
    migrate_db(connection)
    connection.execute(
        """
        INSERT INTO assets (
            symbol, name, asset_type, currency, isin, created_at, updated_at
        )
        VALUES ('BTC', 'Bitcoin', 'crypto', 'EUR', NULL, ?, ?)
        """,
        (NOW.isoformat(), NOW.isoformat()),
    )
    InstrumentService.backfill_active_assets(connection)

    first = InstrumentService.backfill_curated_crypto_ids(connection, NOW)
    second = InstrumentService.backfill_curated_crypto_ids(
        connection,
        NOW + timedelta(days=1),
    )

    row = connection.execute(
        """
        SELECT identifier.normalized_value, attestation.source,
               attestation.observed_at, listing.timezone, listing.mic, asset.isin
        FROM assets AS asset
        JOIN instrument_listings AS listing ON listing.id = asset.instrument_listing_id
        JOIN instrument_identifiers AS identifier
          ON identifier.instrument_id = listing.instrument_id
         AND identifier.scheme = 'COINGECKO_ID'
        JOIN instrument_identifier_attestations AS attestation
          ON attestation.identifier_id = identifier.id
        WHERE asset.symbol = 'BTC'
        """
    ).fetchone()
    assert first == 1
    assert second == 0
    assert dict(row) == {
        "normalized_value": "bitcoin",
        "source": "LEGACY_CURATED",
        "observed_at": NOW.isoformat(),
        "timezone": "UTC",
        "mic": None,
        "isin": None,
    }
    assert connection.execute(
        "SELECT COUNT(*) FROM instrument_identifier_attestations"
    ).fetchone()[0] == 1
    connection.close()


def test_curated_crypto_backfill_requires_unique_active_symbol_and_never_guesses_name() -> None:
    connection = _open_connection()
    connection.executescript(SCHEMA)
    migrate_db(connection)
    connection.executemany(
        """
        INSERT INTO assets (symbol, name, asset_type, currency, created_at, updated_at)
        VALUES (?, ?, ?, 'EUR', ?, ?)
        """,
        [
            ("BTC", "Bitcoin", "crypto", NOW.isoformat(), NOW.isoformat()),
            ("BTC", "Unrelated stock", "stock", NOW.isoformat(), NOW.isoformat()),
            ("DOGE", "Bitcoin", "crypto", NOW.isoformat(), NOW.isoformat()),
        ],
    )
    InstrumentService.backfill_active_assets(connection)

    assert InstrumentService.backfill_curated_crypto_ids(connection, NOW) == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'COINGECKO_ID'"
    ).fetchone()[0] == 0
    connection.close()


def test_market_data_service_uses_coingecko_id_and_projects_daily_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, listing_id = _initialize_connection()
    calls: list[dict[str, object]] = []

    def fetch_daily(self, listing, days, bypass_cache=False):  # noqa: ANN001, ANN202
        calls.append(
            {
                "listing": dict(listing),
                "days": days,
                "bypass_cache": bypass_cache,
            }
        )
        return [
            replace(
                _eod_envelope(
                    listing_id,
                    observed_at=datetime.now(UTC) - timedelta(hours=1),
                    label="service coingecko daily",
                ),
                received_at=datetime.now(UTC),
            )
        ]

    monkeypatch.setattr(CoinGeckoProvider, "fetch_daily", fetch_daily)
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "BTC", force=True)
    finally:
        get_settings.cache_clear()

    assert result["provider"] == "coingecko"
    assert result["used_fallback"] is False
    assert calls[0]["listing"]["coingecko_id"] == "bitcoin"
    assert calls[0]["listing"]["coingecko_id"] != calls[0]["listing"].get("ticker")
    assert calls[0]["bypass_cache"] is True
    assert connection.execute(
        "SELECT COUNT(*) FROM price_history WHERE provider = 'coingecko'"
    ).fetchone()[0] == 1
    connection.close()


def test_coingecko_failure_selects_only_same_currency_coingecko_stale_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, listing_id = _initialize_connection()
    service_now = datetime.now(UTC)
    stale = replace(
        _eod_envelope(
            listing_id,
            observed_at=service_now - timedelta(days=5),
            label="stale coingecko fallback",
        ),
        received_at=service_now,
    )
    other = replace(
        _eod_envelope(
            listing_id,
            provider="other",
            observed_at=service_now - timedelta(hours=1),
            label="newer incompatible provider",
        ),
        received_at=service_now,
        operation="other_daily",
    )
    MarketObservationService().ingest_batch(connection, [stale, other], service_now)
    connection.commit()

    def fail(self, listing, days, bypass_cache=False):  # noqa: ANN001, ANN202
        raise RateLimitExceeded("coingecko:EOD:BUDGET_EXHAUSTED")

    monkeypatch.setattr(CoinGeckoProvider, "fetch_daily", fail)
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "BTC")
    finally:
        get_settings.cache_clear()

    event = connection.execute(
        """
        SELECT event.actual_provider, event.fallback_reason, observation.currency
        FROM market_data_selection_events AS event
        JOIN market_observations AS observation
          ON observation.id = event.selected_observation_id
        ORDER BY event.id DESC
        LIMIT 1
        """
    ).fetchone()
    assert result["used_fallback"] is True
    assert dict(event) == {
        "actual_provider": "coingecko",
        "fallback_reason": "LAST_GOOD_STALE",
        "currency": "EUR",
    }
    connection.close()


def test_coingecko_fallback_never_selects_usd_for_eur_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, listing_id = _initialize_connection(currency="EUR")
    observed_at = NOW - timedelta(hours=1)
    connection.execute(
        """
        INSERT INTO market_observations (
            listing_id, provider, capability, operation, provider_observed_at,
            ingested_at, timezone, session, currency, delay_seconds,
            source_quality, effective_quality, kind, close, observation_hash,
            revision, created_at
        )
        VALUES (?, 'coingecko', 'EOD', 'coingecko_market_chart', ?, ?, 'UTC',
                '24X7', 'USD', 3600, 'eod', 'eod', 'BAR', '70000', ?, 1, ?)
        """,
        (
            listing_id,
            observed_at.isoformat(),
            NOW.isoformat(),
            _payload_hash("wrong currency stored observation"),
            NOW.isoformat(),
        ),
    )
    connection.commit()

    def fail(self, listing, days, bypass_cache=False):  # noqa: ANN001, ANN202
        raise ProviderError("coingecko:EOD:RETRY_EXHAUSTED")

    monkeypatch.setattr(CoinGeckoProvider, "fetch_daily", fail)
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    try:
        result = MarketDataService().refresh_asset_prices(connection, "BTC")
    finally:
        get_settings.cache_clear()

    assert result["used_fallback"] is True
    assert connection.execute(
        "SELECT COUNT(*) FROM market_data_selection_events"
    ).fetchone()[0] == 0
    connection.close()
