"""Pure closed-bar aggregation, with explicit gaps and no synthetic minutes."""
from __future__ import annotations

import math

from backend.app.data_providers.alpaca_metadata import check_ns

MINUTE_NS = 60_000_000_000


def aggregate_as_of(rows, session, *, cutoff_ns, minutes, warmup_bars=0, events=()):
    check_ns(cutoff_ns)
    if type(minutes) is not int or minutes not in {1, 5, 15} or type(warmup_bars) is not int or warmup_bars < 0:
        raise ValueError("AGGREGATE_INVALID")
    if session.known_at_ns > cutoff_ns:
        raise ValueError("CALENDAR_NOT_KNOWN")
    namespace = None
    latest = {}
    exclusions = []
    rows = list(rows)
    captures = {}
    for row in rows:
        if row["kind"] == "BAR" and row["available_at_ns"] is not None and row["available_at_ns"] <= cutoff_ns:
            key = (row["listing_id"], row["event_time_ns"], row["received_at_ns"], row["capture_id"])
            captures[key] = min(captures.get(key, row["id"]), row["id"])
    def order(row):
        key = (row["listing_id"], row["event_time_ns"], row["received_at_ns"], row["capture_id"])
        return (row["received_at_ns"], captures[key],
                row.get("capture_ingest_sequence", row["payload"].get("intake_sequence", row["ingest_sequence"])),
                row["ingest_sequence"], row["id"])
    for row in rows:
        if row["kind"] != "BAR" or row["available_at_ns"] is None or row["available_at_ns"] > cutoff_ns:
            continue
        key = tuple(row[name] for name in ("provider", "feed", "profile_id", "data_mode", "provenance", "replay_grade", "listing_id"))
        if namespace is not None and namespace != key:
            raise ValueError("MIXED_NAMESPACE")
        namespace = key
        at = row["event_time_ns"]
        if not session.open_at_ns <= at < session.close_at_ns or (at - session.open_at_ns) % MINUTE_NS:
            exclusions.append({"start_at_ns": at, "reason_code": "OUT_OF_SESSION_OR_GRID"})
            continue
        previous = latest.get(at)
        if previous is None or order(row) > order(previous):
            latest[at] = row
    corporate = _corporate_as_of(events, cutoff_ns, namespace)
    width = minutes * MINUTE_NS
    bars = []
    start = session.open_at_ns
    while start < min(session.close_at_ns, cutoff_ns):
        end = start + width
        reason = None
        if end > session.close_at_ns:
            reason = "SESSION_INCOMPLETE_GROUP"
        elif end > cutoff_ns:
            reason = "GROUP_NOT_CLOSED"
        elif any(_crosses_action(event, start, end) for event in corporate):
            reason = "CORPORATE_ACTION_WINDOW"
        else:
            members = [latest.get(start + offset * MINUTE_NS) for offset in range(minutes)]
            if any(row is None for row in members):
                reason = "MISSING_MINUTE"
            elif any(row["bar_end_ns"] != row["event_time_ns"] + MINUTE_NS or row["bar_end_ns"] > cutoff_ns for row in members):
                reason = "GROUP_NOT_CLOSED"
            elif any(row["quality"] != "VALID" for row in members):
                reason = "QUARANTINED_MINUTE"
            else:
                raw = [row["payload"]["raw"] for row in members]
                volume = sum(row["v"] for row in raw)
                try:
                    if not math.isfinite(volume):
                        raise OverflowError
                    # Normalize weights first: finite price*large volume must not overflow.
                    vwap = math.fsum(row["vw"] * (row["v"] / volume) for row in raw) if volume > 0 and all(row.get("vw") is not None for row in raw) else None
                    if vwap is not None and not math.isfinite(vwap):
                        raise OverflowError
                except (OverflowError, ValueError):
                    exclusions.append({"start_at_ns": start, "end_at_ns": end, "reason_code": "NUMERIC_OVERFLOW"})
                    start = end
                    continue
                bars.append({"start_at_ns": start, "end_at_ns": end, "minutes": minutes, "complete": True,
                             "open": raw[0]["o"], "high": max(row["h"] for row in raw), "low": min(row["l"] for row in raw),
                             "close": raw[-1]["c"], "volume": volume, "vwap": vwap,
                             "available_at_ns": max(end, session.known_at_ns, *(row["available_at_ns"] for row in members),
                                                    *(event["available_at_ns"] for event in corporate)),
                             "member_ids": [row["id"] for row in members], "namespace": namespace,
                             "calendar_version_id": session.version_id, "signal_eligible": False,
                             "event_versions": [{"id": event["id"], "hash": event["payload_hash"]} for event in corporate]})
        if reason:
            exclusions.append({"start_at_ns": start, "end_at_ns": end, "reason_code": reason})
        start = end
    return {"bars": bars, "exclusions": sorted(exclusions, key=lambda row: (row["start_at_ns"], row["reason_code"])),
            "warmup_complete": len(bars) >= warmup_bars, "status_coverage": "UNKNOWN"}



def _corporate_as_of(events, cutoff, namespace):
    """Choose revisions before listing/window filters, using only visible captures."""
    visible = [r for r in events if r["available_at_ns"] is not None and r["available_at_ns"] <= cutoff]
    if namespace is not None:
        for row in visible:
            if tuple(row[k] for k in ("feed", "profile_id", "data_mode", "provenance", "replay_grade")) != namespace[1:-1]:
                raise ValueError("MIXED_NAMESPACE")
    captures = {}
    for row in visible:
        key = (row["logical_key"], row["received_at_ns"], row["capture_id"])
        captures[key] = min(captures.get(key, row["id"]), row["id"])
    def order(row):
        key = (row["logical_key"], row["received_at_ns"], row["capture_id"])
        return (row["received_at_ns"], captures[key], row["payload"].get("intake_sequence", row["ingest_sequence"]), row["id"])
    latest = {}
    for row in visible:
        key = (row["provider"], row["logical_key"])
        if key not in latest or order(row) > order(latest[key]):
            latest[key] = row
    result = []
    for row in latest.values():
        if row["event_type"] != "CORPORATE_ACTION":
            continue
        if namespace is None:
            continue
        if row["listing_id"] is not None and row["listing_id"] != namespace[-1]:
            continue
        if tuple(row[k] for k in ("feed", "profile_id", "data_mode", "provenance", "replay_grade")) != namespace[1:-1]:
            raise ValueError("MIXED_NAMESPACE")
        result.append(row)
    return sorted(result, key=lambda row: (row["provider"], row["logical_key"], row["id"]))


def _crosses_action(event, start, end):
    if event["payload"].get("cancelled") or not event["payload"].get("discontinuity"):
        return False
    at = event["effective_at_ns"]
    if at is None:
        return True  # Missing economic date cannot certify a window free of discontinuity.
    stop = event["payload"].get("effective_end_ns")
    return start < stop and at < end if stop is not None else start <= at < end
