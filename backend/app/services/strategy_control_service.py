from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import (
    StrategyPlanConfig,
    StrategyPlanFullOut,
    StrategyPlanItemOut,
    StrategyPlanOrderOut,
    StrategyPlanSummaryOut,
    SimulatedOrderIn,
)
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.signal_validation_service import SignalValidationService
from backend.app.services.alert_service import AlertService
from backend.app.services.user_settings_service import UserSettingsService


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class StrategyControlService:
    def __init__(self) -> None:
        self.portfolio_engine = PortfolioEngine()
        self.validation_service = SignalValidationService()
        self.alert_service = AlertService()
        self.settings_service = UserSettingsService()
        self.settings_service = UserSettingsService()

    def generate_strategy_plan(self, connection: sqlite3.Connection, config: StrategyPlanConfig, portfolio_id: int) -> StrategyPlanFullOut:
        # 1. Get current state
        portfolio = self.portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)
        current_cash = portfolio.cash
        total_value = portfolio.total_value

        # 2. Get operational candidates
        validated_signals = self.validation_service.validate_all_signals(connection)
        
        # Get universe symbols for this plan
        universe_symbols = []
        if config.universe_level == "CORE":
            universe_symbols = [r["symbol"] for r in connection.execute("SELECT symbol FROM asset_universe WHERE universe_level = 'CORE'").fetchall()]
        elif config.universe_level == "EXTENDED":
            universe_symbols = [r["symbol"] for r in connection.execute("SELECT symbol FROM asset_universe WHERE universe_level IN ('CORE', 'EXTENDED')").fetchall()]
        elif config.universe_level == "WATCHLIST":
            universe_symbols = [r["symbol"] for r in connection.execute("SELECT symbol FROM asset_universe WHERE is_watchlisted = 1").fetchall()]
        else:
            universe_symbols = [s.symbol for s in validated_signals]

        # 3. Calculate Target Allocation
        items: list[StrategyPlanItemOut] = []
        proposed_orders: list[StrategyPlanOrderOut] = []
        warnings: list[str] = []
        blockers: list[str] = []

        # Filter signals for target calculation
        quality_signals = [s for s in validated_signals if s.data_quality_score >= config.min_data_quality_score and s.symbol in universe_symbols]

        # Current positions map
        positions_map = {p.symbol: p for p in portfolio.positions}
        
        # Decide targets
        target_allocation = self._calculate_target_allocation(config, quality_signals, positions_map)
        
        # 4. Generate Items and Orders
        total_target_invested = 0.0
        
        # Combine all symbols involved (current positions + universe symbols)
        all_symbols = sorted(list(set(list(positions_map.keys()) + universe_symbols)))

        for symbol in all_symbols:
            pos = positions_map.get(symbol)
            target_weight = target_allocation.get(symbol, 0.0)
            
            curr_weight = pos.weight_percent if pos else 0.0
            curr_val = pos.current_value if pos else 0.0
            target_val = (target_weight / 100.0) * total_value
            delta_val = target_val - curr_val
            
            total_target_invested += target_val
            
            val_sig = next((s for s in validated_signals if s.symbol == symbol), None)
            
            # Action logic
            action = "HOLD"
            if target_weight > curr_weight + config.rebalance_threshold_percent:
                action = "BUY"
            elif target_weight < curr_weight - config.rebalance_threshold_percent:
                action = "SELL"
            
            item = StrategyPlanItemOut(
                symbol=symbol,
                current_weight=curr_weight,
                target_weight=target_weight,
                current_value=curr_val,
                target_value=target_val,
                delta_value=delta_val,
                suggested_action=action,
                operational_signal=val_sig.validated_signal if val_sig else None,
                confidence=val_sig.ml_confidence if val_sig else None,
                data_quality_score=val_sig.data_quality_score if val_sig else None,
                reason=val_sig.reason if val_sig else "No validation data",
            )
            
            # Checks for blockers
            if val_sig and val_sig.action_suggested == "EXCLUDE":
                item.blocker = "Signal excluded by validation rules"
                if action == "BUY":
                    action = "HOLD"
                    item.suggested_action = "HOLD"
            elif val_sig and val_sig.data_quality_score < config.min_data_quality_score:
                item.blocker = f"Data quality ({val_sig.data_quality_score:.1f}) below threshold ({config.min_data_quality_score})"
                if action == "BUY":
                    action = "HOLD"
                    item.suggested_action = "HOLD"
            
            items.append(item)
            
            # Proposed order
            if action in ["BUY", "SELL"] and abs(delta_val) > 10.0:  # Min order value
                price_row = connection.execute(
                    "SELECT close FROM price_history WHERE asset_id = (SELECT id FROM assets WHERE symbol = ?) ORDER BY date DESC LIMIT 1",
                    (symbol,)
                ).fetchone()
                if not price_row:
                    price_row = connection.execute(
                        "SELECT close FROM price_history ph JOIN assets a ON ph.asset_id = a.id WHERE a.symbol = ? ORDER BY date DESC LIMIT 1",
                        (symbol,)
                    ).fetchone()
                
                price = float(price_row[0]) if price_row else 100.0 # Fallback
                qty = abs(delta_val) / price
                
                # Simple fee estimation
                fees = abs(delta_val) * 0.001 
                
                proposed_orders.append(StrategyPlanOrderOut(
                    symbol=symbol,
                    order_type="BUY" if delta_val > 0 else "SELL",
                    quantity=round(qty, 4),
                    estimated_price=round(price, 2),
                    estimated_gross_amount=round(abs(delta_val), 2),
                    estimated_fees=round(fees, 2),
                    estimated_net_amount=round(abs(delta_val) + (fees if delta_val > 0 else -fees), 2),
                    reason=f"Target weight change from {curr_weight:.1f}% to {target_weight:.1f}%",
                ))

        # Expected cash
        total_buy_net = sum(o.estimated_net_amount for o in proposed_orders if o.order_type == "BUY")
        total_sell_net = sum(o.estimated_net_amount for o in proposed_orders if o.order_type == "SELL")
        expected_cash = current_cash - total_buy_net + total_sell_net

        if expected_cash < (config.cash_reserve_percent / 100.0) * total_value:
            warnings.append(f"Expected cash ({expected_cash:.2f}) is below the required reserve.")

        # Save to DB
        cursor = connection.execute(
            """
            INSERT INTO strategy_plans (
                portfolio_id, plan_name, strategy_mode, universe_level, config_json, 
                total_current_value, target_invested_value, expected_cash_after_plan, 
                estimated_orders_count, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?)
            """,
            (
                portfolio_id, config.plan_name, config.strategy_mode, config.universe_level, config.model_dump_json(),
                total_value, total_target_invested, expected_cash, len(proposed_orders), _now(), _now()
            )
        )

        plan_id = cursor.lastrowid

        # Create Alert
        if len(proposed_orders) > 0:
            self.alert_service.create_alert(
                connection, "STRATEGY_PLAN_GENERATED", "INFO",
                f"Nuovo piano: {config.plan_name}",
                f"Generato piano operativo con {len(proposed_orders)} ordini paper proposti.",
                source_module="StrategyControl"
            )

        for item in items:
            connection.execute(
                """
                INSERT INTO strategy_plan_items (
                    plan_id, symbol, current_weight, target_weight, current_value, target_value, 
                    delta_value, suggested_action, operational_signal, confidence, 
                    data_quality_score, reason, blocker, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id, item.symbol, item.current_weight, item.target_weight, item.current_value,
                    item.target_value, item.delta_value, item.suggested_action, item.operational_signal,
                    item.confidence, item.data_quality_score, item.reason, item.blocker, _now()
                )
            )

        for o in proposed_orders:
            connection.execute(
                """
                INSERT INTO strategy_plan_orders (
                    plan_id, symbol, order_type, quantity, estimated_price, 
                    estimated_gross_amount, estimated_fees, estimated_net_amount, 
                    reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?)
                """,
                (
                    plan_id, o.symbol, o.order_type, o.quantity, o.estimated_price,
                    o.estimated_gross_amount, o.estimated_fees, o.estimated_net_amount,
                    o.reason, _now()
                )
            )

        summary = StrategyPlanSummaryOut(
            id=plan_id,
            plan_name=config.plan_name,
            strategy_mode=config.strategy_mode,
            universe_level=config.universe_level,
            total_current_value=total_value,
            target_invested_value=total_target_invested,
            expected_cash_after_plan=expected_cash,
            estimated_orders_count=len(proposed_orders),
            status="DRAFT",
            created_at=_now(),
        )

        return StrategyPlanFullOut(
            summary=summary,
            config=config,
            items=items,
            proposed_orders=proposed_orders,
            warnings=warnings,
            blockers=blockers,
        )

    def _calculate_target_allocation(self, config: StrategyPlanConfig, validated_signals: list[Any], positions_map: dict[str, Any]) -> dict[str, float]:
        targets: dict[str, float] = {}
        
        # 1. Decide which assets to keep or sell
        for symbol, pos in positions_map.items():
            val_sig = next((s for s in validated_signals if s.symbol == symbol), None)
            if val_sig and val_sig.action_suggested in ["REDUCE", "EXCLUDE"]:
                targets[symbol] = 0.0 # Full exit for simplicity in strategy plan
            else:
                targets[symbol] = pos.weight_percent # Default keep current weight

        # 2. Add new BUY candidates
        buy_candidates = [s for s in validated_signals if s.action_suggested == "BUY"]
        # Sort by quality/score
        buy_candidates.sort(key=lambda x: x.data_quality_score, reverse=True)
        
        max_to_add = config.max_positions - len([t for t in targets.values() if t > 0])
        added_count = 0
        
        target_weight = 10.0 # Default
        if config.strategy_mode == "CONSERVATIVE": target_weight = 5.0
        if config.strategy_mode == "AGGRESSIVE": target_weight = 15.0

        for s in buy_candidates:
            if added_count >= max_to_add: break
            if s.symbol not in targets or targets[s.symbol] == 0:
                targets[s.symbol] = min(target_weight, config.max_single_asset_weight)
                added_count += 1

        # Normalize weights to stay within 100 - cash_reserve
        total_target = sum(targets.values())
        max_invested = 100.0 - config.cash_reserve_percent
        
        if total_target > max_invested:
            scale = max_invested / total_target
            for s in targets:
                targets[s] *= scale

        return targets

    def list_strategy_plans(self, connection: sqlite3.Connection, portfolio_id: int | None = None) -> list[StrategyPlanSummaryOut]:
        query = "SELECT * FROM strategy_plans"
        params = []
        if portfolio_id is not None:
            query += " WHERE portfolio_id = ?"
            params.append(portfolio_id)
        query += " ORDER BY created_at DESC"
        
        rows = connection.execute(query, params).fetchall()
        return [
            StrategyPlanSummaryOut(
                id=row["id"],
                plan_name=row["plan_name"],
                strategy_mode=row["strategy_mode"],
                universe_level=row["universe_level"],
                total_current_value=row["total_current_value"],
                target_invested_value=row["target_invested_value"],
                expected_cash_after_plan=row["expected_cash_after_plan"],
                estimated_orders_count=row["estimated_orders_count"],
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_strategy_plan(self, connection: sqlite3.Connection, plan_id: int) -> StrategyPlanFullOut:
        row = connection.execute("SELECT * FROM strategy_plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            raise ValueError(f"Plan {plan_id} not found")

        summary = StrategyPlanSummaryOut(
            id=row["id"],
            plan_name=row["plan_name"],
            strategy_mode=row["strategy_mode"],
            universe_level=row["universe_level"],
            total_current_value=row["total_current_value"],
            target_invested_value=row["target_invested_value"],
            expected_cash_after_plan=row["expected_cash_after_plan"],
            estimated_orders_count=row["estimated_orders_count"],
            status=row["status"],
            created_at=row["created_at"],
        )
        
        config = StrategyPlanConfig(**json.loads(row["config_json"]))
        
        items = [
            StrategyPlanItemOut(
                id=r["id"],
                symbol=r["symbol"],
                current_weight=r["current_weight"],
                target_weight=r["target_weight"],
                current_value=r["current_value"],
                target_value=r["target_value"],
                delta_value=r["delta_value"],
                suggested_action=r["suggested_action"],
                operational_signal=r["operational_signal"],
                confidence=r["confidence"],
                data_quality_score=r["data_quality_score"],
                reason=r["reason"],
                blocker=r["blocker"],
            )
            for r in connection.execute("SELECT * FROM strategy_plan_items WHERE plan_id = ?", (plan_id,)).fetchall()
        ]
        
        proposed_orders = [
            StrategyPlanOrderOut(
                id=r["id"],
                symbol=r["symbol"],
                order_type=r["order_type"],
                quantity=r["quantity"],
                estimated_price=r["estimated_price"],
                estimated_gross_amount=r["estimated_gross_amount"],
                estimated_fees=r["estimated_fees"],
                estimated_net_amount=r["estimated_net_amount"],
                reason=r["reason"],
                status=r["status"],
            )
            for r in connection.execute("SELECT * FROM strategy_plan_orders WHERE plan_id = ?", (plan_id,)).fetchall()
        ]
        
        return StrategyPlanFullOut(
            summary=summary,
            config=config,
            items=items,
            proposed_orders=proposed_orders,
        )

    def apply_plan_to_paper_trading(self, connection: sqlite3.Connection, plan_id: int) -> int:
        row = connection.execute("SELECT portfolio_id FROM strategy_plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            raise ValueError(f"Plan {plan_id} not found")
        portfolio_id = row["portfolio_id"]
        
        plan = self.get_strategy_plan(connection, plan_id)
        if plan.summary.status == "APPLIED":
            raise ValueError("Plan already applied")
            
        orders_count = 0
        for o in plan.proposed_orders:
            payload = SimulatedOrderIn(
                symbol=o.symbol,
                order_type=o.order_type,
                quantity=o.quantity,
                price=o.estimated_price,
                fees=o.estimated_fees,
                note=f"Applied from strategy plan: {plan.summary.plan_name}",
            )
            self.portfolio_engine.simulate_order(connection, payload, portfolio_id=portfolio_id)
            orders_count += 1
            
        connection.execute(
            "UPDATE strategy_plans SET status = 'APPLIED', updated_at = ? WHERE id = ?",
            (_now(), plan_id)
        )
        connection.execute(
            "UPDATE strategy_plan_orders SET status = 'EXECUTED' WHERE plan_id = ?",
            (plan_id,)
        )
        
        return orders_count

    def delete_plan(self, connection: sqlite3.Connection, plan_id: int) -> bool:
        connection.execute("DELETE FROM strategy_plans WHERE id = ?", (plan_id,))
        return True
