"""Walk-forward vero (spec SP1 §8.3): finestre mobili, griglia, selezione in-sample e OOS con calendario dei parametri.

1. Ogni configurazione della griglia viene simulata una volta sull'intero periodo (`simulate_grid`).
2. Finestre mobili sul calendario dell'universo: in-sample di `is_sessions` sedute, fuori campione di `oos_sessions`,
   passo = OOS; l'ultima finestra OOS e troncata a fine calendario (`build_windows`).
3. Per ogni finestra si sceglie la configurazione con lo Sharpe netto piu alto sui soli rendimenti giornalieri datati
   dentro la finestra in-sample (`select_parameters`): nessuna informazione successiva a `is_end` entra nella scelta.
   A parita vince la configurazione che precede nella griglia; senza Sharpe definiti si sceglie la prima.
4. Il periodo OOS e un'unica simulazione dalla prima seduta OOS a fine calendario: i parametri cambiano all'inizio di
   ogni finestra OOS (`params_schedule`) e il portafoglio prosegue senza liquidazioni forzate (`simulate_oos`).

Unita pure, senza database: registro dei tentativi e DSR restano al chiamante (`BacktestEngine.walk_forward`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from backend.app.lab.contracts import LabError
from backend.app.lab.simulator import SimulationConfig, SimulationResult, simulate
from backend.app.lab.stats import sharpe_daily
from backend.app.lab.strategies import RebalanceFrequency, StrategyName, StrategyParams
from backend.app.lab.universe import UniverseInputs

SCORE_THRESHOLD_BUY: tuple[float, ...] = (60, 65, 70, 75)
SCORE_THRESHOLD_SELL: tuple[float, ...] = (35, 40, 45)
TOP_N_VALUES: tuple[int, ...] = (3, 5, 8)
TOP_N_FREQUENCIES: tuple[RebalanceFrequency, ...] = ("WEEKLY", "MONTHLY")

WindowBounds = tuple[int, int, int, int]   # (is_start, is_end, oos_start, oos_end), indici inclusivi del calendario
GridResults = Sequence[tuple[StrategyParams, SimulationResult]]
Progress = Callable[[float], None]


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    chosen: StrategyParams
    is_sharpe: float | None   # Sharpe giornaliero (non annualizzato) dei soli rendimenti in-sample della scelta


@dataclass(frozen=True)
class WalkForwardRun:
    windows: tuple[WalkForwardWindow, ...]
    grid_results: tuple[tuple[StrategyParams, SimulationResult], ...]
    oos: SimulationResult


def parameter_grid(strategy: StrategyName, base: StrategyParams) -> list[StrategyParams]:
    """Griglia della spec §8.3 nell'ordine di parita; stop, peso massimo e gli altri parametri restano quelli del run."""
    base = replace(base, name=strategy)
    if strategy == "SCORE_THRESHOLD":
        return [
            replace(base, buy_threshold=float(buy), sell_threshold=float(sell))
            for buy in SCORE_THRESHOLD_BUY
            for sell in SCORE_THRESHOLD_SELL
        ]
    if strategy == "TOP_N_SCORE":
        return [
            replace(base, top_n=top_n, rebalance_frequency=frequency)
            for top_n in TOP_N_VALUES
            for frequency in TOP_N_FREQUENCIES
        ]
    return [base]


def build_windows(calendar: Sequence[str], is_sessions: int, oos_sessions: int) -> list[WindowBounds]:
    """Finestre mobili (passo = OOS); lista vuota se il calendario non supera la finestra in-sample."""
    if is_sessions < 1 or oos_sessions < 1:
        raise ValueError("Le finestre in-sample e fuori campione devono avere almeno una seduta.")
    total = len(calendar)
    windows: list[WindowBounds] = []
    is_start = 0
    while is_start + is_sessions < total:
        is_end = is_start + is_sessions - 1
        oos_start = is_end + 1
        windows.append((is_start, is_end, oos_start, min(oos_start + oos_sessions - 1, total - 1)))
        is_start += oos_sessions
    return windows


def period_too_short_error(available: int, is_sessions: int) -> LabError:
    return LabError(
        "LAB_PERIOD_TOO_SHORT",
        f"Periodo troppo corto per il walk-forward: servono piu di {is_sessions} sedute (finestra in-sample), "
        f"il periodo ne ha {available}.",
    )


def simulate_grid(
    inputs: UniverseInputs,
    base: SimulationConfig,
    grid: Sequence[StrategyParams],
    *,
    progress: Progress | None = None,
) -> list[tuple[StrategyParams, SimulationResult]]:
    """Ogni configurazione simulata una volta sull'intero calendario; `progress` riceve la quota completata."""
    results: list[tuple[StrategyParams, SimulationResult]] = []
    for index, params in enumerate(grid):
        config = replace(base, params_schedule=((inputs.calendar[0], params),))
        results.append((params, simulate(inputs.markets, inputs.signals, inputs.calendar, config)))
        if progress is not None:
            progress((index + 1) / len(grid))
    return results


def select_parameters(
    grid_results: GridResults, calendar: Sequence[str], windows: Sequence[WindowBounds]
) -> list[WalkForwardWindow]:
    """Configurazione con lo Sharpe netto piu alto sui soli rendimenti datati in `[is_start, is_end]`."""
    if not grid_results:
        raise ValueError("La griglia del walk-forward e vuota.")
    days = [str(day) for day in calendar]
    selected: list[WalkForwardWindow] = []
    for number, (is_start, is_end, oos_start, oos_end) in enumerate(windows):
        start, end = days[is_start], days[is_end]
        best_params, best_sharpe = grid_results[0][0], None
        for params, result in grid_results:
            returns = result.daily_returns
            sharpe = sharpe_daily(returns[(returns.index >= start) & (returns.index <= end)])
            if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
                best_params, best_sharpe = params, sharpe
        selected.append(
            WalkForwardWindow(number, start, end, days[oos_start], days[oos_end], best_params, best_sharpe)
        )
    return selected


def simulate_oos(
    inputs: UniverseInputs, base: SimulationConfig, windows: Sequence[WalkForwardWindow]
) -> SimulationResult:
    """Un'unica simulazione OOS con `params_schedule = [(oos_start, scelta)]`, senza liquidazioni ai cambi."""
    if not windows:
        raise ValueError("Nessuna finestra fuori campione.")
    start, end = windows[0].oos_start, windows[-1].oos_end
    calendar = [day for day in inputs.calendar if start <= day <= end]
    schedule = tuple((window.oos_start, window.chosen) for window in windows)
    return simulate(inputs.markets, inputs.signals, calendar, replace(base, params_schedule=schedule))


def run_walk_forward(
    inputs: UniverseInputs,
    base: SimulationConfig,
    grid: Sequence[StrategyParams],
    *,
    is_sessions: int,
    oos_sessions: int,
    progress: Progress | None = None,
) -> WalkForwardRun:
    """Griglia -> finestre -> selezione in-sample -> OOS unico. `LAB_PERIOD_TOO_SHORT` senza nessuna finestra."""
    bounds = build_windows(inputs.calendar, is_sessions, oos_sessions)
    if not bounds:
        raise period_too_short_error(len(inputs.calendar), is_sessions)
    report = progress or (lambda _value: None)
    share = len(grid) / (len(grid) + 1)
    grid_results = simulate_grid(inputs, base, grid, progress=lambda value: report(value * share))
    windows = select_parameters(grid_results, inputs.calendar, bounds)
    oos = simulate_oos(inputs, base, windows)
    report(1.0)
    return WalkForwardRun(tuple(windows), tuple(grid_results), oos)
