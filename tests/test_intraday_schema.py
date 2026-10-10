from __future__ import annotations

import sqlite3

import pytest
from intraday_fixtures import ALL_TABLES, HASH, IMMUTABLE_TABLES, NS, common_row, connect, insert, seed_graph

from backend.app.config import get_settings
from backend.app.services.backup_service import prepare_database


@pytest.fixture
def intraday_db(tmp_path, monkeypatch):
    path = tmp_path / "intraday-fixture.db"
    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(path))
    get_settings.cache_clear()
    prepare_database(backup_existing=False)
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()
        get_settings.cache_clear()


def test_intraday_schema_is_additive_and_contains_required_columns(intraday_db):
    tables = {r[0] for r in intraday_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(ALL_TABLES) <= tables
    for table in ("intraday_observations", "intraday_capture_events", "intraday_news_versions"):
        names = {r[1] for r in intraday_db.execute(f"PRAGMA table_info({table})")}
        assert {
            "event_time_ns",
            "received_at_ns",
            "persisted_at_ns",
            "admitted_at_ns",
            "available_at_ns",
            "payload_hash",
            "profile_id",
            "data_mode",
        } <= names
    indexes = {r[0] for r in intraday_db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_intraday_observations_asof", "idx_intraday_news_asof", "idx_intraday_capture_asof"} <= indexes


@pytest.mark.parametrize("table", IMMUTABLE_TABLES)
@pytest.mark.parametrize("operation", ["update", "delete", "replace"])
def test_evidence_is_immutable_even_without_recursive_triggers(intraday_db, table, operation):
    rows = seed_graph(intraday_db)
    original = dict(intraday_db.execute(f"SELECT * FROM {table} WHERE id=?", (rows[table]["id"],)).fetchone())
    with pytest.raises(sqlite3.IntegrityError, match="INTRADAY_APPEND_ONLY"):
        if operation == "update":
            intraday_db.execute(f"UPDATE {table} SET id=id WHERE id=?", (rows[table]["id"],))
        elif operation == "delete":
            intraday_db.execute(f"DELETE FROM {table} WHERE id=?", (rows[table]["id"],))
        else:
            insert(intraday_db, table, rows[table], replace=True)
    assert dict(intraday_db.execute(f"SELECT * FROM {table} WHERE id=?", (rows[table]["id"],)).fetchone()) == original


def test_natural_unique_replace_is_blocked_and_occurrence_return_is_preserved(intraday_db):
    seed_graph(intraday_db)
    row = common_row(id=2, listing_id=1, kind="QUOTE", quality="VALID", reason_code=None, bar_end_ns=None)
    with pytest.raises(sqlite3.IntegrityError, match="INTRADAY_APPEND_ONLY"):
        insert(intraday_db, "intraday_observations", row, replace=True)
    for i, payload in enumerate(('{"bid":1}', '{"bid":2}', '{"bid":1}'), 2):
        insert(
            intraday_db,
            "intraday_observations",
            {
                **row,
                "id": i,
                "ingest_sequence": i,
                "payload_json": payload,
                "payload_hash": HASH,
                "received_at_ns": NS + i,
                "persisted_at_ns": NS + i,
                "admitted_at_ns": NS + i,
                "available_at_ns": NS + i,
            },
        )
    assert intraday_db.execute("SELECT COUNT(*) FROM intraday_observations").fetchone()[0] == 4


@pytest.mark.parametrize("payload", ['{"x":NaN}', '{"x":[Infinity]}', '{"x":1e999}', "[]"])
def test_direct_sql_non_finite_or_non_object_json_fails(intraday_db, payload):
    seed_graph(intraday_db)
    with pytest.raises(sqlite3.DatabaseError):
        insert(
            intraday_db,
            "intraday_observations",
            common_row(
                id=2,
                ingest_sequence=2,
                listing_id=1,
                kind="QUOTE",
                quality="VALID",
                reason_code=None,
                bar_end_ns=None,
                payload_json=payload,
            ),
        )


def test_ns_precision_raw_not_admitted_and_admission_log(intraday_db):
    seed_graph(intraday_db)
    raw = common_row(
        id=2,
        ingest_sequence=2,
        listing_id=1,
        kind="QUOTE",
        quality="VALID",
        reason_code=None,
        bar_end_ns=None,
        admitted_at_ns=None,
        available_at_ns=None,
    )
    insert(intraday_db, "intraday_observations", raw)
    next_row = {**raw, "id": 3, "ingest_sequence": 3, "event_time_ns": NS + 1}
    insert(intraday_db, "intraday_observations", next_row)
    found = intraday_db.execute(
        "SELECT event_time_ns,available_at_ns FROM intraday_observations WHERE id IN (2,3) ORDER BY id"
    ).fetchall()
    assert found[1][0] - found[0][0] == 1 and found[0][1] is None
    insert(
        intraday_db,
        "intraday_capture_events",
        common_row(
            id=2,
            ingest_sequence=2,
            kind="ADMISSION",
            lease_nonce="fixture",
            observation_id=2,
            news_version_id=None,
            event_version_id=None,
        ),
    )
    assert (
        intraday_db.execute(
            "SELECT available_at_ns FROM intraday_capture_events WHERE observation_id=2 AND kind='ADMISSION'"
        ).fetchone()[0]
        == NS + 8
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"available_at_ns": NS + 7},
        {"admitted_at_ns": NS + 1},
        {"event_time_ns": 1.5},
        {"data_mode": "DEMO"},
        {"listing_id": 999},
        {"profile_id": "c" * 64},
    ],
)
def test_invalid_timing_namespace_and_fk_fail(intraday_db, changes):
    seed_graph(intraday_db)
    row = common_row(
        id=2,
        ingest_sequence=2,
        listing_id=1,
        kind="QUOTE",
        quality="VALID",
        reason_code=None,
        bar_end_ns=None,
        **{k: v for k, v in changes.items() if k != "listing_id"},
    )
    if "listing_id" in changes:
        row["listing_id"] = changes["listing_id"]
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, "intraday_observations", row)


