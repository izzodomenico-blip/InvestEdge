"""Motore di backtest v1: orchestratore di universo, strategie, simulatore e persistenza (spec SP1 §4.2, §7).

- Run `v1` (`engine_version`): segnale as-of dal feature store (`signal_name`, `signal_timeframe`), decisione alla
  chiusura e ordini all'apertura della barra successiva dello stesso listing, costi Trade Republic, contabilita in
  EUR, un solo `data_mode` (REAL di default), impronta canonica di configurazione, versioni e input.
- Ogni run REAL registra un tentativo nel registro (`BACKTEST`, o `COMPARE` per strategia del confronto) nella
  famiglia (`signal_name`, `signal_timeframe`); i run DEMO sono etichettati e mai registrati.
- Imposte e bollo restano nell'analisi netta, in EUR (utili e perdite di cambio inclusi).
- I run `v0` del motore precedente restano leggibili e cancellabili ("motore precedente").
- `walk_forward` (spec §8.3-§8.5): griglia globale per il registro, selezione con simulazioni troncate al cutoff
  IS e finestre sul calendario delle barre utilizzabili prima del filtro NO_FEATURES; un'unica simulazione fuori
  campione con il calendario dei parametri; in REAL ogni
  configurazione della griglia e un tentativo `WF_GRID` e il DSR usa gli Sharpe della famiglia.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from backend.app.config import get_settings
from backend.app.lab.contracts import PERIODS_PER_YEAR, PIPELINE_VERSION, SCORE_VERSION, DataMode, LabError
from backend.app.lab.costs import CostProfile
from backend.app.lab.series import EurConverter, available_data_modes, load_series
from backend.app.lab.simulator import SimulationConfig, SimulationResult, compute_metrics, simulate
from backend.app.lab.stats import DsrResult, deflated_sharpe, sharpe_daily
from backend.app.lab.strategies import StrategyParams
from backend.app.lab.trials import canonical_hash, family_key, family_trial_sharpes, record_trial, trial_config
from backend.app.lab.universe import (
    UniverseInputs,
    _market_bars,
    benchmark_curve,
    build_universe_inputs,
    no_real_series_error,
)
from backend.app.lab.walk_forward import WalkForwardRun, parameter_grid, period_too_short_error, run_walk_forward
from backend.app.models import (
    BacktestBenchmarkComparisonOut,
    BacktestCompareEntryOut,
    BacktestCompareIn,
    BacktestCompareOut,
    BacktestEquityPointOut,
    BacktestNetAnalysisOut,
    BacktestPositionOut,
    BacktestResultOut,
    BacktestRunIn,
    BacktestSummaryOut,
    BacktestTradeOut,
    DeflatedSharpeOut,
    WalkForwardIn,
    WalkForwardMetricsOut,
    WalkForwardOut,
    WalkForwardParamsOut,
    WalkForwardWindowOut,
)
from backend.app.services.common import (
    now_local as _now,
)
from backend.app.services.common import (
    round_safe as _round,
)

ENGINE_VERSION = "v1"
LEGACY_ENGINE_VERSION = "v0"
Checkpoint = Callable[[float], None]
BacktestSettings = BacktestRunIn | BacktestCompareIn

STRATEGY_LABELS: dict[str, str] = {
    "SCORE_THRESHOLD": "Score threshold",
    "BUY_AND_HOLD": "Buy & hold",
    "TOP_N_SCORE": "Top N score",
}

# Modello fiscale Italia (semplificato, per stima "netto in tasca"), in EUR
TAX_RATE_STANDARD = 26.0      # azioni, ETF, cripto: 26% sulle plusvalenze realizzate
TAX_RATE_BONDS = 12.5         # titoli di Stato white-list ed ETF obbligazionari govt
STAMP_DUTY_ANNUAL = 0.2       # imposta di bollo titoli: 0.2% annuo sul controvalore
SLIPPAGE_PER_SIDE = 0.05      # solo run v0: slippage stimato per lato, in percento (nel v1 e nel prezzo)
BOND_ASSET_TYPES = {"bond", "bond_etf"}

_V1_NET_NOTES = [
    "Importi in EUR: plusvalenze e minusvalenze includono gli effetti di cambio.",
    "Tasse stimate sulle sole plusvalenze realizzate (26% standard, 12,5% titoli di Stato/ETF govt).",
    "Le plusvalenze non realizzate sulle posizioni finali non sono tassate.",
    f"Bollo {STAMP_DUTY_ANNUAL:.1f}% annuo sul controvalore medio.",
    "Commissioni e costo per lato (spread e slippage) gia inclusi nel valore finale lordo: mostrati per trasparenza.",
]
_RUN_COLUMNS = (
    "name", "strategy_name", "initial_cash", "start_date", "end_date", "benchmark_symbol", "buy_threshold",
    "sell_threshold", "max_asset_weight", "fee_percent", "stop_loss_percent", "take_profit_percent",
    "rebalance_frequency", "total_return_percent", "cagr", "max_drawdown", "sharpe_ratio", "win_rate",
    "profit_factor", "total_trades", "final_value", "benchmark_return_percent", "alpha_vs_benchmark", "created_at",
    "engine_version", "data_mode", "signal_name", "signal_timeframe", "cost_profile_json", "fingerprint",
    "warnings_json", "excluded_json", "commission_eur", "spread_cost_eur", "turnover", "exposure",
)


def _no_checkpoint(_progress: float) -> None:
    return None


@dataclass(frozen=True)
class _Outcome:
    """Una strategia simulata sull'universo: risultato, sintesi, curva e chiave del tentativo."""

    strategy_name: str
    result: SimulationResult
    metrics: dict[str, float]
    summary: BacktestSummaryOut
    equity_curve: list[BacktestEquityPointOut]
    config_hash: str


