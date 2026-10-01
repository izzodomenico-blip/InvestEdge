"""Metriche misurabili di copertura dati.

Tutte le letture usano la stessa connessione, la stessa transazione e lo stesso
`measured_at`: nessuna chiamata provider e nessuna scrittura. Ogni percentuale ha un
denominatore esplicito e vale 0.0 quando il denominatore e zero; le partizioni sono
verificate prima di restituire l'output.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, get_args

from backend.app.config import Settings, get_settings
from backend.app.data_providers.base import BaseMarketDataProvider
from backend.app.data_providers.coingecko import CoinGeckoProvider
from backend.app.data_providers.finnhub_quote import FinnhubQuoteProvider
from backend.app.data_providers.provider_registry import ProviderRegistry
from backend.app.data_providers.trade_republic_catalog import TRADE_REPUBLIC_SOURCE
from backend.app.models.market_data import EffectiveObservationQuality
from backend.app.models.schemas import (
    CoverageCount,
    DataCoverageOut,
    DataCoverageSummaryOut,
    FxCoverageOut,
    ProviderCoverageOut,
    QualityTier,
)
from backend.app.services.instrument_service import _PROVIDER_INSTRUMENT_TYPES, parse_stored_utc
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.provider_budget_service import (
    BudgetWindow,
    ProviderBudgetManager,
    ProviderBudgetPolicy,
    ProviderCapability,
    _policy_limits,
    _window_values,
)

# Coppie provider/capability mappabili su listing, con le regole di ProviderRegistry.providers_for.
# FX resta separato (fx_rates) e NEWS non produce observation di mercato.
PROVIDER_COVERAGE_PAIRS: tuple[tuple[str, ProviderCapability], ...] = (
    ("coingecko", "EOD"),
    ("coingecko", "QUOTE"),
    ("finnhub", "QUOTE"),
    ("stooq", "EOD"),
)
_QUALITY_TIERS: tuple[QualityTier, ...] = get_args(QualityTier)
_EFFECTIVE_QUALITIES: tuple[str, ...] = get_args(EffectiveObservationQuality)
_TRADE_REPUBLIC_BUCKETS = ("UNRESOLVED_IDENTITY", "NEVER_SEEN", "CATALOGED", "VERIFIED", "UNAVAILABLE")
_RESOLUTION_REJECTIONS = frozenset({"AMBIGUOUS", "UNMATCHED", "REJECTED"})
# Ritardo all'ingestione (`delay_seconds`), estremo superiore incluso.
_DELAY_BUCKETS: tuple[tuple[str, int | None], ...] = (
    ("0-5m", 5 * 60),
    ("5-30m", 30 * 60),
    ("30m-24h", 24 * 3600),
    ("1-4d", 4 * 24 * 3600),
    (">4d", None),
)
_BUDGET_WINDOWS: tuple[BudgetWindow, ...] = ("MINUTE", "DAY", "MONTH")
_UNRESOLVED_MARKET = "UNRESOLVED"
_UNKNOWN_ASSET_CLASS = "UNKNOWN"
_STATUS_CAPABILITIES: dict[str, tuple[ProviderCapability, ...]] = {
    "stooq": ("EOD",),
    "finnhub": ("QUOTE",),
    "alpha_vantage": ("EOD",),
    "yahoo_finance": ("EOD",),
    "coingecko": ("EOD", "QUOTE"),
    "fred": ("REFERENCE",),
}

# Ultimo case per entry ACCEPTED dello snapshot (finestra deterministica su id), una riga
# aggregata per combinazione: il catalogo e contato una volta per catalog_entry.
_CATALOG_SQL = """
WITH ranked_cases AS (
    SELECT resolution.catalog_entry_id,
           resolution.status,
           resolution.reason_code,
           resolution.selected_listing_id,
           ROW_NUMBER() OVER (
               PARTITION BY resolution.catalog_entry_id
               ORDER BY resolution.id DESC
           ) AS case_rank
    FROM catalog_entries AS entry
    JOIN instrument_resolution_cases AS resolution
      ON resolution.catalog_entry_id = entry.id
    WHERE entry.snapshot_id = ? AND entry.parse_status = 'ACCEPTED'
),
latest_cases AS (
    SELECT * FROM ranked_cases WHERE case_rank = 1
)
SELECT entry.parse_status,
       entry.reason_code AS parse_reason,
       CASE
           WHEN entry.parse_status != 'ACCEPTED' THEN NULL
           WHEN latest.status IS NULL THEN 'UNPROCESSED'
           ELSE latest.status
       END AS resolution_bucket,
       latest.reason_code AS resolution_reason,
       instrument.asset_class,
       instrument.quality_tier,
       CASE WHEN latest.status = 'RESOLVED' THEN listing.mic END AS mic,
       CASE WHEN latest.status = 'RESOLVED' THEN listing.trade_republic_status END AS trade_republic_status,
       COUNT(*) AS entries