def test_identity_restrict_and_legacy_asset_purge_preserve_evidence(intraday_db):
    seed_graph(intraday_db)
    with pytest.raises(sqlite3.IntegrityError):
        intraday_db.execute("DELETE FROM instrument_listings WHERE id=1")
    intraday_db.execute(
        "INSERT INTO assets(symbol,name,asset_type,sector,currency) VALUES ('FIX','Fixture','stock','TEST','USD')"
    )
    intraday_db.execute("DELETE FROM assets WHERE symbol='FIX'")
    assert intraday_db.execute("SELECT COUNT(*) FROM intraday_observations").fetchone()[0] == 1


def test_member_references_are_typed_and_membership_cannot_expand(intraday_db):
    seed_graph(intraday_db)
    row = common_row(
        id=2,
        ingest_sequence=2,
        snapshot_id=1,
        member_kind="OBSERVATION",
        observation_id=999,
        news_version_id=None,
        news_link_id=None,
        event_version_id=None,
        identity_version_id=None,
        calendar_version_id=None,
        universe_snapshot_id=None,
        capture_event_id=None,
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, "intraday_dataset_members", row)
    row["observation_id"] = 1
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, "intraday_dataset_members", row)


def test_operational_state_is_mutable_but_not_evidence(intraday_db):
    seed_graph(intraday_db)
    intraday_db.execute("UPDATE intraday_ingest_runs SET state='PARTIAL' WHERE id=1")
    intraday_db.execute(
        "UPDATE intraday_collector_state SET state='CONNECTING',lease_expires_at_ns=? WHERE id=1", (NS,)
    )
    assert intraday_db.execute("SELECT state FROM intraday_ingest_runs").fetchone()[0] == "PARTIAL"


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "REPLACE", "JSON", "CAPACITY"])
def test_public_schema_has_the_same_intraday_guards(tmp_path, operation):
    from backend.app.database import SCHEMA

    connection = connect(tmp_path / "public-schema.db")
    try:
        connection.executescript(SCHEMA)
        rows = seed_graph(connection)
        with pytest.raises(sqlite3.IntegrityError):
            if operation == "UPDATE":
                connection.execute("UPDATE intraday_observations SET id=id")
            elif operation == "DELETE":
                connection.execute("DELETE FROM intraday_observations")
            elif operation == "REPLACE":
                insert(connection, "intraday_observations", rows["intraday_observations"], replace=True)
            elif operation == "JSON":
                insert(
                    connection,
                    "intraday_observations",
                    {**rows["intraday_observations"], "id": 2, "ingest_sequence": 2, "payload_json": '{"x":1e999}'},
                )
            else:
                insert(
                    connection,
                    "intraday_dataset_members",
                    {
                        **rows["intraday_dataset_members"],
                        "id": 2,
                        "ingest_sequence": 2,
                        "member_kind": "NEWS",
                        "observation_id": None,
                        "news_version_id": 1,
                    },
                )
    finally:
        connection.close()


def test_run_cannot_relabel_a_sip_profile_as_iex(intraday_db):
    rows = seed_graph(intraday_db)
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, "intraday_ingest_runs", {**rows["intraday_ingest_runs"], "id": 2, "feed": "iex"})