@dataclass
class BacktestEngine:
    """Backtest locale su dati simulati o reali: nessun broker, nessun ordine reale."""

    def precheck(self, connection: sqlite3.Connection, symbols: Sequence[str], data_mode: DataMode) -> None:
        """Prima di accodare: in REAL almeno un simbolo deve avere una serie reale (`LAB_NO_REAL_SERIES`)."""
        if data_mode != "REAL":
            return
        for symbol in dict.fromkeys(item.strip().upper() for item in symbols if item and item.strip()):
            rows = connection.execute(
                "SELECT id FROM assets WHERE UPPER(symbol) = ? ORDER BY id", (symbol,)
            ).fetchall()
            if len(rows) == 1 and "REAL" in available_data_modes(connection, int(rows[0][0])):
                return
        raise no_real_series_error()

    def precheck_walk_forward(self, connection: sqlite3.Connection, payload: WalkForwardIn) -> None:
        """Prima di accodare: le sedute del periodo nel `data_mode` del run devono superare la finestra in-sample.

        Le date distinte delle barre dei simboli richiesti sono un limite superiore del calendario dell'universo:
        se gia queste non bastano, `LAB_PERIOD_TOO_SHORT` senza accodare (il job ricontrolla sul calendario reale).
        """
        is_sessions, _oos_sessions = _window_sessions(payload)
        asset_ids: list[int] = []
        for symbol in payload.symbols:
            rows = connection.execute("SELECT id FROM assets WHERE UPPER(symbol) = ? ORDER BY id", (symbol,)).fetchall()
            if len(rows) == 1:
                asset_ids.append(int(rows[0][0]))
        available = 0
        if asset_ids:
            available = int(
                connection.execute(
                    f"""
                    SELECT COUNT(DISTINCT substr(date, 1, 10))
                    FROM price_history
                    WHERE asset_id IN ({", ".join("?" * len(asset_ids))})
                      AND is_real_data = ?
                      AND substr(date, 1, 10) BETWEEN ? AND ?
                    """,
                    (*asset_ids, 1 if payload.data_mode == "REAL" else 0, payload.start_date, payload.end_date),
                ).fetchone()[0]
            )
        if available <= is_sessions:
            raise period_too_short_error(available, is_sessions)

    def run_backtest(
        self,
        connection: sqlite3.Connection,
        config: BacktestRunIn,
        *,
        job_id: int | None = None,
        now: datetime | None = None,
        checkpoint: Checkpoint | None = None,
    ) -> BacktestResultOut:
        """Run v1 persistito; `checkpoint(progress)` fra i passi (annullamento cooperativo dei job)."""
        step = checkpoint or _no_checkpoint
        inputs = self._universe(connection, config, now, step, share=0.6)
        costs = _cost_profile(config)
        benchmark = benchmark_curve(
            connection, config.benchmark_symbol, data_mode=config.data_mode, calendar=inputs.calendar
        )
        outcome = self._simulate(config, config.strategy_name, config.name, inputs, costs, benchmark)
        step(0.9)
        backtest_id = self._persist(connection, config, outcome, inputs, job_id)
        return self.get_backtest(connection, backtest_id)

    def compare_strategies(
        self,
        connection: sqlite3.Connection,
        payload: BacktestCompareIn,
        *,
        job_id: int | None = None,
        now: datetime | None = None,
        checkpoint: Checkpoint | None = None,
    ) -> dict[str, Any]:
        """Piu strategie sullo stesso universo, ordinate per Sharpe netto; nessun run persistito.

        Il confronto non corregge per i tentativi (l'evidenza viene dal walk-forward), ma in REAL registra un
        tentativo `COMPARE` per strategia.
        """
        step = checkpoint or _no_checkpoint
        names = list(dict.fromkeys(payload.strategy_names))
        if len(names) < 2:
            raise LabError("LAB_INVALID_STRATEGIES", "Seleziona almeno due strategie diverse.")
        inputs = self._universe(connection, payload, now, step, share=0.5)
        costs = _cost_profile(payload)
        benchmark = benchmark_curve(
            connection, payload.benchmark_symbol, data_mode=payload.data_mode, calendar=inputs.calendar
        )
        outcomes: list[_Outcome] = []
        for index, name in enumerate(names):
            outcomes.append(self._simulate(payload, name, f"{payload.name} - {name}", inputs, costs, benchmark))
            step(0.5 + 0.4 * (index + 1) / len(names))
        ranked = sorted(range(len(outcomes)), key=lambda index: (-outcomes[index].metrics["sharpe_ratio"], index))
        self._record_trials(connection, payload, outcomes, "COMPARE", job_id)
        entries = [
            BacktestCompareEntryOut(
                strategy_name=outcomes[index].strategy_name,
                label=STRATEGY_LABELS.get(outcomes[index].strategy_name, outcomes[index].strategy_name),
                rank=rank,
                summary=outcomes[index].summary,
                equity_curve=outcomes[index].equity_curve,
            )
            for rank, index in enumerate(ranked, start=1)
        ]
        best = entries[0]
        return BacktestCompareOut(
            name=payload.name,
            start_date=inputs.calendar[0],
            end_date=inputs.calendar[-1],
            benchmark_symbol=payload.benchmark_symbol.upper(),
            benchmark_return_percent=best.summary.benchmark_return_percent,
            best_strategy=best.strategy_name,
            entries=entries,
        ).model_dump(mode="json")

    def walk_forward(
        self,
        connection: sqlite3.Connection,
        payload: WalkForwardIn,
        *,
        job_id: int | None = None,
        now: datetime | None = None,
        checkpoint: Checkpoint | None = None,
    ) -> dict[str, Any]:
        """Walk-forward vero sullo stesso universo del backtest; risultato `WalkForwardOut` serializzato.

        Griglia globale per il registro; per la selezione, simulazioni dal primo giorno al cutoff IS di ogni
        finestra e calendario delle barre EUR prima del filtro NO_FEATURES; un'unica simulazione fuori campione con il calendario dei parametri. In REAL ogni configurazione
        della griglia e un tentativo `WF_GRID` (stesso `config_hash` di backtest e confronto) e il DSR usa gli Sharpe
        della famiglia (N = configurazioni distinte); i run DEMO non registrano tentativi e non hanno DSR.
        Tentativi e DSR si scrivono in un savepoint dopo l'ultimo punto di annullamento.
        """
        step = checkpoint or _no_checkpoint
        is_sessions, oos_sessions = _window_sessions(payload)
        inputs = self._universe(connection, payload, now, step, share=0.4)
        costs = _cost_profile(payload)
        params = _strategy_params(payload, payload.strategy_name)
        run = run_walk_forward(
            inputs,
            _simulation_config(payload, costs, params, inputs.calendar),
            parameter_grid(payload.strategy_name, params),
            is_sessions=is_sessions,
            oos_sessions=oos_sessions,
            selection_calendar=_walk_forward_calendar(connection, payload, inputs, step),
            progress=lambda value: step(0.4 + 0.5 * value),
        )
        benchmark = benchmark_curve(
            connection,
            payload.benchmark_symbol,
            data_mode=payload.data_mode,
            calendar=[str(day) for day in run.oos.equity["date"]],
        )
        step(0.95)
        windows = (is_sessions, oos_sessions)
        if payload.data_mode != "REAL":
            return self._walk_forward_out(payload, costs, inputs, run, benchmark, windows, None, None, 0)
        connection.execute("SAVEPOINT walk_forward_trials")
        try:
            skipped = 0
            for grid_params, result in run.grid_results:
                trial = _trial_config(payload, grid_params, costs)
                recorded = self._record_trial(
                    connection,
                    payload,
                    kind="WF_GRID",
                    config_hash=canonical_hash(trial),
                    fingerprint=_run_fingerprint(payload, trial, inputs),
                    returns=result.daily_returns,
                    job_id=job_id,
                )
                skipped += 0 if recorded else 1
            sharpes = family_trial_sharpes(connection, family_key(payload.signal_name, payload.signal_timeframe))
            output = self._walk_forward_out(
                payload, costs, inputs, run, benchmark, windows,
                deflated_sharpe(run.oos.daily_returns, sharpes), len(sharpes), skipped,
            )
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT walk_forward_trials")
            connection.execute("RELEASE SAVEPOINT walk_forward_trials")
            raise
        connection.execute("RELEASE SAVEPOINT walk_forward_trials")
        return output

    def _walk_forward_out(
        self,
        payload: WalkForwardIn,
        costs: CostProfile,
        inputs: UniverseInputs,
        run: WalkForwardRun,
        benchmark: pd.Series | None,
        windows: tuple[int, int],
        dsr: DsrResult | None,
        n_trials: int | None,
        skipped_trials: int,
    ) -> dict[str, Any]:
        annual = math.sqrt(PERIODS_PER_YEAR["D"])
        oos = run.oos
        metrics = compute_metrics(oos, float(payload.initial_cash))
        in_sample = [window.is_sharpe for window in run.windows if window.is_sharpe is not None]
        is_mean = statistics.fmean(in_sample) * annual if in_sample else None
        oos_daily = sharpe_daily(oos.daily_returns)
        oos_sharpe = oos_daily * annual if oos_daily is not None else None
        degradation = is_mean - oos_sharpe if is_mean is not None and oos_sharpe is not None else None
        benchmark_return = _benchmark_return(benchmark)
        warnings = _warnings(payload, costs, inputs, oos, benchmark)
        if payload.data_mode != "REAL":
            warnings.append("DSR non calcolato: i run DEMO non entrano nel registro dei tentativi.")
        elif dsr is None:
            warnings.append("DSR non calcolabile: rendimenti fuori campione senza variazioni.")
        if skipped_trials:
            warnings.append(
                f"{skipped_trials} configurazioni della griglia senza Sharpe definito (valore senza variazioni): "
                "non registrate come tentativi."
            )
        dates = [str(day) for day in oos.equity["date"]]
        final_value = float(oos.equity["value_eur"].iloc[-1])
        return WalkForwardOut(
            strategy_name=payload.strategy_name,
            data_mode=payload.data_mode,
            window_is_sessions=windows[0],
            window_oos_sessions=windows[1],
            windows=[
                WalkForwardWindowOut(
                    index=window.index,
                    is_start=window.is_start,
                    is_end=window.is_end,
                    oos_start=window.oos_start,
                    oos_end=window.oos_end,
                    chosen=WalkForwardParamsOut(**asdict(window.chosen)),
                    is_sharpe=_optional_round(window.is_sharpe * annual if window.is_sharpe is not None else None),
                )
                for window in run.windows
            ],
            grid_size=len(run.grid_results),
            is_sharpe_mean=_optional_round(is_mean),
            oos_sharpe=_optional_round(oos_sharpe),
            degradation=_optional_round(degradation),
            oos_metrics=WalkForwardMetricsOut(
                start_date=dates[0],
                end_date=dates[-1],
                total_return_percent=_round(metrics["total_return_percent"]),
                cagr=_round(metrics["cagr"]),
                max_drawdown=_round(metrics["max_drawdown"]),
                sharpe_ratio=_round(metrics["sharpe_ratio"]),
                profit_factor=_round(metrics["profit_factor"]),
                win_rate=_round(metrics["win_rate"]),
                total_trades=int(metrics["total_trades"]),
                turnover=_round(metrics["turnover"]),
                exposure=_round(metrics["exposure"]),
                commission_eur=_round(metrics["commission_eur"]),
                spread_cost_eur=_round(metrics["spread_cost_eur"]),
                final_value=_round(final_value),
                benchmark_return_percent=_round(benchmark_return),
                alpha_vs_benchmark=_round(metrics["total_return_percent"] - benchmark_return),
            ),
            oos_sessions=len(dates),
            dsr=(
                None
                if dsr is None
                else DeflatedSharpeOut(
                    dsr=_round(dsr.dsr),
                    sr=_round(dsr.sr),
                    sr0=_round(dsr.sr0),
                    n_trials=dsr.n_trials,
                    n_obs=dsr.n_obs,
                    skew=_round(dsr.skew),
                    kurtosis=_round(dsr.kurtosis),
                )
            ),
            n_trials=n_trials,
            excluded=dict(inputs.excluded),
            warnings=warnings,
        ).model_dump(mode="json")

    def list_backtests(self, connection: sqlite3.Connection) -> list[BacktestSummaryOut]:
        rows = connection.execute(
            """
            SELECT *
            FROM backtest_runs
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        return [self._summary_from_row(row) for row in rows]

    def get_backtest(self, connection: sqlite3.Connection, backtest_id: int) -> BacktestResultOut:
        run = connection.execute("SELECT * FROM backtest_runs WHERE id = ?", (backtest_id,)).fetchone()
        if run is None:
            raise ValueError("Backtest non trovato.")

        equity_rows = connection.execute(
            """
            SELECT *
            FROM backtest_equity_curve
            WHERE backtest_id = ?
            ORDER BY date ASC, id ASC
            """,
            (backtest_id,),
        ).fetchall()
        trade_rows = connection.execute(
            """
            SELECT *
            FROM backtest_trades
            WHERE backtest_id = ?
            ORDER BY date ASC, id ASC
            """,
            (backtest_id,),
        ).fetchall()
        position_rows = connection.execute(
            """
            SELECT *
            FROM backtest_positions
            WHERE backtest_id = ?
            ORDER BY final_value DESC, symbol ASC
            """,
            (backtest_id,),
        ).fetchall()

        summary = self._summary_from_row(run)
        equity_curve = [
            BacktestEquityPointOut(
                id=row["id"],
                date=row["date"],
                portfolio_value=_round(row["portfolio_value"]),
                cash=_round(row["cash"]),
                invested_value=_round(row["invested_value"]),
                drawdown_percent=_round(row["drawdown_percent"]),
            )
            for row in equity_rows
        ]
        self._hydrate_benchmark(connection, summary, equity_curve)

        benchmark_final = summary.initial_cash * (1 + (summary.benchmark_return_percent / 100))
        trades = [self._trade_from_row(row) for row in trade_rows]
        return BacktestResultOut(
            backtest_id=backtest_id,
            summary=summary,
            equity_curve=equity_curve,
            trades=trades,
            final_positions=[self._position_from_row(row) for row in position_rows],
            benchmark_comparison=BacktestBenchmarkComparisonOut(
                benchmark_symbol=summary.benchmark_symbol,
                benchmark_return_percent=summary.benchmark_return_percent,
                alpha_vs_benchmark=summary.alpha_vs_benchmark,
                benchmark_final_value=_round(benchmark_final),
            ),
            net_analysis=BacktestNetAnalysisOut(
                **self._net_analysis(connection, summary, trades, equity_curve)
            ),
        )

    def delete_backtest(self, connection: sqlite3.Connection, backtest_id: int) -> bool:
        cursor = connection.execute("DELETE FROM backtest_runs WHERE id = ?", (backtest_id,))
        return cursor.rowcount > 0

    # --- Run v1 -------------------------------------------------------------------------------------------

    def _universe(
        self,
        connection: sqlite3.Connection,
        config: BacktestSettings,
        now: datetime | None,
        step: Checkpoint,
        *,
        share: float,
    ) -> UniverseInputs:
        inputs = build_universe_inputs(
            connection,
            config.symbols,
            data_mode=config.data_mode,
            signal_name=config.signal_name,
            signal_timeframe=config.signal_timeframe,
            start=config.start_date,
            end=config.end_date,
            now=now or datetime.now(UTC),
            progress=lambda value: step(value * share),
        )
        step(share)
        return inputs

    def _simulate(
        self,
        config: BacktestSettings,
        strategy_name: str,
        name: str,
        inputs: UniverseInputs,
        costs: CostProfile,
        benchmark: pd.Series | None,
    ) -> _Outcome:
        params = _strategy_params(config, strategy_name)
        result = simulate(inputs.markets, inputs.signals, inputs.calendar, _simulation_config(config, costs, params, inputs.calendar))
        metrics = compute_metrics(result, float(config.initial_cash))
        trial = _trial_config(config, params, costs)
        fingerprint = _run_fingerprint(config, trial, inputs)
        benchmark_return = _benchmark_return(benchmark)
        total_return = metrics["total_return_percent"]
        summary = BacktestSummaryOut(
            name=name,
            strategy_name=strategy_name,
            initial_cash=_round(config.initial_cash),
            start_date=inputs.calendar[0],
            end_date=inputs.calendar[-1],
            benchmark_symbol=config.benchmark_symbol.strip().upper(),
            buy_threshold=_round(config.buy_threshold),
            sell_threshold=_round(config.sell_threshold),
            max_asset_weight=_round(config.max_asset_weight),
            fee_percent=None,
            stop_loss_percent=_round(config.stop_loss_percent) if config.stop_loss_percent is not None else None,
            take_profit_percent=_round(config.take_profit_percent) if config.take_profit_percent is not None else None,
            rebalance_frequency=config.rebalance_frequency,
            total_return_percent=_round(total_return),
            cagr=_round(metrics["cagr"]),
            max_drawdown=_round(metrics["max_drawdown"]),
            sharpe_ratio=_round(metrics["sharpe_ratio"]),
            win_rate=_round(metrics["win_rate"]),
            profit_factor=_round(metrics["profit_factor"]),
            total_trades=int(metrics["total_trades"]),
            final_value=_round(float(result.equity["value_eur"].iloc[-1])),
            benchmark_return_percent=_round(benchmark_return),
            alpha_vs_benchmark=_round(total_return - benchmark_return),
            engine_version=ENGINE_VERSION,
            data_mode=config.data_mode,
            signal_name=config.signal_name,
            signal_timeframe=config.signal_timeframe,
            cost_profile=asdict(costs),
            warnings=_warnings(config, costs, inputs, result, benchmark),
            excluded=dict(inputs.excluded),
            commission_eur=_round(metrics["commission_eur"]),
            spread_cost_eur=_round(metrics["spread_cost_eur"]),
            turnover=_round(metrics["turnover"]),
            exposure=_round(metrics["exposure"]),
            fingerprint=fingerprint,
        )
        return _Outcome(
            strategy_name=strategy_name,
            result=result,
            metrics=metrics,
            summary=summary,
            equity_curve=_equity_points(result, benchmark, float(config.initial_cash)),
            config_hash=canonical_hash(trial),
        )

    def _record_trials(
        self,
        connection: sqlite3.Connection,
        config: BacktestSettings,
        outcomes: Sequence[_Outcome],
        kind: str,
        job_id: int | None,
    ) -> None:
        if config.data_mode != "REAL":
            return
        connection.execute("SAVEPOINT backtest_trials")
        try:
            for outcome in outcomes:
                self._record_trial(
                    connection,
                    config,
                    kind=kind,
                    config_hash=outcome.config_hash,
                    fingerprint=str(outcome.summary.fingerprint),
                    returns=outcome.result.daily_returns,
                    job_id=job_id,
                )
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT backtest_trials")
            connection.execute("RELEASE SAVEPOINT backtest_trials")
            raise
        connection.execute("RELEASE SAVEPOINT backtest_trials")

    def _record_trial(
        self,
        connection: sqlite3.Connection,
        config: BacktestSettings,
        *,
        kind: str,
        config_hash: str,
        fingerprint: str,
        returns: pd.Series,
        job_id: int | None,
    ) -> bool:
        """Tentativo nella famiglia del run con lo Sharpe giornaliero (`stats.sharpe_daily`; non definito -> nessuna riga)."""
        sharpe = sharpe_daily(returns)
        return record_trial(
            connection,
            data_mode=config.data_mode,
            family=family_key(config.signal_name, config.signal_timeframe),
            kind=kind,  # type: ignore[arg-type]
            config_hash=config_hash,
            fingerprint=fingerprint,
            sharpe_daily=math.nan if sharpe is None else sharpe,
            n_obs=len(returns),
            job_id=job_id,
        )

    def _persist(
        self,
        connection: sqlite3.Connection,
        config: BacktestRunIn,
        outcome: _Outcome,
        inputs: UniverseInputs,
        job_id: int | None,
    ) -> int:
        """Run, curva, operazioni, posizioni finali e tentativo REAL in un'unica transazione breve (savepoint)."""
        summary = outcome.summary
        created_at = _now()
        values = (
            summary.name, summary.strategy_name, float(config.initial_cash), summary.start_date, summary.end_date,
            summary.benchmark_symbol, float(config.buy_threshold), float(config.sell_threshold),
            float(config.max_asset_weight), 0.0, config.stop_loss_percent, config.take_profit_percent,
            config.rebalance_frequency, summary.total_return_percent, summary.cagr, summary.max_drawdown,
            summary.sharpe_ratio, summary.win_rate, summary.profit_factor, summary.total_trades, summary.final_value,
            summary.benchmark_return_percent, summary.alpha_vs_benchmark, created_at, ENGINE_VERSION,
            summary.data_mode, summary.signal_name, summary.signal_timeframe,
            json.dumps(summary.cost_profile, sort_keys=True), summary.fingerprint,
            json.dumps(summary.warnings, ensure_ascii=False), json.dumps(summary.excluded, sort_keys=True),
            summary.commission_eur, summary.spread_cost_eur, summary.turnover, summary.exposure,
        )
        equity = outcome.result.equity
        connection.execute("SAVEPOINT backtest_persist")
        try:
            cursor = connection.execute(
                f"INSERT INTO backtest_runs ({', '.join(_RUN_COLUMNS)}) VALUES ({', '.join('?' * len(_RUN_COLUMNS))})",
                values,
            )
            backtest_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO backtest_equity_curve (
                    backtest_id, date, portfolio_value, cash, invested_value, drawdown_percent, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (backtest_id, str(day), float(value), float(cash), float(invested), float(drawdown), created_at)
                    for day, value, cash, invested, drawdown in equity.itertuples(index=False, name=None)
                ],
            )
            connection.executemany(
                """
                INSERT INTO backtest_trades (
                    backtest_id, date, symbol, order_type, quantity, price, fees,
                    gross_amount, net_amount, pnl, reason, created_at, commission, spread_cost
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        backtest_id, trade.date, trade.symbol, trade.side, trade.quantity, trade.price_eur,
                        trade.commission_eur, trade.gross_eur, trade.net_eur, trade.pnl_eur, trade.reason,
                        created_at, trade.commission_eur, trade.spread_cost_eur,
                    )
                    for trade in outcome.result.trades
                ],
            )
            connection.executemany(
                """
                INSERT INTO backtest_positions (
                    backtest_id, symbol, quantity, average_price, final_price,
                    final_value, realized_pnl, unrealized_pnl, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(backtest_id, *position, created_at) for position in _final_positions(outcome.result, inputs)],
            )
            self._record_trial(
                connection,
                config,
                kind="BACKTEST",
                config_hash=outcome.config_hash,
                fingerprint=str(summary.fingerprint),
                returns=outcome.result.daily_returns,
                job_id=job_id,
            )
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT backtest_persist")
            connection.execute("RELEASE SAVEPOINT backtest_persist")
            raise
        connection.execute("RELEASE SAVEPOINT backtest_persist")
        return backtest_id

    # --- Lettura e analisi netta --------------------------------------------------------------------------

    def _hydrate_benchmark(
        self,
        connection: sqlite3.Connection,
        summary: BacktestSummaryOut,
        equity_curve: list[BacktestEquityPointOut],
    ) -> None:
        if not summary.benchmark_symbol or not equity_curve:
            return
        if summary.engine_version == LEGACY_ENGINE_VERSION:
            self._hydrate_legacy_benchmark(connection, summary, equity_curve)
            return
        if summary.data_mode is None:
            return
        growth = benchmark_curve(
            connection,
            summary.benchmark_symbol,
            data_mode=summary.data_mode,
            calendar=[point.date for point in equity_curve],
        )
        _attach_benchmark(equity_curve, growth, summary.initial_cash)

    def _hydrate_legacy_benchmark(
        self,
        connection: sqlite3.Connection,
        summary: BacktestSummaryOut,
        equity_curve: list[BacktestEquityPointOut],
    ) -> None:
        """Run v0: benchmark dal close dello storico come nel motore precedente (nessuna conversione EUR)."""
        rows = connection.execute(
            """
            SELECT substr(ph.date, 1, 10) AS day, ph.close
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE UPPER(a.symbol) = ? AND substr(ph.date, 1, 10) <= ?
            ORDER BY day, ph.id
            """,
            (str(summary.benchmark_symbol).upper(), summary.end_date),
        ).fetchall()
        index = 0
        latest_price: float | None = None
        first_price: float | None = None
        for point in equity_curve:
            while index < len(rows) and str(rows[index][0]) <= point.date:
                latest_price = float(rows[index][1])
                index += 1
            if latest_price is None:
                continue
            if first_price is None:
                first_price = latest_price
            return_percent = ((latest_price / first_price) - 1) * 100 if first_price else 0.0
            point.benchmark_value = _round(summary.initial_cash * (1 + return_percent / 100))
            point.benchmark_return_percent = _round(return_percent)

    def _net_analysis(
        self,
        connection: sqlite3.Connection,
        summary: BacktestSummaryOut,
        trades: list[BacktestTradeOut],
        equity_curve: list[BacktestEquityPointOut],
    ) -> dict[str, Any]:
        """Stima netta in tasca: tasse italiane sulle plusvalenze realizzate e imposta di bollo.

        Run v1: importi in EUR, commissioni e costo per lato gia nel valore finale (mostrati per trasparenza).
        Run v0: slippage stimato per lato e sottratto, come nel motore precedente. Semplificazioni: compensazione
        delle perdite solo entro la stessa classe (standard vs obbligazionario), bollo sul controvalore medio,
        plusvalenze non realizzate non tassate.
        """
        legacy = summary.engine_version == LEGACY_ENGINE_VERSION
        type_rows = connection.execute("SELECT UPPER(symbol) AS symbol, asset_type FROM assets").fetchall()
        type_map = {row["symbol"]: row["asset_type"] for row in type_rows}

        gain_standard = 0.0
        gain_bonds = 0.0
        commission = 0.0
        slippage = 0.0
        for trade in trades:
            commission += float(trade.fees)
            if legacy:
                slippage += abs(float(trade.gross_amount)) * (SLIPPAGE_PER_SIDE / 100)
            else:
                slippage += float(trade.spread_cost or 0.0)
            if trade.order_type == "SELL":
                asset_type = type_map.get(trade.symbol.upper(), "stock")
                if asset_type in BOND_ASSET_TYPES:
                    gain_bonds += float(trade.pnl)
                else:
                    gain_standard += float(trade.pnl)

        taxable_standard = max(0.0, gain_standard)
        taxable_bonds = max(0.0, gain_bonds)
        taxable_total = taxable_standard + taxable_bonds
        capital_gains_tax = taxable_standard * (TAX_RATE_STANDARD / 100) + taxable_bonds * (TAX_RATE_BONDS / 100)

        mean_equity = (
            sum(point.portfolio_value for point in equity_curve) / len(equity_curve)
            if equity_curve
            else summary.final_value
        )
        days = (datetime.fromisoformat(summary.end_date[:10]) - datetime.fromisoformat(summary.start_date[:10])).days
        years = max(days, 1) / 365.25
        stamp_duty = mean_equity * (STAMP_DUTY_ANNUAL / 100) * years

        initial = summary.initial_cash
        final_value = summary.final_value
        deducted_slippage = slippage if legacy else 0.0
        total_costs = capital_gains_tax + deducted_slippage + stamp_duty
        net_final = final_value - total_costs
        net_return = ((net_final / initial) - 1) * 100 if initial > 0 else 0.0
        effective_rate = (capital_gains_tax / taxable_total * 100) if taxable_total > 0 else 0.0

        if legacy:
            notes = [
                "Tasse stimate sulle sole plusvalenze realizzate (26% standard, 12,5% titoli di Stato/ETF govt).",
                "Le plusvalenze non realizzate sulle posizioni finali non sono tassate.",
                f"Slippage stimato {SLIPPAGE_PER_SIDE:.2f}% per operazione, bollo {STAMP_DUTY_ANNUAL:.1f}% annuo sul controvalore medio.",
                "Commissioni gia incluse nel valore finale lordo; qui mostrate solo per trasparenza.",
            ]
        else:
            notes = list(_V1_NET_NOTES)

        return {
            "gross_return_percent": summary.total_return_percent,
            "gross_profit": _round(final_value - initial, 2),
            "commission_costs": _round(commission, 2),
            "slippage_costs": _round(slippage, 2),
            "realized_gains_taxable": _round(taxable_total, 2),
            "capital_gains_tax": _round(capital_gains_tax, 2),
            "stamp_duty": _round(stamp_duty, 2),
            "total_costs_and_taxes": _round(total_costs, 2),
            "net_final_value": _round(net_final, 2),
            "net_return_percent": _round(net_return, 2),
            "effective_tax_rate_percent": _round(effective_rate, 2),
            "notes": notes,
        }

    def _summary_from_row(self, row: sqlite3.Row) -> BacktestSummaryOut:
        engine_version = row["engine_version"] or LEGACY_ENGINE_VERSION
        legacy = engine_version == LEGACY_ENGINE_VERSION
        return BacktestSummaryOut(
            id=row["id"],
            name=row["name"],
            strategy_name=row["strategy_name"],
            initial_cash=_round(row["initial_cash"]),
            start_date=row["start_date"],
            end_date=row["end_date"],
            benchmark_symbol=row["benchmark_symbol"],
            buy_threshold=_round(row["buy_threshold"]),
            sell_threshold=_round(row["sell_threshold"]),
            max_asset_weight=_round(row["max_asset_weight"]),
            fee_percent=_round(row["fee_percent"]) if legacy else None,
            stop_loss_percent=_round(row["stop_loss_percent"]) if row["stop_loss_percent"] is not None else None,
            take_profit_percent=_round(row["take_profit_percent"]) if row["take_profit_percent"] is not None else None,
            rebalance_frequency=row["rebalance_frequency"],
            total_return_percent=_round(row["total_return_percent"]),
            cagr=_round(row["cagr"]),
            max_drawdown=_round(row["max_drawdown"]),
            sharpe_ratio=_round(row["sharpe_ratio"]),
            win_rate=_round(row["win_rate"]),
            profit_factor=_round(row["profit_factor"]),
            total_trades=int(row["total_trades"]),
            final_value=_round(row["final_value"]),
            benchmark_return_percent=_round(row["benchmark_return_percent"]),
            alpha_vs_benchmark=_round(row["alpha_vs_benchmark"]),
            created_at=row["created_at"],
            engine_version=engine_version,
            data_mode=row["data_mode"],
            signal_name=row["signal_name"],
            signal_timeframe=row["signal_timeframe"],
            cost_profile=_json_or(row["cost_profile_json"], None),
            warnings=_json_or(row["warnings_json"], []),
            excluded=_json_or(row["excluded_json"], {}),
            commission_eur=_optional_round(row["commission_eur"]),
            spread_cost_eur=_optional_round(row["spread_cost_eur"]),
            turnover=_optional_round(row["turnover"]),
            exposure=_optional_round(row["exposure"]),
            fingerprint=row["fingerprint"],
        )

    def _trade_from_row(self, row: sqlite3.Row) -> BacktestTradeOut:
        return BacktestTradeOut(
            id=row["id"],
            date=row["date"],
            symbol=row["symbol"],
            order_type=row["order_type"],
            quantity=_round(row["quantity"]),
            price=_round(row["price"]),
            fees=_round(row["fees"]),
            gross_amount=_round(row["gross_amount"]),
            net_amount=_round(row["net_amount"]),
            pnl=_round(row["pnl"]),
            reason=row["reason"],
            commission=_optional_round(row["commission"]),
            spread_cost=_optional_round(row["spread_cost"]),
        )

    def _position_from_row(self, row: sqlite3.Row) -> BacktestPositionOut:
        return BacktestPositionOut(
            id=row["id"],
            symbol=row["symbol"],
            quantity=_round(row["quantity"]),
            average_price=_round(row["average_price"]),
            final_price=_round(row["final_price"]),
            final_value=_round(row["final_value"]),
            realized_pnl=_round(row["realized_pnl"]),
            unrealized_pnl=_round(row["unrealized_pnl"]),
        )


