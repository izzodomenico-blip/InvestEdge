from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import sqlite3
from dataclasses import asdict
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from backend.app.config import get_settings
from backend.app.models import AssetCreate
from backend.app.services.assets_service import create_asset, get_asset_by_symbol
from backend.app.services.instrument_resolution_service import (
    InstrumentResolutionService,
    ResolutionSnapshot,
)
from backend.app.services.portfolio_engine import PortfolioEngine

portfolio_engine = PortfolioEngine()
instrument_resolution_service = InstrumentResolutionService()

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
_TRUSTED_GOOGLE_HOSTS = {"docs.google.com", "drive.google.com"}
_GOOGLEUSERCONTENT_SUFFIX = ".googleusercontent.com"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 3
_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024


class ImportDisabledError(ValueError):
    pass


class StaleImportError(ValueError):
    pass


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

        asset_type_cell = _cell(row, mapping, "asset_type")
        currency_cell = _cell(row, mapping, "currency")
        asset_type = (asset_type_cell or "stock").lower().replace(" ", "_")
        if asset_type not in _VALID_ASSET_TYPES:
            asset_type = "stock"

        holdings.append(
            {
                "symbol": symbol,
                "name": _cell(row, mapping, "name") or symbol,
                "asset_type": asset_type,
                "quantity": round(quantity, 6),
                "average_price": round(average_price, 6),
                "currency": (currency_cell or "EUR").upper()[:8],
                "asset_type_explicit": bool(asset_type_cell),
                "currency_explicit": bool(currency_cell),
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
    return _validate_csv_url(url)


def _require_import_enabled() -> None:
    if not get_settings().enable_google_sheets_import:
        raise ImportDisabledError("Import Google Sheets disabilitato dalla configurazione.")


def _validate_csv_url(url: str) -> str:
    invalid_url = False
    try:
        parsed = urlsplit(url)
        port = parsed.port
        hostname = (parsed.hostname or "").lower()
    except ValueError:
        invalid_url = True
    if invalid_url:
        raise ValueError("URL Google Sheets non valida o non attendibile.")

    googleusercontent_subdomain = (
        len(hostname) > len(_GOOGLEUSERCONTENT_SUFFIX)
        and hostname.endswith(_GOOGLEUSERCONTENT_SUFFIX)
    )
    trusted_host = hostname in _TRUSTED_GOOGLE_HOSTS or googleusercontent_subdomain
    if (
        parsed.scheme.lower() != "https"
        or not trusted_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("URL Google Sheets non valida o non attendibile.")
    return url


def _read_response(response: httpx.Response, max_bytes: int) -> bytes:
    content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if content_encoding not in {"", "identity"}:
        raise ValueError("Il foglio Google Sheets usa una compressione non supportata.")

    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > max_bytes:
            raise ValueError("Il foglio Google Sheets supera il limite massimo di 5 MiB.")

    payload = bytearray()
    for chunk in response.iter_raw():
        if len(payload) + len(chunk) > max_bytes:
            raise ValueError("Il foglio Google Sheets supera il limite massimo di 5 MiB.")
        payload.extend(chunk)
    return bytes(payload)


def fetch_csv(csv_url: str | None = None) -> str:
    _require_import_enabled()
    current_url = _resolve_csv_url(csv_url)
    configured_max_bytes = get_settings().google_sheets_import_max_bytes
    if configured_max_bytes <= 0:
        raise ValueError("Il limite dell'import Google Sheets non e' configurato correttamente.")
    max_bytes = min(configured_max_bytes, _MAX_DOWNLOAD_BYTES)

    request_failed = False
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            redirects_followed = 0
            while True:
                with client.stream(
                    "GET",
                    current_url,
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        if redirects_followed >= _MAX_REDIRECTS:
                            raise ValueError("Il foglio Google Sheets ha troppi reindirizzamenti.")
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Il foglio Google Sheets ha restituito un reindirizzamento non valido.")
                        current_url = _validate_csv_url(urljoin(current_url, location))
                        redirects_followed += 1
                        continue

                    response.raise_for_status()
                    payload = _read_response(response, max_bytes)
                    break
    except httpx.HTTPError:
        request_failed = True
    if request_failed:
        raise ValueError("Impossibile leggere il foglio Google Sheets.")

    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Il foglio Google Sheets non contiene un CSV UTF-8 valido.") from exc


def status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.enable_google_sheets_import,
        "configured": bool(settings.google_sheets_csv_url),
        "csv_url_set": bool(settings.google_sheets_csv_url),
    }


def _bind_resolution_snapshots(
    connection: sqlite3.Connection,
    parsed: dict[str, Any],
) -> None:
    for holding in parsed["holdings"]:
        explicit_metadata: dict[str, str] = {}
        if holding["asset_type_explicit"]:
            explicit_metadata["asset_type"] = holding["asset_type"]
        if holding["currency_explicit"]:
            explicit_metadata["currency"] = holding["currency"]
        holding["resolution_snapshot"] = asdict(
            instrument_resolution_service.snapshot_for_reference(
                connection,
                holding["symbol"],
                explicit_metadata,
            )
        )


def preview(
    connection: sqlite3.Connection,
    csv_url: str | None = None,
) -> dict[str, Any]:
    _require_import_enabled()
    parsed = parse_holdings(fetch_csv(csv_url))
    _bind_resolution_snapshots(connection, parsed)
    parsed["confirmation_token"] = _confirmation_token(parsed)
    return parsed


def _confirmation_token(parsed: dict[str, Any]) -> str:
    canonical = {
        "holdings": parsed["holdings"],
        "errors": parsed["errors"],
        "rows_total": parsed["rows_total"],
        "rows_valid": parsed["rows_valid"],
        "rows_invalid": parsed["rows_invalid"],
    }
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_import_reference_price(
    connection: sqlite3.Connection,
    asset_id: int,
    average_price: float,
) -> None:
    has_price = connection.execute(
        "SELECT 1 FROM price_history WHERE asset_id = ? LIMIT 1",
        (asset_id,),
    ).fetchone()
    if has_price is not None:
        return
    connection.execute(
        """
        INSERT INTO price_history (
            asset_id, date, close, adjusted_close, source, provider, is_real_data, fetched_at
        )
        VALUES (?, date('now'), ?, ?, 'google_sheets_import', 'google_sheets_import', 0, CURRENT_TIMESTAMP)
        """,
        (asset_id, average_price, average_price),
    )


def apply_import(
    connection: sqlite3.Connection,
    csv_url: str | None = None,
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    _require_import_enabled()
    parsed = parse_holdings(fetch_csv(csv_url))
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    _bind_resolution_snapshots(connection, parsed)
    parsed["confirmation_token"] = _confirmation_token(parsed)
    for holding in parsed["holdings"]:
        instrument_resolution_service.assert_snapshot_current(
            connection,
            ResolutionSnapshot(**holding["resolution_snapshot"]),
        )
    current_token = parsed["confirmation_token"]
    if confirmation_token is None or not hmac.compare_digest(confirmation_token, current_token):
        raise StaleImportError("RESOLUTION_CHANGED")
    holdings = parsed["holdings"]
    if not holdings:
        raise ValueError("Nessuna posizione valida da importare. Controlla il foglio.")

    created_assets = 0
    items: list[dict[str, Any]] = []
    initial_equity_base = 0.0
    connection.execute("SAVEPOINT google_sheets_import")
    try:
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
                asset_type = created.asset_type
                currency = created.currency
                created_assets += 1
            else:
                asset_id = asset.id
                if (
                    holding["asset_type_explicit"]
                    and holding["asset_type"] != asset.asset_type
                ) or (
                    holding["currency_explicit"]
                    and holding["currency"] != asset.currency
                ):
                    raise ValueError(
                        f"Metadata incompatibili per {holding['symbol']}: usa tipo e valuta dell'asset esistente."
                    )
                asset_type = asset.asset_type
                currency = asset.currency

            _ensure_import_reference_price(connection, asset_id, holding["average_price"])
            fx_quote = portfolio_engine.fx_service.get_rate(connection, currency)
            average_price_base = round(holding["average_price"] * fx_quote.rate, 6)
            initial_equity_base += round(holding["quantity"] * average_price_base, 6)
            items.append(
                {
                    "asset_id": asset_id,
                    "symbol": holding["symbol"],
                    "quantity": holding["quantity"],
                    "average_price": holding["average_price"],
                    "asset_type": asset_type,
                    "currency": currency,
                    "notes": "Importato da Google Sheets",
                }
            )
        initial_equity_base = round(initial_equity_base, 6)
        summary = portfolio_engine.replace_positions(
            connection,
            items,
            initial_equity_base=initial_equity_base,
            current_cash_base=0,
        )
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT google_sheets_import")
        connection.execute("RELEASE SAVEPOINT google_sheets_import")
        raise
    connection.execute("RELEASE SAVEPOINT google_sheets_import")

    return {
        "imported": len(holdings),
        "created_assets": created_assets,
        "rows_invalid": parsed["rows_invalid"],
        "errors": parsed["errors"],
        "portfolio_value": summary.total_value,
        "initial_equity_base": initial_equity_base,
        "current_cash_base": 0,
        "base_currency": "EUR",
    }
