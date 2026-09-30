from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args

import pytest

from backend.app.config import get_settings
from backend.app.database import SCHEMA, migrate_db
from backend.app.models.market_data import (
    ADAPTER_VALIDATION_REASONS,
    EffectiveObservationQuality,
    MarketObservation,
    MarketObservationEnvelope,
    ObservationRejection,
    SourceObservationQuality,
    ValidatedObservation,
    ValidationReason,
)
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.prices_service import get_price_history

NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


def _freeze_service_clock(monkeypatch: pytest.MonkeyPatch, *modules: str) -> None:
    """Blocca `datetime.now` dei servizi su NOW: la freschezza non dipende dal calendario reale."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return NOW.replace(tzinfo=None) if tz is None else NOW.astimezone(tz)

    for module in modules:
        monkeypatch.setattr(f"{module}.datetime", FrozenDatetime)


def _payload_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@pytest.fixture
def market_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
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
        VALUES ('ACME', 'Acme Corp', 'stock', 'USD', 'medium', ?)
        """,
        (listing_id,),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _listing(connection: sqlite3.Connection) -> sqlite3.Row:
    return connection.execute(
        "SELECT * FROM instrument_listings WHERE ticker = 'ACME'"
    ).fetchone()


def _envelope(listing_id: int, **changes: object) -> MarketObservationEnvelope:
    envelope = MarketObservationEnvelope(
        listing_id=listing_id,
        provider="fixture_eod",
        capability="EOD",
        operation="daily_prices",
        received_at=NOW,
        provider_observed_at=NOW - timedelta(hours=1),
        timezone="America/New_York",
        session="REGULAR",
        currency="USD",
        source_quality="eod",
        kind="BAR",
        raw_fields={
            "open": "100.10",
            "high": "105.25",
            "low": "99.50",
            "close": "104.75",
            "adjusted_close": "104.75",
            "volume": "1200",
        },
        raw_payload_sha256=_payload_hash("valid"),
    )
    return replace(envelope, **changes)


def test_validation_allowlists_are_exact_and_cover_planned_adapter_reasons() -> None:
    assert set(get_args(ValidationReason)) == {
        "MISSING_PRICE",
        "NON_FINITE",
        "NON_POSITIVE",
        "CROSSED_QUOTE",
        "INVALID_OHLC",
        "NEGATIVE_VOLUME",
        "CURRENCY_MISMATCH",
        "INVALID_TIMESTAMP",
        "FUTURE_TIMESTAMP",
        "INVALID_TIMEZONE",
        "INVALID_DELAY",
        "MALFORMED_PAYLOAD",
        "PROVIDER_NO_DATA",
        "MISSING_VALUE",
    }
    assert set(ADAPTER_VALIDATION_REASONS) == {"PROVIDER_NO_DATA", "MISSING_VALUE"}
    assert set(ADAPTER_VALIDATION_REASONS) <= set(get_args(ValidationReason))
    assert set(get_args(SourceObservationQuality)) == {
        "realtime",
        "delayed",
        "eod",
        "reference",
    }
    assert set(get_args(EffectiveObservationQuality)) == {
        "realtime",
        "delayed",
        "eod",
        "reference",
        "stale",
    }


def test_valid_bar_is_normalized_to_decimals_without_changing_source_quality(
    market_connection: sqlite3.Connection,
) -> None:
    listing = _listing(market_connection)

    result = MarketObservationService().validate(
        listing,
        _envelope(int(listing["id"])),
        NOW,
    )

    assert isinstance(result, ValidatedObservation)
    assert result.observation.close == Decimal("104.75")
    assert result.observation.volume == Decimal("1200")
    assert result.observation.delay_seconds == 3600
    assert result.observation.source_quality == "eod"
    assert result.effective_quality == "eod"
    assert len(result.observation_hash) == 64


