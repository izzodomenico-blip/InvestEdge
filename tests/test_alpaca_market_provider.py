from __future__ import annotations

import importlib
import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.data_providers.base import ProviderError
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import BASE_SCHEMA, INDEX_SCHEMA
from backend.app.intraday.contracts import FeedProfile

NOW = datetime(2026, 10, 11, 16, 0, tzinfo=UTC)


def settings(**overrides):
    values = {"enable_real_data": True, "enable_alpaca_data": True,
              "alpaca_api_key_id": uuid.uuid4().hex, "alpaca_api_secret_key": uuid.uuid4().hex,
              "alpaca_feed": "sip", "alpaca_max_symbols": 30, "alpaca_max_connections": 1,
              "alpaca_http_minute_limit": 20, "alpaca_http_daily_limit": 100,
              "alpaca_http_monthly_limit": 1000, "alpaca_max_frame_bytes": 1048576,
              "alpaca_max_queue_events": 1000, "alpaca_max_archive_bytes": 10485760}
    values.update(overrides)
    return replace(get_settings(), **values)


def profile(config, **overrides):
    values = {"feed": config.alpaca_feed,
              "attested_capabilities": ("bars", "quotes", "news", "assets", "calendar", "corporate_actions"),
              "required_capabilities": ("bars", "quotes"),
              "max_symbols": config.alpaca_max_symbols, "max_connections": config.alpaca_max_connections,
              "http_minute_limit": config.alpaca_http_minute_limit,
              "http_daily_limit": config.alpaca_http_daily_limit,
              "http_monthly_limit": config.alpaca_http_monthly_limit,
              "max_frame_bytes": config.alpaca_max_frame_bytes,
              "max_queue_events": config.alpaca_max_queue_events,
              "max_archive_bytes": config.alpaca_max_archive_bytes}
    values.update(overrides)
    return FeedProfile(**values)


def db(path: Path | None = None):
    connection = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.executescript(BASE_SCHEMA)
    connection.executescript(INDEX_SCHEMA)
    return connection


def response(payload=None, status=200, headers=None):
    return httpx.Response(status, json=payload if payload is not None else {"bars": {}, "next_page_token": None},
                          headers=headers)


def provider(connection, config, handler, prof=None, sleeper=None):
    module = importlib.import_module("backend.app.data_providers.alpaca_market")
    transport = SafeProviderTransport(allowed_hosts={"data.alpaca.markets", "paper-api.alpaca.markets"},
                                     settings=config,
                                     client=httpx.Client(transport=httpx.MockTransport(handler)))
    return module.AlpacaMarketProvider(config, connection, prof or profile(config), transport=transport,
                                       clock=lambda: NOW, sleeper=sleeper or (lambda _: None))


def bars(client, **overrides):
    params = {"symbols": ("AAPL",), "start": "2026-10-09T14:00:00.000000001Z",
              "end": "2026-10-09T15:00:00.000000001Z", "asof": "2026-10-09"}
    params.update(overrides)
    return client.get_bars_page(**params)


def public_db(connection):
    return json.dumps({table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
                       for table in ("api_cache", "provider_request_log", "provider_usage_windows", "api_usage")})


def test_bars_explicit_params_and_auth_in_memory_only():
    config = settings()
    seen = []
    def handler(request):
        seen.append(request)
        assert not connection.in_transaction
        return response({"bars": {"AAPL": [{"t": "2026-10-09T14:00:00.000000001Z", "o": 10, "h": 11,
                                           "l": 9, "c": 10, "v": 20, "n": 2, "vw": 10,
                                           "untrusted": "drop"}]}, "next_page_token": None, "account": "drop"})
    connection = db()
    client = provider(connection, config, handler)
    result = bars(client)
    query = dict(seen[0].url.params)
    assert query["feed"] == "sip" and query["currency"] == "USD"
    assert query["adjustment"] == "raw" and query["timeframe"] == "1Min"
    assert query["sort"] == "asc" and query["asof"] == "2026-10-09"
    assert query["start"].endswith("000000001Z")
    assert bool(seen[0].headers["APCA-API-KEY-ID"] == config.alpaca_api_key_id)
    assert bool(seen[0].headers["APCA-API-SECRET-KEY"] == config.alpaca_api_secret_key)
    serialized = public_db(connection) + repr(client) + repr(client.public_profile()) + str(seen[0].url)
    assert all(value not in serialized for value in (config.alpaca_api_key_id, config.alpaca_api_secret_key))
    assert "untrusted" not in public_db(connection) and "account" not in result.payload


