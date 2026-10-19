import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from swing_research_fixtures import manifest, registry, request

from backend.app.swing_research.contracts import SwingError, canonical_hash


def register(r):
    return r.register(manifest(), request_id=request("register"), now_ns=1)


def move(r, state, reason, *, name=None, now=2):
    return r.transition(manifest().grid[0].config_hash, state, reason, request_id=request(name or state), now_ns=now)


def test_preregister_all_twenty_atomically_before_any_start(tmp_path):
    r = registry(tmp_path)
    s = register(r)
    assert s.n_trials == 14 and len(s.trials) == 20
    assert {x.state for x in s.trials} == {"REGISTERED"}
    assert s.holdout_state == "SEALED" and s.transaction_count == 1
    assert len(list((tmp_path / "registry").glob("*.json"))) == 1
    started = move(r, "STARTED", "EXECUTION_STARTED")
    assert started.trials[0].state == "STARTED" and started.trials[0].attempt == 1


def test_start_without_preregistration_fails_without_artifact(tmp_path):
    r = registry(tmp_path)
    with pytest.raises(SwingError):
        move(r, "STARTED", "EXECUTION_STARTED")
    assert not list((tmp_path / "registry").glob("*.json"))


@pytest.mark.parametrize(
    "state,reason",
    [
        ("FAILED", "INTERNAL_ERROR"),
        ("CANCELLED", "USER_CANCELLED"),
        ("INTERRUPTED", "EXECUTOR_INTERRUPTED"),
        ("COMPLETED", "NO_TRADES"),
        ("COMPLETED", "FINISHED"),
    ],
)
def test_terminal_and_no_trade_trials_are_never_dropped(tmp_path, state, reason):
    r = registry(tmp_path)
    register(r)
    move(r, "STARTED", "EXECUTION_STARTED")
    s = move(r, state, reason, now=3)
    assert s.n_trials == 14 and len(s.trials) == 20 and s.trials[0].state == state
    assert r.snapshot() == s


def test_replay_idempotency_conflict_and_explicit_retry(tmp_path):
    r = registry(tmp_path)
    initial = register(r)
    assert register(r) == initial
    move(r, "STARTED", "EXECUTION_STARTED")
    move(r, "FAILED", "INTERNAL_ERROR", now=3)
    retry = move(r, "STARTED", "RETRY_STARTED", name="retry", now=4)
    assert retry.trials[0].attempt == 2 and retry.n_trials == 14
    assert move(r, "STARTED", "RETRY_STARTED", name="retry", now=4) == retry
    assert retry.transaction_count == 4
    with pytest.raises(SwingError):
        move(r, "CANCELLED", "USER_CANCELLED", name="retry", now=4)
    assert r.snapshot() == retry


def test_reason_timestamp_unknown_trial_and_completed_restart_are_rejected(tmp_path):
    r = registry(tmp_path)
    register(r)
    for now in [True, -1, 2**63]:
        with pytest.raises(SwingError):
            move(r, "STARTED", "EXECUTION_STARTED", now=now)
    with pytest.raises(SwingError):
        move(r, "STARTED", "FINISHED")
    with pytest.raises(SwingError):
        r.transition("f" * 64, "STARTED", "EXECUTION_STARTED", request_id=request("unknown"), now_ns=2)
    move(r, "STARTED", "EXECUTION_STARTED")
    move(r, "COMPLETED", "FINISHED", now=3)
    with pytest.raises(SwingError):
        move(r, "STARTED", "RETRY_STARTED", name="again", now=4)
    with pytest.raises(SwingError):
        move(r, "CANCELLED", "USER_CANCELLED", now=1)


def test_diagnostic_trials_are_audited_but_outside_denominator(tmp_path):
    r = registry(tmp_path)
    register(r)
    diag = manifest().grid[-1]
    s = r.transition(diag.config_hash, "STARTED", "EXECUTION_STARTED", request_id=request("diag"), now_ns=2)
    assert s.n_trials == 14 and s.trials[-1].config.role == "DIAGNOSTIC_ONLY"


