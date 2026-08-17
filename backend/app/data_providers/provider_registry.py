from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from backend.app.config import Settings
from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
from backend.app.data_providers.base import BaseMarketDataProvider
from backend.app.data_providers.coingecko import CoinGeckoProvider
from backend.app.data_providers.finnhub_quote import FinnhubQuoteProvider
from backend.app.data_providers.fred import FredProvider
from backend.app.data_providers.stooq import StooqProvider
from backend.app.data_providers.yahoo_finance import YahooFinanceProvider
from backend.app.services.provider_budget_service import (
    ProviderAvailability,
    ProviderCapability,
)


@dataclass(frozen=True)
class ProviderCapabilityMatch:
    provider: str
    capability: ProviderCapability
    listing_id: int
    provider_symbol: str
    currency: str
    priority: int


class ProviderRegistry:
    def __init__(self, settings: Settings, connection: sqlite3.Connection):
        self.settings = settings
        self.connection = connection
        self.providers: list[BaseMarketDataProvider] = [
            StooqProvider(settings, connection),
            FinnhubQuoteProvider(settings, connection),
            AlphaVantageProvider(settings, connection),
            YahooFinanceProvider(settings, connection),
            CoinGeckoProvider(settings, connection),
            FredProvider(settings, connection),
        ]

    def provider_for_asset_type(self, asset_type: str) -> BaseMarketDataProvider | None:
        normalized = asset_type.lower()
        for provider in self.providers:
            if provider.provider_name in {
                "stooq",
                "finnhub",
                "alpha_vantage",
                "yahoo_finance",
            }:
                continue
            if provider.supports_asset_type(normalized):
                return provider
        return None

    def providers_for(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
        capability: ProviderCapability,
    ) -> tuple[ProviderCapabilityMatch, ...]:
        normalized_capability = str(capability).strip().upper()
        if normalized_capability not in {"EOD", "QUOTE"}:
            return ()
        rows = connection.execute(
            """
            SELECT symbol.provider, symbol.capability, symbol.listing_id,
                   symbol.provider_symbol, listing.currency, listing.mic,
                   instrument.instrument_type
            FROM provider_symbols AS symbol
            JOIN instrument_listings AS listing ON listing.id = symbol.listing_id
            JOIN instruments AS instrument ON instrument.id = listing.instrument_id
            WHERE symbol.listing_id = ?
              AND symbol.capability = ?
              AND symbol.status = 'VERIFIED'
              AND listing.listing_status = 'ACTIVE'
            ORDER BY symbol.provider, symbol.version DESC
            """,
            (listing_id, normalized_capability),
        ).fetchall()
        matches: list[ProviderCapabilityMatch] = []
        seen: set[str] = set()
        for row in rows:
            provider_name = str(row["provider"]).strip().lower()
            expected_provider = "stooq" if normalized_capability == "EOD" else "finnhub"
            if provider_name != expected_provider or provider_name in seen:
                continue
            provider = self.provider_named(provider_name)
            asset_type = str(row["instrument_type"]).strip().lower()
            if provider is None or not provider.supports_asset_type(asset_type):
                continue
            if normalized_capability == "QUOTE":
                mic = str(row["mic"] or "").strip().upper()
                if mic not in FinnhubQuoteProvider.supported_mics:
                    continue
            seen.add(provider_name)
            matches.append(
                ProviderCapabilityMatch(
                    provider=provider_name,
                    capability=cast(ProviderCapability, normalized_capability),
                    listing_id=int(row["listing_id"]),
                    provider_symbol=str(row["provider_symbol"]).strip(),
                    currency=str(row["currency"]).strip().upper(),
                    priority=10,
                )
            )
        return tuple(matches)

    def provider_named(self, provider_name: str) -> BaseMarketDataProvider | None:
        normalized = provider_name.strip().lower()
        return next(
            (provider for provider in self.providers if provider.provider_name == normalized),
            None,
        )

    def availability_for(self, provider_name: str) -> ProviderAvailability:
        normalized = provider_name.strip().lower()
        if normalized == "yahoo_finance":
            return ProviderAvailability("DISABLED", "NOT_PRIMARY_POLICY", None)
        provider = self.provider_named(normalized)
        availability = getattr(provider, "availability", None)
        if callable(availability):
            return availability()
        if provider is None:
            return ProviderAvailability("DISABLED", "UNSUPPORTED_CAPABILITY", None)
        return ProviderAvailability("AVAILABLE", None, None)

    def statuses(self) -> list[dict[str, Any]]:
        usage = self.usage_by_provider()
        return [
            {
                "provider": provider.provider_name,
                "enabled": (
                    self.settings.enable_real_data
                    and self.availability_for(provider.provider_name).state == "AVAILABLE"
                ),
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
