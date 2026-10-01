from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.app.config import get_settings
from backend.app.data_providers.trade_republic_catalog import (
    CATALOG_MAX_RESPONSE_BYTES,
    CATALOG_PARSER_VERSION,
    TRADE_REPUBLIC_CATALOG_BASE_URL,
    TRADE_REPUBLIC_CATALOG_PATH,
    TRADE_REPUBLIC_CATALOG_URL,
    TRADE_REPUBLIC_SOURCE,
    CatalogParseError,
    ParsedCatalogRow,
    parse_trade_republic_pdf,
)
from backend.app.data_providers.transport import SafeProviderTransport, SafeProviderTransportError
from backend.app.models.market_data import EffectiveObservationQuality
from backend.app.models.schemas import (
    CatalogEodEnqueueResult,
    CatalogFailureReason,
    InstrumentDetailOut,
    InstrumentIdentifierOut,
    InstrumentListingOut,
    InstrumentListItem,
    InstrumentSearchOut,
    ResolutionStatus,
)
from backend.app.services.instrument_service import InstrumentService, parse_stored_utc
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.provider_budget_service import (
    ProviderBudgetExceeded,
    ProviderBudgetPolicy,
)

if TYPE_CHECKING:
    from backend.app.services.refresh_planner_service import RefreshPlannerService


@dataclass(frozen=True)
class CatalogIngestResult:
    snapshot_id: int
    content_sha256: str
    accepted: int
    rejected: int
    ambiguous: int
    unchanged: bool


class CatalogRefreshError(RuntimeError):
    def __init__(self, reason_code: CatalogFailureReason) -> None:
        self.reason_code = reason_code
        super().__init__(f"trade_republic_catalog:{reason_code}")


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _counts(rows: list[ParsedCatalogRow]) -> tuple[int, int, int]:
    return (
        sum(row.status == "ACCEPTED" for row in rows),
        sum(row.status == "REJECTED" for row in rows),
        sum(row.status == "AMBIGUOUS" for row in rows),
    )


def _result_for_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: int,
    content_sha256: str,
    *,
    unchanged: bool,
) -> CatalogIngestResult:
    counts = connection.execute(
        """
        SELECT
            SUM(CASE WHEN parse_status = 'ACCEPTED' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN parse_status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN parse_status = 'AMBIGUOUS' THEN 1 ELSE 0 END) AS ambiguous
        FROM catalog_entries
        WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    return CatalogIngestResult(
        snapshot_id=snapshot_id,
        content_sha256=content_sha256,
        accepted=int(counts["accepted"] or 0),
        rejected=int(counts["rejected"] or 0),
        ambiguous=int(counts["ambiguous"] or 0),
        unchanged=unchanged,
    )


def _record_failed_snapshot(
    connection: sqlite3.Connection,
    retrieved_at: datetime,
    reason_code: CatalogFailureReason,
    content_sha256: str | None,
) -> int:
    if connection.in_transaction:
        connection.rollback()
    connection.execute("BEGIN IMMEDIATE")
    try:
        snapshot_id = int(
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, source_date,
                    row_count, status, parser_version, failure_reason_code
                )
                VALUES (?, ?, ?, ?, NULL, 0, 'FAILED', ?, ?)
                """,
                (
                    TRADE_REPUBLIC_SOURCE,
                    TRADE_REPUBLIC_CATALOG_URL,
                    content_sha256,
                    _timestamp(retrieved_at),
                    CATALOG_PARSER_VERSION,
                    reason_code,
                ),
            ).lastrowid
        )
    except Exception:
        connection.rollback()
        raise
    connection.commit()
    return snapshot_id


