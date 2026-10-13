from __future__ import annotations

import sqlite3

import pytest
from intraday_fixtures import insert
from intraday_research_fixtures import (
    NS,
    RESEARCH_TABLES,
    manifest,
    seed_registered_evidence,
    seed_research_inputs,
)

from backend.app.intraday_research.contracts import ResearchError


def test_schema_contains_all_research_tables_without_changing_daily_contracts(research_connection):
    found = {r[0] for r in research_connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(RESEARCH_TABLES) <= found
    assert research_connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "REPLACE"])
@pytest.mark.parametrize("table", RESEARCH_TABLES)
def test_direct_sql_cannot_mutate_registered_evidence(research_connection, operation, table):
    from backend.app.intraday_research.registry import Registry
    ref = seed_registered_evidence(research_connection)
    saved = manifest()
    registry = Registry(research_connection)
    row = dict(research_connection.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    with pytest.raises(sqlite3.IntegrityError):
        if operation == "UPDATE":
            research_connection.execute(f"UPDATE {table} SET id=id WHERE id=?", (row["id"],))
        elif operation == "DELETE":
            research_connection.execute(f"DELETE FROM {table} WHERE id=?", (row["id"],))
        else:
            insert(research_connection, table, row, replace=True)
    assert registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)["experiment_hash"] == saved.experiment_hash


def test_started_is_impossible_until_entire_batch_is_registered(research_connection):
    from backend.app.intraday_research.registry import Registry
    seed_research_inputs(research_connection)
    saved = manifest()
    registry = Registry(research_connection)
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    # Reconstruct an incomplete, synthetic batch only to test the SQL guard.
    research_connection.execute("DROP TRIGGER trg_intraday_research_trial_events_no_delete")
    research_connection.execute("DELETE FROM intraday_research_trial_events WHERE id=(SELECT MAX(id) FROM intraday_research_trial_events)")
    research_connection.commit()
    trial = research_connection.execute("SELECT id FROM intraday_research_trials WHERE manifest_id=? ORDER BY ordinal", (ref["manifest_id"],)).fetchone()[0]
    with pytest.raises(ResearchError):
        registry.append_trial_event(trial, namespace=saved.namespace, state="STARTED",
            reason_code="EXECUTION_STARTED", now_ns=NS + 4_000_000)
    # Bypassing the Python service still cannot start an incomplete batch.
    event = dict(research_connection.execute("SELECT * FROM intraday_research_trial_events LIMIT 1").fetchone())
    original_id = event.pop("id")
    event.update(state="STARTED", reason_code="EXECUTION_STARTED", event_index=2,
                 attempt=1, previous_event_id=original_id, recorded_at_ns=NS + 4_000_000)
    with pytest.raises(sqlite3.IntegrityError, match="RESEARCH_INVALID_TRANSITION"):
        insert(research_connection, "intraday_research_trial_events", event)


@pytest.mark.parametrize("table", [table for table in RESEARCH_TABLES if table != "intraday_research_results"])
def test_natural_key_replace_with_new_id_is_blocked(research_connection, table):
    seed_registered_evidence(research_connection)
    research_connection.execute("PRAGMA recursive_triggers=OFF")
    row = dict(research_connection.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
    row["id"] = 10_000
    with pytest.raises(sqlite3.IntegrityError):
        insert(research_connection, table, row, replace=True)
    assert research_connection.execute(f"SELECT COUNT(*) FROM {table} WHERE id=10000").fetchone()[0] == 0


def test_direct_schema_install_has_finite_json_and_namespace_guards():
    from backend.app.database import SCHEMA
    from backend.app.intraday_research.registry import Registry

    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        seed_registered_evidence(connection)
        row = dict(connection.execute("SELECT * FROM intraday_research_manifests LIMIT 1").fetchone())
        row.pop("id")
        row["experiment_hash"] = "d" * 64
        row["payload_json"] = '{"nested":[1e999]}'
        with pytest.raises(sqlite3.IntegrityError, match="RESEARCH_INVALID_JSON"):
            insert(connection, "intraday_research_manifests", row)
        row["payload_json"] = '{}'
        insert(connection, "intraday_research_manifests", row)
        for change in ({"data_mode": "DEMO", "provenance": "SYNTHETIC", "replay_grade": "RESEARCH_ONLY"},
                       {"provenance": "HISTORICAL_CURRENT", "replay_grade": "RESEARCH_ONLY"}):
            trial = dict(connection.execute("SELECT * FROM intraday_research_trials LIMIT 1").fetchone())
            trial.pop("id")
            trial.update(change, manifest_id=2)
            with pytest.raises(sqlite3.IntegrityError):
                insert(connection, "intraday_research_trials", trial)
        trial = dict(connection.execute("SELECT * FROM intraday_research_trials LIMIT 1").fetchone())
        trial.pop("id")
        trial["manifest_id"] = 2
        insert(connection, "intraday_research_trials", trial)  # Exact scope is accepted.
        assert Registry(connection).read_manifest(1, namespace=manifest().namespace)["holdout_state"] == "SEALED"


@pytest.mark.parametrize("changes", [
    {"quote_size_id": 1, "price_increment_id": 1},
    {"quote_size_id": 999}, {"quote_size_id": 1, "attestation_hash": "d" * 64},
    {"quote_size_id": 1, "provenance": "HISTORICAL_CURRENT", "replay_grade": "RESEARCH_ONLY"},
])
def test_typed_attestation_reference_cannot_cross_scope_or_digest(research_connection, changes):
    seed_registered_evidence(research_connection)
    row = dict(research_connection.execute("SELECT * FROM intraday_research_manifest_attestations LIMIT 1").fetchone())
    row.pop("id")
    row.update(changes)
    with pytest.raises(sqlite3.IntegrityError):
        insert(research_connection, "intraday_research_manifest_attestations", row)
