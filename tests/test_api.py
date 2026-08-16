from __future__ import annotations

import asyncio
import csv
import io
import sqlite3

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.services.backtest_engine import BacktestEngine
from backend.app.services.technical_analysis import TechnicalAnalysisService


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend.app.config import get_settings

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "investedge.db"))
    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    monkeypatch.setenv("COINGECKO_API_KEY", "")
    monkeypatch.setenv("FRED_API_KEY", "")
    monkeypatch.setenv("FINNHUB_API_KEY", "")
    monkeypatch.setenv("ENABLE_REAL_NEWS", "false")
    monkeypatch.setenv("NEWS_DAILY_LIMIT", "20")
    monkeypatch.setenv("NEWS_CACHE_TTL_HOURS", "6")
    monkeypatch.setenv("NEWS_SENTIMENT_WEIGHT", "5")
    monkeypatch.setenv("ENABLE_ALERTS", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("ENABLE_GOOGLE_SHEETS_IMPORT", "false")
    monkeypatch.setenv("GOOGLE_SHEETS_CSV_URL", "")
    get_settings.cache_clear()

    from backend.scripts.seed_database import seed_database

    seed_database(reset=True)

    from backend.app.database import db_session

    with db_session() as connection:
        connection.execute(
            """
            INSERT INTO fx_rates (
                from_currency, to_currency, rate, observed_at, provider, quality
            )
            VALUES ('USD', 'EUR', 0.92, date('now'), 'test', 'reference')
            """
        )

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


def _asset_dependency_state(symbol: str) -> tuple[int | None, dict[str, int], dict[str, int]]:
    from backend.app.database import db_session

    with db_session() as connection:
        asset = connection.execute(
            "SELECT id FROM assets WHERE UPPER(symbol) = UPPER(?)",
            (symbol,),
        ).fetchone()
        totals = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM price_history) AS price_history,
                    (SELECT COUNT(*) FROM portfolio_positions) AS portfolio_positions,
                    (SELECT COUNT(*) FROM simulated_orders) AS simulated_orders,
                    (SELECT COUNT(*) FROM signals) AS signals,
                    (SELECT COUNT(*) FROM news_items) AS news_items
                """
            ).fetchone()
        )
        if asset is None:
            return None, dict.fromkeys(totals, 0), totals

        asset_id = int(asset["id"])
        counts = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM price_history WHERE asset_id = ?) AS price_history,
                    (SELECT COUNT(*) FROM portfolio_positions WHERE asset_id = ?) AS portfolio_positions,
                    (SELECT COUNT(*) FROM simulated_orders WHERE asset_id = ?) AS simulated_orders,
                    (SELECT COUNT(*) FROM signals WHERE asset_id = ?) AS signals,
                    (SELECT COUNT(*) FROM news_items WHERE asset_id = ?) AS news_items
                """,
                (asset_id, asset_id, asset_id, asset_id, asset_id),
            ).fetchone()
        )
        return asset_id, counts, totals


