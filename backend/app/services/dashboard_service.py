from __future__ import annotations

import sqlite3

from backend.app.models import DashboardOut
from backend.app.services.assets_service import list_assets
from backend.app.services.portfolio_service import portfolio_value
from backend.app.services.signals_service import list_signals


def get_dashboard(connection: sqlite3.Connection) -> DashboardOut:
    assets_count = connection.execute("SELECT COUNT(*) AS count FROM assets").fetchone()["count"]
    positions_count = connection.execute(
        "SELECT COUNT(*) AS count FROM portfolio_positions"
    ).fetchone()["count"]
    signals_count = connection.execute("SELECT COUNT(*) AS count FROM signals").fetchone()["count"]
    price_points_count = connection.execute("SELECT COUNT(*) AS count FROM price_history").fetchone()["count"]
    average_score_row = connection.execute("SELECT AVG(score) AS average_score FROM signals").fetchone()

    asset_type_rows = connection.execute(
        """
        SELECT asset_type, COUNT(*) AS count
        FROM assets
        GROUP BY asset_type
        ORDER BY asset_type
        """
    ).fetchall()
    risk_rows = connection.execute(
        """
        SELECT risk_level, COUNT(*) AS count
        FROM assets
        GROUP BY risk_level
        ORDER BY risk_level
        """
    ).fetchall()
    signal_rows = connection.execute(
        """
        SELECT signal, COUNT(*) AS count
        FROM signals
        GROUP BY signal
        ORDER BY signal
        """
    ).fetchall()

    latest_signals = list_signals(connection, limit=5)
    assets = list_assets(connection)
    sorted_by_score = sorted(
        [asset for asset in assets if asset.score is not None],
        key=lambda asset: asset.score or 0,
        reverse=True,
    )

    initialized = assets_count > 0 and price_points_count > 0 and signals_count > 0

    return DashboardOut(
        initialized=initialized,
        message=None
        if initialized
        else "Database non inizializzato. Esegui il seed con python scripts/seed_database.py --reset.",
        assets_count=assets_count,
        positions_count=positions_count,
        portfolio_value=portfolio_value(connection),
        signals_count=signals_count,
        price_points_count=price_points_count,
        average_score=round(float(average_score_row["average_score"]), 2)
        if average_score_row["average_score"] is not None
        else None,
        asset_type_breakdown={row["asset_type"]: row["count"] for row in asset_type_rows},
        risk_breakdown={row["risk_level"]: row["count"] for row in risk_rows},
        signal_breakdown={row["signal"]: row["count"] for row in signal_rows},
        latest_signals=latest_signals,
        top_assets=sorted_by_score[:5],
        weakest_assets=list(reversed(sorted_by_score[-5:])),
        risky_assets=sorted(
            assets,
            key=lambda asset: (
                {"very_high": 3, "high": 2, "medium": 1, "low": 0}.get(asset.risk_level.lower(), 0),
                asset.score or 0,
            ),
            reverse=True,
        )[:5],
    )
