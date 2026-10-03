from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.services.common import now_utc
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.portfolio_engine import PortfolioEngine

portfolio_engine = PortfolioEngine()
market_data_service = MarketDataService()

_PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_MAX_BUY_CANDIDATES = 6


def _buy_priority(signal: str | None, score: float | None) -> str:
    if signal == "STRONG_BUY" or (score is not None and score >= 75):
        return "HIGH"
    return "MEDIUM"


def _signal_data_modes(connection: sqlite3.Connection) -> dict[str, str | None]:
    """`data_mode` dell'ultimo segnale per simbolo (serie dello score: REAL o DEMO)."""
    rows = connection.execute(
        """
        SELECT a.symbol, sig.data_mode
        FROM assets a
        JOIN signals sig ON sig.id = (
            SELECT s.id FROM signals s
            WHERE s.asset_id = a.id
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT 1
        )
        """
    ).fetchall()
    return {str(row[0]): row[1] for row in rows}


def get_action_board(connection: sqlite3.Connection) -> dict[str, Any]:
    """Cruscotto 'Cosa fare oggi': azioni prioritizzate in linguaggio semplice.

    Combina segnali tecnici e regole di portafoglio per dire cosa valutare,
    cosa ridurre/vendere e quali rischi tenere d'occhio. Non esegue ordini.
    """
    recommendations = portfolio_engine.recommendations(connection)
    summary = portfolio_engine.refresh_portfolio(connection, create_snapshot=False)
    data_status = market_data_service.get_global_status(connection)
    signal_modes = _signal_data_modes(connection)

    actions: list[dict[str, Any]] = []
    buy_candidates: list[dict[str, Any]] = []

    for rec in recommendations:
        held = rec.portfolio_weight > 0
        signal = rec.technical_signal
        score = rec.technical_score

        if held:
            if signal == "SELL" or rec.final_recommendation == "SELL":
                actions.append(
                    {
                        "type": "SELL",
                        "priority": "HIGH",
                        "symbol": rec.symbol,
                        "title": f"Valuta la vendita di {rec.symbol}",
                        "reason": f"Segnale tecnico negativo (SELL). Pesa {rec.portfolio_weight:.0f}% del portafoglio.",
                        "signal": signal,
                        "score": score,
                        "weight_percent": rec.portfolio_weight,
                        "data_mode": signal_modes.get(rec.symbol),
                    }
                )
            elif signal == "REDUCE" or rec.final_recommendation == "REDUCE":
                actions.append(
                    {
                        "type": "REDUCE",
                        "priority": "MEDIUM",
                        "symbol": rec.symbol,
                        "title": f"Valuta di alleggerire {rec.symbol}",
                        "reason": f"Segnale in indebolimento. Pesa {rec.portfolio_weight:.0f}% del portafoglio.",
                        "signal": signal,
                        "score": score,
                        "weight_percent": rec.portfolio_weight,
                        "data_mode": signal_modes.get(rec.symbol),
                    }
                )
        else:
            if rec.final_recommendation == "BUY_ALLOWED" and signal in {"STRONG_BUY", "BUY"}:
                buy_candidates.append(
                    {
                        "type": "BUY",
                        "priority": _buy_priority(signal, score),
                        "symbol": rec.symbol,
                        "title": f"Valuta l'acquisto di {rec.symbol}",
                        "reason": f"Segnale {signal} con score {score:.0f}/100. Non presente nel tuo portafoglio.",
                        "signal": signal,
                        "score": score,
                        "weight_percent": 0.0,
                        "data_mode": signal_modes.get(rec.symbol),
                    }
                )

    buy_candidates.sort(key=lambda item: item["score"] or 0, reverse=True)
    actions.extend(buy_candidates[:_MAX_BUY_CANDIDATES])

    for warning in summary.risk_warnings:
        actions.append(
            {
                "type": "RISK",
                "priority": "HIGH" if warning.level == "WARNING" else "LOW",
                "symbol": warning.symbol,
                "title": "Attenzione al rischio di portafoglio",
                "reason": warning.message,
                "signal": None,
                "score": None,
                "weight_percent": None,
            }
        )

    actions.sort(key=lambda item: (_PRIORITY_RANK.get(item["priority"], 1), -(item["score"] or 0)))

    counts = {
        "buy": sum(1 for item in actions if item["type"] == "BUY"),
        "reduce": sum(1 for item in actions if item["type"] == "REDUCE"),
        "sell": sum(1 for item in actions if item["type"] == "SELL"),
        "risk": sum(1 for item in actions if item["type"] == "RISK"),
    }

    if not actions:
        actions.append(
            {
                "type": "OK",
                "priority": "LOW",
                "symbol": None,
                "title": "Nessuna azione urgente oggi",
                "reason": "Il portafoglio e i segnali non richiedono interventi. Continua a monitorare.",
                "signal": None,
                "score": None,
                "weight_percent": None,
            }
        )
        headline = "Tutto sotto controllo: nessuna azione urgente oggi."
    else:
        parts: list[str] = []
        if counts["sell"]:
            parts.append(f"{counts['sell']} da valutare in vendita")
        if counts["reduce"]:
            parts.append(f"{counts['reduce']} da alleggerire")
        if counts["buy"]:
            parts.append(f"{counts['buy']} possibili acquisti")
        if counts["risk"]:
            parts.append(f"{counts['risk']} avvisi di rischio")
        headline = "Oggi: " + ", ".join(parts) + "."

    return {
        "generated_at": now_utc(),
        "data_mode": data_status["data_mode"],
        "enable_real_data": data_status["enable_real_data"],
        "headline": headline,
        "counts": counts,
        "actions": actions,
    }
