import pytest
from unittest.mock import MagicMock, patch
from backend.app.services.google_sheets_service import GoogleSheetsService
from backend.app.models.schemas import GoogleSheetsPreviewIn

@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.enable_google_sheets_import = True
    settings.google_sheets_spreadsheet_id = "test-spreadsheet-id"
    settings.google_sheets_portfolio_range = "PORTFOLIO!A:Z"
    settings.google_sheets_transactions_range = "TRANSACTIONS!A:Z"
    settings.google_sheets_cash_range = "CASH!A:Z"
    settings.google_sheets_watchlist_range = "WATCHLIST!A:Z"
    return settings

@pytest.fixture
def service(mock_settings):
    with patch("backend.app.services.google_sheets_service.get_settings", return_value=mock_settings):
        return GoogleSheetsService()

def test_read_range_uses_correct_parameter_name(service, mock_settings):
    mock_client = MagicMock()
    mock_values = mock_client.spreadsheets.return_value.values.return_value
    mock_values.get.return_value.execute.return_value = {"values": [["header"], ["row1"]]}
    
    with patch.object(service, "get_sheets_client", return_value=mock_client):
        result = service.read_range("TEST!A1")
        
        assert result == [["header"], ["row1"]]
        # Verify spreadsheetId was used, not spreadsheet_id
        mock_values.get.assert_called_with(spreadsheetId="test-spreadsheet-id", range="TEST!A1")

def test_read_range_handles_missing_spreadsheet_id(service, mock_settings):
    mock_settings.google_sheets_spreadsheet_id = None
    
    with pytest.raises(ValueError, match="GOOGLE_SHEETS_SPREADSHEET_ID not configured"):
        service.read_range("TEST!A1")

@patch("backend.app.api.routes.google_sheets_service")
@patch("backend.app.api.routes.get_settings")
def test_test_connection_endpoint_success(mock_get_settings, mock_gs_service):
    # This is a bit tricky since routes.py already instantiated the service
    # We can mock the methods directly
    mock_settings = MagicMock()
    mock_settings.google_sheets_portfolio_range = "PORTFOLIO!A:Z"
    mock_get_settings.return_value = mock_settings
    
    from backend.app.api.routes import test_google_sheets_connection
    
    result = test_google_sheets_connection()
    assert result == {"success": True, "message": "Connection OK"}
    mock_gs_service.read_range.assert_called_once_with("PORTFOLIO!A1:B1")

@patch("backend.app.services.google_tracker_import_service.GoogleSheetsService")
def test_preview_import_service_calls_read_range(mock_gs_service_class):
    from backend.app.services.google_tracker_import_service import GoogleTrackerImportService
    from backend.app.database import SCHEMA
    import sqlite3
    
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    mock_gs_service = mock_gs_service_class.return_value
    mock_gs_service.read_range.return_value = [
        ["portfolio_name", "broker_name", "account_name", "symbol", "isin", "name", "asset_type", "quantity", "average_price", "current_price", "currency", "exchange", "market_value", "as_of_date"],
        ["P1", "B1", "A1", "AAPL", "ISIN1", "Apple", "stock", "10", "150", "160", "USD", "NASDAQ", "1600", "2026-05-22"]
    ]
    mock_gs_service.validate_headers.return_value = []
    mock_gs_service.rows_to_dicts.return_value = [
        {"portfolio_name": "P1", "symbol": "AAPL", "quantity": "10", "average_price": "150", "current_price": "160", "market_value": "1600"}
    ]
    
    service = GoogleTrackerImportService()
    import_id = service.preview_import(conn, "PORTFOLIO")
    
    assert import_id is not None
    # Check if data was "saved" (previewed)
    row = conn.execute("SELECT * FROM external_imports WHERE id = ?", (import_id,)).fetchone()
    assert row["status"] == "PREVIEW"
    assert row["rows_total"] == 1
    assert row["rows_valid"] == 1
