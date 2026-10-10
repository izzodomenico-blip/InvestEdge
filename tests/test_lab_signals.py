"""Score unico v1 servito a segnali e analisi tecnica (spec SP1 §4.2, §5.5-§5.6, §6.1)."""

from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.config import get_settings
from backend.app.database import init_db
from backend.app.lab.contracts import LabError
from backend.app.lab.features import compute_features
from backend.app.lab.score_v1 import explain
from backend.app.services.common import signal_from_score
from backend.app.services.news_engine import NewsEngine
from backend.app.services.scoring_engine import ScoringEngine
from backend.app.services.signals_service import recalculate_signal, score_unavailable_reason
from backend.app.services.technical_analysis_service import get_technical_analysis
from tests.lab_fixtures import insert_asset, insert_bars, synthetic_bars

NOW = datetime(2024, 1, 10, 12, 0, tzinfo=UTC)


def _freeze_sentiment_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """La finestra news di 7 giorni non dipende dal calendario reale."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001, ANN206
            return NOW.replace(tzinfo=None) if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr("backend.app.services.sentiment_engine.datetime", FrozenDatetime)


def _asset_with_bars(
    connection: sqlite3.Connection,
    symbol: str,
    *,
    real_bars: int = 0,
    demo_bars: int = 0,
    risk_level: str = "medium",
) -> int:
    asset_id = insert_asset(connection, symbol, risk_level=risk_level)
    if real_bars:
        insert_bars(connection, asset_id, synthetic_bars(real_bars, seed=7), real=True, provider="stooq")
    if demo_bars:
        insert_bars(connection, asset_id, synthetic_bars(demo_bars, seed=8), real=False, provider=None)
    connection.commit()
    return asset_id


def _insert_real_news(connection: sqlite3.Connection, symbol: str, sentiment: float) -> None:
    published_at = (NOW - timedelta(days=1)).replace(tzinfo=None).isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO news_items (
            symbol, provider, title, summary, url, source, published_at, sentiment_score,
            sentiment_label, impact_level, relevance_score, raw_json, created_at, updated_at
        )
        VALUES (?, 'finnhub_news', 'Real headline', '', 'https://example.com/real', 'src', ?, ?,
            'POSITIVE', 'MEDIUM', 70, '{}', ?, ?)
        """,
        (symbol, published_at, sentiment, published_at, published_at),
    )
    connection.commit()


