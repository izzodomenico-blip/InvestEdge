"""Bounded Alpaca metadata bootstrap; no orders, discovery by name or implicit capture."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime

from backend.app.data_providers.alpaca_market import AlpacaMarketProvider
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.intraday.contracts import MAX_NS, EventEnvelope, canonical_json

_TABLE_KIND = {
    "intraday_identity_versions": "IDENTITY", "intraday_calendar_versions": "CALENDAR",
    "intraday_capture_events": "EVENT", "intraday_universe_snapshots": "UNIVERSE",
    "intraday_universe_members": "UNIVERSE",
}
_EVIDENCE_TABLES = (
    *_TABLE_KIND, "intraday_observations", "intraday_news_versions", "intraday_event_versions",
    "intraday_news_links", "intraday_dataset_snapshots", "intraday_dataset_members", "intraday_quality_reports",
)
_ERRORS = frozenset({
    "METADATA_INVALID", "METADATA_MISSING", "IDENTITY_UNVERIFIED", "IDENTITY_AMBIGUOUS",
    "MAPPING_CHANGED", "CALENDAR_MISSING", "ARCHIVE_LIMIT", "SNAPSHOT_NOT_PIT", "SNAPSHOT_INPUT_MISSING",
    "PROFILE_INVALID", "INVALID_TIMESTAMP", "MODE_MISMATCH", "TRANSACTION_ALREADY_OPEN",
})


class MetadataError(ValueError):
    def __init__(self, code: str):
        self.code = code if code in _ERRORS else "METADATA_INVALID"
        self.reason_code = self.code
        super().__init__(self.code)


def check_ns(value):
    if type(value) is not int or not 0 <= value <= MAX_NS:
        raise MetadataError("INVALID_TIMESTAMP")


def datetime_ns(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MetadataError("INVALID_TIMESTAMP")
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    result = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    check_ns(result)
    return result


def scope(profile_id, data_mode="REAL", provenance="CAPTURED", replay_grade="STRICT_PIT"):
    return (profile_id, data_mode, provenance, replay_grade)


def decode_row(row):
    if row is None:
        raise MetadataError("METADATA_MISSING")
    result = dict(row)
    try:
        payload = json.loads(result["payload_json"])
        text = canonical_json(payload)
        if text != result["payload_json"] or hashlib.sha256(text.encode()).hexdigest() != result["payload_hash"]:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise MetadataError("METADATA_INVALID") from None
    result["payload"] = payload
    return result


def published_select(table):
    if table not in _TABLE_KIND:
        raise MetadataError("METADATA_INVALID")
    return f"""SELECT raw.*, pub.id AS _pub_id, pub.payload_json AS _pub_json,
        pub.payload_hash AS _pub_hash, pub.available_at_ns AS _pub_available
        FROM {table} raw JOIN intraday_capture_events pub ON pub.ingest_run_id=raw.ingest_run_id
          AND pub.profile_id=raw.profile_id AND pub.data_mode=raw.data_mode
          AND pub.provenance=raw.provenance AND pub.replay_grade=raw.replay_grade
          AND pub.kind='BOOTSTRAP' AND json_extract(pub.payload_json,'$.metadata_kind')='PUBLICATION'
    """


def decode_published(row, table, cutoff_ns):
    if row is None:
        raise MetadataError("METADATA_MISSING")
    raw = dict(row)
    proof = decode_row({"id": raw["_pub_id"], "payload_json": raw["_pub_json"], "payload_hash": raw["_pub_hash"]})
    publication = proof["payload"]
    result = decode_row({key: value for key, value in raw.items() if not key.startswith("_pub_")})
    references = publication.get("references", [])
    expected = {"table": table, "id": result["id"], "hash": result["payload_hash"]}
    if (type(references) is not list or publication.get("complete") is not True or
            publication.get("member_count") != len(references) or
            expected not in references):
        raise MetadataError("METADATA_MISSING")
    durable = publication.get("durable_at_ns")
    check_ns(durable)
    known = max(result["available_at_ns"], raw["_pub_available"], durable)
    if durable < result["persisted_at_ns"] or known > cutoff_ns:
        raise MetadataError("METADATA_MISSING")
    result["recorded_available_at_ns"] = result["available_at_ns"]
    result["available_at_ns"] = known
    result["publication_id"] = raw["_pub_id"]
    return result


def read_evidence(connection, table, row_id, cutoff_ns, namespace):
    check_ns(cutoff_ns)
    row = connection.execute(published_select(table) + """
        WHERE raw.id=? AND raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
          AND raw.available_at_ns<=? AND pub.available_at_ns<=?
    """, (row_id, *namespace, cutoff_ns, cutoff_ns)).fetchone()
    return decode_published(row, table, cutoff_ns)


def captures_as_of(connection, cutoff_ns, *, profile_id, data_mode="REAL",
                   provenance="CAPTURED", replay_grade="STRICT_PIT", metadata_kind,
                   session_date=None, latest_only=False):
    check_ns(cutoff_ns)
    query = published_select("intraday_capture_events") + """
        WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
          AND raw.kind='BOOTSTRAP' AND raw.available_at_ns<=? AND pub.available_at_ns<=?
          AND json_extract(raw.payload_json,'$.metadata_kind')=?
    """
    params = (*scope(profile_id, data_mode, provenance, replay_grade), cutoff_ns, cutoff_ns, metadata_kind)
    if session_date is not None:
        query += " AND json_extract(raw.payload_json,'$.start')<=? AND json_extract(raw.payload_json,'$.end')>=?"
        params += (session_date, session_date)
    query += " ORDER BY pub.available_at_ns DESC,raw.available_at_ns DESC,raw.id DESC"
    if latest_only:
        query += " LIMIT 1"
    return [decode_published(row, "intraday_capture_events", cutoff_ns) for row in connection.execute(query, params)]



def asset_rows(connection, capture, cutoff_ns, namespace):
    payload = capture["payload"]
    chunks = payload.get("chunks")
    if type(chunks) is not list or len(chunks) > 30_000:
        raise MetadataError("METADATA_MISSING")
    assets, seen, chunk_ids = [], set(), set()
    try:
        for reference in chunks:
            chunk = read_evidence(connection, "intraday_capture_events", reference["id"], cutoff_ns, namespace)
            part = chunk["payload"]
            if (chunk["id"] in chunk_ids or chunk["ingest_run_id"] != capture["ingest_run_id"] or
                    chunk["publication_id"] != capture["publication_id"] or chunk["payload_hash"] != reference["hash"] or
                    part.get("metadata_kind") != "ASSET_CHUNK" or part.get("complete") is not True or
                    type(part.get("assets")) is not list or part.get("member_count") != len(part["assets"])):
                raise MetadataError("METADATA_MISSING")
            chunk_ids.add(chunk["id"])
            for asset in part["assets"]:
                if asset["id"] in seen:
                    raise MetadataError("METADATA_MISSING")
                seen.add(asset["id"])
                assets.append(asset)
                if len(assets) > 30_000:
                    raise MetadataError("METADATA_MISSING")
        if payload.get("member_count") != len(assets):
            raise MetadataError("METADATA_MISSING")
    except (MetadataError, KeyError, TypeError):
        raise MetadataError("METADATA_MISSING") from None
    return assets


class AlpacaMetadataService:
    """Explicit bootstrap and local evidence writer. Clock injection is for offline tests.

    record_assets accepts a decoded batch in the archive's declared namespace;
    it does not certify G1_DATA. HTTP refresh always uses the governed provider.
    """

    def __init__(self, provider: AlpacaMarketProvider, *, clock_ns: Callable[[], int] = time.time_ns,
                 data_mode="REAL", provenance="CAPTURED", replay_grade="STRICT_PIT"):
        self.provider = provider
        self.connection = provider.connection
        self.profile = provider.profile
        self.settings = provider.settings
        self.clock_ns = clock_ns
        self.data_mode = data_mode
        self.provenance = provenance
        self.replay_grade = replay_grade
        self.public_profile = provider.public_profile()
        # Validate mode combinations without serializing credentials or public IDs.
        EventEnvelope("alpaca", self.profile.feed, self.profile.profile_id, data_mode, provenance, replay_grade,
                      "EVENT", None, "metadata", "metadata", 1, 0, 0, 0, 0, "{}")

    @property
    def namespace(self):
        return scope(self.profile.profile_id, self.data_mode, self.provenance, self.replay_grade)

    def now(self):
        result = self.clock_ns()
        check_ns(result)
        return result

    def safe_json(self, payload):
        secrets = tuple(
            value for name, value in vars(self.settings).items()
            if (name.endswith(("_api_key", "_token", "_chat_id")) or name in
                {"alpaca_api_key_id", "alpaca_api_secret_key"}) and isinstance(value, str) and value
        )
        if SafeProviderTransport._payload_contains_secret(payload, secrets):
            raise MetadataError("METADATA_INVALID")
        try:
            return canonical_json(payload)
        except ValueError:
            raise MetadataError("METADATA_INVALID") from None

    @contextmanager
    def transaction(self):
        if self.connection.in_transaction:
            raise MetadataError("TRANSACTION_ALREADY_OPEN")
        self._references = {}
        self._publication_deadline = None
        self._publishing = False
        self.connection.execute("BEGIN IMMEDIATE")
        self._archive_used = self._archive_bytes()
        try:
            yield
            self.connection.commit()
            if self._references:
                durable = self.now()  # Raw operation is fully committed before admission/publication.
                if self._publication_deadline is not None and durable >= self._publication_deadline:
                    raise MetadataError("SNAPSHOT_NOT_PIT")
                self.connection.execute("BEGIN IMMEDIATE")
                self._archive_used = self._archive_bytes()
                self._publishing = True
                for run_id, references in self._references.items():
                    self.bootstrap(run_id, {
                        "metadata_kind": "PUBLICATION", "version": "intraday-publication-v1",
                        "complete": True, "durable_at_ns": durable, "member_count": len(references),
                        "references": references,
                    }, durable, f"publication:{run_id}")
                    self.connection.execute("""
                        UPDATE intraday_ingest_runs SET state='COMPLETE',finished_at_ns=? WHERE id=?
                    """, (self.now(), run_id))
                if self._publication_deadline is not None and self.now() >= self._publication_deadline:
                    raise MetadataError("SNAPSHOT_NOT_PIT")
                self.connection.commit()
        except sqlite3.DatabaseError:
            self.connection.rollback()
            raise MetadataError("SNAPSHOT_INPUT_MISSING") from None
        except Exception:
            self.connection.rollback()
            raise
        finally:
            self._publishing = False
            self._references = {}

    def _archive_bytes(self):
        return sum(self.connection.execute(
            f"SELECT COALESCE(SUM(length(CAST(payload_json AS BLOB))),0) FROM {name}",
        ).fetchone()[0] for name in _EVIDENCE_TABLES)

    def begin_run(self):
        now = self.now()
        config = self.safe_json(self.public_profile)
        self.connection.execute("""
            INSERT INTO intraday_feed_profiles(id,provider,feed,config_json,created_at_ns)
            SELECT ?, 'alpaca', ?, ?, ? WHERE NOT EXISTS(SELECT 1 FROM intraday_feed_profiles WHERE id=?)
        """, (self.profile.profile_id, self.profile.feed, config, now, self.profile.profile_id))
        row = self.connection.execute("SELECT config_json FROM intraday_feed_profiles WHERE id=?",
                                      (self.profile.profile_id,)).fetchone()
        if row[0] != config:
            raise MetadataError("PROFILE_INVALID")
        return int(self.connection.execute("""
            INSERT INTO intraday_ingest_runs(profile_id,provider,feed,data_mode,provenance,replay_grade,
                state,started_at_ns,limits_json,cursor_json)
            VALUES (?, 'alpaca', ?, ?, ?, ?, 'RUNNING', ?, '{}', '{}')
        """, (self.profile.profile_id, self.profile.feed, self.data_mode, self.provenance,
              self.replay_grade, now)).lastrowid)

    def append(self, table, run_id, payload, *, received_at_ns, fields, logical_key,
               listing_id=None, event_time_ns=None):
        if table not in _TABLE_KIND or not self.connection.in_transaction:
            raise MetadataError("METADATA_INVALID")
        text = self.safe_json(payload)
        size = len(text.encode())
        frame_limit = min(self.profile.max_frame_bytes, self.settings.alpaca_max_frame_bytes)
        if frame_limit <= 0 or size > frame_limit:
            raise MetadataError("METADATA_INVALID")
        limit = min(self.profile.max_archive_bytes, self.settings.alpaca_max_archive_bytes)
        if limit <= 0 or self._archive_used + size > limit:
            raise MetadataError("ARCHIVE_LIMIT")
        now = self.now()
        sequence = self.connection.execute("SELECT accepted_count+1 FROM intraday_ingest_runs WHERE id=?",
                                           (run_id,)).fetchone()[0]
        envelope = EventEnvelope(
            "alpaca", self.profile.feed, self.profile.profile_id, self.data_mode, self.provenance, self.replay_grade,
            _TABLE_KIND[table], listing_id, logical_key, str(uuid.uuid4()), sequence,
            received_at_ns if event_time_ns is None else event_time_ns, received_at_ns, now, now, text,
        )
        envelope.validate_at(now)
        row = {name: getattr(envelope, name) for name in (
            "provider", "feed", "profile_id", "data_mode", "provenance", "replay_grade", "schema_version",
            "listing_id", "logical_key", "capture_id", "ingest_sequence", "event_time_ns", "received_at_ns",
            "persisted_at_ns", "admitted_at_ns", "availability_floor_ns", "payload_json",
            "source_event_id", "source_revision_id",
        )}
        row.update(ingest_run_id=run_id, available_at_ns=envelope.available_at_ns,
                   payload_hash=envelope.payload_hash, **fields)
        columns = ",".join(row)
        result = int(self.connection.execute(
            f"INSERT INTO {table}({columns}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()),
        ).lastrowid)
        self._archive_used += size
        self.connection.execute("UPDATE intraday_ingest_runs SET accepted_count=accepted_count+1 WHERE id=?", (run_id,))
        if not self._publishing:
            self._references.setdefault(run_id, []).append({"table": table, "id": result, "hash": envelope.payload_hash})
        return result

    def finish_run(self, run_id, *, deadline_ns=None):
        if run_id not in self._references:
            raise MetadataError("METADATA_INVALID")
        if deadline_ns is not None:
            check_ns(deadline_ns)
            self._publication_deadline = deadline_ns

    def bootstrap(self, run_id, payload, received_at_ns, logical_key):
        return self.append("intraday_capture_events", run_id, payload, received_at_ns=received_at_ns,
                           fields={"kind": "BOOTSTRAP", "lease_nonce": "metadata-bootstrap-v1",
                                   "observation_id": None, "news_version_id": None, "event_version_id": None},
                           logical_key=logical_key)

    def refresh_assets(self):
        if self.data_mode != "REAL":
            raise MetadataError("MODE_MISMATCH")
        results = [self.provider.request_page("assets", {"asset_class": "us_equity", "status": status},
                                              bypass_cache=True) for status in ("active", "inactive")]
        return self.record_assets([row for result in results for row in result.payload],
                                  received_at_ns=max(datetime_ns(result.fetched_at) for result in results))

    def refresh_calendar(self, start: str, end: str):
        if self.data_mode != "REAL":
            raise MetadataError("MODE_MISMATCH")
        from backend.app.intraday.calendar import CalendarService, validate_range
        validate_range(start, end)
        result = self.provider.request_page("calendar", {"start": start, "end": end, "date_type": "TRADING"},
                                            bypass_cache=True)
        return CalendarService(self).record(result.payload, start=start, end=end,
                                            received_at_ns=datetime_ns(result.fetched_at))

    def record_assets(self, rows, *, received_at_ns):
        check_ns(received_at_ns)
        try:
            if type(rows) is not list or len(rows) > 30_000:
                raise ValueError
            selected, seen = [], set()
            input_size = 0
            input_limit = 2 * min(16 * 1024 * 1024, self.profile.max_frame_bytes, self.settings.alpaca_max_frame_bytes)
            for row in rows:
                if type(row) is not dict:
                    raise ValueError
                input_size += len(self.safe_json(row).encode()) + 1
                if input_size > input_limit:
                    raise ValueError
                asset_id = str(uuid.UUID(row["id"]))
                if asset_id in seen or row["id"] != asset_id or row["class"] not in {"us_equity", "crypto"}:
                    raise ValueError
                if not isinstance(row["symbol"], str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,31}", row["symbol"]):
                    raise ValueError
                if row["exchange"] not in {"AMEX", "ARCA", "BATS", "NYSE", "NASDAQ", "NYSEARCA", "OTC", "CRYPTO"}:
                    raise ValueError
                if row["status"] not in {"active", "inactive"} or type(row["tradable"]) is not bool:
                    raise ValueError
                seen.add(asset_id)
                selected.append({key: row[key] for key in ("id", "class", "symbol", "exchange", "status", "tradable")})
            selected.sort(key=lambda item: item["id"])
        except (ValueError, TypeError, KeyError, AttributeError):
            raise MetadataError("METADATA_INVALID") from None
        with self.transaction():
            run = self.begin_run()
            chunks, current, current_bytes = [], [], 0
            chunk_limit = min(1_048_576, self.profile.max_frame_bytes, self.settings.alpaca_max_frame_bytes)
            def flush():
                if not current:
                    return
                payload = {"metadata_kind": "ASSET_CHUNK", "version": "alpaca-assets-chunk-v1",
                           "complete": True, "member_count": len(current), "assets": list(current)}
                text = self.safe_json(payload)
                chunk_id = self.bootstrap(run, payload, received_at_ns, f"alpaca-assets-chunk:{len(chunks)}")
                chunks.append({"id": chunk_id, "hash": hashlib.sha256(text.encode()).hexdigest()})
            for asset in selected:
                size = len(self.safe_json(asset).encode()) + 1
                if current and current_bytes + size + 160 > chunk_limit:
                    flush()
                    current, current_bytes = [], 0
                current.append(asset)
                current_bytes += size
            flush()
            result = self.bootstrap(run, {"metadata_kind": "ASSETS", "version": "alpaca-assets-v1",
                                          "complete": True, "member_count": len(selected), "chunks": chunks},
                                    received_at_ns, "alpaca-assets")
            self.finish_run(run)
        return result

    def read_capture(self, capture_id, metadata_kind, cutoff_ns=None):
        if type(capture_id) is not int or capture_id <= 0:
            raise MetadataError("METADATA_MISSING")
        cutoff = self.now() if cutoff_ns is None else cutoff_ns
        check_ns(cutoff)
        result = read_evidence(self.connection, "intraday_capture_events", capture_id, cutoff, self.namespace)
        if result["payload"].get("metadata_kind") != metadata_kind or result["payload"].get("complete") is not True:
            raise MetadataError("METADATA_MISSING")
        if metadata_kind == "ASSETS":
            result["assets"] = asset_rows(self.connection, result, cutoff, self.namespace)
        return result
