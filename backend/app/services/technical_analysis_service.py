from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from backend.app.lab.contracts import LabError
from backend.app.lab.series import load_series, preferred_data_mode
from backend.app.models import TechnicalAnalysisOut
from backend.app.services.assets_service import get_asset_by_symbol
from backend.app.services.scoring_engine import ScoringEngine
from backend.app.services.sentiment_engine import aggregate_news_sentiment
from backend.app.services.signals_service import (
    informative_news_score,
    insufficient_history_message,
    latest_segment_bars,
)


def get_technical_analysis(
    connection: sqlite3.Connection,
    symbol: str,
    now: datetime | None = None,
) -> TechnicalAnalysisOut | None:
    """Score v1 dell'ultima barra del segmento corrente, nella serie del segnale (REAL se esiste, altrimenti DEMO).

    Serie REAL senza warm-up completo -> `LabError("INSUFFICIENT_REAL_HISTORY")`, mai ripiego sul seed.
    `final_score = score`; la correzione news resta informativa in `news_score`.
    """
    asset = get_asset_by_symbol(connection, symbol)
    if asset is None:
        return None
    data_mode = preferred_data_mode(connection, asset.id)
    series = load_series(connection, asset.id, data_mode) if data_mode is not None else None
    if series is None:
        return None
    bars = latest_segment_bars(series, (now or datetime.now(UTC)).astimezone(UTC).date())
    if bars.empty:
        return None

    score = ScoringEngine().score_prices(
        bars,
        asset_id=asset.id,
        symbol=asset.symbol,
        risk_level=asset.risk_level,
    )
    if not score["warmup_complete"]:
        if data_mode == "REAL":
            raise LabError("INSUFFICIENT_REAL_HISTORY", insufficient_history_message(len(bars)))
        return None
    news_summary = aggregate_news_sentiment(connection, asset.symbol, lookback_days=7)

    return TechnicalAnalysisOut(
        asset=asset,
        latest_price=score["latest_close"],
        indicators=score["indicators"],
        conditions=score["conditions"],
        support_resistance=score["support_resistance"],
        subscores=score["subscores"],
        score=score["score"],
        technical_score=score["score"],
        news_score=round(informative_news_score(news_summary), 2),
        final_score=score["score"],
        news_sentiment_label=news_summary["sentiment_label"],
        news_impact_level=news_summary["impact_level"],
        signal=score["signal"],
        risk_level=score["risk_level"],
        confidence=score["confidence"],
        reasons=score["reasons"],
        summaries=score["summaries"],
        technical_summary=score["technical_summary"],
        data_mode=data_mode,
    )
