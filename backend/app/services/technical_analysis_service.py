from __future__ import annotations

import sqlite3

import pandas as pd

from backend.app.config import get_settings
from backend.app.models import TechnicalAnalysisOut
from backend.app.services.assets_service import get_asset_by_symbol
from backend.app.services.scoring_engine import ScoringEngine
from backend.app.services.sentiment_engine import aggregate_news_sentiment


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
    news_summary = aggregate_news_sentiment(connection, asset.symbol, lookback_days=7)
    if news_summary["news_count"] == 0:
        news_score = 0.0
    else:
        weight = get_settings().news_sentiment_weight
        news_score = float(news_summary["average_sentiment_score"]) * weight
        news_score = max(-weight, min(weight, news_score))
    final_score = round(max(0.0, min(100.0, float(score["score"]) + news_score)), 2)

    return TechnicalAnalysisOut(
        asset=asset,
        latest_price=score["latest_close"],
        indicators=score["indicators"],
        conditions=score["conditions"],
        support_resistance=score["support_resistance"],
        subscores=score["subscores"],
        score=score["score"],
        technical_score=score["score"],
        news_score=round(news_score, 2),
        final_score=final_score,
        news_sentiment_label=news_summary["sentiment_label"],
        news_impact_level=news_summary["impact_level"],
        signal=score["signal"],
        risk_level=score["risk_level"],
        confidence=score["confidence"],
        reasons=score["reasons"],
        summaries=score["summaries"],
        technical_summary=score["technical_summary"],
    )
