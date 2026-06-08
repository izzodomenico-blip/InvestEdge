from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

import httpx

from backend.app.config import get_settings
from backend.app.models import AssetCreate
from backend.app.services.assets_service import create_asset, get_asset_by_symbol
from backend.app.services.common import now_utc
from backend.app.services.portfolio_engine import PortfolioEngine

portfolio_engine = PortfolioEngine()

# Alias di intestazione accettati (case-insensitive, spazi/underscore normalizzati).
_HEADER_ALIASES: dict[str, set[str]] = {
    "symbol": {"symbol", "ticker", "simbolo"},
    "name": {"name", "nome", "descrizione", "description"},
    "asset_type": {"asset_type", "tipo", "type", "assettype"},
    "quantity": {"quantity", "quantita", "quantità", "qty", "shares", "quote", "numero"},
    "average_price": {
        "average_price",
        "avg_price",
        "averageprice",
        "prezzo_medio",
        "prezzomedio",
        "prezzo medio",
        "pmc",
        "costo_medio",
    },
    "currency": {"currency", "valuta", "ccy"},
}
_VALID_ASSET_TYPES = {"stock", "etf", "crypto", "bond", "bond_etf", "macro", "bond_proxy"}


def _norm_header(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("  ", " ").strip()


def parse_number(value: Any) -> float:
    """Converte numeri in formato europeo o americano. Solleva ValueError se non valido.

    Gestisce: 383.47 / 383,47 / 1,234.56 / 1.234,56 / "€ 383,47" / "$ 1,000.00".
    """
    if value is None or value == "":
        return 0.0
    if isinstance(value, int | float):
        return float(value)

    text = str(value).strip()
    for noise in ("€", "$", "£", " ", " "):
        text = text.replace(noise, "")
    if not text:
        return 0.0

    try:
        return float(text)
    except ValueError:
        pass

    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        # 1.234,56 (IT) -> rimuovi punti, virgola=decimale; 1,234.56 (US) -> rimuovi virgole
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif has_comma:
        text = text.replace(".", "").replace(",", ".") if text.count(",") == 1 else text.replace(",", "")
    elif has_dot and text.count(".") > 1:
        parts = text.split(".")
        if all(len(part) == 3 for part in parts[1:]):
            text = text.replace(".", "")

    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"valore numerico non valido: {value}") from exc


def _cell(row: list[str], mapping: dict[str, int], field: str) -> str:
    idx = mapping.get(field)
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def _map_columns(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, raw in enumerate(header):
        norm = _norm_header(raw)
        for field, aliases in _HEADER_ALIASES.items():
            if field in mapping:
                continue
            if norm in {_norm_header(alias) for alias in aliases}:
                mapping[field] = index
    return mapping


def parse_holdings(csv_text: str) -> dict[str, Any]:
    """Estrae le posizioni dal CSV. Ritorna holdings validi + errori per riga."""
    reader = list(csv.reader(io.StringIO(csv_text)))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return {"holdings": [], "errors": ["Il foglio è vuoto."], "rows_total": 0, "rows_valid": 0, "rows_invalid": 0}

    mapping = _map_columns(rows[0])
    missing = [field for field in ("symbol", "quantity", "average_price") if field not in mapping]
    if missing:
        return {
            "holdings": [],
            "errors": [f"Colonne obbligatorie mancanti: {', '.join(missing)}. Servono: symbol, quantity, average_price."],
            "rows_total": 0,
            "rows_valid": 0,
            "rows_invalid": 0,
        }

    holdings: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, row in enumerate(rows[1:], start=2):
        symbol = _cell(row, mapping, "symbol").upper()
        if not symbol:
            continue
        try:
            quantity = parse_number(_cell(row, mapping, "quantity"))
            average_price = parse_number(_cell(row, mapping, "average_price"))
        except ValueError as exc:
            errors.append(f"Riga {line_no} ({symbol or '?'}): {exc}")
            continue
        if quantity <= 0:
            continue

        asset_type = (_cell(row, mapping, "asset_type") or "stock").lower().replace(" ", "_")
        if asset_type not in _VALID_ASSET_TYPES:
            asset_type = "stock"

        holdings.append(
            {
                "symbol": symbol,
                "name": _cell(row, mapping, "name") or symbol,
                "asset_type": asset_type,
                "quantity": round(quantity, 6),
                "average_price": round(average_price, 6),
                "currency": (_cell(row, mapping, "currency") or "EUR").upper()[:8],
            }
        )

    return {
        "holdings": holdings,
        "errors": errors,
        "rows_total": len(rows) - 1,
        "rows_valid": len(holdings),
        "rows_invalid": len(errors),
    }


def _resolve_csv_url(csv_url: str | None) -> str:
    url = (csv_url or "").strip() or (get_settings().google_sheets_csv_url or "")
    if not url:
        raise ValueError("Nessuna URL CSV configurata. Incolla il link CSV pubblico del foglio o impostalo in backend/.env.")
    return url


def fetch_csv(csv_url: str | None = None) -> str:
    url = _resolve_csv_url(csv_url)
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError(f"Impossibile leggere il foglio: {exc}") from exc
    return response.text


def status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.enable_google_sheets_import,
        "configured": bool(settings.google_sheets_csv_url),
        "csv_url_set": bool(settings.google_sheets_csv_url),
    }


def preview(csv_url: str | None = None) -> dict[str, Any]:
    return parse_holdings(fetch_csv(csv_url))


def apply_import(connection: sqlite3.Connection, csv_url: str | None = None) -> dict[str, Any]:
    parsed = parse_holdings(fetch_csv(csv_url))
    holdings = parsed["holdings"]
    if not holdings:
        raise ValueError("Nessuna posizione valida da importare. Controlla il foglio.")

    now = now_utc()
    created_assets = 0
    connection.execute("SAVEPOINT gs_import")
    try:
        connection.execute("DELETE FROM portfolio_positions")
        for holding in holdings:
            asset = get_asset_by_symbol(connection, holding["symbol"])
            if asset is None:
                created = create_asset(
                    connection,
                    AssetCreate(
                        symbol=holding["symbol"],
                        name=holding["name"],
                        asset_type=holding["asset_type"],
                        currency=holding["currency"],
                    ),
                )
                asset_id = created.id
                created_assets += 1
            else:
                asset_id = asset.id

            invested = round(holding["quantity"] * holding["average_price"], 6)
            connection.execute(
                """
                INSERT INTO portfolio_positions (
                    asset_id, symbol, quantity, average_price, invested_amount,
                    asset_type, currency, opened_at, updated_at, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    holding["symbol"],
                    holding["quantity"],
                    holding["average_price"],
                    invested,
                    holding["asset_type"],
                    holding["currency"],
                    now,
                    now,
                    "Importato da Google Sheets",
                ),
            )
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT gs_import")
        connection.execute("RELEASE SAVEPOINT gs_import")
        raise
    connection.execute("RELEASE SAVEPOINT gs_import")

    summary = portfolio_engine.refresh_portfolio(connection, create_snapshot=True)
    return {
        "imported": len(holdings),
        "created_assets": created_assets,
        "rows_invalid": parsed["rows_invalid"],
        "errors": parsed["errors"],
        "portfolio_value": summary.total_value,
    }
