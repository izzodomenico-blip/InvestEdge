"""Smoke SP1 offline: fixture sintetiche, target nuovo, nessun database utente.

INVESTEDGE_DB_PATH deve indicare un file assoluto non esistente nello scratch.
I risultati sintetici marcati REAL esercitano il contratto, non validano strategie.
Gli obiettivi di tempo sono indicativi e non cambiano l'exit code.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from unittest.mock import patch


def target_path() -> Path:
    raw = os.environ.get("INVESTEDGE_DB_PATH")
    if not raw:
        raise ValueError("Impostare INVESTEDGE_DB_PATH su un nuovo file nello scratch.")
    path = Path(raw)
    if not path.is_absolute() or path.name.lower() == "investedge.db" or path.exists():
        raise ValueError("Il target deve essere assoluto, nuovo e diverso da investedge.db.")
    return path


@contextmanager
def blocked_network():
    attempts = {"count": 0}

    def deny(*args, **kwargs):
        attempts["count"] += 1
        raise RuntimeError("NETWORK_BLOCKED_IN_LAB_SMOKE")

    with (
        patch.object(socket, "create_connection", deny),
        patch.object(socket, "getaddrinfo", deny),
        patch.object(socket.socket, "connect", deny),
        patch.object(socket.socket, "connect_ex", deny),
    ):
        yield attempts


def _emit(phase: str, **values) -> None:
    print(json.dumps({"phase": phase, **values}, allow_nan=False), flush=True)


def main() -> int:
    try:
        path = target_path()
    except ValueError as exc:
        print(str(exc))
        return 2
    # Reserve exclusively before application imports: an existing target is never opened.
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb"):
            pass
    except FileExistsError:
        print("Target gia esistente: smoke rifiutato.")
        return 2
    safe_env = {
        "INVESTEDGE_DB_PATH": str(path),
        "ENABLE_REAL_DATA": "false",
        "ENABLE_ALERTS": "false",
        "ENABLE_TELEGRAM": "false",
        "LAB_JOBS_EXECUTOR": "inline",
    }
    with blocked_network() as attempts, patch.dict(os.environ, safe_env):
        import numpy as np
        import pandas as pd

        from backend.app.config import get_settings
        from backend.app.database import SCHEMA, migrate_db
        from backend.app.lab import handlers  # noqa: F401 -- production job registration
        from backend.app.lab.feature_store import FeatureStore
        from backend.app.lab.jobs import JobService
        from backend.app.models import EvidenceIn

        get_settings.cache_clear()
        count, bars_count = 50, 1500
        dates = pd.bdate_range("2019-01-01", periods=bars_count + 1)
        last_day = dates[bars_count - 1]
        now = datetime.combine(last_day.date(), datetime.min.time(), tzinfo=UTC)
        store = FeatureStore()
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            connection.executescript(SCHEMA)
            migrate_db(connection)
            extra_rows = []
            for asset_id in range(1, count + 1):
                connection.execute(
                    "INSERT INTO assets (id, symbol, name, asset_type, currency, risk_level) "
                    "VALUES (?, ?, ?, 'stock', 'EUR', 'medium')",
                    (asset_id, f"PERF{asset_id:02}", f"Synthetic smoke {asset_id}"),
                )
                rng = np.random.default_rng(16000 + asset_id)
                close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, bars_count + 1)))
                open_ = close * np.exp(rng.normal(0, 0.004, bars_count + 1))
                high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, bars_count + 1))
                low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, bars_count + 1))
                volume = rng.integers(100_000, 2_000_000, bars_count + 1)
                rows = [
                    (asset_id, day.strftime("%Y-%m-%d"), float(o), float(h), float(low_value), float(c), float(c), int(v))
                    for day, o, h, low_value, c, v in zip(dates, open_, high, low, close, volume, strict=True)
                ]
                connection.executemany(
                    "INSERT INTO price_history "
                    "(asset_id, date, open, high, low, close, adjusted_close, volume, source, is_real_data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'synthetic_perf', 1)",
                    rows[:-1],
                )
                extra_rows.append(rows[-1])
            connection.commit()
            _emit("seed", assets=count, bars_per_asset=bars_count, fixture="SYNTHETIC_REAL")
            start = perf_counter()
            full = [store.refresh_asset(connection, i, "REAL", now) for i in range(1, count + 1)]
            full_seconds = perf_counter() - start
            rows_by_tf = dict(connection.execute(
                "SELECT timeframe, COUNT(*) FROM features_daily GROUP BY timeframe ORDER BY timeframe"
            ))
            assert all(r is not None and r.inserted > 0 and r.updated == 0 for r in full)
            assert set(rows_by_tf) == {"D", "W", "M"}
            assert rows_by_tf["D"] == count * bars_count
            _emit("full_features", seconds=full_seconds, rows_by_timeframe=rows_by_tf)
            # One added bar of one asset, as in the Task6 incremental objective.
            connection.execute(
                "INSERT INTO price_history "
                "(asset_id, date, open, high, low, close, adjusted_close, volume, source, is_real_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'synthetic_perf', 1)", extra_rows[0]
            )
            connection.commit()
            later = datetime.combine(dates[-1].date(), datetime.min.time(), tzinfo=UTC)
            start = perf_counter()
            incremental = store.refresh_asset(connection, 1, "REAL", later)
            incremental_seconds = perf_counter() - start
            assert incremental is not None and incremental.inserted >= 1 and incremental.deleted == 0
            _emit("incremental_one_asset_one_bar", seconds=incremental_seconds, inserted=incremental.inserted)
            payload = EvidenceIn(
                signal_name="score", timeframe="D", horizons=[1, 5, 21],
                start_date=(last_day - pd.DateOffset(years=5)).strftime("%Y-%m-%d"),
                end_date=last_day.strftime("%Y-%m-%d"),
            )
        start = perf_counter()
        job = JobService("inline").enqueue("EVIDENCE", payload.model_dump())
        evidence_seconds = perf_counter() - start
        if job.status != "SUCCEEDED":
            raise RuntimeError(f"Smoke evidence job: {job.status}, {job.error_code}.")
        report_ids = job.result["report_ids"]
        assert len(report_ids) == 3
        with sqlite3.connect(path) as connection:
            verdicts = dict(connection.execute(
                "SELECT horizon, verdict FROM lab_evidence_reports ORDER BY horizon"
            ))
            modes = dict(connection.execute(
                "SELECT data_mode, COUNT(*) FROM features_daily GROUP BY data_mode"
            ))
            assert set(modes) == {"REAL"}
            trial_count = connection.execute("SELECT COUNT(*) FROM lab_trials").fetchone()[0]
        _emit("evidence_job", seconds=evidence_seconds, status=job.status, report_ids=report_ids,
              verdicts=verdicts, trials=trial_count, start_date=payload.start_date, end_date=payload.end_date)
        assert attempts["count"] == 0
        _emit("summary", assets=count, bars_per_asset=bars_count, fixture="SYNTHETIC_REAL",
              network_attempts=attempts["count"], full_seconds=full_seconds,
              incremental_seconds=incremental_seconds, evidence_seconds=evidence_seconds,
              indicative_targets_met={"full": full_seconds <= 60, "incremental": incremental_seconds <= 5,
                                      "evidence": evidence_seconds <= 120})
        get_settings.cache_clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
