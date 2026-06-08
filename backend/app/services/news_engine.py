from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from backend.app.config import get_settings
from backend.app.data_providers import MissingApiKey, ProviderError, RateLimitExceeded, RealDataDisabled
from backend.app.data_providers.alpha_vantage_news import AlphaVantageNewsProvider
from backend.app.data_providers.finnhub_news import FinnhubNewsProvider
from backend.app.data_providers.mock_news_provider import NewsProviderMock
from backend.app.data_providers.news_base import BaseNewsProvider
from backend.app.services.common import (
    clamp as _clamp,
)
from backend.app.services.common import (
    now_utc as _now,
)
from backend.app.services.common import (
    signal_from_score as _signal_from_score,
)
from backend.app.services.sentiment_engine import aggregate_news_sentiment, classify_sentiment, estimate_impact


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=True)
    except TypeError:
        return json.dumps({"raw": str(value)}, ensure_ascii=True)


def _parse_json(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _news_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "provider": row["provider"],
        "title": row["title"],
        "summary": row["summary"],
        "url": row["url"],
        "source": row["source"],
        "published_at": row["published_at"],
        "sentiment_score": row["sentiment_score"],
        "sentiment_label": row["sentiment_label"],
        "impact_level": row["impact_level"],
        "relevance_score": row["relevance_score"],
        "raw_json": _parse_json(row["raw_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@dataclass
class NewsEngine:
    """Provider-backed news engine with local fallback and light scoring impact."""

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

    def _real_provider(self, connection: sqlite3.Connection) -> BaseNewsProvider | None:
        # Preferenza: Finnhub (quota dedicata, non intacca Alpha Vantage), poi Alpha Vantage.
        settings = get_settings()
        if settings.finnhub_api_key:
            return FinnhubNewsProvider(settings, connection)
        if settings.alpha_vantage_api_key:
            return AlphaVantageNewsProvider(settings, connection)
        return None

    def _mock_provider(self, connection: sqlite3.Connection) -> NewsProviderMock:
        return NewsProviderMock(get_settings(), connection)

    def _has_real_news_key(self) -> bool:
        settings = get_settings()
        return bool(settings.finnhub_api_key or settings.alpha_vantage_api_key)

    def _provider_for_refresh(self, connection: sqlite3.Connection) -> BaseNewsProvider:
        settings = get_settings()
        if settings.enable_real_news:
            provider = self._real_provider(connection)
            if provider is not None:
                return provider
        return self._mock_provider(connection)

    def refresh_news_for_symbol(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        force: bool = False,
    ) -> dict[str, Any]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")

        settings = get_settings()
        provider = self._provider_for_refresh(connection)
        used_fallback = provider.provider_name == "mock_news"
        message = "News demo/locali aggiornate."

        if settings.enable_real_news and not self._has_real_news_key():
            message = "Provider news non configurato, uso news demo/locali."
        elif not settings.enable_real_news:
            message = "News reali disattivate. Stai usando news demo/locali."

        try:
            news, used_cache = provider.get_news_for_symbol(asset["symbol"], force=force)
        except RateLimitExceeded as exc:
            provider = self._mock_provider(connection)
            news, used_cache = provider.get_news_for_symbol(asset["symbol"], force=False)
            used_fallback = True
            message = str(exc)
        except MissingApiKey:
            provider = self._mock_provider(connection)
            news, used_cache = provider.get_news_for_symbol(asset["symbol"], force=False)
            used_fallback = True
            message = "Provider news non configurato, uso news demo/locali."
        except RealDataDisabled as exc:
            provider = self._mock_provider(connection)
            news, used_cache = provider.get_news_for_symbol(asset["symbol"], force=False)
            used_fallback = True
            message = str(exc)
        except ProviderError as exc:
            provider = self._mock_provider(connection)
            news, used_cache = provider.get_news_for_symbol(asset["symbol"], force=False)
            used_fallback = True
            message = f"{exc} Uso news locali."
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError):
            provider = self._mock_provider(connection)
            news, used_cache = provider.get_news_for_symbol(asset["symbol"], force=False)
            used_fallback = True
            message = "Provider news non disponibile, uso news locali."

        inserted, updated = self.save_news_to_db(connection, asset["symbol"], news)
        self._update_signal_news_score(connection, asset["id"], asset["symbol"])
        if not used_fallback:
            message = "News aggiornate da cache." if used_cache else "News aggiornate da provider reale."

        return {
            "symbol": asset["symbol"],
            "provider": provider.provider_name,
            "items_inserted": inserted,
            "items_updated": updated,
            "used_cache": used_cache,
            "used_fallback": used_fallback,
            "message": message,
        }

    def refresh_all_news(
        self,
        connection: sqlite3.Connection,
        limit: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        rows = connection.execute(
            "SELECT symbol FROM assets ORDER BY asset_type, symbol"
        ).fetchall()
        selected = rows[:limit] if limit else rows
        symbols = [row["symbol"] for row in selected]
        results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                results.append(self.refresh_news_for_symbol(connection, symbol, force=force))
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol,
                        "provider": None,
                        "items_inserted": 0,
                        "items_updated": 0,
                        "used_cache": False,
                        "used_fallback": True,
                        "message": f"Errore: {exc}",
                    }
                )
        return {
            "summary": {
                "requested": len(symbols),
                "updated": sum(1 for item in results if not item["used_fallback"]),
                "fallback": sum(1 for item in results if item["used_fallback"]),
                "items_inserted": sum(int(item["items_inserted"]) for item in results),
                "items_updated": sum(int(item["items_updated"]) for item in results),
            },
            "results": results,
        }

    def get_news_for_symbol(self, connection: sqlite3.Connection, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")
        return self.get_market_news(connection, limit=limit, symbol=asset["symbol"])

    def get_market_news(
        self,
        connection: sqlite3.Connection,
        limit: int = 50,
        symbol: str | None = None,
        impact_level: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("UPPER(symbol) = UPPER(?)")
            params.append(symbol)
        if impact_level:
            clauses.append("impact_level = ?")
            params.append(impact_level.upper())
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            f"""
            SELECT id, symbol, provider, title, summary, url, source, published_at,
                sentiment_score, sentiment_label, impact_level, relevance_score, raw_json, created_at, updated_at
            FROM news_items
            {where_sql}
            ORDER BY published_at DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [_news_from_row(row) for row in rows]

    def get_news_sentiment_summary(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        lookback_days: int = 7,
    ) -> dict[str, Any]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")
        summary = aggregate_news_sentiment(connection, asset["symbol"], lookback_days)
        summary["latest_news"] = [_news_from_row_like(item) for item in summary["latest_news"]]
        return summary

    def get_market_sentiment_summary(self, connection: sqlite3.Connection, lookback_days: int = 7) -> dict[str, Any]:
        cutoff = (datetime.now(UTC).replace(tzinfo=None)).date().isoformat()
        rows = connection.execute(
            """
            SELECT sentiment_score, sentiment_label, impact_level
            FROM news_items
            WHERE published_at IS NULL OR published_at >= date(?, ?)
            """,
            (cutoff, f"-{lookback_days} days"),
        ).fetchall()
        scores = [float(row["sentiment_score"] or 0) for row in rows]
        average = round(sum(scores) / len(scores), 4) if scores else 0.0
        impact_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        impact_level = "LOW"
        for row in rows:
            candidate = row["impact_level"] or "LOW"
            if impact_rank.get(candidate, 1) > impact_rank[impact_level]:
                impact_level = candidate
        return {
            "lookback_days": lookback_days,
            "news_count": len(rows),
            "average_sentiment_score": average,
            "sentiment_label": "POSITIVE" if average >= 0.15 else "NEGATIVE" if average <= -0.15 else "NEUTRAL",
            "impact_level": impact_level,
            "positive_count": sum(1 for row in rows if row["sentiment_label"] == "POSITIVE"),
            "negative_count": sum(1 for row in rows if row["sentiment_label"] == "NEGATIVE"),
            "neutral_count": sum(1 for row in rows if row["sentiment_label"] == "NEUTRAL"),
        }

    def save_news_to_db(self, connection: sqlite3.Connection, symbol: str, news: list[dict[str, Any]]) -> tuple[int, int]:
        asset = self._asset(connection, symbol)
        if asset is None:
            raise ValueError(f"Asset {symbol.upper()} non trovato.")

        inserted = 0
        updated = 0
        now = _now()
        for item in news:
            normalized = self._normalize_for_db(asset["symbol"], item)
            existing = self._existing_news(connection, asset["symbol"], normalized)
            params = (
                asset["id"],
                asset["symbol"],
                normalized["provider"],
                normalized["title"],
                normalized["summary"],
                normalized["url"],
                normalized["source"],
                normalized["published_at"],
                normalized["sentiment_score"],
                normalized["sentiment_label"],
                normalized["impact_level"],
                normalized["relevance_score"],
                normalized["raw_json"],
                now,
            )
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
                    (*params, now),
                )
                inserted += 1
                continue

            connection.execute(
                """
                UPDATE news_items
                SET asset_id = ?, symbol = ?, provider = ?, title = ?, summary = ?, url = ?,
                    source = ?, published_at = ?, sentiment_score = ?, sentiment_label = ?,
                    impact_level = ?, relevance_score = ?, raw_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (*params, existing["id"]),
            )
            updated += 1
        return inserted, updated

    def get_status(self, connection: sqlite3.Connection) -> dict[str, Any]:
        settings = get_settings()
        real_provider = self._real_provider(connection) or AlphaVantageNewsProvider(settings, connection)
        mock_provider = self._mock_provider(connection)
        usage = self._usage_for_provider(connection, real_provider.provider_name)
        latest = connection.execute(
            """
            SELECT MAX(COALESCE(updated_at, created_at)) AS last_refresh
            FROM news_items
            """
        ).fetchone()
        return {
            "enable_real_news": settings.enable_real_news,
            "provider_status": [
                {
                    "provider": real_provider.provider_name,
                    "enabled": settings.enable_real_news,
                    "api_key_configured": real_provider.api_key_configured(),
                    "daily_limit": real_provider.daily_limit,
                    "calls_today": usage["calls_count"],
                    "supports": ["stock", "etf", "bond_etf"],
                },
                {
                    "provider": mock_provider.provider_name,
                    "enabled": True,
                    "api_key_configured": True,
                    "daily_limit": 0,
                    "calls_today": 0,
                    "supports": ["stock", "etf", "crypto", "bond", "bond_etf"],
                },
            ],
            "daily_usage": usage,
            "cache_status": self._cache_stats(connection),
            "last_refresh": latest["last_refresh"] if latest else None,
        }

    def latest(self, symbol: str | None = None) -> list[dict[str, Any]]:
        from backend.app.database import db_session

        with db_session() as connection:
            return self.get_market_news(connection, symbol=symbol)

    def _normalize_for_db(self, symbol: str, item: dict[str, Any]) -> dict[str, Any]:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        score = item.get("sentiment_score")
        label = item.get("sentiment_label")
        if score is None or label not in {"POSITIVE", "NEGATIVE", "NEUTRAL"}:
            sentiment = classify_sentiment(f"{title} {summary}")
            score = sentiment["sentiment_score"]
            label = sentiment["sentiment_label"]

        relevance = float(item.get("relevance_score") or 50)
        normalized = {
            "symbol": symbol.upper(),
            "provider": str(item.get("provider") or "local"),
            "title": title,
            "summary": summary,
            "url": item.get("url") or None,
            "source": str(item.get("source") or "N/D"),
            "published_at": item.get("published_at") or _now(),
            "sentiment_score": max(-1.0, min(1.0, float(score or 0))),
            "sentiment_label": str(label),
            "relevance_score": max(0.0, min(100.0, relevance)),
            "raw_json": _safe_json(item.get("raw_json", item)),
        }
        normalized["impact_level"] = str(item.get("impact_level") or estimate_impact(normalized))
        return normalized

    def _existing_news(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        item: dict[str, Any],
    ) -> sqlite3.Row | None:
        url = item.get("url")
        if url:
            row = connection.execute(
                """
                SELECT id
                FROM news_items
                WHERE UPPER(symbol) = UPPER(?) AND url = ?
                LIMIT 1
                """,
                (symbol, url),
            ).fetchone()
            if row is not None:
                return row
        return connection.execute(
            """
            SELECT id
            FROM news_items
            WHERE UPPER(symbol) = UPPER(?) AND title = ? AND COALESCE(published_at, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (symbol, item["title"], item.get("published_at")),
        ).fetchone()

    def _update_signal_news_score(self, connection: sqlite3.Connection, asset_id: int, symbol: str) -> None:
        latest_signal = connection.execute(
            """
            SELECT id, score, technical_score
            FROM signals
            WHERE asset_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if latest_signal is None:
            return

        settings = get_settings()
        summary = aggregate_news_sentiment(connection, symbol, lookback_days=7)
        technical_score = float(latest_signal["technical_score"] or latest_signal["score"] or 50)
        if summary["news_count"] == 0:
            news_score = 0.0
        else:
            news_score = float(summary["average_sentiment_score"]) * float(settings.news_sentiment_weight)
            news_score = max(-settings.news_sentiment_weight, min(settings.news_sentiment_weight, news_score))
        final_score = round(_clamp(technical_score + news_score), 2)
        now = _now()
        connection.execute(
            """
            UPDATE signals
            SET technical_score = ?,
                news_score = ?,
                final_score = ?,
                score = ?,
                signal = ?,
                news_sentiment_label = ?,
                news_impact_level = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                round(technical_score, 2),
                round(news_score, 2),
                final_score,
                final_score,
                _signal_from_score(final_score),
                summary["sentiment_label"],
                summary["impact_level"],
                now,
                latest_signal["id"],
            ),
        )

    def _usage_for_provider(self, connection: sqlite3.Connection, provider: str) -> dict[str, Any]:
        today = date.today().isoformat()
        row = connection.execute(
            """
            SELECT provider, usage_date, calls_count, daily_limit, updated_at
            FROM api_usage
            WHERE provider = ? AND usage_date = ?
            """,
            (provider, today),
        ).fetchone()
        if row is None:
            return {
                "provider": provider,
                "usage_date": today,
                "calls_count": 0,
                "daily_limit": get_settings().news_daily_limit,
                "updated_at": None,
            }
        return dict(row)

    def _cache_stats(self, connection: sqlite3.Connection) -> dict[str, int]:
        rows = connection.execute(
            """
            SELECT expires_at
            FROM api_cache
            WHERE provider LIKE '%news%'
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


def _news_from_row_like(item: dict[str, Any]) -> dict[str, Any]:
    raw_json = item.get("raw_json")
    return {
        "id": item.get("id"),
        "symbol": item.get("symbol"),
        "provider": item.get("provider"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "url": item.get("url"),
        "source": item.get("source"),
        "published_at": item.get("published_at"),
        "sentiment_score": item.get("sentiment_score"),
        "sentiment_label": item.get("sentiment_label"),
        "impact_level": item.get("impact_level"),
        "relevance_score": item.get("relevance_score"),
        "raw_json": _parse_json(raw_json) if isinstance(raw_json, str) else raw_json,
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }
