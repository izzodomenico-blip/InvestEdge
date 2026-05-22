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
from backend.app.services.universe_service import UNIVERSE_DIR, UniverseService
from backend.app.services.multi_portfolio_service import MultiPortfolioService


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
    connection.execute("DELETE FROM portfolios")
    connection.execute("DELETE FROM portfolio_cash_transfers")
    connection.execute("DELETE FROM portfolio_settings")
    connection.execute("DELETE FROM backtest_runs")
    connection.execute("DELETE FROM ml_predictions")
    connection.execute("DELETE FROM ml_models")
    connection.execute("DELETE FROM ml_training_runs")
    connection.execute("DELETE FROM asset_universe")

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
    mps = MultiPortfolioService()
    portfolio_id = mps.ensure_default_portfolio(connection)
    
    engine = PortfolioEngine()
    engine.initialize_portfolio(
        connection,
        PortfolioInitIn(
            initial_cash=100000,
            max_single_asset_weight=25,
            max_asset_class_weight=55,
            default_fee_percent=0.1,
        ),
        portfolio_id=portfolio_id
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
            portfolio_id=portfolio_id
        )

    engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=True)
    positions_count = connection.execute(
        "SELECT COUNT(*) AS count FROM portfolio_positions WHERE portfolio_id = ? AND quantity > 0",
        (portfolio_id,)
    ).fetchone()["count"]
    orders_count = connection.execute("SELECT COUNT(*) AS count FROM simulated_orders WHERE portfolio_id = ?", (portfolio_id,)).fetchone()["count"]
    snapshots_count = connection.execute("SELECT COUNT(*) AS count FROM portfolio_snapshots WHERE portfolio_id = ?", (portfolio_id,)).fetchone()["count"]
    return {
        "portfolio_positions_inserted": positions_count,
        "simulated_orders_inserted": orders_count,
        "portfolio_snapshots_inserted": snapshots_count,
    }


def _create_default_alert_rules(connection: sqlite3.Connection):
    rules = [
        ("DATA_STALE_WARNING", "DATA_STALE_WARNING", "WARNING", 7.0),
        ("DATA_QUALITY_BAD", "DATA_QUALITY_BAD", "CRITICAL", 50.0),
        ("SIGNAL_CHANGED", "SIGNAL_CHANGED", "INFO", None),
        ("PORTFOLIO_CONCENTRATION", "PORTFOLIO_CONCENTRATION", "WARNING", 20.0),
        ("API_USAGE_HIGH", "API_USAGE_HIGH", "WARNING", 80.0),
    ]
    for name, a_type, severity, threshold in rules:
        connection.execute(
            """
            INSERT OR IGNORE INTO alert_rules (rule_name, alert_type, severity, threshold_value, enabled)
            VALUES (?, ?, ?, ?, 1)
            """,
            (name, a_type, severity, threshold)
        )


