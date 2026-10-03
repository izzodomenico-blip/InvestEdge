"""Serie reale/demo, segmenti, base di rettifica, guardia split e conversione EUR (spec SP1 §6.1-§6.4).

- `data_mode` REAL = righe `price_history` con `is_real_data = 1`, DEMO = `is_real_data = 0`: mai mescolate.
  Con piu righe per data nello stesso modo vince quella con `id` maggiore; date ordinate e uniche.
- Base di rettifica dichiarata per provider. Con base UNKNOWN o NOT_APPLICABLE il fattore vale 1 (§5.1):
  `adjusted_close` = `close`.
- Segmenti (`segment_id` progressivo da 0): nuovo segmento a ogni buco di piu di `max_gap_sessions` sedute
  (giorni lavorativi per azioni/ETF, giorni di calendario per le crypto) e a ogni split sospetto (solo base UNKNOWN).
- Cambio verso EUR: ultima osservazione con data <= barra ed eta <= `max_age_days`; riga diretta X->EUR oppure,
  se manca, inversa EUR->X con reciproco, come `FXService.get_rate`. Le righe seed sono dati demo: escluse.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd

from backend.app.config import get_settings
from backend.app.lab.contracts import DataMode

AdjustmentBasis = Literal["NOT_APPLICABLE", "UNKNOWN", "SPLIT", "SPLIT_DIVIDEND"]

# Costante per provider: cambia solo con un commit dopo una verifica documentata della fonte (spec §6.3).
PROVIDER_ADJUSTMENT_BASIS: Mapping[str, AdjustmentBasis] = MappingProxyType(
    {"coingecko": "NOT_APPLICABLE", "stooq": "UNKNOWN"}
)
SPLIT_RATIOS: tuple[float, ...] = (2.0, 3.0, 4.0, 5.0, 10.0, 1.5)

_BAR_COLUMNS = ("date", "open", "high", "low", "close", "adjusted_close", "volume")
_IS_REAL_DATA: Mapping[DataMode, int] = MappingProxyType({"REAL": 1, "DEMO": 0})
_UNIT_FACTOR_BASES = frozenset({"NOT_APPLICABLE", "UNKNOWN"})
_DEMO_FX_PROVIDER = "seed"


@dataclass(frozen=True)
class SplitEvent:
    date: str
    ratio: float
    direction: Literal["FORWARD", "REVERSE"]


@dataclass(frozen=True)
class SeriesSegment:
    segment_id: int
    bars: pd.DataFrame


@dataclass(frozen=True)
class LabSeries:
    asset_id: int
    symbol: str
    asset_type: str
    currency: str
    risk_level: str
    data_mode: DataMode
    adjustment_basis: AdjustmentBasis
    segments: tuple[SeriesSegment, ...]
    split_events: tuple[SplitEvent, ...]
    gap_starts: tuple[str, ...]

    def bar_count(self) -> int:
        return sum(len(segment.bars) for segment in self.segments)


def available_data_modes(connection: sqlite3.Connection, asset_id: int) -> frozenset[DataMode]:
    rows = connection.execute(
        "SELECT DISTINCT is_real_data FROM price_history WHERE asset_id = ? AND is_real_data IN (0, 1)",
        (asset_id,),
    ).fetchall()
    return frozenset("REAL" if row[0] == 1 else "DEMO" for row in rows)


def preferred_data_mode(connection: sqlite3.Connection, asset_id: int) -> DataMode | None:
    """REAL se l'asset ha una serie reale, altrimenti DEMO; None senza prezzi."""
    modes = available_data_modes(connection, asset_id)
    if "REAL" in modes:
        return "REAL"
    return "DEMO" if "DEMO" in modes else None


