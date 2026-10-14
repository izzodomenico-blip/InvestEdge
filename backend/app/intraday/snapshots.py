"""Finite immutable datasets. RAW output is invisible until durable publication."""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain
from operator import attrgetter
from pathlib import Path

from pydantic_core import from_json, to_json

from backend.app.data_providers.alpaca_metadata import (
    MAX_NS,
    MetadataError,
    decode_published,
    decode_row,
    published_select,
)
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.intraday.contracts import EventEnvelope, QualityPolicy, canonical_json
from backend.app.intraday.quality import _Index, _sessions, planned_listing_ids, quality_report, validate_manifest
from backend.app.intraday.replay import causal_order, check_ns, replay_frozen, visible_rows
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
_SCOPE = ('profile_id', 'feed', 'data_mode', 'provenance', 'replay_grade')
_REFS_SQL = """WITH refs AS (
    SELECT m.id AS member_id,json_extract(m.payload_json,'$.reference') AS reference_json,
      json_extract(m.payload_json,'$.replay') AS replay
    FROM intraday_dataset_members m WHERE m.snapshot_id=:snapshot
    UNION ALL
    SELECT m.id,dependency.value,json_extract(m.payload_json,'$.replay')
    FROM intraday_dataset_members m,json_each(m.payload_json,'$.dependencies') dependency
    WHERE m.snapshot_id=:snapshot AND json_array_length(m.payload_json,'$.dependencies')>0
)"""


_MEMBER_SOURCE_TABLE_SQL = 'CASE m.member_kind '+ ' '.join(
    f"WHEN '{kind}' THEN '{table}'" for table,(kind,column) in _REFERENCES.items())+' END'
_MEMBER_SOURCE_ID_SQL = 'CASE m.member_kind '+ ' '.join(
    f"WHEN '{kind}' THEN m.{column}" for kind,column in _REFERENCES.values())+' END'


def _locator_refs_sql(*, bundle=False):
    """Only validated handles use these small, exact member locators."""
    relation = ('FROM intraday_research_bundle_children c JOIN intraday_dataset_members m ON m.snapshot_id=c.snapshot_id'
                if bundle else 'FROM intraday_dataset_members m')
    scope = 'c.bundle_id=:snapshot' if bundle else 'm.snapshot_id=:snapshot'
    root_ref = ",json_extract(m.payload_json,'$.reference') AS reference_json" if bundle else ''
    dependency_ref = ',dependency.value' if bundle else ''
    inputs = f'''SELECT m.id AS member_id,-1 AS dependency_ordinal,
        {_MEMBER_SOURCE_TABLE_SQL} AS source_table,{_MEMBER_SOURCE_ID_SQL} AS source_id{root_ref}
        {relation} WHERE {scope} AND json_extract(m.payload_json,'$.replay')=1
        UNION ALL SELECT m.id,dependency.key,json_extract(dependency.value,'$.table'),
            json_extract(dependency.value,'$.id'){dependency_ref}
        {relation},json_each(m.payload_json,'$.dependencies') dependency
        WHERE {scope} AND json_extract(m.payload_json,'$.replay')=1
          AND json_array_length(m.payload_json,'$.dependencies')>0'''
    if not bundle:
        return f'WITH refs AS ({inputs})'
    # Canonical reference objects are prefix-free. A locator suffix changes
    # only ties with identical reference text, whose selected bytes are equal.
    # Member IDs retain the entire signed int64 domain (including INT64_MIN).
    return f'''WITH child_refs AS NOT MATERIALIZED ({inputs}),choices AS NOT MATERIALIZED (
        SELECT source_table,source_id,MIN(printf('%019d',COALESCE(
            json_extract(reference_json,'$.projection.available_at_ns'),9223372036854775807))
            ||reference_json||printf('%020d',member_id)||printf('%019d',dependency_ordinal+1)) AS choice
        FROM child_refs GROUP BY source_table,source_id
    ),refs AS MATERIALIZED (
        SELECT source_table,source_id,CAST(substr(choice,-39,20) AS INTEGER) AS member_id,
            CAST(substr(choice,-19) AS INTEGER)-1 AS dependency_ordinal FROM choices
    )'''


_ORDER_REFS_SQL = _locator_refs_sql()


class SnapshotError(MetadataError):
    """Additional fixed public errors without reflecting caller or SQL text."""
    def __init__(self, code):
        self.code = code if code in {'POLICY_MISSING', 'QUALITY_POLICY_INVALID', 'SYMBOL_LIMIT',
                                    'CANCELLED', 'FRAME_LIMIT', 'RESOURCE_LIMIT'} else 'METADATA_INVALID'
        self.reason_code = self.code
        ValueError.__init__(self, self.code)


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


_ENVELOPE_ENCODER = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
# Fresh SQLite headers and decoded projections are acyclic. This encoder has
# no shared markers or caller values; its v1 options match JSONEncoder exactly.
_OWNED_HEADER_ENCODER = (json.encoder.c_make_encoder(None,_ENVELOPE_ENCODER.default,
    json.encoder.encode_basestring,None,':',',',True,False,False)
    if json.encoder.c_make_encoder is not None else None)


def _envelope_bytes(row, *, _owned=False):
    # Payloads have already passed their own canonical/hash validation. The
    # decoded envelope also contains payload_json and has a separate chunk cap.
    if _owned and _OWNED_HEADER_ENCODER is not None:
        return ''.join(_OWNED_HEADER_ENCODER(row,0)).encode()
    return _ENVELOPE_ENCODER.encode(row).encode()


def _json_integer(text):
    value = int(text)
    if len(text)>308 and not math.isfinite(float(value)):
        raise ValueError('METADATA_INVALID')
    return value


_EVIDENCE_DECODER = json.JSONDecoder(parse_int=_json_integer)
_LONG_INTEGER = re.compile(rb'(?<![0-9])[0-9]{309}')


def _native_canonical(value):
    """Native JSON keeps integer/string bytes; v1 float formatting stays stdlib."""
    pending,native = [value],True
    while pending:
        item = pending.pop()
        kind = type(item)
        if kind is dict:
            if tuple(item)!=tuple(sorted(item)):
                native = False
            pending.extend(item.values())
        elif kind is list:
            pending.extend(item)
        elif kind is float:
            # JSONEncoder uses float.__repr__. Native output is eligible only
            # when each scalar has exactly those v1 bytes (including -0/exponents).
            native = (to_json(item)==float.__repr__(item).encode()) and native
        elif kind is int and item.bit_length()>=1024 and not math.isfinite(float(item)):
            raise ValueError('METADATA_INVALID')
    return native


def _canonical_evidence_bytes(payload, raw_utf8):
    # Parsed JSON is acyclic. The stdlib C encoder preserves v1 sorting and
    # float bytes, and rejects nonfinite floats. Integers with at most 308
    # decimal digits are finite as floats; longer digit runs (including false
    # positives inside strings) retain the full v1 numeric validation below.
    if _OWNED_HEADER_ENCODER is not None and _LONG_INTEGER.search(raw_utf8) is None:
        return ''.join(_OWNED_HEADER_ENCODER(payload,0)).encode()
    if _native_canonical(payload):
        try:
            return to_json(payload)
        except ValueError:
            pass
    return _envelope_bytes(payload)


def _decode_evidence(raw, *, _member_scope=None):
    """Same canonical/hash contract, with JSON-native types validated once."""
    if raw is None:
        raise MetadataError('METADATA_MISSING')
    row = dict(raw)
    try:
        if type(row['payload_json']) is not str:
            raise ValueError
        raw_utf8 = row['payload_json'].encode()
        if len(raw_utf8)>1_048_576:
            raise ValueError
        try:
            payload = from_json(raw_utf8, allow_inf_nan=False, cache_strings=False)
        except ValueError:
            payload = _EVIDENCE_DECODER.decode(row['payload_json'])
        if type(payload) is not dict:
            raise ValueError
        if _member_scope is not None and _member_scope.canonical_member(payload,raw_utf8):
            encoded = raw_utf8
        else:
            encoded = _canonical_evidence_bytes(payload,raw_utf8)
        if (len(encoded)>1_048_576 or encoded!=raw_utf8
            or hashlib.sha256(encoded).hexdigest()!=row['payload_hash']):
            raise ValueError
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
        raise MetadataError('METADATA_INVALID') from None
    row['payload'] = payload
    return row


class _ValidationRow(dict):
    """Job/read-local size proof; never part of a public timeline envelope."""
    __slots__ = ('_byte_bound',)


def _row_byte_bound(row, *, _decoded=False):
    if _decoded and isinstance(row, _ValidationRow):
        return row._byte_bound
    if _decoded and 'payload_json' in row and 'payload' in row:
        # Only freshly decoded, validated archive rows use this path. The
        # canonical payload has exactly these UTF-8 bytes; key order changes
        # no length. Public/caller-owned values keep the full encoder below.
        header = {key:value for key,value in row.items() if key not in {'payload','payload_json'}}
        text = row['payload_json']
        # Canonical JSON has no literal control characters: quoting its text
        # adds one byte per quote/backslash and the two enclosing quotes.
        return (len(_envelope_bytes(header,_owned=True)) + bool(header) + 28 + 2*len(text.encode())
                + text.count('"') + text.count('\\'))
    return len(_envelope_bytes(row))


def _peak_rss_bytes():
    if os.name != 'nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform=='darwin' else 1024)
    class Counters(ctypes.Structure):
        _fields_ = [('cb',ctypes.c_ulong),('faults',ctypes.c_ulong),
            *[(name,ctypes.c_size_t) for name in ('peak','working','paged_peak','paged','nonpaged_peak','nonpaged','pagefile','pagefile_peak')]]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel,psapi = ctypes.WinDLL('kernel32'),ctypes.WinDLL('psapi')
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
        raise SnapshotError('RESOURCE_LIMIT')
    return counters.peak


def _source_hash(row):
    return _hash({key: value for key, value in row.items() if key != 'payload_json'})


def _reference_identity(reference):
    return _envelope_bytes(reference | {'projection':{
        key:value for key,value in reference['projection'].items() if key!='available_at_ns'}})


def _digest(manifest, members):
    result = hashlib.sha256()
    for value in chain((manifest,), members):
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


def _reference_batches(cursor, *, max_bytes=2_097_152):
    """Bound canonical reference texts before allocating their decoded trees."""
    batch, size = [], 0
    for item in cursor:
        if type(item[0]) is not str:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        item_size = len(item[0].encode())
        if item_size > max_bytes:
            raise SnapshotError('RESOURCE_LIMIT')
        if batch and (len(batch)==1000 or size+item_size>max_bytes):
            yield batch
            batch, size = [], 0
        batch.append(item)
        size += item_size
    if batch:
        yield batch


@dataclass(frozen=True)
class ValidatedDataset:
    snapshot_id: int
    digest: str
    known_at_ns: int
    manifest: dict
    report: dict
    timeline: FrozenTimeline
    publication_id: int
    publication_hash: str

    def as_dict(self):
        return {'snapshot_id': self.snapshot_id, 'digest': self.digest, 'known_at_ns': self.known_at_ns,
                'manifest': json.loads(canonical_json(self.manifest)),
                'report': json.loads(canonical_json(self.report)), 'timeline': self.timeline}


