from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import numpy as np
import pandas as pd


def synthetic_bars(n: int, seed: int, start: str = "2018-01-01", freq: str = "B") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    volume = rng.integers(100_000, 2_000_000, n).astype(float)
    dates = pd.date_range(start, periods=n, freq=freq).strftime("%Y-%m-%d")
    return pd.DataFrame(
        {"date": dates, "open": open_, "high": high, "low": low, "close": close,
         "adjusted_close": close, "volume": volume}
    )


def insert_asset(
    connection: sqlite3.Connection,
    symbol: str,
    *,
    asset_type: str = "stock",
    currency: str = "EUR",
    risk_level: str = "medium",
) -> int:
    cursor = connection.execute(
        "INSERT INTO assets (symbol, name, asset_type, currency, risk_level) VALUES (?, ?, ?, ?, ?)",
        (symbol, symbol, asset_type, currency, risk_level),
    )
    return int(cursor.lastrowid)


def insert_bars(
    connection: sqlite3.Connection,
    asset_id: int,
    bars: pd.DataFrame,
    *,
    real: bool,
    provider: str | None,
) -> None:
    """Righe `price_history`; `source` = provider, oppure `real`/`mock` senza provider (vincolo univoco per source)."""
    source = provider or ("real" if real else "mock")
    connection.executemany(
        """
        INSERT INTO price_history (
            asset_id, date, open, high, low, close, adjusted_close, volume, source, provider, is_real_data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                asset_id, row.date, row.open, row.high, row.low, row.close, row.adjusted_close, row.volume,
                source, provider, 1 if real else 0,
            )
            for row in bars.itertuples(index=False)
        ],
    )


def insert_fx(
    connection: sqlite3.Connection,
    currency: str,
    rows: Sequence[tuple[str, float]],
    *,
    provider: str = "ecb",
) -> None:
    """Cambi diretti `currency -> EUR`: righe (observed_at, rate)."""
    connection.executemany(
        """
        INSERT INTO fx_rates (from_currency, to_currency, rate, observed_at, provider, quality)
        VALUES (?, 'EUR', ?, ?, ?, 'reference')
        """,
        [(currency, rate, observed_at, provider) for observed_at, rate in rows],
    )
