from __future__ import annotations

import gzip
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.transport import (
    SafeProviderTransport,
    SafeProviderTransportError,
)
from backend.app.database import BASE_SCHEMA, INDEX_SCHEMA
from backend.app.services.provider_budget_service import (
    ProviderBudgetExceeded,
    ProviderBudgetManager,
    ProviderBudgetPolicy,
    ProviderBudgetTransactionError,
)

NOW = datetime(2026, 8, 16, 12, 34, 56, tzinfo=UTC)
POLICY = ProviderBudgetPolicy(
    minute_limit=20,
    daily_limit=100,
    monthly_limit=1_000,
    max_attempts=3,
)


def _connection(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(path) if path is not None else ":memory:",
        check_same_thread=False,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize(path: Path | None = None) -> sqlite3.Connection:
    connection = _connection(path)
    connection.executescript(BASE_SCHEMA)
    connection.executescript(INDEX_SCHEMA)
    return connection


def _transport(
    handler: httpx.MockTransport | Any,
    *,
    allowed_hosts: set[str] | None = None,
) -> SafeProviderTransport:
    mock_transport = handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)
    client = httpx.Client(transport=mock_transport)
    return SafeProviderTransport(
        allowed_hosts=allowed_hosts or {"api.example.test"}
    ).with_client(client)


def _request(
    transport: SafeProviderTransport,
    connection: sqlite3.Connection,
    **overrides: Any,
):
    values: dict[str, Any] = {
        "connection": connection,
        "policy": POLICY,
        "provider": "fixture",
        "method": "GET",
        "base_url": "https://api.example.test",
        "path": "/v1/prices",
        "headers": {},
        "params": {"symbol": "AAPL"},
        "json_body": None,
        "operation": "EOD",
        "cache_scope": "daily:AAPL",
        "cache_ttl_seconds": 300,
        "max_response_bytes": 1024,
        "decoder": "json",
        "now": NOW,
        "sleeper": lambda _delay: None,
    }
    values.update(overrides)
    return transport.request(**values)


def _json_response(payload: object, status_code: int = 200, **headers: str) -> httpx.Response:
    content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(content),
        headers={"content-type": "application/json", **headers},
    )


def test_provider_budget_reservation_is_atomic_across_all_windows() -> None:
    connection = _initialize()
    manager = ProviderBudgetManager()
    policy = ProviderBudgetPolicy(minute_limit=2, daily_limit=1, monthly_limit=5)

    manager.reserve(connection, policy, "fixture", "EOD", "a" * 64, NOW)
    with pytest.raises(ProviderBudgetExceeded) as exc_info:
        manager.reserve(connection, policy, "fixture", "EOD", "b" * 64, NOW)

    rows = connection.execute(
        "SELECT window_kind, used_count FROM provider_usage_windows ORDER BY window_kind"
    ).fetchall()
    assert [(row["window_kind"], row["used_count"]) for row in rows] == [
        ("DAY", 1),
        ("MINUTE", 1),
        ("MONTH", 1),
    ]
    assert str(exc_info.value) == "fixture:EOD:BUDGET_EXHAUSTED"


@pytest.mark.parametrize(
    ("policy", "later", "expected_window"),
    [
        (ProviderBudgetPolicy(1, None, None), datetime(2026, 8, 16, 12, 34, 59, tzinfo=UTC), "MINUTE"),
        (ProviderBudgetPolicy(None, 1, None), datetime(2026, 8, 16, 23, 59, 59, tzinfo=UTC), "DAY"),
        (ProviderBudgetPolicy(None, None, 1), datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC), "MONTH"),
    ],
)
def test_provider_budget_enforces_minute_day_and_month_limits(
    policy: ProviderBudgetPolicy,
    later: datetime,
    expected_window: str,
) -> None:
    connection = _initialize()
    manager = ProviderBudgetManager()
    manager.reserve(connection, policy, "fixture", "QUOTE", "a" * 64, NOW)

    with pytest.raises(ProviderBudgetExceeded) as exc_info:
        manager.reserve(connection, policy, "fixture", "QUOTE", "b" * 64, later)

    assert exc_info.value.window_kind == expected_window
    starts = {
        row["window_kind"]: row["window_start"]
        for row in connection.execute(
            "SELECT window_kind, window_start FROM provider_usage_windows"
        )
    }
    assert starts["MINUTE"] == "2026-08-16T12:34:00Z"
    assert starts["DAY"] == "2026-08-16"
    assert starts["MONTH"] == "2026-08"


