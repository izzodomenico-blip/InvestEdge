from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.database import db_session
from backend.app.models import (
    AssetCreate,
    AssetOut,
    BacktestResultOut,
    BacktestRunIn,
    BacktestSummaryOut,
    DashboardOut,
    ApiUsageOut,
    AssetDataStatusOut,
    DataRefreshAllOut,
    DataRefreshResultOut,
    DataStatusOut,
    MLModelDetailOut,
    MLModelSummaryOut,
    MLPredictAllOut,
    MLPredictIn,
    MLPredictionOut,
    MLStatusOut,
    MLTrainIn,
    MLTrainOut,
    MLTrainingRunOut,
    NewsItemOut,
    NewsRefreshResultOut,
    NewsSentimentSummaryOut,
    NewsStatusOut,
    OrderSimulationOut,
    PortfolioInitIn,
    PortfolioRecommendationOut,
    PortfolioSnapshotOut,
    PortfolioSummaryOut,
    PriceHistoryOut,
    SeedSummaryOut,
    SignalOut,
    SimulatedOrderIn,
    SimulatedOrderOut,
    TechnicalAnalysisOut,
    UniverseAssetOut,
    UniverseImportIn,
    UniverseImportOut,
    UniversePromoteIn,
    UniverseSummaryOut,
    SystemHealthOut,
    DataQualityCheckOut,
    ValidatedSignalOut,
    OperationalRankingOut,
    PortfolioActionOut,
    StrategyPlanConfig,
    StrategyPlanFullOut,
    StrategyPlanItemOut,
    StrategyPlanOrderOut,
    StrategyPlanSummaryOut,
    AlertOut,
    AlertSummaryOut,
    AlertRuleOut,
    AlertRuleToggleIn,
    SchedulerRunIn,
    SchedulerRunOut,
    OperationalReportOut,
    OptimizationMethod,
    OptimizerConfig,
    OptimizationItemOut,
    RebalanceOrderOut,
    OptimizationRunSummaryOut,
    OptimizationRunFullOut,
    ScenarioType,
    ScenarioConfig,
    ScenarioRunSummaryOut,
    ScenarioRunFullOut,
)
from backend.app.services.assets_service import create_asset, get_asset_by_symbol, list_assets
from backend.app.services.backtest_engine import BacktestEngine
from backend.app.services.dashboard_service import get_dashboard
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.ml_engine import MLEngine
from backend.app.services.news_engine import NewsEngine
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.prices_service import get_price_history
from backend.app.services.signals_service import list_signals
from backend.app.services.signals_service import get_signal_by_symbol
from backend.app.services.technical_analysis_service import get_technical_analysis
from backend.app.services.universe_service import UniverseService
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.system_health_service import SystemHealthService
from backend.app.services.signal_validation_service import SignalValidationService
from backend.app.services.operational_ranking_service import OperationalRankingService
from backend.app.services.strategy_control_service import StrategyControlService
from backend.app.services.alert_service import AlertService
from backend.app.services.scheduler_service import SchedulerService
from backend.app.services.report_service import ReportService
from backend.app.services.portfolio_optimizer_service import PortfolioOptimizerService
from backend.app.services.scenario_service import ScenarioService
from backend.scripts.seed_database import seed_database

router = APIRouter()
portfolio_engine = PortfolioEngine()
backtest_engine = BacktestEngine()
market_data_service = MarketDataService()
news_engine = NewsEngine()
ml_engine = MLEngine()
universe_service = UniverseService()
data_quality_service = DataQualityService()
system_health_service = SystemHealthService()
signal_validation_service = SignalValidationService()
operational_ranking_service = OperationalRankingService()
strategy_control_service = StrategyControlService()
alert_service = AlertService()
scheduler_service = SchedulerService()
report_service = ReportService()
portfolio_optimizer_service = PortfolioOptimizerService()
scenario_service = ScenarioService()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "investedge-api"}


