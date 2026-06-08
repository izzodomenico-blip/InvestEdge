from __future__ import annotations

import sqlite3
from collections import deque
from typing import Any

# Aliquote Italia: 26% standard, 12,5% titoli di Stato / ETF obbligazionari governativi.
RATE_STANDARD = 26.0
RATE_BOND = 12.5
BOND_ASSET_TYPES = {"bond", "bond_etf"}
TAX_DISCLAIMER = (
    "Simulazione fiscale indicativa (FIFO, regime amministrato semplificato). "
    "Non sostituisce un commercialista né la normativa ufficiale."
)


def _category(asset_type: str | None) -> str:
    return "bond" if (asset_type or "").lower() in BOND_ASSET_TYPES else "standard"


def _rate(category: str) -> float:
    return RATE_BOND if category == "bond" else RATE_STANDARD


def _year(date_value: str | None) -> int:
    from datetime import datetime

    if date_value and len(date_value) >= 4 and date_value[:4].isdigit():
        return int(date_value[:4])
    return datetime.now().year


def _round(value: float) -> float:
    return round(float(value), 2)


def compute_tax_report(connection: sqlite3.Connection, tax_year: int | None = None) -> dict[str, Any]:
    """Calcola plus/minus realizzate con lot matching FIFO sugli ordini simulati.

    Compensazione perdite per categoria con riporto agli anni successivi (zainetto fiscale
    semplificato). Sola lettura."""
    orders = connection.execute(
        """
        SELECT o.symbol, o.order_type, o.quantity, o.price, o.fees, o.order_date, a.asset_type
        FROM simulated_orders o
        JOIN assets a ON a.id = o.asset_id
        ORDER BY o.order_date ASC, o.id ASC
        """
    ).fetchall()

    lots: dict[str, deque[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []

    for order in orders:
        symbol = order["symbol"]
        quantity = float(order["quantity"] or 0)
        price = float(order["price"] or 0)
        fees = float(order["fees"] or 0)
        if quantity <= 0:
            continue
        symbol_lots = lots.setdefault(symbol, deque())

        if order["order_type"] == "BUY":
            cost_per_unit = price + (fees / quantity if quantity else 0.0)
            symbol_lots.append({"quantity": quantity, "cost_per_unit": cost_per_unit, "date": order["order_date"]})
            continue

        # SELL: abbina FIFO
        remaining = quantity
        proceeds = price * quantity - fees
        cost_basis = 0.0
        matched = 0.0
        open_date = order["order_date"]
        while remaining > 1e-9 and symbol_lots:
            lot = symbol_lots[0]
            take = min(remaining, lot["quantity"])
            cost_basis += take * lot["cost_per_unit"]
            matched += take
            remaining -= take
            lot["quantity"] -= take
            open_date = lot["date"]
            if lot["quantity"] <= 1e-9:
                symbol_lots.popleft()
        if matched <= 0:
            continue
        # proventi proporzionali alla quota effettivamente abbinata
        proceeds_matched = proceeds * (matched / quantity)
        gain = proceeds_matched - cost_basis
        category = _category(order["asset_type"])
        events.append(
            {
                "symbol": symbol,
                "asset_type": order["asset_type"],
                "category": category,
                "sell_date": (order["order_date"] or "")[:10],
                "tax_year": _year(order["order_date"]),
                "quantity": _round(matched),
                "proceeds": _round(proceeds_matched),
                "cost_basis": _round(cost_basis),
                "gain": _round(gain),
                "rate": _rate(category),
                "holding_days": _holding_days(open_date, order["order_date"]),
            }
        )

    years = _summaries_by_year(events)
    open_lots = _open_lots(connection, lots)

    if tax_year is not None:
        events = [event for event in events if event["tax_year"] == tax_year]
        years = [year for year in years if year["tax_year"] == tax_year]

    total_tax_due = _round(sum(year["tax_due"] for year in years))
    total_realized_net = _round(sum(event["gain"] for event in events))

    return {
        "base_currency": "EUR",
        "standard_rate": RATE_STANDARD,
        "bond_rate": RATE_BOND,
        "lot_method": "FIFO",
        "total_tax_due": total_tax_due,
        "total_realized_net": total_realized_net,
        "loss_carryforward": years[-1]["carryforward_remaining"] if years else 0.0,
        "years": years,
        "events": sorted(events, key=lambda event: event["sell_date"], reverse=True),
        "open_lots": open_lots,
        "disclaimer": TAX_DISCLAIMER,
    }


def _summaries_by_year(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year_cat: dict[int, dict[str, list[float]]] = {}
    for event in events:
        by_year_cat.setdefault(event["tax_year"], {"standard": [], "bond": []})[event["category"]].append(event["gain"])

    carryforward = {"standard": 0.0, "bond": 0.0}
    summaries: list[dict[str, Any]] = []
    for year in sorted(by_year_cat):
        gains_total = 0.0
        losses_total = 0.0
        tax_due = 0.0
        carry_used = 0.0
        for category in ("standard", "bond"):
            gains = sum(g for g in by_year_cat[year][category] if g > 0)
            losses = -sum(g for g in by_year_cat[year][category] if g < 0)
            gains_total += gains
            losses_total += losses
            available_losses = losses + carryforward[category]
            taxable = max(0.0, gains - available_losses)
            carry_used += min(gains, available_losses)
            carryforward[category] = max(0.0, available_losses - gains)
            tax_due += taxable * (_rate(category) / 100.0)
        summaries.append(
            {
                "tax_year": year,
                "total_gains": _round(gains_total),
                "total_losses": _round(losses_total),
                "net_realized": _round(gains_total - losses_total),
                "carryforward_used": _round(carry_used),
                "carryforward_remaining": _round(carryforward["standard"] + carryforward["bond"]),
                "tax_due": _round(tax_due),
            }
        )
    return summaries


def _open_lots(connection: sqlite3.Connection, lots: dict[str, deque[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for symbol, symbol_lots in lots.items():
        total_qty = sum(lot["quantity"] for lot in symbol_lots)
        if total_qty <= 1e-9:
            continue
        cost = sum(lot["quantity"] * lot["cost_per_unit"] for lot in symbol_lots)
        price_row = connection.execute(
            """
            SELECT ph.close, a.asset_type
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE UPPER(a.symbol) = UPPER(?)
            ORDER BY ph.date DESC, ph.is_real_data DESC, ph.id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        current_price = float(price_row["close"]) if price_row and price_row["close"] else None
        current_value = current_price * total_qty if current_price else None
        unrealized = (current_value - cost) if current_value is not None else None
        result.append(
            {
                "symbol": symbol,
                "asset_type": price_row["asset_type"] if price_row else None,
                "quantity": _round(total_qty),
                "cost_basis": _round(cost),
                "current_value": _round(current_value) if current_value is not None else None,
                "unrealized_gain": _round(unrealized) if unrealized is not None else None,
            }
        )
    return sorted(result, key=lambda lot: lot["symbol"])


def _holding_days(open_date: str | None, close_date: str | None) -> int:
    from datetime import date

    try:
        start = date.fromisoformat((open_date or "")[:10])
        end = date.fromisoformat((close_date or "")[:10])
        return max((end - start).days, 0)
    except ValueError:
        return 0