FROM catalog_entries AS entry
LEFT JOIN latest_cases AS latest ON latest.catalog_entry_id = entry.id
LEFT JOIN instruments AS instrument ON instrument.id = entry.instrument_id
LEFT JOIN instrument_listings AS listing ON listing.id = latest.selected_listing_id
WHERE entry.snapshot_id = ?
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
ORDER BY 1, 2, 3, 4, 5, 6, 7, 8
"""
# Listing risolti come InstrumentService.resolved_listing (metadata VERIFIED + case RESOLVED),
# con sottoquery non correlate: nessuna scansione per riga del catalogo.
_RESOLVED_LISTINGS_SQL = """
SELECT listing.id AS listing_id, listing.mic, listing.currency, instrument.instrument_type
FROM instrument_listings AS listing
JOIN instruments AS instrument ON instrument.id = listing.instrument_id
WHERE listing.listing_status = 'ACTIVE'
  AND listing.id IN (
      SELECT metadata.instrument_listing_id
      FROM listing_metadata_versions AS metadata
      WHERE metadata.status = 'VERIFIED'
  )
  AND listing.id IN (
      SELECT resolution.selected_listing_id
      FROM instrument_resolution_cases AS resolution
      WHERE resolution.status = 'RESOLVED' AND resolution.selected_listing_id IS NOT NULL
  )
ORDER BY listing.id
"""
_LATEST_OBSERVATION_SQL = """
SELECT provider_observed_at, ingested_at, delay_seconds, source_quality
FROM market_observations
WHERE listing_id = ? AND capability = ? AND provider = ?
ORDER BY provider_observed_at DESC, revision DESC, id DESC
LIMIT 1
"""


class CoverageInvariantError(RuntimeError):
    """Una partizione non somma al proprio denominatore: l'output non viene restituito."""

    def __init__(self, invariant: str) -> None:
        self.invariant = invariant
        super().__init__(f"coverage invariant failed: {invariant}")


@dataclass(frozen=True)
class _ResolvedListing:
    listing_id: int
    mic: str
    currency: str
    instrument_type: str


@dataclass
class _CountBucket:
    total: int = 0
    resolved: int = 0
    qualified: int = 0
    observable: int = 0
    reference_only: int = 0

    def add(self, entries: int, resolved: bool, tier: object) -> None:
        self.total += entries
        if resolved:
            self.resolved += entries
        if tier == "QUALIFIED":
            self.qualified += entries
        elif tier == "OBSERVABLE":
            self.observable += entries
        elif tier == "REFERENCE_ONLY":
            self.reference_only += entries

    def out(self, key: str) -> CoverageCount:
        return CoverageCount(
            key=key,
            total=self.total,
            resolved=self.resolved,
            qualified=self.qualified,
            observable=self.observable,
            reference_only=self.reference_only,
        )


def _percent(count: int, denominator: int) -> float:
    return round(count * 100 / denominator, 2) if denominator else 0.0


def _stored_utc(value: object) -> datetime | None:
    try:
        return parse_stored_utc(value)
    except ValueError:
        return None