def _cost_profile(config: BacktestSettings) -> CostProfile:
    """Profilo costi Trade Republic delle impostazioni con gli override del run (spec §7.3)."""
    overrides = {
        field: getattr(config, field)
        for field in ("commission_eur", "cost_bps_equity", "cost_bps_crypto", "fractional_shares", "min_trade_eur")
        if getattr(config, field) is not None
    }
    return replace(CostProfile.from_settings(), **overrides)


def _strategy_params(config: BacktestSettings, strategy_name: str) -> StrategyParams:
    return StrategyParams(
        name=strategy_name,  # type: ignore[arg-type]
        buy_threshold=float(config.buy_threshold),
        sell_threshold=float(config.sell_threshold),
        max_asset_weight=float(config.max_asset_weight),
        top_n=int(config.top_n or 5),
        rebalance_frequency=config.rebalance_frequency,
    )


def _simulation_config(
    config: BacktestSettings, costs: CostProfile, params: StrategyParams, calendar: Sequence[str]
) -> SimulationConfig:
    return SimulationConfig(
        initial_cash_eur=float(config.initial_cash),
        costs=costs,
        params_schedule=((calendar[0], params),),
        stop_loss_percent=config.stop_loss_percent,
        take_profit_percent=config.take_profit_percent,
        max_pending_sessions=get_settings().lab_order_max_pending_sessions,
    )


