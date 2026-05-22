from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from backend.app.database import db_session
from backend.app.config import get_settings
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
    AppSnapshotOut,
    AppExportOut,
    AppImportOut,
    HardeningCheckOut,
    BackupStatusOut,
    HardeningReportOut,
    AppSettingOut,
    AppSettingUpdateIn,
    RiskProfileOut,
    RiskProfileCreateIn,
    StrategyProfileOut,
    StrategyProfileCreateIn,
    NotificationPreferenceOut,
    UIPerferencesOut,
    UIPerferencesUpdateIn,
    PortfolioCreateIn,
    PortfolioUpdateIn,
    PortfolioOut,
    PortfolioCloneIn,
    CashTransferIn,
    CashTransferOut,
    ConsolidatedSummaryOut,
    PortfolioPerformanceComparisonOut,
    TaxSettingsOut,
    TaxSettingsUpdateIn,
    TaxLotOut,
    TaxRealizedEventOut,
    TaxSummaryOut,
    TaxSummaryGlobalOut,
    TaxReportOut,
    TaxRecalculateIn,
    TaxReportGenerateIn,
    TaxExportIn,
    GoogleSheetsStatusOut,
    GoogleSheetsPreviewIn,
    GoogleSheetsPreviewOut,
    GoogleSheetsImportConfirmIn,
    ExternalImportOut,
    ExternalImportDetailOut,
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
from backend.app.services.backup_service import BackupService
from backend.app.services.google_sheets_service import GoogleSheetsService
from backend.app.services.google_tracker_import_service import GoogleTrackerImportService
from backend.app.services.multi_portfolio_service import MultiPortfolioService
from backend.app.services.export_service import ExportService
from backend.app.services.import_service import ImportService
from backend.app.services.hardening_service import HardeningService
from backend.app.services.user_settings_service import UserSettingsService
from backend.app.services.tax_service import TaxService
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
backup_service = BackupService()
export_service = ExportService()
import_service = ImportService()
hardening_service = HardeningService()
user_settings_service = UserSettingsService()
multi_portfolio_service = MultiPortfolioService()
google_sheets_service = GoogleSheetsService()
google_import_service = GoogleTrackerImportService()
tax_service = TaxService()


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


@router.get("/ranking", response_model=OperationalRankingOut)
def get_operational_ranking(portfolio_id: int | None = Query(default=None)) -> OperationalRankingOut:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return operational_ranking_service.get_operational_ranking(connection, portfolio_id=portfolio_id)