def _instrument_for_row(
    connection: sqlite3.Connection,
    row: ParsedCatalogRow,
    retrieved_at: datetime,
) -> int:
    if row.isin is None or row.name is None:
        raise sqlite3.IntegrityError("accepted catalog row requires ISIN and name")
    identifier = connection.execute(
        """
        SELECT id, scope, instrument_id
        FROM instrument_identifiers
        WHERE scheme = 'ISIN' AND normalized_value = ?
        """,
        (row.isin,),
    ).fetchone()
    if identifier is None:
        instrument_id = int(
            connection.execute(
                """
                INSERT INTO instruments (
                    canonical_name, instrument_type, asset_class, quality_tier,
                    source, source_date
                )
                VALUES (?, 'UNKNOWN', 'UNKNOWN', 'REFERENCE_ONLY', ?, NULL)
                """,
                (row.name, TRADE_REPUBLIC_SOURCE),
            ).lastrowid
        )
        identifier_id = int(
            connection.execute(
                """
                INSERT INTO instrument_identifiers (
                    scheme, normalized_value, scope, instrument_id, listing_id
                )
                VALUES ('ISIN', ?, 'INSTRUMENT', ?, NULL)
                """,
                (row.isin, instrument_id),
            ).lastrowid
        )
    else:
        if identifier["scope"] != "INSTRUMENT" or identifier["instrument_id"] is None:
            raise sqlite3.IntegrityError("ISIN canonical identity has invalid ownership")
        identifier_id = int(identifier["id"])
        instrument_id = int(identifier["instrument_id"])

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
            TRADE_REPUBLIC_SOURCE,
            _timestamp(retrieved_at),
            row.raw_row_sha256,
        ),
    )
    return instrument_id


def ingest_trade_republic_catalog(
    connection: sqlite3.Connection,
    payload: bytes,
    retrieved_at: datetime,
) -> CatalogIngestResult:
    content_sha256 = hashlib.sha256(payload).hexdigest()
    try:
        rows = parse_trade_republic_pdf(payload)
    except CatalogParseError as exc:
        _record_failed_snapshot(connection, retrieved_at, exc.reason_code, content_sha256)
        raise CatalogRefreshError(exc.reason_code) from None
    if not rows:
        _record_failed_snapshot(connection, retrieved_at, "EMPTY_CATALOG", content_sha256)
        raise CatalogRefreshError("EMPTY_CATALOG")

    accepted, rejected, ambiguous = _counts(rows)
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            """
            SELECT id
            FROM catalog_snapshots
            WHERE source = ? AND content_sha256 = ? AND status = 'COMPLETE'
            """,
            (TRADE_REPUBLIC_SOURCE, content_sha256),
        ).fetchone()
        if existing is not None:
            result = _result_for_snapshot(
                connection,
                int(existing["id"]),
                content_sha256,
                unchanged=True,
            )
            connection.commit()
            return result

        snapshot_id = int(
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, source_date,
                    row_count, status, parser_version, failure_reason_code
                )
                VALUES (?, ?, ?, ?, NULL, ?, 'COMPLETE', ?, NULL)
                """,
                (
                    TRADE_REPUBLIC_SOURCE,
                    TRADE_REPUBLIC_CATALOG_URL,
                    content_sha256,
                    _timestamp(retrieved_at),
                    len(rows),
                    CATALOG_PARSER_VERSION,
                ),
            ).lastrowid
        )
        for row in rows:
            instrument_id = (
                _instrument_for_row(connection, row, retrieved_at)
                if row.status == "ACCEPTED"
                else None
            )
            connection.execute(
                """
                INSERT INTO catalog_entries (
                    snapshot_id, row_number, isin, name, parse_status,
                    reason_code, raw_row_sha256, instrument_id, listing_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    snapshot_id,
                    row.row_number,
                    row.isin,
                    row.name,
                    row.status,
                    row.reason_code,
                    row.raw_row_sha256,
                    instrument_id,
                ),
            )
    except Exception:
        connection.rollback()
        raise
    connection.commit()
    return CatalogIngestResult(
        snapshot_id=snapshot_id,
        content_sha256=content_sha256,
        accepted=accepted,
        rejected=rejected,
        ambiguous=ambiguous,
        unchanged=False,
    )


