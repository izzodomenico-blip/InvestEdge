from __future__ import annotations

import sqlite3

from backend.app.models import AssetCreate, AssetOut


def _asset_from_row(row: sqlite3.Row) -> AssetOut:
    return AssetOut(
        id=row["id"],
        symbol=row["symbol"],
        name=row["name"],
        asset_type=row["asset_type"],
        exchange=row["exchange"],
        currency=row["currency"],
    )


def list_assets(connection: sqlite3.Connection) -> list[AssetOut]:
    rows = connection.execute(
        """
        SELECT id, symbol, name, asset_type, exchange, currency
        FROM assets
        ORDER BY asset_type, symbol
        """
    ).fetchall()
    return [_asset_from_row(row) for row in rows]


def create_asset(connection: sqlite3.Connection, payload: AssetCreate) -> AssetOut:
    cursor = connection.execute(
        """
        INSERT INTO assets (symbol, name, asset_type, exchange, currency)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            payload.symbol.upper(),
            payload.name,
            payload.asset_type,
            payload.exchange,
            payload.currency.upper(),
        ),
    )
    row = connection.execute(
        """
        SELECT id, symbol, name, asset_type, exchange, currency
        FROM assets
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return _asset_from_row(row)
