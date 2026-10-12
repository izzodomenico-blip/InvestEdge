"""Finite immutable datasets. RAW output is invisible until durable publication."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass

from backend.app.data_providers.alpaca_metadata import (
    MAX_NS,
    MetadataError,
    decode_published,
    decode_row,
    published_select,
)
from backend.app.intraday.contracts import EventEnvelope, QualityPolicy, canonical_json
from backend.app.intraday.quality import planned_listing_ids, quality_report, validate_manifest
from backend.app.intraday.replay import check_ns, replay_frozen
from backend.app.intraday.universe import frozen_universe_dependencies

_REFERENCES = {
    'intraday_observations': ('OBSERVATION', 'observation_id'),
    'intraday_news_versions': ('NEWS', 'news_version_id'),
    'intraday_news_links': ('NEWS_LINK', 'news_link_id'),
    'intraday_event_versions': ('EVENT', 'event_version_id'),
    'intraday_identity_versions': ('IDENTITY', 'identity_version_id'),
    'intraday_calendar_versions': ('CALENDAR', 'calendar_version_id'),
    'intraday_universe_snapshots': ('UNIVERSE', 'universe_snapshot_id'),
    'intraday_capture_events': ('CAPTURE_EVENT', 'capture_event_id'),
}
_SOURCE_TABLES = {*_REFERENCES, 'intraday_universe_members'}


class SnapshotError(MetadataError):
    """Additional fixed public errors without reflecting caller or SQL text."""
    def __init__(self, code):
        self.code = code if code in {'POLICY_MISSING', 'QUALITY_POLICY_INVALID', 'SYMBOL_LIMIT',
                                    'CANCELLED', 'FRAME_LIMIT'} else 'METADATA_INVALID'
        self.reason_code = self.code
        ValueError.__init__(self, self.code)


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _source_hash(row):
    return _hash({key: value for key, value in row.items() if key != 'payload_json'})


def _digest(manifest, members):
    result = hashlib.sha256()
    for value in (manifest, *members):
        text = canonical_json(value).encode()
        result.update(len(text).to_bytes(8, 'big'))
        result.update(text)
    return result.hexdigest()


def _without_outputs(rows):
    outputs = {row['id'] for row in rows if row['table'] == 'intraday_capture_events'
               and row['payload'].get('metadata_kind') == 'DATASET_PUBLICATION'}
    return [row for row in rows if not (row['table'] == 'intraday_capture_events' and (
        row['id'] in outputs or (row['payload'].get('metadata_kind') == 'PUBLICATION'
        and row['payload'].get('references') and all(ref.get('table') == 'intraday_capture_events' and ref.get('id') in outputs
                for ref in row['payload']['references']))))]


@dataclass(frozen=True)
class DatasetSnapshot:
    snapshot_id: int
    digest: str
    report_id: int


class SnapshotService:
    def __init__(self, store):
        self.store, self.archive, self.connection = store, store.archive, store.connection

    def register_policy(self):
        """Explicit ex-ante registration; freeze never installs today's policy retroactively."""
        if self.connection.in_transaction:
            raise MetadataError('TRANSACTION_ALREADY_OPEN')
        policy = QualityPolicy()
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            self._guard()
            self.connection.execute('''INSERT INTO intraday_quality_policies(id,config_json,policy_hash,created_at_ns)
                SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM intraday_quality_policies WHERE id=?)''',
                (policy.version, policy.config_json, policy.policy_hash, self.archive.now(), policy.version))
            self._policy()
        return policy.version

    def _guard(self):
        if self.store.write_guard is not None:
            self.store.write_guard()

    def _policy(self):
        policy = QualityPolicy()
        row = self.connection.execute('SELECT * FROM intraday_quality_policies WHERE id=?', (policy.version,)).fetchone()
        if row is None:
            raise SnapshotError('POLICY_MISSING')
        if row['config_json'] != policy.config_json or row['policy_hash'] != policy.policy_hash:
            raise SnapshotError('QUALITY_POLICY_INVALID')
        return {'id': row['id'], 'config': json.loads(row['config_json']), 'hash': row['policy_hash'],
                'created_at_ns': row['created_at_ns']}

    def _profile(self):
        row = self.connection.execute('SELECT * FROM intraday_feed_profiles WHERE id=?',
                                      (self.store.profile.profile_id,)).fetchone()
        if row is None or row['config_json'] != self.archive.safe_json(self.archive.public_profile):
            raise MetadataError('PROFILE_INVALID')
        return {'id': row['id'], 'provider': row['provider'], 'feed': row['feed'],
                'config': json.loads(row['config_json']), 'created_at_ns': row['created_at_ns']}

    def _source(self, table, source_id):
        if table not in _SOURCE_TABLES or type(source_id) is not int or source_id <= 0:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        raw = self.connection.execute(f'SELECT * FROM {table} WHERE id=?', (source_id,)).fetchone()
        if raw is None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        raw = dict(raw)
        self.archive.safe_json({key: value for key, value in raw.items() if key != 'payload_json'})
        try:
            self.archive.safe_json(json.loads(raw['payload_json']))
        except ValueError:
            raise MetadataError('METADATA_INVALID') from None
        return raw

    def _reference(self, row):
        raw = self._source(row['table'], row['id'])
        decoded = decode_row(raw)
        if decoded['payload_hash'] != row['payload_hash'] or decoded['payload'] != row['payload']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        projection = {key: value for key, value in row.items()
                      if key not in {'payload', 'payload_json', 'payload_hash', 'links'} and
                      (key not in raw or value != raw[key])}
        return {'table': row['table'], 'id': row['id'], 'payload_hash': raw['payload_hash'],
                'source_hash': _source_hash(raw), 'projection': projection}

    def _hydrate(self, reference):
        raw = self._source(reference['table'], reference['id'])
        if raw['payload_hash'] != reference['payload_hash'] or _source_hash(raw) != reference['source_hash']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        row = decode_row(raw)
        row.update(reference['projection'])
        row['table'] = reference['table']
        return row

    @staticmethod
    def _cancel(cancelled, stage):
        if cancelled is not None and cancelled(stage):
            raise SnapshotError('CANCELLED')

    def freeze_dataset(self, *, start_at_ns, end_at_ns, cutoff_ns, listing_ids, benchmarks, cancelled=None):
        for stamp in (start_at_ns, end_at_ns, cutoff_ns):
            check_ns(stamp)
        if cutoff_ns > self.archive.now():
            raise MetadataError('SNAPSHOT_NOT_PIT')
        if self.connection.in_transaction:
            raise MetadataError('TRANSACTION_ALREADY_OPEN')
        self._cancel(cancelled, 'BEFORE_READ')
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            self._guard()
            manifest = {'version': 'intraday-dataset-v1', 'start_at_ns': start_at_ns, 'end_at_ns': end_at_ns,
                        'cutoff_ns': cutoff_ns, 'listing_ids': listing_ids, 'benchmarks': benchmarks,
                        'namespace': [self.store.profile.profile_id, self.store.profile.feed, self.store.data_mode,
                                      self.store.provenance, self.store.replay_grade],
                        'policy': self._policy(), 'profile': self._profile(),
                        'aggregation': 'closed-open-anchored-1-5-15-v1',
                        'selection': 'full-published-prefix-v1'}
            validate_manifest(manifest)
            if len(listing_ids) > min(self.store.profile.max_symbols, self.archive.settings.alpaca_max_symbols):
                raise SnapshotError('SYMBOL_LIMIT')
            rows = _without_outputs(self.store.replay_as_of(cutoff_ns=cutoff_ns)['timeline'])
            manifest['requested_listing_ids'] = list(listing_ids)
            manifest['listing_ids'] = planned_listing_ids(manifest, rows)
            if len(manifest['listing_ids']) > min(self.store.profile.max_symbols, self.archive.settings.alpaca_max_symbols):
                raise SnapshotError('SYMBOL_LIMIT')
            self._cutoff = cutoff_ns
            self._raw_latest = cutoff_ns
            by_key = {(row['table'], row['id']): row for row in rows}
            audit_keys = set()
            for row in rows:
                orphan = row['payload'].get('orphan_raw_proof') if row['table'] == 'intraday_capture_events' else None
                if orphan is not None:
                    table, source_id = orphan['table'], orphan['id']
                    if table not in {'intraday_observations', 'intraday_news_versions'}:
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    raw = self._source(table, source_id)
                    if (raw['payload_hash'] != orphan['payload_hash'] or raw['received_at_ns'] != orphan['received_at_ns'] or
                            raw['persisted_at_ns'] > row['persisted_at_ns']):
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    key = table, source_id
                    if key not in by_key:
                        by_key[key] = {**decode_row(raw), 'table': table}
                        audit_keys.add(key)
            bodies = []
            for key in sorted(by_key):
                row = by_key[key]
                if row['table'] == 'intraday_universe_members':
                    continue  # No dataset FK for this type: bound as exact dependencies of its universe.
                body = {'reference': self._reference(row), 'dependencies': [], 'replay': key not in audit_keys}
                if row['table'] == 'intraday_universe_snapshots':
                    dependencies = frozen_universe_dependencies(row, rows)
                    body['dependencies'] = [self._reference(item) for item in dependencies]
                bodies.append(body)
            manifest['timeline_count'] = len(rows)
            manifest['typed_member_count'] = len(bodies)
            manifest['audit_member_count'] = len(audit_keys)
            digest = _digest(manifest, bodies)
            report = quality_report(manifest, rows)
            self._cancel(cancelled, 'BEFORE_RAW')
            self._used = self.archive._archive_bytes()
            run = self.archive.begin_run()
            snapshot_id = self._append('intraday_dataset_snapshots', run, manifest, {
                'start_at_ns': start_at_ns, 'end_at_ns': end_at_ns, 'cutoff_ns': cutoff_ns,
                'policy_id': QualityPolicy.version, 'digest': digest, 'member_count': len(bodies)}, 'dataset')
            for body in bodies:
                self._cancel(cancelled, 'DURING_RAW')
                reference = body['reference']
                kind, column = _REFERENCES[reference['table']]
                self._append('intraday_dataset_members', run, body, {
                    'snapshot_id': snapshot_id, 'member_kind': kind, column: reference['id']}, f'dataset:{snapshot_id}:member')
            report_id = self._append('intraday_quality_reports', run, report, {
                'snapshot_id': snapshot_id, 'policy_id': QualityPolicy.version, 'outcome': report['outcome'],
                'metrics_json': self.archive.safe_json(report['metrics']),
                'limits_json': self.archive.safe_json(report['limits'])}, f'dataset:{snapshot_id}:quality')
            self.connection.commit()
        except sqlite3.DatabaseError:
            self.connection.rollback()
            raise MetadataError('SNAPSHOT_INPUT_MISSING') from None
        except Exception:
            self.connection.rollback()
            raise
        self._cancel(cancelled, 'BEFORE_PUBLICATION')
        durable = self.archive.now()
        if durable < self._raw_latest:
            raise MetadataError('SNAPSHOT_NOT_PIT')
        header = self.connection.execute('SELECT payload_hash,persisted_at_ns FROM intraday_dataset_snapshots WHERE id=?',
                                          (snapshot_id,)).fetchone()
        report_row = self.connection.execute('SELECT payload_hash FROM intraday_quality_reports WHERE id=?', (report_id,)).fetchone()
        with self.archive.transaction():
            self._cancel(cancelled, 'PUBLISHING')
            self._guard()
            if self.archive.now() < self._raw_latest:
                raise MetadataError('SNAPSHOT_NOT_PIT')
            self.archive.bootstrap(run, {'metadata_kind': 'DATASET_PUBLICATION', 'version': 'intraday-dataset-publication-v1',
                'complete': True, 'snapshot_id': snapshot_id, 'snapshot_hash': header['payload_hash'],
                'digest': digest, 'typed_member_count': len(bodies), 'timeline_count': len(rows),
                'report_id': report_id, 'report_hash': report_row['payload_hash'], 'durable_at_ns': durable},
                durable, f'dataset-publication:{snapshot_id}')
        return DatasetSnapshot(snapshot_id, digest, report_id)

    def _append(self, table, run, payload, fields, logical_key):
        self._guard()
        text = self.archive.safe_json(payload)
        size = len(text.encode())
        if size > min(self.store.profile.max_frame_bytes, self.archive.settings.alpaca_max_frame_bytes):
            raise SnapshotError('FRAME_LIMIT')
        if self._used + size > min(self.store.profile.max_archive_bytes, self.archive.settings.alpaca_max_archive_bytes):
            raise MetadataError('ARCHIVE_LIMIT')
        stamp = self.archive.now()
        if stamp < self._raw_latest:
            raise MetadataError('SNAPSHOT_NOT_PIT')
        self._raw_latest = stamp
        sequence = self.connection.execute('SELECT accepted_count+1 FROM intraday_ingest_runs WHERE id=?', (run,)).fetchone()[0]
        envelope = EventEnvelope('alpaca', self.store.profile.feed, self.store.profile.profile_id,
            self.store.data_mode, self.store.provenance, self.store.replay_grade, 'EVENT', None,
            logical_key, str(uuid.uuid4()), sequence, stamp, stamp, stamp, None, text)
        row = {name: getattr(envelope, name) for name in (
            'provider', 'feed', 'profile_id', 'data_mode', 'provenance', 'replay_grade', 'schema_version',
            'listing_id', 'logical_key', 'capture_id', 'ingest_sequence', 'source_event_id', 'source_revision_id',
            'event_time_ns', 'received_at_ns', 'persisted_at_ns', 'admitted_at_ns', 'availability_floor_ns', 'payload_json')}
        row.update(ingest_run_id=run, available_at_ns=None, payload_hash=envelope.payload_hash, **fields)
        source_id = self.connection.execute(f"INSERT INTO {table}({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                                            tuple(row.values())).lastrowid
        self.connection.execute('UPDATE intraday_ingest_runs SET accepted_count=accepted_count+1 WHERE id=?', (run,))
        self._used += size
        return int(source_id)

    def read(self, snapshot_id):
        """Exact references only. Never use latest source readers, clocks or provider calls."""
        try:
            return self._read(snapshot_id)
        except (MetadataError, ValueError, KeyError, TypeError, sqlite3.DatabaseError):
            raise MetadataError('SNAPSHOT_INPUT_MISSING') from None

    def _read(self, snapshot_id):
        if type(snapshot_id) is not int or snapshot_id <= 0:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        raw = self.connection.execute('SELECT * FROM intraday_dataset_snapshots WHERE id=?', (snapshot_id,)).fetchone()
        if raw is None or tuple(raw[key] for key in ('profile_id', 'data_mode', 'provenance', 'replay_grade')) != self.store.namespace:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        header = decode_row(raw)
        manifest = header['payload']
        validate_manifest(manifest)
        if (any(header[key] != manifest[key] for key in ('start_at_ns', 'end_at_ns', 'cutoff_ns')) or
                header['policy_id'] != manifest['policy']['id'] or
                [header[k] for k in ('profile_id', 'feed', 'data_mode', 'provenance', 'replay_grade')] != manifest['namespace']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if manifest['policy'] != self._policy() or manifest['profile'] != self._profile():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        query = published_select('intraday_capture_events') + ''' WHERE raw.profile_id=? AND raw.data_mode=?
            AND raw.provenance=? AND raw.replay_grade=? AND raw.kind='BOOTSTRAP'
            AND json_extract(raw.payload_json,'$.metadata_kind')='DATASET_PUBLICATION'
            AND json_extract(raw.payload_json,'$.snapshot_id')=?
            AND EXISTS(SELECT 1 FROM json_each(pub.payload_json,'$.references') ref
                WHERE json_extract(ref.value,'$.table')='intraday_capture_events'
                  AND json_extract(ref.value,'$.id')=raw.id) ORDER BY pub.id,raw.id'''
        publication = self.connection.execute(query, (*self.store.namespace, snapshot_id)).fetchone()
        pub = decode_published(publication, 'intraday_capture_events', MAX_NS) if publication is not None else None
        if pub is None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        proof = pub['payload']
        if pub['ingest_run_id'] != header['ingest_run_id']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        members = [decode_row(row) for row in self.connection.execute(
            'SELECT * FROM intraday_dataset_members WHERE snapshot_id=? ORDER BY ingest_sequence', (snapshot_id,))]
        bodies = [row['payload'] for row in members]
        if (proof.get('complete') is not True or proof['snapshot_hash'] != header['payload_hash'] or
                proof['digest'] != header['digest'] or proof['typed_member_count'] != header['member_count'] or
                len(members) != header['member_count'] or manifest['typed_member_count'] != len(members) or
                _digest(manifest, bodies) != header['digest']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        rows, audits, keys = [], [], set()
        for member, body in zip(members, bodies, strict=True):
            kind, column = _REFERENCES[body['reference']['table']]
            if member['member_kind'] != kind or member[column] != body['reference']['id']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            if (member['ingest_run_id'] != header['ingest_run_id'] or type(body['replay']) is not bool or
                    tuple(member[k] for k in ('profile_id', 'data_mode', 'provenance', 'replay_grade')) != self.store.namespace):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            for reference in [body['reference'], *body['dependencies']]:
                key = reference['table'], reference['id']
                if key in keys:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                keys.add(key)
                hydrated = self._hydrate(reference)
                (rows if body['replay'] else audits).append(hydrated)
        if len(rows) != proof['timeline_count'] or len(rows) != manifest['timeline_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if len(audits) != manifest['audit_member_count']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        _validate_closure(rows, audits)
        links = {}
        for row in rows:
            if row['table'] == 'intraday_news_links':
                links.setdefault(row['news_version_id'], []).append({key: value for key, value in row.items() if key != 'table'})
        for row in rows:
            if row['table'] == 'intraday_news_versions':
                row['links'] = sorted(links.get(row['id'], []), key=lambda item: item['id'])
        report_raw = self.connection.execute('SELECT * FROM intraday_quality_reports WHERE id=? AND snapshot_id=?',
                                              (proof['report_id'], snapshot_id)).fetchone()
        if report_raw is None or self.connection.execute('SELECT COUNT(*) FROM intraday_quality_reports WHERE snapshot_id=?',
                                                        (snapshot_id,)).fetchone()[0] != 1:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        report = decode_row(report_raw)
        if (report['payload_hash'] != proof['report_hash'] or report['outcome'] != report['payload']['outcome'] or
                report['policy_id'] != header['policy_id'] or report['ingest_run_id'] != header['ingest_run_id'] or
                json.loads(report['metrics_json']) != report['payload']['metrics'] or
                json.loads(report['limits_json']) != report['payload']['limits'] or
                proof['durable_at_ns'] < max(row['persisted_at_ns'] for row in [header, report, *members]) or
                proof['durable_at_ns'] < manifest['cutoff_ns'] or
                proof['durable_at_ns'] > pub['available_at_ns']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        replay = replay_frozen(manifest, rows)
        return {'snapshot_id': snapshot_id, 'digest': header['digest'], 'known_at_ns': pub['available_at_ns'],
                'manifest': manifest, 'timeline': replay['timeline'], 'report': report['payload']}

    def replay(self, snapshot_id, *, cutoff_ns=None, listing_ids=None):
        saved = self.read(snapshot_id)
        return replay_frozen(saved['manifest'], saved['timeline'], cutoff_ns=cutoff_ns, listing_ids=listing_ids)


def _validate_closure(rows, audits):
    sources = {(row['table'], row['id']): row for row in [*rows, *audits]}
    def require(table, source_id, payload_hash=None):
        target = sources.get((table, source_id))
        if target is None or (payload_hash is not None and target['payload_hash'] != payload_hash):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return target
    for row in rows:
        table, payload = row['table'], row['payload']
        admission = row.get('admission_id')
        if admission is not None:
            receipt = require('intraday_capture_events', admission)
            kind, column = _REFERENCES[table]
            if (kind not in {'OBSERVATION', 'NEWS', 'EVENT'} or receipt['kind'] != 'ADMISSION' or
                    receipt[column] != row['id'] or receipt['payload']['payload_hash'] != row['payload_hash']):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        publication = row.get('publication_id')
        if publication is not None:
            receipt = require('intraday_capture_events', publication, row.get('publication_hash'))
            proof = receipt['payload']
            reference = {'id': row['id'], 'hash': row['payload_hash'], 'kind': row.get('kind')}
            if proof.get('metadata_kind') == 'COLLECTOR_PUBLICATION':
                valid = proof.get('reference') == reference
            else:
                valid = {'table': table, 'id': row['id'], 'hash': row['payload_hash']} in proof.get('references', [])
            if not valid:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        identity = payload.get('identity') if table in {'intraday_event_versions', 'intraday_news_links'} else None
        if identity is not None:
            target = require('intraday_identity_versions', identity['id'], identity['payload_hash'])
            if target.get('publication_id') != identity['publication_id']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if table == 'intraday_event_versions':
            doc = payload['document']
            require('intraday_capture_events', doc['id'], doc['hash'])
        if table == 'intraday_news_links':
            require('intraday_news_versions', row['news_version_id'], payload['news_hash'])
        if table == 'intraday_universe_members':
            require('intraday_universe_snapshots', row['snapshot_id'])
            require('intraday_identity_versions', row['identity_version_id'], payload['identity_hash'])
        if table == 'intraday_capture_events':
            orphan = payload.get('orphan_raw_proof')
            if orphan:
                require(orphan['table'], orphan['id'], orphan['payload_hash'])
