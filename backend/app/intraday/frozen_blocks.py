"""Explicit v3 evidence imports. Sealed copies are authoritative, never a proof cache.

Legacy datasets without a v3 seal continue to use their original RAW reader.
Only explicit jobs write here. Reads use the caller's public sqlite3 connection.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import zlib
from contextlib import contextmanager
from itertools import chain

from pydantic_core import from_json

from backend.app.data_providers.alpaca_metadata import MAX_NS, MetadataError, check_ns
from backend.app.intraday.contracts import canonical_json

try:
    import _investedge_reader_native as _NATIVE
except ImportError:
    _NATIVE = None
if _NATIVE is not None and getattr(_NATIVE,'FROZEN_API_VERSION',0)!=5:
    _NATIVE = None

FORMAT = 'sealed-evidence-blocks-v3'
SCOPE = ('profile_id','feed','data_mode','provenance','replay_grade')
INPUT_LIMIT = 126_976  # 64x decoded-tree charge + 64KiB reserve stays below 8MiB.


def _text(value):
    return canonical_json({'value':value})[9:-1]


def _sha(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def _decode(raw):
    from backend.app.intraday.snapshots import _decode_evidence
    if _NATIVE is None:
        return _decode_evidence(raw)
    return _NATIVE.decode_evidence(dict(raw),_decode_evidence)


def _unpack(body, size):
    if type(body) is not bytes or type(size) is not int or not 0<size<=INPUT_LIMIT:
        raise MetadataError('SNAPSHOT_INPUT_MISSING')
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(body,size+1)
    except zlib.error:
        raise MetadataError('SNAPSHOT_INPUT_MISSING') from None
    if len(decoded)!=size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise MetadataError('SNAPSHOT_INPUT_MISSING')
    try:
        return from_json(decoded,cache_strings=False,allow_inf_nan=False)
    except ValueError:
        raise MetadataError('SNAPSHOT_INPUT_MISSING') from None


def _frame(hasher, text):
    encoded = text.encode()
    hasher.update(len(encoded).to_bytes(8,'big'))
    hasher.update(encoded)


def compact_member(raw):
    """Retain every field used by the original typed-member validation."""
    from backend.app.intraday.snapshots import _REFERENCES
    fields = (*SCOPE,'ingest_run_id','member_kind','persisted_at_ns','payload_json','payload_hash')
    result = {key:raw[key] for key in fields}
    result.update((column,raw[column]) for _,column in _REFERENCES.values() if raw[column] is not None)
    return result


def reference_text(member,reference):
    prefix = '{"dependencies":[],"reference":'
    suffix = ',"replay":true}' if member['payload']['replay'] else ',"replay":false}'
    text = member['payload_json']
    if (len(member['payload'])==3 and not member['payload']['dependencies']
        and text.startswith(prefix) and text.endswith(suffix)):
        return text[len(prefix):-len(suffix)]
    return _text(reference)


class _FramedRecords(list):
    __slots__ = ()


def _tree_guard(value):
    from backend.app.intraday.snapshots import SnapshotError
    pending,seen,total = [value],set(),0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        total += sys.getsizeof(item)
        if total+sys.getsizeof(seen)+sys.getsizeof(pending)>8_388_608:
            raise SnapshotError('RESOURCE_LIMIT')
        if isinstance(item,dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item,(list,tuple)):
            pending.extend(item)


def _fragment(value):
    return type(value) is list and len(value)==6 and value[0]=='FRAGMENT'


def _logical_blocks(physical):
    active,pieces,seen_bytes = None,[],0
    for row,values in physical:
        if active is None and not _fragment(values[0]):
            yield row,values
            continue
        completed = _FramedRecords()
        for packet in values:
            if not _fragment(packet):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            _,fingerprint,index,count,size,text = packet
            if (type(fingerprint) is not str or len(fingerprint)!=64 or type(index) is not int
                or type(count) is not int or not 1<=count<=(8_388_608+11_999)//12_000
                or type(size) is not int or not 0<size<=8_388_608 or type(text) is not str
                or not 1<=len(text)<=12_000 or index<count-1 and len(text)!=12_000):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            if active is None:
                active = (fingerprint,count,size)
            if active!=(fingerprint,count,size) or index!=len(pieces):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            pieces.append(text)
            seen_bytes += len(text.encode())
            if seen_bytes>size:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            if len(pieces)==count:
                encoded = ''.join(pieces)
                if seen_bytes!=size or _sha(encoded)!=fingerprint:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                try:
                    record = from_json(encoded,cache_strings=False,allow_inf_nan=False)
                except ValueError:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING') from None
                _tree_guard([record,encoded])
                encoded = None
                completed.append(record)
                active,pieces,seen_bytes = None,[],0
        if completed:
            yield row,completed
    if active is not None:
        raise MetadataError('SNAPSHOT_INPUT_MISSING')


class _BlockDatabase:
    """Archive metadata owns its cursors without changing the caller factory."""
    def __init__(self,connection):
        self.connection = connection

    def execute(self,sql,parameters=()):
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute(sql,parameters)

    def __getattr__(self,name):
        return getattr(self.connection,name)


class FrozenBlocks:
    def __init__(self, reader):
        self.reader, self.db = reader,_BlockDatabase(reader.connection)
        self.scope = (reader.store.profile.profile_id,reader.store.profile.feed,*reader.store.namespace[1:])
        self._inventory_proof = None

    @contextmanager
    def validation_scope(self):
        previous = self._inventory_proof
        self._inventory_proof = {}
        try:
            yield self
        finally:
            self._inventory_proof = previous

    @contextmanager
    def _cancel_scope(self,cancelled):
        previous = getattr(self.reader,'_read_cancelled',None)
        self.reader._read_cancelled = cancelled
        try:
            self.reader._cancel(cancelled,'BEFORE_READ')
            yield
        finally:
            self.reader._read_cancelled = previous

    def _safe_text(self,value):
        return self.reader.archive.safe_json({'value':value})[9:-1]

    def _record_text(self,value):
        from backend.app.intraday.snapshots import SnapshotError
        text = self._document_text({'value':value})[9:-1]
        if len(text.encode())>8_388_608:
            raise SnapshotError('RESOURCE_LIMIT')
        return text

    @staticmethod
    def _timeline_text(row):
        from backend.app.intraday.snapshots import SnapshotError, _envelope_bytes
        encoded = _envelope_bytes(row,_owned=True)
        if len(encoded)>8_388_608:
            raise SnapshotError('RESOURCE_LIMIT')
        return encoded.decode()

    def _document_text(self,value):
        from backend.app.data_providers.transport import SafeProviderTransport
        from backend.app.intraday.contracts import _json_value
        from backend.app.intraday.snapshots import SnapshotError
        candidates = tuple(item for _,item in self.reader._secret_fields() if isinstance(item,str) and item)
        if candidates and SafeProviderTransport._payload_contains_secret(value,candidates):
            raise MetadataError('METADATA_INVALID')
        try:
            if type(value) is not dict:
                raise ValueError
            _json_value(value)
            text = json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
            if len(text.encode())>67_108_864:
                raise SnapshotError('RESOURCE_LIMIT')
            return text
        except SnapshotError:
            raise
        except (TypeError,ValueError,OverflowError,RecursionError,UnicodeError):
            raise MetadataError('METADATA_INVALID') from None

    def find(self, kind, subject_id):
        row = self.db.execute('''SELECT s.* FROM intraday_frozen_sets s
            WHERE subject_kind=? AND subject_id=? AND profile_id=? AND feed=? AND data_mode=?
              AND provenance=? AND replay_grade=?''',(kind,subject_id,*self.scope)).fetchone()
        if row is None:
            return None
        header = _decode(row)
        seal = _decode(self.db.execute('SELECT * FROM intraday_frozen_seals WHERE set_id=?',(row['id'],)).fetchone())
        if (header['payload'].get('version')!=FORMAT or header['payload'].get('namespace')!=list(self.scope)
            or _text(header['payload'].get('subject'))!=_text([kind,subject_id])
            or seal['payload'].get('version')!=FORMAT or seal['payload'].get('complete') is not True
            or seal['payload'].get('header_hash')!=header['payload_hash']
            or type(seal['payload'].get('set_id')) is not int or seal['payload'].get('set_id')!=header['id']
            or type(seal['payload'].get('counts')) is not dict or type(seal['payload'].get('groups')) is not dict):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        allowed = {'MARKET','CHILD'} if kind=='MARKET' else {'MEMBER','TIMELINE','CHILD'}
        if (not set(seal['payload']['counts'])<=allowed
            or any(type(value) is not int or not 0<value<=MAX_NS for value in seal['payload']['counts'].values())):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if 'metadata_chunks' in header['payload']:
            descriptor = header['payload']
            count,size = descriptor['metadata_chunks'],descriptor.get('metadata_bytes')
            if (descriptor.get('metadata_format')!='framed-metadata-v1' or type(count) is not int
                or not 1<=count<=(67_108_864+11_999)//12_000 or type(size) is not int or not 0<size<=67_108_864):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            pieces,total = [],0
            for _,records in self._read_blocks(header,seal['payload'],'CHILD'):
                for record in records:
                    if (type(record) is not list or len(record)!=2 or record[0]!='METADATA' or type(record[1]) is not str
                        or not 1<=len(record[1])<=12_000 or len(pieces)<count-1 and len(record[1])!=12_000):
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    total += len(record[1].encode())
                    if total>size:
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    pieces.append(record[1])
                    if len(pieces)==count:
                        break
                if len(pieces)==count:
                    break
            if len(pieces)!=count or total!=size:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            text = ''.join(pieces)
            if _sha(text)!=descriptor['metadata_hash']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            from backend.app.intraday.snapshots import SnapshotError, _peak_rss_bytes
            if _peak_rss_bytes()+64*size+65_536>min(getattr(self.reader,'_validation_rss_limit',2_147_483_648),2_147_483_648):
                raise SnapshotError('RESOURCE_LIMIT')
            try:
                value = from_json(text,cache_strings=False,allow_inf_nan=False)
            except ValueError:
                raise MetadataError('SNAPSHOT_INPUT_MISSING') from None
            if (self._document_text(value)!=text or value.get('version')!=FORMAT or value.get('namespace')!=list(self.scope)
                or _text(value.get('subject'))!=_text([kind,subject_id])):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            header['payload'],header['metadata_chunks'] = value,count
        return header,seal['payload']

    def _budget(self, maximum, minimum):
        from backend.app.intraday.snapshots import SnapshotError, _peak_rss_bytes
        if (type(maximum) is not int or maximum<=0 or type(minimum) is not int or minimum<=0
            or maximum>min(self.reader.store.profile.max_archive_bytes,self.reader.archive.settings.alpaca_max_archive_bytes)):
            raise SnapshotError('RESOURCE_LIMIT')
        path = next((row[2] for row in self.db.execute('PRAGMA database_list') if row[1]=='main'),None)
        size = (self.db.execute('PRAGMA main.page_count').fetchone()[0]*self.db.execute('PRAGMA main.page_size').fetchone()[0]
                +self.db.execute('PRAGMA temp.page_count').fetchone()[0]*self.db.execute('PRAGMA temp.page_size').fetchone()[0])
        if size>maximum:
            raise SnapshotError('RESOURCE_LIMIT')
        if path:
            from pathlib import Path
            parent = Path(path).parent
            size = sum(item.stat().st_size for item in parent.glob(Path(path).name+'*') if item.is_file())
            if size>maximum or shutil.disk_usage(parent).free<minimum:
                raise SnapshotError('RESOURCE_LIMIT')
        if _peak_rss_bytes()>2_147_483_648:
            raise SnapshotError('RESOURCE_LIMIT')

    def _begin(self, kind, subject_id, evidence, maximum, minimum, *, expected_signature=None,cancelled=None):
        if self.db.in_transaction:
            raise MetadataError('TRANSACTION_ALREADY_OPEN')
        self._budget(maximum,minimum)
        self.db.execute('BEGIN IMMEDIATE')
        if expected_signature is not None and expected_signature!=self.reader._read_signature():
            self.db.rollback()
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        self._write_secrets = self.reader._secret_state()
        payload = {'version':FORMAT,'namespace':list(self.scope),'subject':[kind,subject_id],**evidence}
        document = self._document_text(payload)
        chunked = len(document.encode())>1_048_576
        text = (self.reader.archive.safe_json({'version':FORMAT,'namespace':list(self.scope),'subject':[kind,subject_id],
            'metadata_format':'framed-metadata-v1','metadata_chunks':(len(document)+11_999)//12_000,
            'metadata_bytes':len(document.encode()),'metadata_hash':_sha(document)}) if chunked else document)
        values = (kind,subject_id,subject_id if kind=='SNAPSHOT' else None,subject_id if kind=='BUNDLE' else None,
                  *self.scope,text,_sha(text))
        set_id = self.db.execute('''INSERT INTO intraday_frozen_sets(subject_kind,subject_id,snapshot_id,bundle_id,
            profile_id,feed,data_mode,provenance,replay_grade,payload_json,payload_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''',values).lastrowid
        if chunked:
            self._blocks(set_id,'CHILD',(['METADATA',document[index:index+12_000]] for index in range(0,len(document),12_000)),
                         maximum=maximum,minimum=minimum,cancelled=cancelled)
        return set_id

    def _blocks(self, set_id, domain, records, *, maximum, minimum, cancelled=None, listing=0, kind=''):
        if domain=='CHILD':
            ordinal = self.db.execute('SELECT COALESCE(MAX(ordinal)+1,0) FROM intraday_frozen_child_blocks WHERE set_id=?',(set_id,)).fetchone()[0]
        else:
            ordinal = self.db.execute('SELECT COALESCE(MAX(ordinal)+1,0) FROM intraday_frozen_blocks WHERE set_id=? AND domain=?',(set_id,domain)).fetchone()[0]
        batch,size = [],2
        def flush():
            nonlocal batch,size,ordinal
            self.reader._cancel(cancelled,'DURING_BLOCKS')
            text = '['+','.join(batch)+']'
            encoded = text.encode()
            if len(encoded)>INPUT_LIMIT:
                raise MetadataError('RESOURCE_LIMIT')
            body = zlib.compress(encoded,1)
            digest = _sha(body)
            if domain=='CHILD':
                self.db.execute('INSERT INTO intraday_frozen_child_blocks VALUES(?,?,?,?,?,?)',
                                (set_id,ordinal,len(batch),len(encoded),body,digest))
            else:
                self.db.execute('''INSERT INTO intraday_frozen_blocks
                    (set_id,domain,ordinal,listing_id,kind,row_count,input_bytes,body,digest) VALUES(?,?,?,?,?,?,?,?,?)''',
                    (set_id,domain,ordinal,listing,kind,len(batch),len(encoded),body,digest))
            ordinal += 1
            batch,size = [],2
            self._budget(maximum,minimum)
        for record in records:
            text = self._record_text(record)
            charge = len(text.encode())+1
            if charge+2>INPUT_LIMIT:
                if batch:
                    flush()
                fingerprint = _sha(text)
                count = (len(text)+11_999)//12_000
                total = len(text.encode())
                for index in range(count):
                    packet = self._safe_text(['FRAGMENT',fingerprint,index,count,total,text[index*12_000:(index+1)*12_000]])
                    packet_size = len(packet.encode())+1
                    if batch and size+packet_size>INPUT_LIMIT:
                        flush()
                    batch.append(packet)
                    size += packet_size
                if batch:
                    flush()
                continue
            if batch and (len(batch)==1000 or size+charge>INPUT_LIMIT):
                flush()
            batch.append(text)
            size += charge
        if batch:
            flush()

    def _inventory(self,set_id):
        return self.db.execute('''SELECT domain,ordinal,listing_id,kind,row_count,input_bytes,digest
            FROM intraday_frozen_blocks WHERE set_id=?
            UNION ALL SELECT 'CHILD',ordinal,0,'',row_count,input_bytes,digest
            FROM intraday_frozen_child_blocks WHERE set_id=? ORDER BY 1,2''',(set_id,set_id))

    def _finish(self, set_id, maximum, minimum, cancelled, *, validate=None):
        self.reader._cancel(cancelled,'BEFORE_SEAL')
        root = hashlib.sha256()
        counts,groups = {},{}
        for item in self._inventory(set_id):
            value = list(item)
            _frame(root,_text(value))
            counts[value[0]] = counts.get(value[0],0)+value[4]
            key = _text(value[:1]+value[2:4])
            _frame(groups.setdefault(key,hashlib.sha256()),_text(value))
        header = self.db.execute('SELECT payload_hash FROM intraday_frozen_sets WHERE id=?',(set_id,)).fetchone()[0]
        text = self.reader.archive.safe_json({'version':FORMAT,'complete':True,'set_id':set_id,
                                             'header_hash':header,'root':root.hexdigest(),'counts':counts,
                                             'groups':{key:hasher.hexdigest() for key,hasher in groups.items()}})
        self.db.execute('INSERT INTO intraday_frozen_seals VALUES(?,?,?)',(set_id,text,_sha(text)))
        # The provisional seal is visible only inside our writer transaction.
        # No authoritative copy is published until its complete read passes.
        if validate is not None:
            with self._cancel_scope(cancelled):
                validate()
        self.reader._cancel(cancelled,'BEFORE_COMMIT')
        self._budget(maximum,minimum)
        if self.reader._secret_state()!=self._write_secrets:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        self.db.commit()

    def _check_inventory(self, header, seal, domain, *, kind=None, listings=None):
        # The small metadata pass checks the complete inventory, including
        # filtered blocks, before any public result can escape.
        root = hashlib.sha256()
        counts,groups = {},{}
        filtered = domain=='MARKET'
        where,parameters = 'set_id=?',(header['id'],)
        if filtered:
            where += ' AND domain=? AND kind=?'
            parameters += (domain,kind)
            if listings is not None:
                if not listings:
                    return
                where += f" AND listing_id IN ({','.join('?' for _ in listings)})"
                parameters += tuple(listings)
        inventory = (self.db.execute('''SELECT domain,ordinal,listing_id,kind,row_count,input_bytes,digest
                FROM intraday_frozen_blocks WHERE '''+where+' ORDER BY domain,ordinal',parameters)
                if filtered else self._inventory(header['id']))
        for item in inventory:
            value = list(item)
            encoded = _text(value)
            _frame(root,encoded)
            counts[value[0]] = counts.get(value[0],0)+value[4]
            key = _text(value[:1]+value[2:4])
            _frame(groups.setdefault(key,hashlib.sha256()),encoded)
        if filtered:
            expected = {key:value for key,value in seal['groups'].items()
                        if (group:=json.loads(key))[0]==domain and group[2]==kind and (listings is None or group[1] in listings)}
            if {key:value.hexdigest() for key,value in groups.items()}!=expected:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        elif (root.hexdigest()!=seal['root'] or counts!=seal['counts']
              or {key:value.hexdigest() for key,value in groups.items()}!=seal['groups']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')

    def _read_blocks(self, header, seal, domain, *, kind=None, listings=None):
        if domain=='MARKET' or self._inventory_proof is None:
            self._check_inventory(header,seal,domain,kind=kind,listings=listings)
        else:
            key = (self.reader._read_signature(),header['id'],canonical_json(seal))
            if self._inventory_proof.get('key')!=key:
                self._check_inventory(header,seal,domain,kind=kind,listings=listings)
                if key[0]!=self.reader._read_signature():
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                self._inventory_proof['key'] = key
        for row,values in self._raw_block_rows(header['id'],domain,kind=kind,listings=listings):
            if domain=='MARKET':
                columns = header['payload']['columns']
                kind_index,listing_index = columns.index('kind'),columns.index('listing_id')
                if _NATIVE is not None:
                    _NATIVE.market_block(list(values) if isinstance(values,_FramedRecords) else values,
                                         kind_index,listing_index,row['kind'],row['listing_id'])
                else:
                    for value in values:
                        if (type(value) is not list or max(kind_index,listing_index)>=len(value)
                            or type(value[kind_index]) is not str or type(value[listing_index]) is not int
                            or value[kind_index]!=row['kind'] or value[listing_index]!=row['listing_id']):
                            raise MetadataError('SNAPSHOT_INPUT_MISSING')
            from backend.app.intraday.snapshots import SnapshotError, _peak_rss_bytes
            if _peak_rss_bytes()>min(getattr(self.reader,'_validation_rss_limit',2_147_483_648),
                header['payload'].get('manifest',{}).get('resources',{}).get('max_rss_bytes',2_147_483_648)):
                raise SnapshotError('RESOURCE_LIMIT')
            yield row['ordinal'],values

    def _raw_block_rows(self,set_id,domain,*,kind=None,listings=None,cancelled=None):
        query = ("SELECT *, 'CHILD' AS domain,0 AS listing_id,'' AS kind FROM intraday_frozen_child_blocks WHERE set_id=?"
                 if domain=='CHILD' else 'SELECT * FROM intraday_frozen_blocks WHERE set_id=? AND domain=?')
        params = (set_id,) if domain=='CHILD' else (set_id,domain)
        if kind is not None:
            query += ' AND kind=?'
            params += (kind,)
        if listings is not None:
            if not listings:
                return
            query += f" AND listing_id IN ({','.join('?' for _ in listings)})"
            params += tuple(listings)
        query += ' ORDER BY ordinal'
        def physical():
            for row in self.db.execute(query,params):
                self.reader._cancel(cancelled or getattr(self.reader,'_read_cancelled',None),'DURING_VALIDATION')
                if _sha(row['body'])!=row['digest']:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                values = _unpack(row['body'],row['input_bytes'])
                if type(values) is not list or not values or len(values)!=row['row_count']:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                yield row,values
        yield from _logical_blocks(physical())

    def _raw_blocks(self,set_id,domain,*,cancelled=None):
        for row,values in self._raw_block_rows(set_id,domain,cancelled=cancelled):
            yield row['ordinal'],values

    def seal_market(self, *, max_disk_bytes, min_free_bytes, cancelled=None):
        """Import all durable admission pairs; a later tail remains in RAW SQLite."""
        if self.find('MARKET',0) is not None:
            raise MetadataError('FROZEN_EVIDENCE_EXISTS')
        if self.db.in_transaction:
            raise MetadataError('TRANSACTION_ALREADY_OPEN')
        try:
            # A single writer lock makes coverage and copied admission pairs atomic.
            self.db.execute('BEGIN IMMEDIATE')
            water = self.db.execute('SELECT COALESCE(MAX(id),0) FROM intraday_capture_events').fetchone()[0]
            cursor = self.db.cursor()
            cursor.row_factory = None
            cursor.execute('''SELECT raw.*, proof.payload_json AS proof_json,proof.payload_hash AS proof_hash,
                proof.available_at_ns AS proof_available,proof.id AS proof_id
                FROM intraday_observations raw JOIN intraday_capture_events proof ON proof.observation_id=raw.id
                WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
                AND proof.kind='ADMISSION' AND proof.id<=? ORDER BY raw.kind,raw.listing_id,raw.id,proof.id''',
                (*self.reader.store.namespace,water))
            columns = tuple(col[0] for col in cursor.description)
            source = columns[:-4]
            positions = tuple(range(len(source),len(source)+4))
            # _begin owns the transaction. No records were changed by the lock above.
            self.db.rollback()
            cursor.close()
            set_id = self._begin('MARKET',0,{'water':water,'columns':list(source),'proof_positions':list(positions)},max_disk_bytes,min_free_bytes,cancelled=cancelled)
            # Recheck under the actual import lock; no admission may fall through a gap.
            if self.db.execute('SELECT COALESCE(MAX(id),0) FROM intraday_capture_events').fetchone()[0]!=water:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            cursor = self.db.cursor()
            cursor.row_factory = None
            cursor.execute('''SELECT raw.*,proof.payload_json,proof.payload_hash,proof.available_at_ns,proof.id
                FROM intraday_observations raw JOIN intraday_capture_events proof ON proof.observation_id=raw.id
                WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
                AND proof.kind='ADMISSION' AND proof.id<=? ORDER BY raw.kind,raw.listing_id,raw.id,proof.id''',
                (*self.reader.store.namespace,water))
            # Each kind/listing shares the global ordinal domain.
            from itertools import groupby
            ordinal = 0
            for (kind,listing), group in groupby(cursor,key=lambda row:(row[source.index('kind')],row[source.index('listing_id')])):
                # The helper starts ordinals at zero, so stream all blocks through
                # a per-group offset rather than retaining any full listing.
                self._market_blocks(set_id,group,source,kind,listing,ordinal,max_disk_bytes,min_free_bytes,cancelled)
                ordinal = self.db.execute('SELECT COALESCE(MAX(ordinal)+1,0) FROM intraday_frozen_blocks WHERE set_id=?',(set_id,)).fetchone()[0]
            cursor.close()
            self._finish(set_id,max_disk_bytes,min_free_bytes,cancelled,validate=self._validate_market_copy)
            return set_id
        except Exception:
            self.db.rollback()
            raise

    def _validate_market_copy(self):
        header,seal = self.find('MARKET',0)
        columns = tuple(header['payload']['columns'])
        kinds = [row[0] for row in self.db.execute("SELECT DISTINCT kind FROM intraday_frozen_blocks WHERE set_id=? AND domain='MARKET'",(header['id'],))]
        for kind in kinds:
            if kind not in {'BAR','QUOTE','STATUS','LULD'}:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            for _,rows in self._read_blocks(header,seal,'MARKET',kind=kind):
                self._market_rows(iter(rows),columns,MAX_NS,None,None,None,True,(kind,header['payload']['water'],self.scope))

    def _market_blocks(self,set_id,rows,columns,kind,listing,ordinal,maximum,minimum,cancelled):
        def checked():
            for row in rows:
                self._market_rows([tuple(row)],tuple(columns),MAX_NS,None,None,None,True)
                yield list(row)
        self._blocks(set_id,'MARKET',checked(),maximum=maximum,minimum=minimum,
                     cancelled=cancelled,kind=kind,listing=listing)

    def _market_rows(self, rows, columns, cutoff, start, end, listings, revisions, packed=None):
        from backend.app.intraday.replay import select_versions
        from backend.app.intraday.snapshots import _decode_evidence
        from backend.app.intraday.store import StoreError
        positions = tuple(range(len(columns),len(columns)+4))
        if _NATIVE is not None:
            return _NATIVE.read_market(rows,columns,positions,cutoff,start,end,listings,revisions,_decode_evidence,check_ns,StoreError,packed)
        result = []
        for values in rows:
            if packed is not None:
                check_ns(values[-2])
                if type(values) is list and (type(values[-1]) is not int or not 0<=values[-1]<=packed[1]):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                if values[-2]>cutoff:
                    continue
            raw = _decode_evidence(dict(zip(columns,values[:len(columns)],strict=True)))
            if packed is not None and (raw['kind']!=packed[0] or tuple(raw[key] for key in SCOPE)!=packed[2]):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            proof = _decode_evidence({'payload_json':values[-4],'payload_hash':values[-3]})['payload']
            durable = proof.get('durable_at_ns')
            check_ns(durable)
            if proof.get('observation_id')!=raw['id'] or proof.get('payload_hash')!=raw['payload_hash'] or durable<raw['persisted_at_ns']:
                raise StoreError('OBSERVATION_INVALID')
            raw['available_at_ns'] = max(values[-2],durable,raw['availability_floor_ns'])
            if (raw['available_at_ns']>cutoff or listings is not None and raw['listing_id'] not in listings
                or start is not None and raw['event_time_ns']<start or end is not None and raw['event_time_ns']>=end):
                continue
            raw['admission_id'] = values[-1]
            raw['capture_ingest_sequence'] = raw['payload'].get('intake_sequence',raw['ingest_sequence'])
            result.append(raw)
        return select_versions(result,family=result[0]['kind'] if result else 'QUOTE',cutoff_ns=cutoff,revisions=revisions,_decoded=True)

    def market(self, kind, cutoff, listings, start, end, revisions):
        signature = self.reader._read_signature()
        found = self.find('MARKET',0)
        if found is None:
            return None
        header,seal = found
        columns = header['payload']['columns']
        if (type(columns) is not list or any(type(column) is not str for column in columns)
            or len(set(columns))!=len(columns)):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        columns = tuple(columns)
        water = header['payload']['water']
        if type(water) is not int or water<0:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        def values():
            for _,block in self._read_blocks(header,seal,'MARKET',kind=kind,listings=listings):
                yield block
            cursor = self.db.cursor()
            cursor.row_factory = None
            cursor.execute('''SELECT raw.*,proof.payload_json,proof.payload_hash,proof.available_at_ns,proof.id
                FROM intraday_capture_events proof CROSS JOIN intraday_observations raw
                WHERE proof.id>? AND proof.kind='ADMISSION' AND proof.available_at_ns<=?
                AND raw.id=proof.observation_id AND raw.profile_id=? AND raw.data_mode=? AND raw.provenance=?
                AND raw.replay_grade=? AND raw.kind=?''',(water,cutoff,*self.reader.store.namespace,kind))
            try:
                yield cursor
            finally:
                cursor.close()
        result = self._market_rows(chain.from_iterable(values()),columns,cutoff,start,end,listings,revisions,(kind,water,self.scope))
        if signature!=self.reader._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        candidates = tuple(value for _,value in self.reader._secret_fields() if isinstance(value,str) and value)
        if candidates:
            from backend.app.data_providers.transport import SafeProviderTransport
            if SafeProviderTransport._payload_contains_secret(result,candidates):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return result

    def audit_snapshot(self,snapshot_id,*,cancelled=None):
        """Explicit original-RAW audit, separate from reading authoritative v3."""
        try:
            with self._cancel_scope(cancelled):
                return self.reader._open(snapshot_id,10_000,8_388_608)
        except Exception as error:
            from backend.app.intraday.snapshots import SnapshotError
            if isinstance(error,SnapshotError):
                raise
            raise MetadataError('SNAPSHOT_INPUT_MISSING') from None

    def seal_snapshot(self,snapshot_id,*,max_disk_bytes,min_free_bytes,cancelled=None):
        # Import validation must use the original reader, not an earlier wrapper.
        if self.find('SNAPSHOT',snapshot_id) is not None:
            raise MetadataError('FROZEN_EVIDENCE_EXISTS')
        with self._cancel_scope(cancelled):
            original = self.reader.open(snapshot_id)
        evidence = self.snapshot_evidence(original)
        try:
            set_id = self._begin('SNAPSHOT',snapshot_id,evidence,max_disk_bytes,min_free_bytes,
                                 expected_signature=original.timeline.signature,cancelled=cancelled)
            def records():
                for raw in self.db.execute('SELECT * FROM intraday_dataset_members WHERE snapshot_id=? ORDER BY ingest_sequence',(snapshot_id,)):
                    member = _decode(raw)
                    refs = chain((member['payload']['reference'],),member['payload']['dependencies'])
                    sources = []
                    for ref in refs:
                        source = self.reader._raw_source(ref['table'],ref['id'])
                        text = source.pop('payload_json')
                        sources.append([_text(source),text])
                    yield [compact_member(raw),sources]
            self._blocks(set_id,'MEMBER',records(),maximum=max_disk_bytes,minimum=min_free_bytes,cancelled=cancelled)
            self._build_locators(set_id,cancelled=cancelled)
            self._blocks(set_id,'TIMELINE',(self._timeline_text(row) for row in self._original_rows(original)),maximum=max_disk_bytes,
                         minimum=min_free_bytes,cancelled=cancelled)
            self._finish(set_id,max_disk_bytes,min_free_bytes,cancelled,validate=lambda:self.reader.open(snapshot_id))
            return set_id
        except Exception:
            self.db.rollback()
            raise

    def snapshot_evidence(self,original):
        snapshot_id = original.snapshot_id
        from backend.app.data_providers.alpaca_metadata import published_select
        publication = self.db.execute(published_select('intraday_capture_events')+
            ' WHERE raw.id=? ORDER BY pub.id LIMIT 1',(original.publication_id,)).fetchone()
        return {'manifest':original.manifest,'digest':original.digest,'report':original.report,
                    'known_at_ns':original.known_at_ns,'publication_id':original.publication_id,
                    'publication_hash':original.publication_hash,
                    'header':dict(self.db.execute('SELECT * FROM intraday_dataset_snapshots WHERE id=?',(snapshot_id,)).fetchone()),
                    'quality':dict(self.db.execute('SELECT * FROM intraday_quality_reports WHERE snapshot_id=?',(snapshot_id,)).fetchone()),
                    'publication':dict(publication)}

    def _original_rows(self,original):
        from backend.app.intraday.snapshots import _reference_batches
        # An explicit import owns BEGIN IMMEDIATE and writes only its new
        # archive. Hydration is private and uses the fully validated inputs.
        for items in _reference_batches(original.timeline._ordered(original.manifest['cutoff_ns'])):
            for rows in self.reader._hydrated_batches([json.loads(item[0]) for item in items],validated=True):
                for row in rows:
                    row.pop('capture_order',None)
                    if row['table']=='intraday_news_versions':
                        row['links'] = original.timeline.links(row['id'])
                    yield row

    def _members(self, record, manifest, with_raw=False):
        from backend.app.intraday.replay import visible_rows
        from backend.app.intraday.snapshots import _REFERENCES, _SOURCE_TABLES, _row_byte_bound
        raw,sources = record
        member = _decode(raw)
        body = member['payload']
        check_ns(member['persisted_at_ns'])
        check_ns(member['ingest_run_id'])
        if (tuple(raw[key] for key in SCOPE)!=self.scope or type(body['replay']) is not bool
            or type(body['dependencies']) is not list):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        refs = [body['reference'],*body['dependencies']]
        kind,column = (('UNIVERSE_MEMBER','universe_member_id') if refs[0]['table']=='intraday_universe_members'
                       else _REFERENCES[refs[0]['table']])
        if member['member_kind']!=kind or type(member[column]) is not int or member[column]!=refs[0]['id'] or len(sources)!=len(refs):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        result,raw_available = [],[]
        for ref,(header_text,payload_text) in zip(refs,sources,strict=True):
            if ref['table'] not in _SOURCE_TABLES or type(ref['id']) is not int or not 0<ref['id']<=MAX_NS:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            header = json.loads(header_text)
            if (_text(header)!=header_text or _sha(header_text)!=ref['source_hash']
                or type(header['id']) is not int or header['id']!=ref['id']):
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            for key in ('received_at_ns','persisted_at_ns','ingest_sequence','ingest_run_id'):
                check_ns(header[key])
            for key,value in header.items():
                if value is not None and (key.endswith(('_at_ns','_time_ns','_from_ns','_to_ns'))
                    or key in {'ingest_sequence','ingest_run_id','availability_floor_ns'}):
                    check_ns(value)
            source = _decode({**header,'payload_json':payload_text})
            raw_available.append(header.get('available_at_ns'))
            if source['payload_hash']!=ref['payload_hash']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            allowed = {'available_at_ns','recorded_available_at_ns','admission_id','publication_id','publication_hash',
                       'capture_ingest_sequence','metadata_dependency','first_received_at_ns','table'}
            if type(ref['projection']) is not dict or not set(ref['projection'])<=allowed or ref['projection'].get('table',ref['table'])!=ref['table']:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            source.update(ref['projection'])
            source['table'] = ref['table']
            if _row_byte_bound(source,_decoded=True)>8_388_608:
                raise MetadataError('RESOURCE_LIMIT')
            if body['replay']:
                if len(visible_rows([source],cutoff_ns=manifest['cutoff_ns'],namespace=self.scope,_decoded=True))!=1:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
            elif tuple(source[key] for key in SCOPE)!=self.scope:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            result.append(source)
        return (member,result,raw_available) if with_raw else (member,result)

    def _validated_members(self,record,manifest,with_raw=False):
        from backend.app.intraday.snapshots import _decode_evidence
        if _NATIVE is None or with_raw and not getattr(_NATIVE,'FROZEN_MEMBER_RAW',False):
            return self._members(record,manifest,with_raw)
        if with_raw:
            return _NATIVE.frozen_member(record,self.scope,manifest['cutoff_ns'],_decode_evidence,self._members,manifest,True)
        return _NATIVE.frozen_member(record,self.scope,manifest['cutoff_ns'],_decode_evidence,self._members,manifest)

    def _links(self,set_id,news_id):
        result = []
        for item in self.db.execute('''SELECT l.source_id FROM intraday_frozen_locators l
            JOIN intraday_frozen_sets s ON s.id=l.set_id WHERE l.set_id=? AND l.source_table='intraday_news_links'
            AND ((s.subject_kind='BUNDLE' AND l.replay=1) OR (s.subject_kind='SNAPSHOT' AND l.dependency_ordinal<0))
            ORDER BY l.source_id''',(set_id,)):
            row = self._source(set_id,'intraday_news_links',item[0])
            if row['news_version_id']==news_id:
                row.pop('table',None)
                result.append(row)
        return result

    def _binding(self,row,replay,*,set_id=None,snapshot_id=None,links=None):
        if _NATIVE is not None and hasattr(_NATIVE,'frozen_binding'):
            result = _NATIVE.frozen_binding(row,replay)
            if result is not NotImplemented:
                return result
        return self._binding_python(row,replay,set_id=set_id,snapshot_id=snapshot_id,links=links)

    @staticmethod
    def _complex(row):
        return (row.get('publication_id') is not None
                or row['table']!='intraday_observations' and not (row['table']=='intraday_capture_events' and row.get('kind')=='ADMISSION')
                or row['table']=='intraday_capture_events' and (bool(row['payload'].get('orphan_raw_proof'))
                    or row['payload'].get('metadata_kind')=='COLLECTOR_HANDSHAKE'))

    def _binding_python(self,row,replay,*,set_id=None,snapshot_id=None,links=None):
        from backend.app.intraday.snapshots import _envelope_bytes
        payload = row['payload']
        targets = [(table,row.get(key)) for table,key in (
            ('intraday_observations','observation_id'),('intraday_news_versions','news_version_id'),('intraday_event_versions','event_version_id'))
            if row.get(key) is not None] if row['table']=='intraday_capture_events' and row.get('kind')=='ADMISSION' else []
        target = targets[0] if len(targets)==1 else (None,None)
        output = dict(row)
        output.pop('capture_order',None)
        if row['table']=='intraday_news_versions':
            output['links'] = (links(row['id']) if links is not None else self.reader._frozen_links(snapshot_id,row['id']) if snapshot_id is not None
                               else self._links(set_id,row['id']))
        return (row['table'],row['id'],row['payload_hash'],row.get('admission_id'),*target,
                payload.get('payload_hash') if targets else None,row.get('kind',''),int(replay),
                _sha(_envelope_bytes(output,_owned=True)) if replay else None,
                row.get('available_at_ns'),row['received_at_ns'],row['capture_id'],
                row.get('admission_id',row.get('publication_id',row['id'])),
                row.get('capture_ingest_sequence',payload.get('intake_sequence',row['ingest_sequence'])),row['ingest_sequence'])

    def _build_locators(self,set_id,*,links=None,manifest=None,cancelled=None):
        header = _decode(self.db.execute('SELECT * FROM intraday_frozen_sets WHERE id=?',(set_id,)).fetchone())
        # Before publication we own this transaction and read our own staging.
        facts = header['subject_kind']=='BUNDLE'
        manifest = header['payload']['manifest'] if manifest is None else manifest
        for ordinal,records in self._raw_blocks(set_id,'MEMBER',cancelled=cancelled):
            for index,record in enumerate(records):
                decoded = self._validated_members(record,manifest,facts)
                if isinstance(records,_FramedRecords):
                    _tree_guard([records,decoded])
                member,rows = decoded[:2]
                for dep,row in enumerate(rows,-1):
                    binding = self._binding(row,member['payload']['replay'],snapshot_id=header['subject_id'] if not facts else None,
                                            links=links)
                    self.db.execute('''INSERT INTO intraday_frozen_locators
                        (set_id,source_table,source_id,block_ordinal,record_ordinal,dependency_ordinal,
                         payload_hash,admission_id,admitted_table,admitted_id,admitted_hash,kind,replay,output_hash,
                         available,received,capture,proof,intake,ingest)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (set_id,*binding[:2],ordinal,index,dep,*binding[2:]))
                    if facts:
                        ref = ([member['payload']['reference'],*member['payload']['dependencies']])[dep+1]
                        self.db.execute('''INSERT INTO intraday_frozen_source_refs
                            (set_id,source_table,source_id,source_hash,reference_json,raw_available,
                             block_ordinal,record_ordinal,dependency_ordinal,persisted,metadata_scope,needs_closure)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (set_id,row['table'],row['id'],ref['source_hash'],reference_text(member,ref),decoded[2][dep+1],
                             ordinal,index,dep,row['persisted_at_ns'],int(tuple(row[key] for key in SCOPE)!=self.scope),
                             int(self._complex(row))))

    def _source(self,set_id,table,source_id,*,projected=True):
        from backend.app.intraday.snapshots import _SOURCE_TABLES
        if table not in _SOURCE_TABLES or type(source_id) is not int or not 0<source_id<=MAX_NS:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        raw = self.db.execute('''SELECT b.body,b.input_bytes,b.ordinal,l.record_ordinal,l.dependency_ordinal
            FROM intraday_frozen_locators l JOIN intraday_frozen_blocks b ON b.set_id=l.set_id
            AND b.domain='MEMBER' AND b.ordinal=l.block_ordinal
            WHERE l.set_id=? AND l.source_table=? AND l.source_id=?''',(set_id,table,source_id)).fetchone()
        if raw is None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        records = _unpack(raw['body'],raw['input_bytes'])
        if _fragment(records[0]):
            records = next((values for ordinal,values in self._raw_blocks(set_id,'MEMBER') if ordinal==raw['ordinal']),None)
            if records is None:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        record = records[raw['record_ordinal']]
        body = _decode(record[0])['payload']
        ref = ([body['reference'],*body['dependencies']])[raw['dependency_ordinal']+1]
        header,payload = record[1][raw['dependency_ordinal']+1]
        row = _decode({**json.loads(header),'payload_json':payload})
        if projected:
            row.update(ref['projection'])
        row['table'] = table
        return row

    def _metadata(self,evidence):
        from backend.app.data_providers.alpaca_metadata import decode_published
        from backend.app.intraday.quality import validate_manifest
        header = _decode(evidence['header'])
        report = _decode(evidence['quality'])
        pub = decode_published(evidence['publication'],'intraday_capture_events',MAX_NS)
        manifest,proof = header['payload'],pub['payload']
        for row in (header,report,pub):
            if type(row['id']) is not int or not 0<row['id']<=MAX_NS:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            check_ns(row['ingest_run_id'])
            check_ns(row['persisted_at_ns'])
        validate_manifest(manifest)
        if (tuple(header[key] for key in SCOPE)!=self.scope or tuple(manifest['namespace'])!=self.scope
            or tuple(report[key] for key in SCOPE)!=self.scope or tuple(pub[key] for key in SCOPE)!=self.scope
            or _text(evidence['manifest'])!=_text(manifest) or _text(evidence['report'])!=_text(report['payload'])
            or manifest['policy']!=self.reader._policy() or manifest['profile']!=self.reader._profile()
            or any(header[key]!=manifest[key] for key in ('start_at_ns','end_at_ns','cutoff_ns'))
            or header['policy_id']!=manifest['policy']['id'] or proof.get('complete') is not True or pub['kind']!='BOOTSTRAP'
            or proof.get('metadata_kind')!='DATASET_PUBLICATION' or proof['snapshot_id']!=header['id']
            or proof['snapshot_hash']!=header['payload_hash'] or proof['digest']!=header['digest']
            or proof['typed_member_count']!=header['member_count'] or proof['timeline_count']!=manifest['timeline_count']
            or report['payload_hash']!=proof['report_hash'] or report['id']!=proof['report_id']
            or report['snapshot_id']!=header['id'] or report['policy_id']!=header['policy_id']
            or report['outcome']!=report['payload']['outcome'] or pub['ingest_run_id']!=header['ingest_run_id']
            or report['ingest_run_id']!=header['ingest_run_id']
            or json.loads(report['metrics_json'])!=report['payload']['metrics']
            or json.loads(report['limits_json'])!=report['payload']['limits']
            or evidence['digest']!=header['digest'] or evidence['known_at_ns']!=pub['available_at_ns']
            or evidence['publication_id']!=pub['id'] or evidence['publication_hash']!=pub['payload_hash']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return header,report,pub

    def open_snapshot(self,found,max_occurrences,max_bytes):
        from backend.app.intraday.snapshots import ValidatedDataset
        header,seal = found
        signature = self.reader._read_signature()
        evidence = header['payload']
        manifest = evidence['manifest']
        original,report,publication = self._metadata(evidence)
        max_bytes = min(max_bytes,manifest.get('resources',{}).get('max_chunk_bytes',8_388_608))
        max_occurrences = min(max_occurrences,manifest.get('resources',{}).get('max_chunk_occurrences',10_000))
        counts = self.validate_inputs(found,max_bytes=max_bytes,digest=evidence['digest'],ingest_run_id=original['ingest_run_id'])
        if (counts['members']!=manifest['typed_member_count'] or counts['replay']!=manifest['timeline_count']
            or counts['audit']!=manifest['audit_member_count']
            or publication['payload']['durable_at_ns']<max(counts['latest'],original['persisted_at_ns'],report['persisted_at_ns'],manifest['cutoff_ns'])
            or publication['payload']['durable_at_ns']>publication['available_at_ns']):
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        timeline = BlockTimeline(self,header,seal,signature,max_occurrences,max_bytes)
        result = ValidatedDataset(header['subject_id'],evidence['digest'],evidence['known_at_ns'],manifest,evidence['report'],
                                  timeline,evidence['publication_id'],evidence['publication_hash'])
        if signature!=self.reader._read_signature():
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return result

    def validate_inputs(self,found,*,max_bytes=8_388_608,digest=None,ingest_run_id=None,timeline=True):
        """Private full evidence pass; returns counts, never a public handle."""
        header,seal = found
        evidence = header['payload']
        manifest = evidence['manifest']
        facts = header['subject_kind']=='BUNDLE'
        hasher = hashlib.sha256() if digest is not None else None
        if hasher is not None:
            _frame(hasher,_text(manifest))
        members = replay = audit = 0
        latest = 0
        locator_count = 0
        child_bindings,previous_source = 0,None
        candidates = tuple(value for _,value in self.reader._secret_fields() if isinstance(value,str) and value)
        def binding_oracle(row,replay):
            return self._binding(row,replay,set_id=header['id'])
        for ordinal,records in self._read_blocks(header,seal,'MEMBER'):
            expected,expected_facts = [],[]
            prepared = None
            native = NotImplemented
            if (not candidates and type(records) is list and max_bytes>=4*INPUT_LIMIT
                and _NATIVE is not None and hasattr(_NATIVE,'frozen_inputs')):
                from backend.app.intraday.snapshots import _decode_evidence
                native = _NATIVE.frozen_inputs(records,self.scope,manifest,ordinal,facts,ingest_run_id,hasher,
                                               _decode_evidence,self._members,binding_oracle)
            if native is not NotImplemented:
                expected,expected_facts,member_count,replay_count,audit_count,last,complex_rows,prepared = native
                members += member_count
                replay += replay_count
                audit += audit_count
                latest = max(latest,last)
                locator_count += len(expected)
                for row in complex_rows:
                    self.reader._row_closure(header['subject_id'],row,
                        require=lambda table,source_id,payload_hash=None:self._require(header['id'],table,source_id,payload_hash))
            for index,record in enumerate(records if native is NotImplemented else ()):
                decoded = self._validated_members(record,manifest,facts)
                if isinstance(records,_FramedRecords):
                    _tree_guard([records,decoded])
                member,rows = decoded[:2]
                if candidates:
                    from backend.app.data_providers.transport import SafeProviderTransport
                    if SafeProviderTransport._payload_contains_secret([member,*rows],candidates):
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                if ingest_run_id is not None and member['ingest_run_id']!=ingest_run_id:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                latest = max(latest,member['persisted_at_ns'])
                if hasher is not None:
                    _frame(hasher,member['payload_json'])
                members += 1
                for dep,row in enumerate(rows,-1):
                    if isinstance(records,_FramedRecords) or max_bytes<4*INPUT_LIMIT:
                        from backend.app.intraday.snapshots import SnapshotError, _row_byte_bound
                        if _row_byte_bound(row,_decoded=True)>max_bytes:
                            raise SnapshotError('RESOURCE_LIMIT')
                    binding = self._binding(row,member['payload']['replay'],set_id=header['id'])
                    expected.append((*binding[:2],ordinal,index,dep,*binding[2:]))
                    if facts:
                        ref = ([member['payload']['reference'],*member['payload']['dependencies']])[dep+1]
                        raw_available = decoded[2][dep+1]
                        if raw_available is not None:
                            check_ns(raw_available)
                        expected_facts.append((row['table'],row['id'],ref['source_hash'],reference_text(member,ref),
                                               raw_available,ordinal,index,dep,row['persisted_at_ns'],
                                               int(tuple(row[key] for key in SCOPE)!=self.scope),int(self._complex(row))))
                    locator_count += 1
                    if member['payload']['replay'] and self._complex(row) and (row['table']=='intraday_observations' or row['table']=='intraday_capture_events' and row.get('kind')=='ADMISSION'):
                        self.reader._row_closure(header['subject_id'],row,
                            require=lambda table,source_id,payload_hash=None:self._require(header['id'],table,source_id,payload_hash))
                    if member['payload']['replay']:
                        replay += 1
                    else:
                        audit += 1
            actual = [tuple(row) for row in self.db.execute('''SELECT source_table,source_id,block_ordinal,record_ordinal,
                dependency_ordinal,payload_hash,admission_id,admitted_table,admitted_id,admitted_hash,kind,replay,output_hash,
                available,received,capture,proof,intake,ingest
                FROM intraday_frozen_locators WHERE set_id=? AND block_ordinal=? ORDER BY record_ordinal,dependency_ordinal''',
                (header['id'],ordinal))]
            if actual!=expected:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            if facts:
                actual_facts = [tuple(row) for row in self.db.execute('''SELECT source_table,source_id,source_hash,reference_json,
                    raw_available,block_ordinal,record_ordinal,dependency_ordinal,persisted,metadata_scope,needs_closure FROM intraday_frozen_source_refs
                    WHERE set_id=? AND block_ordinal=? ORDER BY record_ordinal,dependency_ordinal''',(header['id'],ordinal))]
                if actual_facts!=expected_facts:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                for fact in expected_facts:
                    identity = (fact[0],fact[1])
                    if previous_source is not None and identity<=previous_source:
                        raise MetadataError('SNAPSHOT_INPUT_MISSING')
                    previous_source = identity
                child_bindings += self._child_sources_block(header['id'],expected,expected_facts,prepared=prepared)
        if self.db.execute('SELECT COUNT(*) FROM intraday_frozen_locators WHERE set_id=?',(header['id'],)).fetchone()[0]!=locator_count:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if hasher is not None and hasher.hexdigest()!=digest:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if facts and self.db.execute('SELECT COUNT(*) FROM intraday_frozen_source_refs WHERE set_id=?',(header['id'],)).fetchone()[0]!=locator_count:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        if facts and self.db.execute('SELECT COUNT(*) FROM intraday_frozen_child_refs WHERE set_id=?',(header['id'],)).fetchone()[0]!=child_bindings:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        missing = self.db.execute('''SELECT 1 FROM intraday_frozen_locators src LEFT JOIN intraday_frozen_locators receipt
            ON receipt.set_id=src.set_id AND receipt.source_table='intraday_capture_events' AND receipt.source_id=src.admission_id
            WHERE src.set_id=? AND src.replay=1 AND src.admission_id IS NOT NULL AND (receipt.source_id IS NULL OR receipt.kind!='ADMISSION'
                OR receipt.admitted_table IS NOT src.source_table OR receipt.admitted_id IS NOT src.source_id
                OR receipt.admitted_hash IS NOT src.payload_hash)
            LIMIT 1''',(header['id'],)).fetchone()
        if missing:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        def require(table,source_id,payload_hash=None):
            return self._require(header['id'],table,source_id,payload_hash)
        rare = self.db.execute('''SELECT source_table,source_id FROM intraday_frozen_locators WHERE set_id=? AND replay=1
            AND NOT(source_table='intraday_observations' OR source_table='intraday_capture_events' AND kind='ADMISSION')''',(header['id'],))
        for table,source_id in rare:
            row = require(table,source_id)
            self.reader._row_closure(header['subject_id'],row,require=require)
        if timeline:
            self.validate_timeline(found,expected_count=replay,max_bytes=max_bytes)
        self._document_text(evidence)
        self.reader.archive.safe_json({'evidence_root':seal['root']})
        return {'members':members,'replay':replay,'audit':audit,'latest':latest}

    def validate_timeline(self,found,*,expected_count,max_bytes=8_388_608):
        """Provisional byte/order pass, composed with fresh locator validation."""
        header,seal = found
        order = self.db.execute('''WITH visible AS (
            SELECT *,MIN(proof) OVER(PARTITION BY received,capture) AS anchor
            FROM intraday_frozen_locators WHERE set_id=? AND replay=1)
            SELECT output_hash FROM visible ORDER BY available,received,anchor,intake,proof,ingest,source_table,source_id''',
            (header['id'],))
        seen = 0
        for _ordinal,texts in self._read_blocks(header,seal,'TIMELINE'):
            for text in texts:
                expected = order.fetchone()
                if expected is None or type(text) is not str:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                encoded = text.encode()
                if len(encoded)>max_bytes:
                    from backend.app.intraday.snapshots import SnapshotError
                    raise SnapshotError('RESOURCE_LIMIT')
                if _sha(encoded)!=expected[0]:
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                seen += 1
        if seen!=expected_count or order.fetchone() is not None:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        self.reader.archive.safe_json({'evidence_root':seal['root']})
        return seen

    def _child_sources_block(self,set_id,locators,facts,*,prepared=None):
        """Exact union/bindings against only this block's freshly derived facts."""
        def groups():
            if prepared is not None:
                table,parameters,expected = prepared
                yield table,parameters,expected,len(expected)
                return
            grouped = {}
            for locator,fact in zip(locators,facts,strict=True):
                grouped.setdefault(fact[0],[]).append((locator,fact))
            for table,items in grouped.items():
                parameters = [value for locator,fact in items
                              for value in (fact[1],fact[2],locator[5],fact[8],fact[9],fact[4])]
                expected = {fact[1]:(locator[11],fact[3]) for locator,fact in items}
                yield table,parameters,expected,len(items)
        count = 0
        for table,parameters,expected,size in groups():
            values = ','.join('(?,?,?,?,?,?)' for _ in range(size))
            parameters = [*parameters,set_id,table]
            rows = self.db.execute('''WITH fresh(source_id,source_hash,payload_hash,persisted,metadata_scope,raw_available) AS (
                VALUES '''+values+''') SELECT f.source_id,MAX(c.replay),
                substr(COALESCE(MIN(CASE WHEN c.replay=1 THEN printf('%019d',c.rank_available)||c.reference_json END),
                                MIN(printf('%019d',c.rank_available)||c.reference_json)),20),COUNT(c.source_id),
                MAX(CASE WHEN c.source_id IS NULL THEN 1 ELSE
                    json_extract(c.reference_json,'$.source_hash') IS NOT f.source_hash
                    OR json_extract(c.reference_json,'$.payload_hash') IS NOT f.payload_hash
                    OR c.available IS NOT CASE WHEN json_type(c.reference_json,'$.projection.available_at_ns') IS NULL
                         THEN f.raw_available ELSE json_extract(c.reference_json,'$.projection.available_at_ns') END
                    OR c.replay=1 AND (c.available IS NULL OR c.available<f.persisted)
                    OR c.replay=0 AND f.metadata_scope=1 END)
                FROM fresh f LEFT JOIN intraday_frozen_child_refs c
                    ON c.set_id=? AND c.source_table=? AND c.source_id=f.source_id GROUP BY f.source_id''',parameters)
            seen = 0
            for source_id,replay,reference,occurrences,invalid in rows:
                if invalid or not occurrences or (replay,reference)!=expected.get(source_id):
                    raise MetadataError('SNAPSHOT_INPUT_MISSING')
                count += occurrences
                seen += 1
            if seen!=size:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return count

    def _require(self,set_id,table,source_id,payload_hash=None):
        row = self._source(set_id,table,source_id)
        if payload_hash is not None and row['payload_hash']!=payload_hash:
            raise MetadataError('SNAPSHOT_INPUT_MISSING')
        return row


