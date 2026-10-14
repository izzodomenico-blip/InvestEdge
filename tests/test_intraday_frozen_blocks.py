"""Offline contracts for explicitly sealed, self-contained evidence blocks."""
from __future__ import annotations

import pytest
from test_intraday_snapshots import freeze, service
from test_intraday_store import OPEN, SECOND, event, prepared

from backend.app.intraday.frozen_blocks import FrozenBlocks


def rewrite_block(s,domain,change):
    """Repair the outer block/seal hashes to exercise the inner evidence checks."""
    import hashlib
    import json
    import zlib
    def text(obj):
        return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    block = s.db.execute('SELECT * FROM intraday_frozen_blocks WHERE domain=? ORDER BY ordinal LIMIT 1',(domain,)).fetchone()
    values = json.loads(zlib.decompress(block['body']))
    change(values)
    encoded = text(values).encode()
    body = zlib.compress(encoded,1)
    for table in ('intraday_frozen_blocks','intraday_frozen_seals'):
        s.db.execute(f'DROP TRIGGER trg_{table}_no_update')
    s.db.execute('UPDATE intraday_frozen_blocks SET body=?,input_bytes=?,digest=? WHERE set_id=? AND domain=? AND ordinal=?',
                 (body,len(encoded),hashlib.sha256(body).hexdigest(),block['set_id'],domain,block['ordinal']))
    root,groups = hashlib.sha256(),{}
    for raw in s.db.execute('SELECT domain,ordinal,listing_id,kind,row_count,input_bytes,digest FROM intraday_frozen_blocks WHERE set_id=? ORDER BY domain,ordinal',(block['set_id'],)):
        row = list(raw)
        encoded = text(row).encode()
        framed = len(encoded).to_bytes(8,'big')+encoded
        root.update(framed)
        groups.setdefault(text([row[0],row[2],row[3]]),hashlib.sha256()).update(framed)
    seal = json.loads(s.db.execute('SELECT payload_json FROM intraday_frozen_seals WHERE set_id=?',(block['set_id'],)).fetchone()[0])
    seal.update(root=root.hexdigest(),groups={key:value.hexdigest() for key,value in groups.items()})
    encoded = text(seal)
    s.db.execute('UPDATE intraday_frozen_seals SET payload_json=?,payload_hash=? WHERE set_id=?',
                 (encoded,hashlib.sha256(encoded.encode()).hexdigest(),block['set_id']))
    s.db.commit()


def test_outer_hash_repair_does_not_authorize_changed_timeline_bytes():
    import json
    s,reader,saved = sealed_fixture()
    def change(values):
        row = json.loads(values[0])
        row['received_at_ns'] += 1
        values[0] = json.dumps(row,sort_keys=True,separators=(',',':'))
    rewrite_block(s,'TIMELINE',change)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


def test_market_block_selector_is_bound_to_the_copied_listing():
    s = prepared()
    s.store.persist((event(s,kind='QUOTE'),))
    archive = FrozenBlocks(service(s))
    archive.seal_market(max_disk_bytes=10_485_760,min_free_bytes=1)
    columns = archive.find('MARKET',0)[0]['payload']['columns']
    def change(values):
        values[0][columns.index('listing_id')]=s.listing+100
    rewrite_block(s,'MARKET',change)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now,listing_ids=(s.listing,))


def test_v3_honors_a_smaller_requested_chunk_cap_before_returning_a_handle():
    _,reader,saved = sealed_fixture()
    with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
        reader.open(saved.snapshot_id,max_bytes=64)


def test_invalid_compression_uses_a_fixed_public_error():
    from backend.app.intraday.frozen_blocks import _unpack
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        _unpack(b'invalid',10)