def _enable_google_sheets_import(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("ENABLE_GOOGLE_SHEETS_IMPORT", "true")
    get_settings.cache_clear()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lifespan_backs_up_before_initializing_outside_tests(monkeypatch) -> None:
    from backend.app import main

    events: list[str] = []
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(main, "backup_before_migration", lambda: events.append("backup"))
    monkeypatch.setattr(main, "init_db", lambda: events.append("init"))

    async def run_lifespan() -> None:
        async with main.lifespan(None):
            events.append("yield")

    asyncio.run(run_lifespan())

    assert events == ["backup", "init", "yield"]


def test_lifespan_does_not_initialize_when_backup_fails(monkeypatch) -> None:
    from backend.app import main

    events: list[str] = []
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def fail_backup() -> None:
        events.append("backup")
        raise RuntimeError("backup failed")

    monkeypatch.setattr(main, "backup_before_migration", fail_backup)
    monkeypatch.setattr(main, "init_db", lambda: events.append("init"))

    async def run_lifespan() -> None:
        async with main.lifespan(None):
            events.append("yield")

    with pytest.raises(RuntimeError, match="backup failed"):
        asyncio.run(run_lifespan())

    assert events == ["backup"]


def test_admin_seed_route_is_not_exposed(client: TestClient) -> None:
    response = client.post("/admin/seed?reset=true")

    assert response.status_code == 404


def test_assets_after_seed(client: TestClient) -> None:
    response = client.get("/assets")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert {asset["symbol"] for asset in data} >= {"AAPL", "BTC", "TLT"}
    assert data[0]["last_price"] is not None


def test_prices_for_symbol(client: TestClient) -> None:
    response = client.get("/prices/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert len(data["prices"]) >= 500
    assert {"date", "open", "high", "low", "close", "sma_50", "ema_50", "macd_line", "bollinger_upper"} <= set(data["prices"][-1])


def test_signals_after_seed(client: TestClient) -> None:
    response = client.get("/signals")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert data[0]["signal"] in {"STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"}
    assert 0 <= data[0]["score"] <= 100


def test_action_board_after_seed(client: TestClient) -> None:
    response = client.get("/action-board")

    assert response.status_code == 200
    data = response.json()
    assert {"generated_at", "data_mode", "headline", "counts", "actions"} <= set(data)
    assert data["data_mode"] == "SEED"
    assert isinstance(data["actions"], list)
    assert len(data["actions"]) >= 1
    valid_types = {"BUY", "REDUCE", "SELL", "WATCH", "RISK", "OK"}
    valid_priorities = {"HIGH", "MEDIUM", "LOW"}
    for action in data["actions"]:
        assert action["type"] in valid_types
        assert action["priority"] in valid_priorities
        assert action["title"]
        assert action["reason"]


def test_alerts_status_not_configured(client: TestClient) -> None:
    response = client.get("/alerts/status")

    assert response.status_code == 200
    data = response.json()
    assert data["channel"] == "telegram"
    assert data["enabled"] is False
    assert data["configured"] is False


def test_alerts_test_requires_config(client: TestClient) -> None:
    response = client.post("/alerts/test")

    assert response.status_code == 400
    assert "Telegram" in response.json()["detail"]


def test_alerts_send_today_requires_config(client: TestClient) -> None:
    response = client.post("/alerts/send-today")

    assert response.status_code == 400


def test_import_status_not_configured(client: TestClient) -> None:
    response = client.get("/import/google-sheets/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["configured"] is False


def test_import_preview_requires_enabled_flag(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: "symbol,quantity,average_price\nAAPL,1,150\n",
    )

    response = client.post(
        "/import/google-sheets/preview",
        json={"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 403


def test_import_apply_requires_enabled_flag(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: "symbol,quantity,average_price\nAAPL,1,150\n",
    )

    response = client.post(
        "/import/google-sheets/apply",
        json={"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 403


def test_import_preview_requires_url_when_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_google_sheets_import(monkeypatch)

    response = client.post("/import/google-sheets/preview", json={"csv_url": ""})

    assert response.status_code == 400
    assert "URL" in response.json()["detail"]


def test_import_apply_replaces_positions(client: TestClient, monkeypatch) -> None:
    _enable_google_sheets_import(monkeypatch)
    csv_text = (
        "symbol,quantity,average_price,currency\n"
        "AAPL,10,150,USD\n"
        "MSFT,4,300,USD\n"
    )
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: csv_text,
    )

    response = client.post(
        "/import/google-sheets/apply",
        json={"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 2
    assert data["initial_equity_base"] == pytest.approx(2484)
    assert data["current_cash_base"] == 0
    assert data["base_currency"] == "EUR"

    portfolio = client.get("/portfolio").json()
    symbols = {position["symbol"] for position in portfolio["positions"]}
    assert symbols == {"AAPL", "MSFT"}
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["quantity"] == 10
    assert aapl["average_price"] == 150
    assert portfolio["settings"]["initial_cash"] == pytest.approx(2484)
    assert portfolio["settings"]["current_cash"] == 0


def test_import_apply_creates_new_asset_with_import_reference_price(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: (
            "symbol,name,quantity,average_price,currency\n"
            "NEWIMPORT,New Import Asset,2,100,EUR\n"
        ),
    )

    response = client.post(
        "/import/google-sheets/apply",
        json={"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 200
    assert response.json()["created_assets"] == 1
    portfolio = client.get("/portfolio").json()
    position = next(item for item in portfolio["positions"] if item["symbol"] == "NEWIMPORT")
    assert position["current_price"] == 100
    assert position["current_value_base"] == 200
    assert portfolio["settings"]["initial_cash"] == 200
    assert portfolio["settings"]["current_cash"] == 0

    with db_session() as connection:
        reference_price = connection.execute(
            """
            SELECT ph.close, ph.source, ph.provider, ph.is_real_data
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE a.symbol = 'NEWIMPORT'
            """
        ).fetchone()

    assert tuple(reference_price) == (100, "google_sheets_import", "google_sheets_import", 0)


def test_import_rolls_back_positions_assets_and_settings_on_second_position_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session
    from backend.app.services import google_sheets_import_service

    _enable_google_sheets_import(monkeypatch)
    allocation_response = client.post(
        "/portfolio/allocation/apply",
        json=_allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT"], total_capital=50000),
    )
    assert allocation_response.status_code == 200

    csv_text = (
        "symbol,quantity,average_price,currency\n"
        "SAFEIMPORT,2,100,EUR\n"
        "FAILIMPORT,3,200,EUR\n"
    )
    monkeypatch.setattr(google_sheets_import_service, "fetch_csv", lambda csv_url=None: csv_text)

    with db_session() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_second_import_position
            BEFORE INSERT ON portfolio_positions
            WHEN NEW.symbol = 'FAILIMPORT'
            BEGIN
                SELECT RAISE(ABORT, 'forced second position failure');
            END
            """
        )
        positions_before = [
            tuple(row)
            for row in connection.execute(
                "SELECT asset_id, symbol, quantity, average_price FROM portfolio_positions ORDER BY id"
            ).fetchall()
        ]
        settings_before = tuple(
            connection.execute(
                "SELECT initial_cash, current_cash, updated_at FROM portfolio_settings WHERE id = 1"
            ).fetchone()
        )
        asset_count_before = int(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])

        with pytest.raises(sqlite3.IntegrityError, match="forced second position failure"):
            google_sheets_import_service.apply_import(
                connection,
                "https://docs.google.com/spreadsheets/d/test/export?format=csv",
            )

        positions_after = [
            tuple(row)
            for row in connection.execute(
                "SELECT asset_id, symbol, quantity, average_price FROM portfolio_positions ORDER BY id"
            ).fetchall()
        ]
        settings_after = tuple(
            connection.execute(
                "SELECT initial_cash, current_cash, updated_at FROM portfolio_settings WHERE id = 1"
            ).fetchone()
        )
        imported_assets = connection.execute(
            "SELECT symbol FROM assets WHERE symbol IN ('SAFEIMPORT', 'FAILIMPORT')"
        ).fetchall()
        asset_count_after = int(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])

    assert positions_after == positions_before
    assert settings_after == settings_before
    assert imported_assets == []
    assert asset_count_after == asset_count_before


def test_ml_status_initially_empty(client: TestClient) -> None:
    response = client.get("/ml/status")

    assert response.status_code == 200
    data = response.json()
    assert data["models_count"] == 0
    assert data["ml_ready"] is False
    assert "HIST_GRADIENT_BOOSTING" in data["available_model_types"]


def test_ml_dataset_has_no_lookahead(client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.services.ml_dataset_service import FEATURE_COLUMNS, MLDatasetService

    service = MLDatasetService()
    with db_session() as connection:
        dataset = service.build_ml_dataset(
            connection=connection,
            symbols=["AAPL", "MSFT", "SPY"],
            horizon_days=14,
            target_type="POSITIVE_RETURN",
        )
    assert not dataset.empty
    assert set(FEATURE_COLUMNS).issubset(dataset.columns)
    # validate_no_lookahead raises if violated; here it must hold
    assert service.validate_no_lookahead(dataset) is True


def test_ml_train_and_predict(client: TestClient) -> None:
    train_payload = {
        "model_name": "Test GB",
        "model_type": "HIST_GRADIENT_BOOSTING",
        "target_type": "POSITIVE_RETURN",
        "horizon_days": 14,
        "symbols": ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
        "min_samples": 100,
        "cv_folds": 3,
    }
    train_response = client.post("/ml/train", json=train_payload)
    assert train_response.status_code == 200
    train_data = train_response.json()
    assert train_data["model_id"] > 0
    metrics = train_data["metrics"]
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["walk_forward"] is None or metrics["walk_forward"]["folds"] >= 1

    status_response = client.get("/ml/status")
    assert status_response.json()["models_count"] == 1

    predict_response = client.post("/ml/predict/AAPL", json={})
    assert predict_response.status_code == 200
    prediction = predict_response.json()
    assert prediction["symbol"] == "AAPL"
    assert prediction["confidence"] in {"LOW", "MEDIUM", "HIGH"}
    assert prediction["predicted_label"]


def test_ml_predict_without_model_fails(client: TestClient) -> None:
    response = client.post("/ml/predict/AAPL", json={})

    assert response.status_code == 400
    assert "modello" in response.json()["detail"].lower()


def test_tax_report_after_buy_sell(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 80, "max_asset_class_weight": 90, "default_fee_percent": 0},
    )
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 100, "fees": 0})
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 140, "fees": 0})

    response = client.get("/tax/report")

    assert response.status_code == 200
    data = response.json()
    assert data["lot_method"] == "SIMPLIFIED_FIFO"
    assert data["standard_rate"] == 26.0
    event = next(e for e in data["events"] if e["symbol"] == "AAPL")
    assert event["gain_native"] == 200.0  # 5 * (140 - 100) USD
    assert event["gain_base"] == 184.0  # cambio congelato USD/EUR 0,92
    assert event["gain"] == 184.0  # alias compatibile espresso nella valuta base EUR
    assert data["total_tax_due"] >= 47.84 - 1e-6  # 26% di 184 EUR


def test_tax_report_after_short_cover(client: TestClient) -> None:
    _init_flat(client)
    opened = client.post(
        "/orders/simulate",
        json={
            "symbol": "AAPL",
            "order_type": "SELL",
            "quantity": 10,
            "price": 100,
            "fees": 0,
            "allow_short": True,
        },
    )
    covered = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 80, "fees": 0},
    )
    assert opened.status_code == 200
    assert covered.status_code == 200

    response = client.get("/tax/report")

    assert response.status_code == 200
    data = response.json()
    event = next(item for item in data["events"] if item["symbol"] == "AAPL")
    assert event["open_side"] == "SELL"
    assert event["close_side"] == "BUY"
    assert event["sell_date"] is None
    assert event["realization_date"]
    assert event["gain_native"] == 200.0
    assert event["gain_base"] == 184.0
    assert event["gain"] == 184.0
    assert event["applied_rate"] == 26.0


def test_seed_assigns_explicit_tax_categories_and_default_is_standard(client: TestClient) -> None:
    created = client.post(
        "/assets",
        json={"symbol": "TAXDEFAULT", "name": "Tax default", "asset_type": "bond_etf", "currency": "EUR"},
    )
    assert created.status_code == 201

    from backend.app.database import db_session

    with db_session() as connection:
        rows = connection.execute(
            "SELECT symbol, tax_category FROM assets WHERE symbol IN ('BTP10Y', 'BTC', 'IB01', 'AGGH', 'TAXDEFAULT')"
        ).fetchall()

    categories = {row["symbol"]: row["tax_category"] for row in rows}
    assert categories == {
        "AGGH": "standard",
        "BTC": "crypto",
        "BTP10Y": "government_bond",
        "IB01": "standard",
        "TAXDEFAULT": "standard",
    }


def test_asset_tax_category_is_created_read_and_defaulted_safely(client: TestClient) -> None:
    explicit = client.post(
        "/assets",
        json={
            "symbol": "CRYPTO_EXPLICIT",
            "name": "Crypto explicit",
            "asset_type": "crypto",
            "currency": "EUR",
            "tax_category": "crypto",
        },
    )
    inferred_crypto = client.post(
        "/assets",
        json={
            "symbol": "CRYPTO_DEFAULT",
            "name": "Crypto default",
            "asset_type": "crypto",
            "currency": "EUR",
        },
    )
    unverified_bond_etf = client.post(
        "/assets",
        json={
            "symbol": "BOND_DEFAULT",
            "name": "Bond ETF default",
            "asset_type": "bond_etf",
            "currency": "EUR",
        },
    )
    invalid = client.post(
        "/assets",
        json={
            "symbol": "INVALID_TAX",
            "name": "Invalid tax",
            "asset_type": "stock",
            "currency": "EUR",
            "tax_category": "unsupported",
        },
    )

    assert explicit.status_code == 201
    assert inferred_crypto.status_code == 201
    assert unverified_bond_etf.status_code == 201
    assert invalid.status_code == 422
    assert explicit.json()["tax_category"] == "crypto"
    assert inferred_crypto.json()["tax_category"] == "crypto"
    assert unverified_bond_etf.json()["tax_category"] == "standard"
    assets = {item["symbol"]: item for item in client.get("/assets").json()}
    assert assets["CRYPTO_EXPLICIT"]["tax_category"] == "crypto"
    assert assets["CRYPTO_DEFAULT"]["tax_category"] == "crypto"
    assert assets["BOND_DEFAULT"]["tax_category"] == "standard"


def test_tax_csv_short_uses_realization_sides_and_native_base_values(client: TestClient) -> None:
    _init_flat(client)
    client.post(
        "/orders/simulate",
        json={
            "symbol": "AAPL",
            "order_type": "SELL",
            "quantity": 10,
            "price": 100,
            "fees": 0,
            "allow_short": True,
        },
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 80, "fees": 0},
    )

    response = client.get("/reports/tax.csv")

    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    event = next(row for row in rows if row["symbol"] == "AAPL")
    assert event["sell_date"] == ""
    assert event["realization_date"]
    assert event["open_side"] == "SELL"
    assert event["close_side"] == "BUY"
    assert float(event["open_value_native"]) == 1000.0
    assert float(event["close_value_native"]) == 800.0
    assert float(event["gain_native"]) == 200.0
    assert float(event["open_value_base"]) == 920.0
    assert float(event["close_value_base"]) == 736.0
    assert float(event["gain_base"]) == 184.0


def test_tax_report_empty(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 50, "max_asset_class_weight": 80, "default_fee_percent": 0},
    )
    response = client.get("/tax/report")

    assert response.status_code == 200
    data = response.json()
    assert data["events"] == []
    assert data["total_tax_due"] == 0.0


def test_remove_asset_without_dependencies(client: TestClient) -> None:
    create = client.post(
        "/assets",
        json={"symbol": "TEST1", "name": "Test Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201

    assets = {a["symbol"] for a in client.get("/assets").json()}
    assert "TEST1" in assets

    delete = client.delete("/assets/TEST1")
    assert delete.status_code == 200
    assert delete.json() == {
        "deleted": True,
        "symbol": "TEST1",
        "purged": False,
        "dependency_counts": {
            "price_history": 0,
            "portfolio_positions": 0,
            "simulated_orders": 0,
            "signals": 0,
            "news_items": 0,
        },
    }

    assets_after = {a["symbol"] for a in client.get("/assets").json()}
    assert "TEST1" not in assets_after


def test_remove_asset_with_dependencies_returns_conflict_without_changes(client: TestClient) -> None:
    asset_id_before, counts_before, totals_before = _asset_dependency_state("AAPL")
    assert asset_id_before is not None
    assert all(count > 0 for count in counts_before.values())

    response = client.delete("/assets/AAPL")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert all(f"{table}={count}" in detail for table, count in counts_before.items())
    assert _asset_dependency_state("AAPL") == (asset_id_before, counts_before, totals_before)


@pytest.mark.parametrize("confirm_symbol", [None, "aapl", "MSFT"])
def test_purge_asset_requires_exact_confirmation(
    client: TestClient,
    confirm_symbol: str | None,
) -> None:
    state_before = _asset_dependency_state("AAPL")
    params = {"purge": "true"}
    if confirm_symbol is not None:
        params["confirm_symbol"] = confirm_symbol

    response = client.delete("/assets/AAPL", params=params)

    assert response.status_code == 400
    assert _asset_dependency_state("AAPL") == state_before


def test_purge_asset_with_confirmation_creates_backup_and_deletes_dependencies(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.api import routes

    asset_id_before, counts_before, totals_before = _asset_dependency_state("AAPL")
    assert asset_id_before is not None
    backup_reasons: list[str] = []
    real_create_backup = routes.create_backup

    def successful_backup(*, reason: str) -> dict[str, object]:
        backup_reasons.append(reason)
        return real_create_backup(reason=reason)

    monkeypatch.setattr(routes, "create_backup", successful_backup)

    response = client.delete(
        "/assets/AAPL",
        params={"purge": "true", "confirm_symbol": "AAPL"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "deleted": True,
        "symbol": "AAPL",
        "purged": True,
        "dependency_counts": counts_before,
    }
    assert backup_reasons == ["pre-asset-purge-AAPL"]
    asset_id_after, _, totals_after = _asset_dependency_state("AAPL")
    assert asset_id_after is None
    assert totals_after == {
        table: totals_before[table] - counts_before[table]
        for table in totals_before
    }


def test_purge_asset_without_created_backup_preserves_data(client: TestClient, monkeypatch) -> None:
    state_before = _asset_dependency_state("AAPL")
    monkeypatch.setattr(
        "backend.app.api.routes.create_backup",
        lambda *, reason: {"created": False, "reason": reason, "file": None},
    )

    response = client.delete(
        "/assets/AAPL",
        params={"purge": "true", "confirm_symbol": "AAPL"},
    )

    assert response.status_code == 503
    assert _asset_dependency_state("AAPL") == state_before


def test_purge_asset_when_backup_raises_preserves_data(client: TestClient, monkeypatch) -> None:
    state_before = _asset_dependency_state("AAPL")

    def failing_backup(*, reason: str) -> dict[str, object]:
        raise OSError(f"backup failed for {reason}")

    monkeypatch.setattr("backend.app.api.routes.create_backup", failing_backup)

    response = client.delete(
        "/assets/AAPL",
        params={"purge": "true", "confirm_symbol": "AAPL"},
    )

    assert response.status_code == 503
    assert _asset_dependency_state("AAPL") == state_before


def test_remove_asset_missing_returns_not_found(client: TestClient) -> None:
    response = client.delete("/assets/NOPE")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "params",
    [{}, {"purge": "true", "confirm_symbol": "DUP"}],
    ids=["remove", "purge"],
)
def test_remove_asset_rejects_ambiguous_symbol(
    client: TestClient,
    monkeypatch,
    params: dict[str, str],
) -> None:
    from backend.app.database import db_session

    for asset_type in ("stock", "etf"):
        response = client.post(
            "/assets",
            json={
                "symbol": "DUP",
                "name": f"Duplicate {asset_type}",
                "asset_type": asset_type,
                "currency": "USD",
            },
        )
        assert response.status_code == 201

    with db_session() as connection:
        duplicate_ids = [
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM assets WHERE symbol = 'DUP' ORDER BY id",
            ).fetchall()
        ]
        connection.execute(
            "INSERT INTO price_history (asset_id, date, close) VALUES (?, '2026-01-01', 10)",
            (duplicate_ids[1],),
        )

    backup_reasons: list[str] = []

    def backup_spy(*, reason: str) -> dict[str, object]:
        backup_reasons.append(reason)
        return {"created": True, "reason": reason, "file": "backup.db"}

    monkeypatch.setattr("backend.app.api.routes.create_backup", backup_spy)

    response = client.delete("/assets/DUP", params=params)

    assert response.status_code == 409
    assert backup_reasons == []
    with db_session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'DUP'").fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
            (duplicate_ids[1],),
        ).fetchone()[0] == 1


def test_remove_asset_counts_symbol_only_news_as_dependency(client: TestClient) -> None:
    from backend.app.database import db_session

    create = client.post(
        "/assets",
        json={"symbol": "NEWSY", "name": "Legacy News Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201
    with db_session() as connection:
        news_id = connection.execute(
            "INSERT INTO news_items (asset_id, symbol, title) VALUES (NULL, 'NEWSY', 'Legacy linked news')"
        ).lastrowid

    response = client.delete("/assets/NEWSY")

    assert response.status_code == 409
    assert "news_items=1" in response.json()["detail"]
    with db_session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'NEWSY'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM news_items WHERE id = ?", (news_id,)).fetchone()[0] == 1


def test_purge_asset_deletes_symbol_only_news(client: TestClient, monkeypatch) -> None:
    from backend.app.database import db_session

    create = client.post(
        "/assets",
        json={"symbol": "NEWSY", "name": "Legacy News Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201
    with db_session() as connection:
        news_id = connection.execute(
            "INSERT INTO news_items (asset_id, symbol, title) VALUES (NULL, 'NEWSY', 'Legacy linked news')"
        ).lastrowid

    monkeypatch.setattr(
        "backend.app.api.routes.create_backup",
        lambda *, reason: {"created": True, "reason": reason, "file": "backup.db"},
    )

    response = client.delete(
        "/assets/NEWSY",
        params={"purge": "true", "confirm_symbol": "NEWSY"},
    )

    assert response.status_code == 200
    assert response.json()["dependency_counts"]["news_items"] == 1
    with db_session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'NEWSY'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM news_items WHERE id = ?", (news_id,)).fetchone()[0] == 0


def test_remove_asset_blocks_concurrent_dependencies_between_count_and_delete(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.api import routes
    from backend.app.config import get_settings

    create = client.post(
        "/assets",
        json={"symbol": "LOCKED", "name": "Lock Test Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201
    original_dependency_counts = routes.asset_dependency_counts
    concurrent_write_errors: list[str] = []

    def counts_with_concurrent_write(connection, asset_id: int) -> dict[str, int]:
        counts = original_dependency_counts(connection, asset_id)
        contender = sqlite3.connect(str(get_settings().database_path), timeout=0)
        try:
            contender.execute(
                "INSERT INTO price_history (asset_id, date, close) VALUES (?, '2026-01-01', 10)",
                (asset_id,),
            )
            contender.commit()
        except sqlite3.OperationalError as exc:
            concurrent_write_errors.append(str(exc))
        finally:
            contender.close()
        return counts

    monkeypatch.setattr(routes, "asset_dependency_counts", counts_with_concurrent_write)

    response = client.delete("/assets/LOCKED")

    assert response.status_code == 200
    assert len(concurrent_write_errors) == 1
    assert "locked" in concurrent_write_errors[0].lower()


def test_backup_create_and_list(client: TestClient) -> None:
    created = client.post("/backups/create")
    assert created.status_code == 200
    data = created.json()
    assert data["created"] is True
    assert data["file"] and data["file"].endswith(".db")

    listing = client.get("/backups")
    assert listing.status_code == 200
    files = [item["file"] for item in listing.json()]
    assert data["file"] in files


def test_reports_summary(client: TestClient) -> None:
    response = client.get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert {"positions_count", "orders_count", "realized_events_count", "portfolio_value", "estimated_tax_due"} <= set(data)


def test_reports_csv_downloads(client: TestClient) -> None:
    for path, header in [
        ("/reports/portfolio.csv", "symbol,asset_type,quantity"),
        ("/reports/orders.csv", "date,symbol,type"),
        ("/reports/tax.csv", "sell_date,symbol,asset_type"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
        assert response.text.splitlines()[0].startswith(header)

    portfolio_headers = client.get("/reports/portfolio.csv").text.splitlines()[0].split(",")
    orders_headers = client.get("/reports/orders.csv").text.splitlines()[0].split(",")
    assert {"currency", "fx_rate_to_base", "current_value", "current_value_base", "base_currency"} <= set(
        portfolio_headers
    )
    assert {"currency", "fx_rate_to_base", "gross_amount", "gross_amount_base", "base_currency"} <= set(
        orders_headers
    )


def test_dashboard_after_seed(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["initialized"] is True
    assert data["assets_count"] == 25
    assert data["signals_count"] == 25
    assert data["price_points_count"] >= 14000
    assert data["latest_signals"]
    assert data["data_status"]["data_mode"] == "SEED"


def _price_frame(values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": values,
            "high": [value * 1.01 for value in values],
            "low": [value * 0.99 for value in values],
            "close": values,
            "adjusted_close": values,
            "volume": [1_000_000 + index * 1000 for index, _ in enumerate(values)],
        }
    )


def test_technical_analysis_increasing_series() -> None:
    service = TechnicalAnalysisService()
    analysis = service.calculate_full_technical_analysis(_price_frame([100 + index for index in range(260)]))

    assert analysis["latest_close"] == 359
    assert analysis["conditions"]["price_above_sma50"] is True
    assert analysis["conditions"]["price_above_sma200"] is True
    assert analysis["indicators"]["sma_200"] > 0


def test_technical_analysis_decreasing_series() -> None:
    service = TechnicalAnalysisService()
    analysis = service.calculate_full_technical_analysis(_price_frame([360 - index for index in range(260)]))

    assert analysis["conditions"]["price_above_sma50"] is False
    assert analysis["conditions"]["price_above_sma200"] is False
    assert analysis["overall_technical_bias"] in {"BEARISH", "NEUTRAL"}


def test_technical_analysis_short_series() -> None:
    service = TechnicalAnalysisService()
    analysis = service.calculate_full_technical_analysis(_price_frame([10, 11, 12]))

    assert analysis["latest_close"] == 12
    assert analysis["support_resistance"]["nearest_support"] is None
    assert "sma_200" not in analysis["indicators"]


def test_technical_analysis_endpoint(client: TestClient) -> None:
    response = client.get("/technical-analysis/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["asset"]["symbol"] == "AAPL"
    assert data["subscores"]
    assert data["reasons"]
    assert data["confidence"] in {"LOW", "MEDIUM", "HIGH"}


def test_advanced_seed_signal_payload(client: TestClient) -> None:
    response = client.get("/signals/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["signal"] in {"STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"}
    assert "trend_score" in data["subscores"]
    assert isinstance(data["reasons"], list)


def test_portfolio_endpoint_after_seed(client: TestClient) -> None:
    response = client.get("/portfolio")

    assert response.status_code == 200
    data = response.json()
    assert data["total_value"] > 0
    assert data["cash"] > 0
    assert data["base_currency"] == "EUR"
    assert len(data["positions"]) == 7
    assert all(position["base_currency"] == "EUR" for position in data["positions"])
    assert all("current_value_base" in position for position in data["positions"])
    assert data["allocation_by_asset_type"]
    assert isinstance(data["risk_warnings"], list)


def test_init_portfolio(client: TestClient) -> None:
    response = client.post(
        "/portfolio/init",
        json={
            "initial_cash": 25000,
            "max_single_asset_weight": 20,
            "max_asset_class_weight": 50,
            "default_fee_percent": 0.2,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["cash"] == 25000
    assert data["total_value"] == 25000
    assert data["positions"] == []
    assert data["settings"]["default_fee_percent"] == 0.2


def test_buy_with_sufficient_cash(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
        },
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 2, "price": 100, "fees": 0},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["order"]["gross_amount"] == 200
    assert data["order"]["currency"] == "USD"
    assert data["order"]["fx_rate_to_base"] == 0.92
    assert data["order"]["gross_amount_base"] == 184
    assert data["order"]["base_currency"] == "EUR"
    assert data["updated_position"]["quantity"] == 2
    assert data["updated_portfolio_summary"]["cash"] == 9816


def test_buy_with_insufficient_cash(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 100,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
        },
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 2, "price": 100, "fees": 0},
    )

    assert response.status_code == 400
    assert "Cash insufficiente" in response.json()["detail"]


def test_sell_with_sufficient_quantity_and_pnl(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
        },
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 2, "price": 100, "fees": 0},
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "SELL", "quantity": 1, "price": 120, "fees": 0},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["order"]["order_type"] == "SELL"
    assert data["updated_position"]["quantity"] == 1
    assert data["updated_portfolio_summary"]["realized_pnl"] == 18.4


def test_sell_with_insufficient_quantity(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
        },
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "SELL", "quantity": 1, "price": 120, "fees": 0},
    )

    assert response.status_code == 400
    assert "Quantita insufficiente" in response.json()["detail"]


def test_average_price_calculation(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 80,
            "max_asset_class_weight": 90,
            "default_fee_percent": 0,
        },
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 1, "price": 100, "fees": 0},
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 1, "price": 200, "fees": 0},
    )

    response = client.get("/portfolio")
    position = next(item for item in response.json()["positions"] if item["symbol"] == "AAPL")

    assert position["quantity"] == 2
    assert position["average_price"] == 150


def test_assets_include_isin(client: TestClient) -> None:
    assets = {a["symbol"]: a for a in client.get("/assets").json()}
    assert assets["AAPL"]["isin"] == "US0378331005"
    assert assets["VWCE"]["isin"] == "IE00BK5BQT80"
    assert assets["IB01"]["isin"] == "IE00BGSF1X88"
    # crypto / indici generici non hanno ISIN
    assert assets["BTC"]["isin"] is None


def test_positions_include_name_and_isin(client: TestClient) -> None:
    portfolio = client.get("/portfolio").json()
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["name"] == "Apple Inc."
    assert aapl["isin"] == "US0378331005"


def test_sell_all_removes_position_and_keeps_realized_pnl(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 80, "max_asset_class_weight": 90, "default_fee_percent": 0},
    )
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 3, "price": 100, "fees": 0})
    # vendita totale
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 3, "price": 110, "fees": 0})

    portfolio = client.get("/portfolio").json()
    symbols = {p["symbol"] for p in portfolio["positions"]}
    assert "AAPL" not in symbols  # il titolo venduto del tutto non appare piu
    assert portfolio["realized_pnl"] == 27.6  # 3 * (110 - 100) USD * 0,92, conservato in EUR


def test_sell_all_with_rounded_quantity_closes_position(client: TestClient) -> None:
    # quantita' frazionaria: "Vendi tutto" usa il valore arrotondato e deve comunque chiudere
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 90, "max_asset_class_weight": 90, "default_fee_percent": 0},
    )
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 1.123456789, "price": 100, "fees": 0})
    # vende la quantita' arrotondata a 8 decimali (come fa il bottone "Vendi tutto")
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 1.12345679, "price": 110, "fees": 0})

    portfolio = client.get("/portfolio").json()
    symbols = {p["symbol"] for p in portfolio["positions"]}
    assert "AAPL" not in symbols


def _init_flat(client: TestClient, cash: float = 10000) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": cash, "max_single_asset_weight": 100, "max_asset_class_weight": 100, "default_fee_percent": 0},
    )


def test_short_requires_allow_short_flag(client: TestClient) -> None:
    _init_flat(client)
    # vendere allo scoperto senza il flag e' bloccato (niente short accidentale)
    blocked = client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 100, "fees": 0})
    assert blocked.status_code == 400
    # con allow_short apre uno short (quantita' negativa) e incassa i proventi
    opened = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 100, "fees": 0, "allow_short": True},
    )
    assert opened.status_code == 200
    portfolio = client.get("/portfolio").json()
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["quantity"] == -5  # short
    assert portfolio["cash"] == 10460  # 10000 EUR + 5*100 USD*0,92 di proventi


def test_short_profit_when_price_falls(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 10, "price": 100, "fees": 0, "allow_short": True})
    # ricopre piu' in basso -> profitto (100 - 90) * 10 = 100
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 90, "fees": 0})
    summary = client.get("/portfolio").json()
    assert summary["realized_pnl"] == 92.0
    assert "AAPL" not in {p["symbol"] for p in summary["positions"]}  # chiuso
    assert summary["cash"] == 10092  # 10000 EUR + 100 USD*0,92 di utile


def test_short_loss_when_price_rises(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 100, "fees": 0, "allow_short": True})
    # il prezzo sale: ricoprire costa di piu' -> perdita (100 - 130) * 5 = -150
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 5, "price": 130, "fees": 0})
    summary = client.get("/portfolio").json()
    assert summary["realized_pnl"] == -138.0


def test_short_position_triggers_risk_warning(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 3, "price": 100, "fees": 0, "allow_short": True})
    warnings = client.get("/portfolio").json()["risk_warnings"]
    assert any(w["code"] == "SHORT_RISK" and w["symbol"] == "AAPL" for w in warnings)


def test_flip_long_to_short_realizes_pnl(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 100, "fees": 0})
    # vende 15 (ne ha 10): chiude il long (+200) e apre uno short di 5 a 120
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 15, "price": 120, "fees": 0, "allow_short": True})
    portfolio = client.get("/portfolio").json()
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["quantity"] == -5  # ora short
    assert portfolio["realized_pnl"] == 184.0  # 10 * (120 - 100) USD * 0,92


def test_portfolio_recommendations_endpoint(client: TestClient) -> None:
    response = client.get("/portfolio/recommendations")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert {"symbol", "technical_signal", "technical_score", "portfolio_weight", "final_recommendation", "reason"} <= set(data[0])


def _backtest_payload(strategy_name: str = "SCORE_THRESHOLD") -> dict[str, object]:
    payload: dict[str, object] = {
        "name": f"Test {strategy_name}",
        "strategy_name": strategy_name,
        "symbols": ["AAPL", "MSFT", "SPY", "QQQ"],
        "initial_cash": 100000,
        "start_date": "2025-01-01",
        "end_date": "2026-05-15",
        "benchmark_symbol": "SPY",
        "buy_threshold": 55,
        "sell_threshold": 40,
        "max_asset_weight": 0.2,
        "fee_percent": 0.1,
        "stop_loss_percent": 8,
        "take_profit_percent": 25,
        "rebalance_frequency": "WEEKLY",
    }
    if strategy_name == "TOP_N_SCORE":
        payload["top_n"] = 2
    return payload


def test_run_backtest_score_threshold(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("SCORE_THRESHOLD"))

    assert response.status_code == 200
    data = response.json()
    summary = data["summary"]
    assert data["backtest_id"] > 0
    assert summary["strategy_name"] == "SCORE_THRESHOLD"
    assert {"total_return_percent", "cagr", "max_drawdown", "sharpe_ratio", "win_rate", "profit_factor", "final_value"} <= set(summary)
    assert len(data["equity_curve"]) > 50
    assert all(trade["quantity"] > 0 and trade["price"] > 0 for trade in data["trades"])
    assert "alpha_vs_benchmark" in data["benchmark_comparison"]


def test_backtest_net_analysis(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("SCORE_THRESHOLD"))

    assert response.status_code == 200
    net = response.json()["net_analysis"]
    assert net is not None
    # struttura completa
    assert {
        "gross_return_percent",
        "net_return_percent",
        "capital_gains_tax",
        "slippage_costs",
        "stamp_duty",
        "net_final_value",
        "total_costs_and_taxes",
    } <= set(net)
    # i costi non sono negativi e il netto non supera il lordo
    assert net["capital_gains_tax"] >= 0
    assert net["slippage_costs"] >= 0
    assert net["stamp_duty"] >= 0
    assert net["net_return_percent"] <= net["gross_return_percent"] + 1e-6
    # con plusvalenze tassabili l'aliquota effettiva resta entro il 26%
    if net["realized_gains_taxable"] > 0:
        assert 0 < net["effective_tax_rate_percent"] <= 26.0 + 1e-6


def test_run_backtest_buy_and_hold(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("BUY_AND_HOLD"))

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["strategy_name"] == "BUY_AND_HOLD"
    assert data["summary"]["total_trades"] >= 1
    assert data["final_positions"]


def test_run_backtest_top_n_score(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("TOP_N_SCORE"))

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["strategy_name"] == "TOP_N_SCORE"
    assert len(data["equity_curve"]) > 50
    assert data["summary"]["total_trades"] >= 1


def _compare_payload() -> dict[str, object]:
    return {
        "name": "Confronto test",
        "strategy_names": ["SCORE_THRESHOLD", "BUY_AND_HOLD", "TOP_N_SCORE"],
        "symbols": ["AAPL", "MSFT", "SPY", "QQQ"],
        "initial_cash": 100000,
        "start_date": "2025-01-01",
        "end_date": "2026-05-15",
        "benchmark_symbol": "SPY",
        "buy_threshold": 55,
        "sell_threshold": 40,
        "max_asset_weight": 0.2,
        "fee_percent": 0.1,
        "stop_loss_percent": 8,
        "take_profit_percent": 25,
        "rebalance_frequency": "WEEKLY",
        "top_n": 2,
    }


def test_compare_strategies_endpoint(client: TestClient) -> None:
    response = client.post("/backtests/compare", json=_compare_payload())

    assert response.status_code == 200
    data = response.json()
    assert len(data["entries"]) == 3
    assert {entry["strategy_name"] for entry in data["entries"]} == {
        "SCORE_THRESHOLD",
        "BUY_AND_HOLD",
        "TOP_N_SCORE",
    }
    ranks = sorted(entry["rank"] for entry in data["entries"])
    assert ranks == [1, 2, 3]
    best = next(entry for entry in data["entries"] if entry["rank"] == 1)
    assert best["strategy_name"] == data["best_strategy"]
    assert all(len(entry["equity_curve"]) > 50 for entry in data["entries"])
    # i run di confronto non vengono persistiti nello storico
    history = client.get("/backtests").json()
    assert all("Confronto test" not in item["name"] for item in history)


def test_compare_strategies_requires_two(client: TestClient) -> None:
    payload = _compare_payload()
    payload["strategy_names"] = ["SCORE_THRESHOLD"]

    response = client.post("/backtests/compare", json=payload)

    assert response.status_code == 422


def test_walk_forward_endpoint(client: TestClient) -> None:
    payload = _backtest_payload("SCORE_THRESHOLD")
    payload["folds"] = 4

    response = client.post("/backtests/walk-forward", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["folds"] == 4
    assert len(data["fold_results"]) == 4
    assert data["consistency"] in {"ROBUSTA", "INCERTA", "FRAGILE"}
    assert data["positive_folds"] <= data["folds"]
    assert data["verdict"]
    folds_seen = [fold["fold"] for fold in data["fold_results"]]
    assert folds_seen == [1, 2, 3, 4]


def test_walk_forward_period_too_short(client: TestClient) -> None:
    payload = _backtest_payload("BUY_AND_HOLD")
    payload["start_date"] = "2026-05-10"
    payload["end_date"] = "2026-05-15"
    payload["folds"] = 12

    response = client.post("/backtests/walk-forward", json=payload)

    assert response.status_code == 400
    assert "fold" in response.json()["detail"].lower()


def _allocation_payload(method: str = "RISK_PARITY", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbols": ["AAPL", "MSFT", "SPY", "QQQ"],
        "method": method,
        "total_capital": 100000,
        "target_volatility": 0.15,
        "lookback_days": 120,
    }
    payload.update(overrides)
    return payload


def test_allocation_equal_weight(client: TestClient) -> None:
    response = client.post("/portfolio/allocation/plan", json=_allocation_payload("EQUAL_WEIGHT"))

    assert response.status_code == 200
    data = response.json()
    assert len(data["allocations"]) == 4
    for item in data["allocations"]:
        assert abs(item["weight_percent"] - 25.0) < 0.5
        assert item["suggested_quantity"] >= 0
    assert abs(data["invested_capital"] + data["cash_buffer"] - data["total_capital"]) < 0.01


def test_allocation_risk_parity_weights_sum(client: TestClient) -> None:
    response = client.post("/portfolio/allocation/plan", json=_allocation_payload("RISK_PARITY"))

    assert response.status_code == 200
    data = response.json()
    total_weight = sum(item["weight_percent"] for item in data["allocations"])
    assert abs(total_weight - 100.0) < 1.0
    # risk parity: l'asset meno volatile pesa piu del piu volatile
    by_vol = sorted(data["allocations"], key=lambda item: item["volatility"])
    assert by_vol[0]["weight_percent"] >= by_vol[-1]["weight_percent"]


def test_allocation_vol_target_keeps_cash(client: TestClient) -> None:
    response = client.post(
        "/portfolio/allocation/plan",
        json=_allocation_payload("VOL_TARGET", target_volatility=0.05),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["invested_capital"] <= data["total_capital"]
    assert data["cash_buffer"] >= 0
    # target molto basso => parte del capitale resta liquida
    assert data["cash_buffer"] > 0


def test_allocation_max_weight_cap(client: TestClient) -> None:
    response = client.post(
        "/portfolio/allocation/plan",
        json=_allocation_payload("RISK_PARITY", max_weight=0.3),
    )

    assert response.status_code == 200
    data = response.json()
    for item in data["allocations"]:
        assert item["weight_percent"] <= 30.5


def test_allocation_apply_creates_portfolio(client: TestClient) -> None:
    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT", "SPY"])
    plan_response = client.post("/portfolio/allocation/plan", json=payload)
    assert plan_response.status_code == 200
    plan = plan_response.json()

    response = client.post(
        "/portfolio/allocation/apply",
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    symbols = {position["symbol"] for position in data["positions"]}
    assert symbols == {"AAPL", "MSFT", "SPY"}
    assert all(position["quantity"] > 0 for position in data["positions"])
    assert data["invested_value"] > 0
    assert data["settings"]["initial_cash"] == payload["total_capital"]
    assert data["settings"]["current_cash"] == plan["cash_buffer"]


def test_scenario_market_crash(client: TestClient) -> None:
    # crea un portafoglio dal pianificatore così lo scenario ha posizioni
    client.post("/portfolio/allocation/apply", json=_allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "BTC", "SPY"]))

    response = client.post("/scenarios/run", json={"scenario_type": "MARKET_CRASH"})

    assert response.status_code == 200
    data = response.json()
    assert data["scenario_type"] == "MARKET_CRASH"
    assert data["base_currency"] == "EUR"
    assert data["stressed_value"] < data["current_value"]
    assert data["absolute_loss"] < 0
    assert data["risk_level"] in {"LOW", "MEDIUM", "HIGH", "EXTREME"}
    assert len(data["asset_impacts"]) == 3
    assert data["mitigation"]


def test_scenario_custom_shocks(client: TestClient) -> None:
    client.post("/portfolio/allocation/apply", json=_allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT"]))

    response = client.post(
        "/scenarios/run",
        json={"scenario_type": "CUSTOM", "class_shocks": {"stock": -10}},
    )

    assert response.status_code == 200
    data = response.json()
    assert all(abs(impact["shock_percent"] + 10) < 0.001 for impact in data["asset_impacts"])


def test_scenario_preserves_signed_short_liability_and_labels_gain_neutrally(client: TestClient) -> None:
    _init_flat(client)

    from backend.app.database import db_session

    with db_session() as connection:
        cursor = connection.execute(
            "INSERT INTO assets (symbol, name, asset_type, currency, risk_level) "
            "VALUES ('SHORT_EUR', 'Short EUR', 'stock', 'EUR', 'medium')"
        )
        connection.execute(
            "INSERT INTO price_history (asset_id, date, close, source, is_real_data) "
            "VALUES (?, '2099-01-01', 100, 'test', 1)",
            (cursor.lastrowid,),
        )

    opened = client.post(
        "/orders/simulate",
        json={
            "symbol": "SHORT_EUR",
            "order_type": "SELL",
            "quantity": 10,
            "price": 100,
            "fees": 0,
            "allow_short": True,
        },
    )
    assert opened.status_code == 200

    adverse = client.post(
        "/scenarios/run",
        json={"scenario_type": "CUSTOM", "symbol_shocks": {"SHORT_EUR": 20}},
    )

    assert adverse.status_code == 200
    adverse_data = adverse.json()
    asset = adverse_data["asset_impacts"][0]
    asset_class = adverse_data["class_impacts"][0]
    assert asset["current_value"] == -1000.0
    assert asset["stressed_value"] == -1200.0
    assert asset["absolute_impact"] == -200.0
    assert asset["outcome"] == "LOSS"
    assert asset_class["shock_percent"] == -20.0
    assert adverse_data["absolute_impact"] == -200.0
    assert adverse_data["absolute_loss"] == -200.0
    assert adverse_data["outcome"] == "LOSS"
    assert adverse_data["impact_label"] == "Perdita stimata"

    favorable = client.post(
        "/scenarios/run",
        json={"scenario_type": "CUSTOM", "symbol_shocks": {"SHORT_EUR": -20}},
    )

    assert favorable.status_code == 200
    favorable_data = favorable.json()
    asset = favorable_data["asset_impacts"][0]
    assert asset["stressed_value"] == -800.0
    assert asset["absolute_impact"] == 200.0
    assert asset["outcome"] == "GAIN"
    assert favorable_data["absolute_impact"] == 200.0
    assert favorable_data["absolute_loss"] == 0.0
    assert favorable_data["percentage_loss"] == 0.0
    assert favorable_data["outcome"] == "GAIN"
    assert favorable_data["impact_label"] == "Guadagno stimato"
    assert all("perdita" not in tip.lower() for tip in favorable_data["mitigation"])


def test_scenario_empty_portfolio_fails(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 50, "max_asset_class_weight": 80, "default_fee_percent": 0},
    )

    response = client.post("/scenarios/run", json={"scenario_type": "MARKET_CRASH"})

    assert response.status_code == 400
    assert "vuoto" in response.json()["detail"].lower()


def test_rebalance_produces_trades(client: TestClient) -> None:
    # portafoglio iniziale concentrato su AAPL
    client.post("/portfolio/allocation/apply", json=_allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"]))

    response = client.post(
        "/portfolio/allocation/rebalance",
        json=_allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT", "SPY"]),
    )

    assert response.status_code == 200
    data = response.json()
    actions = {trade["symbol"]: trade["action"] for trade in data["trades"]}
    # MSFT e SPY non sono in portafoglio -> da comprare
    assert actions.get("MSFT") == "BUY"
    assert actions.get("SPY") == "BUY"
    # AAPL era 100% -> va ridotto
    assert actions.get("AAPL") == "SELL"


def test_allocation_invalid_symbol(client: TestClient) -> None:
    response = client.post(
        "/portfolio/allocation/plan",
        json=_allocation_payload("EQUAL_WEIGHT", symbols=["NOPE"]),
    )

    assert response.status_code == 400
    assert "NOPE" in response.json()["detail"]


def test_backtest_history_and_detail_endpoints(client: TestClient) -> None:
    run_response = client.post("/backtests/run", json=_backtest_payload("SCORE_THRESHOLD"))
    backtest_id = run_response.json()["backtest_id"]

    list_response = client.get("/backtests")
    detail_response = client.get(f"/backtests/{backtest_id}")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert any(item["id"] == backtest_id for item in list_response.json())
    assert detail_response.json()["backtest_id"] == backtest_id
    assert detail_response.json()["trades"] is not None


def test_backtest_no_lookahead_on_future_jump() -> None:
    engine = BacktestEngine()
    stable_values = [100.0] * 90
    future_jump = [250.0] * 20
    full_frame = _price_frame(stable_values + future_jump)
    truncated_frame = _price_frame(stable_values)

    full_scored = engine.prepare_price_frame_for_backtest(full_frame)
    truncated_scored = engine.prepare_price_frame_for_backtest(truncated_frame)

    assert full_scored.loc[89, "rolling_score"] == truncated_scored.loc[89, "rolling_score"]


def test_api_cache_save_and_read(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
    from backend.app.database import db_session

    with db_session() as connection:
        provider = AlphaVantageProvider(get_settings(), connection)
        request_url = "https://example.test/query?symbol=AAPL"
        payload = {"Time Series (Daily)": {"2026-05-15": {"4. close": "100"}}}
        provider.save_to_cache("daily", "AAPL", request_url, payload)

        assert provider.get_from_cache("daily", "AAPL", request_url) == payload


def test_api_rate_limit_guard(client: TestClient) -> None:
    from datetime import date

    from backend.app.config import get_settings
    from backend.app.data_providers.base import RateLimitExceeded
    from backend.app.data_providers.coingecko import CoinGeckoProvider
    from backend.app.database import db_session

    with db_session() as connection:
        provider = CoinGeckoProvider(get_settings(), connection)
        today = date.today().isoformat()
        connection.execute(
            """
            INSERT INTO api_usage (provider, usage_date, calls_count, daily_limit)
            VALUES (?, ?, ?, ?)
            """,
            (provider.provider_name, today, provider.daily_limit, provider.daily_limit),
        )

        with pytest.raises(RateLimitExceeded):
            provider.check_rate_limit()


def test_alpha_vantage_proxy_symbols(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
    from backend.app.database import db_session

    with db_session() as connection:
        provider = AlphaVantageProvider(get_settings(), connection)
        assert "symbol=VT" in provider._request_url("VWCE")
        assert "symbol=BNDW" in provider._request_url("AGGH")
        assert "symbol=SHV" in provider._request_url("IB01")
        # i simboli non mappati restano invariati
        assert "symbol=AAPL" in provider._request_url("AAPL")


def test_yahoo_ticker_mapping(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.base import ProviderError
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider
    from backend.app.database import db_session

    with db_session() as connection:
        provider = YahooFinanceProvider(get_settings(), connection)
        # ETF europei -> ticker della borsa nativa nella valuta giusta
        assert provider.yahoo_ticker("VWCE") == "VWCE.DE"
        assert provider.yahoo_ticker("AGGH") == "AGGH.MI"
        assert provider.yahoo_ticker("IB01") == "IB01.L"
        # i simboli USA passano invariati
        assert provider.yahoo_ticker("AAPL") == "AAPL"
        # i simboli senza equivalente Yahoo restano sui dati locali
        with pytest.raises(ProviderError):
            provider.yahoo_ticker("BTP10Y")
        # nessuna API key richiesta
        assert provider.api_key_configured() is True
        assert provider.full_history is True


def test_yahoo_normalize_prices(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider
    from backend.app.database import db_session

    sample = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "EUR", "symbol": "VWCE.DE"},
                    # 2024-01-02, 2024-01-03, 2024-01-04 (UTC)
                    "timestamp": [1_704_153_600, 1_704_240_000, 1_704_326_400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 101.0, None],
                                "high": [102.0, 103.0, None],
                                "low": [99.0, 100.0, None],
                                "close": [101.0, 102.5, None],
                                "volume": [1000, 1200, None],
                            }
                        ],
                        "adjclose": [{"adjclose": [101.0, 102.5, None]}],
                    },
                }
            ],
        }
    }
    with db_session() as connection:
        provider = YahooFinanceProvider(get_settings(), connection)
        prices = provider.normalize_prices(sample, "VWCE")

    # la candela con close None viene scartata
    assert len(prices) == 2
    assert all(price["source"] == "real" and price["provider"] == "yahoo_finance" for price in prices)
    assert prices[0]["close"] == 101.0
    assert prices[1]["close"] == 102.5
    # ordinato per data crescente
    assert prices[0]["date"] < prices[1]["date"]
    # campi completi
    assert {"date", "open", "high", "low", "close", "adjusted_close", "volume"} <= set(prices[0])


def test_yahoo_news_provider_normalizes(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.yahoo_news import YahooNewsProvider
    from backend.app.database import db_session

    sample = {
        "news": [
            {
                "title": "Apple beats earnings and raises guidance",
                "publisher": "Reuters",
                "link": "https://example.com/aapl",
                "providerPublishTime": 1_700_000_000,
            },
            {"title": "", "link": "https://example.com/skip"},  # senza titolo -> scartata
        ]
    }
    with db_session() as connection:
        provider = YahooNewsProvider(get_settings(), connection)
        items = provider.normalize_news(sample, "AAPL")

    assert provider.api_key_configured() is True
    assert provider.daily_limit == 0  # nessun limite giornaliero
    assert len(items) == 1
    assert items[0]["provider"] == "yahoo_news"
    assert items[0]["title"].startswith("Apple beats")
    assert items[0]["source"] == "Reuters"
    assert items[0]["published_at"] is not None
    assert -1.0 <= items[0]["sentiment_score"] <= 1.0


def test_finnhub_news_provider_normalizes(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.finnhub_news import FinnhubNewsProvider
    from backend.app.database import db_session

    sample = {
        "articles": [
            {
                "headline": "Company beats earnings and raises guidance",
                "summary": "Strong profit growth and upgrade",
                "url": "https://example.com/a",
                "source": "Reuters",
                "datetime": 1_700_000_000,
            },
            {"headline": "", "summary": "no title -> skipped"},
        ]
    }
    with db_session() as connection:
        provider = FinnhubNewsProvider(get_settings(), connection)
        items = provider.normalize_news(sample, "AAPL")

    assert len(items) == 1
    assert items[0]["provider"] == "finnhub_news"
    assert items[0]["title"].startswith("Company beats")
    assert items[0]["published_at"] is not None
    assert -1.0 <= items[0]["sentiment_score"] <= 1.0


def test_provider_registry(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.provider_registry import ProviderRegistry
    from backend.app.database import db_session

    with db_session() as connection:
        registry = ProviderRegistry(get_settings(), connection)

        assert registry.provider_for_asset_type("stock").provider_name == "yahoo_finance"
        assert registry.provider_for_asset_type("etf").provider_name == "yahoo_finance"
        assert registry.provider_for_asset_type("bond_etf").provider_name == "yahoo_finance"
        assert registry.provider_for_asset_type("crypto").provider_name == "coingecko"
        assert registry.provider_for_asset_type("macro").provider_name == "fred"


def test_refresh_asset_with_real_data_disabled(client: TestClient) -> None:
    response = client.post("/data/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["used_fallback"] is True
    assert data["rows_inserted"] == 0
    assert "Dati reali disattivati" in data["message"]


def test_refresh_asset_falls_back_on_provider_error(client: TestClient, monkeypatch) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.base import ProviderError
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()

    # Forza un errore del provider per restare deterministici e non dipendere
    # dalla rete: Yahoo non richiede API key, quindi simuliamo l'indisponibilita'.
    def _raise(self, symbol: str, force: bool = False):  # noqa: ANN001, ANN202
        raise ProviderError("Yahoo non raggiungibile nei test.")

    monkeypatch.setattr(YahooFinanceProvider, "get_daily_prices", _raise)

    response = client.post("/data/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "yahoo_finance"
    assert data["used_fallback"] is True
    assert data["rows_inserted"] == 0

    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    get_settings.cache_clear()


def test_data_status_endpoint(client: TestClient) -> None:
    response = client.get("/data/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enable_real_data"] is False
    assert data["data_mode"] == "SEED"
    assert {provider["provider"] for provider in data["provider_status"]} >= {"yahoo_finance", "coingecko", "fred"}
    assert data["cache_stats"]["entries"] >= 0


def test_asset_data_status_endpoint(client: TestClient) -> None:
    response = client.get("/data/status/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["last_source"] == "seed"
    assert data["is_real_data"] is False
    assert "seed/demo" in data["message"]


def test_data_refresh_endpoint_uses_fallback(client: TestClient) -> None:
    response = client.post("/data/refresh/BTC")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BTC"
    assert data["provider"] == "coingecko"
    assert data["used_fallback"] is True


def test_repeated_refresh_does_not_duplicate_price_history(client: TestClient) -> None:
    from backend.app.database import db_session

    with db_session() as connection:
        before = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE a.symbol = 'AAPL'
            """
        ).fetchone()["count"]

    client.post("/data/refresh/AAPL")
    client.post("/data/refresh/AAPL")

    with db_session() as connection:
        after = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE a.symbol = 'AAPL'
            """
        ).fetchone()["count"]

    assert after == before


def test_sentiment_positive_keyword() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("Earnings beat and revenue growth support a dividend increase.")

    assert result["sentiment_label"] == "POSITIVE"
    assert result["sentiment_score"] > 0


def test_sentiment_negative_keyword() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("Guidance cut follows an investigation and revenue decline.")

    assert result["sentiment_label"] == "NEGATIVE"
    assert result["sentiment_score"] < 0


def test_sentiment_neutral_without_keywords() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("")

    assert result["sentiment_label"] == "NEUTRAL"
    assert result["sentiment_score"] == 0


def test_news_impact_levels() -> None:
    from backend.app.services.sentiment_engine import estimate_impact

    assert estimate_impact({"title": "Upgrade after earnings beat", "summary": "", "sentiment_score": 0.7, "relevance_score": 90}) == "HIGH"
    assert estimate_impact({"title": "Revenue growth update", "summary": "", "sentiment_score": 0.2, "relevance_score": 55}) == "MEDIUM"
    assert estimate_impact({"title": "Market update", "summary": "", "sentiment_score": 0.0, "relevance_score": 20}) == "LOW"


def test_news_deduplication(client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.services.news_engine import NewsEngine

    item = {
        "provider": "test",
        "title": "AAPL earnings beat",
        "summary": "Earnings beat and revenue growth.",
        "url": "https://example.test/aapl-earnings",
        "source": "Unit Test",
        "published_at": "2026-05-18T10:00:00",
        "sentiment_score": 0.6,
        "sentiment_label": "POSITIVE",
        "relevance_score": 90,
    }
    with db_session() as connection:
        engine = NewsEngine()
        first = engine.save_news_to_db(connection, "AAPL", [item])
        second = engine.save_news_to_db(connection, "AAPL", [item])
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM news_items WHERE symbol = 'AAPL' AND url = ?",
            (item["url"],),
        ).fetchone()["count"]

    assert first == (1, 0)
    assert second == (0, 1)
    assert count == 1


def test_refresh_news_with_real_news_disabled(client: TestClient) -> None:
    response = client.post("/news/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["provider"] == "mock_news"
    assert data["used_fallback"] is True
    assert "News reali disattivate" in data["message"]


def test_refresh_news_fallback_when_api_key_missing(client: TestClient, monkeypatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    # disabilita Yahoo (keyless) per testare il fallback a mock quando manca ogni key
    monkeypatch.setenv("ENABLE_YAHOO_NEWS", "false")
    get_settings.cache_clear()

    response = client.post("/news/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock_news"
    assert data["used_fallback"] is True
    assert "Provider news non configurato" in data["message"]

    monkeypatch.setenv("ENABLE_REAL_NEWS", "false")
    monkeypatch.setenv("ENABLE_YAHOO_NEWS", "true")
    get_settings.cache_clear()


def test_news_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news?symbol=AAPL")

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert {"title", "sentiment_label", "impact_level", "relevance_score"} <= set(data[0])


def test_symbol_news_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news/AAPL")

    assert response.status_code == 200
    assert all(item["symbol"] == "AAPL" for item in response.json())


def test_news_sentiment_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news/sentiment/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["news_count"] >= 1
    assert data["sentiment_label"] in {"POSITIVE", "NEGATIVE", "NEUTRAL"}
    assert {"positive_count", "negative_count", "neutral_count", "latest_news"} <= set(data)


def test_news_status_endpoint(client: TestClient) -> None:
    response = client.get("/news/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enable_real_news"] is False
    assert {provider["provider"] for provider in data["provider_status"]} >= {"yahoo_news", "mock_news"}
    assert data["daily_usage"]["calls_count"] == 0


def test_data_refresh_all_endpoint(client: TestClient) -> None:
    response = client.post("/data/refresh-all?limit=3")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["requested"] == 3
    assert data["summary"]["fallback"] == 3
    assert len(data["results"]) == 3
    assert all(item["used_fallback"] is True for item in data["results"])


def test_news_refresh_all_endpoint(client: TestClient) -> None:
    response = client.post("/news/refresh-all?limit=3")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["requested"] == 3
    assert len(data["results"]) == 3
    assert all(item["provider"] == "mock_news" for item in data["results"])
