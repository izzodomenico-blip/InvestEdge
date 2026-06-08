from __future__ import annotations

import sqlite3

from backend.app.models import AssetCreate, AssetOut


def _latest_price_metrics(connection: sqlite3.Connection, asset_id: int) -> tuple[float | None, float | None]:
    rows = connection.execute(
        """
        SELECT close
        FROM price_history
        WHERE asset_id = ?
        ORDER BY date DESC, is_real_data DESC, id DESC
        LIMIT 2
        """,
        (asset_id,),
    ).fetchall()

    if not rows:
        return None, None

    latest = float(rows[0]["close"])
    if len(rows) < 2 or rows[1]["close"] in (None, 0):
        return latest, None

    previous = float(rows[1]["close"])
    return latest, ((latest - previous) / previous) * 100


def _latest_price_metadata(connection: sqlite3.Connection, asset_id: int) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT date, source, provider, is_real_data, fetched_at
        FROM price_history
        WHERE asset_id = ?
        ORDER BY date DESC, is_real_data DESC, id DESC
        LIMIT 1
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        return {
            "last_source": None,
            "provider": None,
            "is_real_data": False,
            "last_price_date": None,
            "last_fetch_at": None,
        }
    return {
        "last_source": row["source"],
        "provider": row["provider"],
        "is_real_data": bool(row["is_real_data"]),
        "last_price_date": row["date"],
        "last_fetch_at": row["fetched_at"],
    }


def _asset_from_row(row: sqlite3.Row) -> AssetOut:
    return AssetOut(
        id=row["id"],
        symbol=row["symbol"],
        name=row["name"],
        asset_type=row["asset_type"],
        exchange=row["exchange"],
        currency=row["currency"],
        sector=row["sector"],
        country=row["country"],
        risk_level=row["risk_level"],
        last_price=row["last_price"],
        daily_change_pct=row["daily_change_pct"],
        last_source=row["last_source"],
        provider=row["provider"],
        is_real_data=bool(row["is_real_data"]) if row["is_real_data"] is not None else False,
        last_price_date=row["last_price_date"],
        last_fetch_at=row["last_fetch_at"],
        score=row["score"],
        technical_score=row["technical_score"],
        news_score=row["news_score"] or 0,
        final_score=row["final_score"],
        news_sentiment_label=row["news_sentiment_label"],
        news_impact_level=row["news_impact_level"],
        signal=row["signal"],
        confidence=row["confidence"],
        technical_summary=row["technical_summary"],
        updated_at=row["updated_at"],
    )


def _asset_from_base_row(connection: sqlite3.Connection, row: sqlite3.Row) -> AssetOut:
    latest_price, daily_change_pct = _latest_price_metrics(connection, row["id"])
    price_metadata = _latest_price_metadata(connection, row["id"])
    signal_row = connection.execute(
        """
        SELECT score, technical_score, news_score, final_score, news_sentiment_label, news_impact_level,
            signal, confidence, technical_summary
        FROM signals
        WHERE asset_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (row["id"],),
    ).fetchone()

    return AssetOut(
        id=row["id"],
        symbol=row["symbol"],
        name=row["name"],
        asset_type=row["asset_type"],
        exchange=row["exchange"],
        currency=row["currency"],
        sector=row["sector"],
        country=row["country"],
        risk_level=row["risk_level"],
        last_price=latest_price,
        daily_change_pct=daily_change_pct,
        last_source=price_metadata["last_source"],
        provider=price_metadata["provider"],
        is_real_data=bool(price_metadata["is_real_data"]),
        last_price_date=price_metadata["last_price_date"],
        last_fetch_at=price_metadata["last_fetch_at"],
        score=signal_row["score"] if signal_row else None,
        technical_score=signal_row["technical_score"] if signal_row else None,
        news_score=signal_row["news_score"] if signal_row else 0,
        final_score=signal_row["final_score"] if signal_row else None,
        news_sentiment_label=signal_row["news_sentiment_label"] if signal_row else None,
        news_impact_level=signal_row["news_impact_level"] if signal_row else None,
        signal=signal_row["signal"] if signal_row else None,
        confidence=signal_row["confidence"] if signal_row else None,
        technical_summary=signal_row["technical_summary"] if signal_row else None,
        updated_at=row["updated_at"],
    )


def list_assets(connection: sqlite3.Connection) -> list[AssetOut]:
    rows = connection.execute(
        """
        SELECT
            a.id,
            a.symbol,
            a.name,
            a.asset_type,
            a.exchange,
            a.currency,
            a.sector,
            a.country,
            a.risk_level,
            a.updated_at,
            latest.close AS last_price,
            latest.date AS last_price_date,
            latest.source AS last_source,
            latest.provider AS provider,
            latest.is_real_data AS is_real_data,
            latest.fetched_at AS last_fetch_at,
            CASE
                WHEN previous.close IS NULL OR previous.close = 0 THEN NULL
                ELSE ((latest.close - previous.close) / previous.close) * 100
            END AS daily_change_pct,
            COALESCE(sig.final_score, sig.score) AS score,
            COALESCE(sig.technical_score, sig.score) AS technical_score,
            COALESCE(sig.news_score, 0) AS news_score,
            COALESCE(sig.final_score, sig.score) AS final_score,
            sig.news_sentiment_label,
            sig.news_impact_level,
            sig.signal,
            sig.confidence,
            sig.technical_summary
        FROM assets a
        LEFT JOIN price_history latest
            ON latest.id = (
                SELECT ph.id
                FROM price_history ph
                WHERE ph.asset_id = a.id
                ORDER BY ph.date DESC
                LIMIT 1
            )
        LEFT JOIN price_history previous
            ON previous.id = (
                SELECT ph.id
                FROM price_history ph
                WHERE ph.asset_id = a.id
                ORDER BY ph.date DESC
                LIMIT 1 OFFSET 1
            )
        LEFT JOIN signals sig
            ON sig.id = (
                SELECT s.id
                FROM signals s
                WHERE s.asset_id = a.id
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT 1
            )
        ORDER BY a.asset_type, a.symbol
        """
    ).fetchall()
    return [_asset_from_row(row) for row in rows]


def get_asset_by_symbol(connection: sqlite3.Connection, symbol: str) -> AssetOut | None:
    row = connection.execute(
        """
        SELECT id, symbol, name, asset_type, exchange, currency, sector, country, risk_level, updated_at
        FROM assets
        WHERE UPPER(symbol) = UPPER(?)
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is None:
        return None
    return _asset_from_base_row(connection, row)


def delete_asset(connection: sqlite3.Connection, symbol: str) -> bool:
    cursor = connection.execute("DELETE FROM assets WHERE UPPER(symbol) = UPPER(?)", (symbol,))
    return cursor.rowcount > 0


def create_asset(connection: sqlite3.Connection, payload: AssetCreate) -> AssetOut:
    cursor = connection.execute(
        """
        INSERT INTO assets (symbol, name, asset_type, exchange, currency, sector, country, risk_level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload.symbol.upper(),
            payload.name,
            payload.asset_type,
            payload.exchange,
            payload.currency.upper(),
            payload.sector,
            payload.country,
            payload.risk_level,
        ),
    )
    row = connection.execute(
        """
        SELECT id, symbol, name, asset_type, exchange, currency, sector, country, risk_level, updated_at
        FROM assets
        WHERE id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return _asset_from_base_row(connection, row)
