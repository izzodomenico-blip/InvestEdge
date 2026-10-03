from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.app.database import SCHEMA, migrate_db
from backend.app.lab.feature_store import FeatureRefreshResult, FeatureStore
from backend.app.lab.features import FEATURE_COLUMNS_V1, compute_features
from backend.app.lab.resample import resample_bars
from backend.app.lab.score_v1 import SUBSCORE_COLUMNS, score_frame
from backend.app.lab.series import load_series
from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

NOW = datetime(2024, 6, 3, 12, 0, tzinfo=UTC)
LATER = datetime(2024, 6, 4, 12, 0, tzinfo=UTC)
ROW_COLUMNS = (
    "timeframe", "date", "segment_id", "pipeline_version", "score_version", "data_mode", "window_hash",
    "warmup_complete", "score", *SUBSCORE_COLUMNS, "features_json", "computed_at",
)


def _real_asset(connection: sqlite3.Connection, bars: pd.DataFrame, symbol: str = "AAA") -> int:
    asset_id = insert_asset(connection, symbol, currency="USD")
    insert_bars(connection, asset_id, bars, real=True, provider=None)
    connection.commit()
    return asset_id


def _rows(connection: sqlite3.Connection, asset_id: int, data_mode: str = "REAL") -> pd.DataFrame:
    rows = connection.execute(
        f"""
        SELECT {", ".join(ROW_COLUMNS)}
        FROM features_daily
        WHERE asset_id = ? AND data_mode = ?
        ORDER BY timeframe, date
        """,
        (asset_id, data_mode),
    ).fetchall()
    return pd.DataFrame([tuple(row) for row in rows], columns=list(ROW_COLUMNS))


def _period_bars(bars: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "D": bars,
        "W": resample_bars(bars, "W", NOW.date()),
        "M": resample_bars(bars, "M", NOW.date()),
    }


def _changed_dates(rows: pd.DataFrame, timeframe: str, moment: datetime) -> list[str]:
    stamp = moment.isoformat(timespec="seconds")
    selected = rows[(rows["timeframe"] == timeframe) & (rows["computed_at"] == stamp)]
    return selected["date"].tolist()


