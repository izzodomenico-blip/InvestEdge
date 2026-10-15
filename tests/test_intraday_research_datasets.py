from __future__ import annotations

import importlib
import json
import sqlite3

import pytest
from test_intraday_snapshots import service
from test_intraday_store import MINUTE, OPEN, event, prepared


def _bundle_query_fixture():
    from types import SimpleNamespace

    from backend.app.intraday_research.datasets import DatasetService

    db = sqlite3.connect(':memory:')
    db.executescript('''CREATE TABLE intraday_research_bundle_children(bundle_id,snapshot_id);
        CREATE TABLE intraday_dataset_members(id INTEGER PRIMARY KEY,snapshot_id,member_kind,
            observation_id,news_version_id,news_link_id,event_version_id,identity_version_id,
            calendar_version_id,universe_snapshot_id,capture_event_id,payload_json,
            UNIQUE(snapshot_id,news_link_id));
        CREATE TABLE intraday_news_links(id INTEGER PRIMARY KEY,news_version_id);
        CREATE INDEX idx_intraday_news_links_news ON intraday_news_links(news_version_id,id);
        CREATE INDEX idx_intraday_dataset_member_dependencies ON intraday_dataset_members(snapshot_id)
            WHERE json_array_length(payload_json,'$.dependencies')>0;''')
    db.executemany('INSERT INTO intraday_research_bundle_children VALUES(?,?)', [(1,1),(1,2),(2,3)])
    db.executemany('INSERT INTO intraday_news_links VALUES(?,?)', [(1,9),(2,10),(3,9)])
    def ref(table, source_id, available):
        return {'table':table,'id':source_id,'projection':{'available_at_ns':available}}
    references = [ref('intraday_observations',index,20) for index in range(1,1001)]
    references += [ref('intraday_news_links',1,30),ref('intraday_news_links',2,10)]
    for snapshot_id in (1,2):
        for reference in references:
            changed = reference | {'projection':{'available_at_ns':10 if snapshot_id==2 else 20}}
            body = {'reference':changed,'replay':True,'dependencies':[ref('intraday_capture_events',1,20)]}
            link_id = reference['id'] if reference['table']=='intraday_news_links' else None
            db.execute('INSERT INTO intraday_dataset_members(snapshot_id,member_kind,observation_id,news_link_id,payload_json) VALUES(?,?,?,?,?)',
                       (snapshot_id,'NEWS_LINK' if link_id else 'OBSERVATION',None if link_id else reference['id'],link_id,json.dumps(body)))
    db.execute('INSERT INTO intraday_dataset_members(snapshot_id,member_kind,news_link_id,payload_json) VALUES(?,?,?,?)',
        (3,'NEWS_LINK',3,json.dumps({'reference':ref('intraday_news_links',3,1),'replay':True,'dependencies':[]})))
    calls = []
    def extract(text, path):
        value = json.loads(text)
        if path=='$.projection.available_at_ns':
            calls.append(value['table'])
        for key in path[2:].split('.'):
            if not isinstance(value,dict) or key not in value:
                return None
            value = value[key]
        return json.dumps(value,separators=(',',':')) if isinstance(value,(dict,list)) else value
    db.create_function('json_extract',2,extract,deterministic=True)
    reader = SimpleNamespace(connection=db,_hydrate=lambda reference:reference.copy())
    return db,DatasetService(reader),calls


def test_source_scope_reads_current_secret_values_without_allocating_named_pairs(monkeypatch):
    from backend.app.intraday.snapshots import _ValidatedSources
    s = prepared()
    reader = service(s)
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    def forbidden():
        raise AssertionError('NAMED_SECRET_PAIRS_IN_HOT_FENCE')
    monkeypatch.setattr(reader,'_secret_fields',forbidden)
    scope.check(reader)
    assert reader._read_signature()==scope.signature
    # The same settings object can be mutated through its mapping despite
    # the frozen dataclass; every fence must still read the current value.
    vars(reader.archive.settings)['alpaca_api_secret_key']='offline-sensitive-fixture'
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        scope.check(reader)
    assert reader._read_signature()!=scope.signature


def test_bundle_count_deduplicates_typed_identity_without_ranking_projections():
    db,research,calls = _bundle_query_fixture()
    try:
        before = db.total_changes
        assert research._bundle_count(1)==1003
        assert not calls
        assert db.total_changes==before
    finally:
        db.close()


def test_bundle_count_never_decodes_primary_member_reference_text():
    db,research,_ = _bundle_query_fixture()
    def extract(text,path):
        assert path!='$.reference', 'PRIMARY_REFERENCE_DECODE_FOR_TYPED_COUNT'
        value = json.loads(text)
        for key in path[2:].split('.'):
            if not isinstance(value,dict) or key not in value:
                return None
            value = value[key]
        return json.dumps(value,separators=(',',':')) if isinstance(value,(dict,list)) else value
    db.create_function('json_extract',2,extract,deterministic=True)
    try:
        before = db.total_changes
        assert research._bundle_count(1)==1003
        assert research._bundle_count(2)==1
        assert db.total_changes==before
    finally:
        db.close()


def test_replay_member_keys_are_read_from_partial_index_without_payload_table_fetch():
    s = prepared()
    cases = (('OBSERVATION','observation_id'),('NEWS','news_version_id'),('NEWS_LINK','news_link_id'),
             ('EVENT','event_version_id'),('IDENTITY','identity_version_id'),('CALENDAR','calendar_version_id'),
             ('UNIVERSE','universe_snapshot_id'),('CAPTURE_EVENT','capture_event_id'))
    source_id = 'CASE member_kind '+' '.join(f"WHEN '{kind}' THEN {column}" for kind,column in cases)+' END'
    query = f'''SELECT member_kind,{source_id} FROM intraday_dataset_members
        WHERE snapshot_id=? AND json_extract(payload_json,'$.replay')=1'''
    plan = s.db.execute('EXPLAIN QUERY PLAN '+query,(1,)).fetchall()
    assert any('idx_intraday_dataset_member_replay_keys' in row[3] for row in plan)
    rootpage = s.db.execute("SELECT rootpage FROM sqlite_master WHERE name='intraday_dataset_members'").fetchone()[0]
    operations = s.db.execute('EXPLAIN '+query,(1,)).fetchall()
    table_cursors = {row[2] for row in operations if row[1]=='OpenRead' and row[3]==rootpage}
    assert not any(row[1]=='Column' and row[2] in table_cursors for row in operations)
    assert not any(row[1]=='Function' and row[5].startswith('json_') for row in operations)