def test_provider_budget_completion_is_idempotent_and_projects_daily_usage() -> None:
    connection = _initialize()
    manager = ProviderBudgetManager()
    reservation_id = manager.reserve(connection, POLICY, "fixture", "EOD", "a" * 64, NOW)

    manager.complete(connection, reservation_id, "SUCCEEDED", 200, 0, None)
    manager.complete(connection, reservation_id, "REJECTED", 500, 9, NOW)

    log = connection.execute(
        "SELECT outcome, status_code, retry_count FROM provider_request_log"
    ).fetchone()
    usage = connection.execute(
        "SELECT usage_date, calls_count, daily_limit FROM api_usage WHERE provider = 'fixture'"
    ).fetchone()
    assert dict(log) == {"outcome": "SUCCEEDED", "status_code": 200, "retry_count": 0}
    assert dict(usage) == {
        "usage_date": "2026-08-16",
        "calls_count": 1,
        "daily_limit": 100,
    }


def test_provider_budget_never_commits_an_existing_caller_transaction(tmp_path: Path) -> None:
    database_path = tmp_path / "caller-transaction.db"
    connection = _initialize(database_path)
    connection.execute(
        "INSERT INTO assets (symbol, name, asset_type) VALUES ('TXN', 'Pending', 'stock')"
    )

    with pytest.raises(ProviderBudgetTransactionError):
        ProviderBudgetManager().reserve(
            connection,
            POLICY,
            "fixture",
            "EOD",
            "a" * 64,
            NOW,
        )
    connection.rollback()

    with _connection(database_path) as observer:
        assert observer.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'TXN'").fetchone()[0] == 0


def test_provider_budget_honors_legacy_daily_usage_at_cutover() -> None:
    connection = _initialize()
    usage_date = NOW.astimezone().date().isoformat()
    connection.execute(
        """
        INSERT INTO api_usage (provider, usage_date, calls_count, daily_limit)
        VALUES ('fixture', ?, 100, 100)
        """,
        (usage_date,),
    )
    connection.commit()

    with pytest.raises(ProviderBudgetExceeded) as exc_info:
        ProviderBudgetManager().reserve(
            connection,
            ProviderBudgetPolicy(None, 100, None),
            "fixture",
            "EOD",
            "a" * 64,
            NOW,
        )

    assert exc_info.value.window_kind == "DAY"
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'fixture' AND usage_date = ?",
        (usage_date,),
    ).fetchone()[0] == 100


def test_safe_transport_cache_hit_happens_before_quota() -> None:
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"value": 42})

    transport = _transport(handler)
    first = _request(transport, connection)
    second = _request(transport, connection)

    assert first.from_cache is False
    assert second.from_cache is True
    assert second.attempts == 0
    assert calls == 1
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'fixture'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE outcome = 'CACHE_HIT'"
    ).fetchone()[0] == 1


def test_safe_transport_bypass_cache_still_reserves_and_rewrites_cache() -> None:
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"version": calls})

    transport = _transport(handler)
    _request(transport, connection)
    forced = _request(transport, connection, bypass_cache=True)
    cached = _request(transport, connection)

    assert forced.payload == {"version": 2}
    assert forced.from_cache is False
    assert cached.payload == {"version": 2}
    assert calls == 2
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'fixture'"
    ).fetchone()[0] == 2


def test_safe_transport_coalesces_two_concurrent_forced_requests(tmp_path: Path) -> None:
    database_path = tmp_path / "budget.db"
    initial = _initialize(database_path)
    initial.close()
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=3)
        return _json_response({"coalesced": True})

    transport = _transport(handler)

    def run() -> object:
        with _connection(database_path) as connection:
            return _request(transport, connection, bypass_cache=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run)
        assert entered.wait(timeout=3)
        second_future = executor.submit(run)
        time.sleep(0.05)
        release.set()
        first = first_future.result(timeout=3)
        second = second_future.result(timeout=3)

    with _connection(database_path) as connection:
        usage = connection.execute(
            "SELECT calls_count FROM api_usage WHERE provider = 'fixture'"
        ).fetchone()[0]
    assert calls == 1
    assert usage == 1
    assert first.request_fingerprint == second.request_fingerprint
    assert first.payload == second.payload == {"coalesced": True}


