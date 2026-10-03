from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from backend.app.config import get_settings
from backend.app.lab.feature_store import FeatureStore
from backend.app.lab.features import MAX_FEATURE_WINDOW
from backend.app.lab.score_v1 import explain
from backend.app.lab.series import LabSeries, load_series, preferred_data_mode
from backend.app.models import SignalOut
from backend.app.services.sentiment_engine import aggregate_news_sentiment


def latest_segment_bars(series: LabSeries, as_of: date) -> pd.DataFrame:
    """Barre daily fino ad `as_of` del segmento piu recente: quelle dell'ultima riga D di `features_daily`."""
    for segment in reversed(series.segments):
        bars = segment.bars[segment.bars["date"] <= as_of.isoformat()]
        if not bars.empty:
            return bars.reset_index(drop=True)
    return series.segments[-1].bars.iloc[0:0]


def insufficient_history_message(bar_count: int) -> str:
    return f"Storico reale insufficiente ({bar_count} barre, servono {MAX_FEATURE_WINDOW})."


def informative_news_score(news_summary: dict[str, Any]) -> float:
    """Sentiment medio a 7 giorni x peso, entro +-peso: solo informativo, fuori dal `final_score` (spec SP1 §2)."""
    if news_summary["news_count"] == 0:
        return 0.0
    weight = get_settings().news_sentiment_weight
    return max(-weight, min(weight, float(news_summary["average_sentiment_score"]) * weight))


def score_unavailable_reason(connection: sqlite3.Connection, asset_id: int) -> str | None:
    """Serie REAL senza le barre del warm-up dello score nel segmento corrente (spec §6.1), altrimenti None."""
    if preferred_data_mode(connection, asset_id) != "REAL":
        return None
    series = load_series(connection, asset_id, "REAL")
    if series is None:
        return None
    bar_count = len(latest_segment_bars(series, datetime.now(UTC).date()))
    return insufficient_history_message(bar_count) if bar_count < MAX_FEATURE_WINDOW else None


def recalculate_signal(connection: sqlite3.Connection, asset_id: int, now: datetime | None = None) -> None:
    """Segnale dell'asset dallo score unico v1 (spec SP1 §4.2, §5.6, §6.1).

    Serie REAL se esiste, altrimenti DEMO (mai mescolate); `features_daily` aggiornata in modo incrementale;
    si usa l'ultima riga D solo se `warmup_complete`, altrimenti nessun segnale (quello vecchio viene rimosso).
    `final_score = score`: la correzione news resta informativa in `news_score`.
    """
    asset = connection.execute("SELECT symbol, risk_level FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        return
    symbol, risk_level = tuple(asset)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    connection.execute("DELETE FROM signals WHERE asset_id = ? AND source = 'scoring_engine'", (asset_id,))
    data_mode = preferred_data_mode(connection, asset_id)
    if data_mode is None:
        return
    store = FeatureStore()
    store.refresh_asset(connection, asset_id, data_mode, moment)
    row = store.latest_row(connection, asset_id, data_mode)
    if row is None or not row["warmup_complete"]:
        return

    explained = explain(row, str(risk_level))
    score = explained["score"]
    news_summary = aggregate_news_sentiment(connection, str(symbol), lookback_days=7)
    timestamp = moment.replace(tzinfo=None).isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO signals (
            asset_id, symbol, signal, score, technical_score, news_score, final_score,
            news_sentiment_label, news_impact_level, risk_level, confidence, technical_summary,
            reasons_json, subscores_json, indicators_json, rationale, source, generated_at, created_at, updated_at,
            data_mode
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scoring_engine', ?, ?, ?, ?)
        """,
        (
            asset_id,
            symbol,
            explained["signal"],
            score,
            score,
            round(informative_news_score(news_summary), 2),
            score,
            news_summary["sentiment_label"],
            news_summary["impact_level"],
            explained["risk_level"],
            explained["confidence"],
            explained["technical_summary"],
            json.dumps(explained["reasons"]),
            json.dumps(explained["subscores"]),
            json.dumps(explained["indicators"]),
            explained["technical_summary"],
            timestamp,
            timestamp,
            timestamp,
            data_mode,
        ),
    )


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
        data_mode=row["data_mode"],
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
            COALESCE(s.created_at, s.generated_at) AS created_at,
            s.data_mode
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
            COALESCE(s.created_at, s.generated_at) AS created_at,
            s.data_mode
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
