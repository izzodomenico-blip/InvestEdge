from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.config import get_settings
from backend.app.database import SCHEMA, migrate_db
from backend.app.models import PortfolioInitIn, SimulatedOrderIn
from backend.app.services.fx_service import FXRateUnavailable
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.report_service import orders_csv, portfolio_csv
from backend.app.services.scenario_service import run_scenario


@pytest.fixture
def connection(monkeypatch) -> sqlite3.Connection:
    monkeypatch.setenv("ECB_FX_MAX_AGE_DAYS", "7")
    get_settings.cache_clear()
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    migrate_db(connection)
    connection.executemany(
        """
        INSERT INTO assets (symbol, name, asset_type, currency, risk_level)
        VALUES (?, ?, ?, ?, 'medium')
        """,
        [
            ("AAPL", "Apple Inc.", "stock", "USD"),
            ("VWCE", "Vanguard FTSE All-World UCITS ETF", "etf", "EUR"),
        ],
    )
    asset_ids = {
        row["symbol"]: row["id"]
        for row in connection.execute("SELECT id, symbol FROM assets").fetchall()
    }
    connection.executemany(
        """
        INSERT INTO price_history (asset_id, date, close, source)
        VALUES (?, '2026-08-16', ?, 'test')
        """,
        [(asset_ids["AAPL"], 110.0), (asset_ids["VWCE"], 120.0)],
    )
    try:
        yield connection
    finally:
        connection.close()
        get_settings.cache_clear()


def _set_usd_rate(
    connection: sqlite3.Connection,
    rate: float,
    *,
    observed_at: str | None = None,
) -> None:
    connection.execute("DELETE FROM fx_rates WHERE from_currency = 'USD' AND to_currency = 'EUR'")
    connection.execute(
        """
        INSERT INTO fx_rates (
            from_currency, to_currency, rate, observed_at, provider, quality
        )
        VALUES ('USD', 'EUR', ?, ?, 'test', 'reference')
        """,
        (rate, observed_at or datetime.now(UTC).date().isoformat()),
    )


def _initialize(engine: PortfolioEngine, connection: sqlite3.Connection) -> None:
    engine.initialize_portfolio(
        connection,
        PortfolioInitIn(
            initial_cash=10_000,
            max_single_asset_weight=100,
            max_asset_class_weight=100,
            default_fee_percent=0,
        ),
    )


def test_usd_buy_and_mark_keep_native_and_eur_accounting_separate(connection) -> None:
    engine = PortfolioEngine()
    _set_usd_rate(connection, 0.80)
    _initialize(engine, connection)

    result = engine.simulate_order(
        connection,
        SimulatedOrderIn(symbol="AAPL", order_type="BUY", quantity=10, price=100, fees=0),
    )

    order = result.order
    position = result.updated_position
    summary = result.updated_portfolio_summary
    assert position is not None
    assert order.currency == "USD"
    assert order.base_currency == "EUR"
    assert order.fx_rate_to_base == 0.80
    assert order.gross_amount == 1_000
    assert order.gross_amount_base == 800
    assert order.net_amount == 1_000
    assert order.net_amount_base == 800
    assert order.fees_base == 0
    assert position.currency == "USD"
    assert position.base_currency == "EUR"
    assert position.fx_rate_to_base == 0.80
    assert position.average_price == 100
    assert position.average_price_base == 80
    assert position.invested_amount == 1_000
    assert position.invested_amount_base == 800
    assert position.current_price == 110
    assert position.current_value == 1_100
    assert position.current_value_base == 880
    assert position.unrealized_pnl == 100
    assert position.unrealized_pnl_base == 80
    assert summary.base_currency == "EUR"
    assert summary.cash == 9_200
    assert summary.invested_value == 880
    assert summary.total_value == 10_080
    assert summary.unrealized_pnl == 80
    assert position.weight_percent == pytest.approx(880 / 10_080 * 100)


def test_sell_uses_execution_fx_for_fees_cash_and_realized_pnl_base(connection) -> None:
    engine = PortfolioEngine()
    _set_usd_rate(connection, 0.80)
    _initialize(engine, connection)
    engine.simulate_order(
        connection,
        SimulatedOrderIn(symbol="AAPL", order_type="BUY", quantity=10, price=100, fees=10),
    )
    _set_usd_rate(connection, 0.90)

    result = engine.simulate_order(
        connection,
        SimulatedOrderIn(symbol="AAPL", order_type="SELL", quantity=4, price=110, fees=5),
    )

    order = result.order
    position = result.updated_position
    summary = result.updated_portfolio_summary
    assert position is not None
    assert order.fees == 5
    assert order.fees_base == 4.5
    assert order.gross_amount == 440
    assert order.gross_amount_base == 396
    assert order.net_amount == 435
    assert order.net_amount_base == 391.5
    assert position.quantity == 6
    assert position.average_price == 100
    assert position.average_price_base == 80
    assert position.realized_pnl == 25
    assert position.realized_pnl_base == 63.5
    assert position.invested_amount == 600
    assert position.invested_amount_base == 480
    assert position.current_value == 660
    assert position.current_value_base == 594
    assert position.unrealized_pnl == 60
    assert position.unrealized_pnl_base == 114
    assert summary.cash == 9_583.5
    assert summary.realized_pnl == 63.5

    _set_usd_rate(connection, 0.70)
    refreshed = engine.refresh_portfolio(connection, create_snapshot=False)
    refreshed_position = refreshed.positions[0]
    assert refreshed_position.fx_rate_to_base == 0.70
    assert refreshed_position.average_price_base == 80
    assert refreshed_position.realized_pnl_base == 63.5
    assert refreshed.realized_pnl == 63.5


