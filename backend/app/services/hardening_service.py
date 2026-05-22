from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.config import get_settings
from backend.app.models.schemas import HardeningCheckOut, HardeningReportOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class HardeningService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.root_dir = Path(__file__).resolve().parents[3]
        self.db_path = Path(self.settings.database_path)

    def run_checks(self, connection: sqlite3.Connection) -> HardeningReportOut:
        checks = []
        
        # 1. Check .env in .gitignore
        checks.append(self._check_gitignore(".env"))
        
        # 2. Check database existence and integrity
        checks.append(self._check_db_integrity(connection))
        
        # 3. Check required directories
        checks.append(self._check_required_dirs())
        
        # 4. Scan for possible API keys in public files (simulated)
        checks.append(self._scan_for_keys())
        
        # 5. Check sensitive files not tracked by git
        checks.append(self._check_git_untracked())

        overall_status = "OK"
        if any(c.status == "ERROR" for c in checks):
            overall_status = "ERROR"
        elif any(c.status == "WARNING" for c in checks):
            overall_status = "WARNING"
            
        for c in checks:
            connection.execute(
                """
                INSERT INTO app_hardening_checks (
                    check_name, status, message, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (c.check_name, c.status, c.message, c.details_json, _now())
            )

        return HardeningReportOut(
            checks=checks,
            overall_status=overall_status,
            timestamp=_now()
        )

    def _check_gitignore(self, pattern: str) -> HardeningCheckOut:
        gitignore_path = self.root_dir / ".gitignore"
        if not gitignore_path.exists():
            return HardeningCheckOut(check_name="Gitignore Check", status="WARNING", message=".gitignore non trovato nella root.")
            
        with open(gitignore_path, "r") as f:
            content = f.read()
            if pattern in content:
                return HardeningCheckOut(check_name=f"Gitignore {pattern}", status="OK", message=f"{pattern} è correttamente ignorato.")
            else:
                return HardeningCheckOut(check_name=f"Gitignore {pattern}", status="ERROR", message=f"{pattern} NON è presente in .gitignore!")

    def _check_db_integrity(self, connection: sqlite3.Connection) -> HardeningCheckOut:
        try:
            res = connection.execute("PRAGMA integrity_check").fetchone()
            if res[0] == "ok":
                return HardeningCheckOut(check_name="DB Integrity", status="OK", message="Integrità del database confermata.")
            else:
                return HardeningCheckOut(check_name="DB Integrity", status="ERROR", message=f"Errori integrità DB: {res[0]}")
        except Exception as e:
            return HardeningCheckOut(check_name="DB Integrity", status="ERROR", message=f"Errore durante check integrità: {str(e)}")

    def _check_required_dirs(self) -> HardeningCheckOut:
        required = ["data/backup", "data/export", "data/import"]
        missing = []
        for d in required:
            p = self.root_dir / d
            if not p.exists():
                missing.append(d)
        
        if not missing:
            return HardeningCheckOut(check_name="Directory Check", status="OK", message="Tutte le cartelle richieste esistono.")
        else:
            return HardeningCheckOut(check_name="Directory Check", status="WARNING", message=f"Cartelle mancanti: {', '.join(missing)}")

    def _scan_for_keys(self) -> HardeningCheckOut:
        # Simplified scan for common API key patterns in README or public files
        readme_path = self.root_dir / "README.md"
        if readme_path.exists():
             with open(readme_path, "r") as f:
                 content = f.read()
                 if "AIza" in content or "sk-" in content: # Common GCP/OpenAI prefixes
                     return HardeningCheckOut(check_name="API Key Scan", status="ERROR", message="Possibile API Key trovata in README.md!")
        
        return HardeningCheckOut(check_name="API Key Scan", status="OK", message="Nessuna API Key evidente trovata nei file pubblici.")

    def _check_git_untracked(self) -> HardeningCheckOut:
        # Check if backend/.env is actually untracked
        # This usually requires running a git command, but we'll simulate for now
        # by checking if it exists and trusting gitignore.
        env_path = self.root_dir / "backend" / ".env"
        if env_path.exists():
             return HardeningCheckOut(check_name="Sensitive File Check", status="OK", message="backend/.env esiste localmente (protezione dipendente da .gitignore).")
        return HardeningCheckOut(check_name="Sensitive File Check", status="OK", message="backend/.env non trovato (modalità demo).")
