from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.lab.contracts import DataMode, Timeframe
from backend.app.lab.features import FEATURE_COLUMNS_V1
from backend.app.lab.score_v1 import SUBSCORE_COLUMNS
from backend.app.models.market_data import (
    EffectiveObservationQuality,
    SourceObservationQuality,
)
from backend.app.services.provider_budget_service import (
    AvailabilityReason,
    AvailabilityState,
    BudgetWindow,
    ProviderCapability,
    RequestOutcome,
)

AssetType = Literal["stock", "etf", "crypto", "bond", "bond_etf", "macro", "bond_proxy"]
InstrumentType = Literal[
    "STOCK",
    "ETF",
    "BOND",
    "ETC",
    "ETN",
    "CRYPTO",
    "FX",
    "INDEX",
    "RATE",
    "MACRO",
    "UNKNOWN",
]
AssetClass = Literal[
    "EQUITY",
    "FUND",
    "FIXED_INCOME",
    "COMMODITY",
    "CRYPTO",
    "FX",
    "REFERENCE",
    "UNKNOWN",
]
QualityTier = Literal["QUALIFIED", "OBSERVABLE", "REFERENCE_ONLY"]
QualityReason = Literal[
    "REFERENCE_INSTRUMENT",
    "AMBIGUOUS_IDENTITY",
    "MISSING_PRIMARY_ID",
    "MISSING_LISTING_METADATA",
    "UNRESOLVED_CRITICAL_REJECTION",
    "NO_VALID_OBSERVATION",
    "STALE_OBSERVATION",
    "INSUFFICIENT_HISTORY",
    "PROVIDER_DIVERGENCE",
    "COMPATIBLE_FALLBACK_IN_USE",
    "VALIDATED_OBSERVABLE",
    "QUALIFICATION_RULES_MET",
]
IdentifierScheme = Literal[
    "ISIN",
    "FIGI",
    "OPENFIGI_TICKER",
    "COINGECKO_ID",
    "FRED_SERIES_ID",
    "ECB_SERIES_KEY",
]
CatalogEntryStatus = Literal["ACCEPTED", "REJECTED", "AMBIGUOUS"]
CatalogReason = Literal[
    "VALID_ISIN",
    "INVALID_ISIN",
    "MISSING_ISIN",
    "MISSING_NAME",
    "DUPLICATE_IN_SNAPSHOT",
    "UNSUPPORTED_ROW",
]
CatalogSnapshotStatus = Literal["COMPLETE", "FAILED"]
CatalogFailureReason = Literal[
    "DOWNLOAD_FAILED",
    "PAYLOAD_TOO_LARGE",
    "PARSER_ERROR",
    "EMPTY_CATALOG",
]
ResolutionStatus = Literal["RESOLVED", "AMBIGUOUS", "UNMATCHED", "REJECTED"]
ResolutionReason = Literal[
    "EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE",
    "MULTIPLE_COMPATIBLE_CANDIDATES",
    "NO_PROVIDER_MATCH",
    "TYPE_MISMATCH",
    "CURRENCY_MISMATCH",
    "MISSING_CURRENCY",
    "MISSING_VENUE",
    "MISSING_TIMEZONE",
    "INVALID_PROVIDER_PAYLOAD",
]
ListingMetadataSource = Literal[
    "OFFICIAL_VENUE",
    "ISSUER_FACTSHEET",
    "LEGACY_ACTIVE_ASSET",
]
SignalType = Literal["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"]
RiskLevel = Literal["low", "medium", "high", "very_high"]
OrderType = Literal["BUY", "SELL"]
TaxCategory = Literal["standard", "government_bond", "crypto", "euro_emt"]
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
    tax_category: TaxCategory | None = None
    exchange: str | None = Field(default=None, max_length=80)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    sector: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    risk_level: RiskLevel = "medium"
    isin: str | None = Field(default=None, max_length=20)


class AssetOut(AssetCreate):
    id: int
    tax_category: TaxCategory
    last_price: float | None = None
    fx_rate_to_base: float | None = None
    last_price_base: float | None = None
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
    signal_data_mode: DataMode | None = None
    score_unavailable_reason: str | None = None


