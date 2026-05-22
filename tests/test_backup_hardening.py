import pytest
import sqlite3
from pathlib import Path
from backend.app.database import SCHEMA
from backend.app.services.backup_service import BackupService
from backend.app.services.export_service import ExportService
from backend.app.services.hardening_service import HardeningService

@pytest.fixture
def mock_db(tmp_path):
    # Create a real file-based DB in tmp_path for backup tests
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # Add some data
    conn.execute("INSERT INTO assets (id, symbol, name, asset_type, risk_level) VALUES (1, 'AAPL', 'Apple', 'stock', 'medium')")
    conn.commit()
    
    yield conn, db_file
    conn.close()

def test_create_backup(mock_db, monkeypatch, tmp_path):
    conn, db_file = mock_db
    
    # Mock settings to use tmp_path
    monkeypatch.setattr("backend.app.config.get_settings", lambda: type('obj', (object,), {'db_path': str(db_file)})())
    
    service = BackupService()
    service.backup_dir = tmp_path / "backup"
    
    backup = service.create_database_backup(conn, snapshot_name="TestBackup")
    assert backup.snapshot_name == "TestBackup"
    assert Path(backup.file_path).exists()
    
    backups = service.list_backups(conn)
    assert len(backups) == 1
    assert backups[0].snapshot_name == "TestBackup"

def test_export_json(mock_db, monkeypatch, tmp_path):
    conn, db_file = mock_db
    monkeypatch.setattr("backend.app.config.get_settings", lambda: type('obj', (object,), {'db_path': str(db_file)})())
    
    service = ExportService()
    service.export_dir = tmp_path / "export"
    
    export = service.export_dataset(conn, "ASSETS", file_format="JSON")
    assert export.file_format == "JSON"
    assert Path(export.file_path).exists()
    
    with open(export.file_path, "r") as f:
        import json
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["symbol"] == "AAPL"

def test_hardening_report(mock_db, monkeypatch, tmp_path):
    conn, db_file = mock_db
    monkeypatch.setattr("backend.app.config.get_settings", lambda: type('obj', (object,), {'db_path': str(db_file)})())
    
    service = HardeningService()
    # Mock root_dir to tmp_path
    service.root_dir = tmp_path
    
    # Create a fake .gitignore
    with open(tmp_path / ".gitignore", "w") as f:
        f.write(".env\nnode_modules/")
        
    report = service.run_checks(conn)
    assert report.overall_status in ["OK", "WARNING", "ERROR"]
    
    gitignore_check = next(c for c in report.checks if "Gitignore" in c.check_name)
    assert gitignore_check.status == "OK"

def test_restore_requires_confirm(mock_db, monkeypatch, tmp_path):
    conn, db_file = mock_db
    monkeypatch.setattr("backend.app.config.get_settings", lambda: type('obj', (object,), {'db_path': str(db_file)})())
    
    service = BackupService()
    service.backup_dir = tmp_path / "backup"
    backup = service.create_database_backup(conn, snapshot_name="ToRestore")
    
    with pytest.raises(ValueError, match="Conferma necessaria"):
        service.restore_backup(conn, backup.id, confirm=False)
