from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.app.config import get_settings
from backend.app.lab.costs import CostProfile
from backend.app.lab.series import EurConverter
from backend.app.lab.simulator import (
    AssetMarket,
    SimulationConfig,
    SimulationResult,
    TradeRecord,
    compute_metrics,
    simulate,
)
from backend.app.lab.strategies import StrategyParams, rebalance_key, target_weights
from tests.lab_fixtures import insert_fx, synthetic_bars

COSTS = CostProfile(
    commission_eur=1.0, cost_bps_equity=10, cost_bps_crypto=50, fractional_shares=False, min_trade_eur=100
)
COST_ENV = (
    "TR_COMMISSION_EUR",
    "TR_COST_BPS_EQUITY",
    "TR_COST_BPS_CRYPTO",
    "BACKTEST_FRACTIONAL_SHARES",
    "BACKTEST_MIN_TRADE_EUR",
    "LAB_ORDER_MAX_PENDING_SESSIONS",
)


def _market(
    asset_id: int,
    rows: list[tuple[str, float, float, float, float]],
    *,
    symbol: str | None = None,
    asset_type: str = "stock",
    segments: list[int] | None = None,
) -> AssetMarket:
    bars = pd.DataFrame(rows, columns=["date", "open_eur", "high_eur", "low_eur", "close_eur"]).set_index("date")
    bars["segment_id"] = segments if segments is not None else 0
    return AssetMarket(asset_id=asset_id, symbol=symbol or f"A{asset_id}", asset_type=asset_type, bars=bars)


def _flat(dates: list[str], price: float = 100.0) -> list[tuple[str, float, float, float, float]]:
    return [(day, price, price, price, price) for day in dates]


def _config(
    params: StrategyParams | tuple[tuple[str, StrategyParams], ...],
    *,
    start: str = "2024-01-01",
    stop: float | None = None,
    take_profit: float | None = None,
    cash: float = 10_000,
    costs: CostProfile = COSTS,
    pending: int = 5,
) -> SimulationConfig:
    schedule = params if isinstance(params, tuple) else ((start, params),)
    return SimulationConfig(
        initial_cash_eur=cash,
        costs=costs,
        params_schedule=schedule,
        stop_loss_percent=stop,
        take_profit_percent=take_profit,
        max_pending_sessions=pending,
    )


def _business_days(start: str, count: int) -> list[str]:
    return list(pd.bdate_range(start, periods=count).strftime("%Y-%m-%d"))


def _threshold(max_weight: float = 0.5, frequency: str = "WEEKLY", **kwargs) -> StrategyParams:
    return StrategyParams(
        "SCORE_THRESHOLD", buy_threshold=70, sell_threshold=40, max_asset_weight=max_weight,
        rebalance_frequency=frequency, **kwargs,
    )


HAND_CALENDAR = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
HAND_ROWS = [
    ("2024-01-01", 100, 101, 99, 100),
    ("2024-01-02", 102, 103, 101, 102),
    ("2024-01-03", 104, 105, 103, 104),
    ("2024-01-04", 103, 104, 90, 95),
    ("2024-01-05", 96, 97, 95, 96),
]


def _hand_result() -> SimulationResult:
    markets = {1: _market(1, HAND_ROWS, symbol="A")}
    signals = pd.DataFrame(80.0, index=HAND_CALENDAR, columns=[1])
    return simulate(markets, signals, HAND_CALENDAR, _config(_threshold(), stop=8))


def test_hand_computed_scenario() -> None:
    result = _hand_result()
    buy, stop = result.trades
    assert (buy.date, buy.side, buy.quantity) == ("2024-01-02", "BUY", 48)        # decisione il 1°, fill il 2
    assert buy.price_eur == pytest.approx(102.102)
    assert buy.spread_cost_eur == pytest.approx(4.896)
    assert buy.commission_eur == pytest.approx(1.0)
    assert (stop.date, stop.reason) == ("2024-01-04", "STOP_LOSS")
    assert stop.price_eur == pytest.approx(93.93384 * 0.999)                       # stop 102.102 x 0,92, poi costo
    assert stop.pnl_eur == pytest.approx(48 * 93.93384 * 0.999 - 1 - (48 * 102.102 + 1))
    values = result.equity.set_index("date")["value_eur"]
    assert values["2024-01-01"] == pytest.approx(10_000)
    assert values["2024-01-02"] == pytest.approx(10_000 - 48 * 102.102 - 1 + 48 * 102)
    assert values["2024-01-03"] == pytest.approx(10_000 - 48 * 102.102 - 1 + 48 * 104)
    assert values["2024-01-05"] == pytest.approx(10_000 - 48 * 102.102 - 1 + 48 * 93.93384 * 0.999 - 1)
    assert result.costs["commission_eur"] == pytest.approx(2.0)


