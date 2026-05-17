from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AssetType = Literal["stock", "etf", "crypto", "bond", "bond_etf"]
SignalType = Literal["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"]
RiskLevel = Literal["low", "medium", "high", "very_high"]
OrderType = Literal["BUY", "SELL"]
BacktestStrategy = Literal["SCORE_THRESHOLD", "BUY_AND_HOLD", "TOP_N_SCORE"]
RebalanceFrequency = Literal["DAILY", "WEEKLY", "MONTHLY"]


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
    score: float | None = None
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


class BacktestResultOut(BaseModel):
    backtest_id: int
    summary: BacktestSummaryOut
    equity_curve: list[BacktestEquityPointOut]
    trades: list[BacktestTradeOut]
    final_positions: list[BacktestPositionOut]
    benchmark_comparison: BacktestBenchmarkComparisonOut