def test_bundle_reference_ranking_sorts_typed_identity_and_keeps_exact_v1_ties():
    from backend.app.intraday_research.datasets import _BUNDLE_REFS

    db,research,_ = _bundle_query_fixture()
    refs = []
    for source_id, available in enumerate((0,9,10,99,2**63-2,2**63-1,None),20000):
        for extra in (True,1,False,0,'é😀\\\n'):
            projection = {'tie':extra}
            if available is not None:
                projection['available_at_ns'] = available
            reference = {'table':'intraday_observations','id':source_id,'projection':projection}
            refs.append(reference)
            db.execute('INSERT INTO intraday_dataset_members(snapshot_id,member_kind,observation_id,payload_json) VALUES(?,?,?,?)',
                (1,'OBSERVATION',source_id,json.dumps({'reference':reference,'replay':True,'dependencies':[]})))
    query = _BUNDLE_REFS+''' SELECT reference_json FROM refs
        ORDER BY json_extract(reference_json,'$.table'),json_extract(reference_json,'$.id')'''
    try:
        # Both queries also order the final output by identity. The ranking
        # sorter itself must compare only the two identity keys, not full refs.
        plan = db.execute('EXPLAIN '+query,{'snapshot':1}).fetchall()
        sort_keys = [row[5] for row in plan if row[1]=='SorterOpen']
        assert sort_keys and all(value.startswith('k(2,') for value in sort_keys)
        actual = {json.loads(row[0])['id']:row[0] for row in db.execute(query,{'snapshot':1})
                  if json.loads(row[0])['id']>=20000}
        # JSON1 reference strings use compact separators and retain input key
        # order. Compare exact text so True/1 and Unicode ties stay distinct.
        expected = {}
        for ref in refs:
            text = json.dumps(ref,separators=(',',':'),ensure_ascii=True)
            rank = (ref['projection'].get('available_at_ns',2**63-1),text)
            if ref['id'] not in expected or rank<expected[ref['id']]:
                expected[ref['id']] = rank
        assert actual=={key:value[1] for key,value in expected.items()}
        assert research._bundle_count(1)==1010
    finally:
        db.close()


@pytest.mark.parametrize('bundle', [False, True])
def test_reference_dependency_scan_uses_partial_index_and_preserves_all_nonempty_arrays(bundle):
    from backend.app.intraday.snapshots import _REFS_SQL
    from backend.app.intraday_research.datasets import _CHILD_REFS

    db,_,_ = _bundle_query_fixture()
    sql = _CHILD_REFS if bundle else _REFS_SQL
    relation = 'child_refs' if bundle else 'refs'
    try:
        db.executemany('INSERT INTO intraday_dataset_members(snapshot_id,member_kind,observation_id,payload_json) VALUES(?,?,?,?)',
            [(1,'OBSERVATION',10000+i,json.dumps({'reference':{'table':'intraday_observations','id':10000+i},
                            'replay':True,'dependencies':[]})) for i in range(50)])
        query = sql+f' SELECT reference_json FROM {relation}'
        before = db.total_changes
        plan = db.execute('EXPLAIN QUERY PLAN '+query,{'snapshot':1}).fetchall()
        assert any('idx_intraday_dataset_member_dependencies' in row[3] for row in plan)
        rows = [json.loads(row[0]) for row in db.execute(query,{'snapshot':1})]
        assert sum(row['table']=='intraday_capture_events' for row in rows)==1002*(2 if bundle else 1)
        assert sum(row['id']>=10000 for row in rows)==50
        assert db.total_changes==before
    finally:
        db.close()


def test_bundle_news_links_rank_only_matching_news_and_keep_earliest_reference():
    db,research,calls = _bundle_query_fixture()
    try:
        before = db.total_changes
        assert research._links(1,9)==[{'id':1,'projection':{'available_at_ns':10}}]
        assert calls and set(calls)=={'intraday_news_links'}
        assert db.total_changes==before
    finally:
        db.close()


def test_bundle_news_links_do_not_decode_unrelated_main_references():
    db,research,_ = _bundle_query_fixture()
    def extract(text,path):
        value = json.loads(text)
        if path=='$.reference' and value['reference']['table']!='intraday_news_links':
            raise AssertionError('UNRELATED_MEMBER_REFERENCE_DECODE')
        for key in path[2:].split('.'):
            if not isinstance(value,dict) or key not in value:
                return None
            value = value[key]
        return json.dumps(value,separators=(',',':')) if isinstance(value,(dict,list)) else value
    db.create_function('json_extract',2,extract,deterministic=True)
    try:
        before = db.total_changes
        assert research._links(1,9)==[{'id':1,'projection':{'available_at_ns':10}}]
        assert db.total_changes==before
    finally:
        db.close()


def test_bundle_news_links_include_dependency_references_and_exclude_audit_members():
    db,research,_ = _bundle_query_fixture()
    def body(available,replay):
        return json.dumps({'reference':{'table':'intraday_observations','id':9000,
            'projection':{'available_at_ns':available}},'replay':replay,
            'dependencies':[{'table':'intraday_news_links','id':3,'projection':{'available_at_ns':available}}]})
    db.executemany('INSERT INTO intraday_dataset_members(snapshot_id,member_kind,observation_id,payload_json) VALUES(?,?,?,?)',
                   [(1,'OBSERVATION',9000,body(15,True)),(2,'OBSERVATION',9000,body(5,True)),(1,'OBSERVATION',9000,body(1,False))])
    try:
        before = db.total_changes
        assert research._links(1,9)==[{'id':1,'projection':{'available_at_ns':10}},
                                     {'id':3,'projection':{'available_at_ns':5}}]
        assert research._links(1,10)==[{'id':2,'projection':{'available_at_ns':10}}]
        assert research._links(2,9)==[{'id':3,'projection':{'available_at_ns':1}}]
        assert db.total_changes==before
    finally:
        db.close()


def test_bundle_staging_liveness_reads_covering_metadata_without_envelope_payload():
    from backend.app.intraday.snapshots import _StagedTimeline

    s = prepared()
    stage = _StagedTimeline.from_frozen(service(s),{'cutoff_ns':s.clock.now},
        {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2,'max_chunk_bytes':8388608},[])
    try:
        plan = s.db.execute(f'''EXPLAIN QUERY PLAN SELECT capture_id,MAX(received_at_ns) FROM {stage.stage}
            WHERE kind IN ('BAR','QUOTE','NEWS') AND available_at_ns<? GROUP BY capture_id,kind='NEWS' ''',
            (s.clock.now,)).fetchall()
        assert any('COVERING INDEX' in row[3] for row in plan)
    finally:
        stage.close()


