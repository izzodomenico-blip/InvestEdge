from __future__ import annotations

import copy
import hashlib
import importlib
import random

import pytest
from test_intraday_store import SECOND, event, prepared

from backend.app.intraday.contracts import canonical_json

TABLES = {'BAR': 'intraday_observations', 'QUOTE': 'intraday_observations',
          'STATUS': 'intraday_observations', 'LULD': 'intraday_observations',
          'NEWS': 'intraday_news_versions', 'EVENT': 'intraday_event_versions',
          'IDENTITY': 'intraday_identity_versions', 'CALENDAR': 'intraday_calendar_versions',
          'UNIVERSE': 'intraday_universe_snapshots', 'CONTROL': 'intraday_capture_events'}


def api():
    return importlib.import_module('backend.app.intraday.replay')


def row(family='BAR', *, at=10, received=20, available=21, row_id=1, capture='capture-a', intake=1, **changes):
    payload = {'intake_sequence': intake, 'raw': {'o': 100, 'h': 102, 'l': 99, 'c': 101, 'v': 10, 'vw': 100.5},
               'source': 'STREAM', 'state': 'NORMAL'}
    result = {'table': TABLES[family], 'id': row_id, 'provider': 'alpaca', 'feed': 'sip',
              'profile_id': 'a' * 64, 'data_mode': 'REAL', 'provenance': 'CAPTURED', 'replay_grade': 'STRICT_PIT',
              'schema_version': 'intraday-v1', 'listing_id': 1, 'logical_key': f'{family}:1:{at}',
              'capture_id': capture, 'ingest_sequence': row_id, 'event_time_ns': at,
              'received_at_ns': received, 'persisted_at_ns': received, 'available_at_ns': available,
              'admission_id': row_id, 'publication_id': row_id, 'publication_hash': 'b' * 64,
              'quality': 'VALID', 'reason_code': None, 'kind': family, 'bar_end_ns': at + 60 * SECOND,
              'article_id': 'benzinga:101', 'updated_at_ns': at, 'published_at_ns': at,
              'event_type': 'CORPORATE_ACTION', 'effective_at_ns': at, 'scheduled_at_ns': None,
              'valid_from_ns': 0, 'valid_to_ns': None, 'confirmed': 1,
              'session_date': '2026-10-12', 'open_at_ns': 0, 'close_at_ns': 100,
              'cutoff_ns': received, 'links': [{'listing_id': 1}], 'payload': payload}
    if family == 'CONTROL':
        result['kind'] = 'CLOCK'
        payload.update(metadata_kind='TRANSPORT_LIVENESS', channel='news', pong_received_at_ns=received)
    result.update(changes)
    text = canonical_json(result['payload'])
    result.update(payload_json=text, payload_hash=hashlib.sha256(text.encode()).hexdigest())
    return result


@pytest.mark.parametrize('family', TABLES)
@pytest.mark.parametrize('operation', ['append', 'change', 'remove'])
def test_future_occurrences_never_change_any_prefix(family, operation):
    first = row(family)
    future = row(family, row_id=2, received=30, available=31)
    baseline = api().replay_as_of([first, future], cutoff_ns=25)
    changed = copy.deepcopy([first, future])
    if operation == 'append':
        changed.append(row(family, row_id=3, received=40, available=41))
    elif operation == 'change':
        changed[-1]['payload'] = {'changed': 'future only'}
    else:
        changed.pop()
    assert api().replay_as_of(changed, cutoff_ns=25) == baseline


def test_quote_arriving_late_never_regresses_event_time_or_falls_back_from_invalid():
    newest = row('QUOTE', at=15, received=16, available=17)
    old = row('QUOTE', at=10, received=20, available=21, row_id=2)
    state = api().quote_state_from_rows([newest, old], listing_id=1, cutoff_ns=22, max_age_ns=100)
    assert state['id'] == newest['id'] and state['executable']
    bad = row('QUOTE', at=18, received=23, available=24, row_id=3, quality='QUARANTINED', reason_code='QUOTE_CROSSED')
    state = api().quote_state_from_rows([newest, old, bad], listing_id=1, cutoff_ns=25, max_age_ns=100)
    assert state['id'] == 3 and not state['executable']


