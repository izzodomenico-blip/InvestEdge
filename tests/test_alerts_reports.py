import pytest
import sqlite3
from datetime import datetime, UTC
from backend.app.database import SCHEMA
from backend.app.services.alert_service import AlertService
from backend.app.services.scheduler_service import SchedulerService
from backend.app.services.report_service import ReportService
from backend.app.models.schemas import SchedulerRunIn

@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # 1. Add some assets
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (1, 'AAPL', 'Apple', 'stock', 'medium')")
    
    # 2. Add portfolio settings
    conn.execute("INSERT INTO portfolio_settings (id, initial_cash, current_cash) VALUES (1, 100000, 100000)")
    
    # 3. Add default rules (similar to seed)
    rules = [
        ("DATA_QUALITY_BAD", "DATA_QUALITY_BAD", "CRITICAL", 50.0),
        ("PORTFOLIO_CONCENTRATION", "PORTFOLIO_CONCENTRATION", "WARNING", 20.0),
    ]
    for name, a_type, severity, threshold in rules:
        conn.execute("INSERT INTO alert_rules (rule_name, alert_type, severity, threshold_value, enabled) VALUES (?, ?, ?, ?, 1)", (name, a_type, severity, threshold))

    yield conn
    conn.close()

def test_create_and_manage_alert(mock_db):
    service = AlertService()
    alert_id = service.create_alert(mock_db, "TEST_ALERT", "INFO", "Title", "Message", symbol="AAPL")
    
    alerts = service.get_open_alerts(mock_db)
    assert len(alerts) == 1
    assert alerts[0].title == "Title"
    
    service.acknowledge_alert(mock_db, alert_id)
    # Status is still visible in list if not filtered or handled by OPEN
    
    service.close_alert(mock_db, alert_id)
    assert len(service.get_open_alerts(mock_db)) == 0

def test_evaluate_quality_alert(mock_db):
    # AAPL has NO history -> quality 0
    service = AlertService()
    service.evaluate_rules(mock_db)
    
    alerts = service.get_open_alerts(mock_db, severity="CRITICAL")
    assert any(a.alert_type == "DATA_QUALITY_BAD" and a.symbol == "AAPL" for a in alerts)

def test_scheduler_run_save(mock_db):
    service = SchedulerService()
    config = SchedulerRunIn(run_type="QUALITY", generate_report=True)
    
    run = service.run_manual_cycle(mock_db, config)
    assert run.status == "SUCCESS"
    assert "quality_audit" in run.summary
    assert "report_id" in run.summary
    
    history = service.list_runs(mock_db)
    assert len(history) == 1

def test_report_generation(mock_db):
    service = ReportService()
    report = service.generate_operational_report(mock_db, report_type="DAILY")
    
    assert report.report_type == "DAILY"
    assert "## Stato Sistema" in report.markdown_text
    
    latest = service.get_latest_report(mock_db)
    assert latest.id == report.id
