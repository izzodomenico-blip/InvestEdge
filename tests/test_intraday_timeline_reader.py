from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import contextmanager

import pytest
from test_intraday_snapshots import freeze, service
from test_intraday_store import OPEN, SECOND, event, prepared

from backend.app.intraday.contracts import canonical_json


def test_frozen_validation_and_iteration_bound_source_lookup_queries():
    s = prepared()
    service(s).register_policy()
    s.store.persist(tuple(event(s, at=OPEN + number * SECOND) for number in range(200)))
    saved = freeze(s)
    queries = []
    s.db.set_trace_callback(queries.append)
    try:
        dataset = service(s).open(saved.snapshot_id)
        rows = list(dataset.timeline)
    finally:
        s.db.set_trace_callback(None)
    assert len(rows) == len(dataset.timeline)
    sources = [sql for sql in queries if 'SELECT * FROM intraday_' in sql and 'WHERE id=' in sql]
    assert len(sources) < 100


@pytest.mark.parametrize('text', ['{ "a":1}', '{"a":1,"a":1}', '{"b":1,"a":1}',
                                  '{"a":"\\u00e9"}', '{"a":-0}', '{"a":1e0}', '{"a":NaN}'])
def test_fast_decoder_rejects_noncanonical_payload_even_with_matching_hash(text):
    from backend.app.intraday.snapshots import _decode_evidence

    with pytest.raises(ValueError, match='METADATA_INVALID'):
        _decode_evidence({'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()})


def test_snapshot_validation_and_page_do_not_compute_replay_projections(monkeypatch):
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    reader = service(s)
    expected = reader.read(saved.snapshot_id)

    def forbidden(*args, **kwargs):
        raise AssertionError("PROJECTION_NOT_ALLOWED_IN_TIMELINE_READER")

    monkeypatch.setattr("backend.app.intraday.snapshots.replay_frozen", forbidden)
    validated = reader.open(saved.snapshot_id)
    assert validated.manifest == expected["manifest"]
    assert list(validated.timeline) == expected["timeline"]
    page = validated.timeline.page(offset=0, limit=1, input_type="BAR")
    assert len(page["items"]) == 1
    assert page["items"][0]["kind"] == "BAR"
    assert page["total"] == 1


def test_digest_framing_consumes_generator_incrementally():
    from backend.app.intraday.snapshots import _digest

    expected = hashlib.sha256()

    class Bodies:
        def __iter__(self):
            for number in range(100):
                yield {"ordinal": number}

        def __length_hint__(self):
            raise AssertionError("FULL_ARCHIVE_MATERIALIZATION")

    for body in ({"manifest": 1}, *({"ordinal": n} for n in range(100))):
        text = canonical_json(body).encode()
        expected.update(len(text).to_bytes(8, "big"))
        expected.update(text)
    assert _digest({"manifest": 1}, Bodies()) == expected.hexdigest()


def test_timeline_only_preserves_v1_order_without_building_observations(monkeypatch):
    s = prepared()
    s.store.persist((event(s, at=OPEN - 60 * SECOND), event(s)))
    expected = s.store.replay_as_of(cutoff_ns=s.clock.now)["timeline"]
    monkeypatch.setattr("backend.app.intraday.replay.select_versions",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("PROJECTION")))
    result = s.store.replay_as_of(cutoff_ns=s.clock.now, timeline_only=True)
    assert result["timeline"] == expected
    assert set(result) == {"version", "cutoff_ns", "namespace", "timeline"}


def test_corrupt_member_outside_requested_page_is_rejected_before_output():
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s), event(s, at=OPEN - 60 * SECOND)))
    saved = freeze(s)
    s.db.execute("DROP TRIGGER trg_intraday_dataset_members_no_update")
    s.db.execute("UPDATE intraday_dataset_members SET payload_hash=? WHERE id=(SELECT MAX(id) FROM intraday_dataset_members)", ("d" * 64,))
    s.db.commit()
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        service(s).open(saved.snapshot_id).timeline.page(offset=0, limit=1, input_type="BAR")


