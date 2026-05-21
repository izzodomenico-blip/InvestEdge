from __future__ import annotations

from enum import Enum
from typing import Literal, Any

from pydantic import BaseModel, Field


AssetType = Literal["stock", "etf", "crypto", "bond", "bond_etf", "macro", "bond_proxy"]
SignalType = Literal["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"]
RiskLevel = Literal["low", "medium", "high", "very_high"]
OrderType = Literal["BUY", "SELL"]
BacktestStrategy = Literal["SCORE_THRESHOLD", "BUY_AND_HOLD", "TOP_N_SCORE"]
RebalanceFrequency = Literal["DAILY", "WEEKLY", "MONTHLY"]
MLModelType = Literal["LOGISTIC_REGRESSION", "RANDOM_FOREST"]
MLTargetType = Literal["POSITIVE_RETURN", "OUTPERFORM_BENCHMARK", "DRAWDOWN_RISK"]
UniverseLevel = Literal["CORE", "EXTENDED", "CANDIDATE"]


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
    signal: SignalType | None = None
    confidence: str | None = None
    technical_summary: str | None = None
    ml_model_id: int | None = None
    ml_probability: float | None = None
    ml_confidence: str | None = None
    ml_label: str | None = None
    ml_target_type: str | None = None
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
    risk_level: str | None = None
    confidence: str | None = None
    technical_summary: str | None = None
    reasons: list[dict[str, str]] = Field(default_factory=list)
    subscores: dict[str, float] = Field(default_factory=dict)
    created_at: str


class SystemHealthOut(BaseModel):
    status: Literal["healthy", "degraded", "down"]
    database: str
    providers: dict[str, str]
    cache: str
    timestamp: str


class DataQualityCheckOut(BaseModel):
    symbol: str
    score: float
    grade: str
    checks: dict[str, bool]
    details: dict[str, str | int | float]
    is_valid: bool
    last_check: str


class ValidatedSignalOut(BaseModel):
    symbol: str
    asset_id: int
    original_signal: str
    validated_signal: str
    reason: str
    data_quality_score: float
    ml_confidence: str | None = None
    news_sentiment: str | None = None
    portfolio_weight: float | None = None
    action_suggested: str
    timestamp: str


class OperationalRankingOut(BaseModel):
    buy_candidates: list[ValidatedSignalOut] = Field(default_factory=list)
    watch_candidates: list[ValidatedSignalOut] = Field(default_factory=list)
    reduce_candidates: list[ValidatedSignalOut] = Field(default_factory=list)
    excluded_candidates: list[ValidatedSignalOut] = Field(default_factory=list)
    updated_at: str


class PortfolioActionOut(BaseModel):
    symbol: str
    action: str
    reason: str
    current_weight: float
    target_weight: float | None = None
    timestamp: str


