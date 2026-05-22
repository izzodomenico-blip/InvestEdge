from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.config import get_settings
from backend.app.models.schemas import AppSnapshotOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class BackupService:
    def __init__(self) -> None:
        settings = get_settings()
        self.db_path = Path(settings.database_path)
        self.backup_dir = self.db_path.parent / "backup"
        self.ensure_backup_directories()

    def ensure_backup_directories(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def calculate_checksum(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def create_database_backup(self, connection: sqlite3.Connection, snapshot_name: str | None = None, snapshot_type: str = "MANUAL", note: str | None = None) -> AppSnapshotOut:
        self.ensure_backup_directories()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = snapshot_name or f"backup_{timestamp}"
        filename = f"{name}.db"
        dest_path = self.backup_dir / filename
        
        # Close connection or use SQLite backup API? 
        # For simplicity in this local app, we'll use shutil copy if no active transactions, 
        # but better to use VACUUM INTO for a clean copy.
        connection.execute(f"VACUUM INTO '{dest_path}'")
        
        checksum = self.calculate_checksum(dest_path)
        size = dest_path.stat().st_size
        
        # Tables summary
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        summary = {}
        for t in tables:
            t_name = t["name"]
            if t_name.startswith("sqlite_"): continue
            count = connection.execute(f"SELECT COUNT(*) FROM {t_name}").fetchone()[0]
            summary[t_name] = count

        cursor = connection.execute(
            """
            INSERT INTO app_snapshots (
                snapshot_name, snapshot_type, file_path, checksum, size_bytes, 
                tables_summary_json, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, snapshot_type, str(dest_path), checksum, size,
                json.dumps(summary), note, _now()
            )
        )
        
        return AppSnapshotOut(
            id=cursor.lastrowid,
            snapshot_name=name,
            snapshot_type=snapshot_type,
            file_path=str(dest_path),
            checksum=checksum,
            size_bytes=size,
            tables_summary_json=json.dumps(summary),
            note=note,
            created_at=_now()
        )

    def list_backups(self, connection: sqlite3.Connection) -> list[AppSnapshotOut]:
        rows = connection.execute("SELECT * FROM app_snapshots ORDER BY created_at DESC").fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    def get_backup(self, connection: sqlite3.Connection, backup_id: int) -> AppSnapshotOut:
        row = connection.execute("SELECT * FROM app_snapshots WHERE id = ?", (backup_id,)).fetchone()
        if not row:
            raise ValueError(f"Backup {backup_id} non trovato.")
        return self._row_to_snapshot(row)

    def restore_backup(self, connection: sqlite3.Connection, backup_id: int, confirm: bool = False) -> bool:
        if not confirm:
            raise ValueError("Conferma necessaria per il ripristino.")
            
        backup = self.get_backup(connection, backup_id)
        backup_path = Path(backup.file_path)
        
        if not backup_path.exists():
            raise FileNotFoundError(f"File backup non trovato: {backup_path}")
            
        # Validate checksum
        current_checksum = self.calculate_checksum(backup_path)
        if current_checksum != backup.checksum:
            raise ValueError("Checksum del backup non valido. Il file potrebbe essere corrotto.")
            
        # Create safety backup first
        self.create_database_backup(connection, snapshot_name=f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}", snapshot_type="AUTO_BEFORE_RESTORE", note=f"Backup automatico prima del ripristino di {backup.snapshot_name}")
        
        # Restore is tricky with an active connection. 
        # We'll need to close all connections. 
        # Since this is a service, we'll provide instructions or use a specialized logic.
        # For SQLite, we can ATTACH and copy tables, or simpler: 
        # tell the user that the app will need to restart.
        
        # Practical local approach: copy over the active db file.
        # This works if no other processes are using it and we close the current one.
        connection.close()
        shutil.copy(backup_path, self.db_path)
        
        return True

    def delete_backup(self, connection: sqlite3.Connection, backup_id: int) -> bool:
        backup = self.get_backup(connection, backup_id)
        path = Path(backup.file_path)
        if path.exists():
            path.unlink()
        connection.execute("DELETE FROM app_snapshots WHERE id = ?", (backup_id,))
        return True

    def _row_to_snapshot(self, r: sqlite3.Row) -> AppSnapshotOut:
        return AppSnapshotOut(
            id=r["id"],
            snapshot_name=r["snapshot_name"],
            snapshot_type=r["snapshot_type"],
            file_path=r["file_path"],
            checksum=r["checksum"],
            size_bytes=r["size_bytes"],
            tables_summary_json=r["tables_summary_json"],
            note=r["note"],
            created_at=r["created_at"]
        )
