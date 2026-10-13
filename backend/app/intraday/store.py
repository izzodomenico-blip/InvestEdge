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
    decode_published,
    decode_row,
    published_select,
    scope,
)
from backend.app.intraday.calendar import session_as_of
from backend.app.intraday.contracts import EventEnvelope
from backend.app.intraday.identity import read_identity_as_of
from backend.app.intraday.replay import quote_state_from_rows, replay_as_of, select_versions

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
                 provenance="CAPTURED", replay_grade="STRICT_PIT", write_guard=None):
        self.archive = AlpacaMetadataService(provider, clock_ns=clock_ns, data_mode=data_mode,
                                            provenance=provenance, replay_grade=replay_grade)
        self.provider, self.connection, self.profile = provider, provider.connection, provider.profile
        self.data_mode, self.provenance, self.replay_grade = data_mode, provenance, replay_grade
        self.write_guard = write_guard

    @property
    def namespace(self):
        return self.archive.namespace

    def _begin(self):
        if self.connection.in_transaction:
            raise StoreError("TRANSACTION_ALREADY_OPEN")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.write_guard is not None:
                self.write_guard()
            self._used = self.archive._archive_bytes()
        except Exception:
            self.connection.rollback()
            raise

    def _sequence(self, run):
        return self.connection.execute("""
            SELECT MAX(
              COALESCE((SELECT MAX(ingest_sequence) FROM intraday_observations),0),
              COALESCE((SELECT MAX(ingest_sequence) FROM intraday_capture_events),0)) + 1
        """).fetchone()[0]

    def _run(self, run):
        row = self.connection.execute("SELECT * FROM intraday_ingest_runs WHERE id=?", (run,)).fetchone()
        if row is None or tuple(row[key] for key in ("profile_id", "data_mode", "provenance", "replay_grade")) != self.namespace:
            raise StoreError("MODE_MISMATCH")

    def _insert(self, table, envelope, run, fields):
        if self.write_guard is not None:
            self.write_guard()
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

    def _prepare(self, envelope, *, identity_reader=None):
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
        reader = read_identity_as_of if identity_reader is None else identity_reader
        identity = reader(self.connection, envelope.listing_id, envelope.event_time_ns,
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
        from backend.app.intraday import identity

        version_cache = {}

        def batch_identity(connection, listing, effective, cutoff, **namespace):
            # Bounded to this call/cutoff. Both local and other-connection writes
            # invalidate reuse; every resolution still checks all listing collisions.
            key = (scope(**namespace), cutoff, connection.total_changes,
                   connection.execute('PRAGMA data_version').fetchone()[0])
            if key not in version_cache:
                version_cache[key] = identity._versions(connection, cutoff, key[0])
            return identity._identity_from_versions(version_cache[key], listing, effective)

        prepared = [self._prepare(envelope, identity_reader=batch_identity) for envelope in values]
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

    def append_capture(self, kind, payload, *, run_id, capture_id, lease_nonce,
                       received_at_ns, listing_id=None):
        """RAW control commit, then immutable post-commit publication in its epoch.

        ADMISSION is reserved for observations/news/events. Control consumers use
        read_capture_as_of, never a raw ACK or mutable collector state as evidence.
        """
        if kind not in {'CAPTURE_START', 'ACK', 'GAP', 'BOOTSTRAP', 'CLOCK', 'STOP'}:
            raise StoreError('OBSERVATION_INVALID')
        if kind == 'CAPTURE_START':
            # Freeze public temporal limits with the new epoch, never borrow
            # mutable runtime configuration when replaying an earlier capture.
            payload = {**payload, 'continuity_policy': {'version': 'collector-continuity-v1',
                'socket_silence_ns': self.archive.settings.alpaca_stream_silence_seconds * 1_000_000_000,
                'lease_ns': self.archive.settings.alpaca_collector_lease_seconds * 1_000_000_000}}
        stamp = self.archive.now()
        envelope = EventEnvelope('alpaca', self.profile.feed, *self.namespace[:2], *self.namespace[2:],
            'EVENT', listing_id, f'collector:{kind}:{capture_id}', capture_id, 1,
            received_at_ns, received_at_ns, stamp, None, self.archive.safe_json(payload))
        fields = {'kind': kind, 'lease_nonce': lease_nonce, 'observation_id': None,
                  'news_version_id': None, 'event_version_id': None}
        self._begin()
        try:
            self._run(run_id)
            row_id = self._insert('intraday_capture_events', envelope, run_id, fields)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        durable = self.archive.now()
        self._begin()
        try:
            now = self.archive.now()
            proof = replace(envelope, event_time_ns=durable, received_at_ns=durable,
                persisted_at_ns=now, admitted_at_ns=now, logical_key=f'collector-publication:{row_id}',
                payload_json=self.archive.safe_json({'metadata_kind': 'COLLECTOR_PUBLICATION',
                    'version': 'collector-publication-v1', 'durable_at_ns': durable,
                    'reference': {'id': row_id, 'hash': envelope.payload_hash, 'kind': kind}}))
            proof.validate_at(now)
            self._insert('intraday_capture_events', proof, run_id, {**fields, 'kind': 'BOOTSTRAP'})
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return row_id

    def read_capture_as_of(self, *, cutoff_ns, capture_id=None):
        check_ns(cutoff_ns)
        query = """SELECT raw.*, pub.id AS proof_id, pub.payload_json AS proof_json,
            pub.payload_hash AS proof_hash, pub.available_at_ns AS proof_available
            FROM intraday_capture_events raw JOIN intraday_capture_events pub
              ON json_extract(pub.payload_json,'$.reference.id')=raw.id
              AND pub.ingest_run_id=raw.ingest_run_id AND pub.capture_id=raw.capture_id
              AND pub.lease_nonce=raw.lease_nonce AND pub.kind='BOOTSTRAP'
              AND pub.profile_id=raw.profile_id AND pub.data_mode=raw.data_mode
              AND pub.provenance=raw.provenance AND pub.replay_grade=raw.replay_grade
              AND pub.provider=raw.provider AND pub.feed=raw.feed AND pub.listing_id IS raw.listing_id
              AND json_extract(pub.payload_json,'$.metadata_kind')='COLLECTOR_PUBLICATION'
            WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
              AND pub.available_at_ns<=?"""
        params = (*self.namespace, cutoff_ns)
        if capture_id is not None:
            query += ' AND raw.capture_id=?'
            params += (capture_id,)
        result = []
        for raw in self.connection.execute(query + ' ORDER BY pub.available_at_ns,raw.ingest_sequence', params):
            raw = dict(raw)
            item = decode_row({key: raw[key] for key in raw if not key.startswith('proof_')})
            proof = decode_row({'payload_json': raw['proof_json'], 'payload_hash': raw['proof_hash']})['payload']
            durable = proof.get('durable_at_ns')
            check_ns(durable)
            if (proof.get('version') != 'collector-publication-v1'
                or proof.get('reference') != {'id': item['id'], 'hash': item['payload_hash'], 'kind': item['kind']}
                or durable < item['persisted_at_ns']):
                raise StoreError('OBSERVATION_INVALID')
            item['available_at_ns'] = max(raw['proof_available'], durable)
            item['publication_id'], item['publication_hash'] = raw['proof_id'], raw['proof_hash']
            if item['available_at_ns'] <= cutoff_ns:
                result.append(item)
        return result

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
        sql = """
            SELECT raw.*, proof.id AS proof_id, proof.payload_json AS proof_json, proof.payload_hash AS proof_hash,
              proof.available_at_ns AS proof_available
            FROM intraday_observations raw JOIN intraday_capture_events proof
              ON proof.observation_id=raw.id AND proof.kind='ADMISSION'
            WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
              AND raw.kind=? AND proof.available_at_ns<=?
        """
        params = (*self.namespace, kind, cutoff_ns)
        if listing_ids is not None:
            listing_ids = tuple(listing_ids)
            if not listing_ids:
                return []
            sql += f" AND raw.listing_id IN ({','.join('?' for _ in listing_ids)})"
            params += listing_ids
        rows = self.connection.execute(sql, params)
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
        return select_versions(result, family=kind, cutoff_ns=cutoff_ns, revisions=revisions, _decoded=True)

    def quote_state(self, listing_id, *, cutoff_ns, max_age_ns=2_000_000_000):
        rows = self.read_as_of("QUOTE", cutoff_ns=cutoff_ns, listing_ids=(listing_id,))
        return quote_state_from_rows(rows, listing_id=listing_id, cutoff_ns=cutoff_ns, max_age_ns=max_age_ns)

    def replay_as_of(self, *, cutoff_ns, listing_ids=None, timeline_only=False):
        """Archive-only adapter; no provider calls or mutable run/collector evidence."""
        from backend.app.intraday.events import EventStore
        from backend.app.intraday.news import NewsStore
        from backend.app.intraday.universe import UniverseService

        check_ns(cutoff_ns)
        rows = []
        def add(table, values):
            rows.extend({**row, 'table': table} for row in values)
        for kind in ('BAR', 'QUOTE', 'STATUS', 'LULD'):
            add('intraday_observations', self.read_as_of(kind, cutoff_ns=cutoff_ns, revisions=True))
        options = {'clock_ns': self.archive.clock_ns, 'data_mode': self.data_mode,
                   'provenance': self.provenance, 'replay_grade': self.replay_grade}
        news = NewsStore(self.provider, **options).read_as_of(cutoff_ns=cutoff_ns, revisions=True)
        add('intraday_news_versions', news)
        add('intraday_news_links', [link for row in news for link in row['links']])
        event_store = EventStore(self.provider, **options)
        events = event_store.read_as_of(cutoff_ns=cutoff_ns, revisions=True)
        add('intraday_event_versions', events)
        for event in events:
            doc = event_store._document(event)
            add('intraday_capture_events', [{**doc, 'recorded_available_at_ns': doc['available_at_ns'],
                                           'available_at_ns': event['available_at_ns']}])
        add('intraday_capture_events', self.read_capture_as_of(cutoff_ns=cutoff_ns))
        metadata_provenance = 'CAPTURED' if self.data_mode == 'REAL' else 'SYNTHETIC'
        metadata_grade = 'STRICT_PIT' if self.data_mode == 'REAL' else 'RESEARCH_ONLY'
        metadata_namespace = (self.profile.profile_id, self.data_mode, metadata_provenance, metadata_grade)
        metadata_archive = AlpacaMetadataService(self.provider, clock_ns=self.archive.clock_ns, data_mode=self.data_mode,
                                                provenance=metadata_provenance, replay_grade=metadata_grade)
        for table in ('intraday_identity_versions', 'intraday_calendar_versions',
                      'intraday_universe_snapshots', 'intraday_universe_members', 'intraday_capture_events'):
            query = published_select(table) + ''' WHERE raw.profile_id=? AND raw.data_mode=?
                AND raw.provenance=? AND raw.replay_grade=? AND raw.available_at_ns<=? AND pub.available_at_ns<=?
                AND EXISTS(SELECT 1 FROM json_each(pub.payload_json,'$.references') ref
                    WHERE json_extract(ref.value,'$.table')=? AND json_extract(ref.value,'$.id')=raw.id)'''
            if table == 'intraday_capture_events' and metadata_namespace != self.namespace:
                query += " AND json_extract(raw.payload_json,'$.metadata_kind') IN ('ASSETS','ASSET_CHUNK','CALENDAR')"
            values = [decode_published(row, table, cutoff_ns)
                      for row in self.connection.execute(query, (*metadata_namespace, cutoff_ns, cutoff_ns, table))]
            if table == 'intraday_universe_snapshots':
                for snapshot in values:
                    UniverseService(metadata_archive).read(snapshot['id'], cutoff_ns=cutoff_ns)
            add(table, [{**row, 'metadata_dependency': True} for row in values])
        for source_namespace in dict.fromkeys((self.namespace, metadata_namespace)):
            proof_rows = self.connection.execute('''SELECT * FROM intraday_capture_events
                WHERE profile_id=? AND data_mode=? AND provenance=? AND replay_grade=? AND available_at_ns<=?
                AND (kind='ADMISSION' OR json_extract(payload_json,'$.metadata_kind') IN ('PUBLICATION','COLLECTOR_PUBLICATION'))''',
                (*source_namespace, cutoff_ns))
            used_publications = {row.get('publication_id') for row in rows if row.get('metadata_dependency')}
            add('intraday_capture_events', [{**decode_row(row), 'metadata_dependency': source_namespace != self.namespace}
                for row in proof_rows if source_namespace == self.namespace or row['id'] in used_publications])
        unique = {}
        for row in rows:
            key = (row['table'], row['id'])
            if key not in unique or row['available_at_ns'] < unique[key]['available_at_ns']:
                unique[key] = row
        namespace = (self.profile.profile_id, self.profile.feed, self.data_mode, self.provenance, self.replay_grade)
        return replay_as_of(unique.values(), cutoff_ns=cutoff_ns, listing_ids=listing_ids,
                            namespace=namespace, timeline_only=timeline_only)

    def _timeline_query(self):
        """Read-only occurrence index. Payload hydration never requires a prefix list."""
        ordinary = "raw.profile_id=:profile AND raw.data_mode=:mode AND raw.provenance=:provenance AND raw.replay_grade=:grade"
        metadata = "raw.profile_id=:profile AND raw.data_mode=:mode AND raw.provenance=:meta_provenance AND raw.replay_grade=:meta_grade"
        parts = []
        for table, column in (('intraday_observations', 'observation_id'),
                              ('intraday_news_versions', 'news_version_id'),
                              ('intraday_event_versions', 'event_version_id')):
            parts.append(f"""SELECT '{table}' AS source_table,raw.id AS source_id,proof.id AS proof_id,
                MAX(proof.available_at_ns,json_extract(proof.payload_json,'$.durable_at_ns'),raw.availability_floor_ns) AS known,
                'ADMISSION' AS method,0 AS metadata_dependency,raw.received_at_ns,raw.capture_id,raw.ingest_sequence,
                COALESCE(json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence) AS intake,0 AS priority
                FROM {table} raw JOIN intraday_capture_events proof ON proof.{column}=raw.id AND proof.kind='ADMISSION'
                WHERE {ordinary} AND proof.available_at_ns<=:cutoff""")
        admission_sql = ' UNION ALL '.join(parts)
        parts = []
        for table in ('intraday_identity_versions', 'intraday_calendar_versions', 'intraday_universe_snapshots',
                      'intraday_universe_members', 'intraday_capture_events'):
            extra = (" AND (:same_namespace=1 OR json_extract(raw.payload_json,'$.metadata_kind') IN ('ASSETS','ASSET_CHUNK','CALENDAR'))"
                     if table == 'intraday_capture_events' else '')
            parts.append(f"""SELECT '{table}' AS source_table,raw.id AS source_id,pub.id AS proof_id,
                MAX(raw.available_at_ns,pub.available_at_ns,json_extract(pub.payload_json,'$.durable_at_ns')) AS known,
                'METADATA' AS method,1 AS metadata_dependency,raw.received_at_ns,raw.capture_id,raw.ingest_sequence,
                COALESCE(json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence) AS intake,6 AS priority
                FROM {table} raw JOIN intraday_capture_events pub ON pub.ingest_run_id=raw.ingest_run_id
                  AND pub.profile_id=raw.profile_id AND pub.data_mode=raw.data_mode AND pub.provenance=raw.provenance
                  AND pub.replay_grade=raw.replay_grade AND pub.kind='BOOTSTRAP'
                  AND json_extract(pub.payload_json,'$.metadata_kind')='PUBLICATION'
                WHERE {metadata} AND raw.available_at_ns<=:cutoff AND pub.available_at_ns<=:cutoff
                AND EXISTS(SELECT 1 FROM json_each(pub.payload_json,'$.references') ref
                    WHERE json_extract(ref.value,'$.table')='{table}' AND json_extract(ref.value,'$.id')=raw.id){extra}""")
        metadata_sql = ' UNION ALL '.join(parts)
        return f"""WITH admissions AS ({admission_sql}), metadata AS ({metadata_sql}), all_occurrences AS (
            SELECT * FROM admissions UNION ALL SELECT * FROM metadata
            UNION ALL
            SELECT 'intraday_news_links',link.id,link.id,a.known,'NEWS_LINK',0,link.received_at_ns,link.capture_id,
                link.ingest_sequence,COALESCE(json_extract(link.payload_json,'$.intake_sequence'),link.ingest_sequence),1
            FROM admissions a JOIN intraday_capture_events proof ON proof.id=a.proof_id,
                json_each(proof.payload_json,'$.links') ref JOIN intraday_news_links link ON link.id=json_extract(ref.value,'$.id')
            WHERE a.source_table='intraday_news_versions'
            UNION ALL
            SELECT 'intraday_capture_events',doc.id,doc.id,a.known,'EVENT_DOCUMENT',0,doc.received_at_ns,
                doc.capture_id,doc.ingest_sequence,COALESCE(json_extract(doc.payload_json,'$.intake_sequence'),doc.ingest_sequence),2
            FROM admissions a JOIN intraday_event_versions event ON event.id=a.source_id
                JOIN intraday_capture_events doc ON doc.id=json_extract(event.payload_json,'$.document.id')
            WHERE a.source_table='intraday_event_versions'
            UNION ALL
            SELECT 'intraday_capture_events',raw.id,pub.id,
                MAX(pub.available_at_ns,json_extract(pub.payload_json,'$.durable_at_ns')),'CONTROL',0,
                raw.received_at_ns,raw.capture_id,raw.ingest_sequence,
                COALESCE(json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence),3
            FROM intraday_capture_events raw JOIN intraday_capture_events pub
              ON json_extract(pub.payload_json,'$.reference.id')=raw.id AND pub.ingest_run_id=raw.ingest_run_id
              AND pub.capture_id=raw.capture_id AND pub.lease_nonce=raw.lease_nonce
              AND pub.kind='BOOTSTRAP' AND json_extract(pub.payload_json,'$.metadata_kind')='COLLECTOR_PUBLICATION'
              AND pub.profile_id=raw.profile_id AND pub.data_mode=raw.data_mode
              AND pub.provenance=raw.provenance AND pub.replay_grade=raw.replay_grade
              AND pub.provider=raw.provider AND pub.feed=raw.feed AND pub.listing_id IS raw.listing_id
            WHERE {ordinary} AND pub.available_at_ns<=:cutoff
            UNION ALL
            SELECT 'intraday_capture_events',raw.id,raw.id,raw.available_at_ns,'PROOF',0,
                raw.received_at_ns,raw.capture_id,raw.ingest_sequence,
                COALESCE(json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence),7
            FROM intraday_capture_events raw WHERE {ordinary} AND raw.available_at_ns<=:cutoff
                AND (raw.kind='ADMISSION' OR json_extract(raw.payload_json,'$.metadata_kind') IN ('PUBLICATION','COLLECTOR_PUBLICATION'))
            UNION ALL
            SELECT 'intraday_capture_events',raw.id,raw.id,raw.available_at_ns,'PROOF',1,
                raw.received_at_ns,raw.capture_id,raw.ingest_sequence,
                COALESCE(json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence),7
            FROM intraday_capture_events raw WHERE {metadata} AND :same_namespace=0 AND raw.available_at_ns<=:cutoff
                AND raw.id IN (SELECT proof_id FROM metadata)
        ), ranked AS (
            SELECT *,ROW_NUMBER() OVER(PARTITION BY source_table,source_id ORDER BY known,priority) AS ordinal
            FROM all_occurrences WHERE known<=:cutoff
        ), unique_occurrences AS (SELECT * FROM ranked WHERE ordinal=1), ordered AS (
            SELECT *,MIN(proof_id) OVER(PARTITION BY received_at_ns,capture_id) AS anchor FROM unique_occurrences
        ) SELECT * FROM ordered
        ORDER BY known,received_at_ns,anchor,intake,proof_id,ingest_sequence,source_table,source_id"""

    def _timeline_source(self, table, source_id):
        row = decode_row(self.connection.execute(f'SELECT * FROM {table} WHERE id=?', (source_id,)).fetchone())
        self.archive.safe_json({key: value for key, value in row.items() if key != 'payload_json'})
        return row

    def _timeline_row(self, occurrence, cutoff):
        table, source_id = occurrence['source_table'], occurrence['source_id']
        row = self._timeline_source(table, source_id)
        method = occurrence['method']
        if method == 'ADMISSION':
            receipt = self._timeline_source('intraday_capture_events', occurrence['proof_id'])
            column = {'intraday_observations': 'observation_id', 'intraday_news_versions': 'news_version_id',
                      'intraday_event_versions': 'event_version_id'}[table]
            durable = receipt['payload'].get('durable_at_ns')
            check_ns(durable)
            if (receipt[column] != source_id or receipt['payload'].get(column) != source_id
                or receipt['payload'].get('payload_hash') != row['payload_hash'] or durable < row['persisted_at_ns']
                or any(receipt[key] != row[key] for key in ('provider', 'feed', 'profile_id', 'data_mode', 'provenance', 'replay_grade'))):
                raise StoreError('OBSERVATION_INVALID')
            row.update(available_at_ns=occurrence['known'], admission_id=occurrence['proof_id'])
            if table == 'intraday_observations':
                row['capture_ingest_sequence'] = row['payload'].get('intake_sequence', row['ingest_sequence'])
            elif table == 'intraday_news_versions':
                # Exact typed links and identity validation, bounded by the mapped listings.
                links = []
                references = receipt['payload'].get('links')
                if type(references) is not list or not references:
                    raise StoreError('OBSERVATION_INVALID')
                for ref in references:
                    link = self._timeline_source('intraday_news_links', ref['id'])
                    if (link['payload_hash'] != ref['hash'] or link['news_version_id'] != source_id
                        or link['payload']['news_hash'] != row['payload_hash'] or durable < link['persisted_at_ns']
                        or any(link[key]!=row[key] for key in ('capture_id','ingest_run_id','provider','feed',
                            'profile_id','data_mode','provenance','replay_grade'))):
                        raise StoreError('OBSERVATION_INVALID')
                    identity = link['payload'].get('identity')
                    if identity:
                        from backend.app.data_providers.alpaca_metadata import read_evidence
                        metadata_scope = (self.profile.profile_id, self.data_mode,
                                          'CAPTURED' if self.data_mode == 'REAL' else 'SYNTHETIC',
                                          'STRICT_PIT' if self.data_mode == 'REAL' else 'RESEARCH_ONLY')
                        target = read_evidence(self.connection, 'intraday_identity_versions', identity['id'], cutoff, metadata_scope)
                        if (target['payload_hash'] != identity['payload_hash'] or target['publication_id'] != identity['publication_id']
                            or target['listing_id'] != link['listing_id'] or target['instrument_id'] != link['instrument_id']
                            or target['available_at_ns'] > row['received_at_ns']):
                            raise StoreError('OBSERVATION_INVALID')
                    link['available_at_ns'] = occurrence['known']
                    links.append(link)
                row.update(links=sorted(links, key=lambda link: link['id']), first_received_at_ns=row['received_at_ns'])
            else:
                from backend.app.intraday.events import EventStore
                document = EventStore(self.provider, data_mode=self.data_mode, provenance=self.provenance,
                                      replay_grade=self.replay_grade)._document(row)
                if receipt['payload'].get('document') != row['payload']['document'] or durable < document['persisted_at_ns']:
                    raise StoreError('OBSERVATION_INVALID')
        elif method == 'METADATA':
            query = published_select(table) + ' WHERE raw.id=? AND pub.id=?'
            row = decode_published(self.connection.execute(query, (source_id, occurrence['proof_id'])).fetchone(), table, cutoff)
            row['metadata_dependency'] = True
            if table == 'intraday_universe_snapshots':
                from backend.app.intraday.universe import UniverseService
                namespace = {'data_mode': self.data_mode, 'provenance': 'CAPTURED' if self.data_mode == 'REAL' else 'SYNTHETIC',
                             'replay_grade': 'STRICT_PIT' if self.data_mode == 'REAL' else 'RESEARCH_ONLY'}
                UniverseService(AlpacaMetadataService(self.provider, **namespace)).read(source_id, cutoff_ns=cutoff)
        elif method == 'CONTROL':
            receipt = self._timeline_source('intraday_capture_events', occurrence['proof_id'])
            proof = receipt['payload']
            check_ns(proof.get('durable_at_ns'))
            if (proof.get('version') != 'collector-publication-v1'
                or proof.get('reference') != {'id': source_id, 'hash': row['payload_hash'], 'kind': row['kind']}
                or proof['durable_at_ns'] < row['persisted_at_ns']):
                raise StoreError('OBSERVATION_INVALID')
            row.update(available_at_ns=occurrence['known'], publication_id=occurrence['proof_id'], publication_hash=receipt['payload_hash'])
        elif method == 'PROOF':
            row['metadata_dependency'] = bool(occurrence['metadata_dependency'])
        elif method == 'EVENT_DOCUMENT':
            row.update(recorded_available_at_ns=row['available_at_ns'], available_at_ns=occurrence['known'])
        elif method == 'NEWS_LINK':
            row['available_at_ns'] = occurrence['known']
        row['table'] = table
        return row

    def _iter_timeline(self, *, cutoff_ns):
        """Internal provisional occurrences; callers must validate the full pass."""
        from backend.app.intraday.replay import visible_rows

        check_ns(cutoff_ns)
        meta_provenance = 'CAPTURED' if self.data_mode == 'REAL' else 'SYNTHETIC'
        meta_grade = 'STRICT_PIT' if self.data_mode == 'REAL' else 'RESEARCH_ONLY'
        namespace = (self.profile.profile_id, self.profile.feed, self.data_mode, self.provenance, self.replay_grade)
        params = {'profile': self.profile.profile_id, 'mode': self.data_mode, 'provenance': self.provenance,
                  'grade': self.replay_grade, 'meta_provenance': meta_provenance, 'meta_grade': meta_grade,
                  'same_namespace': int((self.provenance, self.replay_grade) == (meta_provenance, meta_grade)), 'cutoff': cutoff_ns}
        for occurrence in self.connection.execute(self._timeline_query(), params):
            row = self._timeline_row(occurrence, cutoff_ns)
            if len(visible_rows((row,), cutoff_ns=cutoff_ns, namespace=namespace)) != 1:
                raise StoreError('OBSERVATION_INVALID')
            yield row

    def _validate_timeline_proofs(self, cutoff_ns):
        from backend.app.data_providers.alpaca_metadata import MAX_NS
        check_ns(cutoff_ns)
        relevant_metadata = []
        for table in ('intraday_identity_versions','intraday_calendar_versions','intraday_universe_snapshots',
                      'intraday_universe_members','intraday_capture_events'):
            extra = " AND json_extract(raw.payload_json,'$.metadata_kind') IN ('ASSETS','ASSET_CHUNK','CALENDAR')" if table=='intraday_capture_events' else ''
            relevant_metadata.append(f'''SELECT 1 FROM {table} raw,json_each(proof.payload_json,'$.references') ref
                WHERE raw.ingest_run_id=proof.ingest_run_id AND raw.profile_id=proof.profile_id AND raw.data_mode=proof.data_mode
                AND raw.provenance=proof.provenance AND raw.replay_grade=proof.replay_grade AND raw.available_at_ns<=:cutoff
                AND json_extract(ref.value,'$.table')='{table}' AND json_extract(ref.value,'$.id')=raw.id{extra}''')
        query = '''SELECT * FROM intraday_capture_events proof
            WHERE profile_id=:profile AND data_mode=:mode AND available_at_ns<=:cutoff AND (
            provenance=:provenance AND replay_grade=:grade AND (kind='ADMISSION'
                OR json_extract(payload_json,'$.metadata_kind') IN ('PUBLICATION','COLLECTOR_PUBLICATION'))
            OR provenance=:meta_provenance AND replay_grade=:meta_grade
                AND json_extract(payload_json,'$.metadata_kind')='PUBLICATION' AND EXISTS(''' + ' UNION ALL '.join(relevant_metadata) + '))'
        proofs = self.connection.execute(query,{'profile':self.profile.profile_id,'mode':self.data_mode,'cutoff':cutoff_ns,
            'provenance':self.provenance,'grade':self.replay_grade,
            'meta_provenance':'CAPTURED' if self.data_mode=='REAL' else 'SYNTHETIC',
            'meta_grade':'STRICT_PIT' if self.data_mode=='REAL' else 'RESEARCH_ONLY'})
        for raw in proofs:
            proof = decode_row(raw)
            check_ns(proof['payload'].get('durable_at_ns'))
            if proof['payload']['durable_at_ns'] > cutoff_ns:
                if proof['kind'] == 'ADMISSION':
                    for table,column in (('intraday_observations','observation_id'),('intraday_news_versions','news_version_id'),
                                         ('intraday_event_versions','event_version_id')):
                        if proof.get(column) is not None:
                            self._timeline_row({'source_table':table,'source_id':proof[column],'proof_id':proof['id'],
                                                'known':proof['payload']['durable_at_ns'],'method':'ADMISSION'},MAX_NS)
                elif proof['payload'].get('metadata_kind') == 'COLLECTOR_PUBLICATION':
                    self._timeline_row({'source_table':'intraday_capture_events','source_id':proof['payload']['reference']['id'],
                                        'proof_id':proof['id'],'known':proof['payload']['durable_at_ns'],'method':'CONTROL'},MAX_NS)
                else:
                    raise StoreError('OBSERVATION_INVALID')

    def iter_timeline(self, *, cutoff_ns):
        """Validate the whole visible prefix before emitting its first occurrence."""
        self._validate_timeline_proofs(cutoff_ns)
        for _ in self._iter_timeline(cutoff_ns=cutoff_ns):
            pass
        yield from self._iter_timeline(cutoff_ns=cutoff_ns)

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
