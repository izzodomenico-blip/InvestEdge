from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import httpx

from backend.app.config import get_settings

if TYPE_CHECKING:
    from backend.app.data_providers.ecb import EcbFxProvider
    from backend.app.models import FxRefreshResult

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class FXRateUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class FXQuote:
    from_currency: str
    to_currency: str
    rate: float
    observed_at: str
    provider: str
    quality: str


@dataclass(frozen=True)
class FxBackfillResult:
    currency: str
    inserted: int
    existing: int
    first_observed_at: str | None
    last_observed_at: str | None


class FXService:
    def __init__(self, ecb_provider: EcbFxProvider | None = None) -> None:
        self._ecb_provider = ecb_provider

    def get_rate(
        self,
        connection: sqlite3.Connection,
        from_currency: str,
        to_currency: str = "EUR",
    ) -> FXQuote:
        normalized_from = from_currency.strip().upper()
        normalized_to = to_currency.strip().upper()
        if not normalized_from or not normalized_to:
            raise FXRateUnavailable("La coppia valutaria richiesta non e' valida.")
        if normalized_from == normalized_to:
            return FXQuote(
                from_currency=normalized_from,
                to_currency=normalized_to,
                rate=1.0,
                observed_at=datetime.now(UTC).isoformat(timespec="seconds"),
                provider="identity",
                quality="reference",
            )

        row = self._latest_rate(connection, normalized_from, normalized_to)
        inverse = False
        if row is None:
            row = self._latest_rate(connection, normalized_to, normalized_from)
            inverse = True
        if row is None:
            raise FXRateUnavailable(
                f"Cambio {normalized_from}/{normalized_to} non disponibile."
            )

        rate = float(row[0])
        observed_at = str(row[1])
        quality = str(row[3])
        if inverse:
            rate = 1.0 / rate
        if self._is_stale(observed_at):
            quality = "stale"
        return FXQuote(
            from_currency=normalized_from,
            to_currency=normalized_to,
            rate=rate,
            observed_at=observed_at,
            provider=str(row[2]),
            quality=quality,
        )

    def refresh_currency(
        self,
        connection: sqlite3.Connection,
        from_currency: str,
        now: datetime | None = None,
    ) -> FxRefreshResult:
        """Aggiorna una sola valuta verso EUR dal reference rate ufficiale BCE."""
        from backend.app.data_providers.base import ProviderError
        from backend.app.data_providers.ecb import normalize_ecb_currency
        from backend.app.models import FxRefreshResult

        currency = normalize_ecb_currency(from_currency)
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        previous = connection.execute(
            """
            SELECT observed_at, ingested_at
            FROM fx_rates
            WHERE from_currency = ? AND to_currency = 'EUR' AND provider = 'ecb'
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (currency,),
        ).fetchone()
        since = _date_or_none(previous["observed_at"]) if previous is not None else None

        result = self._ecb(connection).fetch_rate(connection, currency, "EUR", since, moment)
        if result.status == "NOT_MODIFIED" or result.quote is None:
            if previous is None:
                raise ProviderError("ecb:FX:NOT_MODIFIED_WITHOUT_BASELINE")
            return FxRefreshResult(
                from_currency=currency,
                to_currency="EUR",
                provider="ecb",
                status="NOT_MODIFIED",
                rows_written=0,
                observed_at=_datetime_or_none(previous["observed_at"]),
                ingested_at=_datetime_or_none(previous["ingested_at"]),
            )

        rows_written = self._persist_quotes(connection, [result.quote], moment, replace_existing=True)
        return FxRefreshResult(
            from_currency=currency,
            to_currency="EUR",
            provider="ecb",
            status="UPDATED",
            rows_written=rows_written,
            observed_at=_datetime_or_none(result.quote.observed_at),
            ingested_at=moment,
        )

    def backfill_history(
        self,
        connection: sqlite3.Connection,
        currency: str,
        start: date,
        now: datetime | None = None,
    ) -> FxBackfillResult:
        """Storico BCE `currency -> EUR` da `start` a oggi (UTC): inserisce solo le osservazioni mancanti."""
        from backend.app.data_providers.ecb import normalize_ecb_currency

        code = normalize_ecb_currency(currency)
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        quotes = self._ecb(connection).fetch_history(connection, code, start, moment.date(), moment)
        # Stessa direzione e qualita di refresh_currency; le righe esistenti non vengono toccate.
        inserted = self._persist_quotes(connection, quotes, moment, replace_existing=False)
        observed = [quote.observed_at for quote in quotes]
        return FxBackfillResult(
            currency=code,
            inserted=inserted,
            existing=len(quotes) - inserted,
            first_observed_at=min(observed, default=None),
            last_observed_at=max(observed, default=None),
        )

    def refresh_ecb(
        self,
        connection: sqlite3.Connection,
        client: httpx.Client | None = None,
    ) -> int:
        """Percorso Fase 1: un solo documento BCE multi-valuta, persistito atomicamente."""
        provider = self._ecb(connection)
        if client is not None:
            provider = provider.with_client(client)
        now = datetime.now(UTC)
        quotes = provider.fetch_reference_rates(connection, now)
        return self._persist_quotes(connection, quotes, now, replace_existing=False)

    def _ecb(self, connection: sqlite3.Connection) -> EcbFxProvider:
        if self._ecb_provider is not None:
            return self._ecb_provider
        from backend.app.data_providers.provider_registry import ProviderRegistry

        return ProviderRegistry(get_settings(), connection).ecb_fx_provider

    @staticmethod
    def _persist_quotes(
        connection: sqlite3.Connection,
        quotes: Sequence[FXQuote],
        ingested_at: datetime,
        *,
        replace_existing: bool,
    ) -> int:
        """Valida tutte le quote, poi scrive in un savepoint: su errore l'ultimo valore buono resta."""
        from backend.app.data_providers.base import ProviderError

        for quote in quotes:
            if (
                not _CURRENCY_PATTERN.fullmatch(quote.from_currency)
                or quote.to_currency != "EUR"
                or _date_or_none(quote.observed_at) is None
            ):
                raise ProviderError("ecb:FX:MALFORMED_PAYLOAD")
            if not math.isfinite(quote.rate) or quote.rate <= 0:
                raise ProviderError("ecb:FX:INVALID_RATE")

        ingested_at_text = ingested_at.astimezone(UTC).isoformat(timespec="seconds")
        written = 0
        connection.execute("SAVEPOINT fx_persist_quotes")
        try:
            for quote in quotes:
                if replace_existing:
                    connection.execute(
                        """
                        INSERT INTO fx_rates (
                            from_currency, to_currency, rate, observed_at, ingested_at, provider, quality
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(from_currency, to_currency, observed_at, provider) DO UPDATE SET
                            rate = excluded.rate,
                            ingested_at = excluded.ingested_at,
                            quality = excluded.quality
                        """,
                        (
                            quote.from_currency,
                            quote.to_currency,
                            quote.rate,
                            quote.observed_at,
                            ingested_at_text,
                            quote.provider,
                            quote.quality,
                        ),
                    )
                    written += 1
                else:
                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO fx_rates (
                            from_currency, to_currency, rate, observed_at, ingested_at, provider, quality
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            quote.from_currency,
                            quote.to_currency,
                            quote.rate,
                            quote.observed_at,
                            ingested_at_text,
                            quote.provider,
                            quote.quality,
                        ),
                    )
                    written += max(cursor.rowcount, 0)
        except Exception:
            connection.execute("ROLLBACK TO SAVEPOINT fx_persist_quotes")
            connection.execute("RELEASE SAVEPOINT fx_persist_quotes")
            raise
        connection.execute("RELEASE SAVEPOINT fx_persist_quotes")
        return written

    @staticmethod
    def _latest_rate(
        connection: sqlite3.Connection,
        from_currency: str,
        to_currency: str,
    ):
        return connection.execute(
            """
            SELECT rate, observed_at, provider, quality
            FROM fx_rates
            WHERE from_currency = ? AND to_currency = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (from_currency, to_currency),
        ).fetchone()

    @staticmethod
    def _is_stale(observed_at: str) -> bool:
        try:
            observed_date = datetime.fromisoformat(
                observed_at.replace("Z", "+00:00")
            ).date()
        except ValueError:
            return True
        age_days = (datetime.now(UTC).date() - observed_date).days
        return age_days > get_settings().ecb_fx_max_age_days


def _date_or_none(value: object) -> date | None:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _datetime_or_none(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
