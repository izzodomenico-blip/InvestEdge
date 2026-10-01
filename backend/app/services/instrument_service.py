from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from backend.app.models import (
    AssetClass,
    InstrumentType,
    ProviderSymbolApplyIn,
    ProviderSymbolApplyOut,
    ProviderSymbolPreviewIn,
    ProviderSymbolPreviewOut,
    TradeRepublicAttestationApplyIn,
    TradeRepublicAttestationOut,
    TradeRepublicAttestationPreviewIn,
    TradeRepublicAttestationPreviewOut,
)

_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
# Normalizzazione provider-specifica: forma attesa dal provider, mai derivata dal ticker.
_PROVIDER_SYMBOL_PATTERNS = {
    "stooq": re.compile(r"^[a-z0-9^][a-z0-9.\-_]{0,31}$"),
    "finnhub": re.compile(r"^[A-Z0-9][A-Z0-9.\-:]{0,31}$"),
    "coingecko": re.compile(r"^[a-z0-9][a-z0-9\-]{0,99}$"),
}
_PROVIDER_CAPABILITIES = {
    "stooq": frozenset({"EOD"}),
    "finnhub": frozenset({"QUOTE", "NEWS"}),
    "coingecko": frozenset({"EOD", "QUOTE"}),
}
_PROVIDER_INSTRUMENT_TYPES = {
    "stooq": frozenset({"STOCK", "ETF", "BOND", "ETC", "ETN"}),
    "finnhub": frozenset({"STOCK", "ETF"}),
    "coingecko": frozenset({"CRYPTO"}),
}
_LEGACY_SOURCE = "LEGACY_ACTIVE_ASSET"
_LEGACY_CURATED_SOURCE = "LEGACY_CURATED"
_LEGACY_CURATED_CRYPTO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
}

_LEGACY_TYPE_MAPPING: dict[str, tuple[InstrumentType, AssetClass]] = {
    "stock": ("STOCK", "EQUITY"),
    "etf": ("ETF", "FUND"),
    "bond_etf": ("ETF", "FUND"),
    "bond": ("BOND", "FIXED_INCOME"),
    "crypto": ("CRYPTO", "CRYPTO"),
    "fx": ("FX", "FX"),
    "forex": ("FX", "FX"),
    "macro": ("MACRO", "REFERENCE"),
    "bond_proxy": ("RATE", "REFERENCE"),
    "index": ("INDEX", "REFERENCE"),
}


@dataclass(frozen=True)
class ListingKey:
    instrument_id: int
    ticker: str
    mic: str | None
    currency: str


class AmbiguousInstrumentError(ValueError):
    def __init__(self, symbol: str, candidate_listing_ids: Sequence[int]) -> None:
        self.symbol = symbol.strip().upper()
        self.candidate_listing_ids = tuple(candidate_listing_ids)
        joined_ids = ", ".join(str(listing_id) for listing_id in self.candidate_listing_ids)
        super().__init__(
            f"Asset {self.symbol} ambiguo: candidate listing IDs [{joined_ids}]."
        )


class ListingConfirmationError(ValueError):
    """Errore stabile e sanitizzato delle conferme locali di listing."""

    def __init__(
        self,
        reason_code: str,
        kind: Literal["invalid", "conflict", "not_found"],
    ) -> None:
        self.reason_code = reason_code
        self.kind = kind
        super().__init__(reason_code)


