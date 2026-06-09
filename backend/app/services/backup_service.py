"""Backup del database SQLite: copia consistente + rotazione delle vecchie copie.

Usa l'API nativa sqlite3 `Connection.backup`, sicura anche se il DB e' in uso
(a differenza di una semplice copia del file).
"""
from __future__ import annotations

import contextlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.config import get_settings

KEEP_BACKUPS = 10


def _backups_dir() -> Path:
    path = get_settings().database_path.parent / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def create_backup(reason: str = "manual") -> dict[str, Any]:
    db_path = get_settings().database_path
    if not db_path.exists():
        return {"created": False, "reason": "Database non ancora inizializzato.", "file": None}

    target = _backups_dir() / f"investedge-{_stamp()}.db"
    source = sqlite3.connect(str(db_path))
    try:
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()

    prune_backups()
    return {
        "created": True,
        "reason": reason,
        "file": target.name,
        "size_bytes": target.stat().st_size,
        "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
    }


def prune_backups(keep: int = KEEP_BACKUPS) -> int:
    files = sorted(_backups_dir().glob("investedge-*.db"), key=lambda p: p.name, reverse=True)
    removed = 0
    for old in files[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def list_backups() -> list[dict[str, Any]]:
    files = sorted(_backups_dir().glob("investedge-*.db"), key=lambda p: p.name, reverse=True)
    result: list[dict[str, Any]] = []
    for file in files:
        stat = file.stat()
        result.append(
            {
                "file": file.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC)
                .replace(tzinfo=None)
                .isoformat(timespec="seconds"),
            }
        )
    return result


def auto_backup_on_startup() -> None:
    """Backup best-effort all'avvio. Non deve mai bloccare l'app."""
    with contextlib.suppress(Exception):
        create_backup(reason="startup")
