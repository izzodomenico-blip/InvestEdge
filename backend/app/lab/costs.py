"""Profilo costi Trade Republic del simulatore (spec SP1 §7.3).

- Commissione fissa per ordine eseguito, stop inclusi.
- Costo per lato (spread + slippage, cambio incluso: TR quota in EUR) in punti base: crypto con il proprio
  valore, ogni altra classe (azioni, ETF, ETC/ETN, obbligazioni) con quello equity.
- Quote intere per azioni ed ETF salvo `fractional_shares`; le crypto sono sempre frazionarie.
- Nessun ordine sotto `min_trade_eur`.

Il profilo e sovrascrivibile per run e serializzabile con `dataclasses.asdict`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.app.config import get_settings

_CRYPTO = "crypto"


@dataclass(frozen=True)
class CostProfile:
    commission_eur: float
    cost_bps_equity: float
    cost_bps_crypto: float
    fractional_shares: bool
    min_trade_eur: float

    def __post_init__(self) -> None:
        for value in (self.commission_eur, self.cost_bps_equity, self.cost_bps_crypto, self.min_trade_eur):
            if not math.isfinite(value) or value < 0:
                raise ValueError("Profilo costi non valido: valori finiti e non negativi.")

    @classmethod
    def from_settings(cls) -> CostProfile:
        settings = get_settings()
        return cls(
            commission_eur=settings.tr_commission_eur,
            cost_bps_equity=settings.tr_cost_bps_equity,
            cost_bps_crypto=settings.tr_cost_bps_crypto,
            fractional_shares=settings.backtest_fractional_shares,
            min_trade_eur=settings.backtest_min_trade_eur,
        )

    def cost_rate(self, asset_type: str) -> float:
        """Costo per lato come frazione del prezzo (bps / 10.000)."""
        bps = self.cost_bps_crypto if _is_crypto(asset_type) else self.cost_bps_equity
        return bps / 10_000

    def allows_fraction(self, asset_type: str) -> bool:
        return _is_crypto(asset_type) or self.fractional_shares


def _is_crypto(asset_type: str) -> bool:
    return asset_type.strip().lower() == _CRYPTO
