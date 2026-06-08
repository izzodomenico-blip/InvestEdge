from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from backend.app.database import db_session
from backend.app.models import (
    ActionBoardOut,
    AlertSendOut,
    AlertStatusOut,
    AllocationPlanIn,
    AllocationPlanOut,
    ApiUsageOut,
    AssetCreate,
    AssetDataStatusOut,
    AssetOut,
    BacktestCompareIn,
    BacktestCompareOut,
    BacktestResultOut,
    BacktestRunIn,
    BacktestSummaryOut,
    DashboardOut,
    DataRefreshAllOut,
    DataRefreshResultOut,
    DataStatusOut,
    ImportApplyOut,
    ImportInputIn,
    ImportPreviewOut,
    ImportStatusOut,
    MLModelSummaryOut,
    MLPredictAllOut,
    MLPredictIn,
    MLPredictionOut,
    MLStatusOut,
    MLTrainIn,
    MLTrainOut,
    NewsItemOut,
    NewsRefreshAllOut,
    NewsRefreshResultOut,
    NewsSentimentSummaryOut,
    NewsStatusOut,
    OrderSimulationOut,
    PortfolioInitIn,
    PortfolioRecommendationOut,
    PortfolioSnapshotOut,
    PortfolioSummaryOut,
    PriceHistoryOut,
    RebalanceOut,
    RebalanceTradeOut,
    ReportSummaryOut,
    ScenarioRunIn,
    ScenarioRunOut,
    SeedSummaryOut,
    SignalOut,
    SimulatedOrderIn,
    SimulatedOrderOut,
    TaxReportOut,
    TechnicalAnalysisOut,
    WalkForwardIn,
    WalkForwardOut,
)
from backend.app.services import google_sheets_import_service
from backend.app.services.action_board_service import get_action_board
from backend.app.services.alert_service import (
    AlertNotConfigured,
    alert_status,
    send_test_message,
    send_today_alert,
)
from backend.app.services.allocation_engine import AllocationEngine
from backend.app.services.assets_service import create_asset, delete_asset, get_asset_by_symbol, list_assets
from backend.app.services.backtest_engine import BacktestEngine
from backend.app.services.dashboard_service import get_dashboard
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.ml_engine import MLEngine
from backend.app.services.news_engine import NewsEngine
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.prices_service import get_price_history
from backend.app.services.report_service import orders_csv, portfolio_csv, report_summary, tax_csv
from backend.app.services.scenario_service import run_scenario
from backend.app.services.signals_service import get_signal_by_symbol, list_signals
from backend.app.services.tax_service import compute_tax_report
from backend.app.services.technical_analysis_service import get_technical_analysis
from backend.scripts.seed_database import seed_database

router = APIRouter()
portfolio_engine = PortfolioEngine()
backtest_engine = BacktestEngine()
allocation_engine = AllocationEngine()
market_data_service = MarketDataService()
news_engine = NewsEngine()
ml_engine = MLEngine()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "investedge-api"}


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


@router.delete("/assets/{symbol}")
def remove_asset(symbol: str) -> dict[str, bool | str]:
    with db_session() as connection:
        deleted = delete_asset(connection, symbol)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset {symbol.upper()} non trovato.")
    return {"deleted": True, "symbol": symbol.upper()}


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