def _signals(connection: sqlite3.Connection, asset_id: int) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT signal, score, technical_score, news_score, final_score, news_sentiment_label, data_mode
        FROM signals
        WHERE asset_id = ?
        """,
        (asset_id,),
    ).fetchall()


def _latest_complete_d_row(connection: sqlite3.Connection, asset_id: int, data_mode: str) -> sqlite3.Row:
    return connection.execute(
        """
        SELECT date, score
        FROM features_daily
        WHERE asset_id = ? AND data_mode = ? AND timeframe = 'D' AND warmup_complete = 1
        ORDER BY date DESC
        LIMIT 1
        """,
        (asset_id, data_mode),
    ).fetchone()


def _feature_modes(connection: sqlite3.Connection, asset_id: int) -> set[str]:
    rows = connection.execute("SELECT DISTINCT data_mode FROM features_daily WHERE asset_id = ?", (asset_id,))
    return {row[0] for row in rows}


def test_signal_score_equals_features_daily_latest_row(lab_connection: sqlite3.Connection) -> None:
    asset_id = _asset_with_bars(lab_connection, "REAL1", real_bars=400, demo_bars=400)

    recalculate_signal(lab_connection, asset_id, now=NOW)
    lab_connection.commit()

    [signal] = _signals(lab_connection, asset_id)
    latest = _latest_complete_d_row(lab_connection, asset_id, "REAL")
    assert latest["date"] == synthetic_bars(400, seed=7)["date"].iloc[-1]
    assert signal["score"] == latest["score"]
    assert signal["technical_score"] == signal["final_score"] == signal["score"]
    assert signal["signal"] == signal_from_score(signal["score"])
    assert signal["data_mode"] == "REAL"
    # La serie demo dello stesso asset non entra nel calcolo.
    assert _feature_modes(lab_connection, asset_id) == {"REAL"}


def test_news_no_longer_changes_final_score(lab_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze_sentiment_clock(monkeypatch)
    asset_id = _asset_with_bars(lab_connection, "NEWS", real_bars=400)
    _insert_real_news(lab_connection, "NEWS", 0.8)

    recalculate_signal(lab_connection, asset_id, now=NOW)
    lab_connection.commit()

    [signal] = _signals(lab_connection, asset_id)
    weight = get_settings().news_sentiment_weight
    assert signal["news_score"] == round(0.8 * weight, 2) != 0
    assert signal["news_sentiment_label"] == "POSITIVE"
    assert signal["final_score"] == signal["score"] == _latest_complete_d_row(lab_connection, asset_id, "REAL")["score"]
    assert signal["signal"] == signal_from_score(signal["score"])


def test_news_refresh_keeps_final_score_equal_to_score(
    lab_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_sentiment_clock(monkeypatch)
    asset_id = _asset_with_bars(lab_connection, "NEWS2", real_bars=400)
    recalculate_signal(lab_connection, asset_id, now=NOW)
    lab_connection.commit()
    [before] = _signals(lab_connection, asset_id)
    _insert_real_news(lab_connection, "NEWS2", 0.8)

    # Nessun provider live in test: il refresh usa le news locali e ricalcola la sola parte informativa.
    NewsEngine().refresh_news_for_symbol(lab_connection, "NEWS2")
    lab_connection.commit()

    [after] = _signals(lab_connection, asset_id)
    assert after["news_score"] == round(0.8 * get_settings().news_sentiment_weight, 2)
    assert after["final_score"] == after["score"] == after["technical_score"] == before["score"]
    assert after["signal"] == before["signal"]


def test_news_refresh_keeps_a_zero_score(lab_connection: sqlite3.Connection) -> None:
    asset_id = insert_asset(lab_connection, "ZERO")
    lab_connection.execute(
        """
        INSERT INTO signals (asset_id, symbol, signal, score, technical_score, news_score, final_score, source)
        VALUES (?, 'ZERO', 'SELL', 0, 0, 0, 0, 'scoring_engine')
        """,
        (asset_id,),
    )
    lab_connection.commit()

    NewsEngine().refresh_news_for_symbol(lab_connection, "ZERO")

    [signal] = _signals(lab_connection, asset_id)
    assert (signal["score"], signal["technical_score"], signal["final_score"], signal["signal"]) == (0, 0, 0, "SELL")


def test_demo_asset_signal_is_marked_demo(lab_connection: sqlite3.Connection) -> None:
    asset_id = _asset_with_bars(lab_connection, "DEMO1", demo_bars=400)

    recalculate_signal(lab_connection, asset_id, now=NOW)
    lab_connection.commit()

    [signal] = _signals(lab_connection, asset_id)
    assert signal["data_mode"] == "DEMO"
    assert signal["final_score"] == signal["score"] == _latest_complete_d_row(lab_connection, asset_id, "DEMO")["score"]
    assert score_unavailable_reason(lab_connection, asset_id) is None


def test_short_real_history_yields_no_signal_and_reason(lab_connection: sqlite3.Connection) -> None:
    asset_id = _asset_with_bars(lab_connection, "SHORT", real_bars=100, demo_bars=400)
    lab_connection.execute(
        """
        INSERT INTO signals (asset_id, symbol, signal, score, technical_score, news_score, final_score, source)
        VALUES (?, 'SHORT', 'BUY', 72, 72, 0, 72, 'scoring_engine')
        """,
        (asset_id,),
    )
    lab_connection.commit()

    recalculate_signal(lab_connection, asset_id, now=NOW)
    lab_connection.commit()

    assert _signals(lab_connection, asset_id) == []
    assert score_unavailable_reason(lab_connection, asset_id) == "Storico reale insufficiente (100 barre, servono 252)."
    # Nessun ripiego sulla serie demo.
    assert _feature_modes(lab_connection, asset_id) == {"REAL"}


def test_score_prices_keeps_signature_and_uses_score_v1() -> None:
    bars = synthetic_bars(300, seed=11)
    prices = bars.assign(source="seed")

    result = ScoringEngine().score_prices(prices, asset_id=5, symbol="SYN", risk_level="high")

    expected = explain(compute_features(bars, "D").iloc[-1].to_dict(), "high")
    assert list(inspect.signature(ScoringEngine.score_prices).parameters) == [
        "self", "prices", "asset_id", "symbol", "risk_level",
    ]
    assert result["asset_id"] == 5
    assert result["symbol"] == "SYN"
    assert {key: result[key] for key in expected} == expected
    assert result["warmup_complete"] is True
    assert "volatility_30d" in result["indicators"]
    assert "volatility_annualized_30d" not in result["indicators"]


def test_technical_analysis_serves_the_signal_score(lab_connection: sqlite3.Connection) -> None:
    asset_id = _asset_with_bars(lab_connection, "TECH", real_bars=400, demo_bars=400)
    recalculate_signal(lab_connection, asset_id, now=NOW)
    lab_connection.commit()

    analysis = get_technical_analysis(lab_connection, "TECH", now=NOW)

    [signal] = _signals(lab_connection, asset_id)
    assert analysis is not None
    assert analysis.data_mode == "REAL"
    assert analysis.score == analysis.technical_score == analysis.final_score == signal["score"]
    assert analysis.signal == signal["signal"]
    assert analysis.asset.signal_data_mode == "REAL"
    assert {"volatility_30d", "max_drawdown_252"} <= set(analysis.indicators)


def test_technical_analysis_refuses_short_real_history(lab_connection: sqlite3.Connection) -> None:
    _asset_with_bars(lab_connection, "TECHSHORT", real_bars=100, demo_bars=400)

    with pytest.raises(LabError) as error:
        get_technical_analysis(lab_connection, "TECHSHORT", now=NOW)

    assert error.value.code == "INSUFFICIENT_REAL_HISTORY"
    assert error.value.message == "Storico reale insufficiente (100 barre, servono 252)."


_PRE_PHASE_1_SIGNALS = """
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    signal TEXT NOT NULL,
    score REAL NOT NULL,
    rationale TEXT,
    source TEXT NOT NULL DEFAULT 'scoring_engine',
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
_PRE_TASK_7_SIGNALS = """
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    signal TEXT NOT NULL CHECK(signal IN ('STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL')),
    score REAL NOT NULL,
    technical_score REAL,
    news_score REAL NOT NULL DEFAULT 0,
    final_score REAL,
    news_sentiment_label TEXT,
    news_impact_level TEXT,
    risk_level TEXT,
    confidence TEXT,
    technical_summary TEXT,
    reasons_json TEXT,
    subscores_json TEXT,
    indicators_json TEXT,
    rationale TEXT,
    source TEXT NOT NULL DEFAULT 'scoring_engine',
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);
"""


