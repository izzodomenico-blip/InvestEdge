from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import SchedulerRunIn, SchedulerRunOut


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class SchedulerService:
    def run_manual_cycle(self, connection: sqlite3.Connection, config: SchedulerRunIn) -> SchedulerRunOut:
        start_time = time.time()
        started_at = _now()
        
        summary = {}
        errors = []
        status = "SUCCESS"

        # Import needed services inside evaluation to avoid circular dependencies
        from backend.app.services.market_data_service import MarketDataService
        from backend.app.services.technical_analysis import TechnicalAnalysisService
        from backend.app.services.operational_ranking_service import OperationalRankingService
        from backend.app.services.data_quality_service import DataQualityService
        from backend.app.services.alert_service import AlertService
        from backend.app.services.report_service import ReportService

        md_service = MarketDataService()
        ta_service = TechnicalAnalysisService()
        ranking_service = OperationalRankingService()
        dq_service = DataQualityService()
        alert_service = AlertService()
        report_service = ReportService()

        try:
            # 1. Data Refresh
            if config.run_type in ["FULL_MANUAL", "DATA_REFRESH"]:
                limit = config.limit or 10
                refresh_results = md_service.refresh_all_data(connection, limit=limit, force=config.force)
                summary["data_refresh"] = refresh_results.summary

            # 2. Signals Recalculation (AST-only by default in TA service or via explicit refresh)
            # ranking_service implicitly uses the latest technical data.

            # 3. Quality Audit
            if config.run_type in ["FULL_MANUAL", "QUALITY"]:
                quality_list = dq_service.list_all_quality(connection)
                summary["quality_audit"] = {
                    "total": len(quality_list),
                    "valid": len([q for q in quality_list if q.is_valid]),
                    "excluded": len([q for q in quality_list if not q.is_valid])
                }

            # 4. Operational Ranking
            if config.run_type in ["FULL_MANUAL", "RANKING"]:
                ranking = ranking_service.get_operational_ranking(connection)
                summary["operational_ranking"] = {
                    "buy": len(ranking.buy_candidates),
                    "watch": len(ranking.watch_candidates),
                    "reduce": len(ranking.reduce_candidates),
                    "excluded": len(ranking.excluded_candidates)
                }

            # 5. Alert Evaluation
            if config.run_type in ["FULL_MANUAL", "ALERTS"]:
                alert_service.evaluate_rules(connection)
                alert_sum = alert_service.get_alert_summary(connection)
                summary["alerts"] = {"open_count": alert_sum.open_count}

            # 6. Report Generation
            if config.generate_report or config.run_type == "REPORT":
                report = report_service.generate_operational_report(connection, report_type="MANUAL")
                summary["report_id"] = report.id

        except Exception as exc:
            status = "ERROR"
            errors.append(str(exc))

        duration = time.time() - start_time
        
        cursor = connection.execute(
            """
            INSERT INTO scheduler_runs (
                run_type, status, started_at, finished_at, duration_seconds, 
                summary_json, errors_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config.run_type, status, started_at, _now(), duration,
                json.dumps(summary), json.dumps(errors), _now()
            )
        )
        
        return SchedulerRunOut(
            id=cursor.lastrowid,
            run_type=config.run_type,
            status=status,
            started_at=started_at,
            finished_at=_now(),
            duration_seconds=duration,
            summary=summary,
            errors=errors,
            created_at=_now()
        )

    def list_runs(self, connection: sqlite3.Connection, limit: int = 50) -> list[SchedulerRunOut]:
        rows = connection.execute(
            "SELECT * FROM scheduler_runs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [
            SchedulerRunOut(
                id=r["id"],
                run_type=r["run_type"],
                status=r["status"],
                started_at=r["started_at"],
                finished_at=r["finished_at"],
                duration_seconds=r["duration_seconds"],
                summary=json.loads(r["summary_json"]) if r["summary_json"] else {},
                errors=json.loads(r["errors_json"]) if r["errors_json"] else [],
                created_at=r["created_at"],
            )
            for r in rows
        ]