def split_into_segments(
    bars: pd.DataFrame,
    *,
    asset_type: str,
    basis: AdjustmentBasis,
    max_gap_sessions: int,
    split_tolerance: float,
) -> tuple[list[pd.DataFrame], list[SplitEvent], list[str]]:
    """Segmenti, split sospetti e date di inizio dopo un buco. Precondizione: date ordinate e uniche."""
    if bars.empty:
        return [], [], []
    days = np.asarray(bars["date"], dtype="datetime64[D]")
    if asset_type == "crypto":
        missing = (days[1:] - days[:-1]).astype(np.int64) - 1
    else:
        missing = np.busday_count(days[:-1] + np.timedelta64(1, "D"), days[1:])
    gap = np.r_[False, missing > max_gap_sessions]
    if basis == "UNKNOWN":
        ratio, direction = _suspected_splits(bars, split_tolerance)
    else:
        ratio, direction = np.full(len(bars), np.nan), np.full(len(bars), None, dtype=object)
    split = ~np.isnan(ratio)

    starts = np.flatnonzero(np.r_[True, (gap | split)[1:]])
    ends = np.r_[starts[1:], len(bars)]
    segments = [bars.iloc[start:end].reset_index(drop=True) for start, end in zip(starts, ends, strict=True)]
    events = [
        SplitEvent(date=str(bars["date"].iloc[index]), ratio=float(ratio[index]), direction=direction[index])
        for index in np.flatnonzero(split)
    ]
    gap_starts = [str(bars["date"].iloc[index]) for index in np.flatnonzero(gap)]
    return segments, events, gap_starts


