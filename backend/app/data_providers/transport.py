from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import sqlite3
import threading
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from backend.app.config import Settings, get_settings
from backend.app.services.provider_budget_service import (
    ProviderBudgetExceeded,
    ProviderBudgetManager,
    ProviderBudgetPolicy,
    RequestOutcome,
)

HttpMethod = Literal["GET", "POST"]
Decoder = Literal["json", "csv", "bytes"]

_SENSITIVE_QUERY_KEYS = frozenset({"apikey", "api_key", "token", "access_token", "key"})
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,200}$")
_CONTENT_TYPES: dict[Decoder, tuple[str, ...]] = {
    "json": ("application/json",),
    "csv": ("text/csv", "application/csv"),
    "bytes": (
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/xml",
        "text/xml",
    ),
}


@dataclass(frozen=True)
class ProviderResponse:
    status_code: int
    payload: object
    from_cache: bool
    attempts: int
    request_fingerprint: str


class SafeProviderTransportError(RuntimeError):
    def __init__(self, provider: str, operation: str, code: str) -> None:
        self.provider = provider
        self.operation = operation
        self.code = code
        super().__init__(f"{provider}:{operation}:{code}")


@dataclass
class _InflightEntry:
    event: threading.Event = field(default_factory=threading.Event)
    response: ProviderResponse | None = None
    error: SafeProviderTransportError | ProviderBudgetExceeded | None = None


@dataclass
class _SharedState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    inflight: dict[str, _InflightEntry] = field(default_factory=dict)


_DEFAULT_SHARED_STATE = _SharedState()


@dataclass(frozen=True)
class _PreparedRequest:
    method: HttpMethod
    url: str
    host: str
    path: str
    params: dict[str, str]
    canonical_body: bytes
    request_fingerprint: str


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


