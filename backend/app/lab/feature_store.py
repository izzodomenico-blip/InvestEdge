"""Feature store `features_daily` incrementale (spec SP1 §5.4-§5.6).

- Righe D, W e M per segmento: D = barre daily fino ad `as_of`, W/M = `resample_bars(..., as_of)` del segmento;
  feature con `compute_features`, score con `score_frame` sul livello di rischio dell'asset.
- `window_hash` riassume le barre del timeframe nella finestra `[max(inizio segmento, i - MAX_FEATURE_WINDOW + 1), i]`:
  digest a 64 bit per barra sommati modulo 2**64 con somme cumulative (O(n)), piu versioni, timeframe, segmento,
  rischio, prima e ultima data e numero di barre della finestra.
- Refresh: si ricalcolano solo le righe nuove o con hash diverso, su una slice che parte `MAX_FEATURE_WINDOW - 1`
  barre prima della prima riga da ricalcolare (valori identici al calcolo completo, proprieta della pipeline);
  le righe non piu candidate vengono cancellate. Scrittura in un savepoint.
- Uno split a meta settimana o mese produce due barre W/M con la stessa `available_at` in segmenti diversi:
  resta quella del segmento successivo (una riga per data).
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd

from backend.app.lab.contracts import PIPELINE_VERSION, SCORE_VERSION, DataMode, Timeframe
from backend.app.lab.features import FEATURE_COLUMNS_V1, MAX_FEATURE_WINDOW, compute_features
from backend.app.lab.resample import resample_bars
from backend.app.lab.score_v1 import SUBSCORE_COLUMNS, score_frame
from backend.app.lab.series import LabSeries, load_series

TIMEFRAMES: tuple[Timeframe, ...] = ("D", "W", "M")
# `close_adj` non e in FEATURE_COLUMNS_V1 ma serve a `explain` per riprodurre lo score dalla riga salvata.
FEATURE_JSON_COLUMNS: tuple[str, ...] = ("close_adj", *FEATURE_COLUMNS_V1)
FRAME_COLUMNS: tuple[str, ...] = (
    "asset_id", "date", "segment_id", "warmup_complete", "score", *SUBSCORE_COLUMNS, *FEATURE_COLUMNS_V1,
)
_SCORE_COLUMNS: tuple[str, ...] = ("score", *SUBSCORE_COLUMNS)
SIGNAL_COLUMNS: frozenset[str] = frozenset({*_SCORE_COLUMNS, *FEATURE_COLUMNS_V1})
_DIGEST_COLUMNS = ("open", "high", "low", "close", "adjusted_close", "volume")
_UPSERT = f"""
    INSERT INTO features_daily (
        asset_id, timeframe, date, segment_id, pipeline_version, score_version, data_mode, window_hash,
        warmup_complete, {", ".join(_SCORE_COLUMNS)}, features_json, computed_at
    )
    VALUES ({", ".join(["?"] * (11 + len(_SCORE_COLUMNS)))})
    ON CONFLICT(asset_id, timeframe, date, pipeline_version, data_mode) DO UPDATE SET
        segment_id = excluded.segment_id,
        score_version = excluded.score_version,
        window_hash = excluded.window_hash,
        warmup_complete = excluded.warmup_complete,
        {", ".join(f"{column} = excluded.{column}" for column in _SCORE_COLUMNS)},
        features_json = excluded.features_json,
        computed_at = excluded.computed_at
