"""Official, versioned US regular sessions with explicit complete-range evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from backend.app.data_providers.alpaca_metadata import (
    AlpacaMetadataService,
    MetadataError,
    captures_as_of,
    check_ns,
    datetime_ns,
    read_evidence,
    scope,
)


def _date(value):
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise MetadataError("METADATA_INVALID") from None


@dataclass(frozen=True)
class CalendarSession:
    version_id: int
    capture_id: int
    session_date: str
    open_at_ns: int
    close_at_ns: int
    known_at_ns: int
    timezone: str = "America/New_York"

    def bucket(self, at_ns, minutes):
        check_ns(at_ns)
        if type(minutes) is not int or minutes not in {1, 5, 15}:
            raise MetadataError("METADATA_INVALID")
        if not self.open_at_ns <= at_ns < self.close_at_ns:
            return None
        width = minutes * 60 * 1_000_000_000
        start = self.open_at_ns + ((at_ns - self.open_at_ns) // width) * width
        return (start, start + width) if start + width <= self.close_at_ns else None


def session_as_of(connection, session_date, cutoff_ns, *, profile_id, data_mode="REAL",
                  provenance="CAPTURED", replay_grade="STRICT_PIT"):
    _date(session_date)
    batches = captures_as_of(connection, cutoff_ns, profile_id=profile_id, data_mode=data_mode,
                            provenance=provenance, replay_grade=replay_grade, metadata_kind="CALENDAR",
                            session_date=session_date, latest_only=True)
    batch = next((item for item in batches if item["payload"]["start"] <= session_date <= item["payload"]["end"]), None)
    if batch is None or batch["payload"].get("complete") is not True:
        raise MetadataError("CALENDAR_MISSING")
    version_id = batch["payload"]["session_ids"].get(session_date)
    if version_id is None:
        return None  # Holiday/closure known from this immutable complete range, never inferred.
    try:
        row = read_evidence(connection, "intraday_calendar_versions", version_id, cutoff_ns,
                            scope(profile_id, data_mode, provenance, replay_grade))
    except MetadataError:
        raise MetadataError("CALENDAR_MISSING") from None
    if row["session_date"] != session_date:
        raise MetadataError("CALENDAR_MISSING")
    return CalendarSession(version_id, batch["id"], session_date, row["open_at_ns"], row["close_at_ns"],
                           max(row["available_at_ns"], batch["available_at_ns"]))


def validate_range(start, end):
    first, last = _date(start), _date(end)
    # The source documents this coverage; an empty out-of-range response proves no holiday.
    if first.year < 1970 or last.year > 2029:
        raise MetadataError("CALENDAR_MISSING")
    if not 0 <= (last - first).days <= 366:
        raise MetadataError("METADATA_INVALID")
    return first, last


class CalendarService:
    def __init__(self, archive: AlpacaMetadataService):
        self.archive = archive

    def record(self, rows, *, start, end, received_at_ns):
        first, last = validate_range(start, end)
        check_ns(received_at_ns)
        self.archive.safe_json({"rows": rows})
        try:
            if not 0 <= (last - first).days <= 366 or type(rows) is not list or len(rows) > 367:
                raise ValueError
            decoded, seen = [], set()
            for item in rows:
                day = _date(item["date"])
                if not first <= day <= last or item["date"] in seen:
                    raise ValueError
                seen.add(item["date"])
                times = []
                for key in ("open", "close"):
                    if not isinstance(item[key], str) or not re.fullmatch(r"\d{2}:\d{2}", item[key]):
                        raise ValueError
                    value = datetime.fromisoformat(f"{item['date']}T{item[key]}").replace(tzinfo=ZoneInfo("America/New_York"))
                    times.append(datetime_ns(value.astimezone(UTC)))
                if times[0] >= times[1]:
                    raise ValueError
                decoded.append((item["date"], *times))
        except (ValueError, KeyError, TypeError):
            raise MetadataError("METADATA_INVALID") from None
        with self.archive.transaction():
            run = self.archive.begin_run()
            versions = {}
            for day, opening, closing in sorted(decoded):
                previous = self.archive.connection.execute("""
                    SELECT id FROM intraday_calendar_versions WHERE profile_id=? AND data_mode=?
                      AND provenance=? AND replay_grade=? AND session_date=? ORDER BY available_at_ns DESC,id DESC LIMIT 1
                """, (*self.archive.namespace, day)).fetchone()
                versions[day] = self.archive.append(
                    "intraday_calendar_versions", run,
                    {"version": "alpaca-calendar-v1", "source": "ALPACA_CALENDAR", "start": start, "end": end,
                     "session_date": day, "open_at_ns": opening, "close_at_ns": closing, "timezone": "America/New_York"},
                    received_at_ns=received_at_ns, event_time_ns=opening, logical_key=f"us-session:{day}",
                    fields={"session_date": day, "open_at_ns": opening, "close_at_ns": closing,
                            "timezone": "America/New_York", "supersedes_id": previous[0] if previous else None},
                )
            result = self.archive.bootstrap(
                run, {"metadata_kind": "CALENDAR", "version": "alpaca-calendar-range-v1", "complete": True,
                      "start": start, "end": end, "member_count": len(versions), "session_ids": versions},
                received_at_ns, f"us-calendar:{start}:{end}",
            )
            self.archive.finish_run(run)
        return result