@router.post("/portfolio/allocation/plan", response_model=AllocationPlanOut)
def plan_allocation(payload: AllocationPlanIn) -> AllocationPlanOut:
    try:
        with db_session() as connection:
            return AllocationPlanOut(
                **allocation_engine.plan(
                    connection,
                    symbols=payload.symbols,
                    method=payload.method,
                    total_capital=payload.total_capital,
                    target_volatility=payload.target_volatility,
                    max_weight=payload.max_weight,
                    lookback_days=payload.lookback_days,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/portfolio/allocation/apply", response_model=PortfolioSummaryOut)
def apply_allocation(payload: AllocationPlanIn) -> PortfolioSummaryOut:
    try:
        with db_session() as connection:
            plan = allocation_engine.plan(
                connection,
                symbols=payload.symbols,
                method=payload.method,
                total_capital=payload.total_capital,
                target_volatility=payload.target_volatility,
                max_weight=payload.max_weight,
                lookback_days=payload.lookback_days,
            )
            items = []
            for allocation in plan["allocations"]:
                if allocation["suggested_quantity"] <= 0 or not allocation["price"]:
                    continue
                asset = get_asset_by_symbol(connection, allocation["symbol"])
                if asset is None:
                    continue
                items.append(
                    {
                        "asset_id": asset.id,
                        "symbol": asset.symbol,
                        "quantity": allocation["suggested_quantity"],
                        "average_price": allocation["price"],
                        "asset_type": asset.asset_type,
                        "currency": asset.currency,
                        "notes": "Creato dal pianificatore di allocazione",
                    }
                )
            if not items:
                raise ValueError("Nessuna posizione da creare: aumenta il capitale o controlla i prezzi disponibili.")
            return portfolio_engine.replace_positions(connection, items)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/summary", response_model=ReportSummaryOut)
def reports_summary() -> ReportSummaryOut:
    with db_session() as connection:
        return ReportSummaryOut(**report_summary(connection))


@router.get("/reports/portfolio.csv")
def reports_portfolio_csv() -> Response:
    with db_session() as connection:
        return _csv_response(portfolio_csv(connection), "investedge_portafoglio.csv")


@router.get("/reports/orders.csv")
def reports_orders_csv() -> Response:
    with db_session() as connection:
        return _csv_response(orders_csv(connection), "investedge_operazioni.csv")


@router.get("/reports/tax.csv")
def reports_tax_csv() -> Response:
    with db_session() as connection:
        return _csv_response(tax_csv(connection), "investedge_fiscale.csv")


@router.get("/tax/report", response_model=TaxReportOut)
def tax_report(year: int | None = Query(default=None, ge=1990, le=2100)) -> TaxReportOut:
    with db_session() as connection:
        return TaxReportOut(**compute_tax_report(connection, tax_year=year))


@router.post("/scenarios/run", response_model=ScenarioRunOut)
def scenario_run(payload: ScenarioRunIn) -> ScenarioRunOut:
    try:
        with db_session() as connection:
            return ScenarioRunOut(
                **run_scenario(
                    connection,
                    scenario_type=payload.scenario_type,
                    class_shocks=payload.class_shocks,
                    symbol_shocks=payload.symbol_shocks,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/portfolio/allocation/rebalance", response_model=RebalanceOut)
def rebalance_portfolio(payload: AllocationPlanIn) -> RebalanceOut:
    try:
        with db_session() as connection:
            summary = portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
            current = {position.symbol: position for position in summary.positions}
            symbols = payload.symbols or list(current.keys())
            if not symbols:
                raise ValueError("Portafoglio vuoto: crea un portafoglio o indica gli asset da ottimizzare.")
            total_value = summary.total_value if summary.total_value > 0 else payload.total_capital
            plan = allocation_engine.plan(
                connection,
                symbols=symbols,
                method=payload.method,
                total_capital=total_value,
                target_volatility=payload.target_volatility,
                max_weight=payload.max_weight,
                lookback_days=payload.lookback_days,
            )
            target = {item["symbol"]: item for item in plan["allocations"]}
            trades: list[RebalanceTradeOut] = []
            for symbol in dict.fromkeys([*symbols, *current.keys()]):
                position = current.get(symbol)
                target_item = target.get(symbol)
                current_value = float(position.current_value) if position else 0.0
                target_value = float(target_item["capital"]) if target_item else 0.0
                price = (
                    float(target_item["price"])
                    if target_item and target_item.get("price")
                    else (float(position.current_price) if position and position.current_price else None)
                )
                delta_value = round(target_value - current_value, 2)
                action = "BUY" if delta_value > 1 else "SELL" if delta_value < -1 else "HOLD"
                delta_quantity = round(delta_value / price, 4) if price else 0.0
                trades.append(
                    RebalanceTradeOut(
                        symbol=symbol,
                        action=action,
                        current_weight=round((current_value / total_value * 100) if total_value > 0 else 0, 2),
                        target_weight=round(float(target_item["weight_percent"]) if target_item else 0.0, 2),
                        current_value=round(current_value, 2),
                        target_value=round(target_value, 2),
                        delta_value=delta_value,
                        delta_quantity=delta_quantity,
                        price=round(price, 4) if price else None,
                    )
                )
            trades.sort(key=lambda trade: abs(trade.delta_value), reverse=True)
            return RebalanceOut(
                method=payload.method,
                total_value=round(total_value, 2),
                estimated_volatility=plan["estimated_volatility"],
                trades=trades,
                notes=plan["notes"],
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/backtests/run", response_model=BacktestResultOut)
def run_backtest(payload: BacktestRunIn) -> BacktestResultOut:
    try:
        with db_session() as connection:
            return backtest_engine.run_backtest(connection, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/backtests/compare", response_model=BacktestCompareOut)
def compare_backtests(payload: BacktestCompareIn) -> BacktestCompareOut:
    try:
        with db_session() as connection:
            return BacktestCompareOut(**backtest_engine.compare_strategies(connection, payload))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/backtests/walk-forward", response_model=WalkForwardOut)
def walk_forward_backtest(payload: WalkForwardIn) -> WalkForwardOut:
    try:
        with db_session() as connection:
            return WalkForwardOut(**backtest_engine.walk_forward(connection, payload))
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


@router.get("/action-board", response_model=ActionBoardOut)
def action_board() -> ActionBoardOut:
    with db_session() as connection:
        return ActionBoardOut(**get_action_board(connection))


@router.get("/import/google-sheets/status", response_model=ImportStatusOut)
def import_google_sheets_status() -> ImportStatusOut:
    return ImportStatusOut(**google_sheets_import_service.status())


@router.post("/import/google-sheets/preview", response_model=ImportPreviewOut)
def import_google_sheets_preview(payload: ImportInputIn | None = None) -> ImportPreviewOut:
    try:
        return ImportPreviewOut(**google_sheets_import_service.preview(payload.csv_url if payload else None))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/import/google-sheets/apply", response_model=ImportApplyOut)
def import_google_sheets_apply(payload: ImportInputIn | None = None) -> ImportApplyOut:
    try:
        with db_session() as connection:
            return ImportApplyOut(
                **google_sheets_import_service.apply_import(connection, payload.csv_url if payload else None)
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/alerts/status", response_model=AlertStatusOut)
def alerts_status() -> AlertStatusOut:
    return AlertStatusOut(**alert_status())


@router.post("/alerts/test", response_model=AlertSendOut)
def alerts_test() -> AlertSendOut:
    try:
        return AlertSendOut(**send_test_message())
    except AlertNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/alerts/send-today", response_model=AlertSendOut)
def alerts_send_today() -> AlertSendOut:
    try:
        with db_session() as connection:
            return AlertSendOut(**send_today_alert(connection))
    except AlertNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


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
        return [MLModelSummaryOut(**model) for model in ml_engine.list_models(connection)]


@router.post("/ml/predict/{symbol}", response_model=MLPredictionOut)
def ml_predict(symbol: str, payload: MLPredictIn | None = None) -> MLPredictionOut:
    try:
        with db_session() as connection:
            return MLPredictionOut(
                **ml_engine.predict_for_symbol(connection, symbol, payload.model_id if payload else None)
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/ml/predict-all", response_model=MLPredictAllOut)
def ml_predict_all(payload: MLPredictIn | None = None) -> MLPredictAllOut:
    try:
        with db_session() as connection:
            return MLPredictAllOut(**ml_engine.predict_all_watchlist(connection, payload.model_id if payload else None))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/ml/predictions/{symbol}", response_model=list[MLPredictionOut])
def ml_predictions(symbol: str, limit: int = Query(default=10, ge=1, le=50)) -> list[MLPredictionOut]:
    with db_session() as connection:
        return [MLPredictionOut(**item) for item in ml_engine.latest_predictions(connection, symbol, limit=limit)]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard() -> DashboardOut:
    with db_session() as connection:
        return get_dashboard(connection)


@router.get("/news", response_model=list[NewsItemOut])
def get_news(
    limit: int = Query(default=50, ge=1, le=200),
    symbol: str | None = Query(default=None, min_length=1, max_length=24),
) -> list[NewsItemOut]:
    with db_session() as connection:
        return [NewsItemOut(**item) for item in news_engine.get_market_news(connection, limit=limit, symbol=symbol)]


@router.get("/news/status", response_model=NewsStatusOut)
def news_status() -> NewsStatusOut:
    with db_session() as connection:
        return NewsStatusOut(**news_engine.get_status(connection))


@router.get("/news/sentiment/{symbol}", response_model=NewsSentimentSummaryOut)
def news_sentiment(symbol: str) -> NewsSentimentSummaryOut:
    try:
        with db_session() as connection:
            return NewsSentimentSummaryOut(**news_engine.get_news_sentiment_summary(connection, symbol))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/news/refresh/{symbol}", response_model=NewsRefreshResultOut)
def refresh_news(symbol: str, force: bool = Query(default=False)) -> NewsRefreshResultOut:
    try:
        with db_session() as connection:
            return NewsRefreshResultOut(**news_engine.refresh_news_for_symbol(connection, symbol, force=force))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/news/refresh-all", response_model=NewsRefreshAllOut)
def refresh_all_news(
    limit: int | None = Query(default=None, ge=1, le=50),
    force: bool = Query(default=False),
) -> NewsRefreshAllOut:
    with db_session() as connection:
        return NewsRefreshAllOut(**news_engine.refresh_all_news(connection, limit=limit, force=force))


@router.get("/news/{symbol}", response_model=list[NewsItemOut])
def get_symbol_news(symbol: str, limit: int = Query(default=50, ge=1, le=200)) -> list[NewsItemOut]:
    try:
        with db_session() as connection:
            return [NewsItemOut(**item) for item in news_engine.get_news_for_symbol(connection, symbol, limit=limit)]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
    limit: int | None = Query(default=None, ge=1, le=25),
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
