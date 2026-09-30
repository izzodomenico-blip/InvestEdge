from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.data_providers.base import BaseMarketDataProvider, ProviderError
from backend.app.models.market_data import MarketObservationEnvelope
from backend.app.services.provider_budget_service import ProviderAvailability

SYMBOL_TO_SERIES_ID = {
    "DGS10": "DGS10",
    "DGS2": "DGS2",
    "FEDFUNDS": "FEDFUNDS",
    "BTP10Y": "DGS10",
}

_SERIES_DESCRIPTIONS = {
    "DGS10": "Rendimento Treasury USA a 10 anni (FRED DGS10)",
    "DGS2": "Rendimento Treasury USA a 2 anni (FRED DGS2)",
    "FEDFUNDS": "Tasso effettivo Fed Funds USA (FRED FEDFUNDS)",
}

_REFERENCE_OPERATION = "fred_series_observations"


class FredReferenceProvider(BaseMarketDataProvider):
    """Serie macro/tassi FRED: solo riferimento, mai prezzo negoziabile.

    Fail-closed per policy: FRED v1 richiede la key nella query string (vietato) e
    FRED v2 espone soltanto download bulk per release (vietato dal refresh lazy).
    Nessuna chiamata di rete viene mai costruita. Il parser resta disponibile per
    righe gia locali (fixture o import manuale).
    """

    provider_name = "fred"
    endpoint = "series_observations"
    base_url = "https://api.stlouisfed.org"
    capability = "REFERENCE"
    allowed_series = frozenset({"DGS10", "DGS2", "FEDFUNDS"})
    legacy_aliases = {"BTP10Y": "DGS10"}
    alias_labels = {"BTP10Y": "REFERENCE_ONLY/US_10Y_PROXY"}
    # Codici stabili: v1 richiede la key in query string, v2 offre solo download bulk per release.
    capability_notes = ("REFERENCE_ONLY", "SECRET_IN_QUERY_POLICY", "BULK_ONLY_POLICY")
    attribution = "Fonte: FRED®, Federal Reserve Bank of St. Louis"
    series_rights = {
        "DGS10": "Board of Governors of the Federal Reserve System (US), release H.15; dominio pubblico, citazione richiesta",
        "DGS2": "Board of Governors of the Federal Reserve System (US), release H.15; dominio pubblico, citazione richiesta",
        "FEDFUNDS": "Board of Governors of the Federal Reserve System (US), release H.15; dominio pubblico, citazione richiesta",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.daily_limit = 0

    def api_key_configured(self) -> bool:
        return bool(self.settings.fred_api_key)

    def availability(self) -> ProviderAvailability:
        if not self.settings.fred_api_key:
            return ProviderAvailability("DISABLED", "MISSING_CREDENTIAL", None)
        return ProviderAvailability("DISABLED", "SECRET_IN_QUERY_POLICY", None)

    def supports_asset_type(self, asset_type: str) -> bool:
        return asset_type.lower() in {"macro", "bond_proxy"}

    def series_for(self, symbol: str) -> str:
        normalized = str(symbol or "").strip().upper()
        series_id = self.legacy_aliases.get(normalized, normalized)
        if series_id not in self.allowed_series:
            raise ProviderError("fred:REFERENCE:SERIES_NOT_ALLOWED")
        return series_id

    def series_metadata(self, symbol: str) -> dict[str, str]:
        normalized = str(symbol or "").strip().upper()
        series_id = self.series_for(normalized)
        label = self.alias_labels.get(normalized, "REFERENCE_ONLY")
        description = _SERIES_DESCRIPTIONS[series_id]
        if normalized in self.alias_labels:
            description = f"Proxy USA: {description}. Non e' un rendimento di titoli di Stato europei."
        return {
            "series_id": series_id,
            "label": label,
            "description": description,
            "attribution": self.attribution,
            "rights": self.series_rights[series_id],
        }

    def get_daily_prices(self, symbol: str, force: bool = False) -> tuple[list[dict[str, Any]], bool]:
        del force
        self.series_for(symbol)
        reason = self.availability().reason_code or "SECRET_IN_QUERY_POLICY"
        raise ProviderError(f"fred:REFERENCE:{reason}")

    def normalize_prices(self, raw_response: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
        """Parser legacy per righe locali: i valori mancanti (`.`) vengono saltati."""
        observations = raw_response.get("observations")
        if not isinstance(observations, list):
            return []

        prices: list[dict[str, Any]] = []
        for item in observations:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if value in (None, "."):
                continue
            try:
                close = float(value)
            except (TypeError, ValueError):
                continue
            prices.append(
                {
                    "date": str(item.get("date")),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adjusted_close": close,
                    "volume": 0.0,
                    "source": "real",
                    "provider": self.provider_name,
                }
            )
        return sorted(prices, key=lambda item: item["date"])

    def reference_envelopes(
        self,
        raw_response: Mapping[str, object],
        listing: Mapping[str, object] | sqlite3.Row,
        symbol: str,
        received_at: datetime,
    ) -> list[MarketObservationEnvelope]:
        """Righe FRED locali -> osservazioni REFERENCE (kind QUOTE, mai proiettate come prezzo)."""
        self.series_for(symbol)
        listing_id = int(listing["id"])
        timezone = str(listing["timezone"] or "").strip()
        currency = str(listing["currency"] or "").strip().upper()
        observations = raw_response.get("observations") if isinstance(raw_response, Mapping) else None
        if not isinstance(observations, list) or not observations:
            return [self._rejection(listing_id, received_at, "PROVIDER_NO_DATA", raw_response)]

        envelopes: list[MarketObservationEnvelope] = []
        for item in observations:
            if not isinstance(item, Mapping):
                envelopes.append(self._rejection(listing_id, received_at, "MALFORMED_PAYLOAD", item))
                continue
            value = str(item.get("value") or "").strip()
            if value in {"", "."}:
                envelopes.append(self._rejection(listing_id, received_at, "MISSING_VALUE", item))
                continue
            try:
                observed_date = date.fromisoformat(str(item.get("date") or "").strip())
                zone = ZoneInfo(timezone)
            except (ValueError, KeyError):
                envelopes.append(self._rejection(listing_id, received_at, "MALFORMED_PAYLOAD", item))
                continue
            observed_at = datetime.combine(observed_date, datetime.min.time(), tzinfo=zone).astimezone(UTC)
            envelopes.append(
                MarketObservationEnvelope(
                    listing_id=listing_id,
                    provider=self.provider_name,
                    capability="REFERENCE",
                    operation=_REFERENCE_OPERATION,
                    received_at=received_at,
                    provider_observed_at=observed_at,
                    timezone=timezone,
                    session="REFERENCE",
                    currency=currency,
                    source_quality="reference",
                    kind="QUOTE",
                    raw_fields={"last": value},
                    raw_payload_sha256=_payload_hash(item),
                )
            )
        return envelopes

    def _rejection(
        self,
        listing_id: int,
        received_at: datetime,
        reason_code: str,
        payload: object,
    ) -> MarketObservationEnvelope:
        return MarketObservationEnvelope(
            listing_id=listing_id,
            provider=self.provider_name,
            capability="REFERENCE",
            operation=_REFERENCE_OPERATION,
            received_at=received_at,
            provider_observed_at=None,
            timezone=None,
            session=None,
            currency=None,
            source_quality=None,
            kind=None,
            raw_fields={"reason_code": reason_code},
            raw_payload_sha256=_payload_hash(payload),
        )


# Alias di compatibilita: il nome storico resta importabile.
FredProvider = FredReferenceProvider


def _payload_hash(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
