from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from backend.app.models import (
    OrderSimulationOut,
    PortfolioInitIn,
    PortfolioPositionOut,
    PortfolioRecommendationOut,
    PortfolioSettingsOut,
    PortfolioSnapshotOut,
    PortfolioSummaryOut,
    RiskWarningOut,
    SimulatedOrderIn,
    SimulatedOrderOut,
)
from backend.app.services.common import now_local as _now
from backend.app.services.common import round_safe as _round
from backend.app.services.fx_service import FXQuote, FXRateUnavailable, FXService
from backend.app.services.risk_engine import RiskEngine


@dataclass
class PortfolioEngine:
    """Paper-trading portfolio engine. No real broker actions are performed."""

    risk_engine: RiskEngine = field(default_factory=RiskEngine)
    fx_service: FXService = field(default_factory=FXService)

    def ensure_settings(self, connection: sqlite3.Connection) -> dict[str, float]:
        row = connection.execute("SELECT * FROM portfolio_settings WHERE id = 1").fetchone()
        if row is None:
            now = _now()
            connection.execute(
                """
                INSERT INTO portfolio_settings (
                    id, initial_cash, current_cash, max_single_asset_weight, max_asset_class_weight,
                    default_fee_percent, crypto_max_weight, min_cash_weight, max_cash_weight, created_at, updated_at
                )
                VALUES (1, 100000, 100000, 25, 50, 0.1, 15, 2, 35, ?, ?)
                """,
                (now, now),
            )
            row = connection.execute("SELECT * FROM portfolio_settings WHERE id = 1").fetchone()
        return dict(row)

    def initialize_portfolio(self, connection: sqlite3.Connection, payload: PortfolioInitIn) -> PortfolioSummaryOut:
        now = _now()
        # Savepoint locale: il wipe + reinsert e atomico anche se il chiamante
        # non avvolge la chiamata in db_session. Se l'insert fallisce, i DELETE
        # vengono annullati e il portafoglio precedente resta intatto.
        connection.execute("SAVEPOINT portfolio_init")
        try:
            connection.execute("DELETE FROM portfolio_snapshots")
            connection.execute("DELETE FROM simulated_orders")
            connection.execute("DELETE FROM portfolio_positions")
            connection.execute(
                """
                INSERT INTO portfolio_settings (
                    id, initial_cash, current_cash, max_single_asset_weight, max_asset_class_weight,
                    default_fee_percent, crypto_max_weight, min_cash_weight, max_cash_weight, created_at, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, 15, 2, 35, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    initial_cash = excluded.initial_cash,
                    current_cash = excluded.current_cash,
                    max_single_asset_weight = excluded.max_single_asset_weight,
                    max_asset_class_weight = excluded.max_asset_class_weight,
                    default_fee_percent = excluded.default_fee_percent,
                    updated_at = excluded.updated_at
                """,
                (
                    payload.initial_cash,
                    payload.initial_cash,
                    payload.max_single_asset_weight,
                    payload.max_asset_class_weight,
                    payload.default_fee_percent,
                    now,
                    now,
                ),
            )
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT portfolio_init")
            connection.execute("RELEASE SAVEPOINT portfolio_init")
            raise
        connection.execute("RELEASE SAVEPOINT portfolio_init")
        self.refresh_portfolio(connection, create_snapshot=True)
        return self.get_summary(connection)

    def replace_positions(
        self,
        connection: sqlite3.Connection,
        items: list[dict[str, Any]],
    ) -> PortfolioSummaryOut:
        """Sostituisce tutte le posizioni con quelle fornite e ricalcola il portafoglio.

        Ogni item richiede: asset_id, symbol, quantity, average_price.
        Opzionali: asset_type, currency, notes. Operazione atomica (SAVEPOINT)."""
        now = _now()
        connection.execute("SAVEPOINT replace_positions")
        try:
            connection.execute("DELETE FROM portfolio_positions")
            for item in items:
                quantity = float(item["quantity"])
                average_price = float(item["average_price"])
                currency = str(item.get("currency", "EUR")).upper()
                fx_quote = self.fx_service.get_rate(connection, currency)
                invested = _round(quantity * average_price)
                average_price_base = _round(average_price * fx_quote.rate)
                invested_base = _round(quantity * average_price_base)
                connection.execute(
                    """
                    INSERT INTO portfolio_positions (
                        asset_id, symbol, quantity, average_price, fx_rate_to_base,
                        average_price_base, invested_amount, invested_amount_base,
                        asset_type, currency, opened_at, updated_at, notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["asset_id"],
                        item["symbol"],
                        quantity,
                        average_price,
                        fx_quote.rate,
                        average_price_base,
                        invested,
                        invested_base,
                        item.get("asset_type"),
                        currency,
                        now,
                        now,
                        item.get("notes"),
                    ),
                )
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT replace_positions")
            connection.execute("RELEASE SAVEPOINT replace_positions")
            raise
        connection.execute("RELEASE SAVEPOINT replace_positions")
        return self.refresh_portfolio(connection, create_snapshot=True)

    def _asset(self, connection: sqlite3.Connection, symbol: str) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT id, symbol, asset_type, currency, risk_level
            FROM assets
            WHERE UPPER(symbol) = UPPER(?)
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")
        return row

    def _latest_price(self, connection: sqlite3.Connection, asset_id: int) -> float:
        row = connection.execute(
            """
            SELECT close
            FROM price_history
            WHERE asset_id = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Prezzo non disponibile per questo asset.")
        return float(row["close"])

    def _fee(self, settings: dict[str, Any], gross_amount: float, explicit_fees: float | None) -> float:
        if explicit_fees is not None:
            return float(explicit_fees)
        return gross_amount * (float(settings["default_fee_percent"]) / 100)

    def _position_row(self, connection: sqlite3.Connection, asset_id: int) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT *
            FROM portfolio_positions
            WHERE asset_id = ?
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()

    def _execution_fx_quote(self, connection: sqlite3.Connection, currency: str) -> FXQuote:
        quote = self.fx_service.get_rate(connection, currency)
        if quote.quality == "stale":
            raise FXRateUnavailable(
                f"Cambio {quote.from_currency}/{quote.to_currency} obsoleto: ordine simulato bloccato."
            )
        return quote

    def simulate_order(self, connection: sqlite3.Connection, payload: SimulatedOrderIn) -> OrderSimulationOut:
        settings = self.ensure_settings(connection)
        asset = self._asset(connection, payload.symbol)
        fx_quote = self._execution_fx_quote(connection, str(asset["currency"]))
        price = float(payload.price) if payload.price is not None else self._latest_price(connection, asset["id"])
        gross_amount = float(payload.quantity) * price
        fees = self._fee(settings, gross_amount, payload.fees)
        gross_amount_base = gross_amount * fx_quote.rate
        fees_base = fees * fx_quote.rate
        order_type = payload.order_type
        now = _now()

        if order_type == "BUY":
            net_amount = gross_amount + fees
            net_amount_base = gross_amount_base + fees_base
            if float(settings["current_cash"]) < net_amount_base:
                raise ValueError("Cash insufficiente per completare il BUY simulato.")
        else:
            net_amount = gross_amount - fees
            net_amount_base = gross_amount_base - fees_base
        self._apply_order(
            connection,
            asset,
            order_type,
            float(payload.quantity),
            price,
            fees,
            fees_base,
            fx_quote.rate,
            bool(payload.allow_short),
            now,
        )

        cursor = connection.execute(
            """
            INSERT INTO simulated_orders (
                asset_id, symbol, order_type, side, quantity, price, fees, currency,
                fx_rate_to_base, gross_amount, gross_amount_base, net_amount, net_amount_base,
                fees_base, order_date, note, strategy_tag, status, executed_at, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SIMULATED', ?, ?)
            """,
            (
                asset["id"],
                asset["symbol"],
                order_type,
                order_type,
                payload.quantity,
                price,
                fees,
                asset["currency"],
                fx_quote.rate,
                gross_amount,
                gross_amount_base,
                net_amount,
                net_amount_base,
                fees_base,
                now,
                payload.note,
                payload.strategy_tag,
                now,
                payload.note,
            ),
        )
        self.refresh_portfolio(connection, create_snapshot=True)
        order = self.get_order(connection, int(cursor.lastrowid))
        updated_position = self.get_position(connection, asset["id"])
        summary = self.get_summary(connection)
        return OrderSimulationOut(
            order=order,
            updated_position=updated_position,
            updated_portfolio_summary=summary,
            warnings=summary.risk_warnings,
        )

    def _apply_order(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        side: str,
        quantity: float,
        price: float,
        fees: float,
        fees_base: float,
        fx_rate_to_base: float,
        allow_short: bool,
        now: str,
    ) -> None:
        """Applica un ordine al modello a quantita' con SEGNO (long e short).

        ``quantity`` e' sempre > 0; ``side`` (BUY/SELL) ne determina il verso.
        Una posizione con quantity < 0 e' uno short. P&L non realizzato =
        (prezzo - medio) * quantity, corretto in entrambi i versi: uno short
        guadagna se il prezzo scende e perde (in teoria senza limite) se sale.
        Gestisce: apertura, incremento, riduzione/chiusura e inversione (flip).
        """
        position = self._position_row(connection, asset["id"])
        q0 = float(position["quantity"]) if position else 0.0
        avg0 = float(position["average_price"]) if position else 0.0
        avg_base0 = float(position["average_price_base"]) if position else 0.0
        realized0 = float(position["realized_pnl"]) if position else 0.0
        realized_base0 = float(position["realized_pnl_base"]) if position else 0.0

        qty = float(quantity)
        delta = qty if side == "BUY" else -qty
        q1 = q0 + delta

        # Short solo se esplicitamente abilitato. Senza, una SELL puo' al massimo
        # chiudere il long posseduto; un piccolo sforamento da arrotondamento
        # ("Vendi tutto") viene limitato, non trasformato in short.
        if side == "SELL" and not allow_short:
            available = max(0.0, q0)
            if qty > available + 1e-6:
                raise ValueError("Quantita insufficiente per completare il SELL simulato.")
            qty = min(qty, available)
            delta = -qty
            q1 = q0 + delta

        price_base = price * fx_rate_to_base
        realized_delta = -fees  # le commissioni sono sempre un costo realizzato
        realized_base_delta = -fees_base
        same_direction = q0 == 0.0 or (q0 > 0 and delta > 0) or (q0 < 0 and delta < 0)
        if same_direction:
            denom = abs(q0) + qty
            new_avg = ((avg0 * abs(q0)) + (price * qty)) / denom if denom > 0 else price
            new_avg_base = (
                ((avg_base0 * abs(q0)) + (price_base * qty)) / denom if denom > 0 else price_base
            )
        elif abs(delta) <= abs(q0) + 1e-9:
            # riduzione/chiusura parziale: realizza P&L sulla parte chiusa
            direction = 1.0 if q0 > 0 else -1.0
            realized_delta += (price - avg0) * direction * qty
            realized_base_delta += (price_base - avg_base0) * direction * qty
            new_avg = avg0
            new_avg_base = avg_base0
        else:
            # inversione: chiude tutta q0, riapre il residuo al prezzo dell'ordine
            direction = 1.0 if q0 > 0 else -1.0
            realized_delta += (price - avg0) * direction * abs(q0)
            realized_base_delta += (price_base - avg_base0) * direction * abs(q0)
            new_avg = price
            new_avg_base = price_base

        # Snap a zero del residuo (anche da "Vendi tutto" arrotondato): la posizione
        # si chiude e sparisce (il filtro la nasconde).
        if abs(q1) <= 1e-6:
            q1 = 0.0
            new_avg = 0.0
            new_avg_base = 0.0

        invested = new_avg * q1  # firmato: negativo per gli short
        invested_base = new_avg_base * q1
        current_value = q1 * price
        current_value_base = q1 * price_base

        if position is None:
            connection.execute(
                """
                INSERT INTO portfolio_positions (
                    asset_id, symbol, quantity, average_price, fx_rate_to_base,
                    average_price_base, invested_amount, invested_amount_base, current_price,
                    current_value, current_value_base, realized_pnl, realized_pnl_base,
                    unrealized_pnl, unrealized_pnl_base, unrealized_pnl_percent,
                    weight_percent, asset_type, currency, opened_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?, ?, ?)
                """,
                (
                    asset["id"], asset["symbol"], q1, new_avg, fx_rate_to_base,
                    new_avg_base, invested, invested_base, price, current_value,
                    current_value_base, realized_delta, realized_base_delta,
                    asset["asset_type"], asset["currency"], now, now,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE portfolio_positions
                SET quantity = ?, average_price = ?, fx_rate_to_base = ?, average_price_base = ?,
                    invested_amount = ?, invested_amount_base = ?, current_price = ?,
                    current_value = ?, current_value_base = ?, realized_pnl = ?,
                    realized_pnl_base = ?, asset_type = ?, currency = ?, updated_at = ?
                WHERE asset_id = ?
                """,
                (
                    q1, new_avg, fx_rate_to_base, new_avg_base, invested, invested_base,
                    price, current_value, current_value_base, realized0 + realized_delta,
                    realized_base0 + realized_base_delta, asset["asset_type"],
                    asset["currency"], now, asset["id"],
                ),
            )

        # BUY toglie cash (qty*price + fee), SELL aggiunge cash (qty*price - fee),
        # anche quando apre uno short (incassi i proventi della vendita allo scoperto).
        cash_delta = (
            -(qty * price_base + fees_base) if side == "BUY" else (qty * price_base - fees_base)
        )
        connection.execute(
            "UPDATE portfolio_settings SET current_cash = current_cash + ?, updated_at = ? WHERE id = 1",
            (cash_delta, now),
        )

    def refresh_portfolio(self, connection: sqlite3.Connection, create_snapshot: bool = True) -> PortfolioSummaryOut:
        settings = self.ensure_settings(connection)
        rows = connection.execute("SELECT * FROM portfolio_positions").fetchall()

        active_values: dict[int, float] = {}
        invested_value = 0.0
        for row in rows:
            quantity = float(row["quantity"])
            if abs(quantity) <= 1e-9:
                connection.execute(
                    """
                    UPDATE portfolio_positions
                    SET invested_amount = 0, invested_amount_base = 0,
                        current_value = 0, current_value_base = 0,
                        unrealized_pnl = 0, unrealized_pnl_base = 0,
                        unrealized_pnl_percent = 0, weight_percent = 0, updated_at = ?
                    WHERE id = ?
                    """,
                    (_now(), row["id"]),
                )
                continue

            current_price = self._latest_price(connection, row["asset_id"])
            fx_quote = self.fx_service.get_rate(connection, str(row["currency"]))
            current_value = quantity * current_price
            invested_amount = float(row["invested_amount"])
            average_price_base = float(row["average_price_base"])
            if average_price_base <= 0:
                raise FXRateUnavailable(
                    f"Base di costo EUR storica non disponibile per {row['symbol']}: "
                    "refresh del portafoglio bloccato."
                )
            invested_amount_base = average_price_base * quantity
            current_value_base = current_value * fx_quote.rate
            # Vale per long (qty>0) e short (qty<0): invested_amount e' firmato,
            # quindi current_value - invested = (prezzo - medio) * quantity.
            unrealized = current_value - invested_amount
            unrealized_base = current_value_base - invested_amount_base
            unrealized_percent = (unrealized / abs(invested_amount)) * 100 if abs(invested_amount) > 1e-9 else 0.0
            active_values[int(row["id"])] = current_value_base
            invested_value += current_value_base
            connection.execute(
                """
                UPDATE portfolio_positions
                SET fx_rate_to_base = ?, average_price_base = ?,
                    invested_amount_base = ?, current_price = ?, current_value = ?,
                    current_value_base = ?, unrealized_pnl = ?, unrealized_pnl_base = ?,
                    unrealized_pnl_percent = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    fx_quote.rate,
                    average_price_base,
                    invested_amount_base,
                    current_price,
                    current_value,
                    current_value_base,
                    unrealized,
                    unrealized_base,
                    unrealized_percent,
                    _now(),
                    row["id"],
                ),
            )

        total_value = float(settings["current_cash"]) + invested_value
        for row_id, current_value in active_values.items():
            weight = (abs(current_value) / total_value) * 100 if total_value > 0 else 0.0
            connection.execute("UPDATE portfolio_positions SET weight_percent = ? WHERE id = ?", (weight, row_id))

        summary = self.get_summary(connection, include_snapshot=False)
        if create_snapshot:
            self.create_snapshot(connection, summary)
        return summary

    def create_snapshot(self, connection: sqlite3.Connection, summary: PortfolioSummaryOut) -> None:
        connection.execute(
            """
            INSERT INTO portfolio_snapshots (
                snapshot_date, base_currency, total_value, invested_value, cash, realized_pnl,
                unrealized_pnl, total_pnl, total_pnl_percent, created_at
            )
            VALUES (?, 'EUR', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                summary.total_value,
                summary.invested_value,
                summary.cash,
                summary.realized_pnl,
                summary.unrealized_pnl,
                summary.total_pnl,
                summary.total_pnl_percent,
                _now(),
            ),
        )

    def get_summary(self, connection: sqlite3.Connection, include_snapshot: bool = True) -> PortfolioSummaryOut:
        unresolved_position = connection.execute(
            """
            SELECT symbol
            FROM portfolio_positions
            WHERE UPPER(currency) <> 'EUR' AND fx_rate_to_base <= 0
            LIMIT 1
            """
        ).fetchone()
        if unresolved_position is not None:
            raise FXRateUnavailable(
                f"Contabilita EUR storica non disponibile per {unresolved_position['symbol']}: "
                "riepilogo del portafoglio bloccato."
            )

        settings = self.ensure_settings(connection)
        positions = self.list_positions(connection)
        cash = float(settings["current_cash"])
        invested_value = sum(position.current_value_base for position in positions)
        realized_pnl = float(
            connection.execute(
                "SELECT COALESCE(SUM(realized_pnl_base), 0) AS total FROM portfolio_positions"
            ).fetchone()["total"]
        )
        unrealized_pnl = sum(position.unrealized_pnl_base for position in positions)
        total_value = cash + invested_value
        total_pnl = realized_pnl + unrealized_pnl
        initial_cash = float(settings["initial_cash"])
        total_pnl_percent = (total_pnl / initial_cash) * 100 if initial_cash > 0 else 0
        allocation_by_asset_type = self.allocation_by_asset_type(positions, total_value)
        allocation_by_currency = self.allocation_by_currency(positions, total_value)
        risk_warnings = [
            RiskWarningOut(**warning)
            for warning in self.risk_engine.evaluate_portfolio(
                cash=cash,
                total_value=total_value,
                positions=[position.model_dump() for position in positions],
                allocation_by_asset_type=allocation_by_asset_type,
                settings=dict(settings),
            )
        ]
        # Avviso dedicato per ogni posizione short: la perdita e' teoricamente illimitata.
        for position in positions:
            if position.quantity < 0:
                risk_warnings.append(
                    RiskWarningOut(
                        level="HIGH",
                        code="SHORT_RISK",
                        message=(
                            f"Short su {position.symbol}: se il prezzo sale la perdita non ha "
                            "un tetto massimo. Gestisci tu il rischio (es. ricopri con un BUY)."
                        ),
                        symbol=position.symbol,
                    )
                )

        return PortfolioSummaryOut(
            cash=_round(cash),
            total_value=_round(total_value),
            invested_value=_round(invested_value),
            realized_pnl=_round(realized_pnl),
            unrealized_pnl=_round(unrealized_pnl),
            total_pnl=_round(total_pnl),
            total_pnl_percent=_round(total_pnl_percent),
            positions=positions,
            allocation_by_asset_type=allocation_by_asset_type,
            allocation_by_currency=allocation_by_currency,
            risk_warnings=risk_warnings,
            settings=self._settings_out(settings),
        )

    def _settings_out(self, row: dict[str, Any]) -> PortfolioSettingsOut:
        return PortfolioSettingsOut(
            initial_cash=float(row["initial_cash"]),
            current_cash=float(row["current_cash"]),
            max_single_asset_weight=float(row["max_single_asset_weight"]),
            max_asset_class_weight=float(row["max_asset_class_weight"]),
            default_fee_percent=float(row["default_fee_percent"]),
            crypto_max_weight=float(row["crypto_max_weight"]),
            min_cash_weight=float(row["min_cash_weight"]),
            max_cash_weight=float(row["max_cash_weight"]),
        )

    def list_positions(self, connection: sqlite3.Connection) -> list[PortfolioPositionOut]:
        rows = connection.execute(
            """
            SELECT
                pp.*,
                a.name AS asset_name,
                a.isin AS asset_isin,
                sig.signal AS technical_signal
            FROM portfolio_positions pp
            LEFT JOIN assets a ON a.id = pp.asset_id
            LEFT JOIN signals sig ON sig.id = (
                SELECT s.id FROM signals s
                WHERE s.asset_id = pp.asset_id
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT 1
            )
            WHERE pp.quantity > 1e-9 OR pp.quantity < -1e-9
            ORDER BY ABS(pp.current_value_base) DESC
            """
        ).fetchall()
        recommendations = {item.symbol: item.final_recommendation for item in self.recommendations(connection)}
        return [self._position_out(row, recommendations.get(row["symbol"])) for row in rows]

    def get_position(self, connection: sqlite3.Connection, asset_id: int) -> PortfolioPositionOut | None:
        row = connection.execute(
            """
            SELECT pp.*, a.name AS asset_name, a.isin AS asset_isin, sig.signal AS technical_signal
            FROM portfolio_positions pp
            LEFT JOIN assets a ON a.id = pp.asset_id
            LEFT JOIN signals sig ON sig.id = (
                SELECT s.id FROM signals s
                WHERE s.asset_id = pp.asset_id
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT 1
            )
            WHERE pp.asset_id = ? AND (pp.quantity > 1e-9 OR pp.quantity < -1e-9)
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if row is None:
            return None
        recommendations = {item.symbol: item.final_recommendation for item in self.recommendations(connection)}
        return self._position_out(row, recommendations.get(row["symbol"]))

    def _position_out(self, row: sqlite3.Row, recommendation: str | None = None) -> PortfolioPositionOut:
        keys = row.keys()
        return PortfolioPositionOut(
            id=row["id"],
            asset_id=row["asset_id"],
            symbol=row["symbol"],
            name=row["asset_name"] if "asset_name" in keys else None,
            isin=row["asset_isin"] if "asset_isin" in keys else None,
            asset_type=row["asset_type"],
            quantity=round(float(row["quantity"]), 8),
            average_price=_round(row["average_price"]),
            average_price_base=_round(row["average_price_base"]),
            invested_amount=_round(row["invested_amount"]),
            invested_amount_base=_round(row["invested_amount_base"]),
            current_price=_round(row["current_price"]),
            current_value=_round(row["current_value"]),
            current_value_base=_round(row["current_value_base"]),
            realized_pnl=_round(row["realized_pnl"]),
            realized_pnl_base=_round(row["realized_pnl_base"]),
            unrealized_pnl=_round(row["unrealized_pnl"]),
            unrealized_pnl_base=_round(row["unrealized_pnl_base"]),
            unrealized_pnl_percent=_round(row["unrealized_pnl_percent"]),
            weight_percent=_round(row["weight_percent"]),
            currency=row["currency"],
            fx_rate_to_base=_round(row["fx_rate_to_base"]),
            technical_signal=row["technical_signal"],
            recommendation=recommendation,
        )

    def allocation_by_asset_type(self, positions: list[PortfolioPositionOut], total_value: float) -> dict[str, float]:
        allocation: dict[str, float] = {}
        if total_value <= 0:
            return allocation
        for position in positions:
            allocation[position.asset_type] = allocation.get(position.asset_type, 0.0) + (
                abs(position.current_value_base) / total_value
            ) * 100
        return {key: _round(value) for key, value in allocation.items()}

    def allocation_by_currency(self, positions: list[PortfolioPositionOut], total_value: float) -> dict[str, float]:
        allocation: dict[str, float] = {}
        if total_value <= 0:
            return allocation
        for position in positions:
            allocation[position.currency] = allocation.get(position.currency, 0.0) + (
                abs(position.current_value_base) / total_value
            ) * 100
        return {key: _round(value) for key, value in allocation.items()}

    def get_order(self, connection: sqlite3.Connection, order_id: int) -> SimulatedOrderOut:
        row = connection.execute(
            """
            SELECT id, asset_id, symbol, COALESCE(order_type, side) AS order_type, quantity, price, fees,
                fees_base, currency, fx_rate_to_base, gross_amount, gross_amount_base,
                net_amount, net_amount_base, COALESCE(order_date, executed_at, created_at) AS order_date,
                COALESCE(note, notes) AS note, strategy_tag
            FROM simulated_orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Ordine non trovato.")
        return self._order_out(row)

    def list_orders(self, connection: sqlite3.Connection) -> list[SimulatedOrderOut]:
        rows = connection.execute(
            """
            SELECT id, asset_id, symbol, COALESCE(order_type, side) AS order_type, quantity, price, fees,
                fees_base, currency, fx_rate_to_base, gross_amount, gross_amount_base,
                net_amount, net_amount_base, COALESCE(order_date, executed_at, created_at) AS order_date,
                COALESCE(note, notes) AS note, strategy_tag
            FROM simulated_orders
            ORDER BY order_date DESC, id DESC
            """
        ).fetchall()
        return [self._order_out(row) for row in rows]

    def _order_out(self, row: sqlite3.Row) -> SimulatedOrderOut:
        currency = str(row["currency"]).upper()
        fx_rate_to_base = float(row["fx_rate_to_base"])
        if currency != "EUR" and fx_rate_to_base <= 0:
            raise FXRateUnavailable(
                f"Cambio storico {currency}/EUR non disponibile: storico ordini bloccato."
            )
        return SimulatedOrderOut(
            id=row["id"],
            asset_id=row["asset_id"],
            symbol=row["symbol"],
            order_type=row["order_type"],
            quantity=_round(row["quantity"]),
            price=_round(row["price"]),
            fees=_round(row["fees"]),
            fees_base=_round(row["fees_base"]),
            gross_amount=_round(row["gross_amount"]),
            gross_amount_base=_round(row["gross_amount_base"]),
            net_amount=_round(row["net_amount"]),
            net_amount_base=_round(row["net_amount_base"]),
            currency=currency,
            fx_rate_to_base=_round(fx_rate_to_base),
            order_date=row["order_date"],
            note=row["note"],
            strategy_tag=row["strategy_tag"],
        )

    def list_snapshots(self, connection: sqlite3.Connection) -> list[PortfolioSnapshotOut]:
        rows = connection.execute(
            """
            SELECT *
            FROM portfolio_snapshots
            WHERE base_currency = 'EUR'
            ORDER BY snapshot_date ASC, id ASC
            """
        ).fetchall()
        return [
            PortfolioSnapshotOut(
                id=row["id"],
                snapshot_date=row["snapshot_date"],
                total_value=_round(row["total_value"]),
                invested_value=_round(row["invested_value"]),
                cash=_round(row["cash"]),
                realized_pnl=_round(row["realized_pnl"]),
                unrealized_pnl=_round(row["unrealized_pnl"]),
                total_pnl=_round(row["total_pnl"]),
                total_pnl_percent=_round(row["total_pnl_percent"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def recommendations(self, connection: sqlite3.Connection) -> list[PortfolioRecommendationOut]:
        settings = self.ensure_settings(connection)
        summary_positions = self._raw_positions_for_recommendations(connection)
        total_value = float(settings["current_cash"]) + sum(
            float(item["current_value_base"] or 0) for item in summary_positions
        )
        weights = {
            item["symbol"]: (
                (abs(float(item["current_value_base"] or 0)) / total_value) * 100
                if total_value > 0
                else 0
            )
            for item in summary_positions
        }
        class_weights: dict[str, float] = {}
        for item in summary_positions:
            class_weights[item["asset_type"]] = class_weights.get(item["asset_type"], 0.0) + weights[item["symbol"]]

        assets = connection.execute(
            """
            SELECT a.id, a.symbol, a.asset_type, a.risk_level, sig.signal, sig.score
            FROM assets a
            LEFT JOIN signals sig ON sig.id = (
                SELECT s.id FROM signals s
                WHERE s.asset_id = a.id
                ORDER BY s.created_at DESC, s.id DESC
                LIMIT 1
            )
            ORDER BY a.symbol
            """
        ).fetchall()

        result: list[PortfolioRecommendationOut] = []
        for asset in assets:
            weight = weights.get(asset["symbol"], 0.0)
            recommendation, reason = self.risk_engine.final_recommendation(
                technical_signal=asset["signal"],
                technical_score=asset["score"],
                portfolio_weight=weight,
                asset_type=asset["asset_type"],
                risk_level=asset["risk_level"],
                settings=dict(settings),
                asset_class_weight=class_weights.get(asset["asset_type"], 0.0),
            )
            result.append(
                PortfolioRecommendationOut(
                    symbol=asset["symbol"],
                    technical_signal=asset["signal"],
                    technical_score=asset["score"],
                    portfolio_weight=_round(weight),
                    final_recommendation=recommendation,
                    reason=reason,
                )
            )
        return result

    def _raw_positions_for_recommendations(self, connection: sqlite3.Connection) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT symbol, asset_type, current_value_base
            FROM portfolio_positions
            WHERE quantity > 0
            """
        ).fetchall()
