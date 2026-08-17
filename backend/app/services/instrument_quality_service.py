from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from backend.app.config import Settings, get_settings
from backend.app.models.schemas import QualityReason, QualityTier
from backend.app.services.instrument_service import InstrumentService
from backend.app.services.market_observation_service import MarketObservationService
from backend.app.services.provider_budget_service import ProviderCapability

_REFERENCE_TYPES = frozenset({"MACRO", "RATE", "INDEX", "FX"})
_QUALIFIABLE_ASSET_CLASS_BY_TYPE = {
    "STOCK": "EQUITY",
    "ETF": "FUND",
    "BOND": "FIXED_INCOME",
    "ETC": "COMMODITY",
    "ETN": "COMMODITY",
    "CRYPTO": "CRYPTO",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("quality assessment clock must be timezone-aware")
    return value.astimezone(UTC)


def _parse_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("persisted quality timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class TierEvidenceScope:
    listing_id: int
    capability: ProviderCapability
    actual_provider: str
    operation: str
    selected_observation_ids: Sequence[int]


@dataclass(frozen=True)
class TierAssessment:
    instrument_id: int
    tier: QualityTier
    reason_codes: Sequence[QualityReason]
    assessed_at: datetime
    evidence_hash: str
    evidence_scopes: Sequence[TierEvidenceScope]


@dataclass(frozen=True)
class _ScopeCandidate:
    scope: TierEvidenceScope
    requested_provider: str
    fallback_reason: str | None
    observed_at: datetime
    source_quality: str
    currency: str
    fresh: bool

    @property
    def compatible_fallback(self) -> bool:
        return self.fallback_reason == "PROVIDER_FALLBACK"


class InstrumentQualityService:
    def __init__(
        self,
        settings: Settings | None = None,
        observation_service: MarketObservationService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if self.settings.market_data_qualified_history_bars < 1:
            raise ValueError("qualified history threshold must be positive")
        if self.settings.market_data_divergence_bps < 0:
            raise ValueError("divergence threshold cannot be negative")
        self.observation_service = observation_service or MarketObservationService(
            settings=self.settings
        )

    def select_evidence_scopes(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        target_tier: QualityTier,
        now: datetime,
    ) -> Sequence[TierEvidenceScope]:
        instant = _as_utc(now)
        self._require_instrument(connection, instrument_id)
        if target_tier == "REFERENCE_ONLY":
            return ()
        candidates = self._collect_candidates(connection, instrument_id, instant)
        if target_tier == "QUALIFIED":
            candidate = self._best_qualified_candidate(candidates)
        elif target_tier == "OBSERVABLE":
            candidate = self._best_observable_candidate(candidates)
        else:
            raise ValueError(f"Unsupported quality tier: {target_tier}")
        return (candidate.scope,) if candidate is not None else ()

    def assess(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        now: datetime,
    ) -> TierAssessment:
        instant = _as_utc(now)
        instrument = self._require_instrument(connection, instrument_id)
        instrument_type = str(instrument["instrument_type"])
        if instrument_type in _REFERENCE_TYPES:
            return self._build_assessment(
                connection,
                instrument,
                "REFERENCE_ONLY",
                ("REFERENCE_INSTRUMENT",),
                (),
                instant,
            )

        if InstrumentService.has_ambiguous_identity(connection, instrument_id):
            return self._build_assessment(
                connection,
                instrument,
                "REFERENCE_ONLY",
                ("AMBIGUOUS_IDENTITY",),
                (),
                instant,
            )

        candidates = self._collect_candidates(connection, instrument_id, instant)
        best_eod = self._best_qualified_candidate(candidates)
        best_observable = self._best_observable_candidate(candidates)
        candidate = (
            best_eod
            if (
                best_eod is not None
                and best_eod.fresh
                and len(best_eod.scope.selected_observation_ids)
                >= self.settings.market_data_qualified_history_bars
            )
            else best_observable
        )
        scopes = (candidate.scope,) if candidate is not None else ()

        open_rejection_ids = (
            self._open_rejection_ids(connection, candidate.scope)
            if candidate is not None
            else ()
        )
        divergence_pairs = (
            self._divergence_pairs(connection, candidate.scope, instant)
            if candidate is not None
            else ()
        )
        fallback_reasons: tuple[QualityReason, ...] = (
            ("COMPATIBLE_FALLBACK_IN_USE",)
            if candidate is not None and candidate.compatible_fallback
            else ()
        )
        if open_rejection_ids:
            return self._build_assessment(
                connection,
                instrument,
                "REFERENCE_ONLY",
                ("UNRESOLVED_CRITICAL_REJECTION", *fallback_reasons),
                scopes,
                instant,
                candidate=candidate,
                open_rejection_ids=open_rejection_ids,
            )
        if divergence_pairs:
            return self._build_assessment(
                connection,
                instrument,
                "REFERENCE_ONLY",
                ("PROVIDER_DIVERGENCE", *fallback_reasons),
                scopes,
                instant,
                candidate=candidate,
                divergence_pairs=divergence_pairs,
            )

        missing_reasons: list[QualityReason] = []
        if (
            _QUALIFIABLE_ASSET_CLASS_BY_TYPE.get(instrument_type)
            != str(instrument["asset_class"])
        ):
            missing_reasons.append("MISSING_LISTING_METADATA")
        primary_identifier = InstrumentService.verified_primary_identifier(
            connection,
            instrument_id,
            instrument_type,
        )
        if primary_identifier is None:
            missing_reasons.append("MISSING_PRIMARY_ID")
        listing_id = (
            candidate.scope.listing_id
            if candidate is not None
            else self._first_listing_id(connection, instrument_id)
        )
        if (
            listing_id is None
            or not self._listing_metadata_complete(
                connection,
                listing_id,
                instrument_type,
            )
        ) and "MISSING_LISTING_METADATA" not in missing_reasons:
            missing_reasons.append("MISSING_LISTING_METADATA")

        if candidate is None:
            return self._build_assessment(
                connection,
                instrument,
                "REFERENCE_ONLY",
                (*missing_reasons, "NO_VALID_OBSERVATION"),
                (),
                instant,
            )
        if not candidate.fresh:
            return self._build_assessment(
                connection,
                instrument,
                "REFERENCE_ONLY",
                (*missing_reasons, "STALE_OBSERVATION", *fallback_reasons),
                scopes,
                instant,
                candidate=candidate,
            )
        if missing_reasons:
            return self._build_assessment(
                connection,
                instrument,
                "OBSERVABLE",
                (*missing_reasons, "VALIDATED_OBSERVABLE", *fallback_reasons),
                scopes,
                instant,
                candidate=candidate,
            )

        if (
            candidate.scope.capability != "EOD"
            or len(candidate.scope.selected_observation_ids)
            < self.settings.market_data_qualified_history_bars
        ):
            return self._build_assessment(
                connection,
                instrument,
                "OBSERVABLE",
                (
                    "INSUFFICIENT_HISTORY",
                    "VALIDATED_OBSERVABLE",
                    *fallback_reasons,
                ),
                scopes,
                instant,
                candidate=candidate,
            )

        return self._build_assessment(
            connection,
            instrument,
            "QUALIFIED",
            ("QUALIFICATION_RULES_MET", *fallback_reasons),
            scopes,
            instant,
            candidate=candidate,
        )

    def assess_and_record(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        now: datetime,
    ) -> TierAssessment:
        had_transaction = connection.in_transaction
        savepoint = "instrument_quality_assessment"
        if had_transaction:
            connection.execute(f"SAVEPOINT {savepoint}")
        else:
            connection.execute("BEGIN IMMEDIATE")
        try:
            assessment = self.assess(connection, instrument_id, now)
            existing = connection.execute(
                """
                SELECT *
                FROM quality_assessments
                WHERE instrument_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (assessment.instrument_id,),
            ).fetchone()
            if (
                existing is None
                or existing["tier"] != assessment.tier
                or existing["evidence_hash"] != assessment.evidence_hash
            ):
                connection.execute(
                    """
                    INSERT INTO quality_assessments (
                        instrument_id, tier, reason_codes_json, assessed_at,
                        evidence_hash, evidence_scopes_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assessment.instrument_id,
                        assessment.tier,
                        json.dumps(list(assessment.reason_codes), separators=(",", ":")),
                        assessment.assessed_at.isoformat(),
                        assessment.evidence_hash,
                        self._scopes_json(assessment.evidence_scopes),
                        assessment.assessed_at.isoformat(),
                    ),
                )
                recorded = assessment
            else:
                recorded = self._assessment_from_row(existing)
            connection.execute(
                """
                UPDATE instruments
                SET quality_tier = ?, quality_reason_code = ?,
                    quality_assessed_at = ?
                WHERE id = ?
                """,
                (
                    recorded.tier,
                    recorded.reason_codes[0],
                    recorded.assessed_at.isoformat(),
                    recorded.instrument_id,
                ),
            )
            if had_transaction:
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                connection.commit()
            return recorded
        except Exception:
            if had_transaction:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                connection.rollback()
            raise

    def eligible_for_strategy(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        now: datetime,
        require_trade_republic: bool,
    ) -> bool:
        instant = _as_utc(now)
        projection = connection.execute(
            """
            SELECT quality_tier, quality_reason_code, quality_assessed_at
            FROM instruments
            WHERE id = ?
            """,
            (instrument_id,),
        ).fetchone()
        if projection is None or projection["quality_tier"] != "QUALIFIED":
            return False
        recorded_row = connection.execute(
            """
            SELECT *
            FROM quality_assessments
            WHERE instrument_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (instrument_id,),
        ).fetchone()
        if recorded_row is None:
            return False
        recorded = self._assessment_from_row(recorded_row)
        if (
            recorded.tier != "QUALIFIED"
            or not recorded.reason_codes
            or projection["quality_reason_code"] != recorded.reason_codes[0]
            or projection["quality_assessed_at"] is None
            or _parse_datetime(projection["quality_assessed_at"])
            != recorded.assessed_at
        ):
            return False
        assessment = self.assess(connection, instrument_id, instant)
        if (
            assessment.tier != "QUALIFIED"
            or not assessment.evidence_scopes
            or assessment.evidence_hash != recorded.evidence_hash
        ):
            return False
        if not require_trade_republic:
            return True
        cutoff = instant - timedelta(
            days=self.settings.trade_republic_verified_max_age_days
        )
        for scope in assessment.evidence_scopes:
            listing = connection.execute(
                """
                SELECT trade_republic_status, trade_republic_verified_at
                FROM instrument_listings
                WHERE id = ?
                """,
                (scope.listing_id,),
            ).fetchone()
            if (
                listing is None
                or listing["trade_republic_status"] != "VERIFIED"
                or listing["trade_republic_verified_at"] is None
            ):
                continue
            verified_at = _parse_datetime(listing["trade_republic_verified_at"])
            if cutoff <= verified_at <= instant:
                return True
        return False

    @staticmethod
    def _require_instrument(
        connection: sqlite3.Connection,
        instrument_id: int,
    ) -> sqlite3.Row:
        instrument = connection.execute(
            """
            SELECT id, canonical_name, instrument_type, asset_class
            FROM instruments
            WHERE id = ?
            """,
            (instrument_id,),
        ).fetchone()
        if instrument is None:
            raise ValueError(f"Instrument {instrument_id} not found")
        return instrument

    def _collect_candidates(
        self,
        connection: sqlite3.Connection,
        instrument_id: int,
        now: datetime,
    ) -> tuple[_ScopeCandidate, ...]:
        listings = connection.execute(
            """
            SELECT id
            FROM instrument_listings
            WHERE instrument_id = ? AND listing_status = 'ACTIVE'
            ORDER BY id
            """,
            (instrument_id,),
        ).fetchall()
        candidates: list[_ScopeCandidate] = []
        for listing in listings:
            listing_id = int(listing["id"])
            for capability in ("EOD", "QUOTE"):
                observation = self.observation_service.latest_compatible(
                    connection,
                    listing_id,
                    capability,
                    now,
                )
                if observation is None:
                    continue
                event = connection.execute(
                    """
                    SELECT selection.selected_observation_id,
                           selection.requested_provider,
                           selection.actual_provider,
                           selection.fallback_reason,
                           observation.operation
                    FROM market_data_selection_events AS selection
                    JOIN market_observations AS observation
                      ON observation.id = selection.selected_observation_id
                    WHERE observation.listing_id = ?
                      AND observation.capability = ?
                    ORDER BY selection.id DESC
                    LIMIT 1
                    """,
                    (listing_id, capability),
                ).fetchone()
                if event is None:
                    raise sqlite3.IntegrityError(
                        "compatible observation selection event is missing"
                    )
                selected_ids: tuple[int, ...]
                if capability == "EOD":
                    history = connection.execute(
                        """
                        SELECT observation.id, observation.provider_observed_at,
                               observation.timezone
                        FROM market_observations AS observation
                        WHERE observation.listing_id = ?
                          AND observation.capability = 'EOD'
                          AND observation.provider = ?
                          AND observation.operation = ?
                          AND observation.kind = 'BAR'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM market_observations AS newer
                              WHERE newer.supersedes_observation_id = observation.id
                          )
                        ORDER BY observation.provider_observed_at DESC,
                                 observation.id DESC
                        """,
                        (
                            listing_id,
                            event["actual_provider"],
                            event["operation"],
                        ),
                    )
                    latest_daily_ids: list[int] = []
                    selected_dates = set()
                    for row in history:
                        observed_date = _parse_datetime(
                            row["provider_observed_at"]
                        ).astimezone(ZoneInfo(str(row["timezone"]))).date()
                        if observed_date in selected_dates:
                            continue
                        selected_dates.add(observed_date)
                        latest_daily_ids.append(int(row["id"]))
                        if (
                            len(latest_daily_ids)
                            >= self.settings.market_data_qualified_history_bars
                        ):
                            break
                    selected_ids = tuple(reversed(latest_daily_ids))
                else:
                    selected_ids = (int(event["selected_observation_id"]),)
                scope = TierEvidenceScope(
                    listing_id=listing_id,
                    capability=cast(ProviderCapability, capability),
                    actual_provider=str(event["actual_provider"]),
                    operation=str(event["operation"]),
                    selected_observation_ids=selected_ids,
                )
                candidates.append(
                    _ScopeCandidate(
                        scope=scope,
                        requested_provider=str(event["requested_provider"]),
                        fallback_reason=(
                            str(event["fallback_reason"])
                            if event["fallback_reason"] is not None
                            else None
                        ),
                        observed_at=observation.provider_observed_at,
                        source_quality=observation.source_quality,
                        currency=observation.currency,
                        fresh=(
                            self.observation_service.effective_quality(
                                observation,
                                now,
                            )
                            != "stale"
                        ),
                    )
                )
        return tuple(candidates)

    def _best_qualified_candidate(
        self,
        candidates: Sequence[_ScopeCandidate],
    ) -> _ScopeCandidate | None:
        eod = [candidate for candidate in candidates if candidate.scope.capability == "EOD"]
        if not eod:
            return None
        threshold = self.settings.market_data_qualified_history_bars
        return max(
            eod,
            key=lambda candidate: (
                candidate.fresh
                and len(candidate.scope.selected_observation_ids) >= threshold,
                candidate.fresh,
                len(candidate.scope.selected_observation_ids),
                candidate.observed_at,
                -candidate.scope.listing_id,
                candidate.scope.actual_provider,
                candidate.scope.operation,
            ),
        )

    @staticmethod
    def _best_observable_candidate(
        candidates: Sequence[_ScopeCandidate],
    ) -> _ScopeCandidate | None:
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda candidate: (
                candidate.fresh,
                candidate.observed_at,
                candidate.scope.capability == "EOD",
                -candidate.scope.listing_id,
                candidate.scope.actual_provider,
                candidate.scope.operation,
            ),
        )

    @staticmethod
    def _first_listing_id(
        connection: sqlite3.Connection,
        instrument_id: int,
    ) -> int | None:
        row = connection.execute(
            """
            SELECT id
            FROM instrument_listings
            WHERE instrument_id = ? AND listing_status = 'ACTIVE'
            ORDER BY id
            LIMIT 1
            """,
            (instrument_id,),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    @staticmethod
    def _listing_metadata_complete(
        connection: sqlite3.Connection,
        listing_id: int,
        instrument_type: str,
    ) -> bool:
        listing = connection.execute(
            """
            SELECT mic, currency, timezone
            FROM instrument_listings
            WHERE id = ? AND listing_status = 'ACTIVE'
            """,
            (listing_id,),
        ).fetchone()
        if listing is None:
            return False
        currency = str(listing["currency"] or "").strip().upper()
        timezone = str(listing["timezone"] or "").strip()
        if len(currency) != 3:
            return False
        if instrument_type == "CRYPTO":
            return timezone == "UTC"
        return bool(str(listing["mic"] or "").strip() and timezone)

    @staticmethod
    def _open_rejection_ids(
        connection: sqlite3.Connection,
        scope: TierEvidenceScope,
    ) -> tuple[int, ...]:
        rows = connection.execute(
            """
            SELECT rejection.id
            FROM market_data_rejections AS rejection
            LEFT JOIN market_data_rejection_resolutions AS resolution
              ON resolution.rejection_id = rejection.id
            WHERE rejection.listing_id = ?
              AND rejection.provider = ?
              AND rejection.capability = ?
              AND rejection.operation = ?
              AND resolution.id IS NULL
            ORDER BY rejection.id
            """,
            (
                scope.listing_id,
                scope.actual_provider,
                scope.capability,
                scope.operation,
            ),
        ).fetchall()
        return tuple(int(row["id"]) for row in rows)

    def _divergence_pairs(
        self,
        connection: sqlite3.Connection,
        scope: TierEvidenceScope,
        now: datetime,
    ) -> tuple[tuple[int, int], ...]:
        rows = connection.execute(
            """
            SELECT observation.*
            FROM market_observations AS observation
            WHERE observation.listing_id = ?
              AND observation.capability = ?
              AND (observation.last IS NOT NULL OR observation.close IS NOT NULL)
              AND NOT EXISTS (
                  SELECT 1
                  FROM market_observations AS newer
                  WHERE newer.supersedes_observation_id = observation.id
              )
            ORDER BY observation.provider,
                     observation.provider_observed_at DESC,
                     observation.ingested_at DESC,
                     observation.id DESC
            """,
            (scope.listing_id, scope.capability),
        ).fetchall()
        latest_by_provider: dict[str, sqlite3.Row] = {}
        for row in rows:
            provider = str(row["provider"])
            latest_by_provider.setdefault(provider, row)
        comparable: list[tuple[sqlite3.Row, datetime, Decimal]] = []
        for row in latest_by_provider.values():
            observed_at = _parse_datetime(row["provider_observed_at"])
            if MarketObservationService.effective_quality_for(
                str(row["capability"]),
                str(row["source_quality"]),
                observed_at,
                now,
                settings=self.settings,
            ) == "stale":
                continue
            raw_price = row["last"] if row["last"] is not None else row["close"]
            price = Decimal(str(raw_price))
            if price > 0:
                comparable.append((row, observed_at, price))
        divergent: list[tuple[int, int]] = []
        threshold = Decimal(self.settings.market_data_divergence_bps)
        for index, (left, left_at, left_price) in enumerate(comparable):
            for right, right_at, right_price in comparable[index + 1 :]:
                if left["currency"] != right["currency"]:
                    continue
                if abs(left_at - right_at) > timedelta(minutes=10):
                    continue
                bps = abs(left_price - right_price) / min(left_price, right_price) * 10_000
                if bps > threshold:
                    divergent.append(tuple(sorted((int(left["id"]), int(right["id"])))))
        return tuple(sorted(set(divergent)))

    def _build_assessment(
        self,
        connection: sqlite3.Connection,
        instrument: sqlite3.Row,
        tier: QualityTier,
        reasons: Sequence[QualityReason],
        scopes: Sequence[TierEvidenceScope],
        assessed_at: datetime,
        *,
        candidate: _ScopeCandidate | None = None,
        open_rejection_ids: Sequence[int] = (),
        divergence_pairs: Sequence[tuple[int, int]] = (),
    ) -> TierAssessment:
        instrument_id = int(instrument["id"])
        evidence = {
            "instrument": {
                "id": instrument_id,
                "instrument_type": str(instrument["instrument_type"]),
                "asset_class": str(instrument["asset_class"]),
            },
            "listings": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT id, ticker, mic, currency, timezone, listing_status
                    FROM instrument_listings
                    WHERE instrument_id = ?
                    ORDER BY id
                    """,
                    (instrument_id,),
                ).fetchall()
            ],
            "identifiers": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT identifier.id, identifier.scheme,
                           identifier.normalized_value, identifier.scope,
                           identifier.instrument_id, identifier.listing_id,
                           attestation.id AS attestation_id,
                           attestation.evidence_hash
                    FROM instrument_identifiers AS identifier
                    LEFT JOIN instrument_identifier_attestations AS attestation
                      ON attestation.identifier_id = identifier.id
                    WHERE identifier.instrument_id = ?
                       OR identifier.listing_id IN (
                           SELECT id FROM instrument_listings WHERE instrument_id = ?
                       )
                    ORDER BY identifier.id, attestation.id
                    """,
                    (instrument_id, instrument_id),
                ).fetchall()
            ],
            "resolution_cases": [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT resolution.id, resolution.status,
                           resolution.reason_code, resolution.candidate_count,
                           resolution.evidence_hash
                    FROM instrument_resolution_cases AS resolution
                    JOIN catalog_entries AS entry
                      ON entry.id = resolution.catalog_entry_id
                    WHERE entry.instrument_id = ?
                      AND NOT EXISTS (
                          SELECT 1
                          FROM instrument_resolution_cases AS newer
                          WHERE newer.catalog_entry_id = resolution.catalog_entry_id
                            AND newer.id > resolution.id
                      )
                    ORDER BY resolution.id
                    """,
                    (instrument_id,),
                ).fetchall()
            ],
            "tier": tier,
            "reasons": list(reasons),
            "scopes": [self._scope_payload(scope) for scope in scopes],
            "selection": (
                {
                    "requested_provider": candidate.requested_provider,
                    "actual_provider": candidate.scope.actual_provider,
                    "fallback_reason": candidate.fallback_reason,
                }
                if candidate is not None
                else None
            ),
            "open_rejection_ids": list(open_rejection_ids),
            "divergence_pairs": [list(pair) for pair in divergence_pairs],
            "policy": {
                "history_bars": self.settings.market_data_qualified_history_bars,
                "divergence_bps": self.settings.market_data_divergence_bps,
                "quote_age_minutes": self.settings.market_data_quote_max_age_minutes,
                "delayed_age_minutes": self.settings.market_data_delayed_max_age_minutes,
                "eod_age_hours": self.settings.market_data_eod_max_age_hours,
                "reference_age_days": self.settings.market_data_reference_max_age_days,
            },
        }
        canonical = json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return TierAssessment(
            instrument_id=instrument_id,
            tier=tier,
            reason_codes=tuple(reasons),
            assessed_at=assessed_at,
            evidence_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            evidence_scopes=tuple(scopes),
        )

    @staticmethod
    def _scope_payload(scope: TierEvidenceScope) -> dict[str, object]:
        return {
            "listing_id": scope.listing_id,
            "capability": scope.capability,
            "actual_provider": scope.actual_provider,
            "operation": scope.operation,
            "selected_observation_ids": list(scope.selected_observation_ids),
        }

    @classmethod
    def _scopes_json(cls, scopes: Sequence[TierEvidenceScope]) -> str:
        return json.dumps(
            [cls._scope_payload(scope) for scope in scopes],
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _assessment_from_row(row: sqlite3.Row) -> TierAssessment:
        scope_values = json.loads(str(row["evidence_scopes_json"]))
        scopes = tuple(
            TierEvidenceScope(
                listing_id=int(value["listing_id"]),
                capability=cast(ProviderCapability, str(value["capability"])),
                actual_provider=str(value["actual_provider"]),
                operation=str(value["operation"]),
                selected_observation_ids=tuple(
                    int(observation_id)
                    for observation_id in value["selected_observation_ids"]
                ),
            )
            for value in scope_values
        )
        return TierAssessment(
            instrument_id=int(row["instrument_id"]),
            tier=cast(QualityTier, str(row["tier"])),
            reason_codes=tuple(
                cast(QualityReason, value)
                for value in json.loads(str(row["reason_codes_json"]))
            ),
            assessed_at=_parse_datetime(row["assessed_at"]),
            evidence_hash=str(row["evidence_hash"]),
            evidence_scopes=scopes,
        )
