from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from backend.app.config import Settings, get_settings
from backend.app.data_providers.base import ProviderError
from backend.app.data_providers.ecb import ECB_ALLOWED_HOSTS, EcbFxProvider
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import SCHEMA
from backend.app.lab.series import EurConverter
from backend.app.services.fx_service import ECB_DAILY_URL, FXRateUnavailable, FXService
from backend.scripts.seed_database import _seed_fx_rates

HISTORY_CSV = Path(__file__).parent / "fixtures" / "market_data" / "ecb_exr_usd_eur_history.csv"
HISTORY_NOW = datetime(2024, 1, 16, 12, 0, tzinfo=UTC)

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


def _xml_response(content: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(content),
        headers={"content-type": "text/xml"},
    )


def test_refresh_ecb_stores_reciprocal_reference_rates_from_registered_xml(connection) -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return _xml_response(ECB_XML)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        inserted = FXService().refresh_ecb(connection, client=client)

    assert inserted == 2
    assert requested_urls == [ECB_DAILY_URL]
    log = connection.execute("SELECT provider, outcome FROM provider_request_log").fetchall()
    assert [tuple(row) for row in log] == [("ecb", "SUCCEEDED")]
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
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _xml_response(ECB_XML)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert FXService().refresh_ecb(connection, client=client) == 2
        assert FXService().refresh_ecb(connection, client=client) == 0

    assert calls == 1
    assert connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 2


def test_refresh_ecb_checks_http_status(connection) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(404))

    with httpx.Client(transport=transport) as client, pytest.raises(ProviderError) as exc_info:
        FXService().refresh_ecb(connection, client=client)

    assert str(exc_info.value) == "ecb:FX:HTTP_404"
    assert connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 0


def test_refresh_ecb_rejects_responses_larger_than_one_mib(connection) -> None:
    oversized = b"x" * ((1024 * 1024) + 1)
    transport = httpx.MockTransport(lambda _request: _xml_response(oversized))

    with httpx.Client(transport=transport) as client, pytest.raises(ProviderError) as exc_info:
        FXService().refresh_ecb(connection, client=client)

    assert str(exc_info.value) == "ecb:FX:RESPONSE_TOO_LARGE"


def test_refresh_ecb_rejects_xml_entity_declarations(connection) -> None:
    xml_with_entity = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<Envelope><Cube><Cube time="2026-08-14"><Cube currency="USD" rate="1.25"/></Cube></Cube></Envelope>
"""
    transport = httpx.MockTransport(lambda _request: _xml_response(xml_with_entity))

    with httpx.Client(transport=transport) as client, pytest.raises(ProviderError) as exc_info:
        FXService().refresh_ecb(connection, client=client)

    assert str(exc_info.value) == "ecb:FX:XML_ENTITIES_NOT_ALLOWED"
    assert connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 0


def test_refresh_ecb_rejects_documents_with_more_than_64_currencies(connection) -> None:
    cubes = "".join(
        f'<Cube currency="{chr(65 + index // 26)}{chr(65 + index % 26)}X" rate="1.5"/>'
        for index in range(65)
    )
    document = (
        '<?xml version="1.0"?><Envelope><Cube><Cube time="2026-08-14">'
        f"{cubes}</Cube></Cube></Envelope>"
    ).encode()
    transport = httpx.MockTransport(lambda _request: _xml_response(document))

    with httpx.Client(transport=transport) as client, pytest.raises(ProviderError) as exc_info:
        FXService().refresh_ecb(connection, client=client)

    assert str(exc_info.value) == "ecb:FX:TOO_MANY_CURRENCIES"
    assert connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 0


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


def _history_provider(handler) -> EcbFxProvider:  # noqa: ANN001
    transport = SafeProviderTransport(
        allowed_hosts=ECB_ALLOWED_HOSTS,
        settings=get_settings(),
        clock=lambda: HISTORY_NOW,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    return EcbFxProvider(transport, sleeper=lambda _delay: None)


def _history_response(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        stream=httpx.ByteStream(HISTORY_CSV.read_bytes()),
        headers={"content-type": "text/csv"},
    )


def test_backfill_history_is_idempotent_and_feeds_the_eur_converter(connection) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _history_response(request)

    service = FXService(ecb_provider=_history_provider(handler))
    first = service.backfill_history(connection, "usd", date(2024, 1, 1), now=HISTORY_NOW)
    second = service.backfill_history(connection, "USD", date(2024, 1, 1), now=HISTORY_NOW)

    summary = ("currency", "inserted", "existing", "first_observed_at", "last_observed_at")
    assert tuple(getattr(first, name) for name in summary) == ("USD", 10, 0, "2024-01-02", "2024-01-15")
    assert tuple(getattr(second, name) for name in summary) == ("USD", 0, 10, "2024-01-02", "2024-01-15")
    assert calls == 1
    rows = connection.execute(
        """
        SELECT from_currency, to_currency, observed_at, provider, quality, ingested_at
        FROM fx_rates ORDER BY observed_at
        """
    ).fetchall()
    assert len(rows) == 10
    assert {tuple(row[:2]) + tuple(row[3:]) for row in rows} == {
        ("USD", "EUR", "ecb", "reference", "2024-01-16T12:00:00+00:00")
    }
    assert "2099-01-01" not in {row["observed_at"] for row in rows}
    direct = connection.execute(
        "SELECT rate FROM fx_rates WHERE from_currency = 'USD' AND to_currency = 'EUR' AND observed_at = '2024-01-10'"
    ).fetchone()["rate"]
    assert direct == pytest.approx(1 / 1.106)
    # EurConverter legge i cambi una volta per istanza: va creato dopo il backfill.
    converter = EurConverter(connection, max_age_days=7)
    assert converter.rate_on("USD", "2024-01-10") == direct
    with pytest.raises(ValueError, match="data"):
        service.backfill_history(connection, "USD", date(2024, 1, 17), now=HISTORY_NOW)
    assert calls == 1


def test_backfill_script_refuses_without_real_data_before_any_call(
    lab_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend.scripts import backfill_fx_history

    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    get_settings.cache_clear()

    for argv in (
        ["--currency", "USD", "--start", "2024-01-02", "--apply"],
        ["--currency", "USD", "--start", "2024-01-02"],
    ):
        assert backfill_fx_history.main(argv) == 2

    assert "ENABLE_REAL_DATA" in capsys.readouterr().err
    assert lab_connection.execute("SELECT COUNT(*) FROM provider_request_log").fetchone()[0] == 0
    assert lab_connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 0


def test_backfill_script_previews_without_calls_and_applies_on_request(
    lab_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend.scripts import backfill_fx_history

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _history_response(request)

    service = FXService(ecb_provider=_history_provider(handler))
    argv = ["--currency", "usd", "--start", "2024-01-01"]

    assert backfill_fx_history.main(argv, service=service, now=HISTORY_NOW) == 0
    preview = capsys.readouterr().out
    assert calls == 0
    assert "Anteprima" in preview
    assert "USD" in preview
    assert "2024-01-01" in preview and "2024-01-16" in preview
    assert lab_connection.execute("SELECT COUNT(*) FROM provider_request_log").fetchone()[0] == 0

    assert backfill_fx_history.main(
        ["--currency", "USD", "--start", "2024-01-17"], service=service, now=HISTORY_NOW
    ) == 2
    assert calls == 0

    assert backfill_fx_history.main([*argv, "--apply"], service=service, now=HISTORY_NOW) == 0
    applied = capsys.readouterr().out
    assert calls == 1
    assert "USD" in applied and "10" in applied
    assert lab_connection.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 10