def _suspected_splits(bars: pd.DataFrame, tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    """Rapporto e direzione dello split sospetto per barra (NaN/None se assente), spec §6.3.

    Split alla barra t se, per un k in SPLIT_RATIOS, close(t-1)/close(t) (FORWARD) o close(t)/close(t-1) (REVERSE)
    dista meno di `tolerance` relativa da k, e lo stesso vale per close(t-1)/open(t) o open(t)/close(t-1).
    """
    close = bars["close"].to_numpy(dtype=float)
    open_ = bars["open"].to_numpy(dtype=float)
    previous_close = np.r_[np.nan, close[:-1]]
    ratio = np.full(close.shape[0], np.nan)
    direction = np.full(close.shape[0], None, dtype=object)
    with np.errstate(divide="ignore", invalid="ignore"):
        candidates = (
            ("FORWARD", previous_close / close, previous_close / open_),
            ("REVERSE", close / previous_close, open_ / previous_close),
        )
        for k in SPLIT_RATIOS:
            for name, close_ratio, open_ratio in candidates:
                hit = (
                    (np.abs(close_ratio / k - 1) < tolerance)
                    & (np.abs(open_ratio / k - 1) < tolerance)
                    & np.isnan(ratio)
                )
                ratio[hit] = k
                direction[hit] = name
    return ratio, direction


def load_series(connection: sqlite3.Connection, asset_id: int, data_mode: DataMode) -> LabSeries | None:
    """Serie dell'asset nel solo `data_mode` richiesto, divisa in segmenti; None senza asset o senza righe."""
    is_real_data = _IS_REAL_DATA[data_mode]
    asset = connection.execute(
        "SELECT id, symbol, asset_type, currency, risk_level FROM assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    if asset is None:
        return None
    rows = connection.execute(
        """
        SELECT substr(date, 1, 10) AS day, open, high, low, close, adjusted_close, volume, provider
        FROM price_history
        WHERE asset_id = ? AND is_real_data = ?
        ORDER BY day, id
        """,
        (asset_id, is_real_data),
    ).fetchall()
    if not rows:
        return None

    frame = pd.DataFrame([tuple(row) for row in rows], columns=[*_BAR_COLUMNS, "provider"])
    frame = frame.drop_duplicates("date", keep="last").reset_index(drop=True)
    basis = _series_basis(frame["provider"])
    bars = pd.DataFrame({"date": frame["date"].astype(str)})
    for column in _BAR_COLUMNS[1:]:
        bars[column] = frame[column].astype(float)
    if basis in _UNIT_FACTOR_BASES:
        bars["adjusted_close"] = bars["close"]
    else:
        bars["adjusted_close"] = bars["adjusted_close"].fillna(bars["close"])

    settings = get_settings()
    asset_key, symbol, asset_type, currency, risk_level = tuple(asset)
    segments, events, gap_starts = split_into_segments(
        bars,
        asset_type=str(asset_type),
        basis=basis,
        max_gap_sessions=settings.lab_segment_max_gap_sessions,
        split_tolerance=settings.lab_split_tolerance,
    )
    return LabSeries(
        asset_id=int(asset_key),
        symbol=str(symbol),
        asset_type=str(asset_type),
        currency=str(currency),
        risk_level=str(risk_level),
        data_mode=data_mode,
        adjustment_basis=basis,
        segments=tuple(SeriesSegment(segment_id, segment) for segment_id, segment in enumerate(segments)),
        split_events=tuple(events),
        gap_starts=tuple(gap_starts),
    )


def _series_basis(providers: pd.Series) -> AdjustmentBasis:
    """Base comune dei provider della serie; UNKNOWN se mancano o differiscono."""
    bases = {PROVIDER_ADJUSTMENT_BASIS.get(provider, "UNKNOWN") for provider in providers}
    return bases.pop() if len(bases) == 1 else "UNKNOWN"


class EurConverter:
    """Prezzi rettificati in EUR con l'ultimo cambio con data <= barra ed eta <= `max_age_days` (spec §6.4).

    I cambi di una valuta si leggono una sola volta per istanza: un convertitore per calcolo.
    """

    def __init__(self, connection: sqlite3.Connection, *, max_age_days: int) -> None:
        self._connection = connection
        self._max_age_days = max_age_days
        self._tables: dict[str, tuple[tuple[np.ndarray, np.ndarray], ...]] = {}

    def rate_on(self, currency: str, on_date: str) -> float | None:
        rate = self._rates(currency, np.array([on_date], dtype="datetime64[D]"))[0]
        return None if np.isnan(rate) else float(rate)

    def convert_bars(self, bars: pd.DataFrame, currency: str) -> tuple[pd.DataFrame, int]:
        """Aggiunge open/high/low/close_eur (NaN senza cambio valido); ritorna anche le barre escluse."""
        rates = self._rates(currency, np.asarray(bars["date"], dtype="datetime64[D]"))
        close = bars["close"].to_numpy(dtype=float)
        adjusted_close = bars["adjusted_close"].to_numpy(dtype=float)
        factor = adjusted_close / close
        converted = bars.copy()
        for column in ("open", "high", "low"):
            converted[f"{column}_eur"] = bars[column].to_numpy(dtype=float) * factor * rates
        converted["close_eur"] = adjusted_close * rates
        return converted, int(np.isnan(rates).sum())

    def _rates(self, currency: str, days: np.ndarray) -> np.ndarray:
        code = currency.strip().upper()
        if code == "EUR":
            return np.ones(days.shape[0])
        if code not in self._tables:
            self._tables[code] = self._load(code)
        result = np.full(days.shape[0], np.nan)
        pending = np.ones(days.shape[0], dtype=bool)
        # Prima la riga diretta; l'inversa solo dove non esiste una diretta con data <= barra.
        for observed, rates in self._tables[code]:
            if observed.shape[0] == 0:
                continue
            index = np.searchsorted(observed, days, side="right") - 1
            found = pending & (index >= 0)
            position = np.clip(index, 0, None)
            age = (days - observed[position]).astype(np.int64)
            valid = found & (age <= self._max_age_days)
            result[valid] = rates[position][valid]
            pending &= ~found
        return result

    def _load(self, code: str) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
        rows = self._connection.execute(
            """
            SELECT from_currency, substr(observed_at, 1, 10) AS day, rate
            FROM fx_rates
            WHERE ((from_currency = ? AND to_currency = 'EUR') OR (from_currency = 'EUR' AND to_currency = ?))
              AND provider <> ?
            ORDER BY observed_at, id
            """,
            (code, code, _DEMO_FX_PROVIDER),
        ).fetchall()
        direct = [(day, float(rate)) for source, day, rate in rows if source == code]
        inverse = [(day, 1.0 / float(rate)) for source, day, rate in rows if source != code]
        return _rate_table(direct), _rate_table(inverse)


def _rate_table(pairs: Sequence[tuple[str, float]]) -> tuple[np.ndarray, np.ndarray]:
    """Una riga per giorno: con righe in ordine (observed_at, id) resta l'ultima, come in `FXService`."""
    latest = dict(pairs)
    return np.array(list(latest), dtype="datetime64[D]"), np.array(list(latest.values()), dtype=float)
