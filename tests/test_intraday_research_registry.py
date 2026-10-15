from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from intraday_research_fixtures import NS, manifest, seed_research_inputs

from backend.app.intraday.contracts import canonical_json
from backend.app.intraday_research.contracts import (
    DatasetRef,
    ResearchError,
    ResearchNamespace,
    canonical_hash,
)
from backend.app.intraday_research.registry import Registry


@pytest.fixture
def registry(research_connection):
    seed_research_inputs(research_connection)
    return Registry(research_connection)


def test_preregistration_is_atomic_complete_ordered_and_idempotent(registry):
    saved = manifest()
    first = registry.preregister(saved, now_ns=NS + 3_000_000)
    trials = registry.list_trials(first["manifest_id"], namespace=saved.namespace)
    assert len(trials) == 20
    assert len({trial["policy_key"] for trial in trials}) == 10
    assert [row["ordinal"] for row in trials] == list(range(1, 21))
    assert all(row["state"] == "REGISTERED" for row in trials)
    assert registry.preregister(saved, now_ns=NS + 4_000_000) == first
    assert registry.hypothesis_count(namespace=saved.namespace) == 20


def test_injected_failure_rolls_back_manifest_twenty_trials_and_events(registry):
    registry.connection.execute("""CREATE TRIGGER fail_trial BEFORE INSERT ON intraday_research_trials
        WHEN NEW.ordinal=17 BEGIN SELECT RAISE(ABORT,'fixture'); END""")
    with pytest.raises(ResearchError):
        registry.preregister(manifest(), now_ns=NS + 3_000_000)
    for table in ("manifests", "trials", "trial_events", "manifest_datasets"):
        assert registry.connection.execute(f"SELECT COUNT(*) FROM intraday_research_{table}").fetchone()[0] == 0


@pytest.mark.parametrize("state,reason", [
    ("FAILED", "INTERNAL_ERROR"), ("CANCELLED", "USER_CANCELLED"),
    ("INTERRUPTED", "EXECUTOR_INTERRUPTED"), ("COMPLETED", "NO_TRADES"),
])
def test_terminal_events_without_sharpe_are_never_discarded(registry, state, reason):
    saved = manifest()
    registered = registry.preregister(saved, now_ns=NS + 3_000_000)
    trial = registry.list_trials(registered["manifest_id"], namespace=saved.namespace)[0]
    registry.append_trial_event(trial["id"], namespace=saved.namespace, state="STARTED",
        reason_code="EXECUTION_STARTED", now_ns=NS + 4_000_000)
    registry.append_trial_event(trial["id"], namespace=saved.namespace, state=state,
        reason_code=reason, now_ns=NS + 5_000_000)
    events = registry.list_events(trial["id"], namespace=saved.namespace)
    assert [event["state"] for event in events] == ["REGISTERED", "STARTED", state]
    assert events[-1]["reason_code"] == reason
    assert registry.hypothesis_count(namespace=saved.namespace) == 20


