"""Handler dei job del laboratorio, registrati all'import (spec SP1 §9).

- `FEATURE_REFRESH`: `FeatureStore.refresh_asset` per ogni asset (tutti se `asset_ids` e nullo) nel `data_mode`
  richiesto o, se nullo, in quello preferito dell'asset (REAL se esiste, altrimenti DEMO); asset senza prezzi saltati.
- `FX_BACKFILL`: `FXService.backfill_history` per ogni valuta, su una connessione senza transazione aperta
  (il budget del trasporto la rifiuta); ricontrolla `ENABLE_REAL_DATA` prima di ogni chiamata.
- `BACKTEST`: run v1 persistito (`result_ref` = id del run); `COMPARE`: confronto non persistito (risultato inline).
  Avanzamento e `raise_if_cancelled` fra un passo e l'altro: un job annullato non scrive run ne tentativi.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from backend.app.config import get_settings
from backend.app.data_providers.base import ProviderError, RealDataDisabled
from backend.app.database import get_connection
from backend.app.lab.contracts import LabError
from backend.app.lab.feature_store import FeatureStore
from backend.app.lab.jobs import JobContext, JobOutcome, register_job_handler
from backend.app.lab.series import preferred_data_mode
from backend.app.models import BacktestCompareIn, BacktestRunIn
from backend.app.services.backtest_engine import BacktestEngine
from backend.app.services.fx_service import FXService

_REFRESH_COUNTS = ("inserted", "updated", "deleted", "unchanged")


def _real_data_disabled() -> LabError:
    return LabError("REAL_DATA_DISABLED", "Dati reali disattivati: abilita ENABLE_REAL_DATA.")


def refresh_features(context: JobContext, params: Mapping[str, Any]) -> JobOutcome:
    connection = get_connection()
    try:
        asset_ids = params["asset_ids"]
        if asset_ids is None:
            asset_ids = [int(row[0]) for row in connection.execute("SELECT id FROM assets ORDER BY id")]
        totals = dict.fromkeys(("assets", *_REFRESH_COUNTS), 0)
        store = FeatureStore()
        for index, asset_id in enumerate(asset_ids):
            context.raise_if_cancelled()
            data_mode = params["data_mode"] or preferred_data_mode(connection, asset_id)
            result = store.refresh_asset(connection, asset_id, data_mode, datetime.now(UTC)) if data_mode else None
            if result is not None:
                totals["assets"] += 1
                for name in _REFRESH_COUNTS:
                    totals[name] += getattr(result, name)
            context.set_progress((index + 1) / len(asset_ids))
        return JobOutcome(result=totals)
    finally:
        connection.close()


def backfill_fx(context: JobContext, params: Mapping[str, Any]) -> JobOutcome:
    start = date.fromisoformat(params["start_date"])
    currencies = list(params["currencies"])
    service = FXService()
    results: dict[str, dict[str, Any]] = {}
    connection = get_connection()
    try:
        for index, currency in enumerate(currencies):
            context.raise_if_cancelled()
            if not get_settings().enable_real_data:
                raise _real_data_disabled()
            try:
                result = service.backfill_history(connection, currency, start)
            except RealDataDisabled:
                raise _real_data_disabled() from None
            except ProviderError:
                raise LabError("FX_BACKFILL_FAILED", f"Backfill BCE non riuscito per {currency}: riprova piu tardi.") from None
            connection.commit()
            results[currency] = {
                "inserted": result.inserted,
                "existing": result.existing,
                "first_observed_at": result.first_observed_at,
                "last_observed_at": result.last_observed_at,
            }
            context.set_progress((index + 1) / len(currencies))
    finally:
        connection.close()
    return JobOutcome(result={"currencies": results})


def _checkpoint(context: JobContext) -> Callable[[float], None]:
    def step(progress: float) -> None:
        context.set_progress(progress)
        context.raise_if_cancelled()

    return step


def run_backtest(context: JobContext, params: Mapping[str, Any]) -> JobOutcome:
    config = BacktestRunIn.model_validate(dict(params))
    connection = get_connection()
    try:
        result = BacktestEngine().run_backtest(
            connection, config, job_id=context.job_id, now=datetime.now(UTC), checkpoint=_checkpoint(context)
        )
    finally:
        connection.close()
    return JobOutcome(result_ref=str(result.backtest_id), result={"backtest_id": result.backtest_id})


def compare_backtests(context: JobContext, params: Mapping[str, Any]) -> JobOutcome:
    payload = BacktestCompareIn.model_validate(dict(params))
    connection = get_connection()
    try:
        result = BacktestEngine().compare_strategies(
            connection, payload, job_id=context.job_id, now=datetime.now(UTC), checkpoint=_checkpoint(context)
        )
    finally:
        connection.close()
    return JobOutcome(result=result)


register_job_handler("FEATURE_REFRESH", refresh_features)
register_job_handler("FX_BACKFILL", backfill_fx)
register_job_handler("BACKTEST", run_backtest)
register_job_handler("COMPARE", compare_backtests)