def test_v3_news_links_keep_the_exact_legacy_row_shape():
    from test_intraday_news import article

    from backend.app.intraday.news import NewsStore
    s = prepared()
    reader = service(s)
    reader.register_policy()
    NewsStore(s.archive.provider,clock_ns=lambda:s.clock.now).persist([article()],received_at_ns=s.clock.now)
    saved = freeze(s)
    expected = list(reader.open(saved.snapshot_id).timeline)
    FrozenBlocks(reader).seal_snapshot(saved.snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    assert list(reader.open(saved.snapshot_id).timeline)==expected


def test_sealed_bundle_keeps_all_children_union_and_legacy_digest():
    from test_intraday_research_datasets import _small_bundle
    s,research,saved = _small_bundle()
    before = research.open_bundle(saved.bundle_id)
    expected = list(before.timeline)
    research.seal_bundle(saved.bundle_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    result = research.open_bundle(saved.bundle_id)
    assert result.digest==before.digest and result.manifest==before.manifest and result.report==before.report
    assert list(result.timeline)==expected


def test_large_metadata_is_chunked_without_relaxing_the_input_block_cap():
    s = prepared()
    archive = FrozenBlocks(service(s))
    set_id = archive._begin('MARKET',0,{'padding':'x'*1_100_000},10_485_760,1)
    archive._finish(set_id,10_485_760,1,None)
    header,_ = archive.find('MARKET',0)
    assert header['payload']['padding']=='x'*1_100_000
    assert header['metadata_chunks']>1
    assert max(row[0] for row in s.db.execute('SELECT input_bytes FROM intraday_frozen_child_blocks'))<=126_976


def test_chunked_metadata_respects_the_worker_budget_before_aggregate_parse(monkeypatch):
    import backend.app.intraday.frozen_blocks as frozen
    import backend.app.intraday.snapshots as snapshots
    s = prepared()
    reader = service(s)
    archive = FrozenBlocks(reader)
    set_id = archive._begin('MARKET',0,{'padding':'x'*2_100_000},10_485_760,1)
    archive._finish(set_id,10_485_760,1,None)
    reader._validation_rss_limit = 536_870_912
    monkeypatch.setattr(snapshots,'_peak_rss_bytes',lambda:419_430_400)
    original = frozen.from_json
    def guarded(value,**kwargs):
        assert len(value)<=1_048_576, 'aggregate parsed before worker budget check'
        return original(value,**kwargs)
    monkeypatch.setattr(frozen,'from_json',guarded)
    with pytest.raises(snapshots.SnapshotError,match='RESOURCE_LIMIT'):
        archive.find('MARKET',0)


def test_v3_keeps_large_valid_news_without_reducing_the_legacy_envelope_cap():
    from test_intraday_news import article

    from backend.app.data_providers.alpaca_news import NewsRights
    from backend.app.intraday.news import NewsStore
    s = prepared(max_archive_bytes=268_435_456)
    reader = service(s)
    reader.register_policy()
    news = NewsStore(s.archive.provider,clock_ns=lambda:s.clock.now,
        rights=NewsRights(allow_summary=True,allow_content=True,retention='ARCHIVE_ALLOWED',evidence_hash='b'*64))
    news.persist([article(summary='x'*262_000,content='y'*262_000)],received_at_ns=s.clock.now)
    saved = freeze(s)
    expected = list(reader.open(saved.snapshot_id).timeline)
    FrozenBlocks(reader).seal_snapshot(saved.snapshot_id,max_disk_bytes=268_435_456,min_free_bytes=1)
    actual = reader.open(saved.snapshot_id)
    assert list(actual.timeline)==expected
    assert [row for chunk in actual.timeline.chunks() for row in chunk]==expected


def sealed_fixture():
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),event(s,kind='QUOTE')))
    saved = freeze(s)
    FrozenBlocks(reader).seal_snapshot(saved.snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    return s,reader,saved


@pytest.mark.parametrize('value',[True,False,0,-1,'1',None])
def test_sealed_reader_keeps_strict_subject_ids(value):
    _,reader,_ = sealed_fixture()
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(value)


def test_sealed_reader_rejects_an_extra_unbound_locator():
    s,reader,saved = sealed_fixture()
    row = dict(s.db.execute('SELECT * FROM intraday_frozen_locators LIMIT 1').fetchone())
    row.update(source_id=1000000,block_ordinal=1000000,admission_id=None)
    s.db.execute('DROP TRIGGER trg_intraday_frozen_locators_sealed')
    s.db.execute(f"INSERT INTO intraday_frozen_locators({','.join(row)}) VALUES({','.join('?' for _ in row)})",tuple(row.values()))
    s.db.commit()
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


def test_v3_source_authority_is_distinct_from_the_original_raw_audit():
    s,reader,saved = sealed_fixture()
    expected = list(reader.open(saved.snapshot_id).timeline)
    s.db.execute('DROP TRIGGER trg_intraday_observations_no_update')
    s.db.execute("UPDATE intraday_observations SET payload_json='{}'")
    s.db.commit()
    assert list(reader.open(saved.snapshot_id).timeline)==expected
    assert reader.read(saved.snapshot_id)['timeline']==expected
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        FrozenBlocks(reader).audit_snapshot(saved.snapshot_id)


def test_v3_page_keeps_the_public_pagination_contract():
    _,reader,saved = sealed_fixture()
    timeline = reader.open(saved.snapshot_id).timeline
    page = timeline.page(limit=1)
    assert page['items']==list(timeline)[:1]
    assert page['next_offset']==1 and page['total']==len(timeline)


def test_native_member_validator_matches_the_python_oracle():
    import copy
    native = pytest.importorskip('_investedge_reader_native')
    from backend.app.intraday.frozen_blocks import _unpack
    from backend.app.intraday.snapshots import _decode_evidence
    s,reader,saved = sealed_fixture()
    archive = FrozenBlocks(reader)
    manifest = reader.open(saved.snapshot_id).manifest
    for block in s.db.execute("SELECT body,input_bytes FROM intraday_frozen_blocks WHERE domain='MEMBER'"):
        for record in _unpack(*block):
            before = copy.deepcopy(record)
            assert native.frozen_member(record,archive.scope,manifest['cutoff_ns'],_decode_evidence,
                                        archive._members,manifest)==archive._members(record,manifest)
            assert native.frozen_member(record,archive.scope,manifest['cutoff_ns'],_decode_evidence,
                                        archive._members,manifest,True)==archive._members(record,manifest,True)
            assert record==before


def test_native_frozen_binding_matches_the_canonical_python_output():
    native = pytest.importorskip('_investedge_reader_native')
    from backend.app.intraday.frozen_blocks import _unpack
    s,reader,saved = sealed_fixture()
    archive = FrozenBlocks(reader)
    manifest = reader.open(saved.snapshot_id).manifest
    for block in s.db.execute("SELECT body,input_bytes FROM intraday_frozen_blocks WHERE domain='MEMBER'"):
        for record in _unpack(*block):
            member,rows = archive._members(record,manifest)
            for row in rows:
                result = native.frozen_binding(row,member['payload']['replay'])
                if result is not NotImplemented:
                    assert result==archive._binding_python(row,member['payload']['replay'])


def test_unsealed_tail_uses_admission_id_range_instead_of_scanning_the_prefix():
    s = prepared()
    s.store.persist((event(s,kind='QUOTE'),))
    FrozenBlocks(service(s)).seal_market(max_disk_bytes=10_485_760,min_free_bytes=1)
    statements = []
    s.db.set_trace_callback(statements.append)
    s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now,listing_ids=(s.listing,))
    s.db.set_trace_callback(None)
    tail = next(sql for sql in statements if 'proof.id>' in sql)
    plan = [row[3] for row in s.db.execute('EXPLAIN QUERY PLAN '+tail)]
    assert any('SEARCH proof USING INTEGER PRIMARY KEY (rowid>?)' in step for step in plan),plan


