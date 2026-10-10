from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.app.config import get_settings
from backend.app.database import init_db
from backend.app.services import backup_service


def table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}


def _initialize_database(database_path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        init_db()
    finally:
        get_settings.cache_clear()


def _insert_instrument(connection: sqlite3.Connection, name: str) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO instruments (
                canonical_name, instrument_type, asset_class, quality_tier, source
            )
            VALUES (?, 'STOCK', 'EQUITY', 'REFERENCE_ONLY', 'TEST')
            """,
            (name,),
        ).lastrowid
    )


def _insert_listing(
    connection: sqlite3.Connection,
    instrument_id: int,
    ticker: str,
    mic: str | None,
    currency: str = "USD",
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO instrument_listings (
                instrument_id, ticker, mic, currency, listing_status,
                trade_republic_status, source
            )
            VALUES (?, ?, ?, ?, 'ACTIVE', 'NEVER_SEEN', 'TEST')
            """,
            (instrument_id, ticker, mic, currency),
        ).lastrowid
    )


def test_instrument_master_schema_is_additive_for_new_database(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "instrument-master.db"
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "instruments",
            "instrument_identifiers",
            "instrument_identifier_attestations",
            "instrument_listings",
            "provider_symbols",
        } <= tables

        asset_columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(assets)")
        }
        assert asset_columns["instrument_listing_id"][3] == 0
        assert any(
            row[2] == "instrument_listings" and row[3] == "instrument_listing_id"
            for row in connection.execute("PRAGMA foreign_key_list(assets)")
        )

        indexes = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            )
        }
        assert {
            "uq_instrument_identifiers_global_primary",
            "uq_instrument_listings_market_identity",
            "uq_provider_symbols_verified_listing_capability",
            "uq_provider_symbols_verified_symbol_capability",
        } <= indexes.keys()
        assert "WHEREstatus='VERIFIED'" in indexes[
            "uq_provider_symbols_verified_listing_capability"
        ].replace(" ", "")
        assert "WHEREstatus='VERIFIED'" in indexes[
            "uq_provider_symbols_verified_symbol_capability"
        ].replace(" ", "")


