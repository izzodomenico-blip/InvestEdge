from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import contextmanager

import pytest
from test_intraday_snapshots import freeze, service
from test_intraday_store import OPEN, SECOND, event, prepared

from backend.app.intraday.contracts import canonical_json


def test_member_digest_scan_uses_index_order_without_temporary_sort():
    s = prepared()
    plan = s.db.execute('EXPLAIN QUERY PLAN SELECT * FROM intraday_dataset_members '
                        'WHERE snapshot_id=? ORDER BY ingest_sequence', (1,)).fetchall()
    assert not any('TEMP B-TREE' in row[3] for row in plan)
    assert any('idx_intraday_dataset_member_sequence' in row[3] for row in plan)


def test_duplicate_identity_scan_uses_typed_keys_before_full_member_validation():
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    queries = []
    s.db.set_trace_callback(queries.append)
    try:
        assert list(reader.open(saved.snapshot_id).timeline)
    finally:
        s.db.set_trace_callback(None)
    duplicate = next(sql for sql in queries if 'HAVING COUNT(*)>1' in sql)
    assert "'$.reference'" not in duplicate
    assert 'member_kind' in duplicate


@pytest.mark.parametrize('member_id',[-2**63,2**63-1])
def test_ordered_reader_fetches_reference_text_after_causal_sort_with_full_int64_member_ids(member_id):
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),event(s,at=OPEN+SECOND)))
    saved = freeze(s)
    expected = [(row['table'],row['id']) for row in reader.open(saved.snapshot_id).timeline]
    s.db.execute('DROP TRIGGER trg_intraday_dataset_members_no_update')
    s.db.execute('UPDATE intraday_dataset_members SET id=? WHERE snapshot_id=? AND observation_id=1',
                 (member_id,saved.snapshot_id))
    s.db.commit()
    timeline = reader.open(saved.snapshot_id).timeline
    queries = []
    s.db.set_trace_callback(queries.append)
    try:
        refs = list(timeline._ordered(timeline.manifest['cutoff_ns']))
    finally:
        s.db.set_trace_callback(None)
    assert [(json.loads(row[0])['table'],json.loads(row[0])['id']) for row in refs]==expected
    plan = s.db.execute('EXPLAIN QUERY PLAN '+queries[-1]).fetchall()
    assert any('CO-ROUTINE ordered' in row[3] for row in plan)
    assert any('CORRELATED SCALAR SUBQUERY' in row[3] for row in plan)


@pytest.mark.parametrize('reference',[None,1,b'{}'])
def test_reference_batch_rejects_missing_late_reference_with_fixed_error(reference):
    from backend.app.intraday.snapshots import _reference_batches

    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        list(_reference_batches([(reference,)]))


@pytest.mark.parametrize('shadow',['intraday_observations','intraday_dataset_members','INTRADAY_OBSERVATIONS'])
def test_validated_reader_rejects_temp_shadow_without_confusing_legitimate_job_tables(shadow):
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    handle = reader.open(saved.snapshot_id)
    before = s.db.total_changes
    s.db.execute('CREATE TEMP TABLE legitimate_job_fixture(id INTEGER)')
    assert list(handle.timeline)
    columns = [row[1] for row in s.db.execute(f'PRAGMA main.table_info({shadow})')]
    projection = ','.join("'{\"corrupt\":true}' AS payload_json" if key=='payload_json' else key for key in columns)
    s.db.execute(f'CREATE TEMP TABLE {shadow} AS SELECT {projection} FROM main.{shadow}')
    assert s.db.total_changes==before
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        list(handle.timeline)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


@pytest.mark.parametrize('shadow',['intraday_observations','INTRADAY_OBSERVATIONS'])
def test_temp_view_is_rejected_when_rollback_reuses_a_checked_schema_cookie(shadow):
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    handle = reader.open(saved.snapshot_id)
    before = s.db.total_changes
    s.db.execute('BEGIN')
    s.db.execute('CREATE TEMP TABLE timeline_legitimate_rollback(id INTEGER)')
    checked = s.db.execute('PRAGMA temp.schema_version').fetchone()[0]
    assert list(handle.timeline)
    s.db.rollback()
    s.db.execute(f'CREATE TEMP VIEW {shadow} AS SELECT * FROM main.intraday_observations')
    assert s.db.execute('PRAGMA temp.schema_version').fetchone()[0]==checked
    assert s.db.total_changes==before
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        list(handle.timeline)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


