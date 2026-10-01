from __future__ import annotations

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.database import SCHEMA, migrate_db
from backend.app.services.catalog_service import enqueue_catalog_eod
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.provider_budget_service import ProviderBudgetManager
from backend.app.services.refresh_planner_service import (
    MAX_REFRESH_BATCH,
    REFRESH_PRIORITY,
    RefreshOutcome,
    RefreshPlannerService,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "market_data"


def _open(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize(path: Path | None = None) -> sqlite3.Connection:
    connection = _open(path)
    connection.executescript(SCHEMA)
    migrate_db(connection)
    connection.commit()
    return connection


def _add_listing(
    connection: sqlite3.Connection,
    ticker: str,
    *,
    asset: bool = True,
    mapped: bool = True,
) -> int:
    instrument_id = connection.execute(
        """
        INSERT INTO instruments (canonical_name, instrument_type, asset_class, source, source_date)
        VALUES (?, 'STOCK', 'EQUITY', 'test', '2026-10-01')
        """,
        (f"{ticker} Corp",),
    ).lastrowid
    listing_id = int(
        connection.execute(
            """
            INSERT INTO instrument_listings (
                instrument_id, ticker, mic, venue_name, currency, timezone, source, source_date
            )
            VALUES (?, ?, 'XNAS', 'Nasdaq', 'USD', 'America/New_York', 'test', '2026-10-01')
            """,
            (instrument_id, ticker),
        ).lastrowid
    )
    if asset:
        connection.execute(
            """
            INSERT INTO assets (symbol, name, asset_type, currency, risk_level, instrument_listing_id)
            VALUES (?, ?, 'stock', 'USD', 'medium', ?)
            """,
            (ticker, f"{ticker} Corp", listing_id),
        )
    if mapped:
        connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol,
                status, source, observed_at, verified_at, evidence_hash
            )
            VALUES ('stooq', ?, 'EOD', ?, ?, 'VERIFIED', 'test', '2026-10-01T00:00:00Z',
                    '2026-10-01T00:00:00Z', ?)
            """,
            (listing_id, f"{ticker.lower()}.us", f"{ticker.upper()}.US", hashlib.sha256(ticker.encode()).hexdigest()),
        )
    connection.commit()
    return listing_id


def _requests(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT * FROM refresh_requests ORDER BY id").fetchall()


def _recording_planner(calls: list[tuple[int, bool]], state: str = "SUCCEEDED") -> RefreshPlannerService:
    planner = RefreshPlannerService()

    def execute(connection, request, now):  # noqa: ANN001, ANN202
        calls.append((int(request["listing_id"]), bool(request["force"])))
        return RefreshOutcome(
            request_id=int(request["id"]),
            listing_id=int(request["listing_id"]),
            symbol=None,
            state=state,
            provider="fixture",
            rows_inserted=0,
            rows_updated=0,
            used_cache=False,
            reason_code=None,
            message="fixture",
        )

    planner._execute = execute  # type: ignore[method-assign]
    return planner


T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_priority_table_matches_plan() -> None:
    assert REFRESH_PRIORITY == {
        "POSITION": 10,
        "STRATEGY_CANDIDATE": 20,
        "WATCHLIST": 30,
        "REQUESTED": 40,
        "VIEWED": 50,
        "CATALOG_EOD": 60,
    }
    assert MAX_REFRESH_BATCH == 25


def test_enqueue_deduplicates_open_unit_keeping_highest_priority_and_oldest_time() -> None:
    connection = _initialize()
    listing = _add_listing(connection, "AAA")
    planner = RefreshPlannerService()

    first = planner.enqueue(connection, listing, "EOD", "WATCHLIST", T0 + timedelta(minutes=2))
    second = planner.enqueue(connection, listing, "EOD", "POSITION", T0 + timedelta(minutes=3))
    third = planner.enqueue(connection, listing, "EOD", "VIEWED", T0)

    rows = _requests(connection)
    assert first == second == third
    assert len(rows) == 1
    assert (rows[0]["reason"], rows[0]["priority"]) == ("POSITION", 10)
    assert rows[0]["requested_at"] == T0.isoformat()
    assert connection.in_transaction is False


def test_force_is_promoted_atomically_but_never_demoted() -> None:
    connection = _initialize()
    listing = _add_listing(connection, "AAA")
    planner = RefreshPlannerService()

    planner.enqueue(connection, listing, "EOD", "WATCHLIST", T0, force=False)
    planner.enqueue(connection, listing, "EOD", "WATCHLIST", T0, force=True)
    planner.enqueue(connection, listing, "EOD", "REQUESTED", T0, force=False)

    assert _requests(connection)[0]["force"] == 1
    calls: list[tuple[int, bool]] = []
    _recording_planner(calls).run_batch(connection, 5, T0)
    assert calls == [(listing, True)]


def test_run_batch_orders_by_priority_then_requested_at_then_listing_id() -> None:
    connection = _initialize()
    a, b, c, d = (_add_listing(connection, ticker) for ticker in ("AAA", "BBB", "CCC", "DDD"))
    planner = RefreshPlannerService()
    planner.enqueue(connection, d, "EOD", "WATCHLIST", T0)
    planner.enqueue(connection, c, "EOD", "WATCHLIST", T0)
    planner.enqueue(connection, b, "EOD", "POSITION", T0 + timedelta(minutes=5))
    planner.enqueue(connection, a, "EOD", "WATCHLIST", T0 - timedelta(minutes=1))
    calls: list[tuple[int, bool]] = []

    result = _recording_planner(calls).run_batch(connection, 10, T0 + timedelta(minutes=10))

    assert [listing for listing, _force in calls] == [b, a, c, d]
    assert (result.selected, result.succeeded) == (4, 4)


@pytest.mark.parametrize("limit", [0, 26])
def test_run_batch_rejects_limits_outside_1_25(limit: int) -> None:
    connection = _initialize()
    with pytest.raises(ValueError):
        RefreshPlannerService().run_batch(connection, limit, T0)


def test_run_batch_never_executes_more_than_25_units() -> None:
    connection = _initialize()
    planner = RefreshPlannerService()
    for index in range(30):
        planner.enqueue(connection, _add_listing(connection, f"T{index:02d}"), "EOD", "WATCHLIST", T0)
    calls: list[tuple[int, bool]] = []

    result = _recording_planner(calls).run_batch(connection, 25, T0)

    assert result.selected == 25
    assert len(calls) == 25
    pending = connection.execute("SELECT COUNT(*) FROM refresh_requests WHERE state = 'PENDING'").fetchone()[0]
    assert pending == 5


def _fresh_observation(connection: sqlite3.Connection, listing_id: int, now: datetime) -> None:
    from backend.app.models.market_data import MarketObservationEnvelope
    from backend.app.services.market_observation_service import MarketObservationService

    envelope = MarketObservationEnvelope(
        listing_id=listing_id,
        provider="stooq",
        capability="EOD",
        operation="stooq_daily",
        received_at=now,
        provider_observed_at=now - timedelta(hours=2),
        timezone="America/New_York",
        session="REGULAR",
        currency="USD",
        source_quality="eod",
        kind="BAR",
        raw_fields={"close": "100", "volume": "10"},
        raw_payload_sha256=hashlib.sha256(f"fresh-{listing_id}".encode()).hexdigest(),
    )
    MarketObservationService().ingest_batch(connection, [envelope], now)
    connection.commit()


def test_fresh_unit_is_skipped_without_provider_call_unless_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _initialize()
    listing = _add_listing(connection, "AAA")
    now = datetime.now(UTC)
    _fresh_observation(connection, listing, now)
    calls: list[bool] = []

    def refresh_row(self, connection, asset, force=False):  # noqa: ANN001, ANN202
        calls.append(force)
        return {
            "symbol": asset["symbol"],
            "provider": "stooq",
            "rows_inserted": 1,
            "rows_updated": 0,
            "used_cache": False,
            "used_fallback": False,
            "message": "ok",
        }

    monkeypatch.setattr(MarketDataService, "refresh_asset_row", refresh_row)
    planner = RefreshPlannerService()

    planner.enqueue(connection, listing, "EOD", "WATCHLIST", now)
    skipped = planner.run_batch(connection, 5, now)
    planner.enqueue(connection, listing, "EOD", "REQUESTED", now, force=True)
    forced = planner.run_batch(connection, 5, now)

    assert (skipped.selected, skipped.skipped_fresh) == (1, 1)
    assert (forced.selected, forced.succeeded) == (1, 1)
    assert calls == [True]


def test_budget_cooldown_defers_without_reservation_or_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("ENABLE_STOOQ", "true")
    get_settings.cache_clear()
    connection = _initialize()
    listing = _add_listing(connection, "AAA")
    now = datetime.now(UTC)
    # Una richiesta reale respinta con 429 apre il cooldown del provider.
    from backend.app.data_providers.stooq import StooqProvider

    manager = ProviderBudgetManager()
    reservation = manager.reserve(
        connection, StooqProvider(get_settings(), connection).policy, "stooq", "EOD", "a" * 64, now
    )
    manager.complete(connection, reservation, "RATE_LIMITED", 429, 0, now + timedelta(minutes=10))
    manager.restrict(
        connection, "stooq", now, minute_limit=None, remaining=None, cooldown_until=now + timedelta(minutes=10)
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        MarketDataService,
        "refresh_asset_row",
        lambda self, connection, asset, force=False: calls.append(force)
        or {
            "symbol": asset["symbol"],
            "provider": "stooq",
            "rows_inserted": 0,
            "rows_updated": 0,
            "used_cache": True,
            "used_fallback": False,
            "message": "ok",
        },
    )
    planner = RefreshPlannerService()
    try:
        planner.enqueue(connection, listing, "EOD", "WATCHLIST", now)
        deferred = planner.run_batch(connection, 5, now)
        again = planner.run_batch(connection, 5, now + timedelta(minutes=1))
        row = _requests(connection)[0]
        reservations = connection.execute(
            "SELECT COUNT(*) FROM provider_request_log WHERE provider = 'stooq'"
        ).fetchone()[0]
    finally:
        get_settings.cache_clear()

    assert (deferred.selected, deferred.budget_deferred) == (1, 1)
    assert again.selected == 0
    assert row["state"] == "BUDGET_DEFERRED"
    assert row["not_before"] is not None
    assert reservations == 1  # solo la richiesta 429 iniziale: il rinvio non consuma budget
    assert calls == []


def test_failure_is_sanitized_and_other_units_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _initialize()
    bad = _add_listing(connection, "BAD")
    good = _add_listing(connection, "GOOD")

    def refresh_row(self, connection, asset, force=False):  # noqa: ANN001, ANN202
        if asset["symbol"] == "BAD":
            raise RuntimeError("failed at https://provider.example/path?token=SECRET")
        return {
            "symbol": asset["symbol"],
            "provider": "stooq",
            "rows_inserted": 2,
            "rows_updated": 1,
            "used_cache": False,
            "used_fallback": False,
            "message": "ok",
        }

    monkeypatch.setattr(MarketDataService, "refresh_asset_row", refresh_row)
    planner = RefreshPlannerService()
    planner.enqueue(connection, bad, "EOD", "POSITION", T0)
    planner.enqueue(connection, good, "EOD", "WATCHLIST", T0)

    result = planner.run_batch(connection, 5, T0)

    states = {row["listing_id"]: row for row in _requests(connection)}
    assert (result.failed, result.succeeded) == (1, 1)
    assert states[bad]["state"] == "FAILED"
    assert "SECRET" not in str(states[bad]["last_reason_code"])
    assert "https://" not in str(states[bad]["last_reason_code"])
    assert states[good]["state"] == "SUCCEEDED"
    runs = connection.execute("SELECT state, rows_inserted FROM refresh_runs ORDER BY id").fetchall()
    assert [tuple(row) for row in runs] == [("FAILED", 0), ("SUCCEEDED", 2)]


def test_concurrent_batches_never_execute_the_same_unit_twice(tmp_path: Path) -> None:
    database = tmp_path / "planner.db"
    setup = _initialize(database)
    listings = [_add_listing(setup, f"C{index}") for index in range(6)]
    planner = RefreshPlannerService()
    for listing in listings:
        planner.enqueue(setup, listing, "EOD", "WATCHLIST", T0)
    setup.close()
    executed: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        connection = _open(database)
        calls: list[tuple[int, bool]] = []
        _recording_planner(calls).run_batch(connection, 25, T0)
        with lock:
            executed.extend(listing for listing, _force in calls)
        connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(worker), pool.submit(worker)]:
            future.result(timeout=10)

    assert sorted(executed) == sorted(listings)


def _patch_stooq_network(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    import backend.app.data_providers.transport as transport_module

    payload = (FIXTURE_DIR / "stooq_daily.csv").read_bytes()
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(200, stream=httpx.ByteStream(payload), headers={"content-type": "text/csv"})

    monkeypatch.setattr(
        transport_module.httpx,
        "Client",
        lambda *_args, **_kwargs: real_client(transport=httpx.MockTransport(handler)),
    )


def test_non_forced_run_uses_cache_and_forced_run_makes_one_governed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("ENABLE_STOOQ", "true")
    get_settings.cache_clear()
    calls: list[str] = []
    _patch_stooq_network(monkeypatch, calls)
    connection = _initialize()
    listing = _add_listing(connection, "ACME")
    planner = RefreshPlannerService()
    now = datetime.now(UTC)
    try:
        planner.enqueue(connection, listing, "EOD", "WATCHLIST", now)
        first = planner.run_batch(connection, 5, now)
        planner.enqueue(connection, listing, "EOD", "WATCHLIST", now)
        cached = planner.run_batch(connection, 5, now)
        planner.enqueue(connection, listing, "EOD", "REQUESTED", now, force=True)
        forced = planner.run_batch(connection, 5, now)
        runs = connection.execute("SELECT state, used_cache FROM refresh_runs ORDER BY id").fetchall()
    finally:
        get_settings.cache_clear()

    assert (first.succeeded, cached.succeeded, forced.succeeded) == (1, 1, 1)
    assert calls == ["stooq.com", "stooq.com"]
    assert [tuple(row) for row in runs] == [("SUCCEEDED", 0), ("SUCCEEDED", 1), ("SUCCEEDED", 0)]


def test_catalog_eod_keyset_pages_never_skip_and_queries_are_bounded() -> None:
    connection = _initialize()
    mapped = [_add_listing(connection, f"K{index}", asset=False) for index in range(5)]
    unmapped = _add_listing(connection, "NOMAP", asset=False, mapped=False)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    planner = RefreshPlannerService()

    page_one = enqueue_catalog_eod(connection, planner, after_listing_id=0, limit=2, now=T0)
    calls: list[tuple[int, bool]] = []
    _recording_planner(calls).run_batch(connection, 25, T0)
    page_two = enqueue_catalog_eod(connection, planner, after_listing_id=page_one.next_cursor or 0, limit=2, now=T0)
    page_three = enqueue_catalog_eod(connection, planner, after_listing_id=page_two.next_cursor or 0, limit=2, now=T0)
    page_four = enqueue_catalog_eod(connection, planner, after_listing_id=page_three.next_cursor or 0, limit=2, now=T0)
    connection.set_trace_callback(None)

    enqueued = [
        row["listing_id"]
        for row in connection.execute(
            "SELECT listing_id FROM refresh_requests WHERE reason = 'CATALOG_EOD' ORDER BY listing_id"
        )
    ]
    assert (page_one.enqueued, page_one.next_cursor) == (2, mapped[1])
    assert (page_two.enqueued, page_two.next_cursor) == (2, mapped[3])
    assert page_three.enqueued == 1
    assert page_three.next_cursor == unmapped
    assert (page_four.enqueued, page_four.next_cursor) == (0, None)
    assert enqueued == mapped
    assert [listing for listing, _force in calls] == mapped[:2]
    listing_scans = [sql for sql in statements if "FROM instrument_listings" in sql and "SELECT" in sql.upper()]
    assert listing_scans and all("LIMIT" in sql.upper() or "id = " in sql for sql in listing_scans)
    assert all(row["force"] == 0 for row in _requests(connection))


@pytest.mark.parametrize("limit", [0, 26])
def test_catalog_eod_rejects_limits_outside_1_25(limit: int) -> None:
    connection = _initialize()
    with pytest.raises(ValueError):
        enqueue_catalog_eod(connection, RefreshPlannerService(), after_listing_id=0, limit=limit, now=T0)


def test_batch_with_two_real_units_keeps_provider_calls_outside_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regressione: ingest_batch lascia la transazione al chiamante; senza commit per unita
    # la seconda chiamata provider veniva rifiutata dal budget (TRANSPORT_FAILED).
    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("ENABLE_STOOQ", "true")
    get_settings.cache_clear()
    calls: list[str] = []
    _patch_stooq_network(monkeypatch, calls)
    connection = _initialize()
    first = _add_listing(connection, "ONE")
    second = _add_listing(connection, "TWO")
    planner = RefreshPlannerService()
    now = datetime.now(UTC)
    try:
        planner.enqueue(connection, first, "EOD", "WATCHLIST", now)
        planner.enqueue(connection, second, "EOD", "WATCHLIST", now)
        result = planner.run_batch(connection, 5, now)
    finally:
        get_settings.cache_clear()

    assert (result.selected, result.succeeded) == (2, 2)
    assert calls == ["stooq.com", "stooq.com"]
    assert connection.in_transaction is False


def test_activate_script_requires_bounded_limit_and_defaults_to_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backend.scripts import activate_real_data

    source = Path(activate_real_data.__file__).read_text(encoding="utf-8")
    assert "time.sleep" not in source
    assert "Alpha" not in source
    with pytest.raises(SystemExit):
        activate_real_data.build_parser().parse_args([])
    with pytest.raises(SystemExit):
        activate_real_data.build_parser().parse_args(["--limit", "26"])

    database = tmp_path / "script.db"
    connection = _initialize(database)
    _add_listing(connection, "AAA")
    connection.close()
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database))
    get_settings.cache_clear()
    try:
        exit_code = activate_real_data.main(["--limit", "5"])
    finally:
        get_settings.cache_clear()
    verification = _open(database)

    assert exit_code == 0
    assert "Anteprima" in capsys.readouterr().out
    assert verification.execute("SELECT COUNT(*) FROM refresh_requests").fetchone()[0] == 0
