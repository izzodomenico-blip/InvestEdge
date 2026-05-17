from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.database import db_session, init_db
from backend.app.models import PortfolioInitIn, SimulatedOrderIn
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.scoring_engine import ScoringEngine


FIXED_SEED = 20260517
SEED_END_DATE = date(2026, 5, 17)
SEED_CREATED_AT = "2026-05-17T00:00:00"


ASSETS: list[dict[str, Any]] = [
    {"symbol": "AAPL", "name": "Apple Inc.", "asset_type": "stock", "currency": "USD", "exchange": "NASDAQ", "sector": "Technology", "country": "USA", "risk_level": "medium", "start_price": 178.0, "drift": 0.12, "volatility": 0.26, "volume": 58_000_000},
    {"symbol": "MSFT", "name": "Microsoft Corp.", "asset_type": "stock", "currency": "USD", "exchange": "NASDAQ", "sector": "Technology", "country": "USA", "risk_level": "medium", "start_price": 416.0, "drift": 0.11, "volatility": 0.23, "volume": 23_000_000},
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "asset_type": "stock", "currency": "USD", "exchange": "NASDAQ", "sector": "Technology", "country": "USA", "risk_level": "high", "start_price": 94.0, "drift": 0.24, "volatility": 0.44, "volume": 310_000_000},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "asset_type": "stock", "currency": "USD", "exchange": "NASDAQ", "sector": "Consumer Discretionary", "country": "USA", "risk_level": "medium", "start_price": 182.0, "drift": 0.10, "volatility": 0.28, "volume": 42_000_000},
    {"symbol": "GOOGL", "name": "Alphabet Inc. Class A", "asset_type": "stock", "currency": "USD", "exchange": "NASDAQ", "sector": "Communication Services", "country": "USA", "risk_level": "medium", "start_price": 164.0, "drift": 0.09, "volatility": 0.25, "volume": 31_000_000},
    {"symbol": "META", "name": "Meta Platforms Inc.", "asset_type": "stock", "currency": "USD", "exchange": "NASDAQ", "sector": "Communication Services", "country": "USA", "risk_level": "high", "start_price": 498.0, "drift": 0.14, "volatility": 0.33, "volume": 16_000_000},
    {"symbol": "TSLA", "name": "Tesla Inc.", "asset_type": "stock", "currency": "USD", "exchange": "NASDAQ", "sector": "Consumer Discretionary", "country": "USA", "risk_level": "very_high", "start_price": 176.0, "drift": 0.08, "volatility": 0.52, "volume": 92_000_000},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "asset_type": "stock", "currency": "USD", "exchange": "NYSE", "sector": "Financials", "country": "USA", "risk_level": "medium", "start_price": 198.0, "drift": 0.08, "volatility": 0.22, "volume": 9_500_000},
    {"symbol": "UNH", "name": "UnitedHealth Group Inc.", "asset_type": "stock", "currency": "USD", "exchange": "NYSE", "sector": "Healthcare", "country": "USA", "risk_level": "medium", "start_price": 514.0, "drift": 0.07, "volatility": 0.21, "volume": 3_700_000},
    {"symbol": "KO", "name": "The Coca-Cola Company", "asset_type": "stock", "currency": "USD", "exchange": "NYSE", "sector": "Consumer Staples", "country": "USA", "risk_level": "low", "start_price": 62.0, "drift": 0.05, "volatility": 0.14, "volume": 12_000_000},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "asset_type": "etf", "currency": "USD", "exchange": "NYSE Arca", "sector": "Broad Market", "country": "USA", "risk_level": "medium", "start_price": 520.0, "drift": 0.08, "volatility": 0.16, "volume": 72_000_000},
    {"symbol": "QQQ", "name": "Invesco QQQ Trust", "asset_type": "etf", "currency": "USD", "exchange": "NASDAQ", "sector": "Technology Growth", "country": "USA", "risk_level": "medium", "start_price": 444.0, "drift": 0.10, "volatility": 0.20, "volume": 48_000_000},
    {"symbol": "VOO", "name": "Vanguard S&P 500 ETF", "asset_type": "etf", "currency": "USD", "exchange": "NYSE Arca", "sector": "Broad Market", "country": "USA", "risk_level": "medium", "start_price": 478.0, "drift": 0.08, "volatility": 0.16, "volume": 6_200_000},
    {"symbol": "VWCE", "name": "Vanguard FTSE All-World UCITS ETF", "asset_type": "etf", "currency": "EUR", "exchange": "XETRA", "sector": "Global Equity", "country": "Ireland", "risk_level": "medium", "start_price": 116.0, "drift": 0.07, "volatility": 0.15, "volume": 420_000},
    {"symbol": "AGGH", "name": "iShares Core Global Aggregate Bond UCITS ETF", "asset_type": "etf", "currency": "EUR", "exchange": "XETRA", "sector": "Global Bonds", "country": "Ireland", "risk_level": "low", "start_price": 5.0, "drift": 0.025, "volatility": 0.06, "volume": 1_400_000},
    {"symbol": "BTC", "name": "Bitcoin", "asset_type": "crypto", "currency": "USD", "exchange": "Crypto", "sector": "Digital Assets", "country": "Global", "risk_level": "very_high", "start_price": 64000.0, "drift": 0.20, "volatility": 0.64, "volume": 34_000_000_000},
    {"symbol": "ETH", "name": "Ethereum", "asset_type": "crypto", "currency": "USD", "exchange": "Crypto", "sector": "Digital Assets", "country": "Global", "risk_level": "very_high", "start_price": 3200.0, "drift": 0.18, "volatility": 0.70, "volume": 15_000_000_000},
    {"symbol": "SOL", "name": "Solana", "asset_type": "crypto", "currency": "USD", "exchange": "Crypto", "sector": "Digital Assets", "country": "Global", "risk_level": "very_high", "start_price": 150.0, "drift": 0.25, "volatility": 0.86, "volume": 3_300_000_000},
    {"symbol": "BNB", "name": "BNB", "asset_type": "crypto", "currency": "USD", "exchange": "Crypto", "sector": "Digital Assets", "country": "Global", "risk_level": "high", "start_price": 580.0, "drift": 0.12, "volatility": 0.58, "volume": 1_900_000_000},
    {"symbol": "XRP", "name": "XRP", "asset_type": "crypto", "currency": "USD", "exchange": "Crypto", "sector": "Digital Assets", "country": "Global", "risk_level": "very_high", "start_price": 0.58, "drift": 0.10, "volatility": 0.78, "volume": 1_700_000_000},
    {"symbol": "IB01", "name": "iShares USD Treasury Bond 0-1yr UCITS ETF", "asset_type": "bond_etf", "currency": "USD", "exchange": "LSE", "sector": "Short Treasury", "country": "Ireland", "risk_level": "low", "start_price": 110.0, "drift": 0.035, "volatility": 0.025, "volume": 120_000},
    {"symbol": "BTP10Y", "name": "Italian Government Bond 10Y", "asset_type": "bond", "currency": "EUR", "exchange": "MOT", "sector": "Government Bonds", "country": "Italy", "risk_level": "medium", "start_price": 96.5, "drift": 0.025, "volatility": 0.09, "volume": 85_000},
    {"symbol": "TLT", "name": "iShares 20+ Year Treasury Bond ETF", "asset_type": "bond_etf", "currency": "USD", "exchange": "NASDAQ", "sector": "Long Treasury", "country": "USA", "risk_level": "medium", "start_price": 91.0, "drift": 0.025, "volatility": 0.16, "volume": 41_000_000},
    {"symbol": "IEF", "name": "iShares 7-10 Year Treasury Bond ETF", "asset_type": "bond_etf", "currency": "USD", "exchange": "NASDAQ", "sector": "Intermediate Treasury", "country": "USA", "risk_level": "low", "start_price": 94.0, "drift": 0.025, "volatility": 0.08, "volume": 7_800_000},
    {"symbol": "SHY", "name": "iShares 1-3 Year Treasury Bond ETF", "asset_type": "bond_etf", "currency": "USD", "exchange": "NASDAQ", "sector": "Short Treasury", "country": "USA", "risk_level": "low", "start_price": 81.0, "drift": 0.025, "volatility": 0.025, "volume": 5_900_000},
]


