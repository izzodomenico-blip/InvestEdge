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
        signal=row["signal"],
        confidence=row["confidence"],
        technical_summary=row["technical_summary"],
        ml_model_id=row["ml_model_id"],
        ml_probability=row["ml_probability"],
        ml_confidence=row["ml_confidence"],
        ml_label=row["ml_label"],
        ml_target_type=row["ml_target_type"],
        updated_at=row["updated_at"],
    )


def _asset_from_base_row(connection: sqlite3.Connection, row: sqlite3.Row) -> AssetOut:
    latest_price, daily_change_pct = _latest_price_metrics(connection, row["id"])
    price_metadata = _latest_price_metadata(connection, row["id"])
    ml_row = connection.execute(
        """
        SELECT model_id, target_type, probability_positive, probability_outperform,
            probability_drawdown, predicted_label, confidence
        FROM ml_predictions
        WHERE UPPER(symbol) = UPPER(?)
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (row["symbol"],),
    ).fetchone()
    signal_row = connection.execute(
        """
        SELECT score, signal, confidence, technical_summary
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
        signal=signal_row["signal"] if signal_row else None,
        confidence=signal_row["confidence"] if signal_row else None,
        technical_summary=signal_row["technical_summary"] if signal_row else None,
        ml_model_id=ml_row["model_id"] if ml_row else None,
        ml_probability=_ml_probability_from_row(ml_row),
        ml_confidence=ml_row["confidence"] if ml_row else None,
        ml_label=ml_row["predicted_label"] if ml_row else None,
        ml_target_type=ml_row["target_type"] if ml_row else None,
        updated_at=row["updated_at"],
    )


def _ml_probability_from_row(row: sqlite3.Row | None) -> float | None:
    if row is None:
        return None
    target_type = row["target_type"]
    if target_type == "POSITIVE_RETURN":
        return row["probability_positive"]
    if target_type == "OUTPERFORM_BENCHMARK":
        return row["probability_outperform"]
    if target_type == "DRAWDOWN_RISK":
        return row["probability_drawdown"]
    return row["probability_positive"] or row["probability_outperform"] or row["probability_drawdown"]


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
            sig.score,
            sig.signal,
            sig.confidence,
            sig.technical_summary,
            ml.model_id AS ml_model_id,
            ml.target_type AS ml_target_type,
            CASE
                WHEN ml.target_type = 'POSITIVE_RETURN' THEN ml.probability_positive
                WHEN ml.target_type = 'OUTPERFORM_BENCHMARK' THEN ml.probability_outperform
                WHEN ml.target_type = 'DRAWDOWN_RISK' THEN ml.probability_drawdown
                ELSE COALESCE(ml.probability_positive, ml.probability_outperform, ml.probability_drawdown)
            END AS ml_probability,
            ml.confidence AS ml_confidence,
            ml.predicted_label AS ml_label
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
        LEFT JOIN ml_predictions ml
            ON ml.id = (
                SELECT mp.id
                FROM ml_predictions mp
                WHERE UPPER(mp.symbol) = UPPER(a.symbol)
                ORDER BY mp.created_at DESC, mp.id DESC
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
