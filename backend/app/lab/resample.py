"""Barre W/M dalle daily con `available_at` di calendario (spec SP1 §5.4).

- Periodo W = settimana lunedi-domenica, `available_at` = domenica; periodo M = mese di calendario,
  `available_at` = ultimo giorno del mese. Un periodo che finisce dopo `as_of` non produce barra.
- open = primo open, high = massimo, low = minimo, close = ultimo close, volume = somma; la barra porta il
  fattore di rettifica (adjusted_close / close) della sua ultima daily. Open, high e low si aggregano sui prezzi
  rettificati e si riportano nella scala di quel fattore: con fattore costante nel periodo coincidono con
  l'aggregazione dei grezzi (identici con fattore 1), con uno split nel periodo restano coerenti.
- Precondizione del chiamante, come per `compute_features`: daily di un solo segmento, ordinate per data, date uniche.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

_PERIOD_FREQ = {"W": "W-SUN", "M": "M"}
_COLUMNS = ("date", "open", "high", "low", "close", "adjusted_close", "volume")


def resample_bars(daily: pd.DataFrame, timeframe: Literal["W", "M"], as_of: date) -> pd.DataFrame:
    """Barre W/M chiuse entro `as_of`; colonna `date` = `available_at` (YYYY-MM-DD)."""
    if timeframe not in _PERIOD_FREQ:
        raise ValueError("resample_bars accetta solo i timeframe W e M.")
    dates = pd.to_datetime(daily["date"])
    period_end = dates.dt.to_period(_PERIOD_FREQ[timeframe]).dt.end_time.dt.normalize().to_numpy()
    closed = period_end <= np.datetime64(as_of)
    if not closed.any():
        return pd.DataFrame({column: pd.Series(dtype=object if column == "date" else float) for column in _COLUMNS})

    period_end = period_end[closed]
    close = daily["close"].to_numpy(dtype=float)[closed]
    adjusted_close = daily["adjusted_close"].to_numpy(dtype=float)[closed]
    factor = adjusted_close / close
    starts = np.flatnonzero(np.r_[True, period_end[1:] != period_end[:-1]])
    ends = np.r_[starts[1:], period_end.shape[0]] - 1
    last_factor = factor[ends]

    def adjusted(column: str) -> np.ndarray:
        return daily[column].to_numpy(dtype=float)[closed] * factor

    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(period_end[starts]).strftime("%Y-%m-%d"),
            "open": adjusted("open")[starts] / last_factor,
            "high": np.maximum.reduceat(adjusted("high"), starts) / last_factor,
            "low": np.minimum.reduceat(adjusted("low"), starts) / last_factor,
            "close": close[ends],
            "adjusted_close": adjusted_close[ends],
            "volume": np.add.reduceat(daily["volume"].to_numpy(dtype=float)[closed], starts),
        }
    )
