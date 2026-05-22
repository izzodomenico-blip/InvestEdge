from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import (
    CashTransferIn,
    CashTransferOut,
    ConsolidatedSummaryOut,
    PortfolioCloneIn,
    PortfolioCreateIn,
    PortfolioOut,
    PortfolioUpdateIn,
    PortfolioPerformanceComparisonOut
)


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class MultiPortfolioService:
    def __init__(self) -> None:
        pass

    def ensure_default_portfolio(self, connection: sqlite3.Connection) -> int:
        """
        Garantisce l'esistenza di un portafoglio default e associa i dati orfani ad esso.
        """
        row = connection.execute(
            "SELECT id FROM portfolios WHERE portfolio_name = 'Default Portfolio'"
        ).fetchone()

        if row:
            portfolio_id = row["id"]
        else:
            # Crea portafoglio default se non esiste
            # Recupera settings attuali per il cash iniziale
            settings_row = connection.execute("SELECT initial_cash, current_cash FROM portfolio_settings WHERE id = 1").fetchone()
            initial_cash = settings_row["initial_cash"] if settings_row else 100000.0
            current_cash = settings_row["current_cash"] if settings_row else 100000.0

            # Recupera profili attivi per collegarli
            risk_row = connection.execute("SELECT id FROM risk_profiles WHERE is_active = 1 LIMIT 1").fetchone()
            strat_row = connection.execute("SELECT id FROM strategy_profiles WHERE is_active = 1 LIMIT 1").fetchone()
            risk_id = risk_row["id"] if risk_row else None
            strat_id = strat_row["id"] if strat_row else None

            cursor = connection.execute(
                """
                INSERT INTO portfolios (
                    portfolio_name, description, portfolio_type, initial_cash, current_cash, 
                    risk_profile_id, strategy_profile_id, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Default Portfolio", "Main simulated portfolio", "CORE", initial_cash, current_cash, 
                    risk_id, strat_id, 1, _now(), _now()
                )
            )
            portfolio_id = cursor.lastrowid

        # Associa dati orfani (portfolio_id IS NULL)
        tables_to_update = [
            "portfolio_positions",
            "simulated_orders",
            "portfolio_snapshots",
            "strategy_plans",
            "alerts",
            "operational_reports",
            "portfolio_optimization_runs",
            "scenario_runs"
        ]

        for table in tables_to_update:
            connection.execute(
                f"UPDATE {table} SET portfolio_id = ? WHERE portfolio_id IS NULL",
                (portfolio_id,)
            )

        return portfolio_id

    def list_portfolios(self, connection: sqlite3.Connection, include_archived: bool = False) -> list[PortfolioOut]:
        query = "SELECT * FROM portfolios"
        if not include_archived:
            query += " WHERE is_archived = 0"
        query += " ORDER BY is_active DESC, portfolio_name ASC"

        rows = connection.execute(query).fetchall()
        return [PortfolioOut(**dict(row)) for row in rows]

    def get_portfolio(self, connection: sqlite3.Connection, portfolio_id: int) -> PortfolioOut | None:
        row = connection.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        return PortfolioOut(**dict(row)) if row else None

    def get_active_portfolio(self, connection: sqlite3.Connection) -> PortfolioOut:
        row = connection.execute("SELECT * FROM portfolios WHERE is_active = 1 AND is_archived = 0").fetchone()
        if not row:
            # Se nessuno è attivo, attiva il primo non archiviato o crea default
            row = connection.execute("SELECT * FROM portfolios WHERE is_archived = 0 ORDER BY id LIMIT 1").fetchone()
            if row:
                connection.execute("UPDATE portfolios SET is_active = 1 WHERE id = ?", (row["id"],))
                return PortfolioOut(**dict(row))
            else:
                default_id = self.ensure_default_portfolio(connection)
                return self.get_portfolio(connection, default_id)
        return PortfolioOut(**dict(row))

    def set_active_portfolio(self, connection: sqlite3.Connection, portfolio_id: int) -> bool:
        # Verifica esistenza e non archiviato
        row = connection.execute("SELECT id FROM portfolios WHERE id = ? AND is_archived = 0", (portfolio_id,)).fetchone()
        if not row:
            return False

        connection.execute("UPDATE portfolios SET is_active = 0")
        connection.execute("UPDATE portfolios SET is_active = 1 WHERE id = ?", (portfolio_id,))
        return True

    def create_portfolio(self, connection: sqlite3.Connection, data: PortfolioCreateIn) -> PortfolioOut:
        cursor = connection.execute(
            """
            INSERT INTO portfolios (
                portfolio_name, description, portfolio_type, base_currency, 
                initial_cash, current_cash, risk_profile_id, strategy_profile_id, 
                is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.portfolio_name, data.description, data.portfolio_type, data.base_currency,
                data.initial_cash, data.initial_cash, data.risk_profile_id, data.strategy_profile_id,
                0, _now(), _now()
            )
        )
        portfolio_id = cursor.lastrowid
        return self.get_portfolio(connection, portfolio_id)

    def update_portfolio(self, connection: sqlite3.Connection, portfolio_id: int, data: PortfolioUpdateIn) -> PortfolioOut | None:
        updates = []
        params = []

        if data.portfolio_name is not None:
            updates.append("portfolio_name = ?")
            params.append(data.portfolio_name)
        if data.description is not None:
            updates.append("description = ?")
            params.append(data.description)
        if data.portfolio_type is not None:
            updates.append("portfolio_type = ?")
            params.append(data.portfolio_type)
        if data.risk_profile_id is not None:
            updates.append("risk_profile_id = ?")
            params.append(data.risk_profile_id)
        if data.strategy_profile_id is not None:
            updates.append("strategy_profile_id = ?")
            params.append(data.strategy_profile_id)
        if data.is_archived is not None:
            updates.append("is_archived = ?")
            params.append(1 if data.is_archived else 0)
            if data.is_archived:
                updates.append("is_active = 0")

        if not updates:
            return self.get_portfolio(connection, portfolio_id)

        updates.append("updated_at = ?")
        params.append(_now())
        params.append(portfolio_id)

        connection.execute(f"UPDATE portfolios SET {', '.join(updates)} WHERE id = ?", params)
        return self.get_portfolio(connection, portfolio_id)

    def delete_portfolio(self, connection: sqlite3.Connection, portfolio_id: int) -> bool:
        # Verifica se ha ordini o posizioni
        has_data = connection.execute(
            "SELECT 1 FROM simulated_orders WHERE portfolio_id = ? LIMIT 1", (portfolio_id,)
        ).fetchone() or connection.execute(
            "SELECT 1 FROM portfolio_positions WHERE portfolio_id = ? LIMIT 1", (portfolio_id,)
        ).fetchone()

        if has_data:
            # Archiviazione logica
            connection.execute("UPDATE portfolios SET is_archived = 1, is_active = 0 WHERE id = ?", (portfolio_id,))
        else:
            # Eliminazione fisica se vuoto
            connection.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))

        return True

    def clone_portfolio(self, connection: sqlite3.Connection, portfolio_id: int, data: PortfolioCloneIn) -> PortfolioOut | None:
        source = self.get_portfolio(connection, portfolio_id)
        if not source:
            return None

        new_portfolio = self.create_portfolio(connection, PortfolioCreateIn(
            portfolio_name=data.new_name,
            description=f"Clone of {source.portfolio_name}",
            portfolio_type=source.portfolio_type,
            base_currency=source.base_currency,
            initial_cash=source.initial_cash,
            risk_profile_id=source.risk_profile_id,
            strategy_profile_id=source.strategy_profile_id
        ))

        # Update current cash if not including positions
        if not data.include_positions:
            connection.execute("UPDATE portfolios SET current_cash = initial_cash WHERE id = ?", (new_portfolio.id,))
        else:
            # Copy positions
            connection.execute(
                """
                INSERT INTO portfolio_positions (
                    portfolio_id, asset_id, symbol, quantity, average_price, invested_amount, 
                    current_price, current_value, realized_pnl, unrealized_pnl, 
                    unrealized_pnl_percent, weight_percent, asset_type, currency, opened_at, updated_at
                )
                SELECT 
                    ?, asset_id, symbol, quantity, average_price, invested_amount, 
                    current_price, current_value, realized_pnl, unrealized_pnl, 
                    unrealized_pnl_percent, weight_percent, asset_type, currency, ?, ?
                FROM portfolio_positions WHERE portfolio_id = ?
                """,
                (new_portfolio.id, _now(), _now(), portfolio_id)
            )
            # Match current cash
            connection.execute(
                "UPDATE portfolios SET current_cash = ? WHERE id = ?",
                (source.current_cash, new_portfolio.id)
            )

        if data.include_orders:
            connection.execute(
                """
                INSERT INTO simulated_orders (
                    portfolio_id, asset_id, symbol, order_type, side, quantity, price, 
                    fees, gross_amount, net_amount, order_date, note, strategy_tag, 
                    created_at, status, executed_at
                )
                SELECT 
                    ?, asset_id, symbol, order_type, side, quantity, price, 
                    fees, gross_amount, net_amount, order_date, note, strategy_tag, 
                    ?, status, executed_at
                FROM simulated_orders WHERE portfolio_id = ?
                """,
                (new_portfolio.id, _now(), portfolio_id)
            )

        return self.get_portfolio(connection, new_portfolio.id)

    def transfer_cash(self, connection: sqlite3.Connection, data: CashTransferIn) -> CashTransferOut:
        if data.transfer_type == "DEPOSIT":
            if not data.to_portfolio_id:
                raise ValueError("To portfolio ID is required for DEPOSIT")
            connection.execute(
                "UPDATE portfolios SET current_cash = current_cash + ? WHERE id = ?",
                (data.amount, data.to_portfolio_id)
            )
        elif data.transfer_type == "WITHDRAWAL":
            if not data.from_portfolio_id:
                raise ValueError("From portfolio ID is required for WITHDRAWAL")
            connection.execute(
                "UPDATE portfolios SET current_cash = current_cash - ? WHERE id = ?",
                (data.amount, data.from_portfolio_id)
            )
        elif data.transfer_type == "INTERNAL_TRANSFER":
            if not data.from_portfolio_id or not data.to_portfolio_id:
                raise ValueError("Both portfolio IDs are required for INTERNAL_TRANSFER")
            connection.execute(
                "UPDATE portfolios SET current_cash = current_cash - ? WHERE id = ?",
                (data.amount, data.from_portfolio_id)
            )
            connection.execute(
                "UPDATE portfolios SET current_cash = current_cash + ? WHERE id = ?",
                (data.amount, data.to_portfolio_id)
            )

        cursor = connection.execute(
            """
            INSERT INTO portfolio_cash_transfers (
                from_portfolio_id, to_portfolio_id, amount, transfer_type, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (data.from_portfolio_id, data.to_portfolio_id, data.amount, data.transfer_type, data.note, _now())
        )
        
        row = connection.execute("SELECT * FROM portfolio_cash_transfers WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return CashTransferOut(**dict(row))

    def get_consolidated_summary(self, connection: sqlite3.Connection) -> ConsolidatedSummaryOut:
        portfolios = self.list_portfolios(connection, include_archived=False)
        
        total_value = 0.0
        total_cash = 0.0
        total_invested = 0.0
        total_realized_pnl = 0.0
        total_unrealized_pnl = 0.0
        
        portfolio_summaries = []
        asset_type_alloc = {}
        currency_alloc = {}

        for p in portfolios:
            # Calcola valore attuale (somma posizioni + cash)
            pos_rows = connection.execute(
                "SELECT asset_type, currency, current_value, realized_pnl, unrealized_pnl FROM portfolio_positions WHERE portfolio_id = ?",
                (p.id,)
            ).fetchall()
            
            p_invested = sum(r["current_value"] for r in pos_rows)
            p_realized = sum(r["realized_pnl"] for r in pos_rows)
            p_unrealized = sum(r["unrealized_pnl"] for r in pos_rows)
            p_total = p_invested + p.current_cash
            
            total_value += p_total
            total_cash += p.current_cash
            total_invested += p_invested
            total_realized_pnl += p_realized
            total_unrealized_pnl += p_unrealized
            
            for r in pos_rows:
                atype = r["asset_type"] or "Unknown"
                curr = r["currency"] or p.base_currency
                asset_type_alloc[atype] = asset_type_alloc.get(atype, 0) + r["current_value"]
                currency_alloc[curr] = currency_alloc.get(curr, 0) + r["current_value"]
            
            # Cash allocation
            currency_alloc[p.base_currency] = currency_alloc.get(p.base_currency, 0) + p.current_cash
            
            portfolio_summaries.append({
                "id": p.id,
                "name": p.portfolio_name,
                "type": p.portfolio_type,
                "total_value": p_total,
                "cash": p.current_cash,
                "pnl": p_realized + p_unrealized,
                "pnl_percent": ((p_total / p.initial_cash) - 1) * 100 if p.initial_cash > 0 else 0
            })

        total_pnl = total_realized_pnl + total_unrealized_pnl
        # Consolidato P/L % basato su initial_cash totale
        total_initial = sum(p.initial_cash for p in portfolios)
        total_pnl_percent = ((total_value / total_initial) - 1) * 100 if total_initial > 0 else 0

        return ConsolidatedSummaryOut(
            total_value=total_value,
            total_cash=total_cash,
            total_invested=total_invested,
            total_realized_pnl=total_realized_pnl,
            total_unrealized_pnl=total_unrealized_pnl,
            total_pnl=total_pnl,
            total_pnl_percent=total_pnl_percent,
            portfolios_count=len(portfolios),
            active_portfolios_count=len([p for p in portfolios if p.is_active]),
            allocation_by_asset_type=asset_type_alloc,
            allocation_by_currency=currency_alloc,
            portfolio_summaries=portfolio_summaries
        )

    def get_portfolio_performance_comparison(self, connection: sqlite3.Connection) -> PortfolioPerformanceComparisonOut:
        summary = self.get_consolidated_summary(connection)
        
        sorted_portfolios = sorted(summary.portfolio_summaries, key=lambda x: x["pnl_percent"], reverse=True)
        
        best = sorted_portfolios[0] if sorted_portfolios else None
        worst = sorted_portfolios[-1] if sorted_portfolios else None
        
        # Risk comparison (simplified: higher equity/crypto weight = higher risk)
        risk_comp = []
        for p in summary.portfolio_summaries:
            risk_level = "Medium"
            if p["type"] in ["SPECULATIVE", "CRYPTO"]:
                risk_level = "High"
            elif p["type"] in ["CORE", "FAMILY"]:
                risk_level = "Low"
            
            risk_comp.append({
                "id": p["id"],
                "name": p["name"],
                "risk_level": risk_level,
                "pnl_percent": p["pnl_percent"]
            })

        return PortfolioPerformanceComparisonOut(
            portfolios=summary.portfolio_summaries,
            best_performer=best,
            worst_performer=worst,
            risk_comparison=risk_comp
        )
