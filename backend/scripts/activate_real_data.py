"""Refresh manuale dei prezzi reali rispettando il limite Alpha Vantage (5 chiamate/min).

Uso una tantum: popola price_history con dati reali per azioni/ETF.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.database import db_session  # noqa: E402
from backend.app.services.market_data_service import MarketDataService  # noqa: E402

PACE_SECONDS = 13  # < 5 chiamate/min
service = MarketDataService()

with db_session() as connection:
    rows = connection.execute(
        "SELECT symbol, asset_type FROM assets "
        "WHERE asset_type IN ('stock','etf','bond_etf') ORDER BY asset_type, symbol"
    ).fetchall()
    symbols = [(r["symbol"], r["asset_type"]) for r in rows]

print(f"Asset da aggiornare (Alpha Vantage): {len(symbols)}", flush=True)
real = 0
fallback = 0
for index, (symbol, asset_type) in enumerate(symbols, start=1):
    with db_session() as connection:
        result = service.refresh_asset_prices(connection, symbol, force=True)
    used_fallback = result.get("used_fallback", True)
    if used_fallback:
        fallback += 1
        print(f"  {index:2d}. {symbol:6s} [{asset_type}] -> SEED ({result.get('message','')})", flush=True)
    else:
        real += 1
        print(
            f"  {index:2d}. {symbol:6s} [{asset_type}] -> REALE "
            f"(+{result.get('rows_inserted',0)} righe)",
            flush=True,
        )
    if index < len(symbols):
        time.sleep(PACE_SECONDS)

print(f"\nRISULTATO: {real} reali, {fallback} su dati seed.", flush=True)
