from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.data_providers.openfigi import (
    OPENFIGI_PROVIDER,
    OpenFigiCandidate,
    OpenFigiJobResult,
    OpenFigiProvider,
)
from backend.app.models import (
    InstrumentType,
    ListingMetadataApplyIn,
    ListingMetadataPreviewIn,
    ListingMetadataPreviewOut,
    ResolutionReason,
    ResolutionStatus,
)

_TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-/:]{0,63}$")
_MIC_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
_SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
_ISO_4217_CODES = frozenset(
    {
        "AED", "AFN", "ALL", "AMD", "ANG", "AOA", "ARS", "AUD", "AWG",
        "AZN", "BAM", "BBD", "BDT", "BGN", "BHD", "BIF", "BMD", "BND",
        "BOB", "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF",
        "CHF", "CLP", "CNY", "COP", "CRC", "CUP", "CVE", "CZK", "DJF",
        "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD", "FKP",
        "GBP", "GEL", "GHS", "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD",
        "HNL", "HTG", "HUF", "IDR", "ILS", "INR", "IQD", "IRR", "ISK",
        "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW",
        "KWD", "KYD", "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "LYD",
        "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR",
        "MVR", "MWK", "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK",
        "NPR", "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN",
        "PYG", "QAR", "RON", "RSD", "RUB", "RWF", "SAR", "SBD", "SCR",
        "SDG", "SEK", "SGD", "SHP", "SLE", "SOS", "SRD", "SSP", "STN",
        "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP", "TRY",
        "TTD", "TWD", "TZS", "UAH", "UGX", "USD", "UYU", "UZS", "VED",
        "VES", "VND", "VUV", "WST", "XAF", "XCD", "XOF", "XPF", "YER",
        "ZAR", "ZMW", "ZWL",
    }
)
_ASSET_CLASS_BY_TYPE = {
    "STOCK": "EQUITY",
    "ETF": "FUND",
    "BOND": "FIXED_INCOME",
    "ETC": "COMMODITY",
    "ETN": "COMMODITY",
    "CRYPTO": "CRYPTO",
    "FX": "FX",
    "INDEX": "REFERENCE",
    "RATE": "REFERENCE",
    "MACRO": "REFERENCE",
    "UNKNOWN": "UNKNOWN",
}


@dataclass(frozen=True)
class ResolutionResult:
    catalog_entry_id: int
    status: ResolutionStatus
    reason_code: ResolutionReason
    instrument_id: int | None
    listing_id: int | None
    candidate_count: int
    evidence_hash: str


@dataclass(frozen=True)
class _NormalizedMetadata:
    ticker: str
    mic: str
    venue_name: str
    currency: str
    timezone: str
    instrument_type: InstrumentType
    source: str
    observed_at: str
    evidence_hash: str


class ResolutionConflictError(ValueError):
    pass


class CatalogResolutionError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _result_from_case(row: sqlite3.Row) -> ResolutionResult:
    return ResolutionResult(
        catalog_entry_id=int(row["catalog_entry_id"]),
        status=row["status"],
        reason_code=row["reason_code"],
        instrument_id=(
            int(row["selected_instrument_id"])
            if row["selected_instrument_id"] is not None
            else None
        ),
        listing_id=(
            int(row["selected_listing_id"])
            if row["selected_listing_id"] is not None
            else None
        ),
        candidate_count=int(row["candidate_count"]),
        evidence_hash=str(row["evidence_hash"]),
    )