def parse_stored_utc(value: object) -> datetime | None:
    """Converte un timestamp salvato (ISO, `Z` o SQLite senza fuso) in UTC."""
    if value is None or not str(value).strip():
        return None
    parsed = datetime.fromisoformat(str(value).strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class InstrumentService:
    @staticmethod
    def resolved_listing(
        connection: sqlite3.Connection,
        listing_id: int,
    ) -> sqlite3.Row | None:
        """Listing RESOLVED: metadata VERIFIED corrente e almeno un case RESOLVED."""
        return connection.execute(
            """
            SELECT listing.*, instrument.instrument_type, instrument.canonical_name,
                   metadata.instrument_type AS verified_instrument_type
            FROM instrument_listings AS listing
            JOIN instruments AS instrument ON instrument.id = listing.instrument_id
            JOIN listing_metadata_versions AS metadata
              ON metadata.instrument_listing_id = listing.id
             AND metadata.status = 'VERIFIED'
            WHERE listing.id = ?
              AND EXISTS (
                  SELECT 1
                  FROM instrument_resolution_cases AS resolution
                  WHERE resolution.selected_listing_id = listing.id
                    AND resolution.status = 'RESOLVED'
              )
            """,
            (listing_id,),
        ).fetchone()

    @staticmethod
    def backfill_curated_crypto_ids(
        connection: sqlite3.Connection,
        observed_at: datetime,
    ) -> int:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("crypto identity migration timestamp must be timezone-aware")
        observed_at_text = observed_at.astimezone(UTC).isoformat()
        owns_transaction = not connection.in_transaction
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")

        original_row_factory = connection.row_factory
        connection.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" for _ in _LEGACY_CURATED_CRYPTO_IDS)
            rows = connection.execute(
                f"""
                SELECT asset.id AS asset_id, asset.symbol, listing.id AS listing_id,
                       listing.instrument_id
                FROM assets AS asset
                JOIN instrument_listings AS listing
                  ON listing.id = asset.instrument_listing_id
                JOIN instruments AS instrument
                  ON instrument.id = listing.instrument_id
                WHERE LOWER(asset.asset_type) = 'crypto'
                  AND instrument.instrument_type = 'CRYPTO'
                  AND UPPER(asset.symbol) IN ({placeholders})
                  AND (
                      SELECT COUNT(*)
                      FROM assets AS candidate
                      WHERE UPPER(candidate.symbol) = UPPER(asset.symbol)
                  ) = 1
                ORDER BY asset.id
                """,
                tuple(_LEGACY_CURATED_CRYPTO_IDS),
            ).fetchall()
            inserted = 0
            for row in rows:
                symbol = str(row["symbol"]).strip().upper()
                coingecko_id = _LEGACY_CURATED_CRYPTO_IDS[symbol]
                conflicting = connection.execute(
                    """
                    SELECT 1
                    FROM instrument_identifiers AS identifier
                    LEFT JOIN instrument_listings AS owner_listing
                      ON owner_listing.id = identifier.listing_id
                    WHERE identifier.scheme = 'COINGECKO_ID'
                      AND identifier.normalized_value = ?
                      AND COALESCE(identifier.instrument_id, owner_listing.instrument_id) != ?
                    LIMIT 1
                    """,
                    (coingecko_id, row["instrument_id"]),
                ).fetchone()
                if conflicting is not None:
                    raise sqlite3.IntegrityError(
                        "CoinGecko curated identity conflicts with another instrument."
                    )

                identifier = connection.execute(
                    """
                    SELECT id
                    FROM instrument_identifiers
                    WHERE scheme = 'COINGECKO_ID'
                      AND normalized_value = ?
                      AND scope = 'INSTRUMENT'
                      AND instrument_id = ?
                    """,
                    (coingecko_id, row["instrument_id"]),
                ).fetchone()
                if identifier is None:
                    identifier_id = int(
                        connection.execute(
                            """
                            INSERT INTO instrument_identifiers (
                                scheme, normalized_value, scope, instrument_id, listing_id
                            )
                            VALUES ('COINGECKO_ID', ?, 'INSTRUMENT', ?, NULL)
                            """,
                            (coingecko_id, row["instrument_id"]),
                        ).lastrowid
                    )
                else:
                    identifier_id = int(identifier["id"])

                # Anche un listing riaggiunto su un instrument gia attestato riceve il fuso
                # UTC, richiesto dalle barre CoinGecko.
                connection.execute(
                    """
                    UPDATE instrument_listings
                    SET timezone = 'UTC'
                    WHERE id = ? AND (timezone IS NULL OR TRIM(timezone) = '')
                    """,
                    (row["listing_id"],),
                )
                attestation = connection.execute(
                    """
                    SELECT 1
                    FROM instrument_identifier_attestations
                    WHERE identifier_id = ? AND source = ?
                    LIMIT 1
                    """,
                    (identifier_id, _LEGACY_CURATED_SOURCE),
                ).fetchone()
                if attestation is not None:
                    continue

                evidence_hash = hashlib.sha256(
                    (
                        f"{_LEGACY_CURATED_SOURCE}|{row['asset_id']}|"
                        f"COINGECKO_ID|{coingecko_id}"
                    ).encode()
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO instrument_identifier_attestations (
                        identifier_id, source, observed_at, evidence_hash
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        identifier_id,
                        _LEGACY_CURATED_SOURCE,
                        observed_at_text,
                        evidence_hash,
                    ),
                )
                inserted += 1
            if owns_transaction:
                connection.commit()
            return inserted
        except Exception:
            if owns_transaction:
                connection.rollback()
            raise
        finally:
            connection.row_factory = original_row_factory

    @staticmethod
    def _attested_identifier_value_count(
        connection: sqlite3.Connection,
        instrument_id: int,
        scheme: str,
    ) -> int:
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT identifier.normalized_value) AS value_count
            FROM instrument_identifiers AS identifier
            LEFT JOIN instrument_listings AS listing
              ON listing.id = identifier.listing_id
            WHERE identifier.scheme = ?
              AND COALESCE(identifier.instrument_id, listing.instrument_id) = ?
              AND EXISTS (
                  SELECT 1
                  FROM instrument_identifier_attestations AS attestation
                  WHERE attestation.identifier_id = identifier.id
              )
            """,
            (scheme, instrument_id),
        ).fetchone()
        return int(row["value_count"])

    @staticmethod
    def has_ambiguous_identity(
        connection: sqlite3.Connection,
        instrument_id: int,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM instrument_resolution_cases AS resolution
            JOIN catalog_entries AS entry
              ON entry.id = resolution.catalog_entry_id
            WHERE entry.instrument_id = ?
              AND resolution.status = 'AMBIGUOUS'
              AND NOT EXISTS (
                  SELECT 1
                  FROM instrument_resolution_cases AS newer
                  WHERE newer.catalog_entry_id = resolution.catalog_entry_id
                    AND newer.id > resolution.id
              )
            LIMIT 1
            """,
            (instrument_id,),
        ).fetchone()
        if row is not None:
            return True
        instrument = connection.execute(
            "SELECT instrument_type FROM instruments WHERE id = ?",
            (instrument_id,),
        ).fetchone()
        if (
            instrument is not None
            and instrument["instrument_type"] == "CRYPTO"
            and InstrumentService._attested_identifier_value_count(
                connection,
                instrument_id,
                "COINGECKO_ID",
            )
            > 1
        ):
            return True
        duplicate_primary = connection.execute(
            """
            SELECT 1
            FROM instrument_identifiers AS current_identifier
            LEFT JOIN instrument_listings AS current_listing
              ON current_listing.id = current_identifier.listing_id
            JOIN instrument_identifiers AS other_identifier
              ON other_identifier.id != current_identifier.id
             AND other_identifier.scheme = current_identifier.scheme
             AND other_identifier.normalized_value = current_identifier.normalized_value
            LEFT JOIN instrument_listings AS other_listing
              ON other_listing.id = other_identifier.listing_id
            WHERE current_identifier.scheme IN ('ISIN', 'FIGI', 'COINGECKO_ID')
              AND COALESCE(
                    current_identifier.instrument_id,
                    current_listing.instrument_id
                  ) = ?
              AND COALESCE(
                    other_identifier.instrument_id,
                    other_listing.instrument_id
                  ) != ?
            LIMIT 1
            """,
            (instrument_id, instrument_id),
        ).fetchone()
        return duplicate_primary is not None

    @staticmethod
    def verified_primary_identifier(
        connection: sqlite3.Connection,
        instrument_id: int,
        instrument_type: str,
    ) -> sqlite3.Row | None:
        schemes = ("COINGECKO_ID",) if instrument_type == "CRYPTO" else ("ISIN", "FIGI")
        if (
            instrument_type == "CRYPTO"
            and InstrumentService._attested_identifier_value_count(
                connection,
                instrument_id,
                "COINGECKO_ID",
            )
            != 1
        ):
            return None
        placeholders = ",".join("?" for _ in schemes)
        return connection.execute(
            f"""
            SELECT identifier.*
            FROM instrument_identifiers AS identifier
            WHERE identifier.scheme IN ({placeholders})
              AND (
                  (identifier.scope = 'INSTRUMENT' AND identifier.instrument_id = ?)
                  OR
                  (
                      identifier.scope = 'LISTING'
                      AND identifier.listing_id IN (
                          SELECT id FROM instrument_listings WHERE instrument_id = ?
                      )
                  )
              )
              AND EXISTS (
                  SELECT 1
                  FROM instrument_identifier_attestations AS attestation
                  WHERE attestation.identifier_id = identifier.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM instrument_identifiers AS other_identifier
                  LEFT JOIN instrument_listings AS other_listing
                    ON other_listing.id = other_identifier.listing_id
                  WHERE other_identifier.id != identifier.id
                    AND other_identifier.scheme = identifier.scheme
                    AND other_identifier.normalized_value = identifier.normalized_value
                    AND COALESCE(
                          other_identifier.instrument_id,
                          other_listing.instrument_id
                        ) != ?
              )
            ORDER BY CASE identifier.scheme
                         WHEN 'ISIN' THEN 1
                         WHEN 'FIGI' THEN 2
                         ELSE 3
                     END,
                     identifier.id
            LIMIT 1
            """,
            (*schemes, instrument_id, instrument_id, instrument_id),
        ).fetchone()

    @staticmethod
    def backfill_active_assets(connection: sqlite3.Connection) -> int:
        owns_transaction = not connection.in_transaction
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")

        original_row_factory = connection.row_factory
        connection.row_factory = sqlite3.Row
        try:
            assets = connection.execute(
                """
                SELECT id, symbol, name, asset_type, exchange, currency, isin,
                       created_at, updated_at, instrument_listing_id
                FROM assets
                WHERE instrument_listing_id IS NULL
                ORDER BY id
                """
            ).fetchall()
            backfilled = 0
            for asset in assets:
                InstrumentService._backfill_asset(connection, asset)
                backfilled += 1
            if owns_transaction:
                connection.commit()
            return backfilled
        except Exception:
            if owns_transaction:
                connection.rollback()
            raise
        finally:
            connection.row_factory = original_row_factory

    @staticmethod
    def require_unique_active_asset(
        connection: sqlite3.Connection,
        symbol: str,
    ) -> sqlite3.Row | None:
        InstrumentService.backfill_active_assets(connection)
        original_row_factory = connection.row_factory
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT id, symbol, name, asset_type, tax_category, exchange, currency,
                       sector, country, risk_level, isin, instrument_listing_id, updated_at
                FROM assets
                WHERE UPPER(symbol) = UPPER(?)
                ORDER BY id
                """,
                (symbol,),
            ).fetchall()
        finally:
            connection.row_factory = original_row_factory

        if not rows:
            return None
        if len(rows) == 1:
            return rows[0]

        listing_ids = [
            int(row["instrument_listing_id"])
            for row in rows
            if row["instrument_listing_id"] is not None
        ]
        if len(listing_ids) != len(rows):
            raise sqlite3.IntegrityError(
                "Active asset ambiguity cannot be reported without listing identity."
            )
        raise AmbiguousInstrumentError(symbol, listing_ids)

    @staticmethod
    def _backfill_asset(connection: sqlite3.Connection, asset: sqlite3.Row) -> None:
        asset_type = str(asset["asset_type"]).strip().lower()
        instrument_type, asset_class = _LEGACY_TYPE_MAPPING.get(
            asset_type,
            ("UNKNOWN", "UNKNOWN"),
        )
        normalized_isin = InstrumentService._eligible_isin(asset["isin"], asset_type)
        observed_at = str(
            asset["updated_at"]
            or asset["created_at"]
            or connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
        )
        source_date = observed_at[:10] if len(observed_at) >= 10 else None

        instrument_id: int
        identifier_id: int | None = None
        if normalized_isin is not None:
            identifier = connection.execute(
                """
                SELECT id, instrument_id, scope
                FROM instrument_identifiers
                WHERE scheme = 'ISIN' AND normalized_value = ?
                """,
                (normalized_isin,),
            ).fetchone()
            if identifier is not None:
                if identifier["scope"] != "INSTRUMENT" or identifier["instrument_id"] is None:
                    raise sqlite3.IntegrityError("ISIN canonical identity has invalid ownership.")
                identifier_id = int(identifier["id"])
                instrument_id = int(identifier["instrument_id"])
            else:
                instrument_id = InstrumentService._create_instrument(
                    connection,
                    asset,
                    instrument_type,
                    asset_class,
                    source_date,
                )
                identifier_id = int(
                    connection.execute(
                        """
                        INSERT INTO instrument_identifiers (
                            scheme, normalized_value, scope, instrument_id, listing_id
                        )
                        VALUES ('ISIN', ?, 'INSTRUMENT', ?, NULL)
                        """,
                        (normalized_isin, instrument_id),
                    ).lastrowid
                )
        else:
            # Una crypto curata riaggiunta (purge o reset del seed) riusa l'instrument
            # che possiede gia' il COINGECKO_ID, come il ramo ISIN.
            curated_owner = InstrumentService._curated_crypto_owner(connection, asset_type, asset["symbol"])
            instrument_id = curated_owner or InstrumentService._create_instrument(
                connection,
                asset,
                instrument_type,
                asset_class,
                source_date,
            )

        ticker = str(asset["symbol"]).strip().upper()
        currency = str(asset["currency"]).strip().upper()
        listing_id = int(
            connection.execute(
                """
                INSERT INTO instrument_listings (
                    instrument_id, ticker, mic, venue_name, currency, timezone,
                    listing_status, trade_republic_status, source, source_date
                )
                VALUES (?, ?, NULL, NULL, ?, NULL, 'ACTIVE', 'NEVER_SEEN', ?, ?)
                """,
                (instrument_id, ticker, currency, _LEGACY_SOURCE, source_date),
            ).lastrowid
        )
        connection.execute(
            "UPDATE assets SET instrument_listing_id = ? WHERE id = ?",
            (listing_id, asset["id"]),
        )

        if identifier_id is not None and normalized_isin is not None:
            evidence_hash = hashlib.sha256(
                f"{_LEGACY_SOURCE}|{asset['id']}|ISIN|{normalized_isin}".encode()
            ).hexdigest()
            connection.execute(
                """
                INSERT INTO instrument_identifier_attestations (
                    identifier_id, source, observed_at, evidence_hash
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(identifier_id, source, observed_at, evidence_hash) DO NOTHING
                """,
                (identifier_id, _LEGACY_SOURCE, observed_at, evidence_hash),
            )

    @staticmethod
    def _curated_crypto_owner(connection: sqlite3.Connection, asset_type: str, symbol: object) -> int | None:
        coingecko_id = _LEGACY_CURATED_CRYPTO_IDS.get(str(symbol).strip().upper())
        if asset_type != "crypto" or coingecko_id is None:
            return None
        owners = connection.execute(
            """
            SELECT DISTINCT identifier.instrument_id
            FROM instrument_identifiers AS identifier
            JOIN instruments AS instrument ON instrument.id = identifier.instrument_id
            WHERE identifier.scheme = 'COINGECKO_ID'
              AND identifier.normalized_value = ?
              AND identifier.scope = 'INSTRUMENT'
              AND instrument.instrument_type = 'CRYPTO'
            """,
            (coingecko_id,),
        ).fetchall()
        return int(owners[0][0]) if len(owners) == 1 else None

    @staticmethod
    def _create_instrument(
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        instrument_type: InstrumentType,
        asset_class: AssetClass,
        source_date: str | None,
    ) -> int:
        return int(
            connection.execute(
                """
                INSERT INTO instruments (
                    canonical_name, instrument_type, asset_class, quality_tier,
                    source, source_date
                )
                VALUES (?, ?, ?, 'REFERENCE_ONLY', ?, ?)
                """,
                (
                    " ".join(str(asset["name"]).split()),
                    instrument_type,
                    asset_class,
                    _LEGACY_SOURCE,
                    source_date,
                ),
            ).lastrowid
        )

    @staticmethod
    def _eligible_isin(value: object, asset_type: str) -> str | None:
        if asset_type in {"crypto", "fx", "forex"} or not isinstance(value, str):
            return None
        normalized = "".join(value.split()).upper()
        return normalized if _ISIN_PATTERN.fullmatch(normalized) else None


@dataclass(frozen=True)
class _ProviderSymbolRequest:
    provider: str
    capability: str
    provider_symbol: str
    normalized_symbol: str
    source: str
    observed_at: str
    expected_currency: str
    evidence_hash: str


@dataclass(frozen=True)
class _AttestationRequest:
    status: str
    source: str
    observed_at: str
    evidence_hash: str


class ListingConfirmationService:
    """Conferme locali e versionate di provider symbol e stato Trade Republic.

    Preview e apply leggono e scrivono solo il database locale: nessuna chiamata a
    provider, nessun login, nessuna automazione dell'app Trade Republic.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def preview_provider_symbol(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
        payload: ProviderSymbolPreviewIn,
    ) -> ProviderSymbolPreviewOut:
        request = self._provider_symbol_request(payload)
        listing = self._require_resolved_listing(connection, listing_id)
        self._check_provider_listing(listing, request)
        self._ensure_provider_symbol_free(connection, listing_id, request)
        current = self._current_provider_symbol(connection, listing_id, request)
        current_version = int(current["version"]) if current is not None else None
        return ProviderSymbolPreviewOut(
            listing_id=listing_id,
            normalized_provider_symbol=request.provider_symbol,
            current_version=current_version,
            confirmation_token=self._provider_symbol_token(listing_id, request, current_version),
        )

    def apply_provider_symbol(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
        payload: ProviderSymbolApplyIn,
    ) -> ProviderSymbolApplyOut:
        request = self._provider_symbol_request(payload)
        self._begin(connection)
        try:
            listing = self._require_resolved_listing(connection, listing_id)
            self._check_provider_listing(listing, request)
            current = self._current_provider_symbol(connection, listing_id, request)
            if current is not None and self._provider_symbol_matches(current, request):
                connection.commit()
                return self._provider_symbol_out(current)
            self._ensure_provider_symbol_free(connection, listing_id, request)
            current_version = int(current["version"]) if current is not None else None
            expected_token = self._provider_symbol_token(listing_id, request, current_version)
            if not hmac.compare_digest(payload.confirmation_token, expected_token):
                raise ListingConfirmationError("PROVIDER_SYMBOL_CHANGED", "conflict")
            # Ordine obbligato: ritiro della versione corrente, poi nuova VERIFIED.
            if current is not None:
                connection.execute(
                    "UPDATE provider_symbols SET status = 'RETIRED' WHERE id = ?",
                    (int(current["id"]),),
                )
            latest = connection.execute(
                """
                SELECT MAX(version) AS version
                FROM provider_symbols
                WHERE UPPER(provider) = UPPER(?) AND listing_id = ? AND UPPER(capability) = ?
                """,
                (request.provider, listing_id, request.capability),
            ).fetchone()
            symbol_id = int(
                connection.execute(
                    """
                    INSERT INTO provider_symbols (
                        provider, listing_id, capability, provider_symbol, normalized_symbol,
                        status, source, observed_at, verified_at, evidence_hash, version,
                        supersedes_provider_symbol_id
                    )
                    VALUES (?, ?, ?, ?, ?, 'VERIFIED', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.provider,
                        listing_id,
                        request.capability,
                        request.provider_symbol,
                        request.normalized_symbol,
                        request.source,
                        request.observed_at,
                        request.observed_at,
                        request.evidence_hash,
                        int(latest["version"] or 0) + 1,
                        int(current["id"]) if current is not None else None,
                    ),
                ).lastrowid
            )
            created = connection.execute(
                "SELECT * FROM provider_symbols WHERE id = ?",
                (symbol_id,),
            ).fetchone()
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            raise ListingConfirmationError("PROVIDER_SYMBOL_CHANGED", "conflict") from None
        except Exception:
            connection.rollback()
            raise
        return self._provider_symbol_out(created)

    def preview_trade_republic_attestation(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
        payload: TradeRepublicAttestationPreviewIn,
    ) -> TradeRepublicAttestationPreviewOut:
        request = self._attestation_request(payload)
        listing = self._require_resolved_listing(connection, listing_id)
        active = self._active_attestation(connection, listing_id)
        current_version = int(active["version"]) if active is not None else None
        return TradeRepublicAttestationPreviewOut(
            listing_id=listing_id,
            current_status=listing["trade_republic_status"],
            current_version=current_version,
            confirmation_token=self._attestation_token(listing_id, request, current_version),
        )

    def apply_trade_republic_attestation(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
        payload: TradeRepublicAttestationApplyIn,
    ) -> TradeRepublicAttestationOut:
        request = self._attestation_request(payload)
        self._begin(connection)
        try:
            self._require_resolved_listing(connection, listing_id)
            active = self._active_attestation(connection, listing_id)
            if active is not None and self._attestation_matches(active, request):
                connection.commit()
                return self._attestation_out(active)
            current_version = int(active["version"]) if active is not None else None
            expected_token = self._attestation_token(listing_id, request, current_version)
            if not hmac.compare_digest(payload.confirmation_token, expected_token):
                raise ListingConfirmationError("TRADE_REPUBLIC_ATTESTATION_CHANGED", "conflict")
            latest = connection.execute(
                "SELECT MAX(version) AS version FROM trade_republic_attestations WHERE listing_id = ?",
                (listing_id,),
            ).fetchone()
            # Ordine transazionale: retire precedente -> insert nuova ACTIVE -> projection.
            if active is not None:
                connection.execute(
                    """
                    UPDATE trade_republic_attestations
                    SET record_status = 'RETIRED'
                    WHERE id = ? AND record_status = 'ACTIVE'
                    """,
                    (int(active["id"]),),
                )
            attestation_id = int(
                connection.execute(
                    """
                    INSERT INTO trade_republic_attestations (
                        listing_id, status, record_status, source, observed_at,
                        evidence_hash, version, supersedes_attestation_id
                    )
                    VALUES (?, ?, 'ACTIVE', ?, ?, ?, ?, ?)
                    """,
                    (
                        listing_id,
                        request.status,
                        request.source,
                        request.observed_at,
                        request.evidence_hash,
                        int(latest["version"] or 0) + 1,
                        int(active["id"]) if active is not None else None,
                    ),
                ).lastrowid
            )
            connection.execute(
                """
                UPDATE instrument_listings
                SET trade_republic_status = ?,
                    trade_republic_verified_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    request.status,
                    request.observed_at if request.status == "VERIFIED" else None,
                    listing_id,
                ),
            )
            created = connection.execute(
                "SELECT * FROM trade_republic_attestations WHERE id = ?",
                (attestation_id,),
            ).fetchone()
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            # Collisione concorrente sull'indice ACTIVE: rilettura come idempotenza o stale.
            active = self._active_attestation(connection, listing_id)
            if active is not None and self._attestation_matches(active, request):
                return self._attestation_out(active)
            raise ListingConfirmationError(
                "TRADE_REPUBLIC_ATTESTATION_CHANGED",
                "conflict",
            ) from None
        except Exception:
            connection.rollback()
            raise
        return self._attestation_out(created)

    @staticmethod
    def _begin(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            raise RuntimeError("Le conferme locali richiedono una connessione senza transazione aperta.")
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _require_resolved_listing(
        connection: sqlite3.Connection,
        listing_id: int,
    ) -> sqlite3.Row:
        listing = connection.execute(
            "SELECT id FROM instrument_listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        if listing is None:
            raise ListingConfirmationError("LISTING_NOT_FOUND", "not_found")
        resolved = InstrumentService.resolved_listing(connection, listing_id)
        if resolved is None or resolved["listing_status"] != "ACTIVE":
            raise ListingConfirmationError("LISTING_NOT_RESOLVED", "conflict")
        return resolved

    def _observed_at(self, value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ListingConfirmationError("INVALID_OBSERVED_AT", "invalid")
        if value.astimezone(UTC) > self._clock().astimezone(UTC):
            raise ListingConfirmationError("FUTURE_OBSERVED_AT", "invalid")
        return _utc_text(value)

    @staticmethod
    def _evidence_hash(value: str) -> str:
        evidence_hash = value.strip().lower()
        if not _SHA256_PATTERN.fullmatch(evidence_hash):
            raise ListingConfirmationError("INVALID_EVIDENCE_HASH", "invalid")
        return evidence_hash

    def _provider_symbol_request(self, payload: ProviderSymbolPreviewIn) -> _ProviderSymbolRequest:
        provider = payload.provider
        capability = payload.capability
        if capability not in _PROVIDER_CAPABILITIES[provider]:
            raise ListingConfirmationError("INCOMPATIBLE_PROVIDER_CAPABILITY", "invalid")
        raw_symbol = payload.provider_symbol.strip()
        provider_symbol = raw_symbol.upper() if provider == "finnhub" else raw_symbol.lower()
        if not _PROVIDER_SYMBOL_PATTERNS[provider].fullmatch(provider_symbol):
            raise ListingConfirmationError("INVALID_PROVIDER_SYMBOL", "invalid")
        source = payload.source.strip().upper()
        if not _SOURCE_CODE_PATTERN.fullmatch(source):
            raise ListingConfirmationError("INVALID_SOURCE", "invalid")
        expected_currency = payload.expected_currency.strip().upper()
        if not _CURRENCY_PATTERN.fullmatch(expected_currency):
            raise ListingConfirmationError("INVALID_CURRENCY", "invalid")
        return _ProviderSymbolRequest(
            provider=provider,
            capability=capability,
            provider_symbol=provider_symbol,
            normalized_symbol=provider_symbol.upper(),
            source=source,
            observed_at=self._observed_at(payload.observed_at),
            expected_currency=expected_currency,
            evidence_hash=self._evidence_hash(payload.evidence_hash),
        )

    @staticmethod
    def _check_provider_listing(listing: sqlite3.Row, request: _ProviderSymbolRequest) -> None:
        from backend.app.data_providers.coingecko import CoinGeckoProvider
        from backend.app.data_providers.finnhub_quote import FinnhubQuoteProvider

        instrument_type = str(listing["instrument_type"]).strip().upper()
        if instrument_type not in _PROVIDER_INSTRUMENT_TYPES[request.provider]:
            raise ListingConfirmationError("INCOMPATIBLE_INSTRUMENT_TYPE", "invalid")
        mic = str(listing["mic"] or "").strip().upper()
        if request.provider == "finnhub" and mic not in FinnhubQuoteProvider.supported_mics:
            raise ListingConfirmationError("INCOMPATIBLE_VENUE", "invalid")
        currency = str(listing["currency"]).strip().upper()
        if request.expected_currency != currency or (
            request.provider == "coingecko"
            and currency not in CoinGeckoProvider.supported_quote_currencies
        ):
            raise ListingConfirmationError("CURRENCY_MISMATCH", "invalid")

    @staticmethod
    def _current_provider_symbol(
        connection: sqlite3.Connection,
        listing_id: int,
        request: _ProviderSymbolRequest,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT *
            FROM provider_symbols
            WHERE UPPER(provider) = UPPER(?)
              AND listing_id = ?
              AND UPPER(capability) = ?
              AND status = 'VERIFIED'
            """,
            (request.provider, listing_id, request.capability),
        ).fetchone()

    @staticmethod
    def _ensure_provider_symbol_free(
        connection: sqlite3.Connection,
        listing_id: int,
        request: _ProviderSymbolRequest,
    ) -> None:
        collision = connection.execute(
            """
            SELECT 1
            FROM provider_symbols
            WHERE UPPER(provider) = UPPER(?)
              AND UPPER(capability) = ?
              AND UPPER(normalized_symbol) = ?
              AND status = 'VERIFIED'
              AND listing_id != ?
            LIMIT 1
            """,
            (request.provider, request.capability, request.normalized_symbol, listing_id),
        ).fetchone()
        if collision is not None:
            raise ListingConfirmationError("PROVIDER_SYMBOL_IN_USE", "conflict")

    @staticmethod
    def _provider_symbol_matches(row: sqlite3.Row, request: _ProviderSymbolRequest) -> bool:
        return (
            row["provider_symbol"] == request.provider_symbol
            and row["normalized_symbol"] == request.normalized_symbol
            and row["source"] == request.source
            and row["observed_at"] == request.observed_at
            and row["evidence_hash"] == request.evidence_hash
        )

    @staticmethod
    def _provider_symbol_token(
        listing_id: int,
        request: _ProviderSymbolRequest,
        current_version: int | None,
    ) -> str:
        return _canonical_hash(
            {
                "scope": "provider_symbol",
                "listing_id": listing_id,
                "provider": request.provider,
                "provider_symbol": request.provider_symbol,
                "capability": request.capability,
                "currency": request.expected_currency,
                "source": request.source,
                "observed_at": request.observed_at,
                "evidence_hash": request.evidence_hash,
                "current_version": current_version,
            }
        )

    @staticmethod
    def _provider_symbol_out(row: sqlite3.Row) -> ProviderSymbolApplyOut:
        return ProviderSymbolApplyOut(
            listing_id=int(row["listing_id"]),
            provider=str(row["provider"]),
            capability=row["capability"],
            normalized_provider_symbol=str(row["provider_symbol"]),
            version=int(row["version"]),
            status="VERIFIED",
        )

    def _attestation_request(self, payload: TradeRepublicAttestationPreviewIn) -> _AttestationRequest:
        return _AttestationRequest(
            status=payload.status,
            source=payload.source,
            observed_at=self._observed_at(payload.observed_at),
            evidence_hash=self._evidence_hash(payload.evidence_hash),
        )

    @staticmethod
    def _active_attestation(
        connection: sqlite3.Connection,
        listing_id: int,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT *
            FROM trade_republic_attestations
            WHERE listing_id = ? AND record_status = 'ACTIVE'
            """,
            (listing_id,),
        ).fetchone()

    @staticmethod
    def _attestation_matches(row: sqlite3.Row, request: _AttestationRequest) -> bool:
        return (
            row["status"] == request.status
            and row["source"] == request.source
            and row["observed_at"] == request.observed_at
            and row["evidence_hash"] == request.evidence_hash
        )

    @staticmethod
    def _attestation_token(
        listing_id: int,
        request: _AttestationRequest,
        current_version: int | None,
    ) -> str:
        return _canonical_hash(
            {
                "scope": "trade_republic_attestation",
                "listing_id": listing_id,
                "status": request.status,
                "source": request.source,
                "observed_at": request.observed_at,
                "evidence_hash": request.evidence_hash,
                "current_version": current_version,
            }
        )

    @staticmethod
    def _attestation_out(row: sqlite3.Row) -> TradeRepublicAttestationOut:
        return TradeRepublicAttestationOut(
            listing_id=int(row["listing_id"]),
            status=row["status"],
            source=row["source"],
            observed_at=parse_stored_utc(row["observed_at"]),
            evidence_hash=str(row["evidence_hash"]),
            version=int(row["version"]),
        )
