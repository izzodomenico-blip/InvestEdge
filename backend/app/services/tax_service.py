from __future__ import annotations

import sqlite3
from collections import deque
from typing import Any

STANDARD_RATE = 26.0
GOVERNMENT_BOND_RATE = 12.5
CRYPTO_RATE_BY_YEAR = ((2026, 33.0), (0, 26.0))
TAX_CATEGORIES = ("standard", "government_bond", "crypto", "euro_emt")
LOT_EPSILON = 1e-9

# Fonti ufficiali approvate nel piano della Fase 1:
# - art. 3 D.L. 66/2014 (26% ed eccezioni per titoli pubblici):
#   https://www.normattiva.it/uri-res/N2Ls?urn%3Anir%3Astato%3Adecreto.legge%3A2014-04-24%3B66~art3=
# - art. 1, comma 24, L. 207/2024 (cripto 33% dal 2026):
#   https://www.normattiva.it/atto/caricaDettaglioAtto?atto.codiceRedazionale=24G00229
# - art. 68 TUIR (riporto non oltre il quarto periodo successivo):
#   https://www.normattiva.it/uri-res/N2Ls?urn%3Anir%3Apresidente.repubblica%3Adecreto%3A1986-12-22%3B917~art68-com6=
TAX_SOURCES = [
    {
        "id": "dl-66-2014-art-3",
        "title": "Art. 3 D.L. 66/2014",
        "url": (
            "https://www.normattiva.it/uri-res/N2Ls?"
            "urn%3Anir%3Astato%3Adecreto.legge%3A2014-04-24%3B66~art3="
        ),
    },
    {
        "id": "l-207-2024-art-1-c24",
        "title": "Art. 1, comma 24, L. 207/2024",
        "url": "https://www.normattiva.it/atto/caricaDettaglioAtto?atto.codiceRedazionale=24G00229",
    },
    {
        "id": "tuir-art-68-c6",
        "title": "Art. 68, comma 6, TUIR",
        "url": (
            "https://www.normattiva.it/uri-res/N2Ls?"
            "urn%3Anir%3Apresidente.repubblica%3Adecreto%3A1986-12-22%3B917~art68-com6="
        ),
    },
]
TAX_RULES = [
    {
        "tax_category": "standard",
        "from_year": 0,
        "rate": STANDARD_RATE,
        "source_id": "dl-66-2014-art-3",
    },
    {
        "tax_category": "government_bond",
        "from_year": 0,
        "rate": GOVERNMENT_BOND_RATE,
        "source_id": "dl-66-2014-art-3",
    },
    {
        "tax_category": "euro_emt",
        "from_year": 0,
        "rate": GOVERNMENT_BOND_RATE,
        "source_id": "dl-66-2014-art-3",
    },
    {
        "tax_category": "crypto",
        "from_year": 0,
        "rate": 26.0,
        "source_id": "l-207-2024-art-1-c24",
    },
    {
        "tax_category": "crypto",
        "from_year": 2026,
        "rate": 33.0,
        "source_id": "l-207-2024-art-1-c24",
    },
]
TAX_DISCLAIMER = (
    "Stima fiscale semplificata, non dichiarazione. Metodo SIMPLIFIED_FIFO su ordini paper; "
    "non sostituisce un commercialista, un intermediario o la normativa ufficiale."
)
CARRYFORWARD_NOTE = (
    "Le minusvalenze sono conservate per anno d'origine e scadono dopo il quarto periodo "
    "successivo; la simulazione le compensa solo nella stessa categoria fiscale."
)


def _tax_category(value: str | None) -> str:
    category = (value or "standard").lower()
    return category if category in TAX_CATEGORIES else "standard"


def _rate(category: str, year: int) -> float:
    if category == "crypto":
        return next(rate for from_year, rate in CRYPTO_RATE_BY_YEAR if year >= from_year)
    if category in {"government_bond", "euro_emt"}:
        return GOVERNMENT_BOND_RATE
    return STANDARD_RATE


def _year(date_value: str | None) -> int:
    from datetime import datetime

    if date_value and len(date_value) >= 4 and date_value[:4].isdigit():
        return int(date_value[:4])
    return datetime.now().year


def _round(value: float) -> float:
    return round(float(value), 2)


def _frozen_fx(order: sqlite3.Row) -> float:
    currency = str(order["currency"] or "EUR").upper()
    fx_rate = float(order["fx_rate_to_base"] or 0)
    if fx_rate > 0:
        return fx_rate
    if currency == "EUR":
        return 1.0
    raise ValueError(
        f"Cambio storico {currency}/EUR non disponibile per l'ordine fiscale {order['id']}."
    )


