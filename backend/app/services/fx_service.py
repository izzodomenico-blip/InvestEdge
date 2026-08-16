from __future__ import annotations

import math
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from backend.app.config import get_settings

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_RESPONSE_LIMIT_BYTES = 1024 * 1024
ECB_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)


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


class FXService:
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

    def refresh_ecb(
        self,
        connection: sqlite3.Connection,
        client: httpx.Client | None = None,
    ) -> int:
        if client is None:
            with httpx.Client(timeout=ECB_TIMEOUT, follow_redirects=False) as owned_client:
                payload = self._download_ecb(owned_client)
        else:
            payload = self._download_ecb(client)

        inserted = 0
        for currency, rate, observed_at in self._parse_ecb(payload):
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO fx_rates (
                    from_currency, to_currency, rate, observed_at, provider, quality
                )
                VALUES (?, 'EUR', ?, ?, 'ecb', 'reference')
                """,
                (currency, rate, observed_at),
            )
            inserted += max(cursor.rowcount, 0)
        return inserted

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

    @staticmethod
    def _download_ecb(client: httpx.Client) -> bytes:
        with client.stream("GET", ECB_DAILY_URL) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > ECB_RESPONSE_LIMIT_BYTES:
                        raise ValueError("La risposta BCE supera il limite di 1 MiB.")
                except ValueError as exc:
                    if "1 MiB" in str(exc):
                        raise

            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > ECB_RESPONSE_LIMIT_BYTES:
                    raise ValueError("La risposta BCE supera il limite di 1 MiB.")
        return bytes(payload)

    @staticmethod
    def _parse_ecb(payload: bytes) -> list[tuple[str, float, str]]:
        uppercase_payload = payload.upper()
        if b"<!DOCTYPE" in uppercase_payload or b"<!ENTITY" in uppercase_payload:
            raise ValueError("Il feed XML BCE contiene dichiarazioni di entita' non ammesse.")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError("Il feed XML BCE non e' valido.") from exc

        rates: list[tuple[str, float, str]] = []
        for element in root.iter():
            observed_at = element.attrib.get("time")
            if not observed_at:
                continue
            for rate_element in element:
                currency = rate_element.attrib.get("currency", "").strip().upper()
                raw_rate = rate_element.attrib.get("rate")
                if len(currency) != 3 or not currency.isalpha() or raw_rate is None:
                    continue
                try:
                    ecb_rate = float(raw_rate)
                except ValueError as exc:
                    raise ValueError("Il feed XML BCE contiene un cambio non valido.") from exc
                if not math.isfinite(ecb_rate) or ecb_rate <= 0:
                    raise ValueError("Il feed XML BCE contiene un cambio non valido.")
                rates.append((currency, 1.0 / ecb_rate, observed_at))
        if not rates:
            raise ValueError("Il feed XML BCE non contiene cambi utilizzabili.")
        return rates