def _trial_config(config: BacktestSettings, params: StrategyParams, costs: CostProfile) -> dict[str, Any]:
    """Configurazione normalizzata del tentativo: stessa base del `config_hash` in backtest, confronto e griglia."""
    return trial_config(
        params,
        signal_name=config.signal_name,
        signal_timeframe=config.signal_timeframe,
        stop_loss_percent=config.stop_loss_percent,
        take_profit_percent=config.take_profit_percent,
        costs=costs,
        initial_cash_eur=float(config.initial_cash),
        symbols=config.symbols,
    )


def _run_fingerprint(config: BacktestSettings, trial: dict[str, Any], inputs: UniverseInputs) -> str:
    """Impronta canonica di configurazione, periodo, versioni, `data_mode` e input dell'universo."""
    return canonical_hash(
        {
            "config": {
                **trial,
                "start_date": config.start_date,
                "end_date": config.end_date,
                "benchmark_symbol": config.benchmark_symbol.strip().upper(),
                "max_pending_sessions": get_settings().lab_order_max_pending_sessions,
            },
            "versions": {"engine": ENGINE_VERSION, "pipeline": PIPELINE_VERSION, "score": SCORE_VERSION},
            "data_mode": config.data_mode,
            "inputs_hash": inputs.inputs_hash,
        }
    )


