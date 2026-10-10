"""Universo di un run del laboratorio: mercati in EUR, segnale as-of e calendario (spec SP1 §6.1-§6.5, §7.1).

- Un solo `data_mode` per run: REAL usa solo le righe reali, DEMO solo quelle demo (mai mescolate).
- Prima di leggere il segnale, `features_daily` degli asset viene aggiornata (`FeatureStore.refresh_asset`); il segnale
  e quello del feature store (`signal_panel`: solo righe con warm-up completo, W/M as-of nello stesso segmento).
- Barre del periodo `[start, end]` di tutti i segmenti, prezzi rettificati in EUR (`EurConverter`, eta massima
  `ECB_FX_MAX_AGE_DAYS`): le barre senza cambio valido sono escluse e contate, mai colmate. Calendario = unione delle
  date delle barre utilizzabili (spec §7.1: ogni asset agisce solo sulle proprie barre).
- Esclusi (simbolo -> motivo): `NOT_FOUND`, `AMBIGUOUS_SYMBOL`, `NO_REAL_SERIES` / `NO_DEMO_SERIES`,
  `NO_BARS_IN_PERIOD`, `NO_FX` (nessuna barra del periodo con cambio valido), `NO_VALID_PRICES`, `NO_FEATURES`
  (nessuna riga del segnale con warm-up completo sulle barre del periodo).
- Universo vuoto: `LAB_NO_REAL_SERIES` in REAL se nessun asset ha una serie reale, altrimenti `LAB_EMPTY_UNIVERSE`.
- `inputs_hash`: SHA-256 canonico di barre in EUR, segmenti, segnale, calendario ed esclusi.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from backend.app.config import get_settings
from backend.app.lab.contracts import DataMode, LabError, Timeframe
from backend.app.lab.feature_store import FeatureStore
from backend.app.lab.series import EurConverter, LabSeries, SplitEvent, load_series
from backend.app.lab.simulator import PRICE_COLUMNS, AssetMarket
from backend.app.lab.trials import canonical_hash

BAR_COLUMNS: tuple[str, ...] = (*PRICE_COLUMNS, "segment_id")
_MISSING_SERIES_REASONS = frozenset({"NOT_FOUND", "AMBIGUOUS_SYMBOL", "NO_REAL_SERIES"})
_LISTED_EXCLUSIONS = 10


@dataclass(frozen=True)
class UniverseInputs:
    markets: dict[int, AssetMarket]
    signals: pd.DataFrame                    # indice = calendario, colonne = asset_id
    calendar: list[str]
    excluded: dict[str, str]                 # simbolo -> motivo
    split_events: dict[str, list[SplitEvent]]
    fx_excluded_bars: int
    inputs_hash: str
    asset_types: dict[int, str]
    adjustment_basis: dict[int, str]


def build_universe_inputs(
    connection: sqlite3.Connection,
    symbols: Sequence[str] | None,
    *,
    data_mode: DataMode,
    signal_name: str,
    signal_timeframe: Timeframe,
    start: str,
    end: str,
    now: datetime,
    progress: Callable[[float], None] | None = None,
) -> UniverseInputs:
    """Universo del run; simboli None = tutti gli asset attivi. `progress` riceve la quota di asset elaborati."""
    if end < start:
        raise LabError("LAB_INVALID_PERIOD", "La data fine deve essere uguale o successiva alla data inizio.")
    candidates, excluded = _resolve_assets(connection, symbols)
    store = FeatureStore()
    converter = EurConverter(connection, max_age_days=get_settings().ecb_fx_max_age_days)
    markets: dict[int, AssetMarket] = {}
    series_by_id: dict[int, LabSeries] = {}
    keys: dict[int, str] = {}
    fx_excluded = 0
    for index, (asset_id, key) in enumerate(candidates):
        series = load_series(connection, asset_id, data_mode)
        if series is None:
            excluded[key] = f"NO_{data_mode}_SERIES"
        else:
            store.refresh_asset(connection, asset_id, data_mode, now)
            reason, bars, missing = _market_bars(series, converter, start, end)
            fx_excluded += missing
            if reason is not None:
                excluded[key] = reason
            else:
                markets[asset_id] = AssetMarket(asset_id, series.symbol, series.asset_type, bars)
                series_by_id[asset_id] = series
                keys[asset_id] = key
        if progress is not None:
            progress((index + 1) / len(candidates))

    signals = store.signal_panel(
        connection, list(markets), signal_timeframe, data_mode, signal_name, _calendar(markets)
    )
    for asset_id, market in list(markets.items()):
        values = signals.loc[list(market.bars.index), asset_id].to_numpy(dtype=float)
        if not np.isfinite(values).any():
            excluded[keys[asset_id]] = "NO_FEATURES"
            del markets[asset_id]
    if not markets:
        raise _empty_universe(data_mode, excluded)

    markets = {asset_id: markets[asset_id] for asset_id in sorted(markets)}
    calendar = _calendar(markets)
    signals = signals.reindex(
        index=pd.Index(calendar, name="date"), columns=pd.Index(list(markets), name="asset_id")
    )
    excluded = dict(sorted(excluded.items()))
    split_events = {
        keys[asset_id]: events
        for asset_id in markets
        if (events := [event for event in series_by_id[asset_id].split_events if event.date <= end])
    }
    inputs_hash = canonical_hash(
        {
            "data_mode": data_mode,
            "signal": {"name": signal_name, "timeframe": signal_timeframe},
            "calendar": calendar,
            "excluded": excluded,
            "assets": [
                {
                    "asset_id": asset_id,
                    "symbol": market.symbol,
                    "asset_type": market.asset_type,
                    "currency": series_by_id[asset_id].currency,
                    "bars": _bar_rows(market.bars),
                    "signal": _values(signals[asset_id]),
                }
                for asset_id, market in markets.items()
            ],
        }
    )
    return UniverseInputs(
        markets=markets,
        signals=signals,
        calendar=calendar,
        excluded=excluded,
        split_events=split_events,
        fx_excluded_bars=fx_excluded,
        inputs_hash=inputs_hash,
        asset_types={asset_id: market.asset_type for asset_id, market in markets.items()},
        adjustment_basis={asset_id: series_by_id[asset_id].adjustment_basis for asset_id in markets},
    )


@dataclass(frozen=True)
class BenchmarkSnapshot:
    """Input effettivi e crescita EUR dello stesso calcolo, serializzabili senza rileggere le fonti."""

    payload: dict[str, object]

    @property
    def inputs_hash(self) -> str:
        return canonical_hash(self.payload)

    @property
    def curve(self) -> pd.Series | None:
        if self.payload["status"] != "AVAILABLE":
            return None
        points = self.payload["curve"]
        return pd.Series(
            [value for _day, value in points], index=[day for day, _value in points], dtype=float
        )


def benchmark_snapshot(
    connection: sqlite3.Connection,
    symbol: str,
    *,
    data_mode: DataMode,
    calendar: Sequence[str],
) -> BenchmarkSnapshot:
    """Congela barre native, segmenti, cambi as-of usati e curva normalizzata nel solo data_mode richiesto.

    La crescita concatena i rendimenti del close rettificato EUR dentro lo stesso segmento, poi allinea
    l'ultimo valore noto al calendario. L'assenza di dati/cambi e anch'essa parte dell'impronta.
    """
    days = [str(day) for day in calendar]
    payload: dict[str, object] = {
        "version": 1, "symbol": symbol.strip().upper(), "data_mode": data_mode, "calendar": days,
        "status": "UNAVAILABLE", "reason": "NO_CALENDAR", "inputs": {}, "curve": [],
    }
    if not days:
        return BenchmarkSnapshot(payload)
    rows = connection.execute(
        "SELECT id FROM assets WHERE UPPER(symbol) = ? ORDER BY id", (payload["symbol"],)
    ).fetchall()
    if len(rows) != 1:
        payload["reason"] = "NOT_FOUND" if not rows else "AMBIGUOUS_SYMBOL"
        return BenchmarkSnapshot(payload)
    asset_id = int(rows[0][0])
    payload["inputs"] = {"asset_id": asset_id}
    series = load_series(connection, asset_id, data_mode)
    if series is None:
        payload["reason"] = f"NO_{data_mode}_SERIES"
        return BenchmarkSnapshot(payload)
    bars = _all_bars(series)
    bars = bars[bars["date"] <= days[-1]].reset_index(drop=True)
    max_age_days = get_settings().ecb_fx_max_age_days
    converter = EurConverter(connection, max_age_days=max_age_days)
    converted, _missing = converter.convert_bars(bars, series.currency)
    payload["inputs"] = {
        "asset_id": asset_id, "currency": series.currency, "asset_type": series.asset_type,
        "adjustment_basis": series.adjustment_basis,
        "bars": [
            [str(day), *prices, int(segment)]
            for day, prices, segment in zip(
                bars["date"],
                [
                    [float(value) if math.isfinite(float(value)) else None for value in row]
                    for row in bars[["open", "high", "low", "close", "adjusted_close"]].to_numpy()
                ],
                bars["segment_id"], strict=True,
            )
        ],
        "fx": {
            "max_age_days": max_age_days,
            "rates": [[str(day), converter.rate_on(series.currency, str(day))] for day in bars["date"]],
        },
    }
    if bars.empty:
        payload["reason"] = "NO_BARS"
        return BenchmarkSnapshot(payload)
    close = converted["close_eur"].to_numpy(dtype=float)
    valid = np.isfinite(close) & (close > 0)
    if not valid.any():
        payload["reason"] = "NO_VALID_EUR_PRICES"
        return BenchmarkSnapshot(payload)
    close = close[valid]
    segments = converted["segment_id"].to_numpy()[valid]
    ratio = np.ones(close.shape[0])
    same_segment = segments[1:] == segments[:-1]
    ratio[1:] = np.where(same_segment, close[1:] / close[:-1], 1.0)
    chained = pd.Series(np.cumprod(ratio), index=converted["date"].to_numpy()[valid])
    aligned = chained.reindex(chained.index.union(pd.Index(days))).ffill().reindex(days)
    base = aligned.dropna()
    if base.empty:
        payload["reason"] = "NO_VALUE_ON_CALENDAR"
        return BenchmarkSnapshot(payload)
    curve = aligned / float(base.iloc[0])
    payload.update(status="AVAILABLE", reason=None, curve=list(zip(days, _values(curve), strict=True)))
    return BenchmarkSnapshot(payload)


def benchmark_curve(
    connection: sqlite3.Connection,
    symbol: str,
    *,
    data_mode: DataMode,
    calendar: Sequence[str],
) -> pd.Series | None:
    """Crescita EUR del benchmark; compatibilita per i chiamanti che non persistono uno snapshot."""
    return benchmark_snapshot(connection, symbol, data_mode=data_mode, calendar=calendar).curve


def _resolve_assets(
    connection: sqlite3.Connection, symbols: Sequence[str] | None
) -> tuple[list[tuple[int, str]], dict[str, str]]:
    by_symbol: dict[str, list[int]] = {}
    for asset_id, symbol in connection.execute("SELECT id, UPPER(symbol) FROM assets ORDER BY id"):
        by_symbol.setdefault(str(symbol), []).append(int(asset_id))
    if symbols is None:
        requested = sorted(by_symbol)
    else:
        requested = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()))
    candidates: list[tuple[int, str]] = []
    excluded: dict[str, str] = {}
    for key in requested:
        ids = by_symbol.get(key, [])
        if not ids:
            excluded[key] = "NOT_FOUND"
        elif len(ids) > 1:
            excluded[key] = "AMBIGUOUS_SYMBOL"
        else:
            candidates.append((ids[0], key))
    return sorted(candidates), excluded


def _all_bars(series: LabSeries) -> pd.DataFrame:
    frames = [segment.bars.assign(segment_id=segment.segment_id) for segment in series.segments]
    return pd.concat(frames, ignore_index=True)


def _market_bars(
    series: LabSeries, converter: EurConverter, start: str, end: str
) -> tuple[str | None, pd.DataFrame, int]:
    """(motivo di esclusione o None, barre utilizzabili in EUR indicizzate per data, barre senza cambio valido)."""
    bars = _all_bars(series)
    bars = bars[(bars["date"] >= start) & (bars["date"] <= end)].reset_index(drop=True)
    if bars.empty:
        return "NO_BARS_IN_PERIOD", bars, 0
    converted, missing = converter.convert_bars(bars, series.currency)
    prices = converted[list(PRICE_COLUMNS)].to_numpy(dtype=float)
    usable = np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    if not usable.any():
        return ("NO_FX" if missing else "NO_VALID_PRICES"), converted, missing
    market = converted.loc[usable, ["date", *BAR_COLUMNS]].set_index("date")
    market["segment_id"] = market["segment_id"].astype(int)
    return None, market, missing


def _calendar(markets: dict[int, AssetMarket]) -> list[str]:
    days: set[str] = set()
    for market in markets.values():
        days.update(str(day) for day in market.bars.index)
    return sorted(days)


def _bar_rows(bars: pd.DataFrame) -> list[list[object]]:
    prices = bars[list(PRICE_COLUMNS)].to_numpy(dtype=float).tolist()
    segments = bars["segment_id"].astype(int).tolist()
    return [[str(day), *row, segment] for day, row, segment in zip(bars.index, prices, segments, strict=True)]


def _values(column: pd.Series) -> list[float | None]:
    return [value if math.isfinite(value) else None for value in column.to_numpy(dtype=float).tolist()]


def no_real_series_error() -> LabError:
    """409 `LAB_NO_REAL_SERIES` (spec §6.1): in modalita REAL nessun asset dell'universo ha una serie reale."""
    return LabError(
        "LAB_NO_REAL_SERIES",
        "Nessun asset selezionato ha una serie reale: aggiorna i dati reali oppure usa la modalita DEMO.",
    )


def _empty_universe(data_mode: DataMode, excluded: dict[str, str]) -> LabError:
    if data_mode == "REAL" and set(excluded.values()) <= _MISSING_SERIES_REASONS:
        return no_real_series_error()
    listed = ", ".join(f"{symbol[:24]} ({reason})" for symbol, reason in sorted(excluded.items())[:_LISTED_EXCLUSIONS])
    detail = f" Esclusi: {listed}." if listed else ""
    return LabError("LAB_EMPTY_UNIVERSE", f"Nessun asset utilizzabile nel periodo richiesto.{detail}")