def test_snapshot_api_uses_validated_handle_and_bounded_page(monkeypatch):
    from backend.app.api import intraday_routes

    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)

    @contextmanager
    def local_service(params):
        yield s.store

    monkeypatch.setattr(intraday_routes.handlers, "services", local_service)
    monkeypatch.setattr(type(service(s)), "read", lambda *a, **k: (_ for _ in ()).throw(AssertionError("FULL_READ")))
    before = s.db.total_changes
    result = intraday_routes.read_snapshot(saved.snapshot_id, s.store.profile.profile_id,
        data_mode=s.store.data_mode, provenance=s.store.provenance, replay_grade=s.store.replay_grade,
        input_type="BAR", offset=0, limit=1)
    assert result["total"] == 1 and len(result["inputs"]) == 1
    assert s.db.total_changes == before


def test_live_timeline_iteration_does_not_use_materialized_legacy_readers(monkeypatch):
    s = prepared()
    s.store.persist((event(s),))
    expected = s.store.replay_as_of(cutoff_ns=s.clock.now, timeline_only=True)["timeline"]
    monkeypatch.setattr(s.store, "read_as_of", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LEGACY_LIST")))
    assert list(s.store.iter_timeline(cutoff_ns=s.clock.now)) == expected


def test_snapshot_page_next_offset_tracks_byte_capped_emitted_items(monkeypatch):
    from backend.app.api import intraday_routes

    s = prepared()

    @contextmanager
    def local_service(params):
        yield s.store

    class Timeline:
        def page(self, **kwargs):
            return {'items': [{'id': n, 'payload': {'text': 'a' * 400_000}} for n in range(6)],
                    'total': 6, 'offset': 0, 'limit': 6, 'next_offset': None}

    monkeypatch.setattr(intraday_routes.handlers, 'services', local_service)
    monkeypatch.setattr(intraday_routes.handlers, 'frozen', lambda *a: {'timeline': Timeline()})
    result = intraday_routes.read_snapshot(1, s.store.profile.profile_id,
        data_mode=s.store.data_mode, provenance=s.store.provenance, replay_grade=s.store.replay_grade,
        input_type='ALL', offset=0, limit=6)
    assert 0 < len(result['inputs']) < result['total']
    assert result['next_offset'] == len(result['inputs'])


@pytest.mark.parametrize('durable', [None, True, 'invalid', -1])
def test_invalid_receipt_is_rejected_before_first_timeline_output(durable):
    s = prepared()
    s.store.persist((event(s),))
    raw = s.db.execute("SELECT id,payload_json FROM intraday_capture_events WHERE kind='ADMISSION'").fetchone()
    payload = json.loads(raw['payload_json'])
    payload['durable_at_ns'] = durable
    text = canonical_json(payload)
    s.db.execute('DROP TRIGGER trg_intraday_capture_events_no_update')
    s.db.execute('UPDATE intraday_capture_events SET payload_json=?,payload_hash=? WHERE id=?',
                 (text, hashlib.sha256(text.encode()).hexdigest(), raw['id']))
    s.db.commit()
    with pytest.raises(ValueError):
        next(s.store.iter_timeline(cutoff_ns=s.clock.now))


def test_future_durable_receipt_still_validates_its_source_binding():
    s = prepared()
    s.store.persist((event(s),))
    raw = s.db.execute("SELECT id,payload_json FROM intraday_capture_events WHERE kind='ADMISSION'").fetchone()
    payload = json.loads(raw['payload_json'])
    payload.update(durable_at_ns=s.clock.now+1,payload_hash='f'*64)
    text = canonical_json(payload)
    s.db.execute('DROP TRIGGER trg_intraday_capture_events_no_update')
    s.db.execute('UPDATE intraday_capture_events SET payload_json=?,payload_hash=? WHERE id=?',
                 (text,hashlib.sha256(text.encode()).hexdigest(),raw['id']))
    s.db.commit()
    with pytest.raises(ValueError,match='OBSERVATION_INVALID'):
        next(s.store.iter_timeline(cutoff_ns=s.clock.now))


def test_large_valid_v1_news_envelope_uses_chunk_budget_not_payload_budget():
    from test_intraday_news import article

    from backend.app.data_providers.alpaca_news import NewsRights
    from backend.app.intraday.news import NewsStore

    s = prepared()
    service(s).register_policy()
    news = NewsStore(s.archive.provider, clock_ns=lambda: s.clock.now,
        rights=NewsRights(allow_summary=True, allow_content=True,
                         retention='ARCHIVE_ALLOWED', evidence_hash='b' * 64))
    news.persist([article(summary='x' * 262_000, content='y' * 262_000)], received_at_ns=s.clock.now)
    saved = freeze(s)
    expected = service(s).read(saved.snapshot_id)
    actual = service(s).open(saved.snapshot_id)
    assert list(actual.timeline) == expected['timeline']
    assert sum(map(len, actual.timeline.chunks())) == len(actual.timeline)


def test_freeze_stages_exact_references_without_legacy_prefix_list(monkeypatch):
    from backend.app.intraday.quality import quality_report

    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    expected = s.store.replay_as_of(cutoff_ns=s.clock.now, timeline_only=True)['timeline']
    monkeypatch.setattr(s.store, 'replay_as_of', lambda **k: (_ for _ in ()).throw(AssertionError('PREFIX_LIST')))
    saved = freeze(s)
    reader = service(s)
    actual = reader.open(saved.snapshot_id)
    assert list(actual.timeline) == expected
    assert actual.report == quality_report(actual.manifest, expected)


def test_owned_market_read_does_not_copy_or_rehash_decoded_envelopes(monkeypatch):
    s = prepared()
    s.store.persist((event(s, kind='QUOTE'), event(s, kind='QUOTE', at=OPEN - SECOND)))
    expected = s.store.read_as_of('QUOTE', cutoff_ns=s.clock.now)
    monkeypatch.setattr('backend.app.intraday.replay.copy.deepcopy',
                        lambda *a: (_ for _ in ()).throw(AssertionError('DUPLICATE_COPY')))
    assert s.store.read_as_of('QUOTE', cutoff_ns=s.clock.now) == expected


def test_timeline_smoke_refuses_existing_relative_and_real_targets(tmp_path,monkeypatch):
    smoke = importlib.import_module('backend.scripts.intraday_timeline_smoke')
    existing = tmp_path / 'existing.db'
    existing.write_bytes(b'existing')
    for target in (str(existing),'relative.db',str(tmp_path/'investedge.db')):
        monkeypatch.setenv('INVESTEDGE_DB_PATH',target)
        with pytest.raises(ValueError,match='TARGET_MUST_BE_NEW_ABSOLUTE_SCRATCH'):
            smoke.target_path()
    assert existing.read_bytes() == b'existing'


def test_timeline_smoke_blocks_dns_and_datagrams():
    import socket
    smoke = importlib.import_module('backend.scripts.intraday_timeline_smoke')
    with smoke.blocked_network() as attempts:
        with pytest.raises(RuntimeError,match='NETWORK_BLOCKED'):
            socket.gethostbyname('example.invalid')
        with socket.socket(type=socket.SOCK_DGRAM) as source,pytest.raises(RuntimeError,match='NETWORK_BLOCKED'):
            source.sendto(b'x',('127.0.0.1',12345))
    assert attempts['count'] == 2


def test_frozen_page_enforces_its_own_decoded_byte_and_occurrence_caps():
    s = prepared()
    service(s).register_policy()
    s.store.persist(tuple(event(s,at=OPEN+index*60*SECOND) for index in range(25)))
    saved = freeze(s)
    handle = service(s).open(saved.snapshot_id,max_bytes=16_384,max_occurrences=10).timeline
    page = handle.page(limit=25,input_type='BAR')
    assert 0 < len(page['items']) <= 10
    assert sum(len(json.dumps(row,sort_keys=True,separators=(',',':')).encode()) for row in page['items'])<=16_384
    assert page['next_offset'] == len(page['items'])


def test_strict_timeline_ignores_corrupt_receipts_in_an_unrelated_history_namespace():
    from dataclasses import replace

    from backend.app.intraday.store import IntradayStore
    s = prepared()
    s.store.persist((event(s),))
    history = IntradayStore(s.archive.provider,clock_ns=lambda:s.clock.now,
                           provenance='HISTORICAL_CURRENT',replay_grade='RESEARCH_ONLY')
    ids = history.persist((replace(event(s),provenance='HISTORICAL_CURRENT',replay_grade='RESEARCH_ONLY'),))
    raw = s.db.execute("SELECT id,payload_json FROM intraday_capture_events WHERE kind='ADMISSION' AND observation_id=?",(ids[0],)).fetchone()
    payload = json.loads(raw['payload_json'])
    payload['durable_at_ns'] = None
    text = canonical_json(payload)
    s.db.execute('DROP TRIGGER trg_intraday_capture_events_no_update')
    s.db.execute('UPDATE intraday_capture_events SET payload_json=?,payload_hash=? WHERE id=?',
                 (text,hashlib.sha256(text.encode()).hexdigest(),raw['id']))
    s.db.commit()
    expected = s.store.replay_as_of(cutoff_ns=s.clock.now,timeline_only=True)['timeline']
    assert list(s.store.iter_timeline(cutoff_ns=s.clock.now)) == expected


def test_staging_work_queue_does_not_scan_processed_prefix():
    import sqlite3

    from backend.app.intraday.snapshots import _StagedTimeline
    stage = _StagedTimeline.__new__(_StagedTimeline)
    stage.db = sqlite3.connect(':memory:')
    stage.stage = 'fixture_stage'
    stage._create_stage()
    plan = ' '.join(row[3] for row in stage.db.execute(f'EXPLAIN QUERY PLAN SELECT source_table,source_id,replay FROM {stage.stage} WHERE processed=0 LIMIT 1'))
    assert 'SEARCH' in plan and 'SCAN' not in plan


@pytest.mark.parametrize('change',['database','secret'])
def test_suspended_validated_iterator_rechecks_fence_before_next_output(change):
    from dataclasses import replace
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),event(s,at=OPEN+60*SECOND)))
    saved = freeze(s)
    reader = service(s)
    iterator = iter(reader.open(saved.snapshot_id).timeline)
    next(row for row in iterator if row['table']=='intraday_observations')
    second = s.db.execute('SELECT * FROM intraday_observations ORDER BY id DESC LIMIT 1').fetchone()
    if change=='database':
        s.db.execute('DROP TRIGGER trg_intraday_observations_no_update')
        s.db.execute('UPDATE intraday_observations SET payload_json=? WHERE id=?',('{"corrupt":true}',second['id']))
        s.db.commit()
    else:
        reader.archive.settings = replace(reader.archive.settings,alpaca_api_secret_key=second['logical_key'])
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        list(iterator)


