from __future__ import annotations

import sqlite3
from typing import Any

import httpx

from backend.app.config import get_settings
from backend.app.services.action_board_service import get_action_board

_TELEGRAM_API = "https://api.telegram.org"
_TYPE_EMOJI = {
    "BUY": "\U0001F7E2",      # 🟢
    "REDUCE": "\U0001F7E1",   # 🟡
    "SELL": "\U0001F534",     # 🔴
    "RISK": "⚠️",   # ⚠️
    "WATCH": "\U0001F441️",  # 👁️
    "OK": "✅",           # ✅
}


class AlertNotConfigured(RuntimeError):
    pass


def alert_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.enable_alerts,
        "configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "channel": "telegram",
    }


def _send_telegram(text: str) -> dict[str, Any]:
    settings = get_settings()
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        raise AlertNotConfigured(
            "Telegram non configurato. Imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID in backend/.env."
        )
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{_TELEGRAM_API}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Invio Telegram fallito: {exc}") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram ha rifiutato il messaggio: {payload.get('description', 'errore sconosciuto')}")
    return {"ok": True, "message_id": payload["result"]["message_id"]}


def send_test_message() -> dict[str, Any]:
    return _send_telegram(
        "✅ <b>InvestEdge</b>\nNotifiche attive. Riceverai qui il riepilogo <b>Cosa fare oggi</b>."
    )


def _format_board(board: dict[str, Any]) -> str:
    lines: list[str] = ["\U0001F4CA <b>InvestEdge - Cosa fare oggi</b>", ""]
    if board["data_mode"] == "SEED":
        lines.append("⚠️ <i>Dati simulati: indicazioni dimostrative.</i>")
        lines.append("")
    lines.append(board["headline"])
    lines.append("")

    actions = board["actions"]
    shown = [a for a in actions if a["type"] != "OK"][:12]
    if not shown:
        lines.append("✅ Nessuna azione urgente oggi.")
    else:
        for action in shown:
            emoji = _TYPE_EMOJI.get(action["type"], "•")
            symbol = f" <b>{action['symbol']}</b>" if action.get("symbol") else ""
            lines.append(f"{emoji}{symbol} {action['title']}")
            lines.append(f"   <i>{action['reason']}</i>")
    lines.append("")
    lines.append("<i>Supporto decisionale, non consigli finanziari. Gli ordini li esegui tu.</i>")
    return "\n".join(lines)


def send_today_alert(connection: sqlite3.Connection) -> dict[str, Any]:
    board = get_action_board(connection)
    result = _send_telegram(_format_board(board))
    return {
        "ok": result["ok"],
        "message_id": result["message_id"],
        "actions_sent": len([a for a in board["actions"] if a["type"] != "OK"]),
        "headline": board["headline"],
    }
