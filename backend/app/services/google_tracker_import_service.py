from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal

from backend.app.services.google_sheets_service import GoogleSheetsService
from backend.app.services.assets_service import get_asset_by_symbol, create_asset
from backend.app.services.multi_portfolio_service import MultiPortfolioService
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.config import get_settings

def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")

EXPECTED_HEADERS = {
    "PORTFOLIO": [
        "portfolio_name", "broker_name", "account_name", "symbol", "isin", "name", 
        "asset_type", "quantity", "average_price", "current_price", "currency", 
        "exchange", "market_value", "as_of_date"
    ],
    "TRANSACTIONS": [
        "portfolio_name", "broker_name", "account_name", "transaction_date", 
        "transaction_type", "symbol", "isin", "name", "asset_type", "quantity", 
        "price", "gross_amount", "fees", "taxes", "net_amount", "currency", 
        "exchange", "note"
    ],
    "CASH": [
        "portfolio_name", "broker_name", "account_name", "currency", "cash_amount", "as_of_date"
    ],
    "WATCHLIST": [
        "symbol", "isin", "name", "asset_type", "currency", "exchange", "sector", "country", "notes"
    ]
}

class GoogleTrackerImportService:
    def __init__(self) -> None:
        self.sheets_service = GoogleSheetsService()
        self.settings = get_settings()

    def _parse_numeric(self, value: Any, field_name: str, row_idx: int) -> float:
        if value is None or value == "":
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        
        original_s = str(value).strip()
        s = original_s
        
        # 1. Remove currency symbols and common noise
        for char in ['€', '$', '£', ' ']:
            s = s.replace(char, '')
        
        if not s:
            return 0.0
            
        try:
            # 2. Try direct conversion (handles standard 123.45)
            return float(s)
        except ValueError:
            pass

        # 3. Handle European/Italian format (comma as decimal, optional dot as thousand)
        try:
            # Case A: Both dot and comma are present
            if '.' in s and ',' in s:
                if s.rfind(',') > s.rfind('.'):
                    # Italian: 1.234,56
                    s = s.replace('.', '').replace(',', '.')
                else:
                    # US: 1,234.56
                    s = s.replace(',', '')
            # Case B: Only comma
            elif ',' in s:
                if s.count(',') > 1:
                    # Multiple commas: 1,234,567 -> thousand separators
                    s = s.replace(',', '')
                else:
                    # Single comma: 383,47 -> assume decimal
                    s = s.replace(',', '.')
            # Case C: Only dot (multiple dots)
            elif '.' in s:
                if s.count('.') > 1:
                    # Multiple dots: 1.234.567 -> thousand separators
                    # BUT: 383.47.00 is invalid. 
                    # Valid thousand separators must be followed by exactly 3 digits.
                    parts = s.split('.')
                    if all(len(p) == 3 for p in parts[1:]):
                        s = s.replace('.', '')
                    else:
                        raise ValueError("Invalid dot distribution")
            
            return float(s)
        except Exception:
            # If everything fails, raise specific error
            raise ValueError(f"row {row_idx}, field {field_name}, invalid numeric value: {original_s}")

    def preview_import(self, connection: sqlite3.Connection, import_type: str) -> int:
        """
        Reads from Google Sheets and saves to external_import_* tables in PREVIEW status.
        Returns the import_id.
        """
        spreadsheet_id = self.settings.google_sheets_spreadsheet_id
        spreadsheet_id_hash = None
        if spreadsheet_id:
            import hashlib
            spreadsheet_id_hash = hashlib.sha256(spreadsheet_id.encode()).hexdigest()

        # 1. Create entry in external_imports
        cursor = connection.execute(
            """
            INSERT INTO external_imports (
                import_name, import_type, spreadsheet_id_hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'PREVIEW', ?, ?)
            """,
            (f"Google Tracker {import_type} Import", import_type, spreadsheet_id_hash, _now(), _now())
        )
        import_id = cursor.lastrowid

        warnings = []
        errors = []
        rows_total = 0
        rows_valid = 0

        try:
            if import_type == "PORTFOLIO":
                rows_total, rows_valid = self._preview_portfolio(connection, import_id, warnings, errors)
            elif import_type == "TRANSACTIONS":
                rows_total, rows_valid = self._preview_transactions(connection, import_id, warnings, errors)
            elif import_type == "CASH":
                rows_total, rows_valid = self._preview_cash(connection, import_id, warnings, errors)
            elif import_type == "WATCHLIST":
                rows_total, rows_valid = self._preview_watchlist(connection, import_id, warnings, errors)
            elif import_type == "MIXED":
                # For mixed, we might read all ranges. For now, let's just handle them one by one.
                pass
            
            # Update summary
            connection.execute(
                """
                UPDATE external_imports 
                SET rows_total = ?, rows_valid = ?, rows_invalid = ?, 
                    warnings_json = ?, errors_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (rows_total, rows_valid, rows_total - rows_valid, json.dumps(warnings), json.dumps(errors), _now(), import_id)
            )
        except Exception as e:
            connection.execute(
                "UPDATE external_imports SET status = 'FAILED', errors_json = ? WHERE id = ?",
                (json.dumps([str(e)]), import_id)
            )
            raise

        return import_id

    def _preview_portfolio(self, connection: sqlite3.Connection, import_id: int, warnings: list[str], errors: list[str]) -> tuple[int, int]:
        range_name = self.settings.google_sheets_portfolio_range
        rows = self.sheets_service.read_range(range_name)
        if not rows:
            return 0, 0
            
        header_errors = self.sheets_service.validate_headers(rows, EXPECTED_HEADERS["PORTFOLIO"])
        if header_errors:
            errors.extend(header_errors)
            return len(rows) - 1, 0

        dicts = self.sheets_service.rows_to_dicts(rows)
        valid_count = 0
        
        for idx, d in enumerate(dicts, start=2): # Header is row 1
            symbol = d.get("symbol")
            if not symbol:
                continue
            
            try:
                qty = self._parse_numeric(d.get("quantity"), "quantity", idx)
                avg_p = self._parse_numeric(d.get("average_price"), "average_price", idx)
                curr_p = self._parse_numeric(d.get("current_price"), "current_price", idx)
                mkt_v = self._parse_numeric(d.get("market_value"), "market_value", idx)
            except ValueError as e:
                errors.append(str(e))
                connection.execute(
                    """
                    INSERT INTO external_import_positions (
                        import_id, portfolio_name, broker_name, account_name, symbol, isin, name, 
                        asset_type, quantity, average_price, current_price, currency, exchange, 
                        market_value, as_of_date, validation_status, validation_message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?, 0, ?, 'INVALID', ?, ?)
                    """,
                    (
                        import_id, d.get("portfolio_name"), d.get("broker_name"), d.get("account_name"),
                        symbol, d.get("isin"), d.get("name"), d.get("asset_type"),
                        d.get("currency"), d.get("exchange"), d.get("as_of_date"), str(e), _now()
                    )
                )
                continue
            
            # Map symbol
            asset = get_asset_by_symbol(connection, symbol)
            asset_id = asset.id if asset else None
            
            connection.execute(
                """
                INSERT INTO external_import_positions (
                    import_id, portfolio_name, broker_name, account_name, symbol, isin, name, 
                    asset_type, quantity, average_price, current_price, currency, exchange, 
                    market_value, as_of_date, mapped_asset_id, validation_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    import_id, d.get("portfolio_name"), d.get("broker_name"), d.get("account_name"),
                    symbol, d.get("isin"), d.get("name"), d.get("asset_type"),
                    qty, avg_p, curr_p, d.get("currency"), d.get("exchange"),
                    mkt_v, d.get("as_of_date"), asset_id, _now()
                )
            )
            valid_count += 1
            
        return len(dicts), valid_count

    def _preview_transactions(self, connection: sqlite3.Connection, import_id: int, warnings: list[str], errors: list[str]) -> tuple[int, int]:
        range_name = self.settings.google_sheets_transactions_range
        rows = self.sheets_service.read_range(range_name)
        if not rows:
            return 0, 0
            
        header_errors = self.sheets_service.validate_headers(rows, EXPECTED_HEADERS["TRANSACTIONS"])
        if header_errors:
            errors.extend(header_errors)
            return len(rows) - 1, 0

        dicts = self.sheets_service.rows_to_dicts(rows)
        valid_count = 0
        
        for idx, d in enumerate(dicts, start=2):
            symbol = d.get("symbol")
            if not symbol:
                continue
            
            try:
                qty = self._parse_numeric(d.get("quantity"), "quantity", idx)
                price = self._parse_numeric(d.get("price"), "price", idx)
                gross = self._parse_numeric(d.get("gross_amount"), "gross_amount", idx)
                fees = self._parse_numeric(d.get("fees"), "fees", idx)
                taxes = self._parse_numeric(d.get("taxes"), "taxes", idx)
                net = self._parse_numeric(d.get("net_amount"), "net_amount", idx)
            except ValueError as e:
                errors.append(str(e))
                connection.execute(
                    """
                    INSERT INTO external_import_transactions (
                        import_id, portfolio_name, broker_name, account_name, transaction_date, 
                        transaction_type, symbol, isin, name, asset_type, quantity, price, 
                        gross_amount, fees, taxes, net_amount, currency, exchange, note, 
                        validation_status, validation_message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, ?, ?, ?, 'INVALID', ?, ?)
                    """,
                    (
                        import_id, d.get("portfolio_name"), d.get("broker_name"), d.get("account_name"),
                        d.get("transaction_date"), d.get("transaction_type"), symbol, d.get("isin"),
                        d.get("name"), d.get("asset_type"), d.get("currency"), d.get("exchange"),
                        d.get("note"), str(e), _now()
                    )
                )
                continue

            asset = get_asset_by_symbol(connection, symbol)
            asset_id = asset.id if asset else None
            
            connection.execute(
                """
                INSERT INTO external_import_transactions (
                    import_id, portfolio_name, broker_name, account_name, transaction_date, 
                    transaction_type, symbol, isin, name, asset_type, quantity, price, 
                    gross_amount, fees, taxes, net_amount, currency, exchange, note, 
                    mapped_asset_id, validation_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    import_id, d.get("portfolio_name"), d.get("broker_name"), d.get("account_name"),
                    d.get("transaction_date"), d.get("transaction_type"), symbol, d.get("isin"),
                    d.get("name"), d.get("asset_type"), qty, price, gross, fees, taxes, net, 
                    d.get("currency"), d.get("exchange"), d.get("note"), asset_id, _now()
                )
            )
            valid_count += 1
            
        return len(dicts), valid_count

    def _preview_cash(self, connection: sqlite3.Connection, import_id: int, warnings: list[str], errors: list[str]) -> tuple[int, int]:
        range_name = self.settings.google_sheets_cash_range
        rows = self.sheets_service.read_range(range_name)
        if not rows:
            return 0, 0
            
        header_errors = self.sheets_service.validate_headers(rows, EXPECTED_HEADERS["CASH"])
        if header_errors:
            errors.extend(header_errors)
            return len(rows) - 1, 0

        dicts = self.sheets_service.rows_to_dicts(rows)
        valid_count = 0
        
        for idx, d in enumerate(dicts, start=2):
            try:
                cash_amt = self._parse_numeric(d.get("cash_amount"), "cash_amount", idx)
            except ValueError as e:
                errors.append(str(e))
                connection.execute(
                    """
                    INSERT INTO external_import_cash (
                        import_id, portfolio_name, broker_name, account_name, currency, 
                        cash_amount, as_of_date, validation_status, validation_message, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, 'INVALID', ?, ?)
                    """,
                    (
                        import_id, d.get("portfolio_name"), d.get("broker_name"), d.get("account_name"),
                        d.get("currency", "USD"), d.get("as_of_date"), str(e), _now()
                    )
                )
                continue

            connection.execute(
                """
                INSERT INTO external_import_cash (
                    import_id, portfolio_name, broker_name, account_name, currency, 
                    cash_amount, as_of_date, validation_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    import_id, d.get("portfolio_name"), d.get("broker_name"), d.get("account_name"),
                    d.get("currency", "USD"), cash_amt, d.get("as_of_date"), _now()
                )
            )
            valid_count += 1
            
        return len(dicts), valid_count

    def _preview_watchlist(self, connection: sqlite3.Connection, import_id: int, warnings: list[str], errors: list[str]) -> tuple[int, int]:
        range_name = self.settings.google_sheets_watchlist_range
        rows = self.sheets_service.read_range(range_name)
        if not rows:
            return 0, 0
            
        header_errors = self.sheets_service.validate_headers(rows, EXPECTED_HEADERS["WATCHLIST"])
        if header_errors:
            errors.extend(header_errors)
            return len(rows) - 1, 0

        dicts = self.sheets_service.rows_to_dicts(rows)
        valid_count = 0
        
        for d in dicts:
            symbol = d.get("symbol")
            if not symbol:
                continue
            
            asset = get_asset_by_symbol(connection, symbol)
            asset_id = asset.id if asset else None
            
            connection.execute(
                """
                INSERT INTO external_import_watchlist (
                    import_id, symbol, isin, name, asset_type, currency, 
                    exchange, sector, country, notes, mapped_asset_id, 
                    validation_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    import_id, symbol, d.get("isin"), d.get("name"), d.get("asset_type"),
                    d.get("currency"), d.get("exchange"), d.get("sector"), d.get("country"),
                    d.get("notes"), asset_id, _now()
                )
            )
            valid_count += 1
            
        return len(dicts), valid_count

    def list_imports(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute("SELECT * FROM external_imports ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def get_import(self, connection: sqlite3.Connection, import_id: int) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM external_imports WHERE id = ?", (import_id,)).fetchone()
        if not row:
            raise ValueError(f"Import {import_id} not found")
        
        res = dict(row)
        res["warnings"] = json.loads(row["warnings_json"] or "[]")
        res["errors"] = json.loads(row["errors_json"] or "[]")
        
        # Load related data
        res["positions"] = [dict(r) for r in connection.execute("SELECT * FROM external_import_positions WHERE import_id = ?", (import_id,)).fetchall()]
        res["transactions"] = [dict(r) for r in connection.execute("SELECT * FROM external_import_transactions WHERE import_id = ?", (import_id,)).fetchall()]
        res["cash"] = [dict(r) for r in connection.execute("SELECT * FROM external_import_cash WHERE import_id = ?", (import_id,)).fetchall()]
        res["watchlist"] = [dict(r) for r in connection.execute("SELECT * FROM external_import_watchlist WHERE import_id = ?", (import_id,)).fetchall()]
        
        return res

    def confirm_import(self, connection: sqlite3.Connection, import_id: int, mode: str) -> dict[str, Any]:
        """
        Executes the import based on the chosen mode.
        """
        imp = self.get_import(connection, import_id)
        if imp["status"] == "IMPORTED":
            raise ValueError("Import already confirmed and executed")
            
        results = {"success": True, "actions": []}
        
        if mode == "CREATE_READONLY_PORTFOLIO":
            self._execute_readonly_portfolio_import(connection, imp, results)
        elif mode == "UPDATE_WATCHLIST":
            self._execute_watchlist_update(connection, imp, results)
        elif mode == "PREVIEW_ONLY":
            results["actions"].append("Import kept in PREVIEW state as requested.")
        else:
            raise ValueError(f"Invalid import mode: {mode}")

        connection.execute(
            "UPDATE external_imports SET status = 'IMPORTED', import_mode = ?, updated_at = ? WHERE id = ?",
            (mode, _now(), import_id)
        )
        
        return results

    def _execute_readonly_portfolio_import(self, connection: sqlite3.Connection, imp: dict[str, Any], results: dict[str, Any]):
        mps = MultiPortfolioService()
        engine = PortfolioEngine()
        
        # Group positions by portfolio_name
        portfolios_to_create = {}
        for pos in imp["positions"]:
            p_name = pos.get("portfolio_name") or "Google Sheets Import"
            if p_name not in portfolios_to_create:
                portfolios_to_create[p_name] = []
            portfolios_to_create[p_name].append(pos)
            
        for p_name, positions in portfolios_to_create.items():
            # Create a READONLY portfolio (logic for READONLY needs to be enforced in PortfolioEngine/Simulator)
            # For Step 17 we had types like CORE, GROWTH. Let's add CUSTOM or similar.
            # We'll use "CUSTOM" and a description indicating it's READONLY.
            
            existing = connection.execute("SELECT id FROM portfolios WHERE portfolio_name = ?", (p_name,)).fetchone()
            if existing:
                portfolio_id = existing["id"]
                results["actions"].append(f"Updating existing portfolio: {p_name}")
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO portfolios (
                        portfolio_name, description, portfolio_type, base_currency, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (p_name, "Read-only portfolio imported from Google Sheets", "EXTERNAL_TRACKER", "USD", 0, _now(), _now())
                )
                portfolio_id = cursor.lastrowid
                results["actions"].append(f"Created new portfolio: {p_name}")

            # Clear existing positions for this portfolio to refresh from Google Sheets
            connection.execute("DELETE FROM portfolio_positions WHERE portfolio_id = ?", (portfolio_id,))
            
            for pos in positions:
                # Ensure asset exists
                asset = get_asset_by_symbol(connection, pos["symbol"])
                if not asset:
                    # Create asset as candidate
                    from backend.app.models import AssetCreate
                    asset = create_asset(connection, AssetCreate(
                        symbol=pos["symbol"],
                        name=pos["name"] or pos["symbol"],
                        asset_type=pos["asset_type"] or "stock",
                        currency=pos["currency"] or "USD",
                        exchange=pos["exchange"]
                    ))
                
                connection.execute(
                    """
                    INSERT INTO portfolio_positions (
                        portfolio_id, asset_id, symbol, quantity, average_price, invested_amount, 
                        current_price, current_value, asset_type, currency, opened_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        portfolio_id, asset.id, asset.symbol, pos["quantity"], 
                        pos["average_price"], (pos["quantity"] * (pos["average_price"] or 0)),
                        pos["current_price"], pos["market_value"], 
                        pos["asset_type"], pos["currency"], _now(), _now()
                    )
                )

            # Re-calculate cash
            p_cash = sum(c["cash_amount"] for c in imp["cash"] if c.get("portfolio_name") == p_name)
            if p_cash > 0:
                connection.execute("UPDATE portfolios SET current_cash = ?, updated_at = ? WHERE id = ?", (p_cash, _now(), portfolio_id))
            
            # Refresh to calc weights/pnl
            engine.refresh_portfolio(connection, portfolio_id=portfolio_id)

    def _execute_watchlist_update(self, connection: sqlite3.Connection, imp: dict[str, Any], results: dict[str, Any]):
        for item in imp["watchlist"]:
            symbol = item["symbol"]
            # Ensure asset exists
            asset = get_asset_by_symbol(connection, symbol)
            if not asset:
                from backend.app.models import AssetCreate
                asset = create_asset(connection, AssetCreate(
                    symbol=symbol,
                    name=item["name"] or symbol,
                    asset_type=item["asset_type"] or "stock",
                    currency=item["currency"] or "USD",
                    exchange=item["exchange"]
                ))
            
            # Add to watchlist in asset_universe
            connection.execute(
                """
                UPDATE asset_universe 
                SET is_watchlisted = 1, updated_at = ? 
                WHERE symbol = ?
                """,
                (_now(), symbol)
            )
            results["actions"].append(f"Added {symbol} to watchlist.")