def test_transient_source_mutation_during_batch_does_not_emit_buffered_corruption(monkeypatch):
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    s.db.execute('DROP TRIGGER trg_intraday_observations_no_update')
    s.db.commit()
    reader = service(s)
    timeline = reader.open(saved.snapshot_id).timeline
    original = reader._hydrate_batch
    raw = s.db.execute('SELECT id,payload_json FROM intraday_observations LIMIT 1').fetchone()
    changed = False
    def mutated(refs, *, validated=False):
        nonlocal changed
        if not validated or changed:
            return original(refs,validated=validated)
        changed = True
        s.db.execute('UPDATE intraday_observations SET payload_json=? WHERE id=?',('{"corrupt":true}',raw['id']))
        rows = original(refs,validated=validated)
        s.db.execute('UPDATE intraday_observations SET payload_json=? WHERE id=?',(raw['payload_json'],raw['id']))
        return rows
    monkeypatch.setattr(reader,'_hydrate_batch',mutated)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        list(timeline)


@pytest.mark.parametrize('count',[44,80])
def test_many_large_valid_news_split_reader_batches(count):
    from test_intraday_news import article

    from backend.app.data_providers.alpaca_news import NewsRights
    from backend.app.intraday.news import NewsStore
    from backend.app.intraday.snapshots import _envelope_bytes
    s = prepared(max_archive_bytes=268_435_456)
    service(s).register_policy()
    news = NewsStore(s.archive.provider,clock_ns=lambda:s.clock.now,
        rights=NewsRights(allow_summary=True,allow_content=True,retention='ARCHIVE_ALLOWED',evidence_hash='b'*64))
    news.persist([article(id=101+i,summary='x'*262_000,content='y'*262_000) for i in range(count)],received_at_ns=s.clock.now)
    saved = freeze(s)
    reader = service(s)
    expected = reader.read(saved.snapshot_id)['timeline']
    assert max(len(_envelope_bytes(row)) for row in expected)<8_388_608
    actual = reader.open(saved.snapshot_id)
    assert list(actual.timeline)==expected
    assert sum(map(len,actual.timeline.chunks()))==len(expected)


