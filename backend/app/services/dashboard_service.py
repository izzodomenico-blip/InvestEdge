from __future__ import annotations

import sqlite3

from backend.app.models import (
    DashboardOut, 
    NewsItemOut, 
    BackupStatusOut, 
    HardeningReportOut,
    StrategyPlanSummaryOut,
    AlertSummaryOut,
    SchedulerRunOut,
    OperationalReportOut,
    OptimizationRunSummaryOut,
    ScenarioRunSummaryOut,
    SystemHealthOut,
    ValidatedSignalOut
)
from backend.app.services.assets_service import list_assets
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.ml_engine import MLEngine
from backend.app.services.news_engine import NewsEngine
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.signals_service import list_signals
from backend.app.services.universe_service import UniverseService
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.system_health_service import SystemHealthService
from backend.app.services.operational_ranking_service import OperationalRankingService


from backend.app.services.strategy_control_service import StrategyControlService
from backend.app.services.alert_service import AlertService
from backend.app.services.scheduler_service import SchedulerService
from backend.app.services.report_service import ReportService
from backend.app.services.portfolio_optimizer_service import PortfolioOptimizerService
from backend.app.services.scenario_service import ScenarioService
from backend.app.services.backup_service import BackupService
from backend.app.services.hardening_service import HardeningService
from backend.app.services.user_settings_service import UserSettingsService
from backend.app.services.tax_service import TaxService


portfolio_engine = PortfolioEngine()
market_data_service = MarketDataService()
news_engine = NewsEngine()
ml_engine = MLEngine()
universe_service = UniverseService()
data_quality_service = DataQualityService()
system_health_service = SystemHealthService()
operational_ranking_service = OperationalRankingService()
strategy_control_service = StrategyControlService()
alert_service = AlertService()
scheduler_service = SchedulerService()
report_service = ReportService()
portfolio_optimizer_service = PortfolioOptimizerService()
scenario_service = ScenarioService()
backup_service = BackupService()
hardening_service = HardeningService()
settings_service = UserSettingsService()
tax_service = TaxService()


def get_dashboard(connection: sqlite3.Connection, portfolio_id: int | None = None) -> DashboardOut:
    from backend.app.services.multi_portfolio_service import MultiPortfolioService
    mps = MultiPortfolioService()
    
    if portfolio_id is None:
        portfolio_id = mps.get_active_portfolio(connection).id

    assets_count = connection.execute("SELECT COUNT(*) AS count FROM assets").fetchone()["count"]
    positions_count = connection.execute(
        "SELECT COUNT(*) AS count FROM portfolio_positions WHERE portfolio_id = ? AND quantity > 0",
        (portfolio_id,)
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
    portfolio_summary = portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)
    snapshots = portfolio_engine.list_snapshots(connection, portfolio_id=portfolio_id)[-20:]
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
        data_status=market_data_service.get_global_status(connection),
        universe_summary=universe_service.get_summary(connection),
        ml_status=ml_engine.get_status(connection),
        latest_ml_prediction=ml_engine.latest_prediction(connection),
        high_impact_news=_high_impact_news(connection),
        market_sentiment=_market_sentiment(connection),
        system_health=system_health_service.get_health(connection),
        top_buy_candidates=operational_ranking_service.get_operational_ranking(
            connection
        ).buy_candidates[:5],
        data_quality_warnings=[
            f"{q.symbol}: {q.grade} ({q.score:.0f}%)"
            for q in data_quality_service.list_all_quality(connection)
            if q.score < 70
        ],
        latest_strategy_plan=next(iter(strategy_control_service.list_strategy_plans(connection, portfolio_id=portfolio_id)), None),
        open_alerts_summary=alert_service.get_alert_summary(connection, portfolio_id=portfolio_id),
        latest_scheduler_run=next(iter(scheduler_service.list_runs(connection, limit=1)), None),
        latest_operational_report=report_service.get_latest_report(connection),
        latest_optimization_run=next(iter(portfolio_optimizer_service.list_runs(connection, portfolio_id=portfolio_id)), None),
        latest_scenario_run=next(iter(scenario_service.list_runs(connection, portfolio_id=portfolio_id)), None),
        active_risk_profile=settings_service.get_active_risk_profile(connection),
        active_strategy_profile=settings_service.get_active_strategy_profile(connection),
        backup_status=BackupStatusOut(
            backup_directory=str(backup_service.backup_dir),
            backups_count=len(backup_service.list_backups(connection)),
            latest_backup=next(iter(backup_service.list_backups(connection)), None),
            database_size_bytes=backup_service.db_path.stat().st_size if backup_service.db_path.exists() else 0,
            integrity_status="OK"
        ),
        hardening_report=hardening_service.run_checks(connection),
        tax_snapshot=tax_service.get_dashboard_tax_snapshot(connection, portfolio_id),
    )


def _high_impact_news(connection: sqlite3.Connection, limit: int = 5) -> list[NewsItemOut]:
    rows = connection.execute(
        """
        SELECT id, asset_id, symbol, provider, title, summary, url, source, published_at,
               sentiment_score, sentiment_label, impact_level, relevance_score, created_at
        FROM news_items
        WHERE impact_level = 'HIGH'
        ORDER BY COALESCE(published_at, created_at) DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        NewsItemOut(
            id=row["id"],
            asset_id=row["asset_id"],
            symbol=row["symbol"],
            provider=row["provider"],
            title=row["title"],
            summary=row["summary"],
            url=row["url"],
            source=row["source"],
            published_at=row["published_at"],
            sentiment_score=float(row["sentiment_score"] or 0.0),
            sentiment_label=row["sentiment_label"] or "NEUTRAL",
            impact_level=row["impact_level"] or "LOW",
            relevance_score=float(row["relevance_score"] or 0.0),
            created_at=row["created_at"],
        )
        for row in rows
    ]


def _market_sentiment(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN sentiment_label = 'POSITIVE' THEN 1 ELSE 0 END) AS positive,
            SUM(CASE WHEN sentiment_label = 'NEGATIVE' THEN 1 ELSE 0 END) AS negative,
            SUM(CASE WHEN sentiment_label = 'NEUTRAL' THEN 1 ELSE 0 END) AS neutral,
            AVG(sentiment_score) AS avg_score
        FROM news_items
        """
    ).fetchone()
    total = int(row["total"] or 0) if row else 0
    if total == 0:
        return {
            "news_count": 0,
            "average_sentiment_score": 0.0,
            "sentiment_label": "NEUTRAL",
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
        }
    average = float(row["avg_score"] or 0.0)
    if average > 0.1:
        label = "POSITIVE"
    elif average < -0.1:
        label = "NEGATIVE"
    else:
        label = "NEUTRAL"
    return {
        "news_count": total,
        "average_sentiment_score": round(average, 3),
        "sentiment_label": label,
        "positive_count": int(row["positive"] or 0),
        "negative_count": int(row["negative"] or 0),
        "neutral_count": int(row["neutral"] or 0),
    }
