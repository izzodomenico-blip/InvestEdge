from __future__ import annotations

import math
import sqlite3
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Literal

import httpx

from backend.app.data_providers.base import ProviderError, RateLimitExceeded
from backend.app.data_providers.transport import (
    ProviderResponse,
    SafeProviderTransport,
    SafeProviderTransportError,
)
from backend.app.services.fx_service import FXQuote
from backend.app.services.provider_budget_service import (
    ProviderBudgetExceeded,
    ProviderBudgetPolicy,
)

ECB_DATA_API_BASE_URL = "https://data-api.ecb.europa.eu"
ECB_DAILY_BASE_URL = "https://www.ecb.europa.eu"
ECB_DAILY_PATH = "/stats/eurofxref/eurofxref-daily.xml"
ECB_DAILY_URL = f"{ECB_DAILY_BASE_URL}{ECB_DAILY_PATH}"
ECB_ALLOWED_HOSTS = frozenset({"data-api.ecb.europa.eu", "www.ecb.europa.eu"})
ECB_RESPONSE_LIMIT_BYTES = 1024 * 1024
ECB_MAX_CSV_ROWS = 10
ECB_MAX_REFERENCE_CURRENCIES = 64
ECB_CACHE_TTL_SECONDS = 6 * 3600

# Valute con cambio di riferimento BCE giornaliero (serie EXR D.<CUR>.EUR.SP00.A).
# BGN esclusa: la Bulgaria usa l'euro dal 2026-01-01; HRK e RUB non piu pubblicate.
ECB_REFERENCE_CURRENCIES = frozenset(
    {
        "AUD", "BRL", "CAD", "CHF", "CNY", "CZK", "DKK", "GBP", "HKD", "HUF",
        "IDR", "ILS", "INR", "ISK", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD",
        "PHP", "PLN", "RON", "SEK", "SGD", "THB", "TRY", "USD", "ZAR",
    }
)

FxRefreshStatus = Literal["UPDATED", "NOT_MODIFIED"]


@dataclass(frozen=True)
class EcbFetchResult:
    status: FxRefreshStatus
    quote: FXQuote | None


def normalize_ecb_currency(value: str) -> str:
    currency = str(value or "").strip().upper()
    if currency not in ECB_REFERENCE_CURRENCIES:
        raise ValueError("La valuta richiesta non e' tra le valute di riferimento BCE.")
    return currency


