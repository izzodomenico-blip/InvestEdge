from __future__ import annotations

import sqlite3

from backend.app.models import DashboardOut
from backend.app.services.portfolio_service import portfolio_value
from backend.app.services.signals_service import list_signals


def get_dashboard(connection: sqlite3.Connection) -> DashboardOut:
    assets_count = connection.execute("SELECT COUNT(*) AS count FROM assets").fetchone()["count"]
    positions_count = connection.execute(
        "SELECT COUNT(*) AS count FROM portfolio_positions"
    ).fetchone()["count"]
    signals_count = connection.execute("SELECT COUNT(*) AS count FROM signals").fetchone()["count"]

    return DashboardOut(
        assets_count=assets_count,
        positions_count=positions_count,
        portfolio_value=portfolio_value(connection),
        signals_count=signals_count,
        latest_signals=list_signals(connection, limit=5),
    )