def _walk_forward_calendar(
    connection: sqlite3.Connection, payload: WalkForwardIn, inputs: UniverseInputs, checkpoint: Checkpoint
) -> list[str]:
    """Ripristina le date EUR pre-NO_FEATURES: il warm-up OOS non puo' cambiare i confini IS."""
    days = set(inputs.calendar)
    excluded = [symbol for symbol, reason in inputs.excluded.items() if reason == "NO_FEATURES"]
    if not excluded:
        return inputs.calendar
    converter = EurConverter(connection, max_age_days=get_settings().ecb_fx_max_age_days)
    for symbol in excluded:
        rows = connection.execute("SELECT id FROM assets WHERE UPPER(symbol) = ?", (symbol,)).fetchall()
        if len(rows) == 1 and (series := load_series(connection, int(rows[0][0]), payload.data_mode)) is not None:
            reason, bars, _missing = _market_bars(series, converter, payload.start_date, payload.end_date)
            if reason is None:
                days.update(str(day) for day in bars.index)
        checkpoint(0.4)
    return sorted(days)


def _window_sessions(payload: WalkForwardIn) -> tuple[int, int]:
    """Sedute delle finestre in-sample e fuori campione: quelle del run o, se nulle, le impostazioni."""
    settings = get_settings()
    return (
        payload.is_sessions or settings.lab_wf_is_sessions,
        payload.oos_sessions or settings.lab_wf_oos_sessions,
    )


