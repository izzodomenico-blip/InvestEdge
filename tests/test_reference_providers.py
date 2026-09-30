from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.base import ProviderError, RateLimitExceeded
from backend.app.data_providers.ecb import ECB_ALLOWED_HOSTS, EcbFxProvider
from backend.app.data_providers.fred import FredReferenceProvider
from backend.app.data_providers.provider_registry import ProviderRegistry
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import SCHEMA, migrate_db
from backend.app.services.fx_service import FXService
from backend.app.services.market_observation_service import MarketObservationService

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "market_data"
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
FRED_KEY = "SENTINEL_FRED_KEY_12345"


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    migrate_db(connection)
    return connection


def _csv_response(body: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(body),
        headers={"content-type": "text/csv"},
    )


def _ecb_csv() -> bytes:
    return (FIXTURE_DIR / "ecb_exr_usd_eur.csv").read_bytes()


def _ecb_provider(handler, *, now: datetime = NOW) -> EcbFxProvider:  # noqa: ANN001
    transport = SafeProviderTransport(
        allowed_hosts=ECB_ALLOWED_HOSTS,
        settings=get_settings(),
        clock=lambda: now,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    return EcbFxProvider(transport, sleeper=lambda _delay: None)


def _insert_rate(connection: sqlite3.Connection, rate: float, observed_at: str, provider: str = "ecb") -> None:
    connection.execute(
        """
        INSERT INTO fx_rates (from_currency, to_currency, rate, observed_at, ingested_at, provider, quality)
        VALUES ('USD', 'EUR', ?, ?, '2026-08-14T15:00:00+00:00', ?, 'reference')
        """,
        (rate, observed_at, provider),
    )
    # Il budget provider richiede una connessione senza transazione aperta.
    connection.commit()


def _fx_rows(connection: sqlite3.Connection) -> list[tuple[object, ...]]:
    return [
        tuple(row)
        for row in connection.execute(
            """
            SELECT from_currency, to_currency, rate, observed_at, provider, quality
            FROM fx_rates ORDER BY observed_at, id
            """
        )
    ]


def test_ecb_refresh_currency_stores_official_reciprocal_quote() -> None:
    connection = _connection()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _csv_response(_ecb_csv())

    result = FXService(ecb_provider=_ecb_provider(handler)).refresh_currency(connection, " usd ", now=NOW)

    assert result.status == "UPDATED"
    assert result.rows_written == 1
    assert (result.from_currency, result.to_currency, result.provider) == ("USD", "EUR", "ecb")
    assert result.observed_at == datetime(2026, 8, 14, tzinfo=UTC)
    assert result.ingested_at == NOW
    assert _fx_rows(connection) == [("USD", "EUR", 0.8, "2026-08-14", "ecb", "reference")]
    assert len(requests) == 1
    assert requests[0].url.host == "data-api.ecb.europa.eu"
    assert requests[0].url.path == "/service/data/EXR/D.USD.EUR.SP00.A"
    assert dict(requests[0].url.params) == {"format": "csvdata", "lastNObservations": "2"}
    assert "if-modified-since" not in requests[0].headers
    log = connection.execute("SELECT provider, outcome FROM provider_request_log").fetchall()
    assert [tuple(row) for row in log] == [("ecb", "SUCCEEDED")]


def test_ecb_refresh_currency_is_idempotent_and_reuses_cache_before_reservation() -> None:
    connection = _connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _csv_response(_ecb_csv())

    service = FXService(ecb_provider=_ecb_provider(handler))
    first = service.refresh_currency(connection, "USD", now=NOW)
    second = service.refresh_currency(connection, "USD", now=NOW)

    assert (first.status, second.status) == ("UPDATED", "UPDATED")
    assert calls == 1
    assert connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 1
    outcomes = [row["outcome"] for row in connection.execute("SELECT outcome FROM provider_request_log")]
    assert outcomes == ["SUCCEEDED", "CACHE_HIT"]


def test_ecb_not_modified_returns_last_persisted_row_without_writing() -> None:
    connection = _connection()
    _insert_rate(connection, 0.8, "2026-08-14")
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("if-modified-since"))
        return httpx.Response(304)

    result = FXService(ecb_provider=_ecb_provider(handler)).refresh_currency(connection, "USD", now=NOW)

    assert result.status == "NOT_MODIFIED"
    assert result.rows_written == 0
    assert result.observed_at == datetime(2026, 8, 14, tzinfo=UTC)
    assert result.ingested_at == datetime(2026, 8, 14, 15, 0, tzinfo=UTC)
    assert seen == ["Sat, 15 Aug 2026 00:00:00 GMT"]
    assert _fx_rows(connection) == [("USD", "EUR", 0.8, "2026-08-14", "ecb", "reference")]


