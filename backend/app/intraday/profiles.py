"""Public Alpaca configuration checks. No network, persistence or credentials in profiles."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict

from backend.app.config import Settings
from backend.app.intraday.contracts import FeedProfile, IntradayError, ReasonCode
from backend.app.services.provider_budget_service import ProviderBudgetPolicy

REST_CAPABILITIES = frozenset({"bars", "quotes", "news", "assets", "calendar", "corporate_actions"})


def profile_from_settings(
    settings: Settings, *, attested_capabilities: tuple[str, ...],
    required_capabilities: tuple[str, ...] = ("bars", "quotes", "news", "status"),
    quote_conditions: tuple[str, ...] = (),
) -> FeedProfile:
    if settings.alpaca_feed is None:
        raise IntradayError(ReasonCode.PROFILE_INVALID)
    profile = FeedProfile(
        feed=settings.alpaca_feed, required_capabilities=required_capabilities,
        attested_capabilities=attested_capabilities, quote_conditions=quote_conditions,
        max_symbols=settings.alpaca_max_symbols, max_connections=settings.alpaca_max_connections,
        http_minute_limit=settings.alpaca_http_minute_limit,
        http_daily_limit=settings.alpaca_http_daily_limit,
        http_monthly_limit=settings.alpaca_http_monthly_limit,
        max_frame_bytes=settings.alpaca_max_frame_bytes,
        max_queue_events=settings.alpaca_max_queue_events,
        max_archive_bytes=settings.alpaca_max_archive_bytes,
    )
    if profile_has_secret(settings, profile):
        raise IntradayError(ReasonCode.PROFILE_INVALID)
    return profile


def configuration_reason(settings: Settings, profile: FeedProfile, capability: str) -> str | None:
    if not settings.enable_real_data or not settings.enable_alpaca_data:
        return "REAL_DATA_DISABLED"
    for credential in (settings.alpaca_api_key_id, settings.alpaca_api_secret_key):
        if not isinstance(credential, str) or not credential.strip():
            return "MISSING_CREDENTIAL"
        if len(credential) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in credential):
            return "MISSING_CREDENTIAL"
    if (not isinstance(profile, FeedProfile) or profile.provider != "alpaca"
            or settings.alpaca_feed is None or profile_has_secret(settings, profile)):
        return "PROFILE_INVALID"
    if capability not in REST_CAPABILITIES:
        return "UNSUPPORTED_CAPABILITY"
    if settings.alpaca_feed != profile.feed or capability not in profile.attested_capabilities:
        return "FEED_NOT_ENTITLED"
    for configured, frozen in (
        (settings.alpaca_max_symbols, profile.max_symbols),
        (settings.alpaca_http_minute_limit, profile.http_minute_limit),
        (settings.alpaca_http_daily_limit, profile.http_daily_limit),
        (settings.alpaca_http_monthly_limit, profile.http_monthly_limit),
        (settings.alpaca_max_frame_bytes, profile.max_frame_bytes),
    ):
        if type(configured) is not int or configured <= 0 or frozen <= 0:
            return "BUDGET_UNATTESTED"
    for value in (settings.provider_http_connect_timeout_seconds, settings.provider_http_read_timeout_seconds):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            return "PROFILE_INVALID"
    if type(settings.provider_default_max_attempts) is not int or settings.provider_default_max_attempts <= 0:
        return "PROFILE_INVALID"
    if type(settings.provider_retry_after_cap_seconds) is not int or settings.provider_retry_after_cap_seconds < 0:
        return "PROFILE_INVALID"
    return None


def account_budget_policy(settings: Settings, profile: FeedProfile) -> ProviderBudgetPolicy:
    """One public 'alpaca' bucket per DB/account, never a new quota per feed or capability."""
    return ProviderBudgetPolicy(
        minute_limit=min(settings.alpaca_http_minute_limit, profile.http_minute_limit),
        daily_limit=min(settings.alpaca_http_daily_limit, profile.http_daily_limit),
        monthly_limit=min(settings.alpaca_http_monthly_limit, profile.http_monthly_limit),
        max_attempts=min(settings.provider_default_max_attempts, 3),
    )


def profile_has_secret(settings: Settings, profile: FeedProfile) -> bool:
    """Inspect decoded fields before public serialization or profile hashing."""
    secrets = tuple(value for name, value in vars(settings).items()
                    if (name.lower().endswith(("_api_key", "_token", "_chat_id"))
                        or name.lower() in {"alpaca_api_key_id", "alpaca_api_secret_key"})
                    and isinstance(value, str) and value)
    def contains(value):
        if isinstance(value, Mapping):
            return any(contains(key) or contains(item) for key, item in value.items())
        if isinstance(value, str):
            return any(secret in value for secret in secrets)
        if isinstance(value, Sequence):
            return any(contains(item) for item in value)
        return any(secret in str(value) for secret in secrets)
    return not isinstance(profile, FeedProfile) or contains(asdict(profile))


def public_profile(profile: FeedProfile, *, settings: Settings) -> dict[str, object]:
    if profile_has_secret(settings, profile):
        raise IntradayError(ReasonCode.PROFILE_INVALID)
    return json.loads(profile.config_json)