def _benchmark_return(curve: pd.Series | None) -> float:
    """Rendimento percentuale del benchmark fra il primo e l'ultimo valore noto della curva; 0 senza benchmark."""
    if curve is None:
        return 0.0
    values = curve.dropna()
    if values.empty or float(values.iloc[0]) <= 0:
        return 0.0
    return (float(values.iloc[-1]) / float(values.iloc[0]) - 1) * 100


def _attach_benchmark(
    equity_curve: list[BacktestEquityPointOut], growth: pd.Series | None, initial_cash: float
) -> None:
    if growth is None:
        return
    for point in equity_curve:
        value = growth.get(point.date)
        if value is not None and math.isfinite(float(value)):
            point.benchmark_value = _round(initial_cash * float(value))
            point.benchmark_return_percent = _round((float(value) - 1) * 100)


def _equity_points(
    result: SimulationResult, growth: pd.Series | None, initial_cash: float
) -> list[BacktestEquityPointOut]:
    points = [
        BacktestEquityPointOut(
            date=str(day),
            portfolio_value=_round(value),
            cash=_round(cash),
            invested_value=_round(invested),
            drawdown_percent=_round(drawdown),
        )
        for day, value, cash, invested, drawdown in result.equity.itertuples(index=False, name=None)
    ]
    _attach_benchmark(points, growth, initial_cash)
    return points


