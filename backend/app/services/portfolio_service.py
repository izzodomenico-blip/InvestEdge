from __future__ import annotations

import sqlite3

from backend.app.models import PortfolioPositionOut


def list_portfolio(connection: sqlite3.Connection) -> list[PortfolioPositionOut]:
    rows = connection.execute(
        """
        SELECT
            pp.id,
            pp.asset_id,
            a.symbol,
            a.name,
            a.asset_type,
            pp.quantity,
            pp.average_price,
            pp.currency,
            (pp.quantity * pp.average_price) AS market_value
        FROM portfolio_positions pp
        JOIN assets a ON a.id = pp.asset_id
        ORDER BY market_value DESC
        """
    ).fetchall()

    return [
        PortfolioPositionOut(
            id=row["id"],
            asset_id=row["asset_id"],
            symbol=row["symbol"],
            name=row["name"],
            asset_type=row["asset_type"],
            quantity=row["quantity"],
            average_price=row["average_price"],
            currency=row["currency"],
            market_value=row["market_value"],
        )
        for row in rows
    ]


def portfolio_value(connection: sqlite3.Connection) -> float:
    row = connection.execute(
        """
        SELECT COALESCE(SUM(quantity * average_price), 0) AS total
        FROM portfolio_positions
        """
    ).fetchone()
    return float(row["total"])
