"""Refresh manuale dei dati reali tramite il planner prioritario e limitato.

Esegue al massimo `--limit` unita (1..25): posizioni, candidati da segnali e watchlist
attiva, mai l'intero catalogo. Di default e una simulazione (`--dry-run`): mostra cosa
verrebbe aggiornato senza scrivere nulla. Usa `--execute` per eseguire davvero.
Quote, cooldown e cache sono gestiti dal budget dei provider: nessuna pausa fissa.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import db_session  # noqa: E402
from backend.app.services.market_data_service import MarketDataService  # noqa: E402
from backend.app.services.refresh_planner_service import (  # noqa: E402
    MAX_REFRESH_BATCH,
    RefreshPlannerService,
)


def _limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--limit deve essere un intero.") from exc
    if not 1 <= limit <= MAX_REFRESH_BATCH:
        raise argparse.ArgumentTypeError(f"--limit deve essere compreso fra 1 e {MAX_REFRESH_BATCH}.")
    return limit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=_limit, required=True, help="Unita da aggiornare (1..25).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="execute", action="store_false", help="Solo anteprima (default).")
    mode.add_argument("--execute", dest="execute", action="store_true", help="Esegue davvero il batch.")
    parser.add_argument("--force", action="store_true", help="Ignora freschezza e cache (resta soggetto a budget).")
    parser.set_defaults(execute=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = MarketDataService()
    planner = RefreshPlannerService(service)
    with db_session() as connection:
        if not args.execute:
            preview = planner.preview_watchlist(connection, args.limit)
            print(f"Anteprima (nessuna scrittura): {len(preview)} unita.")
            for item in preview:
                print(f"  {item['priority']:>2} {item['reason']:<18} {item['symbol'] or '-':<8} listing {item['listing_id']}")
            print("Per eseguire: --execute")
            return 0
        result = service.refresh_all_watchlist(connection, limit=args.limit, force=args.force)
    summary = result["summary"]
    print(
        f"Eseguite {summary['requested']} unita: {summary['updated']} aggiornate, "
        f"{summary['fallback']} in fallback o rinviate."
    )
    for item in result["results"]:
        print(f"  {item['symbol']:<10} {'OK' if not item['used_fallback'] else 'FALLBACK'}  {item['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