def test_refresh_inserts_d_w_m_rows_with_versions(lab_connection: sqlite3.Connection) -> None:
    bars = synthetic_bars(1500, seed=7)
    asset_id = _real_asset(lab_connection, bars)

    result = FeatureStore().refresh_asset(lab_connection, asset_id, "REAL", NOW)

    rows = _rows(lab_connection, asset_id)
    expected = {timeframe: len(frame) for timeframe, frame in _period_bars(bars).items()}
    assert rows.groupby("timeframe").size().to_dict() == expected
    assert result == FeatureRefreshResult(asset_id, "REAL", sum(expected.values()), 0, 0, 0)
    assert set(zip(rows["pipeline_version"], rows["score_version"], rows["data_mode"], strict=True)) == {
        ("features-v1", "score-v1", "REAL")
    }
    assert rows["window_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert set(rows["segment_id"]) == {0}
    assert set(rows["computed_at"]) == {"2024-06-03T12:00:00+00:00"}
    payload = json.loads(rows["features_json"].iloc[0])
    assert set(payload) == {"close_adj", *FEATURE_COLUMNS_V1}

    daily = rows[rows["timeframe"] == "D"].reset_index(drop=True)
    assert daily["date"].tolist() == bars["date"].tolist()
    assert daily["warmup_complete"].iloc[:251].eq(0).all()
    assert daily["warmup_complete"].iloc[251:].eq(1).all()
    expected_scores = score_frame(compute_features(bars, "D"), "medium")
    np.testing.assert_array_equal(daily["score"].to_numpy(), expected_scores["score"].to_numpy())
    pure = FeatureStore().compute_rows(load_series(lab_connection, asset_id, "REAL"), NOW.date())
    pure = pure.sort_values(["timeframe", "date"], kind="stable").reset_index(drop=True)
    assert pure["window_hash"].tolist() == rows["window_hash"].tolist()
    assert pure["score"].tolist() == rows["score"].tolist()


def test_second_refresh_changes_nothing(lab_connection: sqlite3.Connection) -> None:
    asset_id = _real_asset(lab_connection, synthetic_bars(600, seed=3))
    store = FeatureStore()
    first = store.refresh_asset(lab_connection, asset_id, "REAL", NOW)

    second = store.refresh_asset(lab_connection, asset_id, "REAL", LATER)

    total = first.inserted
    assert second == FeatureRefreshResult(asset_id, "REAL", 0, 0, 0, total)
    assert set(_rows(lab_connection, asset_id)["computed_at"]) == {"2024-06-03T12:00:00+00:00"}


def _revise_close(connection: sqlite3.Connection, asset_id: int, day: str, factor: float) -> None:
    connection.execute(
        "UPDATE price_history SET close = close * ?, adjusted_close = adjusted_close * ? WHERE asset_id = ? AND date = ?",
        (factor, factor, asset_id, day),
    )
    connection.commit()


def test_revised_bar_updates_only_rows_whose_window_contains_it(lab_connection: sqlite3.Connection) -> None:
    bars = synthetic_bars(1500, seed=11)
    asset_id = _real_asset(lab_connection, bars)
    store = FeatureStore()
    first = store.refresh_asset(lab_connection, asset_id, "REAL", NOW)
    # Venerdi e ultima seduta del mese: cambiano la barra D, la barra W e la barra M che la contengono.
    revised_day = "2020-01-31"
    _revise_close(lab_connection, asset_id, revised_day, 1.01)
    revised = bars.copy()
    revised.loc[revised["date"] == revised_day, ["close", "adjusted_close"]] *= 1.01

    result = store.refresh_asset(lab_connection, asset_id, "REAL", LATER)

    rows = _rows(lab_connection, asset_id)
    periods = _period_bars(revised)
    expected: dict[str, list[str]] = {}
    for timeframe, key in (("D", revised_day), ("W", "2020-02-02"), ("M", "2020-01-31")):
        dates = periods[timeframe]["date"].tolist()
        start = dates.index(key)
        expected[timeframe] = dates[start : start + 252]
        assert _changed_dates(rows, timeframe, LATER) == expected[timeframe]
    assert len(expected["D"]) == 252
    updated = sum(len(dates) for dates in expected.values())
    assert result == FeatureRefreshResult(asset_id, "REAL", 0, updated, 0, first.inserted - updated)
    earlier = rows[rows["date"] < revised_day]
    assert set(earlier["computed_at"]) == {"2024-06-03T12:00:00+00:00"}


def _fresh_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    migrate_db(connection)
    return connection


def test_incremental_equals_full_recompute(lab_connection: sqlite3.Connection) -> None:
    bars = synthetic_bars(1500, seed=13)
    asset_id = _real_asset(lab_connection, bars)
    store = FeatureStore()
    store.refresh_asset(lab_connection, asset_id, "REAL", NOW)
    _revise_close(lab_connection, asset_id, "2021-04-30", 0.97)
    lab_connection.execute(
        "DELETE FROM price_history WHERE asset_id = ? AND date = ?", (asset_id, bars["date"].iloc[-1])
    )
    lab_connection.commit()
    incremental = store.refresh_asset(lab_connection, asset_id, "REAL", LATER)
    assert incremental.deleted >= 1

    revised = bars.iloc[:-1].copy()
    revised.loc[revised["date"] == "2021-04-30", ["close", "adjusted_close"]] *= 0.97
    full_connection = _fresh_connection()
    try:
        full_asset = _real_asset(full_connection, revised)
        store.refresh_asset(full_connection, full_asset, "REAL", LATER)
        full = _rows(full_connection, full_asset)
    finally:
        full_connection.close()

    actual = _rows(lab_connection, asset_id)
    compared = [column for column in ROW_COLUMNS if column != "computed_at"]
    assert len(actual) == len(full)
    for column in compared:
        assert actual[column].tolist() == full[column].tolist(), column


def test_backfilled_older_bars_change_only_early_rows(lab_connection: sqlite3.Connection) -> None:
    bars = synthetic_bars(1500, seed=17)
    asset_id = insert_asset(lab_connection, "OLD", currency="USD")
    insert_bars(lab_connection, asset_id, bars.iloc[300:], real=True, provider=None)
    lab_connection.commit()
    store = FeatureStore()
    store.refresh_asset(lab_connection, asset_id, "REAL", NOW)
    insert_bars(lab_connection, asset_id, bars.iloc[:300], real=True, provider=None)
    lab_connection.commit()

    result = store.refresh_asset(lab_connection, asset_id, "REAL", LATER)

    rows = _rows(lab_connection, asset_id)
    dates = bars["date"].tolist()
    # Le righe 300..550 avevano la finestra tagliata dall'inizio della serie; dalla 551 la finestra e invariata.
    assert _changed_dates(rows, "D", LATER) == dates[:551]
    daily = rows[rows["timeframe"] == "D"]
    assert set(daily[daily["date"] >= dates[551]]["computed_at"]) == {"2024-06-03T12:00:00+00:00"}
    assert result.inserted >= 300
    assert result.deleted == 0


def test_real_and_demo_rows_are_separate(lab_connection: sqlite3.Connection) -> None:
    asset_id = insert_asset(lab_connection, "MIX", currency="USD")
    demo = synthetic_bars(500, seed=1)
    real = synthetic_bars(300, seed=2, start="2019-06-03")
    insert_bars(lab_connection, asset_id, demo, real=False, provider=None)
    insert_bars(lab_connection, asset_id, real, real=True, provider=None)
    lab_connection.commit()
    store = FeatureStore()

    real_first = store.refresh_asset(lab_connection, asset_id, "REAL", NOW)
    demo_first = store.refresh_asset(lab_connection, asset_id, "DEMO", NOW)
    real_again = store.refresh_asset(lab_connection, asset_id, "REAL", LATER)

    assert demo_first.inserted > 0 and demo_first.deleted == 0
    assert real_again == FeatureRefreshResult(asset_id, "REAL", 0, 0, 0, real_first.inserted)
    real_daily = store.read_frame(lab_connection, [asset_id], "D", "REAL", complete_only=False)
    demo_daily = store.read_frame(lab_connection, [asset_id], "D", "DEMO", complete_only=False)
    assert real_daily["date"].tolist() == real["date"].tolist()
    assert demo_daily["date"].tolist() == demo["date"].tolist()
    assert set(_rows(lab_connection, asset_id, "DEMO")["data_mode"]) == {"DEMO"}


def test_signal_panel_weekly_uses_last_closed_week(lab_connection: sqlite3.Connection) -> None:
    bars = synthetic_bars(1500, seed=19)
    asset_id = _real_asset(lab_connection, bars)
    store = FeatureStore()
    store.refresh_asset(lab_connection, asset_id, "REAL", NOW)
    weekly = store.read_frame(lab_connection, [asset_id], "W", "REAL", complete_only=False)
    sunday_row = weekly.iloc[280]
    next_row = weekly.iloc[281]
    assert sunday_row["warmup_complete"] == 1 and next_row["warmup_complete"] == 1
    sunday = date.fromisoformat(sunday_row["date"])
    monday = (sunday + timedelta(days=1)).isoformat()
    friday = (sunday + timedelta(days=5)).isoformat()
    next_sunday = (sunday + timedelta(days=7)).isoformat()
    assert next_row["date"] == next_sunday

    panel = store.signal_panel(lab_connection, [asset_id], "W", "REAL", "score", [friday, monday, next_sunday])

    assert panel.index.tolist() == [friday, monday, next_sunday]
    assert panel.columns.tolist() == [asset_id]
    assert panel.loc[monday, asset_id] == sunday_row["score"]
    assert panel.loc[friday, asset_id] == sunday_row["score"]
    assert panel.loc[next_sunday, asset_id] == next_row["score"]
    daily = store.signal_panel(lab_connection, [asset_id], "D", "REAL", "rsi_14", [monday, next_sunday])
    expected_rsi = store.read_frame(lab_connection, [asset_id], "D", "REAL", start=monday, end=monday)["rsi_14"]
    assert daily.loc[monday, asset_id] == expected_rsi.iloc[0]
    assert np.isnan(daily.loc[next_sunday, asset_id])
    with pytest.raises(ValueError):
        store.signal_panel(lab_connection, [asset_id], "D", "REAL", "volume; DROP TABLE assets", [monday])


def test_read_frame_complete_only_filters_warmup(lab_connection: sqlite3.Connection) -> None:
    bars = synthetic_bars(400, seed=23)
    asset_id = _real_asset(lab_connection, bars)
    store = FeatureStore()
    store.refresh_asset(lab_connection, asset_id, "REAL", NOW)

    complete = store.read_frame(lab_connection, [asset_id], "D", "REAL")
    everything = store.read_frame(lab_connection, [asset_id], "D", "REAL", complete_only=False)
    window = store.read_frame(
        lab_connection, [asset_id], "D", "REAL", start=bars["date"].iloc[10], end=bars["date"].iloc[19],
        complete_only=False,
    )

    columns = ["asset_id", "date", "segment_id", "warmup_complete", "score", *SUBSCORE_COLUMNS, *FEATURE_COLUMNS_V1]
    assert complete.columns.tolist() == columns
    assert everything.columns.tolist() == columns
    assert len(everything) == 400
    assert complete["date"].tolist() == bars["date"].iloc[251:].tolist()
    assert complete["warmup_complete"].eq(1).all()
    assert window["date"].tolist() == bars["date"].iloc[10:20].tolist()
    assert np.isnan(everything["sma_200"].iloc[0])
    latest = store.latest_row(lab_connection, asset_id, "REAL")
    assert latest["date"] == bars["date"].iloc[-1]
    assert latest["warmup_complete"] is True
    assert latest["score"] == complete["score"].iloc[-1]
    assert latest["close_adj"] == bars["close"].iloc[-1]
    assert latest["rsi_14"] == complete["rsi_14"].iloc[-1]
    assert store.latest_row(lab_connection, asset_id, "DEMO") is None


def _bars_with_forward_split(day: str) -> pd.DataFrame:
    bars = synthetic_bars(1500, seed=29)
    index = int(np.flatnonzero(bars["date"] == day)[0])
    prices = ["open", "high", "low", "close", "adjusted_close"]
    bars.loc[index:, prices] = bars.loc[index:, prices] / 2
    # Barra dello split 2:1 esatta: close e open a meta del close precedente (entro la tolleranza).
    half = bars.loc[index - 1, "close"] / 2
    bars.loc[index, prices] = [half, half * 1.006, half * 0.998, half * 1.004, half * 1.004]
    return bars


def test_split_mid_week_keeps_later_segment_and_panel_stops_at_boundary(lab_connection: sqlite3.Connection) -> None:
    split_day = "2023-06-07"  # mercoledi: la settimana ha barre in entrambi i segmenti
    bars = _bars_with_forward_split(split_day)
    asset_id = _real_asset(lab_connection, bars)
    series = load_series(lab_connection, asset_id, "REAL")
    assert series is not None and len(series.segments) == 2
    store = FeatureStore()

    store.refresh_asset(lab_connection, asset_id, "REAL", NOW)

    weekly = store.read_frame(lab_connection, [asset_id], "W", "REAL", complete_only=False)
    assert weekly["date"].is_unique
    assert weekly.loc[weekly["date"] == "2023-06-11", "segment_id"].tolist() == [1]
    previous_sunday = weekly[weekly["date"] == "2023-06-04"].iloc[0]
    assert previous_sunday["segment_id"] == 0 and previous_sunday["warmup_complete"] == 1
    panel = store.signal_panel(
        lab_connection, [asset_id], "W", "REAL", "score", ["2023-06-06", "2023-06-07", "2023-06-09"]
    )
    assert panel.loc["2023-06-06", asset_id] == previous_sunday["score"]
    assert np.isnan(panel.loc["2023-06-07", asset_id])
    assert np.isnan(panel.loc["2023-06-09", asset_id])


def test_rows_without_bars_are_deleted(lab_connection: sqlite3.Connection) -> None:
    asset_id = _real_asset(lab_connection, synthetic_bars(300, seed=31))
    store = FeatureStore()
    first = store.refresh_asset(lab_connection, asset_id, "REAL", NOW)
    lab_connection.execute("DELETE FROM price_history WHERE asset_id = ?", (asset_id,))
    lab_connection.commit()

    result = store.refresh_asset(lab_connection, asset_id, "REAL", LATER)

    assert result == FeatureRefreshResult(asset_id, "REAL", 0, 0, first.inserted, 0)
    assert lab_connection.execute("SELECT COUNT(*) FROM features_daily").fetchone()[0] == 0
    assert store.refresh_asset(lab_connection, 999, "REAL", LATER) is None
