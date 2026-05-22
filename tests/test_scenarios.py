import pytest
import sqlite3
from backend.app.database import SCHEMA
from backend.app.services.scenario_service import ScenarioService
from backend.app.models.schemas import ScenarioConfig, ScenarioType

@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # 1. Add some assets
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (1, 'AAPL', 'Apple', 'stock', 'medium')")
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (2, 'BTC', 'Bitcoin', 'crypto', 'high')")
    
    # 2. Add prices (needed for refresh_portfolio)
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (1, '2026-05-21', 150.0, 1)")
    conn.execute("INSERT INTO price_history (asset_id, date, close, is_real_data) VALUES (2, '2026-05-21', 100000.0, 1)") # BTC price 100k for simplicity
    
    # 3. Add portfolio
    conn.execute(
        """
        INSERT INTO portfolios (id, portfolio_name, portfolio_type, initial_cash, current_cash, is_active)
        VALUES (1, 'Default Portfolio', 'CORE', 25000, 0, 1)
        """
    )
    conn.execute("INSERT INTO portfolio_positions (portfolio_id, asset_id, symbol, quantity, average_price, weight_percent, current_value, asset_type, currency) VALUES (1, 1, 'AAPL', 100, 150.0, 60.0, 15000.0, 'stock', 'USD')")
    conn.execute("INSERT INTO portfolio_positions (portfolio_id, asset_id, symbol, quantity, average_price, weight_percent, current_value, asset_type, currency) VALUES (1, 2, 'BTC', 0.1, 100000.0, 40.0, 10000.0, 'crypto', 'USD')")
    
    yield conn
    conn.close()

def test_market_crash_scenario(mock_db):
    service = ScenarioService()
    config = ScenarioConfig(
        scenario_name="Test Crash",
        scenario_type=ScenarioType.MARKET_CRASH,
        portfolio_source="CURRENT_PORTFOLIO"
    )
    
    run = service.run_scenario_analysis(mock_db, config, portfolio_id=1)
    assert run.summary.scenario_type == "MARKET_CRASH"
    # STOCK shock is -20%, CRYPTO is -30%
    # AAPL (15000) -> 12000 (-3000)
    # BTC (10000) -> 7000 (-3000)
    # Total value 25000 -> 19000
    assert run.summary.current_portfolio_value == 25000.0
    assert run.summary.stressed_portfolio_value == 19000.0
    assert run.summary.absolute_loss == -6000.0
    assert run.summary.percentage_loss == -24.0
    assert run.summary.risk_level == "HIGH"

def test_custom_symbol_shock(mock_db):
    service = ScenarioService()
    config = ScenarioConfig(
        scenario_name="Custom Shock",
        scenario_type=ScenarioType.CUSTOM,
        portfolio_source="CURRENT_PORTFOLIO",
        symbol_shocks={"AAPL": -50.0}
    )
    
    run = service.run_scenario_analysis(mock_db, config, portfolio_id=1)
    aapl_impact = next(i for i in run.asset_impacts if i.symbol == "AAPL")
    assert aapl_impact.shock_percent == -50.0
    assert aapl_impact.absolute_impact == -7500.0

def test_mitigation_suggestions(mock_db):
    service = ScenarioService()
    config = ScenarioConfig(
        scenario_name="Recession Test",
        scenario_type=ScenarioType.RECESSION,
        portfolio_source="CURRENT_PORTFOLIO"
    )
    
    run = service.run_scenario_analysis(mock_db, config, portfolio_id=1)
    assert len(run.mitigation_suggestions) > 0
    assert any("ribilanciamento" in s.lower() for s in run.mitigation_suggestions)

def test_scenario_run_persistence(mock_db):
    service = ScenarioService()
    config = ScenarioConfig(
        scenario_name="Persistent Test",
        scenario_type=ScenarioType.BULL_RALLY,
        portfolio_source="CURRENT_PORTFOLIO"
    )
    
    run = service.run_scenario_analysis(mock_db, config, portfolio_id=1)
    runs = service.list_runs(mock_db, portfolio_id=1)
    assert len(runs) >= 1
    assert runs[0].scenario_name == "Persistent Test"
    
    detail = service.get_run(mock_db, run.summary.id)
    assert len(detail.asset_impacts) == 2