def test_hand_scenario_accounting_turnover_and_exposure() -> None:
    result = _hand_result()
    buy, stop = result.trades
    assert buy.gross_eur == pytest.approx(48 * 102.102)
    assert buy.net_eur == pytest.approx(48 * 102.102 + 1)
    assert buy.pnl_eur == 0
    assert stop.gross_eur == pytest.approx(48 * 93.93384 * 0.999)
    assert stop.net_eur == pytest.approx(48 * 93.93384 * 0.999 - 1)
    assert stop.spread_cost_eur == pytest.approx(48 * 93.93384 * 0.001)
    assert result.costs["spread_cost_eur"] == pytest.approx(4.896 + 48 * 93.93384 * 0.001)
    assert result.cancelled_orders == ()
    equity = result.equity.set_index("date")
    assert list(equity.columns) == ["value_eur", "cash_eur", "invested_eur", "drawdown"]
    assert (equity["value_eur"] == equity["cash_eur"] + equity["invested_eur"]).all()
    assert equity.loc["2024-01-03", "drawdown"] == 0
    peak = equity.loc["2024-01-03", "value_eur"]
    assert equity.loc["2024-01-05", "drawdown"] == pytest.approx((equity.loc["2024-01-05", "value_eur"] / peak - 1) * 100)
    assert result.daily_returns.index.tolist() == HAND_CALENDAR[1:]
    assert result.daily_returns.to_numpy() == pytest.approx(equity["value_eur"].pct_change().to_numpy()[1:])
    traded = 48 * 102.102 + 48 * 93.93384 * 0.999
    assert result.turnover == pytest.approx(traded / equity["value_eur"].mean())
    assert result.exposure == pytest.approx((equity["invested_eur"] / equity["value_eur"]).mean())


def test_no_fill_on_signal_bar() -> None:
    frame = synthetic_bars(60, seed=11)
    calendar = frame["date"].tolist()
    markets = {}
    rng = np.random.default_rng(5)
    for asset_id in (1, 2, 3):
        bars = synthetic_bars(60, seed=20 + asset_id)
        rows = list(zip(bars["date"], bars["open"], bars["high"], bars["low"], bars["close"], strict=True))
        markets[asset_id] = _market(asset_id, rows)
    signals = pd.DataFrame(rng.uniform(0, 100, (60, 3)), index=calendar, columns=[1, 2, 3])
    params = StrategyParams("SCORE_THRESHOLD", buy_threshold=60, sell_threshold=40, max_asset_weight=0.3,
                            rebalance_frequency="DAILY")
    result = simulate(markets, signals, calendar, _config(params, start=calendar[0]))

    assert len(result.trades) > 10
    assert all(trade.date != calendar[0] for trade in result.trades)
    for trade in result.trades:
        assert trade.reason in {"SIGNAL", "REBALANCE"}
        open_eur = markets[trade.asset_id].bars.loc[trade.date, "open_eur"]
        side = 1 if trade.side == "BUY" else -1
        assert trade.price_eur == pytest.approx(open_eur * (1 + side * 0.001))


def test_gap_down_stop_fills_at_open() -> None:
    calendar = HAND_CALENDAR[:3]
    rows = [
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 100, 101, 99, 100),          # acquisto a 100,1: stop 8% = 92,092
        ("2024-01-03", 92, 93, 91, 92.5),           # apertura sotto lo stop
    ]
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    result = simulate({1: _market(1, rows)}, signals, calendar, _config(_threshold(), stop=8))
    buy, stop = result.trades
    assert buy.price_eur == pytest.approx(100.1)
    assert (stop.date, stop.reason, stop.quantity) == ("2024-01-03", "STOP_LOSS", buy.quantity)
    assert stop.price_eur == pytest.approx(92 * 0.999)


