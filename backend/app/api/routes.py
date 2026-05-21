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