def test_ecb_not_modified_without_previous_row_is_sanitized_failure() -> None:
    connection = _connection()
    provider = _ecb_provider(lambda _request: httpx.Response(304))

    with pytest.raises(ProviderError) as exc_info:
        FXService(ecb_provider=provider).refresh_currency(connection, "USD", now=NOW)

    assert str(exc_info.value) == "ecb:FX:NOT_MODIFIED_WITHOUT_BASELINE"
    assert "data-api" not in str(exc_info.value)
    assert _fx_rows(connection) == []


@pytest.mark.parametrize(
    ("obs_value", "reason"),
    [("", "MISSING_VALUE"), ("NaN", "MISSING_VALUE"), ("0", "INVALID_RATE"), ("-1.2", "INVALID_RATE")],
)
def test_ecb_invalid_values_never_replace_last_good_rate(obs_value: str, reason: str) -> None:
    connection = _connection()
    _insert_rate(connection, 0.8, "2026-08-14")
    body = (
        "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
        f"EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-08-15,{obs_value}\n"
    ).encode()
    provider = _ecb_provider(lambda _request: _csv_response(body))

    with pytest.raises(ProviderError) as exc_info:
        FXService(ecb_provider=provider).refresh_currency(connection, "USD", now=NOW)

    assert str(exc_info.value) == f"ecb:FX:{reason}"
    assert _fx_rows(connection) == [("USD", "EUR", 0.8, "2026-08-14", "ecb", "reference")]


@pytest.mark.parametrize("currency", ["EUR", "XYZ", "US1", "BGN"])
def test_ecb_rejects_currencies_outside_allowlist_before_transport(currency: str) -> None:
    connection = _connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _csv_response(_ecb_csv())

    with pytest.raises(ValueError, match="valuta"):
        FXService(ecb_provider=_ecb_provider(handler)).refresh_currency(connection, currency, now=NOW)

    assert calls == 0


def test_ecb_rate_limit_sets_cooldown_and_blocks_next_physical_call() -> None:
    connection = _connection()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"retry-after": "60", "content-type": "text/csv"})

    service = FXService(ecb_provider=_ecb_provider(handler))
    with pytest.raises(RateLimitExceeded):
        service.refresh_currency(connection, "USD", now=NOW)
    physical_calls = calls
    with pytest.raises(RateLimitExceeded):
        service.refresh_currency(connection, "USD", now=NOW)

    assert physical_calls >= 1
    assert calls == physical_calls
    outcomes = {row["outcome"] for row in connection.execute("SELECT outcome FROM provider_request_log")}
    assert "RATE_LIMITED" in outcomes
    assert _fx_rows(connection) == []


def test_ecb_quote_older_than_max_age_is_reported_stale() -> None:
    now = datetime.now(UTC)
    today = now.date()

    def body(day) -> bytes:  # noqa: ANN001
        return (
            "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
            f"EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,{day.isoformat()},1.25\n"
        ).encode()

    old_connection = _connection()
    old = FXService(
        ecb_provider=_ecb_provider(lambda _request: _csv_response(body(today - timedelta(days=10))), now=now)
    )
    fresh_connection = _connection()
    fresh = FXService(
        ecb_provider=_ecb_provider(lambda _request: _csv_response(body(today - timedelta(days=1))), now=now)
    )

    assert old.refresh_currency(old_connection, "USD", now=now).status == "UPDATED"
    assert fresh.refresh_currency(fresh_connection, "USD", now=now).status == "UPDATED"
    assert old.get_rate(old_connection, "USD").quality == "stale"
    assert fresh.get_rate(fresh_connection, "USD").quality == "reference"


def test_registry_exposes_governed_ecb_adapter_with_canonical_code() -> None:
    connection = _connection()
    registry = ProviderRegistry(get_settings(), connection)

    adapter = registry.ecb_fx_provider

    assert isinstance(adapter, EcbFxProvider)
    assert adapter.provider_code == "ecb"
    assert adapter.capability == "FX"
    assert adapter.transport.allowed_hosts == ECB_ALLOWED_HOSTS
    assert (adapter.policy.minute_limit, adapter.policy.daily_limit, adapter.policy.monthly_limit) == (5, 50, 500)


