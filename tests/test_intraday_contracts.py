from __future__ import annotations

import importlib
import json
from dataclasses import FrozenInstanceError

import pytest
from intraday_fixtures import NS, envelope_args


def contracts():
    return importlib.import_module("backend.app.intraday.contracts")


def test_ns_precision_and_queue_admission_are_causal():
    c = contracts()
    event = c.EventEnvelope(**envelope_args())
    next_event = c.EventEnvelope(**envelope_args(event_time_ns=NS + 1))
    assert next_event.event_time_ns - event.event_time_ns == 1
    assert event.available_at_ns == NS + 8
    assert not event.is_available_at(NS + 5)
    assert event.is_available_at(NS + 8)
    raw = c.EventEnvelope(**envelope_args(admitted_at_ns=None))
    assert raw.available_at_ns is None
    assert not raw.is_available_at(NS + 100)


@pytest.mark.parametrize("value", [True, 1.5, "1700000000000000000", -1, 2**63])
def test_invalid_ns_are_rejected_without_coercion(value):
    c = contracts()
    with pytest.raises(c.IntradayError, match="INVALID_TIMESTAMP"):
        c.EventEnvelope(**envelope_args(event_time_ns=value))


@pytest.mark.parametrize(
    "changes",
    [
        {"persisted_at_ns": NS + 1},
        {"admitted_at_ns": NS + 2},
        {"ingest_sequence": True},
        {"listing_id": False},
    ],
)
def test_invalid_order_sequence_or_identity(changes):
    c = contracts()
    with pytest.raises(c.IntradayError):
        c.EventEnvelope(**envelope_args(**changes))


def test_clock_validation_is_explicit_and_effective_dates_can_be_future():
    c = contracts()
    event = c.EventEnvelope(**envelope_args())
    with pytest.raises(c.IntradayError, match="INVALID_TIMESTAMP"):
        event.validate_at(NS + 7)
    event.validate_at(NS + 8)
    scheduled = c.EventEnvelope(**envelope_args(kind="EVENT", event_time_ns=NS + 1000))
    scheduled.validate_at(NS + 8)
    assert scheduled.available_at_ns == NS + 8


@pytest.mark.parametrize(
    "payload", ['{"x":NaN}', '{"x":[Infinity]}', '{"x":-Infinity}', '{"x":1e999}', "[]", '{"x":', '{"x":1,"x":2}']
)
def test_non_finite_or_ambiguous_json_is_rejected(payload):
    c = contracts()
    with pytest.raises(c.IntradayError, match="INVALID_JSON"):
        c.EventEnvelope(**envelope_args(payload_json=payload))


def test_json_is_canonical_and_payload_copies_cannot_mutate_hash():
    c = contracts()
    event = c.EventEnvelope(**envelope_args(payload_json='{"z":[1,{"x":2}],"a":0}'))
    old_hash = event.payload_hash
    event.payload["z"][1]["x"] = 9
    assert event.payload["z"][1]["x"] == 2
    assert event.payload_hash == old_hash
    assert event.payload_json == '{"a":0,"z":[1,{"x":2}]}'
    same = c.EventEnvelope(**envelope_args(payload_json='{"a":0,"z":[1,{"x":2}]}'))
    assert same.payload_hash == old_hash
    with pytest.raises(FrozenInstanceError):
        event.received_at_ns = NS


@pytest.mark.parametrize(
    "payload", [{"x": float("nan")}, {"x": [float("inf")]}, {1: "bad"}, {"x": object()}, {"x": (1, 2)}]
)
def test_canonical_json_rejects_non_json_inputs(payload):
    c = contracts()
    with pytest.raises(c.IntradayError, match="INVALID_JSON"):
        c.canonical_json(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"data_mode": "DEMO"},
        {"provenance": "HISTORICAL_CURRENT"},
        {"provenance": "SYNTHETIC"},
        {"feed": "unknown"},
        {"kind": "ORDER"},
    ],
)
def test_invalid_mode_grade_or_feed(changes):
    c = contracts()
    with pytest.raises(c.IntradayError):
        c.EventEnvelope(**envelope_args(**changes))


def test_current_history_and_synthetic_real_are_research_only():
    c = contracts()
    for provenance in ("HISTORICAL_CURRENT", "SYNTHETIC"):
        event = c.EventEnvelope(**envelope_args(provenance=provenance, replay_grade="RESEARCH_ONLY"))
        assert event.replay_grade == "RESEARCH_ONLY"


def test_public_profile_is_frozen_and_has_no_auth_fields():
    c = contracts()
    profile = c.FeedProfile(feed="iex")
    assert len(profile.profile_id) == 64
    assert not profile.ready_for_capture
    sip = c.FeedProfile(feed="sip")
    assert sip.attested_capabilities == ()
    assert profile.profile_id != sip.profile_id
    public = json.loads(profile.config_json)
    assert "api_key" not in public and "secret" not in public
    with pytest.raises(TypeError):
        c.FeedProfile(feed="sip", api_key="generated")


