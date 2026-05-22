from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import (
    ScenarioAssetImpactOut,
    ScenarioClassImpactOut,
    ScenarioConfig,
    ScenarioRunFullOut,
    ScenarioRunSummaryOut,
    ScenarioType,
)
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.portfolio_optimizer_service import PortfolioOptimizerService


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class ScenarioService:
    def __init__(self) -> None:
        self.portfolio_engine = PortfolioEngine()
        self.optimizer_service = PortfolioOptimizerService()

    def run_scenario_analysis(self, connection: sqlite3.Connection, config: ScenarioConfig, portfolio_id: int) -> ScenarioRunFullOut:
        # 1. Get portfolio state based on source
        current_portfolio = self.portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)
        
        if config.portfolio_source == "CURRENT_PORTFOLIO":
            base_value = current_portfolio.total_value
            base_cash = current_portfolio.cash
            positions = [{"symbol": p.symbol, "type": p.asset_type, "value": p.current_value, "weight": p.weight_percent} for p in current_portfolio.positions]
        elif config.portfolio_source == "LATEST_OPTIMIZED_PORTFOLIO":
            latest_run = next(iter(self.optimizer_service.list_runs(connection, portfolio_id=portfolio_id)), None)
            if not latest_run:
                raise ValueError("Nessuna ottimizzazione trovata per questo portafoglio.")
            run_detail = self.optimizer_service.get_run(connection, latest_run.id)
            base_value = run_detail.summary.current_total_value
            base_cash = run_detail.summary.target_cash
            positions = [{"symbol": i.symbol, "type": i.risk_level, "value": i.target_value, "weight": i.target_weight} for i in run_detail.items if i.target_weight > 0]
            # Map risk_level to asset_type for shock logic if needed, or assume symbols are enough
        else: # CUSTOM_TARGET - not fully implemented yet, use current as fallback
            base_value = current_portfolio.total_value
            base_cash = current_portfolio.cash
            positions = [{"symbol": p.symbol, "type": p.asset_type, "value": p.current_value, "weight": p.weight_percent} for p in current_portfolio.positions]

        # 2. Define Shocks based on Scenario Type or Custom config
        shocks = self._get_scenario_shocks(config)
        
        # 3. Apply Shocks and Calculate Impact
        asset_impacts: list[ScenarioAssetImpactOut] = []
        class_impacts_map: dict[str, dict[str, float]] = {}
        
        stressed_invested_value = 0.0
        total_loss = 0.0
        
        for p in positions:
            symbol = p["symbol"]
            a_type = p["type"].upper()
            curr_val = p["value"]
            
            # Shock priority: Symbol specific > Asset Class > Preset Type
            shock_pct = config.symbol_shocks.get(symbol)
            if shock_pct is None:
                shock_pct = shocks.get(a_type, 0.0)
            
            # Apply ML/News risk if enabled (simulated extra penalty)
            if config.include_ml_risk or config.include_news_risk:
                asset_data = connection.execute(
                    "SELECT ml_confidence, ml_probability, signal FROM assets WHERE symbol = ?", (symbol,)
                ).fetchone()
                if asset_data:
                    if config.include_ml_risk and asset_data["ml_confidence"] == "LOW" and shock_pct < 0:
                        shock_pct -= 5.0 # Extra penalty for low confidence
                    if config.include_news_risk and shock_pct < 0:
                        # Check latest news sentiment
                        news = connection.execute(
                            "SELECT sentiment_label, impact_level FROM news_items WHERE symbol = ? ORDER BY published_at DESC LIMIT 1",
                            (symbol,)
                        ).fetchone()
                        if news and news["sentiment_label"] == "NEGATIVE" and news["impact_level"] == "HIGH":
                            shock_pct -= 5.0

            impact_abs = (shock_pct / 100.0) * curr_val
            stressed_val = max(0.0, curr_val + impact_abs)
            total_loss += impact_abs
            stressed_invested_value += stressed_val
            
            asset_impacts.append(ScenarioAssetImpactOut(
                symbol=symbol,
                asset_type=p["type"],
                current_value=curr_val,
                shock_percent=shock_pct,
                stressed_value=stressed_val,
                absolute_impact=impact_abs,
                percentage_impact=shock_pct,
                loss_contribution_percent=0.0 # Will calculate after loop
            ))
            
            # Aggregate by class
            if a_type not in class_impacts_map:
                class_impacts_map[a_type] = {"curr": 0.0, "stressed": 0.0}
            class_impacts_map[a_type]["curr"] += curr_val
            class_impacts_map[a_type]["stressed"] += stressed_val

        # Final calculations
        stressed_portfolio_value = stressed_invested_value + base_cash
        absolute_loss = total_loss # This is negative for losses
        percentage_loss = (absolute_loss / base_value * 100.0) if base_value > 0 else 0.0
        
        # Calculate loss contribution
        for i in asset_impacts:
            if absolute_loss != 0:
                i.loss_contribution_percent = (i.absolute_impact / absolute_loss * 100.0) if absolute_loss < 0 else 0.0
        
        class_impacts: list[ScenarioClassImpactOut] = []
        for c, vals in class_impacts_map.items():
            c_loss = vals["stressed"] - vals["curr"]
            class_impacts.append(ScenarioClassImpactOut(
                asset_class=c,
                current_value=vals["curr"],
                shock_percent=(c_loss / vals["curr"] * 100.0) if vals["curr"] > 0 else 0.0,
                stressed_value=vals["stressed"],
                absolute_impact=c_loss,
                percentage_impact=(c_loss / vals["curr"] * 100.0) if vals["curr"] > 0 else 0.0,
            ))

        risk_level = "LOW"
        if percentage_loss < -5: risk_level = "MEDIUM"
        if percentage_loss < -15: risk_level = "HIGH"
        if percentage_loss < -25: risk_level = "EXTREME"
        
        mitigation = self._generate_mitigation(percentage_loss, asset_impacts, current_portfolio)

        # Save to DB
        cursor = connection.execute(
            """
            INSERT INTO scenario_runs (
                portfolio_id, scenario_name, scenario_type, portfolio_source, config_json,
                current_portfolio_value, stressed_portfolio_value, absolute_loss,
                percentage_loss, risk_level, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id, config.scenario_name, config.scenario_type, config.portfolio_source, config.model_dump_json(),
                base_value, stressed_portfolio_value, absolute_loss, percentage_loss, risk_level,
                json.dumps({"worst_asset": min(asset_impacts, key=lambda x: x.absolute_impact).symbol if asset_impacts else None}),
                _now()
            )
        )
        scenario_id = cursor.lastrowid
        
        for ai in asset_impacts:
            connection.execute(
                """
                INSERT INTO scenario_asset_impacts (
                    scenario_id, symbol, asset_type, current_value, shock_percent,
                    stressed_value, absolute_impact, percentage_impact, loss_contribution_percent, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id, ai.symbol, ai.asset_type, ai.current_value, ai.shock_percent,
                    ai.stressed_value, ai.absolute_impact, ai.percentage_impact, ai.loss_contribution_percent, _now()
                )
            )
            
        for ci in class_impacts:
            connection.execute(
                """
                INSERT INTO scenario_class_impacts (
                    scenario_id, asset_class, current_value, shock_percent,
                    stressed_value, absolute_impact, percentage_impact, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scenario_id, ci.asset_class, ci.current_value, ci.shock_percent,
                    ci.stressed_value, ci.absolute_impact, ci.percentage_impact, _now()
                )
            )

        summary = ScenarioRunSummaryOut(
            id=scenario_id,
            scenario_name=config.scenario_name,
            scenario_type=config.scenario_type,
            portfolio_source=config.portfolio_source,
            current_portfolio_value=base_value,
            stressed_portfolio_value=stressed_portfolio_value,
            absolute_loss=absolute_loss,
            percentage_loss=percentage_loss,
            risk_level=risk_level,
            created_at=_now()
        )

        return ScenarioRunFullOut(
            summary=summary,
            config=config,
            asset_impacts=asset_impacts,
            class_impacts=class_impacts,
            loss_contribution={ai.symbol: ai.loss_contribution_percent for ai in asset_impacts},
            mitigation_suggestions=mitigation
        )

    def _get_scenario_shocks(self, config: ScenarioConfig) -> dict[str, float]:
        # Default shocks if not provided in config
        base_shocks = {
            ScenarioType.MARKET_CRASH: {"STOCK": -20.0, "ETF": -15.0, "CRYPTO": -30.0, "BOND": 3.0, "CASH": 0.0},
            ScenarioType.TECH_SELL_OFF: {"STOCK": -15.0, "ETF": -10.0, "CRYPTO": -20.0, "BOND": 0.0, "CASH": 0.0},
            ScenarioType.CRYPTO_CRASH: {"STOCK": -5.0, "ETF": -5.0, "CRYPTO": -50.0, "BOND": 0.0, "CASH": 0.0},
            ScenarioType.BOND_SHOCK: {"STOCK": -5.0, "ETF": -5.0, "CRYPTO": -10.0, "BOND": -10.0, "CASH": 0.0},
            ScenarioType.RATE_HIKE: {"STOCK": -10.0, "ETF": -8.0, "CRYPTO": -15.0, "BOND": -7.0, "CASH": 0.0},
            ScenarioType.RECESSION: {"STOCK": -25.0, "ETF": -20.0, "CRYPTO": -35.0, "BOND": 5.0, "CASH": 0.0},
            ScenarioType.INFLATION_SHOCK: {"STOCK": -10.0, "ETF": -10.0, "CRYPTO": 10.0, "BOND": -15.0, "CASH": -5.0},
            ScenarioType.BULL_RALLY: {"STOCK": 15.0, "ETF": 12.0, "CRYPTO": 25.0, "BOND": -2.0, "CASH": 0.0},
        }
        
        shocks = base_shocks.get(config.scenario_type, {}).copy()
        # Override with config provided shocks
        shocks.update(config.asset_class_shocks)
        return shocks

    def _generate_mitigation(self, loss_pct: float, impacts: list[ScenarioAssetImpactOut], portfolio: Any) -> list[str]:
        suggestions = []
        if loss_pct > -5:
            suggestions.append("Il portafoglio appare resiliente a questo scenario.")
            return suggestions

        if loss_pct < -15:
            suggestions.append("Rischio elevato rilevato. Considera di aumentare la riserva di Cash.")
            
        # Analyze worst contributors
        sorted_impacts = sorted(impacts, key=lambda x: x.absolute_impact)
        if sorted_impacts:
            worst = sorted_impacts[0]
            if worst.loss_contribution_percent > 30:
                suggestions.append(f"Alta concentrazione di perdita su {worst.symbol}. Valuta riduzione esposizione.")
        
        # Check crypto
        crypto_loss = sum(i.absolute_impact for i in impacts if i.asset_type.upper() == "CRYPTO")
        if crypto_loss < (loss_pct / 100 * portfolio.total_value) * 0.4: # if crypto contributes > 40% of loss
             suggestions.append("Esposizione Crypto eccessivamente vulnerabile in questo scenario.")

        suggestions.append("Valuta un ribilanciamento conservativo tramite il Portfolio Optimizer.")
        return suggestions

    def list_runs(self, connection: sqlite3.Connection, portfolio_id: int | None = None) -> list[ScenarioRunSummaryOut]:
        query = "SELECT * FROM scenario_runs"
        params = []
        if portfolio_id is not None:
            query += " WHERE portfolio_id = ?"
            params.append(portfolio_id)
        query += " ORDER BY created_at DESC"
        
        rows = connection.execute(query, params).fetchall()
        return [
            ScenarioRunSummaryOut(
                id=r["id"],
                scenario_name=r["scenario_name"],
                scenario_type=r["scenario_type"],
                portfolio_source=r["portfolio_source"],
                current_portfolio_value=r["current_portfolio_value"],
                stressed_portfolio_value=r["stressed_portfolio_value"],
                absolute_loss=r["absolute_loss"],
                percentage_loss=r["percentage_loss"],
                risk_level=r["risk_level"],
                created_at=r["created_at"]
            )
            for r in rows
        ]

    def get_run(self, connection: sqlite3.Connection, scenario_id: int) -> ScenarioRunFullOut:
        row = connection.execute("SELECT * FROM scenario_runs WHERE id = ?", (scenario_id,)).fetchone()
        if not row:
            raise ValueError(f"Scenario {scenario_id} non trovato.")
            
        summary = ScenarioRunSummaryOut(
            id=row["id"],
            scenario_name=row["scenario_name"],
            scenario_type=row["scenario_type"],
            portfolio_source=row["portfolio_source"],
            current_portfolio_value=row["current_portfolio_value"],
            stressed_portfolio_value=row["stressed_portfolio_value"],
            absolute_loss=row["absolute_loss"],
            percentage_loss=row["percentage_loss"],
            risk_level=row["risk_level"],
            created_at=row["created_at"]
        )
        
        config = ScenarioConfig(**json.loads(row["config_json"]))
        portfolio_id = row["portfolio_id"]
        
        asset_impacts = [
            ScenarioAssetImpactOut(
                id=r["id"],
                symbol=r["symbol"],
                asset_type=r["asset_type"],
                current_value=r["current_value"],
                shock_percent=r["shock_percent"],
                stressed_value=r["stressed_value"],
                absolute_impact=r["absolute_impact"],
                percentage_impact=r["percentage_impact"],
                loss_contribution_percent=r["loss_contribution_percent"]
            )
            for r in connection.execute("SELECT * FROM scenario_asset_impacts WHERE scenario_id = ?", (scenario_id,)).fetchall()
        ]
        
        class_impacts = [
            ScenarioClassImpactOut(
                id=r["id"],
                asset_class=r["asset_class"],
                current_value=r["current_value"],
                shock_percent=r["shock_percent"],
                stressed_value=r["stressed_value"],
                absolute_impact=r["absolute_impact"],
                percentage_impact=r["percentage_impact"]
            )
            for r in connection.execute("SELECT * FROM scenario_class_impacts WHERE scenario_id = ?", (scenario_id,)).fetchall()
        ]
        
        # Re-fetch portfolio for full generate_mitigation call
        portfolio = self.portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)
        mitigation = self._generate_mitigation(summary.percentage_loss, asset_impacts, portfolio)

        return ScenarioRunFullOut(
            summary=summary,
            config=config,
            asset_impacts=asset_impacts,
            class_impacts=class_impacts,
            loss_contribution={ai.symbol: ai.loss_contribution_percent for ai in asset_impacts},
            mitigation_suggestions=mitigation
        )

    def delete_run(self, connection: sqlite3.Connection, scenario_id: int) -> bool:
        connection.execute("DELETE FROM scenario_runs WHERE id = ?", (scenario_id,))
        return True
