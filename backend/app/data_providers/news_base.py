from __future__ import annotations

import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from backend.app.config import Settings
from backend.app.data_providers.base import MissingApiKey, ProviderError, RateLimitExceeded, RealDataDisabled


def utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class BaseNewsProvider(ABC):
    provider_name = "base_news"
    endpoint = "news"

    def __init__(self, settings: Settings, connection: sqlite3.Connection):
        self.settings = settings
        self.connection = connection
        self.daily_limit = settings.news_daily_limit

    @abstractmethod
    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        """Return normalized news and whether cache was used."""

    @abstractmethod
    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        ...

    def supports_symbol(self, symbol: str) -> bool:
        return bool(symbol.strip())

    def api_key_configured(self) -> bool:
        return True

    def ensure_enabled(self) -> None:
        if not self.settings.enable_real_news:
            raise RealDataDisabled("News reali disattivate. Stai usando news demo/locali.")
        if not self.api_key_configured():
            raise MissingApiKey("Provider news non configurato.")

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
            raise RateLimitExceeded("Limite news giornaliero raggiunto, uso news locali.")

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

    def request_hash(self, request_url: str) -> str:
        return hashlib.sha256(request_url.encode("utf-8")).hexdigest()

    def cache_key(self, endpoint: str, symbol: str, request_url: str) -> str:
        return f"{self.provider_name}:{endpoint}:{symbol.upper()}:{self.request_hash(request_url)}"

    def get_from_cache(self, endpoint: str, symbol: str, request_url: str, force: bool = False) -> dict[str, Any] | None:
        if force:
            return None
        row = self.connection.execute(
            """
            SELECT response_json, payload, expires_at
            FROM api_cache
            WHERE cache_key = ?
            LIMIT 1
            """,
            (self.cache_key(endpoint, symbol, request_url),),
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
        return json.loads(payload)

    def save_to_cache(
        self,
        endpoint: str,
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
                self.cache_key(endpoint, symbol, request_url),
                self.provider_name,
                endpoint,
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
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError("Risposta news non valida.")
        return payload
