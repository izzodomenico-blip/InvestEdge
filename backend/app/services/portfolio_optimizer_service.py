from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import (
    OptimizationItemOut,
    OptimizationMethod,
    OptimizationRunFullOut,
    OptimizationRunSummaryOut,
    OptimizerConfig,
    RebalanceOrderOut,
    SimulatedOrderIn,
)
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.operational_ranking_service import OperationalRankingService
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.risk_engine import RiskEngine


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class PortfolioOptimizerService:
    def __init__(self) -> None:
        self.portfolio_engine = PortfolioEngine()
        self.ranking_service = OperationalRankingService()
        self.dq_service = DataQualityService()
        self.risk_engine = RiskEngine()

    def generate_optimization_run(self, connection: sqlite3.Connection, config: OptimizerConfig, portfolio_id: int) -> OptimizationRunFullOut:
        # 1. Get current state
        portfolio = self.portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)
        current_total_value = portfolio.total_value if config.initial_capital_mode == "CURRENT_PORTFOLIO" else (config.custom_capital or 100000.0)
        
        # 2. Get candidates based on universe_source
        candidates = self._get_candidates(connection, config)
        
        # 3. Calculate target weights
        target_weights = self._calculate_target_weights(connection, config, candidates)
        
        # 4. Generate items and proposed orders
        items: list[OptimizationItemOut] = []
        proposed_orders: list[RebalanceOrderOut] = []
        warnings: list[str] = []
        blockers: list[str] = []
        
        positions_map = {p.symbol: p for p in portfolio.positions}
        all_symbols = sorted(list(set(list(positions_map.keys()) + list(target_weights.keys()))))
        
        total_target_invested = 0.0
        estimated_fees = 0.0
        turnover_value = 0.0
        
        for symbol in all_symbols:
            pos = positions_map.get(symbol)
            target_weight = target_weights.get(symbol, 0.0)
            
            curr_weight = pos.weight_percent if pos else 0.0
            curr_val = pos.current_value if pos else 0.0
            target_val = (target_weight / 100.0) * current_total_value
            delta_val = target_val - curr_val
            
            total_target_invested += target_val
            
            # Metadata for item
            asset = connection.execute(
                """
                SELECT a.risk_level, s.signal, s.score, p.predicted_label AS ml_label, p.probability_positive AS ml_probability
                FROM assets a
                LEFT JOIN signals s ON a.id = s.asset_id
                LEFT JOIN ml_predictions p ON a.symbol = p.symbol
                WHERE a.symbol = ?
                ORDER BY s.created_at DESC, p.created_at DESC
                LIMIT 1
                """,
                (symbol,)
            ).fetchone()
            
            dq = self.dq_service.check_asset_quality(connection, symbol)
            
            items.append(OptimizationItemOut(
                symbol=symbol,
                current_weight=curr_weight,
                target_weight=target_weight,
                current_value=curr_val,
                target_value=target_val,
                delta_value=delta_val,
                operational_signal=asset["signal"] if asset else None,
                data_quality_score=dq.score,
                ml_probability=asset["ml_probability"] if asset else None,
                risk_level=asset["risk_level"] if asset else None,
                reason=f"Target alignment: {target_weight:.1f}%"
            ))
            
            # Proposed order if delta is significant
            if abs(delta_val) > (config.rebalance_threshold_percent / 100.0 * current_total_value) and abs(delta_val) > 10.0:
                order_type = "BUY" if delta_val > 0 else "SELL"
                if (order_type == "BUY" and config.allow_buy) or (order_type == "SELL" and config.allow_sell):
                    price_row = connection.execute(
                        "SELECT close FROM price_history ph JOIN assets a ON ph.asset_id = a.id WHERE a.symbol = ? ORDER BY date DESC LIMIT 1",
                        (symbol,)
                    ).fetchone()
                    price = float(price_row[0]) if price_row else 100.0
                    
                    qty = abs(delta_val) / price
                    fees = abs(delta_val) * (config.fee_percent / 100.0)
                    estimated_fees += fees
                    turnover_value += abs(delta_val)
                    
                    proposed_orders.append(RebalanceOrderOut(
                        symbol=symbol,
                        order_type=order_type,
                        quantity=round(qty, 4),
                        estimated_price=round(price, 2),
                        estimated_gross_amount=round(abs(delta_val), 2),
                        estimated_fees=round(fees, 2),
                        estimated_net_amount=round(abs(delta_val) + (fees if order_type == "BUY" else -fees), 2),
                        reason=f"Rebalance: weight from {curr_weight:.1f}% to {target_weight:.1f}%"
                    ))

        target_cash = current_total_value - total_target_invested
        expected_cash = (portfolio.cash if config.initial_capital_mode == "CURRENT_PORTFOLIO" else current_total_value) - \
                        sum(o.estimated_net_amount for o in proposed_orders if o.order_type == "BUY") + \
                        sum(o.estimated_net_amount for o in proposed_orders if o.order_type == "SELL")
        
        turnover_percent = (turnover_value / current_total_value * 100.0) if current_total_value > 0 else 0.0

        # Save to DB
        cursor = connection.execute(
            """
            INSERT INTO portfolio_optimization_runs (
                portfolio_id, run_name, optimization_method, universe_source, config_json,
                current_total_value, target_invested_value, target_cash,
                expected_cash_after_rebalance, estimated_orders_count, estimated_fees,
                estimated_turnover_percent, risk_summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id, config.run_name, config.optimization_method, config.universe_source, config.model_dump_json(),
                current_total_value, total_target_invested, target_cash, expected_cash, len(proposed_orders),
                estimated_fees, turnover_percent, json.dumps({}), _now()
            )
        )
        run_id = cursor.lastrowid
        
        for item in items:
            connection.execute(
                """
                INSERT INTO portfolio_optimization_items (
                    run_id, symbol, current_weight, target_weight, current_value, target_value,
                    delta_value, operational_signal, data_quality_score, ml_probability, risk_level, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, item.symbol, item.current_weight, item.target_weight, item.current_value,
                    item.target_value, item.delta_value, item.operational_signal, item.data_quality_score,
                    item.ml_probability, item.risk_level, item.reason, _now()
                )
            )
            
        for o in proposed_orders:
            connection.execute(
                """
                INSERT INTO portfolio_rebalance_orders (
                    run_id, symbol, order_type, quantity, estimated_price,
                    estimated_gross_amount, estimated_fees, estimated_net_amount, reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?)
                """,
                (
                    run_id, o.symbol, o.order_type, o.quantity, o.estimated_price,
                    o.estimated_gross_amount, o.estimated_fees, o.estimated_net_amount, o.reason, _now()
                )
            )

        summary = OptimizationRunSummaryOut(
            id=run_id,
            run_name=config.run_name,
            optimization_method=config.optimization_method,
            universe_source=config.universe_source,
            current_total_value=current_total_value,
            target_invested_value=total_target_invested,
            target_cash=target_cash,
            expected_cash_after_rebalance=expected_cash,
            estimated_orders_count=len(proposed_orders),
            estimated_fees=estimated_fees,
            estimated_turnover_percent=turnover_percent,
            created_at=_now()
        )

        return OptimizationRunFullOut(
            summary=summary,
            config=config,
            items=items,
            proposed_orders=proposed_orders,
            warnings=warnings,
            blockers=blockers
        )

    def _get_candidates(self, connection: sqlite3.Connection, config: OptimizerConfig) -> list[Any]:
        ranking = self.ranking_service.get_operational_ranking(connection)
        
        if config.universe_source == "OPERATIONAL_BUY_CANDIDATES":
            return [s for s in ranking.buy_candidates if s.data_quality_score >= config.min_data_quality_score]
        
        # For other sources, filter signals
        if config.universe_source == "WATCHLIST":
            symbols = [r["symbol"] for r in connection.execute("SELECT symbol FROM asset_universe WHERE is_watchlisted = 1").fetchall()]
        elif config.universe_source == "CORE":
            symbols = [r["symbol"] for r in connection.execute("SELECT symbol FROM asset_universe WHERE universe_level = 'CORE'").fetchall()]
        else: # EXTENDED
            symbols = [r["symbol"] for r in connection.execute("SELECT symbol FROM asset_universe WHERE universe_level IN ('CORE', 'EXTENDED')").fetchall()]
            
        all_validated = ranking.buy_candidates + ranking.watch_candidates + ranking.reduce_candidates
        candidates = [s for s in all_validated if s.symbol in symbols and s.data_quality_score >= config.min_data_quality_score]
        
        # Exclude operational EXCLUDE and SELL signals
        candidates = [s for s in candidates if s.action_suggested not in ["EXCLUDE", "REDUCE"]]
        
        return candidates

    def _calculate_target_weights(self, connection: sqlite3.Connection, config: OptimizerConfig, candidates: list[Any]) -> dict[str, float]:
        if not candidates:
            return {}
            
        weights: dict[str, float] = {}
        n = len(candidates[:config.max_positions])
        
        if config.optimization_method == OptimizationMethod.EQUAL_WEIGHT:
            each = (100.0 - config.cash_reserve_percent) / n
            for s in candidates[:config.max_positions]:
                weights[s.symbol] = each
                
        elif config.optimization_method == OptimizationMethod.SCORE_WEIGHTED:
            # Simple score-based weighting
            assets = {}
            for s in candidates[:config.max_positions]:
                row = connection.execute(
                    "SELECT score FROM signals WHERE asset_id = ? ORDER BY created_at DESC LIMIT 1",
                    (s.asset_id,)
                ).fetchone()
                assets[s.symbol] = row["score"] if row else 50.0
            
            total_score = sum(assets.values())
            total_available = 100.0 - config.cash_reserve_percent
            for symbol, score in assets.items():
                weights[symbol] = (score / total_score) * total_available
                
        elif config.optimization_method == OptimizationMethod.RISK_ADJUSTED:
            # Weight inversely proportional to risk_level (simulated)
            risk_map = {"low": 1.0, "medium": 0.5, "high": 0.25, "very_high": 0.1}
            assets = {}
            for s in candidates[:config.max_positions]:
                row = connection.execute(
                    "SELECT risk_level FROM assets WHERE id = ?",
                    (s.asset_id,)
                ).fetchone()
                assets[s.symbol] = risk_map.get(row["risk_level"] if row else "medium", 0.5)
                
            total_risk_points = sum(assets.values())
            total_available = 100.0 - config.cash_reserve_percent
            for symbol, points in assets.items():
                weights[symbol] = (points / total_risk_points) * total_available
                
        elif config.optimization_method == OptimizationMethod.CONSERVATIVE_ALLOCATION:
            # 70% low risk, 30% medium, 0% high/very_high
            each = (100.0 - config.cash_reserve_percent) / n
            for s in candidates[:config.max_positions]:
                weights[s.symbol] = each # Simple for now
                
        else: # AGGRESSIVE
            each = (100.0 - config.cash_reserve_percent) / n
            for s in candidates[:config.max_positions]:
                weights[s.symbol] = each

        # Apply constraints (max single asset)
        total_target = sum(weights.values())
        for symbol in weights:
            weights[symbol] = min(weights[symbol], config.max_single_asset_weight)
            
        # Re-normalize
        current_sum = sum(weights.values())
        max_invested = 100.0 - config.cash_reserve_percent
        if current_sum > 0:
            scale = max_invested / current_sum
            for s in weights:
                weights[s] *= scale
                
        return weights

    def list_runs(self, connection: sqlite3.Connection, portfolio_id: int | None = None) -> list[OptimizationRunSummaryOut]:
        query = "SELECT * FROM portfolio_optimization_runs"
        params = []
        if portfolio_id is not None:
            query += " WHERE portfolio_id = ?"
            params.append(portfolio_id)
        query += " ORDER BY created_at DESC"
        
        rows = connection.execute(query, params).fetchall()
        return [
            OptimizationRunSummaryOut(
                id=r["id"],
                run_name=r["run_name"],
                optimization_method=r["optimization_method"],
                universe_source=r["universe_source"],
                current_total_value=r["current_total_value"],
                target_invested_value=r["target_invested_value"],
                target_cash=r["target_cash"],
                expected_cash_after_rebalance=r["expected_cash_after_rebalance"],
                estimated_orders_count=r["estimated_orders_count"],
                estimated_fees=r["estimated_fees"],
                estimated_turnover_percent=r["estimated_turnover_percent"],
                created_at=r["created_at"]
            )
            for r in rows
        ]

    def get_run(self, connection: sqlite3.Connection, run_id: int) -> OptimizationRunFullOut:
        row = connection.execute("SELECT * FROM portfolio_optimization_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"Run {run_id} not found")
            
        summary = OptimizationRunSummaryOut(
            id=row["id"],
            run_name=row["run_name"],
            optimization_method=row["optimization_method"],
            universe_source=row["universe_source"],
            current_total_value=row["current_total_value"],
            target_invested_value=row["target_invested_value"],
            target_cash=row["target_cash"],
            expected_cash_after_rebalance=row["expected_cash_after_rebalance"],
            estimated_orders_count=row["estimated_orders_count"],
            estimated_fees=row["estimated_fees"],
            estimated_turnover_percent=row["estimated_turnover_percent"],
            created_at=row["created_at"]
        )
        
        config = OptimizerConfig(**json.loads(row["config_json"]))
        
        items = [
            OptimizationItemOut(
                id=r["id"],
                symbol=r["symbol"],
                current_weight=r["current_weight"],
                target_weight=r["target_weight"],
                current_value=r["current_value"],
                target_value=r["target_value"],
                delta_value=r["delta_value"],
                operational_signal=r["operational_signal"],
                data_quality_score=r["data_quality_score"],
                ml_probability=r["ml_probability"],
                news_sentiment=r["news_sentiment"],
                risk_level=r["risk_level"],
                reason=r["reason"]
            )
            for r in connection.execute("SELECT * FROM portfolio_optimization_items WHERE run_id = ?", (run_id,)).fetchall()
        ]
        
        proposed_orders = [
            RebalanceOrderOut(
                id=r["id"],
                symbol=r["symbol"],
                order_type=r["order_type"],
                quantity=r["quantity"],
                estimated_price=r["estimated_price"],
                estimated_gross_amount=r["estimated_gross_amount"],
                estimated_fees=r["estimated_fees"],
                estimated_net_amount=r["estimated_net_amount"],
                reason=r["reason"],
                status=r["status"]
            )
            for r in connection.execute("SELECT * FROM portfolio_rebalance_orders WHERE run_id = ?", (run_id,)).fetchall()
        ]
        
        return OptimizationRunFullOut(
            summary=summary,
            config=config,
            items=items,
            proposed_orders=proposed_orders,
            risk_summary=json.loads(row["risk_summary_json"]) if row["risk_summary_json"] else {}
        )

    def apply_rebalance_orders(self, connection: sqlite3.Connection, run_id: int) -> int:
        row = connection.execute("SELECT portfolio_id FROM portfolio_optimization_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"Run {run_id} not found")
        portfolio_id = row["portfolio_id"]
        
        run = self.get_run(connection, run_id)
        
        count = 0
        for o in run.proposed_orders:
            if o.status == "PROPOSED":
                payload = SimulatedOrderIn(
                    symbol=o.symbol,
                    order_type=o.order_type,
                    quantity=o.quantity,
                    price=o.estimated_price,
                    fees=o.estimated_fees,
                    note=f"Applied from optimization: {run.summary.run_name}"
                )
                self.portfolio_engine.simulate_order(connection, payload, portfolio_id=portfolio_id)
                
                connection.execute(
                    "UPDATE portfolio_rebalance_orders SET status = 'PAPER_CREATED' WHERE id = ?",
                    (o.id,)
                )
                count += 1
                
        return count

    def delete_run(self, connection: sqlite3.Connection, run_id: int) -> bool:
        connection.execute("DELETE FROM portfolio_optimization_runs WHERE id = ?", (run_id,))
        return True
