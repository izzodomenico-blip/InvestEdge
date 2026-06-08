from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.app.models import (
    BacktestBenchmarkComparisonOut,
    BacktestCompareIn,
    BacktestEquityPointOut,
    BacktestNetAnalysisOut,
    BacktestPositionOut,
    BacktestResultOut,
    BacktestRunIn,
    BacktestSummaryOut,
    BacktestTradeOut,
    WalkForwardIn,
)
from backend.app.services.common import (
    SCORE_BUY,
    SCORE_HOLD,
    SCORE_REDUCE,
    SCORE_STRONG_BUY,
)
from backend.app.services.common import (
    now_local as _now,
)
from backend.app.services.common import (
    round_safe as _round,
)
from backend.app.services.technical_analysis import TechnicalAnalysisService


def _date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Data non valida: {value}.")
    return pd.Timestamp(parsed).normalize()


@dataclass
class _Position:
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0
    realized_pnl: float = 0.0

    def value(self, price: float) -> float:
        return self.quantity * price


STRATEGY_LABELS: dict[str, str] = {
    "SCORE_THRESHOLD": "Score threshold",
    "BUY_AND_HOLD": "Buy & hold",
    "TOP_N_SCORE": "Top N score",
}

# Modello fiscale/costi Italia (semplificato, per stima "netto in tasca")
TAX_RATE_STANDARD = 26.0      # azioni, ETF, cripto: 26% sulle plusvalenze realizzate
TAX_RATE_BONDS = 12.5         # titoli di Stato white-list ed ETF obbligazionari govt
STAMP_DUTY_ANNUAL = 0.2       # imposta di bollo titoli: 0.2% annuo sul controvalore
SLIPPAGE_PER_SIDE = 0.05      # slippage/spread stimato per lato, in percento
BOND_ASSET_TYPES = {"bond", "bond_etf"}


