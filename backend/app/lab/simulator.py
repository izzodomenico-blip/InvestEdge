"""Simulatore long-only all'apertura successiva, con costi Trade Republic e contabilita in EUR (spec SP1 §7).

Prezzi in ingresso gia in EUR (`open/high/low/close_eur` dei prezzi rettificati, spec §6.4) e `segment_id`
per barra. Una barra con un prezzo mancante, non finito o non positivo non si usa (come se mancasse).

Per ogni data *d* del calendario del portafoglio (unione dei calendari dei listing):

1. **Apertura.** Gli ordini pendenti degli asset con barra a *d* si eseguiscono all'`open_eur`, prima le vendite e
   poi gli acquisti (segnale decrescente, poi `asset_id`): acquisto a `open × (1 + costo)`, vendita a
   `open × (1 − costo)`, piu la commissione. L'acquisto spende l'importo deciso, limitato dalla cassa al netto
   della commissione; quote intere salvo frazioni ammesse; sotto l'ordine minimo non si esegue (annullato:
   `INSUFFICIENT_CASH` se la cassa era il vincolo, altrimenti `BELOW_MIN_TRADE`). Un ordine senza barra del
   listing attende; oltre `max_pending_sessions` sedute senza barra viene annullato (`PENDING_TIMEOUT`).
2. **Stop e take profit** sulla barra (anche quella d'ingresso: l'apertura precede massimo e minimo), con livelli
   dal prezzo medio di esecuzione in EUR (costo per lato incluso, commissione esclusa): `low <= stop` -> base
   `min(open, stop)`; `high >= tp` -> base `max(open, tp)`; entrambi -> stop. Poi costo per lato e commissione.
3. **Chiusura.** Se la barra valida successiva dell'asset e di un altro segmento, vendita `SEGMENT_EXIT` a
   `close × (1 − costo)`. Valutazione al `close_eur` (ultimo noto per gli asset senza barra a *d*).
4. **Decisione** alla prima data di un nuovo periodo di ribilanciamento (parametri attivi a *d*) con almeno un asset
   negoziabile (barra valida a *d*, non all'ultima barra del segmento): `target_weights` sugli asset negoziabili
   con segnale finito (Buy & hold: tutti), importi = peso × valore del portafoglio alla chiusura di *d*.
   Uscita totale sempre ammessa; acquisti e riduzioni sotto l'ordine minimo non vengono creati.

Motivi: `SIGNAL` apre o chiude una posizione, `REBALANCE` la ridimensiona. Il P&L di una vendita e netto:
incasso meno costo di carico (commissioni d'acquisto comprese). Nessun fill avviene sulla barra della decisione.
Gli ordini ancora pendenti alla fine del calendario non vengono eseguiti ne registrati; le posizioni aperte
restano valutate all'ultimo close.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import numpy as np
import pandas as pd

from backend.app.lab.contracts import PERIODS_PER_YEAR
from backend.app.lab.costs import CostProfile
from backend.app.lab.strategies import StrategyParams, rebalance_key, target_weights

Side = Literal["BUY", "SELL"]
TradeReason = Literal["SIGNAL", "REBALANCE", "STOP_LOSS", "TAKE_PROFIT", "SEGMENT_EXIT"]
PRICE_COLUMNS: tuple[str, ...] = ("open_eur", "high_eur", "low_eur", "close_eur")
EQUITY_COLUMNS: tuple[str, ...] = ("date", "value_eur", "cash_eur", "invested_eur", "drawdown")
_EMPTY_POSITION = 1e-12


@dataclass(frozen=True)
class AssetMarket:
    asset_id: int
    symbol: str
    asset_type: str
    bars: pd.DataFrame  # indice = data; open_eur, high_eur, low_eur, close_eur, segment_id


@dataclass(frozen=True)
class SimulationConfig:
    initial_cash_eur: float
    costs: CostProfile
    params_schedule: tuple[tuple[str, StrategyParams], ...]  # (data di inizio, parametri), ordinato
    stop_loss_percent: float | None
    take_profit_percent: float | None
    max_pending_sessions: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.initial_cash_eur) or self.initial_cash_eur <= 0:
            raise ValueError("Il capitale iniziale deve essere positivo.")
        starts = [start for start, _ in self.params_schedule]
        if not starts or any(previous >= current for previous, current in zip(starts, starts[1:], strict=False)):
            raise ValueError("Il calendario dei parametri deve avere date crescenti.")
        for level in (self.stop_loss_percent, self.take_profit_percent):
            if level is not None and (not math.isfinite(level) or level <= 0):
                raise ValueError("Stop loss e take profit devono essere positivi.")
        if self.max_pending_sessions < 0:
            raise ValueError("Le sedute di attesa di un ordine non possono essere negative.")


@dataclass(frozen=True)
class TradeRecord:
    date: str
    asset_id: int
    symbol: str
    side: Side
    quantity: float
    price_eur: float          # prezzo di esecuzione, costo per lato incluso
    commission_eur: float
    spread_cost_eur: float
    gross_eur: float          # quantita × prezzo di esecuzione
    net_eur: float            # movimento di cassa: lordo + commissione (acquisto), lordo − commissione (vendita)
    pnl_eur: float            # vendite: netto − costo di carico; acquisti: 0
    reason: TradeReason


@dataclass(frozen=True)
class SimulationResult:
    equity: pd.DataFrame      # date, value_eur, cash_eur, invested_eur, drawdown (percento <= 0 dal massimo)
    trades: tuple[TradeRecord, ...]
    # date, decision_date, asset_id, symbol, side, reason (PENDING_TIMEOUT, INSUFFICIENT_CASH, BELOW_MIN_TRADE)
    cancelled_orders: tuple[dict[str, Any], ...]
    daily_returns: pd.Series  # rendimenti del valore fra date consecutive del calendario
    costs: dict[str, float]   # commission_eur, spread_cost_eur
    turnover: float           # valore scambiato (acquisti + vendite) / valore medio del portafoglio
    exposure: float           # media di investito / valore


@dataclass
class _Lane:
    market: AssetMarket
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    usable: np.ndarray
    segment_end: np.ndarray
    signal: np.ndarray
    cost_rate: float
    fractional: bool


@dataclass
class _Position:
    quantity: float = 0.0
    cost_eur: float = 0.0     # costo di carico residuo, commissioni d'acquisto incluse
    entry_eur: float = 0.0    # prezzo medio di esecuzione: base di stop e take profit


@dataclass
class _Order:
    asset_id: int
    side: Side
    decision_date: str
    amount_eur: float
    quantity: float
    priority: float
    reason: TradeReason
    missed: int = 0


class _Book:
    def __init__(self, cash: float, costs: CostProfile) -> None:
        self.cash = cash
        self.costs = costs
        self.positions: dict[int, _Position] = {}
        self.trades: list[TradeRecord] = []
        self.commission = 0.0
        self.spread = 0.0
        self.traded = 0.0

    def buy(self, lane: _Lane, day: str, base: float, amount: float, reason: TradeReason) -> str | None:
        """Esegue l'acquisto; altrimenti il motivo dell'annullamento (cassa insufficiente o sotto il minimo)."""
        commission = self.costs.commission_eur
        price = base * (1 + lane.cost_rate)
        available = self.cash - commission
        failure = "INSUFFICIENT_CASH" if available < amount else "BELOW_MIN_TRADE"
        budget = min(amount, available)
        if budget <= 0:
            return failure
        quantity = budget / price
        if not lane.fractional:
            quantity = float(math.floor(quantity + 1e-9))
        gross = quantity * price
        if quantity <= 0 or gross < self.costs.min_trade_eur:
            return failure
        position = self.positions.setdefault(lane.market.asset_id, _Position())
        held = position.quantity
        position.entry_eur = (position.entry_eur * held + price * quantity) / (held + quantity)
        position.quantity = held + quantity
        position.cost_eur += gross + commission
        # Il budget non supera la cassa: un residuo negativo e solo arrotondamento (come `max(0, cassa)` di oggi).
        self.cash = max(0.0, self.cash - gross - commission)
        self._record(lane, day, "BUY", quantity, price, base, gross, gross + commission, 0.0, reason)
        return None

    def sell(self, lane: _Lane, day: str, base: float, quantity: float, reason: TradeReason) -> None:
        position = self.positions.get(lane.market.asset_id)
        if position is None:
            return
        quantity = min(quantity, position.quantity)
        if quantity <= 0:
            return
        commission = self.costs.commission_eur
        price = base * (1 - lane.cost_rate)
        gross = quantity * price
        net = gross - commission
        carried = position.cost_eur * (quantity / position.quantity)
        position.quantity -= quantity
        position.cost_eur -= carried
        if position.quantity <= _EMPTY_POSITION:
            del self.positions[lane.market.asset_id]
        self.cash += net
        self._record(lane, day, "SELL", quantity, price, base, gross, net, net - carried, reason)

    def _record(
        self,
        lane: _Lane,
        day: str,
        side: Side,
        quantity: float,
        price: float,
        base: float,
        gross: float,
        net: float,
        pnl: float,
        reason: TradeReason,
    ) -> None:
        commission = self.costs.commission_eur
        spread = quantity * base * lane.cost_rate
        self.commission += commission
        self.spread += spread
        self.traded += gross
        market = lane.market
        self.trades.append(
            TradeRecord(day, market.asset_id, market.symbol, side, quantity, price, commission, spread, gross, net,
                        pnl, reason)
        )


def simulate(
    markets: Mapping[int, AssetMarket],
    signals: pd.DataFrame,
    calendar: Sequence[str],
    config: SimulationConfig,
) -> SimulationResult:
    """Simulazione di un'unica sequenza di parametri (`params_schedule`) senza liquidazioni ai cambi.

    `calendar`, l'indice delle barre e l'indice di `signals` sono date `AAAA-MM-GG` in stringa (come
    `FeatureStore.signal_panel`); le colonne di `signals` sono gli `asset_id`. Date o asset mancanti valgono NaN.
    """
    days = [str(day) for day in calendar]
    if any(previous >= current for previous, current in zip(days, days[1:], strict=False)):
        raise ValueError("Il calendario deve avere date crescenti e uniche.")
    lanes = _lanes(markets, signals, days, config.costs)
    book = _Book(float(config.initial_cash_eur), config.costs)
    pending: list[_Order] = []
    cancelled: list[dict[str, Any]] = []
    last_close: dict[int, float] = {}
    rows: list[tuple[str, float, float, float, float]] = []
    peak = float(config.initial_cash_eur)
    last_key: str | None = None
    decided = False
    schedule = config.params_schedule
    active = -1

    for index, day in enumerate(days):
        while active + 1 < len(schedule) and schedule[active + 1][0] <= day:
            active += 1
        pending = _open(book, lanes, pending, index, day, config.max_pending_sessions, cancelled)
        _stops(book, lanes, index, day, config)
        for asset_id in sorted(book.positions):
            lane = lanes[asset_id]
            if lane.usable[index] and lane.segment_end[index]:
                book.sell(lane, day, lane.close[index], book.positions[asset_id].quantity, "SEGMENT_EXIT")
        for asset_id, lane in lanes.items():
            if lane.usable[index]:
                last_close[asset_id] = float(lane.close[index])
        invested = sum(position.quantity * last_close[asset_id] for asset_id, position in book.positions.items())
        value = book.cash + invested
        peak = max(peak, value)
        rows.append((day, value, book.cash, invested, (value / peak - 1) * 100))

        if active < 0 or value <= 0:
            continue
        params = schedule[active][1]
        key = rebalance_key(day, params.rebalance_frequency)
        tradable = [
            asset_id for asset_id, lane in lanes.items() if lane.usable[index] and not lane.segment_end[index]
        ]
        if key == last_key or not tradable:
            continue
        last_key = key
        pending.extend(_decide(book, lanes, params, tradable, index, day, value, first_rebalance=not decided))
        decided = True

    return _result(book, rows, cancelled)


def _lanes(
    markets: Mapping[int, AssetMarket], signals: pd.DataFrame, days: list[str], costs: CostProfile
) -> dict[int, _Lane]:
    calendar = pd.Index(days)
    ids = [market.asset_id for market in markets.values()]
    aligned = signals.reindex(index=calendar, columns=ids)
    lanes: dict[int, _Lane] = {}
    for market in markets.values():
        if not market.bars.index.is_unique:
            raise ValueError("Le barre di un asset devono avere date uniche.")
        bars = market.bars.reindex(calendar)
        prices = bars[list(PRICE_COLUMNS)].to_numpy(dtype=float)
        usable = np.isfinite(prices).all(axis=1)
        usable[usable] = (prices[usable] > 0).all(axis=1)
        segments = bars["segment_id"].to_numpy(dtype=float)
        positions = np.flatnonzero(usable)
        segment_end = np.zeros(len(days), dtype=bool)
        segment_end[positions[:-1]] = segments[positions[:-1]] != segments[positions[1:]]
        lanes[market.asset_id] = _Lane(
            market=market,
            open=prices[:, 0],
            high=prices[:, 1],
            low=prices[:, 2],
            close=prices[:, 3],
            usable=usable,
            segment_end=segment_end,
            signal=aligned[market.asset_id].to_numpy(dtype=float),
            cost_rate=costs.cost_rate(market.asset_type),
            fractional=costs.allows_fraction(market.asset_type),
        )
    return lanes


def _open(
    book: _Book,
    lanes: Mapping[int, _Lane],
    pending: list[_Order],
    index: int,
    day: str,
    max_pending_sessions: int,
    cancelled: list[dict[str, Any]],
) -> list[_Order]:
    waiting: list[_Order] = []
    executable: list[_Order] = []
    for order in pending:
        if lanes[order.asset_id].usable[index]:
            executable.append(order)
            continue
        order.missed += 1
        if order.missed > max_pending_sessions:
            cancelled.append(_cancelled(order, lanes, day, "PENDING_TIMEOUT"))
        else:
            waiting.append(order)
    for order in sorted((o for o in executable if o.side == "SELL"), key=lambda o: o.asset_id):
        lane = lanes[order.asset_id]
        book.sell(lane, day, lane.open[index], order.quantity, order.reason)
    for order in sorted((o for o in executable if o.side == "BUY"), key=lambda o: (-o.priority, o.asset_id)):
        lane = lanes[order.asset_id]
        failure = book.buy(lane, day, lane.open[index], order.amount_eur, order.reason)
        if failure is not None:
            cancelled.append(_cancelled(order, lanes, day, failure))
    return waiting


def _cancelled(order: _Order, lanes: Mapping[int, _Lane], day: str, reason: str) -> dict[str, Any]:
    return {
        "date": day,
        "decision_date": order.decision_date,
        "asset_id": order.asset_id,
        "symbol": lanes[order.asset_id].market.symbol,
        "side": order.side,
        "reason": reason,
    }


def _stops(book: _Book, lanes: Mapping[int, _Lane], index: int, day: str, config: SimulationConfig) -> None:
    if config.stop_loss_percent is None and config.take_profit_percent is None:
        return
    for asset_id in sorted(book.positions):
        lane = lanes[asset_id]
        if not lane.usable[index]:
            continue
        position = book.positions[asset_id]
        if config.stop_loss_percent is not None:
            stop = position.entry_eur * (1 - config.stop_loss_percent / 100)
            if lane.low[index] <= stop:
                book.sell(lane, day, min(lane.open[index], stop), position.quantity, "STOP_LOSS")
                continue
        if config.take_profit_percent is not None:
            take_profit = position.entry_eur * (1 + config.take_profit_percent / 100)
            if lane.high[index] >= take_profit:
                book.sell(lane, day, max(lane.open[index], take_profit), position.quantity, "TAKE_PROFIT")


def _decide(
    book: _Book,
    lanes: Mapping[int, _Lane],
    params: StrategyParams,
    tradable: list[int],
    index: int,
    day: str,
    value: float,
    *,
    first_rebalance: bool,
) -> list[_Order]:
    uses_signal = params.name != "BUY_AND_HOLD"
    signals = {
        asset_id: float(lanes[asset_id].signal[index])
        for asset_id in tradable
        if not uses_signal or math.isfinite(lanes[asset_id].signal[index])
    }
    current = {
        asset_id: book.positions[asset_id].quantity * lanes[asset_id].close[index] / value
        for asset_id in tradable
        if asset_id in book.positions
    }
    targets = target_weights(params, signals, current, first_rebalance=first_rebalance)
    if not targets:
        return []
    min_trade = book.costs.min_trade_eur
    orders: list[_Order] = []
    for asset_id, weight in sorted(targets.items()):
        if asset_id not in current and asset_id not in signals:
            continue
        lane = lanes[asset_id]
        close = float(lane.close[index])
        held = book.positions[asset_id].quantity if asset_id in book.positions else 0.0
        priority = signals.get(asset_id, -math.inf)
        priority = priority if math.isfinite(priority) else -math.inf
        if weight <= 0:
            if held > 0:
                orders.append(_Order(asset_id, "SELL", day, 0.0, held, priority, "SIGNAL"))
            continue
        delta = weight * value - held * close
        reason: TradeReason = "SIGNAL" if held == 0 else "REBALANCE"
        if delta > 0 and delta >= min_trade:
            orders.append(_Order(asset_id, "BUY", day, delta, 0.0, priority, reason))
        elif delta < 0:
            quantity = -delta / close
            if not lane.fractional:
                quantity = float(math.floor(quantity + 1e-9))
            if quantity > 0 and quantity * close >= min_trade:
                orders.append(_Order(asset_id, "SELL", day, 0.0, quantity, priority, "REBALANCE"))
    return orders


def _result(
    book: _Book, rows: list[tuple[str, float, float, float, float]], cancelled: list[dict[str, Any]]
) -> SimulationResult:
    equity = pd.DataFrame(rows, columns=list(EQUITY_COLUMNS))
    values = equity["value_eur"].to_numpy(dtype=float)
    returns = pd.Series(values[1:] / values[:-1] - 1, index=equity["date"].iloc[1:].to_list(), dtype=float)
    mean_value = float(values.mean()) if len(values) else 0.0
    exposure = float((equity["invested_eur"] / equity["value_eur"]).mean()) if len(values) else 0.0
    return SimulationResult(
        equity=equity,
        trades=tuple(book.trades),
        cancelled_orders=tuple(cancelled),
        daily_returns=returns,
        costs={"commission_eur": book.commission, "spread_cost_eur": book.spread},
        turnover=book.traded / mean_value if mean_value > 0 else 0.0,
        exposure=exposure,
    )


def compute_metrics(result: SimulationResult, initial_cash_eur: float) -> dict[str, float]:
    """Metriche in EUR (unita del motore attuale: percentuali per rendimenti, CAGR, drawdown e win rate).

    Sharpe annualizzato con tasso privo di rischio 0 (rendimenti giornalieri × √252); drawdown dal massimo
    raggiunto, capitale iniziale compreso; profit factor e win rate sulle vendite.
    """
    equity = result.equity
    values = equity["value_eur"].to_numpy(dtype=float)
    final = float(values[-1]) if len(values) else float(initial_cash_eur)
    days = 1
    if len(values):
        days = max((date.fromisoformat(str(equity["date"].iloc[-1])[:10])
                    - date.fromisoformat(str(equity["date"].iloc[0])[:10])).days, 1)
    years = days / 365.25
    growth = final / initial_cash_eur
    peaks = np.maximum.accumulate(np.r_[float(initial_cash_eur), values])[1:]
    drawdowns = (values / peaks - 1) * 100
    returns = result.daily_returns.to_numpy(dtype=float)
    sharpe = 0.0
    if len(returns) > 1:
        deviation = float(np.std(returns, ddof=1))
        if math.isfinite(deviation) and deviation > 0:
            sharpe = float(np.mean(returns)) / deviation * math.sqrt(PERIODS_PER_YEAR["D"])
    sells = [trade for trade in result.trades if trade.side == "SELL"]
    profit = sum(trade.pnl_eur for trade in sells if trade.pnl_eur > 0)
    loss = abs(sum(trade.pnl_eur for trade in sells if trade.pnl_eur < 0))
    wins = sum(1 for trade in sells if trade.pnl_eur > 0)
    return {
        "total_return_percent": (growth - 1) * 100,
        "cagr": (growth ** (1 / years) - 1) * 100 if growth > 0 else 0.0,
        "max_drawdown": min(0.0, float(drawdowns.min())) if len(drawdowns) else 0.0,
        "sharpe_ratio": sharpe,
        "profit_factor": profit / loss if loss > 0 else (999.0 if profit > 0 else 0.0),
        "win_rate": wins / len(sells) * 100 if sells else 0.0,
        "total_trades": len(result.trades),
        "turnover": result.turnover,
        "exposure": result.exposure,
        "commission_eur": result.costs.get("commission_eur", 0.0),
        "spread_cost_eur": result.costs.get("spread_cost_eur", 0.0),
    }
