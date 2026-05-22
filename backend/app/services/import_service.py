from __future__ import annotations

import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from backend.app.config import get_settings
from backend.app.models.schemas import AppImportOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class ImportService:
    def __init__(self) -> None:
        settings = get_settings()
        self.db_path = Path(settings.database_path)
        self.import_dir = self.db_path.parent / "import"
        self.ensure_import_directories()

    def ensure_import_directories(self) -> None:
        self.import_dir.mkdir(parents=True, exist_ok=True)

    def list_imports(self, connection: sqlite3.Connection) -> list[AppImportOut]:
        rows = connection.execute("SELECT * FROM app_imports ORDER BY created_at DESC").fetchall()
        return [
            AppImportOut(
                id=r["id"],
                import_name=r["import_name"],
                import_type=r["import_type"],
                file_name=r["file_name"],
                status=r["status"],
                records_processed=r["records_processed"],
                records_imported=r["records_imported"],
                records_failed=r["records_failed"],
                errors_json=r["errors_json"],
                created_at=r["created_at"]
            )
            for r in rows
        ]

    def validate_import_file(self, file_name: str, import_type: str) -> dict[str, Any]:
        file_path = self.import_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"File non trovato in data/import: {file_name}")
            
        try:
            if file_name.endswith(".json"):
                df = pd.read_json(file_path)
            else:
                df = pd.read_csv(file_path)
                
            return {
                "valid": True,
                "rows": len(df),
                "columns": list(df.columns),
                "message": "File validato con successo."
            }
        except Exception as e:
            return {
                "valid": False,
                "message": f"Errore validazione: {str(e)}"
            }

    def run_import(self, connection: sqlite3.Connection, file_name: str, import_type: str, confirm: bool = False) -> AppImportOut:
        if not confirm:
            raise ValueError("Conferma necessaria per l'importazione.")
            
        file_path = self.import_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"File non trovato in data/import: {file_name}")
            
        status = "SUCCESS"
        imported = 0
        failed = 0
        errors = []
        
        try:
            if file_name.endswith(".json"):
                df = pd.read_json(file_path)
            else:
                df = pd.read_csv(file_path)
                
            records = df.to_dict(orient="records")
            
            if import_type.upper() == "UNIVERSE":
                for r in records:
                    try:
                        connection.execute(
                            """
                            INSERT OR REPLACE INTO asset_universe (
                                symbol, name, asset_type, exchange, currency, sector, industry, country,
                                risk_level, universe_level, is_active, is_watchlisted, is_portfolio_asset,
                                refresh_priority, refresh_frequency_days, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                r.get("symbol"), r.get("name"), r.get("asset_type"), r.get("exchange"),
                                r.get("currency", "USD"), r.get("sector"), r.get("industry"), r.get("country"),
                                r.get("risk_level", "medium"), r.get("universe_level", "CANDIDATE"),
                                r.get("is_active", 1), r.get("is_watchlisted", 0), r.get("is_portfolio_asset", 0),
                                r.get("refresh_priority", 1), r.get("refresh_frequency_days", 7), _now()
                            )
                        )
                        imported += 1
                    except Exception as e:
                        failed += 1
                        errors.append(f"Errore riga {r.get('symbol')}: {str(e)}")
            
            elif import_type.upper() == "WATCHLIST":
                 for r in records:
                    try:
                        symbol = r.get("symbol")
                        if not symbol: continue
                        connection.execute(
                            "UPDATE asset_universe SET is_watchlisted = 1, updated_at = ? WHERE UPPER(symbol) = UPPER(?)",
                            (_now(), symbol)
                        )
                        imported += 1
                    except Exception as e:
                        failed += 1
                        errors.append(f"Errore riga {symbol}: {str(e)}")
            
            else:
                raise ValueError(f"Tipo import non supportato: {import_type}")

        except Exception as e:
            status = "ERROR"
            errors.append(f"Errore fatale: {str(e)}")

        cursor = connection.execute(
            """
            INSERT INTO app_imports (
                import_name, import_type, file_name, status, records_processed, 
                records_imported, records_failed, errors_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"Import {import_type} - {file_name}", import_type.upper(), file_name, status,
                len(records) if 'records' in locals() else 0, imported, failed, json.dumps(errors), _now()
            )
        )
        
        return AppImportOut(
            id=cursor.lastrowid,
            import_name=f"Import {import_type} - {file_name}",
            import_type=import_type.upper(),
            file_name=file_name,
            status=status,
            records_processed=len(records) if 'records' in locals() else 0,
            records_imported=imported,
            records_failed=failed,
            errors_json=json.dumps(errors),
            created_at=_now()
        )