def test_canonical_integer_evidence_avoids_python_reencoding(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    payload = {'dependencies': [], 'reference': {'id': 2**63-1, 'text': 'é😀\\\n"'}, 'replay': True}
    text = canonical_json(payload)
    def forbidden(value):
        raise AssertionError('PYTHON_REENCODING_OF_CANONICAL_INTEGER_EVIDENCE')
    monkeypatch.setattr(snapshots, '_envelope_bytes', forbidden)
    row = snapshots._decode_evidence({'payload_json': text, 'payload_hash': hashlib.sha256(text.encode()).hexdigest()})
    assert row['payload'] == payload


def test_native_price_float_encoding_requires_exact_v1_scalar_byte_parity(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    payload = {'prices':[100.0,99.9,1.25,-0.0]}
    text = canonical_json(payload)
    def forbidden(value):
        raise AssertionError('REENCODING_NATIVE_V1_EQUIVALENT_PRICES')
    monkeypatch.setattr(snapshots,'_envelope_bytes',forbidden)
    assert snapshots._decode_evidence({'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()})['payload']==payload


def test_normal_evidence_uses_stdlib_canonical_encoder_without_python_tree_walk(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    payload = {'a':[None,True,2**63-1,1e-6,1e20,-0.0], 'b':{'é':'😀\\\n"'}}
    text = canonical_json(payload)
    def forbidden(value):
        raise AssertionError('PYTHON_TREE_WALK_FOR_BOUNDED_JSON_NUMBERS')
    monkeypatch.setattr(snapshots,'_native_canonical',forbidden)
    assert snapshots._decode_evidence({'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()})['payload']==payload


@pytest.mark.parametrize('payload', [{'n':int('9'*308)}, {'n':int('1'+'0'*308)},
                                   {'n':-int('9'*308)}, {'text':'9'*309}, {'text':'x'+'8'*308+'y'}])
def test_evidence_integer_digit_guard_keeps_v1_finite_boundary_and_string_fallback(payload):
    from backend.app.intraday.snapshots import _decode_evidence

    text = canonical_json(payload)
    assert _decode_evidence({'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()})['payload']==payload


def test_evidence_keeps_full_canonical_fallback_without_stdlib_c_encoder(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    payload = {'n':[1e-6,-0.0,2**63-1], 'text':'é😀'}
    text = canonical_json(payload)
    monkeypatch.setattr(snapshots,'_OWNED_HEADER_ENCODER',None)
    assert snapshots._decode_evidence({'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()})['payload']==payload


@pytest.mark.parametrize('payload', [
    {'a': [1e-6, 1e20, -0.0, 1.25]}, {'a': int('1'+'0'*308)},
    {'a': {'b': ['\u0000', 'é', '😀', '\\', '"']}},
])
def test_evidence_codec_keeps_v1_canonical_bytes_and_finite_numbers(payload):
    from backend.app.intraday.snapshots import _decode_evidence

    text = canonical_json(payload)
    assert _decode_evidence({'payload_json': text, 'payload_hash': hashlib.sha256(text.encode()).hexdigest()})['payload'] == payload


@pytest.mark.parametrize('depth', [99, 200])
def test_evidence_codec_preserves_v1_supported_nested_payloads(depth):
    from backend.app.data_providers.alpaca_metadata import decode_row
    from backend.app.intraday.snapshots import _decode_evidence

    value = 1
    for _ in range(depth):
        value = [value]
    text = canonical_json({'a': value})
    raw = {'payload_json': text, 'payload_hash': hashlib.sha256(text.encode()).hexdigest()}
    assert _decode_evidence(raw) == decode_row(raw)


@pytest.mark.parametrize('text', ['{"a":1e999}', '{"a":'+('9'*400)+'}', '{"a":{"z":1,"a":2}}'])
def test_evidence_codec_rejects_nested_noncanonical_or_nonfinite_values(text):
    from backend.app.intraday.snapshots import _decode_evidence

    with pytest.raises(ValueError, match='METADATA_INVALID'):
        _decode_evidence({'payload_json': text, 'payload_hash': hashlib.sha256(text.encode()).hexdigest()})


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


def test_timeline_order_extracts_each_typed_reference_once_and_keeps_exact_order():
    from collections import Counter

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist(tuple(event(s,at=OPEN+index*SECOND) for index in range(20)))
    saved = freeze(s)
    timeline = reader.open(saved.snapshot_id).timeline
    expected = [(row['table'],row['id']) for row in timeline]
    calls = Counter()
    def extract(text,path):
        calls[path] += 1
        value = json.loads(text)
        for key in path[2:].split('.'):
            if not isinstance(value,dict) or key not in value:
                return None
            value = value[key]
        return canonical_json(value) if isinstance(value,(dict,list)) else value
    s.db.create_function('json_extract',2,extract,deterministic=True)
    before = s.db.total_changes
    try:
        result = [json.loads(row[0]) for row in timeline._ordered(timeline.manifest['cutoff_ns'])]
        assert [(ref['table'],ref['id']) for ref in result]==expected
        assert calls['$.table']<=len(result)
        assert s.db.total_changes==before
    finally:
        s.db.close()


def test_admission_closure_checks_binding_without_rehydrating_full_receipt(monkeypatch):
    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    dataset = reader.open(saved.snapshot_id)
    rows = [row for row in dataset.timeline if row['table'] == 'intraday_observations']
    assert rows and all(row.get('admission_id') for row in rows)
    original = reader._hydrated_batches
    def no_receipt_envelope(refs, *, validated=False):
        assert not validated, 'REDUNDANT_FULL_RECEIPT_HYDRATION'
        yield from original(refs, validated=validated)
    monkeypatch.setattr(reader, '_hydrated_batches', no_receipt_envelope)
    reader._closure_batch(saved.snapshot_id, rows)


@pytest.mark.parametrize('text', ['{ "a":1}', '{"a":1,"a":1}', '{"b":1,"a":1}',
                                  '{"a":"\\u00e9"}', '{"a":-0}', '{"a":1e0}', '{"a":NaN}'])
def test_fast_decoder_rejects_noncanonical_payload_even_with_matching_hash(text):
    from backend.app.intraday.snapshots import _decode_evidence

    with pytest.raises(ValueError, match='METADATA_INVALID'):
        _decode_evidence({'payload_json':text,'payload_hash':hashlib.sha256(text.encode()).hexdigest()})


def test_owned_envelope_size_reuses_canonical_payload_and_preserves_exact_utf8_bytes(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    payload = {'text': 'é😀\\\n"', 'number': 1.25, 'nested': [None, True, {'id': 123}]}
    row = {'table': 'intraday_news_versions', 'payload': payload, 'payload_json': canonical_json(payload),
           'available_at_ns': OPEN, 'links': [{'text': 'é\\"'}]}
    expected = len(snapshots._envelope_bytes(row))
    original = snapshots._envelope_bytes
    def header_only(value,**kwargs):
        assert 'payload' not in value and 'payload_json' not in value, 'REENCODED_CANONICAL_PAYLOAD'
        return original(value,**kwargs)
    monkeypatch.setattr(snapshots, '_envelope_bytes', header_only)
    assert snapshots._row_byte_bound(row, _decoded=True) == expected
    monkeypatch.setattr(snapshots, '_envelope_bytes', original)
    row['payload'] = {'changed': 'payload'}
    assert snapshots._row_byte_bound(row) == len(original(row))


def test_evidence_decoder_parses_the_single_bounded_utf8_buffer(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    payload = {'text':'é😀\\\n"', 'value':1.25}
    text = canonical_json(payload)
    original = snapshots.from_json
    def bytes_only(value, **kwargs):
        assert type(value) is bytes, 'DUPLICATE_UTF8_CONVERSION'
        return original(value, **kwargs)
    monkeypatch.setattr(snapshots, 'from_json', bytes_only)
    assert snapshots._decode_evidence({'payload_json':text,
        'payload_hash':hashlib.sha256(text.encode()).hexdigest()})['payload'] == payload


def test_owned_size_counts_escapes_without_allocating_a_second_payload(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    payload = {'text':'é😀\\\n\t\x00"', 'value':1.25}
    text = canonical_json(payload)
    row = {'payload':payload, 'payload_json':text, 'id':1, 'links':[{'text':'é\\"'}]}
    expected = len(snapshots._envelope_bytes(row))
    original = json.encoder.encode_basestring
    def header_only(value):
        assert value != text, 'ALLOCATED_ESCAPED_CANONICAL_PAYLOAD'
        return original(value)
    monkeypatch.setattr(json.encoder, 'encode_basestring', header_only)
    assert snapshots._row_byte_bound(row, _decoded=True) == expected


@pytest.mark.parametrize('operation',['source','size'])
def test_owned_headers_reuse_the_stdlib_codec_without_rebuilding_it(monkeypatch,operation):
    import backend.app.intraday.snapshots as snapshots

    s = prepared()
    s.store.persist((event(s),))
    reader = service(s)
    raw = reader._raw_source('intraday_observations',1)
    expected = reader._decode_source('intraday_observations',1,raw=raw)
    projected = expected[1] | {'table':'intraday_observations'}
    size = len(snapshots._envelope_bytes(projected))
    def forbidden(value):
        raise AssertionError('REBUILT_OWNED_HEADER_ENCODER')
    monkeypatch.setattr(snapshots._ENVELOPE_ENCODER,'encode',forbidden)
    if operation=='source':
        assert reader._decode_source('intraday_observations',1,raw=raw) == expected
    else:
        assert snapshots._row_byte_bound(projected,_decoded=True) == size


def test_reference_batches_bound_utf8_working_set_before_decoding():
    import backend.app.intraday.snapshots as snapshots

    texts = ['{"value":"é😀"}']*1201
    limit = 3*len(texts[0].encode())
    batches = list(snapshots._reference_batches(((text,) for text in texts), max_bytes=limit))
    assert sum(len(batch) for batch in batches) == len(texts)
    assert all(sum(len(item[0].encode()) for item in batch)<=limit and len(batch)<=1000 for batch in batches)
    with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
        list(snapshots._reference_batches(iter([(texts[0],)]), max_bytes=1))


@pytest.mark.parametrize('field', ['digest','publication_hash'])
def test_open_rejects_current_sensitive_inventory_matching_public_derived_hash(field):
    from dataclasses import replace

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    value = getattr(reader.open(saved.snapshot_id),field)
    reader.archive.settings = replace(reader.archive.settings,alpaca_api_secret_key=value)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


def test_open_fences_mutation_during_timeline_handle_construction(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    s = prepared()
    reader = service(s)
    reader.register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    s.db.execute('DROP TRIGGER trg_intraday_observations_no_update')
    original = snapshots.FrozenTimeline.__init__
    def changed(self,*args,**kwargs):
        s.db.execute('UPDATE intraday_observations SET payload_json=?',('{"corrupt":true}',))
        return original(self,*args,**kwargs)
    monkeypatch.setattr(snapshots.FrozenTimeline,'__init__',changed)
    with pytest.raises(ValueError,match='SNAPSHOT_INPUT_MISSING'):
        reader.open(saved.snapshot_id)


def test_reference_preserves_exact_hash_and_projection_without_decoding_source_twice(monkeypatch):
    import backend.app.intraday.snapshots as snapshots

    s = prepared()
    s.store.persist((event(s),))
    reader = service(s)
    row = s.store.read_as_of('BAR', cutoff_ns=s.clock.now)[0]
    row['table'] = 'intraday_observations'
    expected = reader._reference(row)
    def forbidden(*args, **kwargs):
        raise AssertionError('SOURCE_DECODED_TWICE')
    monkeypatch.setattr(snapshots, 'decode_row', forbidden)
    assert reader._reference(row) == expected
    row['payload'] = {'changed': True}
    with pytest.raises(ValueError, match='SNAPSHOT_INPUT_MISSING'):
        reader._reference(row)


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