@router.get("/ranking/buy-candidates", response_model=list[ValidatedSignalOut])
def get_buy_candidates(portfolio_id: int | None = Query(default=None)) -> list[ValidatedSignalOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        ranking = operational_ranking_service.get_operational_ranking(connection, portfolio_id=portfolio_id)
        return ranking.buy_candidates


@router.get("/ranking/watch-candidates", response_model=list[ValidatedSignalOut])
def get_watch_candidates(portfolio_id: int | None = Query(default=None)) -> list[ValidatedSignalOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        ranking = operational_ranking_service.get_operational_ranking(connection, portfolio_id=portfolio_id)
        return ranking.watch_candidates


@router.get("/ranking/reduce-candidates", response_model=list[ValidatedSignalOut])
def get_reduce_candidates(portfolio_id: int | None = Query(default=None)) -> list[ValidatedSignalOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        ranking = operational_ranking_service.get_operational_ranking(connection, portfolio_id=portfolio_id)
        return ranking.reduce_candidates


@router.get("/ranking/excluded", response_model=list[ValidatedSignalOut])
def get_excluded_candidates(portfolio_id: int | None = Query(default=None)) -> list[ValidatedSignalOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        ranking = operational_ranking_service.get_operational_ranking(connection, portfolio_id=portfolio_id)
        return ranking.excluded_candidates


@router.get("/portfolio/actions", response_model=list[PortfolioActionOut])
def get_portfolio_actions(portfolio_id: int | None = Query(default=None)) -> list[PortfolioActionOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return operational_ranking_service.get_portfolio_actions(connection, portfolio_id=portfolio_id)


# -- ALERTS ------------------------------------------------------------------
@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    portfolio_id: int | None = Query(default=None),
    status: str | None = None,
    severity: str | None = None,
    symbol: str | None = None
) -> list[AlertOut]:
    with db_session() as connection:
        # Note: status/severity filtering could be added to get_open_alerts or new method
        # for now we'll just use get_open_alerts if status is OPEN
        if status == "OPEN" or not status:
            return alert_service.get_open_alerts(connection, portfolio_id=portfolio_id, severity=severity, symbol=symbol)
        # otherwise basic select
        query = "SELECT * FROM alerts WHERE 1=1"
        params = []
        if portfolio_id is not None:
            query += " AND portfolio_id = ?"
            params.append(portfolio_id)
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
def get_alerts_summary(portfolio_id: int | None = Query(default=None)) -> AlertSummaryOut:
    with db_session() as connection:
        return alert_service.get_alert_summary(connection, portfolio_id=portfolio_id)


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
def list_reports(portfolio_id: int | None = Query(default=None)) -> list[OperationalReportOut]:
    with db_session() as connection:
        return report_service.list_reports(connection, portfolio_id=portfolio_id)


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
def generate_report(report_type: str = "MANUAL", portfolio_id: int | None = Query(default=None)) -> OperationalReportOut:
    with db_session() as connection:
        return report_service.generate_operational_report(connection, report_type=report_type, portfolio_id=portfolio_id)


@router.post("/strategy/plans/generate", response_model=StrategyPlanFullOut)
def generate_strategy_plan(payload: StrategyPlanConfig, portfolio_id: int | None = Query(default=None)) -> StrategyPlanFullOut:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return strategy_control_service.generate_strategy_plan(connection, payload, portfolio_id=portfolio_id)


@router.get("/strategy/plans", response_model=list[StrategyPlanSummaryOut])
def list_strategy_plans(portfolio_id: int | None = Query(default=None)) -> list[StrategyPlanSummaryOut]:
    with db_session() as connection:
        return strategy_control_service.list_strategy_plans(connection, portfolio_id=portfolio_id)


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
def run_optimizer(payload: OptimizerConfig, portfolio_id: int | None = Query(default=None)) -> OptimizationRunFullOut:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return portfolio_optimizer_service.generate_optimization_run(connection, payload, portfolio_id=portfolio_id)



@router.get("/optimizer/runs", response_model=list[OptimizationRunSummaryOut])
def list_optimization_runs(portfolio_id: int | None = Query(default=None)) -> list[OptimizationRunSummaryOut]:
    with db_session() as connection:
        return portfolio_optimizer_service.list_runs(connection, portfolio_id=portfolio_id)


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
def run_scenario_analysis(payload: ScenarioConfig, portfolio_id: int | None = Query(default=None)) -> ScenarioRunFullOut:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return scenario_service.run_scenario_analysis(connection, payload, portfolio_id=portfolio_id)


@router.get("/scenarios/runs", response_model=list[ScenarioRunSummaryOut])
def list_scenario_runs(portfolio_id: int | None = Query(default=None)) -> list[ScenarioRunSummaryOut]:
    with db_session() as connection:
        return scenario_service.list_runs(connection, portfolio_id=portfolio_id)


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


# -- GOOGLE SHEETS -----------------------------------------------------------
@router.get("/google-sheets/status", response_model=GoogleSheetsStatusOut)
def get_google_sheets_status() -> GoogleSheetsStatusOut:
    return GoogleSheetsStatusOut(**google_sheets_service.get_status())


@router.post("/google-sheets/authorize")
def authorize_google_sheets():
    try:
        msg = google_sheets_service.authorize_desktop()
        return {"success": True, "message": msg}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/google-sheets/test-connection")
def test_google_sheets_connection():
    try:
        # Just try to read first row of Portfolio
        settings = get_settings()
        google_sheets_service.read_range(f"{settings.google_sheets_portfolio_range.split('!')[0]}!A1:B1")
        return {"success": True, "message": "Connection OK"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/google-sheets/preview", response_model=GoogleSheetsPreviewOut)
def preview_google_sheets_import(payload: GoogleSheetsPreviewIn) -> GoogleSheetsPreviewOut:
    with db_session() as connection:
        try:
            import_id = google_import_service.preview_import(connection, payload.import_type)
            imp_detail = google_import_service.get_import(connection, import_id)
            
            # Extract preview rows based on type
            preview_rows = []
            if payload.import_type == "PORTFOLIO":
                preview_rows = imp_detail["positions"][:10]
            elif payload.import_type == "TRANSACTIONS":
                preview_rows = imp_detail["transactions"][:10]
            elif payload.import_type == "CASH":
                preview_rows = imp_detail["cash"][:10]
            elif payload.import_type == "WATCHLIST":
                preview_rows = imp_detail["watchlist"][:10]
                
            return GoogleSheetsPreviewOut(
                import_id=import_id,
                rows_total=imp_detail["rows_total"],
                rows_valid=imp_detail["rows_valid"],
                rows_invalid=imp_detail["rows_invalid"],
                warnings=imp_detail["warnings"],
                errors=imp_detail["errors"],
                preview_rows=preview_rows
            )
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/google-sheets/import/{import_id}/confirm")
def confirm_google_sheets_import(import_id: int, payload: GoogleSheetsImportConfirmIn):
    if not payload.confirm:
        return {"success": False, "message": "Import cancelled"}
    
    with db_session() as connection:
        try:
            return google_import_service.confirm_import(connection, import_id, payload.mode)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/google-sheets/imports", response_model=list[ExternalImportOut])
def list_google_sheets_imports() -> list[ExternalImportOut]:
    with db_session() as connection:
        return [ExternalImportOut(**item) for item in google_import_service.list_imports(connection)]


@router.get("/google-sheets/imports/{import_id}", response_model=ExternalImportDetailOut)
def get_google_sheets_import_detail(import_id: int) -> ExternalImportDetailOut:
    with db_session() as connection:
        try:
            return ExternalImportDetailOut(**google_import_service.get_import(connection, import_id))
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/google-sheets/templates")
def get_google_sheets_templates():
    from backend.app.services.google_tracker_import_service import EXPECTED_HEADERS
    return EXPECTED_HEADERS


# -- PORTFOLIOS --------------------------------------------------------------
@router.get("/portfolios", response_model=list[PortfolioOut])
def list_portfolios(include_archived: bool = Query(default=False)) -> list[PortfolioOut]:
    with db_session() as connection:
        return multi_portfolio_service.list_portfolios(connection, include_archived=include_archived)


@router.post("/portfolios", response_model=PortfolioOut)
def create_portfolio(payload: PortfolioCreateIn) -> PortfolioOut:
    with db_session() as connection:
        return multi_portfolio_service.create_portfolio(connection, payload)


@router.get("/portfolios/active", response_model=PortfolioOut)
def get_active_portfolio() -> PortfolioOut:
    with db_session() as connection:
        return multi_portfolio_service.get_active_portfolio(connection)


@router.post("/portfolios/{portfolio_id}/activate")
def activate_portfolio(portfolio_id: int):
    with db_session() as connection:
        if not multi_portfolio_service.set_active_portfolio(connection, portfolio_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found or archived")
        return {"success": True}


@router.get("/portfolios/consolidated-summary", response_model=ConsolidatedSummaryOut)
def get_consolidated_summary() -> ConsolidatedSummaryOut:
    with db_session() as connection:
        return multi_portfolio_service.get_consolidated_summary(connection)


@router.get("/portfolios/performance-comparison", response_model=PortfolioPerformanceComparisonOut)
def get_performance_comparison() -> PortfolioPerformanceComparisonOut:
    with db_session() as connection:
        return multi_portfolio_service.get_portfolio_performance_comparison(connection)


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioOut)
def get_portfolio_detail(portfolio_id: int) -> PortfolioOut:
    with db_session() as connection:
        p = multi_portfolio_service.get_portfolio(connection, portfolio_id)
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
        return p


@router.put("/portfolios/{portfolio_id}", response_model=PortfolioOut)
def update_portfolio(portfolio_id: int, payload: PortfolioUpdateIn) -> PortfolioOut:
    with db_session() as connection:
        p = multi_portfolio_service.update_portfolio(connection, portfolio_id, payload)
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
        return p


@router.delete("/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: int):
    with db_session() as connection:
        multi_portfolio_service.delete_portfolio(connection, portfolio_id)
        return {"success": True}


@router.post("/portfolios/{portfolio_id}/clone", response_model=PortfolioOut)
def clone_portfolio(portfolio_id: int, payload: PortfolioCloneIn) -> PortfolioOut:
    with db_session() as connection:
        p = multi_portfolio_service.clone_portfolio(connection, portfolio_id, payload)
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
        return p


@router.post("/portfolios/transfer-cash", response_model=CashTransferOut)
def transfer_cash(payload: CashTransferIn) -> CashTransferOut:
    with db_session() as connection:
        try:
            return multi_portfolio_service.transfer_cash(connection, payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# -- BACKUP & SNAPSHOTS ------------------------------------------------------
@router.get("/backup/status", response_model=BackupStatusOut)
def get_backup_status() -> BackupStatusOut:
    with db_session() as connection:
        backups = backup_service.list_backups(connection)
        db_size = backup_service.db_path.stat().st_size if backup_service.db_path.exists() else 0
        return BackupStatusOut(
            backup_directory=str(backup_service.backup_dir),
            backups_count=len(backups),
            latest_backup=backups[0] if backups else None,
            database_size_bytes=db_size,
            integrity_status="OK"
        )


@router.post("/backup/create", response_model=AppSnapshotOut)
def create_backup(snapshot_name: str | None = None, note: str | None = None) -> AppSnapshotOut:
    with db_session() as connection:
        return backup_service.create_database_backup(connection, snapshot_name=snapshot_name, note=note)


@router.get("/backup/list", response_model=list[AppSnapshotOut])
def list_backups() -> list[AppSnapshotOut]:
    with db_session() as connection:
        return backup_service.list_backups(connection)


@router.get("/backup/{backup_id}", response_model=AppSnapshotOut)
def get_backup_detail(backup_id: int) -> AppSnapshotOut:
    with db_session() as connection:
        try:
            return backup_service.get_backup(connection, backup_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/backup/{backup_id}/restore")
def restore_backup(backup_id: int, confirm: bool = False):
    with db_session() as connection:
        try:
            backup_service.restore_backup(connection, backup_id, confirm=confirm)
            return {"success": True, "message": "Ripristino completato. L'app potrebbe richiedere un riavvio."}
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/backup/{backup_id}")
def delete_backup(backup_id: int) -> dict[str, bool]:
    with db_session() as connection:
        return {"success": backup_service.delete_backup(connection, backup_id)}


@router.get("/snapshots", response_model=list[AppSnapshotOut])
def list_app_snapshots() -> list[AppSnapshotOut]:
    with db_session() as connection:
        return backup_service.list_backups(connection)


# -- EXPORT & IMPORT ---------------------------------------------------------
@router.get("/export/types")
def get_export_types() -> list[str]:
    return [
        "ASSETS", "PRICES", "PORTFOLIO", "ORDERS", "BACKTESTS", 
        "STRATEGY_PLANS", "OPTIMIZATIONS", "SCENARIOS", "ALERTS", 
        "REPORTS", "JOURNAL", "UNIVERSE", "TAX_REPORTS", "TAX_LOTS", "TAX_EVENTS"
    ]


@router.post("/export/create", response_model=AppExportOut)
def create_export(export_type: str, file_format: str = "JSON") -> AppExportOut:
    with db_session() as connection:
        try:
            return export_service.export_dataset(connection, export_type, file_format)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/export/list", response_model=list[AppExportOut])
def list_exports() -> list[AppExportOut]:
    with db_session() as connection:
        return export_service.list_exports(connection)


@router.get("/import/types")
def get_import_types() -> list[str]:
    return ["UNIVERSE", "WATCHLIST", "PORTFOLIO", "JOURNAL", "CUSTOM_ASSETS"]


@router.post("/import/validate")
def validate_import(file_name: str, import_type: str):
    try:
        return import_service.validate_import_file(file_name, import_type)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/import/run", response_model=AppImportOut)
def run_import(file_name: str, import_type: str, confirm: bool = False) -> AppImportOut:
    with db_session() as connection:
        try:
            return import_service.run_import(connection, file_name, import_type, confirm=confirm)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# -- HARDENING ---------------------------------------------------------------
@router.get("/hardening/report", response_model=HardeningReportOut)
def get_hardening_report() -> HardeningReportOut:
    with db_session() as connection:
        return hardening_service.run_checks(connection)


@router.post("/hardening/run", response_model=HardeningReportOut)
def run_hardening_checks() -> HardeningReportOut:
    with db_session() as connection:
        return hardening_service.run_checks(connection)


# -- SETTINGS & PROFILES -----------------------------------------------------
@router.get("/settings", response_model=list[AppSettingOut])
def get_app_settings() -> list[AppSettingOut]:
    with db_session() as connection:
        return user_settings_service.get_app_settings(connection)


@router.put("/settings/{key}")
def update_app_setting(key: str, payload: AppSettingUpdateIn):
    with db_session() as connection:
        user_settings_service.update_app_setting(connection, key, payload.setting_value_json, payload.description)
        return {"success": True}


@router.get("/settings/risk-profiles", response_model=list[RiskProfileOut])
def list_risk_profiles() -> list[RiskProfileOut]:
    with db_session() as connection:
        return user_settings_service.list_risk_profiles(connection)


@router.get("/settings/risk-profiles/active", response_model=RiskProfileOut)
def get_active_risk_profile() -> RiskProfileOut:
    with db_session() as connection:
        return user_settings_service.get_active_risk_profile(connection)


@router.post("/settings/risk-profiles", response_model=RiskProfileOut)
def create_risk_profile(payload: RiskProfileCreateIn) -> RiskProfileOut:
    with db_session() as connection:
        return user_settings_service.create_risk_profile(connection, payload)


@router.put("/settings/risk-profiles/{profile_id}", response_model=RiskProfileOut)
def update_risk_profile(profile_id: int, payload: RiskProfileCreateIn) -> RiskProfileOut:
    with db_session() as connection:
        return user_settings_service.update_risk_profile(connection, profile_id, payload)


@router.post("/settings/risk-profiles/{profile_id}/activate")
def activate_risk_profile(profile_id: int):
    with db_session() as connection:
        user_settings_service.activate_risk_profile(connection, profile_id)
        return {"success": True}


@router.delete("/settings/risk-profiles/{profile_id}")
def delete_risk_profile(profile_id: int):
    with db_session() as connection:
        try:
            user_settings_service.delete_risk_profile(connection, profile_id)
            return {"success": True}
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/settings/strategy-profiles", response_model=list[StrategyProfileOut])
def list_strategy_profiles() -> list[StrategyProfileOut]:
    with db_session() as connection:
        return user_settings_service.list_strategy_profiles(connection)


@router.get("/settings/strategy-profiles/active", response_model=StrategyProfileOut)
def get_active_strategy_profile() -> StrategyProfileOut:
    with db_session() as connection:
        return user_settings_service.get_active_strategy_profile(connection)


@router.post("/settings/strategy-profiles/{profile_id}/activate")
def activate_strategy_profile(profile_id: int):
    with db_session() as connection:
        user_settings_service.activate_strategy_profile(connection, profile_id)
        return {"success": True}


@router.get("/settings/ui", response_model=UIPerferencesOut)
def get_ui_preferences() -> UIPerferencesOut:
    with db_session() as connection:
        return user_settings_service.get_ui_preferences(connection)


# -- TAX & FISCAL SIMULATOR ----------------------------------------------------
@router.get("/tax/settings", response_model=TaxSettingsOut)
def get_tax_settings() -> TaxSettingsOut:
    with db_session() as connection:
        return tax_service.get_tax_settings(connection)


@router.put("/tax/settings", response_model=TaxSettingsOut)
def update_tax_settings(payload: TaxSettingsUpdateIn) -> TaxSettingsOut:
    with db_session() as connection:
        return tax_service.update_tax_settings(connection, payload)


@router.get("/tax/summary", response_model=TaxSummaryOut)
def get_tax_summary(
    portfolio_id: int | None = Query(default=None),
    tax_year: int | None = Query(default=None),
) -> TaxSummaryOut:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return tax_service.calculate_tax_summary(connection, portfolio_id=portfolio_id, tax_year=tax_year)


@router.get("/tax/summary/global", response_model=TaxSummaryGlobalOut)
def get_tax_summary_global(tax_year: int | None = Query(default=None)) -> TaxSummaryGlobalOut:
    with db_session() as connection:
        return tax_service.calculate_multi_portfolio_tax_summary(connection, tax_year=tax_year)


@router.get("/tax/lots", response_model=list[TaxLotOut])
def get_tax_lots(
    portfolio_id: int | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> list[TaxLotOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return tax_service.calculate_tax_lots(connection, portfolio_id=portfolio_id, symbol=symbol)


@router.get("/tax/realized-events", response_model=list[TaxRealizedEventOut])
def get_tax_realized_events(
    portfolio_id: int | None = Query(default=None),
    tax_year: int | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> list[TaxRealizedEventOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return tax_service.calculate_realized_events(
            connection, portfolio_id=portfolio_id, tax_year=tax_year, symbol=symbol
        )


@router.post("/tax/recalculate")
def recalculate_tax(payload: TaxRecalculateIn) -> dict[str, Any]:
    with db_session() as connection:
        try:
            return tax_service.recalculate(
                connection,
                portfolio_id=payload.portfolio_id,
                tax_year=payload.tax_year,
                method=payload.method,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/tax/report/generate", response_model=TaxReportOut)
def generate_tax_report(payload: TaxReportGenerateIn) -> TaxReportOut:
    with db_session() as connection:
        return tax_service.generate_tax_report(
            connection,
            tax_year=payload.tax_year,
            portfolio_id=payload.portfolio_id,
            report_type=payload.report_type,
        )


@router.get("/tax/reports", response_model=list[TaxReportOut])
def list_tax_reports(
    portfolio_id: int | None = Query(default=None),
    tax_year: int | None = Query(default=None),
) -> list[TaxReportOut]:
    with db_session() as connection:
        return tax_service.list_tax_reports(connection, portfolio_id=portfolio_id, tax_year=tax_year)


@router.get("/tax/reports/{report_id}", response_model=TaxReportOut)
def get_tax_report(report_id: int) -> TaxReportOut:
    with db_session() as connection:
        try:
            return tax_service.get_tax_report(connection, report_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/tax/export")
def export_tax_report(payload: TaxExportIn) -> dict[str, Any]:
    with db_session() as connection:
        if payload.portfolio_id is None:
            payload_portfolio = None
        else:
            payload_portfolio = payload.portfolio_id
        return tax_service.export_tax_report(
            connection,
            tax_year=payload.tax_year,
            portfolio_id=payload_portfolio,
            file_format=payload.format,
        )


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
def get_portfolio(portfolio_id: int | None = Query(default=None)) -> PortfolioSummaryOut:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)


@router.post("/portfolio/init", response_model=PortfolioSummaryOut)
def init_portfolio(payload: PortfolioInitIn, portfolio_id: int | None = Query(default=None)) -> PortfolioSummaryOut:
    with db_session() as connection:
        return portfolio_engine.initialize_portfolio(connection, payload, portfolio_id=portfolio_id)


@router.post("/orders/simulate", response_model=OrderSimulationOut)
def simulate_order(payload: SimulatedOrderIn, portfolio_id: int | None = Query(default=None)) -> OrderSimulationOut:
    try:
        with db_session() as connection:
            if portfolio_id is None:
                portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
            return portfolio_engine.simulate_order(connection, payload, portfolio_id=portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/orders", response_model=list[SimulatedOrderOut])
def get_orders(portfolio_id: int | None = Query(default=None)) -> list[SimulatedOrderOut]:
    with db_session() as connection:
        return portfolio_engine.list_orders(connection, portfolio_id=portfolio_id)


@router.get("/portfolio/snapshots", response_model=list[PortfolioSnapshotOut])
def get_portfolio_snapshots(portfolio_id: int | None = Query(default=None)) -> list[PortfolioSnapshotOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return portfolio_engine.list_snapshots(connection, portfolio_id=portfolio_id)


@router.post("/portfolio/refresh", response_model=PortfolioSummaryOut)
def refresh_portfolio(portfolio_id: int | None = Query(default=None)) -> PortfolioSummaryOut:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=True)


@router.get("/portfolio/recommendations", response_model=list[PortfolioRecommendationOut])
def get_portfolio_recommendations(portfolio_id: int | None = Query(default=None)) -> list[PortfolioRecommendationOut]:
    with db_session() as connection:
        if portfolio_id is None:
            portfolio_id = multi_portfolio_service.get_active_portfolio(connection).id
        return portfolio_engine.recommendations(connection, portfolio_id=portfolio_id)


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
def dashboard(portfolio_id: int | None = Query(default=None)) -> DashboardOut:
    with db_session() as connection:
        return get_dashboard(connection, portfolio_id=portfolio_id)


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
