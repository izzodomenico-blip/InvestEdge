from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.config import Settings, get_settings
from backend.app.models.market_data import (
    ADAPTER_VALIDATION_REASONS,
    EffectiveObservationQuality,
    IngestResult,
    MarketObservation,
    MarketObservationEnvelope,
    ObservationKind,
    ObservationRejection,
    SourceObservationQuality,
    ValidatedObservation,
    ValidationReason,
)
from backend.app.services.provider_budget_service import ProviderCapability

_PRICE_FIELDS = (
    "bid",
    "ask",
    "last",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_CAPABILITIES = frozenset(get_args(ProviderCapability))
_KINDS = frozenset(get_args(ObservationKind))
_SOURCE_QUALITIES = frozenset(get_args(SourceObservationQuality))


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _parse_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed.astimezone(UTC)


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


class MarketObservationService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    def validate(
        self,
        listing: sqlite3.Row | Mapping[str, object],
        envelope: MarketObservationEnvelope,
        now: datetime,
    ) -> ValidatedObservation | ObservationRejection:
        rejection = self._validate_envelope_metadata(envelope, now)
        if rejection is not None:
            return rejection

        raw_reason = envelope.raw_fields.get("reason_code")
        if raw_reason in ADAPTER_VALIDATION_REASONS:
            return self._rejection(envelope, cast(ValidationReason, raw_reason))
        if raw_reason is not None:
            return self._rejection(envelope, "MALFORMED_PAYLOAD")

        observed_at = cast(datetime, envelope.provider_observed_at).astimezone(UTC)
        ingested_at = now.astimezone(UTC)
        if observed_at > ingested_at + timedelta(minutes=5):
            return self._rejection(envelope, "FUTURE_TIMESTAMP")

        timezone = cast(str, envelope.timezone).strip()
        try:
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            return self._rejection(envelope, "INVALID_TIMEZONE")
        listing_timezone = self._listing_value(listing, "timezone")
        if envelope.kind == "BAR":
            attested_timezone = str(listing_timezone or "").strip()
            if not attested_timezone or timezone != attested_timezone:
                return self._rejection(envelope, "INVALID_TIMEZONE")

        currency = cast(str, envelope.currency).strip()
        listing_currency = str(self._listing_value(listing, "currency") or "").strip().upper()
        if (
            not _CURRENCY_PATTERN.fullmatch(currency)
            or currency != listing_currency
        ):
            return self._rejection(envelope, "CURRENCY_MISMATCH")

        delay = (ingested_at - observed_at).total_seconds()
        if delay < 0:
            return self._rejection(envelope, "INVALID_DELAY")
        delay_seconds = int(delay)

        values: dict[str, Decimal | None] = {}
        try:
            for field in _PRICE_FIELDS:
                raw_value = envelope.raw_fields.get(field)
                values[field] = self._decimal_value(raw_value) if raw_value is not None else None
        except ValueError as exc:
            reason = "NON_FINITE" if str(exc) == "NON_FINITE" else "MALFORMED_PAYLOAD"
            return self._rejection(envelope, cast(ValidationReason, reason))

        present_prices = [value for value in values.values() if value is not None]
        if not present_prices:
            return self._rejection(envelope, "MISSING_PRICE")
        if any(value <= 0 or float(value) <= 0 for value in present_prices):
            return self._rejection(envelope, "NON_POSITIVE")

        bid = values["bid"]
        ask = values["ask"]
        if bid is not None and ask is not None and bid > ask:
            return self._rejection(envelope, "CROSSED_QUOTE")

        low = values["low"]
        high = values["high"]
        ohlc_values = [
            value
            for field in ("open", "high", "low", "close")
            if (value := values[field]) is not None
        ]
        if (
            (low is not None and any(low > value for value in ohlc_values))
            or (high is not None and any(high < value for value in ohlc_values))
        ):
            return self._rejection(envelope, "INVALID_OHLC")

        raw_volume = envelope.raw_fields.get("volume")
        try:
            volume = self._decimal_value(raw_volume) if raw_volume is not None else None
        except ValueError as exc:
            reason = "NON_FINITE" if str(exc) == "NON_FINITE" else "MALFORMED_PAYLOAD"
            return self._rejection(envelope, cast(ValidationReason, reason))
        if volume is not None and volume < 0:
            return self._rejection(envelope, "NEGATIVE_VOLUME")

        observation = MarketObservation(
            listing_id=envelope.listing_id,
            provider=envelope.provider.strip().lower(),
            capability=cast(ProviderCapability, envelope.capability.upper()),
            operation=envelope.operation.strip(),
            provider_observed_at=observed_at,
            ingested_at=ingested_at,
            timezone=timezone,
            session=cast(str, envelope.session).strip().upper(),
            currency=currency,
            delay_seconds=delay_seconds,
            source_quality=cast(SourceObservationQuality, envelope.source_quality),
            kind=cast(ObservationKind, envelope.kind),
            bid=values["bid"],
            ask=values["ask"],
            last=values["last"],
            open=values["open"],
            high=values["high"],
            low=values["low"],
            close=values["close"],
            adjusted_close=values["adjusted_close"],
            volume=volume,
        )
        effective_quality = self.effective_quality(observation, ingested_at)
        return ValidatedObservation(
            observation=observation,
            effective_quality=effective_quality,
            observation_hash=self._observation_hash(observation),
        )

    def ingest_batch(
        self,
        connection: sqlite3.Connection,
        envelopes: Sequence[MarketObservationEnvelope],
        now: datetime,
    ) -> IngestResult:
        validated_batch: list[ValidatedObservation | ObservationRejection] = []
        for envelope in envelopes:
            listing = connection.execute(
                "SELECT * FROM instrument_listings WHERE id = ?",
                (envelope.listing_id,),
            ).fetchone()
            if listing is None:
                raise ValueError(f"Listing {envelope.listing_id} non trovato.")
            validated_batch.append(self.validate(listing, envelope, now))

        accepted = 0
        rejected = 0
        duplicates = 0
        revisions = 0
        resolved_rejections = 0
        projected_price_rows = 0
        if not validated_batch:
            return IngestResult(0, 0, 0, 0, 0, 0)

        had_transaction = connection.in_transaction
        savepoint = "market_observation_ingest"
        if had_transaction:
            connection.execute(f"SAVEPOINT {savepoint}")
        else:
            connection.execute("BEGIN")
        try:
            for result in validated_batch:
                if isinstance(result, ObservationRejection):
                    self._persist_rejection(connection, result)
                    rejected += 1

            for result in validated_batch:
                if isinstance(result, ObservationRejection):
                    continue

                observation = result.observation
                logical_params = self._logical_key(observation)
                duplicate = connection.execute(
                    """
                    SELECT id, ingested_at
                    FROM market_observations
                    WHERE listing_id = ? AND provider = ? AND capability = ?
                      AND operation = ? AND kind = ? AND provider_observed_at = ?
                      AND session = ? AND observation_hash = ?
                    ORDER BY revision DESC, id DESC
                    LIMIT 1
                    """,
                    (*logical_params, result.observation_hash),
                ).fetchone()
                if duplicate is not None:
                    duplicates += 1
                    resolved_rejections += self._resolve_rejections(
                        connection,
                        observation,
                        int(duplicate["id"]),
                        _parse_datetime(duplicate["ingested_at"]),
                    )
                    continue

                previous = connection.execute(
                    """
                    SELECT id, revision
                    FROM market_observations
                    WHERE listing_id = ? AND provider = ? AND capability = ?
                      AND operation = ? AND kind = ? AND provider_observed_at = ?
                      AND session = ?
                    ORDER BY revision DESC, id DESC
                    LIMIT 1
                    """,
                    logical_params,
                ).fetchone()
                revision = int(previous["revision"]) + 1 if previous is not None else 1
                supersedes_id = int(previous["id"]) if previous is not None else None
                observation_id = self._persist_observation(
                    connection,
                    result,
                    revision,
                    supersedes_id,
                )
                accepted += 1
                if supersedes_id is not None:
                    revisions += 1
                resolved_rejections += self._resolve_rejections(
                    connection,
                    observation,
                    observation_id,
                    observation.ingested_at,
                )
                if observation.kind == "BAR":
                    projected_price_rows += self._project_bar(
                        connection,
                        observation_id,
                        observation,
                        supersedes_id,
                    )
            if had_transaction:
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            if had_transaction:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                connection.rollback()
            raise

        return IngestResult(
            accepted=accepted,
            rejected=rejected,
            duplicates=duplicates,
            revisions=revisions,
            resolved_rejections=resolved_rejections,
            projected_price_rows=projected_price_rows,
        )

    def latest_compatible(
        self,
        connection: sqlite3.Connection,
        listing_id: int,
        capability: str,
        now: datetime,
        requested_provider: str | None = None,
    ) -> MarketObservation | None:
        normalized_capability = capability.strip().upper()
        row = connection.execute(
            """
            SELECT observation.*
            FROM market_observations AS observation
            WHERE observation.listing_id = ?
              AND observation.capability = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM market_observations AS newer
                  WHERE newer.supersedes_observation_id = observation.id
              )
            ORDER BY observation.provider_observed_at DESC,
                     observation.ingested_at DESC,
                     observation.id DESC
            LIMIT 1
            """,
            (listing_id, normalized_capability),
        ).fetchone()
        if row is None:
            return None

        observation = self._observation_from_row(row)
        normalized_requested = str(requested_provider or "").strip().lower()
        if not normalized_requested:
            requested = connection.execute(
                """
                SELECT provider
                FROM provider_symbols
                WHERE listing_id = ? AND UPPER(capability) = ? AND status = 'VERIFIED'
                ORDER BY version DESC, id DESC
                LIMIT 1
                """,
                (listing_id, normalized_capability),
            ).fetchone()
            normalized_requested = (
                str(requested["provider"]).strip().lower()
                if requested is not None
                else observation.provider
            )
        fallback_reason: str | None = None
        if normalized_requested != observation.provider:
            fallback_reason = "PROVIDER_FALLBACK"
        elif self.effective_quality(observation, now) == "stale":
            fallback_reason = "LAST_GOOD_STALE"
        else:
            fallback_reason = "LAST_GOOD"

        connection.execute(
            """
            INSERT INTO market_data_selection_events (
                selected_observation_id, requested_provider, actual_provider,
                selected_at, fallback_reason
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                normalized_requested,
                observation.provider,
                _iso_utc(now),
                fallback_reason,
            ),
        )
        return observation

    def effective_quality(
        self,
        observation: MarketObservation,
        now: datetime,
    ) -> EffectiveObservationQuality:
        return MarketObservationService.effective_quality_for(
            observation.capability,
            observation.source_quality,
            observation.provider_observed_at,
            now,
            settings=self.settings,
        )

    @staticmethod
    def effective_quality_for(
        capability: str,
        source_quality: str,
        provider_observed_at: datetime,
        now: datetime,
        *,
        settings: Settings | None = None,
    ) -> EffectiveObservationQuality:
        policy = settings or get_settings()
        age = now.astimezone(UTC) - provider_observed_at.astimezone(UTC)
        if capability in {"REFERENCE", "FX"}:
            maximum_age = timedelta(days=policy.market_data_reference_max_age_days)
        elif source_quality == "eod" or capability == "EOD":
            maximum_age = timedelta(hours=policy.market_data_eod_max_age_hours)
        elif source_quality == "delayed":
            maximum_age = timedelta(minutes=policy.market_data_delayed_max_age_minutes)
        else:
            maximum_age = timedelta(minutes=policy.market_data_quote_max_age_minutes)
        if age > maximum_age:
            return "stale"
        return cast(EffectiveObservationQuality, source_quality)

    def _validate_envelope_metadata(
        self,
        envelope: MarketObservationEnvelope,
        now: datetime,
    ) -> ObservationRejection | None:
        if not isinstance(envelope.raw_fields, Mapping):
            return self._rejection(envelope, "MALFORMED_PAYLOAD")
        if not _SHA256_PATTERN.fullmatch(envelope.raw_payload_sha256):
            return self._rejection(envelope, "MALFORMED_PAYLOAD")
        if (
            not envelope.provider.strip()
            or envelope.capability.upper() not in _CAPABILITIES
            or not envelope.operation.strip()
        ):
            return self._rejection(envelope, "MALFORMED_PAYLOAD")
        if envelope.received_at.tzinfo is None or envelope.received_at.utcoffset() is None:
            return self._rejection(envelope, "INVALID_TIMESTAMP")
        if now.tzinfo is None or now.utcoffset() is None:
            return self._rejection(envelope, "INVALID_TIMESTAMP")

        raw_reason = envelope.raw_fields.get("reason_code")
        if raw_reason in ADAPTER_VALIDATION_REASONS:
            return None
        if envelope.kind not in _KINDS or envelope.source_quality not in _SOURCE_QUALITIES:
            return self._rejection(envelope, "MALFORMED_PAYLOAD")
        if (
            (envelope.capability.upper() == "QUOTE" and envelope.kind != "QUOTE")
            or (envelope.capability.upper() == "EOD" and envelope.kind != "BAR")
        ):
            return self._rejection(envelope, "MALFORMED_PAYLOAD")
        if not isinstance(envelope.timezone, str) or not envelope.timezone.strip():
            return self._rejection(envelope, "INVALID_TIMEZONE")
        if not isinstance(envelope.session, str) or not envelope.session.strip():
            return self._rejection(envelope, "MALFORMED_PAYLOAD")
        if not isinstance(envelope.currency, str):
            return self._rejection(envelope, "CURRENCY_MISMATCH")
        if envelope.provider_observed_at is None:
            return self._rejection(envelope, "INVALID_TIMESTAMP")
        if (
            envelope.provider_observed_at.tzinfo is None
            or envelope.provider_observed_at.utcoffset() is None
        ):
            return self._rejection(envelope, "INVALID_TIMESTAMP")
        return None

    @staticmethod
    def _decimal_value(value: object) -> Decimal:
        if isinstance(value, bool):
            raise ValueError("MALFORMED_PAYLOAD")
        try:
            numeric = float(str(value))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("MALFORMED_PAYLOAD") from None
        if not math.isfinite(numeric):
            raise ValueError("NON_FINITE")
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("MALFORMED_PAYLOAD") from None
        if not decimal_value.is_finite():
            raise ValueError("NON_FINITE")
        return decimal_value

    @staticmethod
    def _listing_value(
        listing: sqlite3.Row | Mapping[str, object],
        key: str,
    ) -> object | None:
        try:
            return listing[key]
        except (IndexError, KeyError):
            return None

    @staticmethod
    def _safe_payload_hash(value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value):
            return value.lower()
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()

    def _rejection(
        self,
        envelope: MarketObservationEnvelope,
        reason: ValidationReason,
    ) -> ObservationRejection:
        received_at = envelope.received_at
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            received_at = received_at.replace(tzinfo=UTC)
        return ObservationRejection(
            listing_id=envelope.listing_id,
            provider=envelope.provider.strip().lower(),
            capability=cast(ProviderCapability, envelope.capability.upper()),
            operation=envelope.operation.strip(),
            received_at=received_at.astimezone(UTC),
            reason_code=reason,
            raw_payload_sha256=self._safe_payload_hash(envelope.raw_payload_sha256),
        )

    @staticmethod
    def _observation_hash(observation: MarketObservation) -> str:
        canonical = {
            "listing_id": observation.listing_id,
            "provider": observation.provider,
            "capability": observation.capability,
            "operation": observation.operation,
            "kind": observation.kind,
            "provider_observed_at": _iso_utc(observation.provider_observed_at),
            "session": observation.session,
            "timezone": observation.timezone,
            "currency": observation.currency,
            "source_quality": observation.source_quality,
            "values": {
                field: _decimal_text(getattr(observation, field))
                for field in (*_PRICE_FIELDS, "volume")
            },
        }
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _logical_key(observation: MarketObservation) -> tuple[object, ...]:
        return (
            observation.listing_id,
            observation.provider,
            observation.capability,
            observation.operation,
            observation.kind,
            _iso_utc(observation.provider_observed_at),
            observation.session,
        )

    @staticmethod
    def _persist_rejection(
        connection: sqlite3.Connection,
        rejection: ObservationRejection,
    ) -> int:
        return int(
            connection.execute(
                """
                INSERT INTO market_data_rejections (
                    listing_id, provider, capability, operation, received_at,
                    reason_code, raw_payload_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rejection.listing_id,
                    rejection.provider,
                    rejection.capability,
                    rejection.operation,
                    _iso_utc(rejection.received_at),
                    rejection.reason_code,
                    rejection.raw_payload_sha256,
                ),
            ).lastrowid
        )

    @staticmethod
    def _persist_observation(
        connection: sqlite3.Connection,
        validated: ValidatedObservation,
        revision: int,
        supersedes_id: int | None,
    ) -> int:
        observation = validated.observation
        return int(
            connection.execute(
                """
                INSERT INTO market_observations (
                    listing_id, provider, capability, operation,
                    provider_observed_at, ingested_at, timezone, session, currency,
                    delay_seconds, source_quality, effective_quality, kind,
                    bid, ask, last, open, high, low, close, adjusted_close, volume,
                    observation_hash, revision, supersedes_observation_id, created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    observation.listing_id,
                    observation.provider,
                    observation.capability,
                    observation.operation,
                    _iso_utc(observation.provider_observed_at),
                    _iso_utc(observation.ingested_at),
                    observation.timezone,
                    observation.session,
                    observation.currency,
                    observation.delay_seconds,
                    observation.source_quality,
                    validated.effective_quality,
                    observation.kind,
                    _decimal_text(observation.bid),
                    _decimal_text(observation.ask),
                    _decimal_text(observation.last),
                    _decimal_text(observation.open),
                    _decimal_text(observation.high),
                    _decimal_text(observation.low),
                    _decimal_text(observation.close),
                    _decimal_text(observation.adjusted_close),
                    _decimal_text(observation.volume),
                    validated.observation_hash,
                    revision,
                    supersedes_id,
                    _iso_utc(observation.ingested_at),
                ),
            ).lastrowid
        )

    @staticmethod
    def _resolve_rejections(
        connection: sqlite3.Connection,
        observation: MarketObservation,
        observation_id: int,
        resolved_at: datetime,
    ) -> int:
        resolved_at_iso = _iso_utc(resolved_at)
        rejection_rows = connection.execute(
            """
            SELECT rejection.id
            FROM market_data_rejections AS rejection
            LEFT JOIN market_data_rejection_resolutions AS resolution
              ON resolution.rejection_id = rejection.id
            WHERE rejection.listing_id = ?
              AND rejection.provider = ?
              AND rejection.capability = ?
              AND rejection.operation = ?
              AND rejection.received_at <= ?
              AND resolution.id IS NULL
            ORDER BY rejection.id
            """,
            (
                observation.listing_id,
                observation.provider,
                observation.capability,
                observation.operation,
                resolved_at_iso,
            ),
        ).fetchall()
        for rejection in rejection_rows:
            connection.execute(
                """
                INSERT INTO market_data_rejection_resolutions (
                    rejection_id, observation_id, resolved_at
                )
                VALUES (?, ?, ?)
                """,
                (rejection["id"], observation_id, resolved_at_iso),
            )
        return len(rejection_rows)

    @staticmethod
    def _project_bar(
        connection: sqlite3.Connection,
        observation_id: int,
        observation: MarketObservation,
        supersedes_id: int | None,
    ) -> int:
        close = (
            observation.close
            or observation.last
            or observation.adjusted_close
            or observation.open
            or observation.high
            or observation.low
            or observation.bid
            or observation.ask
        )
        if close is None:
            return 0
        open_value = observation.open or close
        high_value = max(observation.high or open_value, open_value, close)
        low_value = min(observation.low or open_value, open_value, close)
        adjusted_close = observation.adjusted_close or close
        volume = observation.volume or Decimal("0")
        observed_date = observation.provider_observed_at.astimezone(
            ZoneInfo(observation.timezone)
        ).date().isoformat()
        assets = connection.execute(
            """
            SELECT id
            FROM assets
            WHERE instrument_listing_id = ?
            ORDER BY id
            """,
            (observation.listing_id,),
        ).fetchall()
        projected = 0
        for asset in assets:
            existing_rows = connection.execute(
                """
                SELECT id, observation_id
                FROM price_history
                WHERE asset_id = ? AND date = ?
                ORDER BY (observation_id IS NOT NULL) DESC,
                         is_real_data DESC,
                         id ASC
                """,
                (asset["id"], observed_date),
            ).fetchall()
            if existing_rows and existing_rows[0]["observation_id"] is not None:
                current = connection.execute(
                    """
                    SELECT id, provider_observed_at, ingested_at
                    FROM market_observations
                    WHERE id = ?
                    """,
                    (existing_rows[0]["observation_id"],),
                ).fetchone()
                if current is not None:
                    candidate_order = (
                        observation.provider_observed_at,
                        observation.ingested_at,
                        observation_id,
                    )
                    current_order = (
                        _parse_datetime(current["provider_observed_at"]),
                        _parse_datetime(current["ingested_at"]),
                        int(current["id"]),
                    )
                    is_direct_revision = supersedes_id == int(current["id"])
                    if not is_direct_revision and candidate_order < current_order:
                        continue
            values = (
                float(open_value),
                float(high_value),
                float(low_value),
                float(close),
                float(adjusted_close),
                float(volume),
                "real",
                observation.provider,
                1,
                _iso_utc(observation.ingested_at),
                observation_id,
            )
            if not existing_rows:
                connection.execute(
                    """
                    INSERT INTO price_history (
                        asset_id, date, open, high, low, close, adjusted_close,
                        volume, source, provider, is_real_data, fetched_at,
                        observation_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset["id"],
                        observed_date,
                        *values,
                        _iso_utc(observation.ingested_at),
                    ),
                )
            else:
                primary_id = int(existing_rows[0]["id"])
                connection.execute(
                    """
                    UPDATE price_history
                    SET open = ?, high = ?, low = ?, close = ?, adjusted_close = ?,
                        volume = ?, source = ?, provider = ?, is_real_data = ?,
                        fetched_at = ?, observation_id = ?
                    WHERE id = ?
                    """,
                    (*values, primary_id),
                )
                duplicate_ids = [int(row["id"]) for row in existing_rows[1:]]
                if duplicate_ids:
                    placeholders = ",".join("?" for _ in duplicate_ids)
                    connection.execute(
                        f"DELETE FROM price_history WHERE id IN ({placeholders})",
                        duplicate_ids,
                    )
            projected += 1
        return projected

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> MarketObservation:
        def decimal_value(name: str) -> Decimal | None:
            value = row[name]
            return Decimal(str(value)) if value is not None else None

        return MarketObservation(
            listing_id=int(row["listing_id"]),
            provider=str(row["provider"]),
            capability=cast(ProviderCapability, str(row["capability"])),
            operation=str(row["operation"]),
            provider_observed_at=_parse_datetime(row["provider_observed_at"]),
            ingested_at=_parse_datetime(row["ingested_at"]),
            timezone=str(row["timezone"]),
            session=str(row["session"]),
            currency=str(row["currency"]),
            delay_seconds=int(row["delay_seconds"]),
            source_quality=cast(SourceObservationQuality, str(row["source_quality"])),
            kind=cast(ObservationKind, str(row["kind"])),
            bid=decimal_value("bid"),
            ask=decimal_value("ask"),
            last=decimal_value("last"),
            open=decimal_value("open"),
            high=decimal_value("high"),
            low=decimal_value("low"),
            close=decimal_value("close"),
            adjusted_close=decimal_value("adjusted_close"),
            volume=decimal_value("volume"),
        )
