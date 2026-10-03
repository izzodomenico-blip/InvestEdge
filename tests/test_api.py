from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import sqlite3

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.services.backtest_engine import BacktestEngine
from backend.app.services.technical_analysis import TechnicalAnalysisService


def _asset_dependency_state(symbol: str) -> tuple[int | None, dict[str, int], dict[str, int]]:
    from backend.app.database import db_session

    with db_session() as connection:
        asset = connection.execute(
            "SELECT id FROM assets WHERE UPPER(symbol) = UPPER(?)",
            (symbol,),
        ).fetchone()
        totals = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM price_history) AS price_history,
                    (SELECT COUNT(*) FROM portfolio_positions) AS portfolio_positions,
                    (SELECT COUNT(*) FROM simulated_orders) AS simulated_orders,
                    (SELECT COUNT(*) FROM signals) AS signals,
                    (SELECT COUNT(*) FROM news_items) AS news_items
                """
            ).fetchone()
        )
        if asset is None:
            return None, dict.fromkeys(totals, 0), totals

        asset_id = int(asset["id"])
        counts = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM price_history WHERE asset_id = ?) AS price_history,
                    (SELECT COUNT(*) FROM portfolio_positions WHERE asset_id = ?) AS portfolio_positions,
                    (SELECT COUNT(*) FROM simulated_orders WHERE asset_id = ?) AS simulated_orders,
                    (SELECT COUNT(*) FROM signals WHERE asset_id = ?) AS signals,
                    (SELECT COUNT(*) FROM news_items WHERE asset_id = ?) AS news_items
                """,
                (asset_id, asset_id, asset_id, asset_id, asset_id),
            ).fetchone()
        )
        return asset_id, counts, totals


def _enable_google_sheets_import(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("ENABLE_GOOGLE_SHEETS_IMPORT", "true")
    get_settings.cache_clear()


def _preview_and_apply_import(client: TestClient, payload: dict[str, object]) -> httpx.Response:
    preview = client.post("/import/google-sheets/preview", json=payload)
    assert preview.status_code == 200
    return client.post(
        "/import/google-sheets/apply",
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )


def _resolution_subject(
    connection: sqlite3.Connection,
    symbol: str,
) -> dict[str, object]:
    active = connection.execute(
        """
        SELECT il.instrument_id, il.id AS listing_id, a.currency, a.asset_type
        FROM assets AS a
        JOIN instrument_listings AS il ON il.id = a.instrument_listing_id
        WHERE UPPER(a.symbol) = UPPER(?)
        """,
        (symbol,),
    ).fetchone()
    if active is not None:
        return {
            "instrument_id": int(active["instrument_id"]),
            "listing_id": int(active["listing_id"]),
            "currency": str(active["currency"]),
            "asset_type": str(active["asset_type"]),
        }

    instrument_id = int(
        connection.execute(
            """
            INSERT INTO instruments (
                canonical_name, instrument_type, asset_class, quality_tier, source
            )
            VALUES (?, 'STOCK', 'EQUITY', 'REFERENCE_ONLY', 'TEST_RESOLUTION')
            """,
            (symbol,),
        ).lastrowid
    )
    return {
        "instrument_id": instrument_id,
        "listing_id": None,
        "currency": "EUR",
        "asset_type": "stock",
    }


def _create_resolution_listing(
    connection: sqlite3.Connection,
    *,
    instrument_id: int,
    symbol: str,
    currency: str,
    mic: str,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO instrument_listings (
                instrument_id, ticker, mic, venue_name, currency, timezone,
                listing_status, trade_republic_status, source
            )
            VALUES (?, ?, ?, ?, ?, 'Europe/Rome', 'ACTIVE', 'NEVER_SEEN', 'TEST_RESOLUTION')
            """,
            (instrument_id, symbol, mic, f"Venue {mic}", currency),
        ).lastrowid
    )


def _append_resolution_case(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    instrument_id: int,
    listing_id: int | None,
    status: str = "RESOLVED",
    evidence_hash: str = "a" * 64,
    catalog_entry_id: int | None = None,
    candidate_count: int | None = None,
) -> dict[str, int | None]:
    ordinal = int(
        connection.execute("SELECT COUNT(*) FROM instrument_resolution_cases").fetchone()[0]
    ) + 1
    if catalog_entry_id is None:
        snapshot_hash = hashlib.sha256(
            f"snapshot|{symbol}|{ordinal}".encode()
        ).hexdigest()
        snapshot_id = int(
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, row_count,
                    status, parser_version
                )
                VALUES (
                    'TEST_RESOLUTION', 'https://example.test/catalog', ?,
                    '2026-08-17T00:00:00Z', 1, 'COMPLETE', 'test-v1'
                )
                """,
                (snapshot_hash,),
            ).lastrowid
        )
        catalog_entry_id = int(
            connection.execute(
                """
                INSERT INTO catalog_entries (
                    snapshot_id, row_number, isin, name, parse_status, reason_code,
                    raw_row_sha256, instrument_id, listing_id
                )
                VALUES (?, 1, 'US0378331005', ?, 'ACCEPTED', 'VALID_ISIN', ?, ?, ?)
                """,
                (
                    snapshot_id,
                    symbol,
                    hashlib.sha256(f"entry|{symbol}|{ordinal}".encode()).hexdigest(),
                    instrument_id,
                    listing_id,
                ),
            ).lastrowid
        )

    effective_candidate_count = (
        candidate_count
        if candidate_count is not None
        else (0 if status == "UNMATCHED" else 1)
    )
    reason_by_status = {
        "RESOLVED": "EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE",
        "AMBIGUOUS": "MULTIPLE_COMPATIBLE_CANDIDATES",
        "UNMATCHED": "NO_PROVIDER_MATCH",
        "REJECTED": "MISSING_CURRENCY",
    }
    selected_listing_id = listing_id if status == "RESOLVED" else None
    case_id = int(
        connection.execute(
            """
            INSERT INTO instrument_resolution_cases (
                catalog_entry_id, provider, request_fingerprint, status, reason_code,
                candidate_count, candidate_hash, evidence_hash,
                selected_instrument_id, selected_listing_id, candidate_figi,
                candidate_ticker, candidate_exchange_code, candidate_market_sector,
                candidate_security_type, candidate_name, candidate_currency_hint,
                created_at
            )
            VALUES (
                ?, 'openfigi', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                'Equity', 'Common Stock', ?, 'EUR', '2026-08-17T00:00:00Z'
            )
            """,
            (
                catalog_entry_id,
                hashlib.sha256(f"request|{ordinal}".encode()).hexdigest(),
                status,
                reason_by_status[status],
                effective_candidate_count,
                hashlib.sha256(f"candidates|{ordinal}".encode()).hexdigest(),
                evidence_hash,
                instrument_id,
                selected_listing_id,
                f"FIGI{ordinal:08d}" if effective_candidate_count else None,
                symbol if effective_candidate_count else None,
                symbol,
            ),
        ).lastrowid
    )
    return {
        "case_id": case_id,
        "catalog_entry_id": catalog_entry_id,
        "listing_id": selected_listing_id,
    }


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_lifespan_backs_up_before_initializing_outside_tests(monkeypatch) -> None:
    from backend.app import main

    events: list[str] = []
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def prepare_database(**kwargs) -> None:  # noqa: ANN003
        assert kwargs == {"reason": "pre-migration", "backup_existing": True}
        events.append("prepare")

    monkeypatch.setattr(main, "prepare_database", prepare_database, raising=False)
    monkeypatch.setattr(main, "backup_before_migration", lambda: events.append("legacy-backup"), raising=False)
    monkeypatch.setattr(main, "init_db", lambda: events.append("legacy-init"), raising=False)

    async def run_lifespan() -> None:
        async with main.lifespan(None):
            events.append("yield")

    asyncio.run(run_lifespan())

    assert events == ["prepare", "yield"]


def test_lifespan_does_not_initialize_or_write_catalog_snapshot_when_backup_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from backend.app import main
    from backend.app.config import get_settings
    from backend.app.database import db_session, init_db

    events: list[str] = []
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "backup-failure.db"))
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    get_settings.cache_clear()
    init_db()

    def fail_prepare(**kwargs) -> None:  # noqa: ANN003
        assert kwargs == {"reason": "pre-migration", "backup_existing": True}
        events.append("prepare")
        raise RuntimeError("backup failed")

    def fail_legacy_backup() -> None:
        events.append("legacy-backup")
        raise RuntimeError("backup failed")

    monkeypatch.setattr(main, "prepare_database", fail_prepare, raising=False)
    monkeypatch.setattr(main, "backup_before_migration", fail_legacy_backup, raising=False)
    monkeypatch.setattr(main, "init_db", lambda: events.append("legacy-init"), raising=False)

    async def run_lifespan() -> None:
        async with main.lifespan(None):
            events.append("yield")

    with pytest.raises(RuntimeError, match="backup failed"):
        asyncio.run(run_lifespan())

    assert events == ["prepare"]
    with db_session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM catalog_snapshots").fetchone()[0] == 0
    get_settings.cache_clear()


def test_admin_seed_route_is_not_exposed(client: TestClient) -> None:
    response = client.post("/admin/seed?reset=true")

    assert response.status_code == 404


def test_assets_after_seed(client: TestClient) -> None:
    response = client.get("/assets")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert {asset["symbol"] for asset in data} >= {"AAPL", "BTC", "TLT"}
    assert data[0]["last_price"] is not None


def test_assets_contract_preserves_assetout_fields_and_excludes_listing_identity(
    client: TestClient,
) -> None:
    from backend.app.models import AssetCreate, AssetOut

    expected_create_fields = [
        "symbol",
        "name",
        "asset_type",
        "tax_category",
        "exchange",
        "currency",
        "sector",
        "country",
        "risk_level",
        "isin",
    ]
    expected_out_fields = [
        *expected_create_fields,
        "id",
        "last_price",
        "fx_rate_to_base",
        "last_price_base",
        "daily_change_pct",
        "last_source",
        "provider",
        "is_real_data",
        "last_price_date",
        "last_fetch_at",
        "score",
        "technical_score",
        "news_score",
        "final_score",
        "news_sentiment_label",
        "news_impact_level",
        "signal",
        "confidence",
        "technical_summary",
        "updated_at",
        "signal_data_mode",
        "score_unavailable_reason",
    ]

    assert list(AssetCreate.model_fields) == expected_create_fields
    assert list(AssetOut.model_fields) == expected_out_fields
    canonical_asset = AssetOut(
        symbol="CONTRACT",
        name="Contract asset",
        asset_type="stock",
        tax_category="standard",
        exchange="XNAS",
        currency="USD",
        sector="Technology",
        country="US",
        risk_level="medium",
        isin="US0378331005",
        id=42,
        last_price=101.25,
        fx_rate_to_base=0.92,
        last_price_base=93.15,
        daily_change_pct=1.5,
        last_source="legacy-source",
        provider="legacy-provider",
        is_real_data=True,
        last_price_date="2026-08-15",
        last_fetch_at="2026-08-16T10:00:00Z",
        score=75.0,
        technical_score=70.0,
        news_score=5.0,
        final_score=75.0,
        news_sentiment_label="POSITIVE",
        news_impact_level="MEDIUM",
        signal="BUY",
        confidence="HIGH",
        technical_summary="Legacy summary",
        updated_at="2026-08-16T10:00:00Z",
    )
    assert canonical_asset.model_dump_json().encode() == (
        b'{"symbol":"CONTRACT","name":"Contract asset","asset_type":"stock",'
        b'"tax_category":"standard","exchange":"XNAS","currency":"USD",'
        b'"sector":"Technology","country":"US","risk_level":"medium",'
        b'"isin":"US0378331005","id":42,"last_price":101.25,'
        b'"fx_rate_to_base":0.92,"last_price_base":93.15,"daily_change_pct":1.5,'
        b'"last_source":"legacy-source","provider":"legacy-provider",'
        b'"is_real_data":true,"last_price_date":"2026-08-15",'
        b'"last_fetch_at":"2026-08-16T10:00:00Z","score":75.0,'
        b'"technical_score":70.0,"news_score":5.0,"final_score":75.0,'
        b'"news_sentiment_label":"POSITIVE","news_impact_level":"MEDIUM",'
        b'"signal":"BUY","confidence":"HIGH","technical_summary":"Legacy summary",'
        b'"updated_at":"2026-08-16T10:00:00Z","signal_data_mode":null,'
        b'"score_unavailable_reason":null}'
    )
    response = client.get("/assets")
    assert response.status_code == 200
    assert all(list(asset) == expected_out_fields for asset in response.json())
    assert b"instrument_listing_id" not in response.content


def _create_ambiguous_assets(client: TestClient) -> None:
    for asset_type in ("stock", "etf"):
        response = client.post(
            "/assets",
            json={
                "symbol": "AMBIG",
                "name": f"Ambiguous {asset_type}",
                "asset_type": asset_type,
                "currency": "USD",
            },
        )
        assert response.status_code == 201


def test_legacy_symbol_ambiguity_returns_conflict_with_candidate_listings(
    client: TestClient,
) -> None:
    _create_ambiguous_assets(client)

    response = client.get("/assets/AMBIG")

    assert response.status_code == 409
    detail = response.json()["detail"]
    from backend.app.database import db_session

    with db_session() as connection:
        listing_ids = [
            int(row["instrument_listing_id"])
            for row in connection.execute(
                "SELECT instrument_listing_id FROM assets WHERE symbol = 'AMBIG' ORDER BY id"
            )
        ]
    assert "AMBIG" in detail
    assert "listing" in detail.lower()
    assert all(str(listing_id) in detail for listing_id in listing_ids)


def test_legacy_symbol_ambiguity_blocks_symbol_only_read_and_write_callers(
    client: TestClient,
) -> None:
    _create_ambiguous_assets(client)
    backtest_payload = {
        **_backtest_payload("BUY_AND_HOLD"),
        "symbols": ["AMBIG"],
    }
    compare_payload = {
        **_compare_payload(),
        "symbols": ["AMBIG"],
    }
    allocation_payload = _allocation_payload(
        "EQUAL_WEIGHT",
        symbols=["AMBIG"],
        confirmation_token="0" * 64,
    )
    requests = [
        ("GET", "/prices/AMBIG", None),
        ("GET", "/technical-analysis/AMBIG", None),
        ("GET", "/signals/AMBIG", None),
        ("GET", "/ml/predictions/AMBIG", None),
        ("GET", "/news?symbol=AMBIG", None),
        ("GET", "/news/sentiment/AMBIG", None),
        ("GET", "/news/AMBIG", None),
        ("GET", "/data/status/AMBIG", None),
        (
            "POST",
            "/orders/simulate",
            {"symbol": "AMBIG", "order_type": "BUY", "quantity": 1, "price": 10, "fees": 0},
        ),
        ("POST", "/portfolio/allocation/plan", allocation_payload),
        ("POST", "/portfolio/allocation/apply", allocation_payload),
        ("POST", "/portfolio/allocation/rebalance", allocation_payload),
        ("POST", "/backtests/run", backtest_payload),
        ("POST", "/backtests/compare", compare_payload),
        ("POST", "/backtests/walk-forward", {**backtest_payload, "folds": 2}),
        (
            "POST",
            "/ml/train",
            {"model_name": "Ambiguous", "symbols": ["AMBIG"], "min_samples": 20, "cv_folds": 2},
        ),
        ("POST", "/ml/predict/AMBIG", {}),
        ("POST", "/ml/predict-all", {}),
        ("POST", "/news/refresh/AMBIG", None),
        ("POST", "/news/refresh-all?limit=25", None),
        ("POST", "/data/refresh/AMBIG", None),
        ("POST", "/data/refresh-all", None),
    ]

    responses = {
        f"{method} {path}": client.request(method, path, json=payload)
        for method, path, payload in requests
    }

    assert {
        endpoint: response.status_code for endpoint, response in responses.items()
    } == dict.fromkeys(responses, 409)
    assert all("AMBIG" in response.json()["detail"] for response in responses.values())