def test_safe_transport_coalesces_forced_requests_across_transport_instances(tmp_path: Path) -> None:
    database_path = tmp_path / "global-inflight.db"
    initial = _initialize(database_path)
    initial.close()
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=3)
        return _json_response({"coalesced": True})

    first_transport = _transport(handler)
    second_transport = _transport(handler)

    def run(transport: SafeProviderTransport) -> object:
        with _connection(database_path) as connection:
            return _request(transport, connection, bypass_cache=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run, first_transport)
        assert entered.wait(timeout=3)
        second_future = executor.submit(run, second_transport)
        time.sleep(0.05)
        release.set()
        first = first_future.result(timeout=3)
        second = second_future.result(timeout=3)

    assert calls == 1
    assert first.request_fingerprint == second.request_fingerprint


def test_safe_transport_force_does_not_join_a_non_force_cache_hit(tmp_path: Path) -> None:
    class BlockingCacheHitManager(ProviderBudgetManager):
        def __init__(self) -> None:
            self.block_cache_hits = False
            self.cache_hit_entered = threading.Event()
            self.release_cache_hit = threading.Event()

        def record_cache_hit(self, *args: Any, **kwargs: Any) -> None:
            if self.block_cache_hits:
                self.cache_hit_entered.set()
                assert self.release_cache_hit.wait(timeout=3)
            super().record_cache_hit(*args, **kwargs)

    database_path = tmp_path / "force-cache-race.db"
    initial = _initialize(database_path)
    manager = BlockingCacheHitManager()
    calls = 0
    physical_force = threading.Event()

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            physical_force.set()
        return _json_response({"version": calls})

    transport = SafeProviderTransport(
        allowed_hosts={"api.example.test"},
        budget_manager=manager,
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    _request(transport, initial)
    initial.close()
    manager.block_cache_hits = True

    def run(force: bool) -> object:
        with _connection(database_path) as connection:
            return _request(transport, connection, bypass_cache=force)

    with ThreadPoolExecutor(max_workers=2) as executor:
        cached_future = executor.submit(run, False)
        assert manager.cache_hit_entered.wait(timeout=3)
        forced_future = executor.submit(run, True)
        force_was_physical = physical_force.wait(timeout=0.25)
        manager.release_cache_hit.set()
        cached = cached_future.result(timeout=3)
        forced = forced_future.result(timeout=3)

    assert force_was_physical is True
    assert cached.from_cache is True
    assert forced.from_cache is False
    assert forced.payload == {"version": 2}
    assert calls == 2


def test_safe_transport_reserves_once_for_every_physical_retry() -> None:
    connection = _initialize()
    responses = iter([_json_response({"error": "temporary"}, 503), _json_response({"ok": True})])
    sleeps: list[float] = []
    transport = _transport(lambda _request: next(responses))

    response = _request(transport, connection, sleeper=sleeps.append)

    assert response.attempts == 2
    assert sleeps == [1.0]
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'fixture'"
    ).fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM provider_request_log").fetchone()[0] == 2


def test_safe_transport_fingerprint_canonicalizes_post_json_without_storing_body() -> None:
    connection = _initialize()
    sentinel = "SENTINEL_OPENFIGI_BODY_12345"
    transport = _transport(lambda _request: _json_response({"data": []}))
    first = _request(
        transport,
        connection,
        method="POST",
        path="/v3/mapping",
        operation="IDENTITY",
        cache_scope="openfigi",
        json_body=[{"idValue": sentinel, "idType": "ID_ISIN"}],
    )
    second = _request(
        transport,
        connection,
        method="POST",
        path="/v3/mapping",
        operation="IDENTITY",
        cache_scope="openfigi-reordered",
        json_body=[{"idType": "ID_ISIN", "idValue": sentinel}],
        bypass_cache=True,
    )

    assert first.request_fingerprint == second.request_fingerprint
    database_text = "\n".join(
        str(value)
        for row in connection.execute("SELECT * FROM provider_request_log")
        for value in row
        if value is not None
    )
    cache_metadata = "\n".join(
        str(value)
        for row in connection.execute(
            "SELECT cache_key, provider, endpoint, symbol, request_url_hash FROM api_cache"
        )
        for value in row
        if value is not None
    )
    assert sentinel not in database_text
    assert sentinel not in cache_metadata


