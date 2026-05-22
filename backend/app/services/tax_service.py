from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.config import get_settings
from backend.app.models.schemas import (
    TaxDashboardSnapshotOut,
    TaxLotOut,
    TaxRealizedEventOut,
    TaxReportOut,
    TaxSettingsOut,
    TaxSettingsUpdateIn,
    TaxSummaryGlobalOut,
    TaxSummaryOut,
)

TAX_DISCLAIMER = (
    "Simulazione fiscale indicativa. Non sostituisce commercialista o normativa fiscale ufficiale."
)


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _tax_year_from_date(value: str | None) -> int:
    if not value:
        return datetime.now().year
    return int(str(value)[:4])


def _round_money(value: float) -> float:
    return round(float(value), 2)


class TaxService:
    def __init__(self) -> None:
        settings = get_settings()
        self.db_path = Path(settings.database_path)
        self.export_dir = self.db_path.parent / "export"
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def ensure_default_settings(self, connection: sqlite3.Connection) -> TaxSettingsOut:
        row = connection.execute("SELECT * FROM tax_settings ORDER BY id ASC LIMIT 1").fetchone()
        if row:
            return self._row_to_settings(row)
        now = _now()
        connection.execute(
            """
            INSERT INTO tax_settings (
                country_code, tax_regime, capital_gain_tax_rate, crypto_tax_rate, dividend_tax_rate,
                lot_matching_method, include_fees_in_cost_basis, base_currency, loss_carryforward_balance,
                created_at, updated_at
            ) VALUES ('IT', 'ITALY_SIMPLIFIED', 26.0, NULL, NULL, 'FIFO', 1, 'EUR', 0, ?, ?)
            """,
            (now, now),
        )
        row = connection.execute("SELECT * FROM tax_settings ORDER BY id ASC LIMIT 1").fetchone()
        return self._row_to_settings(row)

    def get_tax_settings(self, connection: sqlite3.Connection) -> TaxSettingsOut:
        return self.ensure_default_settings(connection)

    def update_tax_settings(self, connection: sqlite3.Connection, payload: TaxSettingsUpdateIn) -> TaxSettingsOut:
        current = self.ensure_default_settings(connection)
        data = payload.model_dump(exclude_unset=True)
        if not data:
            return current
        include_fees = data.pop("include_fees_in_cost_basis", None)
        if include_fees is not None:
            data["include_fees_in_cost_basis"] = 1 if include_fees else 0
        columns = []
        values: list[Any] = []
        for key, value in data.items():
            columns.append(f"{key} = ?")
            values.append(value)
        columns.append("updated_at = ?")
        values.append(_now())
        values.append(current.id)
        connection.execute(
            f"UPDATE tax_settings SET {', '.join(columns)} WHERE id = ?",
            values,
        )
        row = connection.execute("SELECT * FROM tax_settings WHERE id = ?", (current.id,)).fetchone()
        return self._row_to_settings(row)

    def recalculate(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
        tax_year: int | None = None,
        method: str = "FIFO",
    ) -> dict[str, Any]:
        settings = self.ensure_default_settings(connection)
        if method.upper() not in {"FIFO", "LIFO", "AVG_COST"}:
            raise ValueError(f"Metodo lot matching non supportato: {method}")
        if method.upper() != "FIFO":
            raise ValueError("Solo FIFO e implementato in questa versione.")

        portfolio_ids = self._portfolio_ids(connection, portfolio_id)
        for pid in portfolio_ids:
            connection.execute("DELETE FROM tax_realized_events WHERE portfolio_id = ?", (pid,))
            connection.execute("DELETE FROM tax_lots WHERE portfolio_id = ?", (pid,))
            orders = connection.execute(
                """
                SELECT o.*, COALESCE(a.asset_type, 'stock') AS asset_type
                FROM simulated_orders o
                LEFT JOIN assets a ON a.id = o.asset_id
                WHERE o.portfolio_id = ?
                ORDER BY o.order_date ASC, o.id ASC
                """,
                (pid,),
            ).fetchall()
            lots: list[dict[str, Any]] = []
            for order in orders:
                side = (order["order_type"] or order["side"] or "").upper()
                qty = float(order["quantity"])
                price = float(order["price"])
                fees = float(order["fees"] or 0)
                symbol = order["symbol"] or ""
                category = self._tax_category(order["asset_type"])
                if side == "BUY":
                    cost = qty * price + (fees if settings.include_fees_in_cost_basis else 0)
                    now = _now()
                    connection.execute(
                        """
                        INSERT INTO tax_lots (
                            portfolio_id, symbol, buy_order_id, buy_date, quantity_initial,
                            quantity_remaining, buy_price, fees_allocated, cost_basis, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            pid,
                            symbol,
                            int(order["id"]),
                            order["order_date"],
                            qty,
                            qty,
                            price,
                            fees if settings.include_fees_in_cost_basis else 0,
                            _round_money(cost),
                            now,
                            now,
                        ),
                    )
                    lots.append(
                        {
                            "id": int(connection.execute("SELECT last_insert_rowid()").fetchone()[0]),
                            "quantity_remaining": qty,
                            "buy_price": price,
                            "fees_allocated": fees if settings.include_fees_in_cost_basis else 0,
                            "cost_basis": cost,
                            "buy_order_id": int(order["id"]),
                            "buy_date": order["order_date"],
                            "symbol": symbol,
                        }
                    )
                elif side == "SELL":
                    remaining = qty
                    sell_year = _tax_year_from_date(order["order_date"])
                    sell_fee_per_unit = fees / qty if qty else 0.0
                    while remaining > 1e-9 and lots:
                        lot = lots[0]
                        take = min(remaining, float(lot["quantity_remaining"]))
                        init_q = float(
                            connection.execute(
                                "SELECT quantity_initial FROM tax_lots WHERE id = ?", (lot["id"],)
                            ).fetchone()["quantity_initial"]
                        )
                        cost_basis = _round_money(float(lot["cost_basis"]) * (take / init_q) if init_q else 0)
                        proceeds = _round_money(take * price - sell_fee_per_unit * take)
                        realized = _round_money(proceeds - cost_basis)
                        connection.execute(
                            """
                            INSERT INTO tax_realized_events (
                                portfolio_id, symbol, sell_order_id, buy_order_id, sell_date, quantity,
                                buy_price, sell_price, cost_basis, proceeds, fees, realized_pnl,
                                tax_year, tax_category, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                pid,
                                symbol,
                                int(order["id"]),
                                lot["buy_order_id"],
                                order["order_date"],
                                take,
                                float(lot["buy_price"]),
                                price,
                                cost_basis,
                                proceeds,
                                _round_money(fees * take / qty if qty else 0),
                                realized,
                                sell_year,
                                category,
                                _now(),
                            ),
                        )
                        lot["quantity_remaining"] -= take
                        connection.execute(
                            "UPDATE tax_lots SET quantity_remaining = ?, updated_at = ? WHERE id = ?",
                            (lot["quantity_remaining"], _now(), lot["id"]),
                        )
                        if lot["quantity_remaining"] <= 1e-9:
                            lots.pop(0)
                        remaining -= take
                    if remaining > 1e-9:
                        pass  # warning handled in summary

        return {
            "portfolios_processed": len(portfolio_ids),
            "method": method.upper(),
            "tax_year_filter": tax_year,
        }

    def calculate_tax_lots(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
        symbol: str | None = None,
    ) -> list[TaxLotOut]:
        query = "SELECT * FROM tax_lots WHERE quantity_remaining > 0"
        params: list[Any] = []
        if portfolio_id is not None:
            query += " AND portfolio_id = ?"
            params.append(portfolio_id)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        query += " ORDER BY buy_date ASC, id ASC"
        return [self._row_to_lot(r) for r in connection.execute(query, params).fetchall()]

    def calculate_realized_events(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
        tax_year: int | None = None,
        symbol: str | None = None,
    ) -> list[TaxRealizedEventOut]:
        query = "SELECT * FROM tax_realized_events WHERE 1=1"
        params: list[Any] = []
        if portfolio_id is not None:
            query += " AND portfolio_id = ?"
            params.append(portfolio_id)
        if tax_year is not None:
            query += " AND tax_year = ?"
            params.append(tax_year)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        query += " ORDER BY sell_date DESC, id DESC"
        return [self._row_to_event(r) for r in connection.execute(query, params).fetchall()]

    def calculate_realized_gains(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
        tax_year: int | None = None,
    ) -> float:
        year = tax_year or datetime.now().year
        query = "SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM tax_realized_events WHERE realized_pnl > 0"
        params: list[Any] = []
        if portfolio_id is not None:
            query += " AND portfolio_id = ?"
            params.append(portfolio_id)
        query += " AND tax_year = ?"
        params.append(year)
        return _round_money(float(connection.execute(query, params).fetchone()["total"]))

    def calculate_realized_losses(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
        tax_year: int | None = None,
    ) -> float:
        year = tax_year or datetime.now().year
        query = "SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM tax_realized_events WHERE realized_pnl < 0"
        params: list[Any] = []
        if portfolio_id is not None:
            query += " AND portfolio_id = ?"
            params.append(portfolio_id)
        query += " AND tax_year = ?"
        params.append(year)
        return _round_money(float(connection.execute(query, params).fetchone()["total"]))

    def calculate_unrealized_gains(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
    ) -> float:
        lots = self.calculate_tax_lots(connection, portfolio_id=portfolio_id)
        total = 0.0
        for lot in lots:
            row = connection.execute(
                """
                SELECT p.current_price, p.unrealized_pnl
                FROM portfolio_positions p
                WHERE p.portfolio_id = ? AND p.symbol = ? AND p.quantity > 0
                LIMIT 1
                """,
                (lot.portfolio_id, lot.symbol),
            ).fetchone()
            if not row:
                continue
            market_value = float(lot.quantity_remaining) * float(row["current_price"] or lot.buy_price)
            cost = float(lot.cost_basis) * (float(lot.quantity_remaining) / float(lot.quantity_initial))
            total += market_value - cost
        return _round_money(total)

    def calculate_loss_carryforward(self, connection: sqlite3.Connection, tax_year: int | None = None) -> float:
        year = tax_year or datetime.now().year
        rows = connection.execute(
            """
            SELECT tax_year, SUM(realized_pnl) AS net
            FROM tax_realized_events
            WHERE tax_year < ?
            GROUP BY tax_year
            """,
            (year,),
        ).fetchall()
        carry = 0.0
        for row in rows:
            net = float(row["net"] or 0)
            if net < 0:
                carry += net
        settings = self.ensure_default_settings(connection)
        carry += float(settings.loss_carryforward_balance or 0)
        return _round_money(carry)

    def estimate_tax_due(
        self,
        connection: sqlite3.Connection,
        tax_year: int | None = None,
        portfolio_id: int | None = None,
    ) -> float:
        year = tax_year or datetime.now().year
        gains = self.calculate_realized_gains(connection, portfolio_id=portfolio_id, tax_year=year)
        losses = self.calculate_realized_losses(connection, portfolio_id=portfolio_id, tax_year=year)
        net = gains + losses
        carry = self.calculate_loss_carryforward(connection, tax_year=year) if portfolio_id is None else 0.0
        taxable = max(0.0, net + carry)
        settings = self.ensure_default_settings(connection)
        rate = float(settings.capital_gain_tax_rate) / 100.0
        return _round_money(taxable * rate)

    def calculate_tax_summary(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
        tax_year: int | None = None,
    ) -> TaxSummaryOut:
        from backend.app.services.multi_portfolio_service import MultiPortfolioService

        year = tax_year or datetime.now().year
        if portfolio_id is None:
            portfolio_id = MultiPortfolioService().get_active_portfolio(connection).id

        existing = connection.execute(
            "SELECT COUNT(*) AS c FROM tax_lots WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchone()["c"]
        existing += connection.execute(
            "SELECT COUNT(*) AS c FROM tax_realized_events WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchone()["c"]
        if existing == 0:
            self.recalculate(connection, portfolio_id=portfolio_id)

        gains = self.calculate_realized_gains(connection, portfolio_id=portfolio_id, tax_year=year)
        losses = self.calculate_realized_losses(connection, portfolio_id=portfolio_id, tax_year=year)
        net = _round_money(gains + losses)
        unrealized = self.calculate_unrealized_gains(connection, portfolio_id=portfolio_id)
        carry = self.calculate_loss_carryforward(connection, tax_year=year)
        tax_due = self.estimate_tax_due(connection, tax_year=year, portfolio_id=portfolio_id)
        settings = self.ensure_default_settings(connection)

        by_class: dict[str, float] = defaultdict(float)
        by_symbol: dict[str, float] = defaultdict(float)
        for event in self.calculate_realized_events(connection, portfolio_id=portfolio_id, tax_year=year):
            by_class[event.tax_category] += event.realized_pnl
            by_symbol[event.symbol] += event.realized_pnl

        return TaxSummaryOut(
            portfolio_id=portfolio_id,
            tax_year=year,
            country_code=settings.country_code,
            tax_regime=settings.tax_regime,
            total_realized_gains=gains,
            total_realized_losses=losses,
            net_realized_pnl=net,
            estimated_tax_due=tax_due,
            unrealized_pnl=unrealized,
            loss_carryforward=carry,
            breakdown_by_asset_class={k: _round_money(v) for k, v in by_class.items()},
            breakdown_by_symbol={k: _round_money(v) for k, v in by_symbol.items()},
            warnings=self._build_warnings(settings),
            disclaimer=TAX_DISCLAIMER,
        )

    def calculate_multi_portfolio_tax_summary(
        self,
        connection: sqlite3.Connection,
        tax_year: int | None = None,
    ) -> TaxSummaryGlobalOut:
        year = tax_year or datetime.now().year
        rows = connection.execute(
            "SELECT id FROM portfolios WHERE is_archived = 0 ORDER BY id ASC"
        ).fetchall()
        summaries: list[TaxSummaryOut] = []
        for row in rows:
            summaries.append(self.calculate_tax_summary(connection, portfolio_id=int(row["id"]), tax_year=year))

        total_gains = _round_money(sum(s.total_realized_gains for s in summaries))
        total_losses = _round_money(sum(s.total_realized_losses for s in summaries))
        net = _round_money(total_gains + total_losses)
        unrealized = _round_money(sum(s.unrealized_pnl for s in summaries))
        carry = self.calculate_loss_carryforward(connection, tax_year=year)
        tax_due = self.estimate_tax_due(connection, tax_year=year, portfolio_id=None)
        settings = self.ensure_default_settings(connection)

        return TaxSummaryGlobalOut(
            tax_year=year,
            country_code=settings.country_code,
            tax_regime=settings.tax_regime,
            total_realized_gains=total_gains,
            total_realized_losses=total_losses,
            net_realized_pnl=net,
            estimated_tax_due=tax_due,
            unrealized_pnl=unrealized,
            loss_carryforward=carry,
            portfolio_summaries=summaries,
            warnings=self._build_warnings(settings),
            disclaimer=TAX_DISCLAIMER,
        )

    def generate_tax_report(
        self,
        connection: sqlite3.Connection,
        tax_year: int,
        portfolio_id: int | None = None,
        report_type: str = "PORTFOLIO",
    ) -> TaxReportOut:
        settings = self.ensure_default_settings(connection)
        if report_type.upper() == "GLOBAL":
            summary = self.calculate_multi_portfolio_tax_summary(connection, tax_year=tax_year)
            summary_json = summary.model_dump()
            portfolio_id = None
            unrealized = summary.unrealized_pnl
            gains = summary.total_realized_gains
            losses = summary.total_realized_losses
            net = summary.net_realized_pnl
            tax_due = summary.estimated_tax_due
            carry = summary.loss_carryforward
        else:
            if portfolio_id is None:
                from backend.app.services.multi_portfolio_service import MultiPortfolioService

                portfolio_id = MultiPortfolioService().get_active_portfolio(connection).id
            summary = self.calculate_tax_summary(connection, portfolio_id=portfolio_id, tax_year=tax_year)
            summary_json = summary.model_dump()
            unrealized = summary.unrealized_pnl
            gains = summary.total_realized_gains
            losses = summary.total_realized_losses
            net = summary.net_realized_pnl
            tax_due = summary.estimated_tax_due
            carry = summary.loss_carryforward

        cursor = connection.execute(
            """
            INSERT INTO tax_reports (
                portfolio_id, tax_year, report_type, country_code, tax_regime,
                total_realized_gains, total_realized_losses, net_realized_pnl,
                estimated_tax_due, unrealized_pnl, loss_carryforward, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                tax_year,
                report_type.upper(),
                settings.country_code,
                settings.tax_regime,
                gains,
                losses,
                net,
                tax_due,
                unrealized,
                carry,
                json.dumps(summary_json, ensure_ascii=False),
                _now(),
            ),
        )
        row = connection.execute("SELECT * FROM tax_reports WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._row_to_report(row)

    def list_tax_reports(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int | None = None,
        tax_year: int | None = None,
    ) -> list[TaxReportOut]:
        query = "SELECT * FROM tax_reports WHERE 1=1"
        params: list[Any] = []
        if portfolio_id is not None:
            query += " AND portfolio_id = ?"
            params.append(portfolio_id)
        if tax_year is not None:
            query += " AND tax_year = ?"
            params.append(tax_year)
        query += " ORDER BY created_at DESC, id DESC"
        return [self._row_to_report(r) for r in connection.execute(query, params).fetchall()]

    def get_tax_report(self, connection: sqlite3.Connection, report_id: int) -> TaxReportOut:
        row = connection.execute("SELECT * FROM tax_reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            raise ValueError(f"Report fiscale {report_id} non trovato")
        return self._row_to_report(row)

    def export_tax_report(
        self,
        connection: sqlite3.Connection,
        tax_year: int,
        portfolio_id: int | None = None,
        file_format: str = "json",
    ) -> dict[str, Any]:
        report = self.generate_tax_report(
            connection,
            tax_year=tax_year,
            portfolio_id=portfolio_id,
            report_type="PORTFOLIO" if portfolio_id else "GLOBAL",
        )
        summary = json.loads(report.summary_json) if isinstance(report.summary_json, str) else report.summary_json
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"p{portfolio_id}" if portfolio_id else "global"
        fmt = file_format.lower()
        filename = f"tax_report_{tax_year}_{suffix}_{timestamp}.{fmt}"
        dest = self.export_dir / filename

        if fmt == "csv":
            events = self.calculate_realized_events(
                connection, portfolio_id=portfolio_id, tax_year=tax_year
            )
            with dest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "sell_date",
                        "symbol",
                        "quantity",
                        "buy_price",
                        "sell_price",
                        "cost_basis",
                        "proceeds",
                        "realized_pnl",
                        "tax_year",
                        "tax_category",
                    ],
                )
                writer.writeheader()
                for event in events:
                    writer.writerow(event.model_dump())
        else:
            dest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "file_path": str(dest),
            "file_format": fmt.upper(),
            "tax_year": tax_year,
            "portfolio_id": portfolio_id,
            "report_id": report.id,
            "disclaimer": TAX_DISCLAIMER,
        }

    def get_dashboard_tax_snapshot(
        self,
        connection: sqlite3.Connection,
        portfolio_id: int,
    ) -> TaxDashboardSnapshotOut:
        year = datetime.now().year
        try:
            summary = self.calculate_tax_summary(connection, portfolio_id=portfolio_id, tax_year=year)
            return TaxDashboardSnapshotOut(
                tax_year=year,
                realized_pnl_ytd=summary.net_realized_pnl,
                estimated_tax_due=summary.estimated_tax_due,
                unrealized_pnl=summary.unrealized_pnl,
            )
        except Exception:
            return TaxDashboardSnapshotOut(
                tax_year=year,
                realized_pnl_ytd=0.0,
                estimated_tax_due=0.0,
                unrealized_pnl=0.0,
            )

    def match_buy_sell_lots(self, connection: sqlite3.Connection, portfolio_id: int, method: str = "FIFO") -> list[TaxRealizedEventOut]:
        self.recalculate(connection, portfolio_id=portfolio_id, method=method)
        return self.calculate_realized_events(connection, portfolio_id=portfolio_id)

    def calculate_fifo_pnl(self, orders: list[dict[str, Any]], include_fees: bool = True) -> list[dict[str, Any]]:
        lots: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        for order in sorted(orders, key=lambda o: (o.get("order_date", ""), o.get("id", 0))):
            side = str(order.get("order_type", order.get("side", ""))).upper()
            qty = float(order["quantity"])
            price = float(order["price"])
            fees = float(order.get("fees", 0))
            if side == "BUY":
                cost = qty * price + (fees if include_fees else 0)
                lots.append({"qty": qty, "price": price, "cost": cost, "fees": fees})
            elif side == "SELL":
                remaining = qty
                while remaining > 1e-9 and lots:
                    lot = lots[0]
                    take = min(remaining, lot["qty"])
                    unit_cost = lot["cost"] / lot["qty"] if lot["qty"] else 0
                    cost_basis = unit_cost * take
                    proceeds = take * price - (fees * take / qty if qty else 0)
                    events.append(
                        {
                            "quantity": take,
                            "buy_price": lot["price"],
                            "sell_price": price,
                            "cost_basis": _round_money(cost_basis),
                            "proceeds": _round_money(proceeds),
                            "realized_pnl": _round_money(proceeds - cost_basis),
                        }
                    )
                    lot["qty"] -= take
                    if lot["qty"] <= 1e-9:
                        lots.pop(0)
                    remaining -= take
        return events

    def _portfolio_ids(self, connection: sqlite3.Connection, portfolio_id: int | None) -> list[int]:
        if portfolio_id is not None:
            return [portfolio_id]
        rows = connection.execute("SELECT id FROM portfolios ORDER BY id ASC").fetchall()
        return [int(r["id"]) for r in rows]

    def _tax_category(self, asset_type: str | None) -> str:
        normalized = (asset_type or "stock").lower()
        if normalized in {"crypto", "cryptocurrency"}:
            return "CRYPTO"
        if normalized in {"bond", "fixed_income"}:
            return "BOND"
        if normalized in {"etf", "fund"}:
            return "ETF"
        if normalized in {"stock", "equity"}:
            return "STOCK"
        return "OTHER"

    def _build_warnings(self, settings: TaxSettingsOut) -> list[str]:
        warnings = [TAX_DISCLAIMER]
        if settings.crypto_tax_rate is None:
            warnings.append("Tassazione cripto: placeholder/simulazione separata non normata in dettaglio.")
        warnings.append("Obbligazioni: fiscalità complessa non modellata; usare solo come indicazione.")
        warnings.append("Dividendi: non implementati in questa versione (placeholder).")
        return warnings

    def _row_to_settings(self, row: sqlite3.Row) -> TaxSettingsOut:
        return TaxSettingsOut(
            id=row["id"],
            country_code=row["country_code"],
            tax_regime=row["tax_regime"],
            capital_gain_tax_rate=float(row["capital_gain_tax_rate"]),
            crypto_tax_rate=float(row["crypto_tax_rate"]) if row["crypto_tax_rate"] is not None else None,
            dividend_tax_rate=float(row["dividend_tax_rate"]) if row["dividend_tax_rate"] is not None else None,
            lot_matching_method=row["lot_matching_method"],
            include_fees_in_cost_basis=bool(row["include_fees_in_cost_basis"]),
            base_currency=row["base_currency"],
            loss_carryforward_balance=float(row["loss_carryforward_balance"] or 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_lot(self, row: sqlite3.Row) -> TaxLotOut:
        return TaxLotOut(
            id=row["id"],
            portfolio_id=row["portfolio_id"],
            symbol=row["symbol"],
            buy_order_id=row["buy_order_id"],
            buy_date=row["buy_date"],
            quantity_initial=float(row["quantity_initial"]),
            quantity_remaining=float(row["quantity_remaining"]),
            buy_price=float(row["buy_price"]),
            fees_allocated=float(row["fees_allocated"]),
            cost_basis=float(row["cost_basis"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_event(self, row: sqlite3.Row) -> TaxRealizedEventOut:
        return TaxRealizedEventOut(
            id=row["id"],
            portfolio_id=row["portfolio_id"],
            symbol=row["symbol"],
            sell_order_id=row["sell_order_id"],
            buy_order_id=row["buy_order_id"],
            sell_date=row["sell_date"],
            quantity=float(row["quantity"]),
            buy_price=float(row["buy_price"]),
            sell_price=float(row["sell_price"]),
            cost_basis=float(row["cost_basis"]),
            proceeds=float(row["proceeds"]),
            fees=float(row["fees"]),
            realized_pnl=float(row["realized_pnl"]),
            tax_year=int(row["tax_year"]),
            tax_category=row["tax_category"],
            created_at=row["created_at"],
        )

    def _row_to_report(self, row: sqlite3.Row) -> TaxReportOut:
        summary = row["summary_json"]
        if isinstance(summary, str):
            summary = json.loads(summary)
        return TaxReportOut(
            id=row["id"],
            portfolio_id=row["portfolio_id"],
            tax_year=int(row["tax_year"]),
            report_type=row["report_type"],
            country_code=row["country_code"],
            tax_regime=row["tax_regime"],
            total_realized_gains=float(row["total_realized_gains"]),
            total_realized_losses=float(row["total_realized_losses"]),
            net_realized_pnl=float(row["net_realized_pnl"]),
            estimated_tax_due=float(row["estimated_tax_due"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
            loss_carryforward=float(row["loss_carryforward"]),
            summary_json=summary,
            created_at=row["created_at"],
        )