def test_source_updated_time_beats_arrival_and_symbol_filter_follows_selection():
    first = row('NEWS', at=10)
    removed = row('NEWS', at=12, row_id=2, received=22, available=23, links=[])
    old = row('NEWS', at=11, row_id=3, received=24, available=25)
    selected = api().select_versions([first, removed, old], family='NEWS', cutoff_ns=26)
    assert [item['id'] for item in selected] == [2]
    assert not api().select_versions([first, removed, old], family='NEWS', cutoff_ns=26, listing_ids=(1,))
    assert api().select_versions([first, removed], family='NEWS', cutoff_ns=21, listing_ids=(1,))[0]['id'] == 1


def test_event_revision_moved_listing_is_selected_before_listing_filter():
    first = row('EVENT')
    later = row('EVENT', row_id=2, received=22, available=23, listing_id=2)
    assert not api().select_versions([first, later], family='EVENT', cutoff_ns=25, listing_ids=(1,))


@pytest.mark.parametrize('field,value', [('feed', 'iex'), ('profile_id', 'c' * 64), ('data_mode', 'DEMO'),
                                       ('provenance', 'HISTORICAL_CURRENT'), ('replay_grade', 'RESEARCH_ONLY')])
def test_mixed_visible_namespace_is_rejected_before_revision_or_listing_filter(field, value):
    first = row()
    other = row(row_id=2, received=22, available=23, **{field: value})
    with pytest.raises(ValueError, match='MIXED_NAMESPACE'):
        api().replay_as_of([first, other], cutoff_ns=25, listing_ids=(999,))


def test_official_event_provider_may_differ_in_same_profile():
    items = [row(), row('EVENT', row_id=2, provider='bls')]
    assert len(api().replay_as_of(items, cutoff_ns=25)['timeline']) == 2


def test_tied_receipts_are_deterministic_across_permutations_and_chunk_boundaries():
    items = [row(row_id=1, intake=100), row(row_id=2, intake=1),
             row('NEWS', row_id=1, intake=101, admission_id=3),
             row('EVENT', row_id=1, intake=1, capture='independent', admission_id=4)]
    expected = api().replay_as_of(items, cutoff_ns=25)
    rng = random.Random(137)
    for _ in range(12):
        rng.shuffle(items)
        assert api().replay_as_of(items, cutoff_ns=25) == expected
        reducer = api().ReplayReducer()
        for item in items:
            reducer.extend([item])
        assert reducer.as_of(25) == expected
    ordered = expected['timeline']
    assert ordered.index(next(item for item in ordered if item['table'] == TABLES['NEWS'])) > ordered.index(
        next(item for item in ordered if item['table'] == TABLES['BAR'] and item['id'] == 1))


def test_future_capture_order_never_changes_the_visible_tied_order():
    items = [row(row_id=5, capture='a', intake=100), row(row_id=2, capture='b', intake=1)]
    expected = api().replay_as_of(items, cutoff_ns=25)
    future = row(row_id=1, capture='a', intake=1, available=30)
    assert api().replay_as_of([*items, future], cutoff_ns=25) == expected


def test_saved_reducer_input_and_output_are_isolated_from_mutations():
    items = [row()]
    reducer = api().ReplayReducer()
    reducer.extend(items)
    saved = reducer.as_of(25)
    items[0]['payload']['raw']['c'] = 10
    saved['timeline'][0]['payload']['raw']['c'] = 20
    assert reducer.as_of(25)['timeline'][0]['payload']['raw']['c'] == 101


@pytest.mark.parametrize('family', ['BAR', 'NEWS', 'EVENT', 'CONTROL'])
def test_unadmitted_raw_is_never_a_replay_event(family):
    assert not api().replay_as_of([row(family, available_at_ns=None)], cutoff_ns=25)['timeline']


