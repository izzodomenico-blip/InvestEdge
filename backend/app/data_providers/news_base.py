from __future__ import annotations

import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from backend.app.config import Settings


def utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class NewsProviderError(RuntimeError):
    pass


class NewsRateLimitExceeded(NewsProviderError):
    pass


class NewsMissingApiKey(NewsProviderError):
    pass


class NewsRealDisabled(NewsProviderError):
    pass


class BaseNewsProvider(ABC):
    provider_name = "base_news"
    endpoint = "news"

    def __init__(self, settings: Settings, connection: sqlite3.Connection):
        self.settings = settings
        self.connection = connection

    @property
    def daily_limit(self) -> int:
        return self.settings.news_daily_limit

    @abstractmethod
    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        """Return list of normalized news items and whether cache was used."""

    @abstractmethod
    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        ...

    def supports_symbol(self, symbol: str) -> bool:
        return bool(symbol)

    def api_key_configured(self) -> bool:
        return True

    def ensure_enabled(self) -> None:
        if not self.settings.enable_real_news:
            raise NewsRealDisabled("News reali disattivate. Stai usando news demo/locali.")
        if not self.api_key_configured():
            raise NewsMissingApiKey("Provider news non configurato.")

    def check_rate_limit(self) -> None:
        today = date.today().isoformat()
        row = self.connection.execute(
            """
            SELECT calls_count, daily_limit
            FROM api_usage
            WHERE provider = ? AND usage_date = ?
            """,
            (self.provider_name, today),
        ).fetchone()
        calls_count = int(row["calls_count"]) if row else 0
        daily_limit = int(row["daily_limit"]) if row else self.daily_limit
        if daily_limit > 0 and calls_count >= daily_limit:
            raise NewsRateLimitExceeded("Limite news giornaliero raggiunto, uso news locali.")

    def increment_usage(self) -> None:
        today = date.today().isoformat()
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO api_usage (provider, usage_date, calls_count, daily_limit, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(provider, usage_date) DO UPDATE SET
                calls_count = calls_count + 1,
                daily_limit = excluded.daily_limit,
                updated_at = excluded.updated_at
            """,
            (self.provider_name, today, self.daily_limit, now, now),
        )

    def cache_key(self, symbol: str, request_url: str) -> str:
        request_hash = hashlib.sha256(request_url.encode("utf-8")).hexdigest()
        return f"{self.provider_name}:{self.endpoint}:{symbol.upper()}:{request_hash}"

    def request_hash(self, request_url: str) -> str:
        return hashlib.sha256(request_url.encode("utf-8")).hexdigest()

    def get_from_cache(self, symbol: str, request_url: str, force: bool = False) -> dict[str, Any] | None:
        if force:
            return None
        row = self.connection.execute(
            """
            SELECT response_json, payload, expires_at
            FROM api_cache
            WHERE cache_key = ?
            LIMIT 1
            """,
            (self.cache_key(symbol, request_url),),
        ).fetchone()
        if row is None or not row["expires_at"]:
            return None
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return None
        if expires_at <= datetime.now(UTC).replace(tzinfo=None):
            return None
        payload = row["response_json"] or row["payload"]
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def save_to_cache(
        self,
        symbol: str,
        request_url: str,
        response_json: dict[str, Any],
        status: str = "OK",
    ) -> None:
        now = utc_now()
        expires_at = (
            datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=self.settings.news_cache_ttl_hours)
        ).isoformat(timespec="seconds")
        payload = json.dumps(response_json)
        self.connection.execute(
            """
            INSERT INTO api_cache (
                cache_key, provider, endpoint, symbol, request_url_hash, response_json,
                payload, status, last_update, expires_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                response_json = excluded.response_json,
                payload = excluded.payload,
                status = excluded.status,
                last_update = excluded.last_update,
                expires_at = excluded.expires_at
            """,
            (
                self.cache_key(symbol, request_url),
                self.provider_name,
                self.endpoint,
                symbol.upper(),
                self.request_hash(request_url),
                payload,
                payload,
                status,
                now,
                expires_at,
                now,
            ),
        )

    def fetch_json(self, request_url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        self.ensure_enabled()
        self.check_rate_limit()
        with httpx.Client(timeout=20) as client:
            response = client.get(request_url, headers=headers)
            self.increment_usage()
            response.raise_for_status()
        return response.json()