def test_contamination_is_sticky_and_blocks_new_starts(tmp_path):
    r = registry(tmp_path)
    register(r)
    s = r.contaminate_holdout(request_id=request("contaminate"), now_ns=2)
    assert s.holdout_state == "CONTAMINATED"
    assert r.contaminate_holdout(request_id=request("contaminate"), now_ns=2) == s
    with pytest.raises(SwingError):
        move(r, "STARTED", "EXECUTION_STARTED", now=3)
    assert r.snapshot().holdout_state == "CONTAMINATED"


def test_publication_failure_rolls_back_without_orphan_trials(tmp_path, monkeypatch):
    import backend.app.swing_research.registry as module

    r = registry(tmp_path)
    real = module.os.replace

    def fail(*args):
        raise OSError("synthetic-sensitive-path")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(SwingError) as err:
        register(r)
    assert str(err.value) == "REGISTRY_WRITE_FAILED"
    assert not list((tmp_path / "registry").glob("*.json"))
    assert not list((tmp_path / "registry").glob(".pending-*"))
    monkeypatch.setattr(module.os, "replace", real)
    assert register(r).transaction_count == 1


def test_ambiguous_publish_then_retry_is_idempotent(tmp_path, monkeypatch):
    import backend.app.swing_research.registry as module

    r = registry(tmp_path)
    real = module.os.replace

    def published_then_fail(*args):
        real(*args)
        raise OSError("synthetic-after-publish")

    monkeypatch.setattr(module.os, "replace", published_then_fail)
    with pytest.raises(SwingError):
        register(r)
    monkeypatch.setattr(module.os, "replace", real)
    assert register(r).transaction_count == 1


def test_concurrent_registration_has_one_genesis_and_no_interleaving(tmp_path):
    r = registry(tmp_path)

    def attempt(_):
        try:
            return register(r).transaction_count
        except SwingError as error:
            assert error.code == "REGISTRY_BUSY"
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(attempt, range(12)))
    assert any(x == 1 for x in values)
    assert r.snapshot().transaction_count == 1


def test_tampering_missing_transaction_and_unexpected_files_fail_closed(tmp_path):
    r = registry(tmp_path)
    register(r)
    move(r, "STARTED", "EXECUTION_STARTED")
    records = sorted((tmp_path / "registry").glob("*.json"))
    original = records[1].read_bytes()
    data = json.loads(original)
    data["payload"]["state"] = "COMPLETED"
    records[1].write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SwingError):
        r.snapshot()
    records[1].write_bytes(original)
    records[0].unlink()
    with pytest.raises(SwingError):
        r.snapshot()


def test_manifest_change_cannot_reuse_registry(tmp_path):
    from dataclasses import replace

    r = registry(tmp_path)
    register(r)
    with pytest.raises(SwingError):
        r.register(replace(manifest(), software_hash="b" * 64), request_id=request("new"), now_ns=2)


def test_disk_budget_is_enforced_before_publication(tmp_path):
    from dataclasses import replace

    from backend.app.swing_research.contracts import ResourceLimits

    r = registry(tmp_path)
    with pytest.raises(SwingError) as error:
        r.register(replace(manifest(), resources=ResourceLimits(100)), request_id=request("tiny"), now_ns=1)
    assert error.value.code == "RESOURCE_LIMIT"
    assert not list((tmp_path / "registry").glob("*.json"))


def test_same_payload_new_request_is_not_silently_another_registration(tmp_path):
    r = registry(tmp_path)
    register(r)
    with pytest.raises(SwingError):
        r.register(manifest(), request_id=canonical_hash({"other": "request"}), now_ns=2)