def compute_tax_report(connection: sqlite3.Connection, tax_year: int | None = None) -> dict[str, Any]:
    """Stima plus/minus con lotti firmati SIMPLIFIED_FIFO sugli ordini paper.

    Gli eventi usano soltanto prezzo, fee e cambio congelati in ciascun ordine; il cambio
    corrente non viene consultato. Il calcolo e' informativo e non e' una dichiarazione.
    """
    orders = connection.execute(
        """
        SELECT o.id, o.asset_id, o.symbol, COALESCE(o.order_type, o.side) AS order_type,
            o.quantity, o.price, o.fees, o.fees_base, o.currency, o.fx_rate_to_base,
            o.order_date, a.asset_type, a.tax_category
        FROM simulated_orders o
        JOIN assets a ON a.id = o.asset_id
        ORDER BY o.order_date ASC, o.id ASC
        """
    ).fetchall()

    lots: dict[int, deque[dict[str, Any]]] = {}
    events: list[dict[str, Any]] = []

    for order in orders:
        quantity = float(order["quantity"] or 0)
        side = str(order["order_type"] or "").upper()
        if quantity <= 0 or side not in {"BUY", "SELL"}:
            continue

        fx_rate = _frozen_fx(order)
        price = float(order["price"] or 0)
        fees = float(order["fees"] or 0)
        fees_base = float(order["fees_base"] or 0)
        if fees > 0 and fees_base <= 0:
            fees_base = fees * fx_rate
        fee_per_unit = fees / quantity
        fee_base_per_unit = fees_base / quantity
        price_base = price * fx_rate
        close_unit_native = price + fee_per_unit if side == "BUY" else price - fee_per_unit
        close_unit_base = price_base + fee_base_per_unit if side == "BUY" else price_base - fee_base_per_unit

        asset_id = int(order["asset_id"])
        symbol_lots = lots.setdefault(asset_id, deque())
        remaining = quantity
        matched = 0.0
        open_value_native = 0.0
        close_value_native = 0.0
        open_value_base = 0.0
        close_value_base = 0.0
        gain_native = 0.0
        gain_base = 0.0
        open_dates: list[str | None] = []
        open_side: str | None = None

        while remaining > LOT_EPSILON and symbol_lots and symbol_lots[0]["open_side"] != side:
            lot = symbol_lots[0]
            take = min(remaining, float(lot["quantity"]))
            lot_open_native = take * float(lot["open_unit_native"])
            lot_close_native = take * close_unit_native
            lot_open_base = take * float(lot["open_unit_base"])
            lot_close_base = take * close_unit_base
            direction = 1.0 if lot["open_side"] == "BUY" else -1.0

            matched += take
            remaining -= take
            lot["quantity"] -= take
            open_value_native += lot_open_native
            close_value_native += lot_close_native
            open_value_base += lot_open_base
            close_value_base += lot_close_base
            gain_native += direction * (lot_close_native - lot_open_native)
            gain_base += direction * (lot_close_base - lot_open_base)
            open_dates.append(lot["open_date"])
            open_side = str(lot["open_side"])
            if lot["quantity"] <= LOT_EPSILON:
                symbol_lots.popleft()

        if matched > LOT_EPSILON and open_side is not None:
            realization_date = str(order["order_date"] or "")[:10]
            category = _tax_category(order["tax_category"])
            realization_year = _year(order["order_date"])
            proceeds = close_value_base if open_side == "BUY" else open_value_base
            cost_basis = open_value_base if open_side == "BUY" else close_value_base
            applied_rate = _rate(category, realization_year)
            first_open_date = min((date for date in open_dates if date), default=None)
            events.append(
                {
                    "symbol": order["symbol"],
                    "asset_type": order["asset_type"],
                    "tax_category": category,
                    "category": category,
                    "open_side": open_side,
                    "close_side": side,
                    "open_date": (first_open_date or "")[:10],
                    "realization_date": realization_date,
                    "sell_date": realization_date if side == "SELL" else None,
                    "tax_year": realization_year,
                    "quantity": _round(matched),
                    "currency": str(order["currency"] or "EUR").upper(),
                    "base_currency": "EUR",
                    "open_value_native": _round(open_value_native),
                    "close_value_native": _round(close_value_native),
                    "gain_native": _round(gain_native),
                    "open_value_base": _round(open_value_base),
                    "close_value_base": _round(close_value_base),
                    "gain_base": _round(gain_base),
                    "proceeds": _round(proceeds),
                    "cost_basis": _round(cost_basis),
                    "gain": _round(gain_base),
                    "applied_rate": applied_rate,
                    "rate": applied_rate,
                    "holding_days": _holding_days(first_open_date, order["order_date"]),
                }
            )

        if remaining > LOT_EPSILON:
            open_unit_native = price + fee_per_unit if side == "BUY" else price - fee_per_unit
            open_unit_base = price_base + fee_base_per_unit if side == "BUY" else price_base - fee_base_per_unit
            symbol_lots.append(
                {
                    "asset_id": asset_id,
                    "symbol": order["symbol"],
                    "asset_type": order["asset_type"],
                    "tax_category": _tax_category(order["tax_category"]),
                    "currency": str(order["currency"] or "EUR").upper(),
                    "open_side": side,
                    "quantity": remaining,
                    "open_unit_native": open_unit_native,
                    "open_unit_base": open_unit_base,
                    "open_date": order["order_date"],
                }
            )

    all_years = _summaries_by_year(events)
    open_lots = _open_lots(connection, lots)

    if tax_year is not None:
        events = [event for event in events if event["tax_year"] == tax_year]
        years = [year for year in all_years if year["tax_year"] == tax_year]
    else:
        years = all_years

    reference_year = tax_year if tax_year is not None else _year(None)
    carryforward_buckets = _carryforward_as_of(all_years, reference_year)
    total_tax_due = _round(sum(year["tax_due"] for year in years))
    total_realized_net = _round(sum(event["gain_base"] for event in events))

    return {
        "base_currency": "EUR",
        "standard_rate": STANDARD_RATE,
        "bond_rate": GOVERNMENT_BOND_RATE,
        "lot_method": "SIMPLIFIED_FIFO",
        "total_tax_due": total_tax_due,
        "total_realized_net": total_realized_net,
        "loss_carryforward": _round(sum(bucket["remaining"] for bucket in carryforward_buckets)),
        "loss_carryforward_buckets": carryforward_buckets,
        "carryforward_note": CARRYFORWARD_NOTE,
        "tax_rules": TAX_RULES,
        "sources": TAX_SOURCES,
        "classification_warnings": _classification_warnings(connection),
        "years": years,
        "events": sorted(events, key=lambda event: event["realization_date"], reverse=True),
        "open_lots": open_lots,
        "disclaimer": TAX_DISCLAIMER,
    }