def test_take_profit_fills_at_level() -> None:
    calendar = HAND_CALENDAR[:3]
    rows = [
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 100, 101, 99, 100),          # take profit 5% = 105,105
        ("2024-01-03", 103, 107, 102.5, 106),
    ]
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    result = simulate({1: _market(1, rows)}, signals, calendar, _config(_threshold(), take_profit=5))
    _, exit_trade = result.trades
    assert (exit_trade.date, exit_trade.reason) == ("2024-01-03", "TAKE_PROFIT")
    assert exit_trade.price_eur == pytest.approx(100.1 * 1.05 * 0.999)


def test_stop_wins_when_both_levels_hit() -> None:
    calendar = HAND_CALENDAR[:3]
    rows = [
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 100, 101, 99, 100),
        ("2024-01-03", 100, 110, 90, 100),          # tocca sia 92,092 sia 105,105
    ]
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    result = simulate({1: _market(1, rows)}, signals, calendar, _config(_threshold(), stop=8, take_profit=5))
    _, exit_trade = result.trades
    assert exit_trade.reason == "STOP_LOSS"
    assert exit_trade.price_eur == pytest.approx(100.1 * 0.92 * 0.999)


def test_crypto_quantity_is_fractional() -> None:
    calendar = HAND_CALENDAR[:2]
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    markets = {1: _market(1, _flat(calendar, 20_000), symbol="BTC", asset_type="crypto")}
    result = simulate(markets, signals, calendar, _config(_threshold(0.5)))
    (buy,) = result.trades
    assert buy.quantity == pytest.approx(5000 / (20000 * 1.005))
    assert buy.price_eur == pytest.approx(20000 * 1.005)
    assert buy.spread_cost_eur == pytest.approx(buy.quantity * 20000 * 0.005)
    assert buy.commission_eur == pytest.approx(1.0)


def test_order_below_min_trade_is_not_created() -> None:
    calendar = HAND_CALENDAR[:2]
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    fractional = CostProfile(
        commission_eur=1.0, cost_bps_equity=10, cost_bps_crypto=50, fractional_shares=True, min_trade_eur=100
    )
    markets = {1: _market(1, _flat(calendar))}
    below = simulate(markets, signals, calendar, _config(_threshold(0.009), costs=fractional))   # 90 EUR
    assert below.trades == ()
    assert below.cancelled_orders == ()
    above = simulate(markets, signals, calendar, _config(_threshold(0.011), costs=fractional))   # 110 EUR
    (buy,) = above.trades
    assert buy.quantity == pytest.approx(110 / 100.1)


def test_full_exit_is_allowed_below_min_trade() -> None:
    calendar = _business_days("2024-01-01", 10)
    rows = _flat(calendar[:5]) + _flat(calendar[5:], 50.0)
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    signals.loc["2024-01-08":, 1] = 30.0
    fractional = CostProfile(
        commission_eur=1.0, cost_bps_equity=10, cost_bps_crypto=50, fractional_shares=True, min_trade_eur=100
    )
    result = simulate({1: _market(1, rows)}, signals, calendar, _config(_threshold(0.011), costs=fractional))
    buy, sell = result.trades
    assert (sell.date, sell.side, sell.reason) == ("2024-01-09", "SELL", "SIGNAL")
    assert sell.quantity == pytest.approx(buy.quantity)
    assert sell.gross_eur == pytest.approx(110 / 100.1 * 50 * 0.999)          # sotto i 100 EUR, uscita ammessa


def test_buy_below_min_trade_at_open_is_cancelled_and_recorded() -> None:
    calendar = HAND_CALENDAR[:2]
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    markets = {1: _market(1, _flat(calendar, 200.0), symbol="BIG")}
    result = simulate(markets, signals, calendar, _config(_threshold(0.015)))    # 150 EUR, quota da 200,2
    assert result.trades == ()
    assert result.cancelled_orders == (
        {
            "date": "2024-01-02",
            "decision_date": "2024-01-01",
            "asset_id": 1,
            "symbol": "BIG",
            "side": "BUY",
            "reason": "BELOW_MIN_TRADE",
        },
    )


