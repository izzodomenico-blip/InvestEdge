from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import (
    AppSettingOut,
    RiskProfileOut,
    RiskProfileCreateIn,
    StrategyProfileOut,
    StrategyProfileCreateIn,
    NotificationPreferenceOut,
    UIPerferencesOut,
)


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class UserSettingsService:
    def get_app_settings(self, connection: sqlite3.Connection) -> list[AppSettingOut]:
        rows = connection.execute("SELECT * FROM app_settings ORDER BY category, setting_key").fetchall()
        return [
            AppSettingOut(
                id=r["id"],
                setting_key=r["setting_key"],
                setting_value_json=r["setting_value_json"],
                category=r["category"],
                description=r["description"],
                updated_at=r["updated_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def update_app_setting(self, connection: sqlite3.Connection, key: str, value_json: str, description: str | None = None) -> bool:
        connection.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value_json, category, description, updated_at, created_at)
            VALUES (?, ?, 'GENERAL', ?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value_json = excluded.setting_value_json,
                description = COALESCE(excluded.description, app_settings.description),
                updated_at = excluded.updated_at
            """,
            (key, value_json, description, _now(), _now())
        )
        return True

    def get_active_risk_profile(self, connection: sqlite3.Connection) -> RiskProfileOut:
        try:
            row = connection.execute("SELECT * FROM risk_profiles WHERE is_active = 1").fetchone()
            if not row:
                row = connection.execute("SELECT * FROM risk_profiles WHERE profile_type = 'BALANCED'").fetchone()
            
            if row:
                return self._row_to_risk_profile(row)
        except sqlite3.OperationalError:
            pass

        return RiskProfileOut(
            id=0, profile_name="Default Balanced", profile_type="BALANCED", is_active=True,
            max_single_asset_weight=15.0, max_asset_class_weight=40.0, max_crypto_weight=10.0,
            min_cash_reserve_percent=5.0, max_portfolio_drawdown_percent=15.0,
            min_data_quality_score=50.0, min_operational_confidence="MEDIUM",
            require_real_data_for_buy=False, allow_crypto=True, allow_single_stocks=True,
            allow_bonds=True, allow_etf=True, allow_ml_influence=True, allow_news_influence=True,
            technical_weight=50.0, ml_weight=20.0, news_weight=15.0, risk_weight=15.0,
            created_at=_now(), updated_at=_now()
        )

    def get_active_strategy_profile(self, connection: sqlite3.Connection) -> StrategyProfileOut:
        try:
            row = connection.execute("SELECT * FROM strategy_profiles WHERE is_active = 1").fetchone()
            if not row:
                row = connection.execute("SELECT * FROM strategy_profiles ORDER BY id ASC LIMIT 1").fetchone()
            
            if row:
                return self._row_to_strategy_profile(row)
        except sqlite3.OperationalError:
            pass

        return StrategyProfileOut(
            id=0, profile_name="Default Strategy", is_active=True,
            universe_level="CORE", max_positions=15, rebalance_frequency="WEEKLY",
            buy_threshold=70.0, sell_threshold=40.0, watch_threshold=55.0,
            min_score_for_buy=70.0, min_confidence_for_buy="MEDIUM",
            stop_loss_percent=10.0, take_profit_percent=25.0, fee_percent=0.1,
            cash_reserve_percent=5.0, use_ml=True, use_news=True, use_scenario_risk=True,
            use_optimizer=True, created_at=_now(), updated_at=_now()
        )

    def list_risk_profiles(self, connection: sqlite3.Connection) -> list[RiskProfileOut]:
        rows = connection.execute("SELECT * FROM risk_profiles ORDER BY id ASC").fetchall()
        return [self._row_to_risk_profile(r) for r in rows]

    def create_risk_profile(self, connection: sqlite3.Connection, p: RiskProfileCreateIn) -> RiskProfileOut:
        cursor = connection.execute(
            """
            INSERT INTO risk_profiles (
                profile_name, profile_type, is_active, max_single_asset_weight, max_asset_class_weight,
                max_crypto_weight, min_cash_reserve_percent, max_portfolio_drawdown_percent,
                min_data_quality_score, min_operational_confidence, require_real_data_for_buy,
                allow_crypto, allow_single_stocks, allow_bonds, allow_etf,
                allow_ml_influence, allow_news_influence, technical_weight, ml_weight, news_weight, risk_weight,
                created_at, updated_at
            ) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p.profile_name, p.profile_type, p.max_single_asset_weight, p.max_asset_class_weight,
                p.max_crypto_weight, p.min_cash_reserve_percent, p.max_portfolio_drawdown_percent,
                p.min_data_quality_score, p.min_operational_confidence, int(p.require_real_data_for_buy),
                int(p.allow_crypto), int(p.allow_single_stocks), int(p.allow_bonds), int(p.allow_etf),
                int(p.allow_ml_influence), int(p.allow_news_influence), p.technical_weight, p.ml_weight,
                p.news_weight, p.risk_weight, _now(), _now()
            )
        )
        return self.get_risk_profile(connection, cursor.lastrowid)

    def get_risk_profile(self, connection: sqlite3.Connection, profile_id: int) -> RiskProfileOut:
        row = connection.execute("SELECT * FROM risk_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row:
            raise ValueError(f"Profilo rischio {profile_id} non trovato.")
        return self._row_to_risk_profile(row)

    def update_risk_profile(self, connection: sqlite3.Connection, profile_id: int, p: RiskProfileCreateIn) -> RiskProfileOut:
        connection.execute(
            """
            UPDATE risk_profiles SET
                profile_name = ?, profile_type = ?, max_single_asset_weight = ?, max_asset_class_weight = ?,
                max_crypto_weight = ?, min_cash_reserve_percent = ?, max_portfolio_drawdown_percent = ?,
                min_data_quality_score = ?, min_operational_confidence = ?, require_real_data_for_buy = ?,
                allow_crypto = ?, allow_single_stocks = ?, allow_bonds = ?, allow_etf = ?,
                allow_ml_influence = ?, allow_news_influence = ?, technical_weight = ?, ml_weight = ?,
                news_weight = ?, risk_weight = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                p.profile_name, p.profile_type, p.max_single_asset_weight, p.max_asset_class_weight,
                p.max_crypto_weight, p.min_cash_reserve_percent, p.max_portfolio_drawdown_percent,
                p.min_data_quality_score, p.min_operational_confidence, int(p.require_real_data_for_buy),
                int(p.allow_crypto), int(p.allow_single_stocks), int(p.allow_bonds), int(p.allow_etf),
                int(p.allow_ml_influence), int(p.allow_news_influence), p.technical_weight, p.ml_weight,
                p.news_weight, p.risk_weight, _now(), profile_id
            )
        )
        return self.get_risk_profile(connection, profile_id)

    def activate_risk_profile(self, connection: sqlite3.Connection, profile_id: int) -> bool:
        connection.execute("UPDATE risk_profiles SET is_active = 0")
        connection.execute("UPDATE risk_profiles SET is_active = 1, updated_at = ? WHERE id = ?", (_now(), profile_id))
        return True

    def delete_risk_profile(self, connection: sqlite3.Connection, profile_id: int) -> bool:
        # Check if default or active
        row = connection.execute("SELECT is_active, profile_type FROM risk_profiles WHERE id = ?", (profile_id,)).fetchone()
        if not row: return False
        if row["is_active"]:
            raise ValueError("Impossibile eliminare un profilo attivo.")
        if row["profile_type"] in ["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]:
            raise ValueError("Impossibile eliminare un profilo di sistema predefinito.")
            
        connection.execute("DELETE FROM risk_profiles WHERE id = ?", (profile_id,))
        return True

    def get_active_strategy_profile(self, connection: sqlite3.Connection) -> StrategyProfileOut:
        row = connection.execute("SELECT * FROM strategy_profiles WHERE is_active = 1").fetchone()
        if not row:
            row = connection.execute("SELECT * FROM strategy_profiles ORDER BY id ASC LIMIT 1").fetchone()
            if not row:
                raise ValueError("Nessun profilo strategia trovato. Esegui il seed.")
        return self._row_to_strategy_profile(row)

    def list_strategy_profiles(self, connection: sqlite3.Connection) -> list[StrategyProfileOut]:
        rows = connection.execute("SELECT * FROM strategy_profiles ORDER BY id ASC").fetchall()
        return [self._row_to_strategy_profile(r) for r in rows]

    def activate_strategy_profile(self, connection: sqlite3.Connection, profile_id: int) -> bool:
        connection.execute("UPDATE strategy_profiles SET is_active = 0")
        connection.execute("UPDATE strategy_profiles SET is_active = 1, updated_at = ? WHERE id = ?", (_now(), profile_id))
        return True

    def list_notifications(self, connection: sqlite3.Connection) -> list[NotificationPreferenceOut]:
        rows = connection.execute("SELECT * FROM notification_preferences ORDER BY alert_type ASC").fetchall()
        return [
            NotificationPreferenceOut(
                id=r["id"],
                alert_type=r["alert_type"],
                enabled=bool(r["enabled"]),
                min_severity=r["min_severity"],
                show_in_dashboard=bool(r["show_in_dashboard"]),
                include_in_report=bool(r["include_in_report"]),
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def update_notification(self, connection: sqlite3.Connection, alert_type: str, enabled: bool, min_severity: str, show_in_dashboard: bool, include_in_report: bool) -> bool:
        connection.execute(
            """
            INSERT INTO notification_preferences (alert_type, enabled, min_severity, show_in_dashboard, include_in_report, updated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alert_type) DO UPDATE SET
                enabled = excluded.enabled,
                min_severity = excluded.min_severity,
                show_in_dashboard = excluded.show_in_dashboard,
                include_in_report = excluded.include_in_report,
                updated_at = excluded.updated_at
            """,
            (alert_type, int(enabled), min_severity, int(show_in_dashboard), int(include_in_report), _now(), _now())
        )
        return True

    def get_ui_preferences(self, connection: sqlite3.Connection) -> UIPerferencesOut:
        row = connection.execute("SELECT * FROM ui_preferences ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            # Create default if missing
            connection.execute(
                """
                INSERT INTO ui_preferences (theme, default_landing_page, compact_mode, show_advanced_metrics, default_universe_level, default_benchmark, default_currency, updated_at, created_at)
                VALUES ('dark', 'Dashboard', 0, 1, 'CORE', 'SPY', 'USD', ?, ?)
                """,
                (_now(), _now())
            )
            row = connection.execute("SELECT * FROM ui_preferences ORDER BY id DESC LIMIT 1").fetchone()
        
        return UIPerferencesOut(
            theme=row["theme"],
            default_landing_page=row["default_landing_page"],
            compact_mode=bool(row["compact_mode"]),
            show_advanced_metrics=bool(row["show_advanced_metrics"]),
            default_universe_level=row["default_universe_level"],
            default_benchmark=row["default_benchmark"],
            default_currency=row["default_currency"],
            updated_at=row["updated_at"],
        )

    def _row_to_risk_profile(self, r: sqlite3.Row) -> RiskProfileOut:
        return RiskProfileOut(
            id=r["id"],
            profile_name=r["profile_name"],
            profile_type=r["profile_type"],
            is_active=bool(r["is_active"]),
            max_single_asset_weight=r["max_single_asset_weight"],
            max_asset_class_weight=r["max_asset_class_weight"],
            max_crypto_weight=r["max_crypto_weight"],
            min_cash_reserve_percent=r["min_cash_reserve_percent"],
            max_portfolio_drawdown_percent=r["max_portfolio_drawdown_percent"],
            min_data_quality_score=r["min_data_quality_score"],
            min_operational_confidence=r["min_operational_confidence"],
            require_real_data_for_buy=bool(r["require_real_data_for_buy"]),
            allow_crypto=bool(r["allow_crypto"]),
            allow_single_stocks=bool(r["allow_single_stocks"]),
            allow_bonds=bool(r["allow_bonds"]),
            allow_etf=bool(r["allow_etf"]),
            allow_ml_influence=bool(r["allow_ml_influence"]),
            allow_news_influence=bool(r["allow_news_influence"]),
            technical_weight=r["technical_weight"],
            ml_weight=r["ml_weight"],
            news_weight=r["news_weight"],
            risk_weight=r["risk_weight"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def _row_to_strategy_profile(self, r: sqlite3.Row) -> StrategyProfileOut:
        return StrategyProfileOut(
            id=r["id"],
            profile_name=r["profile_name"],
            description=r["description"],
            is_active=bool(r["is_active"]),
            universe_level=r["universe_level"],
            max_positions=r["max_positions"],
            rebalance_frequency=r["rebalance_frequency"],
            buy_threshold=r["buy_threshold"],
            sell_threshold=r["sell_threshold"],
            watch_threshold=r["watch_threshold"],
            min_score_for_buy=r["min_score_for_buy"],
            min_confidence_for_buy=r["min_confidence_for_buy"],
            stop_loss_percent=r["stop_loss_percent"],
            take_profit_percent=r["take_profit_percent"],
            trailing_stop_percent=r["trailing_stop_percent"],
            fee_percent=r["fee_percent"],
            cash_reserve_percent=r["cash_reserve_percent"],
            use_ml=bool(r["use_ml"]),
            use_news=bool(r["use_news"]),
            use_scenario_risk=bool(r["use_scenario_risk"]),
            use_optimizer=bool(r["use_optimizer"]),
            config_json=r["config_json"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
