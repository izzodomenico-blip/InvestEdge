from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

ProviderCapability = Literal["CATALOG", "IDENTITY", "EOD", "QUOTE", "FX", "REFERENCE", "NEWS"]
BudgetWindow = Literal["MINUTE", "DAY", "MONTH"]
RequestOutcome = Literal[
    "SUCCEEDED",
    "CACHE_HIT",
    "RATE_LIMITED",
    "TIMED_OUT",
    "RETRY_EXHAUSTED",
    "REJECTED",
    "DISABLED",
]
AvailabilityState = Literal["AVAILABLE", "DISABLED", "COOLDOWN"]
AvailabilityReason = Literal[
    "MISSING_CREDENTIAL",
    "SECRET_IN_QUERY_POLICY",
    "BULK_ONLY_POLICY",
    "NOT_PRIMARY_POLICY",
    "OPT_IN_DISABLED",
    "RATE_LIMITED",
    "BUDGET_EXHAUSTED",
    "UNSUPPORTED_CAPABILITY",
]


@dataclass(frozen=True)
class ProviderBudgetPolicy:
    minute_limit: int | None
    daily_limit: int | None
    monthly_limit: int | None
    max_attempts: int = 3

    def __post_init__(self) -> None:
        for value in (self.minute_limit, self.daily_limit, self.monthly_limit):
            if value is not None and value < 0:
                raise ValueError("provider budget limits must be non-negative")
        if self.max_attempts < 1:
            raise ValueError("provider max_attempts must be positive")


@dataclass(frozen=True)
class ProviderAvailability:
    state: AvailabilityState
    reason_code: AvailabilityReason | None
    cooldown_until: datetime | None


class ProviderBudgetExceeded(RuntimeError):
    def __init__(
        self,
        provider: str,
        operation: str,
        window_kind: BudgetWindow | None,
        *,
        cooldown: bool = False,
    ) -> None:
        self.provider = provider
        self.operation = operation
        self.window_kind = window_kind
        self.reason_code = "RATE_LIMITED" if cooldown else "BUDGET_EXHAUSTED"
        super().__init__(f"{provider}:{operation}:{self.reason_code}")


class ProviderBudgetTransactionError(RuntimeError):
    pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _window_values(now: datetime) -> dict[BudgetWindow, str]:
    normalized = _as_utc(now)
    return {
        "MINUTE": normalized.strftime("%Y-%m-%dT%H:%M:00Z"),
        "DAY": normalized.strftime("%Y-%m-%d"),
        "MONTH": normalized.strftime("%Y-%m"),
    }


def _policy_limits(policy: ProviderBudgetPolicy) -> dict[BudgetWindow, int | None]:
    return {
        "MINUTE": policy.minute_limit,
        "DAY": policy.daily_limit,
        "MONTH": policy.monthly_limit,
    }