def test_buy_limited_by_cash_is_recorded_as_insufficient_cash() -> None:
    calendar = HAND_CALENDAR[:2]
    markets = {1: _market(1, _flat(calendar)), 2: _market(2, _flat(calendar))}
    signals = pd.DataFrame({1: 90.0, 2: 80.0}, index=calendar)
    result = simulate(markets, signals, calendar, _config(_threshold(1.0)))
    (buy,) = result.trades
    assert (buy.asset_id, buy.quantity) == (1, 99)                    # restano 89,10 EUR di cassa
    assert result.cancelled_orders == (
        {
            "date": "2024-01-02",
            "decision_date": "2024-01-01",
            "asset_id": 2,
            "symbol": "A2",
            "side": "BUY",
            "reason": "INSUFFICIENT_CASH",
        },
    )


def test_fractional_buy_never_leaves_negative_cash() -> None:
    calendar = HAND_CALENDAR[:2]
    markets = {1: _market(1, _flat(calendar, 30_000.0), symbol="BTC", asset_type="crypto")}
    hold = StrategyParams("BUY_AND_HOLD", max_asset_weight=1.0)
    # 7776,77 / 30150 × 30150 supera 7776,77 di un ulp: la cassa resterebbe a -9e-13.
    result = simulate(markets, pd.DataFrame(index=calendar), calendar, _config(hold, cash=7777.77))
    (buy,) = result.trades
    assert buy.quantity == pytest.approx(7776.77 / 30150)
    assert (result.equity["cash_eur"] >= 0).all()


def test_missing_next_bar_keeps_order_pending_then_cancels() -> None:
    calendar = _business_days("2024-01-01", 8)        # 01-01 ... 01-05, 01-08, 01-09, 01-10
    markets = {
        1: _market(1, _flat(["2024-01-01", "2024-01-09"]), symbol="FIVE"),     # 5 sedute senza barra
        2: _market(2, _flat(["2024-01-01", "2024-01-10"]), symbol="SIX"),      # 6 sedute senza barra
        3: _market(3, _flat(calendar), symbol="CAL"),                           # solo calendario
    }
    signals = pd.DataFrame(np.nan, index=calendar, columns=[1, 2, 3])
    signals.loc["2024-01-01", [1, 2]] = 80.0
    result = simulate(markets, signals, calendar, _config(_threshold(0.3, "DAILY")))

    (buy,) = result.trades
    assert (buy.date, buy.asset_id, buy.side) == ("2024-01-09", 1, "BUY")
    assert result.cancelled_orders == (
        {
            "date": "2024-01-09",
            "decision_date": "2024-01-01",
            "asset_id": 2,
            "symbol": "SIX",
            "side": "BUY",
            "reason": "PENDING_TIMEOUT",
        },
    )


def test_segment_exit_sells_at_last_close_of_segment() -> None:
    calendar = HAND_CALENDAR
    rows = [
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 100, 101, 99, 100),
        ("2024-01-03", 103, 105, 102, 104),
        ("2024-01-04", 52, 53, 51, 52),             # split sospetto: nuovo segmento
        ("2024-01-05", 52, 53, 51, 52),
    ]
    markets = {1: _market(1, rows, segments=[0, 0, 0, 1, 1])}
    signals = pd.DataFrame(80.0, index=calendar, columns=[1])
    result = simulate(markets, signals, calendar, _config(_threshold(0.5, "DAILY")))

    buy, segment_exit, new_buy = result.trades
    assert (buy.date, buy.quantity) == ("2024-01-02", 49)
    assert (segment_exit.date, segment_exit.side, segment_exit.reason) == ("2024-01-03", "SELL", "SEGMENT_EXIT")
    assert segment_exit.quantity == 49
    assert segment_exit.price_eur == pytest.approx(104 * 0.999)
    assert segment_exit.pnl_eur == pytest.approx(49 * 104 * 0.999 - 1 - (49 * 100.1 + 1))
    # Nessun ordine deciso sull'ultima barra del segmento: il nuovo acquisto parte dal nuovo segmento.
    assert (new_buy.date, new_buy.side) == ("2024-01-05", "BUY")
    assert new_buy.price_eur == pytest.approx(52 * 1.001)


