from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Literal

from backend.app.config import get_settings
from backend.app.data_providers.provider_registry import ProviderRegistry
from backend.app.models.schemas import SystemHealthOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class SystemHealthService:
    def get_health(self, connection: sqlite3.Connection) -> SystemHealthOut:
        # DB check
        try:
            connection.execute("SELECT 1").fetchone()
            db_status = "connected"
        except Exception:
            db_status = "error"

        # Provider check
        settings = get_settings()
        registry = ProviderRegistry(settings, connection)
        statuses = registry.statuses()
        provider_dict = {
            s["provider"]: "connected" if s["api_key_configured"] else "no_api_key"
            for s in statuses
        }

        # Cache check
        cache_row = connection.execute(
            "SELECT COUNT(*) FROM price_history WHERE is_real_data = 1"
        ).fetchone()
        cache_count = cache_row[0] if cache_row else 0
        cache_status = f"{cache_count} real data points"

        overall_status: Literal["healthy", "degraded", "down"] = "healthy"
        if db_status == "error":
            overall_status = "down"
        elif any(v == "no_api_key" for v in provider_dict.values()) and settings.enable_real_data:
            overall_status = "degraded"

        return SystemHealthOut(
            status=overall_status,
            database=db_status,
            providers=provider_dict,
            cache=cache_status,
            timestamp=_now(),
        )
