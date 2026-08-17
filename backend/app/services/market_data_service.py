from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import pandas as pd

from backend.app.config import get_settings
from backend.app.data_providers import (
    FinnhubQuoteProvider,
    MissingApiKey,
    ProviderError,
    ProviderRegistry,
    RateLimitExceeded,
    RealDataDisabled,
    StooqProvider,
)
from backend.app.data_providers.base import BaseMarketDataProvider
from backend.app.models.market_data import MarketObservationEnvelope
from backend.app.services.common import now_utc as _now
from backend.app.services.instrument_quality_service import InstrumentQualityService
from backend.app.services.instrument_service import InstrumentService
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.scoring_engine import ScoringEngine
from backend.app.services.sentiment_engine import aggregate_news_sentiment


class MarketDataService:
    def __init__(self) -> None:
        self.scoring_engine = ScoringEngine()
        self.portfolio_engine = PortfolioEngine()
        self.observation_service = MarketObservationService()

    def get_provider_for_asset(
        self,
        connection: sqlite3.Connection,
        asset_type: str,
    ) -> BaseMarketDataProvider | None:
        return ProviderRegistry(get_settings(), connection).provider_for_asset_type(asset_type)

    def refresh_asset_prices(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        force: bool = False,
    ) -> dict[str, Any]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")

        settings = get_settings()
        registry = ProviderRegistry(settings, connection)
        provider: BaseMarketDataProvider | None = None
        provider_symbol: str | None = None
        listing_id = asset["instrument_listing_id"]
        selected_capability = self._capability_for_asset(str(asset["asset_type"]))
        if (
            listing_id is not None
            and selected_capability == "EOD"
        ):
            matches = registry.providers_for(connection, int(listing_id), "EOD")
            if not matches:
                matches = registry.providers_for(connection, int(listing_id), "QUOTE")
                if matches:
                    selected_capability = "QUOTE"
            if matches:
                match = matches[0]
                provider = registry.provider_named(match.provider)
                provider_symbol = match.provider_symbol
        if provider is None:
            provider = self.get_provider_for_asset(connection, str(asset["asset_type"]))

        if not settings.enable_real_data:
            return self._fallback_result(
                connection=connection,
                asset=asset,
                provider=provider.provider_name if provider else None,
                message="Dati reali disattivati. Stai usando dati seed/demo.",
                capability=selected_capability,
            )

        if provider is None:
            return self._fallback_result(
                connection=connection,
                asset=asset,
                provider=None,
                message="Nessun provider configurato per questa asset class, uso dati locali.",
                capability=selected_capability,
            )

        if not provider.api_key_configured():
            return self._fallback_result(
                connection=connection,
                asset=asset,
                provider=provider.provider_name,
                message="API key non configurata.",
                capability=selected_capability,
            )

        if isinstance(provider, StooqProvider):
            return self._refresh_stooq_prices(
                connection,
                asset,
                provider,
                provider_symbol,
                force,
            )

        if isinstance(provider, FinnhubQuoteProvider):
            return self._refresh_finnhub_quote(
                connection,
                asset,
                provider,
                provider_symbol,
                force,
            )

        try:
            prices, used_cache = provider.get_daily_prices(asset["symbol"], force=force)
        except RateLimitExceeded as exc:
            return self._fallback_result(connection, asset, provider.provider_name, str(exc))
        except MissingApiKey as exc:
            return self._fallback_result(connection, asset, provider.provider_name, str(exc))
        except RealDataDisabled as exc:
            return self._fallback_result(connection, asset, provider.provider_name, str(exc))
        except ProviderError as exc:
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                f"{exc} Uso dati locali.",
            )
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError):
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider non disponibile, uso dati locali.",
            )

        if not prices:
            now = datetime.now(UTC)
            self._record_provider_no_data(
                connection,
                asset,
                provider.provider_name,
                now,
            )
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider senza dati utilizzabili, uso dati locali.",
                used_cache=used_cache,
            )

        before_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
        )
        inserted, updated, accepted = self._ingest_legacy_prices(
            connection,
            asset,
            prices,
            provider.provider_name,
        )
        if not accepted:
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider senza dati validi, conservo l'ultimo dato locale.",
                used_cache=used_cache,
            )
        after_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
        )
        inserted = max(0, after_count - before_count)
        updated = max(0, updated - inserted)
        if inserted or updated:
            self._recalculate_signal(connection, asset["id"])
            self._refresh_portfolio_if_needed(connection, asset["id"])
        return {
            "symbol": asset["symbol"],
            "provider": provider.provider_name,
            "rows_inserted": inserted,
            "rows_updated": updated,
            "used_cache": used_cache,
            "used_fallback": False,
            "message": "Prezzi aggiornati da cache." if used_cache else "Prezzi aggiornati da provider reale.",
        }

    def _refresh_stooq_prices(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        provider: StooqProvider,
        provider_symbol: str | None,
        force: bool,
    ) -> dict[str, Any]:
        listing = {
            "id": int(asset["instrument_listing_id"]),
            "timezone": asset["listing_timezone"],
            "currency": asset["listing_currency"],
            "instrument_type": asset["instrument_type"],
            "provider_symbol": provider_symbol,
        }
        try:
            envelopes = provider.fetch_observations(
                listing,
                None,
                None,
                bypass_cache=force,
            )
        except (RateLimitExceeded, MissingApiKey, RealDataDisabled) as exc:
            return self._fallback_result(connection, asset, provider.provider_name, str(exc))
        except ProviderError as exc:
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                f"{exc} Uso dati locali.",
            )
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError):
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider non disponibile, uso dati locali.",
            )

        now = datetime.now(UTC)
        if not envelopes:
            self._record_provider_no_data(
                connection,
                asset,
                provider.provider_name,
                now,
                operation=provider.operation,
            )
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider senza dati utilizzabili, uso dati locali.",
                used_cache=provider.last_fetch_used_cache,
            )

        before_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
        )
        ingest_result = self.observation_service.ingest_batch(connection, envelopes, now)
        accepted = ingest_result.accepted > 0 or ingest_result.duplicates > 0
        if not accepted:
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider senza dati validi, conservo l'ultimo dato locale.",
                used_cache=provider.last_fetch_used_cache,
            )
        after_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
        )
        inserted = max(0, after_count - before_count)
        updated = max(0, ingest_result.projected_price_rows - inserted)
        if inserted or updated:
            self._recalculate_signal(connection, int(asset["id"]))
            self._refresh_portfolio_if_needed(connection, int(asset["id"]))
        self.observation_service.latest_compatible(
            connection,
            int(asset["instrument_listing_id"]),
            "EOD",
            now,
            requested_provider=provider.provider_name,
        )
        self._assess_quality(connection, asset, now)
        return {
            "symbol": asset["symbol"],
            "provider": provider.provider_name,
            "rows_inserted": inserted,
            "rows_updated": updated,
            "used_cache": provider.last_fetch_used_cache,
            "used_fallback": False,
            "message": (
                "Prezzi aggiornati da cache."
                if provider.last_fetch_used_cache
                else "Prezzi aggiornati da provider reale."
            ),
        }

    def _refresh_finnhub_quote(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        provider: FinnhubQuoteProvider,
        provider_symbol: str | None,
        force: bool,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        listing = {
            "id": int(asset["instrument_listing_id"]),
            "mic": asset["listing_mic"],
            "timezone": asset["listing_timezone"],
            "currency": asset["listing_currency"],
            "instrument_type": asset["instrument_type"],
            "provider_symbol": provider_symbol,
            "session": "REGULAR",
        }
        try:
            envelope = provider.fetch_quote(
                listing,
                now,
                bypass_cache=force,
            )
        except (RateLimitExceeded, MissingApiKey, RealDataDisabled) as exc:
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                str(exc),
                capability="QUOTE",
            )
        except ProviderError as exc:
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                f"{exc} Uso dati locali.",
                capability="QUOTE",
            )
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError):
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider non disponibile, uso dati locali.",
                capability="QUOTE",
            )

        ingest_result = self.observation_service.ingest_batch(connection, [envelope], now)
        accepted = ingest_result.accepted > 0 or ingest_result.duplicates > 0
        if not accepted:
            return self._fallback_result(
                connection,
                asset,
                provider.provider_name,
                "Provider senza quote valide, conservo l'ultima quote compatibile.",
                used_cache=provider.last_fetch_used_cache,
                capability="QUOTE",
            )

        self.observation_service.latest_compatible(
            connection,
            int(asset["instrument_listing_id"]),
            "QUOTE",
            now,
            requested_provider=provider.provider_name,
        )
        self._assess_quality(connection, asset, now)
        return {
            "symbol": asset["symbol"],
            "provider": provider.provider_name,
            "rows_inserted": 0,
            "rows_updated": 0,
            "used_cache": provider.last_fetch_used_cache,
            "used_fallback": False,
            "message": (
                "Quote aggiornata da cache."
                if provider.last_fetch_used_cache
                else "Quote aggiornata da provider reale."
            ),
        }

    def refresh_all_watchlist(
        self,
        connection: sqlite3.Connection,
        limit: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        query = """
            SELECT symbol
            FROM assets
            ORDER BY asset_type, symbol
        """
        rows = connection.execute(query).fetchall()
        selected_rows = rows[:limit] if limit else rows
        symbols = [row["symbol"] for row in selected_rows]
        results = [self.refresh_asset_prices(connection, symbol, force=force) for symbol in symbols]
        return {
            "summary": {
                "requested": len(symbols),
                "updated": sum(1 for item in results if not item["used_fallback"]),
                "fallback": sum(1 for item in results if item["used_fallback"]),
                "rows_inserted": sum(int(item["rows_inserted"]) for item in results),
                "rows_updated": sum(int(item["rows_updated"]) for item in results),
            },
            "results": results,
        }

    def save_prices_to_db(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        prices: list[dict[str, Any]],
        provider: str,
    ) -> tuple[int, int]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")
        inserted, projected, _accepted = self._ingest_legacy_prices(
            connection,
            asset,
            prices,
            provider,
        )
        return inserted, max(0, projected - inserted)

    def _ingest_legacy_prices(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        prices: list[dict[str, Any]],
        provider: str,
    ) -> tuple[int, int, bool]:
        if asset["instrument_listing_id"] is None:
            InstrumentService.backfill_active_assets(connection)
            refreshed_asset = self._asset(connection, asset["symbol"])
            if refreshed_asset is None or refreshed_asset["instrument_listing_id"] is None:
                raise ValueError(f"Listing per {asset['symbol']} non risolto.")
            asset = refreshed_asset

        now = datetime.now(UTC)
        before_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
        )
        envelopes = [
            self._legacy_price_envelope(asset, price, provider, now)
            for price in prices
        ]
        result = self.observation_service.ingest_batch(connection, envelopes, now)
        after_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
                (asset["id"],),
            ).fetchone()[0]
        )
        inserted = max(0, after_count - before_count)
        accepted = result.accepted > 0 or result.duplicates > 0
        return inserted, result.projected_price_rows, accepted

    @staticmethod
    def _legacy_price_envelope(
        asset: sqlite3.Row,
        price: dict[str, Any],
        provider: str,
        now: datetime,
    ) -> MarketObservationEnvelope:
        timezone = (
            str(asset["listing_timezone"]).strip()
            if asset["listing_timezone"] is not None
            else None
        )
        observed_at = MarketDataService._legacy_observed_at(
            price.get("provider_observed_at") or price.get("date"),
            timezone,
        )
        asset_type = str(asset["asset_type"]).lower()
        capability = MarketDataService._capability_for_asset(asset_type)
        source_quality = "reference" if capability in {"REFERENCE", "FX"} else "eod"
        raw_fields = {
            key: price.get(key)
            for key in (
                "bid",
                "ask",
                "last",
                "open",
                "high",
                "low",
                "close",
                "adjusted_close",
                "volume",
            )
            if key in price
        }
        canonical_payload = json.dumps(
            price,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return MarketObservationEnvelope(
            listing_id=int(asset["instrument_listing_id"]),
            provider=provider,
            capability=capability,
            operation="get_daily_prices",
            received_at=now,
            provider_observed_at=observed_at,
            timezone=timezone,
            session="24X7" if asset_type == "crypto" else "REGULAR",
            currency=str(price.get("currency") or asset["currency"]).strip().upper(),
            source_quality=source_quality,
            kind="BAR",
            raw_fields=raw_fields,
            raw_payload_sha256=hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _legacy_observed_at(value: object, timezone: str | None) -> datetime | None:
        if value is None or not str(value).strip():
            return None
        if not timezone:
            return None
        try:
            zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, time.min)
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(UTC)

    def get_data_status(self, connection: sqlite3.Connection, symbol: str) -> dict[str, Any]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")

        latest = connection.execute(
            """
            SELECT date, source, provider, is_real_data, fetched_at
            FROM price_history
            WHERE asset_id = ?
            ORDER BY date DESC, is_real_data DESC, id DESC
            LIMIT 1
            """,
            (asset["id"],),
        ).fetchone()
        provider = self.get_provider_for_asset(connection, asset["asset_type"])
        cache_status = self._cache_status(connection, provider.provider_name if provider else None, asset["symbol"])

        if not get_settings().enable_real_data:
            message = "Dati reali disattivati. Stai usando dati seed/demo."
        elif provider is None:
            message = "Nessun provider configurato per questa asset class, uso dati locali."
        elif not provider.api_key_configured():
            message = "API key non configurata."
        elif cache_status == "HIT":
            message = "Cache valida disponibile."
        else:
            message = "Refresh manuale disponibile."

        return {
            "symbol": asset["symbol"],
            "last_price_date": latest["date"] if latest else None,
            "last_source": latest["source"] if latest else None,
            "provider": latest["provider"] if latest and latest["provider"] else (provider.provider_name if provider else None),
            "is_real_data": bool(latest["is_real_data"]) if latest else False,
            "last_fetch_at": latest["fetched_at"] if latest else None,
            "cache_status": cache_status,
            "message": message,
        }

    def get_global_status(self, connection: sqlite3.Connection) -> dict[str, Any]:
        settings = get_settings()
        registry = ProviderRegistry(settings, connection)
        stats = self._cache_stats(connection)
        latest_row = connection.execute(
            """
            SELECT MAX(COALESCE(fetched_at, created_at)) AS last_update
            FROM price_history
            """
        ).fetchone()
        count_row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                SUM(CASE WHEN is_real_data = 1 THEN 1 ELSE 0 END) AS real_rows
            FROM price_history
            """
        ).fetchone()
        total_rows = int(count_row["total_rows"] or 0)
        real_rows = int(count_row["real_rows"] or 0)
        if total_rows == 0 or real_rows == 0:
            data_mode = "SEED"
        elif real_rows == total_rows:
            data_mode = "REAL"
        else:
            data_mode = "MIXED"

        return {
            "enable_real_data": settings.enable_real_data,
            "provider_status": registry.statuses(),
            "api_usage": registry.usage_rows(),
            "cache_stats": stats,
            "global_last_update": latest_row["last_update"] if latest_row else None,
            "data_mode": data_mode,
        }

    def get_usage(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        return ProviderRegistry(get_settings(), connection).usage_rows()

    def _asset(self, connection: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT asset.id, asset.symbol, asset.asset_type, asset.risk_level,
                   asset.currency, asset.instrument_listing_id,
                   listing.mic AS listing_mic,
                   listing.timezone AS listing_timezone,
                   listing.currency AS listing_currency,
                   instrument.id AS instrument_id,
                   instrument.instrument_type
            FROM assets AS asset
            LEFT JOIN instrument_listings AS listing
              ON listing.id = asset.instrument_listing_id
            LEFT JOIN instruments AS instrument
              ON instrument.id = listing.instrument_id
            WHERE UPPER(asset.symbol) = UPPER(?)
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

    def _fallback_result(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        provider: str | None,
        message: str,
        used_cache: bool = False,
        capability: str | None = None,
    ) -> dict[str, Any]:
        if asset["instrument_listing_id"] is not None:
            selected_capability = capability or self._capability_for_asset(
                str(asset["asset_type"])
            )
            now = datetime.now(UTC)
            if selected_capability != "QUOTE" or self._has_fresh_observation(
                connection,
                int(asset["instrument_listing_id"]),
                selected_capability,
                now,
            ):
                self.observation_service.latest_compatible(
                    connection,
                    int(asset["instrument_listing_id"]),
                    selected_capability,
                    now,
                    requested_provider=provider,
                )
        if provider == "stooq":
            self._assess_quality(connection, asset, datetime.now(UTC))
        return {
            "symbol": str(asset["symbol"]).upper(),
            "provider": provider,
            "rows_inserted": 0,
            "rows_updated": 0,
            "used_cache": used_cache,
            "used_fallback": True,
            "message": message,
        }

    @staticmethod
    def _has_fresh_observation(
        connection: sqlite3.Connection,
        listing_id: int,
        capability: str,
        now: datetime,
    ) -> bool:
        row = connection.execute(
            """
            SELECT provider_observed_at, source_quality
            FROM market_observations AS observation
            WHERE observation.listing_id = ?
              AND observation.capability = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM market_observations AS newer
                  WHERE newer.supersedes_observation_id = observation.id
              )
            ORDER BY observation.provider_observed_at DESC,
                     observation.ingested_at DESC,
                     observation.id DESC
            LIMIT 1
            """,
            (listing_id, capability.strip().upper()),
        ).fetchone()
        if row is None:
            return False
        try:
            observed_at = datetime.fromisoformat(
                str(row["provider_observed_at"]).replace("Z", "+00:00")
            )
        except ValueError:
            return False
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return False
        return (
            MarketObservationService.effective_quality_for(
                capability.strip().upper(),
                str(row["source_quality"]),
                observed_at,
                now,
            )
            != "stale"
        )

    def _record_provider_no_data(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        provider: str,
        now: datetime,
        operation: str = "get_daily_prices",
    ) -> None:
        listing_id = asset["instrument_listing_id"]
        if listing_id is None:
            return
        capability = self._capability_for_asset(str(asset["asset_type"]))
        stable_payload = f"{provider}|{capability}|{operation}|PROVIDER_NO_DATA"
        envelope = MarketObservationEnvelope(
            listing_id=int(listing_id),
            provider=provider,
            capability=capability,
            operation=operation,
            received_at=now,
            provider_observed_at=None,
            timezone=None,
            session=None,
            currency=None,
            source_quality=None,
            kind=None,
            raw_fields={"reason_code": "PROVIDER_NO_DATA"},
            raw_payload_sha256=hashlib.sha256(stable_payload.encode("utf-8")).hexdigest(),
        )
        self.observation_service.ingest_batch(connection, [envelope], now)

    @staticmethod
    def _assess_quality(
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        now: datetime,
    ) -> None:
        instrument_id = asset["instrument_id"]
        if instrument_id is None:
            return
        InstrumentQualityService().assess_and_record(
            connection,
            int(instrument_id),
            now,
        )

    @staticmethod
    def _capability_for_asset(asset_type: str) -> str:
        normalized = asset_type.strip().lower()
        if normalized == "fx":
            return "FX"
        if normalized in {"macro", "bond_proxy"}:
            return "REFERENCE"
        return "EOD"

    def _recalculate_signal(self, connection: sqlite3.Connection, asset_id: int) -> None:
        asset = connection.execute(
            """
            SELECT id, symbol, risk_level
            FROM assets
            WHERE id = ?
            """,
            (asset_id,),
        ).fetchone()
        if asset is None:
            return

        rows = connection.execute(
            """
            SELECT date, open, high, low, close, adjusted_close, volume, source
            FROM price_history
            WHERE asset_id = ?
            ORDER BY date ASC
            """,
            (asset_id,),
        ).fetchall()
        if not rows:
            return

        score = self.scoring_engine.score_prices(
            pd.DataFrame([dict(row) for row in rows]),
            asset_id=asset["id"],
            symbol=asset["symbol"],
            risk_level=asset["risk_level"],
        )
        news_summary = aggregate_news_sentiment(connection, asset["symbol"], lookback_days=7)
        news_score = 0.0
        if news_summary["news_count"] > 0:
            weight = get_settings().news_sentiment_weight
            news_score = float(news_summary["average_sentiment_score"]) * weight
            news_score = max(-weight, min(weight, news_score))
        final_score = round(max(0.0, min(100.0, float(score["score"]) + news_score)), 2)
        final_signal = self.scoring_engine._signal_from_score(final_score)
        now = _now()
        connection.execute("DELETE FROM signals WHERE asset_id = ? AND source = 'scoring_engine'", (asset_id,))
        connection.execute(
            """
            INSERT INTO signals (
                asset_id, symbol, signal, score, technical_score, news_score, final_score,
                news_sentiment_label, news_impact_level, risk_level, confidence, technical_summary,
                reasons_json, subscores_json, indicators_json, rationale, source, generated_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scoring_engine', ?, ?, ?)
            """,
            (
                asset["id"],
                score["symbol"],
                final_signal,
                final_score,
                score["score"],
                round(news_score, 2),
                final_score,
                news_summary["sentiment_label"],
                news_summary["impact_level"],
                score["risk_level"],
                score["confidence"],
                score["technical_summary"],
                json.dumps(score["reasons"]),
                json.dumps(score["subscores"]),
                json.dumps(score["indicators"]),
                score["technical_summary"],
                now,
                now,
                now,
            ),
        )

    def _refresh_portfolio_if_needed(self, connection: sqlite3.Connection, asset_id: int) -> None:
        row = connection.execute(
            "SELECT id FROM portfolio_positions WHERE asset_id = ? AND quantity > 0 LIMIT 1",
            (asset_id,),
        ).fetchone()
        if row is not None:
            self.portfolio_engine.refresh_portfolio(connection, create_snapshot=False)

    def _cache_status(self, connection: sqlite3.Connection, provider: str | None, symbol: str) -> str:
        if not provider:
            return "NO_PROVIDER"
        row = connection.execute(
            """
            SELECT expires_at
            FROM api_cache
            WHERE provider = ? AND UPPER(symbol) = UPPER(?)
            ORDER BY last_update DESC, id DESC
            LIMIT 1
            """,
            (provider, symbol),
        ).fetchone()
        if row is None:
            return "MISS"
        if not row["expires_at"]:
            return "MISS"
        try:
            return "HIT" if datetime.fromisoformat(row["expires_at"]) > datetime.now(UTC).replace(tzinfo=None) else "EXPIRED"
        except ValueError:
            return "MISS"

    def _cache_stats(self, connection: sqlite3.Connection) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT expires_at
            FROM api_cache
            """
        ).fetchall()
        now = datetime.now(UTC).replace(tzinfo=None)
        valid = 0
        expired = 0
        for row in rows:
            try:
                if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) > now:
                    valid += 1
                else:
                    expired += 1
            except ValueError:
                expired += 1
        return {"entries": len(rows), "valid": valid, "expired": expired}