@pytest.mark.parametrize("overrides,code", [
    ({"enable_real_data": False}, "REAL_DATA_DISABLED"),
    ({"enable_alpaca_data": False}, "REAL_DATA_DISABLED"),
    ({"alpaca_api_key_id": None}, "MISSING_CREDENTIAL"),
    ({"alpaca_api_secret_key": None}, "MISSING_CREDENTIAL"),
    ({"alpaca_feed": None}, "PROFILE_INVALID"),
    ({"alpaca_http_minute_limit": 0}, "BUDGET_UNATTESTED"),
    ({"alpaca_http_daily_limit": 0}, "BUDGET_UNATTESTED"),
    ({"alpaca_http_monthly_limit": 0}, "BUDGET_UNATTESTED"),
    ({"alpaca_max_symbols": 0}, "BUDGET_UNATTESTED"),
    ({"alpaca_max_frame_bytes": 0}, "BUDGET_UNATTESTED"),
])
def test_config_precheck_before_network_and_cache(overrides, code):
    baseline = settings()
    connection = db()
    calls = []
    valid = provider(connection, baseline, lambda request: calls.append(request) or response())
    bars(valid)
    changed = replace(baseline, **overrides)
    invalid = provider(connection, changed, lambda request: calls.append(request) or response(), profile(baseline))
    with pytest.raises(Exception) as caught:
        bars(invalid)
    assert getattr(caught.value, "code", None) == code
    assert len(calls) == 1
    assert connection.execute("SELECT COUNT(*) FROM provider_request_log").fetchone()[0] == 1


def test_unattested_or_different_feed_rejected_without_fallback():
    config = settings()
    connection = db()
    calls = []
    for prof in (profile(config, attested_capabilities=("quotes",)), profile(config, feed="iex")):
        client = provider(connection, config, lambda request: calls.append(request) or response(), prof)
        with pytest.raises(Exception) as caught:
            bars(client)
        assert getattr(caught.value, "code", None) == "FEED_NOT_ENTITLED"
    assert not calls and not connection.execute("SELECT * FROM api_cache").fetchall()


@pytest.mark.parametrize("credential", ["alpaca_api_key_id", "alpaca_api_secret_key"])
@pytest.mark.parametrize("location", ["unknown", "row", "page_token"])
def test_secret_echo_rejected_before_whitelist_and_cache(credential, location, caplog):
    config = settings()
    value = getattr(config, credential)
    payload = {"bars": {}, "next_page_token": None}
    if location == "unknown":
        payload["ignored"] = value
    elif location == "row":
        payload["bars"] = {"AAPL": [{"t": value}]}
    else:
        payload["next_page_token"] = value
    connection = db()
    client = provider(connection, config, lambda _: response(payload))
    with pytest.raises(Exception) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "SECRET_IN_RESPONSE"
    assert not connection.execute("SELECT * FROM api_cache").fetchall()
    assert value not in public_db(connection) + str(caught.value) + caplog.text


@pytest.mark.parametrize("status,code", [(401, "AUTHENTICATION_FAILED"), (403, "FEED_NOT_ENTITLED")])
def test_auth_errors_stop_and_disable_capability_before_cache(status, code):
    config = settings()
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response(status=status))
    original = client.profile.profile_id
    for _ in range(2):
        with pytest.raises(Exception) as caught:
            bars(client)
        assert getattr(caught.value, "code", None) == code
    assert len(calls) == 1
    assert client.availability("bars").state == "DISABLED"
    assert client.profile.profile_id == original
    assert not connection.execute("SELECT * FROM api_cache").fetchall()