def test_research_bundle_contract_is_pure_and_requires_frozen_child_references():
    datasets = importlib.import_module("backend.app.intraday_research.datasets")
    with pytest.raises(ValueError):
        datasets.DatasetBundle(children=(), namespace=(), max_disk_bytes=0, min_free_bytes=0)


def test_window_freeze_uses_versioned_selection_and_refuses_replay_before_carry():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s, at=OPEN - MINUTE), event(s)))
    reader = service(s)
    saved = reader.freeze_window(start_at_ns=OPEN, end_at_ns=OPEN + 3 * MINUTE,
        cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={},
        resources={'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2})
    result = reader.open(saved.snapshot_id)
    assert result.manifest['version'] == 'intraday-dataset-v2'
    assert result.manifest['selection'] == 'window-dependency-closure-v2'
    assert result.manifest['carry_at_ns'] == OPEN - 1
    with pytest.raises(ValueError, match='SNAPSHOT_CUTOFF'):
        reader.replay(saved.snapshot_id, cutoff_ns=OPEN - 2)


def test_bundle_overlap_is_counted_once_and_global_quality_is_recomputed(monkeypatch):
    datasets = importlib.import_module('backend.app.intraday_research.datasets')
    from backend.app.database import RESEARCH_INDEX_SCHEMA
    from backend.app.intraday_research.contracts import ResearchNamespace

    s = prepared()
    s.db.executescript(RESEARCH_INDEX_SCHEMA)
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2}
    children = []
    for start in (OPEN, OPEN + 1):
        saved = reader.freeze_window(start_at_ns=start, end_at_ns=OPEN + 3 * MINUTE,
            cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={}, resources=resources)
        frozen = reader.open(saved.snapshot_id)
        children.append(datasets.DatasetChild(saved.snapshot_id, saved.digest, start,
            OPEN + 3 * MINUTE, s.clock.now, frozen.known_at_ns, frozen.publication_id, frozen.publication_hash))
    request = datasets.DatasetBundle(tuple(children), ResearchNamespace(*reader.open(children[0].snapshot_id).manifest['namespace']), **resources)
    research = datasets.DatasetService(reader)
    def forbidden(row):
        raise AssertionError('REVALIDATING_ALREADY_FROZEN_REFERENCE_DURING_BUNDLE_STAGING')
    monkeypatch.setattr(reader, '_reference', forbidden)
    result = research.freeze_bundle(request)
    before = s.db.total_changes
    reopened = research.open_bundle(result.bundle_id)
    rows = list(reopened.timeline)
    assert len(rows) == len({(row['table'],row['id']) for row in rows})
    assert reopened.report['metrics']['sessions'] == 1
    assert reopened.report['outcome'] != 'READY'
    assert 'SESSIONS_INSUFFICIENT' in reopened.report['reasons']
    assert s.db.total_changes == before
    with pytest.raises(ValueError,match='SNAPSHOT_CUTOFF'):
        list(reopened.timeline.iter_rows(cutoff_ns=OPEN-2))
    with pytest.raises(sqlite3.IntegrityError, match='RESEARCH_APPEND_ONLY'):
        s.db.execute('DELETE FROM intraday_research_dataset_bundles WHERE id=?', (result.bundle_id,))


def test_bundle_reference_identity_distinguishes_boolean_and_integer_projection():
    from backend.app.intraday.snapshots import _StagedTimeline

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2,'max_chunk_bytes':8388608}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    frozen = reader.open(saved.snapshot_id)
    stage = _StagedTimeline.from_frozen(reader,frozen.manifest,resources,[])
    try:
        row = next(row for row in frozen.timeline if row['table']=='intraday_observations')
        ref = reader._reference(row)
        ref['projection']['capture_ingest_sequence'] = 1
        stage._frozen_batch(frozen,[ref])
        changed = ref | {'projection':ref['projection'] | {'capture_ingest_sequence':True}}
        with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
            stage._frozen_batch(frozen,[changed])
    finally:
        stage.close()


def test_bundle_quality_period_can_span_the_preregistered_multi_year_experiment():
    from test_intraday_quality import manifest

    from backend.app.intraday.quality import validate_manifest
    body = manifest()
    body.update(version='intraday-bundle-quality-v1',end_at_ns=OPEN+700*86400*1_000_000_000,
                cutoff_ns=OPEN+700*86400*1_000_000_000,carry_at_ns=OPEN-1)
    validate_manifest(body)


@pytest.mark.parametrize('cache_bytes', [67108864, 32768])
def test_child_source_validation_is_shared_only_in_a_bounded_read_scope(monkeypatch, cache_bytes):
    from collections import Counter

    import backend.app.intraday.snapshots as snapshot_module
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild, DatasetService

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2,
                 'max_cache_bytes': cache_bytes}
    children = []
    for start in (OPEN, OPEN + 1):
        saved = reader.freeze_window(start_at_ns=start, end_at_ns=OPEN + 3 * MINUTE,
            cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={}, resources=resources)
        frozen = reader.open(saved.snapshot_id)
        children.append(DatasetChild(saved.snapshot_id, saved.digest, start, OPEN + 3 * MINUTE,
            s.clock.now, frozen.known_at_ns, frozen.publication_id, frozen.publication_hash))
    request = DatasetBundle(tuple(children), ResearchNamespace(*frozen.manifest['namespace']),
        max_disk_bytes=resources['max_disk_bytes'], min_free_bytes=resources['min_free_bytes'])
    calls = Counter()
    size_headers = Counter()
    original_encoder = snapshot_module._envelope_bytes
    def counted_encoder(value,**kwargs):
        if (value.get('table') in snapshot_module._SOURCE_TABLES and 'id' in value
            and 'payload' not in value and 'payload_json' not in value and 'projection' not in value):
            size_headers[(value['table'],value['id'])] += 1
        return original_encoder(value,**kwargs)
    monkeypatch.setattr(snapshot_module, '_envelope_bytes', counted_encoder)
    original = reader._decode_source
    def counted(table, source_id, **kwargs):
        calls[(table, source_id)] += 1
        return original(table, source_id, **kwargs)
    monkeypatch.setattr(reader, '_decode_source', counted)
    before = s.db.total_changes
    datasets = DatasetService(reader)._children(request)
    assert s.db.total_changes == before
    assert max(calls.values()) == (1 if cache_bytes > 32768 else 2)
    assert max(size_headers.values()) == (1 if cache_bytes > 32768 else 2)
    first_counts = calls.copy()
    DatasetService(reader)._children(request)
    assert calls == Counter({key: 2 * value for key, value in first_counts.items()})
    first = list(datasets[0].timeline)
    assert all(not hasattr(row, '_byte_bound') for row in first)
    first[0]['payload'].clear()
    assert list(datasets[0].timeline)[0]['payload']


