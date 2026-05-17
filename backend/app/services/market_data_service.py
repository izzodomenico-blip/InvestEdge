from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from backend.app.config import get_settings
from backend.app.data_providers import MissingApiKey, ProviderError, ProviderRegistry, RateLimitExceeded, RealDataDisabled
from backend.app.data_providers.base import BaseMarketDataProvider
from backend.app.services.portfolio_engine import PortfolioEngine
from backend.app.services.scoring_engine import ScoringEngine


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class MarketDataService:
    def __init__(self) -> None:
        self.scoring_engine = ScoringEngine()
        self.portfolio_engine = PortfolioEngine()

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
        provider = self.get_provider_for_asset(connection, asset["asset_type"])
        if provider is None:
            return self._fallback_result(
                symbol=asset["symbol"],
                provider=None,
                message="Nessun provider configurato per questa asset class, uso dati locali.",
            )

        if not settings.enable_real_data:
            return self._fallback_result(
                symbol=asset["symbol"],
                provider=provider.provider_name,
                message="Dati reali disattivati. Stai usando dati seed/demo.",
            )

        if not provider.api_key_configured():
            return self._fallback_result(
                symbol=asset["symbol"],
                provider=provider.provider_name,
                message="API key non configurata.",
            )

        try:
            prices, used_cache = provider.get_daily_prices(asset["symbol"], force=force)
        except RateLimitExceeded as exc:
            return self._fallback_result(asset["symbol"], provider.provider_name, str(exc))
        except MissingApiKey as exc:
            return self._fallback_result(asset["symbol"], provider.provider_name, str(exc))
        except RealDataDisabled as exc:
            return self._fallback_result(asset["symbol"], provider.provider_name, str(exc))
        except ProviderError as exc:
            return self._fallback_result(asset["symbol"], provider.provider_name, f"{exc} Uso dati locali.")
        except Exception:
            return self._fallback_result(
                asset["symbol"],
                provider.provider_name,
                "Provider non disponibile, uso dati locali.",
            )

        if not prices:
            return self._fallback_result(
                asset["symbol"],
                provider.provider_name,
                "Provider senza dati utilizzabili, uso dati locali.",
                used_cache=used_cache,
            )

        inserted, updated = self.save_prices_to_db(connection, asset["symbol"], prices, provider.provider_name)
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

        inserted = 0
        updated = 0
        now = _now()
        for price in prices:
            date_value = str(price.get("date") or "")
            if not date_value:
                continue

            existing_rows = connection.execute(
                """
                SELECT id
                FROM price_history
                WHERE asset_id = ? AND date = ?
                ORDER BY is_real_data DESC, id ASC
                """,
                (asset["id"], date_value),
            ).fetchall()
            params = (
                float(price["open"]),
                float(price["high"]),
                float(price["low"]),
                float(price["close"]),
                float(price.get("adjusted_close", price["close"])),
                float(price.get("volume", 0) or 0),
                "real",
                provider,
                1,
                now,
            )
            if not existing_rows:
                connection.execute(
                    """
                    INSERT INTO price_history (
                        asset_id, date, open, high, low, close, adjusted_close, volume,
                        source, provider, is_real_data, fetched_at, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (asset["id"], date_value, *params, now),
                )
                inserted += 1
                continue

            primary_id = existing_rows[0]["id"]
            connection.execute(
                """
                UPDATE price_history
                SET open = ?, high = ?, low = ?, close = ?, adjusted_close = ?, volume = ?,
                    source = ?, provider = ?, is_real_data = ?, fetched_at = ?
                WHERE id = ?
                """,
                (*params, primary_id),
            )
            updated += 1
            duplicate_ids = [row["id"] for row in existing_rows[1:]]
            if duplicate_ids:
                placeholders = ",".join("?" for _ in duplicate_ids)
                connection.execute(f"DELETE FROM price_history WHERE id IN ({placeholders})", duplicate_ids)

        return inserted, updated

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

        if provider is None:
            message = "Nessun provider configurato per questa asset class, uso dati locali."
        elif not get_settings().enable_real_data:
            message = "Dati reali disattivati. Stai usando dati seed/demo."
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
            SELECT id, symbol, asset_type, risk_level
            FROM assets
            WHERE UPPER(symbol) = UPPER(?)
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

    def _fallback_result(
        self,
        symbol: str,
        provider: str | None,
        message: str,
        used_cache: bool = False,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "provider": provider,
            "rows_inserted": 0,
            "rows_updated": 0,
            "used_cache": used_cache,
            "used_fallback": True,
            "message": message,
        }

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
        now = _now()
        connection.execute("DELETE FROM signals WHERE asset_id = ? AND source = 'scoring_engine'", (asset_id,))
        connection.execute(
            """
            INSERT INTO signals (
                asset_id, symbol, signal, score, risk_level, confidence, technical_summary,
                reasons_json, subscores_json, indicators_json, rationale, source, generated_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scoring_engine', ?, ?, ?)
            """,
            (
                asset["id"],
                score["symbol"],
                score["signal"],
                score["score"],
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
