from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.trade_republic_catalog import TRADE_REPUBLIC_SOURCE
from backend.app.database import SCHEMA
from backend.app.models import (
    DataCoverageOut,
    DataStatusOut,
    ProviderSymbolApplyIn,
    ProviderSymbolPreviewIn,
    TradeRepublicAttestationApplyIn,
    TradeRepublicAttestationPreviewIn,
)
from backend.app.models.market_data import MarketObservationEnvelope
from backend.app.services.data_coverage_service import (
    CoverageInvariantError,
    DataCoverageService,
    verify_coverage_invariants,
)
from backend.app.services.fx_service import FXService
from backend.app.services.instrument_service import ListingConfirmationService
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.provider_budget_service import ProviderBudgetManager, ProviderBudgetPolicy
from backend.app.services.refresh_planner_service import RefreshPlannerService

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
ZERO_QUALITY = {"realtime": 0, "delayed": 0, "eod": 0, "reference": 0, "stale": 0}
ZERO_DELAY = {"0-5m": 0, "5-30m": 0, "30m-24h": 0, "1-4d": 0, ">4d": 0}
COVERAGE_FIELDS = {
    "measured_at",
    "latest_catalog_snapshot_id",
    "latest_catalog_retrieved_at",
    "latest_catalog_sha256",
    "parse_accepted_entries",
    "parse_ambiguous_entries",
    "parse_rejected_entries",
    "parse_denominator",
    "resolution_resolved_entries",
    "resolution_ambiguous_entries",
    "resolution_unmatched_entries",
    "resolution_rejected_entries",
    "resolution_unprocessed_entries",
    "resolution_denominator",
    "resolved_percent",
    "tier_denominator",
    "tier_counts",
    "tier_percentages",
    "trade_republic_denominator",
    "trade_republic_status_counts",
    "trade_republic_verified_percent",
    "by_asset_class",
    "by_market",
    "rejection_reasons",
    "provider_coverage",
    "fx_currency_denominator",
    "fx_fresh_currencies",
    "fx_stale_currencies",
    "fx_missing_currencies",
    "fx_coverage",
    "pending_refresh",
    "budget_deferred",
}
ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope
    xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
    xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-09-30">
      <Cube currency="USD" rate="1.25"/>
    </Cube>
    <Cube time="2026-09-15">
      <Cube currency="GBP" rate="0.8"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _freeze(monkeypatch: pytest.MonkeyPatch, instant: datetime, *modules: str) -> None:
    """Blocca `datetime.now`/`date.today` dei moduli indicati: nessuna dipendenza dal calendario reale."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return instant.replace(tzinfo=None) if tz is None else instant.astimezone(tz)

    class FrozenDate(date):
        @classmethod
        def today(cls):  # noqa: ANN206
            return instant.astimezone().date()

    for module in modules:
        monkeypatch.setattr(f"{module}.datetime", FrozenDatetime, raising=False)
        monkeypatch.setattr(f"{module}.date", FrozenDate, raising=False)


@pytest.fixture(autouse=True)
def _coverage_settings(monkeypatch: pytest.MonkeyPatch):
    for name, value in {
        "ENABLE_REAL_DATA": "false",
        "ENABLE_STOOQ": "false",
        "ECB_FX_MAX_AGE_DAYS": "7",
        "MARKET_DATA_QUOTE_MAX_AGE_MINUTES": "5",
        "MARKET_DATA_DELAYED_MAX_AGE_MINUTES": "30",
        "MARKET_DATA_EOD_MAX_AGE_HOURS": "96",
        "MARKET_DATA_REFERENCE_MAX_AGE_DAYS": "7",
        "STOOQ_MINUTE_LIMIT": "5",
        "STOOQ_DAILY_LIMIT": "100",
        "STOOQ_MONTHLY_LIMIT": "1000",
        "COINGECKO_KEYLESS_MINUTE_LIMIT": "10",
        "COINGECKO_KEYLESS_MONTHLY_LIMIT": "1000",
        "ALPHA_VANTAGE_DAILY_LIMIT": "20",
        "ALPHA_VANTAGE_API_KEY": "",
        "COINGECKO_API_KEY": "",
        "FINNHUB_API_KEY": "",
        "FRED_API_KEY": "",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def network_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def forbidden(_transport, request):  # noqa: ANN001, ANN202
        calls.append(str(request.url))
        raise AssertionError("coverage tests must never use the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    return calls


@pytest.fixture
def connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


# --- fixture del catalogo -----------------------------------------------------


def _snapshot(
    connection: sqlite3.Connection,
    *,
    label: str,
    retrieved_at: str,
    source: str = TRADE_REPUBLIC_SOURCE,
    status: str = "COMPLETE",
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO catalog_snapshots (
                source, source_url, content_sha256, retrieved_at, row_count, status,
                parser_version, failure_reason_code
            )
            VALUES (?, 'https://example.test/catalog.pdf', ?, ?, 0, ?, 'test-v1', ?)
            """,
            (
                source,
                _sha(f"snapshot|{label}"),
                retrieved_at,
                status,
                "PARSER_ERROR" if status == "FAILED" else None,
            ),
        ).lastrowid
    )


def _instrument(
    connection: sqlite3.Connection,
    name: str,
    instrument_type: str,
    asset_class: str,
    tier: str = "REFERENCE_ONLY",
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO instruments (canonical_name, instrument_type, asset_class, quality_tier, source)
            VALUES (?, ?, ?, ?, 'TEST_COVERAGE')
            """,
            (name, instrument_type, asset_class, tier),
        ).lastrowid
    )


def _entry(
    connection: sqlite3.Connection,
    snapshot_id: int,
    row_number: int,
    parse_status: str,
    reason_code: str,
    instrument_id: int | None = None,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO catalog_entries (
                snapshot_id, row_number, isin, name, parse_status, reason_code,
                raw_row_sha256, instrument_id, listing_id
            )
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, NULL)
            """,
            (
                snapshot_id,
                row_number,
                f"Row {row_number}",
                parse_status,
                reason_code,
                _sha(f"row|{snapshot_id}|{row_number}"),
                instrument_id,
            ),
        ).lastrowid
    )


