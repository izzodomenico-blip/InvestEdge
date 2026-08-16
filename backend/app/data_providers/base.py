from __future__ import annotations

import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from backend.app.config import Settings
from backend.app.data_providers.transport import SafeProviderTransport, SafeProviderTransportError
from backend.app.services.provider_budget_service import (
    ProviderBudgetExceeded,
    ProviderBudgetManager,
    ProviderBudgetPolicy,
)


def utc_now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class ProviderError(RuntimeError):
    pass


class RateLimitExceeded(ProviderError):
    pass


class MissingApiKey(ProviderError):
    pass


class RealDataDisabled(ProviderError):
    pass


class BaseMarketDataProvider(ABC):
    provider_name = "base"
    daily_limit = 0

    def __init__(
        self,
        settings: Settings,
        connection: sqlite3.Connection,
        transport: SafeProviderTransport | None = None,
        budget_manager: ProviderBudgetManager | None = None,
    ):
        self.settings = settings
        self.connection = connection
        self.budget_manager = budget_manager or (
            transport.budget_manager if transport is not None else ProviderBudgetManager()
        )
        if transport is None:
            host = urlsplit(str(getattr(self, "base_url", ""))).hostname
            transport = SafeProviderTransport(
                allowed_hosts={host} if host else set(),
                budget_manager=self.budget_manager,
                settings=settings,
            )
        elif transport.budget_manager is not self.budget_manager:
            transport = transport.with_budget_manager(self.budget_manager)
        self.transport = transport
        self._request_context = threading.local()

    @abstractmethod
    def get_daily_prices(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        """Return normalized daily prices and whether cache was used."""

    @abstractmethod
    def normalize_prices(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def supports_asset_type(self, asset_type: str) -> bool:
        ...

    def api_key_configured(self) -> bool:
        return True

    def ensure_enabled(self) -> None:
        if not self.settings.enable_real_data:
            raise RealDataDisabled("Dati reali disattivati. Stai usando dati seed/demo.")
        if not self.api_key_configured():
            raise MissingApiKey("API key non configurata.")

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
            raise RateLimitExceeded("Limite giornaliero raggiunto, uso dati locali.")

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

    def cache_key(self, endpoint: str, symbol: str, request_url: str) -> str:
        return f"provider:{self.provider_name}:{self._cache_scope(endpoint, symbol)}:{self.request_hash(request_url)}"

    def request_hash(self, request_url: str) -> str:
        try:
            return self.transport.prepare_legacy_url(
                self.provider_name,
                str(getattr(self, "endpoint", "EOD")),
                "GET",
                request_url,
                None,
                enforce_allowlist=False,
            ).request_fingerprint
        except SafeProviderTransportError as exc:
            raise ProviderError(str(exc)) from None

    def get_from_cache(self, endpoint: str, symbol: str, request_url: str, force: bool = False) -> dict[str, Any] | None:
        self._request_context.pending = (endpoint, symbol, request_url, force)
        try:
            response = self.transport.cached_response_for_url(
                self.connection,
                provider=self.provider_name,
                operation=endpoint,
                cache_scope=self._cache_scope(endpoint, symbol),
                request_url=request_url,
                now=datetime.now(UTC),
                bypass_cache=force,
            )
        except SafeProviderTransportError as exc:
            raise ProviderError(str(exc)) from None
        if response is None:
            return None
        if not isinstance(response.payload, dict):
            raise ProviderError(f"{self.provider_name}:{endpoint}:INVALID_PAYLOAD")
        return response.payload

    def save_to_cache(
        self,
        endpoint: str,
        symbol: str,
        request_url: str,
        response_json: dict[str, Any],
        status: str = "OK",
    ) -> None:
        fingerprint = self.request_hash(request_url)
        if getattr(self._request_context, "last_fingerprint", None) == fingerprint:
            return
        try:
            self.transport.store_response_for_url(
                self.connection,
                provider=self.provider_name,
                operation=endpoint,
                cache_scope=self._cache_scope(endpoint, symbol),
                request_url=request_url,
                payload=response_json,
                status_code=200 if status == "OK" else 206,
                cache_ttl_seconds=self.settings.api_cache_ttl_hours * 3600,
                now=datetime.now(UTC),
            )
        except SafeProviderTransportError as exc:
            raise ProviderError(str(exc)) from None

    def fetch_json(self, request_url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        self.ensure_enabled()
        pending = getattr(self._request_context, "pending", None)
        if pending is not None and pending[2] == request_url:
            endpoint, symbol, _request_url, force = pending
        else:
            endpoint = str(getattr(self, "endpoint", "EOD"))
            symbol = "request"
            force = False
        try:
            response = self.transport.request_url(
                connection=self.connection,
                policy=self._budget_policy(),
                provider=self.provider_name,
                operation=endpoint,
                cache_scope=self._cache_scope(endpoint, symbol),
                request_url=request_url,
                headers=headers or {},
                cache_ttl_seconds=self.settings.api_cache_ttl_hours * 3600,
                max_response_bytes=16 * 1024 * 1024,
                decoder="json",
                now=datetime.now(UTC),
                sleeper=time.sleep,
                bypass_cache=bool(force),
            )
        except ProviderBudgetExceeded as exc:
            raise RateLimitExceeded(str(exc)) from None
        except SafeProviderTransportError as exc:
            raise ProviderError(str(exc)) from None
        finally:
            self._request_context.pending = None
        self._request_context.last_fingerprint = response.request_fingerprint
        if not isinstance(response.payload, dict):
            raise ProviderError(f"{self.provider_name}:{endpoint}:INVALID_PAYLOAD")
        return response.payload

    def _budget_policy(self) -> ProviderBudgetPolicy:
        return ProviderBudgetPolicy(
            minute_limit=None,
            daily_limit=self.daily_limit if self.daily_limit > 0 else None,
            monthly_limit=None,
            max_attempts=self.settings.provider_default_max_attempts,
        )

    @staticmethod
    def _cache_scope(endpoint: str, symbol: str) -> str:
        return f"{endpoint}:{symbol.upper()}"