def _fred_provider(connection: sqlite3.Connection, *, key: str | None, handler=None) -> FredReferenceProvider:  # noqa: ANN001
    settings = replace(get_settings(), enable_real_data=True, fred_api_key=key)
    transport = SafeProviderTransport(
        allowed_hosts={"api.stlouisfed.org"},
        settings=settings,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler or (lambda _r: httpx.Response(500)))))
    return FredReferenceProvider(settings, connection, transport=transport)


def test_fred_availability_is_fail_closed_by_policy() -> None:
    connection = _connection()

    missing = _fred_provider(connection, key=None).availability()
    with_key = _fred_provider(connection, key=FRED_KEY)

    assert (missing.state, missing.reason_code) == ("DISABLED", "MISSING_CREDENTIAL")
    assert (with_key.availability().state, with_key.availability().reason_code) == (
        "DISABLED",
        "SECRET_IN_QUERY_POLICY",
    )
    assert "BULK_ONLY_POLICY" in with_key.capability_notes
    assert "REFERENCE_ONLY" in with_key.capability_notes
    assert with_key.capability == "REFERENCE"
    assert with_key.allowed_series == frozenset({"DGS10", "DGS2", "FEDFUNDS"})


def test_fred_never_calls_v1_or_v2_and_never_exposes_the_key() -> None:
    connection = _connection()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"observations": []})

    provider = _fred_provider(connection, key=FRED_KEY, handler=handler)
    with pytest.raises(ProviderError) as exc_info:
        provider.get_daily_prices("DGS10", force=True)

    assert calls == []
    assert str(exc_info.value) == "fred:REFERENCE:SECRET_IN_QUERY_POLICY"
    assert FRED_KEY not in str(exc_info.value)


def test_fred_btp10y_is_only_a_labelled_us_proxy() -> None:
    provider = _fred_provider(_connection(), key=None)

    metadata = provider.series_metadata("btp10y")

    assert metadata["series_id"] == "DGS10"
    assert metadata["label"] == "REFERENCE_ONLY/US_10Y_PROXY"
    assert "BTP" not in metadata["description"]
    assert "USA" in metadata["description"]
    assert provider.legacy_aliases == {"BTP10Y": "DGS10"}
    with pytest.raises(ProviderError):
        provider.series_metadata("SP500")


def test_fred_declares_attribution_and_series_rights() -> None:
    provider = _fred_provider(_connection(), key=None)

    assert "Federal Reserve Bank of St. Louis" in provider.attribution
    assert set(provider.series_rights) == set(provider.allowed_series)
    assert all(provider.series_rights.values())


def _fred_listing(connection: sqlite3.Connection) -> sqlite3.Row:
    instrument_id = connection.execute(
        """
        INSERT INTO instruments (canonical_name, instrument_type, asset_class, source, source_date)
        VALUES ('US Treasury 10Y yield (DGS10)', 'RATE', 'REFERENCE', 'test', '2026-08-16')
        """
    ).lastrowid
    listing_id = connection.execute(
        """
        INSERT INTO instrument_listings (
            instrument_id, ticker, mic, venue_name, currency, timezone, source, source_date
        )
        VALUES (?, 'DGS10', NULL, NULL, 'USD', 'America/New_York', 'test', '2026-08-16')
        """,
        (instrument_id,),
    ).lastrowid
    return connection.execute("SELECT * FROM instrument_listings WHERE id = ?", (listing_id,)).fetchone()


def test_fred_missing_value_is_rejected_and_resolved_by_later_local_value() -> None:
    connection = _connection()
    listing = _fred_listing(connection)
    provider = _fred_provider(connection, key=None)
    service = MarketObservationService()

    missing = provider.reference_envelopes(
        json.loads((FIXTURE_DIR / "fred_missing_value.json").read_text(encoding="utf-8")),
        listing,
        "DGS10",
        NOW,
    )
    first = service.ingest_batch(connection, missing, NOW)
    rejection = connection.execute(
        "SELECT provider, capability, reason_code FROM market_data_rejections"
    ).fetchone()

    valid = provider.reference_envelopes(
        json.loads((FIXTURE_DIR / "fred_series_observations.json").read_text(encoding="utf-8")),
        listing,
        "DGS10",
        NOW + timedelta(minutes=1),
    )
    second = service.ingest_batch(connection, valid, NOW + timedelta(minutes=1))

    assert (first.rejected, first.accepted) == (1, 0)
    assert tuple(rejection) == ("fred", "REFERENCE", "MISSING_VALUE")
    assert second.accepted == 2
    assert second.resolved_rejections == 1
    assert all(item.source_quality == "reference" for item in valid)
    assert second.projected_price_rows == 0
    assert connection.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 0
