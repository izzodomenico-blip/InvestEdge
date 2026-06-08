from __future__ import annotations

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

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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


def test_import_preview_requires_url(client: TestClient) -> None:
    response = client.post("/import/google-sheets/preview", json={"csv_url": ""})

    assert response.status_code == 400
    assert "URL" in response.json()["detail"]


def test_import_apply_replaces_positions(client: TestClient, monkeypatch) -> None:
    csv_text = (
        "symbol,quantity,average_price,currency\n"
        "AAPL,10,150,USD\n"
        "MSFT,4,300,USD\n"
    )
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: csv_text,
    )

    response = client.post("/import/google-sheets/apply", json={"csv_url": "http://example.test/sheet.csv"})

    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 2

    portfolio = client.get("/portfolio").json()
    symbols = {position["symbol"] for position in portfolio["positions"]}
    assert symbols == {"AAPL", "MSFT"}
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["quantity"] == 10
    assert aapl["average_price"] == 150


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
    assert len(data["positions"]) == 7
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
    assert data["updated_position"]["quantity"] == 2
    assert data["updated_portfolio_summary"]["cash"] == 9800


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
    assert data["updated_portfolio_summary"]["realized_pnl"] == 20


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


def test_provider_registry(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.provider_registry import ProviderRegistry
    from backend.app.database import db_session

    with db_session() as connection:
        registry = ProviderRegistry(get_settings(), connection)

        assert registry.provider_for_asset_type("stock").provider_name == "alpha_vantage"
        assert registry.provider_for_asset_type("crypto").provider_name == "coingecko"
        assert registry.provider_for_asset_type("macro").provider_name == "fred"


def test_refresh_asset_with_real_data_disabled(client: TestClient) -> None:
    response = client.post("/data/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["used_fallback"] is True
    assert data["rows_inserted"] == 0
    assert "Dati reali disattivati" in data["message"]


def test_refresh_asset_fallback_when_api_key_missing(client: TestClient, monkeypatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    get_settings.cache_clear()

    response = client.post("/data/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["used_fallback"] is True
    assert "API key non configurata" in data["message"]

    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    get_settings.cache_clear()


def test_data_status_endpoint(client: TestClient) -> None:
    response = client.get("/data/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enable_real_data"] is False
    assert data["data_mode"] == "SEED"
    assert {provider["provider"] for provider in data["provider_status"]} >= {"alpha_vantage", "coingecko", "fred"}
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
    get_settings.cache_clear()

    response = client.post("/news/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock_news"
    assert data["used_fallback"] is True
    assert "Provider news non configurato" in data["message"]

    monkeypatch.setenv("ENABLE_REAL_NEWS", "false")
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
    assert {provider["provider"] for provider in data["provider_status"]} >= {"alpha_vantage_news", "mock_news"}
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
