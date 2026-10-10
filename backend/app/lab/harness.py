"""Diagnostica cross-sectional su open EUR: non e una strategia short eseguibile.

Bucket fissi: decili soltanto se ogni data valutabile ha >=50 coppie, altrimenti
quintili. mean_names considera tutte le date con almeno una coppia, anche sotto
soglia. IC con ranghi medi; bucket con parita risolta per asset_id.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.app.lab.costs import CostProfile
from backend.app.lab.simulator import AssetMarket
from backend.app.lab.stats import spearman_ic

HORIZONS = (1, 5, 21)


@dataclass(frozen=True)
class HarnessResult:
    horizon: int
    ic_dates: int
    ic_mean: float | None
    ic_std: float | None
    ic_ir: float | None
    ic_positive_share: float | None
    t_nw: float | None
    mean_names: float
    bucket_count: int
    bucket_returns: list[float | None]
    spread_gross: float | None
    spread_net: float | None
    turnover_top: float | None
    rank_autocorr: float | None


def forward_open_returns(
    markets: Mapping[int, AssetMarket],
    calendar: Sequence[str],
    horizon: int,
) -> pd.DataFrame:
    """Open della barra propria t+1+h / open t+1 -1; nessun salto di segmento.

    Barre mancanti (anche senza FX) devono restare righe NaN nel mercato ricevuto.
    Le exit dates sono metadati primitivi per evitare overlap su calendari misti.
    """
    if horizon not in HORIZONS:
        raise ValueError("Orizzonte non supportato.")
    result = pd.DataFrame(np.nan, index=list(calendar), columns=sorted(markets))
    exits: dict[str, dict[int, str]] = {}
    entries: dict[str, dict[int, str]] = {}
    for asset_id, market in markets.items():
        bars = market.bars.sort_index()
        opens = bars["open_eur"].to_numpy(dtype=float)
        segments = bars["segment_id"].to_numpy()
        days = list(bars.index)
        for i in range(len(bars) - horizon - 1):
            if days[i] not in result.index:
                continue
            part = opens[i : i + horizon + 2]
            ids = segments[i : i + horizon + 2]
            if not np.isfinite(part).all() or (part <= 0).any() or not (ids == ids[0]).all():
                continue
            value = opens[i + horizon + 1] / opens[i + 1] - 1
            if math.isfinite(value):
                result.at[days[i], asset_id] = value
                exits.setdefault(str(days[i]), {})[asset_id] = str(days[i + horizon + 1])
                entries.setdefault(str(days[i]), {})[asset_id] = str(days[i + 1])
    result.attrs["exit_dates"] = exits
    result.attrs["entry_dates"] = entries
    return result


def _nw_calendar(ic: np.ndarray, horizon: int) -> float | None:
    """Bartlett h-1: gap conservati, residui assenti zero, nessuna imputazione IC."""
    finite = np.isfinite(ic)
    n = int(finite.sum())
    if n < 2 or np.ptp(ic[finite]) == 0:
        return None
    mean = float(ic[finite].mean())
    deviations = np.where(finite, ic - mean, 0)
    variance = float(deviations @ deviations) / n
    for lag in range(1, min(horizon, len(ic))):
        variance += 2 * (1 - lag / horizon) * float(deviations[lag:] @ deviations[:-lag]) / n
    return mean / math.sqrt(variance / n) if math.isfinite(variance) and variance > 0 else None


def _turnover(previous: Mapping[int, float] | None, current: Mapping[int, float]) -> float:
    if previous is None:
        return 1.0
    return 0.5 * sum(abs(current.get(key, 0) - previous.get(key, 0)) for key in previous.keys() | current.keys())


def evaluate_signal(
    signals: pd.DataFrame,
    labels: pd.DataFrame,
    horizon: int,
    *,
    min_names: int,
    costs: CostProfile,
    asset_types: Mapping[int, str],
    reference_capital_eur: float,
) -> HarnessResult:
    if horizon not in HORIZONS or min_names < 3:
        raise ValueError("Orizzonte o numero minimo di nomi non valido.")
    if not math.isfinite(reference_capital_eur) or reference_capital_eur <= 0:
        raise ValueError("Il capitale deve essere finito e positivo.")
    columns = sorted(set(signals.columns) & set(labels.columns))
    dates = list(signals.index)
    # Nessun attrs nel working panel: pandas copia profondamente i metadati su ogni slice.
    signal = pd.DataFrame(signals.to_numpy(copy=False), index=signals.index, columns=signals.columns).reindex(
        columns=columns
    )
    label = pd.DataFrame(labels.to_numpy(copy=False), index=labels.index, columns=labels.columns).reindex(
        index=dates, columns=columns
    )
    pairs = np.isfinite(signal.to_numpy(dtype=float)) & np.isfinite(label.to_numpy(dtype=float))
    counts = pairs.sum(axis=1)
    eligible = counts >= min_names
    bucket_count = 10 if eligible.any() and counts[eligible].min() >= 50 else 5
    ic = np.full(len(dates), np.nan)
    for i in np.flatnonzero(eligible):
        names = np.asarray(columns)[pairs[i]]
        value = spearman_ic(signal.iloc[i][names], label.iloc[i][names])
        if value is not None:
            ic[i] = value
    values = ic[np.isfinite(ic)]
    mean = float(values.mean()) if len(values) else None
    std = float(values.std(ddof=1)) if len(values) >= 2 else None
    buckets: list[list[float]] = [[] for _ in range(bucket_count)]
    daily_groups = {}
    for i in np.flatnonzero(eligible & (counts >= bucket_count)):
        day = dates[i]
        names = [columns[j] for j in np.flatnonzero(pairs[i])]
        ranked = sorted(names, key=lambda key: (float(signal.at[day, key]), key))
        groups = [list(group) for group in np.array_split(ranked, bucket_count)]
        returns = [float(label.loc[day, group].mean()) for group in groups]
        daily_groups[i] = (names, groups, returns)
        for bucket, value in zip(buckets, returns, strict=True):
            bucket.append(value)
    gross, net, turnovers, autocorr = [], [], [], []
    previous_weights: list[dict[int, float] | None] = [None, None]
    previous_signal: pd.Series | None = None
    exit_dates = labels.attrs.get("exit_dates", {})
    last_exit: str | None = None
    for i in range(0, len(dates), horizon):
        day = dates[i]
        if i not in daily_groups:
            continue
        names, groups, returns = daily_groups[i]
        entries = labels.attrs.get("entry_dates", {}).get(str(day), {})
        if last_exit is not None and min((entries[key] for key in names if key in entries), default=day) < last_exit:
            continue
        leg_costs = []
        for leg, group in enumerate((groups[0], groups[-1])):
            weights = dict.fromkeys(group, 1 / len(group))
            turnover = _turnover(previous_weights[leg], weights)
            rate = float(np.mean([costs.cost_rate(asset_types[key]) for key in group]))
            leg_costs.append(2 * turnover * (costs.commission_eur / (reference_capital_eur / len(group)) + rate))
            previous_weights[leg] = weights
            if leg == 1:
                turnovers.append(turnover)
        current_signal = signal.loc[day, names]
        if previous_signal is not None:
            value = spearman_ic(previous_signal, current_signal)
            if value is not None:
                autocorr.append(value)
        previous_signal = current_signal
        spread = returns[-1] - returns[0]
        gross.append(spread)
        net.append(spread - sum(leg_costs))
        exits = exit_dates.get(str(day), {})
        last_exit = max((exits[key] for key in names if key in exits), default=None)

    def average(items: list[float]) -> float | None:
        return float(np.mean(items)) if items else None

    return HarnessResult(
        horizon,
        len(values),
        mean,
        std,
        mean / std if std and mean is not None else None,
        float(np.mean(values > 0)) if len(values) else None,
        _nw_calendar(ic, horizon),
        float(counts[counts > 0].mean()) if (counts > 0).any() else 0.0,
        bucket_count,
        [average(bucket) for bucket in buckets],
        average(gross),
        average(net),
        average(turnovers),
        average(autocorr),
    )