def _latest(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


def _delay_bucket(delay_seconds: int) -> str:
    for name, upper in _DELAY_BUCKETS:
        if upper is None or delay_seconds <= upper:
            return name
    return _DELAY_BUCKETS[-1][0]


def _fx_is_stale(observed_at: str, moment: datetime, max_age_days: int) -> bool:
    """Stessa soglia di `FXService._is_stale`, valutata al momento della misura."""
    try:
        observed_date = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).date()
    except ValueError:
        return True
    return (moment.date() - observed_date).days > max_age_days


def _eligible(provider: str, listing: _ResolvedListing) -> bool:
    if listing.instrument_type not in _PROVIDER_INSTRUMENT_TYPES[provider]:
        return False
    if provider == "finnhub":
        return listing.mic in FinnhubQuoteProvider.supported_mics
    if provider == "coingecko":
        return listing.currency in CoinGeckoProvider.supported_quote_currencies
    return True


def verify_coverage_invariants(coverage: DataCoverageOut) -> None:
    """Ogni partizione deve sommare esattamente al proprio denominatore."""
    checks: list[tuple[str, int, int]] = [
        (
            "parse_partition",
            coverage.parse_accepted_entries + coverage.parse_ambiguous_entries + coverage.parse_rejected_entries,
            coverage.parse_denominator,
        ),
        (
            "resolution_partition",
            coverage.resolution_resolved_entries
            + coverage.resolution_ambiguous_entries
            + coverage.resolution_unmatched_entries
            + coverage.resolution_rejected_entries
            + coverage.resolution_unprocessed_entries,
            coverage.resolution_denominator,
        ),
        ("resolution_denominator", coverage.resolution_denominator, coverage.parse_accepted_entries),
        ("tier_partition", sum(coverage.tier_counts.values()), coverage.tier_denominator),
        (
            "trade_republic_partition",
            sum(coverage.trade_republic_status_counts.values()),
            coverage.trade_republic_denominator,
        ),
        ("trade_republic_denominator", coverage.trade_republic_denominator, coverage.parse_accepted_entries),
        ("asset_class_partition", sum(item.total for item in coverage.by_asset_class), coverage.parse_accepted_entries),
        ("market_partition", sum(item.total for item in coverage.by_market), coverage.parse_accepted_entries),
        (
            "fx_partition",
            coverage.fx_fresh_currencies + coverage.fx_stale_currencies + coverage.fx_missing_currencies,
            coverage.fx_currency_denominator,
        ),
        ("fx_items", len(coverage.fx_coverage), coverage.fx_currency_denominator),
    ]
    for item in coverage.provider_coverage:
        scope = f"provider_partition:{item.provider}:{item.capability}"
        observed = item.fresh_listings + item.stale_listings
        checks.extend(
            [
                (f"{scope}:mapping", item.unmapped_listings + item.mapped_listings, item.eligible_listings),
                (f"{scope}:freshness", observed + item.missing_observation_listings, item.mapped_listings),
                (f"{scope}:quality", sum(item.quality_counts.values()), observed),
                (f"{scope}:delay", sum(item.delay_bucket_counts.values()), observed),
            ]
        )
    for name, actual, expected in checks:
        if actual != expected:
            raise CoverageInvariantError(name)