def test_429_retries_are_counted_and_caps_never_increase():
    config = settings()
    connection = db()
    attempts, waits = [], []
    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return response(status=429, headers={"Retry-After": "2", "X-RateLimit-Limit": "99999"})
        return response()
    def sleeper(delay):
        assert not connection.in_transaction
        waits.append(delay)
    result = bars(provider(connection, config, handler, sleeper=sleeper))
    assert result.attempts == 2 and waits == [2]
    rows = connection.execute("SELECT * FROM provider_request_log ORDER BY rowid").fetchall()
    assert [(r["outcome"], r["retry_count"]) for r in rows] == [("RATE_LIMITED", 0), ("SUCCEEDED", 1)]
    minute = connection.execute("SELECT * FROM provider_usage_windows WHERE window_kind='MINUTE'").fetchone()
    assert minute["effective_limit"] == config.alpaca_http_minute_limit and minute["used_count"] == 2


@pytest.mark.parametrize("status", [500, 503])
def test_server_retries_exhaust_at_three_physical_attempts(status):
    config = settings()
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response(status=status))
    with pytest.raises(Exception) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "RETRY_EXHAUSTED" and len(calls) == 3
    assert connection.execute("SELECT calls_count FROM api_usage").fetchone()[0] == 3


def test_shared_budget_across_profile_and_capabilities():
    config = settings(alpaca_http_daily_limit=1)
    connection = db()
    calls = []
    def handler(request):
        return calls.append(request) or response()
    bars(provider(connection, config, handler))
    other = provider(connection, config, handler, profile(config, max_symbols=20))
    with pytest.raises(Exception) as caught:
        other.get_quotes_page(symbols=("AAPL",), start="2026-10-09T14:00:00Z",
                              end="2026-10-09T15:00:00Z", asof="2026-10-09")
    assert getattr(caught.value, "code", None) == "BUDGET_EXHAUSTED" and len(calls) == 1
    assert connection.execute("SELECT DISTINCT provider FROM provider_usage_windows").fetchall()[0][0] == "alpaca"


def test_cache_namespace_changes_with_public_profile_but_not_credentials():
    config = settings()
    connection = db()
    calls = []
    def handler(request):
        return calls.append(request) or response()
    result = bars(provider(connection, config, handler))
    cached = bars(provider(connection, config, handler))
    changed = bars(provider(connection, config, handler, profile(config, max_symbols=20)))
    rotated = replace(config, alpaca_api_key_id=uuid.uuid4().hex, alpaca_api_secret_key=uuid.uuid4().hex)
    same_public = bars(provider(connection, rotated, handler))
    assert not result.from_cache and cached.from_cache and not changed.from_cache and same_public.from_cache
    assert len(calls) == 2
    assert result.request_fingerprint == same_public.request_fingerprint
    assert connection.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0] == 2


def test_concurrent_different_profiles_never_share_inflight(tmp_path):
    config = settings()
    path = tmp_path / "transport.db"
    db(path).close()
    barrier = threading.Barrier(2)
    calls = []
    lock = threading.Lock()
    def handler(request):
        with lock:
            calls.append(request)
            number = len(calls)
        barrier.wait(timeout=5)
        return response({"bars": {}, "next_page_token": str(number)})
    transport = SafeProviderTransport(allowed_hosts={"data.alpaca.markets"}, settings=config,
                                     client=httpx.Client(transport=httpx.MockTransport(handler)))
    def run(max_symbols):
        module = importlib.import_module("backend.app.data_providers.alpaca_market")
        connection = sqlite3.connect(path, check_same_thread=False, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            client = module.AlpacaMarketProvider(config, connection, profile(config, max_symbols=max_symbols),
                                                 transport=transport, clock=lambda: NOW, sleeper=lambda _: None)
            return bars(client)
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, (20, 30)))
    assert len(calls) == 2
    assert {r.payload["next_page_token"] for r in results} == {"1", "2"}