class StrategyPlanConfig(BaseModel):
    plan_name: str
    universe_level: str  # CORE, EXTENDED, WATCHLIST
    strategy_mode: Literal["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]
    max_positions: int = 10
    max_single_asset_weight: float = 15.0
    max_asset_class_weight: float = 40.0
    min_data_quality_score: float = 70.0
    min_confidence: str = "MEDIUM"
    allow_crypto: bool = False
    max_crypto_weight: float = 5.0
    require_real_data: bool = False
    include_ml: bool = True
    include_news: bool = True
    rebalance_threshold_percent: float = 2.0
    cash_reserve_percent: float = 5.0
    order_generation_mode: Literal["SUGGEST_ONLY", "PAPER_ORDERS"] = "SUGGEST_ONLY"


class StrategyPlanItemOut(BaseModel):
    id: int | None = None
    symbol: str
    current_weight: float
    target_weight: float
    current_value: float
    target_value: float
    delta_value: float
    suggested_action: str
    operational_signal: str | None = None
    confidence: str | None = None
    data_quality_score: float | None = None
    reason: str | None = None
    blocker: str | None = None


class StrategyPlanOrderOut(BaseModel):
    id: int | None = None
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: float
    estimated_price: float
    estimated_gross_amount: float
    estimated_fees: float
    estimated_net_amount: float
    reason: str | None = None
    status: str = "PROPOSED"


class StrategyPlanSummaryOut(BaseModel):
    id: int
    plan_name: str
    strategy_mode: str
    universe_level: str
    total_current_value: float
    target_invested_value: float
    expected_cash_after_plan: float
    estimated_orders_count: int
    status: str
    created_at: str


class StrategyPlanFullOut(BaseModel):
    summary: StrategyPlanSummaryOut
    config: StrategyPlanConfig
    items: list[StrategyPlanItemOut]
    proposed_orders: list[StrategyPlanOrderOut]
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"


class AlertOut(BaseModel):
    id: int
    alert_type: str
    severity: str
    symbol: str | None = None
    title: str
    message: str
    status: str
    source_module: str | None = None
    payload_json: str | None = None
    created_at: str
    updated_at: str
    acknowledged_at: str | None = None
    closed_at: str | None = None


class AlertSummaryOut(BaseModel):
    open_count: int
    critical_count: int
    warning_count: int
    info_count: int
    latest_alerts: list[AlertOut]
    by_type: dict[str, int]


class AlertRuleOut(BaseModel):
    id: int
    rule_name: str
    alert_type: str
    enabled: bool
    severity: str
    universe_level: str | None = None
    symbol: str | None = None
    threshold_value: float | None = None
    config_json: str | None = None


class AlertRuleToggleIn(BaseModel):
    enabled: bool


class SchedulerRunIn(BaseModel):
    run_type: Literal["FULL_MANUAL", "DATA_REFRESH", "SIGNALS", "RANKING", "QUALITY", "ALERTS", "REPORT"]
    limit: int | None = Field(default=None, ge=1, le=50)
    force: bool = False
    generate_report: bool = False


class SchedulerRunOut(BaseModel):
    id: int
    run_type: str
    status: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    created_at: str


class OperationalReportSummary(BaseModel):
    system_health: dict[str, Any]
    data_quality_avg: float
    buy_candidates_count: int
    watch_candidates_count: int
    reduce_candidates_count: int
    portfolio_value: float
    risk_warnings_count: int
    open_alerts_count: int


class OperationalReportOut(BaseModel):
    id: int
    report_type: str
    report_date: str
    title: str
    summary: OperationalReportSummary
    markdown_text: str | None = None
    created_at: str


class OptimizationMethod(str, Enum):
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    SCORE_WEIGHTED = "SCORE_WEIGHTED"
    RISK_ADJUSTED = "RISK_ADJUSTED"
    CONSERVATIVE_ALLOCATION = "CONSERVATIVE_ALLOCATION"
    AGGRESSIVE_ALLOCATION = "AGGRESSIVE_ALLOCATION"


class OptimizerConfig(BaseModel):
    run_name: str
    universe_source: Literal["WATCHLIST", "CORE", "EXTENDED", "OPERATIONAL_BUY_CANDIDATES"]
    optimization_method: OptimizationMethod
    initial_capital_mode: Literal["CURRENT_PORTFOLIO", "CUSTOM_CAPITAL"]
    custom_capital: float | None = None
    max_positions: int = 15
    min_position_weight: float = 2.0
    max_single_asset_weight: float = 15.0
    max_asset_class_weight: float = 40.0
    max_crypto_weight: float = 10.0
    cash_reserve_percent: float = 5.0
    min_data_quality_score: float = 60.0
    min_operational_confidence: str = "MEDIUM"
    require_real_data: bool = False
    include_ml: bool = True
    include_news: bool = True
    rebalance_threshold_percent: float = 1.5
    allow_sell: bool = True
    allow_buy: bool = True
    fee_percent: float = 0.1


class OptimizationItemOut(BaseModel):
    id: int | None = None
    symbol: str
    current_weight: float
    target_weight: float
    current_value: float
    target_value: float
    delta_value: float
    operational_signal: str | None = None
    data_quality_score: float | None = None
    ml_probability: float | None = None
    news_sentiment: str | None = None
    risk_level: str | None = None
    reason: str | None = None


class RebalanceOrderOut(BaseModel):
    id: int | None = None
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: float
    estimated_price: float
    estimated_gross_amount: float
    estimated_fees: float
    estimated_net_amount: float
    reason: str | None = None
    status: str = "PROPOSED"


class OptimizationRunSummaryOut(BaseModel):
    id: int
    run_name: str
    optimization_method: str
    universe_source: str
    current_total_value: float
    target_invested_value: float
    target_cash: float
    expected_cash_after_rebalance: float
    estimated_orders_count: int
    estimated_fees: float
    estimated_turnover_percent: float
    created_at: str


class OptimizationRunFullOut(BaseModel):
    summary: OptimizationRunSummaryOut
    config: OptimizerConfig
    items: list[OptimizationItemOut]
    proposed_orders: list[RebalanceOrderOut]
    risk_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class ScenarioType(str, Enum):
    CUSTOM = "CUSTOM"
    MARKET_CRASH = "MARKET_CRASH"
    TECH_SELL_OFF = "TECH_SELL_OFF"
    CRYPTO_CRASH = "CRYPTO_CRASH"
    BOND_SHOCK = "BOND_SHOCK"
    RATE_HIKE = "RATE_HIKE"
    RECESSION = "RECESSION"
    INFLATION_SHOCK = "INFLATION_SHOCK"
    BULL_RALLY = "BULL_RALLY"


class ScenarioConfig(BaseModel):
    scenario_name: str
    scenario_type: ScenarioType
    portfolio_source: Literal["CURRENT_PORTFOLIO", "LATEST_OPTIMIZED_PORTFOLIO", "CUSTOM_TARGET"]
    asset_class_shocks: dict[str, float] = Field(default_factory=dict)
    symbol_shocks: dict[str, float] = Field(default_factory=dict)
    include_correlations: bool = False
    include_ml_risk: bool = False
    include_news_risk: bool = False
    include_liquidity_buffer: bool = False
    confidence_level: Literal[95, 99] = 95


class ScenarioAssetImpactOut(BaseModel):
    id: int | None = None
    symbol: str
    asset_type: str
    current_value: float
    shock_percent: float
    stressed_value: float
    absolute_impact: float
    percentage_impact: float
    loss_contribution_percent: float


class ScenarioClassImpactOut(BaseModel):
    id: int | None = None
    asset_class: str
    current_value: float
    shock_percent: float
    stressed_value: float
    absolute_impact: float
    percentage_impact: float


class ScenarioRunSummaryOut(BaseModel):
    id: int
    scenario_name: str
    scenario_type: str
    portfolio_source: str
    current_portfolio_value: float
    stressed_portfolio_value: float
    absolute_loss: float
    percentage_loss: float
    risk_level: str
    created_at: str


class ScenarioRunFullOut(BaseModel):
    summary: ScenarioRunSummaryOut
    config: ScenarioConfig
    asset_impacts: list[ScenarioAssetImpactOut]
    class_impacts: list[ScenarioClassImpactOut]
    loss_contribution: dict[str, float]
    mitigation_suggestions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    portfolio_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    latest_backtest: dict[str, Any] | None = None
    data_status: dict[str, Any] = Field(default_factory=dict)
    universe_summary: dict[str, Any] = Field(default_factory=dict)
    ml_status: dict[str, Any] = Field(default_factory=dict)
    latest_ml_prediction: dict[str, Any] | None = None
    high_impact_news: list[NewsItemOut] = Field(default_factory=list)
    market_sentiment: dict[str, Any] = Field(default_factory=dict)
    system_health: SystemHealthOut | None = None
    top_buy_candidates: list[ValidatedSignalOut] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)
    latest_strategy_plan: StrategyPlanSummaryOut | None = None
    open_alerts_summary: AlertSummaryOut | None = None
    latest_scheduler_run: SchedulerRunOut | None = None
    latest_operational_report: OperationalReportOut | None = None
    latest_optimization_run: OptimizationRunSummaryOut | None = None
    latest_scenario_run: ScenarioRunSummaryOut | None = None


