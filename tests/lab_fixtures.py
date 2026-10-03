from __future__ import annotations

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