def test_store_replay_uses_only_durable_admissions_and_keeps_all_versions():
    s = prepared()
    first = s.clock.now
    ids = s.store.persist((event(s),), admit=False)
    assert not s.store.replay_as_of(cutoff_ns=first)['observations']['BAR']
    s.clock.now += SECOND
    s.store.admit(ids)
    expected = s.store.replay_as_of(cutoff_ns=s.clock.now)
    assert len(expected['observations']['BAR']) == 1
    cutoff = s.clock.now
    s.clock.now += SECOND
    s.store.persist((event(s, change={'c': 100}),))
    assert s.store.replay_as_of(cutoff_ns=cutoff) == expected
    assert len([r for r in s.store.replay_as_of(cutoff_ns=s.clock.now)['timeline'] if r['table'] == TABLES['BAR']]) == 2


def test_collector_transcript_and_replay_agree_at_each_durable_cutoff():
    from test_intraday_collector import boot, deliver, handshake, quote, setup, status
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    s.collector.reconcile()
    for code in ('T', 'H', 'Q', 'T'):
        s.clock.now += SECOND
        deliver(s, 'market', [quote(s), status(s, code)])
        before = s.store.replay_as_of(cutoff_ns=s.clock.now)
        s.clock.now += SECOND
        s.collector.drain()
        s.collector.reconcile()
        assert s.store.replay_as_of(cutoff_ns=s.clock.now - SECOND) == before
        current = s.store.replay_as_of(cutoff_ns=s.clock.now)
        assert current['capture']['state'] == s.collector.status()['state']
        assert current['capture']['listing_states'] == s.collector.status()['listing_states']
        assert current['quotes'][s.listing] == s.store.quote_state(s.listing, cutoff_ns=s.clock.now)


def test_future_calendar_identity_and_universe_evidence_keeps_frozen_timeline():
    s = prepared()
    cutoff = s.clock.now
    expected = s.store.replay_as_of(cutoff_ns=cutoff)
    assert any(item['table'] == TABLES['CALENDAR'] for item in expected['timeline'])
    assert any(item['table'] == TABLES['IDENTITY'] for item in expected['timeline'])
    s.clock.now += SECOND
    s.calendar.record([], start='2026-10-12', end='2026-10-12', received_at_ns=s.clock.now)
    assert s.store.replay_as_of(cutoff_ns=cutoff) == expected
    assert not s.store.replay_as_of(cutoff_ns=s.clock.now)['calendars']


def live_capture(**settings):
    from test_intraday_collector import boot, handshake, setup
    s = setup(**settings)
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    s.collector.reconcile()
    return s


def test_replay_live_expires_from_frozen_transport_policy_without_mutable_collector_state():
    s = live_capture(alpaca_stream_silence_seconds=5)
    cutoff = s.clock.now
    saved = s.store.replay_as_of(cutoff_ns=cutoff)
    s.clock.now += 6 * SECOND
    replay = s.store.replay_as_of(cutoff_ns=s.clock.now)
    assert replay['capture']['state'] == s.collector.status()['state'] == 'DEGRADED'
    assert not replay['capture']['listing_states'][s.listing]['live_eligible']
    assert s.store.replay_as_of(cutoff_ns=cutoff) == saved


def test_legacy_capture_without_frozen_transport_policy_is_not_promoted():
    s = live_capture()
    rows = s.store.replay_as_of(cutoff_ns=s.clock.now)['timeline']
    start = next(item for item in rows if item.get('kind') == 'CAPTURE_START')
    start['payload'].pop('continuity_policy', None)
    start['payload_json'] = canonical_json(start['payload'])
    start['payload_hash'] = hashlib.sha256(start['payload_json'].encode()).hexdigest()
    result = api().replay_as_of(rows, cutoff_ns=s.clock.now)
    assert result['capture']['state'] != 'LIVE'
    assert not any(item['live_eligible'] for item in result['capture']['listing_states'].values())