class TechnicalAnalysisOut(BaseModel):
    asset: AssetOut
    latest_price: float | None
    indicators: dict[str, float] = Field(default_factory=dict)
    conditions: dict[str, bool] = Field(default_factory=dict)
    support_resistance: dict[str, float | None] = Field(default_factory=dict)
    subscores: dict[str, float] = Field(default_factory=dict)
    score: float
    signal: SignalType
    risk_level: str
    confidence: str
    reasons: list[dict[str, str]] = Field(default_factory=list)
    summaries: dict[str, str] = Field(default_factory=dict)
    technical_summary: str
    technical_score: float | None = None
    news_score: float = 0.0
    final_score: float | None = None
    news_sentiment_label: str | None = None
    news_impact_level: str | None = None
    news_count: int = 0
    latest_ml_prediction: dict[str, object] | None = None


class SeedSummaryOut(BaseModel):
    reset: bool
    assets_inserted: int
    price_rows_inserted: int
    signals_inserted: int
    portfolio_positions_inserted: int = 0
    simulated_orders_inserted: int = 0
    portfolio_snapshots_inserted: int = 0
    universe_assets_imported: int = 0
    core_universe_count: int = 0
    extended_universe_count: int = 0
    candidate_universe_count: int = 0
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


class BacktestResultOut(BaseModel):
    backtest_id: int
    summary: BacktestSummaryOut
    equity_curve: list[BacktestEquityPointOut]
    trades: list[BacktestTradeOut]
    final_positions: list[BacktestPositionOut]
    benchmark_comparison: BacktestBenchmarkComparisonOut