def test_safe_transport_get_and_post_have_distinct_fingerprints() -> None:
    connection = _initialize()
    transport = _transport(lambda _request: _json_response({"ok": True}))

    get_response = _request(transport, connection)
    post_response = _request(
        transport,
        connection,
        method="POST",
        json_body={"symbol": "AAPL"},
        bypass_cache=True,
    )

    assert get_response.request_fingerprint != post_response.request_fingerprint


def test_safe_transport_limits_decompressed_bytes_before_json_decode() -> None:
    connection = _initialize()
    compressed = gzip.compress(json.dumps({"payload": "x" * 2_000}).encode())
    transport = _transport(
        lambda _request: httpx.Response(
            200,
            stream=httpx.ByteStream(compressed),
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
        )
    )

    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, max_response_bytes=128)

    assert str(exc_info.value) == "fixture:EOD:RESPONSE_TOO_LARGE"


def test_safe_transport_uses_bounded_raw_streaming_for_decompression() -> None:
    connection = _initialize()
    compressed = gzip.compress(json.dumps({"payload": "x" * 5_000_000}).encode())

    def handler(_request: httpx.Request) -> httpx.Response:
        response = httpx.Response(
            200,
            stream=httpx.ByteStream(compressed),
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
        )

        def unbounded_decode_is_forbidden(*_args: Any, **_kwargs: Any):
            raise AssertionError("iter_bytes decompresses before the transport can enforce its byte limit")

        response.iter_bytes = unbounded_decode_is_forbidden  # type: ignore[method-assign]
        return response

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, max_response_bytes=128)

    assert exc_info.value.code == "RESPONSE_TOO_LARGE"


def test_safe_transport_rejects_closed_client_before_reserving_quota() -> None:
    connection = _initialize()
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: _json_response({"ok": True})))
    client.close()
    transport = SafeProviderTransport(allowed_hosts={"api.example.test"}).with_client(client)

    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, bypass_cache=True)

    assert exc_info.value.code == "CLIENT_CLOSED"
    assert connection.execute("SELECT COUNT(*) FROM provider_request_log").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == 0


def test_safe_transport_rolls_back_reservation_when_client_fails_before_send() -> None:
    class FailingBeforeSendClient(httpx.Client):
        def stream(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("SENTINEL_PRE_SEND_SECRET")

    connection = _initialize()
    client = FailingBeforeSendClient()
    transport = SafeProviderTransport(allowed_hosts={"api.example.test"}).with_client(client)

    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection)

    assert connection.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM provider_request_log").fetchone()[0] == 0
    assert exc_info.value.code == "REQUEST_FAILED"
    assert "SENTINEL" not in str(exc_info.value)
    client.close()


@pytest.mark.parametrize(
    ("decoder", "content_type"),
    [("json", "text/html"), ("csv", "application/json"), ("bytes", "text/html")],
)
def test_safe_transport_rejects_content_types_outside_decoder_allowlist(
    decoder: str,
    content_type: str,
) -> None:
    connection = _initialize()
    transport = _transport(
        lambda _request: httpx.Response(200, content=b"{}", headers={"content-type": content_type})
    )

    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, decoder=decoder)

    assert exc_info.value.code == "UNEXPECTED_CONTENT_TYPE"


def test_safe_transport_rejects_redirects_without_following_location() -> None:
    connection = _initialize()
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://evil.example/secret"})

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection)

    assert exc_info.value.code == "REDIRECT_REJECTED"
    assert seen_hosts == ["api.example.test"]


def test_safe_transport_retries_429_with_capped_numeric_retry_after_and_official_headers() -> None:
    connection = _initialize()
    responses = iter(
        [
            _json_response(
                {"error": "slow"},
                429,
                **{
                    "retry-after": "90",
                    "ratelimit-limit": "5",
                    "ratelimit-remaining": "0",
                    "ratelimit-reset": "90",
                },
            ),
            _json_response({"ok": True}),
        ]
    )
    sleeps: list[float] = []
    transport = _transport(lambda _request: next(responses))

    response = _request(transport, connection, sleeper=sleeps.append)

    assert response.payload == {"ok": True}
    assert response.attempts == 2
    assert sleeps == [60.0]
    first_log = connection.execute(
        "SELECT outcome, status_code, cooldown_until FROM provider_request_log ORDER BY requested_at, rowid LIMIT 1"
    ).fetchone()
    assert first_log["outcome"] == "RATE_LIMITED"
    assert first_log["status_code"] == 429
    assert first_log["cooldown_until"] == "2026-08-16T12:35:56Z"


