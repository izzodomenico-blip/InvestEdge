from __future__ import annotations

import sqlite3

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
