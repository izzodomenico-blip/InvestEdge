from __future__ import annotations

import sqlite3

from backend.app.models import PortfolioPositionOut
from backend.app.services.portfolio_engine import PortfolioEngine


def list_portfolio(connection: sqlite3.Connection) -> list[PortfolioPositionOut]:
    return PortfolioEngine().list_positions(connection)


def portfolio_value(connection: sqlite3.Connection) -> float:
    return PortfolioEngine().get_summary(connection).total_value
