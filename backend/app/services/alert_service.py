from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import AlertOut, AlertSummaryOut, AlertRuleOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class AlertService:
    def create_alert(
        self,
        connection: sqlite3.Connection,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        symbol: str | None = None,
        source_module: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        now = _now()
        cursor = connection.execute(
            """
            INSERT INTO alerts (
                alert_type, severity, symbol, title, message, status, 
                source_module, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
            """,
            (
                alert_type, severity, symbol, title, message, 
                source_module, json.dumps(payload) if payload else None, now, now
            )
        )
        return cursor.lastrowid

    def get_open_alerts(
        self, 
        connection: sqlite3.Connection, 
        severity: str | None = None, 
        symbol: str | None = None
    ) -> list[AlertOut]:
        query = "SELECT * FROM alerts WHERE status = 'OPEN'"
        params = []
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if symbol:
            query += " AND UPPER(symbol) = UPPER(?)"
            params.append(symbol)
        
        query += " ORDER BY created_at DESC"
        rows = connection.execute(query, params).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def acknowledge_alert(self, connection: sqlite3.Connection, alert_id: int) -> bool:
        now = _now()
        connection.execute(
            "UPDATE alerts SET status = 'ACKNOWLEDGED', updated_at = ?, acknowledged_at = ? WHERE id = ?",
            (now, now, alert_id)
        )
        return True

    def close_alert(self, connection: sqlite3.Connection, alert_id: int) -> bool:
        now = _now()
        connection.execute(
            "UPDATE alerts SET status = 'CLOSED', updated_at = ?, closed_at = ? WHERE id = ?",
            (now, now, alert_id)
        )
        return True

    def get_alert_summary(self, connection: sqlite3.Connection) -> AlertSummaryOut:
        open_alerts = self.get_open_alerts(connection)
        
        summary = {
            "open_count": len(open_alerts),
            "critical_count": len([a for a in open_alerts if a.severity == "CRITICAL"]),
            "warning_count": len([a for a in open_alerts if a.severity == "WARNING"]),
            "info_count": len([a for a in open_alerts if a.severity == "INFO"]),
            "latest_alerts": open_alerts[:5],
            "by_type": {}
        }
        
        for a in open_alerts:
            summary["by_type"][a.alert_type] = summary["by_type"].get(a.alert_type, 0) + 1
            
        return AlertSummaryOut(**summary)

    def list_rules(self, connection: sqlite3.Connection) -> list[AlertRuleOut]:
        rows = connection.execute("SELECT * FROM alert_rules ORDER BY id ASC").fetchall()
        return [
            AlertRuleOut(
                id=row["id"],
                rule_name=row["rule_name"],
                alert_type=row["alert_type"],
                enabled=bool(row["enabled"]),
                severity=row["severity"],
                universe_level=row["universe_level"],
                symbol=row["symbol"],
                threshold_value=row["threshold_value"],
                config_json=row["config_json"],
            )
            for row in rows
        ]

    def toggle_rule(self, connection: sqlite3.Connection, rule_id: int, enabled: bool) -> bool:
        connection.execute(
            "UPDATE alert_rules SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, _now(), rule_id)
        )
        return True

    def evaluate_rules(self, connection: sqlite3.Connection):
        rules = self.list_rules(connection)
        # Import needed services inside evaluation to avoid circular dependencies
        from backend.app.services.data_quality_service import DataQualityService
        from backend.app.services.system_health_service import SystemHealthService
        from backend.app.services.portfolio_engine import PortfolioEngine
        from backend.app.services.signal_validation_service import SignalValidationService

        dq_service = DataQualityService()
        health_service = SystemHealthService()
        portfolio_engine = PortfolioEngine()
        val_service = SignalValidationService()

        for rule in [r for r in rules if r.enabled]:
            # 1. DATA_QUALITY_BAD
            if rule.alert_type == "DATA_QUALITY_BAD":
                quality_list = dq_service.list_all_quality(connection)
                for q in quality_list:
                    if q.score < (rule.threshold_value or 50.0):
                        # Avoid duplicate alerts if one is already open for this symbol and type
                        existing = connection.execute(
                            "SELECT id FROM alerts WHERE symbol = ? AND alert_type = ? AND status = 'OPEN'",
                            (q.symbol, rule.alert_type)
                        ).fetchone()
                        if not existing:
                            self.create_alert(
                                connection, rule.alert_type, rule.severity,
                                f"Bassa qualità dati: {q.symbol}",
                                f"Il data quality score di {q.symbol} è {q.score:.1f}% (Grade {q.grade}).",
                                symbol=q.symbol, source_module="DataQuality"
                            )

            # 2. SIGNAL_CHANGED
            if rule.alert_type == "SIGNAL_CHANGED":
                # This would ideally compare with previous state, for now we detect strong signals
                signals = val_service.validate_all_signals(connection)
                for s in signals:
                    if s.action_suggested in ["BUY", "REDUCE", "EXCLUDE"]:
                        existing = connection.execute(
                            "SELECT id, message FROM alerts WHERE symbol = ? AND alert_type = ? AND status = 'OPEN' ORDER BY created_at DESC LIMIT 1",
                            (s.symbol, rule.alert_type)
                        ).fetchone()
                        
                        msg = f"Segnale operativo: {s.action_suggested}. Rationale: {s.reason}"
                        if not existing or existing["message"] != msg:
                            # Close previous if exists? Or just append. 
                            # Let's just create new if message changed.
                            self.create_alert(
                                connection, rule.alert_type, rule.severity,
                                f"Cambio segnale {s.symbol}", msg,
                                symbol=s.symbol, source_module="SignalValidation"
                            )

            # 3. PORTFOLIO_CONCENTRATION
            if rule.alert_type == "PORTFOLIO_CONCENTRATION":
                portfolio = portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
                for pos in portfolio.positions:
                    if pos.weight_percent > (rule.threshold_value or 20.0):
                        existing = connection.execute(
                            "SELECT id FROM alerts WHERE symbol = ? AND alert_type = ? AND status = 'OPEN'",
                            (pos.symbol, rule.alert_type)
                        ).fetchone()
                        if not existing:
                            self.create_alert(
                                connection, rule.alert_type, rule.severity,
                                f"Concentrazione elevata: {pos.symbol}",
                                f"L'asset {pos.symbol} pesa il {pos.weight_percent:.1f}% del portafoglio.",
                                symbol=pos.symbol, source_module="RiskEngine"
                            )

    def _row_to_alert(self, row: sqlite3.Row) -> AlertOut:
        return AlertOut(
            id=row["id"],
            alert_type=row["alert_type"],
            severity=row["severity"],
            symbol=row["symbol"],
            title=row["title"],
            message=row["message"],
            status=row["status"],
            source_module=row["source_module"],
            payload_json=row["payload_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            acknowledged_at=row["acknowledged_at"],
            closed_at=row["closed_at"],
        )