class FrozenTimeline:
    """Re-iterable exact references. Full validation precedes every public handle."""
    def __init__(self, reader, snapshot_id, manifest, count, *, max_occurrences=10_000, max_bytes=8_388_608,
                 refs_sql=_REFS_SQL, links=None, _signature=None, _order_refs_sql=None):
        self.reader, self.snapshot_id, self.manifest, self.count = reader, snapshot_id, manifest, count
        self.max_occurrences, self.max_bytes = max_occurrences, max_bytes
        self.refs_sql = refs_sql
        self._order_refs_sql = (_ORDER_REFS_SQL if refs_sql==_REFS_SQL else None) if _order_refs_sql is None else _order_refs_sql
        self.links = links or (lambda news_id: reader._frozen_links(snapshot_id,news_id))
        self.validator = lambda: reader.open(snapshot_id,max_occurrences=max_occurrences,max_bytes=max_bytes)
        self.signature = reader._read_signature() if _signature is None else _signature

    def __len__(self):
        return self.count

    def __iter__(self):
        return self.iter_rows()

    def _fence(self, *, buffered=False):
        if self.signature!=self.reader._read_signature():
            if buffered:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            self.validator()
            self.signature = self.reader._read_signature()

    def _ordered(self, cutoff):
        if self._order_refs_sql is None:
            # Preserve custom reference selectors used by earlier callers.
            return self._legacy_ordered(cutoff)
        path = "(CASE WHEN r.dependency_ordinal<0 THEN '$.reference' ELSE '$.dependencies['||r.dependency_ordinal||']' END)"
        def projection(field):
            return f"json_extract(m.payload_json,{path}||'.projection.{field}')"
        selects = []
        for table in sorted(_SOURCE_TABLES):
            selects.append(f'''SELECT r.member_id,r.dependency_ordinal,
                raw.received_at_ns,raw.capture_id,raw.ingest_sequence,raw.id,'{table}' AS source_table,
                COALESCE({projection('available_at_ns')},raw.available_at_ns) AS available,
                COALESCE({projection('admission_id')},{projection('publication_id')},raw.id) AS proof_id,
                COALESCE({projection('capture_ingest_sequence')},
                    json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence) AS intake
                FROM refs r JOIN intraday_dataset_members m ON m.id=r.member_id
                JOIN {table} raw ON raw.id=r.source_id WHERE r.source_table='{table}' ''')
        query = self._order_refs_sql+',occurrences AS ('+' UNION ALL '.join(selects)+'''),visible AS (
            SELECT *,MIN(proof_id) OVER(PARTITION BY received_at_ns,capture_id) AS anchor
            FROM occurrences WHERE available<=:cutoff
        ),ordered AS (
            SELECT member_id,dependency_ordinal FROM visible
            ORDER BY available,received_at_ns,anchor,intake,proof_id,ingest_sequence,source_table,id
        ) SELECT (SELECT json_extract(m.payload_json,
            CASE WHEN o.dependency_ordinal<0 THEN '$.reference'
                ELSE '$.dependencies['||o.dependency_ordinal||']' END)
            FROM intraday_dataset_members m WHERE m.id=o.member_id) AS reference_json FROM ordered o'''
        return self.reader.connection.execute(query,{'snapshot':self.snapshot_id,'cutoff':cutoff})

    def _legacy_ordered(self, cutoff):
        selects = []
        for table in sorted(_SOURCE_TABLES):
            selects.append(f"""SELECT r.reference_json,raw.received_at_ns,raw.capture_id,raw.ingest_sequence,
                raw.id,'{table}' AS source_table,
                COALESCE(json_extract(r.reference_json,'$.projection.available_at_ns'),raw.available_at_ns) AS available,
                COALESCE(json_extract(r.reference_json,'$.projection.admission_id'),
                         json_extract(r.reference_json,'$.projection.publication_id'),raw.id) AS proof_id,
                COALESCE(json_extract(r.reference_json,'$.projection.capture_ingest_sequence'),
                         json_extract(raw.payload_json,'$.intake_sequence'),raw.ingest_sequence) AS intake
                FROM refs r JOIN {table} raw ON raw.id=json_extract(r.reference_json,'$.id')
                WHERE r.replay=1 AND json_extract(r.reference_json,'$.table')='{table}'""")
        query = self.refs_sql + ', occurrences AS (' + ' UNION ALL '.join(selects) + """), visible AS (
            SELECT *,MIN(proof_id) OVER(PARTITION BY received_at_ns,capture_id) AS anchor
            FROM occurrences WHERE available<=:cutoff
        ) SELECT reference_json FROM visible
        ORDER BY available,received_at_ns,anchor,intake,proof_id,ingest_sequence,source_table,id"""
        return self.reader.connection.execute(query, {'snapshot': self.snapshot_id, 'cutoff': cutoff})

    def iter_rows(self, *, cutoff_ns=None):
        return self._iter_rows(cutoff_ns=cutoff_ns, public_rows=True)

    def _iter_rows(self, *, cutoff_ns, public_rows):
        cutoff = self.manifest['cutoff_ns'] if cutoff_ns is None else cutoff_ns
        check_ns(cutoff)
        if cutoff > self.manifest['cutoff_ns'] or (self.manifest.get('version') in {'intraday-dataset-v2','intraday-bundle-quality-v1'}
                and cutoff < self.manifest['carry_at_ns']):
            raise ValueError('SNAPSHOT_CUTOFF')
        if _peak_rss_bytes()>self.manifest.get('resources',{}).get('max_rss_bytes',2_147_483_648):
            raise SnapshotError('RESOURCE_LIMIT')
        self._fence()
        cursor = self._ordered(cutoff)
        for items in _reference_batches(cursor):
            self._fence(buffered=True)
            for rows in self.reader._hydrated_batches([json.loads(item[0]) for item in items],validated=True):
                if _peak_rss_bytes()>self.manifest.get('resources',{}).get('max_rss_bytes',2_147_483_648):
                    raise SnapshotError('RESOURCE_LIMIT')
                self._fence(buffered=True)
                for row in rows:
                    if public_rows:
                        self._fence(buffered=True)
                    row.pop('capture_order', None)
                    if row['table'] == 'intraday_news_versions':
                        row['links'] = self.links(row['id'])
                        if _peak_rss_bytes()>self.manifest.get('resources',{}).get('max_rss_bytes',2_147_483_648):
                            raise SnapshotError('RESOURCE_LIMIT')
                        self._fence(buffered=True)
                    yield row

    def chunks(self, *, cutoff_ns=None):
        chunk, size = [], 0
        # Rows stay private until the chunk's fence below. Public row iteration
        # keeps its per-row fence; hydration and news links retain batch fences.
        for row in self._iter_rows(cutoff_ns=cutoff_ns,public_rows=False):
            row_size = _row_byte_bound(row, _decoded=True)
            if row_size>self.max_bytes:
                row_size = len(_envelope_bytes(row))
            if row_size > self.max_bytes:
                raise SnapshotError('RESOURCE_LIMIT')
            if chunk and (len(chunk) == self.max_occurrences or size + row_size > self.max_bytes):
                if _peak_rss_bytes()>self.manifest.get('resources',{}).get('max_rss_bytes',2_147_483_648):
                    raise SnapshotError('RESOURCE_LIMIT')
                self._fence(buffered=True)
                yield chunk
                chunk, size = [], 0
            chunk.append(row)
            size += row_size
        if chunk:
            if _peak_rss_bytes()>self.manifest.get('resources',{}).get('max_rss_bytes',2_147_483_648):
                raise SnapshotError('RESOURCE_LIMIT')
            self._fence(buffered=True)
            yield chunk

    def page(self, *, offset=0, limit=50, input_type='ALL'):
        tables = {'NEWS': 'intraday_news_versions', 'EVENT': 'intraday_event_versions',
                  'IDENTITY': 'intraday_identity_versions', 'CALENDAR': 'intraday_calendar_versions',
                  'UNIVERSE': 'intraday_universe_snapshots', 'CAPTURE': 'intraday_capture_events'}
        if (type(offset) is not int or not 0 <= offset <= 10_000_000 or type(limit) is not int
            or not 1 <= limit <= 200 or type(input_type) is not str or input_type not in {'ALL', 'BAR', 'QUOTE', *tables}):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        items, total, size, full = [], 0, 0, False
        for row in self:
            matched = (input_type == 'ALL' or input_type in {'BAR', 'QUOTE'} and row.get('kind') == input_type
                       or input_type in tables and (row['table'] == tables[input_type]
                           or input_type == 'UNIVERSE' and row['table'] == 'intraday_universe_members'))
            if matched:
                if offset <= total < offset + limit and not full:
                    row_size = _row_byte_bound(row, _decoded=True)
                    if row_size>self.max_bytes:
                        row_size = len(_envelope_bytes(row))
                    if row_size>self.max_bytes:
                        raise SnapshotError('RESOURCE_LIMIT')
                    if len(items)==self.max_occurrences or size+row_size>self.max_bytes:
                        full = True
                    else:
                        items.append(row)
                        size += row_size
                total += 1
        if _peak_rss_bytes()>self.manifest.get('resources',{}).get('max_rss_bytes',2_147_483_648):
            raise SnapshotError('RESOURCE_LIMIT')
        self._fence(buffered=True)
        return {'items': items, 'total': total, 'offset': offset, 'limit': limit,
                'next_offset': offset + len(items) if offset + len(items) < total else None}


