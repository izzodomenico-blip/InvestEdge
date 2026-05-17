from __future__ import annotations

import sqlite3

from backend.app.models import SignalOut


def _signal_from_row(row: sqlite3.Row) -> SignalOut:
    return SignalOut(
        id=row["id"],
        asset_id=row["asset_id"],
        symbol=row["symbol"],
        signal=row["signal"],
        score=row["score"],
        rationale=row["rationale"],
        generated_at=row["generated_at"],
    )


def list_signals(connection: sqlite3.Connection, limit: int = 50) -> list[SignalOut]:
    rows = connection.execute(
        """
        SELECT
            s.id,
            s.asset_id,
            a.symbol,
            s.signal,
            s.score,
            s.rationale,
            s.generated_at
        FROM signals s
        JOIN assets a ON a.id = s.asset_id
        ORDER BY s.generated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_signal_from_row(row) for row in rows]
