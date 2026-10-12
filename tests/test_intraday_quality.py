from __future__ import annotations

import importlib
import json
from datetime import date, timedelta
from functools import lru_cache

import pytest
from test_intraday_replay import row as original_row
from test_intraday_store import MINUTE, OPEN, SECOND

from backend.app.intraday.contracts import FeedProfile, QualityPolicy


def frozen_profile(feed='sip'):
    return FeedProfile(feed=feed, attested_capabilities=('bars', 'quotes', 'news', 'status', 'luld'),
                       max_symbols=30, max_connections=2, http_minute_limit=200, http_daily_limit=1000,
                       http_monthly_limit=10000, max_frame_bytes=1048576, max_queue_events=1000,
                       max_archive_bytes=1000000000)


def row(*args, **changes):
    changes.setdefault('profile_id', frozen_profile().profile_id)
    return original_row(*args, **changes)


def api():
    return importlib.import_module('backend.app.intraday.quality')


def manifest(*, length=30, mode='REAL', feed='sip'):
    return {'version': 'intraday-dataset-v1', 'start_at_ns': OPEN, 'end_at_ns': OPEN + length * MINUTE,
            'cutoff_ns': OPEN + length * MINUTE + 10 * SECOND,
            'namespace': [frozen_profile(feed).profile_id, feed, mode, 'CAPTURED' if mode == 'REAL' else 'SYNTHETIC',
                          'STRICT_PIT' if mode == 'REAL' else 'RESEARCH_ONLY'],
            'listing_ids': list(range(1, 11)), 'benchmarks': {'market': 9, 'sector': 10},
            'profile': {'created_at_ns': OPEN - 1, 'id': frozen_profile(feed).profile_id, 'provider': 'alpaca',
                        'feed': feed, 'config': json.loads(frozen_profile(feed).config_json)},
            'policy': {'id': QualityPolicy.version, 'hash': QualityPolicy().policy_hash,
                       'config': json.loads(QualityPolicy().config_json), 'created_at_ns': OPEN - 1}}


def calendar(length=30):
    return row('CALENDAR', at=OPEN, received=OPEN - 2, available=OPEN - 1,
               open_at_ns=OPEN, close_at_ns=OPEN + length * MINUTE,
               payload={'session_date': '2026-10-12', 'source': 'ALPACA_CALENDAR'})


def calendar_header():
    return row('CONTROL', row_id=2, at=OPEN - 2, received=OPEN - 2, available=OPEN - 1, kind='BOOTSTRAP',
               payload={'metadata_kind': 'CALENDAR', 'complete': True, 'start': '2026-10-12',
                        'end': '2026-10-12', 'session_ids': {'2026-10-12': 1}, 'member_count': 1})


def test_empty_gate_is_insufficient_not_vacuously_ready():
    result = api().quality_report(manifest(), [])
    assert result['outcome'] == 'INSUFFICIENTE'
    assert 'CALENDAR_COVERAGE_UNKNOWN' in result['reasons']
    assert result['g1_tech'] == 'NOT_EVALUATED'


def test_fixed_grid_denominators_include_missing_benchmarks_and_excluded_listings():
    result = api().quality_report(manifest(), [calendar(), calendar_header()])
    cells = result['metrics']['grid']
    assert len(cells) == 30
    assert sum(c['planned'] for c in cells if c['minutes'] == 1) == 300
    assert sum(c['planned'] for c in cells if c['minutes'] == 5) == 60
    assert sum(c['planned'] for c in cells if c['minutes'] == 15) == 20
    assert all(c['usable'] == 0 for c in cells)
    assert result['metrics']['raw']['planned'] == 300


@pytest.mark.parametrize('mode,feed', [('DEMO', 'sip'), ('REAL', 'iex'), ('REAL', 'delayed_sip')])
def test_demo_or_non_sip_cannot_certify_real_data(mode, feed):
    result = api().quality_report(manifest(mode=mode, feed=feed), [])
    assert result['outcome'] == 'NON_IDONEO'


def test_policy_cannot_be_relaxed_and_future_token_is_rejected():
    body = manifest()
    body['policy']['config']['min_sessions'] = 1
    with pytest.raises(ValueError, match='QUALITY_POLICY_INVALID'):
        api().quality_report(body, [])
    body = manifest()
    body['start_at_ns'] = body['end_at_ns']
    with pytest.raises(ValueError, match='DATASET_INVALID'):
        api().quality_report(body, [])


