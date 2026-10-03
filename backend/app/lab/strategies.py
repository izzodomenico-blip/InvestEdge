"""Strategie del simulatore: pesi obiettivo alla chiusura di t (spec SP1 §7.4), semantica del motore attuale.

- `SCORE_THRESHOLD`: posizioni con segnale <= soglia di vendita a peso 0; segnale >= soglia di acquisto e peso
  corrente sotto il massimo -> peso massimo (nessuna riduzione di chi supera il massimo).
- `TOP_N_SCORE`: primi N per segnale (a parita vince l'`asset_id` minore) a peso `min(massimo, 1 / selezionati)`;
  si riduce solo oltre il 5% sopra l'obiettivo, si integra sotto l'obiettivo; le posizioni non selezionate a 0.
- `BUY_AND_HOLD`: solo al primo ribilanciamento, peso `min(massimo, 1 / asset)` per ogni asset ricevuto
  (il valore del segnale non conta); poi nessun cambio.

`target_weights` restituisce solo gli asset da modificare (asset assenti: posizione invariata) oppure `None`
se non cambia nulla. Segnali non finiti vengono ignorati da `SCORE_THRESHOLD` e `TOP_N_SCORE`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal, get_args

StrategyName = Literal["SCORE_THRESHOLD", "TOP_N_SCORE", "BUY_AND_HOLD"]
RebalanceFrequency = Literal["DAILY", "WEEKLY", "MONTHLY"]
STRATEGY_NAMES: tuple[str, ...] = get_args(StrategyName)
REBALANCE_FREQUENCIES: tuple[str, ...] = get_args(RebalanceFrequency)
# Banda del motore attuale: una posizione TOP_N si riduce solo oltre il 5% sopra l'obiettivo.
TOP_N_REDUCE_BAND = 1.05


@dataclass(frozen=True)
class StrategyParams:
    name: StrategyName
    buy_threshold: float = 70
    sell_threshold: float = 40
    max_asset_weight: float = 0.15
    top_n: int = 5
    rebalance_frequency: RebalanceFrequency = "WEEKLY"

    def __post_init__(self) -> None:
        if self.name not in STRATEGY_NAMES:
            raise ValueError("Strategia non supportata.")
        if self.rebalance_frequency not in REBALANCE_FREQUENCIES:
            raise ValueError("Frequenza di ribilanciamento non supportata.")
        if not 0 < self.max_asset_weight <= 1:
            raise ValueError("Il peso massimo per asset deve essere in (0, 1].")
        if self.top_n < 1:
            raise ValueError("N della strategia TOP_N deve essere almeno 1.")


def rebalance_key(day: str, frequency: RebalanceFrequency) -> str:
    """Chiave del periodo di ribilanciamento: giorno, settimana ISO o mese."""
    if frequency == "DAILY":
        return day[:10]
    if frequency == "MONTHLY":
        return day[:7]
    iso = date.fromisoformat(day[:10]).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def target_weights(
    params: StrategyParams,
    signals: Mapping[int, float],
    current_weights: Mapping[int, float],
    *,
    first_rebalance: bool,
) -> dict[int, float] | None:
    """Pesi obiettivo degli asset da modificare; `None` = nessun cambio."""
    if params.name == "BUY_AND_HOLD":
        if not first_rebalance:
            return None
        weight = min(params.max_asset_weight, 1 / len(signals)) if signals else 0.0
        return dict.fromkeys(signals, weight)
    finite = {asset_id: value for asset_id, value in signals.items() if math.isfinite(value)}
    if params.name == "SCORE_THRESHOLD":
        return _score_threshold(params, finite, current_weights)
    return _top_n(params, finite, current_weights)


def _score_threshold(
    params: StrategyParams, signals: Mapping[int, float], current_weights: Mapping[int, float]
) -> dict[int, float]:
    targets: dict[int, float] = {}
    for asset_id, value in signals.items():
        current = current_weights.get(asset_id, 0.0)
        if current > 0 and value <= params.sell_threshold:
            targets[asset_id] = 0.0
        elif value >= params.buy_threshold and current < params.max_asset_weight:
            targets[asset_id] = params.max_asset_weight
    return targets


def _top_n(
    params: StrategyParams, signals: Mapping[int, float], current_weights: Mapping[int, float]
) -> dict[int, float]:
    ranked = sorted(signals.items(), key=lambda item: (-item[1], item[0]))
    selected = [asset_id for asset_id, _ in ranked[: params.top_n]]
    targets = {asset_id: 0.0 for asset_id, weight in current_weights.items() if weight > 0 and asset_id not in selected}
    if not selected:
        return targets
    target = min(params.max_asset_weight, 1 / len(selected))
    for asset_id in selected:
        current = current_weights.get(asset_id, 0.0)
        if current > target * TOP_N_REDUCE_BAND or current < target:
            targets[asset_id] = target
    return targets
