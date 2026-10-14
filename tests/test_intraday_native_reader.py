"""Offline differential contracts for the optional native market reader."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import sqlite3
import struct

import pytest
from test_intraday_store import event, prepared

from backend.app.intraday.replay import select_versions
from backend.app.intraday.snapshots import _decode_evidence

native = pytest.importorskip('_investedge_reader_native',reason='Optional native prototype must be built explicitly')


@pytest.fixture
def native_query_supported():
    db = sqlite3.connect(':memory:')
    try:
        try:
            assert list(native.query(db,'SELECT 1',()))==[(1,)]
        except NotImplementedError:
            pytest.skip('Readonly cursor prototype requires exact CPython 3.14.7 Windows ABI')
    finally:
        db.close()


@pytest.mark.usefixtures('native_query_supported')
def test_native_query_keeps_same_connection_transaction_and_scalar_types():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE t(a,b,c,d,e)')
    db.execute('INSERT INTO t VALUES(?,?,?,?,?)',('é😀\x00',2**63-1,1.25,None,b'\x00\xff'))
    before = db.total_changes
    assert db.in_transaction
    assert list(native.query(db,'SELECT * FROM t WHERE b=?',(2**63-1,)))==[('é😀\x00',2**63-1,1.25,None,b'\x00\xff')]
    assert db.total_changes==before and db.in_transaction
    db.close()


@pytest.mark.parametrize('sql',['INSERT INTO t VALUES(1)','DROP TABLE t','BEGIN','SELECT 1; DELETE FROM t',
    'WITH x AS (SELECT 1) DELETE FROM t'])
@pytest.mark.usefixtures('native_query_supported')
def test_native_query_rejects_writes_and_multiple_statements(sql):
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE t(a)')
    before = db.total_changes
    with pytest.raises(ValueError,match='NATIVE_READ_ONLY'):
        native.query(db,sql,())
    assert db.total_changes==before and not db.in_transaction
    assert db.execute('SELECT COUNT(*) FROM t').fetchone()[0]==0
    db.close()


@pytest.mark.parametrize('sql',['PRAGMA foreign_keys=OFF','PRAGMA query_only=OFF','PRAGMA read_uncommitted=ON'])
@pytest.mark.usefixtures('native_query_supported')
def test_native_query_rejects_prepare_time_pragma_effects(sql):
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA query_only=ON')
    names = ('foreign_keys','query_only','read_uncommitted')
    before = tuple(db.execute('PRAGMA '+name).fetchone()[0] for name in names)
    with pytest.raises(ValueError,match='NATIVE_READ_ONLY'):
        native.query(db,sql,())
    assert tuple(db.execute('PRAGMA '+name).fetchone()[0] for name in names)==before
    db.close()


@pytest.mark.usefixtures('native_query_supported')
def test_native_query_keeps_existing_wal_read_snapshot(tmp_path):
    path = tmp_path/'native-snapshot.db'
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE t(a)')
    db.executemany('INSERT INTO t VALUES(?)',[(index,) for index in range(20)])
    db.commit()
    active = db.execute('SELECT * FROM t')
    assert active.fetchone()==(0,)
    other = sqlite3.connect(path)
    other.execute('INSERT INTO t VALUES(99)')
    other.commit()
    try:
        assert not db.in_transaction
        assert list(native.query(db,'SELECT COUNT(*) FROM t',()))==[(20,)]
    finally:
        active.close()
        other.close()
        db.close()


@pytest.mark.usefixtures('native_query_supported')
def test_native_query_falls_back_for_conversion_modes_and_checks_closed_connection():
    db = sqlite3.connect(':memory:',detect_types=sqlite3.PARSE_DECLTYPES)
    with pytest.raises(NotImplementedError,match='NATIVE_ABI_UNSUPPORTED'):
        native.query(db,'SELECT 1',())
    db.close()
    db = sqlite3.connect(':memory:')
    rows = native.query(db,'SELECT 1 UNION ALL SELECT 2',())
    db.close()
    with pytest.raises(sqlite3.ProgrammingError):
        next(rows)


@pytest.mark.usefixtures('native_query_supported')
def test_native_query_preserves_authorizer_and_thread_owner():
    from concurrent.futures import ThreadPoolExecutor

    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE t(a)')
    db.set_authorizer(lambda action,*args:sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ else sqlite3.SQLITE_OK)
    with pytest.raises(sqlite3.DatabaseError,match='NATIVE_READ_FAILED'):
        native.query(db,'SELECT * FROM t',())
    db.set_authorizer(None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(native.query,db,'SELECT 1',())
        with pytest.raises(sqlite3.ProgrammingError):
            result.result()
    db.close()


@pytest.mark.usefixtures('native_query_supported')
def test_native_query_is_exhausted_after_step_error():
    db = sqlite3.connect(':memory:')
    failed = False
    def value(number):
        nonlocal failed
        if number==2 and not failed:
            failed = True
            raise ValueError('synthetic failure')
        return number
    db.create_function('value',1,value)
    rows = native.query(db,'WITH t(a) AS (VALUES(1),(2),(3)) SELECT value(a) FROM t',())
    assert next(rows)==(1,)
    with pytest.raises(sqlite3.OperationalError,match='NATIVE_READ_FAILED'):
        next(rows)
    assert list(rows)==[]
    db.close()


@pytest.mark.usefixtures('native_query_supported')
def test_native_query_rejects_registered_binding_adapters(monkeypatch):
    key = (int,sqlite3.PrepareProtocol)
    monkeypatch.setitem(sqlite3.adapters,key,lambda value:value+1000)
    sqlite3.register_adapter(int,sqlite3.adapters[key])
    db = sqlite3.connect(':memory:')
    assert db.execute('SELECT ?',(1,)).fetchone()==(1001,)
    with pytest.raises(NotImplementedError,match='NATIVE_ABI_UNSUPPORTED'):
        native.query(db,'SELECT ?',(1,))
    db.close()


@pytest.mark.parametrize('payload',[
    {'a':1,'b':[None,True,False,1.0,-0.0,1e-7,1e20,100.00000000000001]},
    {'a':'é😀\n\t\\"','nested':{'a':{'z':3},'b':[]}},
    {'é':'unicode key','z':1}, {'a':10**307}, {'a':10**308},
])
def test_native_codec_matches_exact_v1_bytes(payload):
    text = json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    raw = {'id':1,'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()}
    assert native.decode_evidence(raw,_decode_evidence)==_decode_evidence(raw)


@pytest.mark.parametrize('text',[
    '{"b":1,"a":2}',' {"a":1}','{"a":-0}','{"a":1e-7}',
    '{"a":NaN}','{"a":1e309}','{"a":1,"a":1}','[]',
    '{"a":"\\u00e9"}', '{"a":'+str(10**400)+'}',
])
def test_native_codec_never_accepts_noncanonical_or_nonfinite_evidence(text):
    raw = {'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()}
    with pytest.raises(ValueError,match='METADATA_INVALID'):
        native.decode_evidence(raw,_decode_evidence)


def test_native_codec_checks_hash_and_uses_python_for_unsupported_shapes():
    raw = {'payload_json':'{"a":1}','payload_hash':'0'*64}
    with pytest.raises(ValueError,match='METADATA_INVALID'):
        native.decode_evidence(raw,_decode_evidence)
    text = '{"a":1,"b":"é😀"}'
    raw = {'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()}
    def forbidden(value):
        raise AssertionError('NORMAL_CANONICAL_FALLBACK')
    assert native.decode_evidence(raw,forbidden)['payload']=={'a':1,'b':'é😀'}
    assert 'payload' not in raw


@pytest.mark.parametrize('change',[{}, {'version':'other'}, {'observation_id':True},
    {'durable_at_ns':2**63},{'extra':'é😀'},{'observation_id':-1}])
def test_native_receipt_projection_validates_exact_payload_and_falls_back(change):
    body = {'version':'intraday-admission-v1','observation_id':7,'payload_hash':'a'*64,'durable_at_ns':2**63-1}|change
    text = json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    raw = {'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()}
    expected = tuple(body.get(key) for key in ('durable_at_ns','observation_id','payload_hash','version'))
    assert native.receipt_values(raw,_decode_evidence)==expected
    if not change:
        def forbidden(value):
            raise AssertionError('NORMAL_RECEIPT_FALLBACK')
        assert native.receipt_values(raw,forbidden)==expected
    with pytest.raises(ValueError,match='METADATA_INVALID'):
        native.receipt_values(raw|{'payload_hash':'0'*64},_decode_evidence)


def test_native_codec_matches_v1_for_random_float_bits_and_unicode_keys():
    rng = random.Random(14102026)
    for index in range(2500):
        values = [struct.unpack('!d',rng.getrandbits(64).to_bytes(8,'big'))[0] for _ in range(4)]
        values = [value for value in values if math.isfinite(value)]
        key = ('plain','é','\x0b','"','😀','')[index%6]
        text = json.dumps({key:values,'z':index},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        raw = {'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()}
        try:
            expected = _decode_evidence(raw)
        except ValueError as exc:
            with pytest.raises(type(exc),match=str(exc)):
                native.decode_evidence(raw,_decode_evidence)
        else:
            assert native.decode_evidence(raw,_decode_evidence)==expected


@pytest.mark.parametrize('revisions',[False,True])
def test_native_market_selection_matches_public_reducer_with_interleaved_captures(revisions):
    s = prepared()
    s.store.persist((event(s),))
    original = s.store.read_as_of('BAR',cutoff_ns=s.clock.now)[0]
    rng = random.Random(241014)
    for _ in range(80):
        rows = []
        for index in range(1,60):
            row = copy.deepcopy(original)
            row.update(id=index,capture_id=str(rng.randrange(4)),received_at_ns=original['received_at_ns']+rng.randrange(3),
                persisted_at_ns=original['persisted_at_ns']+3,available_at_ns=original['available_at_ns']+3,
                event_time_ns=original['event_time_ns']+rng.randrange(8),capture_ingest_sequence=rng.randrange(5))
            rows.append(row)
        rng.shuffle(rows)
        expected = select_versions(copy.deepcopy(rows),family='BAR',cutoff_ns=s.clock.now+10,revisions=revisions,_decoded=True)
        assert native.select_market(rows,s.clock.now+10,revisions)==expected


@pytest.mark.parametrize('column,value,error',[
    ('received_at_ns',True,'INVALID_TIMESTAMP'),('ingest_sequence',-1,'INVALID_TIMESTAMP'),
    ('persisted_at_ns',2**63,'INVALID_TIMESTAMP'),('feed','other','MIXED_NAMESPACE')])
def test_native_market_selection_keeps_visibility_validation(column,value,error):
    s = prepared()
    s.store.persist((event(s),))
    row = s.store.read_as_of('BAR',cutoff_ns=s.clock.now)[0]
    bad = copy.deepcopy(row)
    bad[column] = value
    with pytest.raises(ValueError,match=error):
        native.select_market([row,bad],s.clock.now,False)


def test_native_market_selection_validates_losing_revisions():
    s = prepared()
    s.store.persist((event(s),))
    row = s.store.read_as_of('BAR',cutoff_ns=s.clock.now)[0]
    bad = copy.deepcopy(row)
    bad.update(id=0,persisted_at_ns=0)
    with pytest.raises(ValueError,match='REPLAY_INPUT_INVALID'):
        native.select_market([bad,row],s.clock.now,False)


@pytest.mark.parametrize('revisions',[False,True])
def test_native_monotonic_market_rows_keep_validation_and_exact_anchors(revisions):
    s = prepared()
    s.store.persist((event(s),))
    original = s.store.read_as_of('BAR',cutoff_ns=s.clock.now)[0]
    rows = [dict(original,id=index,event_time_ns=original['event_time_ns']+index) for index in range(1,50)]
    expected = select_versions(copy.deepcopy(rows),family='BAR',cutoff_ns=s.clock.now,revisions=revisions,_decoded=True)
    assert native.select_market(rows,s.clock.now,revisions)==expected
    rows[-1]['feed'] = 'other'
    with pytest.raises(ValueError,match='MIXED_NAMESPACE'):
        native.select_market(rows,s.clock.now,revisions)


@pytest.mark.parametrize('revisions',[False,True])
@pytest.mark.parametrize('bounds',[(None,None),(float('nan'),None),(None,float('nan'))])
def test_native_market_cursor_matches_complete_python_reader(revisions,bounds):
    from dataclasses import replace

    from backend.app.data_providers.alpaca_metadata import check_ns
    from backend.app.intraday.store import StoreError

    s = prepared()
    s.store.persist((event(s),replace(event(s,change={'c':100}),ingest_sequence=2),
        replace(event(s),capture_id='other',ingest_sequence=1)))
    queries = []
    s.db.set_trace_callback(queries.append)
    expected = s.store.read_as_of('BAR',cutoff_ns=s.clock.now,revisions=revisions,start_ns=bounds[0],end_ns=bounds[1])
    s.db.set_trace_callback(None)
    query = next(sql for sql in queries if 'SELECT raw.*, proof.id AS proof_id' in sql)
    cursor = s.db.cursor()
    cursor.row_factory = None
    cursor.execute(query)
    columns = tuple(column[0] for column in cursor.description)
    source = tuple(key for key in columns if not key.startswith('proof_'))
    proof = tuple(columns.index(key) for key in ('proof_json','proof_hash','proof_available','proof_id'))
    try:
        assert native.read_market(cursor,source,proof,s.clock.now,*bounds,None,revisions,
            _decode_evidence,check_ns,StoreError)==expected
    finally:
        cursor.close()


@pytest.mark.parametrize('evidence',['raw','receipt'])
@pytest.mark.parametrize('bounds',[(None,None),(2**63-1,None),(None,0)])
def test_native_cursor_checks_each_evidence_before_bounds(evidence,bounds):
    from backend.app.data_providers.alpaca_metadata import check_ns
    from backend.app.intraday.store import StoreError

    s = prepared()
    s.store.persist((event(s),))
    queries = []
    s.db.set_trace_callback(queries.append)
    s.store.read_as_of('BAR',cutoff_ns=s.clock.now)
    s.db.set_trace_callback(None)
    query = next(sql for sql in queries if 'SELECT raw.*, proof.id AS proof_id' in sql)
    cursor = s.db.cursor()
    cursor.row_factory = None
    cursor.execute(query)
    columns = tuple(column[0] for column in cursor.description)
    source = tuple(key for key in columns if not key.startswith('proof_'))
    proof = tuple(columns.index(key) for key in ('proof_json','proof_hash','proof_available','proof_id'))
    rows = [list(row) for row in cursor]
    cursor.close()
    rows[0][columns.index('payload_hash' if evidence=='raw' else 'proof_hash')] = '0'*64
    with pytest.raises(ValueError,match='METADATA_INVALID'):
        native.read_market([tuple(row) for row in rows],source,proof,s.clock.now,*bounds,None,False,
            _decode_evidence,check_ns,StoreError)