def test_zero_fifteen_minute_points_are_failure_not_one_hundred_percent():
    result = api().quality_report(manifest(length=10), [calendar(10), calendar_header()])
    cells = [c for c in result['metrics']['grid'] if c['minutes'] == 15]
    assert len(cells) == 10 and all(c['planned'] == c['usable'] == 0 and c['coverage'] == 0 for c in cells)
    assert 'GRID_INSUFFICIENT' in result['reasons']


def test_complete_bars_with_no_quote_news_status_never_pass_joint_grid():
    bars = [row('BAR', at=OPEN + minute * MINUTE, row_id=minute * 10 + listing,
                listing_id=listing, logical_key=f'BAR:{listing}:{minute}',
                received=OPEN + (minute + 1) * MINUTE, available=OPEN + (minute + 1) * MINUTE,
                bar_end_ns=OPEN + (minute + 1) * MINUTE)
            for minute in range(30) for listing in range(1, 11)]
    result = api().quality_report(manifest(), [calendar(), calendar_header(), *bars])
    assert result['metrics']['raw']['coverage'] == 1
    assert all(c['usable'] == 0 for c in result['metrics']['grid'])
    assert result['outcome'] == 'INSUFFICIENTE'


@lru_cache(maxsize=1)
def positive():
    """Short SYNTHETIC sessions exercise the unchanged 20/10/99%/90% policy."""
    body = manifest(length=15, mode='DEMO')
    rows, serial, days = [], 0, []
    day = date(2026, 10, 12)
    while len(days) < 20:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    body['end_at_ns'] = OPEN + (days[-1] - days[0]).days * 86400 * SECOND + 15 * MINUTE
    body['cutoff_ns'] = body['end_at_ns'] + 10 * SECOND
    def add(family, payload, stamp, **changes):
        nonlocal serial
        serial += 1
        result = row(family, at=stamp, received=stamp, available=stamp, row_id=serial,
                     data_mode='DEMO', provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY',
                     payload=payload, **changes)
        rows.append(result)
        return result
    identities = {}
    for listing in range(1, 11):
        identities[listing] = add('IDENTITY', {'mic': 'XNAS'}, OPEN - 100 * SECOND,
                                  listing_id=listing, valid_from_ns=0, valid_to_ns=None, confirmed=1)
    for source in ('bls', 'fed', 'issuer'):
        document = add('CONTROL', {'metadata_kind': 'EVENT_DOCUMENT', 'original': {'source':
            {'bls': 'BLS', 'fed': 'FED', 'issuer': 'ISSUER_OFFICIAL'}[source], 'original_text': 'synthetic calendar'}},
            OPEN - 80 * SECOND, provider=source, capture=f'document-{source}', kind='BOOTSTRAP')
        for listing in (range(1, 11) if source == 'issuer' else [None]):
            add('EVENT', {'version': 'official-event-calendar-v1', 'source': source,
                         'coverage': 'ANNOUNCED_EVENTS_ONLY', 'authenticity_basis': 'LOCAL_OFFICIAL_COPY',
                         'document': {'id': document['id'], 'hash': document['payload_hash']}},
                OPEN - 70 * SECOND, provider=source, capture=f'document-{source}', listing_id=listing,
                event_type='EARNINGS' if source == 'issuer' else 'MACRO', logical_key=f'{source}:{listing}',
                scheduled_at_ns=body['end_at_ns'] + MINUTE, effective_at_ns=None)
    session_ids = {}
    for day in days:
        opening = OPEN + (day - days[0]).days * 86400 * SECOND
        closing, capture = opening + 15 * MINUTE, f'day-{day}'
        cal = add('CALENDAR', {'source': 'ALPACA_CALENDAR'}, OPEN - 60 * SECOND,
                  session_date=day.isoformat(), open_at_ns=opening, close_at_ns=closing, capture='metadata',
                  logical_key=f'calendar:{day}')
        session_ids[day.isoformat()] = cal['id']
        members = [{'listing_id': listing, 'identity_version_id': ident['id'], 'identity_hash': ident['payload_hash'],
                    'identity_publication_id': ident['publication_id'], 'eligible': True, 'reason_code': None}
                   for listing, ident in identities.items()]
        add('UNIVERSE', {'kind': 'PROSPECTIVE', 'session_date': day.isoformat(), 'members': members,
                        'open_at_ns': opening, 'close_at_ns': closing, 'requested_listing_ids': list(range(1, 11)),
                        'exclusions': [], 'calendar_version_id': cal['id'], 'calendar_hash': cal['payload_hash']},
            opening - 50 * SECOND, session_date=day.isoformat(), capture='metadata', logical_key=f'universe:{day}')
        subscriptions = {'market': {'bars': ['fixture'], 'quotes': ['fixture'], 'statuses': ['fixture']},
                         'news': {'news': ['fixture']}}
        add('CONTROL', {'listing_ids': list(range(1, 11)), 'subscriptions': subscriptions,
                        'continuity_policy': {'version': 'collector-continuity-v1',
                            'socket_silence_ns': 300 * SECOND, 'lease_ns': 300 * SECOND}},
            opening - 5 * SECOND, kind='CAPTURE_START', capture=capture)
        acks = [add('CONTROL', {'channel': channel, 'subscriptions': subscriptions[channel], 'received_at_ns': stamp},
                    stamp, kind='ACK', capture=capture)
                for channel, stamp in [('market', opening - 4 * SECOND), ('news', opening - 3 * SECOND)]]
        checkpoints = [add('EVENT', {'version': 'utp-status-checkpoint-v1', 'state': 'NORMAL',
                            'expires_at_ns': closing + 30 * SECOND, 'reason_code': None},
                           opening - 2 * SECOND, capture=capture, listing_id=listing,
                           event_type='RESUME', effective_at_ns=opening - 2 * SECOND,
                           logical_key=f'checkpoint:{day}:{listing}') for listing in range(1, 11)]
        add('CONTROL', {'metadata_kind': 'COLLECTOR_HANDSHAKE', 'continuity_attested': True,
            'barrier_at_ns': opening - SECOND,
            'ack_refs': [{'id': r['id'], 'hash': r['payload_hash'], 'publication_id': r['publication_id'],
                         'publication_hash': r['publication_hash']} for r in acks],
            'listings': [{'listing_id': r['listing_id'], 'checkpoint_id': r['id'], 'checkpoint_hash': r['payload_hash'],
                          'checkpoint_admission_id': r['admission_id'], 'snapshot_at_ns': opening - 2 * SECOND,
                          'expires_at_ns': closing + 30 * SECOND, 'status_refs': []} for r in checkpoints]},
            opening - SECOND, kind='BOOTSTRAP', capture=capture)
        for minute in range(15):
            start, end = opening + minute * MINUTE, opening + (minute + 1) * MINUTE
            decision = end + 10 * SECOND
            for listing in range(1, 11):
                add('BAR', {'source': 'STREAM', 'raw': {'o': 100, 'h': 102, 'l': 99, 'c': 101, 'v': 10, 'vw': 100.5}},
                    end + SECOND, event_time_ns=start, bar_end_ns=end, listing_id=listing, capture=capture,
                    logical_key=f'bar:{day}:{listing}:{minute}')
                add('QUOTE', {'source': 'STREAM', 'raw': {'bp': 100, 'ap': 101, 'bs': 1, 'as': 1, 'c': [], 'bx': 'Q', 'ax': 'Q', 'z': 'C'}},
                    decision, event_time_ns=decision - SECOND, listing_id=listing, capture=capture,
                    logical_key=f'quote:{day}:{listing}:{minute}')
            for stamp in (start, end, decision):
                add('CONTROL', {'metadata_kind': 'TRANSPORT_LIVENESS', 'channel': 'news',
                               'ping_sent_at_ns': stamp - 1, 'pong_received_at_ns': stamp}, stamp, kind='CLOCK', capture=capture)
    add('CONTROL', {'metadata_kind': 'CALENDAR', 'complete': True, 'start': days[0].isoformat(),
                   'end': days[-1].isoformat(), 'session_ids': session_ids, 'member_count': len(session_ids)},
        OPEN - 60 * SECOND, kind='BOOTSTRAP', capture='metadata')
    return body, rows


