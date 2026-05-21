import pytest
import sqlite3
from datetime import datetime, UTC
from backend.app.database import SCHEMA
from backend.app.services.strategy_control_service import StrategyControlService
from backend.app.models.schemas import StrategyPlanConfig

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
    conn.execute("INSERT INTO signals (asset_id, symbol, signal, score) VALUES (3, 'BTC', 'BUY', 70.0)")
    
    # 3. Add price history (needed for plan generation)
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (1, '2026-05-21', 150.0, 1)")
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (2, '2026-05-21', 300.0, 1)")
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (3, '2026-05-21', 60000.0, 1)")

    # 4. Add universe info
    conn.execute("INSERT INTO asset_universe (symbol, name, asset_type, universe_level, is_active) VALUES ('AAPL', 'Apple', 'stock', 'CORE', 1)")
    conn.execute("INSERT INTO asset_universe (symbol, name, asset_type, universe_level, is_active) VALUES ('MSFT', 'Microsoft', 'stock', 'CORE', 1)")
    conn.execute("INSERT INTO asset_universe (symbol, name, asset_type, universe_level, is_active) VALUES ('BTC', 'Bitcoin', 'crypto', 'EXTENDED', 1)")
    
    # 5. Add portfolio settings
    conn.execute("INSERT INTO portfolio_settings (id, initial_cash, current_cash) VALUES (1, 100000, 100000)")
    
    yield conn
    conn.close()

def test_generate_conservative_plan(mock_db):
    service = StrategyControlService()
    config = StrategyPlanConfig(
        plan_name="Conservative Test",
        universe_level="CORE",
        strategy_mode="CONSERVATIVE",
        max_positions=5,
        max_single_asset_weight=10.0,
        cash_reserve_percent=10.0,
        min_data_quality_score=0.0,
    )
    
    plan = service.generate_strategy_plan(mock_db, config)
    assert plan.summary.plan_name == "Conservative Test"
    assert plan.summary.strategy_mode == "CONSERVATIVE"
    assert len(plan.items) >= 2 # AAPL and MSFT
    # Target weight for conservative should be low
    aapl_item = next(i for i in plan.items if i.symbol == "AAPL")
    assert aapl_item.target_weight <= 10.0

def test_generate_aggressive_plan(mock_db):
    service = StrategyControlService()
    config = StrategyPlanConfig(
        plan_name="Aggressive Test",
        universe_level="EXTENDED",
        strategy_mode="AGGRESSIVE",
        max_positions=10,
        max_single_asset_weight=20.0,
        allow_crypto=True,
        min_data_quality_score=0.0,
    )
    
    plan = service.generate_strategy_plan(mock_db, config)
    assert plan.summary.strategy_mode == "AGGRESSIVE"
    # BTC should be included as we allowed crypto and used EXTENDED universe
    assert any(i.symbol == "BTC" for i in plan.items)

def test_apply_plan_creates_simulated_orders(mock_db):
    service = StrategyControlService()
    config = StrategyPlanConfig(
        plan_name="Apply Test",
        universe_level="CORE",
        strategy_mode="BALANCED",
        min_data_quality_score=0.0,
    )
    
    plan = service.generate_strategy_plan(mock_db, config)
    assert plan.summary.status == "DRAFT"
    
    orders_count = service.apply_plan_to_paper_trading(mock_db, plan.summary.id)
    assert orders_count > 0
    
    # Verify orders in DB
    executed_orders = mock_db.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0]
    assert executed_orders == orders_count
    
    # Verify plan status updated
    updated_plan = service.get_strategy_plan(mock_db, plan.summary.id)
    assert updated_plan.summary.status == "APPLIED"

def test_exclude_signal_blocks_buy(mock_db):
    # Set data quality very low for MSFT by deleting its history
    mock_db.execute("DELETE FROM price_history WHERE asset_id = 2")
    
    service = StrategyControlService()
    config = StrategyPlanConfig(
        plan_name="Exclude Test",
        universe_level="CORE",
        strategy_mode="BALANCED",
        min_data_quality_score=50.0, # This will trigger exclusion if score < 50
    )
    
    plan = service.generate_strategy_plan(mock_db, config)
    msft_item = next(i for i in plan.items if i.symbol == "MSFT")
    assert msft_item.suggested_action == "HOLD"
    assert msft_item.blocker is not None

def test_list_and_delete_plans(mock_db):
    service = StrategyControlService()
    config = StrategyPlanConfig(
        plan_name="P1", 
        universe_level="CORE", 
        strategy_mode="BALANCED",
        min_data_quality_score=0.0,
    )
    service.generate_strategy_plan(mock_db, config)
    
    plans = service.list_strategy_plans(mock_db)
    assert len(plans) == 1
    
    service.delete_plan(mock_db, plans[0].id)
    assert len(service.list_strategy_plans(mock_db)) == 0
