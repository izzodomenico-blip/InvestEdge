from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from backend.app.data_providers.base import ProviderError, RateLimitExceeded
from backend.app.data_providers.news_base import BaseNewsProvider
from backend.app.data_providers.transport import SafeProviderTransportError
from backend.app.services.provider_budget_service import (
    ProviderAvailability,
    ProviderBudgetExceeded,
    ProviderBudgetPolicy,
)
from backend.app.services.sentiment_engine import classify_sentiment

LOOKBACK_DAYS = 21
MAX_ARTICLES = 50
FINNHUB_NEWS_MINUTE_LIMIT = 55
_FUTURE_TOLERANCE = timedelta(minutes=5)


class FinnhubNewsProvider(BaseNewsProvider):
    """Unico provider news live ammesso: key solo nell'header `X-Finnhub-Token`."""

    provider_name = "finnhub_news"
    endpoint = "company-news"
    base_url = "https://finnhub.io"
    path = "/api/v1/company-news"

    def __init__(
        self,
        *args: Any,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._sleeper = sleeper
        self._clock = clock or (lambda: datetime.now(UTC))

    def api_key_configured(self) -> bool:
        return bool(self.settings.finnhub_api_key)

    def availability(self) -> ProviderAvailability:
        if not self.settings.enable_real_news:
            return ProviderAvailability("DISABLED", "OPT_IN_DISABLED", None)
        if not self.api_key_configured():
            return ProviderAvailability("DISABLED", "MISSING_CREDENTIAL", None)
        return self.budget_manager.availability(
            self.connection,
            self._budget_policy(),
            self.provider_name,
            self._clock(),
        )

    def _budget_policy(self) -> ProviderBudgetPolicy:
        monthly = self.settings.finnhub_news_monthly_limit
        return ProviderBudgetPolicy(
            minute_limit=min(self.settings.finnhub_news_minute_limit, FINNHUB_NEWS_MINUTE_LIMIT),
            daily_limit=self.daily_limit if self.daily_limit > 0 else None,
            monthly_limit=monthly if monthly > 0 else None,
            max_attempts=self.settings.provider_default_max_attempts,
        )

    def _request_params(self, symbol: str, now: datetime) -> dict[str, str]:
        today = now.astimezone(UTC).date()
        start = today - timedelta(days=LOOKBACK_DAYS)
        return {
            "symbol": symbol.strip().upper(),
            "from": start.isoformat(),
            "to": today.isoformat(),
        }

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        self.ensure_enabled()
        now = self._clock()
        try:
            response = self.transport.request(
                connection=self.connection,
                policy=self._budget_policy(),
                provider=self.provider_name,
                method="GET",
                base_url=self.base_url,
                path=self.path,
                headers={"X-Finnhub-Token": self.settings.finnhub_api_key or ""},
                params=self._request_params(symbol, now),
                json_body=None,
                operation=self.endpoint,
                cache_scope=self._cache_scope(self.endpoint, symbol),
                cache_ttl_seconds=self.settings.news_cache_ttl_hours * 3600,
                max_response_bytes=8 * 1024 * 1024,
                decoder="json",
                now=now,
                sleeper=self._sleeper,
                bypass_cache=force,
            )
        except ProviderBudgetExceeded:
            raise RateLimitExceeded(f"{self.provider_name}:{self.endpoint}:RATE_LIMITED") from None
        except SafeProviderTransportError as exc:
            if exc.code == "RATE_LIMITED":
                raise RateLimitExceeded(f"{self.provider_name}:{self.endpoint}:RATE_LIMITED") from None
            raise ProviderError(str(exc)) from None
        if not isinstance(response.payload, list):
            raise ProviderError(f"{self.provider_name}:{self.endpoint}:INVALID_PAYLOAD")
        wrapped = {"articles": response.payload[:MAX_ARTICLES]}
        return self.normalize_news(wrapped, symbol, now=now), response.from_cache

    def normalize_news(
        self,
        raw_response: dict[str, Any],
        symbol: str,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        articles = raw_response.get("articles")
        if not isinstance(articles, list):
            return []

        reference_now = (now or self._clock()).astimezone(UTC)
        normalized: list[dict[str, Any]] = []
        for item in articles[:MAX_ARTICLES]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("headline") or "").strip()
            if not title:
                continue
            published_at = self._published_at(item.get("datetime"), reference_now)
            if published_at is None:
                # Senza un orario valido la news sembrerebbe "di oggi": meglio scartarla.
                continue
            summary = str(item.get("summary") or "").strip()
            # Finnhub free non fornisce sentiment: lo stimiamo dal testo (euristica keyword).
            sentiment = classify_sentiment(f"{title} {summary}")
            normalized.append(
                {
                    "provider": self.provider_name,
                    "title": title,
                    "summary": summary,
                    "url": _public_url(item.get("url")),
                    "source": str(item.get("source") or "Finnhub").strip(),
                    "published_at": published_at,
                    "sentiment_score": float(sentiment["sentiment_score"]),
                    "sentiment_label": str(sentiment["sentiment_label"]),
                    "relevance_score": 75.0,  # news richiesta per ticker -> alta rilevanza
                    "raw_json": item,
                }
            )
        return normalized

    @staticmethod
    def _published_at(value: Any, now: datetime) -> str | None:
        if isinstance(value, bool):
            return None
        try:
            timestamp = float(value)
            published = datetime.fromtimestamp(timestamp, tz=UTC)
        except (TypeError, ValueError, OverflowError, OSError):
            return None
        if timestamp <= 0 or published > now + _FUTURE_TOLERANCE:
            return None
        return published.replace(tzinfo=None).isoformat(timespec="seconds")


def _public_url(value: Any) -> str | None:
    """Solo URL http(s) pubblici: niente schemi locali, credenziali, host locali o IP privati."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        return None
    if port not in {None, 80, 443}:
        return None
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return text
    if not address.is_global:
        return None
    return text
