from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from backend.app.config import get_settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    exchange TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    sector TEXT,
    country TEXT,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, asset_type)
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL NOT NULL,
    adjusted_close REAL,
    volume REAL,
    source TEXT NOT NULL DEFAULT 'mock',
    provider TEXT,
    is_real_data INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    UNIQUE(asset_id, date, source)
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    quantity REAL NOT NULL,
    average_price REAL NOT NULL,
    invested_amount REAL NOT NULL DEFAULT 0,
    current_price REAL NOT NULL DEFAULT 0,
    current_value REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl_percent REAL NOT NULL DEFAULT 0,
    weight_percent REAL NOT NULL DEFAULT 0,
    asset_type TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS simulated_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    order_type TEXT CHECK(order_type IN ('BUY', 'SELL')),
    side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    gross_amount REAL NOT NULL DEFAULT 0,
    net_amount REAL NOT NULL DEFAULT 0,
    order_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note TEXT,
    strategy_tag TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'SIMULATED',
    executed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    total_value REAL NOT NULL DEFAULT 0,
    invested_value REAL NOT NULL DEFAULT 0,
    cash REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    total_pnl REAL NOT NULL DEFAULT 0,
    total_pnl_percent REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    initial_cash REAL NOT NULL DEFAULT 100000,
    current_cash REAL NOT NULL DEFAULT 100000,
    max_single_asset_weight REAL NOT NULL DEFAULT 25,
    max_asset_class_weight REAL NOT NULL DEFAULT 50,
    default_fee_percent REAL NOT NULL DEFAULT 0.1,
    crypto_max_weight REAL NOT NULL DEFAULT 15,
    min_cash_weight REAL NOT NULL DEFAULT 2,
    max_cash_weight REAL NOT NULL DEFAULT 35,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    signal TEXT NOT NULL CHECK(signal IN ('STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL')),
    score REAL NOT NULL,
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

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER,
    symbol TEXT,
    provider TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    source TEXT,
    published_at TEXT,
    sentiment_score REAL,
    sentiment_label TEXT,
    impact_level TEXT,
    relevance_score REAL,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS strategy_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_name TEXT NOT NULL,
    strategy_mode TEXT NOT NULL CHECK(strategy_mode IN ('CONSERVATIVE', 'BALANCED', 'AGGRESSIVE')),
    universe_level TEXT NOT NULL,
    config_json TEXT NOT NULL,
    total_current_value REAL NOT NULL DEFAULT 0,
    target_invested_value REAL NOT NULL DEFAULT 0,
    expected_cash_after_plan REAL NOT NULL DEFAULT 0,
    estimated_orders_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS strategy_plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    current_weight REAL NOT NULL DEFAULT 0,
    target_weight REAL NOT NULL DEFAULT 0,
    current_value REAL NOT NULL DEFAULT 0,
    target_value REAL NOT NULL DEFAULT 0,
    delta_value REAL NOT NULL DEFAULT 0,
    suggested_action TEXT NOT NULL,
    operational_signal TEXT,
    confidence TEXT,
    data_quality_score REAL,
    reason TEXT,
    blocker TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(plan_id) REFERENCES strategy_plans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS strategy_plan_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK(order_type IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    estimated_price REAL NOT NULL,
    estimated_gross_amount REAL NOT NULL,
    estimated_fees REAL NOT NULL,
    estimated_net_amount REAL NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'PROPOSED',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(plan_id) REFERENCES strategy_plans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARNING', 'CRITICAL')),
    symbol TEXT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'ACKNOWLEDGED', 'CLOSED')),
    source_module TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    acknowledged_at TEXT,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    severity TEXT NOT NULL CHECK(severity IN ('INFO', 'WARNING', 'CRITICAL')),
    universe_level TEXT,
    symbol TEXT,
    threshold_value REAL,
    config_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scheduler_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SUCCESS', 'WARNING', 'ERROR')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    summary_json TEXT,
    errors_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operational_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL CHECK(report_type IN ('DAILY', 'WEEKLY', 'MANUAL')),
    report_date TEXT NOT NULL,
    title TEXT NOT NULL,
    summary_json TEXT,
    markdown_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_optimization_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_name TEXT NOT NULL,
    optimization_method TEXT NOT NULL,
    universe_source TEXT NOT NULL,
    config_json TEXT NOT NULL,
    current_total_value REAL NOT NULL DEFAULT 0,
    target_invested_value REAL NOT NULL DEFAULT 0,
    target_cash REAL NOT NULL DEFAULT 0,
    expected_cash_after_rebalance REAL NOT NULL DEFAULT 0,
    estimated_orders_count INTEGER NOT NULL DEFAULT 0,
    estimated_fees REAL NOT NULL DEFAULT 0,
    estimated_turnover_percent REAL NOT NULL DEFAULT 0,
    risk_summary_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_optimization_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    current_weight REAL NOT NULL DEFAULT 0,
    target_weight REAL NOT NULL DEFAULT 0,
    current_value REAL NOT NULL DEFAULT 0,
    target_value REAL NOT NULL DEFAULT 0,
    delta_value REAL NOT NULL DEFAULT 0,
    operational_signal TEXT,
    data_quality_score REAL,
    ml_probability REAL,
    news_sentiment TEXT,
    risk_level TEXT,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES portfolio_optimization_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portfolio_rebalance_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK(order_type IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    estimated_price REAL NOT NULL,
    estimated_gross_amount REAL NOT NULL,
    estimated_fees REAL NOT NULL,
    estimated_net_amount REAL NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'PROPOSED' CHECK(status IN ('PROPOSED', 'PAPER_CREATED', 'IGNORED')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES portfolio_optimization_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenario_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_name TEXT NOT NULL,
    scenario_type TEXT NOT NULL,
    portfolio_source TEXT NOT NULL,
    config_json TEXT NOT NULL,
    current_portfolio_value REAL NOT NULL DEFAULT 0,
    stressed_portfolio_value REAL NOT NULL DEFAULT 0,
    absolute_loss REAL NOT NULL DEFAULT 0,
    percentage_loss REAL NOT NULL DEFAULT 0,
    risk_level TEXT NOT NULL,
    summary_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenario_asset_impacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    current_value REAL NOT NULL DEFAULT 0,
    shock_percent REAL NOT NULL DEFAULT 0,
    stressed_value REAL NOT NULL DEFAULT 0,
    absolute_impact REAL NOT NULL DEFAULT 0,
    percentage_impact REAL NOT NULL DEFAULT 0,
    loss_contribution_percent REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(scenario_id) REFERENCES scenario_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scenario_class_impacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    asset_class TEXT NOT NULL,
    current_value REAL NOT NULL DEFAULT 0,
    shock_percent REAL NOT NULL DEFAULT 0,
    stressed_value REAL NOT NULL DEFAULT 0,
    absolute_impact REAL NOT NULL DEFAULT 0,
    percentage_impact REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(scenario_id) REFERENCES scenario_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS api_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    endpoint TEXT,
    symbol TEXT,
    request_url_hash TEXT,
    response_json TEXT,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'OK',
    last_update TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    usage_date TEXT NOT NULL,
    calls_count INTEGER NOT NULL DEFAULT 0,
    daily_limit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, usage_date)
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    benchmark_symbol TEXT,
    buy_threshold REAL NOT NULL DEFAULT 70,
    sell_threshold REAL NOT NULL DEFAULT 40,
    max_asset_weight REAL NOT NULL DEFAULT 0.15,
    fee_percent REAL NOT NULL DEFAULT 0.1,
    stop_loss_percent REAL,
    take_profit_percent REAL,
    rebalance_frequency TEXT NOT NULL DEFAULT 'WEEKLY',
    total_return_percent REAL NOT NULL DEFAULT 0,
    cagr REAL NOT NULL DEFAULT 0,
    max_drawdown REAL NOT NULL DEFAULT 0,
    sharpe_ratio REAL NOT NULL DEFAULT 0,
    win_rate REAL NOT NULL DEFAULT 0,
    profit_factor REAL NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    final_value REAL NOT NULL DEFAULT 0,
    benchmark_return_percent REAL NOT NULL DEFAULT 0,
    alpha_vs_benchmark REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtest_equity_curve (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    portfolio_value REAL NOT NULL,
    cash REAL NOT NULL,
    invested_value REAL NOT NULL,
    drawdown_percent REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(backtest_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL CHECK(order_type IN ('BUY', 'SELL')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    gross_amount REAL NOT NULL DEFAULT 0,
    net_amount REAL NOT NULL DEFAULT 0,
    pnl REAL NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(backtest_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backtest_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    average_price REAL NOT NULL,
    final_price REAL NOT NULL,
    final_value REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(backtest_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ml_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    model_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    symbols_scope TEXT,
    features_json TEXT,
    metrics_json TEXT,
    model_path TEXT,
    trained_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ml_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER,
    symbol TEXT NOT NULL,
    prediction_date TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    probability_positive REAL,
    probability_outperform REAL,
    probability_drawdown REAL,
    predicted_label TEXT,
    confidence TEXT,
    features_snapshot_json TEXT,
    explanation_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(model_id) REFERENCES ml_models(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ml_training_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    train_start_date TEXT,
    train_end_date TEXT,
    test_start_date TEXT,
    test_end_date TEXT,
    samples_count INTEGER NOT NULL DEFAULT 0,
    accuracy REAL,
    precision REAL,
    recall REAL,
    f1_score REAL,
    roc_auc REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS asset_universe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    exchange TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    country TEXT,
    sector TEXT,
    industry TEXT,
    universe_level TEXT NOT NULL CHECK(universe_level IN ('CORE', 'EXTENDED', 'CANDIDATE')),
    is_active INTEGER NOT NULL DEFAULT 1,
    is_watchlisted INTEGER NOT NULL DEFAULT 0,
    is_portfolio_asset INTEGER NOT NULL DEFAULT 0,
    refresh_priority INTEGER NOT NULL DEFAULT 0,
    refresh_frequency_days INTEGER NOT NULL DEFAULT 7,
    last_price_refresh_at TEXT,
    last_signal_refresh_at TEXT,
    last_news_refresh_at TEXT,
    data_provider TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_assets_symbol ON assets(symbol);
CREATE INDEX IF NOT EXISTS idx_price_history_asset_date ON price_history(asset_id, date);
CREATE INDEX IF NOT EXISTS idx_portfolio_positions_asset ON portfolio_positions(asset_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date ON portfolio_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_signals_asset_generated ON signals(asset_id, generated_at);
CREATE INDEX IF NOT EXISTS idx_signals_asset_created ON signals(asset_id, created_at);
CREATE INDEX IF NOT EXISTS idx_news_items_published ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_items_symbol ON news_items(symbol);
CREATE INDEX IF NOT EXISTS idx_news_items_symbol_published ON news_items(symbol, published_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_news_items_url_unique ON news_items(url) WHERE url IS NOT NULL AND url <> '';
CREATE INDEX IF NOT EXISTS idx_api_cache_key ON api_cache(cache_key);
CREATE INDEX IF NOT EXISTS idx_api_usage_provider_date ON api_usage(provider, usage_date);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_backtest_equity_backtest_date ON backtest_equity_curve(backtest_id, date);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_backtest_date ON backtest_trades(backtest_id, date);
CREATE INDEX IF NOT EXISTS idx_backtest_positions_backtest ON backtest_positions(backtest_id);
CREATE INDEX IF NOT EXISTS idx_ml_models_trained ON ml_models(trained_at);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol_created ON ml_predictions(symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_ml_training_runs_created ON ml_training_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_asset_universe_level ON asset_universe(universe_level);
CREATE INDEX IF NOT EXISTS idx_asset_universe_active_priority ON asset_universe(is_active, refresh_priority);
CREATE INDEX IF NOT EXISTS idx_asset_universe_watchlist ON asset_universe(is_watchlisted, is_portfolio_asset);
"""


MIGRATIONS = {
    "assets": [
        ("sector", "ALTER TABLE assets ADD COLUMN sector TEXT"),
        ("country", "ALTER TABLE assets ADD COLUMN country TEXT"),
        ("risk_level", "ALTER TABLE assets ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'medium'"),
    ],
    "signals": [
        ("symbol", "ALTER TABLE signals ADD COLUMN symbol TEXT"),
        ("risk_level", "ALTER TABLE signals ADD COLUMN risk_level TEXT"),
        ("confidence", "ALTER TABLE signals ADD COLUMN confidence TEXT"),
        ("technical_summary", "ALTER TABLE signals ADD COLUMN technical_summary TEXT"),
        ("reasons_json", "ALTER TABLE signals ADD COLUMN reasons_json TEXT"),
        ("subscores_json", "ALTER TABLE signals ADD COLUMN subscores_json TEXT"),
        ("indicators_json", "ALTER TABLE signals ADD COLUMN indicators_json TEXT"),
        ("created_at", "ALTER TABLE signals ADD COLUMN created_at TEXT"),
        ("updated_at", "ALTER TABLE signals ADD COLUMN updated_at TEXT"),
    ],
    "portfolio_positions": [
        ("symbol", "ALTER TABLE portfolio_positions ADD COLUMN symbol TEXT"),
        ("invested_amount", "ALTER TABLE portfolio_positions ADD COLUMN invested_amount REAL NOT NULL DEFAULT 0"),
        ("current_price", "ALTER TABLE portfolio_positions ADD COLUMN current_price REAL NOT NULL DEFAULT 0"),
        ("current_value", "ALTER TABLE portfolio_positions ADD COLUMN current_value REAL NOT NULL DEFAULT 0"),
        ("realized_pnl", "ALTER TABLE portfolio_positions ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0"),
        ("unrealized_pnl", "ALTER TABLE portfolio_positions ADD COLUMN unrealized_pnl REAL NOT NULL DEFAULT 0"),
        ("unrealized_pnl_percent", "ALTER TABLE portfolio_positions ADD COLUMN unrealized_pnl_percent REAL NOT NULL DEFAULT 0"),
        ("weight_percent", "ALTER TABLE portfolio_positions ADD COLUMN weight_percent REAL NOT NULL DEFAULT 0"),
        ("asset_type", "ALTER TABLE portfolio_positions ADD COLUMN asset_type TEXT"),
        ("updated_at", "ALTER TABLE portfolio_positions ADD COLUMN updated_at TEXT"),
    ],
    "simulated_orders": [
        ("symbol", "ALTER TABLE simulated_orders ADD COLUMN symbol TEXT"),
        ("order_type", "ALTER TABLE simulated_orders ADD COLUMN order_type TEXT"),
        ("gross_amount", "ALTER TABLE simulated_orders ADD COLUMN gross_amount REAL NOT NULL DEFAULT 0"),
        ("net_amount", "ALTER TABLE simulated_orders ADD COLUMN net_amount REAL NOT NULL DEFAULT 0"),
        ("order_date", "ALTER TABLE simulated_orders ADD COLUMN order_date TEXT"),
        ("note", "ALTER TABLE simulated_orders ADD COLUMN note TEXT"),
        ("strategy_tag", "ALTER TABLE simulated_orders ADD COLUMN strategy_tag TEXT"),
        ("created_at", "ALTER TABLE simulated_orders ADD COLUMN created_at TEXT"),
    ],
    "price_history": [
        ("provider", "ALTER TABLE price_history ADD COLUMN provider TEXT"),
        ("is_real_data", "ALTER TABLE price_history ADD COLUMN is_real_data INTEGER NOT NULL DEFAULT 0"),
        ("fetched_at", "ALTER TABLE price_history ADD COLUMN fetched_at TEXT"),
    ],
    "api_cache": [
        ("endpoint", "ALTER TABLE api_cache ADD COLUMN endpoint TEXT"),
        ("symbol", "ALTER TABLE api_cache ADD COLUMN symbol TEXT"),
        ("request_url_hash", "ALTER TABLE api_cache ADD COLUMN request_url_hash TEXT"),
        ("response_json", "ALTER TABLE api_cache ADD COLUMN response_json TEXT"),
        ("status", "ALTER TABLE api_cache ADD COLUMN status TEXT NOT NULL DEFAULT 'OK'"),
        ("last_update", "ALTER TABLE api_cache ADD COLUMN last_update TEXT"),
    ],
    "backtest_runs": [
        ("benchmark_return_percent", "ALTER TABLE backtest_runs ADD COLUMN benchmark_return_percent REAL NOT NULL DEFAULT 0"),
        ("alpha_vs_benchmark", "ALTER TABLE backtest_runs ADD COLUMN alpha_vs_benchmark REAL NOT NULL DEFAULT 0"),
    ],
    "news_items": [
        ("symbol", "ALTER TABLE news_items ADD COLUMN symbol TEXT"),
        ("provider", "ALTER TABLE news_items ADD COLUMN provider TEXT"),
        ("sentiment_label", "ALTER TABLE news_items ADD COLUMN sentiment_label TEXT"),
        ("impact_level", "ALTER TABLE news_items ADD COLUMN impact_level TEXT"),
        ("relevance_score", "ALTER TABLE news_items ADD COLUMN relevance_score REAL"),
        ("raw_json", "ALTER TABLE news_items ADD COLUMN raw_json TEXT"),
        ("updated_at", "ALTER TABLE news_items ADD COLUMN updated_at TEXT"),
    ],
}


SIGNALS_REBUILD_SQL = """
DROP TABLE IF EXISTS signals_new;

CREATE TABLE signals_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    symbol TEXT,
    signal TEXT NOT NULL CHECK(signal IN ('STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL')),
    score REAL NOT NULL,
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

INSERT INTO signals_new (
    id, asset_id, symbol, signal, score, risk_level, confidence, technical_summary,
    reasons_json, subscores_json, indicators_json, rationale, source, generated_at, created_at, updated_at
)
SELECT
    id, asset_id, symbol, signal, score, risk_level, confidence, technical_summary,
    reasons_json,
    subscores_json,
    indicators_json,
    rationale,
    source,
    COALESCE(generated_at, CURRENT_TIMESTAMP),
    COALESCE(created_at, generated_at, CURRENT_TIMESTAMP),
    COALESCE(updated_at, created_at, generated_at, CURRENT_TIMESTAMP)
FROM signals;

DROP TABLE signals;
ALTER TABLE signals_new RENAME TO signals;
"""


def _database_file() -> str:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return str(settings.database_path)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(_database_file(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def migrate_db(connection: sqlite3.Connection) -> None:
    for table_name, migrations in MIGRATIONS.items():
        columns = _table_columns(connection, table_name)
        for column_name, statement in migrations:
            if column_name not in columns:
                connection.execute(statement)
                columns.add(column_name)

    signal_schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'signals'"
    ).fetchone()
    if signal_schema and "STRONG_BUY" not in signal_schema["sql"]:
        connection.executescript(SIGNALS_REBUILD_SQL)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_signals_asset_generated ON signals(asset_id, generated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_signals_asset_created ON signals(asset_id, created_at)")

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_simulated_orders_asset_date ON simulated_orders(asset_id, order_date)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_api_cache_provider_symbol ON api_cache(provider, symbol)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_provider_date ON api_usage(provider, usage_date)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_news_items_symbol ON news_items(symbol)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_news_items_symbol_published ON news_items(symbol, published_at)")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_news_items_url_unique ON news_items(url) WHERE url IS NOT NULL AND url <> ''"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ml_models_trained ON ml_models(trained_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol_created ON ml_predictions(symbol, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_ml_training_runs_created ON ml_training_runs(created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_asset_universe_level ON asset_universe(universe_level)")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_universe_active_priority ON asset_universe(is_active, refresh_priority)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_universe_watchlist ON asset_universe(is_watchlisted, is_portfolio_asset)"
    )


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA)
        migrate_db(connection)