@pytest.mark.parametrize('column',['capture_id','ingest_run_id'])
def test_timeline_rejects_news_link_with_different_capture_or_run(column):
    from test_intraday_news import article

    from backend.app.intraday.news import NewsStore
    s = prepared()
    news = NewsStore(s.archive.provider,clock_ns=lambda:s.clock.now)
    news.persist([article()],received_at_ns=s.clock.now)
    s.db.execute('DROP TRIGGER trg_intraday_news_links_no_update')
    replacement = 'unrelated-capture' if column=='capture_id' else s.archive.begin_run()
    s.db.execute(f'UPDATE intraday_news_links SET {column}=?',(replacement,))
    s.db.commit()
    with pytest.raises(ValueError):
        next(s.store.iter_timeline(cutoff_ns=s.clock.now))


def test_validated_reader_stops_at_rss_limit_before_returning_a_handle(monkeypatch):
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    monkeypatch.setattr('backend.app.intraday.snapshots._peak_rss_bytes',lambda:2_147_483_649)
    with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
        service(s).open(saved.snapshot_id)


def test_reader_checks_rss_after_dependency_closure(monkeypatch):
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    reader = service(s)
    peak = [1]
    original = reader._closure_batch
    def closure(*args):
        result = original(*args)
        peak[0] = 2_147_483_649
        return result
    monkeypatch.setattr(reader,'_closure_batch',closure)
    monkeypatch.setattr('backend.app.intraday.snapshots._peak_rss_bytes',lambda:peak[0])
    with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
        reader.open(saved.snapshot_id)