class InstrumentResolutionService:
    def __init__(
        self,
        *,
        provider: OpenFigiProvider | object | None = None,
        clock=None,  # noqa: ANN001
    ) -> None:
        self._provider = provider or OpenFigiProvider()
        self._clock = clock or (lambda: datetime.now(UTC))

    def resolve_catalog_entries(
        self,
        connection: sqlite3.Connection,
        entry_ids: Sequence[int],
    ) -> list[ResolutionResult]:
        ordered_ids = [int(entry_id) for entry_id in entry_ids]
        if len(ordered_ids) > 5:
            raise ValueError("catalog resolution accepts at most 5 entries")
        if not ordered_ids:
            return []
        entries = {
            int(row["id"]): row
            for row in connection.execute(
                f"""
                SELECT ce.*, cs.status AS snapshot_status, cs.retrieved_at,
                       i.instrument_type
                FROM catalog_entries AS ce
                JOIN catalog_snapshots AS cs ON cs.id = ce.snapshot_id
                JOIN instruments AS i ON i.id = ce.instrument_id
                WHERE ce.id IN ({','.join('?' for _ in ordered_ids)})
                """,
                ordered_ids,
            ).fetchall()
        }
        for entry_id in ordered_ids:
            entry = entries.get(entry_id)
            if entry is None:
                raise CatalogResolutionError("CATALOG_ENTRY_NOT_FOUND")
            if entry["snapshot_status"] != "COMPLETE":
                raise CatalogResolutionError("CATALOG_SNAPSHOT_NOT_COMPLETE")
            if entry["parse_status"] != "ACCEPTED" or not entry["isin"]:
                raise CatalogResolutionError("CATALOG_ENTRY_NOT_ACCEPTED")

        cached: dict[int, sqlite3.Row] = {}
        pending_ids: list[int] = []
        for entry_id in dict.fromkeys(ordered_ids):
            latest = self._latest_case(connection, entry_id)
            if latest is None:
                pending_ids.append(entry_id)
            else:
                cached[entry_id] = latest

        mapped: dict[int, OpenFigiJobResult] = {}
        if pending_ids:
            provider_results = self._provider.map_isins(  # type: ignore[attr-defined]
                connection,
                [str(entries[entry_id]["isin"]) for entry_id in pending_ids],
                now=self._clock(),
            )
            if len(provider_results) != len(pending_ids):
                raise RuntimeError("OpenFIGI result cardinality mismatch")
            mapped = dict(zip(pending_ids, provider_results, strict=True))

        if mapped:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for entry_id, provider_result in mapped.items():
                    cached[entry_id] = self._evaluate_provider_result(
                        connection,
                        entries[entry_id],
                        provider_result,
                    )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
        return [_result_from_case(cached[entry_id]) for entry_id in ordered_ids]

    def preview_listing_metadata(
        self,
        connection: sqlite3.Connection,
        catalog_entry_id: int,
        payload: ListingMetadataPreviewIn,
    ) -> ListingMetadataPreviewOut:
        entry = self._require_accepted_entry(connection, catalog_entry_id)
        candidate_case = self._require_unique_candidate_case(connection, catalog_entry_id)
        normalized = self._normalize_metadata(payload)
        self._validate_metadata_compatibility(entry, candidate_case, normalized)
        listing, current = self._listing_state(connection, entry, normalized)
        current_version = int(current["version"]) if current is not None else None
        token = self._metadata_token(
            catalog_entry_id,
            int(entry["instrument_id"]),
            normalized,
            current_version,
        )
        if listing is not None and current is not None:
            self._ensure_current_type_matches(current, normalized)
        return ListingMetadataPreviewOut(
            catalog_entry_id=catalog_entry_id,
            normalized_ticker=normalized.ticker,
            normalized_mic=normalized.mic,
            normalized_currency=normalized.currency,
            normalized_timezone=normalized.timezone,
            current_version=current_version,
            confirmation_token=token,
        )

    def apply_listing_metadata(
        self,
        connection: sqlite3.Connection,
        catalog_entry_id: int,
        payload: ListingMetadataApplyIn,
    ) -> ResolutionResult:
        nested_transaction = connection.in_transaction
        savepoint = "investedge_listing_metadata_apply"
        if nested_transaction:
            connection.execute(f"SAVEPOINT {savepoint}")
        else:
            connection.execute("BEGIN IMMEDIATE")
        try:
            entry = self._require_accepted_entry(connection, catalog_entry_id)
            candidate_case = self._require_unique_candidate_case(
                connection,
                catalog_entry_id,
            )
            normalized = self._normalize_metadata(payload)
            self._validate_metadata_compatibility(entry, candidate_case, normalized)
            listing, current = self._listing_state(connection, entry, normalized)

            idempotent = self._idempotent_apply_result(
                connection,
                catalog_entry_id,
                listing,
                current,
                normalized,
            )
            if idempotent is not None:
                if nested_transaction:
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    connection.commit()
                return idempotent

            current_version = int(current["version"]) if current is not None else None
            expected_token = self._metadata_token(
                catalog_entry_id,
                int(entry["instrument_id"]),
                normalized,
                current_version,
            )
            if not hmac.compare_digest(payload.confirmation_token, expected_token):
                raise ResolutionConflictError("LISTING_METADATA_CHANGED")

            listing_id = self._create_or_update_listing(
                connection,
                entry,
                listing,
                normalized,
            )
            metadata_version_id = self._create_or_reuse_metadata_version(
                connection,
                listing_id,
                current,
                normalized,
            )
            connection.execute(
                """
                INSERT INTO catalog_listing_attestations (
                    catalog_entry_id, instrument_listing_id,
                    listing_metadata_version_id, evidence_hash, attested_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(
                    catalog_entry_id, instrument_listing_id,
                    listing_metadata_version_id, evidence_hash
                ) DO NOTHING
                """,
                (
                    catalog_entry_id,
                    listing_id,
                    metadata_version_id,
                    normalized.evidence_hash,
                    _timestamp(self._clock()),
                ),
            )
            refreshed_entry = self._require_accepted_entry(connection, catalog_entry_id)
            case = self._resolve_from_persisted_candidate(
                connection,
                refreshed_entry,
                candidate_case,
                listing_id,
                metadata_version_id,
            )
        except Exception:
            if nested_transaction:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                connection.rollback()
            raise
        if nested_transaction:
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        else:
            connection.commit()
        return _result_from_case(case)

    def require_resolved_listing(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT il.*, lmv.id AS listing_metadata_version_id,
                   lmv.version AS metadata_version,
                   lmv.instrument_type AS verified_instrument_type,
                   lmv.source_code AS metadata_source_code,
                   lmv.observed_at AS metadata_observed_at,
                   lmv.evidence_hash AS metadata_evidence_hash
            FROM instrument_listings AS il
            JOIN listing_metadata_versions AS lmv
              ON lmv.instrument_listing_id = il.id AND lmv.status = 'VERIFIED'
            WHERE il.id = ?
              AND EXISTS (
                  SELECT 1
                  FROM instrument_resolution_cases AS irc
                  WHERE irc.selected_listing_id = il.id
                    AND irc.status = 'RESOLVED'
              )
            """,
            (listing_id,),
        ).fetchone()
        if row is None:
            raise ValueError("LISTING_NOT_RESOLVED")
        return row

    @staticmethod
    def _latest_case(
        connection: sqlite3.Connection,
        catalog_entry_id: int,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT *
            FROM instrument_resolution_cases
            WHERE catalog_entry_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (catalog_entry_id,),
        ).fetchone()

    def _evaluate_provider_result(
        self,
        connection: sqlite3.Connection,
        entry: sqlite3.Row,
        provider_result: OpenFigiJobResult,
    ) -> sqlite3.Row:
        instrument_id = int(entry["instrument_id"])
        if provider_result.invalid_payload:
            return self._insert_case(
                connection,
                entry,
                provider_result,
                "REJECTED",
                "INVALID_PROVIDER_PAYLOAD",
                None,
            )
        if not provider_result.candidates:
            return self._insert_case(
                connection,
                entry,
                provider_result,
                "UNMATCHED",
                "NO_PROVIDER_MATCH",
                None,
            )

        type_compatible = [
            candidate
            for candidate in provider_result.candidates
            if self._candidate_type_matches(str(entry["instrument_type"]), candidate)
        ]
        compatible = [
            candidate
            for candidate in type_compatible
            if self._figi_owner_is_compatible(connection, instrument_id, candidate.figi)
        ]
        if not compatible:
            reason: ResolutionReason = (
                "TYPE_MISMATCH" if not type_compatible else "INVALID_PROVIDER_PAYLOAD"
            )
            return self._insert_case(
                connection,
                entry,
                provider_result,
                "REJECTED",
                reason,
                None,
            )
        if len(compatible) > 1:
            return self._insert_case(
                connection,
                entry,
                provider_result,
                "AMBIGUOUS",
                "MULTIPLE_COMPATIBLE_CANDIDATES",
                None,
            )

        matches: list[tuple[OpenFigiCandidate, sqlite3.Row, sqlite3.Row]] = []
        currency_mismatch = False
        ambiguous_local = False
        for candidate in compatible:
            listing, metadata, mismatch, ambiguous = self._current_listing_for_candidate(
                connection,
                instrument_id,
                candidate,
            )
            currency_mismatch = currency_mismatch or mismatch
            ambiguous_local = ambiguous_local or ambiguous
            if listing is not None and metadata is not None:
                matches.append((candidate, listing, metadata))

        if len(matches) == 1:
            candidate, listing, metadata = matches[0]
            return self._finalize_resolution_case(
                connection,
                entry,
                provider_result,
                candidate,
                int(listing["id"]),
                int(metadata["id"]),
            )
        if len(matches) > 1 or ambiguous_local:
            return self._insert_case(
                connection,
                entry,
                provider_result,
                "AMBIGUOUS",
                "MULTIPLE_COMPATIBLE_CANDIDATES",
                None,
            )
        if currency_mismatch:
            return self._insert_case(
                connection,
                entry,
                provider_result,
                "REJECTED",
                "CURRENCY_MISMATCH",
                compatible[0] if len(compatible) == 1 else None,
            )
        reason = self._missing_metadata_reason(
            connection,
            instrument_id,
            compatible[0],
        )
        return self._insert_case(
            connection,
            entry,
            provider_result,
            "REJECTED",
            reason,
            compatible[0],
        )

    def _insert_case(
        self,
        connection: sqlite3.Connection,
        entry: sqlite3.Row,
        provider_result: OpenFigiJobResult,
        status: ResolutionStatus,
        reason: ResolutionReason,
        candidate: OpenFigiCandidate | None,
        *,
        listing_id: int | None = None,
    ) -> sqlite3.Row:
        case_id = int(
            connection.execute(
                """
                INSERT INTO instrument_resolution_cases (
                    catalog_entry_id, provider, request_fingerprint, status,
                    reason_code, candidate_count, candidate_hash, evidence_hash,
                    selected_instrument_id, selected_listing_id,
                    candidate_figi, candidate_ticker, candidate_exchange_code,
                    candidate_market_sector, candidate_security_type, candidate_name,
                    candidate_currency_hint, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(entry["id"]),
                    OPENFIGI_PROVIDER,
                    provider_result.request_fingerprint,
                    status,
                    reason,
                    len(provider_result.candidates),
                    provider_result.candidate_hash,
                    provider_result.evidence_hash,
                    int(entry["instrument_id"]),
                    listing_id,
                    candidate.figi if candidate else None,
                    candidate.ticker if candidate else None,
                    candidate.exchange_code if candidate else None,
                    candidate.market_sector if candidate else None,
                    candidate.security_type if candidate else None,
                    candidate.name if candidate else None,
                    candidate.currency_hint if candidate else None,
                    _timestamp(self._clock()),
                ),
            ).lastrowid
        )
        return connection.execute(
            "SELECT * FROM instrument_resolution_cases WHERE id = ?",
            (case_id,),
        ).fetchone()

    def _finalize_resolution_case(
        self,
        connection: sqlite3.Connection,
        entry: sqlite3.Row,
        provider_result: OpenFigiJobResult,
        candidate: OpenFigiCandidate,
        listing_id: int,
        metadata_version_id: int,
    ) -> sqlite3.Row:
        instrument_id = int(entry["instrument_id"])
        metadata = connection.execute(
            "SELECT * FROM listing_metadata_versions WHERE id = ? AND status = 'VERIFIED'",
            (metadata_version_id,),
        ).fetchone()
        if metadata is None:
            raise ResolutionConflictError("LISTING_METADATA_CHANGED")
        verified_type = str(metadata["instrument_type"])
        if entry["isin"] and verified_type in {"CRYPTO", "FX"}:
            raise ResolutionConflictError("ISIN_INSTRUMENT_TYPE_CONFLICT")
        self._save_resolved_identifiers(
            connection,
            instrument_id,
            listing_id,
            candidate,
            provider_result.evidence_hash,
        )
        instrument = connection.execute(
            "SELECT instrument_type FROM instruments WHERE id = ?",
            (instrument_id,),
        ).fetchone()
        if instrument["instrument_type"] == "UNKNOWN":
            connection.execute(
                """
                UPDATE instruments
                SET instrument_type = ?, asset_class = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    verified_type,
                    _ASSET_CLASS_BY_TYPE[verified_type],
                    instrument_id,
                ),
            )
        elif instrument["instrument_type"] != verified_type:
            raise ResolutionConflictError("INSTRUMENT_TYPE_CHANGED")

        connection.execute(
            "UPDATE catalog_entries SET listing_id = ? WHERE id = ?",
            (listing_id, int(entry["id"])),
        )
        connection.execute(
            """
            UPDATE instrument_listings
            SET trade_republic_status = CASE
                    WHEN trade_republic_status = 'NEVER_SEEN' THEN 'CATALOGED'
                    ELSE trade_republic_status
                END,
                trade_republic_cataloged_at = CASE
                    WHEN trade_republic_cataloged_at IS NULL
                         OR julianday(?) > julianday(trade_republic_cataloged_at)
                    THEN ?
                    ELSE trade_republic_cataloged_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (entry["retrieved_at"], entry["retrieved_at"], listing_id),
        )
        connection.execute(
            """
            INSERT INTO catalog_listing_attestations (
                catalog_entry_id, instrument_listing_id,
                listing_metadata_version_id, evidence_hash, attested_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(
                catalog_entry_id, instrument_listing_id,
                listing_metadata_version_id, evidence_hash
            ) DO NOTHING
            """,
            (
                int(entry["id"]),
                listing_id,
                metadata_version_id,
                metadata["evidence_hash"],
                _timestamp(self._clock()),
            ),
        )
        return self._insert_case(
            connection,
            entry,
            provider_result,
            "RESOLVED",
            "EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE",
            candidate,
            listing_id=listing_id,
        )

    def _resolve_from_persisted_candidate(
        self,
        connection: sqlite3.Connection,
        entry: sqlite3.Row,
        candidate_case: sqlite3.Row,
        listing_id: int,
        metadata_version_id: int,
    ) -> sqlite3.Row:
        candidate = self._candidate_from_case(candidate_case)
        provider_result = OpenFigiJobResult(
            isin=str(entry["isin"]),
            candidates=(candidate,),
            request_fingerprint=str(candidate_case["request_fingerprint"]),
            candidate_hash=str(candidate_case["candidate_hash"]),
            evidence_hash=str(candidate_case["evidence_hash"]),
            invalid_payload=False,
        )
        return self._finalize_resolution_case(
            connection,
            entry,
            provider_result,
            candidate,
            listing_id,
            metadata_version_id,
        )

    @staticmethod
    def _candidate_from_case(row: sqlite3.Row) -> OpenFigiCandidate:
        if not row["candidate_figi"]:
            raise ResolutionConflictError("OPENFIGI_CANDIDATE_CHANGED")
        return OpenFigiCandidate(
            figi=str(row["candidate_figi"]),
            ticker=row["candidate_ticker"],
            exchange_code=row["candidate_exchange_code"],
            market_sector=row["candidate_market_sector"],
            security_type=row["candidate_security_type"],
            name=row["candidate_name"],
            currency_hint=row["candidate_currency_hint"],
        )

    @staticmethod
    def _candidate_type_matches(
        instrument_type: str,
        candidate: OpenFigiCandidate,
    ) -> bool:
        compatible_types = candidate.compatible_types()
        if not compatible_types or compatible_types & {"CRYPTO", "FX"}:
            return False
        return instrument_type == "UNKNOWN" or instrument_type in compatible_types

    @staticmethod
    def _figi_owner_is_compatible(
        connection: sqlite3.Connection,
        instrument_id: int,
        figi: str,
    ) -> bool:
        owner = connection.execute(
            """
            SELECT instrument_id, scope
            FROM instrument_identifiers
            WHERE scheme = 'FIGI' AND normalized_value = ?
            """,
            (figi,),
        ).fetchone()
        return owner is None or (
            owner["scope"] == "INSTRUMENT"
            and owner["instrument_id"] == instrument_id
        )

    def _current_listing_for_candidate(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        candidate: OpenFigiCandidate,
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None, bool, bool]:
        rows = connection.execute(
            """
            SELECT il.*, lmv.id AS metadata_id, lmv.instrument_type AS metadata_type,
                   lmv.version AS metadata_version, lmv.evidence_hash AS metadata_evidence_hash
            FROM instrument_listings AS il
            JOIN listing_metadata_versions AS lmv
              ON lmv.instrument_listing_id = il.id AND lmv.status = 'VERIFIED'
            WHERE il.instrument_id = ?
              AND (
                  UPPER(il.ticker) = UPPER(COALESCE(?, il.ticker))
                  OR EXISTS (
                      SELECT 1
                      FROM instrument_identifiers AS identifier
                      WHERE identifier.scheme = 'OPENFIGI_TICKER'
                        AND identifier.scope = 'LISTING'
                        AND identifier.listing_id = il.id
                        AND identifier.normalized_value = ?
                  )
              )
            ORDER BY il.id
            """,
            (instrument_id, candidate.ticker, candidate.ticker or ""),
        ).fetchall()
        rows = [
            row
            for row in rows
            if row["metadata_type"] in candidate.compatible_types()
        ]
        currency_mismatch = False
        if candidate.currency_hint and rows:
            currency_rows = [
                row
                for row in rows
                if str(row["currency"]).upper() == candidate.currency_hint
            ]
            currency_mismatch = not currency_rows
            rows = currency_rows
        if candidate.exchange_code and rows:
            exact_exchange = [
                row
                for row in rows
                if candidate.exchange_code
                in {
                    str(row["mic"] or "").upper(),
                    str(row["venue_name"] or "").upper(),
                }
            ]
            if exact_exchange:
                rows = exact_exchange
        if len(rows) != 1:
            return None, None, currency_mismatch, len(rows) > 1
        row = rows[0]
        metadata = connection.execute(
            "SELECT * FROM listing_metadata_versions WHERE id = ?",
            (row["metadata_id"],),
        ).fetchone()
        return row, metadata, currency_mismatch, False

    @staticmethod
    def _missing_metadata_reason(
        connection: sqlite3.Connection,
        instrument_id: int,
        candidate: OpenFigiCandidate,
    ) -> ResolutionReason:
        rows = connection.execute(
            """
            SELECT il.*
            FROM instrument_listings AS il
            WHERE il.instrument_id = ?
              AND UPPER(il.ticker) = UPPER(COALESCE(?, il.ticker))
            ORDER BY il.id
            """,
            (instrument_id, candidate.ticker),
        ).fetchall()
        if not rows:
            return "MISSING_CURRENCY"
        if any(not str(row["currency"] or "").strip() for row in rows):
            return "MISSING_CURRENCY"
        if any(not row["mic"] or not str(row["venue_name"] or "").strip() for row in rows):
            return "MISSING_VENUE"
        return "MISSING_TIMEZONE"

    @staticmethod
    def _require_accepted_entry(
        connection: sqlite3.Connection,
        catalog_entry_id: int,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT ce.*, cs.status AS snapshot_status, cs.retrieved_at,
                   i.instrument_type
            FROM catalog_entries AS ce
            JOIN catalog_snapshots AS cs ON cs.id = ce.snapshot_id
            JOIN instruments AS i ON i.id = ce.instrument_id
            WHERE ce.id = ?
            """,
            (catalog_entry_id,),
        ).fetchone()
        if row is None:
            raise CatalogResolutionError("CATALOG_ENTRY_NOT_FOUND")
        if row["snapshot_status"] != "COMPLETE":
            raise CatalogResolutionError("CATALOG_SNAPSHOT_NOT_COMPLETE")
        if row["parse_status"] != "ACCEPTED" or not row["isin"]:
            raise CatalogResolutionError("CATALOG_ENTRY_NOT_ACCEPTED")
        return row

    def _require_unique_candidate_case(
        self,
        connection: sqlite3.Connection,
        catalog_entry_id: int,
    ) -> sqlite3.Row:
        latest = self._latest_case(connection, catalog_entry_id)
        if (
            latest is None
            or int(latest["candidate_count"]) != 1
            or not latest["candidate_figi"]
            or latest["reason_code"] in {"TYPE_MISMATCH", "INVALID_PROVIDER_PAYLOAD"}
        ):
            raise ResolutionConflictError("OPENFIGI_CANDIDATE_NOT_UNIQUE")
        return latest

    @staticmethod
    def _normalize_metadata(payload: ListingMetadataPreviewIn) -> _NormalizedMetadata:
        ticker = "".join(payload.ticker.split()).upper()
        if not _TICKER_PATTERN.fullmatch(ticker):
            raise ValueError("ticker must be a supported normalized symbol")
        mic = "".join(payload.mic.split()).upper()
        if not _MIC_PATTERN.fullmatch(mic):
            raise ValueError("mic must be an ISO 10383 code")
        venue_name = " ".join(payload.venue_name.split())
        if not venue_name:
            raise ValueError("venue_name is required")
        currency = "".join(payload.currency.split()).upper()
        if currency not in _ISO_4217_CODES:
            raise ValueError("currency must be an ISO 4217 code")
        timezone = payload.timezone.strip()
        try:
            timezone = ZoneInfo(timezone).key
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be an IANA timezone") from None
        if payload.instrument_type == "UNKNOWN":
            raise ValueError("instrument_type must be verified")
        evidence_hash = payload.evidence_hash.strip().lower()
        if not _SHA256_PATTERN.fullmatch(evidence_hash):
            raise ValueError("evidence_hash must be SHA-256")
        return _NormalizedMetadata(
            ticker=ticker,
            mic=mic,
            venue_name=venue_name,
            currency=currency,
            timezone=timezone,
            instrument_type=payload.instrument_type,
            source=payload.source,
            observed_at=_timestamp(payload.observed_at),
            evidence_hash=evidence_hash,
        )

    def _validate_metadata_compatibility(
        self,
        entry: sqlite3.Row,
        candidate_case: sqlite3.Row,
        normalized: _NormalizedMetadata,
    ) -> None:
        if entry["isin"] and normalized.instrument_type in {"CRYPTO", "FX"}:
            raise ValueError("ISIN-backed instruments cannot be CRYPTO or FX")
        candidate = self._candidate_from_case(candidate_case)
        if normalized.instrument_type not in candidate.compatible_types():
            raise ValueError("instrument_type conflicts with OpenFIGI evidence")
        if entry["instrument_type"] not in {"UNKNOWN", normalized.instrument_type}:
            raise ValueError("instrument_type conflicts with canonical instrument")
        if (
            candidate.currency_hint
            and candidate.currency_hint != normalized.currency
        ):
            raise ValueError("currency conflicts with OpenFIGI compatibility hint")

    @staticmethod
    def _listing_state(
        connection: sqlite3.Connection,
        entry: sqlite3.Row,
        normalized: _NormalizedMetadata,
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        listings = connection.execute(
            """
            SELECT *
            FROM instrument_listings
            WHERE instrument_id = ?
              AND UPPER(ticker) = ?
              AND UPPER(mic) = ?
              AND UPPER(currency) = ?
            ORDER BY id
            """,
            (
                int(entry["instrument_id"]),
                normalized.ticker,
                normalized.mic,
                normalized.currency,
            ),
        ).fetchall()
        if len(listings) > 1:
            raise ResolutionConflictError("LISTING_IDENTITY_COLLISION")
        listing = listings[0] if listings else None
        current = None
        if listing is not None:
            current = connection.execute(
                """
                SELECT *
                FROM listing_metadata_versions
                WHERE instrument_listing_id = ? AND status = 'VERIFIED'
                """,
                (int(listing["id"]),),
            ).fetchone()
        return listing, current

    @staticmethod
    def _ensure_current_type_matches(
        current: sqlite3.Row,
        normalized: _NormalizedMetadata,
    ) -> None:
        if current["instrument_type"] != normalized.instrument_type:
            raise ResolutionConflictError("LISTING_METADATA_TYPE_CONFLICT")

    @staticmethod
    def _metadata_token(
        catalog_entry_id: int,
        instrument_id: int,
        normalized: _NormalizedMetadata,
        current_version: int | None,
    ) -> str:
        return _canonical_hash(
            {
                "catalog_entry_id": catalog_entry_id,
                "instrument_id": instrument_id,
                "listing_key": {
                    "ticker": normalized.ticker,
                    "mic": normalized.mic,
                    "currency": normalized.currency,
                },
                "venue_name": normalized.venue_name,
                "timezone": normalized.timezone,
                "instrument_type": normalized.instrument_type,
                "source": normalized.source,
                "observed_at": normalized.observed_at,
                "evidence_hash": normalized.evidence_hash,
                "current_version": current_version,
            }
        )

    def _idempotent_apply_result(
        self,
        connection: sqlite3.Connection,
        catalog_entry_id: int,
        listing: sqlite3.Row | None,
        current: sqlite3.Row | None,
        normalized: _NormalizedMetadata,
    ) -> ResolutionResult | None:
        if listing is None or current is None or not self._metadata_matches(current, normalized):
            return None
        attestation = connection.execute(
            """
            SELECT 1
            FROM catalog_listing_attestations
            WHERE catalog_entry_id = ?
              AND instrument_listing_id = ?
              AND listing_metadata_version_id = ?
              AND evidence_hash = ?
            """,
            (
                catalog_entry_id,
                int(listing["id"]),
                int(current["id"]),
                normalized.evidence_hash,
            ),
        ).fetchone()
        latest = self._latest_case(connection, catalog_entry_id)
        if (
            attestation is not None
            and latest is not None
            and latest["status"] == "RESOLVED"
            and latest["selected_listing_id"] == listing["id"]
        ):
            return _result_from_case(latest)
        return None

    @staticmethod
    def _metadata_matches(
        current: sqlite3.Row,
        normalized: _NormalizedMetadata,
    ) -> bool:
        return (
            current["venue_name"] == normalized.venue_name
            and current["timezone"] == normalized.timezone
            and current["instrument_type"] == normalized.instrument_type
            and current["source_code"] == normalized.source
            and current["observed_at"] == normalized.observed_at
            and current["evidence_hash"] == normalized.evidence_hash
        )

    @staticmethod
    def _create_or_update_listing(
        connection: sqlite3.Connection,
        entry: sqlite3.Row,
        listing: sqlite3.Row | None,
        normalized: _NormalizedMetadata,
    ) -> int:
        if listing is None:
            return int(
                connection.execute(
                    """
                    INSERT INTO instrument_listings (
                        instrument_id, ticker, mic, venue_name, currency, timezone,
                        listing_status, trade_republic_status, source, source_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', 'NEVER_SEEN', ?, ?)
                    """,
                    (
                        int(entry["instrument_id"]),
                        normalized.ticker,
                        normalized.mic,
                        normalized.venue_name,
                        normalized.currency,
                        normalized.timezone,
                        normalized.source,
                        normalized.observed_at[:10],
                    ),
                ).lastrowid
            )
        listing_id = int(listing["id"])
        connection.execute(
            """
            UPDATE instrument_listings
            SET venue_name = ?, timezone = ?, source = ?, source_date = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                normalized.venue_name,
                normalized.timezone,
                normalized.source,
                normalized.observed_at[:10],
                listing_id,
            ),
        )
        return listing_id

    @classmethod
    def _create_or_reuse_metadata_version(
        cls,
        connection: sqlite3.Connection,
        listing_id: int,
        current: sqlite3.Row | None,
        normalized: _NormalizedMetadata,
    ) -> int:
        if current is not None and cls._metadata_matches(current, normalized):
            return int(current["id"])
        supersedes = int(current["id"]) if current is not None else None
        next_version = int(current["version"]) + 1 if current is not None else 1
        if current is not None:
            connection.execute(
                "UPDATE listing_metadata_versions SET status = 'RETIRED' WHERE id = ?",
                (supersedes,),
            )
        return int(
            connection.execute(
                """
                INSERT INTO listing_metadata_versions (
                    instrument_listing_id, venue_name, timezone, instrument_type,
                    source_code, observed_at, evidence_hash, status, version,
                    supersedes_listing_metadata_version_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'VERIFIED', ?, ?)
                """,
                (
                    listing_id,
                    normalized.venue_name,
                    normalized.timezone,
                    normalized.instrument_type,
                    normalized.source,
                    normalized.observed_at,
                    normalized.evidence_hash,
                    next_version,
                    supersedes,
                ),
            ).lastrowid
        )

    def _save_resolved_identifiers(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        listing_id: int,
        candidate: OpenFigiCandidate,
        evidence_hash: str,
    ) -> None:
        figi_identifier = connection.execute(
            """
            SELECT id, instrument_id, scope
            FROM instrument_identifiers
            WHERE scheme = 'FIGI' AND normalized_value = ?
            """,
            (candidate.figi,),
        ).fetchone()
        if figi_identifier is None:
            figi_identifier_id = int(
                connection.execute(
                    """
                    INSERT INTO instrument_identifiers (
                        scheme, normalized_value, scope, instrument_id, listing_id
                    )
                    VALUES ('FIGI', ?, 'INSTRUMENT', ?, NULL)
                    """,
                    (candidate.figi, instrument_id),
                ).lastrowid
            )
        elif (
            figi_identifier["scope"] != "INSTRUMENT"
            or figi_identifier["instrument_id"] != instrument_id
        ):
            raise ResolutionConflictError("FIGI_IDENTITY_CONFLICT")
        else:
            figi_identifier_id = int(figi_identifier["id"])
        self._attest_identifier(
            connection,
            figi_identifier_id,
            evidence_hash,
        )

        if candidate.ticker:
            ticker_identifier = connection.execute(
                """
                SELECT id
                FROM instrument_identifiers
                WHERE scheme = 'OPENFIGI_TICKER'
                  AND normalized_value = ?
                  AND scope = 'LISTING'
                  AND listing_id = ?
                """,
                (candidate.ticker, listing_id),
            ).fetchone()
            if ticker_identifier is None:
                ticker_identifier_id = int(
                    connection.execute(
                        """
                        INSERT INTO instrument_identifiers (
                            scheme, normalized_value, scope, instrument_id, listing_id
                        )
                        VALUES ('OPENFIGI_TICKER', ?, 'LISTING', NULL, ?)
                        """,
                        (candidate.ticker, listing_id),
                    ).lastrowid
                )
            else:
                ticker_identifier_id = int(ticker_identifier["id"])
            self._attest_identifier(
                connection,
                ticker_identifier_id,
                evidence_hash,
            )

    def _attest_identifier(
        self,
        connection: sqlite3.Connection,
        identifier_id: int,
        evidence_hash: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO instrument_identifier_attestations (
                identifier_id, source, observed_at, evidence_hash
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(identifier_id, source, observed_at, evidence_hash) DO NOTHING
            """,
            (
                identifier_id,
                OPENFIGI_PROVIDER,
                _timestamp(self._clock()),
                evidence_hash,
            ),
        )
