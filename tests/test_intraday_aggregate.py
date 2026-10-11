from __future__ import annotations

import importlib
from dataclasses import replace

import pytest
from test_intraday_store import MINUTE, OPEN, event, prepared, read

from backend.app.intraday.calendar import CalendarSession


def aggregation():
    return importlib.import_module("backend.app.intraday.aggregate").aggregate_as_of


def session(close=OPEN + 390 * MINUTE):
    return CalendarSession(1, 1, "2026-10-12", OPEN, close, OPEN - MINUTE)


def bars(s, count=15):
    for i in range(count):
        s.store.persist((event(s, at=OPEN + i * MINUTE,
                              change={"o": 100 + i, "h": 102 + i, "l": 99 + i, "c": 101 + i,
                                      "vw": 100.5 + i, "v": i + 1}),))
    return read(s)


@pytest.mark.parametrize("minutes", [1, 5, 15])
def test_complete_closed_ohlc_volume_vwap_computed_by_hand(minutes):
    s = prepared()
    rows = bars(s)
    result = aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=minutes)
    first = result["bars"][0]
    assert first["open"] == 100 and first["high"] == 101 + minutes and first["low"] == 99
    assert first["close"] == 100 + minutes and first["volume"] == sum(range(1, minutes + 1))
    assert first["vwap"] == pytest.approx(sum((100.5 + i) * (i + 1) for i in range(minutes)) / first["volume"])
    assert first["end_at_ns"] == OPEN + minutes * MINUTE and first["complete"]


@pytest.mark.parametrize("count,cutoff,reason", [(4, 30, "MISSING_MINUTE"), (5, 4, "GROUP_NOT_CLOSED")])
def test_incomplete_group_has_no_synthetic_minutes(count, cutoff, reason):
    s = prepared()
    rows = bars(s, count)
    # Historical already known rows are cut off by the market interval as well.
    result = aggregation()(rows, session(), cutoff_ns=OPEN + cutoff * MINUTE, minutes=5)
    assert not result["bars"]
    assert reason in {entry["reason_code"] for entry in result["exclusions"]}


def test_future_revision_is_filtered_and_quarantine_excludes_complete_group():
    s = prepared()
    bars(s, 5)
    cutoff = s.clock.now
    before = aggregation()(read(s), session(), cutoff_ns=cutoff, minutes=5)
    s.clock.now += MINUTE
    s.store.persist((event(s, at=OPEN, change={"c": 105}),))
    all_rows = s.store.read_as_of("BAR", cutoff_ns=s.clock.now, revisions=True)
    assert aggregation()(all_rows, session(), cutoff_ns=cutoff, minutes=5) == before
    after = aggregation()(all_rows, session(), cutoff_ns=s.clock.now, minutes=5)
    assert not after["bars"] and "QUARANTINED_MINUTE" in {x["reason_code"] for x in after["exclusions"]}


@pytest.mark.parametrize("field,value", [("feed", "iex"), ("profile_id", "a" * 64), ("data_mode", "DEMO"),
                                        ("provenance", "HISTORICAL_CURRENT"), ("replay_grade", "RESEARCH_ONLY")])
def test_mixed_namespace_is_rejected(field, value):
    s = prepared()
    rows = bars(s, 5)
    rows[1] = {**rows[1], field: value}
    with pytest.raises(ValueError, match="MIXED_NAMESPACE"):
        aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5)


def test_early_close_out_of_session_and_missing_vwap_zero_volume():
    s = prepared()
    rows = bars(s, 5)
    result = aggregation()(rows, session(OPEN + 4 * MINUTE), cutoff_ns=s.clock.now, minutes=5)
    assert not result["bars"] and result["exclusions"]
    s = prepared()
    for i in range(5):
        s.store.persist((event(s, at=OPEN + i * MINUTE, change={"v": 0, "vw": None}),))
    result = aggregation()(read(s), session(), cutoff_ns=s.clock.now, minutes=5)
    assert result["bars"][0]["vwap"] is None and result["bars"][0]["volume"] == 0


def test_warmup_and_unknown_status_do_not_claim_ready():
    s = prepared()
    result = aggregation()(bars(s, 5), session(), cutoff_ns=s.clock.now, minutes=5, warmup_bars=2)
    assert result["warmup_complete"] is False and result["status_coverage"] == "UNKNOWN"
    assert result["bars"][0]["signal_eligible"] is False


def test_calendar_not_known_at_cutoff_and_bad_width_rejected():
    s = prepared()
    rows = bars(s, 5)
    with pytest.raises(ValueError, match="CALENDAR_NOT_KNOWN"):
        aggregation()(rows, replace(session(), known_at_ns=s.clock.now + 1), cutoff_ns=s.clock.now, minutes=5)
    with pytest.raises(ValueError):
        aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=30)


def test_aggregate_availability_includes_calendar_knowledge():
    s = prepared()
    rows = bars(s, 5)
    late = replace(session(), known_at_ns=s.clock.now + 1)
    result = aggregation()(rows, late, cutoff_ns=s.clock.now + 1, minutes=5)
    assert result["bars"][0]["available_at_ns"] >= late.known_at_ns


def test_numeric_overflow_is_an_explicit_exclusion_and_large_finite_vwap_is_stable():
    s = prepared()
    for i in range(5):
        s.store.persist((event(s, at=OPEN + i * MINUTE, change={"v": 1e308}),))
    result = aggregation()(read(s), session(), cutoff_ns=s.clock.now, minutes=5)
    assert not result["bars"] and "NUMERIC_OVERFLOW" in {row["reason_code"] for row in result["exclusions"]}
    result = aggregation()(read(s), session(), cutoff_ns=s.clock.now, minutes=1)
    assert result["bars"][0]["vwap"] == 100.5


def test_unknown_and_delayed_venue_feeds_are_advisory_and_never_signal_eligible():
    s = prepared(profile_overrides={"feed": "iex"})
    result = aggregation()(bars(s, 5), session(), cutoff_ns=s.clock.now, minutes=5)
    assert result["bars"][0]["namespace"][1] == "iex"
    assert not result["bars"][0]["signal_eligible"]


def test_backlogged_old_revision_is_not_latest_aggregate_input():
    s = prepared()
    early = event(s, change={"c": 100})
    s.clock.now += 1
    bars(s, 5)
    s.clock.now += 1
    s.store.persist((early,))
    rows = s.store.read_as_of("BAR", cutoff_ns=s.clock.now, revisions=True)
    result = aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=1)
    assert result["bars"][0]["close"] == 101