_CASE_REASONS = {
    "RESOLVED": "EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE",
    "AMBIGUOUS": "MULTIPLE_COMPATIBLE_CANDIDATES",
    "UNMATCHED": "NO_PROVIDER_MATCH",
    "REJECTED": "MISSING_CURRENCY",
}


def _case(
    connection: sqlite3.Connection,
    entry_id: int,
    status: str,
    *,
    instrument_id: int,
    listing_id: int | None = None,
) -> int:
    ordinal = int(connection.execute("SELECT COUNT(*) FROM instrument_resolution_cases").fetchone()[0]) + 1
    candidate_count = {"RESOLVED": 1, "AMBIGUOUS": 2, "UNMATCHED": 0, "REJECTED": 1}[status]
    return int(
        connection.execute(
            """
            INSERT INTO instrument_resolution_cases (
                catalog_entry_id, provider, request_fingerprint, status, reason_code,
                candidate_count, candidate_hash, evidence_hash, selected_instrument_id,
                selected_listing_id, created_at
            )
            VALUES (?, 'openfigi', ?, ?, ?, ?, ?, ?, ?, ?, '2026-09-20T09:00:00Z')
            """,
            (
                entry_id,
                _sha(f"request|{ordinal}"),
                status,
                _CASE_REASONS[status],
                candidate_count,
                _sha(f"candidates|{ordinal}"),
                _sha(f"evidence|{ordinal}"),
                instrument_id,
                listing_id if status == "RESOLVED" else None,
            ),
        ).lastrowid
    )