def test_top_n_and_buy_and_hold_follow_legacy_semantics() -> None:
    top = StrategyParams("TOP_N_SCORE", max_asset_weight=0.4, top_n=3)
    weights = target_weights(
        top,
        {1: 90.0, 2: 80.0, 3: 70.0, 4: 85.0, 5: 95.0},
        {1: 0.5, 3: 0.3, 4: 0.34},
        first_rebalance=False,
    )
    # Primi 3 (5, 1, 4) a min(0,4, 1/3); 1 sopra la banda del 5% scende, 4 dentro la banda resta,
    # 3 fuori dalla selezione viene venduto, 2 non posseduto e non selezionato resta fuori.
    assert weights == pytest.approx({5: 1 / 3, 1: 1 / 3, 3: 0.0})
    few = target_weights(
        StrategyParams("TOP_N_SCORE", max_asset_weight=0.6, top_n=5), {7: 50.0}, {}, first_rebalance=False
    )
    assert few == pytest.approx({7: 0.6})

    hold = StrategyParams("BUY_AND_HOLD", max_asset_weight=0.4)
    assert target_weights(hold, {1: 10.0, 2: 20.0, 3: 30.0}, {}, first_rebalance=True) == pytest.approx(
        {1: 1 / 3, 2: 1 / 3, 3: 1 / 3}
    )
    assert target_weights(hold, {1: 10.0}, {1: 0.3}, first_rebalance=False) is None

    threshold = StrategyParams("SCORE_THRESHOLD", buy_threshold=70, sell_threshold=40, max_asset_weight=0.2)
    assert target_weights(
        threshold, {1: 35.0, 2: 75.0, 3: 50.0, 4: 80.0}, {1: 0.1, 3: 0.1, 4: 0.25}, first_rebalance=False
    ) == pytest.approx({1: 0.0, 2: 0.2})

    # Buy & hold nel simulatore: acquisto iniziale (anche senza segnale), poi nessun altro ordine.
    calendar = _business_days("2024-01-01", 15)
    markets = {1: _market(1, _flat(calendar)), 2: _market(2, _flat(calendar, 50.0))}
    signals = pd.DataFrame(np.nan, index=calendar, columns=[1, 2])
    result = simulate(markets, signals, calendar, _config(hold))
    assert [(trade.date, trade.asset_id, trade.side) for trade in result.trades] == [
        ("2024-01-02", 1, "BUY"),
        ("2024-01-02", 2, "BUY"),
    ]
    assert [trade.quantity for trade in result.trades] == [39, 79]       # 4000 / 100,1 e 4000 / 50,05


def test_sells_execute_before_buys_at_the_same_open() -> None:
    calendar = _business_days("2024-01-01", 10)
    markets = {1: _market(1, _flat(calendar)), 2: _market(2, _flat(calendar))}
    signals = pd.DataFrame({1: 90.0, 2: 50.0}, index=calendar)
    signals.loc["2024-01-08":, 1] = 50.0
    signals.loc["2024-01-08":, 2] = 90.0
    params = StrategyParams("TOP_N_SCORE", max_asset_weight=1.0, top_n=1)
    result = simulate(markets, signals, calendar, _config(params))
    assert [(t.date, t.asset_id, t.side, t.quantity, t.reason) for t in result.trades] == [
        ("2024-01-02", 1, "BUY", 99, "SIGNAL"),
        ("2024-01-09", 1, "SELL", 99, "SIGNAL"),
        ("2024-01-09", 2, "BUY", 99, "SIGNAL"),     # possibile solo con la cassa della vendita
    ]


