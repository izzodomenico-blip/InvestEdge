from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from backend.app.config import get_settings
from backend.app.models.schemas import AppExportOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class ExportService:
    def __init__(self) -> None:
        settings = get_settings()
        self.db_path = Path(settings.database_path)
        self.export_dir = self.db_path.parent / "export"
        self.ensure_export_directories()

    def ensure_export_directories(self) -> None:
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def calculate_checksum(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def export_dataset(self, connection: sqlite3.Connection, export_type: str, file_format: str = "JSON") -> AppExportOut:
        self.ensure_export_directories()
        
        table_map = {
            "ASSETS": "assets",
            "PRICES": "price_history",
            "PORTFOLIO": "portfolio_positions",
            "ORDERS": "simulated_orders",
            "BACKTESTS": "backtest_runs",
            "STRATEGY_PLANS": "strategy_plans",
            "OPTIMIZATIONS": "portfolio_optimization_runs",
            "SCENARIOS": "scenario_runs",
            "ALERTS": "alerts",
            "REPORTS": "operational_reports",
            "JOURNAL": "decision_journal",
            "UNIVERSE": "asset_universe"
        }
        
        table_name = table_map.get(export_type.upper())
        if not table_name:
            raise ValueError(f"Tipo export non supportato: {export_type}")
            
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", connection)
        
        # Security: Remove sensitive columns if any (e.g. API keys if they were stored in DB, but they aren't)
        # However, let's be explicit.
        sensitive_cols = ["api_key", "secret", "password"]
        df = df.drop(columns=[c for c in sensitive_cols if c in df.columns])

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{table_name}_{timestamp}.{file_format.lower()}"
        dest_path = self.export_dir / filename
        
        if file_format.upper() == "JSON":
            df.to_json(dest_path, orient="records", date_format="iso", indent=2)
        else:
            df.to_csv(dest_path, index=False)
            
        checksum = self.calculate_checksum(dest_path)
        size = dest_path.stat().st_size
        
        cursor = connection.execute(
            """
            INSERT INTO app_exports (
                export_name, export_type, file_format, file_path, checksum, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filename, export_type.upper(), file_format.upper(), str(dest_path), checksum, size, _now()
            )
        )
        
        return AppExportOut(
            id=cursor.lastrowid,
            export_name=filename,
            export_type=export_type.upper(),
            file_format=file_format.upper(),
            file_path=str(dest_path),
            checksum=checksum,
            size_bytes=size,
            created_at=_now()
        )

    def list_exports(self, connection: sqlite3.Connection) -> list[AppExportOut]:
        rows = connection.execute("SELECT * FROM app_exports ORDER BY created_at DESC").fetchall()
        return [
            AppExportOut(
                id=r["id"],
                export_name=r["export_name"],
                export_type=r["export_type"],
                file_format=r["file_format"],
                file_path=r["file_path"],
                checksum=r["checksum"],
                size_bytes=r["size_bytes"],
                created_at=r["created_at"]
            )
            for r in rows
        ]