def test_catalog_schema_is_additive_and_enforces_snapshot_failure_contract(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "catalog-schema.db"
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"catalog_snapshots", "catalog_entries"} <= tables

        snapshot_columns = table_columns(connection, "catalog_snapshots")
        assert {
            "source",
            "source_url",
            "content_sha256",
            "retrieved_at",
            "source_date",
            "row_count",
            "status",
            "parser_version",
            "failure_reason_code",
        } <= snapshot_columns
        entry_columns = table_columns(connection, "catalog_entries")
        assert {
            "snapshot_id",
            "row_number",
            "isin",
            "name",
            "parse_status",
            "reason_code",
            "raw_row_sha256",
            "instrument_id",
            "listing_id",
        } <= entry_columns

        connection.execute(
            """
            INSERT INTO catalog_snapshots (
                source, source_url, content_sha256, retrieved_at, source_date,
                row_count, status, parser_version, failure_reason_code
            )
            VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', NULL,
                    '2026-08-17T10:30:00Z', NULL, 0, 'FAILED', '1', 'DOWNLOAD_FAILED')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, row_count,
                    status, parser_version, failure_reason_code
                )
                VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', NULL,
                        '2026-08-17T10:31:00Z', 0, 'COMPLETE', '1', NULL)
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, row_count,
                    status, parser_version, failure_reason_code
                )
                VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', ?,
                        '2026-08-17T10:32:00Z', 0, 'COMPLETE', '1', 'PARSER_ERROR')
                """,
                ("a" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, row_count,
                    status, parser_version, failure_reason_code
                )
                VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', NULL,
                        '2026-08-17T10:33:00Z', 0, 'FAILED', '1', 'RAW_EXCEPTION_TEXT')
                """
            )

        indexes = {
            row["name"]: row["sql"]
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            )
        }
        unique_sql = indexes["uq_catalog_snapshots_complete_source_sha"].replace(" ", "")
        assert "ONcatalog_snapshots(source,content_sha256)" in unique_sql
        assert "WHEREstatus='COMPLETE'" in unique_sql


def test_instrument_master_legacy_backfill_is_idempotent_and_preserves_assets(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "legacy-instruments.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                exchange TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                isin TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, asset_type)
            );
            INSERT INTO assets (id, symbol, name, asset_type, exchange, currency, isin)
            VALUES
                (7, 'legacyeq', 'Legacy equity', 'stock', 'NASDAQ', 'usd', 'US0378331005'),
                (11, 'cryptold', 'Legacy crypto', 'crypto', 'CRYPTO', 'eur', 'US5949181045'),
                (12, 'fxlegacy', 'Legacy FX', 'fx', 'FX', 'eur', 'US67066G1040'),
                (13, 'badisin', 'Invalid identifier', 'stock', 'LSE', 'gbp', 'NOT-AN-ISIN');
            """
        )

    _initialize_database(database_path, monkeypatch)

    from backend.app.services.instrument_service import InstrumentService

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        before_counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("assets", "instruments", "instrument_listings", "instrument_identifiers")
        }
        assert [
            row["id"]
            for row in connection.execute("SELECT id FROM assets ORDER BY id")
        ] == [7, 11, 12, 13]
        assert before_counts == {
            "assets": 4,
            "instruments": 4,
            "instrument_listings": 4,
            "instrument_identifiers": 1,
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM assets WHERE instrument_listing_id IS NULL"
        ).fetchone()[0] == 0

        equity_listing = connection.execute(
            """
            SELECT l.ticker, l.mic, l.venue_name, l.currency, l.timezone,
                   i.instrument_type, i.asset_class, i.quality_tier
            FROM assets a
            JOIN instrument_listings l ON l.id = a.instrument_listing_id
            JOIN instruments i ON i.id = l.instrument_id
            WHERE a.id = 7
            """
        ).fetchone()
        assert dict(equity_listing) == {
            "ticker": "LEGACYEQ",
            "mic": None,
            "venue_name": None,
            "currency": "USD",
            "timezone": None,
            "instrument_type": "STOCK",
            "asset_class": "EQUITY",
            "quality_tier": "REFERENCE_ONLY",
        }
        assert connection.execute(
            "SELECT normalized_value FROM instrument_identifiers"
        ).fetchone()[0] == "US0378331005"
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM instrument_identifiers ii
            JOIN instruments i ON i.id = ii.instrument_id
            WHERE i.instrument_type IN ('CRYPTO', 'FX')
            """
        ).fetchone()[0] == 0

        assert InstrumentService.backfill_active_assets(connection) == 0
        after_counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in before_counts
        }
        assert after_counts == before_counts


def test_instrument_master_same_primary_identifier_reuses_instrument_and_attests_sources(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "identifier-attestations.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                exchange TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                isin TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, asset_type)
            );
            INSERT INTO assets (symbol, name, asset_type, currency, isin)
            VALUES
                ('SAMEA', 'Same identity A', 'stock', 'USD', 'US0378331005'),
                ('SAMEB', 'Same identity B', 'stock', 'EUR', 'US0378331005');
            """
        )

    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        instrument_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT l.instrument_id
                FROM assets a
                JOIN instrument_listings l ON l.id = a.instrument_listing_id
                """
            )
        }
        assert len(instrument_ids) == 1
        instrument_id = instrument_ids.pop()
        assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 2
        isin_identifier_id = connection.execute(
            "SELECT id FROM instrument_identifiers WHERE scheme = 'ISIN'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO instrument_identifier_attestations (
                identifier_id, source, observed_at, evidence_hash
            )
            VALUES (?, 'SECOND_SOURCE', '2026-08-16T12:00:00Z', ?)
            """,
            (isin_identifier_id, "a" * 64),
        )
        figi_identifier_id = connection.execute(
            """
            INSERT INTO instrument_identifiers (
                scheme, normalized_value, scope, instrument_id, listing_id
            )
            VALUES ('FIGI', 'BBG000B9XRY4', 'INSTRUMENT', ?, NULL)
            """,
            (instrument_id,),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO instrument_identifier_attestations (
                identifier_id, source, observed_at, evidence_hash
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (figi_identifier_id, "OPENFIGI", "2026-08-16T12:01:00Z", "b" * 64),
                (figi_identifier_id, "ISSUER", "2026-08-16T12:02:00Z", "c" * 64),
            ],
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'ISIN'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'FIGI'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(DISTINCT source) FROM instrument_identifier_attestations"
        ).fetchone()[0] >= 4


