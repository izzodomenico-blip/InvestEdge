import pytest
import sqlite3
from datetime import datetime, UTC
from backend.app.database import SCHEMA
from backend.app.services.portfolio_optimizer_service import PortfolioOptimizerService
from backend.app.models.schemas import OptimizerConfig, OptimizationMethod

@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # 1. Add some assets
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (1, 'AAPL', 'Apple', 'stock', 'medium')")
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (2, 'MSFT', 'Microsoft', 'stock', 'low')")
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (3, 'BTC', 'Bitcoin', 'crypto', 'high')")
    
    # 2. Add signals
    conn.execute("INSERT INTO signals (asset_id, symbol, signal, score) VALUES (1, 'AAPL', 'BUY', 85.0)")
    conn.execute("INSERT INTO signals (asset_id, symbol, signal, score) VALUES (2, 'MSFT', 'BUY', 90.0)")
    conn.execute("INSERT INTO signals (asset_id, symbol, signal, score) VALUES (3, 'BTC', 'HOLD', 40.0)")
    
    # 3. Add universe info
    conn.execute("INSERT INTO asset_universe (symbol, name, asset_type, universe_level, is_active) VALUES ('AAPL', 'Apple', 'stock', 'CORE', 1)")
    conn.execute("INSERT INTO asset_universe (symbol, name, asset_type, universe_level, is_active) VALUES ('MSFT', 'Microsoft', 'stock', 'CORE', 1)")
    conn.execute("INSERT INTO asset_universe (symbol, name, asset_type, universe_level, is_active) VALUES ('BTC', 'Bitcoin', 'crypto', 'CORE', 1)")

    # 3. Add price history
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (1, '2026-05-21', 150.0, 1)")
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (2, '2026-05-21', 300.0, 1)")
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (3, '2026-05-21', 60000.0, 1)")

    # 4. Add portfolio settings
    conn.execute("INSERT INTO portfolio_settings (id, initial_cash, current_cash) VALUES (1, 100000, 100000)")
    
    yield conn
    conn.close()

def test_equal_weight_optimization(mock_db):
    service = PortfolioOptimizerService()
    config = OptimizerConfig(
        run_name="Test Equal",
        universe_source="CORE",
        optimization_method=OptimizationMethod.EQUAL_WEIGHT,
        initial_capital_mode="CUSTOM_CAPITAL",
        custom_capital=100000.0,
        cash_reserve_percent=10.0,
        min_data_quality_score=0.0
    )
    
    run = service.generate_optimization_run(mock_db, config)
    assert run.summary.optimization_method == "EQUAL_WEIGHT"
    # AAPL and MSFT are BUY, BTC is HOLD but CORE. 
    # _get_candidates filters out HOLD if not in OPERATIONAL_BUY_CANDIDATES? 
    # Let's check candidates. 
    # Validated signals include BUY/WATCH/REDUCE. HOLD is not action_suggested = BUY.
    
    # In my implementation, candidates are signals with action_suggested != EXCLUDE and != REDUCE.
    # BTC signal HOLD might result in action_suggested = WATCH or HOLD.
    
    buy_items = [i for i in run.items if i.target_weight > 0]
    assert len(buy_items) > 0
    # Weights should be roughly equal
    weights = [i.target_weight for i in buy_items]
    assert max(weights) - min(weights) < 0.1

def test_score_weighted_optimization(mock_db):
    service = PortfolioOptimizerService()
    config = OptimizerConfig(
        run_name="Test Score",
        universe_source="CORE",
        optimization_method=OptimizationMethod.SCORE_WEIGHTED,
        initial_capital_mode="CUSTOM_CAPITAL",
        custom_capital=100000.0,
        min_data_quality_score=0.0,
        max_single_asset_weight=60.0
    )
    
    run = service.generate_optimization_run(mock_db, config)
    aapl = next(i for i in run.items if i.symbol == "AAPL")
    msft = next(i for i in run.items if i.symbol == "MSFT")
    # MSFT (90) should have more weight than AAPL (85)
    assert msft.target_weight > aapl.target_weight

def test_rebalance_orders_generation(mock_db):
    # Add a current position in BTC
    mock_db.execute("INSERT INTO portfolio_positions (asset_id, symbol, quantity, average_price, weight_percent, current_value, asset_type, currency) VALUES (3, 'BTC', 1.0, 50000.0, 50.0, 60000.0, 'crypto', 'USD')")
    mock_db.execute("UPDATE portfolio_settings SET current_cash = 50000") # Total value 110,000
    
    service = PortfolioOptimizerService()
    config = OptimizerConfig(
        run_name="Test Rebalance",
        universe_source="CORE",
        optimization_method=OptimizationMethod.EQUAL_WEIGHT,
        initial_capital_mode="CURRENT_PORTFOLIO",
        min_data_quality_score=0.0
    )
    
    run = service.generate_optimization_run(mock_db, config)
    # BTC target should be lower than 50% (3 assets + cash reserve)
    # A SELL order for BTC should be proposed
    btc_orders = [o for o in run.proposed_orders if o.symbol == "BTC" and o.order_type == "SELL"]
    assert len(btc_orders) > 0

def test_apply_rebalance_orders(mock_db):
    service = PortfolioOptimizerService()
    config = OptimizerConfig(
        run_name="Test Apply",
        universe_source="CORE",
        optimization_method=OptimizationMethod.EQUAL_WEIGHT,
        initial_capital_mode="CURRENT_PORTFOLIO",
        min_data_quality_score=0.0
    )
    
    run = service.generate_optimization_run(mock_db, config)
    assert len(run.proposed_orders) > 0
    
    count = service.apply_rebalance_orders(mock_db, run.summary.id)
    assert count > 0
    
    # Check if orders are in simulated_orders table
    orders_in_db = mock_db.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0]
    assert orders_in_db == count
