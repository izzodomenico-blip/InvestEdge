import pytest
import sqlite3
import json
from unittest.mock import MagicMock, patch
from backend.app.services.google_tracker_import_service import GoogleTrackerImportService
from backend.app.database import SCHEMA

@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    yield conn
    conn.close()

def test_parse_numeric_formats():
    service = GoogleTrackerImportService()
    # Test helper directly (idx and field name for error msg)
    assert service._parse_numeric("383.47", "f", 1) == 383.47
    assert service._parse_numeric("383,47", "f", 1) == 383.47
    assert service._parse_numeric("1,234.56", "f", 1) == 1234.56
    assert service._parse_numeric("1.234,56", "f", 1) == 1234.56
    assert service._parse_numeric("€ 383,47", "f", 1) == 383.47
    assert service._parse_numeric("$ 1,000.00", "f", 1) == 1000.0
    assert service._parse_numeric(123.45, "f", 1) == 123.45
    assert service._parse_numeric(None, "f", 1) == 0.0
    assert service._parse_numeric("", "f", 1) == 0.0

def test_parse_numeric_invalid_format():
    service = GoogleTrackerImportService()
    with pytest.raises(ValueError, match="invalid numeric value: 383.47.00"):
        service._parse_numeric("383.47.00", "current_price", 2)

@patch("backend.app.services.google_tracker_import_service.GoogleSheetsService")
def test_preview_portfolio_with_invalid_row(mock_gs_service_class, mock_db):
    mock_gs_service = mock_gs_service_class.return_value
    # 2 rows: one valid, one with invalid numeric format
    mock_gs_service.read_range.return_value = [
        ["portfolio_name", "broker_name", "account_name", "symbol", "isin", "name", "asset_type", "quantity", "average_price", "current_price", "currency", "exchange", "market_value", "as_of_date"],
        ["P1", "B1", "A1", "AAPL", "ISIN1", "Apple", "stock", "10", "150", "160.00", "USD", "NASDAQ", "1600", "2026-05-22"],
        ["P1", "B1", "A1", "MSFT", "ISIN2", "Microsoft", "stock", "5", "200", "383.47.00", "USD", "NASDAQ", "1917", "2026-05-22"]
    ]
    mock_gs_service.validate_headers.return_value = []
    # Note: rows_to_dicts is called. In the real code it uses rows[0] as headers.
    mock_gs_service.rows_to_dicts.return_value = [
        {"portfolio_name": "P1", "symbol": "AAPL", "quantity": "10", "average_price": "150", "current_price": "160.00", "market_value": "1600"},
        {"portfolio_name": "P1", "symbol": "MSFT", "quantity": "5", "average_price": "200", "current_price": "383.47.00", "market_value": "1917"}
    ]
    
    service = GoogleTrackerImportService()
    import_id = service.preview_import(mock_db, "PORTFOLIO")
    
    # Verify results in DB
    row = mock_db.execute("SELECT * FROM external_imports WHERE id = ?", (import_id,)).fetchone()
    assert row["rows_total"] == 2
    assert row["rows_valid"] == 1
    assert row["rows_invalid"] == 1
    
    errors = json.loads(row["errors_json"])
    assert len(errors) == 1
    assert "row 3, field current_price, invalid numeric value: 383.47.00" in errors[0]
    
    # Check that rows were saved
    positions = mock_db.execute("SELECT * FROM external_import_positions WHERE import_id = ?", (import_id,)).fetchall()
    assert len(positions) == 2
    
    # AAPL should be PENDING
    aapl = next(p for p in positions if p["symbol"] == "AAPL")
    assert aapl["validation_status"] == "PENDING"
    assert aapl["current_price"] == 160.0
    
    # MSFT should be INVALID
    msft = next(p for p in positions if p["symbol"] == "MSFT")
    assert msft["validation_status"] == "INVALID"
    assert "383.47.00" in msft["validation_message"]