@pytest.mark.parametrize(
    ("scheme", "normalized_value"),
    [("ISIN", "US0378331005"), ("FIGI", "BBG000B9XRY4")],
)
def test_instrument_master_concurrent_primary_identifier_collision_is_blocked(
    tmp_path,
    monkeypatch,
    scheme: str,
    normalized_value: str,
) -> None:
    database_path = tmp_path / f"identifier-race-{scheme.lower()}.db"
    _initialize_database(database_path, monkeypatch)
    barrier = Barrier(2)

    def bind_identifier(name: str) -> bool:
        with sqlite3.connect(database_path, timeout=10) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            barrier.wait()
            try:
                connection.execute("BEGIN IMMEDIATE")
                instrument_id = _insert_instrument(connection, name)
                connection.execute(
                    """
                    INSERT INTO instrument_identifiers (
                        scheme, normalized_value, scope, instrument_id, listing_id
                    )
                        VALUES (?, ?, 'INSTRUMENT', ?, NULL)
                        """,
                        (scheme, normalized_value, instrument_id),
                )
                connection.commit()
                return True
            except sqlite3.IntegrityError:
                connection.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(bind_identifier, ["Race A", "Race B"]))

    assert sorted(results) == [False, True]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = ? AND normalized_value = ?",
            (scheme, normalized_value),
        ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("scheme", "canonical_value", "noncanonical_value"),
    [
        ("ISIN", "US0378331005", " us0378331005 "),
        ("FIGI", "BBG000B9XRY4", "BBG 000B9XRY4"),
    ],
)
def test_instrument_master_primary_identifier_rejects_noncanonical_collision(
    tmp_path,
    monkeypatch,
    scheme: str,
    canonical_value: str,
    noncanonical_value: str,
) -> None:
    database_path = tmp_path / f"identifier-normalization-{scheme.lower()}.db"
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        first_instrument = _insert_instrument(connection, "Canonical owner")
        second_instrument = _insert_instrument(connection, "Noncanonical owner")
        connection.execute(
            """
            INSERT INTO instrument_identifiers (
                scheme, normalized_value, scope, instrument_id, listing_id
            )
            VALUES (?, ?, 'INSTRUMENT', ?, NULL)
            """,
            (scheme, canonical_value, first_instrument),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO instrument_identifiers (
                    scheme, normalized_value, scope, instrument_id, listing_id
                )
                VALUES (?, ?, 'INSTRUMENT', ?, NULL)
                """,
                (scheme, noncanonical_value, second_instrument),
            )

        assert connection.execute(
            "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = ?",
            (scheme,),
        ).fetchone()[0] == 1


def test_instrument_master_does_not_promote_legacy_symbol_inferred_isin(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "legacy-inferred-isin.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                exchange TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                isin TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, asset_type)
            );
            INSERT INTO assets (symbol, name, asset_type, currency, isin)
            VALUES ('AAPL', 'Legacy Apple without identifier evidence', 'stock', 'USD', NULL);
            """
        )

    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT isin FROM assets WHERE symbol = 'AAPL'"
        ).fetchone()[0] == "US0378331005"
        assert connection.execute(
            "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'ISIN'"
        ).fetchone()[0] == 0