class AssetDependencyCountsOut(BaseModel):
    price_history: int = Field(..., ge=0)
    portfolio_positions: int = Field(..., ge=0)
    simulated_orders: int = Field(..., ge=0)
    signals: int = Field(..., ge=0)
    news_items: int = Field(..., ge=0)


class AssetDeleteOut(BaseModel):
    deleted: bool
    symbol: str
    purged: bool
    dependency_counts: AssetDependencyCountsOut


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
    listing_id: int | None = None
    observation_id: int | None = None
    provider_observed_at: str | None = None
    ingested_at: str | None = None
    timezone: str | None = None
    session: str | None = None
    currency: str | None = None
    delay_seconds: int | None = None
    source_quality: SourceObservationQuality | None = None
    effective_quality: EffectiveObservationQuality | None = None
    fallback_reason: str | None = None
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
    name: str | None = None
    isin: str | None = None
    asset_type: str
    quantity: float
    average_price: float
    average_price_base: float
    invested_amount: float
    invested_amount_base: float
    current_price: float
    current_value: float
    current_value_base: float
    realized_pnl: float
    realized_pnl_base: float
    unrealized_pnl: float
    unrealized_pnl_base: float
    unrealized_pnl_percent: float
    weight_percent: float
    currency: str
    fx_rate_to_base: float
    base_currency: Literal["EUR"] = "EUR"
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
    data_mode: DataMode | None = None


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
    confirmation_token: str | None = None


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
    confirmation_token: str


class ImportStatusOut(BaseModel):
    enabled: bool
    configured: bool
    csv_url_set: bool


class MLTrainIn(BaseModel):
    data_mode: DataMode = "REAL"
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
    pipeline_version: str | None = None
    data_mode: DataMode | None = None
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
    pipeline_version: str | None = None
    data_mode: DataMode | None = None
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
    pipeline_version: str | None = None
    data_mode: DataMode | None = None
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
    outcome: Literal["LOSS", "GAIN", "UNCHANGED"]


class ScenarioClassImpactOut(BaseModel):
    asset_class: str
    current_value: float
    stressed_value: float
    absolute_impact: float
    shock_percent: float
    outcome: Literal["LOSS", "GAIN", "UNCHANGED"]


class ScenarioRunOut(BaseModel):
    scenario_type: str
    scenario_label: str
    current_value: float
    stressed_value: float
    cash: float
    absolute_impact: float
    percentage_impact: float
    outcome: Literal["LOSS", "GAIN", "UNCHANGED"]
    impact_label: str
    absolute_loss: float
    percentage_loss: float
    risk_level: str
    asset_impacts: list[ScenarioAssetImpactOut]
    class_impacts: list[ScenarioClassImpactOut]
    mitigation: list[str]
    base_currency: Literal["EUR"] = "EUR"


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


class TaxRealizedEventOut(BaseModel):
    symbol: str
    asset_type: str | None = None
    tax_category: TaxCategory
    category: str
    open_side: OrderType
    close_side: OrderType
    open_date: str
    realization_date: str
    sell_date: str | None = None
    tax_year: int
    quantity: float
    currency: str
    base_currency: Literal["EUR"] = "EUR"
    open_value_native: float
    close_value_native: float
    gain_native: float
    open_value_base: float
    close_value_base: float
    gain_base: float
    proceeds: float
    cost_basis: float
    gain: float
    applied_rate: float
    rate: float
    holding_days: int


class TaxLossBucketOut(BaseModel):
    tax_category: TaxCategory
    origin_year: int
    expires_after_year: int
    remaining: float


class TaxYearSummaryOut(BaseModel):
    tax_year: int
    total_gains: float
    total_losses: float
    net_realized: float
    current_year_losses_used: float
    carryforward_used: float
    carryforward_expired: float
    carryforward_remaining: float
    carryforward_buckets: list[TaxLossBucketOut]
    tax_due: float


