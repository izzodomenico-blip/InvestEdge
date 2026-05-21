from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pandas as pd

from backend.app.models.schemas import DataQualityCheckOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class DataQualityService:
    def check_asset_quality(self, connection: sqlite3.Connection, symbol: str) -> DataQualityCheckOut:
        asset = connection.execute(
            "SELECT id FROM assets WHERE UPPER(symbol) = UPPER(?)", (symbol,)
        ).fetchone()
        if not asset:
            return self._empty_quality(symbol)

        asset_id = asset["id"]
        rows = connection.execute(
            "SELECT date, close, is_real_data FROM price_history WHERE asset_id = ? ORDER BY date DESC",
            (asset_id,),
        ).fetchall()

        if not rows:
            return self._empty_quality(symbol)

        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df["date"])

        # Checks
        history_length = len(df)
        has_real_data = bool(df["is_real_data"].any())

        # Check for gaps (more than 5 business days between prices)
        if history_length > 1:
            df_sorted = df.sort_values("date")
            gaps = int((df_sorted["date"].diff().dt.days > 7).sum())
        else:
            gaps = 0

        # Check for duplicates
        duplicates = int(df.duplicated(subset=["date"]).sum())

        # Check for stale data (last update > 7 days ago)
        last_date = df["date"].max()
        if last_date.tzinfo is not None:
            last_date = last_date.replace(tzinfo=None)
        now = datetime.now(UTC).replace(tzinfo=None)
        days_since_last = (now - last_date).days
        is_stale = days_since_last > 10

        score = 100.0
        checks = {
            "sufficient_history": history_length >= 50,
            "real_data": has_real_data,
            "no_gaps": gaps == 0,
            "no_duplicates": duplicates == 0,
            "fresh_data": not is_stale,
        }

        if history_length < 50:
            score -= 20
        if history_length < 20:
            score -= 30
        if not has_real_data:
            score -= 30
        if gaps > 0:
            score -= 15
        if duplicates > 0:
            score -= 10
        if is_stale:
            score -= 20

        score = max(0.0, score)

        grade = "A"
        if score < 90:
            grade = "B"
        if score < 75:
            grade = "C"
        if score < 50:
            grade = "D"
        if score < 30:
            grade = "F"

        return DataQualityCheckOut(
            symbol=symbol.upper(),
            score=score,
            grade=grade,
            checks=checks,
            details={
                "history_length": int(history_length),
                "gaps_found": int(gaps),
                "duplicates_found": int(duplicates),
                "days_since_last": int(days_since_last),
                "is_real_data": has_real_data,
            },
            is_valid=score >= 50,
            last_check=_now(),
        )

    def list_all_quality(self, connection: sqlite3.Connection) -> list[DataQualityCheckOut]:
        assets = connection.execute("SELECT symbol FROM assets ORDER BY symbol ASC").fetchall()
        return [self.check_asset_quality(connection, row["symbol"]) for row in assets]

    def _empty_quality(self, symbol: str) -> DataQualityCheckOut:
        return DataQualityCheckOut(
            symbol=symbol.upper(),
            score=0.0,
            grade="F",
            checks={
                "sufficient_history": False,
                "real_data": False,
                "no_gaps": False,
                "no_duplicates": False,
                "fresh_data": False,
            },
            details={},
            is_valid=False,
            last_check=_now(),
        )
