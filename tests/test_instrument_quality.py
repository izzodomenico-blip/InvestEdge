from __future__ import annotations

import hashlib
import importlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.config import get_settings
from backend.app.database import SCHEMA, migrate_db
from backend.app.models.market_data import MarketObservationEnvelope
from backend.app.services.market_observation_service import MarketObservationService

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _quality_service(**kwargs: object):
    try:
        module = importlib.import_module(
            "backend.app.services.instrument_quality_service"
        )
    except ModuleNotFoundError:
        pytest.fail("instrument quality service is not implemented")
    return module.InstrumentQualityService(**kwargs)


@pytest.fixture
def quality_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    migrate_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def _add_instrument(
    connection: sqlite3.Connection,
    *,
    instrument_type: str = "STOCK",
    asset_class: str = "EQUITY",
    ticker: str = "ACME",
    mic: str | None = "XNAS",
    currency: str = "USD",
    timezone: str | None = "America/New_York",
    primary_scheme: str | None = "ISIN",
    primary_value: str = "US0000000001",
    trade_republic_status: str = "NEVER_SEEN",
    trade_republic_verified_at: datetime | None = None,
) -> tuple[int, int]:
    instrument_id = int(
        connection.execute(
            """
            INSERT INTO instruments (
                canonical_name, instrument_type, asset_class, source, source_date
            )
            VALUES (?, ?, ?, 'test', '2026-08-17')
            """,
            (f"{ticker} instrument", instrument_type, asset_class),
        ).lastrowid
    )
    listing_id = int(
        connection.execute(
            """
            INSERT INTO instrument_listings (
                instrument_id, ticker, mic, venue_name, currency, timezone,
                listing_status, trade_republic_status, trade_republic_verified_at,
                source, source_date
            )
            VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 'test', '2026-08-17')
            """,
            (
                instrument_id,
                ticker,
                mic,
                "Test venue" if mic is not None else None,
                currency,
                timezone,
                trade_republic_status,
                (
                    trade_republic_verified_at.astimezone(UTC).isoformat()
                    if trade_republic_verified_at is not None
                    else None
                ),
            ),
        ).lastrowid
    )
    if primary_scheme is not None:
        identifier_id = int(
            connection.execute(
                """
                INSERT INTO instrument_identifiers (
                    scheme, normalized_value, scope, instrument_id, listing_id
                )
                VALUES (?, ?, 'INSTRUMENT', ?, NULL)
                """,
                (primary_scheme, primary_value, instrument_id),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO instrument_identifier_attestations (
                identifier_id, source, observed_at, evidence_hash
            )
            VALUES (?, 'test', ?, ?)
            """,
            (identifier_id, NOW.isoformat(), _hash(f"identifier-{instrument_id}")),
        )
    return instrument_id, listing_id


def _bar(
    listing_id: int,
    *,
    provider: str,
    observed_at: datetime,
    close: str = "100",
    operation: str = "daily_prices",
    timezone: str = "America/New_York",
    received_at: datetime = NOW,
) -> MarketObservationEnvelope:
    return MarketObservationEnvelope(
        listing_id=listing_id,
        provider=provider,
        capability="EOD",
        operation=operation,
        received_at=received_at,
        provider_observed_at=observed_at,
        timezone=timezone,
        session="REGULAR",
        currency="USD",
        source_quality="eod",
        kind="BAR",
        raw_fields={"close": close, "volume": "100"},
        raw_payload_sha256=_hash(
            f"{listing_id}-{provider}-{operation}-{observed_at.isoformat()}-{close}"
        ),
    )


def _add_history(
    connection: sqlite3.Connection,
    listing_id: int,
    *,
    count: int,
    provider: str = "fixture_eod",
    close: str = "100",
    now: datetime = NOW,
    timezone: str = "America/New_York",
    operation: str = "daily_prices",
) -> None:
    envelopes = [
        _bar(
            listing_id,
            provider=provider,
            observed_at=now - timedelta(days=count - index - 1, hours=1),
            close=close,
            operation=operation,
            timezone=timezone,
            received_at=now,
        )
        for index in range(count)
    ]
    result = MarketObservationService().ingest_batch(connection, envelopes, now)
    assert result.accepted == count


def _add_rejection(
    connection: sqlite3.Connection,
    listing_id: int,
    *,
    provider: str,
    capability: str = "EOD",
    operation: str = "daily_prices",
    now: datetime = NOW,
) -> int:
    envelope = _bar(
        listing_id,
        provider=provider,
        observed_at=now,
        close="0",
        operation=operation,
        received_at=now,
    )
    if capability == "QUOTE":
        envelope = replace(
            envelope,
            capability="QUOTE",
            kind="QUOTE",
            source_quality="delayed",
            timezone="UTC",
            raw_fields={"last": "0"},
        )
    result = MarketObservationService().ingest_batch(connection, [envelope], now)
    assert result.rejected == 1
    return int(
        connection.execute(
            "SELECT id FROM market_data_rejections ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    )


def _add_ambiguous_resolution(
    connection: sqlite3.Connection,
    instrument_id: int,
) -> None:
    snapshot_id = int(
        connection.execute(
            """
            INSERT INTO catalog_snapshots (
                source, source_url, content_sha256, retrieved_at, row_count,
                status, parser_version
            )
            VALUES ('test', 'https://example.test/catalog', ?, ?, 1, 'COMPLETE', '1')
            """,
            (_hash("catalog"), NOW.isoformat()),
        ).lastrowid
    )
    entry_id = int(
        connection.execute(
            """
            INSERT INTO catalog_entries (
                snapshot_id, row_number, isin, name, parse_status, reason_code,
                raw_row_sha256, instrument_id
            )
            VALUES (?, 1, 'US0000000001', 'Ambiguous', 'ACCEPTED',
                    'VALID_ISIN', ?, ?)
            """,
            (snapshot_id, _hash("catalog-row"), instrument_id),
        ).lastrowid
    )
    connection.execute(
        """
        INSERT INTO instrument_resolution_cases (
            catalog_entry_id, provider, request_fingerprint, status, reason_code,
            candidate_count, candidate_hash, evidence_hash, created_at
        )
        VALUES (?, 'openfigi', ?, 'AMBIGUOUS',
                'MULTIPLE_COMPATIBLE_CANDIDATES', 2, ?, ?, ?)
        """,
        (
            entry_id,
            _hash("resolution-request"),
            _hash("resolution-candidates"),
            _hash("resolution-evidence"),
            NOW.isoformat(),
        ),
    )


def test_quality_tier_schema_has_projection_and_append_only_history(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_columns = {
        row["name"]
        for row in quality_connection.execute("PRAGMA table_info(instruments)")
    }
    tables = {
        row["name"]
        for row in quality_connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert {"quality_tier", "quality_reason_code", "quality_assessed_at"} <= (
        instrument_columns
    )
    assert "quality_assessments" in tables


@pytest.mark.parametrize("instrument_type", ["MACRO", "RATE", "INDEX", "FX"])
def test_quality_tier_reference_instruments_are_never_promoted(
    quality_connection: sqlite3.Connection,
    instrument_type: str,
) -> None:
    instrument_id, _ = _add_instrument(
        quality_connection,
        instrument_type=instrument_type,
        asset_class="REFERENCE" if instrument_type != "FX" else "FX",
    )

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == "REFERENCE_ONLY"
    assert assessment.reason_codes == ("REFERENCE_INSTRUMENT",)


def test_quality_tier_ambiguous_identity_is_fail_closed(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=60)
    _add_ambiguous_resolution(quality_connection, instrument_id)

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == "REFERENCE_ONLY"
    assert assessment.reason_codes[0] == "AMBIGUOUS_IDENTITY"


def test_quality_tier_missing_primary_id_remains_observable_with_valid_data(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(
        quality_connection,
        primary_scheme=None,
    )
    _add_history(quality_connection, listing_id, count=60)

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == "OBSERVABLE"
    assert assessment.reason_codes == (
        "MISSING_PRIMARY_ID",
        "VALIDATED_OBSERVABLE",
    )


def test_quality_tier_crypto_uses_coingecko_identity_without_inventing_isin(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(
        quality_connection,
        instrument_type="CRYPTO",
        asset_class="CRYPTO",
        ticker="BTC",
        mic=None,
        currency="USD",
        timezone="UTC",
        primary_scheme="COINGECKO_ID",
        primary_value="bitcoin",
    )
    _add_history(
        quality_connection,
        listing_id,
        count=60,
        provider="coingecko",
        timezone="UTC",
    )

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == "QUALIFIED"
    assert assessment.reason_codes == ("QUALIFICATION_RULES_MET",)
    assert quality_connection.execute(
        """
        SELECT COUNT(*) FROM instrument_identifiers
        WHERE instrument_id = ? AND scheme = 'ISIN'
        """,
        (instrument_id,),
    ).fetchone()[0] == 0


def test_quality_tier_duplicate_coingecko_identity_is_ambiguous(
    quality_connection: sqlite3.Connection,
) -> None:
    first_id, first_listing_id = _add_instrument(
        quality_connection,
        instrument_type="CRYPTO",
        asset_class="CRYPTO",
        ticker="BTC",
        mic=None,
        timezone="UTC",
        primary_scheme="COINGECKO_ID",
        primary_value="bitcoin",
    )
    second_id, second_listing_id = _add_instrument(
        quality_connection,
        instrument_type="CRYPTO",
        asset_class="CRYPTO",
        ticker="XBT",
        mic=None,
        timezone="UTC",
        primary_scheme="COINGECKO_ID",
        primary_value="bitcoin",
    )
    _add_history(
        quality_connection,
        first_listing_id,
        count=60,
        timezone="UTC",
    )
    _add_history(
        quality_connection,
        second_listing_id,
        count=60,
        timezone="UTC",
    )
    service = _quality_service()

    assessments = (
        service.assess(quality_connection, first_id, NOW),
        service.assess(quality_connection, second_id, NOW),
    )

    assert all(assessment.tier == "REFERENCE_ONLY" for assessment in assessments)
    assert all(
        assessment.reason_codes == ("AMBIGUOUS_IDENTITY",)
        for assessment in assessments
    )


def test_quality_tier_multiple_coingecko_values_on_one_instrument_are_ambiguous(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(
        quality_connection,
        instrument_type="CRYPTO",
        asset_class="CRYPTO",
        ticker="BTC",
        mic=None,
        timezone="UTC",
        primary_scheme="COINGECKO_ID",
        primary_value="bitcoin",
    )
    second_identifier_id = int(
        quality_connection.execute(
            """
            INSERT INTO instrument_identifiers (
                scheme, normalized_value, scope, instrument_id, listing_id
            )
            VALUES ('COINGECKO_ID', 'wrapped-bitcoin', 'INSTRUMENT', ?, NULL)
            """,
            (instrument_id,),
        ).lastrowid
    )
    quality_connection.execute(
        """
        INSERT INTO instrument_identifier_attestations (
            identifier_id, source, observed_at, evidence_hash
        )
        VALUES (?, 'test', ?, ?)
        """,
        (
            second_identifier_id,
            NOW.isoformat(),
            _hash("second coingecko identity"),
        ),
    )
    _add_history(
        quality_connection,
        listing_id,
        count=60,
        provider="coingecko",
        timezone="UTC",
    )

    assessment = _quality_service().assess(
        quality_connection,
        instrument_id,
        NOW,
    )

    assert assessment.tier == "REFERENCE_ONLY"
    assert assessment.reason_codes == ("AMBIGUOUS_IDENTITY",)


@pytest.mark.parametrize(
    ("instrument_type", "asset_class", "primary_scheme"),
    [
        ("UNKNOWN", "UNKNOWN", "ISIN"),
        ("STOCK", "COMMODITY", "ISIN"),
        ("CRYPTO", "EQUITY", "COINGECKO_ID"),
    ],
)
def test_quality_tier_unknown_or_incoherent_classification_is_not_qualified(
    quality_connection: sqlite3.Connection,
    instrument_type: str,
    asset_class: str,
    primary_scheme: str,
) -> None:
    instrument_id, listing_id = _add_instrument(
        quality_connection,
        instrument_type=instrument_type,
        asset_class=asset_class,
        ticker=f"{instrument_type[:3]}{asset_class[:3]}",
        mic=None if instrument_type == "CRYPTO" else "XNAS",
        timezone="UTC" if instrument_type == "CRYPTO" else "America/New_York",
        primary_scheme=primary_scheme,
        primary_value=(
            f"coingecko-{asset_class.lower()}"
            if primary_scheme == "COINGECKO_ID"
            else f"US00000000{10 + len(asset_class)}"
        ),
    )
    _add_history(
        quality_connection,
        listing_id,
        count=60,
        timezone="UTC" if instrument_type == "CRYPTO" else "America/New_York",
    )

    assessment = _quality_service().assess(
        quality_connection,
        instrument_id,
        NOW,
    )

    assert assessment.tier == "OBSERVABLE"
    assert "MISSING_LISTING_METADATA" in assessment.reason_codes


def test_quality_tier_missing_regulated_listing_metadata_blocks_qualification(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=60)
    quality_connection.execute(
        "UPDATE instrument_listings SET timezone = NULL WHERE id = ?",
        (listing_id,),
    )

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == "OBSERVABLE"
    assert assessment.reason_codes == (
        "MISSING_LISTING_METADATA",
        "VALIDATED_OBSERVABLE",
    )


def test_quality_tier_no_data_and_stale_data_are_reference_only(
    quality_connection: sqlite3.Connection,
) -> None:
    missing_id, _ = _add_instrument(quality_connection, ticker="NONE")
    stale_id, stale_listing_id = _add_instrument(
        quality_connection,
        ticker="OLD",
        primary_value="US0000000002",
    )
    _add_history(
        quality_connection,
        stale_listing_id,
        count=1,
        now=NOW - timedelta(hours=97),
    )

    missing = _quality_service().assess(quality_connection, missing_id, NOW)
    stale = _quality_service().assess(quality_connection, stale_id, NOW)

    assert missing.tier == "REFERENCE_ONLY"
    assert missing.reason_codes == ("NO_VALID_OBSERVATION",)
    assert stale.tier == "REFERENCE_ONLY"
    assert stale.reason_codes == ("STALE_OBSERVATION",)


def test_quality_tier_promotes_at_history_threshold_and_demotes_on_actual_rejection(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(
        quality_connection,
        listing_id,
        count=59,
        now=NOW - timedelta(days=1),
    )
    service = _quality_service()

    observable = service.assess_and_record(quality_connection, instrument_id, NOW)
    final_bar = _bar(
        listing_id,
        provider="fixture_eod",
        observed_at=NOW - timedelta(minutes=30),
        received_at=NOW + timedelta(minutes=1),
    )
    MarketObservationService().ingest_batch(
        quality_connection,
        [final_bar],
        NOW + timedelta(minutes=1),
    )
    qualified = service.assess_and_record(
        quality_connection,
        instrument_id,
        NOW + timedelta(minutes=1),
    )
    _add_rejection(
        quality_connection,
        listing_id,
        provider="fixture_eod",
        now=NOW + timedelta(minutes=2),
    )
    demoted = service.assess_and_record(
        quality_connection,
        instrument_id,
        NOW + timedelta(minutes=2),
    )

    assert observable.tier == "OBSERVABLE"
    assert "INSUFFICIENT_HISTORY" in observable.reason_codes
    assert qualified.tier == "QUALIFIED"
    assert len(qualified.evidence_scopes) == 1
    assert len(qualified.evidence_scopes[0].selected_observation_ids) == 60
    assert demoted.tier == "REFERENCE_ONLY"
    assert demoted.reason_codes[0] == "UNRESOLVED_CRITICAL_REJECTION"
    assert quality_connection.execute(
        "SELECT COUNT(*) FROM quality_assessments WHERE instrument_id = ?",
        (instrument_id,),
    ).fetchone()[0] == 3


def test_quality_tier_requires_60_distinct_daily_bars(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    same_day_bars = [
        _bar(
            listing_id,
            provider="fixture_eod",
            observed_at=NOW - timedelta(minutes=index + 1),
            close=str(100 + index),
        )
        for index in range(60)
    ]
    result = MarketObservationService().ingest_batch(
        quality_connection,
        same_day_bars,
        NOW,
    )

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert result.accepted == 60
    assert assessment.tier == "OBSERVABLE"
    assert assessment.reason_codes[0] == "INSUFFICIENT_HISTORY"
    assert len(assessment.evidence_scopes[0].selected_observation_ids) == 1


def test_quality_tier_observable_assessment_uses_publicly_selected_scope(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(
        quality_connection,
        listing_id,
        count=59,
        now=NOW - timedelta(hours=1),
    )
    quote = replace(
        _bar(
            listing_id,
            provider="fixture_quote",
            observed_at=NOW - timedelta(minutes=5),
            received_at=NOW,
        ),
        capability="QUOTE",
        kind="QUOTE",
        source_quality="delayed",
        timezone="UTC",
        raw_fields={"last": "101"},
        raw_payload_sha256=_hash("newer quote"),
    )
    result = MarketObservationService().ingest_batch(
        quality_connection,
        [quote],
        NOW,
    )
    service = _quality_service()

    assessment = service.assess(quality_connection, instrument_id, NOW)
    selected = service.select_evidence_scopes(
        quality_connection,
        instrument_id,
        "OBSERVABLE",
        NOW,
    )

    assert result.accepted == 1
    assert assessment.tier == "OBSERVABLE"
    assert assessment.evidence_scopes == selected
    assert assessment.evidence_scopes[0].capability == "QUOTE"


def test_quality_tier_optional_quote_rejection_does_not_demote_eod_history(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=60)
    _add_rejection(
        quality_connection,
        listing_id,
        provider="finnhub",
        capability="QUOTE",
        operation="quote_snapshot",
    )

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == "QUALIFIED"
    assert "UNRESOLVED_CRITICAL_REJECTION" not in assessment.reason_codes


def test_quality_tier_compatible_fallback_uses_actual_provider_scope(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    quality_connection.execute(
        """
        INSERT INTO provider_symbols (
            provider, listing_id, capability, provider_symbol, normalized_symbol,
            status, source, observed_at, verified_at, evidence_hash
        )
        VALUES ('primary_eod', ?, 'EOD', 'ACME', 'ACME', 'VERIFIED',
                'test', ?, ?, ?)
        """,
        (listing_id, NOW.isoformat(), NOW.isoformat(), _hash("primary mapping")),
    )
    _add_rejection(
        quality_connection,
        listing_id,
        provider="primary_eod",
    )
    _add_history(
        quality_connection,
        listing_id,
        count=60,
        provider="fallback_eod",
    )

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == "QUALIFIED"
    assert assessment.reason_codes == (
        "QUALIFICATION_RULES_MET",
        "COMPATIBLE_FALLBACK_IN_USE",
    )
    assert assessment.evidence_scopes[0].actual_provider == "fallback_eod"


def test_quality_tier_open_rejection_on_selected_fallback_demotes(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(
        quality_connection,
        listing_id,
        count=60,
        provider="fallback_eod",
    )
    _add_rejection(
        quality_connection,
        listing_id,
        provider="fallback_eod",
        now=NOW + timedelta(minutes=1),
    )

    assessment = _quality_service().assess(
        quality_connection,
        instrument_id,
        NOW + timedelta(minutes=1),
    )

    assert assessment.tier == "REFERENCE_ONLY"
    assert assessment.reason_codes[0] == "UNRESOLVED_CRITICAL_REJECTION"


def test_quality_tier_rejection_resolution_recovers_qualification(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(
        quality_connection,
        listing_id,
        count=59,
        now=NOW - timedelta(days=1),
    )
    corrupt_without_timestamp = replace(
        _bar(
            listing_id,
            provider="fixture_eod",
            observed_at=NOW,
            received_at=NOW + timedelta(minutes=1),
        ),
        provider_observed_at=None,
        raw_payload_sha256=_hash("corrupt without timestamp"),
    )
    rejected = MarketObservationService().ingest_batch(
        quality_connection,
        [corrupt_without_timestamp],
        NOW + timedelta(minutes=1),
    )
    rejection = quality_connection.execute(
        """
        SELECT id, reason_code
        FROM market_data_rejections
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    assert rejected.rejected == 1
    assert rejection["reason_code"] == "INVALID_TIMESTAMP"
    rejection_id = int(rejection["id"])
    service = _quality_service()

    blocked = service.assess(
        quality_connection,
        instrument_id,
        NOW + timedelta(minutes=1),
    )
    recovery_bar = _bar(
        listing_id,
        provider="fixture_eod",
        observed_at=NOW + timedelta(minutes=1),
        received_at=NOW + timedelta(minutes=2),
    )
    MarketObservationService().ingest_batch(
        quality_connection,
        [recovery_bar],
        NOW + timedelta(minutes=2),
    )
    recovered = service.assess(
        quality_connection,
        instrument_id,
        NOW + timedelta(minutes=2),
    )

    assert blocked.tier == "REFERENCE_ONLY"
    assert blocked.reason_codes[0] == "UNRESOLVED_CRITICAL_REJECTION"
    assert recovered.tier == "QUALIFIED"
    assert quality_connection.execute(
        """
        SELECT COUNT(*) FROM market_data_rejection_resolutions
        WHERE rejection_id = ?
        """,
        (rejection_id,),
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("other_close", "expected_tier"),
    [("105", "QUALIFIED"), ("105.01", "REFERENCE_ONLY")],
)
def test_quality_tier_divergence_threshold_is_strictly_above_500_bps(
    quality_connection: sqlite3.Connection,
    other_close: str,
    expected_tier: str,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(
        quality_connection,
        listing_id,
        count=60,
        provider="provider_a",
        close="100",
    )
    _add_history(
        quality_connection,
        listing_id,
        count=60,
        provider="provider_b",
        close=other_close,
    )

    assessment = _quality_service().assess(quality_connection, instrument_id, NOW)

    assert assessment.tier == expected_tier
    assert ("PROVIDER_DIVERGENCE" in assessment.reason_codes) is (
        expected_tier == "REFERENCE_ONLY"
    )


def test_quality_tier_assessment_is_idempotent_and_history_is_append_only(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=60)
    service = _quality_service()

    first = service.assess_and_record(quality_connection, instrument_id, NOW)
    second = service.assess_and_record(quality_connection, instrument_id, NOW)
    assessment_id = quality_connection.execute(
        "SELECT id FROM quality_assessments WHERE instrument_id = ?",
        (instrument_id,),
    ).fetchone()[0]

    assert second == first
    assert quality_connection.execute(
        "SELECT COUNT(*) FROM quality_assessments WHERE instrument_id = ?",
        (instrument_id,),
    ).fetchone()[0] == 1
    projection = quality_connection.execute(
        """
        SELECT quality_tier, quality_reason_code, quality_assessed_at
        FROM instruments WHERE id = ?
        """,
        (instrument_id,),
    ).fetchone()
    assert dict(projection) == {
        "quality_tier": "QUALIFIED",
        "quality_reason_code": "QUALIFICATION_RULES_MET",
        "quality_assessed_at": NOW.isoformat(),
    }
    with pytest.raises(sqlite3.IntegrityError):
        quality_connection.execute(
            "UPDATE quality_assessments SET tier = tier WHERE id = ?",
            (assessment_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        quality_connection.execute(
            "DELETE FROM quality_assessments WHERE id = ?",
            (assessment_id,),
        )


def test_quality_tier_records_return_to_prior_evidence_as_new_transition(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=60)
    default_service = _quality_service()
    stricter_service = _quality_service(
        settings=replace(
            get_settings(),
            market_data_qualified_history_bars=61,
        )
    )

    first = default_service.assess_and_record(
        quality_connection,
        instrument_id,
        NOW,
    )
    middle = stricter_service.assess_and_record(
        quality_connection,
        instrument_id,
        NOW + timedelta(minutes=1),
    )
    returned = default_service.assess_and_record(
        quality_connection,
        instrument_id,
        NOW + timedelta(minutes=2),
    )

    history = quality_connection.execute(
        """
        SELECT tier, assessed_at, evidence_hash
        FROM quality_assessments
        WHERE instrument_id = ?
        ORDER BY id
        """,
        (instrument_id,),
    ).fetchall()
    projection = quality_connection.execute(
        """
        SELECT quality_tier, quality_assessed_at
        FROM instruments
        WHERE id = ?
        """,
        (instrument_id,),
    ).fetchone()

    assert first.tier == returned.tier == "QUALIFIED"
    assert middle.tier == "OBSERVABLE"
    assert first.evidence_hash == returned.evidence_hash
    assert len(history) == 3
    assert [row["tier"] for row in history] == [
        "QUALIFIED",
        "OBSERVABLE",
        "QUALIFIED",
    ]
    assert returned.assessed_at == NOW + timedelta(minutes=2)
    assert projection["quality_tier"] == "QUALIFIED"
    assert projection["quality_assessed_at"] == returned.assessed_at.isoformat()


def test_quality_tier_strategy_eligibility_requires_recent_verified_tr_status(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(
        quality_connection,
        trade_republic_status="CATALOGED",
    )
    _add_history(quality_connection, listing_id, count=60)
    service = _quality_service()
    service.assess_and_record(quality_connection, instrument_id, NOW)

    assert service.eligible_for_strategy(
        quality_connection,
        instrument_id,
        NOW,
        require_trade_republic=False,
    ) is True
    assert service.eligible_for_strategy(
        quality_connection,
        instrument_id,
        NOW,
        require_trade_republic=True,
    ) is False

    quality_connection.execute(
        """
        UPDATE instrument_listings
        SET trade_republic_status = 'VERIFIED', trade_republic_verified_at = ?
        WHERE id = ?
        """,
        ((NOW - timedelta(days=30)).isoformat(), listing_id),
    )
    assert service.eligible_for_strategy(
        quality_connection,
        instrument_id,
        NOW,
        require_trade_republic=True,
    ) is True

    quality_connection.execute(
        "UPDATE instrument_listings SET trade_republic_verified_at = ? WHERE id = ?",
        ((NOW - timedelta(days=30, seconds=1)).isoformat(), listing_id),
    )
    assert service.eligible_for_strategy(
        quality_connection,
        instrument_id,
        NOW,
        require_trade_republic=True,
    ) is False


def test_quality_tier_strategy_eligibility_requires_recorded_qualification(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=60)
    quality_connection.execute(
        """
        UPDATE instruments
        SET quality_tier = 'QUALIFIED',
            quality_reason_code = 'QUALIFICATION_RULES_MET',
            quality_assessed_at = ?
        WHERE id = ?
        """,
        (NOW.isoformat(), instrument_id),
    )

    assert _quality_service().eligible_for_strategy(
        quality_connection,
        instrument_id,
        NOW,
        require_trade_republic=False,
    ) is False


def test_quality_tier_trade_republic_status_does_not_change_quality_evidence(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=60)
    service = _quality_service()
    before = service.assess(quality_connection, instrument_id, NOW)

    quality_connection.execute(
        """
        UPDATE instrument_listings
        SET trade_republic_status = 'VERIFIED', trade_republic_verified_at = ?
        WHERE id = ?
        """,
        (NOW.isoformat(), listing_id),
    )
    after = service.assess(quality_connection, instrument_id, NOW)

    assert before.tier == after.tier == "QUALIFIED"
    assert before.evidence_hash == after.evidence_hash


def test_quality_tier_thresholds_can_be_overridden_without_changing_defaults(
    quality_connection: sqlite3.Connection,
) -> None:
    instrument_id, listing_id = _add_instrument(quality_connection)
    _add_history(quality_connection, listing_id, count=2)
    settings = replace(get_settings(), market_data_qualified_history_bars=2)

    assessment = _quality_service(settings=settings).assess(
        quality_connection,
        instrument_id,
        NOW,
    )

    assert get_settings().market_data_qualified_history_bars == 60
    assert assessment.tier == "QUALIFIED"