@pytest.mark.parametrize(
    "changes",
    [
        {"max_symbols": -1},
        {"max_connections": True},
        {"http_minute_limit": float("inf")},
        {"attested_capabilities": ["quotes"]},
        {"feed": "auto"},
        {"delay_ns": -1},
    ],
)
def test_invalid_profile_caps(changes):
    c = contracts()
    with pytest.raises(c.IntradayError):
        c.FeedProfile(**{"feed": "sip", **changes})


def test_v1_quality_policy_is_frozen_ex_ante():
    c = contracts()
    policy = c.QualityPolicy()
    assert (policy.min_sessions, policy.min_listings) == (20, 10)
    assert (policy.raw_coverage_min, policy.usable_grid_min) == (0.99, 0.90)
    assert policy.timeframes_minutes == (1, 5, 15)
    assert policy.decision_delay_ns == 10_000_000_000
    assert policy.quote_max_age_ns == 2_000_000_000
    assert policy.bar_max_delay_ns == 10_000_000_000
    assert policy.min_usable_points == 1
    assert (policy.required_feed, policy.data_mode, policy.provenance, policy.replay_grade) == (
        "sip",
        "REAL",
        "CAPTURED",
        "STRICT_PIT",
    )
    assert len(policy.policy_hash) == 64
    with pytest.raises(TypeError):
        c.QualityPolicy(min_sessions=1)
    with pytest.raises(FrozenInstanceError):
        policy.min_sessions = 1


def test_invalid_json_error_does_not_echo_input():
    c = contracts()
    sentinel = "SENTINEL_" + "PRIVATE_VALUE_123456"
    with pytest.raises(c.IntradayError) as caught:
        c.EventEnvelope(**envelope_args(payload_json=sentinel))
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)


@pytest.mark.parametrize("kind", ["QUOTE", "NEWS", "IDENTITY", "UNIVERSE"])
def test_event_cannot_be_future_at_receive_even_when_final_clock_is_later(kind):
    c = contracts()
    event = c.EventEnvelope(**envelope_args(kind=kind, event_time_ns=NS + 7))
    with pytest.raises(c.IntradayError, match="INVALID_TIMESTAMP"):
        event.validate_at(NS + 8)
    event.validate_at(NS + 8, max_clock_skew_ns=5)


def test_unicode_payload_roundtrip_and_final_size_limit():
    c = contracts()
    payload = json.dumps({"text": "é" * 350_000}, ensure_ascii=False)
    event = c.EventEnvelope(**envelope_args(payload_json=payload))
    assert len(event.payload_json.encode("utf-8")) <= 1_048_576
    restored = c.EventEnvelope(**envelope_args(payload_json=event.payload_json))
    assert restored.payload_hash == event.payload_hash
    with pytest.raises(c.IntradayError, match="INVALID_JSON"):
        c.canonical_json({"text": "é" * 600_000})


@pytest.mark.parametrize("payload", [{"x": "\ud800"}, {"x": 10**400}])
def test_non_utf8_or_sqlite_infinite_json_numbers_are_rejected(payload):
    c = contracts()
    with pytest.raises(c.IntradayError, match="INVALID_JSON"):
        c.canonical_json(payload)


def test_delay_is_derived_from_feed_and_conflicting_declarations_fail():
    c = contracts()
    assert c.FeedProfile(feed="delayed_sip").delay_ns == 900_000_000_000
    assert c.FeedProfile(feed="sip").delay_ns == 0
    for feed, delay in (("delayed_sip", 0), ("sip", 900_000_000_000)):
        with pytest.raises(c.IntradayError, match="PROFILE_INVALID"):
            c.FeedProfile(feed=feed, delay_ns=delay)


@pytest.mark.parametrize(
    "changes",
    [
        {"required_capabilities": ()},
        {"required_capabilities": ("invented",), "attested_capabilities": ("invented",)},
        {"attested_capabilities": ("invented",)},
    ],
)
def test_empty_or_unknown_capabilities_do_not_attest_capture(changes):
    c = contracts()
    with pytest.raises(c.IntradayError, match="PROFILE_INVALID"):
        c.FeedProfile(feed="sip", **changes)


def test_known_capabilities_and_positive_budgets_are_both_required():
    c = contracts()
    caps = {
        "max_symbols": 10,
        "max_connections": 1,
        "http_minute_limit": 1,
        "http_daily_limit": 1,
        "http_monthly_limit": 1,
        "max_frame_bytes": 100,
        "max_queue_events": 10,
        "max_archive_bytes": 100,
    }
    profile = c.FeedProfile(feed="sip", required_capabilities=("bars",), attested_capabilities=("bars",), **caps)
    assert profile.ready_for_capture
    assert not c.FeedProfile(
        feed="sip", required_capabilities=("bars",), attested_capabilities=(), **caps
    ).ready_for_capture