class TaxOpenLotOut(BaseModel):
    symbol: str
    asset_type: str | None = None
    tax_category: TaxCategory
    open_side: OrderType
    currency: str
    base_currency: Literal["EUR"] = "EUR"
    quantity: float
    open_value_native: float
    open_value_base: float
    current_value_native: float | None = None
    current_value_base: float | None = None
    unrealized_gain_native: float | None = None
    unrealized_gain_base: float | None = None
    cost_basis: float | None = None
    current_value: float | None = None
    unrealized_gain: float | None = None


class TaxRuleOut(BaseModel):
    tax_category: TaxCategory
    from_year: int
    rate: float
    source_id: str


class TaxSourceOut(BaseModel):
    id: str
    title: str
    url: str


class BackupOut(BaseModel):
    file: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None
    created: bool = True
    reason: str | None = None


class ReportSummaryOut(BaseModel):
    positions_count: int
    orders_count: int
    realized_events_count: int
    portfolio_value: float
    total_pnl: float
    estimated_tax_due: float


class TaxReportOut(BaseModel):
    base_currency: Literal["EUR"] = "EUR"
    standard_rate: float
    bond_rate: float
    lot_method: str
    total_tax_due: float
    total_realized_net: float
    loss_carryforward: float
    loss_carryforward_buckets: list[TaxLossBucketOut]
    carryforward_note: str
    tax_rules: list[TaxRuleOut]
    sources: list[TaxSourceOut]
    classification_warnings: list[str]
    years: list[TaxYearSummaryOut]
    events: list[TaxRealizedEventOut]
    open_lots: list[TaxOpenLotOut]
    disclaimer: str


class ImportApplyOut(BaseModel):
    imported: int
    created_assets: int
    rows_invalid: int
    errors: list[str]
    portfolio_value: float
    initial_equity_base: float
    current_cash_base: float
    base_currency: Literal["EUR"] = "EUR"


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
    data_mode: DataMode | None = None


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
    confirm_reset: Literal["RESET_PORTFOLIO"] | None = None


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
    base_currency: Literal["EUR"] = "EUR"
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
    # Consente la vendita allo scoperto (short): un SELL puo' portare la quantita'
    # sotto zero. Default False per evitare short accidentali col normale "Vendi".
    allow_short: bool = False


class SimulatedOrderOut(BaseModel):
    id: int
    asset_id: int
    symbol: str
    order_type: OrderType
    quantity: float
    price: float
    fees: float
    fees_base: float
    gross_amount: float
    gross_amount_base: float
    net_amount: float
    net_amount_base: float
    currency: str
    fx_rate_to_base: float
    base_currency: Literal["EUR"] = "EUR"
    order_date: str
    note: str | None = None
    strategy_tag: str | None = None


class OrderSimulationOut(BaseModel):
    order: SimulatedOrderOut
    updated_position: PortfolioPositionOut | None
    updated_portfolio_summary: PortfolioSummaryOut
    warnings: list[RiskWarningOut]


class PortfolioSnapshotOut(BaseModel):
    base_currency: Literal["EUR"] = "EUR"
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


# Segnali valutabili dal laboratorio: score, sottopunteggi e feature `features-v1` (come il feature store).
BACKTEST_SIGNAL_NAMES: frozenset[str] = frozenset({"score", *SUBSCORE_COLUMNS, *FEATURE_COLUMNS_V1})
_ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