def test_positive_fixed_grid_function_is_ready_but_synthetic_is_non_idoneo():
    body, rows = positive()
    report = api().quality_report(body, rows)
    assert report['technical_result'] == 'READY', report['reasons']
    assert report['outcome'] == 'NON_IDONEO'
    assert report['metrics']['sessions'] == report['metrics']['eligible_sessions'] == 20
    assert report['metrics']['raw']['coverage'] == 1
    assert len(report['metrics']['grid']) == 600
    assert all(cell['planned'] == cell['usable'] > 0 for cell in report['metrics']['grid'])


def test_future_revisions_cannot_change_quality_at_saved_cutoff():
    body, rows = positive()
    future = row('BAR', received=body['cutoff_ns'] + 2, available=body['cutoff_ns'] + 3, row_id=999999,
                 payload={'future': 'not a valid bar'})
    assert api().quality_report(body, [*rows, future]) == api().quality_report(body, rows)


@pytest.mark.parametrize('defect', ['nineteen_sessions', 'nine_listings', 'benchmark_excluded',
                                  'all_quotes_stale', 'no_news_proof', 'no_status_checkpoint', 'late_policy'])
def test_joint_gate_rejects_missing_quality_even_with_complete_bars(defect):
    import copy
    body, rows = copy.deepcopy(positive())
    if defect == 'nineteen_sessions':
        body['end_at_ns'] -= 86400 * SECOND
    elif defect == 'nine_listings':
        body['listing_ids'].remove(1)
    elif defect == 'late_policy':
        body['policy']['created_at_ns'] = OPEN + 1
    elif defect == 'all_quotes_stale':
        for r in rows:
            if r.get('kind') == 'QUOTE':
                r['event_time_ns'] -= 3 * SECOND
    elif defect == 'no_news_proof':
        rows = [r for r in rows if r.get('kind') != 'CLOCK']
    elif defect == 'no_status_checkpoint':
        rows = [r for r in rows if r['payload'].get('version') != 'utp-status-checkpoint-v1']
    else:
        rows = [r for r in rows if not (r['table'] == 'intraday_identity_versions' and r['listing_id'] == 9)]
    report = api().quality_report(body, rows)
    assert report['technical_result'] == 'INSUFFICIENTE'
    assert report['metrics']['raw']['coverage'] == 1
    if defect == 'benchmark_excluded':
        cells = [c for c in report['metrics']['grid'] if c['listing_id'] == 9]
        assert len(cells) == 60 and all(c['planned'] > 0 and c['usable'] == 0 for c in cells)


