from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AssetType = Literal["stock", "etf", "crypto", "bond", "bond_etf", "macro", "bond_proxy"]
SignalType = Literal["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"]
RiskLevel = Literal["low", "medium", "high", "very_high"]
OrderType = Literal["BUY", "SELL"]
BacktestStrategy = Literal["SCORE_THRESHOLD", "BUY_AND_HOLD", "TOP_N_SCORE"]
RebalanceFrequency = Literal["DAILY", "WEEKLY", "MONTHLY"]
AllocationMethod = Literal["EQUAL_WEIGHT", "RISK_PARITY", "SCORE_WEIGHTED", "VOL_TARGET"]
ActionType = Literal["BUY", "REDUCE", "SELL", "WATCH", "RISK", "OK"]
ActionPriority = Literal["HIGH", "MEDIUM", "LOW"]
MLModelType = Literal["LOGISTIC_REGRESSION", "RANDOM_FOREST", "HIST_GRADIENT_BOOSTING"]
MLTargetType = Literal["POSITIVE_RETURN", "OUTPERFORM_BENCHMARK", "DRAWDOWN_RISK"]
ScenarioType = Literal[
    "MARKET_CRASH",
    "TECH_SELLOFF",
    "CRYPTO_WINTER",
    "RATE_HIKE",
    "INFLATION_SHOCK",
    "MILD_CORRECTION",
    "CUSTOM",
]


class AssetCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    name: str = Field(..., min_length=1, max_length=160)
    asset_type: AssetType
    exchange: str | None = Field(default=None, max_length=80)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    sector: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    risk_level: RiskLevel = "medium"


class AssetOut(AssetCreate):
    id: int
    last_price: float | None = None
    daily_change_pct: float | None = None
    last_source: str | None = None
    provider: str | None = None
    is_real_data: bool = False
    last_price_date: str | None = None
    last_fetch_at: str | None = None
    score: float | None = None
    technical_score: float | None = None
    news_score: float | None = None
    final_score: float | None = None
    news_sentiment_label: str | None = None
    news_impact_level: str | None = None
    signal: SignalType | None = None
    confidence: str | None = None
    technical_summary: str | None = None
    updated_at: str | None = None