@pytest.mark.parametrize("status_code", [500, 502, 503, 504])
def test_safe_transport_retries_only_supported_server_errors(status_code: int) -> None:
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"error": "temporary"}, status_code)

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection)

    assert exc_info.value.code == "RETRY_EXHAUSTED"
    assert calls == 3


def test_safe_transport_retries_timeouts_with_deterministic_backoff() -> None:
    connection = _initialize()
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("SENTINEL_TIMEOUT_SECRET", request=request)
        return _json_response({"ok": True})

    transport = _transport(handler)
    response = _request(transport, connection, sleeper=sleeps.append)

    assert response.attempts == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_safe_transport_does_not_retry_non_retryable_client_errors(status_code: int) -> None:
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"secret": "SENTINEL_RESPONSE_SECRET"}, status_code)

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection)

    assert calls == 1
    assert exc_info.value.code == f"HTTP_{status_code}"
    assert "SENTINEL" not in str(exc_info.value)


@pytest.mark.parametrize("key", ["apikey", "Api_Key", "TOKEN", "access_TOKEN", "Key"])
def test_safe_transport_rejects_sensitive_query_parameter_names_case_insensitively(key: str) -> None:
    connection = _initialize()
    sentinel = "SENTINEL_QUERY_SECRET_12345"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"ok": True})

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, params={key: sentinel})

    assert calls == 0
    assert str(exc_info.value) == "fixture:EOD:SECRET_IN_QUERY"
    assert sentinel not in str(exc_info.value)
    assert connection.execute("SELECT COUNT(*) FROM provider_request_log").fetchone()[0] == 0


def test_safe_transport_rejects_secret_echo_before_cache_or_return() -> None:
    connection = _initialize()
    sentinel = "SENTINEL_RESPONSE_ECHO_SECRET_12345"

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"echo": request.headers["x-api-key"]})

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, headers={"X-Api-Key": sentinel})

    assert exc_info.value.code == "SECRET_IN_RESPONSE"
    assert sentinel not in str(exc_info.value)
    assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 0
    log = connection.execute(
        "SELECT outcome, status_code FROM provider_request_log"
    ).fetchone()
    assert dict(log) == {"outcome": "REJECTED", "status_code": 200}
    persisted = "\n".join(
        str(value)
        for row in connection.execute("SELECT * FROM api_cache")
        for value in row
        if value is not None
    )
    assert sentinel not in persisted


def test_safe_transport_secret_redaction_handles_json_escaped_characters() -> None:
    connection = _initialize()
    sentinel = 'SENTINEL"QUOTED\\VALUE'

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"echo": request.headers["x-api-key"]})

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, headers={"X-Api-Key": sentinel})

    assert exc_info.value.code == "SECRET_IN_RESPONSE"
    assert sentinel not in str(exc_info.value)
    assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 0


def test_safe_transport_rejects_and_purges_secret_from_cache_hit() -> None:
    connection = _initialize()
    sentinel = "SENTINEL_LEGACY_CACHE_SECRET_12345"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"ok": True})

    transport = _transport(handler)
    transport.store_response_for_url(
        connection,
        provider="fixture",
        operation="EOD",
        cache_scope="daily:AAPL",
        request_url="https://api.example.test/v1/prices?symbol=AAPL",
        payload={"echo": sentinel},
        status_code=200,
        cache_ttl_seconds=300,
        now=NOW,
    )

    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, headers={"X-Api-Key": sentinel})

    assert exc_info.value.code == "SECRET_IN_RESPONSE"
    assert sentinel not in str(exc_info.value)
    assert calls == 0
    assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE outcome = 'CACHE_HIT'"
    ).fetchone()[0] == 0


def test_safe_transport_normalizes_bearer_whitespace_for_secret_redaction() -> None:
    connection = _initialize()
    sentinel = "SENTINEL_MULTISPACE_BEARER_SECRET"

    def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response({"echo": sentinel})

    transport = _transport(handler)
    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(
            transport,
            connection,
            headers={"Authorization": f"Bearer  {sentinel}"},
        )

    assert exc_info.value.code == "SECRET_IN_RESPONSE"
    assert sentinel not in str(exc_info.value)
    assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 0