@pytest.mark.parametrize(
    ("case", "changes", "expected_reason"),
    [
        (
            "missing prices",
            {"raw_fields": {"volume": "10"}},
            "MISSING_PRICE",
        ),
        (
            "nan",
            {"raw_fields": {"close": float("nan")}},
            "NON_FINITE",
        ),
        (
            "infinity",
            {"raw_fields": {"close": float("inf")}},
            "NON_FINITE",
        ),
        (
            "zero price",
            {"raw_fields": {"close": 0}},
            "NON_POSITIVE",
        ),
        (
            "negative price",
            {"raw_fields": {"close": -1}},
            "NON_POSITIVE",
        ),
        (
            "crossed quote",
            {
                "kind": "QUOTE",
                "capability": "QUOTE",
                "source_quality": "realtime",
                "raw_fields": {"bid": "101", "ask": "100"},
            },
            "CROSSED_QUOTE",
        ),
        (
            "invalid ohlc",
            {
                "raw_fields": {
                    "open": "100",
                    "high": "99",
                    "low": "90",
                    "close": "101",
                }
            },
            "INVALID_OHLC",
        ),
        (
            "negative volume",
            {"raw_fields": {"close": "100", "volume": "-0.1"}},
            "NEGATIVE_VOLUME",
        ),
        (
            "currency mismatch",
            {"currency": "EUR"},
            "CURRENCY_MISMATCH",
        ),
        (
            "currency not uppercase",
            {"currency": "usd"},
            "CURRENCY_MISMATCH",
        ),
        (
            "missing timestamp",
            {"provider_observed_at": None},
            "INVALID_TIMESTAMP",
        ),
        (
            "naive timestamp",
            {"provider_observed_at": NOW.replace(tzinfo=None)},
            "INVALID_TIMESTAMP",
        ),
        (
            "future timestamp",
            {"provider_observed_at": NOW + timedelta(minutes=6)},
            "FUTURE_TIMESTAMP",
        ),
        (
            "invalid timezone",
            {"timezone": "Mars/Olympus"},
            "INVALID_TIMEZONE",
        ),
        (
            "bar timezone mismatch",
            {"timezone": "Europe/Rome"},
            "INVALID_TIMEZONE",
        ),
        (
            "negative delay",
            {"provider_observed_at": NOW + timedelta(minutes=1)},
            "INVALID_DELAY",
        ),
        (
            "corrupt numeric field",
            {"raw_fields": {"close": object()}},
            "MALFORMED_PAYLOAD",
        ),
        (
            "invalid raw hash",
            {"raw_payload_sha256": "provider raw text"},
            "MALFORMED_PAYLOAD",
        ),
        (
            "quote capability with bar kind",
            {"capability": "QUOTE", "kind": "BAR", "source_quality": "delayed"},
            "MALFORMED_PAYLOAD",
        ),
        (
            "eod capability with quote kind",
            {"capability": "EOD", "kind": "QUOTE"},
            "MALFORMED_PAYLOAD",
        ),
        (
            "missing session",
            {"session": None},
            "MALFORMED_PAYLOAD",
        ),
        (
            "missing kind",
            {"kind": None},
            "MALFORMED_PAYLOAD",
        ),
        (
            "missing source quality",
            {"source_quality": None},
            "MALFORMED_PAYLOAD",
        ),
    ],
    ids=lambda item: item if isinstance(item, str) else None,
)
def test_quality_gate_returns_stable_reason_codes(
    market_connection: sqlite3.Connection,
    case: str,
    changes: dict[str, object],
    expected_reason: str,
) -> None:
    del case
    listing = _listing(market_connection)

    result = MarketObservationService().validate(
        listing,
        _envelope(int(listing["id"]), **changes),
        NOW,
    )

    assert isinstance(result, ObservationRejection)
    assert result.reason_code == expected_reason


@pytest.mark.parametrize("reason", sorted(ADAPTER_VALIDATION_REASONS))
def test_adapter_no_data_and_missing_value_use_the_common_rejection_lifecycle(
    market_connection: sqlite3.Connection,
    reason: str,
) -> None:
    listing = _listing(market_connection)
    envelope = _envelope(
        int(listing["id"]),
        provider_observed_at=None,
        timezone=None,
        session=None,
        currency=None,
        source_quality=None,
        kind=None,
        raw_fields={"reason_code": reason, "provider_message": "must-not-persist"},
        raw_payload_sha256=_payload_hash(reason),
    )

    result = MarketObservationService().ingest_batch(market_connection, [envelope], NOW)

    assert result.rejected == 1
    row = market_connection.execute(
        "SELECT reason_code, raw_payload_sha256 FROM market_data_rejections"
    ).fetchone()
    assert dict(row) == {
        "reason_code": reason,
        "raw_payload_sha256": _payload_hash(reason),
    }
    columns = {
        item["name"]
        for item in market_connection.execute(
            "PRAGMA table_info(market_data_rejections)"
        ).fetchall()
    }
    assert "raw_fields" not in columns
    assert "raw_payload" not in columns
    assert "provider_message" not in columns