def test_instrument_listing_market_identity_includes_instrument_and_migrates_legacy_index(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "listing-identity.db"
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX uq_instrument_listings_market_identity")
        connection.execute(
            """
            CREATE UNIQUE INDEX uq_instrument_listings_market_identity
            ON instrument_listings(UPPER(ticker), UPPER(mic), UPPER(currency))
            WHERE mic IS NOT NULL
            """
        )
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        first = _insert_instrument(connection, "First listing")
        second = _insert_instrument(connection, "Second listing")
        third = _insert_instrument(connection, "Collision listing")
        _insert_listing(connection, first, "ABC", "XNAS", "USD")
        _insert_listing(connection, second, "abc", "XNYS", "usd")
        _insert_listing(connection, third, "aBc", "xnas", "Usd")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_listing(connection, third, "ABC", "XNAS", "USD")
        index_sql = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'index' AND name = 'uq_instrument_listings_market_identity'
            """
        ).fetchone()[0]
        assert "instrument_id" in index_sql


def test_instrument_listing_provider_symbol_lifecycle_requires_retirement_before_reuse(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "provider-symbol-lifecycle.db"
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        first_listing = _insert_listing(
            connection,
            _insert_instrument(connection, "First provider listing"),
            "AAA",
            "XNAS",
        )
        second_listing = _insert_listing(
            connection,
            _insert_instrument(connection, "Second provider listing"),
            "BBB",
            "XNYS",
        )
        first_symbol_id = connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash, version
            )
            VALUES (
                'stooq', ?, 'EOD', 'aaa.us', 'AAA.US', 'VERIFIED', 'TEST',
                '2026-08-16T12:00:00Z', '2026-08-16T12:00:00Z', ?, 1
            )
            """,
            (first_listing, "d" * 64),
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO provider_symbols (
                    provider, listing_id, capability, provider_symbol, normalized_symbol,
                    status, source, observed_at, verified_at, evidence_hash, version
                )
                VALUES ('stooq', ?, 'EOD', 'other.us', 'OTHER.US', 'VERIFIED', 'TEST',
                        '2026-08-16T12:01:00Z', '2026-08-16T12:01:00Z', ?, 2)
                """,
                (first_listing, "e" * 64),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO provider_symbols (
                    provider, listing_id, capability, provider_symbol, normalized_symbol,
                    status, source, observed_at, verified_at, evidence_hash, version
                )
                VALUES ('stooq', ?, 'EOD', 'AAA.US', 'AAA.US', 'VERIFIED', 'TEST',
                        '2026-08-16T12:02:00Z', '2026-08-16T12:02:00Z', ?, 1)
                """,
                (second_listing, "f" * 64),
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE provider_symbols SET status = 'CANDIDATE' WHERE id = ?",
                (first_symbol_id,),
            )

        connection.execute(
            "UPDATE provider_symbols SET status = 'RETIRED' WHERE id = ?",
            (first_symbol_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE provider_symbols SET status = 'CANDIDATE' WHERE id = ?",
                (first_symbol_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM provider_symbols WHERE id = ?",
                (first_symbol_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO provider_symbols (
                    provider, listing_id, capability, provider_symbol, normalized_symbol,
                    status, source, observed_at, evidence_hash, version,
                    supersedes_provider_symbol_id
                )
                VALUES ('other-provider', ?, 'EOD', 'AAA.US', 'AAA.US', 'CANDIDATE',
                        'TEST', '2026-08-16T12:02:30Z', ?, 1, ?)
                """,
                (second_listing, "0" * 64, first_symbol_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO provider_symbols (
                    provider, listing_id, capability, provider_symbol, normalized_symbol,
                    status, source, observed_at, evidence_hash, version,
                    supersedes_provider_symbol_id
                )
                VALUES ('stooq', ?, 'INTRADAY', 'AAA.US', 'AAA.US', 'CANDIDATE',
                        'TEST', '2026-08-16T12:02:31Z', ?, 1, ?)
                """,
                (second_listing, "3" * 64, first_symbol_id),
            )
        candidate_symbol_id = connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, evidence_hash, version
            )
            VALUES ('stooq', ?, 'EOD', 'OTHER.US', 'OTHER.US', 'CANDIDATE',
                    'TEST', '2026-08-16T12:02:32Z', ?, 2)
            """,
            (first_listing, "4" * 64),
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO provider_symbols (
                    provider, listing_id, capability, provider_symbol, normalized_symbol,
                    status, source, observed_at, evidence_hash, version,
                    supersedes_provider_symbol_id
                )
                VALUES ('stooq', ?, 'EOD', 'OTHER.US', 'OTHER.US', 'CANDIDATE',
                        'TEST', '2026-08-16T12:02:33Z', ?, 2, ?)
                """,
                (second_listing, "5" * 64, candidate_symbol_id),
            )
        replacement_id = connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash, version,
                supersedes_provider_symbol_id
            )
            VALUES ('stooq', ?, 'EOD', 'AAA.US', 'AAA.US', 'VERIFIED', 'TEST',
                    '2026-08-16T12:03:00Z', '2026-08-16T12:03:00Z', ?, 1, ?)
            """,
            (second_listing, "1" * 64, first_symbol_id),
        ).lastrowid
        assert replacement_id is not None


def test_provider_symbol_supersedes_trigger_migrates_to_allow_same_listing_versions(
    tmp_path,
    monkeypatch,
) -> None:
    # Task 14: una nuova versione VERIFIED dello stesso listing puo cambiare simbolo e
    # puntare alla versione ritirata; il vincolo resta su provider/capability.
    database_path = tmp_path / "provider-symbol-supersedes.db"
    _initialize_database(database_path, monkeypatch)
    with sqlite3.connect(database_path) as connection:
        for trigger_name, event in (
            ("trg_provider_symbols_supersedes_insert", "INSERT"),
            ("trg_provider_symbols_supersedes_update", "UPDATE"),
        ):
            connection.execute(f"DROP TRIGGER {trigger_name}")
            connection.execute(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE {event} ON provider_symbols
                WHEN NEW.supersedes_provider_symbol_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1
                    FROM provider_symbols previous
                    WHERE previous.id = NEW.supersedes_provider_symbol_id
                      AND previous.status = 'RETIRED'
                      AND UPPER(previous.provider) = UPPER(NEW.provider)
                      AND UPPER(previous.capability) = UPPER(NEW.capability)
                      AND UPPER(previous.normalized_symbol) = UPPER(NEW.normalized_symbol)
                )
                BEGIN
                    SELECT RAISE(ABORT, 'superseded provider symbol must be related and retired');
                END
                """
            )
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        listing_id = _insert_listing(
            connection,
            _insert_instrument(connection, "Versioned provider listing"),
            "VER",
            "XNAS",
        )
        other_listing_id = _insert_listing(
            connection,
            _insert_instrument(connection, "Unrelated provider listing"),
            "OTH",
            "XNYS",
        )
        first_id = connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash, version
            )
            VALUES ('stooq', ?, 'EOD', 'ver.us', 'VER.US', 'VERIFIED', 'TEST',
                    '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z', ?, 1)
            """,
            (listing_id, "a" * 64),
        ).lastrowid
        connection.execute(
            "UPDATE provider_symbols SET status = 'RETIRED' WHERE id = ?",
            (first_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO provider_symbols (
                    provider, listing_id, capability, provider_symbol, normalized_symbol,
                    status, source, observed_at, verified_at, evidence_hash, version,
                    supersedes_provider_symbol_id
                )
                VALUES ('stooq', ?, 'EOD', 'oth.us', 'OTH.US', 'VERIFIED', 'TEST',
                        '2026-09-02T00:00:00Z', '2026-09-02T00:00:00Z', ?, 1, ?)
                """,
                (other_listing_id, "b" * 64, first_id),
            )
        second_id = connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash, version,
                supersedes_provider_symbol_id
            )
            VALUES ('stooq', ?, 'EOD', 'ver2.us', 'VER2.US', 'VERIFIED', 'TEST',
                    '2026-09-03T00:00:00Z', '2026-09-03T00:00:00Z', ?, 2, ?)
            """,
            (listing_id, "c" * 64, first_id),
        ).lastrowid
        assert second_id is not None
        trigger_sql = [
            row[0]
            for row in connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'trigger' AND name LIKE 'trg_provider_symbols_supersedes_%'
                ORDER BY name
                """
            )
        ]
        assert len(trigger_sql) == 2
        assert all("previous.listing_id = NEW.listing_id" in sql for sql in trigger_sql)