@router.get("/system/health", response_model=SystemHealthOut)
def get_system_health() -> SystemHealthOut:
    with db_session() as connection:
        return system_health_service.get_health(connection)


@router.get("/system/audit", response_model=SystemHealthOut)
def get_system_audit() -> SystemHealthOut:
    with db_session() as connection:
        return system_health_service.get_health(connection)


@router.get("/quality/data", response_model=list[DataQualityCheckOut])
def get_all_data_quality() -> list[DataQualityCheckOut]:
    with db_session() as connection:
        return data_quality_service.list_all_quality(connection)


@router.get("/quality/data/{symbol}", response_model=DataQualityCheckOut)
def get_asset_data_quality(symbol: str) -> DataQualityCheckOut:
    with db_session() as connection:
        return data_quality_service.check_asset_quality(connection, symbol)


@router.get("/signals/validated", response_model=list[ValidatedSignalOut])
def get_all_validated_signals() -> list[ValidatedSignalOut]:
    with db_session() as connection:
        return signal_validation_service.validate_all_signals(connection)


@router.get("/signals/validated/{symbol}", response_model=ValidatedSignalOut)
def get_asset_validated_signal(symbol: str) -> ValidatedSignalOut:
    with db_session() as connection:
        try:
            return signal_validation_service.validate_signal(connection, symbol)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/ranking/operational", response_model=OperationalRankingOut)
def get_operational_ranking() -> OperationalRankingOut:
    with db_session() as connection:
        return operational_ranking_service.get_operational_ranking(connection)


@router.get("/ranking/buy-candidates", response_model=list[ValidatedSignalOut])
def get_buy_candidates() -> list[ValidatedSignalOut]:
    with db_session() as connection:
        ranking = operational_ranking_service.get_operational_ranking(connection)
        return ranking.buy_candidates


@router.get("/ranking/watch-candidates", response_model=list[ValidatedSignalOut])
def get_watch_candidates() -> list[ValidatedSignalOut]:
    with db_session() as connection:
        ranking = operational_ranking_service.get_operational_ranking(connection)
        return ranking.watch_candidates


@router.get("/ranking/reduce-candidates", response_model=list[ValidatedSignalOut])
def get_reduce_candidates() -> list[ValidatedSignalOut]:
    with db_session() as connection:
        ranking = operational_ranking_service.get_operational_ranking(connection)
        return ranking.reduce_candidates


@router.get("/ranking/excluded", response_model=list[ValidatedSignalOut])
def get_excluded_candidates() -> list[ValidatedSignalOut]:
    with db_session() as connection:
        ranking = operational_ranking_service.get_operational_ranking(connection)
        return ranking.excluded_candidates


@router.get("/portfolio/actions", response_model=list[PortfolioActionOut])
def get_portfolio_actions() -> list[PortfolioActionOut]:
    with db_session() as connection:
        return operational_ranking_service.get_portfolio_actions(connection)


# -- ALERTS ------------------------------------------------------------------
@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    status: str | None = None,
    severity: str | None = None,
    symbol: str | None = None
) -> list[AlertOut]:
    with db_session() as connection:
        # Note: status/severity filtering could be added to get_open_alerts or new method
        # for now we'll just use get_open_alerts if status is OPEN
        if status == "OPEN" or not status:
            return alert_service.get_open_alerts(connection, severity=severity, symbol=symbol)
        # otherwise basic select
        query = "SELECT * FROM alerts WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY created_at DESC"
        rows = connection.execute(query, params).fetchall()
        return [alert_service._row_to_alert(row) for row in rows]


@router.get("/alerts/summary", response_model=AlertSummaryOut)
def get_alerts_summary() -> AlertSummaryOut:
    with db_session() as connection:
        return alert_service.get_alert_summary(connection)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int):
    with db_session() as connection:
        alert_service.acknowledge_alert(connection, alert_id)
        return {"success": True}