def test_provider_refresh_guard_checks_symbol_then_releases_lock_before_network(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contratto aggiornato il 2026-09-30 (Task 12): il controllo di univocita resta
    # sotto lock, ma le route che chiamano provider rilasciano il lock prima dell'I/O
    # di rete. Il budget provider rifiuta transazioni del chiamante (Task 2): con il
    # lock tenuto ogni refresh reale via API cadeva in TRANSPORT_FAILED. Il refresh
    # resta sull'asset risolto prima del rilascio (id piu basso).
    response = client.post(
        "/assets",
        json={
            "symbol": "RACELOCK",
            "name": "Race lock stock",
            "asset_type": "stock",
            "currency": "USD",
        },
    )
    assert response.status_code == 201
    lock_errors: list[str] = []

    resolved: list[int] = []

    def probe_concurrent_duplicate(
        connection: sqlite3.Connection,
        asset: sqlite3.Row,
        force: bool = False,
    ) -> dict[str, object]:
        symbol = asset["symbol"]
        assert symbol == "RACELOCK"
        assert force is False
        assert connection.in_transaction is False
        database_path = connection.execute("PRAGMA database_list").fetchone()[2]
        try:
            with sqlite3.connect(database_path, timeout=0) as concurrent:
                concurrent.execute(
                    """
                    INSERT INTO assets (symbol, name, asset_type, currency)
                    VALUES ('RACELOCK', 'Concurrent ETF', 'etf', 'USD')
                    """
                )
        except sqlite3.OperationalError as exc:
            lock_errors.append(str(exc))
        resolved.append(int(asset["id"]))
        return {
            "symbol": symbol,
            "provider": "probe",
            "rows_inserted": 0,
            "rows_updated": 0,
            "used_cache": False,
            "used_fallback": False,
            "message": "Lock probe completed.",
        }

    from backend.app.api import routes

    monkeypatch.setattr(
        routes.market_data_service,
        "refresh_asset_row",
        probe_concurrent_duplicate,
    )

    response = client.post("/data/refresh/RACELOCK")

    assert response.status_code == 200
    assert lock_errors == []
    from backend.app.database import db_session

    with db_session() as connection:
        ids = [
            int(row["id"])
            for row in connection.execute("SELECT id FROM assets WHERE symbol = 'RACELOCK' ORDER BY id")
        ]
    assert len(ids) == 2
    assert resolved == [ids[0]]
    assert client.post("/data/refresh/RACELOCK").status_code == 409


def test_prices_for_symbol(client: TestClient) -> None:
    response = client.get("/prices/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert len(data["prices"]) >= 500
    assert {"date", "open", "high", "low", "close", "sma_50", "ema_50", "macd_line", "bollinger_upper"} <= set(data["prices"][-1])


def test_legacy_prices_expose_nullable_observation_provenance(client: TestClient) -> None:
    response = client.get("/prices/AAPL")

    assert response.status_code == 200
    point = response.json()["prices"][-1]
    assert {
        "listing_id",
        "observation_id",
        "provider_observed_at",
        "ingested_at",
        "timezone",
        "session",
        "currency",
        "delay_seconds",
        "source_quality",
        "effective_quality",
        "fallback_reason",
    } <= set(point)
    assert point["observation_id"] is None
    assert point["provider_observed_at"] is None
    assert point["effective_quality"] is None
    assert point["fallback_reason"] is None


def test_signals_after_seed(client: TestClient) -> None:
    response = client.get("/signals")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert data[0]["signal"] in {"STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"}
    assert 0 <= data[0]["score"] <= 100


def test_action_board_after_seed(client: TestClient) -> None:
    response = client.get("/action-board")

    assert response.status_code == 200
    data = response.json()
    assert {"generated_at", "data_mode", "headline", "counts", "actions"} <= set(data)
    assert data["data_mode"] == "SEED"
    assert isinstance(data["actions"], list)
    assert len(data["actions"]) >= 1
    valid_types = {"BUY", "REDUCE", "SELL", "WATCH", "RISK", "OK"}
    valid_priorities = {"HIGH", "MEDIUM", "LOW"}
    for action in data["actions"]:
        assert action["type"] in valid_types
        assert action["priority"] in valid_priorities
        assert action["title"]
        assert action["reason"]


def test_alerts_status_not_configured(client: TestClient) -> None:
    response = client.get("/alerts/status")

    assert response.status_code == 200
    data = response.json()
    assert data["channel"] == "telegram"
    assert data["enabled"] is False
    assert data["configured"] is False


def test_alerts_test_requires_config(client: TestClient) -> None:
    response = client.post("/alerts/test")

    assert response.status_code == 400
    assert "Telegram" in response.json()["detail"]


def test_alerts_send_today_requires_config(client: TestClient) -> None:
    response = client.post("/alerts/send-today")

    assert response.status_code == 400


def test_import_status_not_configured(client: TestClient) -> None:
    response = client.get("/import/google-sheets/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False
    assert data["configured"] is False


def test_import_preview_requires_enabled_flag(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: "symbol,quantity,average_price\nAAPL,1,150\n",
    )

    response = client.post(
        "/import/google-sheets/preview",
        json={"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 403


def test_import_apply_requires_enabled_flag(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: "symbol,quantity,average_price\nAAPL,1,150\n",
    )

    response = client.post(
        "/import/google-sheets/apply",
        json={"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 403


def test_import_preview_requires_url_when_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_google_sheets_import(monkeypatch)

    response = client.post("/import/google-sheets/preview", json={"csv_url": ""})

    assert response.status_code == 400
    assert "URL" in response.json()["detail"]


def test_import_apply_replaces_positions(client: TestClient, monkeypatch) -> None:
    _enable_google_sheets_import(monkeypatch)
    csv_text = (
        "symbol,quantity,average_price,currency\n"
        "AAPL,10,150,USD\n"
        "MSFT,4,300,USD\n"
    )
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: csv_text,
    )

    response = _preview_and_apply_import(
        client,
        {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 2
    assert data["initial_equity_base"] == pytest.approx(2484)
    assert data["current_cash_base"] == 0
    assert data["base_currency"] == "EUR"

    portfolio = client.get("/portfolio").json()
    symbols = {position["symbol"] for position in portfolio["positions"]}
    assert symbols == {"AAPL", "MSFT"}
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["quantity"] == 10
    assert aapl["average_price"] == 150
    assert portfolio["settings"]["initial_cash"] == pytest.approx(2484)
    assert portfolio["settings"]["current_cash"] == 0


def test_import_apply_creates_new_asset_with_import_reference_price(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: (
            "symbol,name,quantity,average_price,currency\n"
            "NEWIMPORT,New Import Asset,2,100,EUR\n"
        ),
    )

    response = _preview_and_apply_import(
        client,
        {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 200
    assert response.json()["created_assets"] == 1
    portfolio = client.get("/portfolio").json()
    position = next(item for item in portfolio["positions"] if item["symbol"] == "NEWIMPORT")
    assert position["current_price"] == 100
    assert position["current_value_base"] == 200
    assert portfolio["settings"]["initial_cash"] == 200
    assert portfolio["settings"]["current_cash"] == 0

    with db_session() as connection:
        reference_price = connection.execute(
            """
            SELECT ph.close, ph.source, ph.provider, ph.is_real_data
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE a.symbol = 'NEWIMPORT'
            """
        ).fetchone()

    assert tuple(reference_price) == (100, "google_sheets_import", "google_sheets_import", 0)


@pytest.mark.parametrize(
    "header,row",
    [
        ("symbol,quantity,average_price,asset_type,currency", "VWCE,2,100,etf,USD"),
        ("symbol,quantity,average_price,asset_type,currency", "VWCE,2,100,crypto,EUR"),
    ],
)
def test_import_apply_rejects_explicit_existing_asset_metadata_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    header: str,
    row: str,
) -> None:
    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: f"{header}\n{row}\n",
    )
    before = client.get("/portfolio").json()

    response = _preview_and_apply_import(
        client,
        {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 400
    assert "metadata" in response.json()["detail"].lower()
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]


def test_import_apply_uses_canonical_metadata_when_optional_columns_are_omitted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: "symbol,quantity,average_price\nVWCE,2,100\n",
    )

    response = _preview_and_apply_import(
        client,
        {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert response.status_code == 200
    position = next(item for item in client.get("/portfolio").json()["positions"] if item["symbol"] == "VWCE")
    assert position["asset_type"] == "etf"
    assert position["currency"] == "EUR"


def test_import_optional_metadata_is_explicit_per_nonempty_row_cell(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_google_sheets_import(monkeypatch)
    csv_text = (
        "symbol,quantity,average_price,asset_type,currency\n"
        "AAPL,1,100,,\n"
        "VWCE,2,100,crypto,EUR\n"
    )
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: csv_text,
    )

    mismatch = _preview_and_apply_import(
        client,
        {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert mismatch.status_code == 400
    assert "VWCE" in mismatch.json()["detail"]

    csv_text = (
        "symbol,quantity,average_price,asset_type,currency\n"
        "AAPL,1,100,,\n"
        "VWCE,2,100,etf,EUR\n"
    )
    applied = _preview_and_apply_import(
        client,
        {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"},
    )

    assert applied.status_code == 200
    positions = {item["symbol"]: item for item in client.get("/portfolio").json()["positions"]}
    assert positions["AAPL"]["asset_type"] == "stock"
    assert positions["AAPL"]["currency"] == "USD"
    assert positions["VWCE"]["asset_type"] == "etf"
    assert positions["VWCE"]["currency"] == "EUR"


def test_import_apply_rejects_stale_preview(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_google_sheets_import(monkeypatch)
    csv_versions = iter(
        [
            "symbol,quantity,average_price,currency\nAAPL,1,150,USD\n",
            "symbol,quantity,average_price,currency\nMSFT,1,300,USD\n",
        ]
    )
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: next(csv_versions),
    )
    before = client.get("/portfolio").json()
    input_payload = {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"}
    preview_response = client.post("/import/google-sheets/preview", json=input_payload)
    assert preview_response.status_code == 200
    confirmation_token = preview_response.json().get("confirmation_token")

    response = client.post(
        "/import/google-sheets/apply",
        json={**input_payload, "confirmation_token": confirmation_token},
    )

    assert response.status_code == 409
    assert client.get("/portfolio").json()["positions"] == before["positions"]


def test_import_resolution_snapshot_keeps_legacy_unmapped_apply(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: (
            "symbol,quantity,average_price,asset_type,currency\n"
            "LEGACYUNMAPPED,2,100,stock,EUR\n"
        ),
    )
    payload = {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"}

    preview = client.post("/import/google-sheets/preview", json=payload)
    response = client.post(
        "/import/google-sheets/apply",
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )

    assert preview.status_code == 200
    assert len(preview.json()["confirmation_token"]) == 64
    assert response.status_code == 200
    assert response.json()["created_assets"] == 1


def test_import_listing_token_changes_when_local_listing_resolves(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: (
            "symbol,quantity,average_price,asset_type,currency\n"
            "LISTINGTOKEN,2,100,stock,EUR\n"
        ),
    )
    payload = {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"}
    unmapped_preview = client.post("/import/google-sheets/preview", json=payload)
    assert unmapped_preview.status_code == 200

    with db_session() as connection:
        subject = _resolution_subject(connection, "LISTINGTOKEN")
        listing_id = _create_resolution_listing(
            connection,
            instrument_id=int(subject["instrument_id"]),
            symbol="LISTINGTOKEN",
            currency="EUR",
            mic="XTST",
        )
        _append_resolution_case(
            connection,
            symbol="LISTINGTOKEN",
            instrument_id=int(subject["instrument_id"]),
            listing_id=listing_id,
        )

    resolved_preview = client.post("/import/google-sheets/preview", json=payload)

    assert resolved_preview.status_code == 200
    assert len(resolved_preview.json()["confirmation_token"]) == 64
    assert (
        resolved_preview.json()["confirmation_token"]
        != unmapped_preview.json()["confirmation_token"]
    )


def test_import_listing_token_rejects_candidate_appearing_after_preview(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: (
            "symbol,quantity,average_price,asset_type,currency\n"
            "NEWCANDIDATE,2,100,stock,EUR\n"
        ),
    )
    payload = {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"}
    preview = client.post("/import/google-sheets/preview", json=payload)
    assert preview.status_code == 200
    before = client.get("/portfolio").json()

    with db_session() as connection:
        subject = _resolution_subject(connection, "NEWCANDIDATE")
        _append_resolution_case(
            connection,
            symbol="NEWCANDIDATE",
            instrument_id=int(subject["instrument_id"]),
            listing_id=None,
            status="REJECTED",
        )

    response = client.post(
        "/import/google-sheets/apply",
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "RESOLUTION_CHANGED"}
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]
    with db_session() as connection:
        assert connection.execute(
            "SELECT 1 FROM assets WHERE symbol = 'NEWCANDIDATE'"
        ).fetchone() is None


@pytest.mark.parametrize(
    "mutation",
    ["resolution_case_id", "listing_id", "status", "evidence_hash"],
)
def test_import_resolution_snapshot_change_is_stale_before_write(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from backend.app.database import db_session

    _enable_google_sheets_import(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: (
            "symbol,quantity,average_price,asset_type,currency\n"
            "TOKENSTATE,2,100,stock,EUR\n"
        ),
    )
    with db_session() as connection:
        subject = _resolution_subject(connection, "TOKENSTATE")
        listing_id = _create_resolution_listing(
            connection,
            instrument_id=int(subject["instrument_id"]),
            symbol="TOKENSTATE",
            currency="EUR",
            mic="XTST",
        )
        original = _append_resolution_case(
            connection,
            symbol="TOKENSTATE",
            instrument_id=int(subject["instrument_id"]),
            listing_id=listing_id,
        )

    payload = {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"}
    preview = client.post("/import/google-sheets/preview", json=payload)
    assert preview.status_code == 200
    before = client.get("/portfolio").json()

    with db_session() as connection:
        changed_listing_id = listing_id
        changed_status = "RESOLVED"
        changed_evidence = "a" * 64
        if mutation == "listing_id":
            changed_listing_id = _create_resolution_listing(
                connection,
                instrument_id=int(subject["instrument_id"]),
                symbol="TOKENSTATE",
                currency="EUR",
                mic="XALT",
            )
        elif mutation == "status":
            changed_status = "REJECTED"
        elif mutation == "evidence_hash":
            changed_evidence = "b" * 64
        _append_resolution_case(
            connection,
            symbol="TOKENSTATE",
            instrument_id=int(subject["instrument_id"]),
            listing_id=changed_listing_id,
            status=changed_status,
            evidence_hash=changed_evidence,
            catalog_entry_id=int(original["catalog_entry_id"]),
        )

    response = client.post(
        "/import/google-sheets/apply",
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "RESOLUTION_CHANGED"}
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]
    with db_session() as connection:
        assert connection.execute(
            "SELECT 1 FROM assets WHERE symbol = 'TOKENSTATE'"
        ).fetchone() is None


def test_import_listing_token_rejects_two_venue_candidates_without_transport(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    _enable_google_sheets_import(monkeypatch)
    transport_calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal transport_calls
        transport_calls += 1
        raise AssertionError("Import preview must not call OpenFIGI")

    monkeypatch.setattr(
        "backend.app.data_providers.openfigi.OpenFigiProvider.map_isins",
        fail_if_called,
    )
    monkeypatch.setattr(
        "backend.app.services.google_sheets_import_service.fetch_csv",
        lambda csv_url=None: (
            "symbol,quantity,average_price,asset_type,currency\n"
            "DUALVENUE,2,100,stock,EUR\n"
        ),
    )
    with db_session() as connection:
        subject = _resolution_subject(connection, "DUALVENUE")
        listing_id = _create_resolution_listing(
            connection,
            instrument_id=int(subject["instrument_id"]),
            symbol="DUALVENUE",
            currency="EUR",
            mic="XNYS",
        )
        _append_resolution_case(
            connection,
            symbol="DUALVENUE",
            instrument_id=int(subject["instrument_id"]),
            listing_id=listing_id,
        )

    payload = {"csv_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv"}
    preview = client.post("/import/google-sheets/preview", json=payload)
    assert preview.status_code == 200
    before = client.get("/portfolio").json()

    with db_session() as connection:
        second_listing_id = _create_resolution_listing(
            connection,
            instrument_id=int(subject["instrument_id"]),
            symbol="DUALVENUE",
            currency="EUR",
            mic="XNAS",
        )
        _append_resolution_case(
            connection,
            symbol="DUALVENUE",
            instrument_id=int(subject["instrument_id"]),
            listing_id=second_listing_id,
        )

    response = client.post(
        "/import/google-sheets/apply",
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "RESOLUTION_CHANGED"}
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]
    assert transport_calls == 0


def test_import_rolls_back_positions_assets_and_settings_on_second_position_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session
    from backend.app.services import google_sheets_import_service

    _enable_google_sheets_import(monkeypatch)
    allocation_response = _plan_and_apply_allocation(
        client,
        _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT"], total_capital=50000),
    )
    assert allocation_response.status_code == 200

    csv_text = (
        "symbol,quantity,average_price,currency\n"
        "SAFEIMPORT,2,100,EUR\n"
        "FAILIMPORT,3,200,EUR\n"
    )
    monkeypatch.setattr(google_sheets_import_service, "fetch_csv", lambda csv_url=None: csv_text)

    with db_session() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_second_import_position
            BEFORE INSERT ON portfolio_positions
            WHEN NEW.symbol = 'FAILIMPORT'
            BEGIN
                SELECT RAISE(ABORT, 'forced second position failure');
            END
            """
        )
        positions_before = [
            tuple(row)
            for row in connection.execute(
                "SELECT asset_id, symbol, quantity, average_price FROM portfolio_positions ORDER BY id"
            ).fetchall()
        ]
        settings_before = tuple(
            connection.execute(
                "SELECT initial_cash, current_cash, updated_at FROM portfolio_settings WHERE id = 1"
            ).fetchone()
        )
        asset_count_before = int(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])

        preview = google_sheets_import_service.preview(
            connection,
            "https://docs.google.com/spreadsheets/d/test/export?format=csv"
        )
        with pytest.raises(sqlite3.IntegrityError, match="forced second position failure"):
            google_sheets_import_service.apply_import(
                connection,
                "https://docs.google.com/spreadsheets/d/test/export?format=csv",
                preview["confirmation_token"],
            )

        positions_after = [
            tuple(row)
            for row in connection.execute(
                "SELECT asset_id, symbol, quantity, average_price FROM portfolio_positions ORDER BY id"
            ).fetchall()
        ]
        settings_after = tuple(
            connection.execute(
                "SELECT initial_cash, current_cash, updated_at FROM portfolio_settings WHERE id = 1"
            ).fetchone()
        )
        imported_assets = connection.execute(
            "SELECT symbol FROM assets WHERE symbol IN ('SAFEIMPORT', 'FAILIMPORT')"
        ).fetchall()
        asset_count_after = int(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0])

    assert positions_after == positions_before
    assert settings_after == settings_before
    assert imported_assets == []
    assert asset_count_after == asset_count_before


def test_ml_status_initially_empty(client: TestClient) -> None:
    response = client.get("/ml/status")

    assert response.status_code == 200
    data = response.json()
    assert data["models_count"] == 0
    assert data["ml_ready"] is False
    assert "HIST_GRADIENT_BOOSTING" in data["available_model_types"]


def test_ml_dataset_has_no_lookahead(client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.services.ml_dataset_service import FEATURE_COLUMNS, MLDatasetService

    service = MLDatasetService()
    with db_session() as connection:
        dataset = service.build_ml_dataset(
            connection=connection,
            symbols=["AAPL", "MSFT", "SPY"],
            horizon_days=14,
            target_type="POSITIVE_RETURN",
        )
    assert not dataset.empty
    assert set(FEATURE_COLUMNS).issubset(dataset.columns)
    # validate_no_lookahead raises if violated; here it must hold
    assert service.validate_no_lookahead(dataset) is True


def test_ml_train_reports_insufficient_split_after_temporal_purge(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api.routes import ml_engine
    from backend.app.services.ml_dataset_service import FEATURE_COLUMNS

    feature_dates = pd.date_range("2026-01-01", periods=20, freq="D")
    dataset = pd.DataFrame(
        {
            "symbol": "TEST",
            "date": feature_dates.strftime("%Y-%m-%d"),
            "target_date": (feature_dates + pd.to_timedelta(30, unit="D")).strftime("%Y-%m-%d"),
            "target": [index % 2 for index in range(20)],
        }
    )
    for index, column in enumerate(FEATURE_COLUMNS, start=1):
        dataset[column] = float(index)
    monkeypatch.setattr(ml_engine.dataset_service, "build_ml_dataset", lambda **_kwargs: dataset.copy())

    response = client.post(
        "/ml/train",
        json={
            "model_name": "Purged split",
            "symbols": ["TEST"],
            "horizon_days": 5,
            "min_samples": 20,
            "cv_folds": 2,
        },
    )

    assert response.status_code == 400
    assert "dopo la purga temporale" in response.json()["detail"].lower()


def test_ml_train_and_predict(client: TestClient) -> None:
    train_payload = {
        "model_name": "Test GB",
        "model_type": "HIST_GRADIENT_BOOSTING",
        "target_type": "POSITIVE_RETURN",
        "horizon_days": 14,
        "symbols": ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
        "min_samples": 100,
        "cv_folds": 3,
    }
    train_response = client.post("/ml/train", json=train_payload)
    assert train_response.status_code == 200
    train_data = train_response.json()
    assert train_data["model_id"] > 0
    metrics = train_data["metrics"]
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["walk_forward"] is None or metrics["walk_forward"]["folds"] >= 1

    status_response = client.get("/ml/status")
    assert status_response.json()["models_count"] == 1

    predict_response = client.post("/ml/predict/AAPL", json={})
    assert predict_response.status_code == 200
    prediction = predict_response.json()
    assert prediction["symbol"] == "AAPL"
    assert prediction["confidence"] in {"LOW", "MEDIUM", "HIGH"}
    assert prediction["predicted_label"]


def test_ml_predict_without_model_fails(client: TestClient) -> None:
    response = client.post("/ml/predict/AAPL", json={})

    assert response.status_code == 400
    assert "modello" in response.json()["detail"].lower()


def test_tax_report_after_buy_sell(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 80, "max_asset_class_weight": 90, "default_fee_percent": 0, "confirm_reset": "RESET_PORTFOLIO"},
    )
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 100, "fees": 0})
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 140, "fees": 0})

    response = client.get("/tax/report")

    assert response.status_code == 200
    data = response.json()
    assert data["lot_method"] == "SIMPLIFIED_FIFO"
    assert data["standard_rate"] == 26.0
    event = next(e for e in data["events"] if e["symbol"] == "AAPL")
    assert event["gain_native"] == 200.0  # 5 * (140 - 100) USD
    assert event["gain_base"] == 184.0  # cambio congelato USD/EUR 0,92
    assert event["gain"] == 184.0  # alias compatibile espresso nella valuta base EUR
    assert data["total_tax_due"] >= 47.84 - 1e-6  # 26% di 184 EUR


def test_tax_report_after_short_cover(client: TestClient) -> None:
    _init_flat(client)
    opened = client.post(
        "/orders/simulate",
        json={
            "symbol": "AAPL",
            "order_type": "SELL",
            "quantity": 10,
            "price": 100,
            "fees": 0,
            "allow_short": True,
        },
    )
    covered = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 80, "fees": 0},
    )
    assert opened.status_code == 200
    assert covered.status_code == 200

    response = client.get("/tax/report")

    assert response.status_code == 200
    data = response.json()
    event = next(item for item in data["events"] if item["symbol"] == "AAPL")
    assert event["open_side"] == "SELL"
    assert event["close_side"] == "BUY"
    assert event["sell_date"] is None
    assert event["realization_date"]
    assert event["gain_native"] == 200.0
    assert event["gain_base"] == 184.0
    assert event["gain"] == 184.0
    assert event["applied_rate"] == 26.0


def test_seed_assigns_explicit_tax_categories_and_default_is_standard(client: TestClient) -> None:
    created = client.post(
        "/assets",
        json={"symbol": "TAXDEFAULT", "name": "Tax default", "asset_type": "bond_etf", "currency": "EUR"},
    )
    assert created.status_code == 201

    from backend.app.database import db_session

    with db_session() as connection:
        rows = connection.execute(
            "SELECT symbol, tax_category FROM assets WHERE symbol IN ('BTP10Y', 'BTC', 'IB01', 'AGGH', 'TAXDEFAULT')"
        ).fetchall()

    categories = {row["symbol"]: row["tax_category"] for row in rows}
    assert categories == {
        "AGGH": "standard",
        "BTC": "crypto",
        "BTP10Y": "government_bond",
        "IB01": "standard",
        "TAXDEFAULT": "standard",
    }


def test_asset_tax_category_is_created_read_and_defaulted_safely(client: TestClient) -> None:
    explicit = client.post(
        "/assets",
        json={
            "symbol": "CRYPTO_EXPLICIT",
            "name": "Crypto explicit",
            "asset_type": "crypto",
            "currency": "EUR",
            "tax_category": "crypto",
        },
    )
    inferred_crypto = client.post(
        "/assets",
        json={
            "symbol": "CRYPTO_DEFAULT",
            "name": "Crypto default",
            "asset_type": "crypto",
            "currency": "EUR",
        },
    )
    unverified_bond_etf = client.post(
        "/assets",
        json={
            "symbol": "BOND_DEFAULT",
            "name": "Bond ETF default",
            "asset_type": "bond_etf",
            "currency": "EUR",
        },
    )
    invalid = client.post(
        "/assets",
        json={
            "symbol": "INVALID_TAX",
            "name": "Invalid tax",
            "asset_type": "stock",
            "currency": "EUR",
            "tax_category": "unsupported",
        },
    )

    assert explicit.status_code == 201
    assert inferred_crypto.status_code == 201
    assert unverified_bond_etf.status_code == 201
    assert invalid.status_code == 422
    assert explicit.json()["tax_category"] == "crypto"
    assert inferred_crypto.json()["tax_category"] == "crypto"
    assert unverified_bond_etf.json()["tax_category"] == "standard"
    assets = {item["symbol"]: item for item in client.get("/assets").json()}
    assert assets["CRYPTO_EXPLICIT"]["tax_category"] == "crypto"
    assert assets["CRYPTO_DEFAULT"]["tax_category"] == "crypto"
    assert assets["BOND_DEFAULT"]["tax_category"] == "standard"


def test_tax_csv_short_uses_realization_sides_and_native_base_values(client: TestClient) -> None:
    _init_flat(client)
    client.post(
        "/orders/simulate",
        json={
            "symbol": "AAPL",
            "order_type": "SELL",
            "quantity": 10,
            "price": 100,
            "fees": 0,
            "allow_short": True,
        },
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 80, "fees": 0},
    )

    response = client.get("/reports/tax.csv")

    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    event = next(row for row in rows if row["symbol"] == "AAPL")
    assert event["sell_date"] == ""
    assert event["realization_date"]
    assert event["open_side"] == "SELL"
    assert event["close_side"] == "BUY"
    assert float(event["open_value_native"]) == 1000.0
    assert float(event["close_value_native"]) == 800.0
    assert float(event["gain_native"]) == 200.0
    assert float(event["open_value_base"]) == 920.0
    assert float(event["close_value_base"]) == 736.0
    assert float(event["gain_base"]) == 184.0


def test_tax_report_empty(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 50, "max_asset_class_weight": 80, "default_fee_percent": 0, "confirm_reset": "RESET_PORTFOLIO"},
    )
    response = client.get("/tax/report")

    assert response.status_code == 200
    data = response.json()
    assert data["events"] == []
    assert data["total_tax_due"] == 0.0


def test_remove_asset_without_dependencies(client: TestClient) -> None:
    create = client.post(
        "/assets",
        json={"symbol": "TEST1", "name": "Test Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201

    assets = {a["symbol"] for a in client.get("/assets").json()}
    assert "TEST1" in assets

    delete = client.delete("/assets/TEST1")
    assert delete.status_code == 200
    assert delete.json() == {
        "deleted": True,
        "symbol": "TEST1",
        "purged": False,
        "dependency_counts": {
            "price_history": 0,
            "portfolio_positions": 0,
            "simulated_orders": 0,
            "signals": 0,
            "news_items": 0,
        },
    }

    assets_after = {a["symbol"] for a in client.get("/assets").json()}
    assert "TEST1" not in assets_after


def test_remove_asset_with_dependencies_returns_conflict_without_changes(client: TestClient) -> None:
    asset_id_before, counts_before, totals_before = _asset_dependency_state("AAPL")
    assert asset_id_before is not None
    assert all(count > 0 for count in counts_before.values())

    response = client.delete("/assets/AAPL")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert all(f"{table}={count}" in detail for table, count in counts_before.items())
    assert _asset_dependency_state("AAPL") == (asset_id_before, counts_before, totals_before)


@pytest.mark.parametrize("confirm_symbol", [None, "aapl", "MSFT"])
def test_purge_asset_requires_exact_confirmation(
    client: TestClient,
    confirm_symbol: str | None,
) -> None:
    state_before = _asset_dependency_state("AAPL")
    params = {"purge": "true"}
    if confirm_symbol is not None:
        params["confirm_symbol"] = confirm_symbol

    response = client.delete("/assets/AAPL", params=params)

    assert response.status_code == 400
    assert _asset_dependency_state("AAPL") == state_before


def test_purge_asset_with_confirmation_creates_backup_and_deletes_dependencies(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.api import routes

    asset_id_before, counts_before, totals_before = _asset_dependency_state("AAPL")
    assert asset_id_before is not None
    backup_reasons: list[str] = []
    real_create_backup = routes.create_backup

    def successful_backup(*, reason: str) -> dict[str, object]:
        backup_reasons.append(reason)
        return real_create_backup(reason=reason)

    monkeypatch.setattr(routes, "create_backup", successful_backup)

    response = client.delete(
        "/assets/AAPL",
        params={"purge": "true", "confirm_symbol": "AAPL"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "deleted": True,
        "symbol": "AAPL",
        "purged": True,
        "dependency_counts": counts_before,
    }
    assert backup_reasons == ["pre-asset-purge-AAPL"]
    asset_id_after, _, totals_after = _asset_dependency_state("AAPL")
    assert asset_id_after is None
    assert totals_after == {
        table: totals_before[table] - counts_before[table]
        for table in totals_before
    }


def test_purge_asset_without_created_backup_preserves_data(client: TestClient, monkeypatch) -> None:
    state_before = _asset_dependency_state("AAPL")
    monkeypatch.setattr(
        "backend.app.api.routes.create_backup",
        lambda *, reason: {"created": False, "reason": reason, "file": None},
    )

    response = client.delete(
        "/assets/AAPL",
        params={"purge": "true", "confirm_symbol": "AAPL"},
    )

    assert response.status_code == 503
    assert _asset_dependency_state("AAPL") == state_before


def test_purge_asset_when_backup_raises_preserves_data(client: TestClient, monkeypatch) -> None:
    state_before = _asset_dependency_state("AAPL")

    def failing_backup(*, reason: str) -> dict[str, object]:
        raise OSError(f"backup failed for {reason}")

    monkeypatch.setattr("backend.app.api.routes.create_backup", failing_backup)

    response = client.delete(
        "/assets/AAPL",
        params={"purge": "true", "confirm_symbol": "AAPL"},
    )

    assert response.status_code == 503
    assert _asset_dependency_state("AAPL") == state_before


def test_remove_asset_missing_returns_not_found(client: TestClient) -> None:
    response = client.delete("/assets/NOPE")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "params",
    [{}, {"purge": "true", "confirm_symbol": "DUP"}],
    ids=["remove", "purge"],
)
def test_remove_asset_rejects_ambiguous_symbol(
    client: TestClient,
    monkeypatch,
    params: dict[str, str],
) -> None:
    from backend.app.database import db_session

    for asset_type in ("stock", "etf"):
        response = client.post(
            "/assets",
            json={
                "symbol": "DUP",
                "name": f"Duplicate {asset_type}",
                "asset_type": asset_type,
                "currency": "USD",
            },
        )
        assert response.status_code == 201

    with db_session() as connection:
        duplicate_ids = [
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM assets WHERE symbol = 'DUP' ORDER BY id",
            ).fetchall()
        ]
        connection.execute(
            "INSERT INTO price_history (asset_id, date, close) VALUES (?, '2026-01-01', 10)",
            (duplicate_ids[1],),
        )

    backup_reasons: list[str] = []

    def backup_spy(*, reason: str) -> dict[str, object]:
        backup_reasons.append(reason)
        return {"created": True, "reason": reason, "file": "backup.db"}

    monkeypatch.setattr("backend.app.api.routes.create_backup", backup_spy)

    response = client.delete("/assets/DUP", params=params)

    assert response.status_code == 409
    assert backup_reasons == []
    with db_session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'DUP'").fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM price_history WHERE asset_id = ?",
            (duplicate_ids[1],),
        ).fetchone()[0] == 1


def test_remove_asset_counts_symbol_only_news_as_dependency(client: TestClient) -> None:
    from backend.app.database import db_session

    create = client.post(
        "/assets",
        json={"symbol": "NEWSY", "name": "Legacy News Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201
    with db_session() as connection:
        news_id = connection.execute(
            "INSERT INTO news_items (asset_id, symbol, title) VALUES (NULL, 'NEWSY', 'Legacy linked news')"
        ).lastrowid

    response = client.delete("/assets/NEWSY")

    assert response.status_code == 409
    assert "news_items=1" in response.json()["detail"]
    with db_session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'NEWSY'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM news_items WHERE id = ?", (news_id,)).fetchone()[0] == 1


def test_purge_asset_deletes_symbol_only_news(client: TestClient, monkeypatch) -> None:
    from backend.app.database import db_session

    create = client.post(
        "/assets",
        json={"symbol": "NEWSY", "name": "Legacy News Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201
    with db_session() as connection:
        news_id = connection.execute(
            "INSERT INTO news_items (asset_id, symbol, title) VALUES (NULL, 'NEWSY', 'Legacy linked news')"
        ).lastrowid

    monkeypatch.setattr(
        "backend.app.api.routes.create_backup",
        lambda *, reason: {"created": True, "reason": reason, "file": "backup.db"},
    )

    response = client.delete(
        "/assets/NEWSY",
        params={"purge": "true", "confirm_symbol": "NEWSY"},
    )

    assert response.status_code == 200
    assert response.json()["dependency_counts"]["news_items"] == 1
    with db_session() as connection:
        assert connection.execute("SELECT COUNT(*) FROM assets WHERE symbol = 'NEWSY'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM news_items WHERE id = ?", (news_id,)).fetchone()[0] == 0


def test_remove_asset_blocks_concurrent_dependencies_between_count_and_delete(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.api import routes
    from backend.app.config import get_settings

    create = client.post(
        "/assets",
        json={"symbol": "LOCKED", "name": "Lock Test Asset", "asset_type": "stock", "currency": "USD"},
    )
    assert create.status_code == 201
    original_dependency_counts = routes.asset_dependency_counts
    concurrent_write_errors: list[str] = []

    def counts_with_concurrent_write(connection, asset_id: int) -> dict[str, int]:
        counts = original_dependency_counts(connection, asset_id)
        contender = sqlite3.connect(str(get_settings().database_path), timeout=0)
        try:
            contender.execute(
                "INSERT INTO price_history (asset_id, date, close) VALUES (?, '2026-01-01', 10)",
                (asset_id,),
            )
            contender.commit()
        except sqlite3.OperationalError as exc:
            concurrent_write_errors.append(str(exc))
        finally:
            contender.close()
        return counts

    monkeypatch.setattr(routes, "asset_dependency_counts", counts_with_concurrent_write)

    response = client.delete("/assets/LOCKED")

    assert response.status_code == 200
    assert len(concurrent_write_errors) == 1
    assert "locked" in concurrent_write_errors[0].lower()


def test_backup_create_and_list(client: TestClient) -> None:
    created = client.post("/backups/create")
    assert created.status_code == 200
    data = created.json()
    assert data["created"] is True
    assert data["file"] and data["file"].endswith(".db")

    listing = client.get("/backups")
    assert listing.status_code == 200
    files = [item["file"] for item in listing.json()]
    assert data["file"] in files


def test_reports_summary(client: TestClient) -> None:
    response = client.get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert {"positions_count", "orders_count", "realized_events_count", "portfolio_value", "estimated_tax_due"} <= set(data)


def test_reports_csv_downloads(client: TestClient) -> None:
    for path, header in [
        ("/reports/portfolio.csv", "symbol,asset_type,quantity"),
        ("/reports/orders.csv", "date,symbol,type"),
        ("/reports/tax.csv", "sell_date,symbol,asset_type"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
        assert response.text.splitlines()[0].startswith(header)

    portfolio_headers = client.get("/reports/portfolio.csv").text.splitlines()[0].split(",")
    orders_headers = client.get("/reports/orders.csv").text.splitlines()[0].split(",")
    assert {"currency", "fx_rate_to_base", "current_value", "current_value_base", "base_currency"} <= set(
        portfolio_headers
    )
    assert {"currency", "fx_rate_to_base", "gross_amount", "gross_amount_base", "base_currency"} <= set(
        orders_headers
    )


def test_dashboard_after_seed(client: TestClient) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["initialized"] is True
    assert data["assets_count"] == 25
    assert data["signals_count"] == 25
    assert data["price_points_count"] >= 14000
    assert data["latest_signals"]
    assert data["data_status"]["data_mode"] == "SEED"


def test_dashboard_counts_short_only_positions(client: TestClient) -> None:
    _init_flat(client)
    opened = client.post(
        "/orders/simulate",
        json={
            "symbol": "AAPL",
            "order_type": "SELL",
            "quantity": 2,
            "price": 100,
            "fees": 0,
            "allow_short": True,
        },
    )
    assert opened.status_code == 200
    assert len(client.get("/portfolio").json()["positions"]) == 1

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.json()["positions_count"] == 1


def _price_frame(values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": values,
            "high": [value * 1.01 for value in values],
            "low": [value * 0.99 for value in values],
            "close": values,
            "adjusted_close": values,
            "volume": [1_000_000 + index * 1000 for index, _ in enumerate(values)],
        }
    )


def test_technical_analysis_increasing_series() -> None:
    service = TechnicalAnalysisService()
    analysis = service.calculate_full_technical_analysis(_price_frame([100 + index for index in range(260)]))

    assert analysis["latest_close"] == 359
    assert analysis["conditions"]["price_above_sma50"] is True
    assert analysis["conditions"]["price_above_sma200"] is True
    assert analysis["indicators"]["sma_200"] > 0


def test_technical_analysis_decreasing_series() -> None:
    service = TechnicalAnalysisService()
    analysis = service.calculate_full_technical_analysis(_price_frame([360 - index for index in range(260)]))

    assert analysis["conditions"]["price_above_sma50"] is False
    assert analysis["conditions"]["price_above_sma200"] is False
    assert analysis["overall_technical_bias"] in {"BEARISH", "NEUTRAL"}


def test_technical_analysis_short_series() -> None:
    service = TechnicalAnalysisService()
    analysis = service.calculate_full_technical_analysis(_price_frame([10, 11, 12]))

    assert analysis["latest_close"] == 12
    assert analysis["support_resistance"]["nearest_support"] is None
    assert "sma_200" not in analysis["indicators"]


def test_technical_analysis_endpoint(client: TestClient) -> None:
    response = client.get("/technical-analysis/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["asset"]["symbol"] == "AAPL"
    assert data["subscores"]
    assert data["reasons"]
    assert data["confidence"] in {"LOW", "MEDIUM", "HIGH"}


def test_advanced_seed_signal_payload(client: TestClient) -> None:
    response = client.get("/signals/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["signal"] in {"STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL"}
    assert "trend_score" in data["subscores"]
    assert isinstance(data["reasons"], list)


def test_signals_and_assets_expose_score_data_mode(client: TestClient) -> None:
    signals = client.get("/signals").json()
    assets = client.get("/assets").json()

    assert len(signals) == 25
    assert {signal["data_mode"] for signal in signals} == {"DEMO"}
    assert all(signal["final_score"] == signal["technical_score"] == signal["score"] for signal in signals)
    assert client.get("/signals/AAPL").json()["data_mode"] == "DEMO"
    assert {asset["signal_data_mode"] for asset in assets} == {"DEMO"}
    assert all(asset["score_unavailable_reason"] is None for asset in assets)


def test_technical_analysis_serves_the_signal_score_v1(client: TestClient) -> None:
    analysis = client.get("/technical-analysis/AAPL").json()
    signal = client.get("/signals/AAPL").json()

    assert analysis["data_mode"] == "DEMO"
    assert analysis["score"] == analysis["technical_score"] == analysis["final_score"] == signal["score"]
    assert analysis["signal"] == signal["signal"]
    assert {"volatility_30d", "max_drawdown_252"} <= set(analysis["indicators"])
    assert "volatility_annualized_30d" not in analysis["indicators"]


def test_technical_analysis_short_real_history_returns_409(client: TestClient) -> None:
    from backend.app.database import db_session
    from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

    with db_session() as connection:
        asset_id = insert_asset(connection, "SHORTREAL")
        insert_bars(connection, asset_id, synthetic_bars(100, seed=3), real=True, provider="stooq")
    reason = "Storico reale insufficiente (100 barre, servono 252)."

    response = client.get("/technical-analysis/SHORTREAL")
    asset = client.get("/assets/SHORTREAL").json()

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "INSUFFICIENT_REAL_HISTORY", "message": reason}
    assert asset["score"] is None
    assert asset["signal_data_mode"] is None
    assert asset["score_unavailable_reason"] == reason
    listed = next(item for item in client.get("/assets").json() if item["symbol"] == "SHORTREAL")
    assert listed["score_unavailable_reason"] == reason


def test_action_board_items_expose_signal_data_mode(client: TestClient) -> None:
    actions = client.get("/action-board").json()["actions"]

    signal_actions = [action for action in actions if action["type"] in {"BUY", "REDUCE", "SELL"}]
    assert signal_actions
    assert {action["data_mode"] for action in signal_actions} == {"DEMO"}
    assert all(action["data_mode"] is None for action in actions if action["type"] in {"RISK", "OK"})


def test_portfolio_endpoint_after_seed(client: TestClient) -> None:
    response = client.get("/portfolio")

    assert response.status_code == 200
    data = response.json()
    assert data["total_value"] > 0
    assert data["cash"] > 0
    assert data["base_currency"] == "EUR"
    assert len(data["positions"]) == 7
    assert all(position["base_currency"] == "EUR" for position in data["positions"])
    assert all("current_value_base" in position for position in data["positions"])
    assert data["allocation_by_asset_type"]
    assert isinstance(data["risk_warnings"], list)


def test_init_portfolio(client: TestClient) -> None:
    response = client.post(
        "/portfolio/init",
        json={
            "initial_cash": 25000,
            "max_single_asset_weight": 20,
                "max_asset_class_weight": 50,
                "default_fee_percent": 0.2,
                "confirm_reset": "RESET_PORTFOLIO",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["cash"] == 25000
    assert data["total_value"] == 25000
    assert data["positions"] == []
    assert data["settings"]["default_fee_percent"] == 0.2


def test_portfolio_init_requires_backend_confirmation(client: TestClient) -> None:
    before = client.get("/portfolio").json()

    response = client.post("/portfolio/init", json={"initial_cash": 25000})

    assert response.status_code == 400
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]


def test_buy_with_sufficient_cash(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
            "confirm_reset": "RESET_PORTFOLIO",
        },
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 2, "price": 100, "fees": 0},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["order"]["gross_amount"] == 200
    assert data["order"]["currency"] == "USD"
    assert data["order"]["fx_rate_to_base"] == 0.92
    assert data["order"]["gross_amount_base"] == 184
    assert data["order"]["base_currency"] == "EUR"
    assert data["updated_position"]["quantity"] == 2
    assert data["updated_portfolio_summary"]["cash"] == 9816


def test_buy_with_insufficient_cash(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 100,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
            "confirm_reset": "RESET_PORTFOLIO",
        },
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 2, "price": 100, "fees": 0},
    )

    assert response.status_code == 400
    assert "Cash insufficiente" in response.json()["detail"]


def test_sell_with_sufficient_quantity_and_pnl(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
            "confirm_reset": "RESET_PORTFOLIO",
        },
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 2, "price": 100, "fees": 0},
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "SELL", "quantity": 1, "price": 120, "fees": 0},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["order"]["order_type"] == "SELL"
    assert data["updated_position"]["quantity"] == 1
    assert data["updated_portfolio_summary"]["realized_pnl"] == 18.4


def test_sell_with_insufficient_quantity(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 50,
            "max_asset_class_weight": 80,
            "default_fee_percent": 0,
            "confirm_reset": "RESET_PORTFOLIO",
        },
    )

    response = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "SELL", "quantity": 1, "price": 120, "fees": 0},
    )

    assert response.status_code == 400
    assert "Quantita insufficiente" in response.json()["detail"]


def test_average_price_calculation(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={
            "initial_cash": 10000,
            "max_single_asset_weight": 80,
            "max_asset_class_weight": 90,
            "default_fee_percent": 0,
            "confirm_reset": "RESET_PORTFOLIO",
        },
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 1, "price": 100, "fees": 0},
    )
    client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "BUY", "quantity": 1, "price": 200, "fees": 0},
    )

    response = client.get("/portfolio")
    position = next(item for item in response.json()["positions"] if item["symbol"] == "AAPL")

    assert position["quantity"] == 2
    assert position["average_price"] == 150


def test_assets_include_isin(client: TestClient) -> None:
    assets = {a["symbol"]: a for a in client.get("/assets").json()}
    assert assets["AAPL"]["isin"] == "US0378331005"
    assert assets["VWCE"]["isin"] == "IE00BK5BQT80"
    assert assets["IB01"]["isin"] == "IE00BGSF1X88"
    # crypto / indici generici non hanno ISIN
    assert assets["BTC"]["isin"] is None


def test_positions_include_name_and_isin(client: TestClient) -> None:
    portfolio = client.get("/portfolio").json()
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["name"] == "Apple Inc."
    assert aapl["isin"] == "US0378331005"


def test_sell_all_removes_position_and_keeps_realized_pnl(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 80, "max_asset_class_weight": 90, "default_fee_percent": 0, "confirm_reset": "RESET_PORTFOLIO"},
    )
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 3, "price": 100, "fees": 0})
    # vendita totale
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 3, "price": 110, "fees": 0})

    portfolio = client.get("/portfolio").json()
    symbols = {p["symbol"] for p in portfolio["positions"]}
    assert "AAPL" not in symbols  # il titolo venduto del tutto non appare piu
    assert portfolio["realized_pnl"] == 27.6  # 3 * (110 - 100) USD * 0,92, conservato in EUR


def test_sell_all_with_rounded_quantity_closes_position(client: TestClient) -> None:
    # quantita' frazionaria: "Vendi tutto" usa il valore arrotondato e deve comunque chiudere
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 90, "max_asset_class_weight": 90, "default_fee_percent": 0, "confirm_reset": "RESET_PORTFOLIO"},
    )
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 1.123456789, "price": 100, "fees": 0})
    # vende la quantita' arrotondata a 8 decimali (come fa il bottone "Vendi tutto")
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 1.12345679, "price": 110, "fees": 0})

    portfolio = client.get("/portfolio").json()
    symbols = {p["symbol"] for p in portfolio["positions"]}
    assert "AAPL" not in symbols


def _init_flat(client: TestClient, cash: float = 10000) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": cash, "max_single_asset_weight": 100, "max_asset_class_weight": 100, "default_fee_percent": 0, "confirm_reset": "RESET_PORTFOLIO"},
    )


def test_short_requires_allow_short_flag(client: TestClient) -> None:
    _init_flat(client)
    # vendere allo scoperto senza il flag e' bloccato (niente short accidentale)
    blocked = client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 100, "fees": 0})
    assert blocked.status_code == 400
    # con allow_short apre uno short (quantita' negativa) e incassa i proventi
    opened = client.post(
        "/orders/simulate",
        json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 100, "fees": 0, "allow_short": True},
    )
    assert opened.status_code == 200
    portfolio = client.get("/portfolio").json()
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["quantity"] == -5  # short
    assert portfolio["cash"] == 10460  # 10000 EUR + 5*100 USD*0,92 di proventi


def test_short_profit_when_price_falls(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 10, "price": 100, "fees": 0, "allow_short": True})
    # ricopre piu' in basso -> profitto (100 - 90) * 10 = 100
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 90, "fees": 0})
    summary = client.get("/portfolio").json()
    assert summary["realized_pnl"] == 92.0
    assert "AAPL" not in {p["symbol"] for p in summary["positions"]}  # chiuso
    assert summary["cash"] == 10092  # 10000 EUR + 100 USD*0,92 di utile


def test_short_loss_when_price_rises(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 5, "price": 100, "fees": 0, "allow_short": True})
    # il prezzo sale: ricoprire costa di piu' -> perdita (100 - 130) * 5 = -150
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 5, "price": 130, "fees": 0})
    summary = client.get("/portfolio").json()
    assert summary["realized_pnl"] == -138.0


def test_short_position_triggers_risk_warning(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 3, "price": 100, "fees": 0, "allow_short": True})
    warnings = client.get("/portfolio").json()["risk_warnings"]
    assert any(w["code"] == "SHORT_RISK" and w["symbol"] == "AAPL" for w in warnings)


def test_flip_long_to_short_realizes_pnl(client: TestClient) -> None:
    _init_flat(client)
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "BUY", "quantity": 10, "price": 100, "fees": 0})
    # vende 15 (ne ha 10): chiude il long (+200) e apre uno short di 5 a 120
    client.post("/orders/simulate", json={"symbol": "AAPL", "order_type": "SELL", "quantity": 15, "price": 120, "fees": 0, "allow_short": True})
    portfolio = client.get("/portfolio").json()
    aapl = next(p for p in portfolio["positions"] if p["symbol"] == "AAPL")
    assert aapl["quantity"] == -5  # ora short
    assert portfolio["realized_pnl"] == 184.0  # 10 * (120 - 100) USD * 0,92


def test_portfolio_recommendations_endpoint(client: TestClient) -> None:
    response = client.get("/portfolio/recommendations")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 25
    assert {"symbol", "technical_signal", "technical_score", "portfolio_weight", "final_recommendation", "reason"} <= set(data[0])


def _backtest_payload(strategy_name: str = "SCORE_THRESHOLD") -> dict[str, object]:
    payload: dict[str, object] = {
        "name": f"Test {strategy_name}",
        "strategy_name": strategy_name,
        "symbols": ["AAPL", "MSFT", "SPY", "QQQ"],
        "initial_cash": 100000,
        "start_date": "2025-01-01",
        "end_date": "2026-05-15",
        "benchmark_symbol": "SPY",
        "buy_threshold": 55,
        "sell_threshold": 40,
        "max_asset_weight": 0.2,
        "fee_percent": 0.1,
        "stop_loss_percent": 8,
        "take_profit_percent": 25,
        "rebalance_frequency": "WEEKLY",
    }
    if strategy_name == "TOP_N_SCORE":
        payload["top_n"] = 2
    return payload


def test_run_backtest_score_threshold(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("SCORE_THRESHOLD"))

    assert response.status_code == 200
    data = response.json()
    summary = data["summary"]
    assert data["backtest_id"] > 0
    assert summary["strategy_name"] == "SCORE_THRESHOLD"
    assert {"total_return_percent", "cagr", "max_drawdown", "sharpe_ratio", "win_rate", "profit_factor", "final_value"} <= set(summary)
    assert len(data["equity_curve"]) > 50
    assert all(trade["quantity"] > 0 and trade["price"] > 0 for trade in data["trades"])
    assert "alpha_vs_benchmark" in data["benchmark_comparison"]


def test_backtest_net_analysis(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("SCORE_THRESHOLD"))

    assert response.status_code == 200
    net = response.json()["net_analysis"]
    assert net is not None
    # struttura completa
    assert {
        "gross_return_percent",
        "net_return_percent",
        "capital_gains_tax",
        "slippage_costs",
        "stamp_duty",
        "net_final_value",
        "total_costs_and_taxes",
    } <= set(net)
    # i costi non sono negativi e il netto non supera il lordo
    assert net["capital_gains_tax"] >= 0
    assert net["slippage_costs"] >= 0
    assert net["stamp_duty"] >= 0
    assert net["net_return_percent"] <= net["gross_return_percent"] + 1e-6
    # con plusvalenze tassabili l'aliquota effettiva resta entro il 26%
    if net["realized_gains_taxable"] > 0:
        assert 0 < net["effective_tax_rate_percent"] <= 26.0 + 1e-6


def test_run_backtest_buy_and_hold(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("BUY_AND_HOLD"))

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["strategy_name"] == "BUY_AND_HOLD"
    assert data["summary"]["total_trades"] >= 1
    assert data["final_positions"]


def test_run_backtest_top_n_score(client: TestClient) -> None:
    response = client.post("/backtests/run", json=_backtest_payload("TOP_N_SCORE"))

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["strategy_name"] == "TOP_N_SCORE"
    assert len(data["equity_curve"]) > 50
    assert data["summary"]["total_trades"] >= 1


def _compare_payload() -> dict[str, object]:
    return {
        "name": "Confronto test",
        "strategy_names": ["SCORE_THRESHOLD", "BUY_AND_HOLD", "TOP_N_SCORE"],
        "symbols": ["AAPL", "MSFT", "SPY", "QQQ"],
        "initial_cash": 100000,
        "start_date": "2025-01-01",
        "end_date": "2026-05-15",
        "benchmark_symbol": "SPY",
        "buy_threshold": 55,
        "sell_threshold": 40,
        "max_asset_weight": 0.2,
        "fee_percent": 0.1,
        "stop_loss_percent": 8,
        "take_profit_percent": 25,
        "rebalance_frequency": "WEEKLY",
        "top_n": 2,
    }


def test_compare_strategies_endpoint(client: TestClient) -> None:
    response = client.post("/backtests/compare", json=_compare_payload())

    assert response.status_code == 200
    data = response.json()
    assert len(data["entries"]) == 3
    assert {entry["strategy_name"] for entry in data["entries"]} == {
        "SCORE_THRESHOLD",
        "BUY_AND_HOLD",
        "TOP_N_SCORE",
    }
    ranks = sorted(entry["rank"] for entry in data["entries"])
    assert ranks == [1, 2, 3]
    best = next(entry for entry in data["entries"] if entry["rank"] == 1)
    assert best["strategy_name"] == data["best_strategy"]
    assert all(len(entry["equity_curve"]) > 50 for entry in data["entries"])
    # i run di confronto non vengono persistiti nello storico
    history = client.get("/backtests").json()
    assert all("Confronto test" not in item["name"] for item in history)


def test_compare_strategies_requires_two(client: TestClient) -> None:
    payload = _compare_payload()
    payload["strategy_names"] = ["SCORE_THRESHOLD"]

    response = client.post("/backtests/compare", json=payload)

    assert response.status_code == 422


def test_walk_forward_endpoint(client: TestClient) -> None:
    payload = _backtest_payload("SCORE_THRESHOLD")
    payload["folds"] = 4

    response = client.post("/backtests/walk-forward", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["folds"] == 4
    assert len(data["fold_results"]) == 4
    assert data["consistency"] in {"ROBUSTA", "INCERTA", "FRAGILE"}
    assert data["positive_folds"] <= data["folds"]
    assert data["verdict"]
    folds_seen = [fold["fold"] for fold in data["fold_results"]]
    assert folds_seen == [1, 2, 3, 4]


def test_walk_forward_period_too_short(client: TestClient) -> None:
    payload = _backtest_payload("BUY_AND_HOLD")
    payload["start_date"] = "2026-05-10"
    payload["end_date"] = "2026-05-15"
    payload["folds"] = 12

    response = client.post("/backtests/walk-forward", json=payload)

    assert response.status_code == 400
    assert "fold" in response.json()["detail"].lower()


def _allocation_payload(method: str = "RISK_PARITY", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbols": ["AAPL", "MSFT", "SPY", "QQQ"],
        "method": method,
        "total_capital": 100000,
        "target_volatility": 0.15,
        "lookback_days": 120,
    }
    payload.update(overrides)
    return payload


def _plan_and_apply_allocation(client: TestClient, payload: dict[str, object]) -> httpx.Response:
    plan_response = client.post("/portfolio/allocation/plan", json=payload)
    assert plan_response.status_code == 200
    return client.post(
        "/portfolio/allocation/apply",
        json={**payload, "confirmation_token": plan_response.json()["confirmation_token"]},
    )


def test_allocation_equal_weight(client: TestClient) -> None:
    response = client.post("/portfolio/allocation/plan", json=_allocation_payload("EQUAL_WEIGHT"))

    assert response.status_code == 200
    data = response.json()
    assert len(data["allocations"]) == 4
    for item in data["allocations"]:
        assert abs(item["weight_percent"] - 25.0) < 0.5
        assert item["suggested_quantity"] >= 0
    assert abs(data["invested_capital"] + data["cash_buffer"] - data["total_capital"]) < 0.01


def test_allocation_risk_parity_weights_sum(client: TestClient) -> None:
    response = client.post("/portfolio/allocation/plan", json=_allocation_payload("RISK_PARITY"))

    assert response.status_code == 200
    data = response.json()
    total_weight = sum(item["weight_percent"] for item in data["allocations"])
    assert abs(total_weight - 100.0) < 1.0
    # risk parity: l'asset meno volatile pesa piu del piu volatile
    by_vol = sorted(data["allocations"], key=lambda item: item["volatility"])
    assert by_vol[0]["weight_percent"] >= by_vol[-1]["weight_percent"]


def test_allocation_vol_target_keeps_cash(client: TestClient) -> None:
    response = client.post(
        "/portfolio/allocation/plan",
        json=_allocation_payload("VOL_TARGET", target_volatility=0.05),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["invested_capital"] <= data["total_capital"]
    assert data["cash_buffer"] >= 0
    # target molto basso => parte del capitale resta liquida
    assert data["cash_buffer"] > 0


def test_allocation_max_weight_cap(client: TestClient) -> None:
    response = client.post(
        "/portfolio/allocation/plan",
        json=_allocation_payload("RISK_PARITY", max_weight=0.3),
    )

    assert response.status_code == 200
    data = response.json()
    for item in data["allocations"]:
        assert item["weight_percent"] <= 30.5


def test_allocation_apply_creates_portfolio(client: TestClient) -> None:
    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT", "SPY"])
    plan_response = client.post("/portfolio/allocation/plan", json=payload)
    assert plan_response.status_code == 200
    plan = plan_response.json()

    response = _plan_and_apply_allocation(
        client,
        payload,
    )

    assert response.status_code == 200
    data = response.json()
    symbols = {position["symbol"] for position in data["positions"]}
    assert symbols == {"AAPL", "MSFT", "SPY"}
    assert all(position["quantity"] > 0 for position in data["positions"])
    assert data["invested_value"] > 0
    assert data["settings"]["initial_cash"] == payload["total_capital"]
    assert data["settings"]["current_cash"] == plan["cash_buffer"]


def test_allocation_apply_reconciles_integer_residual_in_eur(client: TestClient) -> None:
    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["VWCE"], total_capital=10000)
    plan_response = client.post("/portfolio/allocation/plan", json=payload)
    assert plan_response.status_code == 200
    plan = plan_response.json()
    allocation = plan["allocations"][0]
    expected_cost = allocation["suggested_quantity"] * allocation["price"]
    expected_cash = payload["total_capital"] - expected_cost

    response = client.post(
        "/portfolio/allocation/apply",
        json={**payload, "confirmation_token": plan["confirmation_token"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["cash"] == pytest.approx(expected_cash, abs=0.01)
    assert data["total_value"] == pytest.approx(payload["total_capital"], abs=0.01)
    assert allocation["actual_cost_base"] == pytest.approx(expected_cost, abs=0.01)


def test_allocation_apply_uses_base_price_for_usd_asset(client: TestClient) -> None:
    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"], total_capital=10000)
    plan_response = client.post("/portfolio/allocation/plan", json=payload)
    assert plan_response.status_code == 200
    plan = plan_response.json()
    allocation = plan["allocations"][0]
    expected_price_base = allocation["price"] * 0.92
    expected_quantity = int(payload["total_capital"] // expected_price_base)
    expected_cost = expected_quantity * expected_price_base

    response = client.post(
        "/portfolio/allocation/apply",
        json={**payload, "confirmation_token": plan["confirmation_token"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert allocation["price_base"] == pytest.approx(expected_price_base, abs=0.0001)
    assert allocation["suggested_quantity"] == expected_quantity
    assert data["positions"][0]["average_price"] == pytest.approx(allocation["price"], abs=0.0001)
    assert data["cash"] == pytest.approx(payload["total_capital"] - expected_cost, abs=0.01)
    assert data["total_value"] == pytest.approx(payload["total_capital"], abs=0.01)


def test_rebalance_uses_base_values_for_usd_position(client: TestClient) -> None:
    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"], total_capital=10000)
    applied = _plan_and_apply_allocation(client, payload)
    assert applied.status_code == 200
    position = applied.json()["positions"][0]

    response = client.post("/portfolio/allocation/rebalance", json=payload)

    assert response.status_code == 200
    trade = response.json()["trades"][0]
    expected_price_base = position["current_price"] * position["fx_rate_to_base"]
    assert trade["action"] != "SELL"
    assert trade["current_value"] == pytest.approx(position["current_value_base"], abs=0.01)
    assert trade["price"] == pytest.approx(expected_price_base, abs=0.0001)
    assert trade["delta_quantity"] == pytest.approx(trade["delta_value"] / expected_price_base, abs=0.0001)


def test_assets_expose_eur_reference_prices(client: TestClient) -> None:
    assets = {asset["symbol"]: asset for asset in client.get("/assets").json()}

    assert assets["AAPL"]["fx_rate_to_base"] == pytest.approx(0.92)
    assert assets["AAPL"]["last_price_base"] == pytest.approx(assets["AAPL"]["last_price"] * 0.92)
    assert assets["VWCE"]["fx_rate_to_base"] == pytest.approx(1.0)
    assert assets["VWCE"]["last_price_base"] == pytest.approx(assets["VWCE"]["last_price"])


def test_allocation_apply_rejects_stale_plan(client: TestClient) -> None:
    from backend.app.database import db_session

    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"], total_capital=10000)
    plan_response = client.post("/portfolio/allocation/plan", json=payload)
    assert plan_response.status_code == 200
    confirmation_token = plan_response.json().get("confirmation_token")
    with db_session() as connection:
        connection.execute(
            """
            UPDATE price_history
            SET close = close * 2
            WHERE id = (
                SELECT ph.id
                FROM price_history ph
                JOIN assets a ON a.id = ph.asset_id
                WHERE a.symbol = 'AAPL'
                ORDER BY ph.date DESC, ph.is_real_data DESC, ph.id DESC
                LIMIT 1
                )
                """
            )
    before = client.get("/portfolio").json()["positions"]

    response = client.post(
        "/portfolio/allocation/apply",
        json={**payload, "confirmation_token": confirmation_token},
    )

    assert response.status_code == 409
    assert client.get("/portfolio").json()["positions"] == before


def test_allocation_token_changes_with_local_resolution_and_rejects_old_plan(
    client: TestClient,
) -> None:
    from backend.app.database import db_session

    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"], total_capital=10000)
    unmapped_plan = client.post("/portfolio/allocation/plan", json=payload)
    assert unmapped_plan.status_code == 200

    with db_session() as connection:
        subject = _resolution_subject(connection, "AAPL")
        _append_resolution_case(
            connection,
            symbol="AAPL",
            instrument_id=int(subject["instrument_id"]),
            listing_id=int(subject["listing_id"]),
        )

    resolved_plan = client.post("/portfolio/allocation/plan", json=payload)
    assert resolved_plan.status_code == 200
    assert len(resolved_plan.json()["confirmation_token"]) == 64
    assert (
        resolved_plan.json()["confirmation_token"]
        != unmapped_plan.json()["confirmation_token"]
    )
    before = client.get("/portfolio").json()

    response = client.post(
        "/portfolio/allocation/apply",
        json={**payload, "confirmation_token": unmapped_plan.json()["confirmation_token"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "RESOLUTION_CHANGED"}
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]


def test_allocation_token_rejects_resolution_snapshot_change_without_transport(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    transport_calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal transport_calls
        transport_calls += 1
        raise AssertionError("Allocation apply must not call OpenFIGI")

    monkeypatch.setattr(
        "backend.app.data_providers.openfigi.OpenFigiProvider.map_isins",
        fail_if_called,
    )
    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"], total_capital=10000)
    with db_session() as connection:
        subject = _resolution_subject(connection, "AAPL")
        original = _append_resolution_case(
            connection,
            symbol="AAPL",
            instrument_id=int(subject["instrument_id"]),
            listing_id=int(subject["listing_id"]),
        )
    plan = client.post("/portfolio/allocation/plan", json=payload)
    assert plan.status_code == 200
    before = client.get("/portfolio").json()

    with db_session() as connection:
        _append_resolution_case(
            connection,
            symbol="AAPL",
            instrument_id=int(subject["instrument_id"]),
            listing_id=int(subject["listing_id"]),
            evidence_hash="b" * 64,
            catalog_entry_id=int(original["catalog_entry_id"]),
        )

    response = client.post(
        "/portfolio/allocation/apply",
        json={**payload, "confirmation_token": plan.json()["confirmation_token"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "RESOLUTION_CHANGED"}
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]
    assert transport_calls == 0


def test_allocation_apply_maps_new_local_ambiguity_to_resolution_changed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    transport_calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal transport_calls
        transport_calls += 1
        raise AssertionError("Allocation apply must not call OpenFIGI")

    monkeypatch.setattr(
        "backend.app.data_providers.openfigi.OpenFigiProvider.map_isins",
        fail_if_called,
    )
    payload = _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"], total_capital=10000)
    with db_session() as connection:
        subject = _resolution_subject(connection, "AAPL")
        _append_resolution_case(
            connection,
            symbol="AAPL",
            instrument_id=int(subject["instrument_id"]),
            listing_id=int(subject["listing_id"]),
        )
    plan = client.post("/portfolio/allocation/plan", json=payload)
    assert plan.status_code == 200
    before = client.get("/portfolio").json()

    with db_session() as connection:
        second_listing_id = _create_resolution_listing(
            connection,
            instrument_id=int(subject["instrument_id"]),
            symbol="AAPL",
            currency="USD",
            mic="XNAS",
        )
        _append_resolution_case(
            connection,
            symbol="AAPL",
            instrument_id=int(subject["instrument_id"]),
            listing_id=second_listing_id,
        )

    response = client.post(
        "/portfolio/allocation/apply",
        json={**payload, "confirmation_token": plan.json()["confirmation_token"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"reason_code": "RESOLUTION_CHANGED"}
    after = client.get("/portfolio").json()
    assert after["positions"] == before["positions"]
    assert after["settings"] == before["settings"]
    assert transport_calls == 0


def test_scenario_market_crash(client: TestClient) -> None:
    # crea un portafoglio dal pianificatore così lo scenario ha posizioni
    _plan_and_apply_allocation(
        client,
        _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "BTC", "SPY"]),
    )

    response = client.post("/scenarios/run", json={"scenario_type": "MARKET_CRASH"})

    assert response.status_code == 200
    data = response.json()
    assert data["scenario_type"] == "MARKET_CRASH"
    assert data["base_currency"] == "EUR"
    assert data["stressed_value"] < data["current_value"]
    assert data["absolute_loss"] < 0
    assert data["risk_level"] in {"LOW", "MEDIUM", "HIGH", "EXTREME"}
    assert len(data["asset_impacts"]) == 3
    assert data["mitigation"]


def test_scenario_custom_shocks(client: TestClient) -> None:
    _plan_and_apply_allocation(
        client,
        _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT"]),
    )

    response = client.post(
        "/scenarios/run",
        json={"scenario_type": "CUSTOM", "class_shocks": {"stock": -10}},
    )

    assert response.status_code == 200
    data = response.json()
    assert all(abs(impact["shock_percent"] + 10) < 0.001 for impact in data["asset_impacts"])


def test_scenario_preserves_signed_short_liability_and_labels_gain_neutrally(client: TestClient) -> None:
    _init_flat(client)

    from backend.app.database import db_session

    with db_session() as connection:
        cursor = connection.execute(
            "INSERT INTO assets (symbol, name, asset_type, currency, risk_level) "
            "VALUES ('SHORT_EUR', 'Short EUR', 'stock', 'EUR', 'medium')"
        )
        connection.execute(
            "INSERT INTO price_history (asset_id, date, close, source, is_real_data) "
            "VALUES (?, '2099-01-01', 100, 'test', 1)",
            (cursor.lastrowid,),
        )

    opened = client.post(
        "/orders/simulate",
        json={
            "symbol": "SHORT_EUR",
            "order_type": "SELL",
            "quantity": 10,
            "price": 100,
            "fees": 0,
            "allow_short": True,
        },
    )
    assert opened.status_code == 200

    adverse = client.post(
        "/scenarios/run",
        json={"scenario_type": "CUSTOM", "symbol_shocks": {"SHORT_EUR": 20}},
    )

    assert adverse.status_code == 200
    adverse_data = adverse.json()
    asset = adverse_data["asset_impacts"][0]
    asset_class = adverse_data["class_impacts"][0]
    assert asset["current_value"] == -1000.0
    assert asset["stressed_value"] == -1200.0
    assert asset["absolute_impact"] == -200.0
    assert asset["outcome"] == "LOSS"
    assert asset_class["shock_percent"] == -20.0
    assert adverse_data["absolute_impact"] == -200.0
    assert adverse_data["absolute_loss"] == -200.0
    assert adverse_data["outcome"] == "LOSS"
    assert adverse_data["impact_label"] == "Perdita stimata"

    favorable = client.post(
        "/scenarios/run",
        json={"scenario_type": "CUSTOM", "symbol_shocks": {"SHORT_EUR": -20}},
    )

    assert favorable.status_code == 200
    favorable_data = favorable.json()
    asset = favorable_data["asset_impacts"][0]
    assert asset["stressed_value"] == -800.0
    assert asset["absolute_impact"] == 200.0
    assert asset["outcome"] == "GAIN"
    assert favorable_data["absolute_impact"] == 200.0
    assert favorable_data["absolute_loss"] == 0.0
    assert favorable_data["percentage_loss"] == 0.0
    assert favorable_data["outcome"] == "GAIN"
    assert favorable_data["impact_label"] == "Guadagno stimato"
    assert all("perdita" not in tip.lower() for tip in favorable_data["mitigation"])


def test_scenario_empty_portfolio_fails(client: TestClient) -> None:
    client.post(
        "/portfolio/init",
        json={"initial_cash": 10000, "max_single_asset_weight": 50, "max_asset_class_weight": 80, "default_fee_percent": 0, "confirm_reset": "RESET_PORTFOLIO"},
    )

    response = client.post("/scenarios/run", json={"scenario_type": "MARKET_CRASH"})

    assert response.status_code == 400
    assert "vuoto" in response.json()["detail"].lower()


def test_rebalance_produces_trades(client: TestClient) -> None:
    # portafoglio iniziale concentrato su AAPL
    _plan_and_apply_allocation(
        client,
        _allocation_payload("EQUAL_WEIGHT", symbols=["AAPL"]),
    )

    response = client.post(
        "/portfolio/allocation/rebalance",
        json=_allocation_payload("EQUAL_WEIGHT", symbols=["AAPL", "MSFT", "SPY"]),
    )

    assert response.status_code == 200
    data = response.json()
    actions = {trade["symbol"]: trade["action"] for trade in data["trades"]}
    # MSFT e SPY non sono in portafoglio -> da comprare
    assert actions.get("MSFT") == "BUY"
    assert actions.get("SPY") == "BUY"
    # AAPL era 100% -> va ridotto
    assert actions.get("AAPL") == "SELL"


def test_allocation_invalid_symbol(client: TestClient) -> None:
    response = client.post(
        "/portfolio/allocation/plan",
        json=_allocation_payload("EQUAL_WEIGHT", symbols=["NOPE"]),
    )

    assert response.status_code == 400
    assert "NOPE" in response.json()["detail"]


def test_backtest_history_and_detail_endpoints(client: TestClient) -> None:
    run_response = client.post("/backtests/run", json=_backtest_payload("SCORE_THRESHOLD"))
    backtest_id = run_response.json()["backtest_id"]

    list_response = client.get("/backtests")
    detail_response = client.get(f"/backtests/{backtest_id}")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert any(item["id"] == backtest_id for item in list_response.json())
    assert detail_response.json()["backtest_id"] == backtest_id
    assert detail_response.json()["trades"] is not None


def test_delete_backtest_requires_backend_confirmation(client: TestClient) -> None:
    run_response = client.post("/backtests/run", json=_backtest_payload("BUY_AND_HOLD"))
    assert run_response.status_code == 200
    backtest_id = run_response.json()["backtest_id"]

    response = client.delete(f"/backtests/{backtest_id}")

    assert response.status_code == 400
    assert client.get(f"/backtests/{backtest_id}").status_code == 200

    confirmed = client.delete(
        f"/backtests/{backtest_id}",
        params={"confirmation": f"Test BUY_AND_HOLD #{backtest_id}"},
    )
    assert confirmed.status_code == 200
    assert client.get(f"/backtests/{backtest_id}").status_code == 404


def test_backtest_no_lookahead_on_future_jump() -> None:
    engine = BacktestEngine()
    stable_values = [100.0] * 90
    future_jump = [250.0] * 20
    full_frame = _price_frame(stable_values + future_jump)
    truncated_frame = _price_frame(stable_values)

    full_scored = engine.prepare_price_frame_for_backtest(full_frame)
    truncated_scored = engine.prepare_price_frame_for_backtest(truncated_frame)

    assert full_scored.loc[89, "rolling_score"] == truncated_scored.loc[89, "rolling_score"]


def test_api_cache_save_and_read(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
    from backend.app.database import db_session

    with db_session() as connection:
        provider = AlphaVantageProvider(get_settings(), connection)
        request_url = "https://example.test/query?symbol=AAPL"
        payload = {"Time Series (Daily)": {"2026-05-15": {"4. close": "100"}}}
        provider.save_to_cache("daily", "AAPL", request_url, payload)

        assert provider.get_from_cache("daily", "AAPL", request_url) == payload


def test_api_rate_limit_guard(client: TestClient) -> None:
    from dataclasses import replace
    from datetime import UTC, datetime

    from backend.app.config import get_settings
    from backend.app.data_providers.base import RateLimitExceeded
    from backend.app.data_providers.coingecko import CoinGeckoProvider
    from backend.app.database import db_session

    with db_session() as connection:
        provider = CoinGeckoProvider(
            replace(get_settings(), enable_real_data=True, coingecko_api_key=None),
            connection,
        )
        now = datetime.now(UTC)
        reservation_id = provider.budget_manager.reserve(
            connection,
            provider.policy,
            provider.provider_name,
            "EOD",
            "a" * 64,
            now,
        )
        provider.budget_manager.complete(
            connection,
            reservation_id,
            "SUCCEEDED",
            200,
            0,
            None,
        )
        connection.execute(
            """
            UPDATE provider_usage_windows
            SET used_count = effective_limit
            WHERE provider = ? AND window_kind = 'MONTH'
            """,
            (provider.provider_name,),
        )
        connection.commit()

        with pytest.raises(RateLimitExceeded, match=r"coingecko:EOD:BUDGET_EXHAUSTED"):
            provider.fetch_daily(
                {
                    "id": 1,
                    "currency": "EUR",
                    "coingecko_id": "bitcoin",
                },
                1,
                bypass_cache=True,
            )


def test_data_usage_compat_reads_budget_projection(client: TestClient) -> None:
    from datetime import UTC, datetime

    from backend.app.data_providers.transport import SafeProviderTransport
    from backend.app.database import db_session
    from backend.app.services.provider_budget_service import ProviderBudgetPolicy

    with db_session() as connection:
        reservation_id = SafeProviderTransport().budget_manager.reserve(
            connection,
            ProviderBudgetPolicy(minute_limit=10, daily_limit=25, monthly_limit=100),
            "yahoo_finance",
            "EOD",
            "a" * 64,
            datetime.now(UTC),
        )
        SafeProviderTransport().budget_manager.complete(
            connection,
            reservation_id,
            "SUCCEEDED",
            200,
            0,
            None,
        )

    response = client.get("/data/usage")

    assert response.status_code == 200
    usage = {item["provider"]: item for item in response.json()}
    assert usage["yahoo_finance"]["calls_count"] == 1
    assert usage["yahoo_finance"]["daily_limit"] == 0


def test_manual_catalog_refresh_uses_fixed_transport_and_does_not_mutate_assets_or_prices(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from pathlib import Path

    from backend.app.api import routes
    from backend.app.data_providers.transport import SafeProviderTransport
    from backend.app.database import db_session
    from backend.app.services.catalog_service import CatalogService

    payload = (
        Path(__file__).parent
        / "fixtures"
        / "catalogs"
        / "trade_republic_it_excerpt.pdf"
    ).read_bytes()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(payload),
            headers={"content-type": "application/pdf"},
        )

    transport = SafeProviderTransport(
        allowed_hosts={"assets.traderepublic.com"}
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(
        routes,
        "catalog_service",
        CatalogService(
            transport=transport,
            clock=lambda: datetime(2026, 8, 17, 10, 30, tzinfo=UTC),
            sleeper=lambda _delay: None,
        ),
    )
    with db_session() as connection:
        before = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM assets) AS assets,
                    (SELECT COUNT(*) FROM price_history) AS prices
                """
            ).fetchone()
        )

    response = client.post("/data/catalog/refresh?force=true")

    assert response.status_code == 200
    assert response.json()["accepted"] == 2
    assert response.json()["rejected"] == 2
    assert response.json()["ambiguous"] == 0
    assert response.json()["unchanged"] is False
    assert len(response.json()["content_sha256"]) == 64
    assert len(requests) == 1
    assert str(requests[0].url) == (
        "https://assets.traderepublic.com/assets/files/IT/Instrument_Universe_IT_en.pdf"
    )
    with db_session() as connection:
        after = dict(
            connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM assets) AS assets,
                    (SELECT COUNT(*) FROM price_history) AS prices
                """
            ).fetchone()
        )
    assert after == before


def test_catalog_refresh_rejects_body_and_url_parameters_without_calling_provider(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import routes

    calls = 0

    class ForbiddenCatalogService:
        def refresh(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            nonlocal calls
            calls += 1
            raise AssertionError("catalog service must not be called")

    monkeypatch.setattr(routes, "catalog_service", ForbiddenCatalogService())

    body_response = client.post("/data/catalog/refresh", json={"url": "https://example.test"})
    url_response = client.post("/data/catalog/refresh?url=https://example.test")

    assert body_response.status_code == 422
    assert url_response.status_code == 422
    assert calls == 0


def test_catalog_refresh_failure_response_contains_only_stable_reason(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import routes
    from backend.app.services.catalog_service import CatalogRefreshError

    class FailingCatalogService:
        def refresh(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            try:
                raise RuntimeError("SENTINEL_PROVIDER_INTERNAL_DETAIL")
            except RuntimeError:
                raise CatalogRefreshError("DOWNLOAD_FAILED") from None

    monkeypatch.setattr(routes, "catalog_service", FailingCatalogService())

    response = client.post("/data/catalog/refresh")

    assert response.status_code == 502
    assert response.json() == {"detail": {"reason_code": "DOWNLOAD_FAILED"}}
    assert "SENTINEL" not in response.text


def test_catalog_refresh_runs_blocking_work_outside_the_event_loop(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Download, retry con sleep e parsing PDF sono sincroni: non devono bloccare l'event loop.
    from backend.app.api import routes
    from backend.app.services.catalog_service import CatalogRefreshError

    loop_threads: list[bool] = []

    class RecordingCatalogService:
        def refresh(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            try:
                asyncio.get_running_loop()
                loop_threads.append(True)
            except RuntimeError:
                loop_threads.append(False)
            raise CatalogRefreshError("DOWNLOAD_FAILED")

    monkeypatch.setattr(routes, "catalog_service", RecordingCatalogService())

    response = client.post("/data/catalog/refresh")

    assert response.status_code == 502
    assert loop_threads == [False]


def test_catalog_resolve_route_pages_immutable_accepted_entries_and_validates_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib

    from backend.app.api import routes
    from backend.app.database import db_session
    from backend.app.services.instrument_resolution_service import ResolutionResult

    with db_session() as connection:
        snapshot_id = int(
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, source_date,
                    row_count, status, parser_version, failure_reason_code
                )
                VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', ?,
                        '2026-08-17T12:00:00Z', NULL, 6, 'COMPLETE', 'test-v1', NULL)
                """,
                (hashlib.sha256(b"api-resolution-snapshot").hexdigest(),),
            ).lastrowid
        )
        entry_ids: list[int] = []
        for row_number in range(1, 7):
            entry_ids.append(
                int(
                    connection.execute(
                        """
                        INSERT INTO catalog_entries (
                            snapshot_id, row_number, isin, name, parse_status,
                            reason_code, raw_row_sha256, instrument_id, listing_id
                        )
                        VALUES (?, ?, ?, ?, 'ACCEPTED', 'VALID_ISIN', ?, NULL, NULL)
                        """,
                        (
                            snapshot_id,
                            row_number,
                            f"US00000000{row_number:02d}",
                            f"Synthetic {row_number}",
                            hashlib.sha256(f"row-{row_number}".encode()).hexdigest(),
                        ),
                    ).lastrowid
                )
            )
        failed_snapshot_id = int(
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, source_date,
                    row_count, status, parser_version, failure_reason_code
                )
                VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', NULL,
                        '2026-08-17T12:01:00Z', NULL, 0, 'FAILED', 'test-v1', 'DOWNLOAD_FAILED')
                """
            ).lastrowid
        )

    calls: list[list[int]] = []

    class FakeResolutionService:
        def resolve_catalog_entries(self, _connection, selected_entry_ids):  # noqa: ANN001, ANN202
            selected = list(selected_entry_ids)
            calls.append(selected)
            return [
                ResolutionResult(
                    catalog_entry_id=entry_id,
                    status="UNMATCHED",
                    reason_code="NO_PROVIDER_MATCH",
                    instrument_id=None,
                    listing_id=None,
                    candidate_count=0,
                    evidence_hash="d" * 64,
                )
                for entry_id in selected
            ]

    monkeypatch.setattr(routes, "instrument_resolution_service", FakeResolutionService())

    first = client.post(f"/data/catalog/{snapshot_id}/resolve?offset=0&limit=5")
    repeated = client.post(f"/data/catalog/{snapshot_id}/resolve?offset=0&limit=5")
    second = client.post(f"/data/catalog/{snapshot_id}/resolve?offset=5&limit=1")

    assert first.status_code == repeated.status_code == second.status_code == 200
    assert [item["catalog_entry_id"] for item in first.json()] == entry_ids[:5]
    assert [item["catalog_entry_id"] for item in repeated.json()] == entry_ids[:5]
    assert [item["catalog_entry_id"] for item in second.json()] == entry_ids[5:]
    assert calls == [entry_ids[:5], entry_ids[:5], entry_ids[5:]]
    assert client.post("/data/catalog/999999/resolve").status_code == 404
    assert client.post(f"/data/catalog/{failed_snapshot_id}/resolve").status_code == 409
    assert client.post(f"/data/catalog/{snapshot_id}/resolve?offset=-1").status_code == 422
    assert client.post(f"/data/catalog/{snapshot_id}/resolve?limit=0").status_code == 422
    assert client.post(f"/data/catalog/{snapshot_id}/resolve?limit=6").status_code == 422


@pytest.mark.parametrize(
    ("provider_error", "expected_status", "expected_reason"),
    [
        ("budget", 429, "OPENFIGI_RATE_LIMITED"),
        ("transport", 502, "OPENFIGI_PROVIDER_UNAVAILABLE"),
    ],
)
def test_catalog_resolve_route_sanitizes_provider_failures(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider_error: str,
    expected_status: int,
    expected_reason: str,
) -> None:
    import hashlib

    from backend.app.api import routes
    from backend.app.data_providers.transport import SafeProviderTransportError
    from backend.app.database import db_session
    from backend.app.services.provider_budget_service import ProviderBudgetExceeded

    secret = "SENTINEL_OPENFIGI_SECRET"

    class FailingResolutionService:
        def resolve_catalog_entries(self, _connection, _selected_entry_ids):  # noqa: ANN001, ANN202
            if provider_error == "budget":
                raise ProviderBudgetExceeded(secret, "IDENTITY", "DAY")
            raise SafeProviderTransportError(secret, "IDENTITY", secret)

    monkeypatch.setattr(routes, "instrument_resolution_service", FailingResolutionService())
    with db_session() as connection:
        snapshot_id = int(
            connection.execute(
                """
                INSERT INTO catalog_snapshots (
                    source, source_url, content_sha256, retrieved_at, source_date,
                    row_count, status, parser_version, failure_reason_code
                )
                VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', ?,
                        '2026-08-17T12:00:00Z', NULL, 1, 'COMPLETE', 'test-v1', NULL)
                """,
                (hashlib.sha256(provider_error.encode()).hexdigest(),),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO catalog_entries (
                snapshot_id, row_number, isin, name, parse_status,
                reason_code, raw_row_sha256, instrument_id, listing_id
            )
            VALUES (?, 1, 'US0378331005', 'Synthetic', 'ACCEPTED',
                    'VALID_ISIN', ?, NULL, NULL)
            """,
            (snapshot_id, hashlib.sha256(b"provider-failure-row").hexdigest()),
        )

    response = client.post(f"/data/catalog/{snapshot_id}/resolve")

    assert response.status_code == expected_status
    assert response.json() == {"detail": {"reason_code": expected_reason}}
    assert secret not in response.text


def test_alpha_policy_is_fail_closed_before_url_or_transport(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
    from backend.app.data_providers.base import ProviderError
    from backend.app.database import db_session

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "TEST_ALPHA_API_SENTINEL")
    get_settings.cache_clear()
    try:
        with db_session() as connection:
            provider = AlphaVantageProvider(get_settings(), connection)
            assert provider.availability().state == "DISABLED"
            assert provider.availability().reason_code == "SECRET_IN_QUERY_POLICY"
            with pytest.raises(
                ProviderError,
                match=r"alpha_vantage:EOD:SECRET_IN_QUERY_POLICY",
            ):
                provider.get_daily_prices("AAPL")
    finally:
        get_settings.cache_clear()


def test_yahoo_ticker_mapping(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.base import ProviderError
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider
    from backend.app.database import db_session

    with db_session() as connection:
        provider = YahooFinanceProvider(get_settings(), connection)
        # ETF europei -> ticker della borsa nativa nella valuta giusta
        assert provider.yahoo_ticker("VWCE") == "VWCE.DE"
        assert provider.yahoo_ticker("AGGH") == "AGGH.MI"
        assert provider.yahoo_ticker("IB01") == "IB01.L"
        # i simboli USA passano invariati
        assert provider.yahoo_ticker("AAPL") == "AAPL"
        # i simboli senza equivalente Yahoo restano sui dati locali
        with pytest.raises(ProviderError):
            provider.yahoo_ticker("BTP10Y")
        # nessuna API key richiesta
        assert provider.api_key_configured() is True
        assert provider.full_history is True


def test_yahoo_normalize_prices(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider
    from backend.app.database import db_session

    sample = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "EUR", "symbol": "VWCE.DE"},
                    # 2024-01-02, 2024-01-03, 2024-01-04 (UTC)
                    "timestamp": [1_704_153_600, 1_704_240_000, 1_704_326_400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 101.0, None],
                                "high": [102.0, 103.0, None],
                                "low": [99.0, 100.0, None],
                                "close": [101.0, 102.5, None],
                                "volume": [1000, 1200, None],
                            }
                        ],
                        "adjclose": [{"adjclose": [101.0, 102.5, None]}],
                    },
                }
            ],
        }
    }
    with db_session() as connection:
        provider = YahooFinanceProvider(get_settings(), connection)
        prices = provider.normalize_prices(sample, "VWCE")

    # la candela con close None viene scartata
    assert len(prices) == 2
    assert all(price["source"] == "real" and price["provider"] == "yahoo_finance" for price in prices)
    assert prices[0]["close"] == 101.0
    assert prices[1]["close"] == 102.5
    # ordinato per data crescente
    assert prices[0]["date"] < prices[1]["date"]
    # campi completi
    assert {"date", "open", "high", "low", "close", "adjusted_close", "volume"} <= set(prices[0])


def test_yahoo_news_provider_normalizes(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.yahoo_news import YahooNewsProvider
    from backend.app.database import db_session

    sample = {
        "news": [
            {
                "title": "Apple beats earnings and raises guidance",
                "publisher": "Reuters",
                "link": "https://example.com/aapl",
                "providerPublishTime": 1_700_000_000,
            },
            {"title": "", "link": "https://example.com/skip"},  # senza titolo -> scartata
        ]
    }
    with db_session() as connection:
        provider = YahooNewsProvider(get_settings(), connection)
        items = provider.normalize_news(sample, "AAPL")

    assert provider.api_key_configured() is True
    assert provider.daily_limit == 0  # nessun limite giornaliero
    assert len(items) == 1
    assert items[0]["provider"] == "yahoo_news"
    assert items[0]["title"].startswith("Apple beats")
    assert items[0]["source"] == "Reuters"
    assert items[0]["published_at"] is not None
    assert -1.0 <= items[0]["sentiment_score"] <= 1.0


def test_finnhub_news_provider_normalizes(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.finnhub_news import FinnhubNewsProvider
    from backend.app.database import db_session

    sample = {
        "articles": [
            {
                "headline": "Company beats earnings and raises guidance",
                "summary": "Strong profit growth and upgrade",
                "url": "https://example.com/a",
                "source": "Reuters",
                "datetime": 1_700_000_000,
            },
            {"headline": "", "summary": "no title -> skipped"},
        ]
    }
    with db_session() as connection:
        provider = FinnhubNewsProvider(get_settings(), connection)
        items = provider.normalize_news(sample, "AAPL")

    assert len(items) == 1
    assert items[0]["provider"] == "finnhub_news"
    assert items[0]["title"].startswith("Company beats")
    assert items[0]["published_at"] is not None
    assert -1.0 <= items[0]["sentiment_score"] <= 1.0


def test_eod_capability_registry_does_not_keep_yahoo_primary(client: TestClient) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.provider_registry import ProviderRegistry
    from backend.app.database import db_session

    with db_session() as connection:
        registry = ProviderRegistry(get_settings(), connection)

        assert registry.provider_for_asset_type("stock") is None
        assert registry.provider_for_asset_type("etf") is None
        assert registry.provider_for_asset_type("bond_etf") is None
        assert registry.provider_for_asset_type("crypto").provider_name == "coingecko"
        assert registry.provider_for_asset_type("macro").provider_name == "fred"


def test_refresh_asset_with_real_data_disabled(client: TestClient) -> None:
    response = client.post("/data/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["used_fallback"] is True
    assert data["rows_inserted"] == 0
    assert "Dati reali disattivati" in data["message"]


def test_alpha_policy_and_yahoo_are_never_called_without_stooq_mapping(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.alpha_vantage import AlphaVantageProvider
    from backend.app.data_providers.yahoo_finance import YahooFinanceProvider

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    monkeypatch.setenv("ENABLE_STOOQ", "true")
    get_settings.cache_clear()

    def _forbidden(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("Yahoo/Alpha non devono essere chiamati")

    monkeypatch.setattr(YahooFinanceProvider, "get_daily_prices", _forbidden)
    monkeypatch.setattr(AlphaVantageProvider, "get_daily_prices", _forbidden)

    response = client.post("/data/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] is None
    assert data["used_fallback"] is True
    assert data["rows_inserted"] == 0

    monkeypatch.setenv("ENABLE_REAL_DATA", "false")
    get_settings.cache_clear()


def test_data_status_endpoint(client: TestClient) -> None:
    response = client.get("/data/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enable_real_data"] is False
    assert data["data_mode"] == "SEED"
    assert {provider["provider"] for provider in data["provider_status"]} >= {
        "stooq",
        "alpha_vantage",
        "yahoo_finance",
        "coingecko",
        "fred",
    }
    assert all(provider["enabled"] is False for provider in data["provider_status"])
    coingecko = next(
        provider for provider in data["provider_status"] if provider["provider"] == "coingecko"
    )
    assert "Powered by CoinGecko API" in coingecko["supports"]
    assert data["cache_stats"]["entries"] >= 0


_DATA_STATUS_LEGACY_FIELDS = [
    "enable_real_data",
    "provider_status",
    "api_usage",
    "cache_stats",
    "global_last_update",
    "data_mode",
]
_PROVIDER_STATUS_LEGACY_FIELDS = [
    "provider",
    "enabled",
    "api_key_configured",
    "daily_limit",
    "calls_today",
    "supports",
]
_DATA_COVERAGE_FIELDS = [
    "measured_at",
    "latest_catalog_snapshot_id",
    "latest_catalog_retrieved_at",
    "latest_catalog_sha256",
    "parse_accepted_entries",
    "parse_ambiguous_entries",
    "parse_rejected_entries",
    "parse_denominator",
    "resolution_resolved_entries",
    "resolution_ambiguous_entries",
    "resolution_unmatched_entries",
    "resolution_rejected_entries",
    "resolution_unprocessed_entries",
    "resolution_denominator",
    "resolved_percent",
    "tier_denominator",
    "tier_counts",
    "tier_percentages",
    "trade_republic_denominator",
    "trade_republic_status_counts",
    "trade_republic_verified_percent",
    "by_asset_class",
    "by_market",
    "rejection_reasons",
    "provider_coverage",
    "fx_currency_denominator",
    "fx_fresh_currencies",
    "fx_stale_currencies",
    "fx_missing_currencies",
    "fx_coverage",
    "pending_refresh",
    "budget_deferred",
]


def test_data_coverage_endpoint_serializes_fx_rates_as_decimal_strings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal

    from backend.app.database import db_session
    from backend.app.services.data_coverage_service import CoverageInvariantError, DataCoverageService

    network_calls = _forbid_network(monkeypatch)
    with db_session() as connection:
        connection.execute(
            "INSERT INTO assets (symbol, name, asset_type, currency) VALUES ('CHFX', 'Swiss Fixture', 'stock', 'CHF')"
        )

    response = client.get("/data/coverage")

    assert response.status_code == 200, response.text
    body = response.json()
    assert list(body) == _DATA_COVERAGE_FIELDS
    # Il seed attiva soltanto asset legacy: nessun catalogo TR, denominatori espliciti a zero.
    assert body["latest_catalog_snapshot_id"] is None
    assert (body["parse_denominator"], body["resolution_denominator"], body["resolved_percent"]) == (0, 0, 0.0)
    assert [(item["provider"], item["capability"]) for item in body["provider_coverage"]] == [
        ("coingecko", "EOD"),
        ("coingecko", "QUOTE"),
        ("finnhub", "QUOTE"),
        ("stooq", "EOD"),
    ]
    fx = {item["from_currency"]: item for item in body["fx_coverage"]}
    assert list(fx) == ["CHF", "USD"]
    assert (
        body["fx_currency_denominator"],
        body["fx_fresh_currencies"],
        body["fx_stale_currencies"],
        body["fx_missing_currencies"],
    ) == (2, 1, 0, 1)
    assert isinstance(fx["USD"]["rate_to_eur"], str)
    assert Decimal(fx["USD"]["rate_to_eur"]) == Decimal("0.92")
    assert (fx["USD"]["status"], fx["USD"]["direction"], fx["USD"]["to_currency"]) == ("FRESH", "DIRECT", "EUR")
    assert '"rate_to_eur":"0.92"' in response.text
    assert fx["CHF"]["rate_to_eur"] is None
    assert '"rate_to_eur":null' in response.text
    assert fx["CHF"]["status"] == "MISSING"
    assert network_calls == []

    def broken(self, connection, measured_at):  # noqa: ANN001, ANN202
        raise CoverageInvariantError("parse_partition")

    monkeypatch.setattr(DataCoverageService, "measure", broken)
    failed = client.get("/data/coverage")
    assert failed.status_code == 500
    assert failed.json() == {"detail": {"reason_code": "COVERAGE_INVARIANT_FAILED"}}
    status_response = client.get("/data/status")
    assert status_response.status_code == 200
    assert status_response.json()["coverage_summary"] is None


def test_data_status_compat_keeps_legacy_fields_and_adds_budget_and_coverage(client: TestClient) -> None:
    response = client.get("/data/status")

    assert response.status_code == 200
    body = response.json()
    assert list(body)[: len(_DATA_STATUS_LEGACY_FIELDS)] == _DATA_STATUS_LEGACY_FIELDS
    assert body["data_mode"] == "SEED"
    summary = body["coverage_summary"]
    assert summary is not None
    assert summary["resolution_denominator"] == 0
    assert summary["resolved_percent"] == 0.0
    assert (
        summary["fx_currency_denominator"],
        summary["fx_fresh_currencies"],
        summary["fx_stale_currencies"],
        summary["fx_missing_currencies"],
    ) == (1, 1, 0, 0)
    for provider in body["provider_status"]:
        assert list(provider)[: len(_PROVIDER_STATUS_LEGACY_FIELDS)] == _PROVIDER_STATUS_LEGACY_FIELDS
        windows = {window["window"]: window for window in provider["budget_windows"]}
        assert list(windows) == ["MINUTE", "DAY", "MONTH"]
        # I campi legacy restano coerenti con la finestra giornaliera del budget.
        assert (windows["DAY"]["limit"] or 0) == provider["daily_limit"]
        assert provider["calls_today"] <= windows["DAY"]["used"]
        assert provider["availability_state"] in {"AVAILABLE", "DISABLED", "COOLDOWN"}
    stooq = next(item for item in body["provider_status"] if item["provider"] == "stooq")
    assert stooq["capabilities"] == ["EOD"]
    assert (stooq["availability_state"], stooq["availability_reason"]) == ("DISABLED", "OPT_IN_DISABLED")
    assert stooq["last_outcome"] is None
    assert "http" not in response.text
    assert "fingerprint" not in response.text


def test_status_endpoints_count_cache_rows_written_by_governed_transport(client: TestClient) -> None:
    # Il trasporto Fase 2 salva expires_at con suffisso "Z": lo status legacy non deve rompersi.
    from datetime import UTC, datetime, timedelta

    from backend.app.data_providers.transport import SafeProviderTransport
    from backend.app.database import db_session

    transport = SafeProviderTransport(allowed_hosts={"finnhub.io"})
    now = datetime.now(UTC)
    with db_session() as connection:
        transport._save_cache(connection, "finnhub_news", "company-news:AAPL", "a" * 64, 200, [], "json", now, 3600)
        transport._save_cache(
            connection, "stooq", "eod:spy.us", "b" * 64, 200, "", "text", now - timedelta(days=2), 3600
        )

    data_status = client.get("/data/status")
    news_status = client.get("/news/status")

    assert data_status.status_code == 200
    assert data_status.json()["cache_stats"] == {"entries": 2, "valid": 1, "expired": 1}
    assert news_status.status_code == 200
    assert news_status.json()["cache_status"] == {"entries": 1, "valid": 1, "expired": 0}


def test_asset_data_status_endpoint(client: TestClient) -> None:
    response = client.get("/data/status/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["last_source"] == "seed"
    assert data["is_real_data"] is False
    assert "seed/demo" in data["message"]


def test_data_refresh_endpoint_uses_fallback(client: TestClient) -> None:
    response = client.post("/data/refresh/BTC")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BTC"
    assert data["provider"] == "coingecko"
    assert data["used_fallback"] is True


def test_crypto_identity_backfill_preserves_legacy_symbols_and_curated_ids_only(
    client: TestClient,
) -> None:
    from backend.app.database import db_session

    response = client.get("/assets/BTC")

    assert response.status_code == 200
    assert response.json()["symbol"] == "BTC"
    with db_session() as connection:
        rows = connection.execute(
            """
            SELECT asset.symbol, identifier.normalized_value, attestation.source,
                   listing.timezone, listing.mic, asset.isin
            FROM assets AS asset
            JOIN instrument_listings AS listing
              ON listing.id = asset.instrument_listing_id
            JOIN instrument_identifiers AS identifier
              ON identifier.instrument_id = listing.instrument_id
             AND identifier.scheme = 'COINGECKO_ID'
            JOIN instrument_identifier_attestations AS attestation
              ON attestation.identifier_id = identifier.id
             AND attestation.source = 'LEGACY_CURATED'
            ORDER BY asset.symbol
            """
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("BNB", "binancecoin", "LEGACY_CURATED", "UTC", None, None),
        ("BTC", "bitcoin", "LEGACY_CURATED", "UTC", None, None),
        ("ETH", "ethereum", "LEGACY_CURATED", "UTC", None, None),
        ("SOL", "solana", "LEGACY_CURATED", "UTC", None, None),
        ("XRP", "ripple", "LEGACY_CURATED", "UTC", None, None),
    ]


def test_repeated_refresh_does_not_duplicate_price_history(client: TestClient) -> None:
    from backend.app.database import db_session

    with db_session() as connection:
        before = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE a.symbol = 'AAPL'
            """
        ).fetchone()["count"]

    client.post("/data/refresh/AAPL")
    client.post("/data/refresh/AAPL")

    with db_session() as connection:
        after = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM price_history ph
            JOIN assets a ON a.id = ph.asset_id
            WHERE a.symbol = 'AAPL'
            """
        ).fetchone()["count"]

    assert after == before


def test_sentiment_positive_keyword() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("Earnings beat and revenue growth support a dividend increase.")

    assert result["sentiment_label"] == "POSITIVE"
    assert result["sentiment_score"] > 0


def test_sentiment_negative_keyword() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("Guidance cut follows an investigation and revenue decline.")

    assert result["sentiment_label"] == "NEGATIVE"
    assert result["sentiment_score"] < 0


def test_sentiment_neutral_without_keywords() -> None:
    from backend.app.services.sentiment_engine import classify_sentiment

    result = classify_sentiment("")

    assert result["sentiment_label"] == "NEUTRAL"
    assert result["sentiment_score"] == 0


def test_news_impact_levels() -> None:
    from backend.app.services.sentiment_engine import estimate_impact

    assert estimate_impact({"title": "Upgrade after earnings beat", "summary": "", "sentiment_score": 0.7, "relevance_score": 90}) == "HIGH"
    assert estimate_impact({"title": "Revenue growth update", "summary": "", "sentiment_score": 0.2, "relevance_score": 55}) == "MEDIUM"
    assert estimate_impact({"title": "Market update", "summary": "", "sentiment_score": 0.0, "relevance_score": 20}) == "LOW"


def test_news_deduplication(client: TestClient) -> None:
    from backend.app.database import db_session
    from backend.app.services.news_engine import NewsEngine

    item = {
        "provider": "test",
        "title": "AAPL earnings beat",
        "summary": "Earnings beat and revenue growth.",
        "url": "https://example.test/aapl-earnings",
        "source": "Unit Test",
        "published_at": "2026-05-18T10:00:00",
        "sentiment_score": 0.6,
        "sentiment_label": "POSITIVE",
        "relevance_score": 90,
    }
    with db_session() as connection:
        engine = NewsEngine()
        first = engine.save_news_to_db(connection, "AAPL", [item])
        second = engine.save_news_to_db(connection, "AAPL", [item])
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM news_items WHERE symbol = 'AAPL' AND url = ?",
            (item["url"],),
        ).fetchone()["count"]

    assert first == (1, 0)
    assert second == (0, 1)
    assert count == 1


def test_refresh_news_with_real_news_disabled(client: TestClient) -> None:
    response = client.post("/news/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["provider"] == "mock_news"
    assert data["used_fallback"] is True
    assert "News reali disattivate" in data["message"]


def test_refresh_news_fallback_when_api_key_missing(client: TestClient, monkeypatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    # disabilita Yahoo (keyless) per testare il fallback a mock quando manca ogni key
    monkeypatch.setenv("ENABLE_YAHOO_NEWS", "false")
    get_settings.cache_clear()

    response = client.post("/news/refresh/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "mock_news"
    assert data["used_fallback"] is True
    assert "Provider news non configurato" in data["message"]

    monkeypatch.setenv("ENABLE_REAL_NEWS", "false")
    monkeypatch.setenv("ENABLE_YAHOO_NEWS", "true")
    get_settings.cache_clear()


def test_news_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news?symbol=AAPL")

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert {"title", "sentiment_label", "impact_level", "relevance_score"} <= set(data[0])


def test_symbol_news_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news/AAPL")

    assert response.status_code == 200
    assert all(item["symbol"] == "AAPL" for item in response.json())


def test_news_sentiment_endpoint(client: TestClient) -> None:
    client.post("/news/refresh/AAPL")
    response = client.get("/news/sentiment/AAPL")
    listed = client.get("/news/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    # Le news demo restano visibili ma non entrano mai nel sentiment (Task 12, estensione 2026-09-30).
    assert data["news_count"] == 0
    assert listed.json() and all(item["provider"] == "mock_news" for item in listed.json())
    assert data["sentiment_label"] in {"POSITIVE", "NEGATIVE", "NEUTRAL"}
    assert {"positive_count", "negative_count", "neutral_count", "latest_news"} <= set(data)


def test_news_status_endpoint(client: TestClient) -> None:
    response = client.get("/news/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enable_real_news"] is False
    by_provider = {provider["provider"]: provider for provider in data["provider_status"]}
    assert set(by_provider) >= {"finnhub_news", "alpha_vantage_news", "yahoo_news", "mock_news"}
    assert by_provider["alpha_vantage_news"]["enabled"] is False
    assert "SECRET_IN_QUERY_POLICY" in by_provider["alpha_vantage_news"]["supports"]
    assert by_provider["yahoo_news"]["enabled"] is False
    assert "NOT_PRIMARY_POLICY" in by_provider["yahoo_news"]["supports"]
    assert by_provider["finnhub_news"]["enabled"] is False
    assert data["daily_usage"]["calls_count"] == 0


def test_data_refresh_all_endpoint(client: TestClient) -> None:
    response = client.post("/data/refresh-all?limit=3")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["requested"] == 3
    assert data["summary"]["fallback"] == 3
    assert len(data["results"]) == 3
    assert all(item["used_fallback"] is True for item in data["results"])


def test_news_refresh_all_endpoint(client: TestClient) -> None:
    response = client.post("/news/refresh-all?limit=3")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["requested"] == 3
    assert len(data["results"]) == 3
    assert all(item["provider"] == "mock_news" for item in data["results"])


def _fixture_ecb_adapter(handler):  # noqa: ANN001, ANN202
    from backend.app.data_providers.ecb import ECB_ALLOWED_HOSTS, EcbFxProvider
    from backend.app.data_providers.transport import SafeProviderTransport

    transport = SafeProviderTransport(allowed_hosts=ECB_ALLOWED_HOSTS).with_client(
        httpx.Client(transport=httpx.MockTransport(handler))
    )
    return EcbFxProvider(transport, sleeper=lambda _delay: None)


def _enable_real_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("ENABLE_REAL_DATA", "true")
    get_settings.cache_clear()


def _usd_fx_rows() -> list[tuple[object, ...]]:
    from backend.app.database import db_session

    with db_session() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                """
                SELECT rate, observed_at, provider FROM fx_rates
                WHERE from_currency = 'USD' AND to_currency = 'EUR'
                ORDER BY observed_at, id
                """
            )
        ]


def test_fx_refresh_endpoint_refreshes_exactly_one_currency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.app.api.routes as routes
    from backend.app.services.fx_service import FXService

    body = (
        b"KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
        b"EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2026-08-14,1.25\n"
    )
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, stream=httpx.ByteStream(body), headers={"content-type": "text/csv"})

    monkeypatch.setattr(routes, "fx_service", FXService(ecb_provider=_fixture_ecb_adapter(handler)))
    _enable_real_data(monkeypatch)

    response = client.post("/data/fx/refresh", params={"from_currency": "usd"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UPDATED"
    assert data["rows_written"] == 1
    assert (data["from_currency"], data["to_currency"], data["provider"]) == ("USD", "EUR", "ecb")
    assert paths == ["/service/data/EXR/D.USD.EUR.SP00.A"]
    assert (0.8, "2026-08-14", "ecb") in _usd_fx_rows()


@pytest.mark.parametrize(
    ("status_code", "expected_status"),
    [(404, 503), (429, 429)],
)
def test_fx_refresh_endpoint_failure_is_sanitized_and_does_not_mutate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_status: int,
) -> None:
    import backend.app.api.routes as routes
    from backend.app.services.fx_service import FXService

    before = _usd_fx_rows()
    adapter = _fixture_ecb_adapter(lambda _request: httpx.Response(status_code))
    monkeypatch.setattr(routes, "fx_service", FXService(ecb_provider=adapter))
    _enable_real_data(monkeypatch)

    response = client.post("/data/fx/refresh", params={"from_currency": "USD"})

    assert response.status_code == expected_status
    assert "ecb.europa.eu" not in response.text
    assert _usd_fx_rows() == before


def test_fx_refresh_endpoint_respects_real_data_opt_in_and_validates_currency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.app.api.routes as routes
    from backend.app.services.fx_service import FXService

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    monkeypatch.setattr(routes, "fx_service", FXService(ecb_provider=_fixture_ecb_adapter(handler)))

    disabled = client.post("/data/fx/refresh", params={"from_currency": "USD"})
    _enable_real_data(monkeypatch)
    invalid = client.post("/data/fx/refresh", params={"from_currency": "US1"})

    assert disabled.status_code == 409
    assert invalid.status_code == 422
    assert calls == 0


def _mock_provider_network(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:  # noqa: ANN001
    """Sostituisce il client HTTP del trasporto governato: nessuna rete reale."""
    import backend.app.data_providers.transport as transport_module

    seen: list[httpx.Request] = []
    real_client = httpx.Client

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return real_client(transport=httpx.MockTransport(recording))

    monkeypatch.setattr(transport_module.httpx, "Client", factory)
    return seen


def test_data_refresh_route_reaches_governed_provider_without_route_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from pathlib import Path

    chart = json.loads(
        (Path(__file__).parent / "fixtures" / "market_data" / "coingecko_market_chart.json").read_text(
            encoding="utf-8"
        )
    )
    seen = _mock_provider_network(
        monkeypatch,
        lambda _request: httpx.Response(
            200,
            stream=httpx.ByteStream(json.dumps(chart).encode()),
            headers={"content-type": "application/json"},
        ),
    )
    _enable_real_data(monkeypatch)

    response = client.post("/data/refresh/BTC", params={"force": "true"})

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "coingecko"
    assert data["used_fallback"] is False, data["message"]
    assert [request.url.host for request in seen] == ["api.coingecko.com"]


def _verify_aapl_news_symbol() -> None:
    from backend.app.database import db_session

    with db_session() as connection:
        listing_id = connection.execute(
            "SELECT instrument_listing_id FROM assets WHERE symbol = 'AAPL'"
        ).fetchone()[0]
        connection.execute("UPDATE instrument_listings SET mic = 'XNAS' WHERE id = ?", (listing_id,))
        connection.execute(
            """
            INSERT INTO provider_symbols (
                provider, listing_id, capability, provider_symbol, normalized_symbol, status,
                source, observed_at, verified_at, evidence_hash, version
            )
            VALUES ('finnhub', ?, 'NEWS', 'AAPL', 'AAPL', 'VERIFIED', 'test',
                    '2026-09-30T00:00:00Z', '2026-09-30T00:00:00Z', ?, 1)
            """,
            (listing_id, hashlib.sha256(b"aapl news mapping").hexdigest()),
        )


def test_news_refresh_route_reaches_finnhub_with_verified_symbol(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from pathlib import Path

    from backend.app.config import get_settings

    sentinel = "SENTINEL_FINNHUB_ROUTE_KEY_4242"
    articles = json.loads(
        (Path(__file__).parent / "fixtures" / "market_data" / "finnhub_company_news.json").read_text(
            encoding="utf-8"
        )
    )
    _verify_aapl_news_symbol()
    seen = _mock_provider_network(
        monkeypatch,
        lambda _request: httpx.Response(
            200,
            stream=httpx.ByteStream(json.dumps(articles).encode()),
            headers={"content-type": "application/json"},
        ),
    )
    monkeypatch.setenv("ENABLE_REAL_NEWS", "true")
    monkeypatch.setenv("FINNHUB_API_KEY", sentinel)
    get_settings.cache_clear()

    response = client.post("/news/refresh/AAPL", params={"force": "true"})

    assert response.status_code == 200
    data = response.json()
    assert (data["provider"], data["used_fallback"]) == ("finnhub_news", False), data["message"]
    assert data["items_inserted"] == 2
    assert [request.url.path for request in seen] == ["/api/v1/company-news"]
    assert seen[0].headers["X-Finnhub-Token"] == sentinel
    assert sentinel not in response.text
    assert sentinel not in str(seen[0].url)


def test_news_refresh_all_is_bounded_and_forwards_force(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.services.news_engine import NewsEngine

    calls: list[tuple[str, bool]] = []

    def fake_refresh(self, connection, symbol, force=False):  # noqa: ANN001, ANN202
        calls.append((symbol, force))
        return {
            "symbol": symbol,
            "provider": "mock_news",
            "items_inserted": 0,
            "items_updated": 0,
            "used_cache": False,
            "used_fallback": True,
            "message": "fixture",
        }

    monkeypatch.setattr(NewsEngine, "refresh_news_for_symbol", fake_refresh)

    default = client.post("/news/refresh-all", params={"force": "true"})
    too_many = client.post("/news/refresh-all", params={"limit": "26"})
    maximum = client.post("/news/refresh-all", params={"limit": "25"})

    assert default.status_code == 200
    assert default.json()["summary"]["requested"] == 10
    assert all(force is True for _symbol, force in calls[:10])
    assert too_many.status_code == 422
    assert maximum.status_code == 200
    assert maximum.json()["summary"]["requested"] == 25
    assert len({symbol for symbol, _force in calls}) == 25


_DATA_REFRESH_RESULT_FIELDS = {
    "symbol",
    "provider",
    "rows_inserted",
    "rows_updated",
    "used_cache",
    "used_fallback",
    "message",
}


def test_data_refresh_all_defaults_to_10_and_keeps_legacy_payload(client: TestClient) -> None:
    response = client.post("/data/refresh-all")

    assert response.status_code == 200
    data = response.json()
    assert set(data["summary"]) == {"requested", "updated", "fallback", "rows_inserted", "rows_updated"}
    assert data["summary"]["requested"] == 10
    assert len(data["results"]) == 10
    assert all(set(item) == _DATA_REFRESH_RESULT_FIELDS for item in data["results"])
    assert client.post("/data/refresh-all", params={"limit": "26"}).status_code == 422


def test_data_refresh_all_prioritizes_positions_and_forwards_force(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.api import routes
    from backend.app.database import db_session

    forces: list[tuple[str, bool]] = []

    def fake_row(connection, asset, force=False):  # noqa: ANN001, ANN202
        forces.append((asset["symbol"], force))
        return {
            "symbol": asset["symbol"],
            "provider": "fixture",
            "rows_inserted": 1,
            "rows_updated": 0,
            "used_cache": False,
            "used_fallback": False,
            "message": "ok",
        }

    monkeypatch.setattr(routes.market_data_service, "refresh_asset_row", fake_row)
    with db_session() as connection:
        held = {
            row["symbol"]
            for row in connection.execute(
                """
                SELECT asset.symbol FROM portfolio_positions AS position
                JOIN assets AS asset ON asset.id = position.asset_id
                WHERE position.quantity != 0
                """
            )
        }

    response = client.post("/data/refresh-all", params={"limit": "3", "force": "true"})

    assert response.status_code == 200
    assert response.json()["summary"]["updated"] == 3
    assert all(force is True for _symbol, force in forces)
    assert {symbol for symbol, _force in forces} <= held


def test_single_refresh_enqueues_requested_unit_with_force(client: TestClient) -> None:
    from backend.app.database import db_session

    response = client.post("/data/refresh/AAPL", params={"force": "true"})

    assert response.status_code == 200
    assert set(response.json()) == _DATA_REFRESH_RESULT_FIELDS
    with db_session() as connection:
        row = connection.execute(
            """
            SELECT request.reason, request.force, request.state
            FROM refresh_requests AS request
            JOIN assets AS asset ON asset.instrument_listing_id = request.listing_id
            WHERE asset.symbol = 'AAPL'
            ORDER BY request.id DESC LIMIT 1
            """
        ).fetchone()
    assert (row["reason"], row["force"]) == ("REQUESTED", 1)
    assert row["state"] in {"SUCCEEDED", "FAILED", "SKIPPED_FRESH"}


def test_viewed_refresh_enqueues_single_non_forced_unit(client: TestClient) -> None:
    from backend.app.database import db_session

    with db_session() as connection:
        listing_id = connection.execute(
            "SELECT instrument_listing_id FROM assets WHERE symbol = 'MSFT'"
        ).fetchone()[0]

    first = client.post(f"/data/refresh/viewed/{listing_id}")
    second = client.post(f"/data/refresh/viewed/{listing_id}")
    missing = client.post("/data/refresh/viewed/999999")

    assert first.status_code == 200
    assert first.json()["refresh_request_id"] == second.json()["refresh_request_id"]
    assert missing.status_code == 404
    with db_session() as connection:
        rows = connection.execute(
            "SELECT reason, force, state FROM refresh_requests WHERE listing_id = ?",
            (listing_id,),
        ).fetchall()
    assert [tuple(row) for row in rows] == [("VIEWED", 0, "PENDING")]


def test_catalog_eod_enqueue_endpoint_is_bounded(client: TestClient) -> None:
    ok = client.post("/data/catalog/eod/enqueue", params={"after_listing_id": "0", "limit": "5"})

    assert ok.status_code == 200
    assert set(ok.json()) == {"enqueued", "next_cursor"}
    assert client.post("/data/catalog/eod/enqueue", params={"limit": "26"}).status_code == 422
    assert client.post("/data/catalog/eod/enqueue", params={"limit": "0"}).status_code == 422
    assert client.post("/data/catalog/eod/enqueue", params={"after_listing_id": "-1"}).status_code == 422


# Task 14: API catalogo, attivazione esplicita e conferme versionate (solo locali).

_CATALOG_RETRIEVED_AT = "2026-09-20T08:00:00Z"
_INSTRUMENT_ITEM_FIELDS = [
    "instrument_id",
    "canonical_name",
    "instrument_type",
    "asset_class",
    "quality_tier",
    "quality_reasons",
    "primary_identifier_scheme",
    "primary_identifier",
    "listing_id",
    "ticker",
    "mic",
    "venue_name",
    "currency",
    "timezone",
    "trade_republic_status",
    "trade_republic_cataloged_at",
    "trade_republic_verified_at",
    "observation_quality",
    "observed_at",
]


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def forbidden(_transport, request):  # noqa: ANN001, ANN202
        calls.append(str(request.url))
        raise AssertionError("catalog and attestation APIs must not use the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    return calls


def _insert_catalog_snapshot(
    connection: sqlite3.Connection,
    *,
    label: str,
    source: str = "TRADE_REPUBLIC_IT",
    retrieved_at: str = _CATALOG_RETRIEVED_AT,
    status: str = "COMPLETE",
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO catalog_snapshots (
                source, source_url, content_sha256, retrieved_at, source_date,
                row_count, status, parser_version, failure_reason_code
            )
            VALUES (?, 'https://example.test/catalog.pdf', ?, ?, NULL, ?, ?, 'test-v1', ?)
            """,
            (
                source,
                _sha(f"snapshot|{label}") if status == "COMPLETE" else None,
                retrieved_at,
                3 if status == "COMPLETE" else 0,
                status,
                None if status == "COMPLETE" else "DOWNLOAD_FAILED",
            ),
        ).lastrowid
    )


def _insert_catalog_instrument(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    row_number: int,
    name: str,
    isin: str,
    instrument_type: str,
    asset_class: str,
    figi: str | None = None,
) -> tuple[int, int]:
    instrument_id = int(
        connection.execute(
            """
            INSERT INTO instruments (
                canonical_name, instrument_type, asset_class, quality_tier, source
            )
            VALUES (?, ?, ?, 'REFERENCE_ONLY', 'TRADE_REPUBLIC_IT')
            """,
            (name, instrument_type, asset_class),
        ).lastrowid
    )
    identifiers = [("ISIN", isin, "TRADE_REPUBLIC_IT", _CATALOG_RETRIEVED_AT)]
    if figi is not None:
        identifiers.append(("FIGI", figi, "openfigi", "2026-09-21T09:00:00Z"))
    for scheme, value, source, observed_at in identifiers:
        identifier_id = int(
            connection.execute(
                """
                INSERT INTO instrument_identifiers (
                    scheme, normalized_value, scope, instrument_id, listing_id
                )
                VALUES (?, ?, 'INSTRUMENT', ?, NULL)
                """,
                (scheme, value, instrument_id),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO instrument_identifier_attestations (
                identifier_id, source, observed_at, evidence_hash
            )
            VALUES (?, ?, ?, ?)
            """,
            (identifier_id, source, observed_at, _sha(f"{scheme}|{value}")),
        )
    entry_id = int(
        connection.execute(
            """
            INSERT INTO catalog_entries (
                snapshot_id, row_number, isin, name, parse_status, reason_code,
                raw_row_sha256, instrument_id, listing_id
            )
            VALUES (?, ?, ?, ?, 'ACCEPTED', 'VALID_ISIN', ?, ?, NULL)
            """,
            (snapshot_id, row_number, isin, name, _sha(f"row|{isin}"), instrument_id),
        ).lastrowid
    )
    return instrument_id, entry_id


def _insert_listing_for_catalog(
    connection: sqlite3.Connection,
    *,
    instrument_id: int,
    ticker: str,
    mic: str,
    currency: str,
    timezone: str,
    trade_republic_status: str,
) -> int:
    return int(
        connection.execute(
            """
            INSERT INTO instrument_listings (
                instrument_id, ticker, mic, venue_name, currency, timezone,
                listing_status, trade_republic_status, trade_republic_cataloged_at,
                source, source_date
            )
            VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 'OFFICIAL_VENUE', '2026-09-20')
            """,
            (
                instrument_id,
                ticker,
                mic,
                f"Venue {mic}",
                currency,
                timezone,
                trade_republic_status,
                _CATALOG_RETRIEVED_AT if trade_republic_status == "CATALOGED" else None,
            ),
        ).lastrowid
    )


def _insert_resolved_listing(
    connection: sqlite3.Connection,
    *,
    instrument_id: int,
    catalog_entry_id: int,
    ticker: str,
    mic: str,
    currency: str,
    timezone: str,
    trade_republic_status: str = "CATALOGED",
) -> int:
    listing_id = _insert_listing_for_catalog(
        connection,
        instrument_id=instrument_id,
        ticker=ticker,
        mic=mic,
        currency=currency,
        timezone=timezone,
        trade_republic_status=trade_republic_status,
    )
    instrument_type = connection.execute(
        "SELECT instrument_type FROM instruments WHERE id = ?",
        (instrument_id,),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO listing_metadata_versions (
            instrument_listing_id, venue_name, timezone, instrument_type, source_code,
            observed_at, evidence_hash, status, version, supersedes_listing_metadata_version_id
        )
        VALUES (?, ?, ?, ?, 'OFFICIAL_VENUE', '2026-09-20T09:00:00Z', ?, 'VERIFIED', 1, NULL)
        """,
        (listing_id, f"Venue {mic}", timezone, instrument_type, _sha(f"metadata|{listing_id}")),
    )
    connection.execute(
        """
        INSERT INTO instrument_resolution_cases (
            catalog_entry_id, provider, request_fingerprint, status, reason_code,
            candidate_count, candidate_hash, evidence_hash, selected_instrument_id,
            selected_listing_id, candidate_figi, candidate_ticker, candidate_exchange_code,
            candidate_market_sector, candidate_security_type, candidate_name,
            candidate_currency_hint, created_at
        )
        VALUES (?, 'openfigi', ?, 'RESOLVED', 'EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE', 1, ?, ?,
                ?, ?, ?, ?, ?, 'Equity', 'Common Stock', NULL, ?, '2026-09-20T09:00:00Z')
        """,
        (
            catalog_entry_id,
            _sha(f"request|{listing_id}"),
            _sha(f"candidates|{listing_id}"),
            _sha(f"evidence|{listing_id}"),
            instrument_id,
            listing_id,
            f"BBG{listing_id:09d}",
            ticker,
            mic,
            currency,
        ),
    )
    connection.execute(
        "UPDATE catalog_entries SET listing_id = ? WHERE id = ?",
        (listing_id, catalog_entry_id),
    )
    return listing_id


def _catalog_fixture() -> dict[str, int]:
    from backend.app.database import db_session

    with db_session() as connection:
        _insert_catalog_snapshot(connection, label="older", retrieved_at="2026-09-01T08:00:00Z")
        snapshot_id = _insert_catalog_snapshot(connection, label="main")
        _insert_catalog_snapshot(
            connection,
            label="failed",
            retrieved_at="2026-09-25T08:00:00Z",
            status="FAILED",
        )
        other_source_id = _insert_catalog_snapshot(connection, label="other", source="TEST_SOURCE")
        alpha, alpha_entry = _insert_catalog_instrument(
            connection,
            snapshot_id=snapshot_id,
            row_number=1,
            name="Zeta Catalog Alpha",
            isin="US9ZETAAAA01",
            instrument_type="STOCK",
            asset_class="EQUITY",
            figi="BBG0ZETA0001",
        )
        beta, _beta_entry = _insert_catalog_instrument(
            connection,
            snapshot_id=snapshot_id,
            row_number=2,
            name="Zeta Catalog Beta",
            isin="IE9ZETABBB02",
            instrument_type="UNKNOWN",
            asset_class="UNKNOWN",
        )
        gamma, gamma_entry = _insert_catalog_instrument(
            connection,
            snapshot_id=other_source_id,
            row_number=1,
            name="zeta catalog gamma",
            isin="NL9ZETACCC03",
            instrument_type="ETF",
            asset_class="FUND",
        )
        alpha_us = _insert_resolved_listing(
            connection,
            instrument_id=alpha,
            catalog_entry_id=alpha_entry,
            ticker="ZTAA",
            mic="XNAS",
            currency="USD",
            timezone="America/New_York",
        )
        alpha_de = _insert_resolved_listing(
            connection,
            instrument_id=alpha,
            catalog_entry_id=alpha_entry,
            ticker="ZTAA",
            mic="XETR",
            currency="EUR",
            timezone="Europe/Berlin",
        )
        gamma_listing = _insert_resolved_listing(
            connection,
            instrument_id=gamma,
            catalog_entry_id=gamma_entry,
            ticker="ZTCG",
            mic="XAMS",
            currency="EUR",
            timezone="Europe/Amsterdam",
            trade_republic_status="NEVER_SEEN",
        )
        connection.execute(
            """
            INSERT INTO quality_assessments (
                instrument_id, tier, reason_codes_json, assessed_at, evidence_hash,
                evidence_scopes_json
            )
            VALUES (?, 'REFERENCE_ONLY', '["NO_VALID_OBSERVATION"]', '2026-09-21T10:00:00Z', ?, '[]')
            """,
            (gamma, _sha("quality|gamma")),
        )
        connection.execute(
            "UPDATE instruments SET quality_reason_code = 'NO_VALID_OBSERVATION' WHERE id = ?",
            (gamma,),
        )
        connection.execute(
            """
            INSERT INTO market_observations (
                listing_id, provider, capability, operation, provider_observed_at, ingested_at,
                timezone, session, currency, delay_seconds, source_quality, effective_quality,
                kind, close, observation_hash, revision
            )
            VALUES (?, 'stooq', 'EOD', 'EOD_DAILY', '2026-01-02T21:00:00Z', '2026-01-03T00:00:00Z',
                    'America/New_York', 'REGULAR', 'USD', 0, 'eod', 'eod', 'BAR', '10', ?, 1)
            """,
            (alpha_us, _sha("observation|alpha")),
        )
    return {
        "snapshot": snapshot_id,
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "alpha_us": alpha_us,
        "alpha_de": alpha_de,
        "gamma_listing": gamma_listing,
    }


def _instrument_keys(client: TestClient, params: dict[str, object]) -> list[tuple[int, int | None]]:
    response = client.get("/instruments", params=params)
    assert response.status_code == 200, response.text
    return [(item["instrument_id"], item["listing_id"]) for item in response.json()["items"]]


def test_instrument_search_is_paginated_case_insensitive_and_stable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = _forbid_network(monkeypatch)
    ids = _catalog_fixture()
    alpha_rows = [(ids["alpha"], ids["alpha_us"]), (ids["alpha"], ids["alpha_de"])]

    response = client.get("/instruments", params={"q": "ZETA catalog"})

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["items", "total", "limit", "offset", "catalog_snapshot_id"]
    assert (body["total"], body["limit"], body["offset"]) == (4, 50, 0)
    assert body["catalog_snapshot_id"] == ids["snapshot"]
    assert [(item["instrument_id"], item["listing_id"]) for item in body["items"]] == [
        *alpha_rows,
        (ids["beta"], None),
        (ids["gamma"], ids["gamma_listing"]),
    ]
    assert all(list(item) == _INSTRUMENT_ITEM_FIELDS for item in body["items"])
    alpha_us, _alpha_de, beta, gamma = body["items"]
    assert alpha_us == {
        "instrument_id": ids["alpha"],
        "canonical_name": "Zeta Catalog Alpha",
        "instrument_type": "STOCK",
        "asset_class": "EQUITY",
        "quality_tier": "REFERENCE_ONLY",
        "quality_reasons": [],
        "primary_identifier_scheme": "ISIN",
        "primary_identifier": "US9ZETAAAA01",
        "listing_id": ids["alpha_us"],
        "ticker": "ZTAA",
        "mic": "XNAS",
        "venue_name": "Venue XNAS",
        "currency": "USD",
        "timezone": "America/New_York",
        "trade_republic_status": "CATALOGED",
        "trade_republic_cataloged_at": "2026-09-20T08:00:00Z",
        "trade_republic_verified_at": None,
        "observation_quality": "stale",
        "observed_at": "2026-01-02T21:00:00Z",
    }
    assert beta == {
        "instrument_id": ids["beta"],
        "canonical_name": "Zeta Catalog Beta",
        "instrument_type": "UNKNOWN",
        "asset_class": "UNKNOWN",
        "quality_tier": "REFERENCE_ONLY",
        "quality_reasons": [],
        "primary_identifier_scheme": "ISIN",
        "primary_identifier": "IE9ZETABBB02",
        "listing_id": None,
        "ticker": None,
        "mic": None,
        "venue_name": None,
        "currency": None,
        "timezone": None,
        "trade_republic_status": "CATALOGED",
        "trade_republic_cataloged_at": "2026-09-20T08:00:00Z",
        "trade_republic_verified_at": None,
        "observation_quality": None,
        "observed_at": None,
    }
    assert gamma["quality_reasons"] == ["NO_VALID_OBSERVATION"]
    assert (gamma["trade_republic_status"], gamma["trade_republic_cataloged_at"]) == ("NEVER_SEEN", None)

    assert _instrument_keys(client, {"q": "ztcg"}) == [(ids["gamma"], ids["gamma_listing"])]
    assert _instrument_keys(client, {"q": "us9zetaaaa01"}) == alpha_rows
    assert _instrument_keys(client, {"q": " bbg0zeta0001 "}) == alpha_rows
    assert _instrument_keys(client, {"q": "zeta", "currency": "eur", "mic": "xetr"}) == [
        (ids["alpha"], ids["alpha_de"])
    ]
    assert _instrument_keys(client, {"q": "zeta", "asset_class": "FUND"}) == [
        (ids["gamma"], ids["gamma_listing"])
    ]
    assert _instrument_keys(client, {"q": "zeta", "instrument_type": "UNKNOWN"}) == [(ids["beta"], None)]
    assert _instrument_keys(client, {"q": "zeta", "trade_republic_status": "CATALOGED"}) == [
        *alpha_rows,
        (ids["beta"], None),
    ]
    assert _instrument_keys(client, {"q": "zeta", "quality_tier": "QUALIFIED"}) == []

    page = client.get("/instruments", params={"q": "zeta catalog", "limit": 2, "offset": 1}).json()
    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 1)
    assert [(item["instrument_id"], item["listing_id"]) for item in page["items"]] == [
        (ids["alpha"], ids["alpha_de"]),
        (ids["beta"], None),
    ]
    beyond = client.get("/instruments", params={"q": "zeta catalog", "offset": 4}).json()
    assert (beyond["items"], beyond["total"]) == ([], 4)
    everything = client.get("/instruments", params={"limit": 100}).json()
    assert everything["total"] >= 29
    assert len(everything["items"]) == min(100, everything["total"])

    for params in (
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"quality_tier": "BOGUS"},
        {"trade_republic_status": "BOGUS"},
        {"asset_class": "BOGUS"},
        {"instrument_type": "BOGUS"},
    ):
        assert client.get("/instruments", params=params).status_code == 422, params
    for hostile in ("%' OR 1=1 --", "zeta%catalog", "zeta_catalog", "\\"):
        hostile_response = client.get("/instruments", params={"q": hostile})
        assert hostile_response.status_code == 200
        assert hostile_response.json()["total"] == 0
    assert client.get("/instruments", params={"q": "zeta catalog"}).json()["total"] == 4
    assert network_calls == []


def test_assets_catalog_separation_keeps_assets_to_activated_instruments(
    client: TestClient,
) -> None:
    from backend.app.database import db_session

    ids = _catalog_fixture()

    assets = client.get("/assets").json()

    assert len(assets) == 25
    assert not {"ZTAA", "ZTCG"} & {asset["symbol"] for asset in assets}
    assert client.get("/instruments", params={"q": "zeta catalog"}).json()["total"] == 4
    with db_session() as connection:
        linked = connection.execute(
            "SELECT COUNT(*) FROM assets WHERE instrument_listing_id IN (?, ?, ?)",
            (ids["alpha_us"], ids["alpha_de"], ids["gamma_listing"]),
        ).fetchone()[0]
    assert linked == 0


def test_instrument_detail_lists_identifiers_and_listings_without_raw_payloads(
    client: TestClient,
) -> None:
    from backend.app.database import db_session

    ids = _catalog_fixture()
    with db_session() as connection:
        identifier_id = connection.execute(
            "SELECT id FROM instrument_identifiers WHERE scheme = 'ISIN' AND normalized_value = 'US9ZETAAAA01'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO instrument_identifier_attestations (
                identifier_id, source, observed_at, evidence_hash
            )
            VALUES (?, 'openfigi', '2026-09-22T10:00:00+00:00', ?)
            """,
            (identifier_id, _sha("isin|openfigi")),
        )

    response = client.get(f"/instruments/{ids['alpha']}")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == [*_INSTRUMENT_ITEM_FIELDS, "identifiers", "listings"]
    assert (body["listing_id"], body["ticker"], body["mic"]) == (ids["alpha_us"], "ZTAA", "XNAS")
    assert body["identifiers"] == [
        {
            "scheme": "ISIN",
            "value": "US9ZETAAAA01",
            "sources": ["TRADE_REPUBLIC_IT", "openfigi"],
            "first_observed_at": "2026-09-20T08:00:00Z",
            "last_observed_at": "2026-09-22T10:00:00Z",
        },
        {
            "scheme": "FIGI",
            "value": "BBG0ZETA0001",
            "sources": ["openfigi"],
            "first_observed_at": "2026-09-21T09:00:00Z",
            "last_observed_at": "2026-09-21T09:00:00Z",
        },
    ]
    assert body["listings"] == [
        {
            "listing_id": ids["alpha_us"],
            "ticker": "ZTAA",
            "mic": "XNAS",
            "venue_name": "Venue XNAS",
            "currency": "USD",
            "timezone": "America/New_York",
            "resolution_status": "RESOLVED",
            "trade_republic_status": "CATALOGED",
        },
        {
            "listing_id": ids["alpha_de"],
            "ticker": "ZTAA",
            "mic": "XETR",
            "venue_name": "Venue XETR",
            "currency": "EUR",
            "timezone": "Europe/Berlin",
            "resolution_status": "RESOLVED",
            "trade_republic_status": "CATALOGED",
        },
    ]
    assert "raw" not in response.text.lower()

    beta = client.get(f"/instruments/{ids['beta']}").json()
    assert beta["listings"] == []
    assert (beta["listing_id"], beta["trade_republic_status"]) == (None, "CATALOGED")
    assert [identifier["scheme"] for identifier in beta["identifiers"]] == ["ISIN"]
    missing = client.get("/instruments/999999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"reason_code": "INSTRUMENT_NOT_FOUND"}}


def test_activate_listing_creates_linked_asset_idempotently_and_blocks_conflicts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session
    from backend.app.models import AssetOut

    network_calls = _forbid_network(monkeypatch)
    ids = _catalog_fixture()

    created = client.post(f"/assets/from-listing/{ids['alpha_us']}")

    assert created.status_code == 201, created.text
    asset = created.json()
    assert list(asset) == list(AssetOut.model_fields)
    assert {
        field: asset[field]
        for field in ("symbol", "name", "asset_type", "tax_category", "exchange", "currency", "isin")
    } == {
        "symbol": "ZTAA",
        "name": "Zeta Catalog Alpha",
        "asset_type": "stock",
        "tax_category": "standard",
        "exchange": "XNAS",
        "currency": "USD",
        "isin": "US9ZETAAAA01",
    }
    repeated = client.post(f"/assets/from-listing/{ids['alpha_us']}")
    assert repeated.status_code == 200
    assert repeated.json()["id"] == asset["id"]

    venue_conflict = client.post(f"/assets/from-listing/{ids['alpha_de']}")
    assert venue_conflict.status_code == 409
    assert venue_conflict.json() == {"detail": {"reason_code": "LEGACY_SYMBOL_CONFLICT"}}

    legacy = client.post(
        "/assets",
        json={"symbol": "ZTCG", "name": "Legacy gamma", "asset_type": "etf", "currency": "EUR"},
    )
    assert legacy.status_code == 201
    legacy_conflict = client.post(f"/assets/from-listing/{ids['gamma_listing']}")
    assert legacy_conflict.status_code == 409
    assert legacy_conflict.json() == {"detail": {"reason_code": "LEGACY_SYMBOL_CONFLICT"}}

    with db_session() as connection:
        unresolved = _insert_listing_for_catalog(
            connection,
            instrument_id=ids["beta"],
            ticker="ZTBB",
            mic="XPAR",
            currency="EUR",
            timezone="Europe/Paris",
            trade_republic_status="NEVER_SEEN",
        )
    not_resolved = client.post(f"/assets/from-listing/{unresolved}")
    assert not_resolved.status_code == 409
    assert not_resolved.json() == {"detail": {"reason_code": "LISTING_NOT_RESOLVED"}}
    missing = client.post("/assets/from-listing/999999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"reason_code": "LISTING_NOT_FOUND"}}

    with db_session() as connection:
        rows = connection.execute(
            "SELECT id, instrument_listing_id FROM assets WHERE symbol IN ('ZTAA', 'ZTBB') ORDER BY id"
        ).fetchall()
    assert [tuple(row) for row in rows] == [(asset["id"], ids["alpha_us"])]
    assert len(client.get("/assets").json()) == 27
    assert network_calls == []


def _provider_symbol_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider": "finnhub",
        "provider_symbol": " ztaa ",
        "capability": "QUOTE",
        "source": "official_venue_check",
        "observed_at": "2026-09-25T10:00:00+02:00",
        "expected_currency": "usd",
        "evidence_hash": "A" * 64,
    }
    payload.update(overrides)
    return payload


def _post_provider_symbol(
    client: TestClient,
    listing_id: int,
    action: str,
    payload: dict[str, object],
    token: str | None = None,
) -> httpx.Response:
    body = payload if token is None else {**payload, "confirmation_token": token}
    return client.post(f"/instruments/listings/{listing_id}/provider-symbols/{action}", json=body)


def _provider_symbol_rows(listing_id: int) -> list[sqlite3.Row]:
    from backend.app.database import db_session

    with db_session() as connection:
        return connection.execute(
            """
            SELECT id, provider, capability, provider_symbol, normalized_symbol, status, source,
                   observed_at, verified_at, evidence_hash, version, supersedes_provider_symbol_id
            FROM provider_symbols
            WHERE listing_id = ?
            ORDER BY version
            """,
            (listing_id,),
        ).fetchall()


def test_provider_symbol_preview_apply_versions_and_is_idempotent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.config import get_settings
    from backend.app.data_providers.provider_registry import ProviderRegistry
    from backend.app.database import db_session

    network_calls = _forbid_network(monkeypatch)
    ids = _catalog_fixture()
    listing_id = ids["alpha_us"]
    payload = _provider_symbol_payload()

    preview = _post_provider_symbol(client, listing_id, "preview", payload)

    assert preview.status_code == 200, preview.text
    token = preview.json()["confirmation_token"]
    assert preview.json() == {
        "listing_id": listing_id,
        "normalized_provider_symbol": "ZTAA",
        "current_version": None,
        "confirmation_token": token,
    }
    assert len(token) == 64
    assert _provider_symbol_rows(listing_id) == []

    applied = _post_provider_symbol(client, listing_id, "apply", payload, token)
    assert applied.status_code == 200, applied.text
    assert applied.json() == {
        "listing_id": listing_id,
        "provider": "finnhub",
        "capability": "QUOTE",
        "normalized_provider_symbol": "ZTAA",
        "version": 1,
        "status": "VERIFIED",
    }
    repeated = _post_provider_symbol(client, listing_id, "apply", payload, token)
    assert repeated.status_code == 200
    assert repeated.json() == applied.json()
    rows = _provider_symbol_rows(listing_id)
    assert [tuple(row)[1:] for row in rows] == [
        (
            "finnhub",
            "QUOTE",
            "ZTAA",
            "ZTAA",
            "VERIFIED",
            "OFFICIAL_VENUE_CHECK",
            "2026-09-25T08:00:00Z",
            "2026-09-25T08:00:00Z",
            "a" * 64,
            1,
            None,
        )
    ]

    second_payload = _provider_symbol_payload(
        provider_symbol="ztab",
        observed_at="2026-09-26T09:00:00Z",
        evidence_hash="b" * 64,
    )
    second_preview = _post_provider_symbol(client, listing_id, "preview", second_payload)
    assert second_preview.status_code == 200
    assert second_preview.json()["current_version"] == 1
    second_token = second_preview.json()["confirmation_token"]
    stale_observed_at = _post_provider_symbol(
        client,
        listing_id,
        "apply",
        {**second_payload, "observed_at": "2026-09-26T09:00:01Z"},
        second_token,
    )
    assert stale_observed_at.status_code == 409
    assert stale_observed_at.json() == {"detail": {"reason_code": "PROVIDER_SYMBOL_CHANGED"}}
    stale_version = _post_provider_symbol(client, listing_id, "apply", second_payload, token)
    assert stale_version.status_code == 409
    assert len(_provider_symbol_rows(listing_id)) == 1

    second = _post_provider_symbol(client, listing_id, "apply", second_payload, second_token)
    assert second.status_code == 200, second.text
    assert (second.json()["version"], second.json()["normalized_provider_symbol"]) == (2, "ZTAB")
    rows = _provider_symbol_rows(listing_id)
    assert [(row["normalized_symbol"], row["status"], row["version"]) for row in rows] == [
        ("ZTAA", "RETIRED", 1),
        ("ZTAB", "VERIFIED", 2),
    ]
    assert rows[1]["supersedes_provider_symbol_id"] == rows[0]["id"]
    with db_session() as connection:
        matches = ProviderRegistry(get_settings(), connection).providers_for(
            connection,
            listing_id,
            "QUOTE",
        )
    assert [(match.provider, match.provider_symbol) for match in matches] == [("finnhub", "ZTAB")]
    assert network_calls == []


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"provider": "stooq", "capability": "QUOTE"}, "INCOMPATIBLE_PROVIDER_CAPABILITY"),
        ({"capability": "EOD"}, "INCOMPATIBLE_PROVIDER_CAPABILITY"),
        (
            {"provider": "coingecko", "capability": "EOD", "provider_symbol": "zeta-alpha"},
            "INCOMPATIBLE_INSTRUMENT_TYPE",
        ),
        ({"expected_currency": "EUR"}, "CURRENCY_MISMATCH"),
        ({"provider_symbol": "   "}, "INVALID_PROVIDER_SYMBOL"),
        ({"provider_symbol": "ZT AA"}, "INVALID_PROVIDER_SYMBOL"),
        ({"source": "https://example.test/evidence"}, "INVALID_SOURCE"),
        ({"evidence_hash": "not-a-hash"}, "INVALID_EVIDENCE_HASH"),
        ({"observed_at": "2026-09-25T10:00:00"}, "INVALID_OBSERVED_AT"),
    ],
)
def test_provider_symbol_rejects_incompatible_or_invalid_payloads(
    client: TestClient,
    overrides: dict[str, object],
    reason_code: str,
) -> None:
    ids = _catalog_fixture()
    payload = _provider_symbol_payload(**overrides)

    preview = _post_provider_symbol(client, ids["alpha_us"], "preview", payload)
    apply = _post_provider_symbol(client, ids["alpha_us"], "apply", payload, "0" * 64)

    assert preview.status_code == apply.status_code == 422
    assert preview.json() == apply.json() == {"detail": {"reason_code": reason_code}}
    assert _provider_symbol_rows(ids["alpha_us"]) == []


def test_provider_symbol_normalizes_per_provider_and_blocks_cross_listing_collision(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    network_calls = _forbid_network(monkeypatch)
    ids = _catalog_fixture()
    stooq = _provider_symbol_payload(provider="stooq", capability="EOD", provider_symbol=" ZTAA.US ")

    preview = _post_provider_symbol(client, ids["alpha_us"], "preview", stooq)
    assert preview.status_code == 200
    assert preview.json()["normalized_provider_symbol"] == "ztaa.us"
    applied = _post_provider_symbol(
        client,
        ids["alpha_us"],
        "apply",
        stooq,
        preview.json()["confirmation_token"],
    )
    assert applied.status_code == 200
    stored = _provider_symbol_rows(ids["alpha_us"])
    assert [(row["provider"], row["capability"], row["provider_symbol"], row["normalized_symbol"]) for row in stored] == [
        ("stooq", "EOD", "ztaa.us", "ZTAA.US")
    ]

    collision_payload = {**stooq, "provider_symbol": "ztaa.US", "expected_currency": "EUR"}
    collision = _post_provider_symbol(client, ids["alpha_de"], "preview", collision_payload)
    assert collision.status_code == 409
    assert collision.json() == {"detail": {"reason_code": "PROVIDER_SYMBOL_IN_USE"}}
    collision_apply = _post_provider_symbol(client, ids["alpha_de"], "apply", collision_payload, "0" * 64)
    assert collision_apply.status_code == 409
    assert _provider_symbol_rows(ids["alpha_de"]) == []

    foreign_venue = _post_provider_symbol(
        client,
        ids["alpha_de"],
        "preview",
        _provider_symbol_payload(expected_currency="EUR"),
    )
    assert foreign_venue.status_code == 422
    assert foreign_venue.json() == {"detail": {"reason_code": "INCOMPATIBLE_VENUE"}}
    unknown_provider = _post_provider_symbol(
        client,
        ids["alpha_us"],
        "preview",
        _provider_symbol_payload(provider="alpha_vantage"),
    )
    assert unknown_provider.status_code == 422

    with db_session() as connection:
        unresolved = _insert_listing_for_catalog(
            connection,
            instrument_id=ids["beta"],
            ticker="ZTBB",
            mic="XNYS",
            currency="USD",
            timezone="America/New_York",
            trade_republic_status="NEVER_SEEN",
        )
    not_resolved = _post_provider_symbol(client, unresolved, "preview", _provider_symbol_payload())
    assert not_resolved.status_code == 409
    assert not_resolved.json() == {"detail": {"reason_code": "LISTING_NOT_RESOLVED"}}
    missing = _post_provider_symbol(client, 999999, "preview", _provider_symbol_payload())
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"reason_code": "LISTING_NOT_FOUND"}}
    assert network_calls == []


def _trade_republic_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "VERIFIED",
        "source": "MANUAL_OFFICIAL_APP_CHECK",
        "observed_at": "2026-09-27T18:30:00+02:00",
        "evidence_hash": "C" * 64,
    }
    payload.update(overrides)
    return payload


def _post_trade_republic(
    client: TestClient,
    listing_id: int,
    action: str,
    payload: dict[str, object],
    token: str | None = None,
) -> httpx.Response:
    body = payload if token is None else {**payload, "confirmation_token": token}
    return client.post(f"/instruments/listings/{listing_id}/trade-republic/{action}", json=body)


def _trade_republic_state(listing_id: int) -> tuple[tuple[object, ...], list[tuple[object, ...]]]:
    from backend.app.database import db_session

    with db_session() as connection:
        listing = connection.execute(
            """
            SELECT trade_republic_status, trade_republic_verified_at, trade_republic_cataloged_at
            FROM instrument_listings
            WHERE id = ?
            """,
            (listing_id,),
        ).fetchone()
        attestations = connection.execute(
            """
            SELECT id, version, status, record_status, source, observed_at, evidence_hash,
                   supersedes_attestation_id
            FROM trade_republic_attestations
            WHERE listing_id = ?
            ORDER BY version
            """,
            (listing_id,),
        ).fetchall()
    return tuple(listing), [tuple(row) for row in attestations]


def test_trade_republic_attestation_preview_apply_chain_and_projection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session

    network_calls = _forbid_network(monkeypatch)
    ids = _catalog_fixture()
    listing_id = ids["alpha_us"]
    cataloged = ("CATALOGED", None, _CATALOG_RETRIEVED_AT)
    assert _trade_republic_state(listing_id) == (cataloged, [])
    payload = _trade_republic_payload()

    preview = _post_trade_republic(client, listing_id, "preview", payload)

    assert preview.status_code == 200, preview.text
    token = preview.json()["confirmation_token"]
    assert preview.json() == {
        "listing_id": listing_id,
        "current_status": "CATALOGED",
        "current_version": None,
        "confirmation_token": token,
    }
    assert _trade_republic_state(listing_id) == (cataloged, [])
    wrong_token = _post_trade_republic(client, listing_id, "apply", payload, "0" * 64)
    assert wrong_token.status_code == 409
    assert wrong_token.json() == {"detail": {"reason_code": "TRADE_REPUBLIC_ATTESTATION_CHANGED"}}
    stale = _post_trade_republic(
        client,
        listing_id,
        "apply",
        {**payload, "observed_at": "2026-09-27T18:30:01+02:00"},
        token,
    )
    assert stale.status_code == 409
    assert _trade_republic_state(listing_id) == (cataloged, [])

    applied = _post_trade_republic(client, listing_id, "apply", payload, token)
    assert applied.status_code == 200, applied.text
    assert applied.json() == {
        "listing_id": listing_id,
        "status": "VERIFIED",
        "source": "MANUAL_OFFICIAL_APP_CHECK",
        "observed_at": "2026-09-27T16:30:00Z",
        "evidence_hash": "c" * 64,
        "version": 1,
    }
    repeated = _post_trade_republic(client, listing_id, "apply", payload, token)
    assert repeated.status_code == 200
    assert repeated.json() == applied.json()
    listing_state, attestations = _trade_republic_state(listing_id)
    assert listing_state == ("VERIFIED", "2026-09-27T16:30:00Z", _CATALOG_RETRIEVED_AT)
    first_id = attestations[0][0]
    assert [row[1:] for row in attestations] == [
        (1, "VERIFIED", "ACTIVE", "MANUAL_OFFICIAL_APP_CHECK", "2026-09-27T16:30:00Z", "c" * 64, None)
    ]

    unavailable = _trade_republic_payload(
        status="UNAVAILABLE",
        source="OFFICIAL_SUPPORT_NOTICE",
        observed_at="2026-09-29T09:00:00Z",
        evidence_hash="d" * 64,
    )
    second_preview = _post_trade_republic(client, listing_id, "preview", unavailable)
    assert second_preview.status_code == 200
    assert (second_preview.json()["current_status"], second_preview.json()["current_version"]) == (
        "VERIFIED",
        1,
    )
    second = _post_trade_republic(
        client,
        listing_id,
        "apply",
        unavailable,
        second_preview.json()["confirmation_token"],
    )
    assert second.status_code == 200, second.text
    assert (second.json()["status"], second.json()["version"]) == ("UNAVAILABLE", 2)
    listing_state, attestations = _trade_republic_state(listing_id)
    assert listing_state == ("UNAVAILABLE", None, _CATALOG_RETRIEVED_AT)
    assert [(row[1], row[2], row[3], row[7]) for row in attestations] == [
        (1, "VERIFIED", "RETIRED", None),
        (2, "UNAVAILABLE", "ACTIVE", first_id),
    ]

    item = next(
        item
        for item in client.get("/instruments", params={"q": "zeta catalog alpha"}).json()["items"]
        if item["listing_id"] == listing_id
    )
    assert (item["trade_republic_status"], item["trade_republic_verified_at"]) == ("UNAVAILABLE", None)
    detail = client.get(f"/instruments/{ids['alpha']}").json()
    assert detail["listings"][0]["trade_republic_status"] == "UNAVAILABLE"

    with db_session() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE trade_republic_attestations SET status = 'VERIFIED' WHERE id = ?",
                (first_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM trade_republic_attestations WHERE id = ?", (first_id,))
    assert network_calls == []


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"status": "MAYBE"}, None),
        ({"source": "SCRAPER"}, None),
        ({"evidence_hash": "abc"}, "INVALID_EVIDENCE_HASH"),
        ({"observed_at": "2026-09-27T18:30:00"}, "INVALID_OBSERVED_AT"),
    ],
)
def test_trade_republic_attestation_rejects_invalid_payloads(
    client: TestClient,
    overrides: dict[str, object],
    reason_code: str | None,
) -> None:
    ids = _catalog_fixture()
    payload = _trade_republic_payload(**overrides)

    preview = _post_trade_republic(client, ids["alpha_us"], "preview", payload)
    apply = _post_trade_republic(client, ids["alpha_us"], "apply", payload, "0" * 64)

    assert preview.status_code == apply.status_code == 422
    if reason_code is not None:
        assert preview.json() == apply.json() == {"detail": {"reason_code": reason_code}}
    assert _trade_republic_state(ids["alpha_us"]) == (("CATALOGED", None, _CATALOG_RETRIEVED_AT), [])


def test_provider_symbol_and_trade_republic_attestation_reject_future_observed_at(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from backend.app.api import routes
    from backend.app.services.instrument_service import ListingConfirmationService

    monkeypatch.setattr(
        routes,
        "listing_confirmation_service",
        ListingConfirmationService(clock=lambda: datetime(2026, 9, 30, 12, 0, tzinfo=UTC)),
    )
    ids = _catalog_fixture()
    future = "2026-09-30T12:00:01Z"

    provider_preview = _post_provider_symbol(
        client,
        ids["alpha_us"],
        "preview",
        _provider_symbol_payload(observed_at=future),
    )
    attestation_apply = _post_trade_republic(
        client,
        ids["alpha_us"],
        "apply",
        _trade_republic_payload(observed_at=future),
        "0" * 64,
    )
    accepted = _post_trade_republic(
        client,
        ids["alpha_us"],
        "preview",
        _trade_republic_payload(observed_at="2026-09-30T12:00:00Z"),
    )

    assert provider_preview.status_code == attestation_apply.status_code == 422
    assert provider_preview.json() == attestation_apply.json() == {
        "detail": {"reason_code": "FUTURE_OBSERVED_AT"}
    }
    assert accepted.status_code == 200
    assert _provider_symbol_rows(ids["alpha_us"]) == []
    assert _trade_republic_state(ids["alpha_us"]) == (("CATALOGED", None, _CATALOG_RETRIEVED_AT), [])


def test_trade_republic_attestation_requires_resolved_existing_listing(client: TestClient) -> None:
    from backend.app.database import db_session

    ids = _catalog_fixture()
    with db_session() as connection:
        unresolved = _insert_listing_for_catalog(
            connection,
            instrument_id=ids["beta"],
            ticker="ZTBB",
            mic="XPAR",
            currency="EUR",
            timezone="Europe/Paris",
            trade_republic_status="CATALOGED",
        )

    not_resolved = _post_trade_republic(client, unresolved, "preview", _trade_republic_payload())
    missing = _post_trade_republic(client, 999999, "apply", _trade_republic_payload(), "0" * 64)

    assert not_resolved.status_code == 409
    assert not_resolved.json() == {"detail": {"reason_code": "LISTING_NOT_RESOLVED"}}
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"reason_code": "LISTING_NOT_FOUND"}}
    assert _trade_republic_state(unresolved) == (("CATALOGED", None, _CATALOG_RETRIEVED_AT), [])


def test_trade_republic_attestation_concurrent_applies_keep_one_active_version(
    client: TestClient,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from backend.app.config import get_settings
    from backend.app.database import db_session
    from backend.app.models import (
        TradeRepublicAttestationApplyIn,
        TradeRepublicAttestationPreviewIn,
    )
    from backend.app.services.instrument_service import (
        ListingConfirmationError,
        ListingConfirmationService,
    )

    ids = _catalog_fixture()
    listing_id = ids["alpha_us"]
    database_path = str(get_settings().database_path)
    service = ListingConfirmationService()

    def prepared(**overrides: object) -> TradeRepublicAttestationApplyIn:
        preview_in = TradeRepublicAttestationPreviewIn(**_trade_republic_payload(**overrides))
        with db_session() as connection:
            preview = service.preview_trade_republic_attestation(connection, listing_id, preview_in)
        return TradeRepublicAttestationApplyIn(
            **preview_in.model_dump(),
            confirmation_token=preview.confirmation_token,
        )

    def run_concurrently(payloads: list[TradeRepublicAttestationApplyIn]) -> list[str]:
        barrier = Barrier(len(payloads))

        def apply(payload: TradeRepublicAttestationApplyIn) -> str:
            connection = sqlite3.connect(database_path, timeout=10, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                barrier.wait()
                result = service.apply_trade_republic_attestation(connection, listing_id, payload)
                return f"{result.status}:{result.version}"
            except ListingConfirmationError as exc:
                return exc.reason_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
            return list(executor.map(apply, payloads))

    competing = run_concurrently(
        [
            prepared(evidence_hash="e" * 64),
            prepared(status="UNAVAILABLE", evidence_hash="f" * 64),
        ]
    )

    assert sorted(competing, key=lambda value: value.startswith("TRADE")) in (
        ["VERIFIED:1", "TRADE_REPUBLIC_ATTESTATION_CHANGED"],
        ["UNAVAILABLE:1", "TRADE_REPUBLIC_ATTESTATION_CHANGED"],
    )
    winner_status = next(value for value in competing if ":" in value).split(":")[0]
    listing_state, attestations = _trade_republic_state(listing_id)
    assert [(row[1], row[2], row[3]) for row in attestations] == [(1, winner_status, "ACTIVE")]
    assert listing_state[0] == winner_status

    same_payload = prepared(status="VERIFIED", evidence_hash="9" * 64, observed_at="2026-09-28T08:00:00Z")
    repeated = run_concurrently([same_payload, same_payload])

    assert repeated == ["VERIFIED:2", "VERIFIED:2"]
    listing_state, attestations = _trade_republic_state(listing_id)
    assert [(row[1], row[3]) for row in attestations] == [(1, "RETIRED"), (2, "ACTIVE")]
    assert listing_state[:2] == ("VERIFIED", "2026-09-28T08:00:00Z")