def test_quote_carry_selection_has_bounded_sql_work_for_a_large_prefix():
    import sqlite3

    from test_intraday_store import MINUTE

    from backend.app.intraday.snapshots import _StagedTimeline
    s = prepared(max_archive_bytes=134_217_728)
    reader = service(s)
    s.clock.now = OPEN-SECOND
    reader.register_policy()
    s.store.persist(tuple(event(s,kind='QUOTE',at=OPEN-(1_001-number)*SECOND) for number in range(1_000)))
    s.clock.now = OPEN+30*MINUTE
    saved = freeze(s)
    manifest = reader.open(saved.snapshot_id).manifest
    resources = {'max_disk_bytes':4*1024**3,'min_free_bytes':512*1024**2,'max_chunk_bytes':8_388_608,
                 'max_cache_bytes':67_108_864,'max_rss_bytes':2_147_483_648,'window_sessions':5,'history_sessions':30}
    manifest.update(version='intraday-dataset-v2',carry_at_ns=OPEN-1,history_sessions=30)
    stage = _StagedTimeline(reader,manifest,resources)
    calls = [0]
    def budget():
        calls[0] += 1
        return calls[0]>1_000
    s.db.set_progress_handler(budget,1_000)
    try:
        try:
            stage.select()
        except sqlite3.OperationalError:
            pytest.fail('QUOTE_CARRY_SQL_WORK_EXCEEDED_LINEAR_FIXTURE_BUDGET')
    finally:
        s.db.set_progress_handler(None,0)
        stage.close()
