import pytest
import sqlite3
from backend.app.database import SCHEMA
from backend.app.services.user_settings_service import UserSettingsService
from backend.app.models.schemas import RiskProfileCreateIn

@pytest.fixture
def mock_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # 1. Add default profiles (similar to seed)
    from backend.scripts.seed_database import _create_default_profiles
    _create_default_profiles(conn)
    
    yield conn
    conn.close()

def test_list_risk_profiles(mock_db):
    service = UserSettingsService()
    profiles = service.list_risk_profiles(mock_db)
    assert len(profiles) >= 3
    assert any(p.profile_type == "BALANCED" for p in profiles)

def test_active_risk_profile(mock_db):
    service = UserSettingsService()
    active = service.get_active_risk_profile(mock_db)
    assert active.is_active is True
    assert active.profile_type == "BALANCED" # Default from seed

def test_activate_profile(mock_db):
    service = UserSettingsService()
    # Find Conservative
    profiles = service.list_risk_profiles(mock_db)
    cons = next(p for p in profiles if p.profile_type == "CONSERVATIVE")
    
    service.activate_risk_profile(mock_db, cons.id)
    
    active = service.get_active_risk_profile(mock_db)
    assert active.id == cons.id
    assert active.profile_type == "CONSERVATIVE"

def test_create_custom_profile(mock_db):
    service = UserSettingsService()
    new_p = RiskProfileCreateIn(
        profile_name="Super Safe",
        profile_type="CUSTOM",
        max_single_asset_weight=5.0
    )
    profile = service.create_risk_profile(mock_db, new_p)
    assert profile.profile_name == "Super Safe"
    assert profile.max_single_asset_weight == 5.0
    assert profile.is_active is False

def test_delete_protected_profile(mock_db):
    service = UserSettingsService()
    profiles = service.list_risk_profiles(mock_db)
    balanced = next(p for p in profiles if p.profile_type == "BALANCED")
    
    with pytest.raises(ValueError, match="Impossibile eliminare"):
        service.delete_risk_profile(mock_db, balanced.id)

def test_ui_preferences(mock_db):
    service = UserSettingsService()
    prefs = service.get_ui_preferences(mock_db)
    assert prefs.theme == "dark"