@pytest.mark.parametrize("payload", [
    {"bars": {"AAPL": [{"c": float("nan")}]}},
    {"bars": {"AAPL": [{"c": float("inf")}]}},
    {"bars": []}, {"wrong": {}}, {"bars": {}, "next_page_token": ["bad"]},
])
def test_invalid_or_nonfinite_payload_never_cached(payload):
    config = settings()
    connection = db()
    raw = json.dumps(payload).encode()
    client = provider(connection, config, lambda _: httpx.Response(200, content=raw,
                      headers={"content-type": "application/json"}))
    with pytest.raises(Exception) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "INVALID_PAYLOAD"
    assert not connection.execute("SELECT * FROM api_cache").fetchall()


@pytest.mark.parametrize("overrides", [
    {"symbols": tuple(f"SYM{i}" for i in range(31))},
    {"symbols": ("AAPL", "AAPL")}, {"symbols": ("../account",)},
    {"limit": 0}, {"limit": 10001}, {"limit": True},
    {"start": "2026-10-01", "end": "2026-10-09"},
    {"start": "2026-10-09T15:00:00Z", "end": "2026-10-09T14:00:00Z"},
    {"asof": "-"}, {"page_token": "https://evil.test/"},
])
def test_request_bounds_checked_before_any_attempt(overrides):
    config = settings()
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response())
    with pytest.raises(ProviderError):
        bars(client, **overrides)
    assert not calls and not connection.execute("SELECT * FROM provider_request_log").fetchall()


def test_delayed_profile_uses_explicit_sip_wire_feed_and_cutoff():
    config = settings(alpaca_feed="delayed_sip")
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response())
    result = bars(client)
    assert not result.from_cache and calls[0].url.params["feed"] == "sip"
    assert client.public_profile()["delay_ns"] == 900_000_000_000
    with pytest.raises(Exception) as caught:
        bars(client, start="2026-10-11T15:00:00Z", end="2026-10-11T15:59:00Z")
    assert getattr(caught.value, "code", None) == "INVALID_REQUEST"
    assert len(calls) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_is_rejected_without_second_host(status):
    config = settings()
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or
                      response(status=status, headers={"Location": "https://evil.test"}))
    with pytest.raises(Exception) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "REDIRECT_REJECTED" and len(calls) == 1


def test_metadata_bootstrap_does_not_require_stream_readiness():
    config = settings(alpaca_max_connections=0, alpaca_max_queue_events=0, alpaca_max_archive_bytes=0)
    connection = db()
    prof = profile(config)
    assert not prof.ready_for_capture
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response([]), prof)
    result = client.request_page("assets", {"status": "all", "asset_class": "us_equity"})
    assert result.payload == [] and str(calls[0].url.host) == "paper-api.alpaca.markets"


def test_registry_keeps_alpaca_out_of_eod_selection():
    from backend.app.data_providers.provider_registry import ProviderRegistry
    registry = ProviderRegistry(settings(), db())
    assert all(p.provider_name != "alpaca" for p in registry.providers)
    assert registry.provider_for_asset_type("stock") is None
    assert registry.alpaca_market(profile(registry.settings)).provider_name == "alpaca"


def test_corporate_actions_structural_whitelist_preserves_known_rows():
    config = settings()
    connection = db()
    payload = {"corporate_actions": {"forward_splits": [
        {"id": "public-event", "old_symbol": "AAPL", "new_symbol": "AAPL", "old_rate": 1,
         "new_rate": 2, "process_date": "2026-10-09", "untrusted": "drop"}]},
        "next_page_token": None, "untrusted": "drop"}
    client = provider(connection, config, lambda _: response(payload))
    result = client.request_page("corporate_actions", {"symbols": "AAPL", "start": "2026-10-09",
                                  "end": "2026-10-09", "limit": "1000", "sort": "asc", "region": "us",
                                  "data_quality": "complete"})
    assert result.payload["corporate_actions"]["forward_splits"][0]["new_rate"] == 2
    assert "untrusted" not in public_db(connection)