def test_handshake_cannot_borrow_a_checkpoint_for_another_listing():
    s = live_capture()
    timeline = s.store.replay_as_of(cutoff_ns=s.clock.now)['timeline']
    checkpoint = next(item for item in timeline if item['table'] == TABLES['EVENT'])
    checkpoint['listing_id'] = 999
    assert api().replay_as_of(timeline, cutoff_ns=s.clock.now)['capture']['state'] != 'LIVE'


def test_handshake_status_reference_must_be_available_before_the_barrier():
    from test_intraday_collector import deliver, status
    s = live_capture()
    s.clock.now += SECOND
    deliver(s, 'market', [status(s, 'H')])
    s.collector.drain()
    timeline = s.store.replay_as_of(cutoff_ns=s.clock.now)['timeline']
    observation = next(item for item in timeline if item.get('kind') == 'STATUS')
    handshake = next(item for item in timeline if item['payload'].get('metadata_kind') == 'COLLECTOR_HANDSHAKE')
    handshake['payload']['listings'][0]['status_refs'] = [{'id': observation['id'],
        'hash': observation['payload_hash'], 'admission_id': observation['admission_id']}]
    handshake['payload_json'] = canonical_json(handshake['payload'])
    handshake['payload_hash'] = hashlib.sha256(handshake['payload_json'].encode()).hexdigest()
    assert api().replay_as_of(timeline, cutoff_ns=s.clock.now)['capture']['state'] != 'LIVE'


def test_news_tied_intake_in_different_runs_uses_occurrence_id_not_run_sequence():
    from test_intraday_news import article, setup_news
    s = setup_news()
    s.news.persist([article(id=102), article(headline='Earlier')], received_at_ns=s.clock.now, intake_sequence=1)
    s.news.persist([article(headline='Later')], received_at_ns=s.clock.now, intake_sequence=2)
    assert next(item for item in s.news.read_as_of(cutoff_ns=s.clock.now) if item['payload']['source_article_id'] == '101')['payload']['headline'] == 'Later'


def test_replay_timeline_keeps_exact_admission_and_publication_proofs():
    s = prepared()
    s.store.persist((event(s),))
    replay = s.store.replay_as_of(cutoff_ns=s.clock.now)
    controls = [item for item in replay['timeline'] if item['table'] == TABLES['CONTROL']]
    bar = replay['observations']['BAR'][0]
    receipt = next(item for item in controls if item['id'] == bar['admission_id'])
    assert receipt['kind'] == 'ADMISSION' and receipt['payload']['payload_hash'] == bar['payload_hash']
    identity = replay['identities'][0]
    assert next(item for item in controls if item['id'] == identity['publication_id'])['payload']['metadata_kind'] == 'PUBLICATION'


def test_research_replay_retains_captured_metadata_as_separate_dependencies():
    s = prepared(history=True)
    s.store.persist((event(s, source='REST'),))
    replay = s.store.replay_as_of(cutoff_ns=s.clock.now)
    assert replay['observations']['BAR'][0]['provenance'] == 'HISTORICAL_CURRENT'
    assert replay['identities'][0]['provenance'] == 'CAPTURED'
    assert replay['calendars'][0]['provenance'] == 'CAPTURED'
    assert replay['namespace'][-2:] == ('HISTORICAL_CURRENT', 'RESEARCH_ONLY')


def test_replay_rejects_universe_with_missing_member_in_corrupt_fixture():
    from test_historical_universe import prepare, system
    s = system()
    prepare(s)
    snapshot = s.universe.freeze([s.listing], '2026-10-12', s.clock.now)
    store = importlib.import_module('backend.app.intraday.store').IntradayStore(s.archive.provider, clock_ns=lambda: s.clock.now)
    assert store.replay_as_of(cutoff_ns=s.clock.now)['universes']
    s.db.execute('DROP TRIGGER trg_intraday_universe_members_no_delete')
    s.db.execute('DELETE FROM intraday_universe_members WHERE snapshot_id=?', (snapshot.snapshot_id,))
    s.db.commit()
    with pytest.raises(ValueError, match='SNAPSHOT_INPUT_MISSING'):
        store.replay_as_of(cutoff_ns=s.clock.now)