class DataCoverageService:
    """Misura catalogo, resolution, tier, stato TR, provider, FX e coda sul database locale."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def measure(self, connection: sqlite3.Connection, measured_at: datetime) -> DataCoverageOut:
        if measured_at.tzinfo is None or measured_at.utcoffset() is None:
            raise ValueError("measured_at deve avere un fuso orario esplicito.")
        moment = measured_at.astimezone(UTC)
        settings = self._settings or get_settings()
        owns_transaction = not connection.in_transaction
        if owns_transaction:
            connection.execute("BEGIN")
        try:
            values = self._catalog(connection)
            resolved = self._resolved_listings(connection)
            values["provider_coverage"] = self._providers(connection, resolved, moment, settings)
            values.update(self._fx(connection, resolved, moment, settings))
            values.update(self._queue(connection))
        finally:
            if owns_transaction:
                connection.commit()
        coverage = DataCoverageOut(measured_at=moment, **values)
        verify_coverage_invariants(coverage)
        return coverage

    def summary(self, connection: sqlite3.Connection, measured_at: datetime) -> DataCoverageSummaryOut:
        coverage = self.measure(connection, measured_at)
        return DataCoverageSummaryOut(**coverage.model_dump(include=set(DataCoverageSummaryOut.model_fields)))

    # --- catalogo -------------------------------------------------------------

    @staticmethod
    def _catalog(connection: sqlite3.Connection) -> dict[str, Any]:
        snapshot = connection.execute(
            """
            SELECT id, retrieved_at, content_sha256
            FROM catalog_snapshots
            WHERE source = ? AND status = 'COMPLETE'
            ORDER BY retrieved_at DESC, id DESC
            LIMIT 1
            """,
            (TRADE_REPUBLIC_SOURCE,),
        ).fetchone()
        snapshot_id = int(snapshot["id"]) if snapshot is not None else None
        rows = (
            connection.execute(_CATALOG_SQL, (snapshot_id, snapshot_id)).fetchall()
            if snapshot_id is not None
            else []
        )
        tier_rows = (
            connection.execute(
                """
                SELECT instrument.quality_tier, COUNT(DISTINCT instrument.id) AS instruments
                FROM catalog_entries AS entry
                JOIN instruments AS instrument ON instrument.id = entry.instrument_id
                WHERE entry.snapshot_id = ? AND entry.parse_status = 'ACCEPTED'
                GROUP BY instrument.quality_tier
                """,
                (snapshot_id,),
            ).fetchall()
            if snapshot_id is not None
            else []
        )
        tier_denominator = (
            int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT instrument.id)
                    FROM catalog_entries AS entry
                    JOIN instruments AS instrument ON instrument.id = entry.instrument_id
                    WHERE entry.snapshot_id = ? AND entry.parse_status = 'ACCEPTED'
                    """,
                    (snapshot_id,),
                ).fetchone()[0]
            )
            if snapshot_id is not None
            else 0
        )

        parse: Counter[str] = Counter()
        resolution: Counter[str] = Counter()
        trade_republic: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        by_class: dict[str, _CountBucket] = {}
        by_market: dict[str, _CountBucket] = {}
        for row in rows:
            entries = int(row["entries"])
            parse_status = str(row["parse_status"])
            parse[parse_status] += entries
            if parse_status != "ACCEPTED":
                reasons[f"PARSE:{row['parse_reason']}"] += entries
                continue
            bucket = str(row["resolution_bucket"])
            resolution[bucket] += entries
            if bucket in _RESOLUTION_REJECTIONS:
                reasons[f"RESOLUTION:{row['resolution_reason']}"] += entries
            resolved = bucket == "RESOLVED"
            status = row["trade_republic_status"]
            # Gli irrisolti restano nel denominatore TR invece di sparire.
            trade_republic[str(status) if resolved and status else "UNRESOLVED_IDENTITY"] += entries
            tier = row["quality_tier"]
            asset_class = str(row["asset_class"] or _UNKNOWN_ASSET_CLASS)
            by_class.setdefault(asset_class, _CountBucket()).add(entries, resolved, tier)
            mic = str(row["mic"] or "").strip().upper()
            market = mic if resolved and mic else _UNRESOLVED_MARKET
            by_market.setdefault(market, _CountBucket()).add(entries, resolved, tier)

        accepted = parse["ACCEPTED"]
        tiers = {str(row["quality_tier"]): int(row["instruments"]) for row in tier_rows}
        tier_counts = {tier: tiers.get(tier, 0) for tier in _QUALITY_TIERS}
        return {
            "latest_catalog_snapshot_id": snapshot_id,
            "latest_catalog_retrieved_at": _stored_utc(snapshot["retrieved_at"]) if snapshot is not None else None,
            "latest_catalog_sha256": snapshot["content_sha256"] if snapshot is not None else None,
            "parse_accepted_entries": accepted,
            "parse_ambiguous_entries": parse["AMBIGUOUS"],
            "parse_rejected_entries": parse["REJECTED"],
            "parse_denominator": sum(parse.values()),
            "resolution_resolved_entries": resolution["RESOLVED"],
            "resolution_ambiguous_entries": resolution["AMBIGUOUS"],
            "resolution_unmatched_entries": resolution["UNMATCHED"],
            "resolution_rejected_entries": resolution["REJECTED"],
            "resolution_unprocessed_entries": resolution["UNPROCESSED"],
            "resolution_denominator": accepted,
            "resolved_percent": _percent(resolution["RESOLVED"], accepted),
            "tier_denominator": tier_denominator,
            "tier_counts": tier_counts,
            "tier_percentages": {tier: _percent(count, tier_denominator) for tier, count in tier_counts.items()},
            "trade_republic_denominator": accepted,
            "trade_republic_status_counts": {bucket: trade_republic[bucket] for bucket in _TRADE_REPUBLIC_BUCKETS},
            "trade_republic_verified_percent": _percent(trade_republic["VERIFIED"], accepted),
            "by_asset_class": [bucket.out(key) for key, bucket in sorted(by_class.items())],
            "by_market": [bucket.out(key) for key, bucket in sorted(by_market.items())],
            "rejection_reasons": dict(sorted(reasons.items())),
        }

    # --- provider -------------------------------------------------------------

    @staticmethod
    def _resolved_listings(connection: sqlite3.Connection) -> list[_ResolvedListing]:
        return [
            _ResolvedListing(
                listing_id=int(row["listing_id"]),
                mic=str(row["mic"] or "").strip().upper(),
                currency=str(row["currency"] or "").strip().upper(),
                instrument_type=str(row["instrument_type"]).strip().upper(),
            )
            for row in connection.execute(_RESOLVED_LISTINGS_SQL).fetchall()
        ]

    def _providers(
        self,
        connection: sqlite3.Connection,
        resolved: list[_ResolvedListing],
        moment: datetime,
        settings: Settings,
    ) -> list[ProviderCoverageOut]:
        registry = ProviderRegistry(settings, connection)
        verified = {
            (str(row["provider"]).strip().lower(), str(row["capability"]).strip().upper(), int(row["listing_id"]))
            for row in connection.execute(
                "SELECT provider, capability, listing_id FROM provider_symbols WHERE status = 'VERIFIED'"
            ).fetchall()
        }
        # Rejection correnti: non ancora risolte da un'observation valida successiva.
        open_rejections: Counter[tuple[str, str, int]] = Counter()
        for row in connection.execute(
            """
            SELECT rejection.provider, rejection.capability, rejection.listing_id, COUNT(*) AS rejections
            FROM market_data_rejections AS rejection
            WHERE NOT EXISTS (
                SELECT 1
                FROM market_data_rejection_resolutions AS resolution
                WHERE resolution.rejection_id = rejection.id
            )
            GROUP BY rejection.provider, rejection.capability, rejection.listing_id
            """
        ).fetchall():
            key = (str(row["provider"]).strip().lower(), str(row["capability"]).strip().upper(), int(row["listing_id"]))
            open_rejections[key] += int(row["rejections"])

        coverage: list[ProviderCoverageOut] = []
        for provider, capability in PROVIDER_COVERAGE_PAIRS:
            eligible = [listing for listing in resolved if _eligible(provider, listing)]
            mapped = [
                listing
                for listing in eligible
                if (provider, capability, listing.listing_id) in verified
                or (
                    provider == "coingecko"
                    and any(
                        match.provider == "coingecko"
                        for match in registry.providers_for(connection, listing.listing_id, capability)
                    )
                )
            ]
            fresh = stale = missing = 0
            quality = dict.fromkeys(_EFFECTIVE_QUALITIES, 0)
            delays = dict.fromkeys((name for name, _upper in _DELAY_BUCKETS), 0)
            latest_observed: datetime | None = None
            latest_ingested: datetime | None = None
            for listing in mapped:
                # Ultima revisione dell'ultima observation: un listing conta una sola volta.
                row = connection.execute(
                    _LATEST_OBSERVATION_SQL,
                    (listing.listing_id, capability, provider),
                ).fetchone()
                if row is None:
                    missing += 1
                    continue
                observed_at = _stored_utc(row["provider_observed_at"])
                effective = (
                    "stale"
                    if observed_at is None
                    else MarketObservationService.effective_quality_for(
                        capability,
                        str(row["source_quality"]),
                        observed_at,
                        moment,
                        settings=settings,
                    )
                )
                if effective == "stale":
                    stale += 1
                else:
                    fresh += 1
                quality[effective] = quality.get(effective, 0) + 1
                delays[_delay_bucket(int(row["delay_seconds"]))] += 1
                latest_observed = _latest(latest_observed, observed_at)
                latest_ingested = _latest(latest_ingested, _stored_utc(row["ingested_at"]))
            attribution = getattr(registry.provider_named(provider), "attribution", None)
            coverage.append(
                ProviderCoverageOut(
                    provider=provider,
                    capability=capability,
                    eligible_listings=len(eligible),
                    unmapped_listings=len(eligible) - len(mapped),
                    mapped_listings=len(mapped),
                    fresh_listings=fresh,
                    stale_listings=stale,
                    missing_observation_listings=missing,
                    rejected_observations=sum(
                        open_rejections[(provider, capability, listing.listing_id)] for listing in eligible
                    ),
                    quality_counts=quality,
                    delay_bucket_counts=delays,
                    latest_provider_observed_at=latest_observed,
                    latest_ingested_at=latest_ingested,
                    attribution=attribution if isinstance(attribution, str) and attribution else None,
                )
            )
        return coverage

    # --- FX -------------------------------------------------------------------

    def _fx(
        self,
        connection: sqlite3.Connection,
        resolved: list[_ResolvedListing],
        moment: datetime,
        settings: Settings,
    ) -> dict[str, Any]:
        currencies = {
            str(row["currency"]).strip().upper()
            for row in connection.execute(
                """
                SELECT currency FROM assets
                UNION
                SELECT currency FROM portfolio_positions WHERE quantity > 0
                """
            ).fetchall()
            if row["currency"] is not None
        }
        currencies.update(listing.currency for listing in resolved)
        # EUR resta identita (rate 1 in FXService) e non entra nel denominatore non-EUR.
        currencies.difference_update({"", "EUR"})
        items = [self._fx_item(connection, currency, moment, settings) for currency in sorted(currencies)]
        statuses = Counter(item.status for item in items)
        return {
            "fx_currency_denominator": len(currencies),
            "fx_fresh_currencies": statuses["FRESH"],
            "fx_stale_currencies": statuses["STALE"],
            "fx_missing_currencies": statuses["MISSING"],
            "fx_coverage": items,
        }

    @staticmethod
    def _fx_item(
        connection: sqlite3.Connection,
        currency: str,
        moment: datetime,
        settings: Settings,
    ) -> FxCoverageOut:
        """Ultima riga diretta `currency/EUR`, altrimenti l'inversa: stessa regola di FXService."""
        query = """
            SELECT rate, observed_at, ingested_at, provider, quality
            FROM fx_rates
            WHERE from_currency = ? AND to_currency = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
        """
        direction = "DIRECT"
        row = connection.execute(query, (currency, "EUR")).fetchone()
        if row is None:
            direction = "INVERSE"
            row = connection.execute(query, ("EUR", currency)).fetchone()
        if row is None:
            return FxCoverageOut(
                from_currency=currency,
                to_currency="EUR",
                status="MISSING",
                direction=None,
                provider=None,
                rate_to_eur=None,
                observed_at=None,
                ingested_at=None,
                age_seconds=None,
                quality=None,
            )
        stored_rate = float(row["rate"])
        rate = stored_rate if direction == "DIRECT" else 1.0 / stored_rate
        observed_text = str(row["observed_at"])
        stale = _fx_is_stale(observed_text, moment, settings.ecb_fx_max_age_days)
        observed_at = _stored_utc(observed_text)
        return FxCoverageOut(
            from_currency=currency,
            to_currency="EUR",
            status="STALE" if stale else "FRESH",
            direction=direction,
            provider=str(row["provider"]),
            rate_to_eur=Decimal(str(rate)),
            observed_at=observed_at,
            ingested_at=_stored_utc(row["ingested_at"]),
            age_seconds=max(0, int((moment - observed_at).total_seconds())) if observed_at is not None else None,
            quality="stale" if stale else str(row["quality"]),
        )

    # --- coda -----------------------------------------------------------------

    @staticmethod
    def _queue(connection: sqlite3.Connection) -> dict[str, int]:
        counts = {
            str(row["state"]): int(row["requests"])
            for row in connection.execute(
                """
                SELECT state, COUNT(*) AS requests
                FROM refresh_requests
                WHERE state IN ('PENDING', 'BUDGET_DEFERRED')
                GROUP BY state
                """
            ).fetchall()
        }
        return {
            "pending_refresh": counts.get("PENDING", 0),
            "budget_deferred": counts.get("BUDGET_DEFERRED", 0),
        }


