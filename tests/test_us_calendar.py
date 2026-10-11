from __future__ import annotations

import importlib

import pytest
from test_intraday_identity import SECOND, ns, system


def calendar(s, rows, start, end):
    return s.calendar.record(rows, start=start, end=end, received_at_ns=s.clock.now)


def session(s, day, *, cutoff=None):
    module = importlib.import_module("backend.app.intraday.calendar")
    return module.session_as_of(s.db, day, cutoff or s.clock.now, profile_id=s.profile.profile_id,
                               data_mode=s.archive.data_mode, provenance=s.archive.provenance,
                               replay_grade=s.archive.replay_grade)


@pytest.mark.parametrize("day,opening", [
    ("2026-03-06", "2026-03-06T14:30:00Z"), ("2026-03-09", "2026-03-09T13:30:00Z"),
    ("2026-03-30", "2026-03-30T13:30:00Z"), ("2026-10-30", "2026-10-30T13:30:00Z"),
    ("2026-11-02", "2026-11-02T14:30:00Z"),
])
def test_us_dst_conversion_does_not_follow_europe(day, opening):
    s = system()
    calendar(s, [{"date": day, "open": "09:30", "close": "16:00"}], day, day)
    result = session(s, day)
    assert result.open_at_ns == ns(opening)
    assert result.close_at_ns - result.open_at_ns == 390 * 60 * SECOND


def test_half_day_and_groups_are_anchored_to_regular_open():
    s = system()
    calendar(s, [{"date": "2026-11-27", "open": "09:30", "close": "13:00",
                  "session_open": "0400", "session_close": "2000"}], "2026-11-27", "2026-11-27")
    result = session(s, "2026-11-27")
    assert result.close_at_ns == ns("2026-11-27T18:00:00Z")
    assert result.bucket(result.open_at_ns + 7 * 60 * SECOND, 5) == (
        result.open_at_ns + 5 * 60 * SECOND, result.open_at_ns + 10 * 60 * SECOND,
    )
    assert result.bucket(result.open_at_ns + 17 * 60 * SECOND, 15)[0] == result.open_at_ns + 15 * 60 * SECOND
    assert result.bucket(result.open_at_ns - 1, 5) is None
    assert result.bucket(result.close_at_ns, 5) is None


def test_empty_complete_calendar_attests_holiday_but_not_unrequested_days():
    s = system()
    calendar(s, [], "2026-07-03", "2026-07-03")
    assert session(s, "2026-07-03") is None
    with pytest.raises(ValueError, match="CALENDAR_MISSING"):
        session(s, "2026-07-06")


def test_future_calendar_revision_preserves_previous_cutoff():
    s = system()
    day = "2026-11-27"
    first_capture = calendar(s, [{"date": day, "open": "09:30", "close": "13:00"}], day, day)
    cutoff = s.clock.now
    before = session(s, day)
    s.clock.now += SECOND
    second_capture = calendar(s, [{"date": day, "open": "09:30", "close": "16:00"}], day, day)
    assert session(s, day, cutoff=cutoff) == before
    assert session(s, day).close_at_ns != before.close_at_ns
    assert first_capture != second_capture


def test_revision_removing_a_session_does_not_resurrect_older_session():
    s = system()
    day = "2026-10-12"
    calendar(s, [{"date": day, "open": "09:30", "close": "16:00"}], day, day)
    cutoff = s.clock.now
    s.clock.now += SECOND
    calendar(s, [], day, day)
    assert session(s, day) is None
    assert session(s, day, cutoff=cutoff) is not None


def test_missing_or_future_calendar_is_not_a_guessed_weekday():
    s = system()
    with pytest.raises(ValueError, match="CALENDAR_MISSING"):
        session(s, "2026-10-12")
    cutoff = s.clock.now
    s.clock.now += SECOND
    calendar(s, [{"date": "2026-10-12", "open": "09:30", "close": "16:00"}], "2026-10-12", "2026-10-12")
    with pytest.raises(ValueError, match="CALENDAR_MISSING"):
        session(s, "2026-10-12", cutoff=cutoff)


@pytest.mark.parametrize("rows", [
    [{"date": "2026-10-12", "open": "16:00", "close": "09:30"}],
    [{"date": "2026-10-12", "open": "9:30", "close": "16:00"}],
    [{"date": "2026-10-13", "open": "09:30", "close": "16:00"}],
    [{"date": "2026-10-12", "open": "09:30", "close": "16:00"}] * 2,
])
def test_invalid_calendar_is_atomic(rows):
    s = system()
    with pytest.raises(ValueError, match="METADATA_INVALID"):
        calendar(s, rows, "2026-10-12", "2026-10-12")
    assert s.db.execute("SELECT COUNT(*) FROM intraday_calendar_versions").fetchone()[0] == 0
    assert s.db.execute("SELECT COUNT(*) FROM intraday_capture_events").fetchone()[0] == 0


def test_metadata_refresh_uses_bounded_calendar_get_without_prerequisites():
    s = system()
    s.queue.append([{"date": "2026-10-12", "open": "09:30", "close": "16:00"}])
    s.archive.refresh_calendar("2026-10-12", "2026-10-12")
    assert session(s, "2026-10-12") is not None
    assert s.requests[0].method == "GET" and s.requests[0].url.path == "/v2/calendar"
    assert dict(s.requests[0].url.params) == {"start": "2026-10-12", "end": "2026-10-12", "date_type": "TRADING"}


def test_short_terminal_group_is_not_presented_as_a_complete_timeframe():
    s = system()
    day = "2026-10-12"
    calendar(s, [{"date": day, "open": "09:30", "close": "09:37"}], day, day)
    result = session(s, day)
    assert result.bucket(result.open_at_ns + 4 * 60 * SECOND, 5) is not None
    assert result.bucket(result.open_at_ns + 6 * 60 * SECOND, 5) is None


@pytest.mark.parametrize("day", ["1969-12-31", "2030-01-02"])
def test_empty_calendar_outside_documented_source_coverage_is_missing(day):
    s = system()
    with pytest.raises(ValueError, match="CALENDAR_MISSING"):
        calendar(s, [], day, day)
    with pytest.raises(ValueError, match="CALENDAR_MISSING"):
        session(s, day)