class _ValidatedSources:
    """One read scope: digest/size proofs, bounded global LRU, no durable cache."""
    _PAGE_IDS = 1024
    _ENTRY_BYTES = 76  # two SHA256, exact envelope size, effective availability ns
    # Include page buffers, bitmap, key/node/allocator overhead and transients.
    _PAGE_CHARGE = _PAGE_IDS * _ENTRY_BYTES + 128 + _PAGE_IDS + 1024
    _PROMOTE = bytes(value & 127 for value in range(256))
    _DISCARD = bytes(0 if value & 128 else value for value in range(256))
    _MEMBER_PREFIX = b'{"dependencies":[],"reference":'
    _MEMBER_SUFFIX = b',"replay":true}'

    def __init__(self, reader, budget, signature):
        self.reader, self.connection, self.signature = reader, reader.connection, signature
        self.namespace = self._namespace()
        self.budget = max(0, budget - 4096)
        self.pages = OrderedDict()
        self.closed = False

    def _namespace(self):
        store = self.reader.store
        return (store.profile.profile_id, store.profile.feed, *store.namespace[1:])

    def check(self, reader, *, full=False):
        if (self.closed or reader is not self.reader or reader.connection is not self.connection
            or self.connection.total_changes-getattr(reader,'_scratch_changes',0) != self.signature[0]
            or reader._secret_state() != self.signature[3]
            or full and (self._namespace()!=self.namespace or reader._read_signature()!=self.signature)):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')

    def get(self, reader, table, source_id):
        self.check(reader)
        key, offset = (table, source_id // self._PAGE_IDS), source_id % self._PAGE_IDS
        page = self.pages.get(key)
        if page is None or not page[1][offset//8] & (1 << (offset%8)):
            return None
        self.pages.move_to_end(key)
        position = self._ENTRY_BYTES*offset
        return page[0][position:position+32].hex()

    def remember(self, reader, table, source_id, source_hash):
        self.check(reader)
        if self.budget < self._PAGE_CHARGE:
            return
        key, offset = (table, source_id // self._PAGE_IDS), source_id % self._PAGE_IDS
        page = self.pages.get(key)
        if page is None:
            while (len(self.pages)+1)*self._PAGE_CHARGE > self.budget:
                self.pages.popitem(last=False)
            page = (bytearray(self._PAGE_IDS*self._ENTRY_BYTES), bytearray(self._PAGE_IDS//8),
                    bytearray(self._PAGE_IDS))
            self.pages[key] = page
        self.pages.move_to_end(key)
        position = self._ENTRY_BYTES*offset
        page[0][position:position+32] = bytes.fromhex(source_hash)
        page[2][offset] = 0
        page[1][offset//8] |= 1 << (offset%8)

    def byte_bound(self, row, reference):
        self.check(self.reader)
        key, offset = (reference['table'],reference['id']//self._PAGE_IDS), reference['id']%self._PAGE_IDS
        page = self.pages.get(key)
        if page is None:
            return _row_byte_bound(row, _decoded=True)
        position = self._ENTRY_BYTES*offset
        proof = hashlib.sha256(_envelope_bytes(reference)).digest()
        size = int.from_bytes(page[0][position+64:position+68])
        if size and page[0][position+32:position+64] == proof:
            self.pages.move_to_end(key)
            return size
        size = _row_byte_bound(row, _decoded=True)
        page[2][offset] = 0
        page[0][position+32:position+64] = proof
        page[0][position+64:position+68] = size.to_bytes(4)
        return size

    def complete(self, reference, row):
        """Attest only simple replay rows, after source/visibility/closure pass."""
        if (type(row.get('available_at_ns')) is not int or row.get('publication_id') is not None
            or row['table']=='intraday_capture_events' and (row.get('admission_id') is not None
                or row.get('kind')!='ADMISSION' or row['payload'].get('orphan_raw_proof')
                or row['payload'].get('metadata_kind')=='COLLECTOR_HANDSHAKE'
                or row['payload'].get('version')!='intraday-admission-v1'
                or set(row['payload'])!={'version','observation_id','payload_hash','durable_at_ns'})):
            return
        flag = (1 if row['table']=='intraday_capture_events' else
                2 if row['table']=='intraday_observations' and row.get('admission_id') is not None else 0)
        key,offset = (reference['table'],reference['id']//self._PAGE_IDS),reference['id']%self._PAGE_IDS
        page = self.pages.get(key)
        if page is not None and flag:
            position = self._ENTRY_BYTES*offset
            page[0][position+68:position+76] = row['available_at_ns'].to_bytes(8)
            page[2][offset] = flag | 128

    def finish_child(self, *, valid):
        if valid:
            self.check(self.reader, full=True)
        translation = self._PROMOTE if valid else self._DISCARD
        for page in self.pages.values():
            page[2][:] = page[2].translate(translation)

    def completed(self, reference, cutoff, max_bytes):
        self.check(self.reader)
        key,offset = (reference['table'],reference['id']//self._PAGE_IDS),reference['id']%self._PAGE_IDS
        page = self.pages.get(key)
        if page is None or not page[2][offset] or page[2][offset] & 128:
            return None
        position = self._ENTRY_BYTES*offset
        proof = hashlib.sha256(_envelope_bytes(reference)).digest()
        if page[0][position+32:position+64] != proof:
            return None
        at = int.from_bytes(page[0][position+68:position+76])
        size = int.from_bytes(page[0][position+64:position+68])
        if at>cutoff:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if size>max_bytes:
            raise SnapshotError('RESOURCE_LIMIT')
        row = _ValidationRow({'table':reference['table'],'id':reference['id'],'payload_hash':reference['payload_hash'],
                              'payload':{},**reference['projection']})
        row['available_at_ns'] = at
        if page[2][offset]==1:
            row['kind'] = 'ADMISSION'
        row._byte_bound = size
        self.pages.move_to_end(key)
        return row

    def canonical_member(self, payload, raw_utf8):
        """Reuse only an exact canonical reference from a completed child.

        The fixed v1 wrapper and the promoted full-reference SHA attest these
        bytes without retaining a second proof. The caller still verifies the
        current member SHA, child digest, typed binding and closure.
        """
        self.check(self.reader)
        if not raw_utf8.startswith(self._MEMBER_PREFIX) or not raw_utf8.endswith(self._MEMBER_SUFFIX):
            return False
        reference = payload.get('reference')
        if type(reference) is not dict:
            return False
        table,source_id = reference.get('table'),reference.get('id')
        if table not in _SOURCE_TABLES or type(source_id) is not int or source_id<=0:
            return False
        key,offset = (table,source_id//self._PAGE_IDS),source_id%self._PAGE_IDS
        page = self.pages.get(key)
        if (page is None or not page[1][offset//8] & (1 << (offset%8))
            or not page[2][offset] or page[2][offset] & 128):
            return False
        position = self._ENTRY_BYTES*offset+32
        reference_bytes = memoryview(raw_utf8)[len(self._MEMBER_PREFIX):-len(self._MEMBER_SUFFIX)]
        if hashlib.sha256(reference_bytes).digest()!=page[0][position:position+32]:
            return False
        self.pages.move_to_end(key)
        return True

    def close(self):
        self.pages.clear()
        self.closed = True


class _StagedTimeline:
    """Job-local disk index. Never created by a public GET or retained as a cache."""
    def __init__(self, reader, manifest, resources):
        self.reader, self.db, self.manifest = reader, reader.connection, manifest
        self.resources = resources
        suffix = uuid.uuid4().hex
        self.index, self.stage = 'timeline_index_' + suffix, 'timeline_stage_' + suffix
        store = reader.store
        meta_provenance = 'CAPTURED' if store.data_mode == 'REAL' else 'SYNTHETIC'
        meta_grade = 'STRICT_PIT' if store.data_mode == 'REAL' else 'RESEARCH_ONLY'
        params = {'profile': store.profile.profile_id, 'mode': store.data_mode, 'provenance': store.provenance,
                  'grade': store.replay_grade, 'meta_provenance': meta_provenance, 'meta_grade': meta_grade,
                  'same_namespace': int((store.provenance, store.replay_grade) == (meta_provenance, meta_grade)),
                  'cutoff': manifest['cutoff_ns']}
        self.db.execute(f'CREATE TEMP TABLE {self.index} AS ' + store._timeline_query(), params)
        self.db.execute(f'CREATE UNIQUE INDEX {self.index}_key ON {self.index}(source_table,source_id)')
        self._create_stage()
        self.check_budget()

    def _create_stage(self):
        self.db.execute(f'''CREATE TEMP TABLE {self.stage}(source_table TEXT,source_id INTEGER,
            replay INTEGER NOT NULL,processed INTEGER NOT NULL DEFAULT 0,
            kind TEXT,listing_id INTEGER,event_time_ns INTEGER,available_at_ns INTEGER,capture_id TEXT,received_at_ns INTEGER,
            row_json TEXT,reference_json TEXT,
            PRIMARY KEY(source_table,source_id)) WITHOUT ROWID''')
        self.db.execute(f'CREATE INDEX {self.stage}_market ON {self.stage}(kind,listing_id,available_at_ns,event_time_ns)')
        self.db.execute(f'CREATE INDEX {self.stage}_event ON {self.stage}(event_time_ns)')
        self.db.execute(f'CREATE INDEX {self.stage}_pending ON {self.stage}(processed,source_table,source_id)')
        self.db.execute(f'CREATE INDEX {self.stage}_liveness ON {self.stage}(kind,capture_id,received_at_ns,available_at_ns)')

    @classmethod
    def from_frozen(cls, reader, manifest, resources, datasets, *, cancelled=None):
        result = cls.__new__(cls)
        result.reader, result.db, result.manifest, result.resources = reader, reader.connection, manifest, resources
        suffix = uuid.uuid4().hex
        result.index, result.stage = 'timeline_index_' + suffix, 'timeline_stage_' + suffix
        result._create_stage()
        try:
            processed = 0
            for dataset in datasets:
                reader._cancel(cancelled, 'DURING_BUNDLE_STAGING')
                if isinstance(dataset, ValidatedDataset):
                    timeline = dataset.timeline
                    if timeline.reader is not reader or timeline.snapshot_id != dataset.snapshot_id:
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    timeline._fence(buffered=True)
                    cursor = reader.connection.execute(_REFS_SQL+' SELECT reference_json FROM refs WHERE replay=1',
                                                       {'snapshot':dataset.snapshot_id})
                    for items in _reference_batches(cursor):
                        processed += len(items)
                        result.check_budget()
                        reader._cancel(cancelled, 'DURING_BUNDLE_STAGING')
                        timeline._fence(buffered=True)
                        result._frozen_batch(dataset,[json.loads(item[0]) for item in items])
                        timeline._fence(buffered=True)
                    cursor.close()
                    continue
                for row in dataset.timeline:
                    processed += 1
                    if processed % 1000 == 0:
                        result.check_budget()
                        reader._cancel(cancelled, 'DURING_BUNDLE_STAGING')
                    ref = reader._reference(row)
                    previous = result.db.execute(f'SELECT reference_json FROM {result.stage} WHERE source_table=? AND source_id=?',
                                                 (row['table'],row['id'])).fetchone()
                    if previous:
                        old = json.loads(previous[0])
                        if _reference_identity(old) != _reference_identity(ref):
                            raise MetadataError('SNAPSHOT_INPUT_MISSING')
                        previous_at = old['projection'].get('available_at_ns',row['available_at_ns'])
                        if previous_at <= row['available_at_ns']:
                            continue
                        changed = result.db.execute(f'DELETE FROM {result.stage} WHERE source_table=? AND source_id=?', (row['table'],row['id'])).rowcount
                        reader._scratch_changes = getattr(reader,'_scratch_changes',0)+changed
                    encoded = _envelope_bytes(row)
                    if len(encoded) > resources['max_chunk_bytes']:
                        raise SnapshotError('RESOURCE_LIMIT')
                    changed = result.db.execute(f'''INSERT INTO {result.stage}(source_table,source_id,row_json,reference_json,replay,processed,
                        kind,listing_id,event_time_ns,available_at_ns,capture_id,received_at_ns) VALUES(?,?,?,?,1,1,?,?,?,?,?,?)''',
                        (row['table'],row['id'],encoded.decode(),canonical_json(ref),row.get('kind'),row.get('listing_id'),
                         row.get('event_time_ns'),row['available_at_ns'],row['capture_id'],row['received_at_ns'])).rowcount
                    # Only our private TEMP index writes are excluded from the
                    # source epoch. Main writes, triggers and rotations still fence.
                    reader._scratch_changes = getattr(reader,'_scratch_changes',0)+changed
            result.check_budget()
            reader._cancel(cancelled, 'DURING_BUNDLE_STAGING')
            return result
        except Exception:
            result.close()
            raise

    def _frozen_batch(self, dataset, references):
        """Consume already validated refs, deduplicate before bounded hydration."""
        by_table = {}
        for ref in references:
            by_table.setdefault(ref['table'],[]).append(ref['id'])
        previous = {}
        for table,ids in by_table.items():
            placeholders = ','.join('?' for _ in ids)
            query = f'SELECT source_id,reference_json FROM {self.stage} WHERE source_table=? AND source_id IN ({placeholders})'
            previous.update({(table,item[0]):json.loads(item[1]) for item in self.db.execute(query,(table,*ids))})
        pending = []
        for ref in references:
            old = previous.get((ref['table'],ref['id']))
            if old is not None:
                if _reference_identity(old) != _reference_identity(ref):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                old_at, new_at = old['projection'].get('available_at_ns'), ref['projection'].get('available_at_ns')
                if old_at is None and new_at is None:
                    continue
                if old_at is None or new_at is None:
                    raw_at = self.reader._raw_source(ref['table'],ref['id'])['available_at_ns']
                    old_at = raw_at if old_at is None else old_at
                    new_at = raw_at if new_at is None else new_at
                if old_at <= new_at:
                    continue
            pending.append(ref)
        offset = 0
        for rows in self.reader._hydrated_batches(pending,validated=True) if pending else ():
            values = []
            for row,ref in zip(rows,pending[offset:offset+len(rows)],strict=True):
                if row['table']=='intraday_news_versions':
                    row['links'] = self.reader._frozen_links(dataset.snapshot_id,row['id'])
                encoded = _envelope_bytes(row)
                if len(encoded)>self.resources['max_chunk_bytes']:
                    raise SnapshotError('RESOURCE_LIMIT')
                values.append((row['table'],row['id'],encoded.decode(),canonical_json(ref),row.get('kind'),
                    row.get('listing_id'),row.get('event_time_ns'),row['available_at_ns'],row['capture_id'],row['received_at_ns']))
            changed = self.db.executemany(f'''INSERT OR REPLACE INTO {self.stage}
                (source_table,source_id,row_json,reference_json,replay,processed,kind,listing_id,event_time_ns,
                 available_at_ns,capture_id,received_at_ns) VALUES(?,?,?,?,1,1,?,?,?,?,?,?)''',values).rowcount
            self.reader._scratch_changes = getattr(self.reader,'_scratch_changes',0)+changed
            offset += len(rows)

    def check_budget(self):
        size = self.db.execute('PRAGMA temp.page_count').fetchone()[0] * self.db.execute('PRAGMA temp.page_size').fetchone()[0]
        main = next((row[2] for row in self.db.execute('PRAGMA database_list') if row[1] == 'main'), '')
        directory = Path(main).parent if main else Path(tempfile.gettempdir())
        size += self.db.execute('PRAGMA main.page_count').fetchone()[0]*self.db.execute('PRAGMA main.page_size').fetchone()[0]
        if (size > self.resources['max_disk_bytes'] or shutil.disk_usage(directory).free < self.resources['min_free_bytes']
            or _peak_rss_bytes()>self.resources.get('max_rss_bytes',2_147_483_648)):
            raise SnapshotError('RESOURCE_LIMIT')

    def close(self):
        for table in (self.stage, self.index):
            self.db.execute(f'DROP TABLE IF EXISTS temp.{table}')

    def seed(self, query, params=()):
        self.db.execute(f'''INSERT OR IGNORE INTO {self.stage}(source_table,source_id,replay)
            SELECT source_table,source_id,1 FROM ({query})''', params)

    def select(self):
        m = self.manifest
        if m['version'] == 'intraday-dataset-v1':
            self.seed(f'SELECT source_table,source_id FROM {self.index}')
            return
        start, end, carry = m['start_at_ns'], m['end_at_ns'], m['carry_at_ns']
        # Economic changes are selected by availability, including late revisions
        # of pre-period observations and news, and unrelated liveness receipts.
        self.seed(f'SELECT source_table,source_id FROM {self.index} WHERE known>=?', (start,))
        calendar_rows,size = [],0
        query = f'''SELECT i.* FROM {self.index} i WHERE i.source_table='intraday_calendar_versions'
            OR i.source_table='intraday_capture_events' AND EXISTS(SELECT 1 FROM intraday_capture_events raw
                WHERE raw.id=i.source_id AND json_extract(raw.payload_json,'$.metadata_kind')='CALENDAR')'''
        for occurrence in self.db.execute(query):
            row = self.reader.store._timeline_row(occurrence,m['cutoff_ns'])
            size += _row_byte_bound(row)
            if size>self.resources['max_cache_bytes']:
                raise SnapshotError('RESOURCE_LIMIT')
            calendar_rows.append(row)
        index = _Index(calendar_rows,max_cache_bytes=self.resources['max_cache_bytes'])
        m['window_session_count'] = len(_sessions(m,index,set()))
        earliest = min((row['open_at_ns'] for row in calendar_rows if row['table']=='intraday_calendar_versions'),default=start)
        previous = []
        if earliest<start:
            history = _Index([row for row in calendar_rows if row['available_at_ns']<=carry],
                             max_cache_bytes=self.resources['max_cache_bytes'])
            candidates = _sessions(m | {'start_at_ns':earliest,'end_at_ns':start,'cutoff_ns':carry},history,set())
            previous = [(row,valid) for row,valid in candidates if row['close_at_ns']<=start][-m['history_sessions']:]
        warm_start = min((row['open_at_ns'] for row,valid in previous),default=start)
        m['support_start_at_ns'] = warm_start
        if m['window_session_count'] > self.resources['window_sessions']:
            raise SnapshotError('RESOURCE_LIMIT')
        availability_sessions = len(_sessions(m | {'end_at_ns':max(end,m['cutoff_ns'])},index,set()))
        if availability_sessions>self.resources['window_sessions']:
            raise SnapshotError('RESOURCE_LIMIT')
        self.seed(f'''SELECT i.source_table,i.source_id FROM {self.index} i JOIN intraday_observations raw
            ON raw.id=i.source_id WHERE i.source_table='intraday_observations' AND i.known<=?
            AND raw.kind='BAR' AND raw.event_time_ns>=? AND raw.event_time_ns<?''', (carry, warm_start, start))
        # A quote carry is the latest event time, even when invalid or stale. All
        # its revisions are retained so ties use the same visible evidence.
        self.seed(f'''WITH candidates AS MATERIALIZED (
            SELECT i.source_table,i.source_id,raw.listing_id,raw.event_time_ns FROM {self.index} i
            JOIN intraday_observations raw ON raw.id=i.source_id
            WHERE i.source_table='intraday_observations' AND i.known<=? AND raw.kind='QUOTE'),
            latest AS (SELECT listing_id,MAX(event_time_ns) AS event_time_ns FROM candidates GROUP BY listing_id)
            SELECT c.source_table,c.source_id FROM candidates c JOIN latest l
            ON l.listing_id=c.listing_id AND l.event_time_ns=c.event_time_ns''', (carry,))
        for table, key, order, anchor in (
            ('intraday_news_versions', 'provider,article_id', 'updated_at_ns DESC,received_at_ns DESC,local_anchor DESC,intake DESC,id DESC',
             'raw.provider,raw.article_id,raw.updated_at_ns,raw.received_at_ns,raw.capture_id'),
            ('intraday_event_versions', 'provider,logical_key', 'received_at_ns DESC,local_anchor DESC,intake DESC,id DESC',
             'raw.provider,raw.logical_key,raw.received_at_ns,raw.capture_id'),
            ('intraday_identity_versions', 'listing_id,valid_from_ns', 'known DESC,id DESC','raw.id')):
            self.seed(f'''WITH candidates AS (SELECT i.source_table,i.source_id,i.known,i.intake,raw.*,
                MIN(raw.id) OVER(PARTITION BY {anchor}) AS local_anchor FROM {self.index} i
                JOIN {table} raw ON raw.id=i.source_id WHERE i.source_table=? AND i.known<=?)
                SELECT source_table,source_id FROM (SELECT source_table,source_id,
                ROW_NUMBER() OVER(PARTITION BY {key} ORDER BY {order}) AS rank FROM candidates) WHERE rank=1''', (table, carry))
        for table, predicate in (
            ('intraday_calendar_versions', 'raw.close_at_ns>:warm'),
            ('intraday_universe_snapshots', "json_extract(raw.payload_json,'$.close_at_ns')>:warm"),
            ('intraday_capture_events', "json_extract(raw.payload_json,'$.metadata_kind') IN ('ASSETS','ASSET_CHUNK','CALENDAR')")):
            self.seed(f'''SELECT i.source_table,i.source_id FROM {self.index} i JOIN {table} raw ON raw.id=i.source_id
                WHERE i.source_table=:table AND i.known<=:carry AND {predicate}''',
                {'table': table, 'carry': carry, 'warm': warm_start})
        active = self.db.execute(f'''SELECT raw.capture_id FROM {self.index} i JOIN intraday_capture_events raw ON raw.id=i.source_id
            WHERE i.source_table='intraday_capture_events' AND i.known<=? AND raw.kind='CAPTURE_START'
            ORDER BY i.known DESC,raw.received_at_ns DESC,i.anchor DESC,i.intake DESC,i.proof_id DESC LIMIT 1''', (carry,)).fetchone()
        if active:
            capture = active[0]
            # Keep every invalid clock and protocol/state transition in the
            # active epoch; none can be repaired by a later valid heartbeat.
            for table, predicate in (
                ('intraday_capture_events', "raw.kind!='ADMISSION' AND COALESCE(json_extract(raw.payload_json,'$.metadata_kind'),'') NOT IN ('PUBLICATION','COLLECTOR_PUBLICATION','DATASET_PUBLICATION','EVENT_DOCUMENT')"),
                ('intraday_observations', "raw.kind IN ('STATUS','LULD')")):
                self.seed(f'''SELECT i.source_table,i.source_id FROM {self.index} i JOIN {table} raw ON raw.id=i.source_id
                    WHERE i.source_table=? AND i.known<=? AND raw.capture_id=? AND {predicate}''', (table, carry, capture))
        for table in ('intraday_observations', 'intraday_news_versions'):
            self.seed(f'''SELECT source_table,source_id FROM (SELECT i.source_table,i.source_id,
                ROW_NUMBER() OVER(PARTITION BY raw.capture_id ORDER BY raw.received_at_ns DESC,raw.id DESC) AS rank
                FROM {self.index} i JOIN {table} raw ON raw.id=i.source_id
                WHERE i.source_table=? AND i.known<=?) WHERE rank=1''', (table, carry))

    def require(self, table, source_id, *, replay=True):
        if table not in _SOURCE_TABLES or type(source_id) is not int or source_id <= 0:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if replay and self.db.execute(f'SELECT 1 FROM {self.index} WHERE source_table=? AND source_id=?', (table, source_id)).fetchone() is None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        self.db.execute(f'INSERT OR IGNORE INTO {self.stage}(source_table,source_id,replay) VALUES(?,?,?)',
                        (table, source_id, int(replay)))

    def hydrate(self):
        processed = 0
        while True:
            pending = self.db.execute(f'SELECT source_table,source_id,replay FROM {self.stage} WHERE processed=0 LIMIT 1').fetchone()
            if pending is None:
                break
            table, source_id, replay = tuple(pending)
            occurrence = self.db.execute(f'SELECT * FROM {self.index} WHERE source_table=? AND source_id=?', (table, source_id)).fetchone()
            if replay:
                row = self.reader.store._timeline_row(occurrence, self.manifest['cutoff_ns'])
                if len(visible_rows((row,), cutoff_ns=self.manifest['cutoff_ns'], namespace=tuple(self.manifest['namespace']))) != 1:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
            else:
                row = {**decode_row(self.reader._source(table, source_id)), 'table': table}
            if table == 'intraday_capture_events' and (row['payload'].get('metadata_kind') == 'DATASET_PUBLICATION'
                or row['payload'].get('metadata_kind') == 'PUBLICATION' and row['payload'].get('references')
                and all(ref.get('table') == 'intraday_capture_events' and self.reader._source(ref['table'], ref['id'])['kind'] == 'BOOTSTRAP'
                        and json.loads(self.reader._source(ref['table'], ref['id'])['payload_json']).get('metadata_kind') == 'DATASET_PUBLICATION'
                        for ref in row['payload']['references'])):
                self.db.execute(f'DELETE FROM {self.stage} WHERE source_table=? AND source_id=?', (table, source_id))
                continue
            payload = row['payload']
            for field in ('admission_id', 'publication_id'):
                if row.get(field) is not None:
                    self.require('intraday_capture_events', row[field])
            if table == 'intraday_news_versions':
                for link in row['links']:
                    self.require('intraday_news_links', link['id'])
            if table == 'intraday_event_versions':
                self.require('intraday_capture_events', payload['document']['id'])
            if table in {'intraday_event_versions', 'intraday_news_links'} and payload.get('identity'):
                self.require('intraday_identity_versions', payload['identity']['id'])
            if table == 'intraday_news_links':
                self.require('intraday_news_versions', row['news_version_id'])
            if table == 'intraday_universe_snapshots':
                for member in self.db.execute('SELECT id FROM intraday_universe_members WHERE snapshot_id=?', (source_id,)):
                    self.require('intraday_universe_members', member[0])
            if table == 'intraday_universe_members':
                self.require('intraday_universe_snapshots', row['snapshot_id'])
                self.require('intraday_identity_versions', row['identity_version_id'])
            if table == 'intraday_capture_events' and payload.get('orphan_raw_proof'):
                orphan = payload['orphan_raw_proof']
                raw = self.reader._source(orphan['table'], orphan['id'])
                if (raw['payload_hash'] != orphan['payload_hash'] or raw['received_at_ns'] != orphan['received_at_ns']
                    or raw['persisted_at_ns'] > row['persisted_at_ns']):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                self.require(orphan['table'], orphan['id'], replay=False)
            if table == 'intraday_capture_events' and payload.get('metadata_kind')=='COLLECTOR_HANDSHAKE':
                for ack in payload['ack_refs']:
                    self.require('intraday_capture_events',ack['id'])
                    self.require('intraday_capture_events',ack['publication_id'])
                for listing in payload['listings']:
                    self.require('intraday_event_versions',listing['checkpoint_id'])
                    self.require('intraday_capture_events',listing['checkpoint_admission_id'])
                    for status in listing['status_refs']:
                        self.require('intraday_observations',status['id'])
                        self.require('intraday_capture_events',status['admission_id'])
            encoded = _envelope_bytes(row)
            if len(encoded) > self.resources['max_chunk_bytes']:
                raise SnapshotError('RESOURCE_LIMIT')
            self.db.execute(f'''UPDATE {self.stage} SET row_json=?,reference_json=?,processed=1,
                kind=?,listing_id=?,event_time_ns=?,available_at_ns=?,capture_id=?,received_at_ns=?
                WHERE source_table=? AND source_id=?''',
                (encoded.decode(), canonical_json(self.reader._reference(row)), row.get('kind'),row.get('listing_id'),
                 row.get('event_time_ns'),row['available_at_ns'],row['capture_id'],row['received_at_ns'],table,source_id))
            processed += 1
            if processed % 1000 == 0:
                self.check_budget()
        self.check_budget()

    def rows(self, predicate='1', params=()):
        for row in self.db.execute(f'SELECT row_json FROM {self.stage} WHERE replay=1 AND ({predicate}) ORDER BY source_table,source_id', params):
            yield json.loads(row[0])

    def planning(self):
        values,size = [],0
        rows = self.rows("source_table IN ('intraday_identity_versions','intraday_calendar_versions','intraday_universe_snapshots',"
            "'intraday_event_versions') OR kind='STATUS' OR source_table='intraday_capture_events' AND kind!='ADMISSION' "
            "AND COALESCE(json_extract(row_json,'$.payload.metadata_kind'),'') NOT IN ('PUBLICATION','COLLECTOR_PUBLICATION','DATASET_PUBLICATION')")
        for row in rows:
            size += len(_envelope_bytes(row))
            if size>self.resources.get('max_cache_bytes',67_108_864):
                raise SnapshotError('RESOURCE_LIMIT')
            values.append(row)
        return values

    def session(self, calendar):
        start, end = calendar['open_at_ns'], calendar['close_at_ns']
        decision_end = end + QualityPolicy().decision_delay_ns
        # Late revisions of this session are retained at the global cutoff;
        # reducers still apply their individual decision cutoffs.
        query = f'''WITH carry AS (SELECT listing_id,MAX(event_time_ns) AS event_time_ns FROM {self.stage}
                WHERE kind='QUOTE' AND available_at_ns<:start GROUP BY listing_id),
            liveness AS (SELECT capture_id,MAX(received_at_ns) AS received FROM {self.stage}
                WHERE kind IN ('BAR','QUOTE','NEWS') AND available_at_ns<:start GROUP BY capture_id,kind='NEWS')
            SELECT row_json FROM {self.stage} s WHERE replay=1 AND (
                source_table IN ('intraday_identity_versions','intraday_calendar_versions','intraday_universe_snapshots','intraday_event_versions')
                OR source_table='intraday_capture_events' AND kind!='ADMISSION'
                    AND COALESCE(json_extract(row_json,'$.payload.metadata_kind'),'') NOT IN ('PUBLICATION','COLLECTOR_PUBLICATION','DATASET_PUBLICATION')
                OR kind IN ('STATUS','LULD') OR (kind='BAR' AND event_time_ns>=:start AND event_time_ns<:end)
                OR kind IN ('BAR','QUOTE','NEWS') AND available_at_ns>=:start AND available_at_ns<=:decision_end
                OR kind='QUOTE' AND EXISTS(SELECT 1 FROM carry c WHERE c.listing_id=s.listing_id AND c.event_time_ns=s.event_time_ns)
                OR EXISTS(SELECT 1 FROM liveness l WHERE l.capture_id=s.capture_id AND l.received=s.received_at_ns))
            ORDER BY source_table,source_id'''
        return (json.loads(row[0]) for row in self.db.execute(query, {'start': start, 'end': end,'decision_end':decision_end}))

    def bodies(self):
        for raw in self.db.execute(f'''SELECT source_table,source_id,row_json,reference_json,replay FROM {self.stage}
            WHERE source_table!='intraday_universe_members' ORDER BY source_table,source_id'''):
            body = {'reference': json.loads(raw['reference_json']), 'dependencies': [], 'replay': bool(raw['replay'])}
            if raw['source_table'] == 'intraday_universe_snapshots':
                universe = json.loads(raw['row_json'])
                dependencies = list(self.rows("source_table='intraday_universe_members' AND json_extract(row_json,'$.snapshot_id')=?", (raw['source_id'],)))
                frozen_universe_dependencies(universe, dependencies)
                body['dependencies'] = [self.reader._reference(item) for item in sorted(dependencies, key=lambda item: item['listing_id'])]
            yield body


class SnapshotService:
    def __init__(self, store):
        self.store, self.archive, self.connection = store, store.archive, store.connection

    @contextmanager
    def validated_sources(self, snapshot_ids):
        signature = self._read_signature()
        budget = 67_108_864
        for snapshot_id in snapshot_ids:
            header = _decode_evidence(self.connection.execute(
                'SELECT * FROM intraday_dataset_snapshots WHERE id=?', (snapshot_id,)).fetchone())
            validate_manifest(header['payload'])
            budget = min(budget, header['payload'].get('resources',{}).get('max_cache_bytes',67_108_864))
        scope = _ValidatedSources(self, budget, signature)
        try:
            scope.check(self, full=True)
            yield scope
            scope.check(self, full=True)
        finally:
            scope.close()

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
        return self._decode_source(table,source_id)[0]

    def _raw_source(self, table, source_id):
        if table not in _SOURCE_TABLES or type(source_id) is not int or source_id <= 0:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        raw = self.connection.execute(f'SELECT * FROM {table} WHERE id=?', (source_id,)).fetchone()
        if raw is None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        raw = dict(raw)
        return raw

    def _decode_source(self, table, source_id, *, raw=None):
        raw = self._raw_source(table,source_id) if raw is None else raw
        header = {key:value for key,value in raw.items() if key!='payload_json'}
        encoded = _envelope_bytes(header,_owned=True)
        if len(encoded)>1_048_576:
            raise MetadataError('METADATA_INVALID')
        row = _decode_evidence(raw)
        candidates = tuple(value for name,value in self._secret_fields() if isinstance(value,str) and value)
        if candidates and (SafeProviderTransport._payload_contains_secret(header,candidates)
                           or SafeProviderTransport._payload_contains_secret(row['payload'],candidates)):
            raise MetadataError('METADATA_INVALID')
        return raw,row,hashlib.sha256(encoded).hexdigest()

    def _secret_fields(self):
        names,values = self._secret_state()
        return tuple(zip(names,values,strict=True))

    def _secret_state(self):
        settings = self.archive.settings
        if getattr(self,'_secret_settings',None) is not settings:
            self._secret_names = tuple(name for name in vars(settings)
                if name.endswith(('_api_key','_token','_chat_id')) or name in {'alpaca_api_key_id','alpaca_api_secret_key'})
            self._secret_getter = (attrgetter(*self._secret_names)
                if self._secret_names and not any('.' in name for name in self._secret_names) else None)
            self._secret_settings = settings
        if self._secret_getter is None:
            return self._secret_names,tuple(getattr(settings,name) for name in self._secret_names)
        values = self._secret_getter(settings)
        if len(self._secret_names)==1:
            values = (values,)
        return self._secret_names,values

    def _read_signature(self):
        # A rolled-back TEMP DDL can reuse its schema cookie. Check the names
        # themselves at every fence; explicit jobs own only timeline_* tables.
        if self.connection.execute("SELECT 1 FROM temp.sqlite_master WHERE type IN ('table','view') "
                                   "AND lower(name) GLOB 'intraday_*' LIMIT 1").fetchone():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        secret_fields = self._secret_state()
        return (self.connection.total_changes-getattr(self,'_scratch_changes',0),self.connection.execute('PRAGMA data_version').fetchone()[0],
                self.connection.execute('PRAGMA schema_version').fetchone()[0],secret_fields)

    def _reference(self, row):
        raw, decoded, source_hash = self._decode_source(row['table'], row['id'])
        if decoded['payload_hash'] != row['payload_hash'] or decoded['payload'] != row['payload']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        projection = {key: value for key, value in row.items()
                      if key not in {'payload', 'payload_json', 'payload_hash', 'links'} and
                      (key not in raw or value != raw[key])}
        return {'table': row['table'], 'id': row['id'], 'payload_hash': raw['payload_hash'],
                'source_hash': source_hash, 'projection': projection}

    def _hydrate(self, reference, *, _validated=False):
        allowed = {'available_at_ns','recorded_available_at_ns','admission_id','publication_id','publication_hash',
                   'capture_ingest_sequence','metadata_dependency','first_received_at_ns','table'}
        if (type(reference['projection']) is not dict or not set(reference['projection'])<=allowed
            or reference['projection'].get('table',reference['table'])!=reference['table']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if _validated:
            row = self._raw_source(reference['table'],reference['id'])
            row['payload'] = json.loads(row['payload_json'])
        else:
            raw,row,source_hash = self._decode_source(reference['table'],reference['id'])
            if raw['payload_hash']!=reference['payload_hash'] or source_hash!=reference['source_hash']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        row.update(reference['projection'])
        row['table'] = reference['table']
        return row

    def _hydrate_batch(self, references, *, validated=False, _source_scope=None):
        """Bounded working set; tuple cursors avoid repeated sqlite Row key scans."""
        allowed = {'available_at_ns','recorded_available_at_ns','admission_id','publication_id','publication_hash',
                   'capture_ingest_sequence','metadata_dependency','first_received_at_ns','table'}
        by_table = {}
        for ref in references:
            if (ref['table'] not in _SOURCE_TABLES or type(ref['id']) is not int or ref['id']<=0
                or type(ref['projection']) is not dict or not set(ref['projection'])<=allowed
                or ref['projection'].get('table',ref['table'])!=ref['table']):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            by_table.setdefault(ref['table'],{})[ref['id']] = ref
        sources,size = {},0
        for table, refs in by_table.items():
            ids = tuple(refs)
            cursor = self.connection.cursor()
            cursor.row_factory = None
            cursor.execute(f"SELECT * FROM {table} WHERE id IN ({','.join('?' for _ in ids)})",ids)
            keys = tuple(column[0] for column in cursor.description)
            for values in cursor:
                raw = dict(zip(keys,values,strict=True))
                ref = refs[raw['id']]
                size += 3*len(raw['payload_json'].encode())+4_096
                if size>67_108_864:
                    raise SnapshotError('RESOURCE_LIMIT')
                if validated:
                    row = raw
                    row['payload'] = json.loads(row['payload_json'])
                else:
                    source_hash = _source_scope.get(self,table,raw['id']) if _source_scope is not None else None
                    cached = source_hash is not None
                    if source_hash is None:
                        raw,row,source_hash = self._decode_source(table,raw['id'],raw=raw)
                    else:
                        row = raw
                        row['payload'] = _EVIDENCE_DECODER.decode(row['payload_json'])
                    if raw['payload_hash']!=ref['payload_hash'] or source_hash!=ref['source_hash']:
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    if _source_scope is not None and not cached:
                        _source_scope.remember(self,table,raw['id'],source_hash)
                row.update(ref['projection'])
                row['table'] = table
                if not validated:
                    bound = _source_scope.byte_bound(row,ref) if _source_scope is not None else _row_byte_bound(row,_decoded=True)
                    row = _ValidationRow(row)
                    row._byte_bound = bound
                sources[(table,row['id'])] = row
            cursor.close()
        if len(sources)!=sum(len(refs) for refs in by_table.values()):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return [sources[(ref['table'],ref['id'])] for ref in references]

    def _hydrated_batches(self, references, *, validated=False, _source_scope=None):
        if _source_scope is not None:
            _source_scope.check(self, full=True)
        def hydrate(batch):
            if _source_scope is None:
                return self._hydrate_batch(batch, validated=validated)
            return self._hydrate_batch(batch, validated=validated, _source_scope=_source_scope)
        # Inspect byte lengths before allocating envelopes. Large valid news
        # split into small working batches rather than rejecting a whole page.
        sizes = {}
        by_table = {}
        for ref in references:
            if ref['table'] not in _SOURCE_TABLES or type(ref['id']) is not int or ref['id']<=0:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            by_table.setdefault(ref['table'],set()).add(ref['id'])
        for table,ids in by_table.items():
            ids = tuple(ids)
            for raw in self.connection.execute(f"SELECT id,length(CAST(payload_json AS BLOB)) FROM {table} WHERE id IN ({','.join('?' for _ in ids)})",ids):
                if type(raw[1]) is not int or not 0<raw[1]<=1_048_576:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                sizes[(table,raw[0])] = 3*raw[1]+4_096
        batch,size = [],0
        for ref in references:
            key = (ref['table'],ref['id'])
            if key not in sizes:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            if batch and size+sizes[key]>8_388_608:
                yield hydrate(batch)
                batch,size = [],0
            batch.append(ref)
            size += sizes[key]
        if batch:
            yield hydrate(batch)

    @staticmethod
    def _cancel(cancelled, stage):
        if cancelled is not None and cancelled(stage):
            raise SnapshotError('CANCELLED')

    def freeze_dataset(self, *, start_at_ns, end_at_ns, cutoff_ns, listing_ids, benchmarks, cancelled=None,
                       resources=None, _window=False):
        for stamp in (start_at_ns, end_at_ns, cutoff_ns):
            check_ns(stamp)
        if cutoff_ns > self.archive.now():
            raise MetadataError('SNAPSHOT_NOT_PIT')
        if self.connection.in_transaction:
            raise MetadataError('TRANSACTION_ALREADY_OPEN')
        limits = {'max_disk_bytes': min(self.store.profile.max_archive_bytes, self.archive.settings.alpaca_max_archive_bytes),
                  'max_listings':30,
                  'min_free_bytes': 1_048_576, 'max_chunk_occurrences': 10_000, 'max_chunk_bytes': 8_388_608,
                  'max_cache_bytes': 67_108_864, 'max_rss_bytes': 2_147_483_648, 'window_sessions': 5, 'history_sessions': 30}
        if resources is not None:
            if type(resources) is not dict or not set(resources) <= set(limits) or not {'max_disk_bytes','min_free_bytes'} <= set(resources):
                raise SnapshotError('RESOURCE_LIMIT')
            for key, value in resources.items():
                if type(value) is not int or value <= 0 or (key not in {'max_disk_bytes','min_free_bytes'} and value > limits[key]):
                    raise SnapshotError('RESOURCE_LIMIT')
            limits.update(resources)
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise SnapshotError('RESOURCE_LIMIT')
        self._cancel(cancelled, 'BEFORE_READ')
        self.connection.execute('PRAGMA temp_store=FILE')
        self.connection.execute('PRAGMA temp.cache_size=-8192')
        self.connection.execute('BEGIN IMMEDIATE')
        stage = None
        try:
            self._guard()
            manifest = {'version': 'intraday-dataset-v1', 'start_at_ns': start_at_ns, 'end_at_ns': end_at_ns,
                        'cutoff_ns': cutoff_ns, 'listing_ids': listing_ids, 'benchmarks': benchmarks,
                        'namespace': [self.store.profile.profile_id, self.store.profile.feed, self.store.data_mode,
                                      self.store.provenance, self.store.replay_grade],
                        'policy': self._policy(), 'profile': self._profile(),
                        'aggregation': 'closed-open-anchored-1-5-15-v1',
                        'selection': 'full-published-prefix-v1'}
            if _window:
                manifest.update(version='intraday-dataset-v2', selection='window-dependency-closure-v2',
                                carry_at_ns=start_at_ns-1, window_session_count=0,
                                support_start_at_ns=start_at_ns,history_sessions=limits['history_sessions'], resources=limits)
            validate_manifest(manifest)
            if resources is None and self.archive._archive_bytes() + len(canonical_json(manifest).encode()) > limits['max_disk_bytes']:
                raise MetadataError('ARCHIVE_LIMIT')
            if len(listing_ids) > min(limits['max_listings'],self.store.profile.max_symbols, self.archive.settings.alpaca_max_symbols):
                raise SnapshotError('SYMBOL_LIMIT')
            self.store._validate_timeline_proofs(cutoff_ns)
            stage = _StagedTimeline(self, manifest, limits)
            stage.select()
            stage.hydrate()
            planning = stage.planning()
            manifest['requested_listing_ids'] = list(listing_ids)
            manifest['listing_ids'] = planned_listing_ids(manifest, planning)
            if len(manifest['listing_ids']) > min(limits['max_listings'],self.store.profile.max_symbols, self.archive.settings.alpaca_max_symbols):
                raise SnapshotError('SYMBOL_LIMIT')
            self._cutoff = cutoff_ns
            self._raw_latest = cutoff_ns
            manifest['timeline_count'] = self.connection.execute(f'SELECT COUNT(*) FROM {stage.stage} WHERE replay=1').fetchone()[0]
            manifest['typed_member_count'] = self.connection.execute(f"SELECT COUNT(*) FROM {stage.stage} WHERE source_table!='intraday_universe_members'").fetchone()[0]
            manifest['audit_member_count'] = self.connection.execute(f'SELECT COUNT(*) FROM {stage.stage} WHERE replay=0').fetchone()[0]
            digest = _digest(manifest, stage.bodies())
            report = quality_report(manifest, planning, row_factory=stage.session,resource_guard=stage.check_budget)
            self._cancel(cancelled, 'BEFORE_RAW')
            self._used = self.archive._archive_bytes()
            run = self.archive.begin_run()
            snapshot_id = self._append('intraday_dataset_snapshots', run, manifest, {
                'start_at_ns': start_at_ns, 'end_at_ns': end_at_ns, 'cutoff_ns': cutoff_ns,
                'policy_id': QualityPolicy.version, 'digest': digest, 'member_count': manifest['typed_member_count']}, 'dataset')
            for body in stage.bodies():
                self._cancel(cancelled, 'DURING_RAW')
                reference = body['reference']
                kind, column = _REFERENCES[reference['table']]
                self._append('intraday_dataset_members', run, body, {
                    'snapshot_id': snapshot_id, 'member_kind': kind, column: reference['id']}, f'dataset:{snapshot_id}:member')
            report_id = self._append('intraday_quality_reports', run, report, {
                'snapshot_id': snapshot_id, 'policy_id': QualityPolicy.version, 'outcome': report['outcome'],
                'metrics_json': self.archive.safe_json(report['metrics']),
                'limits_json': self.archive.safe_json(report['limits'])}, f'dataset:{snapshot_id}:quality')
            stage.check_budget()
            stage.close()
            stage = None
            self.connection.commit()
        except sqlite3.DatabaseError:
            self.connection.rollback()
            raise MetadataError('SNAPSHOT_INPUT_MISSING') from None
        except Exception:
            self.connection.rollback()
            raise
        finally:
            if stage is not None:
                stage.close()
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
                'digest': digest, 'typed_member_count': manifest['typed_member_count'], 'timeline_count': manifest['timeline_count'],
                'report_id': report_id, 'report_hash': report_row['payload_hash'], 'durable_at_ns': durable},
                durable, f'dataset-publication:{snapshot_id}')
        return DatasetSnapshot(snapshot_id, digest, report_id)

    def freeze_window(self, *, resources, **kwargs):
        if resources is None:
            raise SnapshotError('RESOURCE_LIMIT')
        return self.freeze_dataset(resources=resources, _window=True, **kwargs)

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
        timeline = causal_order(rows, cutoff_ns=manifest['cutoff_ns'], namespace=tuple(manifest['namespace']))
        return {'snapshot_id': snapshot_id, 'digest': header['digest'], 'known_at_ns': pub['available_at_ns'],
                'manifest': manifest, 'timeline': timeline, 'report': report['payload']}

    def replay(self, snapshot_id, *, cutoff_ns=None, listing_ids=None):
        saved = self.read(snapshot_id)
        return replay_frozen(saved['manifest'], saved['timeline'], cutoff_ns=cutoff_ns, listing_ids=listing_ids)

    def _frozen_links(self, snapshot_id, news_id):
        links = []
        rows = self.connection.execute('''SELECT m.payload_json FROM intraday_dataset_members m
            JOIN intraday_news_links l ON l.id=m.news_link_id
            WHERE m.snapshot_id=? AND l.news_version_id=? ORDER BY l.id''', (snapshot_id, news_id))
        for member in rows:
            row = self._hydrate(json.loads(member[0])['reference'])
            row.pop('table', None)
            links.append(row)
        return links

    def _included(self, snapshot_id, table, source_id, payload_hash=None, *, _provisional=False):
        if table not in _SOURCE_TABLES or type(source_id) is not int or source_id <= 0:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        params = (snapshot_id, source_id)
        if table in _REFERENCES:
            column = _REFERENCES[table][1]
            row = self.connection.execute(f'''SELECT json_extract(payload_json,'$.reference')
                FROM intraday_dataset_members WHERE snapshot_id=? AND {column}=?''', params).fetchone()
        else:
            row = self.connection.execute('''SELECT dependency.value FROM intraday_dataset_members m,
                json_each(m.payload_json,'$.dependencies') dependency
                WHERE m.snapshot_id=? AND json_extract(dependency.value,'$.table')=?
                AND json_extract(dependency.value,'$.id')=?''', (snapshot_id, table, source_id)).fetchone()
        if row is None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        ref = json.loads(row[0])
        if payload_hash is not None and ref['payload_hash'] != payload_hash:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if not _provisional:
            return self._hydrate(ref)
        # Closure is provisional until the full member pass verifies this exact
        # source independently. No public handle exists at this point.
        raw = self._raw_source(table,source_id)
        if raw['payload_hash']!=ref['payload_hash']:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        raw.update(payload=json.loads(raw['payload_json']),**ref['projection'])
        raw['table'] = table
        return raw

    def _closure_batch(self, snapshot_id, rows):
        sources = {(row['table'],row['id']):row for row in rows}
        needed, admissions = set(), set()
        for row in rows:
            table,payload = row['table'],row['payload']
            if row.get('admission_id') is not None:
                admissions.add(('intraday_capture_events',row['admission_id']))
            if row.get('publication_id') is not None:
                needed.add(('intraday_capture_events',row['publication_id']))
            identity = payload.get('identity') if table in {'intraday_event_versions','intraday_news_links'} else None
            if identity is not None:
                needed.add(('intraday_identity_versions',identity['id']))
            if table=='intraday_event_versions':
                needed.add(('intraday_capture_events',payload['document']['id']))
            if table=='intraday_news_links':
                needed.add(('intraday_news_versions',row['news_version_id']))
            if table=='intraday_universe_members':
                needed.update((('intraday_universe_snapshots',row['snapshot_id']),
                               ('intraday_identity_versions',row['identity_version_id'])))
            if table=='intraday_capture_events':
                orphan = payload.get('orphan_raw_proof')
                if orphan:
                    needed.add((orphan['table'],orphan['id']))
                if payload.get('metadata_kind')=='COLLECTOR_HANDSHAKE':
                    for ref in payload['ack_refs']:
                        needed.update(((table,ref['id']),(table,ref['publication_id'])))
                    for ref in payload['listings']:
                        needed.update((('intraday_event_versions',ref['checkpoint_id']),
                                       (table,ref['checkpoint_admission_id'])))
                        for status in ref['status_refs']:
                            needed.update((('intraday_observations',status['id']),(table,status['admission_id'])))
        # These edges need only the typed binding. The receipt itself still
        # undergoes the complete member/source pass before open can return.
        # Other uses (publication/document/handshake) retain full hydration.
        ids = [source_id for table,source_id in admissions-needed
               if (table,source_id) not in sources
               or 'observation_id' not in sources[(table,source_id)]
               or 'payload_hash' not in sources[(table,source_id)]['payload']]
        for start in range(0,len(ids),500):
            part = ids[start:start+500]
            placeholders = ','.join('?' for _ in part)
            query = f'''SELECT raw.id,raw.kind,raw.observation_id,raw.news_version_id,raw.event_version_id,
                raw.payload_hash,json_extract(raw.payload_json,'$.payload_hash') AS admitted_hash,
                json_extract(m.payload_json,'$.reference.payload_hash') AS member_hash
                FROM intraday_dataset_members m JOIN intraday_capture_events raw ON raw.id=m.capture_event_id
                WHERE m.snapshot_id=? AND raw.id IN ({placeholders})'''
            for receipt in self.connection.execute(query,(snapshot_id,*part)):
                if receipt['payload_hash'] != receipt['member_hash']:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                sources[('intraday_capture_events',receipt['id'])] = {
                    key:receipt[key] for key in ('id','kind','observation_id','news_version_id','event_version_id','payload_hash')}
                sources[('intraday_capture_events',receipt['id'])]['payload'] = {'payload_hash':receipt['admitted_hash']}
        needed.update(admissions)
        by_table = {}
        for table,source_id in needed-sources.keys():
            if table not in _SOURCE_TABLES or type(source_id) is not int or source_id<=0:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            by_table.setdefault(table,[]).append(source_id)
        references = []
        for table,ids in by_table.items():
            for start in range(0,len(ids),500):
                part = ids[start:start+500]
                placeholders = ','.join('?' for _ in part)
                if table in _REFERENCES:
                    column = _REFERENCES[table][1]
                    query = f'''SELECT json_extract(payload_json,'$.reference') FROM intraday_dataset_members
                        WHERE snapshot_id=? AND {column} IN ({placeholders})'''
                    params = (snapshot_id,*part)
                else:
                    names = ','.join(f':source{index}' for index in range(len(part)))
                    query = _REFS_SQL+f''' SELECT reference_json FROM refs
                        WHERE json_extract(reference_json,'$.table')=:table
                        AND json_extract(reference_json,'$.id') IN ({names})'''
                    params = {'snapshot':snapshot_id,'table':table,
                              **{f'source{index}':item for index,item in enumerate(part)}}
                references.extend(json.loads(item[0]) for item in self.connection.execute(query,params))
        size = sum(_row_byte_bound(row, _decoded=True) for row in rows)
        for batch in self._hydrated_batches(references,validated=True) if references else ():
            for row in batch:
                size += _row_byte_bound(row, _decoded=True)
                if size>67_108_864:
                    if len(rows)==1:
                        raise SnapshotError('RESOURCE_LIMIT')
                    # Fan-out (many small links to large news) can exceed a
                    # source batch. Revalidate smaller requesting groups.
                    del sources,references,batch
                    midpoint = len(rows)//2
                    self._closure_batch(snapshot_id,rows[:midpoint])
                    self._closure_batch(snapshot_id,rows[midpoint:])
                    return
                sources[(row['table'],row['id'])] = row
        def require(table,source_id,payload_hash=None):
            target = sources.get((table,source_id))
            if target is None or (payload_hash is not None and target['payload_hash']!=payload_hash):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            return target
        for row in rows:
            self._row_closure(snapshot_id,row,require=require)

    def _row_closure(self, snapshot_id, row, *, require=None):
        if require is None:
            def require(table,source_id,payload_hash=None):
                return self._included(snapshot_id,table,source_id,payload_hash,_provisional=True)

        table, payload = row['table'], row['payload']
        if row.get('admission_id') is not None:
            receipt = require('intraday_capture_events', row['admission_id'])
            kind, column = _REFERENCES[table]
            if (kind not in {'OBSERVATION', 'NEWS', 'EVENT'} or receipt['kind'] != 'ADMISSION'
                or receipt[column] != row['id'] or receipt['payload']['payload_hash'] != row['payload_hash']):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if row.get('publication_id') is not None:
            receipt = require('intraday_capture_events', row['publication_id'], row.get('publication_hash'))
            proof = receipt['payload']
            expected = {'id': row['id'], 'hash': row['payload_hash'], 'kind': row.get('kind')}
            valid = (proof.get('reference') == expected if proof.get('metadata_kind') == 'COLLECTOR_PUBLICATION'
                     else {'table': table, 'id': row['id'], 'hash': row['payload_hash']} in proof.get('references', []))
            if not valid:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        identity = payload.get('identity') if table in {'intraday_event_versions', 'intraday_news_links'} else None
        if identity is not None:
            target = require('intraday_identity_versions', identity['id'], identity['payload_hash'])
            if target.get('publication_id') != identity['publication_id']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if table == 'intraday_event_versions':
            require('intraday_capture_events', payload['document']['id'], payload['document']['hash'])
        if table == 'intraday_news_links':
            target = require('intraday_news_versions', row['news_version_id'], payload['news_hash'])
            if any(target[key]!=row[key] for key in ('capture_id','ingest_run_id','provider','feed',
                                                    'profile_id','data_mode','provenance','replay_grade')):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if table == 'intraday_universe_members':
            require('intraday_universe_snapshots', row['snapshot_id'])
            require('intraday_identity_versions', row['identity_version_id'], payload['identity_hash'])
        orphan = payload.get('orphan_raw_proof') if table == 'intraday_capture_events' else None
        if orphan:
            require(orphan['table'], orphan['id'], orphan['payload_hash'])
        if table=='intraday_capture_events' and payload.get('metadata_kind')=='COLLECTOR_HANDSHAKE':
            for ref in payload['ack_refs']:
                ack = require(table,ref['id'],ref['hash'])
                require(table,ref['publication_id'],ref['publication_hash'])
                if ack.get('publication_id')!=ref['publication_id'] or ack['capture_id']!=row['capture_id']:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
            for ref in payload['listings']:
                checkpoint = require('intraday_event_versions',ref['checkpoint_id'],ref['checkpoint_hash'])
                require(table,ref['checkpoint_admission_id'])
                if (checkpoint.get('admission_id')!=ref['checkpoint_admission_id']
                    or checkpoint['capture_id']!=row['capture_id'] or checkpoint['listing_id']!=ref['listing_id']):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                for status in ref['status_refs']:
                    observation = require('intraday_observations',status['id'],status['hash'])
                    require(table,status['admission_id'])
                    if observation.get('admission_id')!=status['admission_id'] or observation['capture_id']!=row['capture_id']:
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')

    def open(self, snapshot_id, *, max_occurrences=10_000, max_bytes=8_388_608, _source_scope=None):
        """Validate every exact member before returning a bounded timeline handle."""
        if (type(max_occurrences) is not int or not 1 <= max_occurrences <= 10_000
            or type(max_bytes) is not int or not 1 <= max_bytes <= 8_388_608):
            raise SnapshotError('RESOURCE_LIMIT')
        try:
            return self._open(snapshot_id, max_occurrences, max_bytes, _source_scope)
        except SnapshotError:
            raise
        except (MetadataError, ValueError, KeyError, TypeError, OverflowError, RecursionError, sqlite3.DatabaseError):
            raise MetadataError('SNAPSHOT_INPUT_MISSING') from None
        finally:
            if _source_scope is not None:
                _source_scope.finish_child(valid=False)

    def _open(self, snapshot_id, max_occurrences, max_bytes, _source_scope=None):
        from backend.app.intraday.replay import visible_rows

        signature = self._read_signature()
        if _source_scope is not None:
            _source_scope.check(self, full=True)
        if type(snapshot_id) is not int or snapshot_id <= 0:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        header = _decode_evidence(self.connection.execute('SELECT * FROM intraday_dataset_snapshots WHERE id=?', (snapshot_id,)).fetchone())
        namespace = (self.store.profile.profile_id, self.store.profile.feed, self.store.data_mode,
                     self.store.provenance, self.store.replay_grade)
        manifest = header['payload']
        validate_manifest(manifest)
        rss_limit = manifest.get('resources',{}).get('max_rss_bytes',2_147_483_648)
        if _peak_rss_bytes()>rss_limit:
            raise SnapshotError('RESOURCE_LIMIT')
        max_occurrences = min(max_occurrences,manifest.get('resources',{}).get('max_chunk_occurrences',10_000))
        max_bytes = min(max_bytes,manifest.get('resources',{}).get('max_chunk_bytes',8_388_608))
        if (tuple(header[key] for key in _SCOPE) != namespace or tuple(manifest['namespace']) != namespace
            or any(header[key] != manifest[key] for key in ('start_at_ns', 'end_at_ns', 'cutoff_ns'))
            or header['policy_id'] != manifest['policy']['id'] or manifest['policy'] != self._policy()
            or manifest['profile'] != self._profile()):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        query = published_select('intraday_capture_events') + ''' WHERE raw.profile_id=? AND raw.data_mode=?
            AND raw.provenance=? AND raw.replay_grade=? AND raw.kind='BOOTSTRAP'
            AND json_extract(raw.payload_json,'$.metadata_kind')='DATASET_PUBLICATION'
            AND json_extract(raw.payload_json,'$.snapshot_id')=?
            AND EXISTS(SELECT 1 FROM json_each(pub.payload_json,'$.references') ref
                WHERE json_extract(ref.value,'$.table')='intraday_capture_events'
                AND json_extract(ref.value,'$.id')=raw.id) ORDER BY pub.id,raw.id'''
        publication = self.connection.execute(query, (*self.store.namespace, snapshot_id)).fetchone()
        pub = decode_published(publication, 'intraday_capture_events', MAX_NS)
        proof = pub['payload']
        report_raw = self.connection.execute('SELECT * FROM intraday_quality_reports WHERE id=? AND snapshot_id=?',
                                             (proof['report_id'], snapshot_id)).fetchone()
        report = _decode_evidence(report_raw)
        if (proof.get('complete') is not True or proof['snapshot_hash'] != header['payload_hash']
            or proof['digest'] != header['digest'] or proof['typed_member_count'] != header['member_count']
            or pub['ingest_run_id'] != header['ingest_run_id'] or report['payload_hash'] != proof['report_hash']
            or report['outcome'] != report['payload']['outcome'] or report['policy_id'] != header['policy_id']
            or report['ingest_run_id'] != header['ingest_run_id']
            or json.loads(report['metrics_json']) != report['payload']['metrics']
            or json.loads(report['limits_json']) != report['payload']['limits']
            or self.connection.execute('SELECT COUNT(*) FROM intraday_quality_reports WHERE snapshot_id=?', (snapshot_id,)).fetchone()[0] != 1):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        # Include audit members too. The full pass below still binds every
        # canonical reference to its typed key before a handle can escape.
        duplicate = self.connection.execute(f'''WITH identities AS (
            SELECT {_MEMBER_SOURCE_TABLE_SQL} AS source_table,{_MEMBER_SOURCE_ID_SQL} AS source_id
            FROM intraday_dataset_members m WHERE m.snapshot_id=:snapshot
            UNION ALL SELECT json_extract(dependency.value,'$.table'),json_extract(dependency.value,'$.id')
            FROM intraday_dataset_members m,json_each(m.payload_json,'$.dependencies') dependency
            WHERE m.snapshot_id=:snapshot AND json_array_length(m.payload_json,'$.dependencies')>0
        ) SELECT 1 FROM identities GROUP BY source_table,source_id
            HAVING COUNT(*)>1 LIMIT 1''', {'snapshot': snapshot_id}).fetchone()
        if duplicate:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        hasher = hashlib.sha256()
        text = canonical_json(manifest).encode()
        hasher.update(len(text).to_bytes(8, 'big'))
        hasher.update(text)
        members = replay_count = audit_count = 0
        latest = max(header['persisted_at_ns'], report['persisted_at_ns'])
        pending, pending_bytes = [], 0
        def validate_pending():
            nonlocal replay_count,audit_count,pending_bytes
            roles = {(ref['table'],ref['id']):replay for ref,replay in pending}
            remaining,cached = [],[]
            if _source_scope is not None:
                _source_scope.check(self, full=True)
            for ref,replay in pending:
                row = _source_scope.completed(ref,manifest['cutoff_ns'],max_bytes) if _source_scope is not None and replay else None
                if row is None:
                    remaining.append(ref)
                else:
                    cached.append(row)
            if cached:
                # A shared proof does not attest inclusion in this child. Its
                # receipt edges are checked again against this exact snapshot.
                self._closure_batch(snapshot_id,cached)
                replay_count += len(cached)
            for rows in self._hydrated_batches(remaining, _source_scope=_source_scope) if remaining else ():
                if _peak_rss_bytes()>rss_limit:
                    raise SnapshotError('RESOURCE_LIMIT')
                replay_rows = []
                for row in rows:
                    if _row_byte_bound(row, _decoded=True)>max_bytes:
                        raise SnapshotError('RESOURCE_LIMIT')
                    if roles[(row['table'],row['id'])]:
                        replay_rows.append(row)
                        replay_count += 1
                    else:
                        if tuple(row[key] for key in _SCOPE)!=namespace:
                            raise MetadataError('SNAPSHOT_INPUT_MISSING')
                        audit_count += 1
                if len(visible_rows(replay_rows,cutoff_ns=manifest['cutoff_ns'],namespace=namespace,
                                    _decoded=True))!=len(replay_rows):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                self._closure_batch(snapshot_id,replay_rows)
                if _source_scope is not None:
                    references = {(ref['table'],ref['id']):ref for ref in remaining}
                    for row in replay_rows:
                        _source_scope.complete(references[(row['table'],row['id'])],row)
                if _peak_rss_bytes()>rss_limit:
                    raise SnapshotError('RESOURCE_LIMIT')
            pending.clear()
            pending_bytes = 0
        cursor = self.connection.cursor()
        cursor.row_factory = None
        columns = (*_SCOPE,'ingest_run_id','member_kind',*(column for _,column in _REFERENCES.values()),
                   'persisted_at_ns','payload_json','payload_hash')
        cursor.execute(f'SELECT {",".join(columns)} FROM intraday_dataset_members WHERE snapshot_id=? ORDER BY ingest_sequence', (snapshot_id,))
        positions = {key:index for index,key in enumerate(columns)}
        for values in cursor:
            raw = {'payload_json':values[positions['payload_json']],'payload_hash':values[positions['payload_hash']]}
            member = (_decode_evidence(raw) if _source_scope is None else
                      _decode_evidence(raw,_member_scope=_source_scope))
            body = member['payload']
            if (values[:len(_SCOPE)] != namespace or values[positions['ingest_run_id']] != header['ingest_run_id']
                or type(body['replay']) is not bool or type(body['dependencies']) is not list):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            reference = body['reference']
            kind, column = _REFERENCES[reference['table']]
            if values[positions['member_kind']] != kind or values[positions[column]] != reference['id']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            text = member['payload_json'].encode()
            if len(text) > max_bytes:
                raise SnapshotError('RESOURCE_LIMIT')
            hasher.update(len(text).to_bytes(8, 'big'))
            hasher.update(text)
            members += 1
            latest = max(latest, values[positions['persisted_at_ns']])
            for ref in chain((reference,), body['dependencies']):
                if pending and pending_bytes+len(text)>2_097_152:
                    validate_pending()
                pending.append((ref,body['replay']))
                pending_bytes += len(text)
                if len(pending)==1_000:
                    validate_pending()
        if pending:
            validate_pending()
        cursor.close()
        if (hasher.hexdigest() != header['digest'] or members != header['member_count']
            or members != manifest['typed_member_count'] or replay_count != manifest['timeline_count']
            or replay_count != proof['timeline_count'] or audit_count != manifest['audit_member_count']
            or proof['durable_at_ns'] < max(latest, manifest['cutoff_ns']) or proof['durable_at_ns'] > pub['available_at_ns']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        self.archive.safe_json(manifest)
        self.archive.safe_json(report['payload'])
        self.archive.safe_json({'digest':header['digest'],'publication_hash':pub['payload_hash']})
        if _peak_rss_bytes()>rss_limit:
            raise SnapshotError('RESOURCE_LIMIT')
        timeline = FrozenTimeline(self, snapshot_id, manifest, replay_count,
                                  max_occurrences=max_occurrences, max_bytes=max_bytes, _signature=signature)
        result = ValidatedDataset(snapshot_id, header['digest'], pub['available_at_ns'], manifest, report['payload'],
                                  timeline, pub['id'], pub['payload_hash'])
        if signature!=self._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if _source_scope is not None:
            _source_scope.finish_child(valid=True)
        return result


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