def test_identical_child_references_reuse_completed_validation_but_check_each_child_closure(monkeypatch):
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    raw_queries = []
    closures = []
    original = reader._closure_batch
    completed_original = reader._completed_closure_batch
    def closure(snapshot_id,rows):
        closures.extend(row['id'] for row in rows if row['table']=='intraday_observations')
        return original(snapshot_id,rows)
    monkeypatch.setattr(reader,'_closure_batch',closure)
    def completed_closure(snapshot_id,rows):
        closures.extend(row['id'] for row in rows if row['table']=='intraday_observations')
        return completed_original(snapshot_id,rows)
    monkeypatch.setattr(reader,'_completed_closure_batch',completed_closure)
    before = s.db.total_changes
    try:
        first = reader.open(saved.snapshot_id,_source_scope=scope)
        s.db.set_trace_callback(raw_queries.append)
        second = reader.open(saved.snapshot_id,_source_scope=scope)
        s.db.set_trace_callback(None)
        assert second.digest==first.digest and len(second.timeline)==len(first.timeline)
        assert closures==[1,1]
        assert not any('SELECT * FROM intraday_observations WHERE id IN' in query for query in raw_queries)
        assert s.db.total_changes==before
    finally:
        s.db.set_trace_callback(None)
        scope.close()


def test_distinct_children_reuse_member_canonical_proof_but_keep_hash_and_closure(monkeypatch):
    import hashlib

    from test_intraday_snapshots import freeze

    import backend.app.intraday.snapshots as snapshots

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    first,second = freeze(s),freeze(s)
    raw = s.db.execute('SELECT payload_json FROM intraday_dataset_members '
        'WHERE snapshot_id=? AND observation_id=1',(second.snapshot_id,)).fetchone()[0]
    body = json.loads(raw)
    scope = snapshots._ValidatedSources(reader,67108864,reader._read_signature())
    try:
        reader.open(first.snapshot_id,_source_scope=scope)
        walks,hashes,closures = [],[],[]
        original_walk,original_hash = snapshots._canonical_evidence_bytes,hashlib.sha256
        original_closure = reader._closure_batch
        original_completed = reader._completed_closure_batch
        def walk(value,raw_utf8):
            if value==body:
                walks.append(value)
            return original_walk(value,raw_utf8)
        def hashed(value=b'',*args,**kwargs):
            if value==raw.encode():
                hashes.append(True)
            return original_hash(value,*args,**kwargs)
        def closure(snapshot_id,rows):
            closures.extend(snapshot_id for row in rows if row['table']=='intraday_observations')
            return original_closure(snapshot_id,rows)
        monkeypatch.setattr(snapshots,'_canonical_evidence_bytes',walk)
        monkeypatch.setattr(hashlib,'sha256',hashed)
        monkeypatch.setattr(reader,'_closure_batch',closure)
        def completed_closure(snapshot_id,rows):
            closures.extend(snapshot_id for row in rows if row['table']=='intraday_observations')
            return original_completed(snapshot_id,rows)
        monkeypatch.setattr(reader,'_completed_closure_batch',completed_closure)
        actual = reader.open(second.snapshot_id,_source_scope=scope)
        assert actual.digest==first.digest and actual.snapshot_id!=first.snapshot_id
        assert not walks
        assert hashes and closures==[second.snapshot_id]
    finally:
        scope.close()


def test_child_member_validation_reads_only_used_columns_and_decodes_only_payload(monkeypatch):
    from test_intraday_snapshots import freeze

    import backend.app.intraday.snapshots as snapshots

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    decoded,queries = [],[]
    original = snapshots._decode_evidence
    def decode(raw,**kwargs):
        if 'reference' in json.loads(raw['payload_json']):
            decoded.append(set(raw))
        return original(raw,**kwargs)
    monkeypatch.setattr(snapshots,'_decode_evidence',decode)
    s.db.set_trace_callback(queries.append)
    try:
        result = reader.open(saved.snapshot_id)
        assert result.digest==saved.digest
        assert decoded and all(fields=={'payload_json','payload_hash'} for fields in decoded)
        assert not any('SELECT * FROM intraday_dataset_members WHERE snapshot_id=' in query for query in queries)
    finally:
        s.db.set_trace_callback(None)


@pytest.mark.parametrize('variant', ['whitespace','extra','dependencies','audit','projection',
                                    'pending','discard','eviction','small_budget','bad_hash'])
