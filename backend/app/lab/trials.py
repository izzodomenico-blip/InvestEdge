"""Registro append-only dei tentativi (spec SP1 §8.4).

- Una riga per configurazione simulata su dati REAL: famiglia (`signal_name|signal_timeframe`), tipo (`BACKTEST`,
  `COMPARE`, `WF_GRID`), `config_hash` della configurazione, impronta del run, Sharpe giornaliero, osservazioni e job.
  Trigger contro UPDATE e DELETE (`lab_trials`).
- N del DSR = configurazioni distinte della famiglia; per ciascuna vale lo Sharpe piu recente: rieseguire la stessa
  configurazione non fa crescere N.
- I run DEMO non vengono registrati, come le serie con meno di 2 osservazioni o uno Sharpe non finito.
- `trial_config` normalizza la configurazione di strategia (solo i parametri che la strategia usa, numeri come float):
  la stessa configurazione ha lo stesso `config_hash` in backtest, confronto e griglia del walk-forward. Periodo,
  nome e benchmark non ne fanno parte (rieseguire con dati piu recenti non e un tentativo nuovo).
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from backend.app.lab.contracts import DataMode, Timeframe
from backend.app.lab.costs import CostProfile
from backend.app.lab.strategies import StrategyParams
from backend.app.services.common import now_utc

TrialKind = Literal["BACKTEST", "COMPARE", "WF_GRID"]

# Parametri che ciascuna strategia usa davvero: gli altri non distinguono due configurazioni.
_STRATEGY_FIELDS: Mapping[str, tuple[str, ...]] = {
    "SCORE_THRESHOLD": ("buy_threshold", "sell_threshold", "max_asset_weight", "rebalance_frequency"),
    "TOP_N_SCORE": ("top_n", "max_asset_weight", "rebalance_frequency"),
    "BUY_AND_HOLD": ("max_asset_weight",),
}


def family_key(signal_name: str, signal_timeframe: Timeframe) -> str:
    return f"{signal_name}|{signal_timeframe}"


def canonical_hash(payload: Mapping[str, Any]) -> str:
    """SHA-256 del JSON canonico (chiavi ordinate, separatori compatti, nessun NaN)."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _optional_float(value: float | None) -> float | None:
    return None if value is None else float(value)


def trial_config(
    params: StrategyParams,
    *,
    signal_name: str,
    signal_timeframe: Timeframe,
    stop_loss_percent: float | None,
    take_profit_percent: float | None,
    costs: CostProfile,
    initial_cash_eur: float,
    symbols: Sequence[str] | None,
) -> dict[str, Any]:
    """Configurazione normalizzata di un tentativo (base del `config_hash`)."""
    strategy: dict[str, Any] = {"name": params.name}
    for field in _STRATEGY_FIELDS[params.name]:
        value = getattr(params, field)
        strategy[field] = value if isinstance(value, str) else (int(value) if field == "top_n" else float(value))
    return {
        "strategy": strategy,
        "signal": {"name": signal_name, "timeframe": signal_timeframe},
        "stop_loss_percent": _optional_float(stop_loss_percent),
        "take_profit_percent": _optional_float(take_profit_percent),
        "costs": {
            "commission_eur": float(costs.commission_eur),
            "cost_bps_equity": float(costs.cost_bps_equity),
            "cost_bps_crypto": float(costs.cost_bps_crypto),
            "fractional_shares": bool(costs.fractional_shares),
            "min_trade_eur": float(costs.min_trade_eur),
        },
        "initial_cash_eur": float(initial_cash_eur),
        "symbols": None if symbols is None else sorted({symbol.strip().upper() for symbol in symbols}),
    }


def record_trial(
    connection: sqlite3.Connection,
    *,
    data_mode: DataMode,
    family: str,
    kind: TrialKind,
    config_hash: str,
    fingerprint: str,
    sharpe_daily: float,
    n_obs: int,
    job_id: int | None,
) -> bool:
    """Registra un tentativo REAL; False (nessuna riga) per DEMO, meno di 2 osservazioni o Sharpe non finito.

    La transazione resta al chiamante (la riga va scritta insieme al run che la produce).
    """
    if data_mode != "REAL" or n_obs < 2 or not math.isfinite(sharpe_daily):
        return False
    connection.execute(
        """
        INSERT INTO lab_trials (family_key, kind, config_hash, fingerprint, sharpe_daily, n_obs, job_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (family, kind, config_hash, fingerprint, float(sharpe_daily), int(n_obs), job_id, now_utc()),
    )
    return True


def family_trial_sharpes(connection: sqlite3.Connection, family: str) -> list[float]:
    """Sharpe giornalieri della famiglia: uno per `config_hash`, il piu recente (ultima riga inserita)."""
    latest: dict[str, float] = {}
    for config_hash, sharpe in connection.execute(
        "SELECT config_hash, sharpe_daily FROM lab_trials WHERE family_key = ? ORDER BY id",
        (family,),
    ):
        latest[str(config_hash)] = float(sharpe)
    return list(latest.values())