class CatalogService:
    def __init__(
        self,
        *,
        transport: SafeProviderTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport or SafeProviderTransport(
            allowed_hosts={"assets.traderepublic.com"}
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper or time.sleep

    def refresh(
        self,
        connection: sqlite3.Connection,
        *,
        force: bool = False,
        retrieved_at: datetime | None = None,
    ) -> CatalogIngestResult:
        instant = retrieved_at or self._clock()
        settings = get_settings()
        policy = ProviderBudgetPolicy(
            minute_limit=settings.trade_republic_catalog_minute_limit,
            daily_limit=settings.trade_republic_catalog_daily_limit,
            monthly_limit=settings.trade_republic_catalog_monthly_limit,
            max_attempts=settings.provider_default_max_attempts,
        )
        try:
            response = self._transport.request(
                connection=connection,
                policy=policy,
                provider=TRADE_REPUBLIC_SOURCE,
                method="GET",
                base_url=TRADE_REPUBLIC_CATALOG_BASE_URL,
                path=TRADE_REPUBLIC_CATALOG_PATH,
                headers={},
                params={},
                json_body=None,
                operation="CATALOG",
                cache_scope="official-it-pdf",
                cache_ttl_seconds=settings.trade_republic_catalog_cache_ttl_hours * 3600,
                max_response_bytes=CATALOG_MAX_RESPONSE_BYTES,
                decoder="bytes",
                now=instant,
                sleeper=self._sleeper,
                bypass_cache=force,
            )
        except (SafeProviderTransportError, ProviderBudgetExceeded) as exc:
            reason: CatalogFailureReason = (
                "PAYLOAD_TOO_LARGE"
                if isinstance(exc, SafeProviderTransportError) and exc.code == "RESPONSE_TOO_LARGE"
                else "DOWNLOAD_FAILED"
            )
            _record_failed_snapshot(connection, instant, reason, None)
            raise CatalogRefreshError(reason) from None
        if not isinstance(response.payload, bytes):
            _record_failed_snapshot(connection, instant, "DOWNLOAD_FAILED", None)
            raise CatalogRefreshError("DOWNLOAD_FAILED")
        return ingest_trade_republic_catalog(connection, response.payload, instant)


def enqueue_catalog_eod(
    connection: sqlite3.Connection,
    planner: RefreshPlannerService,
    *,
    after_listing_id: int,
    limit: int,
    now: datetime,
) -> CatalogEodEnqueueResult:
    """Accoda refresh EOD del catalogo per pagine keyset (mai OFFSET, mai scansioni complete).

    Esamina al massimo `limit` listing attivi con `id > after_listing_id`; accoda soltanto
    quelli con mapping provider EOD verificato e dati non freschi. `next_cursor` e l'ultimo
    listing esaminato, `None` quando la pagina non e piena.
    """
    from backend.app.data_providers.provider_registry import ProviderRegistry
    from backend.app.services.refresh_planner_service import MAX_REFRESH_BATCH

    if isinstance(limit, bool) or not 1 <= int(limit) <= MAX_REFRESH_BATCH:
        raise ValueError(f"La pagina del catalogo accetta da 1 a {MAX_REFRESH_BATCH} listing.")
    if int(after_listing_id) < 0:
        raise ValueError("Cursore del catalogo non valido.")
    rows = connection.execute(
        """
        SELECT id
        FROM instrument_listings
        WHERE id > ? AND listing_status = 'ACTIVE'
        ORDER BY id
        LIMIT ?
        """,
        (int(after_listing_id), int(limit)),
    ).fetchall()
    registry = ProviderRegistry(get_settings(), connection)
    enqueued = 0
    for row in rows:
        listing_id = int(row["id"])
        if not registry.providers_for(connection, listing_id, "EOD"):
            continue
        if planner.market_data_service._has_fresh_observation(connection, listing_id, "EOD", now):
            continue
        planner.enqueue(connection, listing_id, "EOD", "CATALOG_EOD", now, force=False)
        enqueued += 1
    next_cursor = int(rows[-1]["id"]) if len(rows) == int(limit) else None
    return CatalogEodEnqueueResult(enqueued=enqueued, next_cursor=next_cursor)


# Righe del catalogo: una per listing, oppure una sola riga senza listing per gli
# strumenti non ancora risolti. Lo stato TR di uno strumento senza listing deriva
# dalla presenza in uno snapshot COMPLETE del catalogo ufficiale (mai VERIFIED).
_CATALOG_ROWS_CTE = """
WITH catalog_presence AS (
    SELECT entry.instrument_id, MAX(snapshot.retrieved_at) AS cataloged_at
    FROM catalog_entries AS entry
    JOIN catalog_snapshots AS snapshot ON snapshot.id = entry.snapshot_id
    WHERE snapshot.source = ?
      AND snapshot.status = 'COMPLETE'
      AND entry.parse_status = 'ACCEPTED'
      AND entry.instrument_id IS NOT NULL
    GROUP BY entry.instrument_id
),
catalog_rows AS (
    SELECT instrument.id AS instrument_id,
           instrument.canonical_name,
           instrument.instrument_type,
           instrument.asset_class,
           instrument.quality_tier,
           instrument.quality_reason_code,
           listing.id AS listing_id,
           listing.ticker,
           listing.mic,
           listing.venue_name,
           listing.currency,
           listing.timezone,
           CASE
               WHEN listing.id IS NOT NULL THEN listing.trade_republic_status
               WHEN presence.cataloged_at IS NOT NULL THEN 'CATALOGED'
               ELSE 'NEVER_SEEN'
           END AS trade_republic_status,
           CASE
               WHEN listing.id IS NOT NULL THEN listing.trade_republic_cataloged_at
               ELSE presence.cataloged_at
           END AS trade_republic_cataloged_at,
           listing.trade_republic_verified_at
    FROM instruments AS instrument
    LEFT JOIN instrument_listings AS listing ON listing.instrument_id = instrument.id
    LEFT JOIN catalog_presence AS presence ON presence.instrument_id = instrument.id
)
"""
# Allowlist dei filtri: solo frammenti costanti, i valori viaggiano come parametri.
_SEARCH_FILTERS = {
    "asset_class": "catalog_rows.asset_class = ?",
    "instrument_type": "catalog_rows.instrument_type = ?",
    "currency": "UPPER(catalog_rows.currency) = ?",
    "mic": "UPPER(catalog_rows.mic) = ?",
    "quality_tier": "catalog_rows.quality_tier = ?",
    "trade_republic_status": "catalog_rows.trade_republic_status = ?",
}
# La sottoquery sugli identificativi non e correlata: SQLite la valuta una sola volta
# invece di scandire gli identificativi per ogni riga del catalogo.
_TEXT_FILTER = """(
    LOWER(catalog_rows.canonical_name) LIKE ? ESCAPE '\\'
    OR LOWER(COALESCE(catalog_rows.ticker, '')) LIKE ? ESCAPE '\\'
    OR catalog_rows.instrument_id IN (
        SELECT COALESCE(identifier.instrument_id, owner.instrument_id)
        FROM instrument_identifiers AS identifier
        LEFT JOIN instrument_listings AS owner ON owner.id = identifier.listing_id
        WHERE identifier.scheme IN ('ISIN', 'FIGI')
          AND identifier.normalized_value LIKE ? ESCAPE '\\'
    )
)"""
_CATALOG_ORDER = (
    "ORDER BY catalog_rows.canonical_name COLLATE NOCASE, "
    "catalog_rows.instrument_id, catalog_rows.listing_id"
)
_IDENTIFIER_ORDER = {"ISIN": 0, "FIGI": 1}


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _latest_catalog_snapshot_id(connection: sqlite3.Connection) -> int | None:
    row = connection.execute(
        """
        SELECT id
        FROM catalog_snapshots
        WHERE source = ? AND status = 'COMPLETE'
        ORDER BY retrieved_at DESC, id DESC
        LIMIT 1
        """,
        (TRADE_REPUBLIC_SOURCE,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


class _CatalogItemBuilder:
    """Arricchisce le righe con identificativo primario, tier e ultima observation."""

    def __init__(self, connection: sqlite3.Connection, now: datetime) -> None:
        self._connection = connection
        self._now = now
        self._primary: dict[int, sqlite3.Row | None] = {}
        self._reasons: dict[int, list[str]] = {}

    def item(self, row: sqlite3.Row) -> InstrumentListItem:
        instrument_id = int(row["instrument_id"])
        if instrument_id not in self._primary:
            self._primary[instrument_id] = InstrumentService.verified_primary_identifier(
                self._connection,
                instrument_id,
                str(row["instrument_type"]),
            )
        primary = self._primary[instrument_id]
        listing_id = int(row["listing_id"]) if row["listing_id"] is not None else None
        observation_quality, observed_at = self._observation(listing_id)
        return InstrumentListItem(
            instrument_id=instrument_id,
            canonical_name=row["canonical_name"],
            instrument_type=row["instrument_type"],
            asset_class=row["asset_class"],
            quality_tier=row["quality_tier"],
            quality_reasons=self._quality_reasons(instrument_id, row["quality_reason_code"]),
            primary_identifier_scheme=primary["scheme"] if primary is not None else None,
            primary_identifier=primary["normalized_value"] if primary is not None else None,
            listing_id=listing_id,
            ticker=row["ticker"],
            mic=row["mic"],
            venue_name=row["venue_name"],
            currency=row["currency"],
            timezone=row["timezone"],
            trade_republic_status=row["trade_republic_status"],
            trade_republic_cataloged_at=parse_stored_utc(row["trade_republic_cataloged_at"]),
            trade_republic_verified_at=parse_stored_utc(row["trade_republic_verified_at"]),
            observation_quality=observation_quality,
            observed_at=observed_at,
        )

    def _quality_reasons(self, instrument_id: int, fallback: object) -> list[str]:
        if instrument_id not in self._reasons:
            assessment = self._connection.execute(
                """
                SELECT reason_codes_json
                FROM quality_assessments
                WHERE instrument_id = ?
                ORDER BY assessed_at DESC, id DESC
                LIMIT 1
                """,
                (instrument_id,),
            ).fetchone()
            if assessment is not None:
                self._reasons[instrument_id] = [
                    str(reason) for reason in json.loads(assessment["reason_codes_json"])
                ]
            else:
                self._reasons[instrument_id] = [str(fallback)] if fallback else []
        return self._reasons[instrument_id]

    def _observation(
        self,
        listing_id: int | None,
    ) -> tuple[EffectiveObservationQuality | None, datetime | None]:
        if listing_id is None:
            return None, None
        row = self._connection.execute(
            """
            SELECT capability, source_quality, provider_observed_at
            FROM market_observations
            WHERE listing_id = ? AND capability IN ('EOD', 'QUOTE', 'FX', 'REFERENCE')
            ORDER BY provider_observed_at DESC, revision DESC, id DESC
            LIMIT 1
            """,
            (listing_id,),
        ).fetchone()
        observed_at = parse_stored_utc(row["provider_observed_at"]) if row is not None else None
        if row is None or observed_at is None:
            return None, None
        quality = MarketObservationService.effective_quality_for(
            str(row["capability"]),
            str(row["source_quality"]),
            observed_at,
            self._now,
        )
        return quality, observed_at


def search_instruments(
    connection: sqlite3.Connection,
    *,
    q: str | None,
    filters: Mapping[str, str | None],
    limit: int,
    offset: int,
    now: datetime,
) -> InstrumentSearchOut:
    """Ricerca paginata del catalogo: count e pagina nella stessa transazione di lettura."""
    if not 1 <= int(limit) <= 100 or int(offset) < 0:
        raise ValueError("Paginazione del catalogo non valida.")
    clauses: list[str] = []
    params: list[object] = [TRADE_REPUBLIC_SOURCE]
    text = (q or "").strip()
    if text:
        pattern = _like_pattern(text)
        clauses.append(_TEXT_FILTER)
        params.extend([pattern.lower(), pattern.lower(), pattern.upper()])
    for name, value in filters.items():
        if value is None:
            continue
        clauses.append(_SEARCH_FILTERS[name])
        params.append(value.strip().upper() if name in {"currency", "mic"} else value)
    where = " AND ".join(clauses) if clauses else "1 = 1"

    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN")
    try:
        total = int(
            connection.execute(
                f"{_CATALOG_ROWS_CTE} SELECT COUNT(*) AS total FROM catalog_rows WHERE {where}",
                params,
            ).fetchone()["total"]
        )
        rows = connection.execute(
            f"{_CATALOG_ROWS_CTE} SELECT * FROM catalog_rows WHERE {where} "
            f"{_CATALOG_ORDER} LIMIT ? OFFSET ?",
            [*params, int(limit), int(offset)],
        ).fetchall()
        builder = _CatalogItemBuilder(connection, now)
        items = [builder.item(row) for row in rows]
        snapshot_id = _latest_catalog_snapshot_id(connection)
    finally:
        if owns_transaction:
            connection.commit()
    return InstrumentSearchOut(
        items=items,
        total=total,
        limit=int(limit),
        offset=int(offset),
        catalog_snapshot_id=snapshot_id,
    )


def get_instrument_detail(
    connection: sqlite3.Connection,
    instrument_id: int,
    *,
    now: datetime,
) -> InstrumentDetailOut | None:
    """Dettaglio con identificativi attestati e tutti i listing, senza payload provider raw."""
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN")
    try:
        rows = connection.execute(
            f"{_CATALOG_ROWS_CTE} SELECT * FROM catalog_rows "
            "WHERE catalog_rows.instrument_id = ? ORDER BY catalog_rows.listing_id",
            (TRADE_REPUBLIC_SOURCE, int(instrument_id)),
        ).fetchall()
        if not rows:
            return None
        item = _CatalogItemBuilder(connection, now).item(rows[0])
        listings = [
            InstrumentListingOut(
                listing_id=int(row["listing_id"]),
                ticker=row["ticker"],
                mic=row["mic"],
                venue_name=row["venue_name"],
                currency=row["currency"],
                timezone=row["timezone"],
                resolution_status=_listing_resolution_status(
                    connection,
                    int(row["listing_id"]),
                    int(instrument_id),
                ),
                trade_republic_status=row["trade_republic_status"],
            )
            for row in rows
            if row["listing_id"] is not None
        ]
        identifiers = _instrument_identifiers(connection, int(instrument_id))
    finally:
        if owns_transaction:
            connection.commit()
    return InstrumentDetailOut(
        **item.model_dump(),
        identifiers=identifiers,
        listings=listings,
    )


def _listing_resolution_status(
    connection: sqlite3.Connection,
    listing_id: int,
    instrument_id: int,
) -> ResolutionStatus:
    if InstrumentService.resolved_listing(connection, listing_id) is not None:
        return "RESOLVED"
    latest = connection.execute(
        """
        SELECT resolution.status
        FROM instrument_resolution_cases AS resolution
        JOIN catalog_entries AS entry ON entry.id = resolution.catalog_entry_id
        WHERE entry.instrument_id = ?
        ORDER BY resolution.id DESC
        LIMIT 1
        """,
        (instrument_id,),
    ).fetchone()
    if latest is not None and latest["status"] != "RESOLVED":
        return latest["status"]
    return "UNMATCHED"


def _instrument_identifiers(
    connection: sqlite3.Connection,
    instrument_id: int,
) -> list[InstrumentIdentifierOut]:
    rows = connection.execute(
        """
        SELECT identifier.scheme, identifier.normalized_value, attestation.source,
               attestation.observed_at
        FROM instrument_identifiers AS identifier
        LEFT JOIN instrument_listings AS owner ON owner.id = identifier.listing_id
        JOIN instrument_identifier_attestations AS attestation
          ON attestation.identifier_id = identifier.id
        WHERE COALESCE(identifier.instrument_id, owner.instrument_id) = ?
        ORDER BY identifier.id, attestation.id
        """,
        (instrument_id,),
    ).fetchall()
    grouped: dict[tuple[str, str], tuple[set[str], list[datetime]]] = {}
    for row in rows:
        sources, observed = grouped.setdefault(
            (str(row["scheme"]), str(row["normalized_value"])),
            (set(), []),
        )
        sources.add(str(row["source"]))
        observed_at = parse_stored_utc(row["observed_at"])
        if observed_at is not None:
            observed.append(observed_at)
    return [
        InstrumentIdentifierOut(
            scheme=scheme,
            value=value,
            sources=sorted(sources),
            first_observed_at=min(observed),
            last_observed_at=max(observed),
        )
        for (scheme, value), (sources, observed) in sorted(
            grouped.items(),
            key=lambda entry: (_IDENTIFIER_ORDER.get(entry[0][0], 2), entry[0][0], entry[0][1]),
        )
        if observed
    ]
