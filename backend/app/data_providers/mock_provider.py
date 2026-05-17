from __future__ import annotations

import pandas as pd


class MockMarketDataProvider:
    name = "mock"

    def get_price_history(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"symbol": symbol.upper(), "date": "2026-01-01", "close": 100.0},
                {"symbol": symbol.upper(), "date": "2026-01-02", "close": 101.5},
            ]
        )