def _final_positions(result: SimulationResult, inputs: UniverseInputs) -> list[tuple[Any, ...]]:
    """Posizioni a fine run ricostruite dalle operazioni (costo di carico con commissioni, come il simulatore)."""
    book: dict[int, dict[str, Any]] = {}
    for trade in result.trades:
        entry = book.setdefault(trade.asset_id, {"symbol": trade.symbol, "quantity": 0.0, "cost": 0.0, "realized": 0.0})
        if trade.side == "BUY":
            entry["quantity"] += trade.quantity
            entry["cost"] += trade.net_eur
            continue
        held = entry["quantity"]
        share = trade.quantity / held if held > 0 else 1.0
        entry["cost"] *= 1.0 - share
        entry["quantity"] = held - trade.quantity
        entry["realized"] += trade.pnl_eur
        if entry["quantity"] <= 1e-12:
            entry["quantity"], entry["cost"] = 0.0, 0.0
    rows: list[tuple[Any, ...]] = []
    for asset_id, entry in book.items():
        closes = inputs.markets[asset_id].bars["close_eur"]
        final_price = float(closes.iloc[-1]) if len(closes) else 0.0
        quantity = entry["quantity"]
        final_value = quantity * final_price
        average_price = entry["cost"] / quantity if quantity > 0 else 0.0
        unrealized = final_value - entry["cost"] if quantity > 0 else 0.0
        rows.append((entry["symbol"], quantity, average_price, final_price, final_value, entry["realized"], unrealized))
    return sorted(rows, key=lambda row: (-row[4], row[0]))


