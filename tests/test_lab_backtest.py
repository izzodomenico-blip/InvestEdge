"""Backtest onesto in EUR come job, con registro dei tentativi (spec SP1 §6.1, §6.5-§6.6, §7, §8.4)."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import get_settings
from backend.app.database import db_session, get_connection, init_db
from backend.app.lab.contracts import LabError
from backend.app.lab.trials import canonical_hash, family_key, family_trial_sharpes, record_trial
from backend.app.lab.universe import build_universe_inputs
from backend.app.models import BacktestCompareIn, BacktestRunIn
from backend.app.services.backtest_engine import BacktestEngine
from tests.lab_fixtures import insert_asset, insert_bars, insert_fx, synthetic_bars

NOW = datetime(2024, 1, 10, 12, 0, tzinfo=UTC)
BARS = 400
PRICE_COLUMNS = ["open", "high", "low", "close", "adjusted_close"]
DIGEST = "f" * 64


def _freeze_handler_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'handler dei job usa `datetime.now`: i test non dipendono dal calendario reale."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return NOW.replace(tzinfo=None) if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr("backend.app.lab.handlers.datetime", FrozenDatetime)


def _real_asset(
    connection: sqlite3.Connection,
    symbol: str,
    *,
    seed: int = 7,
    currency: str = "EUR",
    bars: pd.DataFrame | None = None,
) -> tuple[int, pd.DataFrame]:
    asset_id = insert_asset(connection, symbol, currency=currency)
    frame = bars if bars is not None else synthetic_bars(BARS, seed)
    insert_bars(connection, asset_id, frame, real=True, provider="stooq")
    connection.commit()
    return asset_id, frame


def _demo_asset(connection: sqlite3.Connection, symbol: str, *, seed: int = 5) -> tuple[int, pd.DataFrame]:
    asset_id = insert_asset(connection, symbol)
    frame = synthetic_bars(BARS, seed)
    insert_bars(connection, asset_id, frame, real=False, provider=None)
    connection.commit()
    return asset_id, frame


def _payload_data(symbols: list[str], *, start: str, end: str, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "Test v1",
        "strategy_name": "BUY_AND_HOLD",
        "symbols": symbols,
        "initial_cash": 10_000,
        "start_date": start,
        "end_date": end,
        "benchmark_symbol": "SPY",
        "max_asset_weight": 0.5,
        "stop_loss_percent": None,
        "take_profit_percent": None,
        "rebalance_frequency": "WEEKLY",
    }
    data.update(overrides)
    return data


def _payload(symbols: list[str], *, start: str, end: str, **overrides: object) -> BacktestRunIn:
    return BacktestRunIn(**_payload_data(symbols, start=start, end=end, **overrides))


def _period(bars: pd.DataFrame) -> dict[str, str]:
    return {"start": str(bars["date"].iloc[260]), "end": str(bars["date"].iloc[-1])}


def _trial_rows(connection: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            "SELECT family_key, kind, config_hash, fingerprint, n_obs, job_id FROM lab_trials ORDER BY id"
        )
    ]


# --- Motore ---------------------------------------------------------------------------------------------


def test_usd_asset_trades_are_converted_to_eur(lab_connection: sqlite3.Connection) -> None:
    _asset_id, bars = _real_asset(lab_connection, "USDA", currency="USD")
    insert_fx(lab_connection, "USD", [(str(day), 0.9) for day in bars["date"]])
    lab_connection.commit()
    period = _period(bars)

    result = BacktestEngine().run_backtest(lab_connection, _payload(["USDA"], **period), now=NOW)

    buy = result.trades[0]
    # Decisione alla chiusura della prima data del periodo, esecuzione all'apertura della barra successiva.
    assert (buy.date, buy.order_type, buy.reason) == (str(bars["date"].iloc[261]), "BUY", "SIGNAL")
    open_eur = float(bars["open"].iloc[261]) * 0.9
    assert buy.price == pytest.approx(open_eur * 1.001)
    assert buy.quantity == math.floor(5_000 / (open_eur * 1.001))
    assert buy.fees == pytest.approx(1.0)
    assert buy.commission == pytest.approx(1.0)
    assert buy.spread_cost == pytest.approx(buy.quantity * open_eur * 0.001)
    assert buy.net_amount == pytest.approx(buy.quantity * open_eur * 1.001 + 1)

    summary = result.summary
    assert (summary.engine_version, summary.data_mode, summary.fee_percent) == ("v1", "REAL", None)
    assert (summary.signal_name, summary.signal_timeframe) == ("score", "D")
    assert summary.cost_profile == {
        "commission_eur": 1.0, "cost_bps_equity": 10.0, "cost_bps_crypto": 50.0,
        "fractional_shares": False, "min_trade_eur": 100.0,
    }
    assert summary.excluded == {}
    assert summary.commission_eur == pytest.approx(1.0)
    assert summary.spread_cost_eur == pytest.approx(buy.spread_cost)
    assert len(summary.fingerprint or "") == 64
    assert any("Benchmark SPY non disponibile" in warning for warning in summary.warnings)
    assert any("bias di sopravvivenza" in warning for warning in summary.warnings)
    last = result.equity_curve[-1]
    assert last.date == period["end"]
    assert last.invested_value == pytest.approx(buy.quantity * float(bars["close"].iloc[-1]) * 0.9, rel=1e-6)
    [position] = result.final_positions
    assert (position.symbol, position.quantity) == ("USDA", buy.quantity)
    assert position.final_price == pytest.approx(float(bars["close"].iloc[-1]) * 0.9)
    # Commissioni e costo per lato sono gia nel valore finale: il netto toglie solo imposte e bollo.
    net = result.net_analysis
    assert net is not None
    assert net.slippage_costs == pytest.approx(buy.spread_cost, abs=0.01)
    assert net.total_costs_and_taxes == pytest.approx(net.capital_gains_tax + net.stamp_duty, abs=0.01)
    assert net.net_final_value == pytest.approx(summary.final_value - net.total_costs_and_taxes, abs=0.01)


def test_real_run_excludes_assets_without_real_series_and_lists_them(lab_connection: sqlite3.Connection) -> None:
    asset_id, real = _real_asset(lab_connection, "REALA")
    demo = synthetic_bars(BARS, 99)
    demo[PRICE_COLUMNS] = demo[PRICE_COLUMNS] * 10
    insert_bars(lab_connection, asset_id, demo, real=False, provider=None)
    _demo_asset(lab_connection, "DEMOB")
    lab_connection.commit()

    result = BacktestEngine().run_backtest(
        lab_connection, _payload(["REALA", "DEMOB", "NOPE"], **_period(real)), now=NOW
    )

    assert result.summary.excluded == {"DEMOB": "NO_REAL_SERIES", "NOPE": "NOT_FOUND"}
    assert {trade.symbol for trade in result.trades} == {"REALA"}
    real_open = dict(zip(real["date"], real["open"], strict=True))
    for trade in result.trades:
        assert trade.order_type == "BUY"
        assert trade.price == pytest.approx(real_open[trade.date] * 1.001)   # mai i prezzi demo (x10)
    assert {point.date for point in result.equity_curve} <= set(real["date"])


def test_demo_run_is_labeled_and_not_recorded_as_trial(lab_connection: sqlite3.Connection) -> None:
    _demo_asset(lab_connection, "DEMOA")
    _asset_id, real = _real_asset(lab_connection, "REALB", seed=11)
    strategy = {"strategy_name": "TOP_N_SCORE", "top_n": 1, "rebalance_frequency": "DAILY"}

    demo = BacktestEngine().run_backtest(
        lab_connection, _payload(["DEMOA"], data_mode="DEMO", **_period(real), **strategy), now=NOW
    )

    assert demo.summary.data_mode == "DEMO"
    assert demo.summary.warnings[0].startswith("Run DEMO")
    assert demo.summary.total_trades > 0
    assert _trial_rows(lab_connection) == []

    run = BacktestEngine().run_backtest(lab_connection, _payload(["REALB"], **_period(real), **strategy), now=NOW)

    [trial] = _trial_rows(lab_connection)
    assert trial[:2] == ("score|D", "BACKTEST")
    assert trial[3] == run.summary.fingerprint
    assert trial[4] == len(run.equity_curve) - 1
    assert trial[5] is None


def test_same_inputs_produce_same_fingerprint_and_metrics(lab_connection: sqlite3.Connection) -> None:
    _asset_id, bars = _real_asset(lab_connection, "FPA")
    _real_asset(lab_connection, "FPB", seed=11)
    payload = _payload(
        ["FPA", "FPB"], **_period(bars), strategy_name="TOP_N_SCORE", top_n=1, rebalance_frequency="DAILY",
        stop_loss_percent=8, take_profit_percent=25,
    )
    engine = BacktestEngine()

    first = engine.run_backtest(lab_connection, payload.model_copy(update={"name": "Primo"}), now=NOW)
    second = engine.run_backtest(
        lab_connection, payload.model_copy(update={"name": "Secondo"}), now=NOW + timedelta(days=30)
    )

    assert len(first.summary.fingerprint or "") == 64
    assert first.summary.fingerprint == second.summary.fingerprint
    ignored = {"id", "name", "created_at"}
    assert first.summary.model_dump(exclude=ignored) == second.summary.model_dump(exclude=ignored)
    assert [trade.model_dump(exclude={"id"}) for trade in first.trades] == [
        trade.model_dump(exclude={"id"}) for trade in second.trades
    ]
    assert first.summary.total_trades > 0

    changed = engine.run_backtest(lab_connection, payload.model_copy(update={"top_n": 2}), now=NOW)

    assert changed.summary.fingerprint != first.summary.fingerprint
    # Stessa configurazione su una barra rivista: impronta diversa (dati), stessa configurazione (N invariato).
    lab_connection.execute(
        "UPDATE price_history SET close = close * 1.01, adjusted_close = adjusted_close * 1.01 "
        "WHERE asset_id = ? AND date = ?",
        (_asset_id, str(bars["date"].iloc[300])),
    )
    lab_connection.commit()
    revised = engine.run_backtest(lab_connection, payload, now=NOW)

    assert revised.summary.fingerprint not in {first.summary.fingerprint, changed.summary.fingerprint}
    # Quattro run, due configurazioni distinte: N non cresce rieseguendo la stessa configurazione.
    assert len(_trial_rows(lab_connection)) == 4
    assert len(family_trial_sharpes(lab_connection, family_key("score", "D"))) == 2


def test_real_benchmark_uses_only_real_series(lab_connection: sqlite3.Connection) -> None:
    _asset_id, bars = _real_asset(lab_connection, "BMKA")
    _demo_asset(lab_connection, "BENCHD")
    _bench_id, bench = _real_asset(lab_connection, "BENCHR", seed=11)
    period = _period(bars)
    engine = BacktestEngine()

    demo_only = engine.run_backtest(lab_connection, _payload(["BMKA"], benchmark_symbol="BENCHD", **period), now=NOW)

    assert demo_only.summary.benchmark_return_percent == 0
    assert any("Benchmark BENCHD non disponibile in modalita REAL" in warning for warning in demo_only.summary.warnings)
    assert all(point.benchmark_value is None for point in demo_only.equity_curve)

    real = engine.run_backtest(lab_connection, _payload(["BMKA"], benchmark_symbol="BENCHR", **period), now=NOW)

    expected = (float(bench["close"].iloc[-1]) / float(bench["close"].iloc[260]) - 1) * 100
    assert real.summary.benchmark_return_percent == pytest.approx(expected)
    assert real.summary.alpha_vs_benchmark == pytest.approx(real.summary.total_return_percent - expected)
    assert real.equity_curve[0].benchmark_value == pytest.approx(10_000)
    assert real.equity_curve[-1].benchmark_value == pytest.approx(10_000 * (1 + expected / 100))
    assert not any("Benchmark" in warning for warning in real.summary.warnings)


def test_bars_without_valid_fx_are_excluded_and_counted(lab_connection: sqlite3.Connection) -> None:
    _asset_id, bars = _real_asset(lab_connection, "USDB", currency="USD")
    _real_asset(lab_connection, "GBPC", currency="GBP", seed=11)   # nessun cambio GBP
    dates = [str(day) for day in bars["date"]]
    insert_fx(lab_connection, "USD", [(day, 0.9) for day in [*dates[:301], *dates[340:]]])
    lab_connection.commit()
    period = _period(bars)
    observed = [date.fromisoformat(day) for day in [*dates[:301], *dates[340:]]]

    def has_rate(day: str) -> bool:
        current = date.fromisoformat(day)
        last = max(item for item in observed if item <= current)
        return (current - last).days <= get_settings().ecb_fx_max_age_days

    in_period = [day for day in dates if period["start"] <= day <= period["end"]]
    missing = [day for day in in_period if not has_rate(day)]
    assert missing   # il buco supera l'eta massima del cambio

    inputs = build_universe_inputs(
        lab_connection, ["USDB", "GBPC"], data_mode="REAL", signal_name="score", signal_timeframe="D",
        start=period["start"], end=period["end"], now=NOW,
    )

    assert inputs.excluded == {"GBPC": "NO_FX"}
    assert inputs.fx_excluded_bars == len(missing) + len(in_period)
    assert inputs.calendar == [day for day in in_period if has_rate(day)]
    [market] = inputs.markets.values()
    assert list(market.bars.index) == inputs.calendar

    result = BacktestEngine().run_backtest(lab_connection, _payload(["USDB", "GBPC"], **period), now=NOW)

    assert result.summary.excluded == {"GBPC": "NO_FX"}
    assert any(f"{len(missing) + len(in_period)} barre escluse" in warning for warning in result.summary.warnings)


def test_suspected_split_closes_the_position_at_segment_end_and_is_declared(
    lab_connection: sqlite3.Connection,
) -> None:
    bars = synthetic_bars(BARS, 7)
    factor = float(bars.loc[329, "close"]) / (2 * float(bars.loc[330, "close"]))
    bars.loc[330:, PRICE_COLUMNS] = bars.loc[330:, PRICE_COLUMNS] * factor   # split 2:1 non rettificato
    _real_asset(lab_connection, "SPL", bars=bars)

    result = BacktestEngine().run_backtest(lab_connection, _payload(["SPL"], **_period(bars)), now=NOW)

    buy, segment_exit = result.trades
    assert (buy.order_type, buy.date) == ("BUY", str(bars["date"].iloc[261]))
    assert (segment_exit.order_type, segment_exit.reason) == ("SELL", "SEGMENT_EXIT")
    assert segment_exit.date == str(bars["date"].iloc[329])            # ultima barra valida del segmento
    assert segment_exit.price == pytest.approx(float(bars["close"].iloc[329]) * 0.999)
    assert segment_exit.quantity == buy.quantity
    assert result.final_positions[0].quantity == 0
    assert any(
        warning.startswith(f"Split sospetto su SPL il {bars['date'].iloc[330]} (rapporto 2, FORWARD)")
        for warning in result.summary.warnings
    )


def test_run_declares_cancelled_orders_mixed_calendars_and_limits(lab_connection: sqlite3.Connection) -> None:
    _asset_id, bars = _real_asset(lab_connection, "STK")
    coin_id = insert_asset(lab_connection, "COIN", asset_type="crypto")
    insert_bars(lab_connection, coin_id, synthetic_bars(600, 21, freq="D"), real=True, provider="coingecko")
    lab_connection.commit()

    result = BacktestEngine().run_backtest(
        lab_connection,
        _payload(
            ["STK", "COIN"], **_period(bars), strategy_name="SCORE_THRESHOLD", buy_threshold=0, sell_threshold=0,
            max_asset_weight=1.0,
        ),
        now=NOW,
    )

    warnings = result.summary.warnings
    assert any(warning.startswith("Ordini annullati: ") and "INSUFFICIENT_CASH" in warning for warning in warnings)
    assert any(warning.startswith("Calendari misti") for warning in warnings)
    assert "Rettifica non verificata (base UNKNOWN), dividendi assenti: STK." in warnings
    assert "Storico CoinGecko di circa 365 giorni." in warnings
    assert warnings[-1].startswith("Costi di esecuzione ipotizzati: commissione 1 EUR per ordine")
    assert result.summary.excluded == {}


def test_assets_without_complete_signal_rows_are_excluded(lab_connection: sqlite3.Connection) -> None:
    _asset_id, bars = _real_asset(lab_connection, "LONG")
    _real_asset(lab_connection, "SHORT", bars=synthetic_bars(120, 3, start=str(bars["date"].iloc[280])))
    period = _period(bars)

    inputs = build_universe_inputs(
        lab_connection, ["LONG", "SHORT"], data_mode="REAL", signal_name="score", signal_timeframe="D",
        start=period["start"], end=period["end"], now=NOW,
    )

    assert inputs.excluded == {"SHORT": "NO_FEATURES"}
    assert [market.symbol for market in inputs.markets.values()] == ["LONG"]
    assert list(inputs.signals.columns) == list(inputs.markets)
    assert inputs.asset_types == {next(iter(inputs.markets)): "stock"}
    assert len(inputs.inputs_hash) == 64

    # Settimanale: servono 252 barre W complete, nessun asset le ha -> universo vuoto (non "senza serie reale").
    with pytest.raises(LabError) as error:
        build_universe_inputs(
            lab_connection, ["LONG", "SHORT"], data_mode="REAL", signal_name="score", signal_timeframe="W",
            start=period["start"], end=period["end"], now=NOW,
        )
    assert error.value.code == "LAB_EMPTY_UNIVERSE"


def test_real_universe_without_real_series_is_rejected(lab_connection: sqlite3.Connection) -> None:
    _asset_id, bars = _demo_asset(lab_connection, "ONLYDEMO")
    engine = BacktestEngine()

    with pytest.raises(LabError) as error:
        engine.precheck(lab_connection, ["ONLYDEMO", "NOPE"], "REAL")
    assert error.value.code == "LAB_NO_REAL_SERIES"
    engine.precheck(lab_connection, ["ONLYDEMO"], "DEMO")

    with pytest.raises(LabError) as error:
        engine.run_backtest(lab_connection, _payload(["ONLYDEMO"], **_period(bars)), now=NOW)
    assert error.value.code == "LAB_NO_REAL_SERIES"
    assert lab_connection.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 0


def test_universe_signals_ignore_future_bars(lab_connection: sqlite3.Connection) -> None:
    base = synthetic_bars(320, 13)
    jumped = base.copy()
    jumped.loc[300:, PRICE_COLUMNS] = jumped.loc[300:, PRICE_COLUMNS] * 2.5
    short_id, _ = _real_asset(lab_connection, "PAST", bars=base.iloc[:300].reset_index(drop=True))
    long_id, _ = _real_asset(lab_connection, "FUTURE", bars=jumped)
    window = {"start": str(base["date"].iloc[255]), "end": str(base["date"].iloc[319])}

    def signals(symbol: str, asset_id: int) -> pd.Series:
        inputs = build_universe_inputs(
            lab_connection, [symbol], data_mode="REAL", signal_name="score", signal_timeframe="D", now=NOW, **window,
        )
        return inputs.signals[asset_id]

    past = signals("PAST", short_id)
    future = signals("FUTURE", long_id)
    common = [day for day in past.index if day <= str(base["date"].iloc[299])]
    assert past.loc[common].notna().all()
    pd.testing.assert_series_equal(past.loc[common], future.loc[common], check_names=False)


# --- Registro dei tentativi -----------------------------------------------------------------------------


def test_trials_count_distinct_configs_only(lab_connection: sqlite3.Connection) -> None:
    family = family_key("score", "D")
    config = canonical_hash({"strategy": "A", "top_n": 3})
    other = canonical_hash({"strategy": "A", "top_n": 5})
    common = {"family": family, "fingerprint": DIGEST, "n_obs": 100, "job_id": None}

    assert family == "score|D"
    assert canonical_hash({"b": 1, "a": [1, 2]}) == canonical_hash({"a": [1, 2], "b": 1})
    assert record_trial(lab_connection, data_mode="REAL", kind="BACKTEST", config_hash=config, sharpe_daily=0.01, **common)
    assert record_trial(lab_connection, data_mode="REAL", kind="COMPARE", config_hash=config, sharpe_daily=0.03, **common)
    assert family_trial_sharpes(lab_connection, family) == [0.03]

    assert record_trial(lab_connection, data_mode="REAL", kind="WF_GRID", config_hash=other, sharpe_daily=-0.02, **common)
    assert sorted(family_trial_sharpes(lab_connection, family)) == [-0.02, 0.03]
    assert family_trial_sharpes(lab_connection, family_key("score", "W")) == []

    assert not record_trial(lab_connection, data_mode="DEMO", kind="BACKTEST", config_hash=other, sharpe_daily=0.5, **common)
    assert not record_trial(
        lab_connection, data_mode="REAL", kind="BACKTEST", config_hash=other, sharpe_daily=0.5,
        family=family, fingerprint=DIGEST, n_obs=1, job_id=None,
    )
    assert not record_trial(
        lab_connection, data_mode="REAL", kind="BACKTEST", config_hash=other, sharpe_daily=math.nan, **common
    )
    assert len(_trial_rows(lab_connection)) == 3


def test_lab_trials_are_append_only(lab_connection: sqlite3.Connection) -> None:
    record_trial(
        lab_connection, data_mode="REAL", family="score|D", kind="BACKTEST", config_hash=DIGEST, fingerprint=DIGEST,
        sharpe_daily=0.02, n_obs=50, job_id=7,
    )
    lab_connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        lab_connection.execute("UPDATE lab_trials SET sharpe_daily = 1.0")
    with pytest.raises(sqlite3.IntegrityError):
        lab_connection.execute("DELETE FROM lab_trials")
    insert = (
        "INSERT INTO lab_trials (family_key, kind, config_hash, fingerprint, sharpe_daily, n_obs, created_at) "
        "VALUES ('score|D', ?, ?, ?, 0.1, ?, '2024-01-10T12:00:00')"
    )
    for values in (("OTHER", DIGEST, DIGEST, 10), ("BACKTEST", "short", DIGEST, 10), ("BACKTEST", DIGEST, DIGEST, 1)):
        with pytest.raises(sqlite3.IntegrityError):
            lab_connection.execute(insert, values)
    assert _trial_rows(lab_connection) == [("score|D", "BACKTEST", DIGEST, DIGEST, 50, 7)]


LEGACY_BACKTEST_SCHEMA = """
CREATE TABLE backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    benchmark_symbol TEXT,
    buy_threshold REAL NOT NULL DEFAULT 70,
    sell_threshold REAL NOT NULL DEFAULT 40,
    max_asset_weight REAL NOT NULL DEFAULT 0.15,
    fee_percent REAL NOT NULL DEFAULT 0.1,
    stop_loss_percent REAL,
    take_profit_percent REAL,
    rebalance_frequency TEXT NOT NULL DEFAULT 'WEEKLY',
    total_return_percent REAL NOT NULL DEFAULT 0,
    cagr REAL NOT NULL DEFAULT 0,
    max_drawdown REAL NOT NULL DEFAULT 0,
    sharpe_ratio REAL NOT NULL DEFAULT 0,
    win_rate REAL NOT NULL DEFAULT 0,
    profit_factor REAL NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    final_value REAL NOT NULL DEFAULT 0,
    benchmark_return_percent REAL NOT NULL DEFAULT 0,
    alpha_vs_benchmark REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE backtest_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK(order_type IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    gross_amount REAL NOT NULL DEFAULT 0,
    net_amount REAL NOT NULL DEFAULT 0,
    pnl REAL NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(backtest_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);
INSERT INTO backtest_runs (
    name, strategy_name, initial_cash, start_date, end_date, benchmark_symbol, fee_percent,
    total_return_percent, total_trades, final_value, created_at
)
VALUES ('Motore vecchio', 'BUY_AND_HOLD', 1000, '2025-01-02', '2025-03-31', 'SPY', 0.1, 5.0, 1, 1050,
    '2025-04-01T10:00:00');
INSERT INTO backtest_trades (backtest_id, date, symbol, order_type, quantity, price, fees, gross_amount, net_amount, pnl)
VALUES (1, '2025-01-02', 'AAA', 'BUY', 10, 100, 1, 1000, 1001, 0);
"""


def test_existing_runs_are_marked_v0_after_migration(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(LEGACY_BACKTEST_SCHEMA)
    legacy.close()
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(path))
    get_settings.cache_clear()
    connection = None
    try:
        init_db()
        connection = get_connection()
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(backtest_runs)")}
        trade_columns = {row[1] for row in connection.execute("PRAGMA table_info(backtest_trades)")}
        assert {
            "engine_version", "data_mode", "signal_name", "signal_timeframe", "cost_profile_json", "fingerprint",
            "warnings_json",
        } <= run_columns
        assert {"commission", "spread_cost"} <= trade_columns
        engine = BacktestEngine()

        [summary] = engine.list_backtests(connection)

        assert (summary.engine_version, summary.fee_percent, summary.data_mode) == ("v0", 0.1, None)
        assert (summary.warnings, summary.excluded, summary.cost_profile) == ([], {}, None)
        detail = engine.get_backtest(connection, summary.id)
        assert detail.trades[0].fees == 1
        assert detail.trades[0].commission is None
        assert detail.net_analysis is not None
        assert engine.delete_backtest(connection, summary.id)
        connection.commit()
        assert engine.list_backtests(connection) == []
    finally:
        if connection is not None:
            connection.close()
        get_settings.cache_clear()


# --- Job e annullamento ---------------------------------------------------------------------------------


def test_cancel_between_steps_persists_no_run_and_no_trial(
    lab_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.lab import handlers  # noqa: F401 - registra BACKTEST e COMPARE
    from backend.app.lab.jobs import JobService
    from backend.app.services import backtest_engine as engine_module

    _freeze_handler_clock(monkeypatch)
    _asset_id, bars = _real_asset(lab_connection, "CANC")
    original = engine_module.build_universe_inputs

    def cancel_after_universe(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        inputs = original(*args, **kwargs)
        other = get_connection()
        try:
            other.execute("UPDATE lab_jobs SET cancel_requested = 1")
            other.commit()
        finally:
            other.close()
        return inputs

    monkeypatch.setattr(engine_module, "build_universe_inputs", cancel_after_universe)

    job = JobService("inline").enqueue("BACKTEST", _payload(["CANC"], **_period(bars)).model_dump(mode="json"))

    assert job.status == "CANCELLED"
    assert lab_connection.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 0
    assert _trial_rows(lab_connection) == []


def test_backtest_payload_validation() -> None:
    base = _payload_data(["AAA"], start="2024-01-02", end="2024-06-28")

    assert "fee_percent" not in BacktestRunIn.model_fields
    accepted = BacktestRunIn(**base, fee_percent=0.1)   # campo legacy ignorato
    assert (accepted.data_mode, accepted.signal_name, accepted.signal_timeframe) == ("REAL", "score", "D")
    assert BacktestRunIn(**{**base, "symbols": [" aaa ", "AAA", "bbb"]}).symbols == ["AAA", "BBB"]
    assert BacktestRunIn(**{**base, "signal_name": "rsi_14", "signal_timeframe": "W"}).signal_name == "rsi_14"
    invalid = (
        {"signal_name": "chikou_span"},
        {"signal_timeframe": "H"},
        {"data_mode": "MIXED"},
        {"start_date": "2024-07-01"},
        {"end_date": "2024-02-30"},
        {"start_date": "02/01/2024"},
        {"symbols": ["  "]},
        {"commission_eur": -1},
        {"cost_bps_equity": -5},
    )
    for override in invalid:
        with pytest.raises(ValidationError):
            BacktestRunIn(**{**base, **override})
    compare = {key: value for key, value in base.items() if key != "strategy_name"}
    with pytest.raises(ValidationError):
        BacktestCompareIn(**compare, strategy_names=["TOP_N_SCORE", "TOP_N_SCORE"])
    assert BacktestCompareIn(**compare, strategy_names=["TOP_N_SCORE", "BUY_AND_HOLD"]).data_mode == "REAL"


# --- API ------------------------------------------------------------------------------------------------


def test_real_universe_empty_is_rejected_before_enqueue(client: TestClient) -> None:
    payload = _payload_data(["AAPL", "MSFT"], start="2025-06-02", end="2026-05-15")
    compare = {key: value for key, value in payload.items() if key != "strategy_name"}
    requests = (
        ("/backtests/run", payload),
        ("/backtests/compare", {**compare, "strategy_names": ["TOP_N_SCORE", "BUY_AND_HOLD"]}),
    )

    for path, body in requests:
        response = client.post(path, json=body)

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["reason_code"] == "LAB_NO_REAL_SERIES"
        assert detail["message"]
    assert client.get("/lab/jobs").json() == []


def test_backtest_route_returns_202_job_and_persists_a_v1_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_handler_clock(monkeypatch)
    with db_session() as connection:
        _asset_id, bars = _real_asset(connection, "LABA")
        _real_asset(connection, "LABB", seed=11)
    payload = _payload_data(
        ["LABA", "LABB"], **_period(bars), strategy_name="TOP_N_SCORE", top_n=1, rebalance_frequency="DAILY"
    )

    response = client.post("/backtests/run", json=payload)

    assert response.status_code == 202
    job = response.json()
    assert (job["kind"], job["status"]) == ("BACKTEST", "SUCCEEDED")
    polled = client.get(f"/lab/jobs/{job['id']}").json()
    assert polled["status"] == "SUCCEEDED"
    run_id = int(polled["result_ref"])
    assert polled["result"] == {"backtest_id": run_id}
    detail = client.get(f"/backtests/{run_id}").json()
    summary = detail["summary"]
    assert (summary["engine_version"], summary["data_mode"], summary["fee_percent"]) == ("v1", "REAL", None)
    assert summary["total_trades"] > 0
    assert all(trade["commission"] == 1.0 for trade in detail["trades"])
    history = client.get("/backtests").json()
    assert [item["engine_version"] for item in history if item["id"] == run_id] == ["v1"]
    with db_session() as connection:
        trials = _trial_rows(connection)
    assert [(row[1], row[3], row[5]) for row in trials] == [("BACKTEST", summary["fingerprint"], job["id"])]


def test_compare_route_returns_job_ranked_by_net_sharpe(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_handler_clock(monkeypatch)
    with db_session() as connection:
        _asset_id, bars = _real_asset(connection, "CMPA")
        _real_asset(connection, "CMPB", seed=11)
    payload = _payload_data(
        ["CMPA", "CMPB"], **_period(bars), name="Confronto v1", buy_threshold=0, sell_threshold=0, top_n=1,
        rebalance_frequency="DAILY",
    )
    payload.pop("strategy_name")
    payload["strategy_names"] = ["BUY_AND_HOLD", "SCORE_THRESHOLD", "TOP_N_SCORE"]

    response = client.post("/backtests/compare", json=payload)

    assert response.status_code == 202
    job = response.json()
    assert (job["kind"], job["status"], job["result_ref"]) == ("COMPARE", "SUCCEEDED", None)
    result = client.get(f"/lab/jobs/{job['id']}").json()["result"]
    entries = result["entries"]
    assert [entry["rank"] for entry in entries] == [1, 2, 3]
    assert {entry["strategy_name"] for entry in entries} == {"BUY_AND_HOLD", "SCORE_THRESHOLD", "TOP_N_SCORE"}
    sharpes = [entry["summary"]["sharpe_ratio"] for entry in entries]
    assert sharpes == sorted(sharpes, reverse=True)
    assert result["best_strategy"] == entries[0]["strategy_name"]
    assert all(entry["summary"]["data_mode"] == "REAL" for entry in entries)
    assert all(len(entry["equity_curve"]) > 50 for entry in entries)
    with db_session() as connection:
        trials = _trial_rows(connection)
    assert [row[1] for row in trials] == ["COMPARE"] * 3
    assert len({row[2] for row in trials}) == 3
    assert {row[5] for row in trials} == {job["id"]}
    assert all("Confronto v1" not in item["name"] for item in client.get("/backtests").json())
