from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pandas as pd

from backend.app.models import PriceHistoryOut, PricePointOut
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.technical_analysis import TechnicalAnalysisService


def _clean_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 6)


def _optional_string(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _effective_quality(row: pd.Series, now: datetime) -> str | None:
    observed_at = _optional_string(row.get("provider_observed_at"))
    capability = _optional_string(row.get("observation_capability"))
    source_quality = _optional_string(row.get("source_quality"))
    if observed_at is None or capability is None or source_quality is None:
        return None
    parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return None
    return MarketObservationService.effective_quality_for(
        capability,
        source_quality,
        parsed,
        now,
    )


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

    projection = """
        SELECT ph.date, ph.open, ph.high, ph.low, ph.close, ph.adjusted_close,
               ph.volume, ph.source, ph.provider, ph.is_real_data, ph.fetched_at,
               observation.listing_id,
               observation.id AS observation_id,
               observation.provider_observed_at,
               observation.ingested_at,
               observation.timezone,
               observation.session,
               observation.currency AS observation_currency,
               observation.delay_seconds,
               observation.source_quality,
               observation.capability AS observation_capability,
               (
                   SELECT selection.fallback_reason
                   FROM market_data_selection_events AS selection
                   WHERE selection.selected_observation_id = observation.id
                   ORDER BY selection.selected_at DESC, selection.id DESC
                   LIMIT 1
               ) AS fallback_reason
        FROM price_history AS ph
        LEFT JOIN market_observations AS observation
          ON observation.id = ph.observation_id
    """
    query = projection + """
        WHERE ph.asset_id = ?
        ORDER BY ph.date ASC, ph.is_real_data DESC, ph.id ASC
    """
    params: tuple[object, ...] = (asset["id"],)
    if limit:
        query = """
            SELECT *
            FROM (
        """ + projection + """
                WHERE ph.asset_id = ?
                ORDER BY ph.date DESC, ph.is_real_data DESC, ph.id DESC
                LIMIT ?
            )
            ORDER BY date ASC, is_real_data DESC
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

    now = datetime.now(UTC)
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
            provider=row.get("provider"),
            is_real_data=bool(row.get("is_real_data", 0)),
            fetched_at=row.get("fetched_at"),
            listing_id=_optional_int(row.get("listing_id")),
            observation_id=_optional_int(row.get("observation_id")),
            provider_observed_at=_optional_string(row.get("provider_observed_at")),
            ingested_at=_optional_string(row.get("ingested_at")),
            timezone=_optional_string(row.get("timezone")),
            session=_optional_string(row.get("session")),
            currency=_optional_string(row.get("observation_currency")),
            delay_seconds=_optional_int(row.get("delay_seconds")),
            source_quality=_optional_string(row.get("source_quality")),
            effective_quality=_effective_quality(row, now),
            fallback_reason=_optional_string(row.get("fallback_reason")),
            sma_20=_clean_float(row.get("sma_20")),
            sma_50=_clean_float(row.get("sma_50")),
            sma_200=_clean_float(row.get("sma_200")),
            ema_12=_clean_float(row.get("ema_12")),
            ema_26=_clean_float(row.get("ema_26")),
            ema_50=_clean_float(row.get("ema_50")),
            ema_200=_clean_float(row.get("ema_200")),
            rsi_14=_clean_float(row.get("rsi_14")),
            macd_line=_clean_float(row.get("macd_line")),
            macd_signal=_clean_float(row.get("macd_signal")),
            macd_histogram=_clean_float(row.get("macd_histogram")),
            bollinger_upper=_clean_float(row.get("bollinger_upper")),
            bollinger_lower=_clean_float(row.get("bollinger_lower")),
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