def test_params_schedule_switches_without_liquidation() -> None:
    calendar = _business_days("2024-01-01", 10)
    markets = {1: _market(1, _flat(calendar)), 2: _market(2, _flat(calendar))}
    signals = pd.DataFrame({1: 80.0, 2: 65.0}, index=calendar)
    signals.loc["2024-01-08":, 1] = 50.0
    first = StrategyParams("SCORE_THRESHOLD", buy_threshold=70, sell_threshold=40, max_asset_weight=0.4)
    second = StrategyParams("SCORE_THRESHOLD", buy_threshold=60, sell_threshold=45, max_asset_weight=0.4)
    schedule = (("2024-01-01", first), ("2024-01-08", second))
    result = simulate(markets, signals, calendar, _config(schedule))
    assert [(t.date, t.asset_id, t.side) for t in result.trades] == [
        ("2024-01-02", 1, "BUY"),
        ("2024-01-09", 2, "BUY"),
    ]
    equity = result.equity.set_index("date")
    assert equity.loc["2024-01-12", "invested_eur"] == pytest.approx((39 + 39) * 100)


def test_three_asset_scenario_converts_usd_and_stops_on_eur_gap(lab_connection) -> None:
    insert_fx(lab_connection, "USD", [("2024-01-01", 0.9), ("2024-01-03", 0.8)])
    calendar = HAND_CALENDAR[:3]
    local = {
        1: ("EURSTK", "stock", "EUR", [(50, 50, 50, 50), (50, 51, 49.5, 50.5), (50.5, 51, 50, 51)]),
        2: ("USDSTK", "stock", "USD", [(200, 200, 200, 200), (200, 202, 199, 201), (200, 201, 195, 198)]),
        3: ("BTC", "crypto", "EUR", [(30000,) * 4, (30000, 30500, 29800, 30200), (30200, 31000, 30100, 30900)]),
    }
    converter = EurConverter(lab_connection, max_age_days=7)
    markets = {}
    for asset_id, (symbol, asset_type, currency, ohlc) in local.items():
        bars = pd.DataFrame(ohlc, columns=["open", "high", "low", "close"])
        bars.insert(0, "date", calendar)
        bars["adjusted_close"] = bars["close"]
        converted, excluded = converter.convert_bars(bars, currency)
        assert excluded == 0
        eur = converted.set_index("date")[["open_eur", "high_eur", "low_eur", "close_eur"]]
        eur["segment_id"] = 0
        markets[asset_id] = AssetMarket(asset_id=asset_id, symbol=symbol, asset_type=asset_type, bars=eur)
    signals = pd.DataFrame(80.0, index=calendar, columns=[1, 2, 3])

    result = simulate(markets, signals, calendar, _config(_threshold(0.3), stop=10))

    eur_buy, usd_buy, btc_buy, usd_stop = result.trades
    assert (eur_buy.quantity, eur_buy.price_eur) == (59, pytest.approx(50.05))
    assert (usd_buy.quantity, usd_buy.price_eur) == (16, pytest.approx(200 * 0.9 * 1.001))
    assert btc_buy.quantity == pytest.approx(3000 / 30150)
    # 200 USD al cambio 0,8 = 160 EUR: apertura sotto lo stop 162,162 (180,18 x 0,9).
    assert (usd_stop.date, usd_stop.reason, usd_stop.quantity) == ("2024-01-03", "STOP_LOSS", 16)
    assert usd_stop.price_eur == pytest.approx(160 * 0.999)
    assert usd_stop.pnl_eur == pytest.approx(16 * 159.84 - 1 - (16 * 180.18 + 1))
    cash = 10_000 - 59 * 50.05 - 16 * 180.18 - 3000 - 3 + 16 * 159.84 - 1
    invested = 59 * 51 + (3000 / 30150) * 30900
    final = result.equity.set_index("date").loc["2024-01-03"]
    assert final["cash_eur"] == pytest.approx(cash)
    assert final["value_eur"] == pytest.approx(cash + invested)
    assert result.costs["commission_eur"] == pytest.approx(4.0)
    assert result.costs["spread_cost_eur"] == pytest.approx(
        59 * 50 * 0.001 + 16 * 180 * 0.001 + (3000 / 30150) * 30000 * 0.005 + 16 * 160 * 0.001
    )


