from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.data_providers import (
    AlphaVantageNewsProvider,
    BaseNewsProvider,
    MockNewsProvider,
    NewsMissingApiKey,
    NewsProviderError,
    NewsRateLimitExceeded,
    NewsRealDisabled,
)
from backend.app.services.sentiment_engine import aggregate_news_sentiment, estimate_impact


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class NewsEngine:
    """News orchestration engine. Mock/fallback by default, real provider opt-in."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def settings(self) -> Settings:
        return self._settings or get_settings()

    # -- providers ---------------------------------------------------------
    def real_provider(self, connection: sqlite3.Connection) -> BaseNewsProvider:
        return AlphaVantageNewsProvider(self.settings(), connection)

    def mock_provider(self, connection: sqlite3.Connection) -> BaseNewsProvider:
        return MockNewsProvider(self.settings(), connection)

    def active_provider(self, connection: sqlite3.Connection) -> BaseNewsProvider:
        settings = self.settings()
        if settings.enable_real_news:
            return self.real_provider(connection)
        return self.mock_provider(connection)

    # -- core operations ---------------------------------------------------
    def refresh_news_for_symbol(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        force: bool = False,
    ) -> dict[str, Any]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")

        settings = self.settings()
        if not settings.enable_real_news:
            inserted, updated = self._save_provider_news(connection, asset, self.mock_provider(connection), force=force)
            return self._refresh_result(
                symbol=asset["symbol"],
                provider="mock_news",
                inserted=inserted,
                updated=updated,
                used_cache=False,
                used_fallback=True,
                message="News reali disattivate. Stai usando news demo/locali.",
            )

        provider = self.real_provider(connection)
        if not provider.api_key_configured():
            inserted, updated = self._save_provider_news(connection, asset, self.mock_provider(connection), force=force)
            return self._refresh_result(
                symbol=asset["symbol"],
                provider=provider.provider_name,
                inserted=inserted,
                updated=updated,
                used_cache=False,
                used_fallback=True,
                message="Provider news non configurato.",
            )

        try:
            news, used_cache = provider.get_news_for_symbol(asset["symbol"], force=force)
        except NewsRateLimitExceeded:
            inserted, updated = self._save_provider_news(connection, asset, self.mock_provider(connection), force=force)
            return self._refresh_result(
                symbol=asset["symbol"],
                provider=provider.provider_name,
                inserted=inserted,
                updated=updated,
                used_cache=False,
                used_fallback=True,
                message="Limite news giornaliero raggiunto, uso news locali.",
            )
        except NewsMissingApiKey:
            inserted, updated = self._save_provider_news(connection, asset, self.mock_provider(connection), force=force)
            return self._refresh_result(
                symbol=asset["symbol"],
                provider=provider.provider_name,
                inserted=inserted,
                updated=updated,
                used_cache=False,
                used_fallback=True,
                message="Provider news non configurato.",
            )
        except NewsRealDisabled:
            inserted, updated = self._save_provider_news(connection, asset, self.mock_provider(connection), force=force)
            return self._refresh_result(
                symbol=asset["symbol"],
                provider=provider.provider_name,
                inserted=inserted,
                updated=updated,
                used_cache=False,
                used_fallback=True,
                message="News reali disattivate. Stai usando news demo/locali.",
            )
        except (NewsProviderError, Exception):
            inserted, updated = self._save_provider_news(connection, asset, self.mock_provider(connection), force=force)
            return self._refresh_result(
                symbol=asset["symbol"],
                provider=provider.provider_name,
                inserted=inserted,
                updated=updated,
                used_cache=False,
                used_fallback=True,
                message="Provider news non disponibile, uso news locali.",
            )

        inserted, updated = self.save_news_to_db(connection, asset, news, provider.provider_name)
        return self._refresh_result(
            symbol=asset["symbol"],
            provider=provider.provider_name,
            inserted=inserted,
            updated=updated,
            used_cache=used_cache,
            used_fallback=False,
            message="News aggiornate da cache." if used_cache else "News aggiornate da provider reale.",
        )

    def save_news_to_db(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row | dict[str, Any],
        news: list[dict[str, Any]],
        provider_name: str,
    ) -> tuple[int, int]:
        asset_id = asset["id"]
        symbol_upper = str(asset["symbol"]).upper()
        inserted = 0
        updated = 0
        now = _now()

        for raw in news or []:
            enriched = estimate_impact(raw)
            title = str(raw.get("title") or "").strip()
            if not title:
                continue
            summary = str(raw.get("summary") or "").strip() or None
            url = str(raw.get("url") or "").strip() or None
            source = str(raw.get("source") or "").strip() or None
            published_at = raw.get("published_at")
            raw_payload = raw.get("raw") if isinstance(raw.get("raw"), dict | list) else raw

            existing = self._find_existing(connection, asset_id, url, title, published_at)
            sentiment_score = float(enriched["sentiment_score"])
            sentiment_label = enriched["sentiment_label"]
            impact_level = enriched["impact_level"]
            relevance_score = float(enriched["relevance_score"])
            raw_json = json.dumps(raw_payload)[:8000]

            if existing is None:
                connection.execute(
                    """
                    INSERT INTO news_items (
                        asset_id, symbol, provider, title, summary, url, source, published_at,
                        sentiment_score, sentiment_label, impact_level, relevance_score, raw_json,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        symbol_upper,
                        provider_name,
                        title,
                        summary,
                        url,
                        source,
                        published_at,
                        sentiment_score,
                        sentiment_label,
                        impact_level,
                        relevance_score,
                        raw_json,
                        now,
                        now,
                    ),
                )
                inserted += 1
            else:
                connection.execute(
                    """
                    UPDATE news_items
                    SET symbol = ?, provider = ?, summary = ?, source = ?, published_at = ?,
                        sentiment_score = ?, sentiment_label = ?, impact_level = ?, relevance_score = ?,
                        raw_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        symbol_upper,
                        provider_name,
                        summary,
                        source,
                        published_at,
                        sentiment_score,
                        sentiment_label,
                        impact_level,
                        relevance_score,
                        raw_json,
                        now,
                        existing["id"],
                    ),
                )
                updated += 1
        return inserted, updated

    def get_news_for_symbol(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT id, asset_id, symbol, provider, title, summary, url, source, published_at,
                   sentiment_score, sentiment_label, impact_level, relevance_score, created_at
            FROM news_items
            WHERE UPPER(COALESCE(symbol, '')) = UPPER(?)
            ORDER BY COALESCE(published_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            (symbol, max(1, min(limit, 200))),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_market_news(
        self,
        connection: sqlite3.Connection,
        limit: int = 50,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        if symbol:
            return self.get_news_for_symbol(connection, symbol, limit=limit)
        rows = connection.execute(
            """
            SELECT id, asset_id, symbol, provider, title, summary, url, source, published_at,
                   sentiment_score, sentiment_label, impact_level, relevance_score, created_at
            FROM news_items
            ORDER BY COALESCE(published_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_news_sentiment_summary(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        lookback_days: int = 7,
    ) -> dict[str, Any]:
        return aggregate_news_sentiment(connection, symbol, lookback_days=lookback_days)

    def get_status(self, connection: sqlite3.Connection) -> dict[str, Any]:
        settings = self.settings()
        real_provider = self.real_provider(connection)
        usage = self._usage_today(connection, real_provider.provider_name)
        cache_stats = self._cache_stats(connection)
        last_refresh = connection.execute(
            "SELECT MAX(COALESCE(updated_at, created_at)) AS last_refresh FROM news_items"
        ).fetchone()
        return {
            "enable_real_news": settings.enable_real_news,
            "provider_status": [
                {
                    "provider": real_provider.provider_name,
                    "enabled": settings.enable_real_news,
                    "api_key_configured": real_provider.api_key_configured(),
                    "daily_limit": real_provider.daily_limit,
                    "calls_today": usage,
                    "supports": ["stock", "etf", "bond_etf"],
                },
                {
                    "provider": "mock_news",
                    "enabled": True,
                    "api_key_configured": True,
                    "daily_limit": 0,
                    "calls_today": 0,
                    "supports": ["stock", "etf", "crypto", "bond", "bond_etf", "macro"],
                },
            ],
            "daily_usage": {
                "provider": real_provider.provider_name,
                "usage_date": date.today().isoformat(),
                "calls_count": usage,
                "daily_limit": real_provider.daily_limit,
            },
            "cache_status": cache_stats,
            "last_refresh": last_refresh["last_refresh"] if last_refresh else None,
            "news_sentiment_weight": settings.news_sentiment_weight,
            "news_cache_ttl_hours": settings.news_cache_ttl_hours,
        }

    def compute_news_score(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        lookback_days: int = 7,
    ) -> dict[str, Any]:
        """Compute optional news_score (-NEWS_SENTIMENT_WEIGHT .. +NEWS_SENTIMENT_WEIGHT)."""
        settings = self.settings()
        weight = max(0, int(settings.news_sentiment_weight))
        summary = aggregate_news_sentiment(connection, symbol, lookback_days=lookback_days)
        if summary["news_count"] == 0 or weight == 0:
            return {
                "news_score": 0.0,
                "news_sentiment_label": "NEUTRAL",
                "news_impact_level": "LOW",
                "news_count": summary["news_count"],
                "average_sentiment_score": summary["average_sentiment_score"],
                "lookback_days": lookback_days,
            }
        average = float(summary["average_sentiment_score"])
        impact_multiplier = {"HIGH": 1.0, "MEDIUM": 0.7, "LOW": 0.4}.get(summary["impact_level"], 0.5)
        news_score = max(-weight, min(weight, average * weight * impact_multiplier))
        return {
            "news_score": round(news_score, 2),
            "news_sentiment_label": summary["sentiment_label"],
            "news_impact_level": summary["impact_level"],
            "news_count": summary["news_count"],
            "average_sentiment_score": summary["average_sentiment_score"],
            "lookback_days": lookback_days,
        }

    # -- helpers -----------------------------------------------------------
    def _asset(self, connection: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT id, symbol, asset_type
            FROM assets
            WHERE UPPER(symbol) = UPPER(?)
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

    def _save_provider_news(
        self,
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        provider: BaseNewsProvider,
        force: bool = False,
    ) -> tuple[int, int]:
        try:
            news, _ = provider.get_news_for_symbol(asset["symbol"], force=force)
        except Exception:
            return 0, 0
        return self.save_news_to_db(connection, asset, news, provider.provider_name)

    def _find_existing(
        self,
        connection: sqlite3.Connection,
        asset_id: int,
        url: str | None,
        title: str,
        published_at: Any,
    ) -> sqlite3.Row | None:
        if url:
            row = connection.execute(
                "SELECT id FROM news_items WHERE url = ? LIMIT 1",
                (url,),
            ).fetchone()
            if row:
                return row
        return connection.execute(
            """
            SELECT id
            FROM news_items
            WHERE asset_id = ?
              AND title = ?
              AND COALESCE(published_at, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (asset_id, title, published_at),
        ).fetchone()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "asset_id": row["asset_id"],
            "symbol": row["symbol"],
            "provider": row["provider"],
            "title": row["title"],
            "summary": row["summary"],
            "url": row["url"],
            "source": row["source"],
            "published_at": row["published_at"],
            "sentiment_score": float(row["sentiment_score"] or 0.0),
            "sentiment_label": row["sentiment_label"] or "NEUTRAL",
            "impact_level": row["impact_level"] or "LOW",
            "relevance_score": float(row["relevance_score"] or 0.0),
            "created_at": row["created_at"],
        }

    def _refresh_result(
        self,
        symbol: str,
        provider: str | None,
        inserted: int,
        updated: int,
        used_cache: bool,
        used_fallback: bool,
        message: str,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "provider": provider,
            "rows_inserted": inserted,
            "rows_updated": updated,
            "used_cache": used_cache,
            "used_fallback": used_fallback,
            "message": message,
        }

    def _usage_today(self, connection: sqlite3.Connection, provider_name: str) -> int:
        today = date.today().isoformat()
        row = connection.execute(
            "SELECT calls_count FROM api_usage WHERE provider = ? AND usage_date = ?",
            (provider_name, today),
        ).fetchone()
        return int(row["calls_count"]) if row else 0

    def _cache_stats(self, connection: sqlite3.Connection) -> dict[str, int]:
        rows = connection.execute(
            "SELECT expires_at FROM api_cache WHERE provider IN (?, ?)",
            ("alpha_vantage_news", "mock_news"),
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
            except (ValueError, TypeError):
                expired += 1
        return {"entries": len(rows), "valid": valid, "expired": expired}

    # -- backwards compatibility ------------------------------------------
    def latest(self, symbol: str | None = None) -> list[dict[str, object]]:
        return []
