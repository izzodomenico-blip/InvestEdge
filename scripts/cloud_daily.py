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
from backend.scripts.seed_database import seed_database


def main() -> None:
    """Esecuzione giornaliera in cloud (GitHub Actions).

    Il DB e effimero: si ricostruisce a ogni run. Quindi NON conosce il portafoglio
    reale dell'utente; l'alert si concentra su segnali di mercato e opportunita su
    dati reali. Passi: prepara DB e asset -> aggiorna dati reali -> invia alert.
    """
    settings = get_settings()

    # reset=False: niente portafoglio demo, per non dare falsi consigli "sul tuo portafoglio".
    summary = seed_database(reset=False)
    print(f"Seed: {summary['assets_inserted']} asset, {summary['price_rows_inserted']} righe prezzo.")

    if settings.enable_real_data:
        with db_session() as connection:
            result = MarketDataService().refresh_all_watchlist(connection, limit=None, force=False)
        updated = result["summary"]["updated"]
        fallback = result["summary"]["fallback"]
        print(f"Dati reali: {updated} aggiornati, {fallback} in fallback.")
    else:
        print("ENABLE_REAL_DATA=false: alert su dati simulati (dimostrativo).")

    try:
        with db_session() as connection:
            sent = send_today_alert(connection)
        print(f"Alert inviato: message_id={sent['message_id']} azioni={sent['actions_sent']}")
    except AlertNotConfigured as exc:
        print(f"Non configurato: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