class EcbFxProvider:
    """Cambi di riferimento BCE governati dal trasporto sicuro condiviso.

    Scrive soltanto quote `currency -> EUR`: nessun instrument listing e nessuna
    observation di mercato. Il reference rate BCE e' giornaliero e informativo:
    la qualita e' sempre `reference`, mai `realtime`.
    """

    capability = "FX"
    provider_code = "ecb"
    policy = ProviderBudgetPolicy(minute_limit=5, daily_limit=50, monthly_limit=500)
    attribution = "Fonte: Banca centrale europea (ECB Data Portal)"

    def __init__(
        self,
        transport: SafeProviderTransport,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        cache_ttl_seconds: int = ECB_CACHE_TTL_SECONDS,
    ) -> None:
        self.transport = transport
        self._sleeper = sleeper
        self._cache_ttl_seconds = cache_ttl_seconds

    def with_client(self, client: httpx.Client) -> EcbFxProvider:
        return EcbFxProvider(
            self.transport.with_client(client),
            sleeper=self._sleeper,
            cache_ttl_seconds=self._cache_ttl_seconds,
        )

    def fetch_rate(
        self,
        connection: sqlite3.Connection,
        from_currency: str,
        to_currency: Literal["EUR"],
        since: date | None,
        now: datetime,
    ) -> EcbFetchResult:
        currency = normalize_ecb_currency(from_currency)
        if str(to_currency).strip().upper() != "EUR":
            raise ValueError("La valuta di destinazione BCE deve essere EUR.")
        headers: dict[str, str] = {}
        if since is not None:
            # I dati BCE di un giorno sono pubblicati in quel giorno: se nulla e'
            # cambiato dall'inizio del giorno successivo all'ultima osservazione, 304.
            modified_since = datetime.combine(since + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            headers["If-Modified-Since"] = format_datetime(modified_since, usegmt=True)
        try:
            response = self._request(
                connection,
                base_url=ECB_DATA_API_BASE_URL,
                path=f"/service/data/EXR/D.{currency}.EUR.SP00.A",
                params={"format": "csvdata", "lastNObservations": "2"},
                headers=headers,
                cache_scope=f"fx:{currency}:EUR",
                decoder="csv",
                now=now,
            )
        except _NotModified:
            return EcbFetchResult("NOT_MODIFIED", None)
        return EcbFetchResult("UPDATED", self._quote_from_csv(currency, response.payload, now))

    def fetch_reference_rates(self, connection: sqlite3.Connection, now: datetime) -> list[FXQuote]:
        try:
            response = self._request(
                connection,
                base_url=ECB_DAILY_BASE_URL,
                path=ECB_DAILY_PATH,
                params={},
                headers={},
                cache_scope="fx:eurofxref-daily",
                decoder="bytes",
                now=now,
            )
        except _NotModified:
            raise ProviderError("ecb:FX:NOT_MODIFIED_WITHOUT_BASELINE") from None
        payload = response.payload
        if not isinstance(payload, bytes | bytearray):
            raise ProviderError("ecb:FX:MALFORMED_PAYLOAD")
        return self._quotes_from_daily_xml(bytes(payload), now)

    def _request(
        self,
        connection: sqlite3.Connection,
        *,
        base_url: str,
        path: str,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        cache_scope: str,
        decoder: Literal["csv", "bytes"],
        now: datetime,
    ) -> ProviderResponse:
        try:
            return self.transport.request(
                connection=connection,
                policy=self.policy,
                provider=self.provider_code,
                method="GET",
                base_url=base_url,
                path=path,
                headers=headers,
                params=params,
                json_body=None,
                operation=self.capability,
                cache_scope=cache_scope,
                cache_ttl_seconds=self._cache_ttl_seconds,
                max_response_bytes=ECB_RESPONSE_LIMIT_BYTES,
                decoder=decoder,
                now=now,
                sleeper=self._sleeper,
            )
        except ProviderBudgetExceeded:
            raise RateLimitExceeded("ecb:FX:RATE_LIMITED") from None
        except SafeProviderTransportError as exc:
            if exc.code == "NOT_MODIFIED":
                raise _NotModified() from None
            if exc.code == "RATE_LIMITED":
                raise RateLimitExceeded("ecb:FX:RATE_LIMITED") from None
            raise ProviderError(f"ecb:FX:{exc.code}") from None

    @staticmethod
    def _quote_from_csv(currency: str, payload: object, now: datetime) -> FXQuote:
        if not isinstance(payload, list) or len(payload) > ECB_MAX_CSV_ROWS:
            raise ProviderError("ecb:FX:MALFORMED_PAYLOAD")
        observations: list[tuple[str, str]] = []
        for row in payload:
            if not isinstance(row, Mapping):
                raise ProviderError("ecb:FX:MALFORMED_PAYLOAD")
            if (
                str(row.get("FREQ") or "").strip() != "D"
                or str(row.get("CURRENCY") or "").strip().upper() != currency
                or str(row.get("CURRENCY_DENOM") or "").strip().upper() != "EUR"
            ):
                continue
            try:
                observed = date.fromisoformat(str(row.get("TIME_PERIOD") or "").strip())
            except ValueError:
                raise ProviderError("ecb:FX:MALFORMED_PAYLOAD") from None
            _reject_future(observed, now)
            observations.append((observed.isoformat(), str(row.get("OBS_VALUE") or "").strip()))
        if not observations:
            raise ProviderError("ecb:FX:PROVIDER_NO_DATA")
        observed_at, raw_value = max(observations)
        ecb_rate = _parse_rate(raw_value)
        return FXQuote(currency, "EUR", 1.0 / ecb_rate, observed_at, "ecb", "reference")

    @staticmethod
    def _quotes_from_daily_xml(payload: bytes, now: datetime) -> list[FXQuote]:
        uppercase_payload = payload.upper()
        if b"<!DOCTYPE" in uppercase_payload or b"<!ENTITY" in uppercase_payload:
            raise ProviderError("ecb:FX:XML_ENTITIES_NOT_ALLOWED")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            raise ProviderError("ecb:FX:MALFORMED_PAYLOAD") from None

        quotes: list[FXQuote] = []
        for element in root.iter():
            observed_at = element.attrib.get("time")
            if not observed_at:
                continue
            try:
                observed_day = date.fromisoformat(observed_at.strip())
            except ValueError:
                raise ProviderError("ecb:FX:MALFORMED_PAYLOAD") from None
            _reject_future(observed_day, now)
            observed = observed_day.isoformat()
            for rate_element in element:
                currency = rate_element.attrib.get("currency", "").strip().upper()
                raw_rate = rate_element.attrib.get("rate")
                if len(currency) != 3 or not currency.isalpha() or raw_rate is None:
                    continue
                quotes.append(
                    FXQuote(currency, "EUR", 1.0 / _parse_rate(raw_rate), observed, "ecb", "reference")
                )
                if len(quotes) > ECB_MAX_REFERENCE_CURRENCIES:
                    raise ProviderError("ecb:FX:TOO_MANY_CURRENCIES")
        if not quotes:
            raise ProviderError("ecb:FX:PROVIDER_NO_DATA")
        return quotes


class _NotModified(Exception):
    pass


def _reject_future(observed: date, now: datetime) -> None:
    # Un cambio datato dopo il giorno UTC corrente diventerebbe il piu recente e mai stale.
    if observed > now.astimezone(UTC).date():
        raise ProviderError("ecb:FX:FUTURE_TIMESTAMP")


def _parse_rate(raw_value: str) -> float:
    if not raw_value or raw_value.strip().upper() in {"NAN", "NA", "."}:
        raise ProviderError("ecb:FX:MISSING_VALUE")
    try:
        value = float(raw_value)
    except ValueError:
        raise ProviderError("ecb:FX:MALFORMED_PAYLOAD") from None
    if math.isnan(value):
        raise ProviderError("ecb:FX:MISSING_VALUE")
    if not math.isfinite(value) or value <= 0:
        raise ProviderError("ecb:FX:INVALID_RATE")
    return value