def _summaries_by_year(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year_category: dict[int, dict[str, list[float]]] = {}
    for event in events:
        categories = by_year_category.setdefault(
            event["tax_year"],
            {category: [] for category in TAX_CATEGORIES},
        )
        categories[event["tax_category"]].append(float(event["gain_base"]))

    carryforward: dict[str, deque[dict[str, Any]]] = {
        category: deque() for category in TAX_CATEGORIES
    }
    summaries: list[dict[str, Any]] = []
    for year in sorted(by_year_category):
        gains_total = 0.0
        losses_total = 0.0
        tax_due = 0.0
        carry_used = 0.0
        current_year_losses_used = 0.0
        carry_expired = 0.0

        for category in TAX_CATEGORIES:
            buckets = carryforward[category]
            while buckets and year > int(buckets[0]["origin_year"]) + 4:
                carry_expired += float(buckets.popleft()["remaining"])

            values = by_year_category[year][category]
            gains = sum(value for value in values if value > 0)
            losses = -sum(value for value in values if value < 0)
            gains_total += gains
            losses_total += losses
            if losses > LOT_EPSILON:
                buckets.append({"origin_year": year, "remaining": losses})

            remaining_gains = gains
            for bucket in buckets:
                if remaining_gains <= LOT_EPSILON:
                    break
                used = min(remaining_gains, float(bucket["remaining"]))
                bucket["remaining"] -= used
                remaining_gains -= used
                if int(bucket["origin_year"]) < year:
                    carry_used += used
                else:
                    current_year_losses_used += used
            while buckets and float(buckets[0]["remaining"]) <= LOT_EPSILON:
                buckets.popleft()

            tax_due += remaining_gains * (_rate(category, year) / 100.0)

        buckets_snapshot = _loss_buckets(carryforward)
        summaries.append(
            {
                "tax_year": year,
                "total_gains": _round(gains_total),
                "total_losses": _round(losses_total),
                "net_realized": _round(gains_total - losses_total),
                "current_year_losses_used": _round(current_year_losses_used),
                "carryforward_used": _round(carry_used),
                "carryforward_expired": _round(carry_expired),
                "carryforward_remaining": _round(
                    sum(bucket["remaining"] for bucket in buckets_snapshot)
                ),
                "carryforward_buckets": buckets_snapshot,
                "tax_due": _round(tax_due),
            }
        )
    return summaries


def _carryforward_as_of(years: list[dict[str, Any]], reference_year: int) -> list[dict[str, Any]]:
    snapshots = [year for year in years if int(year["tax_year"]) <= reference_year]
    if not snapshots:
        return []
    return [
        bucket
        for bucket in snapshots[-1]["carryforward_buckets"]
        if reference_year <= int(bucket["expires_after_year"])
    ]


def _loss_buckets(carryforward: dict[str, deque[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for category in TAX_CATEGORIES:
        for bucket in carryforward[category]:
            remaining = float(bucket["remaining"])
            if remaining <= LOT_EPSILON:
                continue
            origin_year = int(bucket["origin_year"])
            result.append(
                {
                    "tax_category": category,
                    "origin_year": origin_year,
                    "expires_after_year": origin_year + 4,
                    "remaining": _round(remaining),
                }
            )
    return result


def _open_lots(
    connection: sqlite3.Connection,
    lots: dict[int, deque[dict[str, Any]]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for asset_id, asset_lots in lots.items():
        if not asset_lots:
            continue
        open_side = str(asset_lots[0]["open_side"])
        total_quantity = sum(float(lot["quantity"]) for lot in asset_lots)
        if total_quantity <= LOT_EPSILON:
            continue

        open_value_native = sum(
            float(lot["quantity"]) * float(lot["open_unit_native"]) for lot in asset_lots
        )
        open_value_base = sum(
            float(lot["quantity"]) * float(lot["open_unit_base"]) for lot in asset_lots
        )
        price_row = connection.execute(
            """
            SELECT close
            FROM price_history
            WHERE asset_id = ?
            ORDER BY date DESC, is_real_data DESC, id DESC
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        current_price = float(price_row["close"]) if price_row and price_row["close"] else None
        signed_quantity = total_quantity if open_side == "BUY" else -total_quantity
        current_value_native = current_price * signed_quantity if current_price is not None else None
        current_abs_native = current_price * total_quantity if current_price is not None else None
        unrealized_native = None
        if current_abs_native is not None:
            unrealized_native = (
                current_abs_native - open_value_native
                if open_side == "BUY"
                else open_value_native - current_abs_native
            )

        position = connection.execute(
            "SELECT quantity, current_value_base FROM portfolio_positions WHERE asset_id = ? LIMIT 1",
            (asset_id,),
        ).fetchone()
        current_value_base: float | None = None
        if position and abs(float(position["quantity"] or 0)) > LOT_EPSILON:
            unit_value_base = abs(float(position["current_value_base"])) / abs(float(position["quantity"]))
            current_value_base = unit_value_base * signed_quantity
        elif str(asset_lots[0]["currency"]).upper() == "EUR" and current_value_native is not None:
            current_value_base = current_value_native

        unrealized_base = None
        if current_value_base is not None:
            current_abs_base = abs(current_value_base)
            unrealized_base = (
                current_abs_base - open_value_base
                if open_side == "BUY"
                else open_value_base - current_abs_base
            )

        result.append(
            {
                "symbol": asset_lots[0]["symbol"],
                "asset_type": asset_lots[0]["asset_type"],
                "tax_category": asset_lots[0]["tax_category"],
                "open_side": open_side,
                "currency": asset_lots[0]["currency"],
                "base_currency": "EUR",
                "quantity": _round(signed_quantity),
                "open_value_native": _round(open_value_native),
                "open_value_base": _round(open_value_base),
                "current_value_native": (
                    _round(current_value_native) if current_value_native is not None else None
                ),
                "current_value_base": (
                    _round(current_value_base) if current_value_base is not None else None
                ),
                "unrealized_gain_native": (
                    _round(unrealized_native) if unrealized_native is not None else None
                ),
                "unrealized_gain_base": (
                    _round(unrealized_base) if unrealized_base is not None else None
                ),
                "cost_basis": _round(open_value_base) if open_side == "BUY" else None,
                "current_value": (
                    _round(current_value_base) if current_value_base is not None else None
                ),
                "unrealized_gain": (
                    _round(unrealized_base) if unrealized_base is not None else None
                ),
            }
        )
    return sorted(result, key=lambda lot: lot["symbol"])


def _classification_warnings(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT DISTINCT o.symbol
        FROM simulated_orders o
        JOIN assets a ON a.id = o.asset_id
        WHERE a.tax_category = 'standard' AND a.asset_type IN ('bond', 'bond_etf', 'crypto')
        ORDER BY o.symbol
        """
    ).fetchall()
    if not rows:
        return []
    symbols = ", ".join(str(row["symbol"]) for row in rows)
    return [
        f"Categoria fiscale non verificata per {symbols}: applicata l'aliquota standard del 26%."
    ]


def _holding_days(open_date: str | None, close_date: str | None) -> int:
    from datetime import date

    try:
        start = date.fromisoformat((open_date or "")[:10])
        end = date.fromisoformat((close_date or "")[:10])
        return max((end - start).days, 0)
    except ValueError:
        return 0