@dataclass
class BacktestEngine:
    """Local backtest engine for simulated strategies only."""

    technical_service: TechnicalAnalysisService = field(default_factory=TechnicalAnalysisService)

    def run_backtest(self, connection: sqlite3.Connection, config: BacktestRunIn) -> BacktestResultOut:
        symbols = self._normalize_symbols(config.symbols)
        start_date = _date(config.start_date)
        end_date = _date(config.end_date)
        if end_date < start_date:
            raise ValueError("La data fine deve essere successiva alla data inizio.")

        market_data = self._load_market_data(connection, symbols, end_date)
        if not market_data:
            raise ValueError("Database non inizializzato o storico prezzi non disponibile. Esegui il seed.")

        benchmark_symbol = config.benchmark_symbol.upper()
        benchmark_data = self._load_market_data(connection, [benchmark_symbol], end_date).get(benchmark_symbol)

        available_dates = self._available_dates(market_data, start_date, end_date)
        if not available_dates:
            raise ValueError("Nessun dato prezzo disponibile nel periodo richiesto.")

        state = self._simulate(config, symbols, market_data, available_dates)
        benchmark_curve = self._benchmark_curve(
            benchmark_symbol,
            benchmark_data,
            available_dates,
            config.initial_cash,
        )
        self._attach_benchmark(state["equity_curve"], benchmark_curve)

        summary = self._calculate_summary(config, state, available_dates, benchmark_curve)
        backtest_id = self._persist(connection, config, summary, state)
        return self.get_backtest(connection, backtest_id)

    def compare_strategies(self, connection: sqlite3.Connection, payload: BacktestCompareIn) -> dict[str, Any]:
        """Esegue piu strategie sullo stesso periodo/universo senza persistere i run."""
        symbols = self._normalize_symbols(payload.symbols)
        start_date = _date(payload.start_date)
        end_date = _date(payload.end_date)
        if end_date < start_date:
            raise ValueError("La data fine deve essere successiva alla data inizio.")

        strategy_names: list[str] = []
        for name in payload.strategy_names:
            if name not in strategy_names:
                strategy_names.append(name)
        if len(strategy_names) < 2:
            raise ValueError("Seleziona almeno due strategie diverse.")

        market_data = self._load_market_data(connection, symbols, end_date)
        if not market_data:
            raise ValueError("Database non inizializzato o storico prezzi non disponibile. Esegui il seed.")

        benchmark_symbol = payload.benchmark_symbol.upper()
        benchmark_data = self._load_market_data(connection, [benchmark_symbol], end_date).get(benchmark_symbol)

        available_dates = self._available_dates(market_data, start_date, end_date)
        if not available_dates:
            raise ValueError("Nessun dato prezzo disponibile nel periodo richiesto.")

        benchmark_curve = self._benchmark_curve(
            benchmark_symbol,
            benchmark_data,
            available_dates,
            payload.initial_cash,
        )

        entries: list[dict[str, Any]] = []
        for strategy_name in strategy_names:
            config = BacktestRunIn(
                name=f"{payload.name} - {strategy_name}",
                strategy_name=strategy_name,
                symbols=symbols,
                initial_cash=payload.initial_cash,
                start_date=payload.start_date,
                end_date=payload.end_date,
                benchmark_symbol=payload.benchmark_symbol,
                buy_threshold=payload.buy_threshold,
                sell_threshold=payload.sell_threshold,
                max_asset_weight=payload.max_asset_weight,
                fee_percent=payload.fee_percent,
                stop_loss_percent=payload.stop_loss_percent,
                take_profit_percent=payload.take_profit_percent,
                rebalance_frequency=payload.rebalance_frequency,
                top_n=payload.top_n,
            )
            state = self._simulate(config, symbols, market_data, available_dates)
            self._attach_benchmark(state["equity_curve"], benchmark_curve)
            summary = self._calculate_summary(config, state, available_dates, benchmark_curve)
            entries.append(
                {
                    "strategy_name": strategy_name,
                    "label": STRATEGY_LABELS.get(strategy_name, strategy_name),
                    "summary": summary,
                    "equity_curve": state["equity_curve"],
                }
            )

        ranked = sorted(entries, key=lambda item: item["summary"].total_return_percent, reverse=True)
        for position, entry in enumerate(ranked, start=1):
            entry["rank"] = position

        benchmark_return = ranked[0]["summary"].benchmark_return_percent if ranked else 0.0
        return {
            "name": payload.name,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "benchmark_symbol": benchmark_symbol,
            "benchmark_return_percent": benchmark_return,
            "best_strategy": ranked[0]["strategy_name"] if ranked else "",
            "entries": entries,
        }

    def walk_forward(self, connection: sqlite3.Connection, payload: WalkForwardIn) -> dict[str, Any]:
        """Validazione out-of-sample: divide il periodo in N fold consecutivi e
        misura la consistenza della strategia su ciascun sottoperiodo indipendente.
        Smaschera il rischio che il rendimento dipenda da una sola finestra fortunata."""
        symbols = self._normalize_symbols(payload.symbols)
        start_date = _date(payload.start_date)
        end_date = _date(payload.end_date)
        if end_date < start_date:
            raise ValueError("La data fine deve essere successiva alla data inizio.")

        market_data = self._load_market_data(connection, symbols, end_date)
        if not market_data:
            raise ValueError("Database non inizializzato o storico prezzi non disponibile. Esegui il seed.")

        benchmark_symbol = payload.benchmark_symbol.upper()
        benchmark_data = self._load_market_data(connection, [benchmark_symbol], end_date).get(benchmark_symbol)

        available_dates = self._available_dates(market_data, start_date, end_date)
        if len(available_dates) < payload.folds * 2:
            raise ValueError("Periodo troppo corto per il numero di fold richiesto.")

        full_summary = self._summary_for_dates(payload, symbols, market_data, benchmark_data, available_dates)

        fold_size = len(available_dates) // payload.folds
        fold_results: list[dict[str, Any]] = []
        for index in range(payload.folds):
            start_idx = index * fold_size
            end_idx = len(available_dates) if index == payload.folds - 1 else (index + 1) * fold_size
            fold_dates = available_dates[start_idx:end_idx]
            if len(fold_dates) < 2:
                continue
            summary = self._summary_for_dates(payload, symbols, market_data, benchmark_data, fold_dates)
            fold_results.append(
                {
                    "fold": index + 1,
                    "start_date": summary.start_date,
                    "end_date": summary.end_date,
                    "total_return_percent": summary.total_return_percent,
                    "cagr": summary.cagr,
                    "max_drawdown": summary.max_drawdown,
                    "sharpe_ratio": summary.sharpe_ratio,
                    "alpha_vs_benchmark": summary.alpha_vs_benchmark,
                    "total_trades": summary.total_trades,
                    "final_value": summary.final_value,
                }
            )

        returns = [item["total_return_percent"] for item in fold_results]
        alphas = [item["alpha_vs_benchmark"] for item in fold_results]
        positive = sum(1 for value in returns if value > 0)
        beating = sum(1 for value in alphas if value > 0)
        count = len(fold_results)
        mean_return = statistics.fmean(returns) if returns else 0.0
        median_return = statistics.median(returns) if returns else 0.0
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0.0
        mean_alpha = statistics.fmean(alphas) if alphas else 0.0

        positive_ratio = positive / count if count else 0.0
        beating_ratio = beating / count if count else 0.0
        consistency, verdict = self._consistency_verdict(
            positive_ratio, beating_ratio, mean_return, mean_alpha, count
        )

        return {
            "strategy_name": payload.strategy_name,
            "folds": count,
            "full_period_return_percent": full_summary.total_return_percent,
            "mean_return_percent": _round(mean_return, 2),
            "median_return_percent": _round(median_return, 2),
            "std_return_percent": _round(std_return, 2),
            "positive_folds": positive,
            "folds_beating_benchmark": beating,
            "worst_fold_return_percent": _round(min(returns), 2) if returns else 0.0,
            "best_fold_return_percent": _round(max(returns), 2) if returns else 0.0,
            "mean_alpha_vs_benchmark": _round(mean_alpha, 2),
            "consistency": consistency,
            "verdict": verdict,
            "fold_results": fold_results,
        }

    def _summary_for_dates(
        self,
        config: BacktestRunIn,
        symbols: list[str],
        market_data: dict[str, pd.DataFrame],
        benchmark_data: pd.DataFrame | None,
        dates: list[pd.Timestamp],
    ) -> BacktestSummaryOut:
        state = self._simulate(config, symbols, market_data, dates)
        benchmark_curve = self._benchmark_curve(
            config.benchmark_symbol.upper(), benchmark_data, dates, config.initial_cash
        )
        self._attach_benchmark(state["equity_curve"], benchmark_curve)
        return self._calculate_summary(config, state, dates, benchmark_curve)

    def _consistency_verdict(
        self,
        positive_ratio: float,
        beating_ratio: float,
        mean_return: float,
        mean_alpha: float,
        count: int,
    ) -> tuple[str, str]:
        if count == 0:
            return "FRAGILE", "Nessun fold valutabile."
        if positive_ratio >= 0.7 and mean_alpha > 0:
            return (
                "ROBUSTA",
                f"Positiva in {positive_ratio * 100:.0f}% dei periodi con alpha medio {mean_alpha:+.1f}%. "
                "Comportamento consistente, ma resta una simulazione: nessuna garanzia sul futuro.",
            )
        if positive_ratio <= 0.4 or mean_return <= 0:
            return (
                "FRAGILE",
                f"Positiva solo nel {positive_ratio * 100:.0f}% dei periodi (rendimento medio {mean_return:+.1f}%). "
                "Il risultato sull'intero periodo dipende probabilmente da poche finestre fortunate: alto rischio di overfitting.",
            )
        return (
            "INCERTA",
            f"Positiva nel {positive_ratio * 100:.0f}% dei periodi, batte il benchmark nel {beating_ratio * 100:.0f}%. "
            "Segnali misti: non affidarti a questa strategia senza ulteriori verifiche.",
        )

    def prepare_price_frame_for_backtest(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Precompute rolling indicators and score rows without using future values."""
        frame = self.technical_service.enrich_price_history(prices)
        if frame.empty:
            return frame

        frame["rolling_score"] = frame.apply(self._score_row, axis=1)
        # Bins derivati dalle soglie condivise: ogni soglia e estremo destro escluso (epsilon).
        eps = 0.001
        frame["rolling_signal"] = pd.cut(
            frame["rolling_score"],
            bins=[
                -1,
                SCORE_REDUCE - eps,
                SCORE_HOLD - eps,
                SCORE_BUY - eps,
                SCORE_STRONG_BUY - eps,
                101,
            ],
            labels=["SELL", "REDUCE", "HOLD", "BUY", "STRONG_BUY"],
        ).astype(str)
        return frame

    def list_backtests(self, connection: sqlite3.Connection) -> list[BacktestSummaryOut]:
        rows = connection.execute(
            """
            SELECT *
            FROM backtest_runs
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        return [self._summary_from_row(row) for row in rows]

    def get_backtest(self, connection: sqlite3.Connection, backtest_id: int) -> BacktestResultOut:
        run = connection.execute("SELECT * FROM backtest_runs WHERE id = ?", (backtest_id,)).fetchone()
        if run is None:
            raise ValueError("Backtest non trovato.")

        equity_rows = connection.execute(
            """
            SELECT *
            FROM backtest_equity_curve
            WHERE backtest_id = ?
            ORDER BY date ASC, id ASC
            """,
            (backtest_id,),
        ).fetchall()
        trade_rows = connection.execute(
            """
            SELECT *
            FROM backtest_trades
            WHERE backtest_id = ?
            ORDER BY date ASC, id ASC
            """,
            (backtest_id,),
        ).fetchall()
        position_rows = connection.execute(
            """
            SELECT *
            FROM backtest_positions
            WHERE backtest_id = ?
            ORDER BY final_value DESC, symbol ASC
            """,
            (backtest_id,),
        ).fetchall()

        summary = self._summary_from_row(run)
        equity_curve = [
            BacktestEquityPointOut(
                id=row["id"],
                date=row["date"],
                portfolio_value=_round(row["portfolio_value"]),
                cash=_round(row["cash"]),
                invested_value=_round(row["invested_value"]),
                drawdown_percent=_round(row["drawdown_percent"]),
            )
            for row in equity_rows
        ]
        self._hydrate_benchmark_from_run(connection, summary, equity_curve)

        benchmark_final = summary.initial_cash * (1 + (summary.benchmark_return_percent / 100))
        trades = [self._trade_from_row(row) for row in trade_rows]
        return BacktestResultOut(
            backtest_id=backtest_id,
            summary=summary,
            equity_curve=equity_curve,
            trades=trades,
            final_positions=[self._position_from_row(row) for row in position_rows],
            benchmark_comparison=BacktestBenchmarkComparisonOut(
                benchmark_symbol=summary.benchmark_symbol,
                benchmark_return_percent=summary.benchmark_return_percent,
                alpha_vs_benchmark=summary.alpha_vs_benchmark,
                benchmark_final_value=_round(benchmark_final),
            ),
            net_analysis=BacktestNetAnalysisOut(
                **self._net_analysis(connection, summary, trades, equity_curve)
            ),
        )

    def delete_backtest(self, connection: sqlite3.Connection, backtest_id: int) -> bool:
        cursor = connection.execute("DELETE FROM backtest_runs WHERE id = ?", (backtest_id,))
        return cursor.rowcount > 0

    def _normalize_symbols(self, symbols: list[str]) -> list[str]:
        normalized: list[str] = []
        for symbol in symbols:
            clean = symbol.strip().upper()
            if clean and clean not in normalized:
                normalized.append(clean)
        if not normalized:
            raise ValueError("Seleziona almeno un asset.")
        return normalized

    def _load_market_data(
        self,
        connection: sqlite3.Connection,
        symbols: list[str],
        end_date: pd.Timestamp,
    ) -> dict[str, pd.DataFrame]:
        placeholders = ",".join("?" for _ in symbols)
        if not placeholders:
            return {}
        rows = connection.execute(
            f"""
            SELECT a.symbol, ph.date, ph.open, ph.high, ph.low, ph.close, ph.adjusted_close, ph.volume
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE UPPER(a.symbol) IN ({placeholders}) AND ph.date <= ?
            ORDER BY a.symbol, ph.date ASC
            """,
            [*symbols, end_date.strftime("%Y-%m-%d")],
        ).fetchall()
        if not rows:
            return {}

        raw = pd.DataFrame([dict(row) for row in rows])
        result: dict[str, pd.DataFrame] = {}
        for symbol, group in raw.groupby("symbol"):
            prepared = self.prepare_price_frame_for_backtest(group.drop(columns=["symbol"]))
            if not prepared.empty:
                prepared["date_ts"] = pd.to_datetime(prepared["date"])
                result[str(symbol).upper()] = prepared
        return result

    def _available_dates(
        self,
        market_data: dict[str, pd.DataFrame],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> list[pd.Timestamp]:
        dates: set[pd.Timestamp] = set()
        for frame in market_data.values():
            filtered = frame[(frame["date_ts"] >= start_date) & (frame["date_ts"] <= end_date)]
            dates.update(pd.Timestamp(value).normalize() for value in filtered["date_ts"])
        return sorted(dates)

    def _simulate(
        self,
        config: BacktestRunIn,
        symbols: list[str],
        market_data: dict[str, pd.DataFrame],
        dates: list[pd.Timestamp],
    ) -> dict[str, Any]:
        positions: dict[str, _Position] = {}
        cash = float(config.initial_cash)
        trades: list[BacktestTradeOut] = []
        equity_curve: list[BacktestEquityPointOut] = []
        latest_rows: dict[str, pd.Series] = {}
        record_index = dict.fromkeys(symbols, 0)
        records = {symbol: frame.to_dict("records") for symbol, frame in market_data.items() if symbol in symbols}
        peak_value = float(config.initial_cash)
        last_rebalance_key: str | None = None

        for current_date in dates:
            for symbol in symbols:
                symbol_records = records.get(symbol, [])
                index = record_index.get(symbol, 0)
                while index < len(symbol_records) and pd.Timestamp(symbol_records[index]["date_ts"]).normalize() <= current_date:
                    latest_rows[symbol] = pd.Series(symbol_records[index])
                    index += 1
                record_index[symbol] = index

            self._apply_stops(config, current_date, positions, latest_rows, trades, cash_holder := {"cash": cash})
            cash = cash_holder["cash"]

            rebalance_key = self._rebalance_key(current_date, config.rebalance_frequency)
            if rebalance_key != last_rebalance_key:
                if config.strategy_name == "BUY_AND_HOLD" and last_rebalance_key is None:
                    cash = self._buy_and_hold(config, current_date, symbols, positions, latest_rows, trades, cash)
                elif config.strategy_name == "SCORE_THRESHOLD":
                    cash = self._score_threshold(config, current_date, symbols, positions, latest_rows, trades, cash)
                elif config.strategy_name == "TOP_N_SCORE":
                    cash = self._top_n_score(config, current_date, symbols, positions, latest_rows, trades, cash)
                last_rebalance_key = rebalance_key

            invested_value = self._invested_value(positions, latest_rows)
            portfolio_value = cash + invested_value
            peak_value = max(peak_value, portfolio_value)
            drawdown = ((portfolio_value / peak_value) - 1) * 100 if peak_value > 0 else 0.0
            equity_curve.append(
                BacktestEquityPointOut(
                    date=current_date.strftime("%Y-%m-%d"),
                    portfolio_value=_round(portfolio_value),
                    cash=_round(cash),
                    invested_value=_round(invested_value),
                    drawdown_percent=_round(drawdown),
                )
            )

        final_positions = self._final_positions(positions, latest_rows)
        return {
            "cash": cash,
            "positions": positions,
            "trades": trades,
            "equity_curve": equity_curve,
            "final_positions": final_positions,
        }

    def _score_row(self, row: pd.Series) -> float:
        score = 50.0
        close = row.get("close")
        sma_50 = row.get("sma_50")
        sma_200 = row.get("sma_200")
        rsi = row.get("rsi_14")
        macd = row.get("macd_line")
        macd_signal = row.get("macd_signal")
        volatility = row.get("volatility_annualized_30d")
        drawdown = row.get("max_drawdown")

        if pd.notna(sma_50):
            score += 10 if close > sma_50 else -10
        if pd.notna(sma_200):
            score += 12 if close > sma_200 else -12
        if pd.notna(sma_50) and pd.notna(sma_200):
            score += 8 if sma_50 > sma_200 else -8
        if pd.notna(rsi):
            if 45 <= rsi <= 65:
                score += 10
            elif 35 <= rsi < 45 or 65 < rsi <= 72:
                score += 4
            elif rsi > 78:
                score -= 12
            elif rsi < 30:
                score -= 6
        if pd.notna(macd) and pd.notna(macd_signal):
            score += 8 if macd > macd_signal else -8
        if pd.notna(volatility):
            if volatility < 0.18:
                score += 5
            elif volatility > 0.45:
                score -= 10
        if pd.notna(drawdown) and drawdown < -0.25:
            score -= 8
        return _round(min(100, max(0, score)), 2)

    def _rebalance_key(self, current_date: pd.Timestamp, frequency: str) -> str:
        if frequency == "DAILY":
            return current_date.strftime("%Y-%m-%d")
        if frequency == "MONTHLY":
            return current_date.strftime("%Y-%m")
        iso = current_date.isocalendar()
        return f"{iso.year}-{iso.week}"

    def _row_price(self, rows: dict[str, pd.Series], symbol: str) -> float | None:
        row = rows.get(symbol)
        if row is None or pd.isna(row.get("close")):
            return None
        return float(row["close"])

    def _row_score(self, rows: dict[str, pd.Series], symbol: str) -> float | None:
        row = rows.get(symbol)
        if row is None or pd.isna(row.get("rolling_score")):
            return None
        return float(row["rolling_score"])

    def _portfolio_value(
        self,
        cash: float,
        positions: dict[str, _Position],
        rows: dict[str, pd.Series],
    ) -> float:
        return cash + self._invested_value(positions, rows)

    def _invested_value(self, positions: dict[str, _Position], rows: dict[str, pd.Series]) -> float:
        total = 0.0
        for symbol, position in positions.items():
            price = self._row_price(rows, symbol)
            if price is not None and position.quantity > 0:
                total += position.value(price)
        return total

    def _apply_stops(
        self,
        config: BacktestRunIn,
        current_date: pd.Timestamp,
        positions: dict[str, _Position],
        rows: dict[str, pd.Series],
        trades: list[BacktestTradeOut],
        cash_holder: dict[str, float],
    ) -> None:
        for symbol, position in list(positions.items()):
            price = self._row_price(rows, symbol)
            if price is None or position.quantity <= 0:
                continue
            if config.stop_loss_percent and price <= position.average_price * (1 - config.stop_loss_percent / 100):
                cash_holder["cash"] = self._sell(
                    config,
                    current_date,
                    symbol,
                    position.quantity,
                    price,
                    "Stop loss",
                    positions,
                    trades,
                    cash_holder["cash"],
                )
            elif config.take_profit_percent and price >= position.average_price * (1 + config.take_profit_percent / 100):
                cash_holder["cash"] = self._sell(
                    config,
                    current_date,
                    symbol,
                    position.quantity,
                    price,
                    "Take profit",
                    positions,
                    trades,
                    cash_holder["cash"],
                )

    def _buy_and_hold(
        self,
        config: BacktestRunIn,
        current_date: pd.Timestamp,
        symbols: list[str],
        positions: dict[str, _Position],
        rows: dict[str, pd.Series],
        trades: list[BacktestTradeOut],
        cash: float,
    ) -> float:
        target_weight = min(config.max_asset_weight, 1 / max(len(symbols), 1))
        portfolio_value = self._portfolio_value(cash, positions, rows)
        for symbol in symbols:
            price = self._row_price(rows, symbol)
            if price is None:
                continue
            target_amount = portfolio_value * target_weight
            cash = self._buy(config, current_date, symbol, target_amount, price, "Buy and hold entry", positions, trades, cash)
        return cash

    def _score_threshold(
        self,
        config: BacktestRunIn,
        current_date: pd.Timestamp,
        symbols: list[str],
        positions: dict[str, _Position],
        rows: dict[str, pd.Series],
        trades: list[BacktestTradeOut],
        cash: float,
    ) -> float:
        for symbol, position in list(positions.items()):
            score = self._row_score(rows, symbol)
            price = self._row_price(rows, symbol)
            if score is not None and price is not None and score <= config.sell_threshold:
                cash = self._sell(config, current_date, symbol, position.quantity, price, f"Score {score:.1f} <= sell threshold", positions, trades, cash)

        candidates = []
        for symbol in symbols:
            score = self._row_score(rows, symbol)
            price = self._row_price(rows, symbol)
            if score is not None and price is not None and score >= config.buy_threshold:
                candidates.append((symbol, score, price))
        candidates.sort(key=lambda item: item[1], reverse=True)

        for symbol, score, price in candidates:
            portfolio_value = self._portfolio_value(cash, positions, rows)
            current_value = positions.get(symbol, _Position(symbol)).value(price)
            target_amount = max(0.0, (portfolio_value * config.max_asset_weight) - current_value)
            cash = self._buy(config, current_date, symbol, target_amount, price, f"Score {score:.1f} >= buy threshold", positions, trades, cash)
        return cash

    def _top_n_score(
        self,
        config: BacktestRunIn,
        current_date: pd.Timestamp,
        symbols: list[str],
        positions: dict[str, _Position],
        rows: dict[str, pd.Series],
        trades: list[BacktestTradeOut],
        cash: float,
    ) -> float:
        scored = [
            (symbol, score, self._row_price(rows, symbol))
            for symbol in symbols
            if (score := self._row_score(rows, symbol)) is not None and self._row_price(rows, symbol) is not None
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        selected = scored[: max(1, config.top_n or 5)]
        selected_symbols = {symbol for symbol, _, _ in selected}

        for symbol, position in list(positions.items()):
            price = self._row_price(rows, symbol)
            if price is not None and symbol not in selected_symbols:
                cash = self._sell(config, current_date, symbol, position.quantity, price, "Removed from TOP_N selection", positions, trades, cash)

        target_weight = min(config.max_asset_weight, 1 / max(len(selected), 1))
        for symbol, score, price in selected:
            if price is None:
                continue
            portfolio_value = self._portfolio_value(cash, positions, rows)
            target_value = portfolio_value * target_weight
            current_value = positions.get(symbol, _Position(symbol)).value(price)
            if current_value > target_value * 1.05:
                excess_value = current_value - target_value
                cash = self._sell(config, current_date, symbol, excess_value / price, price, "Rebalance down to TOP_N target", positions, trades, cash)
            else:
                cash = self._buy(config, current_date, symbol, target_value - current_value, price, f"TOP_N score {score:.1f}", positions, trades, cash)
        return cash

    def _buy(
        self,
        config: BacktestRunIn,
        current_date: pd.Timestamp,
        symbol: str,
        target_amount: float,
        price: float,
        reason: str,
        positions: dict[str, _Position],
        trades: list[BacktestTradeOut],
        cash: float,
    ) -> float:
        if target_amount <= 0 or cash <= 0 or price <= 0:
            return cash
        spend = min(target_amount, cash)
        fees = spend * (config.fee_percent / 100)
        gross_amount = max(0.0, spend - fees)
        if gross_amount <= 0:
            return cash
        quantity = gross_amount / price
        position = positions.setdefault(symbol, _Position(symbol=symbol))
        old_cost = position.average_price * position.quantity
        new_quantity = position.quantity + quantity
        position.average_price = (old_cost + gross_amount + fees) / new_quantity if new_quantity > 0 else 0.0
        position.quantity = new_quantity
        cash -= gross_amount + fees
        trades.append(
            BacktestTradeOut(
                date=current_date.strftime("%Y-%m-%d"),
                symbol=symbol,
                order_type="BUY",
                quantity=_round(quantity),
                price=_round(price),
                fees=_round(fees),
                gross_amount=_round(gross_amount),
                net_amount=_round(gross_amount + fees),
                pnl=0,
                reason=reason,
            )
        )
        return max(0.0, cash)

    def _sell(
        self,
        config: BacktestRunIn,
        current_date: pd.Timestamp,
        symbol: str,
        quantity: float,
        price: float,
        reason: str,
        positions: dict[str, _Position],
        trades: list[BacktestTradeOut],
        cash: float,
    ) -> float:
        position = positions.get(symbol)
        if position is None or position.quantity <= 0 or price <= 0:
            return cash
        sell_quantity = min(quantity, position.quantity)
        gross_amount = sell_quantity * price
        fees = gross_amount * (config.fee_percent / 100)
        net_amount = gross_amount - fees
        pnl = ((price - position.average_price) * sell_quantity) - fees
        position.quantity -= sell_quantity
        position.realized_pnl += pnl
        if position.quantity <= 1e-9:
            position.quantity = 0.0
        cash += net_amount
        trades.append(
            BacktestTradeOut(
                date=current_date.strftime("%Y-%m-%d"),
                symbol=symbol,
                order_type="SELL",
                quantity=_round(sell_quantity),
                price=_round(price),
                fees=_round(fees),
                gross_amount=_round(gross_amount),
                net_amount=_round(net_amount),
                pnl=_round(pnl),
                reason=reason,
            )
        )
        return cash

    def _final_positions(
        self,
        positions: dict[str, _Position],
        rows: dict[str, pd.Series],
    ) -> list[BacktestPositionOut]:
        result: list[BacktestPositionOut] = []
        for symbol, position in positions.items():
            price = self._row_price(rows, symbol) or 0.0
            final_value = position.quantity * price
            unrealized = (price - position.average_price) * position.quantity if position.quantity > 0 else 0.0
            result.append(
                BacktestPositionOut(
                    symbol=symbol,
                    quantity=_round(position.quantity),
                    average_price=_round(position.average_price),
                    final_price=_round(price),
                    final_value=_round(final_value),
                    realized_pnl=_round(position.realized_pnl),
                    unrealized_pnl=_round(unrealized),
                )
            )
        return sorted(result, key=lambda item: item.final_value, reverse=True)

    def _benchmark_curve(
        self,
        symbol: str,
        frame: pd.DataFrame | None,
        dates: list[pd.Timestamp],
        initial_cash: float,
    ) -> dict[str, dict[str, float]]:
        if frame is None or frame.empty:
            return {}
        rows = frame.to_dict("records")
        index = 0
        latest_price: float | None = None
        first_price: float | None = None
        curve: dict[str, dict[str, float]] = {}
        for current_date in dates:
            while index < len(rows) and pd.Timestamp(rows[index]["date_ts"]).normalize() <= current_date:
                latest_price = float(rows[index]["close"])
                index += 1
            if latest_price is None:
                continue
            if first_price is None:
                first_price = latest_price
            return_percent = ((latest_price / first_price) - 1) * 100 if first_price else 0.0
            curve[current_date.strftime("%Y-%m-%d")] = {
                "benchmark_value": initial_cash * (1 + return_percent / 100),
                "benchmark_return_percent": return_percent,
            }
        return curve

    def _attach_benchmark(
        self,
        equity_curve: list[BacktestEquityPointOut],
        benchmark_curve: dict[str, dict[str, float]],
    ) -> None:
        for point in equity_curve:
            benchmark = benchmark_curve.get(point.date)
            if benchmark:
                point.benchmark_value = _round(benchmark["benchmark_value"])
                point.benchmark_return_percent = _round(benchmark["benchmark_return_percent"])

    def _calculate_summary(
        self,
        config: BacktestRunIn,
        state: dict[str, Any],
        dates: list[pd.Timestamp],
        benchmark_curve: dict[str, dict[str, float]],
    ) -> BacktestSummaryOut:
        equity_curve: list[BacktestEquityPointOut] = state["equity_curve"]
        final_value = equity_curve[-1].portfolio_value if equity_curve else config.initial_cash
        total_return = ((final_value / config.initial_cash) - 1) * 100
        days = max((dates[-1] - dates[0]).days, 1)
        years = days / 365.25
        cagr = ((final_value / config.initial_cash) ** (1 / years) - 1) * 100 if years > 0 and final_value > 0 else 0.0
        returns = pd.Series([point.portfolio_value for point in equity_curve]).pct_change().dropna()
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if len(returns) > 1 and returns.std() not in (0, np.nan) else 0.0
        sell_trades = [trade for trade in state["trades"] if trade.order_type == "SELL"]
        wins = [trade for trade in sell_trades if trade.pnl > 0]
        losses = [trade for trade in sell_trades if trade.pnl < 0]
        gross_profit = sum(trade.pnl for trade in wins)
        gross_loss = abs(sum(trade.pnl for trade in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        benchmark_return = 0.0
        if benchmark_curve:
            benchmark_return = list(benchmark_curve.values())[-1]["benchmark_return_percent"]

        return BacktestSummaryOut(
            name=config.name,
            strategy_name=config.strategy_name,
            initial_cash=_round(config.initial_cash),
            start_date=dates[0].strftime("%Y-%m-%d"),
            end_date=dates[-1].strftime("%Y-%m-%d"),
            benchmark_symbol=config.benchmark_symbol.upper(),
            buy_threshold=_round(config.buy_threshold),
            sell_threshold=_round(config.sell_threshold),
            max_asset_weight=_round(config.max_asset_weight),
            fee_percent=_round(config.fee_percent),
            stop_loss_percent=_round(config.stop_loss_percent) if config.stop_loss_percent is not None else None,
            take_profit_percent=_round(config.take_profit_percent) if config.take_profit_percent is not None else None,
            rebalance_frequency=config.rebalance_frequency,
            total_return_percent=_round(total_return),
            cagr=_round(cagr),
            max_drawdown=_round(min((point.drawdown_percent for point in equity_curve), default=0.0)),
            sharpe_ratio=_round(sharpe),
            win_rate=_round((len(wins) / len(sell_trades)) * 100 if sell_trades else 0.0),
            profit_factor=_round(profit_factor),
            total_trades=len(state["trades"]),
            final_value=_round(final_value),
            benchmark_return_percent=_round(benchmark_return),
            alpha_vs_benchmark=_round(total_return - benchmark_return),
        )

    def _net_analysis(
        self,
        connection: sqlite3.Connection,
        summary: BacktestSummaryOut,
        trades: list[BacktestTradeOut],
        equity_curve: list[BacktestEquityPointOut],
    ) -> dict[str, Any]:
        """Stima netta in tasca: tasse italiane sulle plusvalenze realizzate,
        slippage/spread e imposta di bollo. Semplificazioni: compensazione perdite
        solo entro la stessa classe (standard vs obbligazionario), bollo su controvalore
        medio, slippage stimato per lato. Le plusvalenze NON realizzate non sono tassate."""
        type_rows = connection.execute("SELECT UPPER(symbol) AS symbol, asset_type FROM assets").fetchall()
        type_map = {row["symbol"]: row["asset_type"] for row in type_rows}

        gain_standard = 0.0
        gain_bonds = 0.0
        commission = 0.0
        slippage = 0.0
        for trade in trades:
            commission += float(trade.fees)
            slippage += abs(float(trade.gross_amount)) * (SLIPPAGE_PER_SIDE / 100)
            if trade.order_type == "SELL":
                asset_type = type_map.get(trade.symbol.upper(), "stock")
                if asset_type in BOND_ASSET_TYPES:
                    gain_bonds += float(trade.pnl)
                else:
                    gain_standard += float(trade.pnl)

        taxable_standard = max(0.0, gain_standard)
        taxable_bonds = max(0.0, gain_bonds)
        taxable_total = taxable_standard + taxable_bonds
        capital_gains_tax = taxable_standard * (TAX_RATE_STANDARD / 100) + taxable_bonds * (TAX_RATE_BONDS / 100)

        mean_equity = (
            sum(point.portfolio_value for point in equity_curve) / len(equity_curve)
            if equity_curve
            else summary.final_value
        )
        years = max((_date(summary.end_date) - _date(summary.start_date)).days, 1) / 365.25
        stamp_duty = mean_equity * (STAMP_DUTY_ANNUAL / 100) * years

        initial = summary.initial_cash
        final_value = summary.final_value
        net_final = final_value - capital_gains_tax - slippage - stamp_duty
        net_return = ((net_final / initial) - 1) * 100 if initial > 0 else 0.0
        effective_rate = (capital_gains_tax / taxable_total * 100) if taxable_total > 0 else 0.0

        notes = [
            "Tasse stimate sulle sole plusvalenze realizzate (26% standard, 12,5% titoli di Stato/ETF govt).",
            "Le plusvalenze non realizzate sulle posizioni finali non sono tassate.",
            f"Slippage stimato {SLIPPAGE_PER_SIDE:.2f}% per operazione, bollo {STAMP_DUTY_ANNUAL:.1f}% annuo sul controvalore medio.",
            "Commissioni gia incluse nel valore finale lordo; qui mostrate solo per trasparenza.",
        ]

        return {
            "gross_return_percent": summary.total_return_percent,
            "gross_profit": _round(final_value - initial, 2),
            "commission_costs": _round(commission, 2),
            "slippage_costs": _round(slippage, 2),
            "realized_gains_taxable": _round(taxable_total, 2),
            "capital_gains_tax": _round(capital_gains_tax, 2),
            "stamp_duty": _round(stamp_duty, 2),
            "total_costs_and_taxes": _round(capital_gains_tax + slippage + stamp_duty, 2),
            "net_final_value": _round(net_final, 2),
            "net_return_percent": _round(net_return, 2),
            "effective_tax_rate_percent": _round(effective_rate, 2),
            "notes": notes,
        }

    def _persist(
        self,
        connection: sqlite3.Connection,
        config: BacktestRunIn,
        summary: BacktestSummaryOut,
        state: dict[str, Any],
    ) -> int:
        now = _now()
        cursor = connection.execute(
            """
            INSERT INTO backtest_runs (
                name, strategy_name, initial_cash, start_date, end_date, benchmark_symbol,
                buy_threshold, sell_threshold, max_asset_weight, fee_percent, stop_loss_percent,
                take_profit_percent, rebalance_frequency, total_return_percent, cagr, max_drawdown,
                sharpe_ratio, win_rate, profit_factor, total_trades, final_value,
                benchmark_return_percent, alpha_vs_benchmark, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config.name,
                config.strategy_name,
                config.initial_cash,
                summary.start_date,
                summary.end_date,
                config.benchmark_symbol.upper(),
                config.buy_threshold,
                config.sell_threshold,
                config.max_asset_weight,
                config.fee_percent,
                config.stop_loss_percent,
                config.take_profit_percent,
                config.rebalance_frequency,
                summary.total_return_percent,
                summary.cagr,
                summary.max_drawdown,
                summary.sharpe_ratio,
                summary.win_rate,
                summary.profit_factor,
                summary.total_trades,
                summary.final_value,
                summary.benchmark_return_percent,
                summary.alpha_vs_benchmark,
                now,
            ),
        )
        backtest_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO backtest_equity_curve (
                backtest_id, date, portfolio_value, cash, invested_value, drawdown_percent, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    backtest_id,
                    point.date,
                    point.portfolio_value,
                    point.cash,
                    point.invested_value,
                    point.drawdown_percent,
                    now,
                )
                for point in state["equity_curve"]
            ],
        )
        connection.executemany(
            """
            INSERT INTO backtest_trades (
                backtest_id, date, symbol, order_type, quantity, price, fees,
                gross_amount, net_amount, pnl, reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    backtest_id,
                    trade.date,
                    trade.symbol,
                    trade.order_type,
                    trade.quantity,
                    trade.price,
                    trade.fees,
                    trade.gross_amount,
                    trade.net_amount,
                    trade.pnl,
                    trade.reason,
                    now,
                )
                for trade in state["trades"]
            ],
        )
        connection.executemany(
            """
            INSERT INTO backtest_positions (
                backtest_id, symbol, quantity, average_price, final_price,
                final_value, realized_pnl, unrealized_pnl, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    backtest_id,
                    position.symbol,
                    position.quantity,
                    position.average_price,
                    position.final_price,
                    position.final_value,
                    position.realized_pnl,
                    position.unrealized_pnl,
                    now,
                )
                for position in state["final_positions"]
            ],
        )
        return backtest_id

    def _summary_from_row(self, row: sqlite3.Row) -> BacktestSummaryOut:
        return BacktestSummaryOut(
            id=row["id"],
            name=row["name"],
            strategy_name=row["strategy_name"],
            initial_cash=_round(row["initial_cash"]),
            start_date=row["start_date"],
            end_date=row["end_date"],
            benchmark_symbol=row["benchmark_symbol"],
            buy_threshold=_round(row["buy_threshold"]),
            sell_threshold=_round(row["sell_threshold"]),
            max_asset_weight=_round(row["max_asset_weight"]),
            fee_percent=_round(row["fee_percent"]),
            stop_loss_percent=_round(row["stop_loss_percent"]) if row["stop_loss_percent"] is not None else None,
            take_profit_percent=_round(row["take_profit_percent"]) if row["take_profit_percent"] is not None else None,
            rebalance_frequency=row["rebalance_frequency"],
            total_return_percent=_round(row["total_return_percent"]),
            cagr=_round(row["cagr"]),
            max_drawdown=_round(row["max_drawdown"]),
            sharpe_ratio=_round(row["sharpe_ratio"]),
            win_rate=_round(row["win_rate"]),
            profit_factor=_round(row["profit_factor"]),
            total_trades=int(row["total_trades"]),
            final_value=_round(row["final_value"]),
            benchmark_return_percent=_round(row["benchmark_return_percent"]),
            alpha_vs_benchmark=_round(row["alpha_vs_benchmark"]),
            created_at=row["created_at"],
        )

    def _trade_from_row(self, row: sqlite3.Row) -> BacktestTradeOut:
        return BacktestTradeOut(
            id=row["id"],
            date=row["date"],
            symbol=row["symbol"],
            order_type=row["order_type"],
            quantity=_round(row["quantity"]),
            price=_round(row["price"]),
            fees=_round(row["fees"]),
            gross_amount=_round(row["gross_amount"]),
            net_amount=_round(row["net_amount"]),
            pnl=_round(row["pnl"]),
            reason=row["reason"],
        )

    def _position_from_row(self, row: sqlite3.Row) -> BacktestPositionOut:
        return BacktestPositionOut(
            id=row["id"],
            symbol=row["symbol"],
            quantity=_round(row["quantity"]),
            average_price=_round(row["average_price"]),
            final_price=_round(row["final_price"]),
            final_value=_round(row["final_value"]),
            realized_pnl=_round(row["realized_pnl"]),
            unrealized_pnl=_round(row["unrealized_pnl"]),
        )

    def _hydrate_benchmark_from_run(
        self,
        connection: sqlite3.Connection,
        summary: BacktestSummaryOut,
        equity_curve: list[BacktestEquityPointOut],
    ) -> None:
        if not summary.benchmark_symbol or not equity_curve:
            return
        benchmark_data = self._load_market_data(connection, [summary.benchmark_symbol], pd.Timestamp(summary.end_date)).get(
            summary.benchmark_symbol
        )
        if benchmark_data is None:
            return
        dates = [pd.Timestamp(point.date) for point in equity_curve]
        benchmark_curve = self._benchmark_curve(summary.benchmark_symbol, benchmark_data, dates, summary.initial_cash)
        self._attach_benchmark(equity_curve, benchmark_curve)