def test_replay_requires_exact_canonical_bytes(tmp_path):
    r = registry(tmp_path)
    register(r)
    record = next((tmp_path / "registry").glob("*.json"))
    record.write_bytes(record.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(SwingError, match="^REGISTRY_INTEGRITY$"):
        r.snapshot()


def test_process_lock_excludes_other_writer_and_recovers_after_crash(tmp_path):
    r = registry(tmp_path)
    register(r)
    script = """
import os
import sys
from pathlib import Path
from backend.app.swing_research.registry import Registry
r = Registry(input_root=Path(sys.argv[1]), output_root=Path(sys.argv[2]))
with r._lock():
    print('LOCKED', flush=True)
    sys.stdin.read(1)
    os._exit(0)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "input"), str(tmp_path / "registry")],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "LOCKED"
        with pytest.raises(SwingError, match="^REGISTRY_BUSY$"):
            move(r, "STARTED", "EXECUTION_STARTED")
        process.communicate("x", timeout=10)
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    assert move(r, "STARTED", "EXECUTION_STARTED").transaction_count == 2


@pytest.mark.parametrize("state,reason", [("CANCELLED", "USER_CANCELLED"), ("REJECTED", "INPUT_NOT_ELIGIBLE")])
def test_unstarted_trials_can_be_cancelled_or_rejected_without_disappearing(tmp_path, state, reason):
    r = registry(tmp_path)
    register(r)
    snapshot = move(r, state, reason)
    assert snapshot.trials[0].attempt == 0
    assert snapshot.trials[0].state == state
    assert snapshot.n_trials == 14 and len(snapshot.trials) == 20


def test_failed_append_preserves_prior_records_byte_for_byte(tmp_path, monkeypatch):
    import backend.app.swing_research.registry as module

    r = registry(tmp_path)
    before = register(r)
    record = next((tmp_path / "registry").glob("*.json"))
    raw = record.read_bytes()

    def fail(*args):
        raise OSError("synthetic-write-failure")

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "fsync", fail)
        with pytest.raises(SwingError, match="^REGISTRY_WRITE_FAILED$"):
            move(r, "STARTED", "EXECUTION_STARTED")
    assert record.read_bytes() == raw
    assert r.snapshot() == before
    assert not list((tmp_path / "registry").glob(".pending-*"))


def test_clock_cannot_regress_when_starting_another_trial(tmp_path):
    r = registry(tmp_path)
    register(r)
    move(r, "STARTED", "EXECUTION_STARTED", now=5)
    with pytest.raises(SwingError, match="^INVALID_TRANSITION$"):
        r.transition(
            manifest().grid[1].config_hash, "STARTED", "EXECUTION_STARTED", request_id=request("old"), now_ns=4
        )


def test_marker_initialisation_stale_size_cannot_write_before_lock(tmp_path, monkeypatch):
    """A stale empty-file observation must still acquire the OS lock first."""
    import threading

    import backend.app.swing_research.registry as module

    r = registry(tmp_path)
    original_stat = module.os.fstat
    ready = threading.Event()
    owner_locked = threading.Event()
    waiter_done = threading.Event()
    stale = []
    errors = []
    results = []

    def controlled_stat(fd):
        if threading.current_thread().name == "sp3s-init-waiter":
            if not stale:
                stale.append(original_stat(fd))
                assert stale[0].st_size == 0
                ready.set()
                assert owner_locked.wait(5)
            return stale[0]
        return original_stat(fd)

    def waiter():
        try:
            with r._lock():
                results.append("UNEXPECTED_LOCK")
        except SwingError as error:
            results.append(error.code)
        except BaseException as error:
            errors.append(type(error).__name__)
        finally:
            waiter_done.set()

    def owner():
        try:
            with r._lock():
                owner_locked.set()
                assert waiter_done.wait(5)
        except BaseException as error:
            errors.append(type(error).__name__)

    monkeypatch.setattr(module.os, "fstat", controlled_stat)
    waiting = threading.Thread(target=waiter, name="sp3s-init-waiter")
    holding = threading.Thread(target=owner, name="sp3s-init-owner")
    waiting.start()
    assert ready.wait(5)
    holding.start()
    waiting.join(10)
    holding.join(10)
    assert not waiting.is_alive() and not holding.is_alive()
    assert not errors
    assert results == ["REGISTRY_BUSY"]