def test_short_cash_value_pnl_and_weight_use_absolute_eur_exposure(connection) -> None:
    engine = PortfolioEngine()
    _set_usd_rate(connection, 0.80)
    _initialize(engine, connection)

    result = engine.simulate_order(
        connection,
        SimulatedOrderIn(
            symbol="AAPL",
            order_type="SELL",
            quantity=5,
            price=100,
            fees=0,
            allow_short=True,
        ),
    )

    position = result.updated_position
    summary = result.updated_portfolio_summary
    assert position is not None
    assert summary.cash == 10_400
    assert position.quantity == -5
    assert position.invested_amount == -500
    assert position.invested_amount_base == -400
    assert position.current_value == -550
    assert position.current_value_base == -440
    assert position.unrealized_pnl == -50
    assert position.unrealized_pnl_base == -40
    assert summary.total_value == 9_960
    assert position.weight_percent == pytest.approx(440 / 9_960 * 100)


def test_mixed_currency_summary_weights_and_scenario_use_eur_values(connection) -> None:
    engine = PortfolioEngine()
    _set_usd_rate(connection, 0.80)
    _initialize(engine, connection)
    engine.simulate_order(
        connection,
        SimulatedOrderIn(symbol="AAPL", order_type="BUY", quantity=10, price=100, fees=0),
    )
    engine.simulate_order(
        connection,
        SimulatedOrderIn(symbol="VWCE", order_type="BUY", quantity=10, price=100, fees=0),
    )

    summary = engine.refresh_portfolio(connection, create_snapshot=False)
    positions = {position.symbol: position for position in summary.positions}
    assert summary.cash == 8_200
    assert summary.invested_value == 2_080
    assert summary.total_value == 10_280
    assert summary.unrealized_pnl == 280
    assert positions["AAPL"].current_value == 1_100
    assert positions["AAPL"].current_value_base == 880
    assert positions["VWCE"].current_value == 1_200
    assert positions["VWCE"].current_value_base == 1_200
    assert positions["AAPL"].weight_percent == pytest.approx(880 / 10_280 * 100)
    assert positions["VWCE"].weight_percent == pytest.approx(1_200 / 10_280 * 100)
    assert summary.allocation_by_currency == {
        "USD": pytest.approx(880 / 10_280 * 100),
        "EUR": pytest.approx(1_200 / 10_280 * 100),
    }

    scenario = run_scenario(
        connection,
        scenario_type="CUSTOM",
        symbol_shocks={"AAPL": -10, "VWCE": -10},
    )
    impacts = {item["symbol"]: item for item in scenario["asset_impacts"]}
    assert scenario["base_currency"] == "EUR"
    assert scenario["current_value"] == 10_280
    assert impacts["AAPL"]["current_value"] == 880
    assert impacts["AAPL"]["absolute_impact"] == -88
    assert impacts["VWCE"]["current_value"] == 1_200
    assert impacts["VWCE"]["absolute_impact"] == -120


def test_missing_fx_blocks_order_without_mutating_portfolio(connection) -> None:
    engine = PortfolioEngine()
    _initialize(engine, connection)

    with pytest.raises(FXRateUnavailable, match="USD/EUR"):
        engine.simulate_order(
            connection,
            SimulatedOrderIn(symbol="AAPL", order_type="BUY", quantity=1, price=100, fees=0),
        )

    settings = engine.ensure_settings(connection)
    assert settings["current_cash"] == 10_000
    assert connection.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM portfolio_positions").fetchone()[0] == 0


def test_stale_fx_blocks_order_without_mutating_portfolio(connection) -> None:
    engine = PortfolioEngine()
    stale_date = (datetime.now(UTC).date() - timedelta(days=8)).isoformat()
    _set_usd_rate(connection, 0.80, observed_at=stale_date)
    _initialize(engine, connection)

    with pytest.raises(FXRateUnavailable, match="obsoleto"):
        engine.simulate_order(
            connection,
            SimulatedOrderIn(symbol="AAPL", order_type="BUY", quantity=1, price=100, fees=0),
        )

    settings = engine.ensure_settings(connection)
    assert settings["current_cash"] == 10_000
    assert connection.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM portfolio_positions").fetchone()[0] == 0


