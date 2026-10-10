"""Evidenza REAL congelata: harness, walk-forward long-only, DSR e report append-only."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Literal

from backend.app.config import get_settings
from backend.app.lab.contracts import PIPELINE_VERSION, SCORE_VERSION, LabError, Timeframe
from backend.app.lab.costs import CostProfile
from backend.app.lab.harness import HORIZONS, HarnessResult, evaluate_signal, forward_open_returns
from backend.app.lab.series import EurConverter, available_data_modes, load_series
from backend.app.lab.simulator import AssetMarket, SimulationConfig, SimulationResult, compute_metrics
from backend.app.lab.stats import deflated_sharpe, sharpe_daily
from backend.app.lab.strategies import StrategyParams
from backend.app.lab.trials import canonical_hash, family_key, record_trial, trial_config
from backend.app.lab.universe import UniverseInputs, _market_bars, _resolve_assets, build_universe_inputs
from backend.app.lab.walk_forward import run_walk_forward
from backend.app.models.lab import EvidenceIn, EvidenceReportOut, EvidenceSummaryOut

EVIDENCE_VERSION = "evidence-v1"
Verdict = Literal["VALIDATO", "NON_VALIDATO", "INSUFFICIENTE"]
Checkpoint = Callable[[float], None]


@dataclass(frozen=True)
class EvidenceThresholds:
    min_names: int
    min_ic_dates: int
    min_oos_sessions: int
    min_t_stat: float
    min_dsr: float

    def __post_init__(self) -> None:
        if self.min_names < 3 or self.min_ic_dates < 2 or self.min_oos_sessions < 2:
            raise ValueError("Le soglie di campione devono essere positive.")
        if not math.isfinite(self.min_t_stat) or self.min_t_stat <= 0:
            raise ValueError("Soglia t non valida.")
        if not math.isfinite(self.min_dsr) or not 0 < self.min_dsr <= 1:
            raise ValueError("Soglia DSR non valida.")

    @classmethod
    def from_settings(cls) -> EvidenceThresholds:
        s = get_settings()
        return cls(s.lab_min_names, s.lab_min_ic_dates, s.lab_min_oos_sessions, s.lab_min_t_stat, s.lab_min_dsr)


def decide_verdict(
    harness: HarnessResult,
    wf_oos_sessions: int,
    dsr: float | None,
    thresholds: EvidenceThresholds,
) -> Verdict:
    if (
        harness.ic_dates < thresholds.min_ic_dates
        or wf_oos_sessions < thresholds.min_oos_sessions
        or not math.isfinite(harness.mean_names)
        or harness.mean_names < thresholds.min_names
    ):
        return "INSUFFICIENTE"
    values = (harness.ic_mean, harness.t_nw, harness.spread_net, dsr)
    if any(value is None or not math.isfinite(value) for value in values):
        return "NON_VALIDATO"
    if (
        harness.ic_mean > 0
        and harness.t_nw >= thresholds.min_t_stat
        and harness.spread_net > 0
        and dsr >= thresholds.min_dsr
    ):
        return "VALIDATO"
    return "NON_VALIDATO"


@dataclass(frozen=True)
class EvidenceOutcome:
    horizon: int
    verdict: Verdict
    harness: HarnessResult
    walk_forward: dict[str, Any] | None


def evaluate_evidence(
    inputs: UniverseInputs,
    horizons: Sequence[int],
    *,
    thresholds: EvidenceThresholds,
    costs: CostProfile,
    reference_capital_eur: float,
    trial_sharpes: Callable[[list[tuple[StrategyParams, SimulationResult]]], list[float]],
    selection_calendar: Sequence[str] | None = None,
    label_markets: dict[int, AssetMarket] | None = None,
    is_sessions: int | None = None,
    oos_sessions: int | None = None,
    max_pending_sessions: int | None = None,
    checkpoint: Checkpoint | None = None,
    data_mode: str = "REAL",
) -> list[EvidenceOutcome]:
    if data_mode != "REAL":
        raise LabError("LAB_EVIDENCE_REAL_ONLY", "L'evidenza richiede esclusivamente dati REAL.")
    requested = sorted(set(horizons))
    if not requested or any(h not in HORIZONS or isinstance(h, bool) for h in requested):
        raise ValueError("Orizzonte non supportato.")
    s = get_settings()
    step = checkpoint or (lambda _: None)
    prepared = []
    for index, horizon in enumerate(requested):
        step(index / len(requested))
        labels = forward_open_returns(label_markets or inputs.markets, inputs.calendar, horizon)
        harness = evaluate_signal(
            inputs.signals,
            labels,
            horizon,
            min_names=thresholds.min_names,
            costs=costs,
            asset_types=inputs.asset_types,
            reference_capital_eur=reference_capital_eur,
        )
        frequency = {1: "DAILY", 5: "WEEKLY", 21: "MONTHLY"}[horizon]
        grid = [StrategyParams("TOP_N_SCORE", top_n=n, rebalance_frequency=frequency) for n in (3, 5, 8)]
        base = SimulationConfig(
            reference_capital_eur,
            costs,
            ((inputs.calendar[0], grid[0]),),
            None,
            None,
            s.lab_order_max_pending_sessions if max_pending_sessions is None else max_pending_sessions,
        )
        try:
            run = run_walk_forward(
                inputs,
                base,
                grid,
                is_sessions=s.lab_wf_is_sessions if is_sessions is None else is_sessions,
                oos_sessions=s.lab_wf_oos_sessions if oos_sessions is None else oos_sessions,
                selection_calendar=selection_calendar,
                progress=lambda value, index=index: step((index + value) / len(requested)),
            )
        except LabError as exc:
            if exc.code != "LAB_PERIOD_TOO_SHORT":
                raise
            run = None
        prepared.append((horizon, harness, run))
    # Una sola famiglia effettiva per TUTTI gli orizzonti: DSR indipendente dall'ordine.
    family = trial_sharpes([pair for _, _, run in prepared if run is not None for pair in run.grid_results])
    outcomes = []
    for horizon, harness, run in prepared:
        wf = None
        sessions, dsr = 0, None
        if run is not None:
            result = deflated_sharpe(run.oos.daily_returns, family)
            dsr = result.dsr if result else None
            sessions = len(run.oos.equity)
            is_values = [window.is_sharpe for window in run.windows if window.is_sharpe is not None]
            is_mean = sum(is_values) / len(is_values) if is_values else None
            oos_sharpe = sharpe_daily(run.oos.daily_returns)
            metrics = compute_metrics(run.oos, reference_capital_eur)
            metrics["final_value_eur"] = float(run.oos.equity["value_eur"].iloc[-1])
            wf = {
                "oos_sessions": sessions,
                "oos_observations": len(run.oos.daily_returns),
                "windows": [asdict(window) for window in run.windows],
                "grid_size": len(run.grid_results),
                "oos_sharpe_daily": oos_sharpe,
                "is_sharpe_mean_daily": is_mean,
                "degradation_daily": is_mean - oos_sharpe if is_mean is not None and oos_sharpe is not None else None,
                "oos_metrics": metrics,
                "units": {
                    "window_is_sharpe": "daily",
                    "is_sharpe_mean_daily": "daily",
                    "oos_sharpe_daily": "daily",
                    "degradation_daily": "daily",
                    "oos_metrics.sharpe_ratio": "annualized_sqrt_252",
                    "oos_metrics.total_return_percent": "percent",
                    "oos_metrics.cagr": "percent",
                    "oos_metrics.max_drawdown": "percent",
                    "oos_metrics.win_rate": "percent",
                },
                "dsr": asdict(result) if result else None,
                "n_trials": len(family),
                "trial_sharpes": family,
                "costs": run.oos.costs,
                "turnover": run.oos.turnover,
                "exposure": run.oos.exposure,
            }
        outcomes.append(EvidenceOutcome(horizon, decide_verdict(harness, sessions, dsr, thresholds), harness, wf))
    step(1)
    return outcomes


def precheck_evidence(connection: sqlite3.Connection, request: EvidenceIn) -> None:
    candidates, _ = _resolve_assets(connection, request.symbols)
    if not any("REAL" in available_data_modes(connection, asset_id) for asset_id, _ in candidates):
        raise LabError("LAB_NO_REAL_SERIES", "Nessuna serie REAL disponibile per gli asset richiesti.")


def _source_calendars(
    connection: sqlite3.Connection,
    request: EvidenceIn,
    inputs: UniverseInputs,
    step: Checkpoint,
) -> tuple[list[str], dict[int, AssetMarket]]:
    """Calendario R1 pre-NO_FEATURES; labels conservano le barre native senza FX."""
    days = set(inputs.calendar)
    labels = {}
    converter = EurConverter(connection, max_age_days=get_settings().ecb_fx_max_age_days)
    candidates, _ = _resolve_assets(connection, request.symbols)
    for asset_id, symbol in candidates:
        if asset_id not in inputs.markets and inputs.excluded.get(symbol) != "NO_FEATURES":
            continue
        series = load_series(connection, asset_id, "REAL")
        if series is None:
            continue
        if asset_id in inputs.markets:
            market = inputs.markets[asset_id]
            native_dates = sorted(
                str(day)
                for segment in series.segments
                for day in segment.bars["date"]
                if request.start_date <= str(day) <= request.end_date
            )
            labels[asset_id] = replace(market, bars=market.bars.reindex(native_dates))
        else:
            reason, bars, _ = _market_bars(series, converter, request.start_date, request.end_date)
            if reason is None:
                days.update(str(day) for day in bars.index)
        step(0.2)
    return sorted(days), labels


def run_evidence(
    connection: sqlite3.Connection,
    request: EvidenceIn,
    *,
    job_id: int | None,
    now: datetime,
    checkpoint: Checkpoint | None = None,
) -> list[int]:
    step = checkpoint or (lambda _: None)
    step(0)
    precheck_evidence(connection, request)
    settings = get_settings()
    thresholds = EvidenceThresholds.from_settings()
    costs = CostProfile.from_settings()
    capital = settings.lab_reference_capital_eur
    inputs = build_universe_inputs(
        connection,
        request.symbols,
        data_mode="REAL",
        signal_name=request.signal_name,
        signal_timeframe=request.timeframe,
        start=request.start_date,
        end=request.end_date,
        now=now,
        progress=lambda fraction: step(fraction * 0.2),
    )
    calendar, label_markets = _source_calendars(connection, request, inputs, step)
    family_name = family_key(request.signal_name, request.timeframe)
    latest = dict(
        connection.execute(
            "SELECT config_hash, sharpe_daily FROM lab_trials WHERE family_key=? ORDER BY id",
            (family_name,),
        )
    )
    pending: list[tuple[str, float, int]] = []

    def capture(results: list[tuple[StrategyParams, SimulationResult]]) -> list[float]:
        for params, result in results:
            sr = sharpe_daily(result.daily_returns)
            if sr is None:
                continue
            config_hash = canonical_hash(
                trial_config(
                    params,
                    signal_name=request.signal_name,
                    signal_timeframe=request.timeframe,
                    stop_loss_percent=None,
                    take_profit_percent=None,
                    costs=costs,
                    initial_cash_eur=capital,
                    symbols=request.symbols,
                )
            )
            pending.append((config_hash, sr, len(result.daily_returns)))
            latest[config_hash] = sr
        return [float(latest[key]) for key in sorted(latest)]

    outcomes = evaluate_evidence(
        inputs,
        request.horizons,
        thresholds=thresholds,
        costs=costs,
        reference_capital_eur=capital,
        trial_sharpes=capture,
        selection_calendar=calendar,
        label_markets=label_markets,
        is_sessions=settings.lab_wf_is_sessions,
        oos_sessions=settings.lab_wf_oos_sessions,
        max_pending_sessions=settings.lab_order_max_pending_sessions,
        checkpoint=lambda fraction: step(0.2 + 0.75 * fraction),
    )
    universe = {
        "assets": [
            {"asset_id": key, "symbol": market.symbol, "asset_type": market.asset_type}
            for key, market in inputs.markets.items()
        ],
        "excluded": inputs.excluded,
        "inputs_hash": inputs.inputs_hash,
    }
    limits = {
        "survivorship_bias": "Universo disponibile oggi; manca un archivio point-in-time dei listing cessati.",
        "adjustment_basis": inputs.adjustment_basis,
        "split_events": {key: [asdict(event) for event in events] for key, events in inputs.split_events.items()},
        "fx_excluded_bars": inputs.fx_excluded_bars,
        "assumed_costs": asdict(costs),
        "coingecko_note": (
            "OHLCV daily sintetici da market_chart; volume approssimato; storico gratuito circa 365 giorni."
            if "NOT_APPLICABLE" in inputs.adjustment_basis.values()
            else None
        ),
        "diagnostic_spread": "Spread high-low diagnostico, non una strategia short eseguibile.",
        "label_rule": "Next open EUR, h barre proprie; NaN per FX mancanti o cambio segmento.",
        "rebalance_rule": "Ogni h date union; nuovi ingressi non precedono l'ultima exit.",
        "bucket_rule": "Decili solo con >=50 coppie in ogni data ammissibile; altrimenti quintili.",
        "mean_names_rule": "Media su tutte le date con almeno una coppia, incluse le date sotto soglia.",
        "newey_west_rule": "Bartlett h-1 sulle distanze del calendario, senza imputare IC mancanti.",
        "validation_scope": "D/W/M e orizzonti in sedute; non valida intraday 15-30 minuti.",
    }
    config = {
        "request": request.model_dump(),
        "data_mode": "REAL",
        "thresholds": asdict(thresholds),
        "costs": asdict(costs),
        "reference_capital_eur": capital,
        "is_sessions": settings.lab_wf_is_sessions,
        "oos_sessions": settings.lab_wf_oos_sessions,
        "max_pending_sessions": settings.lab_order_max_pending_sessions,
        "versions": {
            "evidence": EVIDENCE_VERSION,
            "engine": "v1",
            "pipeline": PIPELINE_VERSION,
            "score": SCORE_VERSION,
        },
        "grid": {
            "strategy": "TOP_N_SCORE",
            "top_n": [3, 5, 8],
            "max_asset_weight": 0.15,
            "rebalance": {"1": "DAILY", "5": "WEEKLY", "21": "MONTHLY"},
            "stop_loss_percent": None,
            "take_profit_percent": None,
        },
        "selection_calendar": calendar,
        "preprocessing": {
            "ecb_fx_max_age_days": settings.ecb_fx_max_age_days,
            "segment_max_gap_sessions": settings.lab_segment_max_gap_sessions,
            "split_tolerance": settings.lab_split_tolerance,
        },
        "label_calendars": {str(key): list(market.bars.index) for key, market in label_markets.items()},
        "family_trial_snapshot": {str(key): float(latest[key]) for key in sorted(latest)},
    }

    def encode(value: Any) -> str:
        return json.dumps(value, sort_keys=True, allow_nan=False)

    job_fingerprint = canonical_hash({"config": config, "universe": universe, "limits": limits})
    rows = []
    for outcome in outcomes:
        effective_config = {**config, "horizon": outcome.horizon}
        fingerprint = canonical_hash({"config": effective_config, "universe": universe, "limits": limits})
        rows.append(
            (
                job_id,
                request.signal_name,
                request.timeframe,
                outcome.horizon,
                outcome.verdict,
                encode(asdict(outcome.harness)),
                encode(outcome.walk_forward) if outcome.walk_forward else None,
                encode(effective_config),
                encode(universe),
                encode(limits),
                fingerprint,
                now.isoformat(),
            )
        )
    step(0.99)  # ultimo punto annullabile prima della transazione breve
    connection.execute("SAVEPOINT evidence_reports")
    ids = []
    try:
        for config_hash, sr, n_obs in pending:
            record_trial(
                connection,
                data_mode="REAL",
                family=family_name,
                kind="WF_GRID",
                config_hash=config_hash,
                fingerprint=job_fingerprint,
                sharpe_daily=sr,
                n_obs=n_obs,
                job_id=job_id,
            )
        for row in rows:
            cursor = connection.execute(
                """INSERT INTO lab_evidence_reports
                (job_id, signal_name, timeframe, horizon, verdict, metrics_json, walk_forward_json,
                 config_json, universe_json, limits_json, fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
            ids.append(int(cursor.lastrowid))
    except BaseException:
        connection.execute("ROLLBACK TO SAVEPOINT evidence_reports")
        connection.execute("RELEASE SAVEPOINT evidence_reports")
        raise
    connection.execute("RELEASE SAVEPOINT evidence_reports")
    return ids


def report_from_row(row: sqlite3.Row) -> EvidenceReportOut:
    return EvidenceReportOut(
        **{
            key: row[key]
            for key in ("id", "job_id", "signal_name", "timeframe", "horizon", "verdict", "fingerprint", "created_at")
        },
        **{
            key: json.loads(row[key + "_json"]) if row[key + "_json"] else None
            for key in ("metrics", "walk_forward", "config", "universe", "limits")
        },
    )


def summary_from_row(row: sqlite3.Row) -> EvidenceSummaryOut:
    return EvidenceSummaryOut(**{key: row[key] for key in EvidenceSummaryOut.model_fields})


def latest_verdicts(
    connection: sqlite3.Connection,
    signal_name: str,
    timeframe: Timeframe,
) -> dict[int, dict[str, Any] | None]:
    result = {}
    for horizon in HORIZONS:
        row = connection.execute(
            """SELECT * FROM lab_evidence_reports WHERE signal_name=? AND timeframe=? AND horizon=?
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (signal_name, timeframe, horizon),
        ).fetchone()
        result[horizon] = summary_from_row(row).model_dump() if row else None
    return result