def _listing(
    connection: sqlite3.Connection,
    instrument_id: int,
    ticker: str,
    mic: str | None,
    currency: str,
    timezone: str,
    *,
    trade_republic_status: str = "NEVER_SEEN",
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO instrument_listings (
                instrument_id, ticker, mic, venue_name, currency, timezone,
                listing_status, trade_republic_status, trade_republic_cataloged_at, source
            )
            VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 'TEST_COVERAGE')
            """,
            (
                instrument_id,
                ticker,
                mic,
                f"Venue {mic or ticker}",
                currency,
                timezone,
                trade_republic_status,
                "2026-09-20T08:00:00Z" if trade_republic_status == "CATALOGED" else None,
            ),
        ).lastrowid
    )


def _resolved_listing(
    connection: sqlite3.Connection,
    *,
    entry_id: int,
    instrument_id: int,
    instrument_type: str,
    ticker: str,
    mic: str | None,
    currency: str,
    timezone: str,
) -> int:
    listing_id = _listing(
        connection,
        instrument_id,
        ticker,
        mic,
        currency,
        timezone,
        trade_republic_status="CATALOGED",
    )
    connection.execute(
        """
        INSERT INTO listing_metadata_versions (
            instrument_listing_id, venue_name, timezone, instrument_type, source_code,
            observed_at, evidence_hash, status, version
        )
        VALUES (?, ?, ?, ?, 'OFFICIAL_VENUE', '2026-09-20T09:00:00Z', ?, 'VERIFIED', 1)
        """,
        (listing_id, f"Venue {mic or ticker}", timezone, instrument_type, _sha(f"metadata|{listing_id}")),
    )
    _case(connection, entry_id, "RESOLVED", instrument_id=instrument_id, listing_id=listing_id)
    connection.execute("UPDATE catalog_entries SET listing_id = ? WHERE id = ?", (listing_id, entry_id))
    return listing_id


def _confirm_symbol(
    connection: sqlite3.Connection,
    service: ListingConfirmationService,
    listing_id: int,
    provider: str,
    capability: str,
    symbol: str,
    currency: str,
) -> None:
    preview_in = ProviderSymbolPreviewIn(
        provider=provider,
        provider_symbol=symbol,
        capability=capability,
        source="OFFICIAL_SITE",
        observed_at=NOW - timedelta(days=1),
        expected_currency=currency,
        evidence_hash=_sha(f"symbol|{listing_id}|{provider}|{capability}"),
    )
    preview = service.preview_provider_symbol(connection, listing_id, preview_in)
    service.apply_provider_symbol(
        connection,
        listing_id,
        ProviderSymbolApplyIn(**preview_in.model_dump(), confirmation_token=preview.confirmation_token),
    )
    connection.commit()


def _attest_trade_republic(
    connection: sqlite3.Connection,
    service: ListingConfirmationService,
    listing_id: int,
    status: str,
) -> None:
    preview_in = TradeRepublicAttestationPreviewIn(
        status=status,
        source="MANUAL_OFFICIAL_APP_CHECK",
        observed_at=NOW - timedelta(hours=2),
        evidence_hash=_sha(f"trade-republic|{listing_id}|{status}"),
    )
    preview = service.preview_trade_republic_attestation(connection, listing_id, preview_in)
    service.apply_trade_republic_attestation(
        connection,
        listing_id,
        TradeRepublicAttestationApplyIn(**preview_in.model_dump(), confirmation_token=preview.confirmation_token),
    )
    connection.commit()


def _envelope(
    listing_id: int,
    provider: str,
    capability: str,
    *,
    observed_at: datetime,
    received_at: datetime,
    timezone: str,
    currency: str,
    price: str = "10",
    session: str = "REGULAR",
) -> MarketObservationEnvelope:
    kind = "QUOTE" if capability == "QUOTE" else "BAR"
    raw_fields = (
        {"last": price}
        if kind == "QUOTE"
        else {"open": price, "high": price, "low": price, "close": price, "volume": "100"}
    )
    return MarketObservationEnvelope(
        listing_id=listing_id,
        provider=provider,
        capability=capability,
        operation=f"{provider}_{capability.lower()}",
        received_at=received_at,
        provider_observed_at=observed_at,
        timezone=timezone,
        session=session,
        currency=currency,
        source_quality="realtime" if kind == "QUOTE" else "eod",
        kind=kind,
        raw_fields=raw_fields,
        raw_payload_sha256=_sha(f"payload|{listing_id}|{provider}|{observed_at.isoformat()}|{price}"),
    )


def _ingest(connection: sqlite3.Connection, envelope: MarketObservationEnvelope, now: datetime) -> None:
    MarketObservationService().ingest_batch(connection, [envelope], now)
    connection.commit()


def _build_coverage_fixture(connection: sqlite3.Connection) -> dict[str, int]:
    """Catalogo, listing, mapping, observation e coda sintetici; TR tramite il servizio del Task 14."""
    ids: dict[str, int] = {}
    old = _snapshot(connection, label="old", retrieved_at="2026-09-01T08:00:00Z")
    main = _snapshot(connection, label="main", retrieved_at="2026-09-20T08:00:00Z")
    _snapshot(connection, label="failed", retrieved_at="2026-09-25T08:00:00Z", status="FAILED")
    other = _snapshot(connection, label="other-source", retrieved_at="2026-09-28T08:00:00Z", source="TEST_SOURCE")
    ids["main"] = main

    alpha = _instrument(connection, "Alpha", "STOCK", "EQUITY", "QUALIFIED")
    beta = _instrument(connection, "Beta", "ETF", "FUND", "OBSERVABLE")
    gamma = _instrument(connection, "Gamma", "STOCK", "EQUITY")
    delta = _instrument(connection, "Delta", "UNKNOWN", "UNKNOWN")
    epsilon = _instrument(connection, "Epsilon", "UNKNOWN", "UNKNOWN")
    zeta = _instrument(connection, "Zeta", "UNKNOWN", "UNKNOWN")

    # Snapshot corrente: 7 ACCEPTED (beta due volte), 1 AMBIGUOUS, 2 REJECTED.
    alpha_entry = _entry(connection, main, 1, "ACCEPTED", "VALID_ISIN", alpha)
    _case(connection, alpha_entry, "UNMATCHED", instrument_id=alpha)
    ids["alpha_us"] = _resolved_listing(
        connection,
        entry_id=alpha_entry,
        instrument_id=alpha,
        instrument_type="STOCK",
        ticker="ALFA",
        mic="XNAS",
        currency="USD",
        timezone="America/New_York",
    )
    beta_entry = _entry(connection, main, 2, "ACCEPTED", "VALID_ISIN", beta)
    ids["beta_de"] = _resolved_listing(
        connection,
        entry_id=beta_entry,
        instrument_id=beta,
        instrument_type="ETF",
        ticker="BETA",
        mic="XETR",
        currency="EUR",
        timezone="Europe/Berlin",
    )
    gamma_entry = _entry(connection, main, 3, "ACCEPTED", "VALID_ISIN", gamma)
    _case(connection, gamma_entry, "UNMATCHED", instrument_id=gamma)
    _case(connection, gamma_entry, "AMBIGUOUS", instrument_id=gamma)
    delta_entry = _entry(connection, main, 4, "ACCEPTED", "VALID_ISIN", delta)
    _case(connection, delta_entry, "REJECTED", instrument_id=delta)
    _case(connection, delta_entry, "UNMATCHED", instrument_id=delta)
    epsilon_entry = _entry(connection, main, 5, "ACCEPTED", "VALID_ISIN", epsilon)
    _case(connection, epsilon_entry, "REJECTED", instrument_id=epsilon)
    _entry(connection, main, 6, "ACCEPTED", "VALID_ISIN", zeta)
    beta_it_entry = _entry(connection, main, 7, "ACCEPTED", "VALID_ISIN", beta)
    ids["beta_it"] = _resolved_listing(
        connection,
        entry_id=beta_it_entry,
        instrument_id=beta,
        instrument_type="ETF",
        ticker="BETA",
        mic="XMIL",
        currency="EUR",
        timezone="Europe/Rome",
    )
    _entry(connection, main, 8, "REJECTED", "INVALID_ISIN")
    _entry(connection, main, 9, "AMBIGUOUS", "DUPLICATE_IN_SNAPSHOT")
    _entry(connection, main, 10, "REJECTED", "MISSING_NAME")

    # Snapshot precedente: resta consultabile ma non entra nei denominatori correnti.
    old_alpha = _entry(connection, old, 1, "ACCEPTED", "VALID_ISIN", alpha)
    _case(connection, old_alpha, "RESOLVED", instrument_id=alpha, listing_id=ids["alpha_us"])
    _entry(connection, old, 2, "REJECTED", "INVALID_ISIN")

    # Listing risolti fuori dal catalogo TR corrente: contano solo per provider e FX.
    crypto = _instrument(connection, "Zeta Coin", "CRYPTO", "CRYPTO")
    jota = _instrument(connection, "Jota", "ETF", "FUND")
    nu = _instrument(connection, "Nu", "ETF", "FUND")
    kappa = _instrument(connection, "Kappa", "STOCK", "EQUITY")
    ids["crypto"] = _resolved_listing(
        connection,
        entry_id=_entry(connection, other, 1, "ACCEPTED", "VALID_ISIN", crypto),
        instrument_id=crypto,
        instrument_type="CRYPTO",
        ticker="ZETA",
        mic=None,
        currency="USD",
        timezone="UTC",
    )
    ids["jota_us"] = _resolved_listing(
        connection,
        entry_id=_entry(connection, other, 2, "ACCEPTED", "VALID_ISIN", jota),
        instrument_id=jota,
        instrument_type="ETF",
        ticker="JOTA",
        mic="XNYS",
        currency="USD",
        timezone="America/New_York",
    )
    ids["nu_ch"] = _resolved_listing(
        connection,
        entry_id=_entry(connection, other, 3, "ACCEPTED", "VALID_ISIN", nu),
        instrument_id=nu,
        instrument_type="ETF",
        ticker="NUCH",
        mic="XSWX",
        currency="CHF",
        timezone="Europe/Zurich",
    )
    ids["kappa_inactive"] = _resolved_listing(
        connection,
        entry_id=_entry(connection, other, 4, "ACCEPTED", "VALID_ISIN", kappa),
        instrument_id=kappa,
        instrument_type="STOCK",
        ticker="KAPA",
        mic="XNYS",
        currency="USD",
        timezone="America/New_York",
    )
    # Listing legacy non risolto (niente metadata VERIFIED ne case RESOLVED), valuta HKD.
    legacy = _instrument(connection, "Lambda Legacy", "STOCK", "EQUITY")
    ids["legacy"] = _listing(connection, legacy, "LMBD", "XHKG", "HKD", "Asia/Hong_Kong")

    identifier_id = int(
        connection.execute(
            """
            INSERT INTO instrument_identifiers (scheme, normalized_value, scope, instrument_id, listing_id)
            VALUES ('COINGECKO_ID', 'zeta-coin', 'INSTRUMENT', ?, NULL)
            """,
            (crypto,),
        ).lastrowid
    )
    connection.execute(
        """
        INSERT INTO instrument_identifier_attestations (identifier_id, source, observed_at, evidence_hash)
        VALUES (?, 'LEGACY_CURATED', '2026-09-20T09:00:00Z', ?)
        """,
        (identifier_id, _sha("coingecko|zeta-coin")),
    )
    connection.commit()

    service = ListingConfirmationService(clock=lambda: NOW)
    _confirm_symbol(connection, service, ids["alpha_us"], "stooq", "EOD", "alfa.us", "USD")
    _confirm_symbol(connection, service, ids["alpha_us"], "finnhub", "QUOTE", "ALFA", "USD")
    _confirm_symbol(connection, service, ids["beta_de"], "stooq", "EOD", "beta.de", "EUR")
    _confirm_symbol(connection, service, ids["beta_it"], "stooq", "EOD", "beta.it", "EUR")
    _confirm_symbol(connection, service, ids["kappa_inactive"], "stooq", "EOD", "kapa.us", "USD")
    connection.execute(
        "UPDATE instrument_listings SET listing_status = 'INACTIVE' WHERE id = ?",
        (ids["kappa_inactive"],),
    )
    connection.execute(
        """
        INSERT INTO provider_symbols (
            provider, listing_id, capability, provider_symbol, normalized_symbol, status,
            source, observed_at, verified_at, evidence_hash, version
        )
        VALUES ('stooq', ?, 'EOD', 'lmbd.hk', 'lmbd.hk', 'VERIFIED', 'TEST', ?, ?, ?, 1)
        """,
        (ids["legacy"], NOW.isoformat(), NOW.isoformat(), _sha("legacy-symbol")),
    )
    connection.commit()
    _attest_trade_republic(connection, service, ids["alpha_us"], "VERIFIED")
    _attest_trade_republic(connection, service, ids["beta_it"], "UNAVAILABLE")

    # Observation: rejection risolta poi barra fresca (alpha), barra stale con revisione (beta DE),
    # rejection corrente senza observation (beta IT), quote fresca (alpha), EOD crypto fresca.
    _ingest(
        connection,
        _envelope(
            ids["alpha_us"],
            "stooq",
            "EOD",
            observed_at=NOW - timedelta(hours=21),
            received_at=NOW - timedelta(hours=20),
            timezone="America/New_York",
            currency="USD",
            price="-1",
        ),
        NOW - timedelta(hours=20),
    )
    _ingest(
        connection,
        _envelope(
            ids["alpha_us"],
            "stooq",
            "EOD",
            observed_at=NOW - timedelta(hours=20),
            received_at=NOW - timedelta(hours=19),
            timezone="America/New_York",
            currency="USD",
        ),
        NOW - timedelta(hours=19),
    )
    for price, ingested in (("20", NOW - timedelta(days=8)), ("21", NOW - timedelta(days=7))):
        _ingest(
            connection,
            _envelope(
                ids["beta_de"],
                "stooq",
                "EOD",
                observed_at=NOW - timedelta(days=10),
                received_at=ingested,
                timezone="Europe/Berlin",
                currency="EUR",
                price=price,
            ),
            ingested,
        )
    _ingest(
        connection,
        _envelope(
            ids["beta_it"],
            "stooq",
            "EOD",
            observed_at=NOW - timedelta(hours=2),
            received_at=NOW - timedelta(hours=1),
            timezone="Europe/Rome",
            currency="EUR",
            price="0",
        ),
        NOW - timedelta(hours=1),
    )
    _ingest(
        connection,
        _envelope(
            ids["alpha_us"],
            "finnhub",
            "QUOTE",
            observed_at=NOW - timedelta(minutes=2),
            received_at=NOW - timedelta(seconds=90),
            timezone="America/New_York",
            currency="USD",
        ),
        NOW - timedelta(seconds=90),
    )
    _ingest(
        connection,
        _envelope(
            ids["crypto"],
            "coingecko",
            "EOD",
            observed_at=NOW - timedelta(days=1),
            received_at=NOW - timedelta(hours=22),
            timezone="UTC",
            currency="USD",
            session="24X7",
        ),
        NOW - timedelta(hours=22),
    )
    _ingest(
        connection,
        _envelope(
            ids["legacy"],
            "stooq",
            "EOD",
            observed_at=NOW - timedelta(hours=1),
            received_at=NOW - timedelta(minutes=30),
            timezone="Asia/Hong_Kong",
            currency="HKD",
        ),
        NOW - timedelta(minutes=30),
    )

    # Asset attivi e posizioni per il denominatore FX; le valute EUR non entrano.
    asset_ids = {}
    for symbol, currency in (("AAA", "USD"), ("GGG", "GBP"), ("JJJ", "JPY"), ("EEE", "EUR")):
        asset_ids[symbol] = int(
            connection.execute(
                "INSERT INTO assets (symbol, name, asset_type, currency) VALUES (?, ?, 'stock', ?)",
                (symbol, f"Asset {symbol}", currency),
            ).lastrowid
        )
    for quantity, currency in ((3.0, "SEK"), (-2.0, "NOK")):
        connection.execute(
            """
            INSERT INTO portfolio_positions (asset_id, symbol, quantity, average_price, currency)
            VALUES (?, 'EEE', ?, 10, ?)
            """,
            (asset_ids["EEE"], quantity, currency),
        )
    connection.commit()

    planner = RefreshPlannerService(MarketDataService())
    planner.enqueue(connection, ids["alpha_us"], "EOD", "VIEWED", NOW)
    planner.enqueue(connection, ids["jota_us"], "EOD", "CATALOG_EOD", NOW)
    deferred = planner.enqueue(connection, ids["beta_it"], "EOD", "WATCHLIST", NOW)
    finished = planner.enqueue(connection, ids["crypto"], "EOD", "REQUESTED", NOW)
    connection.execute(
        "UPDATE refresh_requests SET state = 'BUDGET_DEFERRED', not_before = ? WHERE id = ?",
        ((NOW + timedelta(minutes=1)).isoformat(), deferred),
    )
    connection.execute("UPDATE refresh_requests SET state = 'SUCCEEDED' WHERE id = ?", (finished,))
    connection.commit()
    return ids


def _provider(coverage: DataCoverageOut, provider: str, capability: str):  # noqa: ANN202
    return next(
        item
        for item in coverage.provider_coverage
        if item.provider == provider and item.capability == capability
    )


# --- catalogo, resolution, tier e TR ------------------------------------------


def test_coverage_counts_only_latest_complete_snapshot_and_latest_case(connection) -> None:
    ids = _build_coverage_fixture(connection)

    coverage = DataCoverageService().measure(connection, NOW)

    assert coverage.measured_at == NOW
    assert coverage.latest_catalog_snapshot_id == ids["main"]
    assert coverage.latest_catalog_retrieved_at == datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
    assert coverage.latest_catalog_sha256 == _sha("snapshot|main")
    assert (
        coverage.parse_accepted_entries,
        coverage.parse_ambiguous_entries,
        coverage.parse_rejected_entries,
        coverage.parse_denominator,
    ) == (7, 1, 2, 10)
    assert (
        coverage.resolution_resolved_entries,
        coverage.resolution_ambiguous_entries,
        coverage.resolution_unmatched_entries,
        coverage.resolution_rejected_entries,
        coverage.resolution_unprocessed_entries,
        coverage.resolution_denominator,
    ) == (3, 1, 1, 1, 1, 7)
    assert coverage.resolution_denominator == coverage.parse_accepted_entries
    assert coverage.resolved_percent == 42.86
    # Rejection parser e resolution restano distinte; i case storici non contano.
    assert coverage.rejection_reasons == {
        "PARSE:DUPLICATE_IN_SNAPSHOT": 1,
        "PARSE:INVALID_ISIN": 1,
        "PARSE:MISSING_NAME": 1,
        "RESOLUTION:MISSING_CURRENCY": 1,
        "RESOLUTION:MULTIPLE_COMPATIBLE_CANDIDATES": 1,
        "RESOLUTION:NO_PROVIDER_MATCH": 1,
    }
    assert list(coverage.rejection_reasons) == sorted(coverage.rejection_reasons)


def test_coverage_tier_and_trade_republic_denominators_include_unresolved(connection) -> None:
    _build_coverage_fixture(connection)

    coverage = DataCoverageService().measure(connection, NOW)

    # Beta compare in due entry ACCEPTED ma e un solo instrument.
    assert coverage.tier_denominator == 6
    assert coverage.tier_counts == {"QUALIFIED": 1, "OBSERVABLE": 1, "REFERENCE_ONLY": 4}
    assert coverage.tier_percentages == {"QUALIFIED": 16.67, "OBSERVABLE": 16.67, "REFERENCE_ONLY": 66.67}
    assert coverage.trade_republic_denominator == coverage.parse_accepted_entries == 7
    assert coverage.trade_republic_status_counts == {
        "UNRESOLVED_IDENTITY": 4,
        "NEVER_SEEN": 0,
        "CATALOGED": 1,
        "VERIFIED": 1,
        "UNAVAILABLE": 1,
    }
    assert coverage.trade_republic_verified_percent == 14.29


def test_coverage_groups_catalog_entries_by_asset_class_and_market(connection) -> None:
    _build_coverage_fixture(connection)

    coverage = DataCoverageService().measure(connection, NOW)

    assert [item.model_dump() for item in coverage.by_asset_class] == [
        {"key": "EQUITY", "total": 2, "resolved": 1, "qualified": 1, "observable": 0, "reference_only": 1},
        {"key": "FUND", "total": 2, "resolved": 2, "qualified": 0, "observable": 2, "reference_only": 0},
        {"key": "UNKNOWN", "total": 3, "resolved": 0, "qualified": 0, "observable": 0, "reference_only": 3},
    ]
    assert [item.model_dump() for item in coverage.by_market] == [
        {"key": "UNRESOLVED", "total": 4, "resolved": 0, "qualified": 0, "observable": 0, "reference_only": 4},
        {"key": "XETR", "total": 1, "resolved": 1, "qualified": 0, "observable": 1, "reference_only": 0},
        {"key": "XMIL", "total": 1, "resolved": 1, "qualified": 0, "observable": 1, "reference_only": 0},
        {"key": "XNAS", "total": 1, "resolved": 1, "qualified": 1, "observable": 0, "reference_only": 0},
    ]
    assert sum(item.total for item in coverage.by_asset_class) == coverage.parse_accepted_entries
    assert sum(item.total for item in coverage.by_market) == coverage.parse_accepted_entries


# --- provider -----------------------------------------------------------------


def test_provider_coverage_partitions_eligible_listings_without_multiplying_revisions(connection) -> None:
    _build_coverage_fixture(connection)

    coverage = DataCoverageService().measure(connection, NOW)

    assert [(item.provider, item.capability) for item in coverage.provider_coverage] == [
        ("coingecko", "EOD"),
        ("coingecko", "QUOTE"),
        ("finnhub", "QUOTE"),
        ("stooq", "EOD"),
    ]
    stooq = _provider(coverage, "stooq", "EOD")
    # Eleggibili: alpha US, beta DE, beta IT, jota US, nu CH (no inattivo, no legacy, no crypto).
    assert (stooq.eligible_listings, stooq.unmapped_listings, stooq.mapped_listings) == (5, 2, 3)
    assert (stooq.fresh_listings, stooq.stale_listings, stooq.missing_observation_listings) == (1, 1, 1)
    assert stooq.rejected_observations == 1
    assert stooq.quality_counts == {**ZERO_QUALITY, "eod": 1, "stale": 1}
    assert stooq.delay_bucket_counts == {**ZERO_DELAY, "30m-24h": 1, "1-4d": 1}
    assert stooq.latest_provider_observed_at == NOW - timedelta(hours=20)
    assert stooq.latest_ingested_at == NOW - timedelta(hours=19)
    assert stooq.attribution is None

    finnhub = _provider(coverage, "finnhub", "QUOTE")
    assert (finnhub.eligible_listings, finnhub.unmapped_listings, finnhub.mapped_listings) == (2, 1, 1)
    assert (finnhub.fresh_listings, finnhub.stale_listings, finnhub.missing_observation_listings) == (1, 0, 0)
    assert finnhub.quality_counts == {**ZERO_QUALITY, "realtime": 1}
    assert finnhub.delay_bucket_counts == {**ZERO_DELAY, "0-5m": 1}
    assert finnhub.latest_provider_observed_at == NOW - timedelta(minutes=2)
    assert finnhub.latest_ingested_at == NOW - timedelta(seconds=90)

    crypto_eod = _provider(coverage, "coingecko", "EOD")
    assert (crypto_eod.eligible_listings, crypto_eod.unmapped_listings, crypto_eod.mapped_listings) == (1, 0, 1)
    assert (crypto_eod.fresh_listings, crypto_eod.stale_listings, crypto_eod.missing_observation_listings) == (
        1,
        0,
        0,
    )
    assert crypto_eod.delay_bucket_counts == {**ZERO_DELAY, "30m-24h": 1}
    assert crypto_eod.attribution == "Powered by CoinGecko API"

    crypto_quote = _provider(coverage, "coingecko", "QUOTE")
    assert (crypto_quote.eligible_listings, crypto_quote.mapped_listings) == (1, 1)
    assert crypto_quote.missing_observation_listings == 1
    assert crypto_quote.quality_counts == ZERO_QUALITY
    assert crypto_quote.delay_bucket_counts == ZERO_DELAY
    assert (crypto_quote.latest_provider_observed_at, crypto_quote.latest_ingested_at) == (None, None)

    for item in coverage.provider_coverage:
        assert item.capability not in {"FX", "NEWS"}
        assert item.unmapped_listings + item.mapped_listings == item.eligible_listings
        assert (
            item.fresh_listings + item.stale_listings + item.missing_observation_listings
            == item.mapped_listings
        )
        assert sum(item.quality_counts.values()) == item.fresh_listings + item.stale_listings
        assert sum(item.delay_bucket_counts.values()) == item.fresh_listings + item.stale_listings


def test_provider_freshness_uses_policy_at_measured_at(connection) -> None:
    _build_coverage_fixture(connection)

    later = DataCoverageService().measure(connection, NOW + timedelta(days=5))

    stooq = _provider(later, "stooq", "EOD")
    assert (stooq.fresh_listings, stooq.stale_listings, stooq.missing_observation_listings) == (0, 2, 1)
    assert stooq.quality_counts == {**ZERO_QUALITY, "stale": 2}
    finnhub = _provider(later, "finnhub", "QUOTE")
    assert (finnhub.fresh_listings, finnhub.stale_listings) == (0, 1)
    assert finnhub.quality_counts == {**ZERO_QUALITY, "stale": 1}
    # Il ritardo resta quello misurato all'ingestione, non l'eta al momento della misura.
    assert finnhub.delay_bucket_counts == {**ZERO_DELAY, "0-5m": 1}


# --- FX -----------------------------------------------------------------------


def test_fx_coverage_is_separate_from_listings_with_direct_inverse_stale_missing(
    connection,
    monkeypatch,
) -> None:
    _build_coverage_fixture(connection)
    connection.execute(
        """
        INSERT INTO fx_rates (from_currency, to_currency, rate, observed_at, ingested_at, provider, quality)
        VALUES
            ('EUR', 'CHF', 0.95, '2026-09-29', '2026-09-29T16:00:00+00:00', 'test', 'reference'),
            ('USD', 'EUR', 0.7, '2026-09-01', '2026-09-01T16:00:00+00:00', 'old', 'reference'),
            ('EUR', 'USD', 2.0, '2026-09-30', '2026-09-30T16:00:00+00:00', 'test', 'reference')
        """
    )
    connection.commit()
    listings_before = connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0]
    observations_before = connection.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0]
    _freeze(monkeypatch, NOW, "backend.app.services.fx_service")

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                stream=httpx.ByteStream(ECB_XML),
                headers={"content-type": "text/xml"},
            )
        )
    ) as client:
        assert FXService().refresh_ecb(connection, client=client) == 2
    connection.commit()

    coverage = DataCoverageService().measure(connection, NOW)

    assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == listings_before
    assert connection.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0] == observations_before
    fx = {item.from_currency: item for item in coverage.fx_coverage}
    # USD/GBP/JPY da asset, SEK da posizione positiva, CHF da listing risolto;
    # esclusi EUR (identita), NOK (posizione short) e HKD (listing non risolto).
    assert list(fx) == ["CHF", "GBP", "JPY", "SEK", "USD"]
    assert coverage.fx_currency_denominator == 5
    assert (coverage.fx_fresh_currencies, coverage.fx_stale_currencies, coverage.fx_missing_currencies) == (2, 1, 2)
    assert (
        coverage.fx_fresh_currencies + coverage.fx_stale_currencies + coverage.fx_missing_currencies
        == coverage.fx_currency_denominator
    )
    assert fx["USD"].model_dump() == {
        "from_currency": "USD",
        "to_currency": "EUR",
        "status": "FRESH",
        "direction": "DIRECT",
        "provider": "ecb",
        "rate_to_eur": Decimal("0.8"),
        "observed_at": datetime(2026, 9, 30, tzinfo=UTC),
        "ingested_at": NOW,
        "age_seconds": 43_200,
        "quality": "reference",
    }
    assert fx["GBP"].model_dump() == {
        "from_currency": "GBP",
        "to_currency": "EUR",
        "status": "STALE",
        "direction": "DIRECT",
        "provider": "ecb",
        "rate_to_eur": Decimal("1.25"),
        "observed_at": datetime(2026, 9, 15, tzinfo=UTC),
        "ingested_at": NOW,
        "age_seconds": 1_339_200,
        "quality": "stale",
    }
    assert fx["CHF"].model_dump() == {
        "from_currency": "CHF",
        "to_currency": "EUR",
        "status": "FRESH",
        "direction": "INVERSE",
        "provider": "test",
        "rate_to_eur": Decimal(str(1.0 / 0.95)),
        "observed_at": datetime(2026, 9, 29, tzinfo=UTC),
        "ingested_at": datetime(2026, 9, 29, 16, 0, tzinfo=UTC),
        "age_seconds": 129_600,
        "quality": "reference",
    }
    for missing in ("JPY", "SEK"):
        assert fx[missing].model_dump() == {
            "from_currency": missing,
            "to_currency": "EUR",
            "status": "MISSING",
            "direction": None,
            "provider": None,
            "rate_to_eur": None,
            "observed_at": None,
            "ingested_at": None,
            "age_seconds": None,
            "quality": None,
        }
    # Stessa reciprocita di FXService; EUR resta identita senza entrare nel denominatore.
    assert float(fx["CHF"].rate_to_eur) == FXService().get_rate(connection, "CHF").rate
    assert FXService().get_rate(connection, "EUR").rate == 1.0
    assert {item.capability for item in coverage.provider_coverage}.isdisjoint({"FX"})


# --- coda, zero, invarianti, assenza di rete ----------------------------------


def test_coverage_counts_pending_and_budget_deferred_refresh(connection) -> None:
    _build_coverage_fixture(connection)

    coverage = DataCoverageService().measure(connection, NOW)

    assert (coverage.pending_refresh, coverage.budget_deferred) == (2, 1)


def test_coverage_zero_denominators_return_zero_percentages(connection) -> None:
    coverage = DataCoverageService().measure(connection, NOW)

    assert set(DataCoverageOut.model_fields) == COVERAGE_FIELDS
    assert coverage.latest_catalog_snapshot_id is None
    assert coverage.latest_catalog_retrieved_at is None
    assert coverage.latest_catalog_sha256 is None
    assert coverage.parse_denominator == coverage.resolution_denominator == 0
    assert coverage.resolved_percent == 0.0
    assert coverage.tier_denominator == 0
    assert coverage.tier_counts == {"QUALIFIED": 0, "OBSERVABLE": 0, "REFERENCE_ONLY": 0}
    assert coverage.tier_percentages == {"QUALIFIED": 0.0, "OBSERVABLE": 0.0, "REFERENCE_ONLY": 0.0}
    assert coverage.trade_republic_denominator == 0
    assert set(coverage.trade_republic_status_counts.values()) == {0}
    assert coverage.trade_republic_verified_percent == 0.0
    assert (coverage.by_asset_class, coverage.by_market, coverage.rejection_reasons) == ([], [], {})
    assert len(coverage.provider_coverage) == 4
    for item in coverage.provider_coverage:
        assert (item.eligible_listings, item.mapped_listings, item.rejected_observations) == (0, 0, 0)
        assert (item.quality_counts, item.delay_bucket_counts) == (ZERO_QUALITY, ZERO_DELAY)
        assert (item.latest_provider_observed_at, item.latest_ingested_at) == (None, None)
    assert (coverage.fx_currency_denominator, coverage.fx_coverage) == (0, [])
    assert (coverage.pending_refresh, coverage.budget_deferred) == (0, 0)


def test_coverage_is_read_only_and_never_calls_the_network(connection, network_calls) -> None:
    _build_coverage_fixture(connection)
    changes_before = connection.total_changes

    coverage = DataCoverageService().measure(connection, NOW)

    assert connection.total_changes == changes_before
    assert not connection.in_transaction
    assert network_calls == []
    payload = coverage.model_dump_json()
    assert "http" not in payload
    assert "target" not in payload.lower()


def test_coverage_invariants_reject_inconsistent_partitions(connection) -> None:
    _build_coverage_fixture(connection)
    coverage = DataCoverageService().measure(connection, NOW)
    verify_coverage_invariants(coverage)

    broken_parse = coverage.model_copy(update={"parse_denominator": coverage.parse_denominator + 1})
    with pytest.raises(CoverageInvariantError, match="parse"):
        verify_coverage_invariants(broken_parse)
    broken_resolution = coverage.model_copy(
        update={"resolution_unprocessed_entries": coverage.resolution_unprocessed_entries + 1}
    )
    with pytest.raises(CoverageInvariantError, match="resolution"):
        verify_coverage_invariants(broken_resolution)
    stooq = _provider(coverage, "stooq", "EOD")
    broken_provider = coverage.model_copy(
        update={
            "provider_coverage": [
                item if item is not stooq else stooq.model_copy(update={"fresh_listings": 2})
                for item in coverage.provider_coverage
            ]
        }
    )
    with pytest.raises(CoverageInvariantError, match="provider"):
        verify_coverage_invariants(broken_provider)
    broken_fx = coverage.model_copy(update={"fx_missing_currencies": coverage.fx_missing_currencies + 1})
    with pytest.raises(CoverageInvariantError, match="fx"):
        verify_coverage_invariants(broken_fx)


# --- status provider additivo -------------------------------------------------


def test_provider_status_reports_budget_windows_cooldown_and_last_outcome(connection, monkeypatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "fixture-secret-token")
    get_settings.cache_clear()
    moment = NOW + timedelta(seconds=30)
    _freeze(
        monkeypatch,
        moment,
        "backend.app.services.provider_budget_service",
        "backend.app.data_providers.provider_registry",
    )
    manager = ProviderBudgetManager()
    policy = ProviderBudgetPolicy(minute_limit=5, daily_limit=100, monthly_limit=1000)
    reservation = manager.reserve(connection, policy, "stooq", "EOD", "f" * 64, moment)
    manager.complete(connection, reservation, "RATE_LIMITED", 429, 1, NOW + timedelta(minutes=2))
    manager.restrict(
        connection,
        "stooq",
        moment,
        minute_limit=3,
        remaining=0,
        cooldown_until=NOW + timedelta(minutes=2),
    )

    status = DataStatusOut.model_validate(MarketDataService().get_global_status(connection, now=moment))

    stooq = next(item for item in status.provider_status if item.provider == "stooq")
    assert (stooq.daily_limit, stooq.calls_today) == (100, 1)
    assert stooq.capabilities == ["EOD"]
    assert [window.model_dump() for window in stooq.budget_windows] == [
        {"window": "MINUTE", "limit": 3, "used": 3, "remaining": 0, "reset_at": NOW + timedelta(minutes=1)},
        {"window": "DAY", "limit": 100, "used": 1, "remaining": 99, "reset_at": datetime(2026, 10, 1, tzinfo=UTC)},
        {"window": "MONTH", "limit": 1000, "used": 1, "remaining": 999, "reset_at": datetime(2026, 10, 1, tzinfo=UTC)},
    ]
    assert stooq.cooldown_until == NOW + timedelta(minutes=2)
    assert (stooq.availability_state, stooq.availability_reason) == ("DISABLED", "OPT_IN_DISABLED")
    assert (stooq.last_outcome, stooq.last_outcome_at) == ("RATE_LIMITED", moment)

    coingecko = next(item for item in status.provider_status if item.provider == "coingecko")
    assert coingecko.capabilities == ["EOD", "QUOTE"]
    assert [(window.window, window.limit, window.used, window.remaining) for window in coingecko.budget_windows] == [
        ("MINUTE", 10, 0, 10),
        ("DAY", None, 0, None),
        ("MONTH", 1000, 0, 1000),
    ]
    assert (coingecko.cooldown_until, coingecko.last_outcome, coingecko.last_outcome_at) == (None, None, None)
    for item in status.provider_status:
        day = next(window for window in item.budget_windows if window.window == "DAY")
        assert (day.limit or 0) == item.daily_limit
        assert item.calls_today <= day.used

    assert status.coverage_summary is not None
    assert status.coverage_summary.measured_at == moment
    dumped = status.model_dump_json()
    assert "fixture-secret-token" not in dumped
    assert "f" * 64 not in dumped
    assert "http" not in dumped


def test_global_status_keeps_working_when_coverage_invariants_fail(connection, monkeypatch) -> None:
    def broken(self, connection, measured_at):  # noqa: ANN001, ANN202
        raise CoverageInvariantError("parse")

    monkeypatch.setattr(DataCoverageService, "measure", broken)

    status = MarketDataService().get_global_status(connection, now=NOW)

    assert status["coverage_summary"] is None
    assert json.loads(DataStatusOut.model_validate(status).model_dump_json())["provider_status"]