def test_reports_append_currency_fx_and_eur_columns_after_legacy_columns(connection) -> None:
    engine = PortfolioEngine()
    _set_usd_rate(connection, 0.80)
    _initialize(engine, connection)
    engine.simulate_order(
        connection,
        SimulatedOrderIn(symbol="AAPL", order_type="BUY", quantity=10, price=100, fees=2),
    )

    assert portfolio_csv(connection).splitlines()[0] == (
        "symbol,asset_type,quantity,average_price,current_price,current_value,"
        "unrealized_pnl,unrealized_pnl_percent,weight_percent,currency,"
        "fx_rate_to_base,average_price_base,invested_amount,invested_amount_base,"
        "current_value_base,realized_pnl,realized_pnl_base,unrealized_pnl_base,"
        "base_currency"
    )
    assert orders_csv(connection).splitlines()[0] == (
        "date,symbol,type,quantity,price,fees,gross_amount,net_amount,note,strategy,"
        "currency,fx_rate_to_base,fees_base,gross_amount_base,net_amount_base,"
        "base_currency"
    )


def test_seed_uses_deterministic_fx_only_during_setup_and_runtime_stays_fail_closed(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "seed.db"
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    monkeypatch.setenv("ECB_FX_MAX_AGE_DAYS", "7")
    get_settings.cache_clear()
    try:
        from backend.scripts.seed_database import seed_database

        result = seed_database(reset=True)
        assert result["simulated_orders_inserted"] == 7

        with sqlite3.connect(database_path) as seeded_connection:
            seeded_connection.row_factory = sqlite3.Row
            seeded_rate = seeded_connection.execute(
                """
                SELECT id, rate, observed_at, provider, quality
                FROM fx_rates
                WHERE from_currency = 'USD' AND to_currency = 'EUR' AND provider = 'seed'
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            assert seeded_rate["rate"] == 0.92
            assert seeded_rate["observed_at"] == datetime.now(UTC).date().isoformat()
            assert seeded_rate["provider"] == "seed"
            assert seeded_rate["quality"] == "seed"

            stale_date = (datetime.now(UTC).date() - timedelta(days=8)).isoformat()
            seeded_connection.execute(
                "UPDATE fx_rates SET observed_at = ? WHERE id = ?",
                (stale_date, seeded_rate["id"]),
            )
            with pytest.raises(FXRateUnavailable, match="obsoleto"):
                PortfolioEngine().simulate_order(
                    seeded_connection,
                    SimulatedOrderIn(
                        symbol="AAPL",
                        order_type="BUY",
                        quantity=1,
                        price=100,
                        fees=0,
                    ),
                )
    finally:
        get_settings.cache_clear()


def test_refresh_rejects_legacy_usd_cost_basis_instead_of_inventing_historical_fx(
    connection,
) -> None:
    engine = PortfolioEngine()
    _set_usd_rate(connection, 0.80)
    _initialize(engine, connection)
    asset_id = connection.execute("SELECT id FROM assets WHERE symbol = 'AAPL'").fetchone()["id"]
    connection.execute(
        """
        INSERT INTO portfolio_positions (
            asset_id, symbol, quantity, average_price, invested_amount,
            current_price, current_value, asset_type, currency
        )
        VALUES (?, 'AAPL', 10, 100, 1000, 100, 1000, 'stock', 'USD')
        """,
        (asset_id,),
    )

    with pytest.raises(FXRateUnavailable, match="Base di costo EUR"):
        engine.refresh_portfolio(connection, create_snapshot=False)


def test_migration_does_not_rewrite_frozen_order_currency(connection) -> None:
    connection.execute(
        """
        INSERT INTO simulated_orders (
            asset_id, symbol, order_type, side, quantity, price, currency,
            fx_rate_to_base, gross_amount, gross_amount_base, net_amount,
            net_amount_base, fees_base
        )
        SELECT id, symbol, 'BUY', 'BUY', 1, 100, 'USD', 0.8, 100, 80, 100, 80, 0
        FROM assets
        WHERE symbol = 'AAPL'
        """
    )
    connection.execute("UPDATE assets SET currency = 'EUR' WHERE symbol = 'AAPL'")

    migrate_db(connection)

    order = connection.execute("SELECT * FROM simulated_orders").fetchone()
    assert order["currency"] == "USD"
    assert order["fx_rate_to_base"] == 0.8


def test_migration_keeps_legacy_snapshots_out_of_eur_history(connection) -> None:
    connection.execute("DROP TABLE portfolio_snapshots")
    connection.executescript(
        """
        CREATE TABLE portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            total_value REAL NOT NULL DEFAULT 0,
            invested_value REAL NOT NULL DEFAULT 0,
            cash REAL NOT NULL DEFAULT 0,
            realized_pnl REAL NOT NULL DEFAULT 0,
            unrealized_pnl REAL NOT NULL DEFAULT 0,
            total_pnl REAL NOT NULL DEFAULT 0,
            total_pnl_percent REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO portfolio_snapshots (
            snapshot_date, total_value, invested_value, cash, realized_pnl,
            unrealized_pnl, total_pnl, total_pnl_percent
        ) VALUES ('2026-08-15', 11000, 1000, 10000, 0, 0, 0, 0);
        """
    )

    migrate_db(connection)

    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(portfolio_snapshots)")
    }
    assert "base_currency" in columns
    assert PortfolioEngine().list_snapshots(connection) == []


def test_summary_rejects_closed_legacy_usd_realized_pnl_without_base(connection) -> None:
    engine = PortfolioEngine()
    _initialize(engine, connection)
    asset_id = connection.execute("SELECT id FROM assets WHERE symbol = 'AAPL'").fetchone()["id"]
    connection.execute(
        """
        INSERT INTO portfolio_positions (
            asset_id, symbol, quantity, average_price, invested_amount,
            realized_pnl, realized_pnl_base, asset_type, currency
        )
        VALUES (?, 'AAPL', 0, 0, 0, 100, 0, 'stock', 'USD')
        """,
        (asset_id,),
    )

    with pytest.raises(FXRateUnavailable, match="Contabilita EUR storica"):
        engine.refresh_portfolio(connection, create_snapshot=False)


def test_order_history_rejects_legacy_usd_amounts_without_frozen_fx(connection) -> None:
    asset_id = connection.execute("SELECT id FROM assets WHERE symbol = 'AAPL'").fetchone()["id"]
    connection.execute(
        """
        INSERT INTO simulated_orders (
            asset_id, symbol, order_type, side, quantity, price, currency,
            fx_rate_to_base, gross_amount, net_amount
        )
        VALUES (?, 'AAPL', 'BUY', 'BUY', 1, 100, 'USD', 0, 100, 100)
        """,
        (asset_id,),
    )

    with pytest.raises(FXRateUnavailable, match="Cambio storico USD/EUR"):
        PortfolioEngine().list_orders(connection)


def test_invalid_market_observation_keeps_portfolio_on_last_good_projection(
    connection: sqlite3.Connection,
) -> None:
    from backend.app.models.market_data import MarketObservationEnvelope
    from backend.app.services.instrument_service import InstrumentService
    from backend.app.services.market_observation_service import MarketObservationService

    InstrumentService.backfill_active_assets(connection)
    listing_id = connection.execute(
        """
        SELECT instrument_listing_id
        FROM assets
        WHERE symbol = 'AAPL'
        """
    ).fetchone()["instrument_listing_id"]
    connection.execute(
        """
        UPDATE instrument_listings
        SET mic = 'XNAS', venue_name = 'Nasdaq', timezone = 'America/New_York'
        WHERE id = ?
        """,
        (listing_id,),
    )
    now = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)
    valid = MarketObservationEnvelope(
        listing_id=listing_id,
        provider="portfolio_fixture",
        capability="EOD",
        operation="daily_prices",
        received_at=now,
        provider_observed_at=now - timedelta(hours=1),
        timezone="America/New_York",
        session="REGULAR",
        currency="USD",
        source_quality="eod",
        kind="BAR",
        raw_fields={"close": "125"},
        raw_payload_sha256="a" * 64,
    )
    service = MarketObservationService()
    accepted = service.ingest_batch(connection, [valid], now)
    assert accepted.projected_price_rows == 1

    _set_usd_rate(connection, 0.80)
    _initialize(PortfolioEngine(), connection)
    PortfolioEngine().simulate_order(
        connection,
        SimulatedOrderIn(symbol="AAPL", order_type="BUY", quantity=1, price=100, fees=0),
    )

    invalid = MarketObservationEnvelope(
        listing_id=listing_id,
        provider="portfolio_fixture",
        capability="EOD",
        operation="daily_prices",
        received_at=now + timedelta(minutes=1),
        provider_observed_at=now,
        timezone="America/New_York",
        session="REGULAR",
        currency="USD",
        source_quality="eod",
        kind="BAR",
        raw_fields={"close": "-999"},
        raw_payload_sha256="b" * 64,
    )
    rejected = service.ingest_batch(
        connection,
        [invalid],
        now + timedelta(minutes=1),
    )
    refreshed = PortfolioEngine().refresh_portfolio(connection, create_snapshot=False)

    assert rejected.rejected == 1
    assert rejected.projected_price_rows == 0
    assert refreshed.positions[0].current_price == 125