def test_official_event_source_is_kept_distinct_from_operating_profile_provider(intraday_db):
    rows = seed_graph(intraday_db)
    insert(intraday_db, "intraday_ingest_runs", {**rows["intraday_ingest_runs"], "id": 2, "provider": "bls"})
    insert(
        intraday_db,
        "intraday_event_versions",
        {**rows["intraday_event_versions"], "id": 2, "ingest_run_id": 2, "provider": "bls"},
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, "intraday_event_versions", {**rows["intraday_event_versions"], "id": 3, "ingest_run_id": 2})


@pytest.mark.parametrize(
    "table",
    [
        "intraday_identity_versions",
        "intraday_universe_members",
        "intraday_news_links",
    ],
)
def test_listing_ownership_and_identity_links_cannot_cross(intraday_db, table):
    rows = seed_graph(intraday_db)
    intraday_db.execute(
        "INSERT INTO instruments(id,canonical_name,instrument_type,asset_class,source) VALUES (2,'Other','STOCK','EQUITY','TEST')"
    )
    intraday_db.execute(
        "INSERT INTO instrument_listings(id,instrument_id,ticker,currency,source) VALUES (2,2,'OTHER','USD','TEST')"
    )
    row = {**rows[table], "id": 2, "ingest_sequence": 2}
    if table == "intraday_universe_members":
        insert(
            intraday_db,
            "intraday_universe_snapshots",
            {**rows["intraday_universe_snapshots"], "id": 2, "ingest_sequence": 2},
        )
        row.update(snapshot_id=2, listing_id=2)  # Identity version still belongs to listing 1.
    else:
        row["instrument_id"] = 2  # Listing still belongs to instrument 1.
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, table, row)


@pytest.mark.parametrize(
    "target, column",
    [
        ("intraday_observations", "observation_id"),
        ("intraday_news_versions", "news_version_id"),
        ("intraday_event_versions", "event_version_id"),
    ],
)
@pytest.mark.parametrize(
    "changes",
    [
        {"persisted_at_ns": NS + 100},
        {"availability_floor_ns": NS + 100},
        {"capture_id": "other-capture"},
        {"ingest_run_id": 2},
        {"ingest_run_id": 3, "provenance": "HISTORICAL_CURRENT", "replay_grade": "RESEARCH_ONLY"},
    ],
)
def test_admission_cannot_anticipate_or_change_its_target_scope(intraday_db, target, column, changes):
    rows = seed_graph(intraday_db)
    for run_id, provenance, grade in ((2, "CAPTURED", "STRICT_PIT"), (3, "HISTORICAL_CURRENT", "RESEARCH_ONLY")):
        insert(
            intraday_db,
            "intraday_ingest_runs",
            {**rows["intraday_ingest_runs"], "id": run_id, "provenance": provenance, "replay_grade": grade},
        )
    raw = {**rows[target], "id": 2, "ingest_sequence": 2, "admitted_at_ns": None, "available_at_ns": None, **changes}
    insert(intraday_db, target, raw)
    admission = {**rows["intraday_capture_events"], "id": 2, "ingest_sequence": 2, "kind": "ADMISSION", column: 2}
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, "intraday_capture_events", admission)
    assert intraday_db.execute(f"SELECT available_at_ns FROM {target} WHERE id=2").fetchone()[0] is None


def test_typed_member_fk_is_checked_when_capacity_is_available(intraday_db):
    rows = seed_graph(intraday_db)
    insert(
        intraday_db, "intraday_dataset_snapshots", {**rows["intraday_dataset_snapshots"], "id": 2, "ingest_sequence": 2}
    )
    row = {**rows["intraday_dataset_members"], "id": 2, "ingest_sequence": 2, "snapshot_id": 2, "observation_id": 999}
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        insert(intraday_db, "intraday_dataset_members", row)
    insert(intraday_db, "intraday_dataset_members", {**row, "observation_id": 1})


@pytest.mark.parametrize(
    "payload",
    [
        '{"x":' + "1" + "0" * 400 + "}",
        '{"x":-' + "1" + "0" * 400 + "}",
        '{"x":[{"nested":' + "1" + "0" * 400 + "}]}",
    ],
)
def test_direct_sql_large_integer_cannot_become_infinite(payload, intraday_db):
    rows = seed_graph(intraday_db)
    with pytest.raises(sqlite3.IntegrityError, match="INTRADAY_INVALID_JSON"):
        insert(
            intraday_db,
            "intraday_observations",
            {**rows["intraday_observations"], "id": 2, "ingest_sequence": 2, "payload_json": payload},
        )


@pytest.mark.parametrize(
    "table, value",
    [
        ("intraday_feed_profiles", None),
        ("intraday_quality_policies", None),
        ("intraday_quality_policies", ""),
    ],
)
def test_versioned_profile_and_policy_keys_are_required(intraday_db, table, value):
    rows = seed_graph(intraday_db)
    with pytest.raises(sqlite3.IntegrityError):
        insert(intraday_db, table, {**rows[table], "id": value})
