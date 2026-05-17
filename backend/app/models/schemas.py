from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AssetType = Literal["stock", "etf", "crypto", "bond", "bond_etf"]
SignalType = Literal["BUY", "HOLD", "REDUCE", "SELL"]


class AssetCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=24)
    name: str = Field(..., min_length=1, max_length=160)
    asset_type: AssetType
    exchange: str | None = Field(default=None, max_length=80)
    currency: str = Field(default="USD", min_length=3, max_length=8)


class AssetOut(AssetCreate):
    id: int


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
    rationale: str | None
    generated_at: str


class DashboardOut(BaseModel):
    assets_count: int
    positions_count: int
    portfolio_value: float
    signals_count: int
    latest_signals: list[SignalOut]
