from __future__ import annotations

from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    name: str

    def get_price_history(self, symbol: str) -> pd.DataFrame:
        """Return historical OHLCV data for an asset symbol."""
        ...
