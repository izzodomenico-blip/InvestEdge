"""Atomic preregistration and append-only trial metadata, with explicit clocks."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict

from backend.app.intraday.contracts import canonical_json
from backend.app.intraday_research.contracts import (
    REASONS,
    STATES,
    TRANSITIONS,
    VERSION,
    DatasetRef,
    ResearchError,
    ResearchManifest,
    ResearchNamespace,
    ResourceLimits,
    canonical_hash,
    integer,
    parse_object,
)

_SCOPE = ("profile_id", "feed", "data_mode", "provenance", "replay_grade")
_WHERE = " AND ".join(f"{name}=?" for name in _SCOPE)


def _current_inventory() -> tuple[str, ...]:
    # Settings only, loaded lazily; no handler, provider or collector is imported.
    from backend.app.config import get_settings
    return tuple(value for name, value in vars(get_settings()).items()
                 if isinstance(value, str) and value and
                 (name.endswith(("_api_key", "_token", "_chat_id"))
                  or name in {"alpaca_api_key_id", "alpaca_api_secret_key"}))


def _contains(value, inventory):
    if isinstance(value, dict):
        return any(_contains(key, inventory) or _contains(item, inventory) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains(item, inventory) for item in value)
    return any(secret in str(value) for secret in inventory)


class Registry:
    def __init__(self, connection: sqlite3.Connection,
                 *, secret_inventory: Callable[[], tuple[str, ...]] | None = None):
        self.connection = connection
        self.secret_inventory = secret_inventory or _current_inventory

    def _guard(self, payload):
        if _contains(payload, tuple(value for value in self.secret_inventory() if isinstance(value, str) and value)):
            raise ResearchError("PUBLIC_METADATA_INVALID")

    def _namespace(self, namespace):
        if type(namespace) is not ResearchNamespace:
            raise ResearchError("INVALID_CONTRACT")
        self._guard(asdict(namespace))

    def _rows(self, sql, params=()):
        cursor = self.connection.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor]

    def _checked(self, row, namespace):
        if tuple(row[key] for key in _SCOPE) != namespace.key or row["schema_version"] != VERSION:
            raise ResearchError("NAMESPACE_MISMATCH")
        payload = parse_object(row["payload_json"])
        self._guard(row)
        self._guard(payload)
        if canonical_json(payload) != row["payload_json"] or canonical_hash(payload) != row["payload_hash"]:
            raise ResearchError("REGISTRY_INTEGRITY")
        return payload

    @contextmanager
    def _write(self):
        if self.connection.in_transaction:
            raise ResearchError("TRANSACTION_ALREADY_OPEN")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def _insert(self, table, namespace, payload, stamp, fields):
        self._guard(payload)
        self._guard(fields)
        row = asdict(namespace) | {
            "schema_version": VERSION, "payload_json": canonical_json(payload),
            "payload_hash": canonical_hash(payload), "recorded_at_ns": stamp,
        } | fields
        self._guard(row)  # Derived hashes and metadata are public too.
        cursor = self.connection.execute(
            f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))
        self._guard(cursor.lastrowid)
        return int(cursor.lastrowid)

    def _verify_datasets(self, body, namespace):
        for reference in body["datasets"]:
            rows = self._rows(f"SELECT * FROM intraday_dataset_snapshots WHERE id=? AND {_WHERE}",
                              (reference["snapshot_id"], *namespace.key))
            if len(rows) != 1 or rows[0]["digest"] != reference["digest"]:
                raise ResearchError("INPUT_MISSING")
            self._guard(rows[0])

    def preregister(self, manifest: ResearchManifest, *, now_ns: int) -> dict:
        if type(manifest) is not ResearchManifest:
            raise ResearchError("INVALID_CONTRACT")
        integer(now_ns)
        if now_ns < manifest.cutoff_ns:
            raise ResearchError("INVALID_TIMESTAMP")
        body = manifest.to_dict()
        self._guard(body)  # Before any hashes or SQL writes.
        experiment_hash = canonical_hash(body)
        try:
            with self._write():
                existing = self._rows("SELECT id FROM intraday_research_manifests WHERE experiment_hash=?", (experiment_hash,))
                if existing:
                    manifest_id = existing[0]["id"]
                    self.read_manifest(manifest_id, namespace=manifest.namespace)
                else:
                    self._verify_datasets(body, manifest.namespace)
                    manifest_id = self._insert("intraday_research_manifests", manifest.namespace, body, now_ns,
                        {"experiment_hash": experiment_hash, "start_at_ns": manifest.start_at_ns,
                         "end_at_ns": manifest.end_at_ns, "cutoff_ns": manifest.cutoff_ns,
                         "trial_count": 20, "policy_count": 10})
                    for ref in manifest.datasets:
                        self._insert("intraday_research_manifest_datasets", manifest.namespace,
                            {"snapshot_id": ref.snapshot_id, "digest": ref.digest}, now_ns,
                            {"manifest_id": manifest_id, "snapshot_id": ref.snapshot_id, "dataset_digest": ref.digest})
                    trials = []
                    for ordinal, config in enumerate(manifest.grid, 1):
                        payload = {"ordinal": ordinal, "config": config.to_dict(),
                                   "config_hash": config.config_hash, "policy_key": config.policy_key}
                        trial_id = self._insert("intraday_research_trials", manifest.namespace, payload, now_ns,
                            {"manifest_id": manifest_id, "ordinal": ordinal,
                             "config_hash": config.config_hash, "policy_key": config.policy_key})
                        trials.append(trial_id)
                    # Every hypothesis exists before any REGISTERED/STARTED event.
                    for trial_id in trials:
                        self._event(trial_id, manifest_id, manifest.namespace, "REGISTERED", "PREREGISTERED", now_ns, None)
                    self._insert("intraday_research_holdout_events", manifest.namespace,
                        {"state": "SEALED", "scope": "RESEARCH_WORKFLOW"}, now_ns,
                        {"manifest_id": manifest_id, "event_index": 1, "state": "SEALED"})
                ids = self._rows("SELECT id FROM intraday_research_trials WHERE manifest_id=? ORDER BY ordinal", (manifest_id,))
                output = {"manifest_id": manifest_id, "experiment_hash": experiment_hash,
                          "trial_ids": [row["id"] for row in ids]}
                self._guard(output)
                return output
        except sqlite3.DatabaseError:
            raise ResearchError("REGISTRY_WRITE_FAILED") from None

    def read_manifest(self, manifest_id: int, *, namespace: ResearchNamespace) -> dict:
        integer(manifest_id, positive=True)
        self._namespace(namespace)
        rows = self._rows(f"SELECT * FROM intraday_research_manifests WHERE id=? AND {_WHERE}", (manifest_id, *namespace.key))
        if len(rows) != 1:
            raise ResearchError("INPUT_MISSING")
        row = rows[0]
        body = self._checked(row, namespace)
        try:
            restored = ResearchManifest(
                namespace=ResearchNamespace(**body["namespace"]), resources=ResourceLimits(**body["resources"]),
                datasets=tuple(DatasetRef(**ref) for ref in body["datasets"]),
                start_at_ns=body["start_at_ns"], end_at_ns=body["end_at_ns"], cutoff_ns=body["cutoff_ns"],
                code_revision=body["code_revision"], cost_profile_hash=body["costs"]["profile_hash"],
                seed=body["statistics"]["seed"],
            )
            if restored.config_json != row["payload_json"]:
                raise ResearchError("REGISTRY_INTEGRITY")
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ResearchError("REGISTRY_INTEGRITY") from None
        if (body.get("namespace") != asdict(namespace) or body.get("version") != VERSION
            or canonical_hash(body) != row["experiment_hash"]
            or any(body.get(key) != row[key] for key in ("start_at_ns", "end_at_ns", "cutoff_ns"))):
            raise ResearchError("REGISTRY_INTEGRITY")
        self._verify_datasets(body, namespace)
        refs = self._rows("SELECT * FROM intraday_research_manifest_datasets WHERE manifest_id=? ORDER BY id", (manifest_id,))
        actual = []
        for reference in refs:
            payload = self._checked(reference, namespace)
            if canonical_json(payload) != canonical_json({"snapshot_id": reference["snapshot_id"], "digest": reference["dataset_digest"]}):
                raise ResearchError("REGISTRY_INTEGRITY")
            actual.append(payload)
        if actual != body["datasets"]:
            raise ResearchError("REGISTRY_INTEGRITY")
        trials = self._trials(manifest_id, namespace, body)
        if len(trials) != row["trial_count"] or len({trial["policy_key"] for trial in trials}) != row["policy_count"]:
            raise ResearchError("REGISTRY_INTEGRITY")
        holdout_state = self._holdout_state(manifest_id, namespace, row["recorded_at_ns"])
        output = {"manifest_id": manifest_id, "experiment_hash": row["experiment_hash"],
                  "config": body, "holdout_state": holdout_state}
        self._guard(output)
        return output

    def _holdout_state(self, manifest_id, namespace, registered_at_ns):
        rows = self._rows("SELECT * FROM intraday_research_holdout_events WHERE manifest_id=? ORDER BY event_index", (manifest_id,))
        if not rows:
            raise ResearchError("REGISTRY_INTEGRITY")
        previous = None
        transitions = {"SEALED": {"INTEGRITY_ATTESTED", "CONTAMINATED"},
                       "INTEGRITY_ATTESTED": {"OPENED", "CONTAMINATED"},
                       "OPENED": {"CONTAMINATED"}, "CONTAMINATED": set()}
        for index, row in enumerate(rows, 1):
            payload = self._checked(row, namespace)
            if (row["event_index"] != index or payload.get("state") != row["state"]
                or payload.get("scope") != "RESEARCH_WORKFLOW"
                or row["recorded_at_ns"] < registered_at_ns):
                raise ResearchError("REGISTRY_INTEGRITY")
            if previous is None:
                if payload != {"state": "SEALED", "scope": "RESEARCH_WORKFLOW"}:
                    raise ResearchError("REGISTRY_INTEGRITY")
            elif (row["state"] not in transitions[previous["state"]]
                  or row["recorded_at_ns"] < previous["recorded_at_ns"]):
                raise ResearchError("REGISTRY_INTEGRITY")
            previous = row
        return rows[-1]["state"]

    def _trials(self, manifest_id, namespace, body):
        rows = self._rows("SELECT * FROM intraday_research_trials WHERE manifest_id=? ORDER BY ordinal", (manifest_id,))
        if len(rows) != 20 or len(body.get("grid", [])) != 20:
            raise ResearchError("REGISTRY_INTEGRITY")
        for ordinal, row in enumerate(rows, 1):
            payload = self._checked(row, namespace)
            expected = body["grid"][ordinal - 1]
            policy_key = f"{expected['family']}|{expected['holding_minutes']}|{expected['arm']}"
            expected_payload = {"ordinal": ordinal, "config": expected,
                                "config_hash": canonical_hash(expected), "policy_key": policy_key}
            if (row["ordinal"] != ordinal or canonical_json(payload) != canonical_json(expected_payload)
                or expected_payload["config_hash"] != row["config_hash"] or row["policy_key"] != policy_key):
                raise ResearchError("REGISTRY_INTEGRITY")
            events = self.list_events(row["id"], namespace=namespace)
            if not events or events[0]["state"] != "REGISTERED":
                raise ResearchError("REGISTRY_INTEGRITY")
            row["state"] = events[-1]["state"]
        return rows

    def list_trials(self, manifest_id: int, *, namespace: ResearchNamespace) -> list[dict]:
        saved = self.read_manifest(manifest_id, namespace=namespace)
        rows = self._trials(manifest_id, namespace, saved["config"])
        return [{key: row[key] for key in ("id", "ordinal", "config_hash", "policy_key", "state")} for row in rows]

    def list_events(self, trial_id: int, *, namespace: ResearchNamespace) -> list[dict]:
        integer(trial_id, positive=True)
        self._namespace(namespace)
        parent = self._rows(f"SELECT * FROM intraday_research_trials WHERE id=? AND {_WHERE}", (trial_id, *namespace.key))
        if not parent:
            raise ResearchError("INPUT_MISSING")
        self._checked(parent[0], namespace)
        manifests = self._rows(f"SELECT * FROM intraday_research_manifests WHERE id=? AND {_WHERE}",
                               (parent[0]["manifest_id"], *namespace.key))
        if len(manifests) != 1:
            raise ResearchError("REGISTRY_INTEGRITY")
        self._checked(manifests[0], namespace)
        if parent[0]["recorded_at_ns"] < manifests[0]["recorded_at_ns"]:
            raise ResearchError("REGISTRY_INTEGRITY")
        rows = self._rows("SELECT * FROM intraday_research_trial_events WHERE trial_id=? ORDER BY event_index", (trial_id,))
        previous = None
        for index, row in enumerate(rows, 1):
            payload = self._checked(row, namespace)
            keys = ("state", "reason_code", "attempt", "event_index", "previous_event_id")
            if canonical_json(payload) != canonical_json({key: row[key] for key in keys}) or row["event_index"] != index or row["manifest_id"] != parent[0]["manifest_id"]:
                raise ResearchError("REGISTRY_INTEGRITY")
            if previous is None:
                if (row["state"] != "REGISTERED" or row["reason_code"] != "PREREGISTERED"
                    or row["attempt"] != 0 or row["previous_event_id"] is not None
                    or row["recorded_at_ns"] < parent[0]["recorded_at_ns"]):
                    raise ResearchError("REGISTRY_INTEGRITY")
            elif (row["state"] not in TRANSITIONS[previous["state"]]
                  or row["previous_event_id"] != previous["id"]
                  or row["recorded_at_ns"] < previous["recorded_at_ns"]
                  or row["attempt"] != previous["attempt"] + int(row["state"] == "STARTED")):
                raise ResearchError("REGISTRY_INTEGRITY")
            previous = row
        return [{key: row[key] for key in ("id", "state", "reason_code", "attempt", "event_index", "previous_event_id", "recorded_at_ns")} for row in rows]

    def _event(self, trial_id, manifest_id, namespace, state, reason, stamp, previous):
        fields = {"state": state, "reason_code": reason,
                  "attempt": (previous["attempt"] if previous else 0) + int(state == "STARTED"),
                  "event_index": previous["event_index"] + 1 if previous else 1,
                  "previous_event_id": previous["id"] if previous else None}
        return self._insert("intraday_research_trial_events", namespace, fields, stamp,
                            fields | {"manifest_id": manifest_id, "trial_id": trial_id})

    def append_trial_event(self, trial_id: int, *, namespace: ResearchNamespace,
                           state: str, reason_code: str, now_ns: int) -> int:
        integer(trial_id, positive=True)
        integer(now_ns)
        self._namespace(namespace)
        if type(state) is not str or type(reason_code) is not str or state not in STATES or reason_code not in REASONS:
            raise ResearchError("INVALID_TRANSITION")
        try:
            with self._write():
                parent = self._rows(f"SELECT * FROM intraday_research_trials WHERE id=? AND {_WHERE}", (trial_id, *namespace.key))
                if not parent:
                    raise ResearchError("INPUT_MISSING")
                self.read_manifest(parent[0]["manifest_id"], namespace=namespace)
                events = self.list_events(trial_id, namespace=namespace)
                previous = events[-1]
                if state not in TRANSITIONS[previous["state"]]:
                    raise ResearchError("INVALID_TRANSITION")
                if now_ns < previous["recorded_at_ns"]:
                    raise ResearchError("INVALID_TIMESTAMP")
                return self._event(trial_id, parent[0]["manifest_id"], namespace, state, reason_code, now_ns, previous)
        except sqlite3.DatabaseError:
            raise ResearchError("REGISTRY_WRITE_FAILED") from None

    def hypothesis_count(self, *, namespace: ResearchNamespace) -> int:
        self._namespace(namespace)
        # REAL is cumulative across profiles/periods; DEMO never contributes to it.
        rows = self._rows("SELECT COUNT(*) AS n FROM intraday_research_trials WHERE data_mode=?", (namespace.data_mode,))
        self._guard(rows)
        return int(rows[0]["n"])
