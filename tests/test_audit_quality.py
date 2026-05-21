import pytest
from datetime import datetime, timedelta, UTC
import sqlite3
from backend.app.database import db_session
from backend.app.services.data_quality_service import DataQualityService
from backend.app.services.signal_validation_service import SignalValidationService
from backend.app.services.system_health_service import SystemHealthService
from backend.app.services.operational_ranking_service import OperationalRankingService
from backend.app.models.schemas import AssetCreate

from backend.app.database import SCHEMA

@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # Add an asset
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (1, 'AAPL', 'Apple', 'stock', 'medium')")
    
    # Add an ML model
    conn.execute("""
        INSERT INTO ml_models (id, model_name, model_type, target_type, horizon_days)
        VALUES (1, 'Test Model', 'RANDOM_FOREST', 'POSITIVE_RETURN', 7)
    """)
    
    # Add a signal
    conn.execute("""
        INSERT INTO signals (asset_id, symbol, signal, score, confidence, technical_summary)
        VALUES (1, 'AAPL', 'BUY', 80.0, 'HIGH', 'Test technical summary')
    """)
    
    # Add an ML prediction
    conn.execute("""
        INSERT INTO ml_predictions (symbol, model_id, target_type, predicted_label, confidence, probability_positive, prediction_date, horizon_days)
        VALUES ('AAPL', 1, 'POSITIVE_RETURN', 'BUY', 'HIGH', 0.8, '2026-05-21', 7)
    """)
    
    # Add portfolio settings
    conn.execute("INSERT OR IGNORE INTO portfolio_settings (id, initial_cash, current_cash) VALUES (1, 100000, 100000)")
    
    yield conn
    conn.close()

def test_data_quality_good_series(mock_db):
    service = DataQualityService()
    # Add 60 days of prices
    base_date = datetime.now(UTC)
    for i in range(60):
        date_str = (base_date - timedelta(days=i)).isoformat()
        mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, ?, 150.0, 1, 'test')", (date_str,))
    
    quality = service.check_asset_quality(mock_db, "AAPL")
    assert quality.score >= 90
    assert quality.checks["sufficient_history"] is True
    assert quality.checks["real_data"] is True

def test_data_quality_short_series(mock_db):
    service = DataQualityService()
    # Add 5 days of prices
    base_date = datetime.now(UTC)
    for i in range(5):
        date_str = (base_date - timedelta(days=i)).isoformat()
        mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, ?, 150.0, 1, 'test')", (date_str,))
    
    quality = service.check_asset_quality(mock_db, "AAPL")
    assert quality.score < 70
    assert quality.checks["sufficient_history"] is False

def test_data_quality_duplicates(mock_db):
    service = DataQualityService()
    base_date = datetime.now(UTC).isoformat()
    mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, ?, 150.0, 1, 'test')", (base_date,))
    mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, ?, 155.0, 1, 'test2')", (base_date,))
    
    quality = service.check_asset_quality(mock_db, "AAPL")
    assert quality.checks["no_duplicates"] is False
    assert quality.details["duplicates_found"] == 1

def test_data_quality_stale(mock_db):
    service = DataQualityService()
    old_date = (datetime.now(UTC) - timedelta(days=20)).isoformat()
    mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, ?, 150.0, 1, 'test')", (old_date,))
    
    quality = service.check_asset_quality(mock_db, "AAPL")
    assert quality.checks["fresh_data"] is False

def test_signal_validation_low_quality(mock_db):
    service = SignalValidationService()
    # Add only 2 days of data -> low quality
    mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, '2023-01-01', 150.0, 0, 'test')")
    
    validation = service.validate_signal(mock_db, "AAPL")
    assert validation.validated_signal == "HOLD"
    assert validation.action_suggested == "EXCLUDE"
    assert "Data quality too low" in validation.reason

def test_signal_validation_high_weight(mock_db):
    service = SignalValidationService()
    # Good quality data
    base_date = datetime.now(UTC)
    for i in range(60):
        date_str = (base_date - timedelta(days=i)).isoformat()
        mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, ?, 150.0, 1, 'test')", (date_str,))
    
    # High weight in portfolio (300 shares @ 150 = 45,000. Total value with 100,000 cash = 145,000. Weight = 31%)
    mock_db.execute("INSERT INTO portfolio_positions (asset_id, symbol, weight_percent, quantity, average_price, asset_type, currency, invested_amount) VALUES (1, 'AAPL', 31.0, 300, 150.0, 'stock', 'USD', 45000.0)")
    
    validation = service.validate_signal(mock_db, "AAPL")
    assert validation.validated_signal == "HOLD"
    assert validation.action_suggested == "HOLD"
    assert "portfolio weight too high" in validation.reason

def test_operational_ranking_not_empty(mock_db):
    # Add enough data to make AAPL valid
    base_date = datetime.now(UTC)
    for i in range(60):
        date_str = (base_date - timedelta(days=i)).isoformat()
        mock_db.execute("INSERT INTO price_history (asset_id, date, close, is_real_data, source) VALUES (1, ?, 150.0, 1, 'test')", (date_str,))
    
    service = OperationalRankingService()
    ranking = service.get_operational_ranking(mock_db)
    assert len(ranking.buy_candidates) > 0
    assert ranking.buy_candidates[0].symbol == "AAPL"

def test_system_health(mock_db):
    service = SystemHealthService()
    health = service.get_health(mock_db)
    assert health.status in ["healthy", "degraded"]
    assert health.database == "connected"