@pytest.mark.parametrize("value", [{"hidden": "object"}, ["nested"], float("nan")])
def test_wrong_row_field_structure_rejected(value):
    config = settings()
    connection = db()
    raw = json.dumps({"bars": {"AAPL": [{"o": value}]}}).encode()
    client = provider(connection, config, lambda _: httpx.Response(200, content=raw,
                       headers={"content-type": "application/json"}))
    with pytest.raises(Exception) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "INVALID_PAYLOAD"
    assert not connection.execute("SELECT * FROM api_cache").fetchall()


def test_response_size_and_timeout_exception_are_sanitized():
    config = settings(alpaca_max_frame_bytes=128)
    connection = db()
    client = provider(connection, config, lambda _: response({"bars": {}, "ignored": "x" * 256}))
    with pytest.raises(Exception) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "RESPONSE_TOO_LARGE"
    assert not connection.execute("SELECT * FROM api_cache").fetchall()


def test_timeout_retries_consume_budget_without_echoing_exception(caplog):
    config = settings()
    connection = db()
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout(config.alpaca_api_secret_key)
    client = provider(connection, config, handler)
    with pytest.raises(Exception) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "RETRY_EXHAUSTED" and len(calls) == 3
    assert config.alpaca_api_secret_key not in str(caught.value) + caplog.text + public_db(connection)
    assert connection.execute("SELECT calls_count FROM api_usage").fetchone()[0] == 3


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_rate_headers_do_not_upgrade_or_break_valid_response(value):
    config = settings()
    connection = db()
    client = provider(connection, config, lambda _: response(headers={"X-RateLimit-Limit": value,
                                                                     "X-RateLimit-Remaining": value}))
    assert bars(client).attempts == 1
    row = connection.execute("SELECT effective_limit FROM provider_usage_windows WHERE window_kind='MINUTE'").fetchone()
    assert row[0] == config.alpaca_http_minute_limit


def test_retry_after_is_bounded_even_if_legacy_config_is_large():
    config = settings(provider_retry_after_cap_seconds=100000)
    connection = db()
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        return response(status=429, headers={"Retry-After": "100000"}) if len(calls) == 1 else response()
    result = bars(provider(connection, config, handler, sleeper=waits.append))
    assert result.attempts == 2 and waits == [60]


def test_401_blocks_all_capabilities_but_403_only_denies_requested_capability():
    for status in (401, 403):
        config = settings()
        connection = db()
        calls = []
        def handler(request, *, calls=calls, status=status):
            calls.append(request)
            return response(status=status) if len(calls) == 1 else response({"quotes": {}, "next_page_token": None})
        client = provider(connection, config, handler)
        with pytest.raises(ProviderError):
            bars(client)
        if status == 401:
            with pytest.raises(Exception) as caught:
                client.get_quotes_page(symbols=("AAPL",), start="2026-10-09T14:00:00Z",
                                       end="2026-10-09T15:00:00Z", asof="2026-10-09")
            assert getattr(caught.value, "code", None) == "AUTHENTICATION_FAILED" and len(calls) == 1
        else:
            assert client.get_quotes_page(symbols=("AAPL",), start="2026-10-09T14:00:00Z",
                                         end="2026-10-09T15:00:00Z", asof="2026-10-09").attempts == 1
            assert len(calls) == 2


def test_secret_in_query_value_never_enters_fingerprint_or_log():
    config = settings()
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response())
    with pytest.raises(Exception) as caught:
        bars(client, page_token=config.alpaca_api_secret_key)
    assert getattr(caught.value, "code", None) == "SECRET_IN_REQUEST"
    assert not calls and not connection.execute("SELECT * FROM provider_request_log").fetchall()