def test_late_calendar_revision_never_erases_planned_past_session_grid():
    body = manifest()
    late = row('CALENDAR', row_id=3, at=OPEN + 40 * MINUTE, received=OPEN + 20 * MINUTE,
               available=OPEN + 20 * MINUTE, open_at_ns=OPEN + 40 * MINUTE, close_at_ns=OPEN + 70 * MINUTE,
               payload={'source': 'ALPACA_CALENDAR'})
    baseline = api().quality_report(body, [calendar(), calendar_header()])
    revised = api().quality_report(body, [calendar(), calendar_header(), late])
    assert revised['metrics']['raw']['planned'] == baseline['metrics']['raw']['planned'] == 300
    assert revised['metrics']['grid'] == baseline['metrics']['grid']


def test_planned_exclusion_cannot_be_dropped_from_manifest_request():
    universe = row('UNIVERSE', received=OPEN - 2, available=OPEN - 1,
                   payload={'kind': 'PROSPECTIVE', 'session_date': '2026-10-12', 'requested_listing_ids': list(range(1, 12)),
                            'members': [], 'exclusions': [{'listing_id': 11, 'reason_code': 'IDENTITY_UNVERIFIED'}]})
    report = api().quality_report(manifest(), [calendar(), calendar_header(), universe])
    assert report['metrics']['planned_listings'] == 11
    assert report['metrics']['raw']['planned'] == 330
    assert len([c for c in report['metrics']['grid'] if c['listing_id'] == 11]) == 3
    assert 'DATASET_SCOPE_INCOMPLETE' in report['reasons']


def test_missing_internal_news_proof_cannot_be_repaired_only_at_final_decision():
    body, rows = positive()
    amended = [r for r in rows if not (r.get('kind') == 'CLOCK' and r['available_at_ns'] in {OPEN, OPEN + MINUTE})]
    report = api().quality_report(body, amended)
    cell = next(c for c in report['metrics']['grid'] if c['listing_id'] == 1 and c['session_date'] == '2026-10-12' and c['minutes'] == 15)
    assert cell['usable'] == 0 and cell['exclusions']['NEWS_COVERAGE_UNKNOWN'] == 1


