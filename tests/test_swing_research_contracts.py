from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest
from swing_research_fixtures import manifest

from backend.app.swing_research.contracts import (
    DataContext,
    InputRef,
    Policy,
    ResourceLimits,
    SwingError,
    TrialConfig,
    canonical_hash,
    canonical_json,
    diagnostic_grid,
    parse_object,
    research_grid,
    trial_grid,
)


def test_fixed_grid_has_14_research_and_six_diagnostics_in_stable_order():
    research = research_grid()
    diagnostics = diagnostic_grid()
    assert len(research) == 14 and len(diagnostics) == 6
    assert len({c.config_hash for c in trial_grid()}) == 20
    assert research[0] == TrialConfig("MOM", 5, "BEST", "RESEARCH", "CANDIDATE")
    assert research[-1] == TrialConfig("WFO", 0, "DIRECT", "RESEARCH", "SELECTOR")
    assert diagnostics[-1] == TrialConfig("BREAKOUT", 1, "DIRECT", "DIAGNOSTIC_ONLY", "CANDIDATE")
    assert all(c.holding_sessions in {5, 21} for c in research[:12])
    assert all(c.holding_sessions == 1 for c in diagnostics)


@pytest.mark.parametrize(
    "args",
    [
        ("MOM", 1, "BEST", "RESEARCH", "CANDIDATE"),
        ("MOM", 5, "BEST", "DIAGNOSTIC_ONLY", "CANDIDATE"),
        ("WFO", 0, "BEST", "DIAGNOSTIC_ONLY", "SELECTOR"),
        ("MOM", True, "BEST", "RESEARCH", "CANDIDATE"),
        ("NEW", 5, "BEST", "RESEARCH", "CANDIDATE"),
        ("MOM", 5, "ALPACA", "RESEARCH", "CANDIDATE"),
    ],
)
def test_no_additional_hypotheses_or_role_confusion(args):
    with pytest.raises(SwingError):
        TrialConfig(*args)


def test_manifest_is_deeply_immutable_and_copies_detached():
    m = manifest()
    with pytest.raises(FrozenInstanceError):
        m.software_hash = "b" * 64
    view = m.to_dict()
    view["policy"]["capital_eur"] = "1"
    view["grid"].clear()
    assert m.to_dict()["policy"]["capital_eur"] == "10000"
    assert len(m.grid) == 20 and m.n_trials == 14
    assert m == type(m).from_dict(parse_object(canonical_json(m.to_dict())))


def test_hash_covers_inputs_fx_benchmark_costs_risk_and_namespace():
    m = manifest()
    for ref in m.inputs:
        new = tuple(replace(x, sha256="f" * 64) if x.kind == ref.kind else x for x in m.inputs)
        assert replace(m, inputs=new).experiment_hash != m.experiment_hash
    for changes in [
        {"software_hash": "b" * 64},
        {"resources": ResourceLimits(4_194_304)},
        {"context": DataContext("RESEARCH_ONLY", "HISTORICAL_CURRENT", "SIP")},
    ]:
        assert replace(m, **changes).experiment_hash != m.experiment_hash
    altered = m.to_dict()
    altered["policy"]["risk_per_position_eur"] = "99"
    assert canonical_hash(altered) != m.experiment_hash
    with pytest.raises(SwingError):
        type(m).from_dict(altered)


def test_grid_reordering_or_missing_trial_is_rejected():
    m = manifest()
    for grid in [tuple(reversed(m.grid)), m.grid[:-1], list(m.grid)]:
        with pytest.raises(SwingError):
            replace(m, grid=grid)


@pytest.mark.parametrize(
    "values",
    [
        ("REAL", "SYNTHETIC", "SIP"),
        ("SYNTHETIC", "CAPTURED", "SIP"),
        ("RESEARCH_ONLY", "HISTORICAL_CURRENT", "SYNTHETIC"),
        ("DEMO", "SYNTHETIC", "SYNTHETIC"),
    ],
)
def test_context_does_not_mix_real_and_synthetic(values):
    with pytest.raises(SwingError):
        DataContext(*values)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.0, Decimal("NaN"), {"x": float("-inf")}])
def test_canonical_json_rejects_floats_and_nonfinite(value):
    with pytest.raises(SwingError):
        canonical_json({"value": value})


@pytest.mark.parametrize("value", ['{"a":1,"a":2}', '{"a":NaN}', "[]", '{"x":"\\ud800"}'])
def test_parse_rejects_duplicates_nonfinite_and_invalid_unicode(value):
    with pytest.raises(SwingError):
        parse_object(value)


def test_decimal_canonicalisation_is_context_independent():
    from decimal import localcontext

    with localcontext() as ctx:
        ctx.prec = 2
        assert canonical_json({"x": Decimal("123.4500")}) == '{"x":"123.45"}'
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_batch_rows", 10001),
        ("max_batch_bytes", 8_388_609),
        ("max_rss_bytes", 2_147_483_649),
        ("max_disk_bytes", True),
        ("max_disk_bytes", 0),
        ("max_disk_bytes", 2**63),
    ],
)
def test_resource_caps_fail_closed(field, value):
    with pytest.raises(SwingError):
        ResourceLimits(**({"max_disk_bytes": 8_388_608} | {field: value}))


def test_frozen_policy_contains_costs_thresholds_dates_and_severe_fx_rule():
    p = Policy().to_dict()
    assert p["research_n"] == 14 and p["capital_eur"] == "10000"
    assert p["holding_research"] == [5, 21] and p["holding_diagnostic"] == [1]
    assert p["bootstrap"] == {"replicas": 10000, "seed": 20261015, "mean_blocks": [63, 21], "alpha_family": "0.05"}
    assert p["costs"]["SEVERE"] == {
        "fee_best_eur": "2",
        "fee_direct_eur": "4",
        "bps_side": 50,
        "delay_minutes": 15,
        "fx_rule": "ZERO_ONLY_EUR_NO_CONVERSION_OTHERWISE_ATTESTED_OR_INSUFFICIENT",
    }
    assert p["sample"]["holdout"] == ["2024-01-02", "2026-09-30"]


def test_input_refs_are_closed_and_all_required_once():
    m = manifest()
    with pytest.raises(SwingError):
        replace(m, inputs=m.inputs[:-1])
    with pytest.raises(SwingError):
        InputRef("api_key", "a" * 64)
    with pytest.raises(SwingError):
        InputRef("FX", "not-a-hash")
