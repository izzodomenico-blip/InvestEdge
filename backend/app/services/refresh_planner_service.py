from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from backend.app.config import get_settings
from backend.app.data_providers.base import (
    MissingApiKey,
    ProviderError,
    RateLimitExceeded,
    RealDataDisabled,
)
from backend.app.data_providers.coingecko import CoinGeckoProvider
from backend.app.data_providers.provider_registry import ProviderRegistry
from backend.app.data_providers.stooq import StooqProvider
from backend.app.services.market_data_service import MarketDataService

RefreshReason = Literal["POSITION", "STRATEGY_CANDIDATE", "WATCHLIST", "REQUESTED", "VIEWED", "CATALOG_EOD"]
RefreshState = Literal["PENDING", "RUNNING", "SUCCEEDED", "SKIPPED_FRESH", "BUDGET_DEFERRED", "FAILED"]
RefreshCapability = Literal["EOD", "QUOTE"]

REFRESH_PRIORITY: dict[str, int] = {
    "POSITION": 10,
    "STRATEGY_CANDIDATE": 20,
    "WATCHLIST": 30,
    "REQUESTED": 40,
    "VIEWED": 50,
    "CATALOG_EOD": 60,
}
MAX_REFRESH_BATCH = 25
_OPEN_STATES = ("PENDING", "BUDGET_DEFERRED")
_BUDGET_REASONS = frozenset({"RATE_LIMITED", "BUDGET_EXHAUSTED"})
_DEFAULT_DEFER = timedelta(minutes=1)
_CANDIDATE_SIGNALS = ("STRONG_BUY", "BUY")


@dataclass(frozen=True)
class RefreshBatchResult:
    selected: int
    succeeded: int
    skipped_fresh: int
    budget_deferred: int
    failed: int


@dataclass(frozen=True)
class RefreshOutcome:
    request_id: int
    listing_id: int
    symbol: str | None
    state: RefreshState
    provider: str | None
    rows_inserted: int
    rows_updated: int
    used_cache: bool
    reason_code: str | None
    message: str
    not_before: datetime | None = None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


class RefreshPlannerTransactionError(RuntimeError):
    pass


def _require_no_caller_transaction(connection: sqlite3.Connection) -> None:
    # Come il budget provider: mai commit di lavoro del chiamante non ancora confermato.
    if connection.in_transaction:
        raise RefreshPlannerTransactionError(
            "Il planner di refresh richiede una connessione senza transazioni in sospeso."
        )


