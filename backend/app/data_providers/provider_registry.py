from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from backend.app.config import Settings
from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
from backend.app.data_providers.base import BaseMarketDataProvider
from backend.app.data_providers.coingecko import CoinGeckoProvider
from backend.app.data_providers.fred import FredProvider


class ProviderRegistry:
    def __init__(self, settings: Settings, connection: sqlite3.Connection):
        self.settings = settings
        self.connection = connection
        self.providers: list[BaseMarketDataProvider] = [
            AlphaVantageProvider(settings, connection),
            CoinGeckoProvider(settings, connection),
            FredProvider(settings, connection),
        ]

    def provider_for_asset_type(self, asset_type: str) -> BaseMarketDataProvider | None:
        normalized = asset_type.lower()
        for provider in self.providers:
            if provider.supports_asset_type(normalized):
                return provider
        return None

    def statuses(self) -> list[dict[str, Any]]:
        usage = self.usage_by_provider()
        return [
            {
                "provider": provider.provider_name,
                "enabled": self.settings.enable_real_data,
                "api_key_configured": provider.api_key_configured(),
                "daily_limit": provider.daily_limit,
                "calls_today": usage.get(provider.provider_name, {}).get("calls_count", 0),
                "supports": self._supports(provider),
            }
            for provider in self.providers
        ]

    def usage_by_provider(self) -> dict[str, dict[str, int | str]]:
        today = date.today().isoformat()
        rows = self.connection.execute(
            """
            SELECT provider, usage_date, calls_count, daily_limit, updated_at
            FROM api_usage
            WHERE usage_date = ?
            ORDER BY provider
            """,
            (today,),
        ).fetchall()
        return {
            row["provider"]: {
                "usage_date": row["usage_date"],
                "calls_count": int(row["calls_count"]),
                "daily_limit": int(row["daily_limit"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def usage_rows(self) -> list[dict[str, Any]]:
        usage = self.usage_by_provider()
        rows: list[dict[str, Any]] = []
        for provider in self.providers:
            provider_usage = usage.get(provider.provider_name, {})
            rows.append(
                {
                    "provider": provider.provider_name,
                    "usage_date": provider_usage.get("usage_date", date.today().isoformat()),
                    "calls_count": int(provider_usage.get("calls_count", 0)),
                    "daily_limit": provider.daily_limit,
                    "updated_at": provider_usage.get("updated_at"),
                }
            )
        return rows

    def _supports(self, provider: BaseMarketDataProvider) -> list[str]:
        known_types = ["stock", "etf", "crypto", "macro", "bond_proxy", "bond", "bond_etf"]
        return [asset_type for asset_type in known_types if provider.supports_asset_type(asset_type)]