class MLTrainIn(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=120)
    model_type: MLModelType
    target_type: MLTargetType
    horizon_days: int = Field(default=14, ge=1, le=120)
    symbols: list[str] = Field(default_factory=list)
    benchmark_symbol: str = Field(default="SPY", min_length=1, max_length=24)
    test_size_time_percent: float = Field(default=25, ge=10, le=50)
    min_samples: int = Field(default=200, ge=20, le=100000)


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
    metrics: dict[str, object] = Field(default_factory=dict)
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
    explanation: dict[str, object] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    created_at: str | None = None


class MLTrainOut(BaseModel):
    model_id: int
    training_run: MLTrainingRunOut
    metrics: dict[str, object]
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


class UniverseAssetOut(BaseModel):
    id: int
    asset_id: int | None = None
    symbol: str
    name: str
    asset_type: str
    exchange: str | None = None
    currency: str
    country: str | None = None
    sector: str | None = None
    industry: str | None = None
    risk_level: str = "medium"
    universe_level: UniverseLevel
    is_active: bool
    is_watchlisted: bool
    is_portfolio_asset: bool
    refresh_priority: int
    refresh_frequency_days: int
    last_price_refresh_at: str | None = None
    last_signal_refresh_at: str | None = None
    last_news_refresh_at: str | None = None
    data_provider: str | None = None
    notes: str | None = None
    last_price: float | None = None
    daily_change_pct: float | None = None
    last_source: str | None = None
    provider: str | None = None
    is_real_data: bool = False
    last_price_date: str | None = None
    last_fetch_at: str | None = None
    score: float | None = None
    signal: SignalType | None = None
    confidence: str | None = None
    technical_summary: str | None = None
    ml_model_id: int | None = None
    ml_probability: float | None = None
    ml_confidence: str | None = None
    ml_label: str | None = None
    ml_target_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UniverseSummaryOut(BaseModel):
    total_assets: int
    core_count: int
    extended_count: int
    candidate_count: int
    active_count: int
    watchlist_count: int
    portfolio_count: int
    priced_assets_count: int
    refresh_candidates_count: int
    by_asset_type: dict[str, int] = Field(default_factory=dict)
    by_country: dict[str, int] = Field(default_factory=dict)
    by_exchange: dict[str, int] = Field(default_factory=dict)


class UniverseImportIn(BaseModel):
    file_name: str = Field(..., min_length=1, max_length=160)
    universe_level: UniverseLevel


class UniverseImportOut(BaseModel):
    file_name: str
    universe_level: UniverseLevel
    inserted: int
    updated: int
    skipped: int
    total_rows: int


class UniversePromoteIn(BaseModel):
    universe_level: UniverseLevel


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


SentimentLabel = Literal["POSITIVE", "NEGATIVE", "NEUTRAL"]
ImpactLevel = Literal["LOW", "MEDIUM", "HIGH"]


class NewsItemOut(BaseModel):
    id: int
    asset_id: int | None = None
    symbol: str | None = None
    provider: str | None = None
    title: str
    summary: str | None = None
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    sentiment_score: float = 0.0
    sentiment_label: SentimentLabel = "NEUTRAL"
    impact_level: ImpactLevel = "LOW"
    relevance_score: float = 0.0
    created_at: str | None = None


class NewsRefreshResultOut(BaseModel):
    symbol: str
    provider: str | None = None
    rows_inserted: int = 0
    rows_updated: int = 0
    used_cache: bool = False
    used_fallback: bool = False
    message: str


class NewsLatestOut(BaseModel):
    id: int
    title: str
    summary: str | None = None
    url: str | None = None
    source: str | None = None
    published_at: str | None = None
    sentiment_label: SentimentLabel = "NEUTRAL"
    sentiment_score: float = 0.0
    impact_level: ImpactLevel = "LOW"
    relevance_score: float = 0.0


class NewsSentimentSummaryOut(BaseModel):
    symbol: str
    lookback_days: int
    news_count: int
    average_sentiment_score: float
    sentiment_label: SentimentLabel
    impact_level: ImpactLevel
    positive_count: int
    negative_count: int
    neutral_count: int
    latest_news: list[NewsLatestOut] = Field(default_factory=list)


class NewsProviderStatusOut(BaseModel):
    provider: str
    enabled: bool
    api_key_configured: bool
    daily_limit: int
    calls_today: int
    supports: list[str] = Field(default_factory=list)


class NewsDailyUsageOut(BaseModel):
    provider: str
    usage_date: str
    calls_count: int
    daily_limit: int


class NewsStatusOut(BaseModel):
    enable_real_news: bool
    provider_status: list[NewsProviderStatusOut]
    daily_usage: NewsDailyUsageOut
    cache_status: dict[str, int]
    last_refresh: str | None = None
    news_sentiment_weight: int
    news_cache_ttl_hours: int


DashboardOut.model_rebuild()