def test_halt_inside_group_followed_by_normal_is_excluded_and_reported_separately():
    body, rows = positive()
    capture = 'day-2026-10-12'
    statuses = [row('STATUS', row_id=800000 + i, received=OPEN + 4 * MINUTE,
                    available=OPEN + 4 * MINUTE, at=OPEN + (2 + i) * MINUTE, capture=capture,
                    data_mode='DEMO', provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY',
                    payload={'state': state, 'source': 'STREAM'}, listing_id=1)
                for i, state in enumerate(['HALTED', 'NORMAL'])]
    report = api().quality_report(body, [*rows, *statuses])
    cell = next(c for c in report['metrics']['grid'] if c['listing_id'] == 1 and c['session_date'] == '2026-10-12' and c['minutes'] == 15)
    assert cell['usable'] == 0
    assert report['metrics']['known_halts'][0]['occurrences'] == 1


def test_tied_start_index_agrees_with_pure_causal_reducer_receipts():
    import copy

    from backend.app.intraday.replay import capture_state_from_rows
    body, rows = copy.deepcopy(positive())
    first = next(r for r in rows if r.get('kind') == 'CAPTURE_START')
    first.pop('admission_id', None)
    first['publication_id'] = 100000
    invalid = row('CONTROL', row_id=999999, at=first['event_time_ns'], received=first['received_at_ns'],
                  available=first['available_at_ns'], capture='uninitialized', kind='CAPTURE_START',
                  data_mode='DEMO', provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY', payload=first['payload'], publication_id=1)
    invalid.pop('admission_id', None)
    rows.append(invalid)
    index = api()._Index(rows)
    cutoff = OPEN + MINUTE + 10 * SECOND
    controls = [r for r in rows if r['table'] == 'intraday_capture_events']
    events = [r for r in rows if r['table'] == 'intraday_event_versions']
    obs = [r for r in rows if r['table'] == 'intraday_observations' and r['available_at_ns'] <= cutoff]
    expected = capture_state_from_rows(controls, events, obs, cutoff_ns=cutoff)
    assert expected['state'] == 'LIVE'
    assert index.context(cutoff) == expected


def test_profile_hash_and_budget_attestation_cannot_be_fabricated():
    body = manifest()
    body['profile']['config']['max_symbols'] += 1
    with pytest.raises(ValueError, match='QUALITY_PROFILE_INVALID'):
        api().quality_report(body, [])


def test_finite_evaluation_rejects_unbounded_period_before_looping_dates():
    body = manifest()
    body['end_at_ns'] = OPEN + 367 * 86400 * SECOND
    body['cutoff_ns'] = body['end_at_ns']
    with pytest.raises(ValueError, match='DATASET_INVALID'):
        api().quality_report(body, [])


def test_overnight_checkpoint_halt_is_reported_without_new_status_ticks():
    import copy
    import hashlib

    from backend.app.intraday.contracts import canonical_json
    body, rows = copy.deepcopy(positive())
    checkpoint = next(r for r in rows if r['payload'].get('version') == 'utp-status-checkpoint-v1' and r['listing_id'] == 1)
    checkpoint['payload']['state'] = 'HALTED'
    checkpoint['payload_json'] = canonical_json(checkpoint['payload'])
    checkpoint['payload_hash'] = hashlib.sha256(checkpoint['payload_json'].encode()).hexdigest()
    boot = next(r for r in rows if r['payload'].get('metadata_kind') == 'COLLECTOR_HANDSHAKE')
    boot['payload']['listings'][0]['checkpoint_hash'] = checkpoint['payload_hash']
    boot['payload_json'] = canonical_json(boot['payload'])
    boot['payload_hash'] = hashlib.sha256(boot['payload_json'].encode()).hexdigest()
    report = api().quality_report(body, rows)
    known = report['metrics']['known_halts']
    assert known and known[0]['source'] == 'CHECKPOINT' and known[0]['carried_in']
    assert known[0]['first_version_id'] == checkpoint['id']
    resume = row('STATUS', row_id=900000, at=OPEN - SECOND // 2, received=OPEN - SECOND // 2,
                 available=OPEN - SECOND // 2, capture=checkpoint['capture_id'], listing_id=1,
                 data_mode='DEMO', provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY',
                 payload={'state': 'NORMAL', 'source': 'STREAM'})
    resumed = api().quality_report(body, [*rows, resume])
    assert not resumed['metrics']['known_halts']
