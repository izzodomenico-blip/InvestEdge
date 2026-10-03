"""Backfill storico dei cambi di riferimento BCE verso EUR.

Di default mostra solo l'anteprima (valute e intervallo) senza chiamate di rete.
Con `--apply` esegue una chiamata BCE per valuta (trasporto governato, budget `ecb`)
e inserisce in `fx_rates` solo le osservazioni mancanti, senza toccare quelle esistenti.
Richiede ENABLE_REAL_DATA=true: altrimenti esce con codice 2 senza chiamate.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.data_providers.base import ProviderError  # noqa: E402
from backend.app.data_providers.ecb import normalize_ecb_currency  # noqa: E402
from backend.app.database import db_session  # noqa: E402
from backend.app.services.fx_service import FXService  # noqa: E402

EXIT_REFUSED = 2


def _currency(value: str) -> str:
    try:
        return normalize_ecb_currency(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _start(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("--start deve essere una data AAAA-MM-GG.") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--currency", type=_currency, action="append", required=True, help="Valuta BCE verso EUR (ripetibile)."
    )
    parser.add_argument("--start", type=_start, required=True, help="Prima data dello storico (AAAA-MM-GG).")
    parser.add_argument("--apply", action="store_true", help="Esegue il backfill (default: solo anteprima).")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    service: FXService | None = None,
    now: datetime | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if not get_settings().enable_real_data:
        print("Dati reali disattivati: abilita ENABLE_REAL_DATA per il backfill dei cambi BCE.", file=sys.stderr)
        return EXIT_REFUSED
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    end = moment.date()
    if args.start > end:
        print("--start non puo' essere successiva alla data odierna (UTC).", file=sys.stderr)
        return EXIT_REFUSED
    currencies = list(dict.fromkeys(args.currency))
    if not args.apply:
        print(f"Anteprima (nessuna chiamata): valute {', '.join(currencies)}; intervallo {args.start} - {end} (UTC).")
        print("Una chiamata BCE per valuta; inserite solo le osservazioni mancanti. Per eseguire: --apply")
        return 0

    fx_service = service or FXService()
    with db_session() as connection:
        for currency in currencies:
            try:
                result = fx_service.backfill_history(connection, currency, args.start, now=moment)
            except ProviderError as exc:
                print(f"{currency}: backfill non riuscito ({exc}).", file=sys.stderr)
                return 1
            period = (
                f"dal {result.first_observed_at} al {result.last_observed_at}"
                if result.first_observed_at
                else "nessuna osservazione"
            )
            print(f"{result.currency}: {result.inserted} inserite, {result.existing} gia' presenti, {period}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
