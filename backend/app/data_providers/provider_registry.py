from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from backend.app.config import Settings
from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
from backend.app.data_providers.base import BaseMarketDataProvider
from backend.app.data_providers.coingecko import CoinGeckoProvider
from backend.app.data_providers.ecb import ECB_ALLOWED_HOSTS, EcbFxProvider
from backend.app.data_providers.finnhub_quote import FinnhubQuoteProvider
from backend.app.data_providers.fred import FredReferenceProvider
from backend.app.data_providers.stooq import StooqProvider
from backend.app.data_providers.transport import SafeProviderTransport
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
            FredReferenceProvider(settings, connection),
        ]
        # FX BCE: modello separato (fx_rates/FXQuote), stesso trasporto governato e bucket `ecb`.
        self.ecb_fx_provider = EcbFxProvider(
            SafeProviderTransport(allowed_hosts=ECB_ALLOWED_HOSTS, settings=settings),
            cache_ttl_seconds=max(0, settings.ecb_fx_cache_ttl_hours) * 3600,
        )

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
            instrument_type = str(row["instrument_type"]).strip().upper()
            if instrument_type == "CRYPTO":
                expected_provider = "coingecko"
            else:
                expected_provider = "stooq" if normalized_capability == "EOD" else "finnhub"
            if provider_name != expected_provider or provider_name in seen:
                continue
            provider = self.provider_named(provider_name)
            asset_type = instrument_type.lower()
            if provider is None or not provider.supports_asset_type(asset_type):
                continue
            currency = str(row["currency"]).strip().upper()
            if (
                provider_name == "coingecko"
                and currency not in CoinGeckoProvider.supported_quote_currencies
            ):
                continue
            if normalized_capability == "QUOTE":
                mic = str(row["mic"] or "").strip().upper()
                if (
                    provider_name == "finnhub"
                    and mic not in FinnhubQuoteProvider.supported_mics
                ):
                    continue
            seen.add(provider_name)
            matches.append(
                ProviderCapabilityMatch(
                    provider=provider_name,
                    capability=cast(ProviderCapability, normalized_capability),
                    listing_id=int(row["listing_id"]),
                    provider_symbol=str(row["provider_symbol"]).strip(),
                    currency=currency,
                    priority=10,
                )
            )
        if "coingecko" in seen:
            return tuple(matches)

        listing = connection.execute(
            """
            SELECT listing.id, listing.instrument_id, listing.currency,
                   instrument.instrument_type
            FROM instrument_listings AS listing
            JOIN instruments AS instrument ON instrument.id = listing.instrument_id
            WHERE listing.id = ? AND listing.listing_status = 'ACTIVE'
            """,
            (listing_id,),
        ).fetchone()
        if (
            listing is None
            or str(listing["instrument_type"]).strip().upper() != "CRYPTO"
            or str(listing["currency"]).strip().upper()
            not in CoinGeckoProvider.supported_quote_currencies
        ):
            return tuple(matches)

        identifiers = connection.execute(
            """
            SELECT DISTINCT identifier.normalized_value
            FROM instrument_identifiers AS identifier
            LEFT JOIN instrument_listings AS owner_listing
              ON owner_listing.id = identifier.listing_id
            WHERE identifier.scheme = 'COINGECKO_ID'
              AND COALESCE(identifier.instrument_id, owner_listing.instrument_id) = ?
              AND EXISTS (
                  SELECT 1
                  FROM instrument_identifier_attestations AS attestation
                  WHERE attestation.identifier_id = identifier.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM instrument_identifiers AS other_identifier
                  LEFT JOIN instrument_listings AS other_listing
                    ON other_listing.id = other_identifier.listing_id
                  WHERE other_identifier.id != identifier.id
                    AND other_identifier.scheme = 'COINGECKO_ID'
                    AND other_identifier.normalized_value = identifier.normalized_value
                    AND COALESCE(
                          other_identifier.instrument_id,
                          other_listing.instrument_id
                        ) != ?
              )
            ORDER BY identifier.normalized_value
            """,
            (listing["instrument_id"], listing["instrument_id"]),
        ).fetchall()
        if len(identifiers) != 1:
            return tuple(matches)
        matches.append(
            ProviderCapabilityMatch(
                provider="coingecko",
                capability=cast(ProviderCapability, normalized_capability),
                listing_id=listing_id,
                provider_symbol=str(identifiers[0]["normalized_value"]).strip(),
                currency=str(listing["currency"]).strip().upper(),
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
        supports = [
            asset_type for asset_type in known_types if provider.supports_asset_type(asset_type)
        ]
        attribution = getattr(provider, "attribution", None)
        if isinstance(attribution, str) and attribution:
            supports.append(attribution)
        return supports