def test_news_and_metadata_use_only_their_documented_query_and_row_fields():
    config = settings()
    connection = db()
    calls = []
    def handler(request):
        calls.append(request)
        return response({"news": [{"id": 123, "headline": "Fixture", "content": "<script>ignored</script>",
                                  "summary": "Fixture", "symbols": ["AAPL"], "untrusted": "drop"}],
                         "next_page_token": None})
    client = provider(connection, config, handler)
    result = client.request_page("news", {"symbols": "AAPL", "start": "2026-10-09T14:00:00Z",
                                 "end": "2026-10-09T15:00:00Z", "sort": "asc", "limit": "50",
                                 "include_content": "false", "exclude_contentless": "false"})
    assert "content" not in result.payload["news"][0] and "untrusted" not in public_db(connection)
    assert not {"feed", "asof", "currency", "adjustment"} & set(calls[0].url.params)
    for capability, params in (("news", {"feed": "sip"}), ("assets", {"limit": "100"}),
                               ("calendar", {"page_token": "bad"})):
        with pytest.raises(Exception) as caught:
            client.request_page(capability, params)
        assert getattr(caught.value, "code", None) == "INVALID_REQUEST"
    assert len(calls) == 1


def test_public_profile_construction_does_not_include_auth_or_require_stream_readiness():
    from backend.app.intraday.profiles import profile_from_settings
    config = settings(alpaca_max_connections=0)
    built = profile_from_settings(config, attested_capabilities=("assets",), required_capabilities=("assets",))
    rotated = replace(config, alpaca_api_key_id=uuid.uuid4().hex, alpaca_api_secret_key=uuid.uuid4().hex)
    other = profile_from_settings(rotated, attested_capabilities=("assets",), required_capabilities=("assets",))
    assert built.profile_id == other.profile_id
    assert not built.ready_for_capture
    assert all(secret not in built.config_json for secret in (config.alpaca_api_key_id, config.alpaca_api_secret_key))


def test_numeric_credential_echo_is_rejected_before_json_decoding():
    value = str(uuid.uuid4().int % (10 ** 18))
    config = settings(alpaca_api_key_id=value)
    connection = db()
    client = provider(connection, config, lambda _: response({"bars": {"AAPL": [{"o": int(value)}]}}))
    with pytest.raises(ProviderError) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "SECRET_IN_RESPONSE"
    assert not connection.execute("SELECT * FROM api_cache").fetchall()


def test_429_without_headers_blocks_other_capabilities():
    config = settings(provider_default_max_attempts=1)
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response(status=429))
    with pytest.raises(ProviderError):
        bars(client)
    assert client.availability("quotes").state == "COOLDOWN"
    with pytest.raises(ProviderError) as caught:
        client.get_quotes_page(symbols=("AAPL",), start="2026-10-09T14:00:00Z",
                               end="2026-10-09T15:00:00Z", asof="2026-10-09")
    assert getattr(caught.value, "code", None) == "RATE_LIMITED" and len(calls) == 1