def test_global_macro_event_remains_in_replay_filtered_to_one_listing():
    macro = row('EVENT', listing_id=None, provider='fed', event_type='MACRO')
    assert api().replay_as_of([macro], cutoff_ns=25, listing_ids=(1,))['events'] == [macro]


def test_new_captured_news_is_transport_evidence_without_inventing_articles():
    from test_intraday_collector import deliver, quote

    from backend.app.data_providers.alpaca_market import format_ns
    s = live_capture(alpaca_stream_silence_seconds=5)
    s.clock.now += 6 * SECOND
    raw = {'T': 'n', 'id': 1, 'source': 'benzinga', 'headline': 'Company releases earnings',
           'symbols': ['AAPL'], 'created_at': format_ns(s.clock.now), 'updated_at': format_ns(s.clock.now)}
    deliver(s, 'news', [raw])
    # Market independently receives data; both channels remain healthy.
    deliver(s, 'market', [quote(s)])
    s.collector.drain()
    assert s.collector.status()['state'] == 'LIVE'
    assert s.store.replay_as_of(cutoff_ns=s.clock.now)['capture']['state'] == 'LIVE'


def test_invalid_future_pong_never_certifies_news_covered_zero():
    s = live_capture()
    s.collector._log('CLOCK', {'metadata_kind': 'TRANSPORT_LIVENESS', 'channel': 'news',
        'ping_sent_at_ns': s.clock.now, 'pong_received_at_ns': s.clock.now + 100 * SECOND})
    capture = s.store.replay_as_of(cutoff_ns=s.clock.now)['capture']
    assert capture['state'] == 'DEGRADED' and capture['news_coverage'] == 'UNKNOWN'


def test_future_handshake_barrier_cannot_extend_capture_coverage():
    s = live_capture()
    timeline = s.store.replay_as_of(cutoff_ns=s.clock.now)['timeline']
    boot = next(row for row in timeline if row['payload'].get('metadata_kind') == 'COLLECTOR_HANDSHAKE')
    boot['payload']['barrier_at_ns'] = s.clock.now + SECOND
    boot['payload_json'] = canonical_json(boot['payload'])
    boot['payload_hash'] = hashlib.sha256(boot['payload_json'].encode()).hexdigest()
    capture = api().replay_as_of(timeline, cutoff_ns=s.clock.now)['capture']
    assert capture['state'] != 'LIVE' and capture['news_coverage'] == 'UNKNOWN'


def test_metadata_dependency_flag_cannot_admit_captured_market_controls_into_research():
    research = row(provenance='HISTORICAL_CURRENT', replay_grade='RESEARCH_ONLY')
    clock = row('CONTROL', metadata_dependency=True)
    with pytest.raises(ValueError, match='MIXED_NAMESPACE'):
        api().replay_as_of([research, clock], cutoff_ns=25)


def test_research_timeline_does_not_include_unrelated_captured_admissions():
    from dataclasses import replace
    s = prepared(history=True)
    captured = importlib.import_module('backend.app.intraday.store').IntradayStore(s.archive.provider, clock_ns=lambda: s.clock.now)
    captured.persist((replace(event(s), provenance='CAPTURED', replay_grade='STRICT_PIT'),))
    captured_receipt = captured.read_as_of('BAR', cutoff_ns=s.clock.now)[0]['admission_id']
    s.store.persist((event(s, source='REST'),))
    replay = s.store.replay_as_of(cutoff_ns=s.clock.now)
    assert not any(row['table'] == TABLES['CONTROL'] and row['id'] == captured_receipt for row in replay['timeline'])
