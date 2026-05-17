from __future__ import annotations

import sqlite3

import pandas as pd

from backend.app.models import PriceHistoryOut, PricePointOut
from backend.app.services.technical_analysis import TechnicalAnalysisService


def _clean_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 6)


def get_price_history(
    connection: sqlite3.Connection,
    symbol: str,
    limit: int | None = None,
) -> PriceHistoryOut | None:
    asset = connection.execute(
        """
        SELECT id, symbol, name, asset_type, currency
        FROM assets
        WHERE UPPER(symbol) = UPPER(?)
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if asset is None:
        return None

    query = """
        SELECT date, open, high, low, close, adjusted_close, volume, source
        FROM price_history
        WHERE asset_id = ?
        ORDER BY date ASC
    """
    params: tuple[object, ...] = (asset["id"],)
    if limit:
        query = """
            SELECT *
            FROM (
                SELECT date, open, high, low, close, adjusted_close, volume, source
                FROM price_history
                WHERE asset_id = ?
                ORDER BY date DESC
                LIMIT ?
            )
            ORDER BY date ASC
        """
        params = (asset["id"], limit)

    rows = connection.execute(query, params).fetchall()
    if not rows:
        return PriceHistoryOut(
            symbol=asset["symbol"],
            name=asset["name"],
            asset_type=asset["asset_type"],
            currency=asset["currency"],
            prices=[],
        )

    frame = pd.DataFrame([dict(row) for row in rows])
    enriched = TechnicalAnalysisService().enrich_price_history(frame)

    prices = [
        PricePointOut(
            date=str(row["date"]),
            open=round(float(row["open"]), 6),
            high=round(float(row["high"]), 6),
            low=round(float(row["low"]), 6),
            close=round(float(row["close"]), 6),
            adjusted_close=round(float(row["adjusted_close"]), 6),
            volume=round(float(row["volume"]), 2),
            source=str(row["source"]),
            sma_20=_clean_float(row.get("sma_20")),
            sma_50=_clean_float(row.get("sma_50")),
            sma_200=_clean_float(row.get("sma_200")),
            ema_12=_clean_float(row.get("ema_12")),
            ema_26=_clean_float(row.get("ema_26")),
            rsi_14=_clean_float(row.get("rsi_14")),
            macd_line=_clean_float(row.get("macd_line")),
            macd_signal=_clean_float(row.get("macd_signal")),
        )
        for _, row in enriched.iterrows()
    ]

    return PriceHistoryOut(
        symbol=asset["symbol"],
        name=asset["name"],
        asset_type=asset["asset_type"],
        currency=asset["currency"],
        prices=prices,
    )