@contextmanager
def _write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Transazione breve e propria: il lavoro lasciato aperto da un'unita viene prima
    reso durevole, cosi le chiamate provider successive partono senza transazione."""
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        connection.rollback()
        raise
    connection.commit()


class RefreshPlannerService:
    """Coda lazy di refresh: priorita esplicite, deduplica per listing/capability,
    batch limitato (1..25), skip dei dati freschi e rinvio senza consumo di budget."""

    def __init__(self, market_data_service: MarketDataService | None = None) -> None:
        self.market_data_service = market_data_service or MarketDataService()

    # --- coda -----------------------------------------------------------------

    def enqueue(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
        capability: RefreshCapability,
        reason: RefreshReason,
        requested_at: datetime,
        force: bool = False,
    ) -> int:
        _require_no_caller_transaction(connection)
        normalized_capability = str(capability).strip().upper()
        if normalized_capability not in {"EOD", "QUOTE"}:
            raise ValueError("Capability di refresh non supportata.")
        if reason not in REFRESH_PRIORITY:
            raise ValueError("Motivo di refresh non supportato.")
        priority = REFRESH_PRIORITY[reason]
        requested = _iso(requested_at)
        with _write_transaction(connection):
            existing = connection.execute(
                f"""
                SELECT id, reason, priority, requested_at, force
                FROM refresh_requests
                WHERE listing_id = ? AND capability = ?
                  AND state IN ({",".join("?" for _ in _OPEN_STATES)})
                """,
                (int(listing_id), normalized_capability, *_OPEN_STATES),
            ).fetchone()
            if existing is None:
                return int(
                    connection.execute(
                        """
                        INSERT INTO refresh_requests (
                            listing_id, capability, reason, priority, force, state, requested_at
                        )
                        VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                        """,
                        (int(listing_id), normalized_capability, reason, priority, int(bool(force)), requested),
                    ).lastrowid
                )
            better = priority < int(existing["priority"])
            connection.execute(
                """
                UPDATE refresh_requests
                SET reason = ?, priority = ?, requested_at = ?, force = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    reason if better else existing["reason"],
                    min(priority, int(existing["priority"])),
                    min(requested, str(existing["requested_at"])),
                    int(bool(existing["force"]) or bool(force)),
                    requested,
                    int(existing["id"]),
                ),
            )
            return int(existing["id"])

    # --- esecuzione -----------------------------------------------------------

    def run_batch(self, connection: sqlite3.Connection, limit: int, now: datetime) -> RefreshBatchResult:
        result, _outcomes = self.run_batch_detailed(connection, limit, now)
        return result

    def run_batch_detailed(
        self,
        connection: sqlite3.Connection,
        limit: int,
        now: datetime,
    ) -> tuple[RefreshBatchResult, list[RefreshOutcome]]:
        if isinstance(limit, bool) or not 1 <= int(limit) <= MAX_REFRESH_BATCH:
            raise ValueError(f"Il batch di refresh accetta da 1 a {MAX_REFRESH_BATCH} unita.")
        _require_no_caller_transaction(connection)
        claimed = self._claim(connection, int(limit), now)
        outcomes = [self._run_claimed(connection, request, now) for request in claimed]
        return self._summarize(outcomes), outcomes

    def run_request(self, connection: sqlite3.Connection, request_id: int, now: datetime) -> RefreshOutcome:
        _require_no_caller_transaction(connection)
        claimed = self._claim(connection, 1, now, request_id=int(request_id))
        if not claimed:
            raise ValueError("Richiesta di refresh non disponibile.")
        return self._run_claimed(connection, claimed[0], now)

    def _claim(
        self,
        connection: sqlite3.Connection,
        limit: int,
        now: datetime,
        request_id: int | None = None,
    ) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in _OPEN_STATES)
        with _write_transaction(connection):
            if request_id is None:
                rows = connection.execute(
                    f"""
                    SELECT *
                    FROM refresh_requests
                    WHERE state IN ({placeholders})
                      AND (not_before IS NULL OR not_before <= ?)
                    ORDER BY priority, requested_at, listing_id
                    LIMIT ?
                    """,
                    (*_OPEN_STATES, _iso(now), limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT * FROM refresh_requests WHERE id = ? AND state IN ({placeholders})",
                    (request_id, *_OPEN_STATES),
                ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE refresh_requests
                    SET state = 'RUNNING', attempts = attempts + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (_iso(now), int(row["id"])),
                )
        return rows

    def _run_claimed(self, connection: sqlite3.Connection, request: sqlite3.Row, now: datetime) -> RefreshOutcome:
        started_at = datetime.now(UTC)
        try:
            outcome = self._execute(connection, request, now)
        except Exception:
            outcome = self._outcome(request, "FAILED", None, "EXECUTION_FAILED", "Refresh non riuscito.")
        self._finish(connection, request, outcome, started_at)
        return outcome

    def _finish(
        self,
        connection: sqlite3.Connection,
        request: sqlite3.Row,
        outcome: RefreshOutcome,
        started_at: datetime,
    ) -> None:
        finished = datetime.now(UTC)
        with _write_transaction(connection):
            connection.execute(
                """
                UPDATE refresh_requests
                SET state = ?, not_before = ?, last_reason_code = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    outcome.state,
                    _iso(outcome.not_before) if outcome.not_before else None,
                    outcome.reason_code,
                    _iso(finished),
                    int(request["id"]),
                ),
            )
            connection.execute(
                """
                INSERT INTO refresh_runs (
                    request_id, started_at, finished_at, state, provider,
                    rows_inserted, rows_updated, used_cache, reason_code
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(request["id"]),
                    _iso(started_at),
                    _iso(finished),
                    outcome.state,
                    outcome.provider,
                    max(0, int(outcome.rows_inserted)),
                    max(0, int(outcome.rows_updated)),
                    int(bool(outcome.used_cache)),
                    outcome.reason_code,
                ),
            )

    def _execute(self, connection: sqlite3.Connection, request: sqlite3.Row, now: datetime) -> RefreshOutcome:
        listing_id = int(request["listing_id"])
        capability = str(request["capability"])
        force = bool(request["force"])
        listing = connection.execute(
            """
            SELECT listing.id, listing.ticker, listing.currency, listing.timezone, listing.listing_status,
                   instrument.instrument_type
            FROM instrument_listings AS listing
            JOIN instruments AS instrument ON instrument.id = listing.instrument_id
            WHERE listing.id = ?
            """,
            (listing_id,),
        ).fetchone()
        if listing is None or str(listing["listing_status"]) != "ACTIVE":
            return self._outcome(request, "FAILED", None, "LISTING_INACTIVE", "Listing non attivo.")

        if not force and self.market_data_service._has_fresh_observation(connection, listing_id, capability, now):
            return self._outcome(
                request, "SKIPPED_FRESH", None, None, "Dati gia aggiornati.", symbol=str(listing["ticker"])
            )

        registry = ProviderRegistry(get_settings(), connection)
        asset = self.market_data_service._asset_for_listing(connection, listing_id)
        if asset is not None:
            provider, _symbol, _capability = self.market_data_service.select_provider(connection, asset, registry)
        else:
            matches = registry.providers_for(connection, listing_id, capability)
            provider = registry.provider_named(matches[0].provider) if matches else None
        if provider is not None and get_settings().enable_real_data:
            deferred = self._budget_deferral(registry, provider.provider_name, request, now)
            if deferred is not None:
                return deferred

        if asset is not None:
            result = self.market_data_service.refresh_asset_row(connection, asset, force=force)
            return self._outcome_from_result(request, result)
        return self._refresh_unactivated_listing(connection, request, listing, registry, force, now)

    def _budget_deferral(
        self,
        registry: ProviderRegistry,
        provider_name: str,
        request: sqlite3.Row,
        now: datetime,
    ) -> RefreshOutcome | None:
        availability = registry.availability_for(provider_name)
        if availability.state != "COOLDOWN" and availability.reason_code not in _BUDGET_REASONS:
            return None
        not_before = availability.cooldown_until or (now + _DEFAULT_DEFER)
        return self._outcome(
            request,
            "BUDGET_DEFERRED",
            provider_name,
            availability.reason_code or "RATE_LIMITED",
            "Budget provider esaurito: aggiornamento rinviato.",
            not_before=not_before,
        )

    def _refresh_unactivated_listing(
        self,
        connection: sqlite3.Connection,
        request: sqlite3.Row,
        listing: sqlite3.Row,
        registry: ProviderRegistry,
        force: bool,
        now: datetime,
    ) -> RefreshOutcome:
        """Listing del catalogo senza asset attivo: solo osservazioni, nessuna proiezione su asset."""
        capability = str(request["capability"])
        matches = registry.providers_for(connection, int(listing["id"]), capability)
        if not matches:
            return self._outcome(request, "FAILED", None, "NO_PROVIDER_MAPPING", "Nessun mapping provider verificato.")
        match = matches[0]
        provider = registry.provider_named(match.provider)
        listing_payload = {
            "id": int(listing["id"]),
            "timezone": listing["timezone"],
            "currency": listing["currency"],
            "instrument_type": listing["instrument_type"],
            "provider_symbol": match.provider_symbol,
            "coingecko_id": match.provider_symbol,
            "session": "24X7",
        }
        try:
            if isinstance(provider, StooqProvider) and capability == "EOD":
                envelopes = provider.fetch_observations(listing_payload, None, None, bypass_cache=force)
            elif isinstance(provider, CoinGeckoProvider) and capability == "EOD":
                envelopes = provider.fetch_daily(listing_payload, 365, bypass_cache=force)
            else:
                return self._outcome(
                    request, "FAILED", match.provider, "UNSUPPORTED_CAPABILITY", "Capability non supportata."
                )
        except RateLimitExceeded:
            return self._outcome(
                request,
                "BUDGET_DEFERRED",
                match.provider,
                "RATE_LIMITED",
                "Budget provider esaurito: aggiornamento rinviato.",
                not_before=now + _DEFAULT_DEFER,
            )
        except (MissingApiKey, RealDataDisabled, ProviderError, ValueError, KeyError):
            return self._outcome(request, "FAILED", match.provider, "PROVIDER_FAILED", "Provider non disponibile.")
        ingest = self.market_data_service.observation_service.ingest_batch(connection, envelopes, now)
        if ingest.accepted == 0 and ingest.duplicates == 0:
            return self._outcome(request, "FAILED", match.provider, "NO_VALID_DATA", "Nessun dato valido.")
        return self._outcome(
            request,
            "SUCCEEDED",
            match.provider,
            None,
            "Osservazioni aggiornate.",
            used_cache=bool(getattr(provider, "last_fetch_used_cache", False)),
        )

    # --- refresh-all compatibile ---------------------------------------------

    def refresh_watchlist(
        self,
        connection: sqlite3.Connection,
        *,
        limit: int | None,
        force: bool,
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Accoda posizioni, candidati da segnali e watchlist attiva (mai il catalogo),
        esegue un batch limitato e restituisce risultati nel formato `DataRefreshResultOut`."""
        effective = get_settings().refresh_batch_default_limit if limit is None else int(limit)
        effective = max(1, min(effective, MAX_REFRESH_BATCH))
        for reason, listing_id in self._watchlist_units(connection):
            self.enqueue(connection, listing_id, "EOD", reason, now, force=force)  # type: ignore[arg-type]
        _result, outcomes = self.run_batch_detailed(connection, effective, now)
        return [self.legacy_result(connection, outcome) for outcome in outcomes]

    def preview_watchlist(self, connection: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
        """Anteprima in sola lettura: unita che un refresh-all accoderebbe, in ordine di priorita."""
        if isinstance(limit, bool) or not 1 <= int(limit) <= MAX_REFRESH_BATCH:
            raise ValueError(f"L'anteprima accetta da 1 a {MAX_REFRESH_BATCH} unita.")
        best: dict[int, str] = {}
        for reason, listing_id in self._watchlist_units(connection):
            current = best.get(listing_id)
            if current is None or REFRESH_PRIORITY[reason] < REFRESH_PRIORITY[current]:
                best[listing_id] = reason
        ordered = sorted(best.items(), key=lambda item: (REFRESH_PRIORITY[item[1]], item[0]))[: int(limit)]
        preview: list[dict[str, Any]] = []
        for listing_id, reason in ordered:
            asset = self.market_data_service._asset_for_listing(connection, listing_id)
            preview.append(
                {
                    "listing_id": listing_id,
                    "symbol": str(asset["symbol"]) if asset is not None else None,
                    "reason": reason,
                    "priority": REFRESH_PRIORITY[reason],
                }
            )
        return preview

    @staticmethod
    def _watchlist_units(connection: sqlite3.Connection) -> list[tuple[str, int]]:
        """Posizioni, candidati da segnali esistenti e watchlist attiva: mai il catalogo."""
        units: list[tuple[str, int]] = []
        queries: list[tuple[str, str, tuple[Any, ...]]] = [
            (
                "POSITION",
                """
                SELECT DISTINCT asset.instrument_listing_id AS listing_id
                FROM portfolio_positions AS position
                JOIN assets AS asset ON asset.id = position.asset_id
                WHERE position.quantity != 0 AND asset.instrument_listing_id IS NOT NULL
                """,
                (),
            ),
            (
                "STRATEGY_CANDIDATE",
                f"""
                SELECT DISTINCT asset.instrument_listing_id AS listing_id
                FROM signals AS signal
                JOIN assets AS asset ON asset.id = signal.asset_id
                WHERE signal.signal IN ({",".join("?" for _ in _CANDIDATE_SIGNALS)})
                  AND asset.instrument_listing_id IS NOT NULL
                  AND signal.id = (
                      SELECT latest.id FROM signals AS latest
                      WHERE latest.asset_id = signal.asset_id
                      ORDER BY latest.created_at DESC, latest.id DESC
                      LIMIT 1
                  )
                """,
                _CANDIDATE_SIGNALS,
            ),
            (
                "WATCHLIST",
                """
                SELECT DISTINCT instrument_listing_id AS listing_id
                FROM assets
                WHERE instrument_listing_id IS NOT NULL
                """,
                (),
            ),
        ]
        for reason, query, params in queries:
            units.extend((reason, int(row["listing_id"])) for row in connection.execute(query, params).fetchall())
        return units

    def legacy_result(
        self,
        connection: sqlite3.Connection,
        outcome: RefreshOutcome,
        *,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """Esito planner nel formato `DataRefreshResultOut` (deferred/failed = fallback)."""
        symbol = symbol or outcome.symbol
        if symbol is None:
            asset = self.market_data_service._asset_for_listing(connection, outcome.listing_id)
            symbol = str(asset["symbol"]) if asset is not None else f"listing:{outcome.listing_id}"
        return {
            "symbol": symbol,
            "provider": outcome.provider,
            "rows_inserted": int(outcome.rows_inserted),
            "rows_updated": int(outcome.rows_updated),
            "used_cache": bool(outcome.used_cache),
            "used_fallback": outcome.state not in {"SUCCEEDED", "SKIPPED_FRESH"},
            "message": outcome.message,
        }

    # --- helper ---------------------------------------------------------------

    def _outcome_from_result(self, request: sqlite3.Row, result: dict[str, Any]) -> RefreshOutcome:
        used_fallback = bool(result.get("used_fallback", True))
        return RefreshOutcome(
            request_id=int(request["id"]),
            listing_id=int(request["listing_id"]),
            symbol=str(result.get("symbol")) if result.get("symbol") else None,
            state="FAILED" if used_fallback else "SUCCEEDED",
            provider=result.get("provider"),
            rows_inserted=int(result.get("rows_inserted") or 0),
            rows_updated=int(result.get("rows_updated") or 0),
            used_cache=bool(result.get("used_cache")),
            reason_code="PROVIDER_FALLBACK" if used_fallback else None,
            message=str(result.get("message") or ""),
        )

    @staticmethod
    def _outcome(
        request: sqlite3.Row,
        state: RefreshState,
        provider: str | None,
        reason_code: str | None,
        message: str,
        *,
        symbol: str | None = None,
        used_cache: bool = False,
        not_before: datetime | None = None,
    ) -> RefreshOutcome:
        return RefreshOutcome(
            request_id=int(request["id"]),
            listing_id=int(request["listing_id"]),
            symbol=symbol,
            state=state,
            provider=provider,
            rows_inserted=0,
            rows_updated=0,
            used_cache=used_cache,
            reason_code=reason_code,
            message=message,
            not_before=not_before,
        )

    @staticmethod
    def _summarize(outcomes: list[RefreshOutcome]) -> RefreshBatchResult:
        return RefreshBatchResult(
            selected=len(outcomes),
            succeeded=sum(1 for item in outcomes if item.state == "SUCCEEDED"),
            skipped_fresh=sum(1 for item in outcomes if item.state == "SKIPPED_FRESH"),
            budget_deferred=sum(1 for item in outcomes if item.state == "BUDGET_DEFERRED"),
            failed=sum(1 for item in outcomes if item.state == "FAILED"),
        )