@router.post("/alerts/{alert_id}/close")
def close_alert(alert_id: int):
    with db_session() as connection:
        alert_service.close_alert(connection, alert_id)
        return {"success": True}


@router.get("/alerts/rules", response_model=list[AlertRuleOut])
def get_alert_rules() -> list[AlertRuleOut]:
    with db_session() as connection:
        return alert_service.list_rules(connection)


@router.post("/alerts/rules/{rule_id}/toggle")
def toggle_alert_rule(rule_id: int, payload: AlertRuleToggleIn):
    with db_session() as connection:
        alert_service.toggle_rule(connection, rule_id, payload.enabled)
        return {"success": True}


@router.post("/alerts/evaluate")
def evaluate_alerts():
    with db_session() as connection:
        alert_service.evaluate_rules(connection)
        return {"success": True}


# -- SCHEDULER ---------------------------------------------------------------
@router.get("/scheduler/runs", response_model=list[SchedulerRunOut])
def list_scheduler_runs() -> list[SchedulerRunOut]:
    with db_session() as connection:
        return scheduler_service.list_runs(connection)


@router.post("/scheduler/run", response_model=SchedulerRunOut)
def run_scheduler(payload: SchedulerRunIn) -> SchedulerRunOut:
    with db_session() as connection:
        return scheduler_service.run_manual_cycle(connection, payload)


# -- REPORTS -----------------------------------------------------------------
@router.get("/reports", response_model=list[OperationalReportOut])
def list_reports() -> list[OperationalReportOut]:
    with db_session() as connection:
        return report_service.list_reports(connection)


@router.get("/reports/latest", response_model=OperationalReportOut | None)
def get_latest_report() -> OperationalReportOut | None:
    with db_session() as connection:
        return report_service.get_latest_report(connection)