def _dates_for_asset(asset_type: str) -> list[date]:
    start = SEED_END_DATE - timedelta(days=730)
    days = [start + timedelta(days=offset) for offset in range((SEED_END_DATE - start).days + 1)]
    if asset_type == "crypto":
        return days
    return [day for day in days if day.weekday() < 5]


def _generate_price_history(asset: dict[str, Any], index: int) -> list[dict[str, Any]]:
    rng = np.random.default_rng(FIXED_SEED + (index * 101))
    dates = _dates_for_asset(asset["asset_type"])
    periods_per_year = 365 if asset["asset_type"] == "crypto" else 252
    daily_drift = asset["drift"] / periods_per_year
    daily_volatility = asset["volatility"] / np.sqrt(periods_per_year)

    close = float(asset["start_price"])
    rows: list[dict[str, Any]] = []

    for current_date in dates:
        shock = rng.normal(daily_drift, daily_volatility)
        new_close = max(close * (1 + shock), 0.01)
        open_price = close * (1 + rng.normal(0, daily_volatility * 0.25))
        intraday_range = abs(rng.normal(daily_volatility * 0.75, daily_volatility * 0.35))
        high = max(open_price, new_close) * (1 + intraday_range)
        low = min(open_price, new_close) * (1 - intraday_range)
        volume_noise = max(0.18, 1 + rng.normal(0, 0.24 if asset["asset_type"] == "crypto" else 0.16))
        volume = float(asset["volume"]) * volume_noise

        rows.append(
            {
                "date": current_date.isoformat(),
                "open": round(open_price, 4),
                "high": round(high, 4),
                "low": round(max(low, 0.01), 4),
                "close": round(new_close, 4),
                "adjusted_close": round(new_close, 4),
                "volume": round(volume, 2),
                "source": "seed",
                "created_at": SEED_CREATED_AT,
            }
        )
        close = new_close

    return rows