def test_explicit_market_seal_preserves_full_prefix_and_reads_an_unsealed_tail():
    s = prepared()
    s.store.persist((event(s,kind='QUOTE'),event(s,kind='QUOTE',at=OPEN+SECOND)))
    expected = s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now)
    archive = FrozenBlocks(service(s))
    archive.seal_market(max_disk_bytes=10_485_760,min_free_bytes=1)
    assert s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now)==expected
    s.clock.now += SECOND
    s.store.persist((event(s,kind='QUOTE',at=OPEN+2*SECOND),))
    assert len(s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now))==3
    assert s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now-SECOND)==expected


def test_sealed_snapshot_preserves_all_rows_bytes_manifest_and_digest():
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),event(s,kind='QUOTE')))
    saved = freeze(s)
    old = reader.open(saved.snapshot_id)
    expected = list(old.timeline)
    FrozenBlocks(reader).seal_snapshot(saved.snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    result = reader.open(saved.snapshot_id)
    assert result.digest==old.digest and result.manifest==old.manifest and result.report==old.report
    assert list(result.timeline)==expected
    assert [row for chunk in result.timeline.chunks() for row in chunk]==expected
    assert result.evidence_format=='sealed-evidence-blocks-v3'
    assert len(result.evidence_root)==64
    assert result.as_dict()['evidence_root']==result.evidence_root


def test_cancelled_seal_is_atomic_and_leaves_legacy_reader_usable():
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    before = list(reader.open(saved.snapshot_id).timeline)
    with pytest.raises(ValueError,match='CANCEL'):
        FrozenBlocks(reader).seal_snapshot(saved.snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1,
                                            cancelled=lambda stage:stage=='BEFORE_SEAL')
    assert s.db.execute('SELECT COUNT(*) FROM intraday_frozen_sets').fetchone()[0]==0
    assert list(reader.open(saved.snapshot_id).timeline)==before


def test_invalid_staged_timeline_never_publishes_a_seal(monkeypatch):
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    monkeypatch.setattr(FrozenBlocks,'_timeline_text',staticmethod(lambda row:'{}'))
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        FrozenBlocks(reader).seal_snapshot(saved.snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    assert s.db.execute('SELECT COUNT(*) FROM intraday_frozen_seals').fetchone()[0]==0
    assert s.db.execute('SELECT COUNT(*) FROM intraday_frozen_sets').fetchone()[0]==0


def test_earlier_cutoff_recomputes_capture_anchors():
    import json
    import sqlite3
    from types import SimpleNamespace

    from backend.app.intraday.frozen_blocks import BlockTimeline
    from backend.app.intraday.replay import causal_order
    rows = []
    for source_id,available,capture in ((50,30,'a'),(200,10,'a'),(100,10,'b')):
        rows.append({'id':source_id,'table':'intraday_capture_events','available_at_ns':available,
            'received_at_ns':1,'persisted_at_ns':1,'ingest_sequence':source_id,'capture_id':capture,'payload':{},
            'profile_id':'profile','feed':'sip','data_mode':'DEMO','provenance':'SYNTHETIC','replay_grade':'RESEARCH_ONLY'})
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE intraday_frozen_locators(set_id,replay,source_table,source_id,available,received,capture,proof,intake,ingest)')
    for row in rows:
        db.execute('INSERT INTO intraday_frozen_locators VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (7,1,row['table'],row['id'],row['available_at_ns'],1,row['capture_id'],row['id'],row['id'],row['id']))
    archive = SimpleNamespace(db=db,reader=SimpleNamespace(_read_signature=lambda:0),
        _source=lambda set_id,table,source_id:next(dict(row) for row in rows if row['id']==source_id),
        _read_blocks=lambda *args:iter([(0,[json.dumps(row) for row in causal_order(rows,cutoff_ns=30)])]))
    timeline = BlockTimeline(archive,{'id':7,'subject_id':1,'subject_kind':'SNAPSHOT',
        'payload':{'manifest':{'cutoff_ns':30,'carry_at_ns':0,'timeline_count':3}}},{'root':'a'*64},0,10_000,8_388_608)
    assert [row['id'] for row in timeline.iter_rows(cutoff_ns=20)]==[row['id'] for row in causal_order(rows,cutoff_ns=20)]
    db.close()


def test_published_evidence_rejects_new_blocks():
    import sqlite3
    s,_,_ = sealed_fixture()
    row = s.db.execute('SELECT * FROM intraday_frozen_blocks ORDER BY ordinal LIMIT 1').fetchone()
    with pytest.raises(sqlite3.IntegrityError,match='FROZEN_EVIDENCE_IMMUTABLE'):
        s.db.execute('INSERT INTO intraday_frozen_blocks VALUES(?,?,?,?,?,?,?,?,?)',
            (row['set_id'],row['domain'],999_999,row['listing_id'],row['kind'],row['row_count'],row['input_bytes'],row['body'],row['digest']))


def test_python_fallback_preserves_sealed_snapshot_market_and_bundle(monkeypatch):
    from test_intraday_research_datasets import _small_bundle

    import backend.app.intraday.frozen_blocks as blocks
    s,research,bundle = _small_bundle()
    s.store.persist((event(s,kind='QUOTE'),))
    reader = research.snapshots
    archive = FrozenBlocks(reader)
    expected_market = s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now)
    snapshot_id = s.db.execute('SELECT id FROM intraday_dataset_snapshots').fetchone()[0]
    archive.seal_snapshot(snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    research.seal_bundle(bundle.bundle_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    archive.seal_market(max_disk_bytes=10_485_760,min_free_bytes=1)
    expected_snapshot = list(reader.open(snapshot_id).timeline)
    expected_bundle = list(research.open_bundle(bundle.bundle_id).timeline)
    monkeypatch.setattr(blocks,'_NATIVE',None)
    assert s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now)==expected_market
    assert list(reader.open(snapshot_id).timeline)==expected_snapshot
    assert list(research.open_bundle(bundle.bundle_id).timeline)==expected_bundle


def test_v3_reads_are_clock_provider_and_write_free(monkeypatch):
    s,reader,saved = sealed_fixture()
    def forbidden(*args,**kwargs):
        raise AssertionError('READ_SIDE_EFFECT')
    monkeypatch.setattr(reader.archive,'now',forbidden)
    monkeypatch.setattr(reader.store.provider.transport,'request',forbidden)
    before = s.db.total_changes
    statements = []
    s.db.set_trace_callback(statements.append)
    list(reader.open(saved.snapshot_id).timeline)
    s.db.set_trace_callback(None)
    assert s.db.total_changes==before
    assert all(not text.lstrip().upper().startswith(('BEGIN','INSERT','UPDATE','DELETE','CREATE','DROP','REPLACE')) for text in statements)


def test_explicit_window_job_can_request_the_v3_wrapper():
    from test_intraday_store import MINUTE
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':10_485_760,'min_free_bytes':1},
        evidence_blocks=True)
    assert reader.open(saved.snapshot_id).evidence_format=='sealed-evidence-blocks-v3'


def test_native_child_batch_has_a_public_bounded_entry_point():
    native = pytest.importorskip('_investedge_reader_native')
    assert callable(native.frozen_children)
    assert callable(native.frozen_inputs)


def test_windows_rss_checks_reuse_only_api_definitions(monkeypatch):
    import ctypes
    import os

    import backend.app.intraday.snapshots as snapshots
    if os.name!='nt':
        return
    if hasattr(snapshots,'_windows_rss_api'):
        snapshots._windows_rss_api.cache_clear()
    original,calls = ctypes.WinDLL,[]
    def observed(name):
        calls.append(name)
        return original(name)
    monkeypatch.setattr(ctypes,'WinDLL',observed)
    first = snapshots._peak_rss_bytes()
    second = snapshots._peak_rss_bytes()
    assert second>=first>0
    assert calls==['kernel32','psapi']


@pytest.mark.parametrize('column',[0,1,2,3,4,5,6,7,8,9,10,11,12,13])
def test_native_child_batch_rejects_each_unbound_index_column(column):
    import hashlib
    import json

    from test_intraday_research_datasets import _small_bundle

    from backend.app.intraday.frozen_blocks import _decode, _frame, _text
    from backend.app.intraday.snapshots import _decode_evidence
    native = pytest.importorskip('_investedge_reader_native')
    s,research,bundle = _small_bundle()
    research.seal_bundle(bundle.bundle_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    archive = FrozenBlocks(research.snapshots)
    header,seal = archive.find('BUNDLE',bundle.bundle_id)
    child_id = header['payload']['child_documents'][0]['header']['id']
    child = archive._metadata(header['payload']['child_documents'][0])[0]
    raw = s.db.execute("SELECT * FROM intraday_dataset_members WHERE snapshot_id=? AND member_kind='OBSERVATION' LIMIT 1",(child_id,)).fetchone()
    from backend.app.intraday.frozen_blocks import compact_member
    record = [child_id,compact_member(raw)]
    body = _decode(raw)['payload']
    ref = body['reference']
    projection = ref['projection']
    available = projection['available_at_ns']
    actual = [child_id,0,0,-1,ref['table'],ref['id'],ref['payload_hash'],ref['source_hash'],_text(ref),1,
              available,available,projection.get('admission_id'),projection.get('publication_id')]
    actual[column] = 'changed' if isinstance(actual[column],str) else 9_999_999
    hasher = hashlib.sha256()
    _frame(hasher,_text(child['payload']))
    states = {child_id:{'header':child,'hash':hasher,'members':0,'replay':0,'audit':0,'latest':0}}
    before = json.dumps(record,sort_keys=True)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        native.frozen_children([record],[tuple(actual)],archive.scope,states,0,_decode_evidence)
    assert states[child_id]['members']==0
    assert json.dumps(record,sort_keys=True)==before


@pytest.mark.parametrize('native_enabled',[True,False])
def test_member_payload_tamper_is_rejected_even_with_repaired_outer_hashes(monkeypatch,native_enabled):
    import backend.app.intraday.frozen_blocks as blocks
    s,reader,saved = sealed_fixture()
    if not native_enabled:
        monkeypatch.setattr(blocks,'_NATIVE',None)
    def change(values):
        values[0][0]['payload_hash']='0'*64
    rewrite_block(s,'MEMBER',change)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


@pytest.mark.parametrize('field',['publication_kind','snapshot_boolean_id'])
def test_copied_publication_keeps_original_typed_header_constraints(field):
    import copy
    _,reader,saved = sealed_fixture()
    archive = FrozenBlocks(reader)
    evidence = copy.deepcopy(archive.find('SNAPSHOT',saved.snapshot_id)[0]['payload'])
    if field=='publication_kind':
        evidence['publication']['kind']='ADMISSION'
    else:
        evidence['header']['id']=True
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        archive._metadata(evidence)


@pytest.mark.parametrize('role',['SOURCES','CHILDREN','TIMELINE'])
def test_isolated_worker_repeats_full_read_only_validation(tmp_path,role,monkeypatch):
    import sqlite3

    from test_intraday_research_datasets import _small_bundle

    import backend.app.intraday.snapshots as snapshots
    import backend.app.intraday_research.datasets as datasets
    monkeypatch.setattr(snapshots,'_WORKER_PEAK_BOUND',0)
    s,research,bundle = _small_bundle()
    research.seal_bundle(bundle.bundle_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    archive = FrozenBlocks(research.snapshots)
    header,seal = archive.find('BUNDLE',bundle.bundle_id)
    path = tmp_path/'sealed-worker.db'
    copied = sqlite3.connect(path)
    s.db.backup(copied)
    copied.close()
    request = research._worker_request(header,seal,path)
    result = datasets._read_bundle_worker(request,role)
    assert result['network_attempts']==result['changes']==0
    assert result['validated'] is True and result['peak_rss_bytes']>0
    if role=='SOURCES':
        assert result['counts']['replay']==len(bundle.timeline)
    if role=='TIMELINE':
        assert result['timeline_count']==len(bundle.timeline)


def test_three_process_coordinator_keeps_full_counts_and_aggregates_memory(tmp_path,monkeypatch):
    import sqlite3

    from test_intraday_research_datasets import _small_bundle

    import backend.app.intraday.snapshots as snapshots
    pytest.importorskip('_investedge_reader_native')
    s,research,bundle = _small_bundle()
    research.seal_bundle(bundle.bundle_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    path = tmp_path/'coordinator.db'
    db = sqlite3.connect(path)
    s.db.backup(db)
    db.row_factory = sqlite3.Row
    research.db = research.snapshots.connection = db
    archive = FrozenBlocks(research.snapshots)
    header,seal = archive.find('BUNDLE',bundle.bundle_id)
    peaks = []
    original = snapshots._record_worker_peaks
    def record(values):
        peaks.extend(values)
        original(values)
    monkeypatch.setattr(snapshots,'_record_worker_peaks',record)
    before = snapshots._peak_rss_bytes()
    result = research._run_bundle_workers(research._worker_request(header,seal,path))
    assert result['replay']==len(bundle.timeline)
    assert snapshots._peak_rss_bytes()>=before and db.total_changes==0
    assert len(peaks)==3 and all(peak>0 for peak in peaks)
    assert sum(peaks) <= snapshots._WORKER_PEAK_BOUND
    db.close()


@pytest.mark.parametrize('failure',['SOURCES','CHILDREN','TIMELINE','count','bool_count'])
def test_bundle_coordinator_requires_every_pass_and_the_same_timeline_count(failure,monkeypatch):
    import json
    import subprocess
    from types import SimpleNamespace

    from test_intraday_research_datasets import _small_bundle
    _,research,_ = _small_bundle()
    roles = []
    def run(command,**kwargs):
        role = command[-1]
        roles.append(role)
        value = {'validated':True,'network_attempts':0,'changes':0,'peak_rss_bytes':1}
        if role=='SOURCES':
            value['counts'] = {'replay':1}
        if role=='TIMELINE':
            value['timeline_count'] = 2 if failure=='count' else True if failure=='bool_count' else 1
        if role==failure:
            value = {'validated':False,'error':'SNAPSHOT_INPUT_MISSING'}
        return SimpleNamespace(returncode=0,stdout=json.dumps(value))
    monkeypatch.setattr(subprocess,'run',run)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        research._run_bundle_workers({})
    assert set(roles)=={'SOURCES','CHILDREN','TIMELINE'}


def test_db_fence_includes_reading_the_wrapper_header(monkeypatch):
    s,reader,saved = sealed_fixture()
    original = FrozenBlocks.find
    def changed(self,*args):
        result = original(self,*args)
        self.db.execute('CREATE TABLE unrelated_epoch_change(value INTEGER)')
        return result
    monkeypatch.setattr(FrozenBlocks,'find',changed)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


def test_cancel_during_copy_validation_rolls_back_before_publication():
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    def cancelled(stage):
        return stage=='DURING_VALIDATION' and s.db.execute('SELECT COUNT(*) FROM intraday_frozen_sets').fetchone()[0]>0
    with pytest.raises(ValueError,match='CANCEL'):
        FrozenBlocks(reader).seal_snapshot(saved.snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1,cancelled=cancelled)
    assert s.db.execute('SELECT COUNT(*) FROM intraday_frozen_sets').fetchone()[0]==0


@pytest.mark.parametrize('replay',[True,False])
def test_native_complex_classification_matches_python_and_keeps_audits_private(replay):
    import copy
    import hashlib
    import json

    from backend.app.intraday.frozen_blocks import _text
    from backend.app.intraday.snapshots import _decode_evidence
    native = pytest.importorskip('_investedge_reader_native')
    _,reader,saved = sealed_fixture()
    archive = FrozenBlocks(reader)
    header,_ = archive.find('SNAPSHOT',saved.snapshot_id)
    record = next(copy.deepcopy(record) for _,records in archive._raw_blocks(header['id'],'MEMBER')
                  for record in records if json.loads(record[1][0][0]).get('kind')=='ADMISSION')
    source = json.loads(record[1][0][0])
    payload = json.loads(record[1][0][1])
    payload['metadata_kind']='COLLECTOR_HANDSHAKE'
    record[1][0][1] = _text(payload)
    source['payload_hash']=hashlib.sha256(record[1][0][1].encode()).hexdigest()
    record[1][0][0] = _text(source)
    body = json.loads(record[0]['payload_json'])
    body['replay']=replay
    body['reference'].update(source_hash=hashlib.sha256(record[1][0][0].encode()).hexdigest(),payload_hash=source['payload_hash'])
    record[0]['payload_json'] = _text(body)
    record[0]['payload_hash'] = hashlib.sha256(record[0]['payload_json'].encode()).hexdigest()
    member,rows = archive._members(record,header['payload']['manifest'])
    expected = archive._complex(rows[0])
    result = native.frozen_inputs([record],archive.scope,header['payload']['manifest'],0,True,None,None,
                                  _decode_evidence,archive._members,archive._binding_python)
    assert bool(result[1][0][10])==expected
    assert len(result[6])==int(replay and expected)


def test_sealed_market_does_not_depend_on_the_callers_row_factory():
    s = prepared()
    s.store.persist((event(s,kind='QUOTE'),))
    expected = s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now)
    FrozenBlocks(service(s)).seal_market(max_disk_bytes=10_485_760,min_free_bytes=1)
    original = s.db.row_factory
    class SlowMapping:
        def keys(self):
            raise AssertionError('CALLER_MAPPING_USED')
    s.db.row_factory = lambda cursor,values:SlowMapping()
    try:
        assert s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now)==expected
    finally:
        s.db.row_factory = original


@pytest.mark.parametrize('native_enabled',[True,False])
@pytest.mark.parametrize('field',['id','received_at_ns','persisted_at_ns','ingest_sequence','ingest_run_id'])
def test_copied_audit_source_keeps_strict_sql_integer_types(field,native_enabled):
    import copy
    import hashlib
    import json

    from backend.app.intraday.frozen_blocks import _text
    from backend.app.intraday.snapshots import _decode_evidence
    _,reader,saved = sealed_fixture()
    archive = FrozenBlocks(reader)
    header,_ = archive.find('SNAPSHOT',saved.snapshot_id)
    record = next(copy.deepcopy(record) for _,records in archive._raw_blocks(header['id'],'MEMBER')
                  for record in records if json.loads(record[1][0][0]).get('id')==1)
    source = json.loads(record[1][0][0])
    source[field]=True
    record[1][0][0] = _text(source)
    body = json.loads(record[0]['payload_json'])
    body['replay']=False
    body['reference']['source_hash']=hashlib.sha256(record[1][0][0].encode()).hexdigest()
    record[0]['payload_json'] = _text(body)
    record[0]['payload_hash'] = hashlib.sha256(record[0]['payload_json'].encode()).hexdigest()
    with pytest.raises(ValueError):
        if native_enabled:
            native = pytest.importorskip('_investedge_reader_native')
            native.frozen_member(record,archive.scope,header['payload']['manifest']['cutoff_ns'],_decode_evidence,archive._members,header['payload']['manifest'])
        else:
            archive._members(record,header['payload']['manifest'])


def test_typed_member_boolean_cannot_alias_a_sql_integer_key():
    s,reader,saved = sealed_fixture()
    def change(records):
        record = next(record for record in records if record[0].get('observation_id')==1)
        record[0]['observation_id']=True
    rewrite_block(s,'MEMBER',change)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


def test_legacy_bundle_retains_raw_authority_when_a_child_has_a_v3_wrapper():
    from test_intraday_research_datasets import _small_bundle
    s,research,bundle = _small_bundle()
    reader = research.snapshots
    snapshot_id = s.db.execute('SELECT id FROM intraday_dataset_snapshots').fetchone()[0]
    FrozenBlocks(reader).seal_snapshot(snapshot_id,max_disk_bytes=10_485_760,min_free_bytes=1)
    s.db.execute('DROP TRIGGER trg_intraday_observations_no_update')
    s.db.execute("UPDATE intraday_observations SET payload_json='{}'")
    s.db.commit()
    assert list(reader.open(snapshot_id).timeline)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        research.open_bundle(bundle.bundle_id)


@pytest.mark.parametrize('selection',['intraday_observations','intraday_capture_events','mixed'])
def test_native_batch_prepares_the_exact_fresh_source_bindings(selection):
    import copy
    import json

    from backend.app.intraday.snapshots import _decode_evidence
    native = pytest.importorskip('_investedge_reader_native')
    _,reader,saved = sealed_fixture()
    archive = FrozenBlocks(reader)
    header,_ = archive.find('SNAPSHOT',saved.snapshot_id)
    records = [copy.deepcopy(record) for _,block in archive._raw_blocks(header['id'],'MEMBER')
               for record in block if json.loads(record[1][0][0]).get('kind') in {'BAR','QUOTE','ADMISSION'}]
    if selection!='mixed':
        records = [record for record in records if json.loads(record[0]['payload_json'])['reference']['table']==selection]
    assert records
    before = copy.deepcopy(records)
    result = native.frozen_inputs(records,archive.scope,header['payload']['manifest'],0,True,None,None,
                                  _decode_evidence,archive._members,archive._binding_python)
    assert len(result)==8
    locators,facts = result[:2]
    if selection=='mixed':
        assert result[7] is None
    else:
        expected_parameters = [value for locator,fact in zip(locators,facts,strict=True)
                               for value in (fact[1],fact[2],locator[5],fact[8],fact[9],fact[4])]
        expected_union = {fact[1]:(locator[11],fact[3]) for locator,fact in zip(locators,facts,strict=True)}
        assert result[7]==(selection,expected_parameters,expected_union)
    assert records==before


@pytest.mark.parametrize('change',['body','metadata','seal'])
def test_inventory_proof_cannot_hide_changes_between_domains(change):
    s,reader,saved = sealed_fixture()
    archive = FrozenBlocks(reader)
    header,seal = archive.find('SNAPSHOT',saved.snapshot_id)
    if change!='seal':
        s.db.execute('DROP TRIGGER trg_intraday_frozen_blocks_no_update')
    with archive.validation_scope():
        list(archive._read_blocks(header,seal,'MEMBER'))
        if change=='seal':
            seal['root'] = '0'*64
        else:
            if change=='body':
                s.db.execute("UPDATE intraday_frozen_blocks SET body=? WHERE set_id=? AND domain='TIMELINE'",
                             (b'invalid-compressed-block',header['id']))
            else:
                s.db.execute("UPDATE intraday_frozen_blocks SET row_count=row_count+1 WHERE set_id=? AND domain='TIMELINE'",
                             (header['id'],))
            s.db.commit()
        with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
            list(archive._read_blocks(header,seal,'TIMELINE'))


def test_inventory_validation_is_repeated_after_the_public_handle_returns(monkeypatch):
    _,reader,saved = sealed_fixture()
    original = FrozenBlocks._inventory
    calls = []
    def observed(self,set_id):
        calls.append(set_id)
        return original(self,set_id)
    monkeypatch.setattr(FrozenBlocks,'_inventory',observed)
    result = reader.open(saved.snapshot_id)
    before_replay = len(calls)
    assert before_replay>0
    list(result.timeline.chunks())
    assert len(calls)>before_replay
    before_open = len(calls)
    reader.open(saved.snapshot_id)
    assert len(calls)>before_open


def test_inventory_scope_preserves_the_original_seal_document_size_limit():
    import hashlib
    import json

    s,reader,saved = sealed_fixture()
    raw = s.db.execute('SELECT * FROM intraday_frozen_seals').fetchone()
    seal = json.loads(raw['payload_json'])
    seal['padding'] = ''
    empty = json.dumps(seal,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    seal['padding'] = 'x'*(1_048_576-len(empty.encode()))
    text = json.dumps(seal,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    assert len(text.encode())==1_048_576
    s.db.execute('DROP TRIGGER trg_intraday_frozen_seals_no_update')
    s.db.execute('UPDATE intraday_frozen_seals SET payload_json=?,payload_hash=? WHERE set_id=?',
                 (text,hashlib.sha256(text.encode()).hexdigest(),raw['set_id']))
    s.db.commit()
    result = reader.open(saved.snapshot_id)
    assert sum(map(len,result.timeline.chunks()))==result.manifest['timeline_count']


def test_market_header_cannot_alias_a_source_column_after_outer_hash_repair():
    import hashlib
    import json

    from backend.app.intraday.contracts import canonical_json

    s,reader,_ = sealed_fixture()
    FrozenBlocks(reader).seal_market(max_disk_bytes=10_485_760,min_free_bytes=1)
    raw = s.db.execute("SELECT * FROM intraday_frozen_sets WHERE subject_kind='MARKET'").fetchone()
    header = json.loads(raw['payload_json'])
    header['columns'][header['columns'].index('logical_key')] = 'provider'
    text = canonical_json(header)
    header_hash = hashlib.sha256(text.encode()).hexdigest()
    seal = json.loads(s.db.execute('SELECT payload_json FROM intraday_frozen_seals WHERE set_id=?',(raw['id'],)).fetchone()[0])
    seal['header_hash'] = header_hash
    seal_text = canonical_json(seal)
    for table in ('intraday_frozen_sets','intraday_frozen_seals'):
        s.db.execute(f'DROP TRIGGER trg_{table}_no_update')
    s.db.execute('UPDATE intraday_frozen_sets SET payload_json=?,payload_hash=? WHERE id=?',(text,header_hash,raw['id']))
    s.db.execute('UPDATE intraday_frozen_seals SET payload_json=?,payload_hash=? WHERE set_id=?',
                 (seal_text,hashlib.sha256(seal_text.encode()).hexdigest(),raw['id']))
    s.db.commit()
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now,listing_ids=(s.listing,))