class BlockTimeline:
    def __init__(self,archive,header,seal,signature,max_occurrences,max_bytes):
        self.archive,self.header,self.seal,self.signature = archive,header,seal,signature
        self.manifest = header['payload']['manifest']
        self.evidence_format,self.evidence_root = FORMAT,seal['root']
        self.max_occurrences,self.max_bytes = max_occurrences,max_bytes
        self.validator = lambda:archive.reader.open(header['subject_id'],max_occurrences=max_occurrences,max_bytes=max_bytes)

    def __len__(self):
        return (self.header['payload']['timeline_count'] if self.header['subject_kind']=='BUNDLE'
                else self.manifest['timeline_count'])

    def _fence(self,*,buffered=False):
        if self.signature!=self.archive.reader._read_signature():
            if buffered:
                raise MetadataError('SNAPSHOT_INPUT_MISSING')
            self.validator()
            self.signature = self.archive.reader._read_signature()

    def __iter__(self):
        return self.iter_rows()

    def iter_rows(self,*,cutoff_ns=None):
        return self._iter_rows(cutoff_ns=cutoff_ns,public_rows=True)

    def _cutoff_rows(self,cutoff):
        # Anchors depend on the visible prefix. Filtering a later total order
        # would retain anchors introduced by evidence unavailable at cutoff.
        ordered = self.archive.db.execute('''WITH visible AS (
            SELECT *,MIN(proof) OVER(PARTITION BY received,capture) AS anchor
            FROM intraday_frozen_locators WHERE set_id=? AND replay=1 AND available<=?)
            SELECT source_table,source_id FROM visible
            ORDER BY available,received,anchor,intake,proof,ingest,source_table,source_id''',(self.header['id'],cutoff))
        for table,source_id in ordered:
            self._fence(buffered=True)
            row = self.archive._source(self.header['id'],table,source_id)
            row.pop('capture_order',None)
            if table=='intraday_news_versions':
                row['links'] = self.archive._links(self.header['id'],source_id)
            yield row

    def _iter_rows(self,*,cutoff_ns,public_rows,with_size=False):
        cutoff = self.manifest['cutoff_ns'] if cutoff_ns is None else cutoff_ns
        check_ns(cutoff)
        if cutoff>self.manifest['cutoff_ns'] or cutoff<self.manifest.get('carry_at_ns',0):
            raise ValueError('SNAPSHOT_CUTOFF')
        self._fence()
        if cutoff!=self.manifest['cutoff_ns']:
            for row in self._cutoff_rows(cutoff):
                text = FrozenBlocks._timeline_text(row)
                if public_rows:
                    self._fence(buffered=True)
                yield (row,len(text.encode())) if with_size else row
            self._fence(buffered=True)
            return
        for _ordinal,rows in self.archive._read_blocks(self.header,self.seal,'TIMELINE'):
            self._fence(buffered=True)
            for text in rows:
                row = from_json(text,cache_strings=False,allow_inf_nan=False)
                if isinstance(rows,_FramedRecords):
                    _tree_guard([rows,row])
                if row['available_at_ns']<=cutoff:
                    if public_rows:
                        self._fence(buffered=True)
                    yield (row,len(text.encode())) if with_size else row
        self._fence(buffered=True)

    def chunks(self,*,cutoff_ns=None):
        chunk,size = [],0
        for row,charge in self._iter_rows(cutoff_ns=cutoff_ns,public_rows=False,with_size=True):
            if charge>self.max_bytes:
                raise MetadataError('RESOURCE_LIMIT')
            if chunk and (len(chunk)==self.max_occurrences or size+charge>self.max_bytes):
                self._fence(buffered=True)
                yield chunk
                chunk,size = [],0
            chunk.append(row)
            size += charge
        if chunk:
            self._fence(buffered=True)
            yield chunk

    def page(self,*,offset=0,limit=50,input_type='ALL'):
        from backend.app.intraday.snapshots import FrozenTimeline
        return FrozenTimeline.page(self,offset=offset,limit=limit,input_type=input_type)
