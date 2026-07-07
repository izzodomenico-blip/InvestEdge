from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import get_settings
from backend.app.database import db_session
from backend.app.services.alert_service import AlertNotConfigured, send_today_alert
from backend.app.services.market_data_service import MarketDataService


def _refresh_prices() -> None:
    """Aggiorna i prezzi reali prima dell'alert, cosi' segnali e P&L sono
    sull'ultima chiusura disponibile e non su dati fermi al refresh precedente."""
    settings = get_settings()
    if not settings.enable_real_data:
        print("ENABLE_REAL_DATA=false: nessun refresh, alert sui dati esistenti.")
        return
    try:
        with db_session() as connection:
            result = MarketDataService().refresh_all_watchlist(connection, limit=None, force=False)
        summary = result["summary"]
        print(f"Prezzi aggiornati: {summary['updated']} ok, {summary['fallback']} in fallback.")
    except Exception as exc:  # noqa: BLE001 - se il refresh fallisce, invio comunque sull'ultimo dato
        print(f"Refresh prezzi fallito (invio sull'ultimo dato): {exc}")


def main() -> None:
    settings = get_settings()
    if not settings.enable_alerts:
        print("Alert disabilitati (ENABLE_ALERTS=false). Niente da inviare.")
        return
    _refresh_prices()
    try:
        with db_session() as connection:
            result = send_today_alert(connection)
        print(f"Alert inviato: message_id={result['message_id']} azioni={result['actions_sent']}")
    except AlertNotConfigured as exc:
        print(f"Non configurato: {exc}")
    except Exception as exc:  # noqa: BLE001 - script schedulato: logga ed esce senza crash
        print(f"Errore invio alert: {exc}")


if __name__ == "__main__":
    main()