def test_rejected_trial_and_linked_retry_preserve_entire_history(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    trials = registry.list_trials(ref["manifest_id"], namespace=saved.namespace)
    registry.append_trial_event(trials[0]["id"], namespace=saved.namespace, state="REJECTED",
        reason_code="INPUT_NOT_ELIGIBLE", now_ns=NS + 4_000_000)
    for state, reason, stamp in (("STARTED", "EXECUTION_STARTED", 4),
                                ("FAILED", "INTERNAL_ERROR", 5),
                                ("STARTED", "EXECUTION_STARTED", 6)):
        registry.append_trial_event(trials[1]["id"], namespace=saved.namespace, state=state,
            reason_code=reason, now_ns=NS + stamp * 1_000_000)
    events = registry.list_events(trials[1]["id"], namespace=saved.namespace)
    assert [row["attempt"] for row in events] == [0, 1, 1, 2]
    assert events[-1]["previous_event_id"] == events[-2]["id"]


def test_mode_mismatch_and_backward_clock_never_write(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    trial = registry.list_trials(ref["manifest_id"], namespace=saved.namespace)[0]
    wrong = ResearchNamespace(saved.namespace.profile_id, "sip", "DEMO", "SYNTHETIC", "RESEARCH_ONLY")
    before = registry.connection.total_changes
    for namespace, stamp in ((wrong, NS + 4_000_000), (saved.namespace, NS)):
        with pytest.raises(ResearchError):
            registry.append_trial_event(trial["id"], namespace=namespace, state="STARTED",
                reason_code="EXECUTION_STARTED", now_ns=stamp)
    assert registry.connection.total_changes == before


def test_changed_period_is_new_experiment_even_with_same_configs(registry):
    first = manifest()
    registry.preregister(first, now_ns=NS + 3_000_000)
    second = replace(first, end_at_ns=NS + 1_000_001)
    assert first.grid[0].config_hash == second.grid[0].config_hash
    registry.preregister(second, now_ns=NS + 3_000_001)
    assert registry.hypothesis_count(namespace=first.namespace) == 40


def test_demo_registry_does_not_change_real_hypothesis_count(registry):
    from intraday_fixtures import insert

    real = manifest()
    registry.preregister(real, now_ns=NS + 3_000_000)
    demo_ns = ResearchNamespace(real.namespace.profile_id, "sip", "DEMO", "SYNTHETIC", "RESEARCH_ONLY")
    for table in ("intraday_ingest_runs", "intraday_dataset_snapshots"):
        row = dict(registry.connection.execute(f"SELECT * FROM {table} LIMIT 1").fetchone())
        row.update(id=2, data_mode="DEMO", provenance="SYNTHETIC", replay_grade="RESEARCH_ONLY")
        if table == "intraday_dataset_snapshots":
            row.update(ingest_run_id=2, ingest_sequence=2)
        insert(registry.connection, table, row)
    registry.connection.commit()
    demo = replace(real, namespace=demo_ns, datasets=(DatasetRef(2, real.datasets[0].digest),))
    ref = registry.preregister(demo, now_ns=NS + 3_000_000)
    assert registry.hypothesis_count(namespace=demo_ns) == 20
    assert registry.hypothesis_count(namespace=real.namespace) == 20
    assert registry.read_manifest(ref["manifest_id"], namespace=demo_ns)["config"]["gate"]["economic_status"] == "NOT_EVALUATED"


def test_dataset_wrong_namespace_or_digest_is_rejected(registry):
    for digest in ("d" * 64,):
        with pytest.raises(ResearchError):
            registry.preregister(manifest(datasets=(DatasetRef(1, digest),)), now_ns=NS + 3_000_000)
    demo = ResearchNamespace(manifest().namespace.profile_id, "sip", "DEMO", "SYNTHETIC", "RESEARCH_ONLY")
    with pytest.raises(ResearchError):
        registry.preregister(manifest(namespace=demo), now_ns=NS + 3_000_000)


def test_secret_guard_precedes_persistence_and_rechecks_after_rotation(registry):
    saved = manifest()
    inventory = []
    protected = Registry(registry.connection, secret_inventory=lambda: tuple(inventory))
    ref = protected.preregister(saved, now_ns=NS + 3_000_000)
    inventory.append(saved.namespace.profile_id)
    with pytest.raises(ResearchError, match="PUBLIC_METADATA_INVALID"):
        protected.read_manifest(ref["manifest_id"], namespace=saved.namespace)
    inventory.clear()
    generated = uuid4().hex
    poisoned = replace(saved, code_revision=generated + "a" * 8)
    inventory.append(generated)
    before = registry.connection.total_changes
    with pytest.raises(ResearchError, match="PUBLIC_METADATA_INVALID"):
        protected.preregister(poisoned, now_ns=NS + 3_000_001)
    assert registry.connection.total_changes == before


def test_reads_are_detached_and_perform_no_dml(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    before = registry.connection.total_changes
    data = registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)
    data["config"]["resources"]["max_listings"] = 999
    assert registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)["config"]["resources"]["max_listings"] == 30
    assert registry.connection.total_changes == before


def test_unknown_reason_or_invalid_transition_has_fixed_error(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    trial = registry.list_trials(ref["manifest_id"], namespace=saved.namespace)[0]
    for state, reason in (("COMPLETED", "FINISHED"), ("STARTED", "untrusted-raw-error")):
        with pytest.raises(ResearchError) as caught:
            registry.append_trial_event(trial["id"], namespace=saved.namespace, state=state,
                reason_code=reason, now_ns=NS + 4_000_000)
        assert "untrusted" not in str(caught.value)


def test_registry_refuses_callers_open_transaction(registry):
    registry.connection.execute("BEGIN")
    try:
        with pytest.raises(ResearchError, match="TRANSACTION_ALREADY_OPEN"):
            registry.preregister(manifest(), now_ns=NS + 3_000_000)
    finally:
        registry.connection.rollback()


@pytest.mark.parametrize("tamper", ["resources", "gate", "grid", "noncanonical"])
def test_read_revalidates_frozen_manifest_even_with_coherent_hashes(registry, tamper):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    body = saved.to_dict()
    if tamper == "resources":
        body["resources"]["max_listings"] = 999
    elif tamper == "gate":
        body["gate"]["economic_status"] = "PASS"
    elif tamper == "grid":
        body["grid"][0]["risk"]["k"] = "100"
    text = canonical_json(body)
    if tamper == "noncanonical":
        text = " " + text
    # Corruption is confined to this scratch fixture; production guards stay intact.
    registry.connection.execute("DROP TRIGGER trg_intraday_research_manifests_no_update")
    registry.connection.execute(
        "UPDATE intraday_research_manifests SET payload_json=?,payload_hash=?,experiment_hash=? WHERE id=?",
        (text, canonical_hash(body), canonical_hash(body), ref["manifest_id"]),
    )
    registry.connection.commit()
    with pytest.raises(ResearchError, match="REGISTRY_INTEGRITY"):
        registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)


def test_read_requires_intact_initial_holdout_seal(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    registry.connection.execute("DROP TRIGGER trg_intraday_research_holdout_events_no_delete")
    registry.connection.execute("DELETE FROM intraday_research_holdout_events")
    registry.connection.commit()
    with pytest.raises(ResearchError, match="REGISTRY_INTEGRITY"):
        registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)


def test_holdout_current_contamination_is_visible_without_mutating_manifest(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    registry._insert("intraday_research_holdout_events", saved.namespace,
        {"state": "CONTAMINATED", "scope": "RESEARCH_WORKFLOW"}, NS + 4_000_000,
        {"manifest_id": ref["manifest_id"], "event_index": 2, "state": "CONTAMINATED"})
    registry.connection.commit()
    before = registry.connection.total_changes
    view = registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)
    assert view["holdout_state"] == "CONTAMINATED"
    assert view["config"]["holdout"]["state"] == "SEALED"
    assert registry.connection.total_changes == before


def test_secret_guard_checks_derived_hash_before_sql_and_rolls_back(registry):
    saved = manifest()
    config = saved.grid[0]
    derived = canonical_hash({"ordinal": 1, "config": config.to_dict(),
        "config_hash": config.config_hash, "policy_key": config.policy_key})
    protected = Registry(registry.connection, secret_inventory=lambda: (derived,))
    with pytest.raises(ResearchError, match="PUBLIC_METADATA_INVALID"):
        protected.preregister(saved, now_ns=NS + 3_000_000)
    assert registry.connection.execute("SELECT COUNT(*) FROM intraday_research_manifests").fetchone()[0] == 0


@pytest.mark.parametrize("state,reason", [([], "EXECUTION_STARTED"), ("STARTED", {})])
def test_unhashable_event_input_has_fixed_error(registry, state, reason):
    with pytest.raises(ResearchError, match="INVALID_TRANSITION"):
        registry.append_trial_event(1, namespace=manifest().namespace, state=state,
            reason_code=reason, now_ns=NS)


def test_two_connections_cannot_duplicate_identical_preregistration(registry):
    path = registry.connection.execute("PRAGMA database_list").fetchone()[2]
    barrier = Barrier(2)

    def register(_):
        with sqlite3.connect(path, timeout=10) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            barrier.wait(timeout=10)
            return Registry(connection).preregister(manifest(), now_ns=NS + 3_000_000)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(register, range(2)))
    assert first == second
    assert registry.hypothesis_count(namespace=manifest().namespace) == 20