def test_ingest_batch_persists_valid_and_rejected_rows_before_projecting_only_valid_bars(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    valid = _envelope(listing_id)
    invalid = _envelope(
        listing_id,
        operation="quote_snapshot",
        capability="QUOTE",
        kind="QUOTE",
        source_quality="realtime",
        raw_fields={"last": 0},
        raw_payload_sha256=_payload_hash("invalid"),
    )

    result = MarketObservationService().ingest_batch(
        market_connection,
        [valid, invalid],
        NOW,
    )

    assert result.accepted == 1
    assert result.rejected == 1
    assert result.duplicates == 0
    assert result.revisions == 0
    assert result.projected_price_rows == 1
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_observations"
    ).fetchone()[0] == 1
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_data_rejections"
    ).fetchone()[0] == 1


def test_same_observation_hash_deduplicates_across_ingest_clocks(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    first_now = NOW
    observed_at = first_now - timedelta(minutes=4)
    first = _envelope(
        listing_id,
        capability="QUOTE",
        operation="quote_snapshot",
        kind="QUOTE",
        source_quality="realtime",
        provider_observed_at=observed_at,
        raw_fields={"last": "101.0000"},
        raw_payload_sha256=_payload_hash("first wire representation"),
    )
    second = replace(
        first,
        received_at=NOW + timedelta(minutes=10),
        raw_fields={"last": 101},
        raw_payload_sha256=_payload_hash("second wire representation"),
    )
    service = MarketObservationService()

    validated_first = service.validate(_listing(market_connection), first, first_now)
    validated_second = service.validate(
        _listing(market_connection),
        second,
        NOW + timedelta(minutes=10),
    )
    assert isinstance(validated_first, ValidatedObservation)
    assert isinstance(validated_second, ValidatedObservation)
    assert validated_first.effective_quality == "realtime"
    assert validated_second.effective_quality == "stale"
    assert validated_first.observation_hash == validated_second.observation_hash

    first_result = service.ingest_batch(market_connection, [first], first_now)
    second_result = service.ingest_batch(
        market_connection,
        [second],
        NOW + timedelta(minutes=10),
    )

    assert first_result.accepted == 1
    assert second_result.accepted == 0
    assert second_result.duplicates == 1
    assert second_result.revisions == 0
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_observations"
    ).fetchone()[0] == 1