@pytest.mark.parametrize("legacy_signals", [_PRE_PHASE_1_SIGNALS, _PRE_TASK_7_SIGNALS], ids=["rebuild", "alter"])
def test_signals_data_mode_migration_is_additive(
    tmp_path,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    legacy_signals: str,
) -> None:
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                exchange TEXT,
                currency TEXT NOT NULL DEFAULT 'USD',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, asset_type)
            );
            {legacy_signals}
            INSERT INTO assets (id, symbol, name, asset_type, currency) VALUES (1, 'LEGACY', 'Legacy', 'stock', 'EUR');
            INSERT INTO signals (asset_id, signal, score, rationale) VALUES (1, 'BUY', 75, 'legacy-signal');
            """
        )
    connection.close()
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    get_settings.cache_clear()
    try:
        init_db()
    finally:
        get_settings.cache_clear()

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT rationale, data_mode FROM signals").fetchall() == []
        connection.execute("INSERT INTO signals (asset_id, signal, score, data_mode) VALUES (1, 'HOLD', 60, 'REAL')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO signals (asset_id, signal, score, data_mode) VALUES (1, 'HOLD', 60, 'SEED')")
    finally:
        connection.close()


def test_fresh_schema_has_checked_signals_data_mode(lab_connection: sqlite3.Connection) -> None:
    asset_id = insert_asset(lab_connection, "FRESH")
    lab_connection.execute(
        "INSERT INTO signals (asset_id, signal, score, data_mode) VALUES (?, 'HOLD', 60, 'DEMO')", (asset_id,)
    )
    with pytest.raises(sqlite3.IntegrityError):
        lab_connection.execute(
            "INSERT INTO signals (asset_id, signal, score, data_mode) VALUES (?, 'HOLD', 60, 'MIXED')", (asset_id,)
        )

@pytest.mark.parametrize("bars_count", [100, 320])
def test_migration_invalidates_unclassified_legacy_score(lab_connection, bars_count) -> None:
    from backend.app.database import migrate_db
    from backend.app.services.assets_service import list_assets
    from backend.app.services.signals_service import list_signals

    asset_id = _asset_with_bars(lab_connection, "OLD", real_bars=bars_count, demo_bars=400)
    lab_connection.execute(
        "INSERT INTO signals (asset_id, symbol, signal, score, technical_score, news_score, final_score) "
        "VALUES (?, 'OLD', 'BUY', 95, 75, 20, 95)", (asset_id,)
    )
    lab_connection.commit()
    migrate_db(lab_connection)
    migrate_db(lab_connection)
    [asset] = list_assets(lab_connection)
    assert asset.score is None and asset.final_score is None and asset.signal_data_mode is None
    assert list_signals(lab_connection) == []
    recalculate_signal(lab_connection, asset_id, now=NOW)
    lab_connection.commit()
    [asset] = list_assets(lab_connection)
    if bars_count < 252:
        assert asset.score is None
        assert asset.score_unavailable_reason == "Storico reale insufficiente (100 barre, servono 252)."
    else:
        assert asset.score == asset.final_score == _latest_complete_d_row(lab_connection, asset_id, "REAL")["score"]
        assert asset.signal_data_mode == "REAL"
        migrate_db(lab_connection)
        assert list_assets(lab_connection)[0].score == asset.score
