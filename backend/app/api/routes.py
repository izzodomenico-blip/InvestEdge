from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from backend.app.database import db_session
from backend.app.models import AssetCreate, AssetOut, DashboardOut, PortfolioPositionOut, SignalOut
from backend.app.services.assets_service import create_asset, list_assets
from backend.app.services.dashboard_service import get_dashboard
from backend.app.services.portfolio_service import list_portfolio
from backend.app.services.signals_service import list_signals

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "investedge-api"}


@router.get("/assets", response_model=list[AssetOut])
def get_assets() -> list[AssetOut]:
    with db_session() as connection:
        return list_assets(connection)


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


@router.get("/portfolio", response_model=list[PortfolioPositionOut])
def get_portfolio() -> list[PortfolioPositionOut]:
    with db_session() as connection:
        return list_portfolio(connection)


@router.get("/signals", response_model=list[SignalOut])
def get_signals() -> list[SignalOut]:
    with db_session() as connection:
        return list_signals(connection)


@router.get("/dashboard", response_model=DashboardOut)
def dashboard() -> DashboardOut:
    with db_session() as connection:
        return get_dashboard(connection)
