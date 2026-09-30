from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.data_providers.base import ProviderError
from backend.app.data_providers.news_base import BaseNewsProvider
from backend.app.services.provider_budget_service import ProviderAvailability
from backend.app.services.sentiment_engine import classify_sentiment


class YahooNewsProvider(BaseNewsProvider):
    """Yahoo Finance news: disabilitato come provider live (`NOT_PRIMARY_POLICY`).

    Yahoo non offre una API pubblica supportata per la raccolta automatizzata: nessuna
    richiesta di rete e nessun User-Agent da browser. Resta soltanto il parser, per
    compatibilita con payload gia locali.
    """

    provider_name = "yahoo_news"
    endpoint = "search-news"
    base_url = "https://query1.finance.yahoo.com/v1/finance/search"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # 0 = nessun limite giornaliero (Yahoo non pubblica quote).
        self.daily_limit = self.settings.yahoo_news_daily_limit

    def api_key_configured(self) -> bool:
        # Yahoo Finance non richiede API key.
        return True

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability("DISABLED", "NOT_PRIMARY_POLICY", None)

    def _asset_type(self, symbol: str) -> str:
        row = self.connection.execute(
            "SELECT asset_type FROM assets WHERE UPPER(symbol) = UPPER(?) LIMIT 1",
            (symbol,),
        ).fetchone()
        return str(row["asset_type"]).lower() if row else "stock"

    def get_news_for_symbol(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        del symbol, force
        raise ProviderError(f"{self.provider_name}:{self.endpoint}:NOT_PRIMARY_POLICY")

    def normalize_news(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        items = raw_response.get("news")
        if not isinstance(items, list):
            return []

        # ETF/crypto: news generiche -> rilevanza piu' bassa per non sovrastare il segnale tecnico.
        is_specific = self._asset_type(symbol) == "stock"
        relevance = 72.0 if is_specific else 45.0

        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            summary = str(item.get("summary") or "").strip()
            sentiment = classify_sentiment(f"{title} {summary}")
            normalized.append(
                {
                    "provider": self.provider_name,
                    "title": title,
                    "summary": summary,
                    "url": str(item.get("link") or "").strip() or None,
                    "source": str(item.get("publisher") or "Yahoo Finance").strip(),
                    "published_at": self._published_at(item.get("providerPublishTime")),
                    "sentiment_score": float(sentiment["sentiment_score"]),
                    "sentiment_label": str(sentiment["sentiment_label"]),
                    "relevance_score": relevance,
                    "raw_json": item,
                }
            )
        return normalized

    def _published_at(self, value: Any) -> str | None:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=UTC).replace(tzinfo=None).isoformat(timespec="seconds")