def test_metrics_known_values() -> None:
    dates = ["2024-01-01", "2024-04-01", "2024-07-01", "2025-01-01"]
    values = pd.Series([100.0, 110.0, 99.0, 108.9])
    equity = pd.DataFrame(
        {"date": dates, "value_eur": values, "cash_eur": values * 0.4, "invested_eur": values * 0.6,
         "drawdown": [0.0, 0.0, -10.0, -1.0]}
    )
    returns = pd.Series([0.1, -0.1, 0.1], index=dates[1:])

    def sell(pnl: float) -> TradeRecord:
        return TradeRecord("2024-07-01", 1, "A", "SELL", 1, 10.0, 1.0, 0.01, 10.0, 9.0, pnl, "SIGNAL")

    buy = TradeRecord("2024-01-01", 1, "A", "BUY", 1, 10.0, 1.0, 0.01, 10.0, 11.0, 0.0, "SIGNAL")
    result = SimulationResult(
        equity=equity, trades=(buy, sell(30), sell(-10), sell(20)), cancelled_orders=(), daily_returns=returns,
        costs={"commission_eur": 4.0, "spread_cost_eur": 2.5}, turnover=1.5, exposure=0.6,
    )

    metrics = compute_metrics(result, 100.0)

    assert metrics["total_return_percent"] == pytest.approx(8.9)
    assert metrics["cagr"] == pytest.approx((1.089 ** (365.25 / 366) - 1) * 100)
    assert metrics["max_drawdown"] == pytest.approx(-10.0)
    assert metrics["sharpe_ratio"] == pytest.approx(returns.mean() / returns.std(ddof=1) * math.sqrt(252))
    assert metrics["profit_factor"] == pytest.approx(5.0)
    assert metrics["win_rate"] == pytest.approx(200 / 3)
    assert metrics["total_trades"] == 4
    assert (metrics["turnover"], metrics["exposure"]) == (1.5, 0.6)
    assert (metrics["commission_eur"], metrics["spread_cost_eur"]) == (4.0, 2.5)


def test_rebalance_key_by_frequency() -> None:
    assert rebalance_key("2024-01-03", "DAILY") == "2024-01-03"
    assert rebalance_key("2024-01-01", "WEEKLY") == rebalance_key("2024-01-07", "WEEKLY")
    assert rebalance_key("2024-01-08", "WEEKLY") != rebalance_key("2024-01-07", "WEEKLY")
    assert rebalance_key("2024-12-30", "WEEKLY") == rebalance_key("2025-01-01", "WEEKLY")     # settimana ISO
    assert rebalance_key("2024-01-31", "MONTHLY") == "2024-01"
    assert rebalance_key("2024-02-01", "MONTHLY") == "2024-02"


def test_cost_profile_from_settings_and_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in COST_ENV:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    try:
        assert CostProfile.from_settings() == CostProfile(
            commission_eur=1.0, cost_bps_equity=10.0, cost_bps_crypto=50.0, fractional_shares=False,
            min_trade_eur=100.0,
        )
        assert get_settings().lab_order_max_pending_sessions == 5
        for name, value in zip(COST_ENV, ("0.5", "12", "40", "true", "50", "3"), strict=True):
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        profile = CostProfile.from_settings()
        assert profile == CostProfile(
            commission_eur=0.5, cost_bps_equity=12.0, cost_bps_crypto=40.0, fractional_shares=True,
            min_trade_eur=50.0,
        )
        assert get_settings().lab_order_max_pending_sessions == 3
    finally:
        get_settings.cache_clear()

    assert COSTS.cost_rate("stock") == pytest.approx(0.001)
    assert COSTS.cost_rate("etf") == pytest.approx(0.001)
    assert COSTS.cost_rate("bond") == pytest.approx(0.001)
    assert COSTS.cost_rate("crypto") == pytest.approx(0.005)
    assert COSTS.allows_fraction("crypto") and not COSTS.allows_fraction("stock")
    assert profile.allows_fraction("etf")
    with pytest.raises(ValueError):
        CostProfile(commission_eur=-1.0, cost_bps_equity=10, cost_bps_crypto=50, fractional_shares=False,
                    min_trade_eur=100)