def test_instrument_listing_provider_history_blocks_replace_semantics(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "provider-symbol-replace.db"
    _initialize_database(database_path, monkeypatch)

    with sqlite3.connect(database_path) as connection:
        first_listing = _insert_listing(
            connection,
            _insert_instrument(connection, "Replace-protected listing"),
            "SAFE",
            "XNAS",
        )
        second_listing = _insert_listing(
            connection,
            _insert_instrument(connection, "Candidate listing"),
            "NEXT",
            "XNYS",
        )
        verified_id = connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash, version
            )
            VALUES ('stooq', ?, 'EOD', 'SAFE.US', 'SAFE.US', 'VERIFIED', 'TEST',
                    '2026-08-16T12:00:00Z', '2026-08-16T12:00:00Z', ?, 1)
            """,
            (first_listing, "6" * 64),
        ).lastrowid

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT OR REPLACE INTO provider_symbols (
                    provider, listing_id, capability, provider_symbol, normalized_symbol,
                    status, source, observed_at, evidence_hash, version
                )
                VALUES ('stooq', ?, 'EOD', 'REPLACED.US', 'REPLACED.US', 'CANDIDATE',
                        'TEST', '2026-08-16T12:01:00Z', ?, 1)
                """,
                (first_listing, "7" * 64),
            )

        candidate_id = connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, evidence_hash, version
            )
            VALUES ('stooq', ?, 'EOD', 'NEXT.US', 'NEXT.US', 'CANDIDATE', 'TEST',
                    '2026-08-16T12:02:00Z', ?, 2)
            """,
            (second_listing, "8" * 64),
        ).lastrowid
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                UPDATE OR REPLACE provider_symbols
                SET listing_id = ?, version = 1
                WHERE id = ?
                """,
                (first_listing, candidate_id),
            )

        assert connection.execute(
            "SELECT status FROM provider_symbols WHERE id = ?",
            (verified_id,),
        ).fetchone()[0] == "VERIFIED"
        assert connection.execute(
            "SELECT status FROM provider_symbols WHERE id = ?",
            (candidate_id,),
        ).fetchone()[0] == "CANDIDATE"


