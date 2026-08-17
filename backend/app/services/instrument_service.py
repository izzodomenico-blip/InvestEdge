from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from backend.app.models import AssetClass, InstrumentType

_ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_LEGACY_SOURCE = "LEGACY_ACTIVE_ASSET"

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


class InstrumentService:
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
            instrument_id = InstrumentService._create_instrument(
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
