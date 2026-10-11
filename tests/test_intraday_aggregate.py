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


def test_aggregate_revision_selection_matches_original_capture_intake():
    s = prepared()
    s.store.persist((replace(event(s, change={"c": 101}), ingest_sequence=2),))
    s.store.persist((replace(event(s, change={"c": 100}), ingest_sequence=1),))
    rows = s.store.read_as_of("BAR", cutoff_ns=s.clock.now, revisions=True)
    assert read(s)[0]["payload"]["raw"]["c"] == 101
    assert aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=1)["bars"][0]["close"] == 101


def test_future_admission_does_not_change_the_aggregate_prefix_capture_order():
    s = prepared()
    orphan = s.store.persist((replace(event(s, change={"c": 100}), ingest_sequence=1),), admit=False)
    s.store.persist((replace(event(s, change={"c": 100.5}), capture_id="other-capture", ingest_sequence=1),))
    s.store.persist((replace(event(s, change={"c": 101}), ingest_sequence=2),))
    cutoff = s.clock.now
    before = aggregation()(s.store.read_as_of("BAR", cutoff_ns=cutoff, revisions=True),
                           session(), cutoff_ns=cutoff, minutes=1)
    s.clock.now += 1_000_000_000
    s.store.admit(orphan)
    final = s.store.read_as_of("BAR", cutoff_ns=s.clock.now, revisions=True)
    assert aggregation()(final, session(), cutoff_ns=cutoff, minutes=1) == before



def corporate_event(s, *, at=OPEN+2*MINUTE, known=None, revision=1, cancelled=False, effective_end=None):
    return {"id": revision, "provider": "alpaca", "feed": s.profile.feed, "profile_id": s.profile.profile_id,
            "data_mode": "REAL", "provenance": "CAPTURED", "replay_grade": "STRICT_PIT", "listing_id": s.listing,
            "logical_key": "split-synthetic", "capture_id": "corporate-fixture", "ingest_sequence": revision,
            "received_at_ns": s.clock.now if known is None else known,
            "available_at_ns": s.clock.now if known is None else known, "event_type": "CORPORATE_ACTION",
            "effective_at_ns": at, "payload_hash": str(revision)*64,
            "payload": {"discontinuity": True, "family": "reorganizations", "intake_sequence": revision,
                        "effective_end_ns": effective_end, "cancelled": cancelled}}


def test_split_or_reorganization_window_excluded_without_adjusting_raw_prices():
    s = prepared()
    rows = bars(s, 5)
    before = [dict(row["payload"]["raw"]) for row in rows]
    result = aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5, events=[corporate_event(s)])
    assert not result["bars"] and result["exclusions"][0]["reason_code"] == "CORPORATE_ACTION_WINDOW"
    assert [row["payload"]["raw"] for row in rows] == before


def test_future_event_revision_does_not_change_saved_aggregate_prefix():
    s = prepared()
    rows = bars(s, 5)
    cutoff = s.clock.now
    first = corporate_event(s, at=OPEN-1)
    before = aggregation()(rows, session(), cutoff_ns=cutoff, minutes=5, events=[first])
    future = corporate_event(s, revision=2, known=cutoff+1)
    assert aggregation()(rows, session(), cutoff_ns=cutoff, minutes=5, events=[first, future]) == before
    assert not aggregation()(rows, session(), cutoff_ns=cutoff+1, minutes=5, events=[first, future])["bars"]


def test_event_revision_selected_before_window_and_cancellation_filter():
    s = prepared()
    rows = bars(s, 5)
    first = corporate_event(s)
    moved = corporate_event(s, at=OPEN+60*MINUTE, revision=2)
    result = aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5, events=[first, moved])
    assert len(result["bars"]) == 1
    cancelled = corporate_event(s, revision=3, cancelled=True)
    assert len(aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5,
                            events=[first, moved, cancelled])["bars"]) == 1


def test_unknown_effective_time_fails_closed_and_date_only_blocks_whole_day():
    s = prepared()
    rows = bars(s, 5)
    unknown = corporate_event(s, at=None)
    assert not aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5, events=[unknown])["bars"]
    date_only = corporate_event(s, at=OPEN-9*60*MINUTE, effective_end=OPEN+15*60*MINUTE)
    assert not aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5, events=[date_only])["bars"]


def test_corporate_event_cannot_cross_namespace_into_other_mode():
    s = prepared()
    rows = bars(s, 5)
    wrong = {**corporate_event(s), "data_mode": "DEMO"}
    with pytest.raises(ValueError, match="MIXED_NAMESPACE"):
        aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5, events=[wrong])


def test_demo_cancellation_cannot_hide_real_discontinuity_before_namespace_check():
    s = prepared()
    rows = bars(s, 5)
    wrong = {**corporate_event(s, revision=2, cancelled=True), 'data_mode': 'DEMO',
             'provenance': 'SYNTHETIC', 'replay_grade': 'RESEARCH_ONLY'}
    with pytest.raises(ValueError, match='MIXED_NAMESPACE'):
        aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5, events=[corporate_event(s), wrong])


@pytest.mark.parametrize('cancelled', [False, True])
def test_corporate_revision_reopens_bar_only_at_its_knowledge_time(cancelled):
    s = prepared()
    rows = bars(s, 5)
    first = corporate_event(s)
    before = s.clock.now
    s.clock.now += MINUTE
    moved = corporate_event(s, at=OPEN+60*MINUTE, revision=2, cancelled=cancelled)
    result = aggregation()(rows, session(), cutoff_ns=s.clock.now, minutes=5, events=[first, moved])
    assert result['bars'][0]['available_at_ns'] == s.clock.now
    assert result['bars'][0]['event_versions'] == [{'id': 2, 'hash': moved['payload_hash']}]
    assert not aggregation()(rows, session(), cutoff_ns=before, minutes=5, events=[first, moved])['bars']
