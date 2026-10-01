from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
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
from backend.app.models.schemas import CatalogEodEnqueueResult, CatalogFailureReason
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
