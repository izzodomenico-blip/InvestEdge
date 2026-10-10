"""Walk-forward vero (spec SP1 §8.3-§8.5): finestre, griglia, selezione in-sample, OOS unico, tentativi e DSR."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.config import get_settings
from backend.app.database import get_connection
from backend.app.lab.contracts import LabError
from backend.app.lab.costs import CostProfile
from backend.app.lab.series import split_into_segments
from backend.app.lab.simulator import AssetMarket, SimulationConfig, SimulationResult, simulate
from backend.app.lab.stats import EULER_MASCHERONI, sharpe_daily
from backend.app.lab.strategies import StrategyParams
from backend.app.lab.trials import canonical_hash, family_key, family_trial_sharpes, trial_config
from backend.app.lab.universe import UniverseInputs, build_universe_inputs
from backend.app.lab.walk_forward import (
    WalkForwardWindow,
    build_windows,
    parameter_grid,
    run_walk_forward,
    select_parameters,
    simulate_grid,
    simulate_oos,
)
from backend.app.models import BacktestRunIn, WalkForwardIn
from backend.app.services.backtest_engine import BacktestEngine
from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

NOW = datetime(2024, 1, 10, 12, 0, tzinfo=UTC)
BARS = 700
EUR_PRICES = ["open_eur", "high_eur", "low_eur", "close_eur"]
DB_PRICES = ["open", "high", "low", "close", "adjusted_close"]
COSTS = CostProfile(
    commission_eur=1.0, cost_bps_equity=10.0, cost_bps_crypto=50.0, fractional_shares=False, min_trade_eur=100.0
)
SYMBOLS = ["WFA", "WFB", "WFC", "WFD"]


# --- Universi sintetici ---------------------------------------------------------------------------------


def _market(asset_id: int, bars: pd.DataFrame) -> AssetMarket:
    frame = bars.set_index("date")[["open", "high", "low", "close"]].add_suffix("_eur")
    frame["segment_id"] = 0
    return AssetMarket(asset_id, f"A{asset_id}", "stock", frame)


def _inputs(markets: dict[int, AssetMarket], signals: pd.DataFrame) -> UniverseInputs:
    calendar = sorted({str(day) for market in markets.values() for day in market.bars.index})
    return UniverseInputs(
        markets=markets,
        signals=signals.reindex(calendar),
        calendar=calendar,
        excluded={},
        split_events={},
        fx_excluded_bars=0,
        inputs_hash="0" * 64,
        asset_types=dict.fromkeys(markets, "stock"),
        adjustment_basis=dict.fromkeys(markets, "UNKNOWN"),
    )


def _random_universe(*, assets: int = 4, sessions: int = 300, seed: int = 3) -> UniverseInputs:
    markets = {asset_id: _market(asset_id, synthetic_bars(sessions, seed + asset_id)) for asset_id in range(1, assets + 1)}
    calendar = list(markets[1].bars.index)
    rng = np.random.default_rng(seed)
    signals = pd.DataFrame(rng.uniform(20, 90, (sessions, assets)), index=calendar, columns=list(markets))
    return _inputs(markets, signals)


def _base(params: StrategyParams, calendar: list[str]) -> SimulationConfig:
    return SimulationConfig(
        initial_cash_eur=10_000,
        costs=COSTS,
        params_schedule=((calendar[0], params),),
        stop_loss_percent=None,
        take_profit_percent=None,
        max_pending_sessions=5,
    )


def _result(returns: list[float], calendar: list[str]) -> SimulationResult:
    return SimulationResult(
        equity=pd.DataFrame(),
        trades=(),
        cancelled_orders=(),
        daily_returns=pd.Series(returns, index=calendar[1:], dtype=float),
        costs={},
        turnover=0.0,
        exposure=0.0,
    )


# --- Unita pure -----------------------------------------------------------------------------------------


def test_build_windows_rolls_by_oos_length() -> None:
    calendar = [f"2024-01-{day:02d}" for day in range(1, 21)]

    assert build_windows(calendar, 8, 4) == [(0, 7, 8, 11), (4, 11, 12, 15), (8, 15, 16, 19)]
    # Ultima finestra OOS troncata a fine calendario; con una sola seduta dopo l'in-sample resta una finestra.
    assert build_windows(calendar[:18], 8, 4) == [(0, 7, 8, 11), (4, 11, 12, 15), (8, 15, 16, 17)]
    assert build_windows(calendar[:9], 8, 4) == [(0, 7, 8, 8)]
    assert build_windows(calendar[:8], 8, 4) == []
    for windows in (build_windows(calendar, 8, 4), build_windows(calendar, 5, 3)):
        # OOS contigue e senza sovrapposizioni fino a fine calendario; IS = le sedute appena prima dell'OOS.
        assert [w[2] for w in windows[1:]] == [w[3] + 1 for w in windows[:-1]]
        assert windows[-1][3] == len(calendar) - 1
        assert all(w[2] == w[1] + 1 for w in windows)
    with pytest.raises(ValueError):
        build_windows(calendar, 0, 4)
    with pytest.raises(ValueError):
        build_windows(calendar, 8, 0)


def test_grid_sizes() -> None:
    base = StrategyParams("SCORE_THRESHOLD", max_asset_weight=0.2, top_n=4, rebalance_frequency="DAILY")

    score = parameter_grid("SCORE_THRESHOLD", base)
    top = parameter_grid("TOP_N_SCORE", replace(base, name="TOP_N_SCORE"))
    hold = parameter_grid("BUY_AND_HOLD", replace(base, name="BUY_AND_HOLD"))

    assert (len(score), len(top), len(hold)) == (12, 6, 1)
    assert [(p.buy_threshold, p.sell_threshold) for p in score] == [
        (buy, sell) for buy in (60, 65, 70, 75) for sell in (35, 40, 45)
    ]
    # Gli altri parametri restano quelli del run.
    assert {(p.name, p.max_asset_weight, p.rebalance_frequency) for p in score} == {("SCORE_THRESHOLD", 0.2, "DAILY")}
    assert [(p.top_n, p.rebalance_frequency) for p in top] == [
        (n, frequency) for n in (3, 5, 8) for frequency in ("WEEKLY", "MONTHLY")
    ]
    assert {(p.name, p.max_asset_weight) for p in top} == {("TOP_N_SCORE", 0.2)}
    assert hold == [replace(base, name="BUY_AND_HOLD")]


def test_selection_uses_only_in_sample_returns_and_breaks_ties_on_grid_order() -> None:
    calendar = [f"2024-02-{day:02d}" for day in range(1, 13)]
    windows = build_windows(calendar, 6, 3)
    assert windows == [(0, 5, 6, 8), (3, 8, 9, 11)]
    first = [0.02, -0.01, 0.02, -0.01, 0.02, -0.03, -0.03, 0.01, -0.02, -0.01, 0.0]
    # C e mediocre nell'in-sample della finestra 0 e ottima subito dopo: la finestra 0 non deve vederlo.
    late = [0.0, 0.001, -0.001, 0.0, 0.001, 0.05, 0.06, 0.05, 0.07, 0.04, 0.05]
    grid = [StrategyParams("SCORE_THRESHOLD", buy_threshold=buy) for buy in (60, 65, 70)]
    results = [(grid[0], _result(first, calendar)), (grid[1], _result(first, calendar)), (grid[2], _result(late, calendar))]

    chosen = select_parameters(results, calendar, windows)

    # Finestra 0: rendimenti alle date 1..5 = [0,02; -0,01; 0,02; -0,01; 0,02]: media 0,008, scarti
    # [0,012; -0,018; ...], somma dei quadrati 1,08e-3, varianza campionaria 2,7e-4.
    assert chosen[0] == WalkForwardWindow(
        0, calendar[0], calendar[5], calendar[6], calendar[8], grid[0], pytest.approx(0.008 / math.sqrt(2.7e-4))
    )
    # A parita (A e B identiche) vince la prima nell'ordine della griglia; la finestra 1 vede gli anni buoni di C.
    assert chosen[1].chosen == grid[2]
    assert (chosen[1].is_start, chosen[1].oos_end) == (calendar[3], calendar[11])
    # Nessuna configurazione con Sharpe definito: si sceglie la prima, Sharpe in-sample non definito.
    flat = [(params, _result([0.0] * 11, calendar)) for params in grid]
    assert [(w.chosen, w.is_sharpe) for w in select_parameters(flat, calendar, windows)] == [(grid[0], None)] * 2


def test_selection_ignores_oos_perturbation() -> None:
    inputs = _random_universe()
    base_params = StrategyParams("SCORE_THRESHOLD", max_asset_weight=0.25, rebalance_frequency="DAILY")
    base = _base(base_params, inputs.calendar)
    grid = parameter_grid("SCORE_THRESHOLD", base_params)
    windows = build_windows(inputs.calendar, 120, 60)
    is_end = inputs.calendar[windows[0][1]]
    original = simulate_grid(inputs, base, grid)
    in_sample = [sharpe_daily(result.daily_returns.loc[inputs.calendar[0]:is_end]) for _params, result in original]
    assert len({value for value in in_sample if value is not None}) > 1   # selezione non banale

    rng = np.random.default_rng(99)
    markets = {}
    for asset_id, market in inputs.markets.items():
        bars = market.bars.copy()
        after = bars.index > is_end
        bars.loc[after, EUR_PRICES] = bars.loc[after, EUR_PRICES].mul(np.exp(rng.normal(0, 0.05, after.sum())), axis=0)
        markets[asset_id] = replace(market, bars=bars)
    signals = inputs.signals.copy()
    later = signals.index > is_end
    signals.loc[later] = rng.uniform(20, 90, (int(later.sum()), signals.shape[1]))
    perturbed = replace(inputs, markets=markets, signals=signals)

    before = select_parameters(original, inputs.calendar, windows)
    after = select_parameters(simulate_grid(perturbed, base, grid), inputs.calendar, windows)

    assert after[0] == before[0]
    assert before[0].is_sharpe == max(value for value in in_sample if value is not None)
    assert before[0].chosen == grid[in_sample.index(before[0].is_sharpe)]
    # La perturbazione cambia davvero il periodo fuori campione.
    oos_before = simulate_oos(inputs, base, before).daily_returns
    oos_after = simulate_oos(perturbed, base, after).daily_returns
    assert not np.allclose(oos_before.to_numpy(), oos_after.to_numpy())


def _segmented_inputs(bars: pd.DataFrame, signals: pd.DataFrame) -> UniverseInputs:
    segments, _events, _gaps = split_into_segments(
        bars, asset_type="stock", basis="UNKNOWN", max_gap_sessions=5, split_tolerance=0.03
    )
    market = _market(1, bars)
    for segment_id, segment in enumerate(segments):
        market.bars.loc[segment["date"], "segment_id"] = segment_id
    return _inputs({1: market}, signals)


def _is_sharpes(inputs: UniverseInputs, params: StrategyParams, grid: list[StrategyParams]) -> list[float | None]:
    # Osserviamo lo Sharpe realmente usato dal walk-forward per ogni candidato, senza leggere la griglia globale.
    return [
        run_walk_forward(
            inputs, _base(params, inputs.calendar), [candidate], is_sessions=40, oos_sessions=20
        ).windows[0].is_sharpe
        for candidate in grid
    ]


@pytest.mark.parametrize("change", ["split", "gap", "remove", "add"])
def test_is_results_ignore_oos_segment_changes(change: str) -> None:
    bars = synthetic_bars(60, 137)
    signals = pd.DataFrame({1: np.random.default_rng(1137).uniform(25, 85, 60)}, index=bars["date"])
    split_bars = bars.copy()
    split_bars.loc[40, DB_PRICES] *= 0.5
    original_bars, changed_bars = bars, split_bars
    if change == "gap":
        changed_bars = bars.drop(index=range(40, 46))
    elif change == "remove":
        original_bars, changed_bars = split_bars, split_bars.drop(index=40)
    elif change == "add":
        original_bars, changed_bars = bars.drop(index=40), split_bars
    cutoff = str(bars["date"].iloc[39])
    original = _segmented_inputs(original_bars, signals)
    changed = _segmented_inputs(changed_bars, signals)
    pd.testing.assert_frame_equal(original.markets[1].bars.loc[:cutoff], changed.markets[1].bars.loc[:cutoff])
    pd.testing.assert_frame_equal(original.signals.loc[:cutoff], changed.signals.loc[:cutoff])
    params = StrategyParams("SCORE_THRESHOLD", max_asset_weight=1.0, rebalance_frequency="DAILY")
    grid = parameter_grid(params.name, params)
    before = run_walk_forward(original, _base(params, original.calendar), grid, is_sessions=40, oos_sessions=20)
    after = run_walk_forward(changed, _base(params, changed.calendar), grid, is_sessions=40, oos_sessions=20)
    before_sharpes, after_sharpes = _is_sharpes(original, params, grid), _is_sharpes(changed, params, grid)
    assert len(set(before_sharpes)) > 1  # La selezione non e' banale.
    assert after_sharpes == before_sharpes
    first, second = before.windows[0], after.windows[0]
    assert (second.is_start, second.is_end, second.chosen, second.is_sharpe) == (
        first.is_start, first.is_end, first.chosen, first.is_sharpe
    )
    defined = [value for value in before_sharpes if value is not None]
    assert first.is_sharpe == max(defined)
    assert first.chosen == grid[before_sharpes.index(first.is_sharpe)]
    # I run globali conservati per i tentativi vedono invece il vero cambiamento OOS.
    assert any(
        not left.equity.equals(right.equity)
        for (_p, left), (_q, right) in zip(before.grid_results, after.grid_results, strict=True)
    )
    assert not before.oos.equity.equals(after.oos.equity)


@pytest.mark.parametrize("split_at", [None, 30, 40])
def test_in_sample_sharpe_includes_terminal_return_and_known_segment_exits(split_at: int | None) -> None:
    bars = synthetic_bars(60, 137)
    if split_at is not None:
        bars.loc[split_at, DB_PRICES] *= 0.5
    signals = pd.DataFrame({1: 80.0}, index=bars["date"])
    inputs = _segmented_inputs(bars, signals)
    params = StrategyParams("BUY_AND_HOLD", max_asset_weight=1.0, rebalance_frequency="DAILY")
    base = _base(params, inputs.calendar)
    result = run_walk_forward(inputs, base, [params], is_sessions=40, oos_sessions=20)
    reference = simulate(inputs.markets, inputs.signals, inputs.calendar[:40], base)
    assert reference.daily_returns.index[-1] == inputs.calendar[39]
    expected = sharpe_daily(reference.daily_returns)
    assert expected is not None
    assert result.windows[0].is_sharpe == expected
    assert expected != sharpe_daily(reference.daily_returns.iloc[:-1])
    exits = [trade for trade in reference.trades if trade.reason == "SEGMENT_EXIT"]
    if split_at == 30:
        assert exits and exits[0].date == inputs.calendar[29]
        assert exits[0].commission_eur == COSTS.commission_eur
    else:
        assert exits == []
        assert reference.equity["invested_eur"].iloc[-1] > 0


def test_rolling_is_preserves_history_before_window_start() -> None:
    inputs = _random_universe(assets=1, sessions=80, seed=137)
    params = StrategyParams("BUY_AND_HOLD", max_asset_weight=1.0, rebalance_frequency="DAILY")
    base = _base(params, inputs.calendar)
    run = run_walk_forward(inputs, base, [params], is_sessions=40, oos_sessions=20)
    window = run.windows[1]
    assert (window.index, window.is_start, window.is_end) == (1, inputs.calendar[20], inputs.calendar[59])
    history = simulate(inputs.markets, inputs.signals, inputs.calendar[:60], base)
    expected = sharpe_daily(history.daily_returns.loc[window.is_start:window.is_end])
    reset = simulate(inputs.markets, inputs.signals, inputs.calendar[20:60], base)
    assert window.is_sharpe == expected
    assert expected != sharpe_daily(reset.daily_returns)
    assert history.trades[0].date < window.is_start


def test_is_ignores_next_segment_of_asset_missing_at_cutoff() -> None:
    # Una seconda lane mantiene il calendario: l'ultimo prezzo A precede is_end di due sedute.
    bars = synthetic_bars(60, 137).drop(index=[38, 39])
    signals = pd.DataFrame({1: 80.0, 2: np.nan}, index=synthetic_bars(60, 138)["date"])
    original = _segmented_inputs(bars, signals)
    changed_bars = bars.copy()
    changed_bars.loc[40, DB_PRICES] *= 0.5
    changed = _segmented_inputs(changed_bars, signals)
    calendar_market = _market(2, synthetic_bars(60, 138))
    original = _inputs({**original.markets, 2: calendar_market}, signals)
    changed = _inputs({**changed.markets, 2: calendar_market}, signals)
    params = StrategyParams("SCORE_THRESHOLD", max_asset_weight=1.0, rebalance_frequency="DAILY")
    first = run_walk_forward(original, _base(params, original.calendar), [params], is_sessions=40, oos_sessions=20)
    second = run_walk_forward(changed, _base(params, changed.calendar), [params], is_sessions=40, oos_sessions=20)
    assert second.windows[0] == first.windows[0]


def test_oos_only_features_cannot_admit_asset_to_is() -> None:
    inputs = _random_universe(assets=2, sessions=60, seed=137)
    inputs.signals.loc[inputs.calendar[:40], 2] = np.nan
    # NO_FEATURES nel builder globale puo' eliminare il secondo asset dopo una revisione solo OOS.
    changed = _inputs({1: inputs.markets[1]}, inputs.signals)
    params = StrategyParams("BUY_AND_HOLD", max_asset_weight=1.0, rebalance_frequency="DAILY")
    first = run_walk_forward(inputs, _base(params, inputs.calendar), [params], is_sessions=40, oos_sessions=20)
    second = run_walk_forward(changed, _base(params, changed.calendar), [params], is_sessions=40, oos_sessions=20)
    assert first.windows[0] == second.windows[0]
    assert not first.grid_results[0][1].equity.equals(second.grid_results[0][1].equity)




def test_is_eligibility_requires_signal_on_an_asset_bar() -> None:
    inputs = _random_universe(assets=2, sessions=60, seed=137)
    inputs.markets[2] = replace(inputs.markets[2], bars=inputs.markets[2].bars.drop(inputs.calendar[11:40]))
    inputs.signals.loc[inputs.calendar[:40], 2] = np.nan
    inputs.signals.loc[inputs.calendar[20], 2] = 80.0  # as-of valido, ma nessuna barra EUR dell'asset quel giorno
    changed = _inputs({1: inputs.markets[1]}, inputs.signals)
    params = StrategyParams("BUY_AND_HOLD", max_asset_weight=0.5, rebalance_frequency="DAILY")
    first = run_walk_forward(inputs, _base(params, inputs.calendar), [params], is_sessions=40, oos_sessions=20)
    second = run_walk_forward(changed, _base(params, changed.calendar), [params], is_sessions=40, oos_sessions=20)
    assert first.windows[0] == second.windows[0]

def test_is_without_eligible_assets_is_flat_and_uses_first_candidate() -> None:
    inputs = _random_universe(assets=1, sessions=60, seed=137)
    inputs.signals.loc[inputs.calendar[:40], 1] = np.nan
    params = StrategyParams("SCORE_THRESHOLD", max_asset_weight=1.0, rebalance_frequency="DAILY")
    grid = parameter_grid(params.name, params)
    result = run_walk_forward(inputs, _base(params, inputs.calendar), grid, is_sessions=40, oos_sessions=20)
    assert (result.windows[0].chosen, result.windows[0].is_sharpe) == (grid[0], None)
    assert result.oos.equity["invested_eur"].max() > 0

def test_walk_forward_reports_and_cancels_during_is_simulations() -> None:
    inputs = _random_universe(sessions=80)
    params = StrategyParams("TOP_N_SCORE", top_n=2, rebalance_frequency="DAILY")
    grid = parameter_grid(params.name, params)
    progress: list[float] = []

    def cancel_in_is(value: float) -> None:
        progress.append(value)
        if len(progress) > len(grid) and value < 1.0:
            raise RuntimeError("CANCEL_DURING_IS")

    with pytest.raises(RuntimeError, match="CANCEL_DURING_IS"):
        run_walk_forward(
            inputs, _base(params, inputs.calendar), grid, is_sessions=40, oos_sessions=20, progress=cancel_in_is
        )
    assert progress == sorted(progress)
    assert 0 < progress[-1] < 1


@pytest.mark.parametrize("window_index", [0, 1, 2])
def test_each_rolling_window_ignores_data_after_its_own_cutoff(window_index: int) -> None:
    bars = synthetic_bars(100, 137)
    signals = pd.DataFrame({1: np.random.default_rng(1137).uniform(25, 85, 100)}, index=bars["date"])
    inputs = _segmented_inputs(bars, signals)
    cutoff_index = 39 + 20 * window_index
    changed_bars = bars.copy()
    changed_bars.loc[cutoff_index + 1, DB_PRICES] *= 0.5
    changed = _segmented_inputs(changed_bars, signals)
    params = StrategyParams("SCORE_THRESHOLD", max_asset_weight=1.0, rebalance_frequency="DAILY")
    grid = parameter_grid(params.name, params)
    before = run_walk_forward(inputs, _base(params, inputs.calendar), grid, is_sessions=40, oos_sessions=20)
    after = run_walk_forward(changed, _base(params, changed.calendar), grid, is_sessions=40, oos_sessions=20)
    assert before.windows[window_index] == after.windows[window_index]
    # Non imponiamo invarianza alle finestre successive: includono legittimamente i dati modificati.
    for candidate in grid:
        first = run_walk_forward(inputs, _base(params, inputs.calendar), [candidate], is_sessions=40, oos_sessions=20)
        second = run_walk_forward(changed, _base(params, changed.calendar), [candidate], is_sessions=40, oos_sessions=20)
        assert first.windows[window_index].is_sharpe == second.windows[window_index].is_sharpe


def test_oos_is_one_simulation_with_parameter_schedule() -> None:
    # Prezzi costanti: nessuna deriva dei pesi, quindi ogni operazione viene solo dai parametri.
    dates = pd.bdate_range("2024-03-01", periods=40).strftime("%Y-%m-%d")
    markets = {
        asset_id: _market(asset_id, pd.DataFrame({"date": dates, "open": price, "high": price, "low": price, "close": price}))
        for asset_id, price in ((1, 100.0), (2, 50.0))
    }
    calendar = list(dates)
    signals = pd.DataFrame({1: 80.0, 2: 70.0}, index=calendar)
    inputs = _inputs(markets, signals)
    one = StrategyParams("TOP_N_SCORE", max_asset_weight=0.5, top_n=1, rebalance_frequency="DAILY")
    two = replace(one, top_n=2)
    windows = [
        WalkForwardWindow(0, calendar[0], calendar[19], calendar[20], calendar[29], one, 0.1),
        WalkForwardWindow(1, calendar[10], calendar[29], calendar[30], calendar[39], two, 0.2),
    ]

    result = simulate_oos(inputs, _base(one, calendar), windows)

    # Un'unica simulazione dalla prima seduta OOS a fine calendario.
    assert result.equity["date"].tolist() == calendar[20:]
    trades = [(trade.date, trade.asset_id, trade.side, trade.reason) for trade in result.trades]
    # Decisione alla chiusura della prima seduta OOS; il secondo asset entra solo con i parametri della finestra 1
    # (decisione il 30, esecuzione il 31); la posizione aperta prosegue: nessuna vendita o SEGMENT_EXIT al cambio.
    assert trades == [(calendar[21], 1, "BUY", "SIGNAL"), (calendar[31], 2, "BUY", "SIGNAL")]


def test_period_too_short_raises() -> None:
    inputs = _random_universe(sessions=50)
    params = StrategyParams("TOP_N_SCORE", top_n=2, rebalance_frequency="DAILY")
    base = _base(params, inputs.calendar)
    grid = parameter_grid("TOP_N_SCORE", params)

    with pytest.raises(LabError) as error:
        run_walk_forward(inputs, base, grid, is_sessions=50, oos_sessions=10)

    assert error.value.code == "LAB_PERIOD_TOO_SHORT"
    assert "50" in error.value.message
    run = run_walk_forward(inputs, base, grid, is_sessions=40, oos_sessions=6)
    assert [(w.oos_start, w.oos_end) for w in run.windows] == [
        (inputs.calendar[40], inputs.calendar[45]), (inputs.calendar[46], inputs.calendar[49])
    ]
    assert [params for params, _result in run.grid_results] == grid
    assert run.oos.equity["date"].tolist() == inputs.calendar[40:]


def test_walk_forward_settings_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LAB_WF_IS_SESSIONS", "LAB_WF_OOS_SESSIONS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    try:
        assert (get_settings().lab_wf_is_sessions, get_settings().lab_wf_oos_sessions) == (504, 126)
        monkeypatch.setenv("LAB_WF_IS_SESSIONS", "252")
        monkeypatch.setenv("LAB_WF_OOS_SESSIONS", "63")
        get_settings.cache_clear()
        assert (get_settings().lab_wf_is_sessions, get_settings().lab_wf_oos_sessions) == (252, 63)
    finally:
        get_settings.cache_clear()


def test_walk_forward_payload_validation() -> None:
    base = {
        "name": "WF", "strategy_name": "TOP_N_SCORE", "symbols": ["AAA"], "start_date": "2024-01-02",
        "end_date": "2024-06-28",
    }

    payload = WalkForwardIn(**base, folds=4)   # campo del contratto a fold ignorato

    assert (payload.is_sessions, payload.oos_sessions, payload.data_mode) == (None, None, "REAL")
    assert "folds" not in WalkForwardIn.model_fields
    assert WalkForwardIn(**base, is_sessions=252, oos_sessions=63).oos_sessions == 63
    for override in ({"is_sessions": 1}, {"oos_sessions": 0}, {"is_sessions": 10_001}):
        with pytest.raises(ValidationError):
            WalkForwardIn(**base, **override)


# --- Motore e registro dei tentativi --------------------------------------------------------------------


def _real_asset(connection: sqlite3.Connection, symbol: str, seed: int) -> pd.DataFrame:
    asset_id = insert_asset(connection, symbol)
    bars = synthetic_bars(BARS, seed)
    insert_bars(connection, asset_id, bars, real=True, provider="stooq")
    connection.commit()
    return bars


def _demo_asset(connection: sqlite3.Connection, symbol: str, seed: int) -> pd.DataFrame:
    asset_id = insert_asset(connection, symbol)
    bars = synthetic_bars(BARS, seed)
    insert_bars(connection, asset_id, bars, real=False, provider=None)
    connection.commit()
    return bars


def _payload_data(bars: pd.DataFrame, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "WF v1",
        "strategy_name": "TOP_N_SCORE",
        "symbols": SYMBOLS,
        "initial_cash": 10_000,
        "start_date": str(bars["date"].iloc[260]),
        "end_date": str(bars["date"].iloc[-1]),
        "benchmark_symbol": "SPY",
        "max_asset_weight": 0.3,
        "stop_loss_percent": None,
        "take_profit_percent": None,
        "rebalance_frequency": "WEEKLY",
        "top_n": 3,
        "is_sessions": 120,
        "oos_sessions": 60,
    }
    data.update(overrides)
    return data


def _trials(connection: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            "SELECT kind, config_hash, fingerprint, sharpe_daily, n_obs, job_id FROM lab_trials ORDER BY id"
        )
    ]


def _grid_hashes(strategy: str, payload: WalkForwardIn) -> list[str]:
    base = StrategyParams(
        strategy, buy_threshold=payload.buy_threshold, sell_threshold=payload.sell_threshold,
        max_asset_weight=payload.max_asset_weight, top_n=payload.top_n or 5,
        rebalance_frequency=payload.rebalance_frequency,
    )
    return [
        canonical_hash(
            trial_config(
                params, signal_name="score", signal_timeframe="D", stop_loss_percent=None, take_profit_percent=None,
                costs=CostProfile.from_settings(), initial_cash_eur=10_000, symbols=payload.symbols,
            )
        )
        for params in parameter_grid(strategy, base)  # type: ignore[arg-type]
    ]


def test_walk_forward_records_one_trial_per_grid_config_and_reports_dsr(lab_connection: sqlite3.Connection) -> None:
    bars = [_real_asset(lab_connection, symbol, seed) for seed, symbol in enumerate(SYMBOLS, start=7)][0]
    payload = WalkForwardIn(**_payload_data(bars))
    engine = BacktestEngine()

    result = engine.walk_forward(lab_connection, payload, job_id=41, now=NOW)

    assert (result["strategy_name"], result["data_mode"], result["grid_size"]) == ("TOP_N_SCORE", "REAL", 6)
    assert (result["window_is_sessions"], result["window_oos_sessions"]) == (120, 60)
    trials = _trials(lab_connection)
    assert [row[0] for row in trials] == ["WF_GRID"] * 6
    assert [row[1] for row in trials] == _grid_hashes("TOP_N_SCORE", payload)
    assert all(len(row[2]) == 64 and row[5] == 41 for row in trials)
    assert result["n_trials"] == 6

    windows = result["windows"]
    sessions = 440   # sedute del periodo: dalla barra 260 alla 699
    assert result["oos_sessions"] == sessions - 120
    assert [w["index"] for w in windows] == list(range(len(windows)))
    assert windows[0]["oos_start"] == str(bars["date"].iloc[260 + 120])
    assert windows[-1]["oos_end"] == payload.end_date
    assert all(w["chosen"]["name"] == "TOP_N_SCORE" and w["chosen"]["top_n"] in (3, 5, 8) for w in windows)
    assert result["oos_metrics"]["start_date"] == windows[0]["oos_start"]

    dsr = result["dsr"]
    assert dsr is not None
    assert (dsr["n_trials"], dsr["n_obs"]) == (6, result["oos_sessions"] - 1)
    assert 0.0 <= dsr["dsr"] <= 1.0
    # SR0 dalla formula della spec sugli Sharpe della famiglia (ultimo per configurazione), con pandas e NormalDist.
    sharpes = pd.Series([row[3] for row in trials])
    inv = NormalDist().inv_cdf
    sr0 = math.sqrt(sharpes.var(ddof=1)) * (
        (1 - EULER_MASCHERONI) * inv(1 - 1 / 6) + EULER_MASCHERONI * inv(1 - 1 / (6 * math.e))
    )
    assert dsr["sr0"] == pytest.approx(sr0, abs=1e-6)
    assert result["oos_sharpe"] == pytest.approx(dsr["sr"] * math.sqrt(252), abs=1e-5)
    in_sample = [w["is_sharpe"] for w in windows if w["is_sharpe"] is not None]
    assert in_sample
    assert result["is_sharpe_mean"] == pytest.approx(sum(in_sample) / len(in_sample), abs=1e-5)
    assert result["degradation"] == pytest.approx(result["is_sharpe_mean"] - result["oos_sharpe"], abs=1e-5)

    # Rieseguire la stessa griglia non fa crescere N; un backtest con una configurazione della griglia nemmeno
    # (stessa simulazione sull'intero periodo, stesso Sharpe); una configurazione nuova si'.
    again = engine.walk_forward(lab_connection, payload, now=NOW)
    assert (again["n_trials"], len(_trials(lab_connection))) == (6, 12)
    backtest = {key: value for key, value in _payload_data(bars).items() if key not in {"is_sessions", "oos_sessions"}}
    engine.run_backtest(lab_connection, BacktestRunIn(**backtest), now=NOW)
    family = family_key("score", "D")
    assert len(family_trial_sharpes(lab_connection, family)) == 6
    last = _trials(lab_connection)[-1]
    assert last[0] == "BACKTEST"
    assert last[1] == trials[0][1]
    assert last[3] == pytest.approx(trials[0][3])
    engine.run_backtest(lab_connection, BacktestRunIn(**{**backtest, "top_n": 4}), now=NOW)
    assert len(family_trial_sharpes(lab_connection, family)) == 7
    assert engine.walk_forward(lab_connection, payload, now=NOW)["n_trials"] == 7


def test_engine_selection_ignores_oos_price_perturbation(lab_connection: sqlite3.Connection) -> None:
    bars = [_real_asset(lab_connection, symbol, seed) for seed, symbol in enumerate(SYMBOLS, start=7)][0]
    payload = WalkForwardIn(**_payload_data(bars))
    engine = BacktestEngine()
    before = engine.walk_forward(lab_connection, payload, now=NOW)
    is_end = before["windows"][0]["is_end"]

    rng = np.random.default_rng(5)
    rows = lab_connection.execute("SELECT id FROM price_history WHERE date > ? ORDER BY id", (is_end,)).fetchall()
    lab_connection.executemany(
        "UPDATE price_history SET open = open * ?1, high = high * ?1, low = low * ?1, close = close * ?1, "
        "adjusted_close = adjusted_close * ?1 WHERE id = ?2",
        [(float(np.exp(rng.normal(0, 0.01))), int(row[0])) for row in rows],
    )
    lab_connection.commit()

    after = engine.walk_forward(lab_connection, payload, now=NOW)

    assert after["windows"][0] == before["windows"][0]
    assert after["oos_metrics"] != before["oos_metrics"]
    # Dati nuovi, stesse configurazioni: impronte diverse, N invariato.
    trials = _trials(lab_connection)
    assert [row[1] for row in trials[:6]] == [row[1] for row in trials[6:]]
    assert {row[2] for row in trials[:6]}.isdisjoint({row[2] for row in trials[6:]})
    assert after["n_trials"] == 6



@pytest.mark.parametrize("unique_is_date", [False, True])
def test_engine_oos_warmup_cannot_change_is_eligibility_or_calendar(
    lab_connection: sqlite3.Connection, unique_is_date: bool
) -> None:
    anchor = synthetic_bars(700, 7)
    young = synthetic_bars(310, 8, start=str(anchor["date"].iloc[150]))
    anchor_id = insert_asset(lab_connection, "ANCHOR")
    young_id = insert_asset(lab_connection, "YOUNG")
    # Questa seduta IS resta solo in YOUNG: NO_FEATURES globale non deve cancellarla dal calendario.
    anchor_rows = anchor.drop(index=264) if unique_is_date else anchor
    insert_bars(lab_connection, anchor_id, anchor_rows, real=True, provider="stooq")
    insert_bars(lab_connection, young_id, young, real=True, provider="stooq")
    lab_connection.commit()
    payload = WalkForwardIn(**_payload_data(
        anchor, symbols=["ANCHOR", "YOUNG"], strategy_name="BUY_AND_HOLD",
        end_date=str(anchor["date"].iloc[459]), max_asset_weight=0.5, oos_sessions=80,
    ))
    engine = BacktestEngine()
    before = engine.walk_forward(lab_connection, payload, now=NOW)
    cutoff = str(anchor["date"].iloc[379])
    assert before["windows"][0]["is_end"] == cutoff

    def universe() -> UniverseInputs:
        return build_universe_inputs(
            lab_connection, payload.symbols, data_mode="REAL", signal_name="score", signal_timeframe="D",
            start=payload.start_date, end=payload.end_date, now=NOW,
        )

    before_inputs = universe()
    assert young_id in before_inputs.markets
    assert not np.isfinite(before_inputs.signals.loc[:cutoff, young_id].to_numpy()).any()
    assert np.isfinite(before_inputs.signals[young_id].to_numpy()).any()
    raw_is = list(lab_connection.execute(
        "SELECT asset_id, date, open, high, low, close, adjusted_close FROM price_history "
        "WHERE date <= ? ORDER BY asset_id, date", (cutoff,),
    ))
    # Rapporto 2:1 esatto alla prima barra OOS: cambia il segmento e cancella il warm-up successivo.
    factor = float(young["close"].iloc[229] / (2 * young["close"].iloc[230]))
    lab_connection.execute(
        "UPDATE price_history SET open=open*?1, high=high*?1, low=low*?1, close=close*?1, "
        "adjusted_close=adjusted_close*?1 WHERE asset_id=?2 AND date=?3",
        (factor, young_id, str(anchor["date"].iloc[380])),
    )
    lab_connection.commit()
    after = engine.walk_forward(lab_connection, payload, now=NOW)
    after_inputs = universe()
    assert after_inputs.excluded["YOUNG"] == "NO_FEATURES"
    assert list(lab_connection.execute(
        "SELECT asset_id, date, open, high, low, close, adjusted_close FROM price_history "
        "WHERE date <= ? ORDER BY asset_id, date", (cutoff,),
    )) == raw_is
    assert after["windows"][0] == before["windows"][0]
    assert [(w["is_start"], w["is_end"], w["oos_start"], w["oos_end"]) for w in after["windows"]] == [
        (w["is_start"], w["is_end"], w["oos_start"], w["oos_end"]) for w in before["windows"]
    ]
    assert after["oos_metrics"] != before["oos_metrics"]

def test_real_grid_without_variation_records_no_trial_and_declares_it(lab_connection: sqlite3.Connection) -> None:
    bars = [_real_asset(lab_connection, symbol, seed) for seed, symbol in enumerate(SYMBOLS, start=7)][0]
    # `close_return_1d` vale circa +-0,02: le soglie di acquisto 60..75 non scattano mai, nessuna operazione.
    payload = WalkForwardIn(**_payload_data(bars, strategy_name="SCORE_THRESHOLD", signal_name="close_return_1d"))

    result = BacktestEngine().walk_forward(lab_connection, payload, now=NOW)

    assert (result["grid_size"], result["n_trials"], result["dsr"]) == (12, 0, None)
    assert result["oos_metrics"]["total_trades"] == 0
    assert all(window["is_sharpe"] is None for window in result["windows"])
    assert "DSR non calcolabile: rendimenti fuori campione senza variazioni." in result["warnings"]
    assert any(warning.startswith("12 configurazioni della griglia senza Sharpe") for warning in result["warnings"])
    assert _trials(lab_connection) == []


def test_precheck_counts_sessions_of_the_run_data_mode(lab_connection: sqlite3.Connection) -> None:
    bars = _real_asset(lab_connection, "PRA", seed=7)
    demo_id = insert_asset(lab_connection, "PRD")
    insert_bars(lab_connection, demo_id, synthetic_bars(BARS, 8), real=False, provider=None)
    lab_connection.commit()
    engine = BacktestEngine()
    start, end = str(bars["date"].iloc[260]), str(bars["date"].iloc[359])   # 100 sedute reali

    def check(**overrides: object) -> None:
        engine.precheck_walk_forward(
            lab_connection, WalkForwardIn(**_payload_data(bars, start_date=start, end_date=end, **overrides))
        )

    check(symbols=["PRA"], is_sessions=99)
    for overrides in (
        {"symbols": ["PRA"], "is_sessions": 100},                        # serve almeno una seduta fuori campione
        {"symbols": ["PRD"], "is_sessions": 99},                         # nessuna seduta REAL
        {"symbols": ["NOPE"], "is_sessions": 2},
        {"symbols": ["PRA"], "is_sessions": None},                       # default 504
    ):
        with pytest.raises(LabError) as error:
            check(**overrides)
        assert error.value.code == "LAB_PERIOD_TOO_SHORT"
    check(symbols=["PRD"], is_sessions=99, data_mode="DEMO")


def test_demo_walk_forward_has_no_trials_and_no_dsr(lab_connection: sqlite3.Connection) -> None:
    bars = [_demo_asset(lab_connection, symbol, seed) for seed, symbol in enumerate(SYMBOLS, start=7)][0]
    payload = WalkForwardIn(**_payload_data(bars, data_mode="DEMO", strategy_name="SCORE_THRESHOLD"))

    result = BacktestEngine().walk_forward(lab_connection, payload, now=NOW)

    assert (result["data_mode"], result["grid_size"], result["dsr"], result["n_trials"]) == ("DEMO", 12, None, None)
    assert result["windows"]
    assert result["warnings"][0].startswith("Run DEMO")
    assert any(warning.startswith("DSR non calcolato") for warning in result["warnings"])
    assert _trials(lab_connection) == []


# --- Job ------------------------------------------------------------------------------------------------


def _freeze_handler_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return NOW.replace(tzinfo=None) if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr("backend.app.lab.handlers.datetime", FrozenDatetime)


def test_walk_forward_job_cancel_and_sanitized_failure(
    lab_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.lab import handlers  # noqa: F401 - registra WALK_FORWARD
    from backend.app.lab.jobs import JobService
    from backend.app.services import backtest_engine as engine_module

    _freeze_handler_clock(monkeypatch)
    bars = [_real_asset(lab_connection, symbol, seed) for seed, symbol in enumerate(SYMBOLS, start=7)][0]
    service = JobService("inline")

    succeeded = service.enqueue("WALK_FORWARD", WalkForwardIn(**_payload_data(bars)).model_dump(mode="json"))

    assert succeeded.status == "SUCCEEDED", succeeded.error_code
    assert succeeded.result_ref is None
    assert {"windows", "dsr", "n_trials", "oos_metrics"} <= set(succeeded.result or {})
    assert {row[5] for row in _trials(lab_connection)} == {succeeded.id}

    too_short = service.enqueue(
        "WALK_FORWARD", WalkForwardIn(**_payload_data(bars, is_sessions=440)).model_dump(mode="json")
    )

    assert (too_short.status, too_short.error_code) == ("FAILED", "LAB_PERIOD_TOO_SHORT")
    assert "440" in (too_short.error_message or "")
    assert len(_trials(lab_connection)) == 6

    original = engine_module.build_universe_inputs

    def cancel_after_universe(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        inputs = original(*args, **kwargs)
        other = get_connection()
        try:
            other.execute("UPDATE lab_jobs SET cancel_requested = 1 WHERE status = 'RUNNING'")
            other.commit()
        finally:
            other.close()
        return inputs

    monkeypatch.setattr(engine_module, "build_universe_inputs", cancel_after_universe)
    cancelled = service.enqueue(
        "WALK_FORWARD", WalkForwardIn(**_payload_data(bars, oos_sessions=50)).model_dump(mode="json")
    )

    assert cancelled.status == "CANCELLED"
    assert len(_trials(lab_connection)) == 6

@pytest.mark.parametrize("change", ["replace", "append"])
def test_engine_is_selection_ignores_future_provider(lab_connection, change) -> None:
    bars = synthetic_bars(701, seed=137, start="2020-01-01", freq="D")
    previous = bars.loc[299, "close"]
    bars.loc[300, ["open", "high", "low", "close"]] = [previous, previous*1.01, previous*0.99, previous]
    bars.loc[300:, ["open", "high", "low", "close", "adjusted_close"]] *= 0.5
    bars["adjusted_close"] = bars["close"]
    asset_id = insert_asset(lab_connection, "PROVIDER", asset_type="crypto")
    insert_bars(lab_connection, asset_id, bars.iloc[:700], real=True, provider="coingecko")
    lab_connection.commit()
    payload = WalkForwardIn(**_payload_data(bars.iloc[:700], symbols=["PROVIDER"], benchmark_symbol="PROVIDER"))
    engine = BacktestEngine()
    before = engine.walk_forward(lab_connection, payload, now=NOW)
    assert all(w["is_sharpe"] is not None for w in before["windows"])
    if change == "replace":
        lab_connection.execute("UPDATE price_history SET provider='manual' WHERE asset_id=? AND date=?",
                               (asset_id, bars.iloc[699]["date"]))
    else:
        insert_bars(lab_connection, asset_id, bars.iloc[700:], real=True, provider="manual")
    lab_connection.commit()
    after = engine.walk_forward(lab_connection, payload, now=NOW)
    assert [(w["is_start"], w["is_end"], w["is_sharpe"], w["chosen"]) for w in before["windows"]] == [
        (w["is_start"], w["is_end"], w["is_sharpe"], w["chosen"]) for w in after["windows"]
    ]