def test_read_detects_rehashed_trial_policy_key_tamper(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    from backend.app.intraday_research.contracts import parse_object
    registry.connection.execute("DROP TRIGGER trg_intraday_research_trials_no_update")
    for row in registry.connection.execute("SELECT * FROM intraday_research_trials WHERE ordinal IN (1,2)").fetchall():
        payload = parse_object(row["payload_json"])
        payload["policy_key"] = "wrong-policy"
        registry.connection.execute("UPDATE intraday_research_trials SET policy_key=?,payload_json=?,payload_hash=? WHERE id=?",
            (payload["policy_key"], canonical_json(payload), canonical_hash(payload), row["id"]))
    registry.connection.commit()
    with pytest.raises(ResearchError, match="REGISTRY_INTEGRITY"):
        registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)


@pytest.mark.parametrize("table", ["intraday_research_trials", "intraday_research_trial_events"])
def test_registered_clock_cannot_precede_manifest_even_after_storage_corruption(registry, table):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    registry.connection.execute(f"DROP TRIGGER trg_{table}_no_update")
    registry.connection.execute(f"UPDATE {table} SET recorded_at_ns=0 WHERE id=1")
    registry.connection.commit()
    for reader in (lambda: registry.read_manifest(ref["manifest_id"], namespace=saved.namespace),
                   lambda: registry.list_events(ref["trial_ids"][0], namespace=saved.namespace)):
        with pytest.raises(ResearchError, match="REGISTRY_INTEGRITY"):
            reader()


