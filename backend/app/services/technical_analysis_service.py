from __future__ import annotations

import sqlite3

import pandas as pd

from backend.app.models import TechnicalAnalysisOut
from backend.app.services.assets_service import get_asset_by_symbol
from backend.app.services.scoring_engine import ScoringEngine


def get_technical_analysis(connection: sqlite3.Connection, symbol: str) -> TechnicalAnalysisOut | None:
    asset = get_asset_by_symbol(connection, symbol)
    if asset is None:
        return None

    rows = connection.execute(
        """
        SELECT date, open, high, low, close, adjusted_close, volume, source
        FROM price_history
        WHERE asset_id = ?
        ORDER BY date ASC
        """,
        (asset.id,),
    ).fetchall()
    if not rows:
        return None

    price_frame = pd.DataFrame([dict(row) for row in rows])
    score = ScoringEngine().score_prices(
        price_frame,
        asset_id=asset.id,
        symbol=asset.symbol,
        risk_level=asset.risk_level,
    )

    return TechnicalAnalysisOut(
        asset=asset,
        latest_price=score["latest_close"],
        indicators=score["indicators"],
        conditions=score["conditions"],
        support_resistance=score["support_resistance"],
        subscores=score["subscores"],
        score=score["score"],
        signal=score["signal"],
        risk_level=score["risk_level"],
        confidence=score["confidence"],
        reasons=score["reasons"],
        summaries=score["summaries"],
        technical_summary=score["technical_summary"],
    )
