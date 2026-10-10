"""Fixture intraday locali: non sono catture di provider né evidenza G1_DATA."""

from __future__ import annotations

import sqlite3

NS = 1_700_000_000_000_000_000
PROFILE = "a" * 64
HASH = "b" * 64
IMMUTABLE_TABLES = (
    "intraday_feed_profiles",
    "intraday_quality_policies",
    "intraday_observations",
    "intraday_capture_events",
    "intraday_identity_versions",
    "intraday_calendar_versions",
    "intraday_universe_snapshots",
    "intraday_universe_members",
    "intraday_news_versions",
    "intraday_news_links",
    "intraday_event_versions",
    "intraday_dataset_snapshots",
    "intraday_dataset_members",
    "intraday_quality_reports",
)
ALL_TABLES = (*IMMUTABLE_TABLES, "intraday_ingest_runs", "intraday_collector_state")


def envelope_args(**changes):
    args = {
        "provider": "alpaca",
        "feed": "sip",
        "profile_id": PROFILE,
        "data_mode": "REAL",
        "provenance": "CAPTURED",
        "replay_grade": "STRICT_PIT",
        "kind": "QUOTE",
        "listing_id": 1,
        "logical_key": "quote:1",
        "capture_id": "fixture",
        "ingest_sequence": 1,
        "event_time_ns": NS,
        "received_at_ns": NS + 2,
        "persisted_at_ns": NS + 3,
        "admitted_at_ns": NS + 8,
        "availability_floor_ns": NS,
        "payload_json": '{"bid":100,"ask":101}',
    }
    return {**args, **changes}


def common_row(**changes):
    row = {
        "id": 1,
        "ingest_run_id": 1,
        "provider": "alpaca",
        "feed": "sip",
        "profile_id": PROFILE,
        "data_mode": "REAL",
        "provenance": "CAPTURED",
        "replay_grade": "STRICT_PIT",
        "schema_version": "intraday-v1",
        "listing_id": None,
        "logical_key": "fixture",
        "capture_id": "fixture",
        "ingest_sequence": 1,
        "source_event_id": None,
        "source_revision_id": None,
        "event_time_ns": NS,
        "received_at_ns": NS + 2,
        "persisted_at_ns": NS + 3,
        "admitted_at_ns": NS + 8,
        "available_at_ns": NS + 8,
        "availability_floor_ns": NS,
        "payload_json": "{}",
        "payload_hash": HASH,
    }
    return {**row, **changes}


def graph_rows():
    return {
        "intraday_feed_profiles": {
            "id": PROFILE,
            "provider": "alpaca",
            "feed": "sip",
            "config_json": "{}",
            "created_at_ns": NS,
        },
        "intraday_quality_policies": {
            "id": "intraday-quality-v1",
            "config_json": "{}",
            "policy_hash": HASH,
            "created_at_ns": NS,
        },
        "intraday_ingest_runs": {
            "id": 1,
            "profile_id": PROFILE,
            "provider": "alpaca",
            "feed": "sip",
            "data_mode": "REAL",
            "provenance": "CAPTURED",
            "replay_grade": "STRICT_PIT",
            "state": "RUNNING",
            "started_at_ns": NS,
            "limits_json": "{}",
            "cursor_json": "{}",
        },
        "intraday_collector_state": {
            "id": 1,
            "profile_id": PROFILE,
            "data_mode": "REAL",
            "state": "STOPPED",
            "lease_expires_at_ns": 0,
        },
        "intraday_identity_versions": common_row(
            listing_id=1,
            instrument_id=1,
            broker_asset_id="fixture-uuid",
            ticker="FIX",
            venue="XNAS",
            valid_from_ns=NS,
            valid_to_ns=None,
            confirmed=1,
            supersedes_id=None,
        ),
        "intraday_calendar_versions": common_row(
            session_date="2023-11-14",
            open_at_ns=NS,
            close_at_ns=NS + 390 * 60 * 1_000_000_000,
            timezone="America/New_York",
            supersedes_id=None,
        ),
        "intraday_observations": common_row(
            listing_id=1, kind="QUOTE", quality="VALID", reason_code=None, bar_end_ns=None
        ),
        "intraday_news_versions": common_row(
            article_id="article:1", published_at_ns=NS, updated_at_ns=NS, supersedes_id=None
        ),
        "intraday_event_versions": common_row(
            event_type="EARNINGS", effective_at_ns=NS, scheduled_at_ns=NS + 100, supersedes_id=None
        ),
        "intraday_capture_events": common_row(
            kind="ACK", lease_nonce="fixture-nonce", observation_id=None, news_version_id=None, event_version_id=None
        ),
        "intraday_universe_snapshots": common_row(cutoff_ns=NS + 8, member_count=1),
        "intraday_universe_members": common_row(
            listing_id=1, snapshot_id=1, identity_version_id=1, eligible=1, reason_code=None
        ),
        "intraday_news_links": common_row(
            listing_id=1,
            news_version_id=1,
            instrument_id=1,
            cluster_id="cluster:1",
            category="UNKNOWN",
            rule_version="news-v1",
        ),
        "intraday_dataset_snapshots": common_row(
            start_at_ns=NS,
            end_at_ns=NS + 100,
            cutoff_ns=NS + 8,
            policy_id="intraday-quality-v1",
            digest=HASH,
            member_count=1,
        ),
        "intraday_dataset_members": common_row(
            snapshot_id=1,
            member_kind="OBSERVATION",
            observation_id=1,
            news_version_id=None,
            news_link_id=None,
            event_version_id=None,
            identity_version_id=None,
            calendar_version_id=None,
            universe_snapshot_id=None,
            capture_event_id=None,
        ),
        "intraday_quality_reports": common_row(
            snapshot_id=1, policy_id="intraday-quality-v1", outcome="INSUFFICIENTE", metrics_json="{}", limits_json="{}"
        ),
    }


def insert(connection, table, row, *, replace=False):
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    command = "INSERT OR REPLACE" if replace else "INSERT"
    connection.execute(f"{command} INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))


def seed_graph(connection):
    connection.execute(
        "INSERT INTO instruments(id, canonical_name, instrument_type, asset_class, source) VALUES (1,'Fixture','STOCK','EQUITY','TEST')"
    )
    connection.execute(
        "INSERT INTO instrument_listings(id,instrument_id,ticker,currency,source) VALUES (1,1,'FIX','USD','TEST')"
    )
    for table, row in graph_rows().items():
        insert(connection, table, row)
    connection.commit()
    return graph_rows()


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA recursive_triggers=OFF")
    return connection