class _BacktestSettingsIn(BaseModel):
    """Campi comuni di run, confronto e walk-forward del motore v1 (SP1 Task 10).

    Via `fee_percent` (un campo legacy inviato viene ignorato): profilo costi Trade Republic con i default delle
    impostazioni per i campi nulli. Un solo `data_mode` per run (REAL di default).
    """

    symbols: list[str] = Field(..., min_length=1)
    initial_cash: float = Field(default=100000, gt=0)
    start_date: str = Field(..., pattern=_ISO_DATE)
    end_date: str = Field(..., pattern=_ISO_DATE)
    benchmark_symbol: str = Field(default="SPY", min_length=1, max_length=24)
    buy_threshold: float = Field(default=70, ge=0, le=100)
    sell_threshold: float = Field(default=40, ge=0, le=100)
    max_asset_weight: float = Field(default=0.15, gt=0, le=1)
    stop_loss_percent: float | None = Field(default=8, gt=0, le=100)
    take_profit_percent: float | None = Field(default=25, gt=0, le=500)
    rebalance_frequency: RebalanceFrequency = "WEEKLY"
    top_n: int | None = Field(default=5, ge=1, le=25)
    data_mode: DataMode = "REAL"
    signal_name: str = "score"
    signal_timeframe: Timeframe = "D"
    commission_eur: float | None = Field(default=None, ge=0, le=100)
    cost_bps_equity: float | None = Field(default=None, ge=0, le=1000)
    cost_bps_crypto: float | None = Field(default=None, ge=0, le=1000)
    fractional_shares: bool | None = None
    min_trade_eur: float | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("symbols")
    @classmethod
    def _normalize_symbols(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(symbol.strip().upper() for symbol in value if symbol.strip()))
        if not normalized:
            raise ValueError("Seleziona almeno un asset.")
        return normalized

    @field_validator("signal_name")
    @classmethod
    def _known_signal(cls, value: str) -> str:
        if value not in BACKTEST_SIGNAL_NAMES:
            raise ValueError("Segnale non disponibile nel laboratorio.")
        return value

    @field_validator("start_date", "end_date")
    @classmethod
    def _valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def _ordered_period(self) -> _BacktestSettingsIn:
        if self.end_date < self.start_date:
            raise ValueError("La data fine deve essere uguale o successiva alla data inizio.")
        return self


class BacktestRunIn(_BacktestSettingsIn):
    name: str = Field(..., min_length=1, max_length=120)
    strategy_name: BacktestStrategy


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
    fee_percent: float | None = None  # solo motore v0; i run v1 usano il profilo costi
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
    # Campi additivi del motore v1 (SP1 Task 10); i run `v0` ("motore precedente") li hanno nulli o vuoti.
    engine_version: str = "v0"
    data_mode: DataMode | None = None
    signal_name: str | None = None
    signal_timeframe: Timeframe | None = None
    cost_profile: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    excluded: dict[str, str] = Field(default_factory=dict)
    commission_eur: float | None = None
    spread_cost_eur: float | None = None
    turnover: float | None = None
    exposure: float | None = None
    fingerprint: str | None = None
    benchmark_snapshot_status: Literal["FROZEN", "UNAVAILABLE", "NOT_RECORDED"] = "NOT_RECORDED"


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
    commission: float | None = None   # v1: commissione dell'ordine (uguale a `fees`)
    spread_cost: float | None = None  # v1: costo per lato (spread e slippage) incluso nel prezzo


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


class BacktestCompareIn(_BacktestSettingsIn):
    name: str = Field(default="Confronto strategie", min_length=1, max_length=120)
    strategy_names: list[BacktestStrategy] = Field(..., min_length=2, max_length=3)

    @field_validator("strategy_names")
    @classmethod
    def _distinct_strategies(cls, value: list[str]) -> list[str]:
        distinct = list(dict.fromkeys(value))
        if len(distinct) < 2:
            raise ValueError("Seleziona almeno due strategie diverse.")
        return distinct


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
    """Walk-forward vero (SP1 Task 11): finestre mobili in sedute del calendario dell'universo.

    Default dalle impostazioni (`LAB_WF_IS_SESSIONS`, `LAB_WF_OOS_SESSIONS`); via `folds` del contratto a fold
    (un campo legacy inviato viene ignorato).
    """

    is_sessions: int | None = Field(default=None, ge=2, le=10_000)
    oos_sessions: int | None = Field(default=None, ge=1, le=10_000)


class WalkForwardParamsOut(BaseModel):
    name: str
    buy_threshold: float
    sell_threshold: float
    max_asset_weight: float
    top_n: int
    rebalance_frequency: str


class WalkForwardWindowOut(BaseModel):
    index: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    chosen: WalkForwardParamsOut
    is_sharpe: float | None = None  # annualizzato (x sqrt(252)) sui soli rendimenti in-sample della scelta


