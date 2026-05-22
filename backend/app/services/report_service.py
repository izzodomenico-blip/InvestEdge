from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from backend.app.models.schemas import OperationalReportOut, OperationalReportSummary


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


class ReportService:
    def generate_operational_report(self, connection: sqlite3.Connection, report_type: str = "MANUAL", portfolio_id: int | None = None) -> OperationalReportOut:
        # Import needed services inside evaluation to avoid circular dependencies
        from backend.app.services.system_health_service import SystemHealthService
        from backend.app.services.data_quality_service import DataQualityService
        from backend.app.services.operational_ranking_service import OperationalRankingService
        from backend.app.services.portfolio_engine import PortfolioEngine
        from backend.app.services.alert_service import AlertService
        from backend.app.services.multi_portfolio_service import MultiPortfolioService

        health_service = SystemHealthService()
        dq_service = DataQualityService()
        ranking_service = OperationalRankingService()
        portfolio_engine = PortfolioEngine()
        alert_service = AlertService()
        multi_portfolio_service = MultiPortfolioService()

        # 1. Collect data
        health = health_service.get_health(connection)
        quality = dq_service.list_all_quality(connection)
        ranking = ranking_service.get_operational_ranking(connection)
        
        if portfolio_id:
            portfolio = portfolio_engine.refresh_portfolio(connection, portfolio_id=portfolio_id, create_snapshot=False)
            alerts = alert_service.get_alert_summary(connection, portfolio_id=portfolio_id)
            p_data = multi_portfolio_service.get_portfolio(connection, portfolio_id)
            portfolio_name = p_data.portfolio_name if p_data else f"ID:{portfolio_id}"
        else:
            # Consolidated report
            summary_cons = multi_portfolio_service.get_consolidated_summary(connection)
            portfolio = summary_cons # Partially compatible
            alerts = alert_service.get_alert_summary(connection)
            portfolio_name = "Consolidato"

        dq_avg = sum(q.score for q in quality) / (len(quality) or 1)

        summary = OperationalReportSummary(
            system_health=health.model_dump(),
            data_quality_avg=round(dq_avg, 1),
            buy_candidates_count=len(ranking.buy_candidates),
            watch_candidates_count=len(ranking.watch_candidates),
            reduce_candidates_count=len(ranking.reduce_candidates),
            portfolio_value=portfolio.total_value if portfolio_id else summary_cons.total_value,
            risk_warnings_count=len(portfolio.risk_warnings) if portfolio_id else 0,
            open_alerts_count=alerts.open_count,
        )

        title = f"Report Operativo {report_type} ({portfolio_name}) - {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        tax_note: dict[str, Any] | None = None
        try:
            from backend.app.services.tax_service import TaxService

            tax_svc = TaxService()
            tax_svc.ensure_default_settings(connection)
            year = datetime.now().year
            if portfolio_id:
                tax_summary = tax_svc.calculate_tax_summary(connection, portfolio_id=portfolio_id, tax_year=year)
                tax_note = tax_summary.model_dump()
            else:
                tax_summary = tax_svc.calculate_multi_portfolio_tax_summary(connection, tax_year=year)
                tax_note = tax_summary.model_dump()
        except Exception:
            tax_note = None

        markdown = self._build_markdown(title, summary, ranking, portfolio, portfolio_id, tax_note)

        cursor = connection.execute(
            """
            INSERT INTO operational_reports (
                portfolio_id, report_type, report_date, title, summary_json, markdown_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id, report_type, _now(), title, summary.model_dump_json(), markdown, _now()
            )
        )

        return OperationalReportOut(
            id=cursor.lastrowid,
            report_type=report_type,
            report_date=_now(),
            title=title,
            summary=summary,
            markdown_text=markdown,
            created_at=_now()
        )

    def get_latest_report(self, connection: sqlite3.Connection) -> OperationalReportOut | None:
        row = connection.execute(
            "SELECT * FROM operational_reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return self._row_to_report(row)

    def list_reports(self, connection: sqlite3.Connection, portfolio_id: int | None = None, limit: int = 50) -> list[OperationalReportOut]:
        query = "SELECT * FROM operational_reports"
        params = []
        if portfolio_id is not None:
            query += " WHERE portfolio_id = ?"
            params.append(portfolio_id)
        else:
            query += " WHERE portfolio_id IS NULL"
            
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = connection.execute(query, params).fetchall()
        return [self._row_to_report(row) for row in rows]

    def get_report(self, connection: sqlite3.Connection, report_id: int) -> OperationalReportOut:
        row = connection.execute(
            "SELECT * FROM operational_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Report {report_id} not found")
        return self._row_to_report(row)

    def _build_markdown(
        self,
        title: str,
        summary: OperationalReportSummary,
        ranking: Any,
        portfolio: Any,
        portfolio_id: int | None,
        tax_note: dict[str, Any] | None = None,
    ) -> str:
        md = f"# {title}\n\n"
        md += "## Stato Sistema\n"
        md += f"- **Health**: {summary.system_health['status'].upper()}\n"
        md += f"- **Qualità Dati Media**: {summary.data_quality_avg}%\n"
        md += f"- **Alert Aperti**: {summary.open_alerts_count}\n\n"

        md += "## Candidati Operativi\n"
        md += f"- **BUY**: {summary.buy_candidates_count}\n"
        if ranking.buy_candidates:
            md += "  - " + ", ".join([s.symbol for s in ranking.buy_candidates[:5]]) + "\n"
        md += f"- **WATCH**: {summary.watch_candidates_count}\n"
        md += f"- **REDUCE/SELL**: {summary.reduce_candidates_count}\n\n"

        md += "## Portafoglio\n"
        if portfolio_id:
            md += f"- **Valore Totale**: {portfolio.total_value:,.2f}\n"
            md += f"- **Cash**: {portfolio.cash:,.2f}\n"
            md += f"- **Warning Rischio**: {summary.risk_warnings_count}\n"
            if hasattr(portfolio, 'risk_warnings'):
                for w in portfolio.risk_warnings:
                    md += f"  - [{w.level.upper()}] {w.message}\n"
        else:
            md += f"- **Valore Consolidato**: {portfolio.total_value:,.2f}\n"
            md += f"- **Cash Totale**: {portfolio.total_cash:,.2f}\n"
            md += f"- **Portafogli inclusi**: {portfolio.portfolios_count}\n"

        if tax_note:
            md += "\n## Riepilogo Fiscale (Simulato)\n"
            md += f"- **Anno**: {tax_note.get('tax_year', datetime.now().year)}\n"
            md += f"- **P/L realizzato netto**: {tax_note.get('net_realized_pnl', 0):,.2f}\n"
            md += f"- **Imposta teorica stimata**: {tax_note.get('estimated_tax_due', 0):,.2f}\n"
            md += f"- **P/L non realizzato**: {tax_note.get('unrealized_pnl', 0):,.2f}\n"
            md += "_Simulazione indicativa, non sostituisce consulenza fiscale._\n"

        return md

    def _row_to_report(self, row: sqlite3.Row) -> OperationalReportOut:
        return OperationalReportOut(
            id=row["id"],
            report_type=row["report_type"],
            report_date=row["report_date"],
            title=row["title"],
            summary=OperationalReportSummary(**json.loads(row["summary_json"])),
            markdown_text=row["markdown_text"],
            created_at=row["created_at"]
        )
