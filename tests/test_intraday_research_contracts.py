from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from intraday_research_fixtures import HASH, NS, manifest

from backend.app.intraday_research.contracts import (
    CandidateConfig,
    DatasetRef,
    ResearchError,
    ResearchNamespace,
    ResourceLimits,
    canonical_hash,
    parse_object,
    trial_grid,
)


def test_twenty_unique_configs_ten_policies_and_stable_order():
    grid = trial_grid()
    assert len(grid) == 20
    assert len({config.config_hash for config in grid}) == 20
    assert len({config.policy_key for config in grid}) == 10
    assert grid[0] == CandidateConfig("TREND_PULLBACK", 15, "TECH_ONLY", "R0")
    assert grid[-1] == CandidateConfig("NEWS_ONLY", 30, "NEWS_ONLY", "R1")
    assert sum(config.arm == "NEWS_ONLY" for config in grid) == 4


@pytest.mark.parametrize("changes", [
    {"start_at_ns": True}, {"end_at_ns": float(NS)},
    {"cutoff_ns": 2**63}, {"start_at_ns": -1},
    {"end_at_ns": NS}, {"cutoff_ns": NS},
])
def test_manifest_rejects_invalid_or_inexact_int64(changes):
    with pytest.raises(ResearchError):
        manifest(**changes)


def test_manifest_preserves_nanoseconds_and_is_deeply_immutable():
    saved = manifest(end_at_ns=NS + 1, cutoff_ns=NS + 2)
    assert parse_object(saved.config_json)["end_at_ns"] == NS + 1
    with pytest.raises(FrozenInstanceError):
        saved.cutoff_ns = NS + 3
    copy = saved.to_dict()
    copy["resources"]["max_listings"] = 999
    assert saved.resources.max_listings == 30


@pytest.mark.parametrize("args", [
    ("DEMO", "CAPTURED", "STRICT_PIT"),
    ("DEMO", "SYNTHETIC", "STRICT_PIT"),
    ("REAL", "HISTORICAL_CURRENT", "STRICT_PIT"),
    ("REAL", "SYNTHETIC", "STRICT_PIT"),
])
def test_namespace_rejects_mixed_modes(args):
    with pytest.raises(ResearchError):
        ResearchNamespace(HASH, "sip", *args)


@pytest.mark.parametrize("field", [
    "max_disk_bytes", "min_free_bytes", "max_listings", "max_chunk_occurrences",
    "max_chunk_bytes", "max_cache_bytes", "max_rss_bytes", "window_sessions", "history_sessions",
])
@pytest.mark.parametrize("bad", [0, -1, True, float("nan"), 2**63])
def test_resources_require_bounded_positive_exact_caps(field, bad):
    values = {"max_disk_bytes": 4_294_967_296, "min_free_bytes": 536_870_912}
    values[field] = bad
    with pytest.raises(ResearchError):
        ResourceLimits(**values)


@pytest.mark.parametrize("text", [
    '{"x":NaN}', '{"x":[Infinity]}', '{"x":1e999}',
    '{"x":1,"x":2}', '[]', '{"x":"\\ud800"}',
])
def test_json_rejects_nonfinite_duplicate_keys_and_invalid_unicode(text):
    with pytest.raises(ResearchError):
        parse_object(text)


def test_config_hash_and_experiment_hash_have_distinct_scope():
    first = manifest()
    changed = replace(first, datasets=(DatasetRef(2, "d" * 64),))
    assert first.grid[0].config_hash == changed.grid[0].config_hash
    assert first.experiment_hash != changed.experiment_hash
    assert first.experiment_hash == manifest().experiment_hash
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


@pytest.mark.parametrize("args", [
    ("TREND_PULLBACK", 15, "NEWS_ONLY", "R0"),
    ("NEWS_ONLY", 15, "TECH_ONLY", "R0"),
    ("BREAKOUT_CONTINUATION", 5, "TECH_ONLY", "R0"),
    ("TREND_PULLBACK", 15, "TECH_ONLY", "R2"),
])
def test_invalid_candidate_grid_cannot_create_extra_hypotheses(args):
    with pytest.raises(ResearchError):
        CandidateConfig(*args)


def test_manifest_freezes_split_cost_seed_thresholds_without_promotion():
    body = manifest().to_dict()
    assert body["split"]["is_sessions"] == 126
    assert body["split"]["oos_sessions"] == 63
    assert body["split"]["oos_blocks"] == 4
    assert body["split"]["holdout_sessions"] == 63
    assert body["split"]["embargo_sessions"] == 1
    assert body["statistics"]["seed"] == 137
    assert body["statistics"]["bootstrap_blocks"] == [1, 5, 10]
    assert body["costs"]["status"] == "UNVERIFIED"
    assert body["gate"]["economic_status"] == "NOT_EVALUATED"
    assert body["gate"]["mean_trade_bps"] == 5
    assert body["execution"]["holding_origin"] == "FIRST_FILL"


@pytest.mark.parametrize("field", ["family", "arm", "risk_id"])
def test_unhashable_candidate_fields_have_fixed_contract_error(field):
    values = {"family": "TREND_PULLBACK", "holding_minutes": 15, "arm": "TECH_ONLY", "risk_id": "R0"}
    values[field] = []
    with pytest.raises(ResearchError, match="INVALID_CONTRACT"):
        CandidateConfig(**values)


@pytest.mark.parametrize("field", ["feed", "data_mode", "provenance", "replay_grade"])
def test_unhashable_namespace_fields_have_fixed_contract_error(field):
    values = {"profile_id": HASH, "feed": "sip", "data_mode": "REAL", "provenance": "CAPTURED", "replay_grade": "STRICT_PIT"}
    values[field] = {}
    with pytest.raises(ResearchError, match="NAMESPACE_MISMATCH"):
        ResearchNamespace(**values)


def test_bootstrap_budget_freezes_minimum_and_adaptive_rule_before_runs():
    stats = manifest().to_dict()["statistics"]
    assert stats["minimum_bootstrap_replicates"] == 10_000
    assert stats["replicates_rule"] == "max(10000,ceil(minimum_tail_replicates*M/alpha))"