def test_instrument_listing_concurrent_provider_symbol_verification_is_blocked(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "provider-symbol-race.db"
    _initialize_database(database_path, monkeypatch)
    with sqlite3.connect(database_path) as connection:
        listing_ids = [
            _insert_listing(
                connection,
                _insert_instrument(connection, f"Provider race {suffix}"),
                f"RACE{suffix}",
                mic,
            )
            for suffix, mic in (("A", "XNAS"), ("B", "XNYS"))
        ]
    barrier = Barrier(2)

    def verify_symbol(listing_id: int) -> bool:
        with sqlite3.connect(database_path, timeout=10) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            barrier.wait()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO provider_symbols (
                        provider, listing_id, capability, provider_symbol, normalized_symbol,
                        status, source, observed_at, verified_at, evidence_hash, version
                    )
                    VALUES ('stooq', ?, 'EOD', 'race.us', 'RACE.US', 'VERIFIED', 'TEST',
                            '2026-08-16T12:00:00Z', '2026-08-16T12:00:00Z', ?, 1)
                    """,
                    (listing_id, "2" * 64),
                )
                connection.commit()
                return True
            except sqlite3.IntegrityError:
                connection.rollback()
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(verify_symbol, listing_ids))

    assert sorted(results) == [False, True]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM provider_symbols WHERE status = 'VERIFIED'"
        ).fetchone()[0] == 1


def test_instrument_master_prepare_database_calls_backup_before_migration(
    monkeypatch,
) -> None:
    from backend.app import database

    events: list[str] = []
    monkeypatch.setattr(
        backup_service,
        "create_backup",
        lambda *, reason: events.append(f"backup:{reason}")
        or {"created": True, "reason": reason, "file": "backup.db"},
    )
    monkeypatch.setattr(database, "init_db", lambda: events.append("migration"))

    result = backup_service.prepare_database(reason="pre-migration", backup_existing=True)

    assert result["created"] is True
    assert events == ["backup:pre-migration", "migration"]


def test_instrument_master_unique_active_asset_contract(tmp_path, monkeypatch) -> None:
    from backend.app.services.instrument_service import (
        AmbiguousInstrumentError,
        InstrumentService,
    )

    database_path = tmp_path / "unique-active-asset.db"
    _initialize_database(database_path, monkeypatch)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        assert InstrumentService.require_unique_active_asset(connection, "MISSING") is None

        connection.execute(
            """
            INSERT INTO assets (symbol, name, asset_type, currency)
            VALUES ('UNIQUE', 'Unique stock', 'stock', 'USD')
            """
        )
        row = InstrumentService.require_unique_active_asset(connection, "unique")
        assert isinstance(row, sqlite3.Row)
        assert row["symbol"] == "UNIQUE"

        connection.execute(
            """
            INSERT INTO assets (symbol, name, asset_type, currency)
            VALUES ('UNIQUE', 'Unique ETF', 'etf', 'EUR')
            """
        )
        with pytest.raises(AmbiguousInstrumentError) as error:
            InstrumentService.require_unique_active_asset(connection, "unique")
        expected_listing_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT instrument_listing_id FROM assets WHERE symbol = 'UNIQUE' ORDER BY id"
            )
        )
        assert error.value.symbol == "UNIQUE"
        assert error.value.candidate_listing_ids == expected_listing_ids


def test_init_db_migrates_legacy_tables_before_creating_indexes(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                exchange TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, asset_type)
            );

            CREATE TABLE signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                signal TEXT NOT NULL,
                score REAL NOT NULL,
                rationale TEXT,
                source TEXT NOT NULL DEFAULT 'scoring_engine',
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE simulated_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fees REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'SIMULATED',
                executed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            );

            CREATE TABLE news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER,
                title TEXT NOT NULL,
                summary TEXT,
                url TEXT,
                source TEXT,
                published_at TEXT,
                sentiment_score REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE api_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL UNIQUE,
                provider TEXT NOT NULL,
                payload TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO assets (id, symbol, name, asset_type, currency)
            VALUES (1, 'LEGACY', 'Legacy sentinel', 'stock', 'EUR');
            INSERT INTO signals (asset_id, signal, score, rationale)
            VALUES (1, 'BUY', 75, 'legacy-signal');
            INSERT INTO signals (asset_id, signal, score, rationale, source)
            VALUES (1, 'HOLD', 60, 'manual-sentinel', 'manual');
            INSERT INTO simulated_orders (asset_id, side, quantity, price, notes)
            VALUES (1, 'BUY', 2, 10, 'legacy-order');
            INSERT INTO news_items (asset_id, title, url)
            VALUES (1, 'Legacy news', 'https://example.test/legacy');
            INSERT INTO api_cache (cache_key, provider, payload)
            VALUES ('legacy-cache', 'legacy-provider', '{}');
            """
        )

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        init_db()
    finally:
        get_settings.cache_clear()

    with sqlite3.connect(database_path) as connection:
        assert "created_at" in table_columns(connection, "signals")
        assert "order_date" in table_columns(connection, "simulated_orders")
        assert "updated_at" in table_columns(connection, "news_items")
        assert "symbol" in table_columns(connection, "api_cache")
        # Unclassified scoring cache is invalidated; independent user records below survive.
        assert connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
        assert connection.execute("SELECT score, rationale, source FROM signals").fetchall() == [
            (60, "manual-sentinel", "manual")
        ]
        assert connection.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM news_items").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 1