def test_safe_transport_compatibility_cache_rejects_configured_secret() -> None:
    connection = _initialize()
    sentinel = "SENTINEL_COMPATIBILITY_CACHE_SECRET"
    transport = SafeProviderTransport(
        allowed_hosts={"api.example.test"},
        settings=replace(get_settings(), finnhub_api_key=sentinel),
    )
    request_url = "https://api.example.test/v1/prices?symbol=AAPL"
    SafeProviderTransport(allowed_hosts={"api.example.test"}).store_response_for_url(
        connection,
        provider="fixture",
        operation="EOD",
        cache_scope="daily:AAPL",
        request_url=request_url,
        payload={"nested": [{"echo": sentinel}]},
        status_code=200,
        cache_ttl_seconds=300,
        now=NOW,
    )

    with pytest.raises(SafeProviderTransportError) as exc_info:
        transport.cached_response_for_url(
            connection,
            provider="fixture",
            operation="EOD",
            cache_scope="daily:AAPL",
            request_url=request_url,
            now=NOW,
        )

    assert exc_info.value.code == "SECRET_IN_RESPONSE"
    assert sentinel not in str(exc_info.value)
    assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE outcome = 'CACHE_HIT'"
    ).fetchone()[0] == 0


def test_safe_transport_compatibility_store_rejects_configured_secret() -> None:
    connection = _initialize()
    sentinel = "SENTINEL_COMPATIBILITY_STORE_SECRET"
    transport = SafeProviderTransport(
        allowed_hosts={"api.example.test"},
        settings=replace(get_settings(), finnhub_api_key=sentinel),
    )

    with pytest.raises(SafeProviderTransportError) as exc_info:
        transport.store_response_for_url(
            connection,
            provider="fixture",
            operation="EOD",
            cache_scope="daily:AAPL",
            request_url="https://api.example.test/v1/prices?symbol=AAPL",
            payload={"echo": sentinel},
            status_code=200,
            cache_ttl_seconds=300,
            now=NOW,
        )

    assert exc_info.value.code == "SECRET_IN_RESPONSE"
    assert sentinel not in str(exc_info.value)
    assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 0


def test_safe_transport_cache_purge_never_commits_caller_transaction(tmp_path: Path) -> None:
    database_path = tmp_path / "cache-purge-transaction.db"
    connection = _initialize(database_path)
    sentinel = "SENTINEL_CACHE_PURGE_TRANSACTION_SECRET"
    transport = _transport(lambda _request: _json_response({"ok": True}))
    transport.store_response_for_url(
        connection,
        provider="fixture",
        operation="EOD",
        cache_scope="daily:AAPL",
        request_url="https://api.example.test/v1/prices?symbol=AAPL",
        payload={"echo": sentinel},
        status_code=200,
        cache_ttl_seconds=300,
        now=NOW,
    )
    connection.execute(
        "INSERT INTO assets (symbol, name, asset_type) VALUES ('TXN', 'Pending', 'stock')"
    )

    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, headers={"X-Api-Key": sentinel})
    connection.rollback()

    assert exc_info.value.code == "SECRET_IN_RESPONSE"
    with _connection(database_path) as observer:
        assert observer.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'TXN'").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("base_url", "path", "code"),
    [
        ("http://api.example.test", "/v1/prices", "HTTPS_REQUIRED"),
        ("https://user:password@api.example.test", "/v1/prices", "INVALID_BASE_URL"),
        ("https://api.example.test?token=secret", "/v1/prices", "INVALID_BASE_URL"),
        ("https://unlisted.example.test", "/v1/prices", "HOST_NOT_ALLOWED"),
        ("https://api.example.test", "https://evil.example/path", "INVALID_PATH"),
    ],
)
def test_safe_transport_fails_closed_for_untrusted_urls(
    base_url: str,
    path: str,
    code: str,
) -> None:
    connection = _initialize()
    transport = _transport(lambda _request: _json_response({"ok": True}))

    with pytest.raises(SafeProviderTransportError) as exc_info:
        _request(transport, connection, base_url=base_url, path=path)

    assert exc_info.value.code == code