class SafeProviderTransport:
    def __init__(
        self,
        *,
        allowed_hosts: set[str] | frozenset[str] | None = None,
        client: httpx.Client | None = None,
        budget_manager: ProviderBudgetManager | None = None,
        settings: Settings | None = None,
        shared_state: _SharedState | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._allowed_hosts = frozenset(host.strip().lower() for host in (allowed_hosts or set()) if host.strip())
        self._settings = settings or get_settings()
        self._budget_manager = budget_manager or ProviderBudgetManager()
        self._client = client or httpx.Client(follow_redirects=False)
        self._shared_state = shared_state or _DEFAULT_SHARED_STATE
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def budget_manager(self) -> ProviderBudgetManager:
        return self._budget_manager

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return self._allowed_hosts

    def with_client(self, client: httpx.Client) -> SafeProviderTransport:
        return SafeProviderTransport(
            allowed_hosts=self._allowed_hosts,
            client=client,
            budget_manager=self._budget_manager,
            settings=self._settings,
            shared_state=self._shared_state,
            clock=self._clock,
        )

    def with_budget_manager(self, budget_manager: ProviderBudgetManager) -> SafeProviderTransport:
        return SafeProviderTransport(
            allowed_hosts=self._allowed_hosts,
            client=self._client,
            budget_manager=budget_manager,
            settings=self._settings,
            shared_state=self._shared_state,
            clock=self._clock,
        )

    def request(
        self,
        connection: sqlite3.Connection,
        policy: ProviderBudgetPolicy,
        provider: str,
        method: HttpMethod,
        base_url: str,
        path: str,
        headers: Mapping[str, str],
        params: Mapping[str, str],
        json_body: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
        operation: str,
        cache_scope: str,
        cache_ttl_seconds: int,
        max_response_bytes: int,
        decoder: Decoder,
        now: datetime,
        sleeper: Callable[[float], None],
        bypass_cache: bool = False,
    ) -> ProviderResponse:
        normalized_provider, normalized_operation, normalized_scope = self._validate_labels(
            provider,
            operation,
            cache_scope,
        )
        if cache_ttl_seconds < 0 or max_response_bytes < 1:
            raise SafeProviderTransportError(normalized_provider, normalized_operation, "INVALID_LIMIT")
        if decoder not in _CONTENT_TYPES:
            raise SafeProviderTransportError(normalized_provider, normalized_operation, "INVALID_DECODER")
        prepared = self._prepare_request(
            normalized_provider,
            normalized_operation,
            method,
            base_url,
            path,
            params,
            json_body,
            enforce_allowlist=True,
        )
        safe_headers = self._validate_headers(headers, normalized_provider, normalized_operation)

        if not bypass_cache:
            cached = self._lookup_cache(
                connection,
                normalized_provider,
                normalized_operation,
                normalized_scope,
                prepared.request_fingerprint,
                decoder,
                now,
                record_hit=False,
            )
            if cached is not None:
                try:
                    self._reject_secret_echo(
                        cached.payload,
                        safe_headers,
                        normalized_provider,
                        normalized_operation,
                    )
                except SafeProviderTransportError:
                    self._purge_cache(
                        connection,
                        normalized_provider,
                        normalized_scope,
                        prepared.request_fingerprint,
                    )
                    raise
                self._budget_manager.record_cache_hit(
                    connection,
                    normalized_provider,
                    normalized_operation,
                    prepared.request_fingerprint,
                    now,
                )
                return cached
        if self._client.is_closed:
            raise SafeProviderTransportError(
                normalized_provider,
                normalized_operation,
                "CLIENT_CLOSED",
            )

        entry, owner = self._acquire_inflight(prepared.request_fingerprint)
        if not owner:
            entry.event.wait()
            if entry.error is not None:
                raise entry.error
            if entry.response is None:
                raise SafeProviderTransportError(
                    normalized_provider,
                    normalized_operation,
                    "INFLIGHT_FAILED",
                )
            return entry.response

        try:
            response = self._send_with_retries(
                connection=connection,
                policy=policy,
                provider=normalized_provider,
                operation=normalized_operation,
                cache_scope=normalized_scope,
                prepared=prepared,
                headers=headers,
                json_body=json_body,
                cache_ttl_seconds=cache_ttl_seconds,
                max_response_bytes=max_response_bytes,
                decoder=decoder,
                now=now,
                sleeper=sleeper,
            )
        except (SafeProviderTransportError, ProviderBudgetExceeded) as exc:
            self._publish(prepared.request_fingerprint, entry, error=exc)
            raise
        except Exception:
            error = SafeProviderTransportError(
                normalized_provider,
                normalized_operation,
                "TRANSPORT_FAILED",
            )
            self._publish(prepared.request_fingerprint, entry, error=error)
            raise error from None
        self._publish(prepared.request_fingerprint, entry, response=response)
        return response

    def cached_response_for_url(
        self,
        connection: sqlite3.Connection,
        *,
        provider: str,
        operation: str,
        cache_scope: str,
        request_url: str,
        now: datetime,
        headers: Mapping[str, str] | None = None,
        decoder: Decoder = "json",
        bypass_cache: bool = False,
    ) -> ProviderResponse | None:
        normalized_provider, normalized_operation, normalized_scope = self._validate_labels(
            provider,
            operation,
            cache_scope,
        )
        prepared = self.prepare_legacy_url(
            normalized_provider,
            normalized_operation,
            "GET",
            request_url,
            None,
            enforce_allowlist=False,
        )
        if bypass_cache:
            return None
        safe_headers = self._validate_headers(
            headers or {},
            normalized_provider,
            normalized_operation,
        )
        cached = self._lookup_cache(
            connection,
            normalized_provider,
            normalized_operation,
            normalized_scope,
            prepared.request_fingerprint,
            decoder,
            now,
            record_hit=False,
        )
        if cached is None:
            return None
        try:
            self._reject_secret_echo(
                cached.payload,
                safe_headers,
                normalized_provider,
                normalized_operation,
            )
        except SafeProviderTransportError:
            self._purge_cache(
                connection,
                normalized_provider,
                normalized_scope,
                prepared.request_fingerprint,
            )
            raise
        self._budget_manager.record_cache_hit(
            connection,
            normalized_provider,
            normalized_operation,
            prepared.request_fingerprint,
            now,
        )
        return cached

    def store_response_for_url(
        self,
        connection: sqlite3.Connection,
        *,
        provider: str,
        operation: str,
        cache_scope: str,
        request_url: str,
        payload: object,
        status_code: int,
        cache_ttl_seconds: int,
        now: datetime,
        decoder: Decoder = "json",
    ) -> str:
        normalized_provider, normalized_operation, normalized_scope = self._validate_labels(
            provider,
            operation,
            cache_scope,
        )
        prepared = self.prepare_legacy_url(
            normalized_provider,
            normalized_operation,
            "GET",
            request_url,
            None,
            enforce_allowlist=False,
        )
        self._reject_secret_echo(
            payload,
            {},
            normalized_provider,
            normalized_operation,
        )
        self._save_cache(
            connection,
            normalized_provider,
            normalized_scope,
            prepared.request_fingerprint,
            status_code,
            payload,
            decoder,
            now,
            cache_ttl_seconds,
        )
        return prepared.request_fingerprint

    def request_url(
        self,
        *,
        connection: sqlite3.Connection,
        policy: ProviderBudgetPolicy,
        provider: str,
        operation: str,
        cache_scope: str,
        request_url: str,
        headers: Mapping[str, str],
        cache_ttl_seconds: int,
        max_response_bytes: int,
        decoder: Decoder,
        now: datetime,
        sleeper: Callable[[float], None] = time.sleep,
        bypass_cache: bool = False,
    ) -> ProviderResponse:
        prepared = self.prepare_legacy_url(
            provider,
            operation,
            "GET",
            request_url,
            None,
            enforce_allowlist=True,
        )
        parsed = urlsplit(prepared.url)
        base_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        return self.request(
            connection=connection,
            policy=policy,
            provider=provider,
            method="GET",
            base_url=base_url,
            path=prepared.path,
            headers=headers,
            params=prepared.params,
            json_body=None,
            operation=operation,
            cache_scope=cache_scope,
            cache_ttl_seconds=cache_ttl_seconds,
            max_response_bytes=max_response_bytes,
            decoder=decoder,
            now=now,
            sleeper=sleeper,
            bypass_cache=bypass_cache,
        )

    def prepare_legacy_url(
        self,
        provider: str,
        operation: str,
        method: HttpMethod,
        request_url: str,
        json_body: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
        *,
        enforce_allowlist: bool,
    ) -> _PreparedRequest:
        parsed = urlsplit(request_url)
        if parsed.fragment:
            raise SafeProviderTransportError(provider, operation, "INVALID_BASE_URL")
        try:
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            raise SafeProviderTransportError(provider, operation, "INVALID_QUERY") from None
        params: dict[str, str] = {}
        for key, value in pairs:
            if key in params:
                raise SafeProviderTransportError(provider, operation, "DUPLICATE_QUERY_PARAMETER")
            params[key] = value
        base_url = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        return self._prepare_request(
            provider,
            operation,
            method,
            base_url,
            parsed.path or "/",
            params,
            json_body,
            enforce_allowlist=enforce_allowlist,
        )

    def _prepare_request(
        self,
        provider: str,
        operation: str,
        method: str,
        base_url: str,
        path: str,
        params: Mapping[str, str],
        json_body: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
        *,
        enforce_allowlist: bool,
    ) -> _PreparedRequest:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "POST"}:
            raise SafeProviderTransportError(provider, operation, "METHOD_NOT_ALLOWED")
        parsed_base = urlsplit(base_url)
        if parsed_base.scheme.lower() != "https":
            raise SafeProviderTransportError(provider, operation, "HTTPS_REQUIRED")
        if (
            not parsed_base.hostname
            or parsed_base.username is not None
            or parsed_base.password is not None
            or parsed_base.query
            or parsed_base.fragment
            or parsed_base.path not in {"", "/"}
        ):
            raise SafeProviderTransportError(provider, operation, "INVALID_BASE_URL")
        try:
            port = parsed_base.port
        except ValueError:
            raise SafeProviderTransportError(provider, operation, "INVALID_BASE_URL") from None
        if port not in {None, 443}:
            raise SafeProviderTransportError(provider, operation, "INVALID_BASE_URL")
        host = parsed_base.hostname.lower()
        if enforce_allowlist and host not in self._allowed_hosts:
            raise SafeProviderTransportError(provider, operation, "HOST_NOT_ALLOWED")

        parsed_path = urlsplit(path)
        if (
            not path.startswith("/")
            or parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.query
            or parsed_path.fragment
            or "\\" in path
            or any(ord(character) < 32 for character in path)
        ):
            raise SafeProviderTransportError(provider, operation, "INVALID_PATH")

        normalized_params: dict[str, str] = {}
        for raw_key, raw_value in params.items():
            key = str(raw_key)
            value = str(raw_value)
            if key.strip().lower() in _SENSITIVE_QUERY_KEYS:
                raise SafeProviderTransportError(provider, operation, "SECRET_IN_QUERY")
            if not key or any(ord(character) < 32 for character in key + value):
                raise SafeProviderTransportError(provider, operation, "INVALID_QUERY")
            normalized_params[key] = value

        canonical_body = self._canonical_json_body(provider, operation, json_body)
        body_hash = hashlib.sha256(canonical_body).hexdigest()
        canonical_params = urlencode(sorted(normalized_params.items()), doseq=False)
        fingerprint_material = "\n".join(
            (
                provider,
                operation,
                normalized_method,
                host,
                parsed_path.path,
                canonical_params,
                body_hash,
            )
        )
        request_fingerprint = hashlib.sha256(fingerprint_material.encode("utf-8")).hexdigest()
        url = urlunsplit(("https", parsed_base.netloc, parsed_path.path, "", ""))
        return _PreparedRequest(
            method=cast(HttpMethod, normalized_method),
            url=url,
            host=host,
            path=parsed_path.path,
            params=normalized_params,
            canonical_body=canonical_body,
            request_fingerprint=request_fingerprint,
        )

    @staticmethod
    def _canonical_json_body(
        provider: str,
        operation: str,
        json_body: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
    ) -> bytes:
        if json_body is None:
            return b""
        if not isinstance(json_body, Mapping) and (
            not isinstance(json_body, Sequence) or isinstance(json_body, (str, bytes, bytearray))
        ):
            raise SafeProviderTransportError(provider, operation, "INVALID_JSON_BODY")
        try:
            return json.dumps(
                json_body,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise SafeProviderTransportError(provider, operation, "INVALID_JSON_BODY") from None

    def _send_with_retries(
        self,
        *,
        connection: sqlite3.Connection,
        policy: ProviderBudgetPolicy,
        provider: str,
        operation: str,
        cache_scope: str,
        prepared: _PreparedRequest,
        headers: Mapping[str, str],
        json_body: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
        cache_ttl_seconds: int,
        max_response_bytes: int,
        decoder: Decoder,
        now: datetime,
        sleeper: Callable[[float], None],
    ) -> ProviderResponse:
        max_attempts = min(policy.max_attempts, self._settings.provider_default_max_attempts, 3)
        attempts = 0
        elapsed_seconds = 0.0
        timeout = httpx.Timeout(
            connect=self._settings.provider_http_connect_timeout_seconds,
            read=self._settings.provider_http_read_timeout_seconds,
            write=self._settings.provider_http_read_timeout_seconds,
            pool=self._settings.provider_http_connect_timeout_seconds,
        )
        safe_headers = self._validate_headers(headers, provider, operation)

        while attempts < max_attempts:
            attempt_now = _as_utc(now) + timedelta(seconds=elapsed_seconds)
            attempts += 1
            try:
                response_stream = self._client.stream(
                    prepared.method,
                    prepared.url,
                    headers=safe_headers,
                    params=prepared.params,
                    json=json_body,
                    timeout=timeout,
                    follow_redirects=False,
                )
            except Exception:
                raise SafeProviderTransportError(provider, operation, "REQUEST_FAILED") from None
            reservation_id = self._budget_manager.reserve(
                connection,
                policy,
                provider,
                operation,
                prepared.request_fingerprint,
                attempt_now,
            )
            try:
                with response_stream as response:
                    status_code = response.status_code
                    if status_code == 304:
                        # Risposta condizionale (If-Modified-Since): chiamata riuscita,
                        # nessun payload e nessuna cache; il chiamante decide.
                        self._budget_manager.complete(
                            connection,
                            reservation_id,
                            "SUCCEEDED",
                            status_code,
                            attempts - 1,
                            None,
                        )
                        raise SafeProviderTransportError(provider, operation, "NOT_MODIFIED")
                    if 300 <= status_code < 400:
                        self._budget_manager.complete(
                            connection,
                            reservation_id,
                            "REJECTED",
                            status_code,
                            attempts - 1,
                            None,
                        )
                        raise SafeProviderTransportError(provider, operation, "REDIRECT_REJECTED")

                    minute_limit, remaining, cooldown = self._rate_limit_state(
                        response.headers,
                        attempt_now,
                        status_code,
                    )
                    if minute_limit is not None or remaining is not None or cooldown is not None:
                        self._budget_manager.restrict(
                            connection,
                            provider,
                            attempt_now,
                            minute_limit=minute_limit,
                            remaining=remaining,
                            cooldown_until=cooldown,
                        )

                    if status_code in _RETRYABLE_STATUS_CODES:
                        outcome: RequestOutcome
                        if status_code == 429:
                            outcome = "RATE_LIMITED"
                        elif attempts >= max_attempts:
                            outcome = "RETRY_EXHAUSTED"
                        else:
                            outcome = "REJECTED"
                        self._budget_manager.complete(
                            connection,
                            reservation_id,
                            outcome,
                            status_code,
                            attempts - 1,
                            cooldown,
                        )
                        if attempts >= max_attempts:
                            code = "RATE_LIMITED" if status_code == 429 else "RETRY_EXHAUSTED"
                            raise SafeProviderTransportError(provider, operation, code)
                        delay = self._retry_delay(attempts - 1, attempt_now, cooldown)
                        self._sleep(sleeper, delay, provider, operation)
                        elapsed_seconds += delay
                        continue

                    if not 200 <= status_code < 300:
                        self._budget_manager.complete(
                            connection,
                            reservation_id,
                            "REJECTED",
                            status_code,
                            attempts - 1,
                            cooldown,
                        )
                        raise SafeProviderTransportError(provider, operation, f"HTTP_{status_code}")

                    try:
                        self._validate_content_type(response, decoder, provider, operation)
                        raw_payload = self._read_limited(
                            response,
                            max_response_bytes,
                            provider,
                            operation,
                        )
                        payload = self._decode(raw_payload, decoder, provider, operation)
                        self._reject_secret_echo(
                            payload,
                            safe_headers,
                            provider,
                            operation,
                        )
                    except SafeProviderTransportError:
                        self._budget_manager.complete(
                            connection,
                            reservation_id,
                            "REJECTED",
                            status_code,
                            attempts - 1,
                            cooldown,
                        )
                        raise
                    self._budget_manager.complete(
                        connection,
                        reservation_id,
                        "SUCCEEDED",
                        status_code,
                        attempts - 1,
                        cooldown,
                    )
                    self._save_cache(
                        connection,
                        provider,
                        cache_scope,
                        prepared.request_fingerprint,
                        status_code,
                        payload,
                        decoder,
                        attempt_now,
                        cache_ttl_seconds,
                    )
                    return ProviderResponse(
                        status_code=status_code,
                        payload=payload,
                        from_cache=False,
                        attempts=attempts,
                        request_fingerprint=prepared.request_fingerprint,
                    )
            except httpx.TimeoutException:
                outcome = "RETRY_EXHAUSTED" if attempts >= max_attempts else "TIMED_OUT"
                self._budget_manager.complete(
                    connection,
                    reservation_id,
                    outcome,
                    None,
                    attempts - 1,
                    None,
                )
                if attempts >= max_attempts:
                    raise SafeProviderTransportError(provider, operation, "RETRY_EXHAUSTED") from None
                delay = float(min(2 ** (attempts - 1), 8))
                self._sleep(sleeper, delay, provider, operation)
                elapsed_seconds += delay
            except SafeProviderTransportError:
                raise
            except httpx.HTTPError:
                self._budget_manager.complete(
                    connection,
                    reservation_id,
                    "REJECTED",
                    None,
                    attempts - 1,
                    None,
                )
                raise SafeProviderTransportError(provider, operation, "REQUEST_FAILED") from None
            except Exception:
                self._budget_manager.complete(
                    connection,
                    reservation_id,
                    "REJECTED",
                    None,
                    attempts - 1,
                    None,
                )
                raise SafeProviderTransportError(provider, operation, "REQUEST_FAILED") from None

        raise SafeProviderTransportError(provider, operation, "RETRY_EXHAUSTED")

    def _lookup_cache(
        self,
        connection: sqlite3.Connection,
        provider: str,
        operation: str,
        cache_scope: str,
        request_fingerprint: str,
        decoder: Decoder,
        now: datetime,
        *,
        record_hit: bool,
    ) -> ProviderResponse | None:
        row = connection.execute(
            """
            SELECT response_json, payload, expires_at
            FROM api_cache
            WHERE cache_key = ?
            LIMIT 1
            """,
            (self._cache_key(provider, cache_scope, request_fingerprint),),
        ).fetchone()
        if row is None:
            return None
        expires_at = _parse_timestamp(row["expires_at"])
        if expires_at is None or expires_at <= _as_utc(now):
            return None
        serialized = row["response_json"] or row["payload"]
        if not serialized:
            return None
        try:
            envelope = json.loads(serialized)
            status_code = int(envelope["status_code"])
            cached_decoder = str(envelope["decoder"])
            if cached_decoder != decoder:
                return None
            payload = self._deserialize_payload(envelope["payload"], decoder)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if record_hit:
            self._budget_manager.record_cache_hit(
                connection,
                provider,
                operation,
                request_fingerprint,
                now,
            )
        return ProviderResponse(
            status_code=status_code,
            payload=payload,
            from_cache=True,
            attempts=0,
            request_fingerprint=request_fingerprint,
        )

    def _save_cache(
        self,
        connection: sqlite3.Connection,
        provider: str,
        cache_scope: str,
        request_fingerprint: str,
        status_code: int,
        payload: object,
        decoder: Decoder,
        now: datetime,
        cache_ttl_seconds: int,
    ) -> None:
        instant = _as_utc(now)
        serialized = json.dumps(
            {
                "status_code": status_code,
                "decoder": decoder,
                "payload": self._serialize_payload(payload, decoder),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        cache_key = self._cache_key(provider, cache_scope, request_fingerprint)
        connection.execute(
            """
            INSERT INTO api_cache (
                cache_key, provider, endpoint, symbol, request_url_hash,
                response_json, payload, status, last_update, expires_at, created_at
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, 'OK', ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                response_json = excluded.response_json,
                payload = excluded.payload,
                status = excluded.status,
                last_update = excluded.last_update,
                expires_at = excluded.expires_at
            """,
            (
                cache_key,
                provider,
                cache_scope,
                request_fingerprint,
                serialized,
                serialized,
                _timestamp(instant),
                _timestamp(instant + timedelta(seconds=cache_ttl_seconds)),
                _timestamp(instant),
            ),
        )
        connection.commit()

    @staticmethod
    def _purge_cache(
        connection: sqlite3.Connection,
        provider: str,
        cache_scope: str,
        request_fingerprint: str,
    ) -> None:
        owns_transaction = not connection.in_transaction
        connection.execute(
            "DELETE FROM api_cache WHERE cache_key = ?",
            (SafeProviderTransport._cache_key(provider, cache_scope, request_fingerprint),),
        )
        if owns_transaction:
            connection.commit()

    @staticmethod
    def _serialize_payload(payload: object, decoder: Decoder) -> object:
        if decoder == "bytes":
            if not isinstance(payload, bytes):
                raise TypeError("bytes decoder payload must be bytes")
            return base64.b64encode(payload).decode("ascii")
        return payload

    @staticmethod
    def _deserialize_payload(payload: object, decoder: Decoder) -> object:
        if decoder == "bytes":
            if not isinstance(payload, str):
                raise TypeError("cached bytes payload must be text")
            return base64.b64decode(payload.encode("ascii"), validate=True)
        return payload

    @staticmethod
    def _cache_key(provider: str, cache_scope: str, request_fingerprint: str) -> str:
        return f"provider:{provider}:{cache_scope}:{request_fingerprint}"

    @staticmethod
    def _validate_content_type(
        response: httpx.Response,
        decoder: Decoder,
        provider: str,
        operation: str,
    ) -> None:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        allowed = _CONTENT_TYPES[decoder]
        accepted = content_type in allowed or (decoder == "json" and content_type.endswith("+json"))
        if not accepted:
            raise SafeProviderTransportError(provider, operation, "UNEXPECTED_CONTENT_TYPE")

    @staticmethod
    def _read_limited(
        response: httpx.Response,
        max_response_bytes: int,
        provider: str,
        operation: str,
    ) -> bytes:
        if response.is_stream_consumed:
            materialized = response.content
            if len(materialized) > max_response_bytes:
                raise SafeProviderTransportError(provider, operation, "RESPONSE_TOO_LARGE")
            return bytes(materialized)
        payload = bytearray()
        content_encoding = response.headers.get("content-encoding", "").strip().lower()
        if content_encoding in {"", "identity"}:
            for chunk in response.iter_raw(chunk_size=min(64 * 1024, max_response_bytes + 1)):
                SafeProviderTransport._extend_limited(
                    payload,
                    chunk,
                    max_response_bytes,
                    provider,
                    operation,
                )
            return bytes(payload)
        if content_encoding not in {"gzip", "deflate"}:
            raise SafeProviderTransportError(provider, operation, "UNSUPPORTED_CONTENT_ENCODING")

        window_bits = 16 + zlib.MAX_WBITS if content_encoding == "gzip" else zlib.MAX_WBITS
        decompressor = zlib.decompressobj(window_bits)
        try:
            for raw_chunk in response.iter_raw(chunk_size=64 * 1024):
                pending = raw_chunk
                while pending:
                    remaining = max_response_bytes - len(payload)
                    decoded = decompressor.decompress(pending, remaining + 1)
                    SafeProviderTransport._extend_limited(
                        payload,
                        decoded,
                        max_response_bytes,
                        provider,
                        operation,
                    )
                    pending = decompressor.unconsumed_tail
                    if pending and len(payload) >= max_response_bytes:
                        raise SafeProviderTransportError(
                            provider,
                            operation,
                            "RESPONSE_TOO_LARGE",
                        )
            remaining = max_response_bytes - len(payload)
            decoded = decompressor.flush(remaining + 1)
            SafeProviderTransport._extend_limited(
                payload,
                decoded,
                max_response_bytes,
                provider,
                operation,
            )
        except zlib.error:
            raise SafeProviderTransportError(provider, operation, "DECODE_FAILED") from None
        if not decompressor.eof or decompressor.unused_data:
            raise SafeProviderTransportError(provider, operation, "DECODE_FAILED")
        return bytes(payload)

    @staticmethod
    def _extend_limited(
        payload: bytearray,
        chunk: bytes,
        max_response_bytes: int,
        provider: str,
        operation: str,
    ) -> None:
        if len(chunk) > max_response_bytes - len(payload):
            raise SafeProviderTransportError(provider, operation, "RESPONSE_TOO_LARGE")
        payload.extend(chunk)

    @staticmethod
    def _validate_headers(
        headers: Mapping[str, str],
        provider: str,
        operation: str,
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_value in headers.items():
            key = str(raw_key)
            value = str(raw_value)
            if (
                not key
                or any(ord(character) < 33 or ord(character) > 126 for character in key)
                or any(character in "\r\n" for character in value)
            ):
                raise SafeProviderTransportError(provider, operation, "INVALID_HEADER")
            normalized[key] = value
        return normalized

    def _reject_secret_echo(
        self,
        payload: object,
        headers: Mapping[str, str],
        provider: str,
        operation: str,
    ) -> None:
        candidates: set[str] = set()
        for setting_name, setting_value in vars(self._settings).items():
            if not setting_name.lower().endswith(("_api_key", "_token")):
                continue
            if isinstance(setting_value, str) and setting_value:
                candidates.add(setting_value)
        for raw_key, raw_value in headers.items():
            compact_key = re.sub(r"[-_]", "", raw_key).lower()
            if not (
                compact_key in {"authorization", "proxyauthorization", "key", "token"}
                or compact_key.endswith(("apikey", "accesstoken", "authtoken", "token"))
            ):
                continue
            value = raw_value.strip()
            if not value:
                continue
            candidates.add(value)
            parts = value.split(maxsplit=1)
            if len(parts) == 2 and parts[0].lower() in {"basic", "bearer", "token"}:
                candidates.add(parts[1])
        if not candidates:
            return
        if SafeProviderTransport._payload_contains_secret(payload, candidates):
            raise SafeProviderTransportError(provider, operation, "SECRET_IN_RESPONSE")

    @staticmethod
    def _payload_contains_secret(payload: object, candidates: set[str]) -> bool:
        if isinstance(payload, str):
            return any(candidate in payload for candidate in candidates)
        if isinstance(payload, bytes):
            return any(candidate.encode("utf-8") in payload for candidate in candidates)
        if isinstance(payload, Mapping):
            return any(
                SafeProviderTransport._payload_contains_secret(key, candidates)
                or SafeProviderTransport._payload_contains_secret(value, candidates)
                for key, value in payload.items()
            )
        if isinstance(payload, Sequence):
            return any(
                SafeProviderTransport._payload_contains_secret(item, candidates)
                for item in payload
            )
        return False

    @staticmethod
    def _decode(
        payload: bytes,
        decoder: Decoder,
        provider: str,
        operation: str,
    ) -> object:
        try:
            if decoder == "bytes":
                return payload
            text = payload.decode("utf-8-sig")
            if decoder == "csv":
                return [dict(row) for row in csv.DictReader(io.StringIO(text))]
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError, csv.Error):
            raise SafeProviderTransportError(provider, operation, "DECODE_FAILED") from None

    def _rate_limit_state(
        self,
        headers: httpx.Headers,
        now: datetime,
        status_code: int,
    ) -> tuple[int | None, int | None, datetime | None]:
        minute_limit = self._first_int(headers, "ratelimit-limit", "x-ratelimit-limit")
        remaining = self._first_int(headers, "ratelimit-remaining", "x-ratelimit-remaining")
        cooldown: datetime | None = None
        if status_code == 429:
            retry_after = self._first_float(headers, "retry-after")
            if retry_after is not None:
                retry_after = min(max(retry_after, 0.0), float(self._settings.provider_retry_after_cap_seconds))
                cooldown = now + timedelta(seconds=retry_after)
        if remaining == 0:
            reset = self._first_float(headers, "ratelimit-reset", "x-ratelimit-reset")
            if reset is not None:
                now_timestamp = now.timestamp()
                reset_seconds = reset - now_timestamp if reset > now_timestamp else reset
                reset_seconds = min(
                    max(reset_seconds, 0.0),
                    float(self._settings.provider_retry_after_cap_seconds),
                )
                reset_cooldown = now + timedelta(seconds=reset_seconds)
                if cooldown is None or reset_cooldown > cooldown:
                    cooldown = reset_cooldown
        return minute_limit, remaining, cooldown

    @staticmethod
    def _first_int(headers: httpx.Headers, *names: str) -> int | None:
        value = SafeProviderTransport._first_float(headers, *names)
        if value is None or value < 0:
            return None
        return int(value)

    @staticmethod
    def _first_float(headers: httpx.Headers, *names: str) -> float | None:
        for name in names:
            raw = headers.get(name)
            if raw is None:
                continue
            try:
                return float(raw.strip())
            except ValueError:
                continue
        return None

    @staticmethod
    def _retry_delay(retry_index: int, now: datetime, cooldown: datetime | None) -> float:
        delay = float(min(2**retry_index, 8))
        if cooldown is not None:
            delay = max(delay, max((cooldown - now).total_seconds(), 0.0))
        return delay

    @staticmethod
    def _sleep(
        sleeper: Callable[[float], None],
        delay: float,
        provider: str,
        operation: str,
    ) -> None:
        try:
            sleeper(delay)
        except Exception:
            raise SafeProviderTransportError(provider, operation, "SLEEP_FAILED") from None

    def _acquire_inflight(self, fingerprint: str) -> tuple[_InflightEntry, bool]:
        with self._shared_state.lock:
            existing = self._shared_state.inflight.get(fingerprint)
            if existing is not None:
                return existing, False
            entry = _InflightEntry()
            self._shared_state.inflight[fingerprint] = entry
            return entry, True

    def _publish(
        self,
        fingerprint: str,
        entry: _InflightEntry,
        *,
        response: ProviderResponse | None = None,
        error: SafeProviderTransportError | ProviderBudgetExceeded | None = None,
    ) -> None:
        with self._shared_state.lock:
            entry.response = response
            entry.error = error
            entry.event.set()
            self._shared_state.inflight.pop(fingerprint, None)

    @staticmethod
    def _validate_labels(provider: str, operation: str, cache_scope: str) -> tuple[str, str, str]:
        normalized_provider = provider.strip()
        normalized_operation = operation.strip()
        normalized_scope = cache_scope.strip()
        if not all(
            _SAFE_SCOPE.fullmatch(value)
            for value in (normalized_provider, normalized_operation, normalized_scope)
        ):
            raise SafeProviderTransportError("provider", "operation", "INVALID_LABEL")
        return normalized_provider, normalized_operation, normalized_scope
