"""Append-only minute/quote archive. RAW commit precedes each typed ADMISSION.

REST backfills are current historical research, never STRICT_PIT capture. No I/O
at construction; no projection into the daily market-data pipeline.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import islice
from zoneinfo import ZoneInfo

from backend.app.data_providers.alpaca_market import (
    AlpacaProviderError,
    _ns,
    decode_market_row,
    format_ns,
)
from backend.app.data_providers.alpaca_metadata import (
    AlpacaMetadataService,
    MetadataError,
    captures_as_of,
    check_ns,
    datetime_ns,
    decode_row,
)
from backend.app.intraday.calendar import session_as_of
from backend.app.intraday.contracts import EventEnvelope
from backend.app.intraday.identity import read_identity_as_of

MINUTE_NS = 60_000_000_000
_COMMON = ("provider", "feed", "profile_id", "data_mode", "provenance", "replay_grade", "schema_version",
           "listing_id", "logical_key", "capture_id", "ingest_sequence", "event_time_ns", "received_at_ns",
           "persisted_at_ns", "admitted_at_ns", "availability_floor_ns", "payload_json",
           "source_event_id", "source_revision_id")
_CODES = frozenset({"OBSERVATION_INVALID", "SOURCE_REVISION_CONFLICT", "MODE_MISMATCH", "ARCHIVE_LIMIT",
                   "IDENTITY_UNVERIFIED", "CALENDAR_MISSING", "INVALID_REQUEST", "TOKEN_LOOP", "PAGE_LIMIT",
                   "CANCELLED", "PAGE_INVALID", "TRANSACTION_ALREADY_OPEN", "PROFILE_INVALID"})


class StoreError(ValueError):
    def __init__(self, code):
        self.code = code if code in _CODES else "OBSERVATION_INVALID"
        self.reason_code = self.code
        super().__init__(self.code)


class IntradayStore:
    def __init__(self, provider, *, clock_ns=time.time_ns, data_mode="REAL",
                 provenance="CAPTURED", replay_grade="STRICT_PIT"):
        self.archive = AlpacaMetadataService(provider, clock_ns=clock_ns, data_mode=data_mode,
                                            provenance=provenance, replay_grade=replay_grade)
        self.provider, self.connection, self.profile = provider, provider.connection, provider.profile
        self.data_mode, self.provenance, self.replay_grade = data_mode, provenance, replay_grade

    @property
    def namespace(self):
        return self.archive.namespace

    def _begin(self):
        if self.connection.in_transaction:
            raise StoreError("TRANSACTION_ALREADY_OPEN")
        self.connection.execute("BEGIN IMMEDIATE")
        self._used = self.archive._archive_bytes()

    def _sequence(self, run):
        return self.connection.execute("""
            SELECT COALESCE(MAX(ingest_sequence),0)+1 FROM (
              SELECT ingest_sequence FROM intraday_observations
              UNION ALL SELECT ingest_sequence FROM intraday_capture_events)
        """).fetchone()[0]

    def _run(self, run):
        row = self.connection.execute("SELECT * FROM intraday_ingest_runs WHERE id=?", (run,)).fetchone()
        if row is None or tuple(row[key] for key in ("profile_id", "data_mode", "provenance", "replay_grade")) != self.namespace:
            raise StoreError("MODE_MISMATCH")

    def _insert(self, table, envelope, run, fields):
        if table == "intraday_observations":
            # Keep original intake order separately from the globally unique storage sequence.
            envelope = replace(envelope, payload_json=self.archive.safe_json(
                {**envelope.payload, "intake_sequence": envelope.ingest_sequence}))
        text = self.archive.safe_json(json.loads(envelope.payload_json))
        size = len(text.encode())
        settings = self.archive.settings
        if size > min(self.profile.max_frame_bytes, settings.alpaca_max_frame_bytes):
            raise StoreError("OBSERVATION_INVALID")
        cap = min(self.profile.max_archive_bytes, settings.alpaca_max_archive_bytes)
        if cap <= 0 or self._used + size > cap:
            raise StoreError("ARCHIVE_LIMIT")
        row = {name: getattr(envelope, name) for name in _COMMON}
        row.update(ingest_run_id=run, ingest_sequence=self._sequence(run), available_at_ns=envelope.available_at_ns,
                   payload_hash=envelope.payload_hash, **fields)
        result = int(self.connection.execute(
            f"INSERT INTO {table}({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()),
        ).lastrowid)
        self._used += size
        self.connection.execute("UPDATE intraday_ingest_runs SET accepted_count=accepted_count+1 WHERE id=?", (run,))
        return result

    def _prepare(self, envelope):
        if not isinstance(envelope, EventEnvelope) or envelope.kind not in {"BAR", "QUOTE", "STATUS", "LULD"}:
            raise StoreError("OBSERVATION_INVALID")
        if ((envelope.profile_id, envelope.data_mode, envelope.provenance, envelope.replay_grade) != self.namespace or
                envelope.feed != self.profile.feed or envelope.provider != "alpaca"):
            raise StoreError("MODE_MISMATCH")
        # Secret guard precedes decode, digest queries and persistence.
        self.archive.safe_json(json.loads(envelope.payload_json))
        payload = json.loads(envelope.payload_json)
        if envelope.kind in {"STATUS", "LULD"}:
            from backend.app.data_providers.alpaca_events import decode_status_row
            decoded = decode_status_row(envelope.kind, payload.get("raw"), source=payload.get("source"))
        else:
            decoded = decode_market_row(envelope.kind, payload.get("raw"), source=payload.get("source"))
        if payload != decoded or _ns(decoded["raw"]["t"]) != envelope.event_time_ns:
            raise StoreError("OBSERVATION_INVALID")
        if decoded["source"] == "REST" and (self.provenance != "HISTORICAL_CURRENT" or self.replay_grade != "RESEARCH_ONLY"):
            raise StoreError("MODE_MISMATCH")
        now = self.archive.now()
        future = envelope.event_time_ns > envelope.received_at_ns
        floor = max(envelope.availability_floor_ns, envelope.event_time_ns if future else 0)
        envelope = replace(envelope, persisted_at_ns=now, admitted_at_ns=None, availability_floor_ns=floor)
        # Future events retain their original timestamp, quarantined and unavailable until their floor.
        replace(envelope, event_time_ns=min(envelope.event_time_ns, envelope.received_at_ns),
                availability_floor_ns=min(floor, now)).validate_at(now)
        reason = "TIMESTAMP_FUTURE" if future else decoded["reason_code"]
        end = envelope.event_time_ns + MINUTE_NS if envelope.kind == "BAR" else None
        if end is not None:
            if envelope.availability_floor_ns < end:
                raise StoreError("OBSERVATION_INVALID")
            if end > envelope.received_at_ns and reason is None:
                reason = "BAR_NOT_CLOSED"
        elif envelope.kind == "QUOTE":
            conditions = decoded["raw"].get("c", [])
            if reason is None:
                if "c" not in decoded["raw"]:
                    reason = "QUOTE_CONDITIONS_MISSING"
                elif any(code not in self.profile.quote_conditions for code in conditions):
                    reason = "QUOTE_CONDITION_UNATTESTED"
                elif any(not isinstance(decoded["raw"].get(key), str) or not decoded["raw"][key] or
                         len(decoded["raw"][key]) > 16 for key in ("bx", "ax", "z")):
                    reason = "QUOTE_METADATA_MISSING"
        metadata_scope = {"data_mode": self.data_mode, "provenance": "CAPTURED" if self.data_mode == "REAL" else "SYNTHETIC",
                          "replay_grade": "STRICT_PIT" if self.data_mode == "REAL" else "RESEARCH_ONLY"}
        identity = read_identity_as_of(self.connection, envelope.listing_id, envelope.event_time_ns,
                                      envelope.received_at_ns, profile_id=self.profile.profile_id, **metadata_scope)
        if envelope.kind in {"STATUS", "LULD"}:
            if self.profile.feed != "sip" or envelope.kind.lower() not in self.profile.attested_capabilities:
                reason = "FEED_NOT_ENTITLED"
            elif identity is None or decoded["raw"]["S"] != identity["ticker"] or (
                    identity["venue"] == "NASDAQ" and decoded["raw"]["z"] != "C"):
                reason = "IDENTITY_UNVERIFIED"
        if reason is None and (identity is None or (envelope.kind in {"BAR", "QUOTE"} and
                                                    envelope.kind not in identity["payload"]["capabilities"])):
            reason = "IDENTITY_UNVERIFIED"
        return envelope, {"kind": envelope.kind, "quality": "QUARANTINED" if reason else "VALID",
                          "reason_code": reason, "bar_end_ns": end}

    def _duplicate(self, envelope, fields):
        params = (*self.namespace, envelope.listing_id, envelope.kind, envelope.logical_key)
        where = "profile_id=? AND data_mode=? AND provenance=? AND replay_grade=? AND listing_id=? AND kind=? AND logical_key=?"
        identified = envelope.source_event_id is not None or envelope.source_revision_id is not None
        if identified:
            rows = self.connection.execute(f"SELECT * FROM intraday_observations WHERE {where} AND source_event_id IS ? AND source_revision_id IS ? ORDER BY id DESC",
                                           (*params, envelope.source_event_id, envelope.source_revision_id)).fetchall()
            if envelope.source_revision_id is not None and any(self._source_payload(row) != envelope.payload for row in rows):
                raise StoreError("SOURCE_REVISION_CONFLICT")
            row = rows[0] if rows else None
        else:
            row = self.connection.execute(f"""SELECT * FROM intraday_observations WHERE {where} AND capture_id=?
                AND (received_at_ns<? OR (received_at_ns=? AND
                  COALESCE(json_extract(payload_json,'$.intake_sequence'),ingest_sequence)<=?))
                ORDER BY received_at_ns DESC,COALESCE(json_extract(payload_json,'$.intake_sequence'),ingest_sequence) DESC,id DESC LIMIT 1""",
                (*params, envelope.capture_id, envelope.received_at_ns, envelope.received_at_ns, envelope.ingest_sequence)).fetchone()
        temporal_change = (not identified and row is not None and row["reason_code"] in {"BAR_NOT_CLOSED", "TIMESTAMP_FUTURE"}
                           and row["reason_code"] != fields["reason_code"])
        return row["id"] if row is not None and self._source_payload(row) == envelope.payload and not temporal_change else None

    @staticmethod
    def _source_payload(row):
        payload = decode_row(row)["payload"]
        payload.pop("intake_sequence", None)
        return payload

    def persist(self, envelopes, *, run_id=None, admit=True):
        cap = min(self.profile.max_queue_events, self.archive.settings.alpaca_max_queue_events)
        values = tuple(islice(iter(envelopes), max(0, cap) + 1))
        if not values or len(values) > cap:
            raise StoreError("OBSERVATION_INVALID")
        prepared = [self._prepare(envelope) for envelope in values]
        self._begin()
        try:
            run = run_id if run_id is not None else self.archive.begin_run()
            self._run(run)
            ids = []
            for envelope, fields in prepared:
                duplicate = self._duplicate(envelope, fields)
                ids.append(duplicate if duplicate is not None else self._insert("intraday_observations", envelope, run, fields))
            self.connection.commit()
        except (sqlite3.DatabaseError, MetadataError) as exc:
            self.connection.rollback()
            raise StoreError(getattr(exc, "code", "OBSERVATION_INVALID")) from None
        except Exception:
            self.connection.rollback()
            raise
        if admit:
            self.admit(tuple(ids))  # Separate call after committed RAW; crash here leaves invisible evidence.
        if run_id is None:
            self._finish(run, "COMPLETE")
        return tuple(ids)

    def admit(self, observation_ids):
        ids = tuple(dict.fromkeys(observation_ids))
        if not ids or len(ids) > min(self.profile.max_queue_events, self.archive.settings.alpaca_max_queue_events):
            raise StoreError("OBSERVATION_INVALID")
        durable = self.archive.now()  # Caller has committed raw before reaching this boundary.
        self._begin()
        try:
            receipts = []
            for row_id in ids:
                raw = self.connection.execute("SELECT * FROM intraday_observations WHERE id=?", (row_id,)).fetchone()
                if raw is None or tuple(raw[k] for k in ("profile_id", "data_mode", "provenance", "replay_grade")) != self.namespace:
                    raise StoreError("MODE_MISMATCH")
                self._run(raw["ingest_run_id"])
                if self.connection.execute("SELECT 1 FROM intraday_capture_events WHERE kind='ADMISSION' AND observation_id=?",
                                           (row_id,)).fetchone():
                    continue
                decode_row(raw)
                if durable < max(raw["persisted_at_ns"], raw["availability_floor_ns"]):
                    continue
                text = self.archive.safe_json({"version": "intraday-admission-v1", "observation_id": row_id,
                                               "payload_hash": raw["payload_hash"], "durable_at_ns": durable})
                stamp = self.archive.now()
                proof = EventEnvelope("alpaca", self.profile.feed, *self.namespace[:2], *self.namespace[2:],
                                      "EVENT", raw["listing_id"], f"admission:{row_id}", raw["capture_id"], 1,
                                      durable, durable, stamp, stamp, text, raw["availability_floor_ns"])
                proof.validate_at(stamp)
                receipts.append(self._insert("intraday_capture_events", proof, raw["ingest_run_id"],
                                             {"kind": "ADMISSION", "lease_nonce": "intraday-store-v1",
                                              "observation_id": row_id, "news_version_id": None, "event_version_id": None}))
            self.connection.commit()
            return tuple(receipts)
        except (sqlite3.DatabaseError, MetadataError) as exc:
            self.connection.rollback()
            raise StoreError(getattr(exc, "code", "OBSERVATION_INVALID")) from None
        except Exception:
            self.connection.rollback()
            raise

    def read_as_of(self, kind, *, cutoff_ns, listing_ids=None, start_ns=None, end_ns=None, revisions=False):
        check_ns(cutoff_ns)
        if kind not in {"BAR", "QUOTE", "STATUS", "LULD"}:
            raise StoreError("OBSERVATION_INVALID")
        rows = self.connection.execute("""
            SELECT raw.*, proof.id AS proof_id, proof.payload_json AS proof_json, proof.payload_hash AS proof_hash,
              proof.available_at_ns AS proof_available
            FROM intraday_observations raw JOIN intraday_capture_events proof
              ON proof.observation_id=raw.id AND proof.kind='ADMISSION'
            WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
              AND raw.kind=? AND proof.available_at_ns<=? ORDER BY proof.available_at_ns,raw.received_at_ns,raw.ingest_sequence,raw.id
        """, (*self.namespace, kind, cutoff_ns))
        result = []
        for row in rows:
            raw = dict(row)
            proof = decode_row({"payload_json": raw["proof_json"], "payload_hash": raw["proof_hash"]})["payload"]
            item = decode_row({k: v for k, v in raw.items() if not k.startswith("proof_")})
            durable = proof.get("durable_at_ns")
            check_ns(durable)
            if (proof.get("observation_id") != item["id"] or proof.get("payload_hash") != item["payload_hash"] or
                    durable < item["persisted_at_ns"]):
                raise StoreError("OBSERVATION_INVALID")
            item["available_at_ns"] = max(raw["proof_available"], durable, item["availability_floor_ns"])
            if item["available_at_ns"] > cutoff_ns:
                continue
            if listing_ids is not None and item["listing_id"] not in listing_ids:
                continue
            if start_ns is not None and item["event_time_ns"] < start_ns:
                continue
            if end_ns is not None and item["event_time_ns"] >= end_ns:
                continue
            item["admission_id"] = raw["proof_id"]
            item["capture_ingest_sequence"] = item["payload"].get("intake_sequence", item["ingest_sequence"])
            result.append(item)
        # A total order within each logical observation/receipt, using visible evidence only.
        # Intake ordinals are comparable inside a capture; first visible ID orders separate captures.
        captures = {}
        for item in result:
            key = (item["listing_id"], item["event_time_ns"], item["received_at_ns"], item["capture_id"])
            captures[key] = min(captures.get(key, item["id"]), item["id"])
        for item in result:
            key = (item["listing_id"], item["event_time_ns"], item["received_at_ns"], item["capture_id"])
            item["capture_order"] = captures[key]
        def order(item):
            return (item["received_at_ns"], item["capture_order"], item["capture_ingest_sequence"],
                    item["ingest_sequence"], item["id"])
        if not revisions:
            latest = {}
            for item in result:
                key = (item["listing_id"], item["event_time_ns"])
                previous = latest.get(key)
                if previous is None or order(item) > order(previous):
                    latest[key] = item
            result = list(latest.values())
        return sorted(result, key=lambda row: (row["event_time_ns"], row["available_at_ns"], *order(row)))

    def quote_state(self, listing_id, *, cutoff_ns, max_age_ns=2_000_000_000):
        check_ns(max_age_ns)
        rows = self.read_as_of("QUOTE", cutoff_ns=cutoff_ns, listing_ids=(listing_id,))
        if not rows:
            return None
        result = dict(rows[-1])
        result["nbbo"] = self.profile.feed == "sip"
        result["delayed"] = self.profile.feed == "delayed_sip"
        result["size_conversion_attested"] = False
        if cutoff_ns - result["event_time_ns"] > max_age_ns:
            result.update(quality="QUARANTINED", reason_code="QUOTE_STALE")
        result["executable"] = (result["quality"] == "VALID" and result["nbbo"] and
                                result["payload"]["source"] == "STREAM")
        return result

    def _finish(self, run, state, reason=None):
        self.connection.execute("UPDATE intraday_ingest_runs SET state=?,finished_at_ns=?,cursor_json=? WHERE id=?",
                                (state, self.archive.now(), self.archive.safe_json({"reason_code": reason}), run))
        self.connection.commit()

    def progress_as_of(self, *, cutoff_ns):
        return captures_as_of(self.connection, cutoff_ns, profile_id=self.profile.profile_id,
                              data_mode=self.data_mode, provenance=self.provenance, replay_grade=self.replay_grade,
                              metadata_kind="MARKET_PROGRESS")

    def _progress(self, payload):
        with self.archive.transaction():
            run = self.archive.begin_run()
            result = self.archive.bootstrap(run, {"metadata_kind": "MARKET_PROGRESS", "version": "intraday-backfill-v1", **payload},
                                            self.archive.now(), f"market-progress:{payload['chunk_key']}")
            self.archive.finish_run(run)
        return result

    def _mappings(self, kind, listing_ids, start, end, cutoff, asof_at):
        result, identities = {}, {}
        for listing in listing_ids:
            first = read_identity_as_of(self.connection, listing, start, cutoff, profile_id=self.profile.profile_id)
            last = read_identity_as_of(self.connection, listing, end, cutoff, profile_id=self.profile.profile_id)
            symbol_asof = read_identity_as_of(self.connection, listing, asof_at, cutoff, profile_id=self.profile.profile_id)
            if (first is None or last is None or symbol_asof is None or
                    (symbol_asof["broker_asset_id"], symbol_asof["ticker"]) != (first["broker_asset_id"], first["ticker"]) or
                    first["id"] != last["id"] or
                    kind not in first["payload"]["capabilities"] or first["ticker"] in result):
                raise StoreError("IDENTITY_UNVERIFIED")
            result[first["ticker"]] = first
            for identity in (first, last, symbol_asof):
                identities[identity["id"]] = {"id": identity["id"], "hash": identity["payload_hash"],
                                                "publication_id": identity["publication_id"]}
        # Calendar knowledge is captured today, referenced as research input without relabeling it historical PIT.
        first_day = datetime.fromtimestamp(start // 1_000_000_000, UTC).astimezone(ZoneInfo("America/New_York")).date()
        last_day = datetime.fromtimestamp(end // 1_000_000_000, UTC).astimezone(ZoneInfo("America/New_York")).date()
        day = first_day
        calendars = []
        while day <= last_day:
            try:
                session = session_as_of(self.connection, day.isoformat(), cutoff, profile_id=self.profile.profile_id)
            except MetadataError:
                raise StoreError("CALENDAR_MISSING") from None
            if session is not None:
                calendars.append({"version_id": session.version_id, "capture_id": session.capture_id})
            batches = captures_as_of(self.connection, cutoff, profile_id=self.profile.profile_id,
                                     metadata_kind="CALENDAR", session_date=day.isoformat(), latest_only=True)
            batch = batches[0]
            calendars.append({"capture_id": batch["id"], "hash": batch["payload_hash"],
                              "publication_id": batch["publication_id"], "session_date": day.isoformat()})
            day += timedelta(days=1)
        return result, calendars, [identities[key] for key in sorted(identities)]

    def backfill(self, *, kind, listing_ids, start, end, asof, chunk_days=7, max_pages=100, cancel=None):
        if self.data_mode != "REAL" or self.provenance != "HISTORICAL_CURRENT" or self.replay_grade != "RESEARCH_ONLY":
            raise StoreError("MODE_MISMATCH")
        try:
            left, right = _ns(start), _ns(end)
            if (kind not in {"BAR", "QUOTE"} or type(listing_ids) is not tuple or not listing_ids or
                    any(type(item) is not int or item <= 0 for item in listing_ids) or len(set(listing_ids)) != len(listing_ids) or
                    len(listing_ids) > min(self.profile.max_symbols, self.archive.settings.alpaca_max_symbols) or
                    type(chunk_days) is not int or not 1 <= chunk_days <= 7 or
                    type(max_pages) is not int or not 1 <= max_pages <= 1000 or not 0 <= right - left <= 366 * 86400 * 1_000_000_000):
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise StoreError("INVALID_REQUEST") from None
        cutoff = self.archive.now()
        try:
            asof_start = _ns(asof)
            if asof_start > cutoff:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise StoreError("INVALID_REQUEST") from None
        # The date-only source parameter must bind the same known entity; today uses current known time.
        asof_at = min(asof_start + 86400 * 1_000_000_000 - 1, cutoff)
        mappings, calendar_ids, identity_refs = self._mappings(kind, listing_ids, left, right, cutoff, asof_at)
        limit = min(10000, self.profile.max_queue_events, self.archive.settings.alpaca_max_queue_events)
        capability = "bars" if kind == "BAR" else "quotes"
        base = {"symbols": ",".join(mappings), "start": start, "end": format_ns(min(right, left + chunk_days * 86400 * 1_000_000_000)),
                "asof": asof, "limit": str(limit), "feed": "sip" if self.profile.feed == "delayed_sip" else self.profile.feed,
                "currency": "USD", "sort": "asc"}
        if kind == "BAR":
            base.update(timeframe="1Min", adjustment="raw")
        # Validate the final bound as well as the first chunk before HTTP or creating a run.
        self.provider._validate_params(capability, {**base, "start": format_ns(max(left, right - chunk_days * 86400 * 1_000_000_000)),
                                                   "end": end}, self.provider.clock())
        self.archive.safe_json(base)
        archive_cap = min(self.profile.max_archive_bytes, self.archive.settings.alpaca_max_archive_bytes)
        if archive_cap <= self.archive._archive_bytes():
            raise StoreError("ARCHIVE_LIMIT")
        self._begin()
        try:
            run = self.archive.begin_run()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        pages = 0
        chunk_start = left
        reason = None
        key = None
        try:
            while chunk_start <= right:
                chunk_end = min(right, chunk_start + chunk_days * 86400 * 1_000_000_000)
                request = {**base, "start": format_ns(chunk_start), "end": format_ns(chunk_end)}
                metadata = {"identities": identity_refs, "calendar_proofs": calendar_ids}
                key = hashlib.sha256(self.archive.safe_json({"request": request, "metadata": metadata}).encode()).hexdigest()
                if cancel is not None and cancel():
                    raise StoreError("CANCELLED")
                completed = any(row["payload"].get("chunk_key") == key and row["payload"].get("phase") == "CHUNK" and
                                row["payload"].get("complete") is True for row in self.progress_as_of(cutoff_ns=self.archive.now()))
                if not completed:
                    token, seen, page_refs = None, set(), []
                    while True:
                        if cancel is not None and cancel():
                            raise StoreError("CANCELLED")
                        if pages >= max_pages:
                            raise StoreError("PAGE_LIMIT")
                        method = self.provider.get_bars_page if kind == "BAR" else self.provider.get_quotes_page
                        response = method(symbols=tuple(mappings), start=request["start"], end=request["end"], asof=asof,
                                          limit=limit, page_token=token, bypass_cache=True)
                        pages += 1
                        received = datetime_ns(response.fetched_at)
                        source = response.payload[capability]
                        if not set(source) <= set(mappings) or sum(len(rows) for rows in source.values()) > limit:
                            raise StoreError("PAGE_INVALID")
                        values = []
                        for symbol, rows in source.items():
                            identity = mappings[symbol]
                            for raw in rows:
                                decoded = decode_market_row(kind, raw, source="REST")
                                at = _ns(raw["t"])
                                if not chunk_start <= at <= chunk_end:
                                    raise StoreError("PAGE_INVALID")
                                values.append(EventEnvelope("alpaca", self.profile.feed, *self.namespace[:2], *self.namespace[2:],
                                                            kind, identity["listing_id"], f"{kind}:{identity['listing_id']}:{at}", key,
                                                            len(values) + 1, at, received, received, None,
                                                            self.archive.safe_json(decoded), at + MINUTE_NS if kind == "BAR" else 0))
                        ids = self.persist(values, run_id=run) if values else ()
                        next_token = response.payload["next_page_token"]
                        page_refs.append(self._progress({"phase": "PAGE", "chunk_key": key, "complete": False,
                                                        "request": request, "metadata": metadata, "page_number": len(page_refs) + 1,
                                                        "observation_ids": list(ids), "has_next_page": next_token is not None}))
                        if cancel is not None and cancel():
                            raise StoreError("CANCELLED")
                        if next_token is None:
                            break
                        if next_token in seen:
                            raise StoreError("TOKEN_LOOP")
                        seen.add(next_token)
                        token = next_token
                    self._progress({"phase": "CHUNK", "chunk_key": key, "complete": True,
                                    "request": request, "metadata": metadata, "page_ids": page_refs})
                if chunk_end == right:
                    break
                chunk_start = chunk_end + 1  # REST bounds are inclusive, retain every nanosecond exactly once.
        except (StoreError, AlpacaProviderError, MetadataError, ValueError) as exc:
            reason = getattr(exc, "code", "PAGE_INVALID")
            if key is not None:
                try:
                    self._progress({"phase": "CHUNK", "chunk_key": key, "complete": False,
                                    "inputs_complete": False, "reason_code": reason})
                except MetadataError as marker_error:
                    if marker_error.code not in {"ARCHIVE_LIMIT", "METADATA_INVALID"}:
                        self._finish(run, "PARTIAL", reason)
                        raise
            self._finish(run, "PARTIAL", reason)
            return {"run_id": run, "state": "PARTIAL", "reason_code": reason, "pages": pages}
        self._finish(run, "COMPLETE")
        return {"run_id": run, "state": "COMPLETE", "reason_code": None, "pages": pages}