def test_safe_transport_with_client_preserves_budget_cache_and_inflight_state() -> None:
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"ok": True})

    original = SafeProviderTransport(allowed_hosts={"api.example.test"})
    replaced = original.with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    first = _request(replaced, connection)
    second = _request(
        replaced.with_client(httpx.Client(transport=httpx.MockTransport(handler))),
        connection,
    )

    assert first.from_cache is False
    assert second.from_cache is True
    assert calls == 1
    assert replaced.budget_manager is original.budget_manager


def test_market_provider_force_is_forwarded_only_as_transport_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "provider.db"))
    get_settings.cache_clear()
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(
            {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1_754_870_400],
                            "indicators": {
                                "quote": [
                                    {"open": [100], "high": [101], "low": [99], "close": [100], "volume": [10]}
                                ],
                                "adjclose": [{"adjclose": [100]}],
                            },
                        }
                    ],
                    "error": None,
                }
            }
        )

    transport = _transport(handler, allowed_hosts={"query1.finance.yahoo.com"})
    provider = YahooFinanceProvider(get_settings(), connection, transport=transport)
    provider.get_daily_prices("AAPL")
    provider.get_daily_prices("AAPL", force=True)

    assert calls == 2
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'yahoo_finance'"
    ).fetchone()[0] == 2
    get_settings.cache_clear()


def test_news_provider_force_is_forwarded_only_as_transport_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.data_providers.yahoo_news import YahooNewsProvider

    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "news.db"))
    get_settings.cache_clear()
    connection = _initialize()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"news": []})

    transport = _transport(handler, allowed_hosts={"query1.finance.yahoo.com"})
    provider = YahooNewsProvider(get_settings(), connection, transport=transport)
    provider.get_news_for_symbol("AAPL")
    provider.get_news_for_symbol("AAPL", force=True)

    assert calls == 2
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = 'yahoo_news'"
    ).fetchone()[0] == 2
    get_settings.cache_clear()


def test_finnhub_news_sends_secret_only_in_header_via_safe_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.data_providers.finnhub_news import FinnhubNewsProvider

    sentinel = "SENTINEL_FINNHUB_HEADER_12345"
    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", sentinel)
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "finnhub.db"))
    get_settings.cache_clear()
    connection = _initialize()
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["header"] = request.headers.get("x-finnhub-token", "")
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"[]"),
            headers={"content-type": "application/json"},
        )

    transport = _transport(handler, allowed_hosts={"finnhub.io"})
    provider = FinnhubNewsProvider(get_settings(), connection, transport=transport)

    news, used_cache = provider.get_news_for_symbol("AAPL")

    assert news == []
    assert used_cache is False
    assert observed["header"] == sentinel
    assert "token=" not in observed["url"].lower()
    assert sentinel not in observed["url"]
    persisted_metadata = "\n".join(
        str(value)
        for row in connection.execute(
            "SELECT cache_key, provider, endpoint, symbol, request_url_hash FROM api_cache"
        )
        for value in row
        if value is not None
    )
    assert sentinel not in persisted_metadata
    get_settings.cache_clear()


def test_finnhub_us_quote_local_policy_blocks_request_56_in_same_minute() -> None:
    from backend.app.data_providers.finnhub_quote import FinnhubQuoteProvider

    connection = _initialize()
    settings = replace(
        get_settings(),
        enable_real_data=True,
        finnhub_api_key="TEST_FINNHUB_QUOTE_KEY_12345",
        finnhub_quote_minute_limit=80,
    )
    provider = FinnhubQuoteProvider(
        settings,
        connection,
        transport=_transport(
            lambda _request: _json_response({"c": 1, "h": 1, "l": 1, "o": 1, "pc": 1, "t": 1}),
            allowed_hosts={"finnhub.io"},
        ),
    )
    manager = ProviderBudgetManager()

    for index in range(55):
        manager.reserve(
            connection,
            provider.policy,
            "finnhub",
            "QUOTE",
            f"{index:064x}",
            NOW,
        )
    with pytest.raises(ProviderBudgetExceeded) as exc_info:
        manager.reserve(connection, provider.policy, "finnhub", "QUOTE", "f" * 64, NOW)

    assert provider.policy == ProviderBudgetPolicy(55, None, None, 3)
    assert exc_info.value.window_kind == "MINUTE"
