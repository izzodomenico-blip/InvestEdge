from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.tax_service import compute_tax_report

portfolio_engine = PortfolioEngine()


def _to_csv(headers: list[str], rows: list[list[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def portfolio_csv(connection: sqlite3.Connection) -> str:
    summary = portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
    rows = [
        [
            position.symbol,
            position.asset_type,
            position.quantity,
            position.average_price,
            position.current_price,
            position.current_value,
            position.unrealized_pnl,
            position.unrealized_pnl_percent,
            position.weight_percent,
            position.currency,
        ]
        for position in summary.positions
    ]
    return _to_csv(
        [
            "symbol",
            "asset_type",
            "quantity",
            "average_price",
            "current_price",
            "current_value",
            "unrealized_pnl",
            "unrealized_pnl_percent",
            "weight_percent",
            "currency",
        ],
        rows,
    )


def orders_csv(connection: sqlite3.Connection) -> str:
    orders = portfolio_engine.list_orders(connection)
    rows = [
        [
            order.order_date,
            order.symbol,
            order.order_type,
            order.quantity,
            order.price,
            order.fees,
            order.gross_amount,
            order.net_amount,
            order.note or "",
            order.strategy_tag or "",
        ]
        for order in orders
    ]
    return _to_csv(
        [
            "date",
            "symbol",
            "type",
            "quantity",
            "price",
            "fees",
            "gross_amount",
            "net_amount",
            "note",
            "strategy",
        ],
        rows,
    )


def tax_csv(connection: sqlite3.Connection) -> str:
    report = compute_tax_report(connection)
    rows = [
        [
            event["sell_date"],
            event["symbol"],
            event["asset_type"] or "",
            event["category"],
            event["quantity"],
            event["proceeds"],
            event["cost_basis"],
            event["gain"],
            event["rate"],
            event["tax_year"],
            event["holding_days"],
        ]
        for event in report["events"]
    ]
    return _to_csv(
        [
            "sell_date",
            "symbol",
            "asset_type",
            "category",
            "quantity",
            "proceeds",
            "cost_basis",
            "gain",
            "rate_percent",
            "tax_year",
            "holding_days",
        ],
        rows,
    )


def report_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    summary = portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
    orders = portfolio_engine.list_orders(connection)
    tax = compute_tax_report(connection)
    return {
        "positions_count": len(summary.positions),
        "orders_count": len(orders),
        "realized_events_count": len(tax["events"]),
        "portfolio_value": round(summary.total_value, 2),
        "total_pnl": round(summary.total_pnl, 2),
        "estimated_tax_due": tax["total_tax_due"],
    }
