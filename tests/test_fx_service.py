from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.config import Settings, get_settings
from backend.app.database import SCHEMA
from backend.app.services.fx_service import ECB_DAILY_URL, FXRateUnavailable, FXService
from backend.scripts.seed_database import _seed_fx_rates

ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope
    xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
    xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-08-14">
      <Cube currency="USD" rate="1.25"/>
      <Cube currency="GBP" rate="0.8"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@pytest.fixture
def connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    try:
        yield connection
    finally:
        connection.close()


def _insert_rate(
    connection: sqlite3.Connection,
    from_currency: str,
    to_currency: str,
    rate: float,
    observed_at: str,
    provider: str = "test-provider",
    quality: str = "reference",
) -> None:
    connection.execute(
        """
        INSERT INTO fx_rates (
            from_currency, to_currency, rate, observed_at, provider, quality
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (from_currency, to_currency, rate, observed_at, provider, quality),
    )


def test_get_rate_returns_eur_identity_without_cached_data(connection) -> None:
    quote = FXService().get_rate(connection, " eur ")

    assert quote.from_currency == "EUR"
    assert quote.to_currency == "EUR"
    assert quote.rate == 1.0


def test_get_rate_returns_latest_cached_direct_quote(connection) -> None:
    today = datetime.now(UTC).date()
    _insert_rate(connection, "USD", "EUR", 0.75, (today - timedelta(days=1)).isoformat())
    _insert_rate(connection, "USD", "EUR", 0.8, today.isoformat())

    quote = FXService().get_rate(connection, "usd")

    assert quote.from_currency == "USD"
    assert quote.to_currency == "EUR"
    assert quote.rate == 0.8
    assert quote.observed_at == today.isoformat()
    assert quote.provider == "test-provider"
    assert quote.quality == "reference"


def test_get_rate_uses_reciprocal_when_only_inverse_quote_is_cached(connection) -> None:
    today = datetime.now(UTC).date().isoformat()
    _insert_rate(connection, "EUR", "USD", 1.25, today)

    quote = FXService().get_rate(connection, "USD", "EUR")

    assert quote.from_currency == "USD"
    assert quote.to_currency == "EUR"
    assert quote.rate == pytest.approx(0.8)
    assert quote.observed_at == today
    assert quote.provider == "test-provider"
    assert quote.quality == "reference"


def test_get_rate_marks_an_observed_quote_as_stale_without_inventing_a_rate(
    connection,
    monkeypatch,
) -> None:
    observed_at = (datetime.now(UTC).date() - timedelta(days=8)).isoformat()
    _insert_rate(connection, "USD", "EUR", 0.8125, observed_at)
    monkeypatch.setenv("ECB_FX_MAX_AGE_DAYS", "7")
    get_settings.cache_clear()
    try:
        quote = FXService().get_rate(connection, "USD")
    finally:
        get_settings.cache_clear()

    assert quote.rate == 0.8125
    assert quote.observed_at == observed_at
    assert quote.provider == "test-provider"
    assert quote.quality == "stale"


def test_get_rate_raises_when_neither_direct_nor_inverse_quote_exists(connection) -> None:
    with pytest.raises(FXRateUnavailable, match="CHF/EUR"):
        FXService().get_rate(connection, "CHF")


def test_refresh_ecb_stores_reciprocal_reference_rates_from_registered_xml(connection) -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=ECB_XML, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        inserted = FXService().refresh_ecb(connection, client=client)

    assert inserted == 2
    assert requested_urls == [ECB_DAILY_URL]
    rows = connection.execute(
        """
        SELECT from_currency, to_currency, rate, observed_at, provider, quality, ingested_at
        FROM fx_rates
        ORDER BY from_currency
        """
    ).fetchall()
    assert [tuple(row[:6]) for row in rows] == [
        ("GBP", "EUR", 1.25, "2026-08-14", "ecb", "reference"),
        ("USD", "EUR", 0.8, "2026-08-14", "ecb", "reference"),
    ]
    assert all(row["ingested_at"] for row in rows)


def test_refresh_ecb_keeps_cached_observations_idempotent(connection) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=ECB_XML, request=request))

    with httpx.Client(transport=transport) as client:
        assert FXService().refresh_ecb(connection, client=client) == 2
        assert FXService().refresh_ecb(connection, client=client) == 0

    assert connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 2


def test_refresh_ecb_checks_http_status(connection) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))

    with httpx.Client(transport=transport) as client, pytest.raises(httpx.HTTPStatusError):
        FXService().refresh_ecb(connection, client=client)


def test_refresh_ecb_rejects_responses_larger_than_one_mib(connection) -> None:
    oversized = b"x" * ((1024 * 1024) + 1)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=oversized, request=request))

    with httpx.Client(transport=transport) as client, pytest.raises(ValueError, match="1 MiB"):
        FXService().refresh_ecb(connection, client=client)


def test_refresh_ecb_rejects_xml_entity_declarations(connection) -> None:
    xml_with_entity = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<Envelope><Cube><Cube time="2026-08-14"><Cube currency="USD" rate="1.25"/></Cube></Cube></Envelope>
"""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=xml_with_entity, request=request)
    )

    with httpx.Client(transport=transport) as client, pytest.raises(ValueError, match="entit"):
        FXService().refresh_ecb(connection, client=client)


def test_settings_reads_ecb_fx_max_age_days(monkeypatch) -> None:
    monkeypatch.setenv("ECB_FX_MAX_AGE_DAYS", "3")

    assert Settings.from_env().ecb_fx_max_age_days == 3


def test_seed_inserts_only_a_deterministic_usd_eur_quote(connection) -> None:
    before_seed = datetime.now(UTC).date().isoformat()
    _seed_fx_rates(connection)
    _seed_fx_rates(connection)
    after_seed = datetime.now(UTC).date().isoformat()

    rows = connection.execute(
        """
        SELECT from_currency, to_currency, rate, observed_at, provider, quality
        FROM fx_rates
        """
    ).fetchall()
    assert len(rows) == 1
    row = tuple(rows[0])
    assert row[:3] == ("USD", "EUR", 0.92)
    assert row[3] in {before_seed, after_seed}
    assert row[4:] == ("seed", "seed")