# --- status provider additivo -------------------------------------------------


def _budget_policy(provider: BaseMarketDataProvider) -> ProviderBudgetPolicy:
    policy = getattr(provider, "policy", None)
    if isinstance(policy, ProviderBudgetPolicy):
        return policy
    return provider._budget_policy()


def _window_resets(moment: datetime) -> dict[BudgetWindow, datetime]:
    minute = moment.replace(second=0, microsecond=0)
    day = minute.replace(hour=0, minute=0)
    month = day.replace(day=1)
    return {
        "MINUTE": minute + timedelta(minutes=1),
        "DAY": day + timedelta(days=1),
        "MONTH": (month + timedelta(days=32)).replace(day=1),
    }


def _budget_windows(
    connection: sqlite3.Connection,
    provider: str,
    policy: ProviderBudgetPolicy,
    moment: datetime,
) -> list[dict[str, Any]]:
    starts = _window_values(moment)
    limits = _policy_limits(policy)
    resets = _window_resets(moment)
    windows: list[dict[str, Any]] = []
    for kind in _BUDGET_WINDOWS:
        row = connection.execute(
            """
            SELECT used_count, effective_limit
            FROM provider_usage_windows
            WHERE provider = ? AND window_kind = ? AND window_start = ?
            """,
            (provider, kind, starts[kind]),
        ).fetchone()
        used = int(row["used_count"]) if row is not None else 0
        if kind == "DAY":
            # Stessa proiezione legacy del budget manager: api_usage per data locale.
            legacy = connection.execute(
                "SELECT calls_count FROM api_usage WHERE provider = ? AND usage_date = ?",
                (provider, moment.astimezone().date().isoformat()),
            ).fetchone()
            if legacy is not None:
                used = max(used, int(legacy["calls_count"]))
        limit = ProviderBudgetManager._minimum_limit(
            limits[kind],
            int(row["effective_limit"]) if row is not None and row["effective_limit"] is not None else None,
        )
        windows.append(
            {
                "window": kind,
                "limit": limit,
                "used": used,
                "remaining": max(0, limit - used) if limit is not None else None,
                "reset_at": resets[kind],
            }
        )
    return windows