class WalkForwardMetricsOut(BaseModel):
    """Metriche della simulazione fuori campione, nelle unita di `BacktestSummaryOut` (importi in EUR)."""

    start_date: str
    end_date: str
    total_return_percent: float
    cagr: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float
    win_rate: float
    total_trades: int
    turnover: float
    exposure: float
    commission_eur: float
    spread_cost_eur: float
    final_value: float
    benchmark_return_percent: float = 0
    alpha_vs_benchmark: float = 0


class DeflatedSharpeOut(BaseModel):
    """DSR di Bailey e Lopez de Prado: Sharpe giornalieri (non annualizzati), curtosi non in eccesso."""

    dsr: float
    sr: float
    sr0: float
    n_trials: int
    n_obs: int
    skew: float
    kurtosis: float


class WalkForwardOut(BaseModel):
    """Risultato del job `WALK_FORWARD` (spec SP1 §8.3-§8.5).

    Sharpe di finestre, media in-sample, OOS e degrado annualizzati (x sqrt(252), come `sharpe_ratio` dei
    backtest); `dsr` e `n_trials` (configurazioni distinte della famiglia) solo in REAL, null in DEMO.
    """

    strategy_name: str
    data_mode: DataMode
    window_is_sessions: int
    window_oos_sessions: int
    windows: list[WalkForwardWindowOut]
    grid_size: int
    is_sharpe_mean: float | None = None
    oos_sharpe: float | None = None
    degradation: float | None = None
    oos_metrics: WalkForwardMetricsOut
    oos_sessions: int
    dsr: DeflatedSharpeOut | None = None
    n_trials: int | None = None
    excluded: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ActionItemOut(BaseModel):
    type: ActionType
    priority: ActionPriority
    symbol: str | None = None
    title: str
    reason: str
    signal: str | None = None
    score: float | None = None
    weight_percent: float | None = None
    data_mode: DataMode | None = None


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
    confirmation_token: str | None = Field(default=None, min_length=64, max_length=64)


class AllocationItemOut(BaseModel):
    symbol: str
    name: str
    weight_percent: float
    capital: float
    price: float | None = None
    price_base: float | None = None
    actual_cost_base: float
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
    confirmation_token: str


class ProviderBudgetWindowOut(BaseModel):
    window: BudgetWindow
    limit: int | None
    used: int
    remaining: int | None
    reset_at: datetime


class DataProviderStatusOut(BaseModel):
    provider: str
    enabled: bool
    api_key_configured: bool
    daily_limit: int
    calls_today: int
    supports: list[str] = Field(default_factory=list)
    # Estensioni additive: nessuna key, URL, endpoint o fingerprint.
    capabilities: list[ProviderCapability] = Field(default_factory=list)
    budget_windows: list[ProviderBudgetWindowOut] = Field(default_factory=list)
    cooldown_until: datetime | None = None
    availability_state: AvailabilityState | None = None
    availability_reason: AvailabilityReason | None = None
    last_outcome: RequestOutcome | None = None
    last_outcome_at: datetime | None = None


class ApiUsageOut(BaseModel):
    provider: str
    usage_date: str
    calls_count: int
    daily_limit: int
    updated_at: str | None = None


class CoverageCount(BaseModel):
    key: str
    total: int
    resolved: int
    qualified: int
    observable: int
    reference_only: int


class ProviderCoverageOut(BaseModel):
    provider: str
    capability: ProviderCapability
    eligible_listings: int
    unmapped_listings: int
    mapped_listings: int
    fresh_listings: int
    stale_listings: int
    missing_observation_listings: int
    rejected_observations: int
    quality_counts: dict[str, int]
    delay_bucket_counts: dict[str, int]
    latest_provider_observed_at: datetime | None
    latest_ingested_at: datetime | None
    attribution: str | None


FxCoverageStatus = Literal["FRESH", "STALE", "MISSING"]
FxRateDirection = Literal["DIRECT", "INVERSE"]


class FxCoverageOut(BaseModel):
    from_currency: str
    to_currency: Literal["EUR"]
    status: FxCoverageStatus
    direction: FxRateDirection | None
    provider: str | None
    # Pydantic serializza Decimal come stringa decimale JSON (mai binary float) o null.
    rate_to_eur: Decimal | None
    observed_at: datetime | None
    ingested_at: datetime | None
    age_seconds: int | None
    quality: str | None


