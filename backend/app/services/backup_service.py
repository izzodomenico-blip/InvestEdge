"""Backup del database SQLite: copia consistente + rotazione delle vecchie copie.

Usa l'API nativa sqlite3 `Connection.backup`, sicura anche se il DB e' in uso
(a differenza di una semplice copia del file).
"""
from __future__ import annotations

import re
import sqlite3
import tempfile
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


def _reason_slug(reason: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", reason.lower()).strip("-")[:48] or "backup"


def create_backup(reason: str = "manual") -> dict[str, Any]:
    db_path = get_settings().database_path
    if not db_path.exists():
        return {"created": False, "reason": "Database non ancora inizializzato.", "file": None}

    backups_dir = _backups_dir()
    with tempfile.NamedTemporaryFile(
        prefix=f"investedge-{_stamp()}-{_reason_slug(reason)}-",
        suffix=".db",
        dir=backups_dir,
        delete=False,
    ) as reserved:
        target = Path(reserved.name)
    source: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(str(db_path))
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        if source is not None:
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
    files = sorted(
        _backups_dir().glob("investedge-*.db"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed = 0
    for old in files[keep:]:
        try:
            old.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def list_backups() -> list[dict[str, Any]]:
    files = sorted(
        _backups_dir().glob("investedge-*.db"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
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


def backup_before_migration() -> dict[str, Any]:
    return create_backup(reason="pre-migration")


def prepare_database(*, reason: str = "pre-migration", backup_existing: bool = True) -> dict[str, Any]:
    if backup_existing:
        backup = create_backup(reason=reason)
    else:
        backup = {"created": False, "reason": "Backup disabilitato per questa inizializzazione.", "file": None}

    from backend.app.database import init_db

    init_db()
    return backup