def test_member_canonical_proof_falls_back_on_any_unattested_body_and_still_checks_hash(monkeypatch,variant):
    import hashlib

    from test_intraday_snapshots import freeze

    import backend.app.intraday.snapshots as snapshots
    from backend.app.intraday.contracts import canonical_json

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    raw = dict(s.db.execute('SELECT payload_json,payload_hash FROM intraday_dataset_members '
        'WHERE snapshot_id=? AND observation_id=1',(saved.snapshot_id,)).fetchone())
    scope = snapshots._ValidatedSources(reader,32768 if variant=='small_budget' else 67108864,reader._read_signature())
    try:
        reader.open(saved.snapshot_id,_source_scope=scope)
        body = json.loads(raw['payload_json'])
        ref = body['reference']
        if variant=='extra':
            body['extra'] = 1
        elif variant=='dependencies':
            body['dependencies'] = [ref.copy()]
        elif variant=='audit':
            body['replay'] = False
        elif variant=='projection':
            ref['projection']['capture_ingest_sequence'] = True
        elif variant in {'pending','discard'}:
            page = scope.pages[(ref['table'],ref['id']//scope._PAGE_IDS)]
            page[2][ref['id']%scope._PAGE_IDS] |= 128
            if variant=='discard':
                scope.finish_child(valid=False)
        elif variant=='eviction':
            scope.pages.clear()
        raw['payload_json'] = canonical_json(body)
        if variant=='whitespace':
            raw['payload_json'] = ' '+raw['payload_json']
        raw['payload_hash'] = hashlib.sha256(raw['payload_json'].encode()).hexdigest()
        if variant=='bad_hash':
            raw['payload_hash'] = '0'*64
        walks = []
        original = snapshots._canonical_evidence_bytes
        def walk(value,raw_utf8):
            walks.append(True)
            return original(value,raw_utf8)
        monkeypatch.setattr(snapshots,'_canonical_evidence_bytes',walk)
        if variant in {'whitespace','bad_hash'}:
            with pytest.raises(ValueError,match='METADATA_INVALID'):
                snapshots._decode_evidence(raw,_member_scope=scope)
        else:
            assert snapshots._decode_evidence(raw,_member_scope=scope)['payload']==body
        assert bool(walks)==(variant!='bad_hash')
    finally:
        scope.close()


def test_completed_reference_proof_requires_successful_child_and_exact_cutoff_and_local_receipt():
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    row = next(row for row in reader.open(saved.snapshot_id).timeline if row['table']=='intraday_observations')
    ref = reader._reference(row)
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    try:
        decoded = reader._hydrate_batch([ref],_source_scope=scope)[0]
        scope.complete(ref,decoded)
        assert scope.completed(ref,s.clock.now,8388608) is None
        scope.finish_child(valid=False)
        assert scope.completed(ref,s.clock.now,8388608) is None
        scope.complete(ref,decoded)
        scope.finish_child(valid=True)
        completed = scope.completed(ref,s.clock.now,8388608)
        assert completed is not None
        with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
            scope.completed(ref,row['available_at_ns']-1,8388608)
        with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
            scope.completed(ref,s.clock.now,1)
        with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
            reader._closure_batch(saved.snapshot_id+1,[completed])
        for changed in (ref | {'source_hash':'f'*64},ref | {'payload_hash':'f'*64},
                        ref | {'projection':ref['projection'] | {'available_at_ns':row['available_at_ns']+1}}):
            assert scope.completed(changed,s.clock.now,8388608) is None
    finally:
        scope.close()


def test_cached_receipt_and_observation_in_same_batch_still_validate_typed_binding():
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    rows = [row for row in reader.open(saved.snapshot_id).timeline
            if row['table']=='intraday_observations' or row.get('kind')=='ADMISSION']
    refs = [reader._reference(row) for row in rows]
    for ref,row in zip(refs,rows,strict=True):
        ref['projection']['available_at_ns'] = row['available_at_ns']
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    try:
        decoded = reader._hydrate_batch(refs,_source_scope=scope)
        reader._closure_batch(saved.snapshot_id,decoded)
        for ref,row in zip(refs,decoded,strict=True):
            scope.complete(ref,row)
        scope.finish_child(valid=True)
        completed = [scope.completed(ref,s.clock.now,8388608) for ref in refs]
        assert len(completed)==2 and all(row is not None for row in completed)
        reader._closure_batch(saved.snapshot_id,completed)
    finally:
        scope.close()


def test_completed_child_checks_current_receipt_membership_without_rehydrating_the_edge(monkeypatch):
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    closure = reader._closure_batch
    def fresh_closure(snapshot_id, rows):
        assert all(row['payload'] for row in rows), 'COMPLETED_EDGE_REHYDRATED'
        return closure(snapshot_id,rows)
    monkeypatch.setattr(reader,'_closure_batch',fresh_closure)
    try:
        baseline = reader.open(saved.snapshot_id,_source_scope=scope)
        queries = []
        s.db.set_trace_callback(queries.append)
        again = reader.open(saved.snapshot_id,_source_scope=scope)
        assert again.digest==baseline.digest and list(again.timeline)==list(baseline.timeline)
        assert any('SELECT capture_event_id FROM intraday_dataset_members' in sql for sql in queries)
    finally:
        s.db.set_trace_callback(None)
        scope.close()


@pytest.mark.parametrize('corruption',['missing_receipt','receipt_body'])
def test_completed_child_still_rejects_corrupt_receipt_in_another_child(corruption):
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    options = {'start_at_ns':OPEN,'end_at_ns':OPEN+3*MINUTE,'cutoff_ns':s.clock.now,
        'listing_ids':[s.listing],'benchmarks':{},'resources':{'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}}
    first,second = reader.freeze_window(**options),reader.freeze_window(**options)
    member = s.db.execute("SELECT m.id FROM intraday_dataset_members m JOIN intraday_capture_events r "
        "ON r.id=m.capture_event_id WHERE m.snapshot_id=? AND r.kind='ADMISSION'",(second.snapshot_id,)).fetchone()[0]
    for trigger in s.db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='intraday_dataset_members'").fetchall():
        s.db.execute('DROP TRIGGER "'+trigger[0].replace('"','""')+'"')
    if corruption=='missing_receipt':
        s.db.execute('DELETE FROM intraday_dataset_members WHERE id=?',(member,))
    else:
        s.db.execute("UPDATE intraday_dataset_members SET payload_json='{}' WHERE id=?",(member,))
    s.db.commit()
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    try:
        reader.open(first.snapshot_id,_source_scope=scope)
        with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING|METADATA_INVALID'):
            reader.open(second.snapshot_id,_source_scope=scope)
    finally:
        scope.close()


def test_completed_receipt_keeps_exact_raw_availability_when_projection_omits_it():
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    row = next(row for row in reader.open(saved.snapshot_id).timeline if row.get('kind')=='ADMISSION')
    ref = reader._reference(row)
    assert 'available_at_ns' not in ref['projection']
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    try:
        decoded = reader._hydrate_batch([ref],_source_scope=scope)[0]
        scope.complete(ref,decoded)
        scope.finish_child(valid=True)
        completed = scope.completed(ref,row['available_at_ns'],8388608)
        assert completed is not None
        with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
            scope.completed(ref,row['available_at_ns']-1,8388608)
    finally:
        scope.close()


def test_failed_child_open_discards_pending_proof_after_unexpected_exception(monkeypatch):
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    row = next(row for row in reader.open(saved.snapshot_id).timeline if row['table']=='intraday_observations')
    ref = reader._reference(row)
    scope = _ValidatedSources(reader,67108864,reader._read_signature())
    complete = scope.complete
    def stop_after_complete(reference,item):
        complete(reference,item)
        if item['table']=='intraday_observations':
            raise RuntimeError('OFFLINE_VALIDATION_INTERRUPTED')
    monkeypatch.setattr(scope,'complete',stop_after_complete)
    try:
        with pytest.raises(RuntimeError,match='OFFLINE_VALIDATION_INTERRUPTED'):
            reader.open(saved.snapshot_id,_source_scope=scope)
        assert scope.completed(ref,s.clock.now,8388608) is None
        monkeypatch.setattr(scope,'complete',complete)
        reader.open(saved.snapshot_id,_source_scope=scope)
        assert scope.completed(ref,s.clock.now,8388608) is not None
    finally:
        scope.close()


def test_failed_handle_construction_does_not_promote_child_proof(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    row = next(row for row in reader.open(saved.snapshot_id).timeline if row['table']=='intraday_observations')
    ref = reader._reference(row)
    scope = snapshots._ValidatedSources(reader,67108864,reader._read_signature())
    def stop(*args,**kwargs):
        raise RuntimeError('OFFLINE_HANDLE_INTERRUPTED')
    monkeypatch.setattr(snapshots.FrozenTimeline,'__init__',stop)
    try:
        with pytest.raises(RuntimeError,match='OFFLINE_HANDLE_INTERRUPTED'):
            reader.open(saved.snapshot_id,_source_scope=scope)
        assert scope.completed(ref,s.clock.now,8388608) is None
    finally:
        scope.close()


@pytest.mark.parametrize('stop', ['cancel', 'budget'])
def test_bundle_staging_checks_every_processed_occurrence_including_duplicates(monkeypatch, stop):
    from types import SimpleNamespace

    from backend.app.intraday.snapshots import SnapshotError, _StagedTimeline

    s = prepared()
    reader = service(s)
    s.store.persist((event(s),))
    row = s.store.read_as_of('BAR', cutoff_ns=s.clock.now)[0]
    row['table'] = 'intraday_observations'
    reference = reader._reference(row)
    monkeypatch.setattr(reader, '_reference', lambda item: reference)
    processed = 0

    def rows():
        nonlocal processed
        for _ in range(2100):
            processed += 1
            yield row

    def cancelled(phase):
        return phase == 'DURING_BUNDLE_STAGING' and processed >= 1000

    def budget(stage):
        if processed >= 1000:
            raise SnapshotError('RESOURCE_LIMIT')

    if stop == 'budget':
        monkeypatch.setattr(_StagedTimeline, 'check_budget', budget)
    kwargs = {'cancelled': cancelled} if stop == 'cancel' else {}
    with pytest.raises(ValueError, match='CANCELLED' if stop == 'cancel' else 'RESOURCE_LIMIT'):
        _StagedTimeline.from_frozen(reader, {}, {'max_chunk_bytes': 8388608,
                                   'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2},
                                   [SimpleNamespace(timeline=rows())], **kwargs)
    assert processed <= 1000
    assert s.db.execute("SELECT COUNT(*) FROM sqlite_temp_master WHERE name LIKE 'timeline_stage_%'").fetchone()[0] == 0


@pytest.mark.parametrize('changed_hash', ['uppercase', 'different', 'payload'])
def test_cached_source_still_rejects_each_wrong_exact_reference(changed_hash):
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    s.store.persist((event(s),))
    row = reader._decode_source('intraday_observations', 1)[1]
    row['table'] = 'intraday_observations'
    ref = reader._reference(row)
    scope = _ValidatedSources(reader, 67108864, reader._read_signature())
    try:
        reader._hydrate_batch([ref], _source_scope=scope)
        bad = dict(ref)
        if changed_hash == 'payload':
            bad['payload_hash'] = 'f' * 64
        else:
            bad['source_hash'] = ref['source_hash'].upper() if changed_hash == 'uppercase' else 'f' * 64
        with pytest.raises(ValueError, match='SNAPSHOT_INPUT_MISSING'):
            reader._hydrate_batch([bad], _source_scope=scope)
    finally:
        scope.close()


@pytest.mark.parametrize('change', ['database', 'inventory', 'schema'])
def test_source_scope_fences_transient_writes_inventory_and_schema(change):
    from dataclasses import replace

    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    scope = _ValidatedSources(reader, 67108864, reader._read_signature())
    if change == 'database':
        s.db.execute('CREATE TEMP TABLE scope_probe(value INTEGER)')
        s.db.execute('INSERT INTO scope_probe VALUES(1)')
        s.db.execute('DELETE FROM scope_probe')
    elif change == 'inventory':
        import uuid
        reader.archive.settings = replace(reader.archive.settings, alpaca_api_secret_key=uuid.uuid4().hex)
    else:
        s.db.execute('CREATE TABLE scope_probe(value INTEGER)')
    try:
        with pytest.raises(ValueError, match='SNAPSHOT_INPUT_MISSING'):
            scope.check(reader, full=True)
    finally:
        scope.close()
    assert scope.closed and not scope.pages


def test_source_scope_lru_is_global_and_high_ids_allocate_only_one_fixed_page():
    from backend.app.intraday.snapshots import _ValidatedSources

    s = prepared()
    reader = service(s)
    scope = _ValidatedSources(reader, 170000, reader._read_signature())
    table = 'intraday_observations'
    try:
        scope.remember(reader, table, 1, 'a' * 64)
        scope.remember(reader, table, 1025, 'b' * 64)
        assert scope.get(reader, table, 1) == 'a' * 64
        scope.remember(reader, table, 2**62, 'c' * 64)
        assert scope.get(reader, table, 1025) is None
        assert scope.get(reader, table, 1) == 'a' * 64
        assert scope.get(reader, 'intraday_capture_events', 1) is None
        assert len(scope.pages) * scope._PAGE_CHARGE <= scope.budget
    finally:
        scope.close()


def test_bundle_cancel_during_staging_rolls_back_before_raw_or_seal():
    from backend.app.database import RESEARCH_INDEX_SCHEMA
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild, DatasetService

    s = prepared()
    s.db.executescript(RESEARCH_INDEX_SCHEMA)
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes': 4 * 1024**3, 'min_free_bytes': 512 * 1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN, end_at_ns=OPEN + 3 * MINUTE,
        cutoff_ns=s.clock.now, listing_ids=[s.listing], benchmarks={}, resources=resources)
    frozen = reader.open(saved.snapshot_id)
    child = DatasetChild(saved.snapshot_id, saved.digest, OPEN, OPEN + 3 * MINUTE,
        s.clock.now, frozen.known_at_ns, frozen.publication_id, frozen.publication_hash)
    request = DatasetBundle((child,), ResearchNamespace(*frozen.manifest['namespace']), **resources)
    with pytest.raises(ValueError, match='CANCELLED'):
        DatasetService(reader).freeze_bundle(request, cancelled=lambda phase: phase == 'DURING_BUNDLE_STAGING')
    assert not s.db.in_transaction
    for table in ('intraday_research_dataset_bundles', 'intraday_research_bundle_children',
                  'intraday_research_bundle_chunks', 'intraday_research_bundle_seals'):
        assert s.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    assert s.db.execute("SELECT COUNT(*) FROM sqlite_temp_master WHERE name LIKE 'timeline_stage_%'").fetchone()[0] == 0


def test_window_job_enforces_declared_rss_budget_before_publication():
    s = prepared()
    reader = service(s)
    reader.register_policy()
    with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
        reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
            listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,
            'min_free_bytes':512*1024**2,'max_rss_bytes':1})
    assert s.db.execute('SELECT COUNT(*) FROM intraday_dataset_snapshots').fetchone()[0] == 0


def test_window_keeps_superseded_checkpoint_still_referenced_by_handshake():
    from test_intraday_collector import boot
    from test_intraday_replay import live_capture
    from test_intraday_store import SECOND
    s = live_capture()
    old = next(row for row in s.events.read_as_of(cutoff_ns=s.clock.now,revisions=True)
               if row['payload'].get('version')=='utp-status-checkpoint-v1')
    ids = boot(s)
    new = next(row for row in s.events.read_as_of(cutoff_ns=s.clock.now,revisions=True) if row['id'] in ids)
    assert new['supersedes_id'] == old['id']
    reader = service(s)
    reader.register_policy()
    start = s.clock.now+1
    s.clock.now = start
    expected = s.store.replay_as_of(cutoff_ns=start)['capture']
    assert expected['state']=='LIVE'
    end = start+MINUTE
    s.clock.now = end+10*SECOND
    saved = reader.freeze_window(start_at_ns=start,end_at_ns=end,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    frozen = reader.open(saved.snapshot_id)
    assert {old['id'],new['id']} <= {row['id'] for row in frozen.timeline if row['table']=='intraday_event_versions'}
    assert reader.replay(saved.snapshot_id,cutoff_ns=start)['capture']==expected


def test_window_carry_does_not_use_future_quote_revision_and_is_immutable_after_append():
    from test_intraday_store import SECOND
    s = prepared()
    reader = service(s)
    s.clock.now = OPEN-SECOND
    reader.register_policy()
    s.store.persist((event(s,kind='QUOTE',at=OPEN-SECOND),))
    expected = s.store.replay_as_of(cutoff_ns=OPEN)['observations']['QUOTE']
    s.clock.now = OPEN+SECOND
    s.store.persist((event(s,kind='QUOTE',at=OPEN-SECOND,change={'bp':99}),))
    s.clock.now = OPEN+3*MINUTE+10*SECOND
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    assert reader.replay(saved.snapshot_id,cutoff_ns=OPEN)['observations']['QUOTE']==expected
    before = list(reader.open(saved.snapshot_id).timeline)
    s.clock.now += SECOND
    s.store.persist((event(s,kind='QUOTE',at=OPEN-SECOND,change={'bp':98}),))
    assert list(reader.open(saved.snapshot_id).timeline)==before


def test_window_accepts_full_registered_resource_profile_and_binds_chunk_limits():
    from dataclasses import asdict

    from backend.app.intraday_research.contracts import ResourceLimits
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist(tuple(event(s,at=OPEN+i*MINUTE) for i in range(10)))
    resources = asdict(ResourceLimits(max_disk_bytes=4*1024**3,min_free_bytes=512*1024**2,
                                     max_chunk_occurrences=3))
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+10*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    handle = reader.open(saved.snapshot_id)
    assert handle.manifest['resources']==resources
    assert all(len(chunk)<=3 for chunk in handle.timeline.chunks())


@pytest.mark.parametrize('key,value',[('max_chunk_occurrences',True),('max_chunk_bytes',-1),
    ('max_cache_bytes',67_108_865),('max_listings',31),('window_sessions',6),('history_sessions',31)])
def test_window_manifest_rejects_invalid_frozen_resource_limits(key,value):
    from backend.app.intraday.quality import validate_manifest
    s = prepared()
    reader = service(s)
    reader.register_policy()
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    manifest = reader.open(saved.snapshot_id).manifest
    manifest['resources'][key] = value
    with pytest.raises(ValueError,match='DATASET_INVALID'):
        validate_manifest(manifest)


def _small_bundle():
    from backend.app.database import RESEARCH_INDEX_SCHEMA
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild, DatasetService
    s = prepared()
    s.db.executescript(RESEARCH_INDEX_SCHEMA)
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2}
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=OPEN+3*MINUTE,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources=resources)
    frozen = reader.open(saved.snapshot_id)
    child = DatasetChild(saved.snapshot_id,saved.digest,OPEN,OPEN+3*MINUTE,s.clock.now,
        frozen.known_at_ns,frozen.publication_id,frozen.publication_hash)
    research = DatasetService(reader)
    result = research.freeze_bundle(DatasetBundle((child,),ResearchNamespace(*frozen.manifest['namespace']),**resources))
    return s,research,result


def test_candidate_bundle_path_is_read_only_and_blocks_missing_context():
    from backend.app.intraday_research.contracts import CandidateConfig, ResearchNamespace
    from backend.app.intraday_research.quote_units import QuoteUnits
    from backend.app.intraday_research.registry import Registry
    s,research,bundle = _small_bundle()
    registry = Registry(s.db)
    ns = ResearchNamespace(*bundle.manifest['namespace'])
    calendar = next(r for r in bundle.timeline if r['table']=='intraday_calendar_versions')
    before = s.db.total_changes
    result = research.research_signal(bundle.bundle_id,config=CandidateConfig('TREND_PULLBACK',15,'TECH_ONLY','R0'),
        listing_id=s.listing,session_date=calendar['session_date'],cutoff_ns=bundle.manifest['cutoff_ns'],
        registry=registry,quote_units=QuoteUnits(registry,ns))
    assert not result['signal']['admitted'] and s.db.total_changes==before
    assert research.open_bundle(bundle.bundle_id).digest==bundle.digest


def test_attested_bundle_has_its_own_fingerprint_and_preserves_old_dataset_digest():
    from intraday_research_fixtures import quote_terms_fixture

    from backend.app.intraday_research.contracts import ResearchNamespace
    s,research,saved = _small_bundle()
    namespace = ResearchNamespace(*saved.manifest['namespace'])
    registry,refs,_,_ = quote_terms_fixture(s.db,namespace=namespace,available=saved.manifest['cutoff_ns'])
    before = s.db.total_changes
    wrapped = research.bind_attestations(saved.bundle_id,references=refs,registry=registry,
                                         cutoff_ns=saved.manifest['cutoff_ns'])
    assert wrapped['bundle_digest']==saved.digest and wrapped['fingerprint']!=saved.digest
    assert len(wrapped['attestations'])==2
    assert research.open_bundle(saved.bundle_id).digest==saved.digest
    assert s.db.total_changes==before


def test_attested_bundle_rejects_proof_imported_after_its_cutoff():
    from intraday_research_fixtures import quote_terms_fixture

    from backend.app.intraday_research.contracts import ResearchNamespace
    s,research,saved = _small_bundle()
    registry,refs,_,_ = quote_terms_fixture(s.db,namespace=ResearchNamespace(*saved.manifest['namespace']),
                                          available=saved.manifest['cutoff_ns']+1)
    with pytest.raises(ValueError):
        research.bind_attestations(saved.bundle_id,references=refs,registry=registry,
                                   cutoff_ns=saved.manifest['cutoff_ns'])


def test_bundle_rejects_current_sensitive_inventory_matching_public_bundle_digest():
    from dataclasses import replace

    s,research,result = _small_bundle()
    reader = research.snapshots
    reader.archive.settings = replace(reader.archive.settings,alpaca_api_secret_key=result.digest)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        research.open_bundle(result.bundle_id)


def test_bundle_fences_mutation_during_public_timeline_handle_construction(monkeypatch):
    import backend.app.intraday_research.datasets as datasets

    s,research,result = _small_bundle()
    s.db.execute('DROP TRIGGER trg_intraday_observations_no_update')
    original = datasets.FrozenTimeline.__init__
    def changed(self,reader,snapshot_id,*args,**kwargs):
        if 'refs_sql' in kwargs:
            s.db.execute('UPDATE intraday_observations SET payload_json=?',('{"corrupt":true}',))
        return original(self,reader,snapshot_id,*args,**kwargs)
    monkeypatch.setattr(datasets.FrozenTimeline,'__init__',changed)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        research.open_bundle(result.bundle_id)


@pytest.mark.parametrize('column',['recorded_at_ns','feed'])
def test_bundle_seal_is_bound_to_header_scope_and_clock(column):
    s,research,bundle = _small_bundle()
    s.db.execute('DROP TRIGGER trg_intraday_research_bundle_seals_no_update')
    s.db.commit()
    s.db.execute('PRAGMA foreign_keys=OFF')
    value = s.clock.now+1 if column=='recorded_at_ns' else 'iex'
    s.db.execute(f'UPDATE intraday_research_bundle_seals SET {column}=?',(value,))
    s.db.commit()
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        research.open_bundle(bundle.bundle_id)


@pytest.mark.parametrize('rollback',[False,True])
def test_bundle_publication_uses_clock_after_raw_and_rejects_rollback(rollback):
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild
    s,research,existing = _small_bundle()
    snapshot_id = s.db.execute('SELECT snapshot_id FROM intraday_research_bundle_children LIMIT 1').fetchone()[0]
    child = research.snapshots.open(snapshot_id)
    request = DatasetBundle((DatasetChild(snapshot_id,child.digest,child.manifest['start_at_ns'],
        child.manifest['end_at_ns'],child.manifest['cutoff_ns'],child.known_at_ns,child.publication_id,child.publication_hash),),
        ResearchNamespace(*child.manifest['namespace']),max_disk_bytes=4*1024**3,min_free_bytes=512*1024**2)
    start = s.clock.now
    def clock_change(stage):
        if stage=='BEFORE_READ':
            s.clock.now = start+1_000_000_000
        elif stage=='BEFORE_PUBLICATION' and rollback:
            s.clock.now = start-1
        return False
    if rollback:
        with pytest.raises(ValueError,match='SNAPSHOT_NOT_PIT'):
            research.freeze_bundle(request,cancelled=clock_change)
    else:
        result = research.freeze_bundle(request,cancelled=clock_change)
        assert result.known_at_ns==s.clock.now and result.known_at_ns>start


def test_window_session_cap_uses_complete_preopen_calendar_replacement():
    from test_intraday_identity import ns

    from backend.app.intraday.calendar import CalendarService
    s = prepared()
    reader = service(s)
    s.clock.now = OPEN-10_000_000_000
    reader.register_policy()
    dates = ['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-19']
    calendars = CalendarService(s.archive)
    rows = [{'date':day,'open':'09:30','close':'16:00'} for day in dates]
    calendars.record(rows,start=dates[0],end=dates[-1],received_at_ns=s.clock.now)
    s.clock.now += 1_000_000_000
    calendars.record([row for row in rows if row['date']!='2026-10-14'],start=dates[0],end=dates[-1],received_at_ns=s.clock.now)
    end = ns('2026-10-19T20:00:00Z')
    s.clock.now = end+10_000_000_000
    old = reader.freeze_dataset(start_at_ns=OPEN,end_at_ns=end,cutoff_ns=s.clock.now,
                               listing_ids=[s.listing],benchmarks={})
    saved = reader.freeze_window(start_at_ns=OPEN,end_at_ns=end,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    assert reader.open(old.snapshot_id).report['metrics']['sessions']==5
    assert reader.open(saved.snapshot_id).manifest['window_session_count']==5


def test_intraday_window_keeps_thirty_complete_previous_sessions():
    from datetime import date, timedelta

    from backend.app.intraday.calendar import CalendarService, session_as_of
    s = prepared()
    reader = service(s)
    s.clock.now = OPEN-10_000_000_000
    reader.register_policy()
    dates,day = [],date(2026,10,12)
    while len(dates)<31:
        if day.weekday()<5:
            dates.append(day.isoformat())
        day += timedelta(days=1)
    CalendarService(s.archive).record([{'date':day,'open':'09:30','close':'16:00'} for day in dates],
        start=dates[0],end=dates[-1],received_at_ns=s.clock.now)
    current = session_as_of(s.db,dates[-1],s.clock.now,profile_id=s.store.profile.profile_id,
        data_mode='REAL',provenance='CAPTURED',replay_grade='STRICT_PIT')
    start,end = current.open_at_ns+MINUTE,current.close_at_ns
    s.clock.now = end+10_000_000_000
    saved = reader.freeze_window(start_at_ns=start,end_at_ns=end,cutoff_ns=s.clock.now,
        listing_ids=[s.listing],benchmarks={},resources={'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2})
    assert reader.open(saved.snapshot_id).manifest['support_start_at_ns']==OPEN