def _reset_seed_data(connection) -> None:
    connection.execute("DELETE FROM portfolio_snapshots")
    connection.execute("DELETE FROM simulated_orders")
    connection.execute("DELETE FROM portfolio_positions")
    connection.execute("DELETE FROM portfolio_settings")
    connection.execute("DELETE FROM backtest_runs")

    symbols = [asset["symbol"] for asset in ASSETS]
    placeholders = ",".join("?" for _ in symbols)
    asset_rows = connection.execute(
        f"SELECT id FROM assets WHERE symbol IN ({placeholders})",
        symbols,
    ).fetchall()
    asset_ids = [row["id"] for row in asset_rows]
    if not asset_ids:
        return

    id_placeholders = ",".join("?" for _ in asset_ids)
    connection.execute(
        f"DELETE FROM price_history WHERE asset_id IN ({id_placeholders}) AND source = 'seed'",
        asset_ids,
    )
    connection.execute(
        f"DELETE FROM signals WHERE asset_id IN ({id_placeholders}) AND source = 'scoring_engine'",
        asset_ids,
    )
    connection.execute(f"DELETE FROM assets WHERE id IN ({id_placeholders})", asset_ids)


def _historical_close(connection, symbol: str, days_ago: int) -> float:
    target_date = (SEED_END_DATE - timedelta(days=days_ago)).isoformat()
    row = connection.execute(
        """
        SELECT ph.close
        FROM price_history ph
        JOIN assets a ON a.id = ph.asset_id
        WHERE a.symbol = ? AND ph.date <= ?
        ORDER BY ph.date DESC
        LIMIT 1
        """,
        (symbol, target_date),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Prezzo storico non disponibile per {symbol}.")
    return float(row["close"])


def _create_demo_portfolio(connection) -> dict[str, int]:
    engine = PortfolioEngine()
    engine.initialize_portfolio(
        connection,
        PortfolioInitIn(
            initial_cash=100000,
            max_single_asset_weight=25,
            max_asset_class_weight=55,
            default_fee_percent=0.1,
        ),
    )

    demo_orders = [
        ("SPY", 40, 330, "Core ETF USA"),
        ("QQQ", 30, 300, "Growth ETF"),
        ("AAPL", 50, 260, "Quality stock"),
        ("MSFT", 25, 220, "Quality stock"),
        ("NVDA", 80, 180, "Momentum tech"),
        ("BTC", 0.18, 140, "Crypto satellite"),
        ("ETH", 2.5, 120, "Crypto satellite"),
    ]

    for symbol, quantity, days_ago, tag in demo_orders:
        engine.simulate_order(
            connection,
            SimulatedOrderIn(
                symbol=symbol,
                order_type="BUY",
                quantity=quantity,
                price=_historical_close(connection, symbol, days_ago),
                note=f"Demo seed paper trade generato a {days_ago} giorni dal seed.",
                strategy_tag=tag,
            ),
        )

    engine.refresh_portfolio(connection, create_snapshot=True)
    positions_count = connection.execute(
        "SELECT COUNT(*) AS count FROM portfolio_positions WHERE quantity > 0"
    ).fetchone()["count"]
    orders_count = connection.execute("SELECT COUNT(*) AS count FROM simulated_orders").fetchone()["count"]
    snapshots_count = connection.execute("SELECT COUNT(*) AS count FROM portfolio_snapshots").fetchone()["count"]
    return {
        "portfolio_positions_inserted": positions_count,
        "simulated_orders_inserted": orders_count,
        "portfolio_snapshots_inserted": snapshots_count,
    }


def seed_database(reset: bool = False) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    init_db()

    price_rows_inserted = 0
    signals_inserted = 0
    portfolio_summary = {
        "portfolio_positions_inserted": 0,
        "simulated_orders_inserted": 0,
        "portfolio_snapshots_inserted": 0,
    }
    scoring_engine = ScoringEngine()

    with db_session() as connection:
        if reset:
            _reset_seed_data(connection)

        for index, asset in enumerate(ASSETS):
            connection.execute(
                """
                INSERT INTO assets (
                    symbol, name, asset_type, currency, exchange, sector, country, risk_level, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, asset_type) DO UPDATE SET
                    name = excluded.name,
                    currency = excluded.currency,
                    exchange = excluded.exchange,
                    sector = excluded.sector,
                    country = excluded.country,
                    risk_level = excluded.risk_level,
                    updated_at = excluded.updated_at
                """,
                (
                    asset["symbol"],
                    asset["name"],
                    asset["asset_type"],
                    asset["currency"],
                    asset["exchange"],
                    asset["sector"],
                    asset["country"],
                    asset["risk_level"],
                    SEED_CREATED_AT,
                    SEED_CREATED_AT,
                ),
            )

            asset_id = connection.execute(
                "SELECT id FROM assets WHERE symbol = ? AND asset_type = ?",
                (asset["symbol"], asset["asset_type"]),
            ).fetchone()["id"]

            price_rows = _generate_price_history(asset, index)
            connection.executemany(
                """
                INSERT INTO price_history (
                    asset_id, date, open, high, low, close, adjusted_close, volume, source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id, date, source) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    adjusted_close = excluded.adjusted_close,
                    volume = excluded.volume,
                    created_at = excluded.created_at
                """,
                [
                    (
                        asset_id,
                        row["date"],
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row["adjusted_close"],
                        row["volume"],
                        row["source"],
                        row["created_at"],
                    )
                    for row in price_rows
                ],
            )
            price_rows_inserted += len(price_rows)

            prices_frame = pd.DataFrame(price_rows)
            score = scoring_engine.score_prices(
                prices_frame,
                asset_id=asset_id,
                symbol=asset["symbol"],
                risk_level=asset["risk_level"],
            )
            connection.execute(
                "DELETE FROM signals WHERE asset_id = ? AND source = 'scoring_engine'",
                (asset_id,),
            )
            connection.execute(
                """
                INSERT INTO signals (
                    asset_id, symbol, signal, score, risk_level, confidence, technical_summary,
                    reasons_json, subscores_json, indicators_json, rationale, source, generated_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scoring_engine', ?, ?, ?)
                """,
                (
                    asset_id,
                    score["symbol"],
                    score["signal"],
                    score["score"],
                    score["risk_level"],
                    score["confidence"],
                    score["technical_summary"],
                    json.dumps(score["reasons"]),
                    json.dumps(score["subscores"]),
                    json.dumps(score["indicators"]),
                    score["technical_summary"],
                    SEED_CREATED_AT,
                    SEED_CREATED_AT,
                    SEED_CREATED_AT,
                ),
            )
            signals_inserted += 1

        if reset:
            portfolio_summary = _create_demo_portfolio(connection)

    completed_at = datetime.now().isoformat(timespec="seconds")
    return {
        "reset": reset,
        "assets_inserted": len(ASSETS),
        "price_rows_inserted": price_rows_inserted,
        "signals_inserted": signals_inserted,
        **portfolio_summary,
        "started_at": started_at,
        "completed_at": completed_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed InvestEdge SQLite database with deterministic market data.")
    parser.add_argument("--reset", action="store_true", help="Delete previous seed data before inserting.")
    args = parser.parse_args()
    summary = seed_database(reset=args.reset)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