class ProviderBudgetManager:
    def reserve(
        self,
        connection: sqlite3.Connection,
        policy: ProviderBudgetPolicy,
        provider: str,
        operation: str,
        request_fingerprint: str,
        now: datetime,
    ) -> str:
        normalized_provider = provider.strip()
        normalized_operation = operation.strip()
        if not normalized_provider or not normalized_operation:
            raise ValueError("provider and operation are required")
        if len(request_fingerprint) != 64:
            raise ValueError("request_fingerprint must be SHA-256")

        instant = _as_utc(now)
        timestamp = _timestamp(instant)
        starts = _window_values(instant)
        projection_date = instant.astimezone().date().isoformat()
        limits = _policy_limits(policy)
        reservation_id = uuid.uuid4().hex

        self._begin_immediate(connection)
        try:
            active_cooldown = self._active_cooldown(connection, normalized_provider, instant)
            if active_cooldown is not None:
                raise ProviderBudgetExceeded(
                    normalized_provider,
                    normalized_operation,
                    None,
                    cooldown=True,
                )

            current: dict[BudgetWindow, tuple[int, int | None, int | None]] = {}
            for window_kind, window_start in starts.items():
                row = connection.execute(
                    """
                    SELECT used_count, configured_limit, effective_limit
                    FROM provider_usage_windows
                    WHERE provider = ? AND window_kind = ? AND window_start = ?
                    """,
                    (normalized_provider, window_kind, window_start),
                ).fetchone()
                used_count = int(row["used_count"]) if row is not None else 0
                if window_kind == "DAY":
                    legacy_usage = connection.execute(
                        """
                        SELECT calls_count
                        FROM api_usage
                        WHERE provider = ? AND usage_date = ?
                        """,
                        (normalized_provider, projection_date),
                    ).fetchone()
                    if legacy_usage is not None:
                        used_count = max(used_count, int(legacy_usage["calls_count"]))
                configured_limit = limits[window_kind]
                existing_effective = (
                    int(row["effective_limit"])
                    if row is not None and row["effective_limit"] is not None
                    else None
                )
                effective_limit = self._minimum_limit(configured_limit, existing_effective)
                if effective_limit is not None and used_count >= effective_limit:
                    raise ProviderBudgetExceeded(
                        normalized_provider,
                        normalized_operation,
                        cast(BudgetWindow, window_kind),
                    )
                current[window_kind] = (used_count, configured_limit, effective_limit)

            for window_kind, window_start in starts.items():
                _used, configured_limit, effective_limit = current[window_kind]
                connection.execute(
                    """
                    INSERT INTO provider_usage_windows (
                        provider, window_kind, window_start, used_count,
                        configured_limit, effective_limit, cooldown_until,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    ON CONFLICT(provider, window_kind, window_start) DO UPDATE SET
                        used_count = MAX(
                            provider_usage_windows.used_count,
                            excluded.used_count - 1
                        ) + 1,
                        configured_limit = excluded.configured_limit,
                        effective_limit = CASE
                            WHEN provider_usage_windows.effective_limit IS NULL
                                THEN excluded.effective_limit
                            WHEN excluded.effective_limit IS NULL
                                THEN provider_usage_windows.effective_limit
                            ELSE MIN(provider_usage_windows.effective_limit, excluded.effective_limit)
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        normalized_provider,
                        window_kind,
                        window_start,
                        _used + 1,
                        configured_limit,
                        effective_limit,
                        timestamp,
                        timestamp,
                    ),
                )

            connection.execute(
                """
                INSERT INTO provider_request_log (
                    reservation_id, provider, operation, request_fingerprint,
                    outcome, status_code, retry_count, cooldown_until,
                    requested_at, completed_at
                )
                VALUES (?, ?, ?, ?, NULL, NULL, 0, NULL, ?, NULL)
                """,
                (
                    reservation_id,
                    normalized_provider,
                    normalized_operation,
                    request_fingerprint,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO api_usage (
                    provider, usage_date, calls_count, daily_limit, created_at, updated_at
                )
                VALUES (?, ?, 1, ?, ?, ?)
                ON CONFLICT(provider, usage_date) DO UPDATE SET
                    calls_count = api_usage.calls_count + 1,
                    daily_limit = excluded.daily_limit,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_provider,
                    projection_date,
                    policy.daily_limit or 0,
                    timestamp,
                    timestamp,
                ),
            )
        except Exception:
            connection.rollback()
            raise
        connection.commit()
        return reservation_id

    def complete(
        self,
        connection: sqlite3.Connection,
        reservation_id: str,
        outcome: RequestOutcome,
        status_code: int | None,
        retry_count: int,
        cooldown_until: datetime | None,
    ) -> None:
        if retry_count < 0:
            raise ValueError("retry_count must be non-negative")
        self._begin_immediate(connection)
        try:
            row = connection.execute(
                "SELECT requested_at, completed_at FROM provider_request_log WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown provider reservation")
            if row["completed_at"] is not None:
                connection.commit()
                return
            completed_at = _timestamp(datetime.now(UTC))
            connection.execute(
                """
                UPDATE provider_request_log
                SET outcome = ?, status_code = ?, retry_count = ?,
                    cooldown_until = ?, completed_at = ?
                WHERE reservation_id = ? AND completed_at IS NULL
                """,
                (
                    outcome,
                    status_code,
                    retry_count,
                    _timestamp(cooldown_until) if cooldown_until else None,
                    completed_at,
                    reservation_id,
                ),
            )
        except Exception:
            connection.rollback()
            raise
        connection.commit()

    def record_cache_hit(
        self,
        connection: sqlite3.Connection,
        provider: str,
        operation: str,
        request_fingerprint: str,
        now: datetime,
    ) -> None:
        self._begin_immediate(connection)
        try:
            timestamp = _timestamp(now)
            connection.execute(
                """
                INSERT INTO provider_request_log (
                    reservation_id, provider, operation, request_fingerprint,
                    outcome, status_code, retry_count, cooldown_until,
                    requested_at, completed_at
                )
                VALUES (?, ?, ?, ?, 'CACHE_HIT', NULL, 0, NULL, ?, ?)
                """,
                (uuid.uuid4().hex, provider, operation, request_fingerprint, timestamp, timestamp),
            )
        except Exception:
            connection.rollback()
            raise
        connection.commit()

    def restrict(
        self,
        connection: sqlite3.Connection,
        provider: str,
        now: datetime,
        *,
        minute_limit: int | None,
        remaining: int | None,
        cooldown_until: datetime | None,
    ) -> None:
        starts = _window_values(now)
        timestamp = _timestamp(now)
        self._begin_immediate(connection)
        try:
            if minute_limit is not None or remaining is not None:
                row = connection.execute(
                    """
                    SELECT used_count, effective_limit
                    FROM provider_usage_windows
                    WHERE provider = ? AND window_kind = 'MINUTE' AND window_start = ?
                    """,
                    (provider, starts["MINUTE"]),
                ).fetchone()
                if row is not None:
                    used_count = int(row["used_count"])
                    effective_limit = (
                        int(row["effective_limit"])
                        if row["effective_limit"] is not None
                        else None
                    )
                    effective_limit = self._minimum_limit(effective_limit, minute_limit)
                    if remaining is not None and effective_limit is not None:
                        used_count = max(used_count, effective_limit - max(remaining, 0))
                    connection.execute(
                        """
                        UPDATE provider_usage_windows
                        SET used_count = ?, effective_limit = ?, updated_at = ?
                        WHERE provider = ? AND window_kind = 'MINUTE' AND window_start = ?
                        """,
                        (used_count, effective_limit, timestamp, provider, starts["MINUTE"]),
                    )
            if cooldown_until is not None:
                connection.execute(
                    """
                    UPDATE provider_usage_windows
                    SET cooldown_until = CASE
                            WHEN cooldown_until IS NULL OR cooldown_until < ? THEN ?
                            ELSE cooldown_until
                        END,
                        updated_at = ?
                    WHERE provider = ?
                      AND (window_kind, window_start) IN (
                          ('MINUTE', ?), ('DAY', ?), ('MONTH', ?)
                      )
                    """,
                    (
                        _timestamp(cooldown_until),
                        _timestamp(cooldown_until),
                        timestamp,
                        provider,
                        starts["MINUTE"],
                        starts["DAY"],
                        starts["MONTH"],
                    ),
                )
        except Exception:
            connection.rollback()
            raise
        connection.commit()

    def availability(
        self,
        connection: sqlite3.Connection,
        policy: ProviderBudgetPolicy,
        provider: str,
        now: datetime,
    ) -> ProviderAvailability:
        instant = _as_utc(now)
        cooldown = self._active_cooldown(connection, provider, instant)
        if cooldown is not None:
            return ProviderAvailability("COOLDOWN", "RATE_LIMITED", cooldown)
        starts = _window_values(instant)
        for window_kind, configured_limit in _policy_limits(policy).items():
            row = connection.execute(
                """
                SELECT used_count, effective_limit
                FROM provider_usage_windows
                WHERE provider = ? AND window_kind = ? AND window_start = ?
                """,
                (provider, window_kind, starts[window_kind]),
            ).fetchone()
            if row is None:
                continue
            effective_limit = self._minimum_limit(
                configured_limit,
                int(row["effective_limit"]) if row["effective_limit"] is not None else None,
            )
            if effective_limit is not None and int(row["used_count"]) >= effective_limit:
                return ProviderAvailability("DISABLED", "BUDGET_EXHAUSTED", None)
        return ProviderAvailability("AVAILABLE", None, None)

    @staticmethod
    def _minimum_limit(first: int | None, second: int | None) -> int | None:
        if first is None:
            return second
        if second is None:
            return first
        return min(first, second)

    @staticmethod
    def _begin_immediate(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            raise ProviderBudgetTransactionError(
                "provider budget requires a connection without an active transaction"
            )
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _active_cooldown(
        connection: sqlite3.Connection,
        provider: str,
        now: datetime,
    ) -> datetime | None:
        row = connection.execute(
            "SELECT MAX(cooldown_until) AS cooldown_until FROM provider_usage_windows WHERE provider = ?",
            (provider,),
        ).fetchone()
        cooldown = _parse_timestamp(row["cooldown_until"] if row is not None else None)
        return cooldown if cooldown is not None and cooldown > now else None