@router.get("/reports/{report_id}", response_model=OperationalReportOut)
def get_report(report_id: int) -> OperationalReportOut:
    with db_session() as connection:
        try:
            return report_service.get_report(connection, report_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/reports/generate", response_model=OperationalReportOut)
def generate_report(report_type: str = "MANUAL") -> OperationalReportOut:
    with db_session() as connection:
        return report_service.generate_operational_report(connection, report_type=report_type)


@router.post("/strategy/plans/generate", response_model=StrategyPlanFullOut)
def generate_strategy_plan(payload: StrategyPlanConfig) -> StrategyPlanFullOut:
    with db_session() as connection:
        return strategy_control_service.generate_strategy_plan(connection, payload)


@router.get("/strategy/plans", response_model=list[StrategyPlanSummaryOut])
def list_strategy_plans() -> list[StrategyPlanSummaryOut]:
    with db_session() as connection:
        return strategy_control_service.list_strategy_plans(connection)


@router.get("/strategy/plans/{plan_id}", response_model=StrategyPlanFullOut)
def get_strategy_plan(plan_id: int) -> StrategyPlanFullOut:
    with db_session() as connection:
        try:
            return strategy_control_service.get_strategy_plan(connection, plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/strategy/plans/{plan_id}/apply-paper")
def apply_strategy_plan(plan_id: int) -> dict[str, int]:
    with db_session() as connection:
        try:
            count = strategy_control_service.apply_plan_to_paper_trading(connection, plan_id)
            return {"orders_created": count}
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/strategy/plans/{plan_id}")
def delete_strategy_plan(plan_id: int) -> dict[str, bool]:
    with db_session() as connection:
        return {"success": strategy_control_service.delete_plan(connection, plan_id)}


@router.get("/strategy/default-config", response_model=StrategyPlanConfig)
def get_default_strategy_config() -> StrategyPlanConfig:
    return StrategyPlanConfig(
        plan_name=f"Plan {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        universe_level="CORE",
        strategy_mode="BALANCED",
    )


# -- OPTIMIZER ---------------------------------------------------------------
@router.get("/optimizer/default-config", response_model=OptimizerConfig)
def get_default_optimizer_config() -> OptimizerConfig:
    return OptimizerConfig(
        run_name=f"Optimization {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        universe_source="CORE",
        optimization_method=OptimizationMethod.EQUAL_WEIGHT,
        initial_capital_mode="CURRENT_PORTFOLIO",
    )


@router.post("/optimizer/run", response_model=OptimizationRunFullOut)
def run_optimization(payload: OptimizerConfig) -> OptimizationRunFullOut:
    with db_session() as connection:
        return portfolio_optimizer_service.generate_optimization_run(connection, payload)


@router.get("/optimizer/runs", response_model=list[OptimizationRunSummaryOut])
def list_optimization_runs() -> list[OptimizationRunSummaryOut]:
    with db_session() as connection:
        return portfolio_optimizer_service.list_runs(connection)


@router.get("/optimizer/runs/{run_id}", response_model=OptimizationRunFullOut)
def get_optimization_run(run_id: int) -> OptimizationRunFullOut:
    with db_session() as connection:
        try:
            return portfolio_optimizer_service.get_run(connection, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/optimizer/runs/{run_id}/create-paper-orders")
def create_optimizer_paper_orders(run_id: int) -> dict[str, int]:
    with db_session() as connection:
        try:
            count = portfolio_optimizer_service.apply_rebalance_orders(connection, run_id)
            return {"orders_created": count}
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/optimizer/runs/{run_id}")
def delete_optimization_run(run_id: int) -> dict[str, bool]:
    with db_session() as connection:
        return {"success": portfolio_optimizer_service.delete_run(connection, run_id)}


# -- SCENARIOS ---------------------------------------------------------------
@router.get("/scenarios/default-config", response_model=ScenarioConfig)
def get_default_scenario_config() -> ScenarioConfig:
    return ScenarioConfig(
        scenario_name=f"Stress Test {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        scenario_type=ScenarioType.MARKET_CRASH,
        portfolio_source="CURRENT_PORTFOLIO",
    )


@router.get("/scenarios/presets")
def get_scenario_presets() -> list[dict[str, str]]:
    return [
        {"id": t.value, "label": t.value.replace("_", " ").title()}
        for t in ScenarioType
    ]


@router.post("/scenarios/run", response_model=ScenarioRunFullOut)
def run_scenario_analysis(payload: ScenarioConfig) -> ScenarioRunFullOut:
    with db_session() as connection:
        return scenario_service.run_scenario_analysis(connection, payload)


@router.get("/scenarios/runs", response_model=list[ScenarioRunSummaryOut])
def list_scenario_runs() -> list[ScenarioRunSummaryOut]:
    with db_session() as connection:
        return scenario_service.list_runs(connection)


@router.get("/scenarios/runs/{scenario_id}", response_model=ScenarioRunFullOut)
def get_scenario_run(scenario_id: int) -> ScenarioRunFullOut:
    with db_session() as connection:
        try:
            return scenario_service.get_run(connection, scenario_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/scenarios/runs/{scenario_id}")
def delete_scenario_run(scenario_id: int) -> dict[str, bool]:
    with db_session() as connection:
        return {"success": scenario_service.delete_run(connection, scenario_id)}


@router.get("/assets", response_model=list[AssetOut])
def get_assets() -> list[AssetOut]:
    with db_session() as connection:
        return list_assets(connection)


@router.get("/assets/{symbol}", response_model=AssetOut)
def get_asset(symbol: str) -> AssetOut:
    with db_session() as connection:
        asset = get_asset_by_symbol(connection, symbol)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found. Se il database e vuoto, esegui backend\\.venv\\Scripts\\python.exe scripts\\seed_database.py --reset.",
        )
    return asset


@router.post("/assets", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def post_asset(payload: AssetCreate) -> AssetOut:
    try:
        with db_session() as connection:
            return create_asset(connection, payload)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Asset already exists or violates database constraints.",
        ) from exc


@router.get("/portfolio", response_model=PortfolioSummaryOut)
def get_portfolio() -> PortfolioSummaryOut:
    with db_session() as connection:
        return portfolio_engine.refresh_portfolio(connection, create_snapshot=False)


@router.post("/portfolio/init", response_model=PortfolioSummaryOut)
def init_portfolio(payload: PortfolioInitIn) -> PortfolioSummaryOut:
    with db_session() as connection:
        return portfolio_engine.initialize_portfolio(connection, payload)


@router.post("/orders/simulate", response_model=OrderSimulationOut)
def simulate_order(payload: SimulatedOrderIn) -> OrderSimulationOut:
    try:
        with db_session() as connection:
            return portfolio_engine.simulate_order(connection, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/orders", response_model=list[SimulatedOrderOut])
def get_orders() -> list[SimulatedOrderOut]:
    with db_session() as connection:
        return portfolio_engine.list_orders(connection)


@router.get("/portfolio/snapshots", response_model=list[PortfolioSnapshotOut])
def get_portfolio_snapshots() -> list[PortfolioSnapshotOut]:
    with db_session() as connection:
        return portfolio_engine.list_snapshots(connection)


@router.post("/portfolio/refresh", response_model=PortfolioSummaryOut)
def refresh_portfolio() -> PortfolioSummaryOut:
    with db_session() as connection:
        return portfolio_engine.refresh_portfolio(connection, create_snapshot=True)


@router.get("/portfolio/recommendations", response_model=list[PortfolioRecommendationOut])
def get_portfolio_recommendations() -> list[PortfolioRecommendationOut]:
    with db_session() as connection:
        return portfolio_engine.recommendations(connection)


@router.post("/backtests/run", response_model=BacktestResultOut)
def run_backtest(payload: BacktestRunIn) -> BacktestResultOut:
    try:
        with db_session() as connection:
            return backtest_engine.run_backtest(connection, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/backtests", response_model=list[BacktestSummaryOut])
def get_backtests() -> list[BacktestSummaryOut]:
    with db_session() as connection:
        return backtest_engine.list_backtests(connection)


@router.get("/backtests/{backtest_id}", response_model=BacktestResultOut)
def get_backtest(backtest_id: int) -> BacktestResultOut:
    try:
        with db_session() as connection:
            return backtest_engine.get_backtest(connection, backtest_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/backtests/{backtest_id}")
def delete_backtest(backtest_id: int) -> dict[str, int | bool]:
    with db_session() as connection:
        deleted = backtest_engine.delete_backtest(connection, backtest_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest non trovato.")
    return {"deleted": True, "backtest_id": backtest_id}


@router.get("/prices/{symbol}", response_model=PriceHistoryOut)
def get_prices(symbol: str, limit: int | None = Query(default=None, ge=1, le=1000)) -> PriceHistoryOut:
    with db_session() as connection:
        prices = get_price_history(connection, symbol, limit=limit)
    if prices is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prices not found. Se il database e vuoto, esegui backend\\.venv\\Scripts\\python.exe scripts\\seed_database.py --reset.",
        )
    if not prices.prices:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Price history empty for this asset. Esegui il seed del database.",
        )
    return prices


@router.get("/technical-analysis/{symbol}", response_model=TechnicalAnalysisOut)
def technical_analysis(symbol: str) -> TechnicalAnalysisOut:
    with db_session() as connection:
        analysis = get_technical_analysis(connection, symbol)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Technical analysis not found. Se il database e vuoto, esegui backend\\.venv\\Scripts\\python.exe scripts\\seed_database.py --reset.",
        )
    return analysis


@router.get("/signals", response_model=list[SignalOut])
def get_signals() -> list[SignalOut]:
    with db_session() as connection:
        return list_signals(connection)


@router.get("/signals/{symbol}", response_model=SignalOut)
def get_signal(symbol: str) -> SignalOut:
    with db_session() as connection:
        signal = get_signal_by_symbol(connection, symbol)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found. Se il database e vuoto, esegui backend\\.venv\\Scripts\\python.exe scripts\\seed_database.py --reset.",
        )
    return signal


@router.get("/dashboard", response_model=DashboardOut)
def dashboard() -> DashboardOut:
    with db_session() as connection:
        return get_dashboard(connection)


@router.get("/universe", response_model=list[UniverseAssetOut])
def get_universe(
    level: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> list[UniverseAssetOut]:
    try:
        with db_session() as connection:
            rows = universe_service.get_universe(
                connection,
                level=level,
                asset_type=asset_type,
                active_only=active_only,
                limit=limit,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [UniverseAssetOut(**row) for row in rows]


@router.get("/universe/summary", response_model=UniverseSummaryOut)
def get_universe_summary() -> UniverseSummaryOut:
    with db_session() as connection:
        return UniverseSummaryOut(**universe_service.get_summary(connection))


@router.post("/universe/import", response_model=UniverseImportOut)
def import_universe(payload: UniverseImportIn) -> UniverseImportOut:
    try:
        with db_session() as connection:
            result = universe_service.import_universe_from_csv(connection, payload.file_name, payload.universe_level)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UniverseImportOut(**result)


@router.post("/universe/{symbol}/watchlist", response_model=UniverseAssetOut)
def add_universe_watchlist(symbol: str) -> UniverseAssetOut:
    try:
        with db_session() as connection:
            return UniverseAssetOut(**universe_service.add_to_watchlist(connection, symbol))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/universe/{symbol}/watchlist", response_model=UniverseAssetOut)
def remove_universe_watchlist(symbol: str) -> UniverseAssetOut:
    try:
        with db_session() as connection:
            return UniverseAssetOut(**universe_service.remove_from_watchlist(connection, symbol))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/universe/{symbol}/promote", response_model=UniverseAssetOut)
def promote_universe(symbol: str, payload: UniversePromoteIn) -> UniverseAssetOut:
    try:
        with db_session() as connection:
            return UniverseAssetOut(**universe_service.promote(connection, symbol, payload.universe_level))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/universe/refresh-candidates", response_model=list[UniverseAssetOut])
def get_universe_refresh_candidates(limit: int = Query(default=10, ge=1, le=100)) -> list[UniverseAssetOut]:
    with db_session() as connection:
        return [UniverseAssetOut(**row) for row in universe_service.get_refresh_candidates(connection, limit=limit)]


@router.get("/data/status", response_model=DataStatusOut)
def data_status() -> DataStatusOut:
    with db_session() as connection:
        return DataStatusOut(**market_data_service.get_global_status(connection))


@router.get("/data/status/{symbol}", response_model=AssetDataStatusOut)
def asset_data_status(symbol: str) -> AssetDataStatusOut:
    try:
        with db_session() as connection:
            return AssetDataStatusOut(**market_data_service.get_data_status(connection, symbol))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/data/refresh/{symbol}", response_model=DataRefreshResultOut)
def refresh_asset_data(symbol: str, force: bool = Query(default=False)) -> DataRefreshResultOut:
    try:
        with db_session() as connection:
            return DataRefreshResultOut(**market_data_service.refresh_asset_prices(connection, symbol, force=force))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/data/refresh-all", response_model=DataRefreshAllOut)
def refresh_all_data(
    limit: int | None = Query(default=10, ge=1, le=50),
    force: bool = Query(default=False),
) -> DataRefreshAllOut:
    with db_session() as connection:
        return DataRefreshAllOut(**market_data_service.refresh_all_watchlist(connection, limit=limit, force=force))


@router.get("/data/usage", response_model=list[ApiUsageOut])
def data_usage() -> list[ApiUsageOut]:
    with db_session() as connection:
        return [ApiUsageOut(**row) for row in market_data_service.get_usage(connection)]


@router.post("/admin/seed", response_model=SeedSummaryOut)
def admin_seed(reset: bool = Query(default=False)) -> SeedSummaryOut:
    return SeedSummaryOut(**seed_database(reset=reset))


@router.get("/news", response_model=list[NewsItemOut])
def list_news(
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None, min_length=1, max_length=24),
) -> list[NewsItemOut]:
    with db_session() as connection:
        rows = news_engine.get_market_news(connection, limit=limit, symbol=symbol)
    return [NewsItemOut(**row) for row in rows]


@router.get("/news/status", response_model=NewsStatusOut)
def news_status() -> NewsStatusOut:
    with db_session() as connection:
        payload = news_engine.get_status(connection)
    return NewsStatusOut(**payload)


@router.get("/news/sentiment/{symbol}", response_model=NewsSentimentSummaryOut)
def news_sentiment(symbol: str, lookback_days: int = Query(default=7, ge=1, le=60)) -> NewsSentimentSummaryOut:
    with db_session() as connection:
        summary = news_engine.get_news_sentiment_summary(connection, symbol, lookback_days=lookback_days)
    return NewsSentimentSummaryOut(**summary)


@router.get("/news/{symbol}", response_model=list[NewsItemOut])
def news_for_symbol(symbol: str, limit: int = Query(default=50, ge=1, le=200)) -> list[NewsItemOut]:
    with db_session() as connection:
        rows = news_engine.get_news_for_symbol(connection, symbol, limit=limit)
    return [NewsItemOut(**row) for row in rows]


@router.post("/news/refresh/{symbol}", response_model=NewsRefreshResultOut)
def refresh_news(symbol: str, force: bool = Query(default=False)) -> NewsRefreshResultOut:
    try:
        with db_session() as connection:
            payload = news_engine.refresh_news_for_symbol(connection, symbol, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return NewsRefreshResultOut(**payload)


@router.get("/ml/status", response_model=MLStatusOut)
def ml_status() -> MLStatusOut:
    with db_session() as connection:
        return MLStatusOut(**ml_engine.get_status(connection))


@router.post("/ml/train", response_model=MLTrainOut)
def ml_train(payload: MLTrainIn) -> MLTrainOut:
    try:
        with db_session() as connection:
            return MLTrainOut(**ml_engine.train_model(connection, payload))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/ml/models", response_model=list[MLModelSummaryOut])
def ml_models() -> list[MLModelSummaryOut]:
    with db_session() as connection:
        return [MLModelSummaryOut(**item) for item in ml_engine.list_models(connection)]


@router.get("/ml/models/{model_id}", response_model=MLModelDetailOut)
def ml_model_detail(model_id: int) -> MLModelDetailOut:
    with db_session() as connection:
        model = ml_engine.get_model(connection, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modello ML non trovato.")
    return MLModelDetailOut(**model)


@router.post("/ml/predict/{symbol}", response_model=MLPredictionOut)
def ml_predict(symbol: str, payload: MLPredictIn | None = None) -> MLPredictionOut:
    try:
        with db_session() as connection:
            model_id = payload.model_id if payload else None
            return MLPredictionOut(**ml_engine.predict_for_symbol(connection, symbol, model_id=model_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/ml/predict-all", response_model=MLPredictAllOut)
def ml_predict_all(payload: MLPredictIn | None = None) -> MLPredictAllOut:
    try:
        with db_session() as connection:
            model_id = payload.model_id if payload else None
            return MLPredictAllOut(**ml_engine.predict_all_watchlist(connection, model_id=model_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/ml/predictions/{symbol}", response_model=list[MLPredictionOut])
def ml_predictions(symbol: str, limit: int = Query(default=10, ge=1, le=50)) -> list[MLPredictionOut]:
    with db_session() as connection:
        return [MLPredictionOut(**item) for item in ml_engine.latest_predictions(connection, symbol, limit=limit)]


@router.get("/ml/training-runs", response_model=list[MLTrainingRunOut])
def ml_training_runs() -> list[MLTrainingRunOut]:
    with db_session() as connection:
        return [MLTrainingRunOut(**item) for item in ml_engine.list_training_runs(connection)]
