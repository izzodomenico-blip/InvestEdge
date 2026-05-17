from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AssetType = Literal["stock", "etf", "crypto", "bond", "bond_etf"]
SignalType = Literal["BUY", "HOLD", "REDUCE", "SELL"]
RiskLevel = Literal["low", "medium", "high", "very_high"]


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
    rsi_14: float | None = None
    macd_line: float | None = None
    macd_signal: float | None = None


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
    name: str
    asset_type: str
    quantity: float
    average_price: float
    currency: str
    market_value: float


class SignalOut(BaseModel):
    id: int
    asset_id: int
    symbol: str
    signal: SignalType
    score: float
    risk_level: str | None = None
    technical_summary: str | None = None
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
    latest_signals: list[SignalOut]
    top_assets: list[AssetOut] = Field(default_factory=list)
    weakest_assets: list[AssetOut] = Field(default_factory=list)


class SeedSummaryOut(BaseModel):
    reset: bool
    assets_inserted: int
    price_rows_inserted: int
    signals_inserted: int
    started_at: str
    completed_at: str