"""


@dataclass(frozen=True)
class FeatureRefreshResult:
    asset_id: int
    data_mode: DataMode
    inserted: int
    updated: int
    deleted: int
    unchanged: int


@dataclass(frozen=True)
class _Block:
    """Barre di un timeframe in un segmento, hash per riga e righe candidate."""

    timeframe: Timeframe
    segment_id: int
    bars: pd.DataFrame
    dates: tuple[str, ...]
    hashes: tuple[str, ...]
    candidate: tuple[bool, ...]


class FeatureStore:
    def compute_rows(self, series: LabSeries, as_of: date) -> pd.DataFrame:
        """Calcolo completo e puro: righe D, W, M con `window_hash`, score, sottopunteggi e feature."""
        frames = [
            _compute(block, series.risk_level, np.flatnonzero(block.candidate))
            for block in _blocks(series, as_of)
            if any(block.candidate)
        ]
        if not frames:
            return pd.DataFrame(columns=list(_ROW_COLUMNS))
        return pd.concat(frames, ignore_index=True)

    def refresh_asset(
        self,
        connection: sqlite3.Connection,
        asset_id: int,
        data_mode: DataMode,
        now: datetime,
    ) -> FeatureRefreshResult | None:
        """Aggiorna le righe di un asset in un `data_mode`; None se l'asset non esiste."""
        if connection.execute("SELECT 1 FROM assets WHERE id = ?", (asset_id,)).fetchone() is None:
            return None
        moment = now.astimezone(UTC)
        series = load_series(connection, asset_id, data_mode)
        blocks = _blocks(series, moment.date()) if series is not None else []
        stored = {
            (str(row[1]), str(row[2])): (int(row[0]), str(row[3]))
            for row in connection.execute(
                """
                SELECT id, timeframe, date, window_hash
                FROM features_daily
                WHERE asset_id = ? AND data_mode = ? AND pipeline_version = ?
                """,
                (asset_id, data_mode, PIPELINE_VERSION),
            )
        }
        inserted = updated = unchanged = 0
        frames: list[pd.DataFrame] = []
        for block in blocks:
            pending: list[int] = []
            for position in np.flatnonzero(block.candidate).tolist():
                previous = stored.pop((block.timeframe, block.dates[position]), None)
                if previous is None:
                    inserted += 1
                elif previous[1] == block.hashes[position]:
                    unchanged += 1
                    continue
                else:
                    updated += 1
                pending.append(position)
            if pending and series is not None:
                frames.append(_compute(block, series.risk_level, np.asarray(pending)))
        stale_ids = [row_id for row_id, _hash in stored.values()]
        _write(connection, asset_id, data_mode, frames, stale_ids, moment)
        return FeatureRefreshResult(asset_id, data_mode, inserted, updated, len(stale_ids), unchanged)

    def read_frame(
        self,
        connection: sqlite3.Connection,
        asset_ids: Sequence[int],
        timeframe: Timeframe,
        data_mode: DataMode,
        *,
        start: str | None = None,
        end: str | None = None,
        complete_only: bool = True,
    ) -> pd.DataFrame:
        """Righe ordinate per asset e data; feature mancanti come NaN."""
        rows = _select(
            connection,
            asset_ids,
            timeframe,
            data_mode,
            ("asset_id", "date", "segment_id", "warmup_complete", *_SCORE_COLUMNS, "features_json"),
            start=start,
            end=end,
            complete_only=complete_only,
        )
        records = []
        for row in rows:
            features = json.loads(row[-1])
            records.append((*tuple(row)[:-1], *(features.get(column) for column in FEATURE_COLUMNS_V1)))
        frame = pd.DataFrame.from_records(records, columns=list(FRAME_COLUMNS))
        numeric = [*_SCORE_COLUMNS, *FEATURE_COLUMNS_V1]
        frame[numeric] = frame[numeric].astype(float)
        return frame

    def signal_panel(
        self,
        connection: sqlite3.Connection,
        asset_ids: Sequence[int],
        timeframe: Timeframe,
        data_mode: DataMode,
        signal_name: str,
        dates: Sequence[str],
    ) -> pd.DataFrame:
        """Valori del segnale per data (indice) e asset (colonne), solo da righe `warmup_complete`.

        D: valore solo se esiste la riga a quella data. W/M: ultima riga con data <= data (`merge_asof`),
        usata solo se e dello stesso segmento della data (mai un valore di un segmento precedente).
        """
        if signal_name not in SIGNAL_COLUMNS:
            raise ValueError("Segnale non disponibile nel feature store.")
        ids = [int(asset_id) for asset_id in asset_ids]
        index = pd.Index([str(day) for day in dates], name="date")
        panel = pd.DataFrame(np.nan, index=index, columns=pd.Index(ids, name="asset_id"))
        if not ids or index.empty:
            return panel
        end = max(index)
        rows = _signal_rows(connection, ids, timeframe, data_mode, signal_name, end)
        if timeframe == "D":
            complete = rows[rows["warmup_complete"] == 1]
            values = complete.pivot(index="date", columns="asset_id", values="value")
            panel.update(values.reindex(index=index, columns=ids).astype(float))
            return panel

        daily = _signal_rows(connection, ids, "D", data_mode, "score", end)
        targets = pd.DataFrame({"date": index, "key": pd.to_datetime(index)}).sort_values("key", kind="stable")
        for asset_id in ids:
            period = _asof_frame(rows[rows["asset_id"] == asset_id], ["segment_id", "warmup_complete", "value"])
            segments = _asof_frame(daily[daily["asset_id"] == asset_id], ["segment_id"]).rename(
                columns={"segment_id": "daily_segment"}
            )
            merged = pd.merge_asof(targets, period, on="key", direction="backward")
            merged = pd.merge_asof(merged, segments, on="key", direction="backward")
            valid = (merged["warmup_complete"] == 1) & (merged["segment_id"] == merged["daily_segment"])
            panel.loc[merged.loc[valid, "date"].to_numpy(), asset_id] = merged.loc[valid, "value"].astype(float).to_numpy()
        return panel

    def latest_row(self, connection: sqlite3.Connection, asset_id: int, data_mode: DataMode) -> dict[str, Any] | None:
        """Ultima riga D dell'asset (anche se il warm-up non e completo), con le feature del JSON."""
        cursor = connection.execute(
            f"""
            SELECT asset_id, timeframe, date, segment_id, pipeline_version, score_version, data_mode, window_hash,
                warmup_complete, {", ".join(_SCORE_COLUMNS)}, computed_at, features_json
            FROM features_daily
            WHERE asset_id = ? AND data_mode = ? AND timeframe = 'D' AND pipeline_version = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (asset_id, data_mode, PIPELINE_VERSION),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        result = dict(zip((column[0] for column in cursor.description), tuple(row), strict=True))
        features = json.loads(result.pop("features_json"))
        result["warmup_complete"] = bool(result["warmup_complete"])
        result.update({column: features.get(column) for column in FEATURE_JSON_COLUMNS})
        return result


_ROW_COLUMNS: tuple[str, ...] = (
    "timeframe", "date", "segment_id", "window_hash", "warmup_complete", *_SCORE_COLUMNS, *FEATURE_JSON_COLUMNS,
)


def _blocks(series: LabSeries, as_of: date) -> list[_Block]:
    parts: list[tuple[Timeframe, int, pd.DataFrame]] = []
    for segment in series.segments:
        daily = segment.bars[segment.bars["date"] <= as_of.isoformat()].reset_index(drop=True)
        if daily.empty:
            continue
        for timeframe in TIMEFRAMES:
            bars = daily if timeframe == "D" else resample_bars(daily, timeframe, as_of)
            if not bars.empty:
                parts.append((timeframe, segment.segment_id, bars))

    # A parita di timeframe e data vince il segmento successivo (si scorre dall'ultimo).
    taken: dict[Timeframe, set[str]] = {timeframe: set() for timeframe in TIMEFRAMES}
    blocks: list[_Block] = []
    for timeframe, segment_id, bars in reversed(parts):
        dates = tuple(str(day) for day in bars["date"])
        candidate = tuple(day not in taken[timeframe] for day in dates)
        taken[timeframe].update(dates)
        hashes = _window_hashes(bars, dates, timeframe, segment_id, series.risk_level)
        blocks.append(_Block(timeframe, segment_id, bars, dates, hashes, candidate))
    blocks.reverse()
    return blocks


def _bar_digest(day: str, *values: float) -> int:
    text = "|".join([day, *(repr(value) for value in values)])
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def _window_hashes(
    bars: pd.DataFrame,
    dates: tuple[str, ...],
    timeframe: Timeframe,
    segment_id: int,
    risk_level: str,
) -> tuple[str, ...]:
    columns = [bars[column].to_numpy(dtype=float).tolist() for column in _DIGEST_COLUMNS]
    digests = np.fromiter(
        (_bar_digest(day, *values) for day, *values in zip(dates, *columns, strict=True)),
        dtype=np.uint64,
        count=len(dates),
    )
    # uint64: somme e differenze si riducono modulo 2**64.
    cumulative = np.concatenate((np.zeros(1, dtype=np.uint64), np.cumsum(digests, dtype=np.uint64)))
    ends = np.arange(1, len(dates) + 1)
    starts = np.maximum(ends - MAX_FEATURE_WINDOW, 0)
    totals = cumulative[ends] - cumulative[starts]
    prefix = f"{PIPELINE_VERSION}|{SCORE_VERSION}|{timeframe}|{segment_id}|{risk_level}"
    return tuple(
        hashlib.sha256(f"{prefix}|{dates[start]}|{dates[end - 1]}|{end - start}|{total}".encode()).hexdigest()
        for start, end, total in zip(starts.tolist(), ends.tolist(), totals.tolist(), strict=True)
    )


def _compute(block: _Block, risk_level: str, positions: np.ndarray) -> pd.DataFrame:
    first, last = int(positions[0]), int(positions[-1])
    start = max(0, first - MAX_FEATURE_WINDOW + 1)
    features = compute_features(block.bars.iloc[start : last + 1].reset_index(drop=True), block.timeframe)
    features = features.iloc[positions - start].reset_index(drop=True)
    scores = score_frame(features, risk_level)
    frame = pd.DataFrame(
        {
            "timeframe": block.timeframe,
            "date": features["date"].astype(str),
            "segment_id": block.segment_id,
            "window_hash": [block.hashes[position] for position in positions.tolist()],
            "warmup_complete": scores["warmup_complete"].astype(int),
        }
    )
    for column in _SCORE_COLUMNS:
        frame[column] = scores[column].astype(float)
    for column in FEATURE_JSON_COLUMNS:
        frame[column] = features[column].astype(float)
    return frame


def _finite(value: object) -> float | None:
    number = float(value)  # type: ignore[arg-type]
    return number if math.isfinite(number) else None


def _write(
    connection: sqlite3.Connection,
    asset_id: int,
    data_mode: DataMode,
    frames: list[pd.DataFrame],
    stale_ids: list[int],
    moment: datetime,
) -> None:
    if not frames and not stale_ids:
        return
    computed_at = moment.isoformat(timespec="seconds")
    records = [
        (
            asset_id, row["timeframe"], row["date"], int(row["segment_id"]), PIPELINE_VERSION, SCORE_VERSION,
            data_mode, row["window_hash"], int(row["warmup_complete"]),
            *(_finite(row[column]) for column in _SCORE_COLUMNS),
            json.dumps(
                {column: _finite(row[column]) for column in FEATURE_JSON_COLUMNS},
                separators=(",", ":"),
                allow_nan=False,
            ),
            computed_at,
        )
        for frame in frames
        for row in frame.to_dict("records")
    ]
    connection.execute("SAVEPOINT features_daily_refresh")
    try:
        connection.executemany(_UPSERT, records)
        connection.executemany("DELETE FROM features_daily WHERE id = ?", [(row_id,) for row_id in stale_ids])
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT features_daily_refresh")
        connection.execute("RELEASE SAVEPOINT features_daily_refresh")
        raise
    connection.execute("RELEASE SAVEPOINT features_daily_refresh")


def _select(
    connection: sqlite3.Connection,
    asset_ids: Sequence[int],
    timeframe: Timeframe,
    data_mode: DataMode,
    columns: Sequence[str],
    *,
    start: str | None = None,
    end: str | None = None,
    complete_only: bool = False,
) -> list[sqlite3.Row]:
    ids = [int(asset_id) for asset_id in asset_ids]
    if not ids:
        return []
    clauses = [
        f"asset_id IN ({', '.join(['?'] * len(ids))})",
        "timeframe = ?",
        "data_mode = ?",
        "pipeline_version = ?",
    ]
    params: list[object] = [*ids, timeframe, data_mode, PIPELINE_VERSION]
    if start is not None:
        clauses.append("date >= ?")
        params.append(start)
    if end is not None:
        clauses.append("date <= ?")
        params.append(end)
    if complete_only:
        clauses.append("warmup_complete = 1")
    return connection.execute(
        f"SELECT {', '.join(columns)} FROM features_daily WHERE {' AND '.join(clauses)} ORDER BY asset_id, date",
        params,
    ).fetchall()


def _signal_rows(
    connection: sqlite3.Connection,
    asset_ids: Sequence[int],
    timeframe: Timeframe,
    data_mode: DataMode,
    signal_name: str,
    end: str,
) -> pd.DataFrame:
    """asset_id, date, segment_id, warmup_complete, value; `signal_name` gia validato contro SIGNAL_COLUMNS."""
    from_json = signal_name not in _SCORE_COLUMNS
    source = "features_json" if from_json else signal_name
    rows = _select(
        connection, asset_ids, timeframe, data_mode, ("asset_id", "date", "segment_id", "warmup_complete", source), end=end
    )
    records = [
        (*tuple(row)[:4], json.loads(row[4]).get(signal_name) if from_json else row[4])
        for row in rows
    ]
    frame = pd.DataFrame.from_records(records, columns=["asset_id", "date", "segment_id", "warmup_complete", "value"])
    frame["value"] = frame["value"].astype(float)
    return frame


def _asof_frame(rows: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = rows[columns].copy()
    frame.insert(0, "key", pd.to_datetime(rows["date"]))
    return frame.sort_values("key", kind="stable")