def test_backup_before_migration_creates_consistent_copy(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "investedge.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel (value) VALUES ('preserved')")

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        result = backup_service.backup_before_migration()
    finally:
        get_settings.cache_clear()

    assert result["created"] is True
    assert result["reason"] == "pre-migration"
    backup_path = database_path.parent / "backups" / result["file"]
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "preserved"


def test_backup_before_migration_allows_missing_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "missing.db"))
    get_settings.cache_clear()
    try:
        result = backup_service.backup_before_migration()
    finally:
        get_settings.cache_clear()

    assert result["created"] is False


def test_same_second_backups_preserve_distinct_contents_and_reasons(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "investedge.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel (value) VALUES ('first-state')")

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    monkeypatch.setattr(backup_service, "_stamp", lambda: "20260816-120000")
    get_settings.cache_clear()
    try:
        first = backup_service.create_backup(reason="pre-seed-reset")
        with sqlite3.connect(database_path) as connection:
            connection.execute("UPDATE sentinel SET value = 'second-state'")
        second = backup_service.create_backup(reason="manual")
    finally:
        get_settings.cache_clear()

    assert first["file"] != second["file"]
    assert "pre-seed-reset" in first["file"]
    assert "manual" in second["file"]
    backup_dir = database_path.parent / "backups"
    with sqlite3.connect(backup_dir / first["file"]) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "first-state"
    with sqlite3.connect(backup_dir / second["file"]) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "second-state"


def test_concurrent_backups_reserve_unique_targets_atomically(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "investedge.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel (value) VALUES ('preserved')")

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    monkeypatch.setattr(backup_service, "_stamp", lambda: "20260816-120000")
    get_settings.cache_clear()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(backup_service.create_backup, ["worker-one", "worker-two"]))
    finally:
        get_settings.cache_clear()

    names = {result["file"] for result in results}
    assert len(names) == 2
    backup_dir = database_path.parent / "backups"
    for name in names:
        with sqlite3.connect(backup_dir / name) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "preserved"