def provider_status_details(
    connection: sqlite3.Connection,
    registry: ProviderRegistry,
    now: datetime,
) -> dict[str, dict[str, Any]]:
    """Campi additivi dello status provider: capability, finestre budget, cooldown e ultimo esito.

    Solo letture locali; l'output non contiene key, URL, endpoint o fingerprint.
    """
    moment = now.astimezone(UTC)
    details: dict[str, dict[str, Any]] = {}
    for provider in registry.providers:
        name = provider.provider_name
        availability = registry.availability_for(name)
        last = connection.execute(
            """
            SELECT outcome, completed_at
            FROM provider_request_log
            WHERE provider = ? AND outcome IS NOT NULL
            ORDER BY requested_at DESC, completed_at DESC, rowid DESC
            LIMIT 1
            """,
            (name,),
        ).fetchone()
        details[name] = {
            "capabilities": list(_STATUS_CAPABILITIES.get(name, ())),
            "budget_windows": _budget_windows(connection, name, _budget_policy(provider), moment),
            "cooldown_until": ProviderBudgetManager._active_cooldown(connection, name, moment),
            "availability_state": availability.state,
            "availability_reason": availability.reason_code,
            "last_outcome": last["outcome"] if last is not None else None,
            "last_outcome_at": _stored_utc(last["completed_at"]) if last is not None else None,
        }
    return details