def _create_default_profiles(connection: sqlite3.Connection):
    # Risk Profiles
    risk_profiles = [
        ("Conservative", "CONSERVATIVE", 1, 5, 20, 2, 15, 10, 80, "HIGH", 1, 0, 0, 1, 1, 0, 0, 70, 0, 0, 30),
        ("Balanced", "BALANCED", 1, 15, 40, 10, 5, 15, 60, "MEDIUM", 0, 1, 1, 1, 1, 1, 1, 50, 20, 15, 15),
        ("Aggressive", "AGGRESSIVE", 1, 25, 60, 25, 2, 25, 40, "LOW", 0, 1, 1, 1, 1, 1, 1, 40, 30, 20, 10),
    ]
    for name, p_type, active, msw, macw, mcw, mcr, mpd, mdq, moc, rrd, ac, ass, ab, ae, aml, anl, tw, mw, nw, rw in risk_profiles:
        connection.execute(
            """
            INSERT OR IGNORE INTO risk_profiles (
                profile_name, profile_type, is_active, max_single_asset_weight, max_asset_class_weight,
                max_crypto_weight, min_cash_reserve_percent, max_portfolio_drawdown_percent,
                min_data_quality_score, min_operational_confidence, require_real_data_for_buy,
                allow_crypto, allow_single_stocks, allow_bonds, allow_etf,
                allow_ml_influence, allow_news_influence, technical_weight, ml_weight, news_weight, risk_weight,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, p_type, active if p_type == 'BALANCED' else 0, msw, macw, mcw, mcr, mpd, mdq, moc, rrd, ac, ass, ab, ae, aml, anl, tw, mw, nw, rw, SEED_CREATED_AT, SEED_CREATED_AT)
        )

    # Strategy Profiles
    strat_profiles = [
        ("Conservative Weekly Review", "CORE", 10, "WEEKLY", 75, 45, 60, 75, "HIGH", 8, 20, 0.1, 15, 0, 0, 1, 1),
        ("Balanced Core Rotation", "CORE", 15, "WEEKLY", 70, 40, 55, 70, "MEDIUM", 10, 25, 0.1, 5, 1, 1, 1, 1),
        ("Aggressive Growth Radar", "EXTENDED", 25, "DAILY", 65, 35, 50, 65, "LOW", 15, 40, 0.1, 2, 1, 1, 1, 1),
    ]
    for name, univ, mp, freq, bt, st, wt, msb, mcb, sl, tp, fp, crp, ml, news, sr, opt in strat_profiles:
        connection.execute(
            """
            INSERT OR IGNORE INTO strategy_profiles (
                profile_name, is_active, universe_level, max_positions, rebalance_frequency,
                buy_threshold, sell_threshold, watch_threshold, min_score_for_buy, min_confidence_for_buy,
                stop_loss_percent, take_profit_percent, fee_percent, cash_reserve_percent,
                use_ml, use_news, use_scenario_risk, use_optimizer, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, 1 if "Balanced" in name else 0, univ, mp, freq, bt, st, wt, msb, mcb, sl, tp, fp, crp, ml, news, sr, opt, SEED_CREATED_AT, SEED_CREATED_AT)
        )

    # UI Preferences
    connection.execute(
        """
        INSERT OR IGNORE INTO ui_preferences (theme, default_landing_page, compact_mode, show_advanced_metrics, default_universe_level, default_benchmark, default_currency, created_at, updated_at)
        VALUES ('dark', 'Dashboard', 0, 1, 'CORE', 'SPY', 'USD', ?, ?)
        """,
        (SEED_CREATED_AT, SEED_CREATED_AT)
    )

    from backend.app.services.tax_service import TaxService

    TaxService().ensure_default_settings(connection)


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
    universe_service = UniverseService()
    universe_import_summary = {
        "universe_assets_imported": 0,
        "core_universe_count": 0,
        "extended_universe_count": 0,
        "candidate_universe_count": 0,
    }

    with db_session() as connection:
        if reset:
            _reset_seed_data(connection)

        _create_default_alert_rules(connection)
        _create_default_profiles(connection)

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

        for file_name, level in [
            ("core_universe.csv", "CORE"),
            ("extended_universe.csv", "EXTENDED"),
            ("crypto_universe.csv", "CANDIDATE"),
            ("etf_universe.csv", "CANDIDATE"),
        ]:
            if (UNIVERSE_DIR / file_name).exists():
                universe_service.import_universe_from_csv(connection, file_name, level)

        universe_service.sync_assets(connection, watchlist_symbols={asset["symbol"] for asset in ASSETS})

        if reset:
            portfolio_summary = _create_demo_portfolio(connection)
            universe_service.sync_assets(connection, watchlist_symbols={asset["symbol"] for asset in ASSETS})
            from backend.app.services.tax_service import TaxService

            TaxService().recalculate(connection)

        universe_service.update_refresh_priority(connection)
        universe_summary = universe_service.get_summary(connection)
        universe_import_summary = {
            "universe_assets_imported": universe_summary["total_assets"],
            "core_universe_count": universe_summary["core_count"],
            "extended_universe_count": universe_summary["extended_count"],
            "candidate_universe_count": universe_summary["candidate_count"],
        }

    completed_at = datetime.now().isoformat(timespec="seconds")
    return {
        "reset": reset,
        "assets_inserted": len(ASSETS),
        "price_rows_inserted": price_rows_inserted,
        "signals_inserted": signals_inserted,
        **portfolio_summary,
        **universe_import_summary,
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
