from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.app.database import SCHEMA, migrate_db
from backend.app.services.tax_service import TaxService


@pytest.fixture()
def tax_db(tmp_path):
    db_file = tmp_path / "tax_test.db"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate_db(conn)
    conn.execute(
        "INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (1, 'AAPL', 'Apple', 'stock', 'medium')"
    )
    conn.execute(
        "INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (2, 'BTC', 'Bitcoin', 'crypto', 'high')"
    )
    conn.execute(
        """
        INSERT INTO portfolios (
            id, portfolio_name, description, portfolio_type, base_currency,
            initial_cash, current_cash, is_active, is_archived, created_at, updated_at
        ) VALUES (1, 'Test', '', 'CORE', 'EUR', 100000, 100000, 1, 0, '2024-01-01', '2024-01-01')
        """
    )
    conn.commit()
    yield conn, db_file
    conn.close()


@pytest.fixture()
def tax_client(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "tax_api.db"))
    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    from backend.app.config import get_settings

    get_settings.cache_clear()
    from backend.scripts.seed_database import seed_database

    seed_database(reset=True)
    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def _year() -> int:
    return datetime.now().year


def _insert_order(
    conn: sqlite3.Connection,
    *,
    order_type: str,
    quantity: float,
    price: float,
    fees: float = 0,
    order_date: str | None = None,
) -> int:
    if order_date is None:
        order_date = f"{_year()}-06-15T10:00:00"
    gross = quantity * price
    net = gross + fees if order_type == "BUY" else gross - fees
    cur = conn.execute(
        """
        INSERT INTO simulated_orders (
            portfolio_id, asset_id, symbol, order_type, side, quantity, price, fees,
            gross_amount, net_amount, order_date, status, executed_at
        ) VALUES (1, 1, 'AAPL', ?, ?, ?, ?, ?, ?, ?, ?, 'SIMULATED', ?)
        """,
        (order_type, order_type, quantity, price, fees, gross, net, order_date, order_date),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_fifo_lot_matching_base(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    orders = [
        {"order_type": "BUY", "quantity": 10, "price": 100, "fees": 5, "order_date": "2024-01-01"},
        {"order_type": "SELL", "quantity": 4, "price": 120, "fees": 2, "order_date": "2024-02-01"},
    ]
    events = service.calculate_fifo_pnl(orders, include_fees=True)
    assert len(events) == 1
    assert events[0]["quantity"] == 4
    assert events[0]["realized_pnl"] > 0


def test_buy_creates_tax_lot(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=5, price=50, fees=1)
    service.recalculate(conn, portfolio_id=1)
    lots = service.calculate_tax_lots(conn, portfolio_id=1)
    assert len(lots) == 1
    assert lots[0].quantity_remaining == 5


def test_sell_generates_realized_event(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=10, price=100, fees=0)
    _insert_order(conn, order_type="SELL", quantity=3, price=110, fees=0, order_date=f"{_year()}-07-01T10:00:00")
    service.recalculate(conn, portfolio_id=1)
    events = service.calculate_realized_events(conn, portfolio_id=1, tax_year=_year())
    assert len(events) == 1
    assert events[0].quantity == 3


def test_partial_sell_updates_quantity_remaining(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=10, price=100, fees=0)
    _insert_order(conn, order_type="SELL", quantity=4, price=105, fees=0)
    service.recalculate(conn, portfolio_id=1)
    lots = service.calculate_tax_lots(conn, portfolio_id=1)
    assert lots[0].quantity_remaining == 6


def test_realized_gain_positive(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=2, price=100, fees=0)
    _insert_order(conn, order_type="SELL", quantity=2, price=150, fees=0)
    service.recalculate(conn, portfolio_id=1)
    events = service.calculate_realized_events(conn, portfolio_id=1)
    assert all(e.realized_pnl > 0 for e in events)


def test_realized_loss_negative(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=2, price=200, fees=0)
    _insert_order(conn, order_type="SELL", quantity=2, price=120, fees=0)
    service.recalculate(conn, portfolio_id=1)
    events = service.calculate_realized_events(conn, portfolio_id=1)
    assert all(e.realized_pnl < 0 for e in events)


def test_estimated_tax_26_percent_on_net_gains(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=1, price=100, fees=0)
    _insert_order(conn, order_type="SELL", quantity=1, price=200, fees=0)
    service.recalculate(conn, portfolio_id=1)
    year = _year()
    tax_due = service.estimate_tax_due(conn, tax_year=year, portfolio_id=1)
    gains = service.calculate_realized_gains(conn, portfolio_id=1, tax_year=year)
    losses = service.calculate_realized_losses(conn, portfolio_id=1, tax_year=year)
    net = gains + losses
    assert tax_due == round(max(0, net) * 0.26, 2)


def test_loss_carryforward_simplified(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=1, price=100, fees=0, order_date="2023-01-01T10:00:00")
    _insert_order(conn, order_type="SELL", quantity=1, price=50, fees=0, order_date="2023-06-01T10:00:00")
    service.recalculate(conn, portfolio_id=1)
    carry = service.calculate_loss_carryforward(conn, tax_year=2024)
    assert carry < 0


def test_tax_summary_portfolio(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    _insert_order(conn, order_type="BUY", quantity=1, price=100, fees=0)
    _insert_order(conn, order_type="SELL", quantity=1, price=130, fees=0)
    summary = service.calculate_tax_summary(conn, portfolio_id=1, tax_year=_year())
    assert summary.portfolio_id == 1
    assert summary.disclaimer


def test_tax_summary_global(tax_db):
    conn, _ = tax_db
    service = TaxService()
    service.ensure_default_settings(conn)
    global_summary = service.calculate_multi_portfolio_tax_summary(conn, tax_year=_year())
    assert global_summary.tax_regime == "ITALY_SIMPLIFIED"
    assert len(global_summary.portfolio_summaries) >= 1


def test_endpoint_tax_settings(tax_client: TestClient):
    r = tax_client.get("/tax/settings")
    assert r.status_code == 200
    assert r.json()["tax_regime"] == "ITALY_SIMPLIFIED"
    assert r.json()["capital_gain_tax_rate"] == 26.0


def test_endpoint_tax_summary(tax_client: TestClient):
    r = tax_client.get("/tax/summary")
    assert r.status_code == 200
    assert "estimated_tax_due" in r.json()
    assert "disclaimer" in r.json()


def test_endpoint_tax_recalculate(tax_client: TestClient):
    r = tax_client.post("/tax/recalculate", json={"method": "FIFO"})
    assert r.status_code == 200
    assert r.json()["method"] == "FIFO"


def test_endpoint_tax_report_generate(tax_client: TestClient):
    year = datetime.now().year
    r = tax_client.post(
        "/tax/report/generate",
        json={"tax_year": year, "report_type": "PORTFOLIO"},
    )
    assert r.status_code == 200
    assert r.json()["tax_year"] == year


def test_endpoint_tax_export(tax_client: TestClient):
    year = datetime.now().year
    r = tax_client.post("/tax/export", json={"tax_year": year, "format": "json"})
    assert r.status_code == 200
    assert "file_path" in r.json()
    assert r.json()["disclaimer"]