def test_failed_backup_removes_reserved_target(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "investedge.db"
    database_path.write_bytes(b"sqlite-source-sentinel")
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()

    def fail_connect(path):  # noqa: ANN001, ANN202
        raise sqlite3.OperationalError("simulated open failure")

    monkeypatch.setattr(backup_service.sqlite3, "connect", fail_connect)
    try:
        with pytest.raises(sqlite3.OperationalError, match="simulated open failure"):
            backup_service.create_backup(reason="failure-probe")
    finally:
        get_settings.cache_clear()

    backup_dir = database_path.parent / "backups"
    assert list(backup_dir.glob("investedge-*.db")) == []


def test_prune_backups_keeps_newest_filesystem_timestamp(tmp_path, monkeypatch) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    older = backup_dir / "investedge-99999999-manual-old.db"
    newer = backup_dir / "investedge-00000000-manual-new.db"
    older.write_bytes(b"older")
    newer.write_bytes(b"newer")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    monkeypatch.setattr(backup_service, "_backups_dir", lambda: backup_dir)

    removed = backup_service.prune_backups(keep=1)

    assert removed == 1
    assert newer.exists()
    assert not older.exists()


def test_seed_reset_backs_up_custom_legacy_database_before_migration(tmp_path, monkeypatch) -> None:
    from backend.scripts.seed_database import seed_database

    database_path = tmp_path / "custom" / "legacy.db"
    database_path.parent.mkdir()
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE legacy_sentinel (value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_sentinel (value) VALUES ('preserved-before-reset')")

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        seed_database(reset=True)
    finally:
        get_settings.cache_clear()

    backups = list((database_path.parent / "backups").glob("investedge-*-pre-seed-reset-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT value FROM legacy_sentinel").fetchone()[0] == "preserved-before-reset"


def _curated_coingecko_owners(
    database_path,  # noqa: ANN001
    symbol: str,
    coingecko_id: str,
) -> tuple[int, set[int], str | None]:
    with sqlite3.connect(database_path) as connection:
        asset_instrument, listing_timezone = connection.execute(
            """
            SELECT listing.instrument_id, listing.timezone
            FROM assets AS asset
            JOIN instrument_listings AS listing ON listing.id = asset.instrument_listing_id
            WHERE UPPER(asset.symbol) = ? AND asset.asset_type = 'crypto'
            """,
            (symbol,),
        ).fetchone()
        owners = {
            int(row[0])
            for row in connection.execute(
                """
                SELECT instrument_id FROM instrument_identifiers
                WHERE scheme = 'COINGECKO_ID' AND normalized_value = ?
                """,
                (coingecko_id,),
            )
        }
    return int(asset_instrument), owners, listing_timezone


def test_seed_reset_then_restart_reuses_curated_crypto_identity(tmp_path, monkeypatch) -> None:
    from backend.scripts.seed_database import seed_database

    database_path = tmp_path / "seed-reset.db"
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        seed_database(reset=False)
        init_db()
        seed_database(reset=True)
        # Riavvio dopo il reset documentato: la migrazione non deve fallire.
        init_db()
    finally:
        get_settings.cache_clear()

    # Le barre CoinGecko richiedono il fuso UTC sul listing collegato all'asset.
    for symbol, coingecko_id in (("BTC", "bitcoin"), ("SOL", "solana")):
        asset_instrument, owners, listing_timezone = _curated_coingecko_owners(database_path, symbol, coingecko_id)
        assert owners == {asset_instrument}
        assert listing_timezone == "UTC"


def test_purged_curated_crypto_can_be_added_again_and_restarted(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "purge-readd.db"
    _initialize_database(database_path, monkeypatch)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO assets (symbol, name, asset_type, currency) VALUES ('SOL', 'Solana', 'crypto', 'EUR')"
        )
    _initialize_database(database_path, monkeypatch)
    first_instrument, owners, _timezone = _curated_coingecko_owners(database_path, "SOL", "solana")
    assert owners == {first_instrument}

    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM assets WHERE symbol = 'SOL'")
        connection.execute(
            "INSERT INTO assets (symbol, name, asset_type, currency) VALUES ('SOL', 'Solana', 'crypto', 'EUR')"
        )
    _initialize_database(database_path, monkeypatch)

    asset_instrument, owners, listing_timezone = _curated_coingecko_owners(database_path, "SOL", "solana")
    assert asset_instrument == first_instrument
    assert owners == {first_instrument}
    assert listing_timezone == "UTC"


def test_features_daily_schema_unique_key_and_cascade_from_protected_delete(tmp_path, monkeypatch) -> None:
    from backend.app.services.assets_service import delete_asset

    database_path = tmp_path / "features.db"
    _initialize_database(database_path, monkeypatch)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        assert table_columns(connection, "features_daily") == {
            "id", "asset_id", "timeframe", "date", "segment_id", "pipeline_version", "score_version",
            "data_mode", "window_hash", "warmup_complete", "score", "trend_score", "momentum_score",
            "volatility_score", "volume_score", "support_resistance_score", "risk_penalty", "features_json",
            "computed_at",
        }
        index_columns = [row[2] for row in connection.execute("PRAGMA index_info(idx_features_daily_lookup)")]
        assert index_columns == ["asset_id", "data_mode", "timeframe", "pipeline_version", "date"]
        asset_id = connection.execute(
            "INSERT INTO assets (symbol, name, asset_type, currency) VALUES ('FS', 'FS', 'stock', 'USD')"
        ).lastrowid
        connection.execute(
            "INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (?, '2024-01-02', 10, 1)",
            (asset_id,),
        )
        insert = """
            INSERT INTO features_daily (
                asset_id, timeframe, date, segment_id, pipeline_version, score_version, data_mode,
                window_hash, warmup_complete, features_json, computed_at
            )
            VALUES (?, ?, '2024-01-02', 0, 'features-v1', 'score-v1', ?, ?, 0, '{}', '2024-01-03T00:00:00+00:00')
        """
        connection.execute(insert, (asset_id, "D", "REAL", "a" * 64))
        connection.execute(insert, (asset_id, "D", "DEMO", "a" * 64))
        for values in (
            (asset_id, "D", "REAL", "b" * 64),
            (asset_id, "X", "REAL", "a" * 64),
            (asset_id, "W", "MIXED", "a" * 64),
            (asset_id, "W", "REAL", "short"),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(insert, values)

        assert delete_asset(connection, asset_id, symbol="FS", purge=True) is True
        assert connection.execute("SELECT COUNT(*) FROM features_daily").fetchone()[0] == 0
    finally:
        connection.close()


def test_init_db_creates_traceable_fx_rates_and_lookup_index(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "fx.db"
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        init_db()
    finally:
        get_settings.cache_clear()

    with sqlite3.connect(database_path) as connection:
        assert table_columns(connection, "fx_rates") == {
            "id",
            "from_currency",
            "to_currency",
            "rate",
            "observed_at",
            "ingested_at",
            "provider",
            "quality",
        }
        index_columns = {
            row[2]
            for row in connection.execute("PRAGMA index_info(idx_fx_rates_pair_observed)")
        }
        assert index_columns == {"from_currency", "to_currency", "observed_at"}
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO fx_rates (
                    from_currency, to_currency, rate, observed_at, provider, quality
                )
                VALUES ('USD', 'EUR', 0, '2026-08-14', 'test', 'reference')
                """
            )