class PricePointOut(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: float
    source: str
    provider: str | None = None
    is_real_data: bool = False
    fetched_at: str | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    rsi_14: float | None = None
    macd_line: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bollinger_upper: float | None = None
    bollinger_lower: float | None = None


class PriceHistoryOut(BaseModel):
    symbol: str
    name: str
    asset_type: str
    currency: str
    prices: list[PricePointOut]


class PortfolioPositionOut(BaseModel):
    id: int
    asset_id: int
    symbol: str
    asset_type: str
    quantity: float
    average_price: float
    invested_amount: float
    current_price: float
    current_value: float
    realized_pnl: float
    unrealized_pnl: float
    unrealized_pnl_percent: float
    weight_percent: float
    currency: str
    technical_signal: str | None = None
    recommendation: str | None = None


class SignalOut(BaseModel):
    id: int
    asset_id: int
    symbol: str
    signal: SignalType
    score: float
    technical_score: float | None = None
    news_score: float = 0
    final_score: float | None = None
    news_sentiment_label: str | None = None
    news_impact_level: str | None = None
    risk_level: str | None = None
    confidence: str | None = None
    technical_summary: str | None = None
    reasons: list[dict[str, str]] = Field(default_factory=list)
    subscores: dict[str, float] = Field(default_factory=dict)
    created_at: str


class NewsItemOut(BaseModel):
    id: int | None = None
    symbol: str | None = None
    provider: str
    title: str
    summary: str | None = None
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    sentiment_score: float | None = None
    sentiment_label: str | None = None
    impact_level: str | None = None
    relevance_score: float | None = None
    raw_json: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NewsRefreshResultOut(BaseModel):
    symbol: str
    provider: str | None = None
    items_inserted: int
    items_updated: int
    used_cache: bool
    used_fallback: bool
    message: str


class NewsRefreshAllOut(BaseModel):
    summary: dict[str, int]
    results: list[NewsRefreshResultOut]


class NewsProviderStatusOut(BaseModel):
    provider: str
    enabled: bool
    api_key_configured: bool
    daily_limit: int
    calls_today: int
    supports: list[str] = Field(default_factory=list)


class NewsStatusOut(BaseModel):
    enable_real_news: bool
    provider_status: list[NewsProviderStatusOut]
    daily_usage: dict[str, Any]
    cache_status: dict[str, int]
    last_refresh: str | None = None


class NewsSentimentSummaryOut(BaseModel):
    symbol: str
    lookback_days: int
    news_count: int
    average_sentiment_score: float
    sentiment_label: str
    impact_level: str
    positive_count: int
    negative_count: int
    neutral_count: int
    latest_news: list[NewsItemOut] = Field(default_factory=list)


class AlertStatusOut(BaseModel):
    enabled: bool
    configured: bool
    channel: str


class ImportInputIn(BaseModel):
    csv_url: str | None = None


class ImportHoldingOut(BaseModel):
    symbol: str
    name: str
    asset_type: str
    quantity: float
    average_price: float
    currency: str


class ImportPreviewOut(BaseModel):
    rows_total: int
    rows_valid: int
    rows_invalid: int
    holdings: list[ImportHoldingOut]
    errors: list[str]


class ImportStatusOut(BaseModel):
    enabled: bool
    configured: bool
    csv_url_set: bool


class MLTrainIn(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=120)
    model_type: MLModelType = "HIST_GRADIENT_BOOSTING"
    target_type: MLTargetType = "POSITIVE_RETURN"
    horizon_days: int = Field(default=14, ge=1, le=120)
    symbols: list[str] = Field(default_factory=list)
    benchmark_symbol: str = Field(default="SPY", min_length=1, max_length=24)
    test_size_time_percent: float = Field(default=25, ge=10, le=50)
    min_samples: int = Field(default=200, ge=20, le=100000)
    cv_folds: int = Field(default=4, ge=2, le=8)


class MLPredictIn(BaseModel):
    model_id: int | None = None


class MLTrainingRunOut(BaseModel):
    id: int | None = None
    model_name: str
    target_type: str
    horizon_days: int
    train_start_date: str | None = None
    train_end_date: str | None = None
    test_start_date: str | None = None
    test_end_date: str | None = None
    samples_count: int
    accuracy: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1_score: float | None = None
    roc_auc: float | None = None
    created_at: str | None = None


class MLModelSummaryOut(BaseModel):
    id: int
    model_name: str
    model_type: str
    target_type: str
    horizon_days: int
    symbols_scope: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    model_path: str | None = None
    trained_at: str | None = None
    created_at: str | None = None


class MLModelDetailOut(MLModelSummaryOut):
    training_run: MLTrainingRunOut | None = None


class MLPredictionOut(BaseModel):
    id: int | None = None
    symbol: str
    model_id: int
    horizon_days: int
    target_type: str
    prediction_date: str
    probabilities: dict[str, float | None]
    probability_positive: float | None = None
    probability_outperform: float | None = None
    probability_drawdown: float | None = None
    predicted_label: str
    confidence: str
    features_snapshot: dict[str, float] = Field(default_factory=dict)
    explanation: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    created_at: str | None = None


class MLTrainOut(BaseModel):
    model_id: int
    training_run: MLTrainingRunOut
    metrics: dict[str, Any]
    features_used: list[str]
    warnings: list[str] = Field(default_factory=list)


class MLPredictAllOut(BaseModel):
    model_id: int
    predictions: list[MLPredictionOut]
    warnings: list[str] = Field(default_factory=list)


class MLStatusOut(BaseModel):
    models_count: int
    latest_model: MLModelSummaryOut | None = None
    latest_training_run: MLTrainingRunOut | None = None
    available_targets: list[str]
    available_model_types: list[str]
    ml_ready: bool
    message: str


class ScenarioRunIn(BaseModel):
    scenario_type: ScenarioType = "MARKET_CRASH"
    class_shocks: dict[str, float] = Field(default_factory=dict)
    symbol_shocks: dict[str, float] = Field(default_factory=dict)


class ScenarioAssetImpactOut(BaseModel):
    symbol: str
    asset_type: str
    current_value: float
    shock_percent: float
    stressed_value: float
    absolute_impact: float
    loss_contribution_percent: float


class ScenarioClassImpactOut(BaseModel):
    asset_class: str
    current_value: float
    stressed_value: float
    absolute_impact: float
    shock_percent: float


class ScenarioRunOut(BaseModel):
    scenario_type: str
    scenario_label: str
    current_value: float
    stressed_value: float
    cash: float
    absolute_loss: float
    percentage_loss: float
    risk_level: str
    asset_impacts: list[ScenarioAssetImpactOut]
    class_impacts: list[ScenarioClassImpactOut]
    mitigation: list[str]


class RebalanceTradeOut(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL", "HOLD"]
    current_weight: float
    target_weight: float
    current_value: float
    target_value: float
    delta_value: float
    delta_quantity: float
    price: float | None = None


class RebalanceOut(BaseModel):
    method: str
    total_value: float
    estimated_volatility: float
    trades: list[RebalanceTradeOut]
    notes: list[str] = Field(default_factory=list)


class ImportApplyOut(BaseModel):
    imported: int
    created_assets: int
    rows_invalid: int
    errors: list[str]
    portfolio_value: float


class AlertSendOut(BaseModel):
    ok: bool
    message_id: int | None = None
    actions_sent: int | None = None
    headline: str | None = None


class DashboardOut(BaseModel):
    initialized: bool
    message: str | None = None
    assets_count: int
    positions_count: int
    portfolio_value: float
    signals_count: int
    price_points_count: int = 0
    average_score: float | None = None
    asset_type_breakdown: dict[str, int] = Field(default_factory=dict)
    risk_breakdown: dict[str, int] = Field(default_factory=dict)
    signal_breakdown: dict[str, int] = Field(default_factory=dict)
    latest_signals: list[SignalOut]
    top_assets: list[AssetOut] = Field(default_factory=list)
    weakest_assets: list[AssetOut] = Field(default_factory=list)
    risky_assets: list[AssetOut] = Field(default_factory=list)
    cash: float = 0
    total_pnl: float = 0
    total_pnl_percent: float = 0
    risk_warnings_count: int = 0
    top_position: PortfolioPositionOut | None = None
    portfolio_snapshots: list[dict[str, float | str]] = Field(default_factory=list)
    latest_backtest: dict[str, float | int | str | None] | None = None
    data_status: dict[str, object] = Field(default_factory=dict)
    latest_high_impact_news: list[NewsItemOut] = Field(default_factory=list)
    market_news_summary: dict[str, Any] = Field(default_factory=dict)


class TechnicalAnalysisOut(BaseModel):
    asset: AssetOut
    latest_price: float | None
    indicators: dict[str, float] = Field(default_factory=dict)
    conditions: dict[str, bool] = Field(default_factory=dict)
    support_resistance: dict[str, float | None] = Field(default_factory=dict)
    subscores: dict[str, float] = Field(default_factory=dict)
    score: float
    technical_score: float | None = None
    news_score: float = 0
    final_score: float | None = None
    news_sentiment_label: str | None = None
    news_impact_level: str | None = None
    signal: SignalType
    risk_level: str
    confidence: str
    reasons: list[dict[str, str]] = Field(default_factory=list)
    summaries: dict[str, str] = Field(default_factory=dict)
    technical_summary: str


class SeedSummaryOut(BaseModel):
    reset: bool
    assets_inserted: int
    price_rows_inserted: int
    signals_inserted: int
    portfolio_positions_inserted: int = 0
    simulated_orders_inserted: int = 0
    portfolio_snapshots_inserted: int = 0
    started_at: str
    completed_at: str


class PortfolioInitIn(BaseModel):
    initial_cash: float = Field(..., gt=0)
    max_single_asset_weight: float = Field(default=25, gt=0, le=100)
    max_asset_class_weight: float = Field(default=50, gt=0, le=100)
    default_fee_percent: float = Field(default=0.1, ge=0, le=5)


class PortfolioSettingsOut(BaseModel):
    initial_cash: float
    current_cash: float
    max_single_asset_weight: float
    max_asset_class_weight: float
    default_fee_percent: float
    crypto_max_weight: float
    min_cash_weight: float
    max_cash_weight: float


class RiskWarningOut(BaseModel):
    level: str
    code: str
    message: str
    symbol: str | None = None


class PortfolioSummaryOut(BaseModel):
    cash: float
    total_value: float
    invested_value: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_pnl_percent: float
    positions: list[PortfolioPositionOut]
    allocation_by_asset_type: dict[str, float]
    allocation_by_currency: dict[str, float]
    risk_warnings: list[RiskWarningOut]
    settings: PortfolioSettingsOut


class SimulatedOrderIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    order_type: OrderType
    quantity: float = Field(..., gt=0)
    price: float | None = Field(default=None, gt=0)
    fees: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=500)
    strategy_tag: str | None = Field(default=None, max_length=80)


class SimulatedOrderOut(BaseModel):
    id: int
    asset_id: int
    symbol: str
    order_type: OrderType
    quantity: float
    price: float
    fees: float
    gross_amount: float
    net_amount: float
    order_date: str
    note: str | None = None
    strategy_tag: str | None = None


class OrderSimulationOut(BaseModel):
    order: SimulatedOrderOut
    updated_position: PortfolioPositionOut | None
    updated_portfolio_summary: PortfolioSummaryOut
    warnings: list[RiskWarningOut]


class PortfolioSnapshotOut(BaseModel):
    id: int
    snapshot_date: str
    total_value: float
    invested_value: float
    cash: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_pnl_percent: float
    created_at: str


class PortfolioRecommendationOut(BaseModel):
    symbol: str
    technical_signal: str | None
    technical_score: float | None
    portfolio_weight: float
    final_recommendation: str
    reason: str


class BacktestRunIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    strategy_name: BacktestStrategy
    symbols: list[str] = Field(..., min_length=1)
    initial_cash: float = Field(default=100000, gt=0)
    start_date: str
    end_date: str
    benchmark_symbol: str = Field(default="SPY", min_length=1, max_length=24)
    buy_threshold: float = Field(default=70, ge=0, le=100)
    sell_threshold: float = Field(default=40, ge=0, le=100)
    max_asset_weight: float = Field(default=0.15, gt=0, le=1)
    fee_percent: float = Field(default=0.1, ge=0, le=5)
    stop_loss_percent: float | None = Field(default=8, gt=0, le=100)
    take_profit_percent: float | None = Field(default=25, gt=0, le=500)
    rebalance_frequency: RebalanceFrequency = "WEEKLY"
    top_n: int | None = Field(default=5, ge=1, le=25)


class BacktestSummaryOut(BaseModel):
    id: int | None = None
    name: str
    strategy_name: str
    initial_cash: float
    start_date: str
    end_date: str
    benchmark_symbol: str | None = None
    buy_threshold: float
    sell_threshold: float
    max_asset_weight: float
    fee_percent: float
    stop_loss_percent: float | None = None
    take_profit_percent: float | None = None
    rebalance_frequency: str
    total_return_percent: float
    cagr: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    final_value: float
    benchmark_return_percent: float = 0
    alpha_vs_benchmark: float = 0
    created_at: str | None = None


class BacktestEquityPointOut(BaseModel):
    id: int | None = None
    date: str
    portfolio_value: float
    cash: float
    invested_value: float
    drawdown_percent: float
    benchmark_value: float | None = None
    benchmark_return_percent: float | None = None


class BacktestTradeOut(BaseModel):
    id: int | None = None
    date: str
    symbol: str
    order_type: OrderType
    quantity: float
    price: float
    fees: float
    gross_amount: float
    net_amount: float
    pnl: float
    reason: str | None = None


class BacktestPositionOut(BaseModel):
    id: int | None = None
    symbol: str
    quantity: float
    average_price: float
    final_price: float
    final_value: float
    realized_pnl: float
    unrealized_pnl: float


class BacktestBenchmarkComparisonOut(BaseModel):
    benchmark_symbol: str | None = None
    benchmark_return_percent: float
    alpha_vs_benchmark: float
    benchmark_final_value: float


class BacktestNetAnalysisOut(BaseModel):
    gross_return_percent: float
    gross_profit: float
    commission_costs: float
    slippage_costs: float
    realized_gains_taxable: float
    capital_gains_tax: float
    stamp_duty: float
    total_costs_and_taxes: float
    net_final_value: float
    net_return_percent: float
    effective_tax_rate_percent: float
    notes: list[str] = Field(default_factory=list)


class BacktestResultOut(BaseModel):
    backtest_id: int
    summary: BacktestSummaryOut
    equity_curve: list[BacktestEquityPointOut]
    trades: list[BacktestTradeOut]
    final_positions: list[BacktestPositionOut]
    benchmark_comparison: BacktestBenchmarkComparisonOut
    net_analysis: BacktestNetAnalysisOut | None = None


class BacktestCompareIn(BaseModel):
    name: str = Field(default="Confronto strategie", min_length=1, max_length=120)
    strategy_names: list[BacktestStrategy] = Field(..., min_length=2, max_length=3)
    symbols: list[str] = Field(..., min_length=1)
    initial_cash: float = Field(default=100000, gt=0)
    start_date: str
    end_date: str
    benchmark_symbol: str = Field(default="SPY", min_length=1, max_length=24)
    buy_threshold: float = Field(default=70, ge=0, le=100)
    sell_threshold: float = Field(default=40, ge=0, le=100)
    max_asset_weight: float = Field(default=0.15, gt=0, le=1)
    fee_percent: float = Field(default=0.1, ge=0, le=5)
    stop_loss_percent: float | None = Field(default=8, gt=0, le=100)
    take_profit_percent: float | None = Field(default=25, gt=0, le=500)
    rebalance_frequency: RebalanceFrequency = "WEEKLY"
    top_n: int | None = Field(default=5, ge=1, le=25)


class BacktestCompareEntryOut(BaseModel):
    strategy_name: str
    label: str
    rank: int
    summary: BacktestSummaryOut
    equity_curve: list[BacktestEquityPointOut]


class BacktestCompareOut(BaseModel):
    name: str
    start_date: str
    end_date: str
    benchmark_symbol: str | None = None
    benchmark_return_percent: float
    best_strategy: str
    entries: list[BacktestCompareEntryOut]


class WalkForwardIn(BacktestRunIn):
    folds: int = Field(default=4, ge=2, le=12)


class WalkForwardFoldOut(BaseModel):
    fold: int
    start_date: str
    end_date: str
    total_return_percent: float
    cagr: float
    max_drawdown: float
    sharpe_ratio: float
    alpha_vs_benchmark: float
    total_trades: int
    final_value: float


class WalkForwardOut(BaseModel):
    strategy_name: str
    folds: int
    full_period_return_percent: float
    mean_return_percent: float
    median_return_percent: float
    std_return_percent: float
    positive_folds: int
    folds_beating_benchmark: int
    worst_fold_return_percent: float
    best_fold_return_percent: float
    mean_alpha_vs_benchmark: float
    consistency: Literal["ROBUSTA", "INCERTA", "FRAGILE"]
    verdict: str
    fold_results: list[WalkForwardFoldOut]


class ActionItemOut(BaseModel):
    type: ActionType
    priority: ActionPriority
    symbol: str | None = None
    title: str
    reason: str
    signal: str | None = None
    score: float | None = None
    weight_percent: float | None = None


class ActionBoardOut(BaseModel):
    generated_at: str
    data_mode: str
    enable_real_data: bool
    headline: str
    counts: dict[str, int]
    actions: list[ActionItemOut]


class AllocationPlanIn(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=25)
    method: AllocationMethod = "RISK_PARITY"
    total_capital: float = Field(default=100000, gt=0)
    target_volatility: float | None = Field(default=0.15, gt=0, le=2)
    max_weight: float | None = Field(default=None, gt=0, le=1)
    lookback_days: int = Field(default=120, ge=20, le=750)


class AllocationItemOut(BaseModel):
    symbol: str
    name: str
    weight_percent: float
    capital: float
    price: float | None = None
    suggested_quantity: int
    volatility: float
    score: float | None = None


class AllocationPlanOut(BaseModel):
    method: str
    total_capital: float
    invested_capital: float
    cash_buffer: float
    target_volatility: float | None = None
    estimated_volatility: float
    allocations: list[AllocationItemOut]
    notes: list[str] = Field(default_factory=list)


class DataProviderStatusOut(BaseModel):
    provider: str
    enabled: bool
    api_key_configured: bool
    daily_limit: int
    calls_today: int
    supports: list[str] = Field(default_factory=list)


class ApiUsageOut(BaseModel):
    provider: str
    usage_date: str
    calls_count: int
    daily_limit: int
    updated_at: str | None = None


class DataStatusOut(BaseModel):
    enable_real_data: bool
    provider_status: list[DataProviderStatusOut]
    api_usage: list[ApiUsageOut]
    cache_stats: dict[str, int]
    global_last_update: str | None = None
    data_mode: Literal["SEED", "MIXED", "REAL"]


class AssetDataStatusOut(BaseModel):
    symbol: str
    last_price_date: str | None = None
    last_source: str | None = None
    provider: str | None = None
    is_real_data: bool = False
    last_fetch_at: str | None = None
    cache_status: str
    message: str


class DataRefreshResultOut(BaseModel):
    symbol: str
    provider: str | None = None
    rows_inserted: int
    rows_updated: int
    used_cache: bool
    used_fallback: bool
    message: str


class DataRefreshAllOut(BaseModel):
    summary: dict[str, int]
    results: list[DataRefreshResultOut]