def _warnings(
    config: BacktestSettings,
    costs: CostProfile,
    inputs: UniverseInputs,
    result: SimulationResult,
    benchmark: pd.Series | None,
) -> list[str]:
    """Avvisi del run e limiti dichiarati (spec §6.5-§6.6), testi senza percorsi o dati sensibili."""
    warnings: list[str] = []
    if config.data_mode == "DEMO":
        warnings.append(
            "Run DEMO su dati dimostrativi: nessun valore di evidenza, non registrato nel registro dei tentativi."
        )
    if benchmark is None:
        warnings.append(
            f"Benchmark {config.benchmark_symbol.strip().upper()} non disponibile in modalita {config.data_mode}: "
            "nessuna serie convertibile in EUR."
        )
    if inputs.fx_excluded_bars:
        warnings.append(
            f"{inputs.fx_excluded_bars} barre escluse per cambio EUR mancante o piu vecchio di "
            f"{get_settings().ecb_fx_max_age_days} giorni."
        )
    for symbol, events in inputs.split_events.items():
        for event in events:
            warnings.append(
                f"Split sospetto su {symbol} il {event.date} (rapporto {event.ratio:g}, {event.direction}): "
                "la serie riparte con un nuovo segmento e un nuovo warm-up (SEGMENT_EXIT al confine)."
            )
    cancelled = Counter(str(order["reason"]) for order in result.cancelled_orders)
    if cancelled:
        counts = ", ".join(f"{reason} {count}" for reason, count in sorted(cancelled.items()))
        warnings.append(f"Ordini annullati: {counts}.")
    asset_types = {asset_type.strip().lower() for asset_type in inputs.asset_types.values()}
    if "crypto" in asset_types and len(asset_types) > 1:
        warnings.append(
            "Calendari misti (crypto e mercati con sedute): ogni decisione considera solo gli asset con una barra "
            "in quella data."
        )
    warnings.append("Universo limitato agli asset attivi oggi: possibile bias di sopravvivenza.")
    unknown = sorted(
        inputs.markets[asset_id].symbol
        for asset_id, basis in inputs.adjustment_basis.items()
        if basis == "UNKNOWN"
    )
    if unknown:
        warnings.append(f"Rettifica non verificata (base UNKNOWN), dividendi assenti: {', '.join(unknown)}.")
    if any(basis == "NOT_APPLICABLE" for basis in inputs.adjustment_basis.values()):
        warnings.append("Storico CoinGecko di circa 365 giorni.")
    warnings.append(
        f"Costi di esecuzione ipotizzati: commissione {costs.commission_eur:g} EUR per ordine, costo per lato "
        f"{costs.cost_bps_equity:g} bps (azioni, ETF, obbligazioni) e {costs.cost_bps_crypto:g} bps (crypto)."
    )
    return warnings


def _json_or(text: str | None, default: Any) -> Any:
    return default if text is None else json.loads(text)


def _optional_round(value: float | None) -> float | None:
    return None if value is None else _round(value)