class DataCoverageOut(BaseModel):
    measured_at: datetime
    latest_catalog_snapshot_id: int | None
    latest_catalog_retrieved_at: datetime | None
    latest_catalog_sha256: str | None
    parse_accepted_entries: int
    parse_ambiguous_entries: int
    parse_rejected_entries: int
    parse_denominator: int
    resolution_resolved_entries: int
    resolution_ambiguous_entries: int
    resolution_unmatched_entries: int
    resolution_rejected_entries: int
    resolution_unprocessed_entries: int
    resolution_denominator: int
    resolved_percent: float
    tier_denominator: int
    tier_counts: dict[QualityTier, int]
    tier_percentages: dict[QualityTier, float]
    trade_republic_denominator: int
    trade_republic_status_counts: dict[str, int]
    trade_republic_verified_percent: float
    by_asset_class: list[CoverageCount]
    by_market: list[CoverageCount]
    rejection_reasons: dict[str, int]
    provider_coverage: list[ProviderCoverageOut]
    fx_currency_denominator: int
    fx_fresh_currencies: int
    fx_stale_currencies: int
    fx_missing_currencies: int
    fx_coverage: list[FxCoverageOut]
    pending_refresh: int
    budget_deferred: int


class DataCoverageSummaryOut(BaseModel):
    """Sintesi di `DataCoverageOut` per `/data/status`, con gli stessi denominatori espliciti."""

    measured_at: datetime
    latest_catalog_snapshot_id: int | None
    latest_catalog_retrieved_at: datetime | None
    resolution_denominator: int
    resolved_percent: float
    tier_denominator: int
    tier_percentages: dict[QualityTier, float]
    trade_republic_denominator: int
    trade_republic_verified_percent: float
    fx_currency_denominator: int
    fx_fresh_currencies: int
    fx_stale_currencies: int
    fx_missing_currencies: int
    pending_refresh: int
    budget_deferred: int


class DataStatusOut(BaseModel):
    enable_real_data: bool
    provider_status: list[DataProviderStatusOut]
    api_usage: list[ApiUsageOut]
    cache_stats: dict[str, int]
    global_last_update: str | None = None
    data_mode: Literal["SEED", "MIXED", "REAL"]
    coverage_summary: DataCoverageSummaryOut | None = None


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


class RefreshRequestOut(BaseModel):
    refresh_request_id: int


class CatalogEodEnqueueResult(BaseModel):
    enqueued: int
    next_cursor: int | None


FxRefreshStatus = Literal["UPDATED", "NOT_MODIFIED"]


class FxRefreshResult(BaseModel):
    from_currency: str
    to_currency: Literal["EUR"]
    provider: Literal["ecb"]
    status: FxRefreshStatus
    rows_written: int
    observed_at: datetime | None
    ingested_at: datetime | None


class CatalogIngestResultOut(BaseModel):
    snapshot_id: int
    content_sha256: str = Field(..., min_length=64, max_length=64)
    accepted: int = Field(..., ge=0)
    rejected: int = Field(..., ge=0)
    ambiguous: int = Field(..., ge=0)
    unchanged: bool


class ResolutionResultOut(BaseModel):
    catalog_entry_id: int
    status: ResolutionStatus
    reason_code: ResolutionReason
    instrument_id: int | None = None
    listing_id: int | None = None
    candidate_count: int = Field(..., ge=0)
    evidence_hash: str = Field(..., min_length=64, max_length=64)


class ListingMetadataPreviewIn(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=64)
    mic: str = Field(..., min_length=1, max_length=16)
    venue_name: str = Field(..., min_length=1, max_length=160)
    currency: str = Field(..., min_length=1, max_length=8)
    timezone: str = Field(..., min_length=1, max_length=128)
    instrument_type: InstrumentType
    source: ListingMetadataSource
    observed_at: datetime
    evidence_hash: str = Field(..., min_length=1, max_length=256)


class ListingMetadataApplyIn(ListingMetadataPreviewIn):
    confirmation_token: str = Field(..., min_length=64, max_length=64)