def test_dataset_reference_rejects_boolean_id_after_coherent_rehash(registry):
    saved = manifest()
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    payload = {"snapshot_id": True, "digest": saved.datasets[0].digest}
    registry.connection.execute("DROP TRIGGER trg_intraday_research_manifest_datasets_no_update")
    registry.connection.execute("UPDATE intraday_research_manifest_datasets SET payload_json=?,payload_hash=?",
        (canonical_json(payload), canonical_hash(payload)))
    registry.connection.commit()
    with pytest.raises(ResearchError, match="REGISTRY_INTEGRITY"):
        registry.read_manifest(ref["manifest_id"], namespace=saved.namespace)


@pytest.mark.parametrize('listing_ids',[[{}],[1,'2'],[True]])
def test_news_authority_rejects_malformed_listing_scope_with_fixed_error(listing_ids):
    from backend.app.intraday_research.contracts import AttestationAuthority
    body = {'version':'news-primary-contract-v1','schema':'issuer-facts-v1','issuer_id':'ISSUER_FIXTURE',
        'listing_ids':listing_ids,'archive_originals':True,'research_use':True}
    with pytest.raises(ResearchError,match='INVALID_CONTRACT'):
        AttestationAuthority(manifest().namespace,'SYNTHETIC_FIXTURE',canonical_json(body),'a'*64)


def test_news_import_is_idempotent_append_only_and_exact_bytes_are_revalidated(registry):
    from intraday_research_fixtures import news_terms_fixture
    news = news_terms_fixture(registry.connection)
    reader,ref,authority,_,document,evidence = news
    repeated=reader.import_attestation(document,namespace=manifest().namespace,evidence=evidence,
        authority_hash=authority.authority_hash,now_ns=NS+50)
    assert repeated==ref
    assert reader.connection.execute('SELECT COUNT(*) FROM intraday_news_source_attestations').fetchone()[0]==1
    for sql in ('UPDATE intraday_news_source_attestations SET valid_to_ns=1','DELETE FROM intraday_news_source_attestations'):
        with pytest.raises(sqlite3.IntegrityError):
            reader.connection.execute(sql)
    reader.connection.rollback()
    reader.connection.execute('DROP TRIGGER trg_intraday_news_versions_no_update')
    reader.connection.execute("UPDATE intraday_news_versions SET payload_json='{}' WHERE id=101")
    reader.connection.commit()
    with pytest.raises(ResearchError,match='REGISTRY_INTEGRITY'):
        reader.read_attestation(ref,namespace=manifest().namespace)