def test_timezone_change_creates_revision_for_same_quote_scope(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    first = _envelope(
        listing_id,
        capability="QUOTE",
        operation="quote_snapshot",
        kind="QUOTE",
        source_quality="delayed",
        raw_fields={"last": "101"},
    )
    corrected_timezone = replace(
        first,
        timezone="UTC",
        raw_payload_sha256=_payload_hash("corrected timezone"),
    )
    service = MarketObservationService()

    service.ingest_batch(market_connection, [first], NOW)
    result = service.ingest_batch(market_connection, [corrected_timezone], NOW)

    assert result.revisions == 1
    rows = market_connection.execute(
        """
        SELECT revision, supersedes_observation_id, timezone
        FROM market_observations
        ORDER BY revision
        """
    ).fetchall()
    assert [row["revision"] for row in rows] == [1, 2]
    assert rows[1]["supersedes_observation_id"] is not None
    assert rows[1]["timezone"] == "UTC"


def test_provider_correction_creates_revision_and_reprojects_same_date(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    original = _envelope(listing_id)
    corrected = replace(
        original,
        raw_fields={**original.raw_fields, "close": "103.25", "adjusted_close": "103.25"},
        raw_payload_sha256=_payload_hash("provider correction"),
    )

    first = service.ingest_batch(market_connection, [original], NOW)
    projected_first = market_connection.execute(
        "SELECT close, observation_id FROM price_history"
    ).fetchone()
    second = service.ingest_batch(market_connection, [corrected], NOW)
    projected_second = market_connection.execute(
        "SELECT close, observation_id FROM price_history"
    ).fetchone()

    assert first.revisions == 0
    assert second.revisions == 1
    assert second.projected_price_rows == 1
    assert projected_first["close"] == pytest.approx(104.75)
    assert projected_second["close"] == pytest.approx(103.25)
    assert projected_second["observation_id"] != projected_first["observation_id"]


def test_same_timestamp_from_different_providers_is_not_a_revision(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    primary = _envelope(listing_id)
    fallback = replace(
        primary,
        provider="fixture_fallback",
        raw_payload_sha256=_payload_hash("fallback provider"),
    )

    result = MarketObservationService().ingest_batch(
        market_connection,
        [primary, fallback],
        NOW,
    )

    assert result.accepted == 2
    assert result.revisions == 0
    rows = market_connection.execute(
        "SELECT provider, revision, supersedes_observation_id FROM market_observations"
    ).fetchall()
    assert {row["provider"] for row in rows} == {"fixture_eod", "fixture_fallback"}
    assert {row["revision"] for row in rows} == {1}
    assert all(row["supersedes_observation_id"] is None for row in rows)


def test_valid_observation_resolves_all_earlier_open_rejections_in_same_scope(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    rejected = _envelope(
        listing_id,
        provider_observed_at=None,
        raw_payload_sha256=_payload_hash("bad timestamp one"),
    )
    rejected_again = replace(
        rejected,
        received_at=NOW + timedelta(minutes=1),
        raw_payload_sha256=_payload_hash("bad timestamp two"),
    )
    service.ingest_batch(market_connection, [rejected, rejected_again], NOW)

    accepted = replace(
        _envelope(listing_id),
        received_at=NOW + timedelta(minutes=2),
    )
    result = service.ingest_batch(
        market_connection,
        [accepted],
        NOW + timedelta(minutes=2),
    )

    assert result.resolved_rejections == 2
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_data_rejection_resolutions"
    ).fetchone()[0] == 2
    assert market_connection.execute(
        """
        SELECT COUNT(*)
        FROM market_data_rejections AS rejection
        LEFT JOIN market_data_rejection_resolutions AS resolution
          ON resolution.rejection_id = rejection.id
        WHERE resolution.id IS NULL
        """
    ).fetchone()[0] == 0


def test_rejection_in_other_scope_is_not_resolved(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    rejected_quote = _envelope(
        listing_id,
        capability="QUOTE",
        operation="quote_snapshot",
        kind="QUOTE",
        source_quality="realtime",
        provider_observed_at=None,
        raw_payload_sha256=_payload_hash("bad quote"),
    )
    service.ingest_batch(market_connection, [rejected_quote], NOW)

    result = service.ingest_batch(market_connection, [_envelope(listing_id)], NOW)

    assert result.resolved_rejections == 0
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_data_rejection_resolutions"
    ).fetchone()[0] == 0


def test_duplicate_does_not_backdate_resolution_with_an_older_observation(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    original = _envelope(listing_id)
    service.ingest_batch(market_connection, [original], NOW)
    rejection = replace(
        original,
        received_at=NOW + timedelta(minutes=1),
        provider_observed_at=None,
        raw_payload_sha256=_payload_hash("rejection after observation"),
    )
    service.ingest_batch(
        market_connection,
        [rejection],
        NOW + timedelta(minutes=1),
    )
    duplicate = replace(
        original,
        received_at=NOW + timedelta(minutes=2),
        raw_payload_sha256=_payload_hash("duplicate after rejection"),
    )

    result = service.ingest_batch(
        market_connection,
        [duplicate],
        NOW + timedelta(minutes=2),
    )

    assert result.duplicates == 1
    assert result.resolved_rejections == 0
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_data_rejection_resolutions"
    ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("capability", "source_quality", "age", "expected"),
    [
        ("QUOTE", "realtime", timedelta(minutes=4), "realtime"),
        ("QUOTE", "realtime", timedelta(minutes=6), "stale"),
        ("QUOTE", "delayed", timedelta(minutes=29), "delayed"),
        ("QUOTE", "delayed", timedelta(minutes=31), "stale"),
        ("EOD", "eod", timedelta(hours=95), "eod"),
        ("EOD", "eod", timedelta(hours=97), "stale"),
        ("REFERENCE", "reference", timedelta(days=6), "reference"),
        ("FX", "reference", timedelta(days=8), "stale"),
    ],
)
def test_freshness_thresholds_use_injected_clock_without_rewriting_source_quality(
    market_connection: sqlite3.Connection,
    capability: str,
    source_quality: str,
    age: timedelta,
    expected: str,
) -> None:
    listing = _listing(market_connection)
    kind = "QUOTE" if capability == "QUOTE" else "BAR"
    fields = {"last": "100"} if kind == "QUOTE" else {"close": "100"}
    envelope = _envelope(
        int(listing["id"]),
        capability=capability,
        source_quality=source_quality,
        kind=kind,
        provider_observed_at=NOW - age,
        raw_fields=fields,
    )

    result = MarketObservationService().validate(listing, envelope, NOW)

    assert isinstance(result, ValidatedObservation)
    assert result.observation.source_quality == source_quality
    assert result.effective_quality == expected


def test_invalid_only_batch_never_overwrites_last_good_projection(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    service.ingest_batch(market_connection, [_envelope(listing_id)], NOW)
    before = dict(
        market_connection.execute(
            "SELECT close, observation_id, fetched_at FROM price_history"
        ).fetchone()
    )

    result = service.ingest_batch(
        market_connection,
        [
            _envelope(
                listing_id,
                provider_observed_at=NOW,
                raw_fields={"close": "-999"},
                raw_payload_sha256=_payload_hash("bad replacement"),
            )
        ],
        NOW + timedelta(minutes=1),
    )
    after = dict(
        market_connection.execute(
            "SELECT close, observation_id, fetched_at FROM price_history"
        ).fetchone()
    )

    assert result.accepted == 0
    assert result.rejected == 1
    assert result.projected_price_rows == 0
    assert after == before


def test_latest_compatible_records_provider_fallback_selection_event(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    market_connection.execute(
        """
        INSERT INTO provider_symbols (
            provider, listing_id, capability, provider_symbol, normalized_symbol,
            status, source, observed_at, verified_at, evidence_hash
        )
        VALUES (
            'requested_primary', ?, 'EOD', 'ACME', 'ACME', 'VERIFIED',
            'test', ?, ?, ?
        )
        """,
        (listing_id, NOW.isoformat(), NOW.isoformat(), _payload_hash("mapping")),
    )
    fallback = _envelope(
        listing_id,
        provider="actual_fallback",
        raw_payload_sha256=_payload_hash("actual fallback"),
    )
    service = MarketObservationService()
    service.ingest_batch(market_connection, [fallback], NOW)

    selected = service.latest_compatible(market_connection, listing_id, "EOD", NOW)

    assert isinstance(selected, MarketObservation)
    assert selected.provider == "actual_fallback"
    event = market_connection.execute(
        """
        SELECT requested_provider, actual_provider, fallback_reason
        FROM market_data_selection_events
        """
    ).fetchone()
    assert dict(event) == {
        "requested_provider": "requested_primary",
        "actual_provider": "actual_fallback",
        "fallback_reason": "PROVIDER_FALLBACK",
    }


def test_latest_compatible_marks_stale_last_good_without_mutating_observation(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    stale_quote = _envelope(
        listing_id,
        capability="QUOTE",
        operation="quote_snapshot",
        kind="QUOTE",
        source_quality="realtime",
        provider_observed_at=NOW - timedelta(minutes=10),
        raw_fields={"last": "101"},
    )
    service = MarketObservationService()
    service.ingest_batch(market_connection, [stale_quote], NOW)

    selected = service.latest_compatible(market_connection, listing_id, "QUOTE", NOW)

    assert selected is not None
    assert selected.source_quality == "realtime"
    event = market_connection.execute(
        "SELECT fallback_reason FROM market_data_selection_events"
    ).fetchone()
    assert event["fallback_reason"] == "LAST_GOOD_STALE"


def test_quality_tier_freshness_policy_uses_configured_eod_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MARKET_DATA_EOD_MAX_AGE_HOURS", "2")
    get_settings.cache_clear()
    try:
        assert MarketObservationService.effective_quality_for(
            "EOD",
            "eod",
            NOW - timedelta(hours=3),
            NOW,
        ) == "stale"
    finally:
        get_settings.cache_clear()


def test_price_history_projection_exposes_provenance_and_fallback_fields(
    market_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_service_clock(monkeypatch, "backend.app.services.prices_service")
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    service.ingest_batch(market_connection, [_envelope(listing_id)], NOW)
    service.latest_compatible(market_connection, listing_id, "EOD", NOW)

    history = get_price_history(market_connection, "ACME")

    assert history is not None
    point = history.prices[-1]
    assert point.listing_id == listing_id
    assert point.observation_id is not None
    assert point.provider_observed_at == (NOW - timedelta(hours=1)).isoformat()
    assert point.ingested_at == NOW.isoformat()
    assert point.timezone == "America/New_York"
    assert point.session == "REGULAR"
    assert point.currency == "USD"
    assert point.delay_seconds == 3600
    assert point.source_quality == "eod"
    assert point.effective_quality == "eod"
    assert point.fallback_reason == "LAST_GOOD"


def test_observation_rejection_resolution_and_selection_tables_are_append_only(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    rejected = _envelope(
        listing_id,
        provider_observed_at=None,
        raw_payload_sha256=_payload_hash("append only rejection"),
    )
    service.ingest_batch(market_connection, [rejected], NOW)
    service.ingest_batch(
        market_connection,
        [replace(_envelope(listing_id), received_at=NOW + timedelta(minutes=1))],
        NOW + timedelta(minutes=1),
    )
    stale_now = NOW + timedelta(days=5)
    service.latest_compatible(market_connection, listing_id, "EOD", stale_now)

    for table in (
        "market_observations",
        "market_data_rejections",
        "market_data_rejection_resolutions",
        "market_data_selection_events",
    ):
        row_id = market_connection.execute(f"SELECT id FROM {table} LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            market_connection.execute(
                f"UPDATE {table} SET id = id WHERE id = ?",
                (row_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            market_connection.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))


def test_legacy_full_history_refresh_preserves_dates_absent_from_new_batch(
    market_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset_id = market_connection.execute(
        "SELECT id FROM assets WHERE symbol = 'ACME'"
    ).fetchone()[0]
    market_connection.executemany(
        """
        INSERT INTO price_history (
            asset_id, date, open, high, low, close, adjusted_close, volume, source
        )
        VALUES (?, ?, 90, 92, 89, ?, ?, 10, 'seed')
        """,
        [
            (asset_id, "2026-08-14", 91, 91),
            (asset_id, "2026-08-15", 92, 92),
        ],
    )

    class FullHistoryFixtureProvider:
        provider_name = "fixture_full_history"
        full_history = True

        @staticmethod
        def api_key_configured() -> bool:
            return True

        @staticmethod
        def get_daily_prices(symbol: str, force: bool = False):
            assert symbol == "ACME"
            assert force is True
            return (
                [
                    {
                        "date": "2026-08-15",
                        "open": 100,
                        "high": 106,
                        "low": 99,
                        "close": 105,
                        "adjusted_close": 105,
                        "volume": 20,
                    }
                ],
                False,
            )

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    service = MarketDataService()
    monkeypatch.setattr(
        service,
        "get_provider_for_asset",
        lambda connection, asset_type: FullHistoryFixtureProvider(),
    )

    result = service.refresh_asset_prices(market_connection, "ACME", force=True)
    dates = market_connection.execute(
        "SELECT date, close FROM price_history WHERE asset_id = ? ORDER BY date",
        (asset_id,),
    ).fetchall()

    assert result["used_fallback"] is False
    assert [(row["date"], row["close"]) for row in dates] == [
        ("2026-08-14", 91.0),
        ("2026-08-15", 105.0),
    ]
    get_settings.cache_clear()


def test_subsecond_provider_timestamps_remain_distinct_logical_observations(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    first = _envelope(
        listing_id,
        provider_observed_at=(NOW - timedelta(hours=1)).replace(microsecond=100_000),
    )
    second = replace(
        first,
        provider_observed_at=first.provider_observed_at + timedelta(microseconds=100_000),
        raw_payload_sha256=_payload_hash("second subsecond observation"),
    )

    result = MarketObservationService().ingest_batch(
        market_connection,
        [first, second],
        NOW,
    )

    assert result.accepted == 2
    assert result.duplicates == 0
    assert result.revisions == 0
    timestamps = market_connection.execute(
        "SELECT provider_observed_at FROM market_observations ORDER BY id"
    ).fetchall()
    assert len({row["provider_observed_at"] for row in timestamps}) == 2


def test_subsecond_future_timestamp_is_rejected_as_negative_delay(
    market_connection: sqlite3.Connection,
) -> None:
    listing = _listing(market_connection)

    result = MarketObservationService().validate(
        listing,
        _envelope(
            int(listing["id"]),
            provider_observed_at=NOW + timedelta(microseconds=500_000),
        ),
        NOW,
    )

    assert isinstance(result, ObservationRejection)
    assert result.reason_code == "INVALID_DELAY"


def test_same_batch_rejection_resolution_is_independent_from_input_order(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    valid = _envelope(listing_id)
    rejected = replace(
        valid,
        provider_observed_at=None,
        raw_payload_sha256=_payload_hash("same batch rejected after valid"),
    )

    result = MarketObservationService().ingest_batch(
        market_connection,
        [valid, rejected],
        NOW,
    )

    assert result.accepted == 1
    assert result.rejected == 1
    assert result.resolved_rejections == 1
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_data_rejection_resolutions"
    ).fetchone()[0] == 1


def test_ingest_batch_keeps_caller_transaction_rollbackable(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    rejected = _envelope(
        listing_id,
        operation="quote_snapshot",
        capability="QUOTE",
        kind="QUOTE",
        source_quality="realtime",
        raw_fields={"last": 0},
        raw_payload_sha256=_payload_hash("rollback rejection"),
    )
    assert market_connection.in_transaction is False

    MarketObservationService().ingest_batch(
        market_connection,
        [_envelope(listing_id), rejected],
        NOW,
    )

    assert market_connection.in_transaction is True
    market_connection.rollback()
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_observations"
    ).fetchone()[0] == 0
    assert market_connection.execute(
        "SELECT COUNT(*) FROM market_data_rejections"
    ).fetchone()[0] == 0
    assert market_connection.execute(
        "SELECT COUNT(*) FROM price_history"
    ).fetchone()[0] == 0


def test_older_provider_bar_cannot_replace_newer_same_date_projection(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    newer = _envelope(
        listing_id,
        provider="newer",
        provider_observed_at=NOW - timedelta(hours=1),
        raw_fields={"close": "100"},
        raw_payload_sha256=_payload_hash("newer bar"),
    )
    older = replace(
        newer,
        provider="older_later",
        provider_observed_at=NOW - timedelta(hours=8),
        raw_fields={"close": "90"},
        raw_payload_sha256=_payload_hash("older bar ingested later"),
    )
    service = MarketObservationService()
    service.ingest_batch(market_connection, [newer], NOW)

    result = service.ingest_batch(
        market_connection,
        [older],
        NOW + timedelta(minutes=1),
    )
    selected = service.latest_compatible(
        market_connection,
        listing_id,
        "EOD",
        NOW + timedelta(minutes=1),
    )
    projected = market_connection.execute(
        "SELECT close, provider, observation_id FROM price_history"
    ).fetchone()

    assert result.accepted == 1
    assert result.projected_price_rows == 0
    assert selected is not None
    assert selected.provider == "newer"
    assert dict(projected) == {
        "close": 100.0,
        "provider": "newer",
        "observation_id": market_connection.execute(
            "SELECT id FROM market_observations WHERE provider = 'newer'"
        ).fetchone()[0],
    }


def test_partial_bar_projection_keeps_derived_ohlc_coherent(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    partial = _envelope(
        listing_id,
        raw_fields={"last": "100", "high": "90", "low": "80"},
        raw_payload_sha256=_payload_hash("partial coherent projection"),
    )

    result = MarketObservationService().ingest_batch(
        market_connection,
        [partial],
        NOW,
    )
    projected = market_connection.execute(
        "SELECT open, high, low, close FROM price_history"
    ).fetchone()

    assert result.accepted == 1
    assert dict(projected) == {
        "open": 100.0,
        "high": 100.0,
        "low": 80.0,
        "close": 100.0,
    }


def test_bar_requires_listing_attested_timezone(
    market_connection: sqlite3.Connection,
) -> None:
    listing = _listing(market_connection)
    market_connection.execute(
        "UPDATE instrument_listings SET timezone = NULL WHERE id = ?",
        (listing["id"],),
    )
    listing_without_timezone = _listing(market_connection)

    result = MarketObservationService().validate(
        listing_without_timezone,
        _envelope(int(listing["id"]), timezone="UTC"),
        NOW,
    )

    assert isinstance(result, ObservationRejection)
    assert result.reason_code == "INVALID_TIMEZONE"


def test_refresh_no_data_records_rejection_fallback_and_later_resolution(
    market_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_service_clock(monkeypatch, "backend.app.services.market_data_service")
    listing_id = int(_listing(market_connection)["id"])
    service = MarketDataService()
    service.observation_service.ingest_batch(
        market_connection,
        [_envelope(listing_id)],
        NOW,
    )
    market_connection.commit()

    class SequencedProvider:
        provider_name = "fixture_eod"
        responses: list[list[dict[str, object]]] = [
            [],
            [
                {
                    "date": "2026-08-16",
                    "open": 100,
                    "high": 106,
                    "low": 99,
                    "close": 105,
                    "adjusted_close": 105,
                    "volume": 20,
                }
            ],
        ]

        @staticmethod
        def api_key_configured() -> bool:
            return True

        @classmethod
        def get_daily_prices(cls, symbol: str, force: bool = False):
            assert symbol == "ACME"
            return cls.responses.pop(0), False

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        service,
        "get_provider_for_asset",
        lambda connection, asset_type: SequencedProvider(),
    )

    fallback = service.refresh_asset_prices(market_connection, "ACME")
    rejection = market_connection.execute(
        "SELECT id, reason_code FROM market_data_rejections"
    ).fetchone()
    selection = market_connection.execute(
        "SELECT selected_observation_id, fallback_reason FROM market_data_selection_events"
    ).fetchone()
    refreshed = service.refresh_asset_prices(market_connection, "ACME")

    assert fallback["used_fallback"] is True
    assert rejection["reason_code"] == "PROVIDER_NO_DATA"
    assert dict(selection) == {
        "selected_observation_id": market_connection.execute(
            "SELECT MIN(id) FROM market_observations"
        ).fetchone()[0],
        "fallback_reason": "LAST_GOOD",
    }
    assert refreshed["used_fallback"] is False
    assert market_connection.execute(
        """
        SELECT COUNT(*)
        FROM market_data_rejection_resolutions
        WHERE rejection_id = ?
        """,
        (rejection["id"],),
    ).fetchone()[0] == 1
    get_settings.cache_clear()


def test_refresh_provider_error_records_requested_provider_fallback(
    market_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.data_providers import ProviderError

    listing_id = int(_listing(market_connection)["id"])
    service = MarketDataService()
    last_good = _envelope(
        listing_id,
        provider="last_good",
        raw_payload_sha256=_payload_hash("last good before provider error"),
    )
    service.observation_service.ingest_batch(market_connection, [last_good], NOW)
    market_connection.commit()

    class FailingProvider:
        provider_name = "requested_primary"

        @staticmethod
        def api_key_configured() -> bool:
            return True

        @staticmethod
        def get_daily_prices(symbol: str, force: bool = False):
            raise ProviderError("fixture unavailable")

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        service,
        "get_provider_for_asset",
        lambda connection, asset_type: FailingProvider(),
    )

    result = service.refresh_asset_prices(market_connection, "ACME")
    event = market_connection.execute(
        """
        SELECT requested_provider, actual_provider, fallback_reason
        FROM market_data_selection_events
        """
    ).fetchone()

    assert result["used_fallback"] is True
    assert dict(event) == {
        "requested_provider": "requested_primary",
        "actual_provider": "last_good",
        "fallback_reason": "PROVIDER_FALLBACK",
    }
    get_settings.cache_clear()


def test_latest_revision_projects_even_when_injected_clock_moves_backward(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])
    service = MarketObservationService()
    original = _envelope(
        listing_id,
        raw_fields={"close": "100"},
        raw_payload_sha256=_payload_hash("clock original"),
    )
    correction = replace(
        original,
        raw_fields={"close": "110"},
        raw_payload_sha256=_payload_hash("clock correction"),
    )
    service.ingest_batch(market_connection, [original], NOW)

    result = service.ingest_batch(
        market_connection,
        [correction],
        NOW - timedelta(minutes=1),
    )
    projected = market_connection.execute(
        "SELECT close, observation_id FROM price_history"
    ).fetchone()
    latest_revision = market_connection.execute(
        """
        SELECT id
        FROM market_observations
        WHERE provider = 'fixture_eod'
        ORDER BY revision DESC
        LIMIT 1
        """
    ).fetchone()

    assert result.revisions == 1
    assert result.projected_price_rows == 1
    assert dict(projected) == {
        "close": 110.0,
        "observation_id": latest_revision["id"],
    }


def test_price_that_underflows_legacy_real_projection_is_rejected(
    market_connection: sqlite3.Connection,
) -> None:
    listing_id = int(_listing(market_connection)["id"])

    result = MarketObservationService().ingest_batch(
        market_connection,
        [
            _envelope(
                listing_id,
                raw_fields={"close": "1e-400"},
                raw_payload_sha256=_payload_hash("underflowing price"),
            )
        ],
        NOW,
    )

    assert result.accepted == 0
    assert result.rejected == 1
    assert market_connection.execute(
        "SELECT reason_code FROM market_data_rejections"
    ).fetchone()["reason_code"] == "NON_POSITIVE"
    assert market_connection.execute(
        "SELECT COUNT(*) FROM price_history"
    ).fetchone()[0] == 0
