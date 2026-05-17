from __future__ import annotations

import sqlite3

from backend.app.models import DashboardOut
from backend.app.services.assets_service import list_assets
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.signals_service import list_signals


portfolio_engine = PortfolioEngine()


def get_dashboard(connection: sqlite3.Connection) -> DashboardOut:
    assets_count = connection.execute("SELECT COUNT(*) AS count FROM assets").fetchone()["count"]
    positions_count = connection.execute(
        "SELECT COUNT(*) AS count FROM portfolio_positions WHERE quantity > 0"
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
    portfolio_summary = portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
    snapshots = portfolio_engine.list_snapshots(connection)[-20:]
    latest_backtest_row = connection.execute(
        """
        SELECT id, name, strategy_name, total_return_percent, max_drawdown,
            alpha_vs_benchmark, final_value, created_at
        FROM backtest_runs
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
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
        else "Database non inizializzato. Esegui il seed con backend\\.venv\\Scripts\\python.exe scripts\\seed_database.py --reset.",
        assets_count=assets_count,
        positions_count=positions_count,
        portfolio_value=portfolio_summary.total_value,
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
        cash=portfolio_summary.cash,
        total_pnl=portfolio_summary.total_pnl,
        total_pnl_percent=portfolio_summary.total_pnl_percent,
        risk_warnings_count=len(portfolio_summary.risk_warnings),
        top_position=portfolio_summary.positions[0] if portfolio_summary.positions else None,
        portfolio_snapshots=[
            {
                "snapshot_date": snapshot.snapshot_date,
                "total_value": snapshot.total_value,
                "cash": snapshot.cash,
                "total_pnl": snapshot.total_pnl,
                "total_pnl_percent": snapshot.total_pnl_percent,
            }
            for snapshot in snapshots
        ],
        latest_backtest=dict(latest_backtest_row) if latest_backtest_row else None,
    )