def test_warm_cache_respects_reduced_runtime_response_limit():
    config = settings()
    connection = db()
    payload = {"bars": {"AAPL": [{"t": "2026-10-09T14:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10, "v": 20}]}, "next_page_token": None}
    calls = []
    def handler(request):
        calls.append(request)
        return response(payload)
    bars(provider(connection, config, handler))
    narrowed = provider(connection, replace(config, alpaca_max_frame_bytes=32), handler, profile(config))
    with pytest.raises(ProviderError) as caught:
        bars(narrowed)
    assert getattr(caught.value, "code", None) == "RESPONSE_TOO_LARGE"
    assert len(calls) == 1 and not connection.execute("SELECT * FROM api_cache").fetchall()


def test_response_clock_starts_cooldown_at_receipt_and_dates_each_retry():
    from datetime import timedelta
    config = settings()
    connection = db()
    current = [NOW]
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            current[0] += timedelta(seconds=70)
            return response(status=429, headers={"Retry-After": "20", "X-RateLimit-Limit": "20",
                                                  "X-RateLimit-Remaining": "18"})
        current[0] += timedelta(seconds=3)
        return response()
    def sleeper(delay):
        assert not connection.in_transaction
        waits.append(delay)
        current[0] += timedelta(seconds=delay)
    client = provider(connection, config, handler, sleeper=sleeper)
    client.clock = lambda: current[0]
    result = bars(client)
    first = connection.execute("SELECT * FROM provider_request_log ORDER BY rowid LIMIT 1").fetchone()
    second = connection.execute("SELECT * FROM provider_request_log ORDER BY rowid DESC LIMIT 1").fetchone()
    assert waits == [20]
    assert first["cooldown_until"] == "2026-10-11T16:01:30Z"
    assert second["requested_at"] == "2026-10-11T16:01:30Z"
    assert result.fetched_at == current[0] == NOW + timedelta(seconds=93)


def test_singular_corporate_type_filter_is_valid_plural_is_rejected():
    config = settings()
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or
                      response({"corporate_actions": {"forward_splits": []}, "next_page_token": None}))
    params = {"symbols": "AAPL", "start": "2026-10-09", "end": "2026-10-09",
              "limit": "1000", "sort": "asc", "region": "us", "data_quality": "complete",
              "types": "forward_split"}
    assert client.request_page("corporate_actions", params).attempts == 1
    with pytest.raises(ProviderError):
        client.request_page("corporate_actions", {**params, "types": "forward_splits"})
    assert len(calls) == 1


@pytest.mark.parametrize("credential", ["alpaca_api_key_id", "alpaca_api_secret_key"])
def test_profile_builder_rejects_credentials_before_public_config_or_digest(credential):
    from backend.app.intraday.contracts import IntradayError
    from backend.app.intraday.profiles import profile_from_settings
    config = settings()
    with pytest.raises(IntradayError) as caught:
        profile_from_settings(config, attested_capabilities=("bars",),
                              required_capabilities=("bars",),
                              quote_conditions=(getattr(config, credential),))
    assert str(caught.value) == "PROFILE_INVALID"


@pytest.mark.parametrize("credential", ["alpaca_api_key_id", "alpaca_api_secret_key"])
def test_supplied_profile_cannot_echo_credentials_to_requests_or_public_output(credential):
    config = settings()
    connection = db()
    calls = []
    prof = profile(config, quote_conditions=(getattr(config, credential),))
    client = provider(connection, config, lambda request: calls.append(request) or response(), prof)
    for operation in (client.public_profile, lambda: bars(client)):
        with pytest.raises(Exception) as caught:
            operation()
        assert getattr(caught.value, "code", None) == "PROFILE_INVALID"
    assert client.availability("bars").reason_code == "PROFILE_INVALID"
    assert not calls and not connection.execute("SELECT * FROM api_cache").fetchall()


def test_headers_received_in_new_minute_reduce_that_minute_budget():
    from datetime import timedelta
    config = settings(provider_default_max_attempts=1)
    connection = db()
    current = [NOW]
    calls = []
    def handler(request):
        calls.append(request)
        current[0] += timedelta(seconds=70)
        return response(headers={"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "0"})
    client = provider(connection, config, handler)
    client.clock = lambda: current[0]
    bars(client)
    assert client.availability("quotes").reason_code == "BUDGET_EXHAUSTED"
    with pytest.raises(ProviderError) as caught:
        client.get_quotes_page(symbols=("AAPL",), start="2026-10-09T14:00:00Z",
                               end="2026-10-09T15:00:00Z", asof="2026-10-09")
    assert getattr(caught.value, "code", None) == "BUDGET_EXHAUSTED"
    assert len(calls) == 1


def test_timeout_sleep_cannot_reserve_next_minute_before_clock_reaches_it():
    from datetime import timedelta
    config = settings(alpaca_http_minute_limit=1)
    connection = db()
    current = [NOW - timedelta(seconds=2)]
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("synthetic timeout")
        return response()
    def sleeper(delay):
        current[0] += timedelta(seconds=delay)
    client = provider(connection, config, handler, sleeper=sleeper)
    client.clock = lambda: current[0]
    with pytest.raises(ProviderError) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "BUDGET_EXHAUSTED"
    assert len(calls) == 1
    logged = connection.execute("SELECT requested_at FROM provider_request_log").fetchall()
    assert len(logged) == 1 and logged[0]["requested_at"] == "2026-10-11T15:59:58Z"


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf")])
def test_nonfinite_legacy_cache_returns_static_error_and_is_purged(nonfinite):
    config = settings()
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response())
    bars(client)
    row = connection.execute("SELECT cache_key, response_json FROM api_cache").fetchone()
    envelope = json.loads(row["response_json"])
    envelope["payload"]["bars"] = {"AAPL": [{"o": nonfinite}]}
    connection.execute("UPDATE api_cache SET response_json=? WHERE cache_key=?",
                       (json.dumps(envelope), row["cache_key"]))
    connection.commit()
    with pytest.raises(ProviderError) as caught:
        bars(client)
    assert getattr(caught.value, "code", None) == "INVALID_PAYLOAD"
    assert len(calls) == 1 and not connection.execute("SELECT * FROM api_cache").fetchall()


@pytest.mark.parametrize("credential", [
    "alpha_vantage_api_key", "coingecko_api_key", "fred_api_key", "openfigi_api_key",
    "finnhub_api_key", "telegram_bot_token", "telegram_chat_id",
])
def test_public_profile_rejects_all_known_sensitive_settings(credential):
    from backend.app.intraday.contracts import IntradayError
    from backend.app.intraday.profiles import profile_from_settings
    secret = uuid.uuid4().hex
    config = settings(**{credential: secret})
    with pytest.raises(IntradayError) as caught:
        profile_from_settings(config, attested_capabilities=("bars",),
                              required_capabilities=("bars",), quote_conditions=(secret,))
    assert str(caught.value) == "PROFILE_INVALID"
    connection = db()
    calls = []
    client = provider(connection, config, lambda request: calls.append(request) or response(),
                      profile(config, quote_conditions=(secret,)))
    for operation in (client.public_profile, lambda: bars(client)):
        with pytest.raises(Exception) as caught:
            operation()
        assert getattr(caught.value, "code", None) == "PROFILE_INVALID"
    assert not calls and not connection.execute("SELECT * FROM api_cache").fetchall()


@pytest.mark.parametrize("stamp,expected", [("2026-10-12T13:30:00.000000001Z", 1),
                                           ("2026-10-12T15:30:00.000000002+02:00", 2)])
def test_market_decoder_preserves_nanoseconds_and_timezone(stamp, expected):
    from backend.app.data_providers.alpaca_market import _ns, decode_market_row, format_ns
    value = decode_market_row("QUOTE", {"t": stamp, "bp": 10, "ap": 11, "bs": 2, "as": 3, "c": []}, source="STREAM")
    assert _ns(value["raw"]["t"]) % 1_000_000_000 == expected
    assert _ns(format_ns(_ns(stamp))) == _ns(stamp)
    assert value["size_unit"] == "ROUND_LOTS"


@pytest.mark.parametrize("payload", [{"bars": {}}, {"quotes": {}}])
def test_market_page_requires_explicit_terminal_pagination(payload):
    from backend.app.data_providers.alpaca_market import _payload
    with pytest.raises(ValueError):
        _payload(next(iter(payload)), payload)


@pytest.mark.parametrize("change", [{"o": True}, {"h": 90}, {"v": -1}, {"vw": 500}, {"n": -1}])
def test_invalid_bar_economics_remain_quarantined(change):
    from backend.app.data_providers.alpaca_market import decode_market_row
    row = {"t": "2026-10-12T13:30:00Z", "o": 100, "h": 102, "l": 99, "c": 101, "v": 10, "vw": 100.5}
    value = decode_market_row("BAR", {**row, **change}, source="REST")
    assert value["reason_code"] == "BAR_INVALID"


@pytest.mark.parametrize("stamp", ["bad", "1969-12-31T23:59:59Z", "2026-10-12T13:30:00.1234567890Z"])
def test_bad_market_timestamps_fail_closed(stamp):
    from backend.app.data_providers.alpaca_market import decode_market_row
    with pytest.raises(ProviderError):
        decode_market_row("QUOTE", {"t": stamp, "bp": 1, "ap": 2, "bs": 1, "as": 1}, source="STREAM")
