"""Versioned events, original documents and post-commit typed admission.

Event dates describe economics. Knowledge is receipt + RAW durability + admission.
Bootstrap is status-only CONNECTING; continuous stream reconciliation is Task 7.
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
from dataclasses import replace

from backend.app.data_providers.alpaca_events import (
    EventError,
    StatusAuthority,
    decode_corporate_page,
    decode_status_checkpoint,
)
from backend.app.data_providers.alpaca_metadata import MetadataError, check_ns, decode_row, read_evidence
from backend.app.data_providers.official_event_calendar import IssuerAuthority, decode_calendar
from backend.app.intraday.calendar import session_as_of
from backend.app.intraday.contracts import EventEnvelope
from backend.app.intraday.identity import read_identity_as_of, resolve_symbol_as_of
from backend.app.intraday.replay import select_versions, status_state_from_rows
from backend.app.intraday.store import IntradayStore, StoreError


class EventStore(IntradayStore):
    def _sequence(self, run):
        return self.connection.execute('SELECT accepted_count+1 FROM intraday_ingest_runs WHERE id=?', (run,)).fetchone()[0]

    @property
    def metadata_scope(self):
        return {'profile_id': self.profile.profile_id, 'data_mode': self.data_mode,
                'provenance': 'CAPTURED' if self.data_mode == 'REAL' else 'SYNTHETIC',
                'replay_grade': 'STRICT_PIT' if self.data_mode == 'REAL' else 'RESEARCH_ONLY'}

    def _identity(self, payload, received):
        at = payload.get('effective_at_ns') or payload.get('scheduled_at_ns') or payload.get('day_start_ns') or received
        if payload.get('day_start_ns') is not None and payload['day_start_ns'] <= received < payload['day_end_ns']:
            at = payload.get('scheduled_at_ns') or received
        if payload.get('symbol') is not None:
            identity = resolve_symbol_as_of(self.connection, payload['symbol'], at, received, **self.metadata_scope)
        elif payload.get('listing_id') is not None:
            identity = read_identity_as_of(self.connection, payload['listing_id'], at, received, **self.metadata_scope)
        else:
            return None
        if identity is None or (payload.get('scope') == 'NASDAQ_TAPE_C' and identity['venue'] != 'NASDAQ'):
            return None
        return identity

    def _envelope(self, payload, source, received, key, capture, listing=None):
        now = self.archive.now()
        result = EventEnvelope(source, self.profile.feed, *self.namespace[:2], *self.namespace[2:],
            'EVENT', listing, key, capture, 1, payload.get('effective_at_ns') or payload.get('scheduled_at_ns') or received,
            received, now, None, self.archive.safe_json(payload), source_event_id=payload.get('source_event_id'))
        result.validate_at(now)
        return result

    @staticmethod
    def _body(payload):
        return {k: v for k, v in payload.items() if k not in {'document', 'intake_sequence'}}

    def _previous(self, source, key, received, intake):
        return self.connection.execute('''SELECT * FROM intraday_event_versions
            WHERE profile_id=? AND data_mode=? AND provenance=? AND replay_grade=? AND provider=? AND logical_key=?
              AND (received_at_ns<? OR (received_at_ns=? AND json_extract(payload_json,'$.intake_sequence')<=?))
            ORDER BY received_at_ns DESC,json_extract(payload_json,'$.intake_sequence') DESC,id DESC LIMIT 1''',
            (*self.namespace, source, key, received, received, intake)).fetchone()

    def _persist_events(self, document, entries, *, received_at_ns, capture_id, admit, intake_sequence=None):
        check_ns(received_at_ns)
        if received_at_ns > self.archive.now():
            raise EventError('TIMESTAMP_FUTURE')
        cap = min(self.profile.max_queue_events, self.archive.settings.alpaca_max_queue_events)
        if not entries or len(entries) > cap:
            raise EventError('EVENT_LIMIT')
        source = entries[0]['source']
        if any(p['source'] != source for p in entries):
            raise EventError('MODE_MISMATCH')
        if intake_sequence is None:
            intake_sequence = self.connection.execute("SELECT COALESCE(MAX(json_extract(payload_json,'$.intake_sequence')),0)+1 FROM intraday_event_versions").fetchone()[0]
        if type(intake_sequence) is not int or intake_sequence <= 0:
            raise EventError('EVENT_ROW_INVALID')
        prepared = []
        for index, payload in enumerate(entries):
            identity = self._identity(payload, received_at_ns)
            listing = identity['listing_id'] if identity is not None else None
            payload = {**payload, 'identity': {k: identity[k] for k in ('id', 'payload_hash', 'publication_id')} if identity else None,
                       'intake_sequence': intake_sequence + index}
            if identity is None and (payload.get('symbol') or payload.get('listing_id')):
                payload['reason_code'] = 'IDENTITY_UNVERIFIED'
            else:
                payload.setdefault('reason_code', None)
            logical = payload.get('local_event_id') or payload.get('source_event_id') or payload.get('symbol') or str(listing)
            key = hashlib.sha256(self.archive.safe_json({'source': source, 'kind': payload['version'], 'id': logical,
                'issuer_listing_id': payload.get('listing_id') if source == 'issuer' else None}).encode()).hexdigest()
            prepared.append((payload, key, listing))
        self._begin()
        try:
            run = self.archive.begin_run()
            self.connection.execute('UPDATE intraday_ingest_runs SET provider=? WHERE id=?', (source, run))
            raw_document = {'version': 'event-document-v1', 'metadata_kind': 'EVENT_DOCUMENT', 'original': document}
            doc_env = self._envelope(raw_document, source, received_at_ns, f'event-document:{run}', capture_id)
            doc_id = self._insert('intraday_capture_events', doc_env, run,
                {'kind': 'BOOTSTRAP', 'lease_nonce': 'event-store-v1', 'observation_id': None,
                 'news_version_id': None, 'event_version_id': None})
            reference = {'id': doc_id, 'hash': doc_env.payload_hash}
            ids = []
            for payload, key, listing in prepared:
                previous = self._previous(source, key, received_at_ns, payload['intake_sequence'])
                if previous is not None and self._body(decode_row(previous)['payload']) == self._body(payload):
                    ids.append(previous['id'])
                    continue
                payload = {**payload, 'document': reference}
                env = self._envelope(payload, source, received_at_ns, key, capture_id, listing)
                ids.append(self._insert('intraday_event_versions', env, run,
                    {'event_type': payload['event_type'], 'effective_at_ns': payload.get('effective_at_ns'),
                     'scheduled_at_ns': payload.get('scheduled_at_ns'), 'supersedes_id': previous['id'] if previous else None}))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        if admit:
            self.admit(ids)
        self._finish(run, 'COMPLETE')
        return tuple(ids)

    def import_corporate(self, page, *, received_at_ns, capture_id='corporate-local', admit=True, intake_sequence=None):
        self.archive.safe_json(page)
        if self.provenance != 'HISTORICAL_CURRENT' or self.replay_grade != 'RESEARCH_ONLY' or self.data_mode != 'REAL':
            raise EventError('MODE_MISMATCH')
        if 'corporate_actions' not in self.profile.attested_capabilities:
            raise EventError('FEED_NOT_ENTITLED')
        entries = decode_corporate_page(page)
        return self._persist_events(page, entries, received_at_ns=received_at_ns, capture_id=capture_id,
                                    admit=admit, intake_sequence=intake_sequence) if entries else ()

    def import_calendar(self, document, *, received_at_ns, issuer_authority=None, capture_id='calendar-local', admit=True,
                        intake_sequence=None):
        self.archive.safe_json(document)
        if issuer_authority is not None:
            if not isinstance(issuer_authority, IssuerAuthority):
                raise EventError('EVENT_CALENDAR_INVALID')
            self.archive.safe_json({'issuer_authority': issuer_authority.__dict__})
        entries = decode_calendar(document, issuer_authority=issuer_authority)
        return self._persist_events(document, entries, received_at_ns=received_at_ns, capture_id=capture_id,
                                    admit=admit, intake_sequence=intake_sequence)

    def import_status_checkpoint(self, document, *, authority, received_at_ns, capture_id='status-bootstrap-local', admit=True):
        try:
            if (self.profile.feed != 'sip' or not {'status', 'luld'} <= set(self.profile.attested_capabilities) or
                    self.provenance != 'CAPTURED' or self.replay_grade != 'STRICT_PIT' or self.data_mode != 'REAL'):
                raise EventError('STATUS_BOOTSTRAP_UNAVAILABLE')
            self.archive.safe_json(document)
            if not isinstance(authority, StatusAuthority):
                raise EventError('STATUS_BOOTSTRAP_UNAVAILABLE')
            self.archive.safe_json({'authority': authority.public()})
            # Encoded transcripts must also pass the credential echo guard as ORIGINAL bytes.
            for channel in document.get('channels', []):
                raw = base64.b64decode(channel['original_b64'], validate=True)
                self.archive.safe_json({'wire': raw.decode('latin1')})
            entries = decode_status_checkpoint(document, authority=authority, received_at_ns=received_at_ns)
            entries = [p for p in entries if self._identity(p, received_at_ns) is not None]
            if not entries:
                raise EventError('STATUS_BOOTSTRAP_UNAVAILABLE')
            return self._persist_events(document, entries, received_at_ns=received_at_ns,
                                        capture_id=capture_id, admit=admit)
        except (MetadataError, StoreError, KeyError, TypeError, ValueError, OverflowError):
            raise EventError('STATUS_BOOTSTRAP_UNAVAILABLE') from None

    def admit(self, event_ids):
        ids = tuple(dict.fromkeys(event_ids))
        if not ids or len(ids) > min(self.profile.max_queue_events, self.archive.settings.alpaca_max_queue_events):
            raise EventError('EVENT_LIMIT')
        durable = self.archive.now()
        self._begin()
        try:
            receipts = []
            for row_id in ids:
                raw = decode_row(self.connection.execute('SELECT * FROM intraday_event_versions WHERE id=?', (row_id,)).fetchone())
                if tuple(raw[k] for k in ('profile_id', 'data_mode', 'provenance', 'replay_grade')) != self.namespace:
                    raise EventError('MODE_MISMATCH')
                if self.connection.execute("SELECT 1 FROM intraday_capture_events WHERE kind='ADMISSION' AND event_version_id=?", (row_id,)).fetchone():
                    continue
                doc = self._document(raw)
                if durable < max(raw['persisted_at_ns'], doc['persisted_at_ns']):
                    raise EventError('EVENT_INPUT_MISSING')
                text = {'version': 'event-admission-v1', 'event_version_id': row_id, 'payload_hash': raw['payload_hash'],
                        'document': raw['payload']['document'], 'durable_at_ns': durable}
                env = self._envelope(text, raw['provider'], durable, f'event-admission:{row_id}', raw['capture_id'], raw['listing_id'])
                env = replace(env, admitted_at_ns=self.archive.now())
                receipts.append(self._insert('intraday_capture_events', env, raw['ingest_run_id'],
                    {'kind': 'ADMISSION', 'lease_nonce': 'event-store-v1', 'observation_id': None,
                     'news_version_id': None, 'event_version_id': row_id}))
            self.connection.commit()
            return tuple(receipts)
        except Exception:
            self.connection.rollback()
            raise

    def _document(self, raw):
        ref = raw['payload'].get('document', {})
        doc = decode_row(self.connection.execute('SELECT * FROM intraday_capture_events WHERE id=?', (ref.get('id'),)).fetchone())
        if (doc['payload_hash'] != ref.get('hash') or doc['kind'] != 'BOOTSTRAP' or
                doc['payload'].get('metadata_kind') != 'EVENT_DOCUMENT' or
                any(doc[k] != raw[k] for k in ('provider', 'feed', 'profile_id', 'data_mode', 'provenance',
                                             'replay_grade', 'ingest_run_id', 'capture_id', 'received_at_ns'))):
            raise EventError('EVENT_INPUT_MISSING')
        return doc

    def read_as_of(self, *, cutoff_ns, listing_ids=None, revisions=False):
        check_ns(cutoff_ns)
        try:
            result = []
            rows = self.connection.execute('''SELECT raw.*, proof.id AS proof_id, proof.payload_json AS proof_json,
                    proof.payload_hash AS proof_hash, proof.available_at_ns AS proof_available
                FROM intraday_event_versions raw JOIN intraday_capture_events proof
                  ON proof.event_version_id=raw.id AND proof.kind='ADMISSION'
                WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
                  AND proof.available_at_ns<=? ORDER BY proof.available_at_ns,raw.id''', (*self.namespace, cutoff_ns))
            for row in rows:
                raw = dict(row)
                proof = decode_row({'payload_json': raw['proof_json'], 'payload_hash': raw['proof_hash']})['payload']
                item = decode_row({k: v for k, v in raw.items() if not k.startswith('proof_')})
                doc = self._document(item)
                durable = proof.get('durable_at_ns')
                check_ns(durable)
                if (proof.get('event_version_id') != item['id'] or proof.get('payload_hash') != item['payload_hash'] or
                        proof.get('document') != item['payload']['document'] or
                        durable < max(item['persisted_at_ns'], doc['persisted_at_ns'])):
                    raise EventError('EVENT_INPUT_MISSING')
                item['available_at_ns'] = max(raw['proof_available'], durable, item['availability_floor_ns'])
                if item['available_at_ns'] > cutoff_ns:
                    continue
                identity = item['payload'].get('identity')
                if identity is not None:
                    frozen = read_evidence(self.connection, 'intraday_identity_versions', identity['id'], cutoff_ns,
                                           tuple(self.metadata_scope.values()))
                    if frozen['payload_hash'] != identity['payload_hash'] or frozen['publication_id'] != identity['publication_id']:
                        raise EventError('EVENT_INPUT_MISSING')
                item['admission_id'] = raw['proof_id']
                result.append(item)
            return select_versions(result, family='EVENT', cutoff_ns=cutoff_ns, listing_ids=listing_ids, revisions=revisions)
        except (MetadataError, sqlite3.DatabaseError, KeyError, TypeError):
            raise EventError('EVENT_INPUT_MISSING') from None

    def scheduled_risks(self, session_date, *, cutoff_ns, listing_ids=None, buffer_ns=15*60_000_000_000):
        check_ns(buffer_ns)
        session = session_as_of(self.connection, session_date, cutoff_ns, **self.metadata_scope)
        if session is None:
            return []
        result = []
        for row in self.read_as_of(cutoff_ns=cutoff_ns):
            payload = row['payload']
            if (row['event_type'] not in {'MACRO', 'EARNINGS'} or payload['event_date'] != session_date or
                    payload['cancelled'] or payload.get('reason_code') is not None or
                    (listing_ids is not None and row['listing_id'] is not None and row['listing_id'] not in listing_ids)):
                continue
            at = row['scheduled_at_ns']
            start, end = (session.open_at_ns, session.close_at_ns) if at is None else (
                max(session.open_at_ns, at-buffer_ns), min(session.close_at_ns, at+buffer_ns))
            if end <= start:
                continue
            result.append({'event_version_id': row['id'], 'event_hash': row['payload_hash'], 'listing_id': row['listing_id'],
                'start_at_ns': start, 'end_at_ns': end, 'time_uncertainty': payload['time_uncertainty'],
                'available_at_ns': max(row['available_at_ns'], session.known_at_ns),
                'consensus': None, 'surprise': None})
        return result

    def record_status_gap(self, *, listing_id, received_at_ns, reason='CAPTURE_GAP'):
        if reason != 'CAPTURE_GAP':
            raise EventError('EVENT_ROW_INVALID')
        payload = {'version': 'status-gap-v1', 'source': 'alpaca', 'event_type': 'HALT', 'listing_id': listing_id,
                   'state': 'UNKNOWN', 'reason_code': 'CAPTURE_GAP', 'effective_at_ns': received_at_ns,
                   'source_event_id': None, 'source_revision_id': None, 'scheduled_at_ns': None}
        return self._persist_events({'reason_code': reason}, [payload], received_at_ns=received_at_ns,
                                    capture_id='status-gap-local', admit=True)

    def status_as_of(self, listing_id, *, cutoff_ns):
        unknown = {'state': 'UNKNOWN', 'reason_code': 'STATUS_BOOTSTRAP_UNAVAILABLE', 'phase': 'DEGRADED', 'live_eligible': False}
        if self.profile.feed != 'sip' or not {'status', 'luld'} <= set(self.profile.attested_capabilities):
            return unknown
        rows = self.read_as_of(cutoff_ns=cutoff_ns, listing_ids=(listing_id,), revisions=True)
        checkpoints = [r for r in rows if r['payload']['version'] == 'utp-status-checkpoint-v1']
        if not checkpoints:
            return unknown
        rank = {'NORMAL': 1, 'UNKNOWN': 2, 'QUOTATION_ONLY': 3, 'HALTED': 4}
        # Snapshot economic time prevails over transport receipt. Tied source state is restrictive.
        row = max(checkpoints, key=lambda r: (r['effective_at_ns'], rank[r['payload']['state']], r['id']))
        payload = row['payload']
        if payload['expires_at_ns'] <= cutoff_ns or payload.get('reason_code') is not None:
            return unknown
        gaps = [r for r in rows if r['payload']['version'] == 'status-gap-v1' and
                r['effective_at_ns'] >= row['effective_at_ns']]
        if gaps:
            return {**unknown, 'reason_code': 'CAPTURE_GAP'}
        observations = IntradayStore.read_as_of(self, 'STATUS', cutoff_ns=cutoff_ns, listing_ids=(listing_id,), revisions=True)
        state = status_state_from_rows(row, observations, cutoff_ns=cutoff_ns)
        return {'state': state, 'reason_code': None if state != 'UNKNOWN' else 'STATUS_UNKNOWN',
                'phase': 'CONNECTING', 'live_eligible': False, 'checkpoint_version_id': row['id'],
                'checkpoint_hash': row['payload_hash'], 'next_sequence': payload['next_sequence'],
                'expires_at_ns': payload['expires_at_ns']}
