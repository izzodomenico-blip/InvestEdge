from __future__ import annotations

import json
import sqlite3

from backend.app.models import SignalOut


def _json_list(value: str | None) -> list[dict[str, str]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: str | None) -> dict[str, float]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _signal_from_row(row: sqlite3.Row) -> SignalOut:
    return SignalOut(
        id=row["id"],
        asset_id=row["asset_id"],
        symbol=row["symbol"],
        signal=row["signal"],
        score=row["score"],
        technical_score=row["technical_score"],
        news_score=row["news_score"] or 0,
        final_score=row["final_score"],
        news_sentiment_label=row["news_sentiment_label"],
        news_impact_level=row["news_impact_level"],
        risk_level=row["risk_level"],
        confidence=row["confidence"],
        technical_summary=row["technical_summary"],
        reasons=_json_list(row["reasons_json"]),
        subscores=_json_dict(row["subscores_json"]),
        created_at=row["created_at"],
    )


def list_signals(connection: sqlite3.Connection, limit: int = 50) -> list[SignalOut]:
    rows = connection.execute(
        """
        SELECT
            s.id,
            s.asset_id,
            COALESCE(s.symbol, a.symbol) AS symbol,
            s.signal,
            COALESCE(s.final_score, s.score) AS score,
            COALESCE(s.technical_score, s.score) AS technical_score,
            COALESCE(s.news_score, 0) AS news_score,
            COALESCE(s.final_score, s.score) AS final_score,
            s.news_sentiment_label,
            s.news_impact_level,
            COALESCE(s.risk_level, a.risk_level) AS risk_level,
            s.confidence,
            COALESCE(s.technical_summary, s.rationale) AS technical_summary,
            s.reasons_json,
            s.subscores_json,
            COALESCE(s.created_at, s.generated_at) AS created_at
        FROM signals s
        JOIN assets a ON a.id = s.asset_id
        ORDER BY s.created_at DESC, s.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_signal_from_row(row) for row in rows]


def get_signal_by_symbol(connection: sqlite3.Connection, symbol: str) -> SignalOut | None:
    row = connection.execute(
        """
        SELECT
            s.id,
            s.asset_id,
            COALESCE(s.symbol, a.symbol) AS symbol,
            s.signal,
            COALESCE(s.final_score, s.score) AS score,
            COALESCE(s.technical_score, s.score) AS technical_score,
            COALESCE(s.news_score, 0) AS news_score,
            COALESCE(s.final_score, s.score) AS final_score,
            s.news_sentiment_label,
            s.news_impact_level,
            COALESCE(s.risk_level, a.risk_level) AS risk_level,
            s.confidence,
            COALESCE(s.technical_summary, s.rationale) AS technical_summary,
            s.reasons_json,
            s.subscores_json,
            COALESCE(s.created_at, s.generated_at) AS created_at
        FROM signals s
        JOIN assets a ON a.id = s.asset_id
        WHERE UPPER(a.symbol) = UPPER(?)
        ORDER BY s.created_at DESC, s.id DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is None:
        return None
    return _signal_from_row(row)
