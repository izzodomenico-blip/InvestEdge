from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.config import get_settings
from backend.app.database import init_db
from backend.app.services import backup_service


def table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}


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
        assert connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
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
