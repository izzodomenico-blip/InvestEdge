from __future__ import annotations

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from backend.app.services.backtest_engine import BacktestEngine
from backend.app.services.technical_analysis import TechnicalAnalysisService


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "investedge.db"))

    from backend.app.config import get_settings

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


def test_dashboard_after_seed(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["initialized"] is True
    assert data["assets_count"] == 25
    assert data["signals_count"] == 25
    assert data["price_points_count"] >= 14000
    assert data["latest_signals"]


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