class ListingMetadataPreviewOut(BaseModel):
    catalog_entry_id: int
    normalized_ticker: str
    normalized_mic: str
    normalized_currency: str
    normalized_timezone: str
    current_version: int | None = None
    confirmation_token: str = Field(..., min_length=64, max_length=64)


TradeRepublicListingStatus = Literal["NEVER_SEEN", "CATALOGED", "VERIFIED", "UNAVAILABLE"]
TradeRepublicAttestationStatus = Literal["VERIFIED", "UNAVAILABLE"]
TradeRepublicAttestationSource = Literal["MANUAL_OFFICIAL_APP_CHECK", "OFFICIAL_SUPPORT_NOTICE"]
ProviderSymbolProvider = Literal["stooq", "finnhub", "coingecko"]


class InstrumentListItem(BaseModel):
    instrument_id: int
    canonical_name: str
    instrument_type: InstrumentType
    asset_class: AssetClass
    quality_tier: QualityTier
    quality_reasons: list[str]
    primary_identifier_scheme: IdentifierScheme | None
    primary_identifier: str | None
    listing_id: int | None
    ticker: str | None
    mic: str | None
    venue_name: str | None
    currency: str | None
    timezone: str | None
    trade_republic_status: TradeRepublicListingStatus
    trade_republic_cataloged_at: datetime | None
    trade_republic_verified_at: datetime | None
    observation_quality: EffectiveObservationQuality | None
    observed_at: datetime | None


class InstrumentSearchOut(BaseModel):
    items: list[InstrumentListItem]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
    offset: int = Field(..., ge=0)
    catalog_snapshot_id: int | None


class InstrumentIdentifierOut(BaseModel):
    scheme: IdentifierScheme
    value: str
    sources: list[str]
    first_observed_at: datetime
    last_observed_at: datetime


class InstrumentListingOut(BaseModel):
    listing_id: int
    ticker: str
    mic: str | None
    venue_name: str | None
    currency: str
    timezone: str | None
    resolution_status: ResolutionStatus
    trade_republic_status: TradeRepublicListingStatus


class InstrumentDetailOut(InstrumentListItem):
    identifiers: list[InstrumentIdentifierOut]
    listings: list[InstrumentListingOut]


class ProviderSymbolPreviewIn(BaseModel):
    provider: ProviderSymbolProvider
    provider_symbol: str = Field(..., min_length=1, max_length=128)
    capability: ProviderCapability
    source: str = Field(..., min_length=1, max_length=64)
    observed_at: datetime
    expected_currency: str = Field(..., min_length=1, max_length=8)
    evidence_hash: str = Field(..., min_length=1, max_length=256)


class ProviderSymbolPreviewOut(BaseModel):
    listing_id: int
    normalized_provider_symbol: str
    current_version: int | None
    confirmation_token: str = Field(..., min_length=64, max_length=64)


class ProviderSymbolApplyIn(ProviderSymbolPreviewIn):
    confirmation_token: str = Field(..., min_length=64, max_length=64)


class ProviderSymbolApplyOut(BaseModel):
    listing_id: int
    provider: str
    capability: ProviderCapability
    normalized_provider_symbol: str
    version: int = Field(..., ge=1)
    status: Literal["VERIFIED"]


class TradeRepublicAttestationPreviewIn(BaseModel):
    status: TradeRepublicAttestationStatus
    source: TradeRepublicAttestationSource
    observed_at: datetime
    evidence_hash: str = Field(..., min_length=1, max_length=256)


class TradeRepublicAttestationPreviewOut(BaseModel):
    listing_id: int
    current_status: TradeRepublicListingStatus
    current_version: int | None
    confirmation_token: str = Field(..., min_length=64, max_length=64)


class TradeRepublicAttestationApplyIn(TradeRepublicAttestationPreviewIn):
    confirmation_token: str = Field(..., min_length=64, max_length=64)


class TradeRepublicAttestationOut(BaseModel):
    listing_id: int
    status: TradeRepublicAttestationStatus
    source: TradeRepublicAttestationSource
    observed_at: datetime
    evidence_hash: str = Field(..., min_length=64, max_length=64)
    version: int = Field(..., ge=1)
