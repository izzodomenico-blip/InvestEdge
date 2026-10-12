from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_disabled_status_and_boot_are_read_only(client, monkeypatch):
    from backend.app.data_providers.alpaca_market import AlpacaMarketProvider
    from backend.app.database import get_connection
    monkeypatch.setattr(AlpacaMarketProvider, 'request_page', lambda *a, **k: pytest.fail('network'))
    with get_connection() as db:
        before = list(db.execute('SELECT * FROM intraday_collector_state'))
    response = client.get('/intraday/status')
    assert response.status_code == 200
    assert response.json()['enabled'] is False
    assert response.json()['collector']['state'] == 'STOPPED'
    with get_connection() as db:
        assert list(db.execute('SELECT * FROM intraday_collector_state')) == before


@pytest.mark.parametrize('route', ('metadata/refresh', 'backfill', 'snapshots', 'quality', 'collector/start', 'status-checkpoints'))
def test_intraday_validation_never_reflects_bad_inputs(client, route):
    secret = uuid.uuid4().hex
    response = client.post('/intraday/' + route, json={'api_secret_key': secret, 'url': 'https://example.invalid/' + secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert 'https://' not in response.text
    assert response.json()['detail']['reason_code'] == 'INVALID_REQUEST'


def test_status_rejects_unknown_query_without_echo(client):
    secret = uuid.uuid4().hex
    response = client.get('/intraday/status', params={'api_key': secret})
    assert response.status_code == 422 and secret not in response.text


def install_system(client, monkeypatch, s):
    from backend.app.api import intraday_routes
    from backend.app.database import get_connection
    from backend.app.intraday import handlers
    with get_connection() as db:
        s.db.backup(db)
    def make(connection, profile):
        value = copy.copy(s.archive.provider)
        value.connection, value.profile = connection, profile
        return value
    monkeypatch.setattr(handlers, 'make_provider', make)
    monkeypatch.setattr(handlers, 'get_settings', lambda: s.config)
    monkeypatch.setattr(intraday_routes, 'get_settings', lambda: s.config)
    monkeypatch.setattr(handlers, 'clock_ns', lambda: s.clock.now)
    monkeypatch.setattr(handlers, '_runtime', None)
    return s


def snapshot_body(s):
    from test_intraday_store import MINUTE, OPEN
    return {'profile_id': s.profile.profile_id, 'listing_ids': [s.listing], 'start_at_ns': OPEN,
            'end_at_ns': OPEN + 2 * MINUTE, 'cutoff_ns': s.clock.now, 'benchmarks': {}}


def test_empty_bootstrap_identity_then_research_backfill_is_explicit(client, monkeypatch):
    from test_intraday_identity import asset, system
    from test_intraday_store import MINUTE, OPEN

    from backend.app.database import get_connection
    s = install_system(client, monkeypatch, system())
    source = asset()
    s.queue.extend([[source], [], [{'date': '2026-10-12', 'open': '09:30', 'close': '16:00'}]])
    body = {'profile_id': s.profile.profile_id, 'profile': json.loads(s.profile.config_json),
            'start_date': '2026-10-12', 'end_date': '2026-10-12'}
    refresh = client.post('/intraday/metadata/refresh', json=body)
    assert refresh.status_code == 202
    job = refresh.json()
    assert job['kind'] == 'INTRADAY_METADATA' and job['status'] == 'SUCCEEDED', job
    assert len(s.requests) == 3
    assert client.get(f"/lab/jobs/{job['id']}").json() == job
    mapping = {'profile_id': s.profile.profile_id, 'listing_id': s.listing,
               'metadata_capture_id': job['result']['assets_capture_id'], 'broker_asset_id': source['id'],
               'capabilities': ['BAR', 'QUOTE', 'NEWS'], 'evidence_hash': 'b' * 64}
    preview = client.post('/intraday/identity/preview', json=mapping)
    assert preview.status_code == 200, preview.text
    with get_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM intraday_identity_versions').fetchone()[0] == 0
    applied = client.post('/intraday/identity/apply', json=mapping | {'confirmation_token': preview.json()['confirmation_token']})
    assert applied.status_code == 200 and applied.json()['status'] == 'CONFIRMED'
    assert client.post('/intraday/identity/apply', json=mapping | {'confirmation_token': preview.json()['confirmation_token']}).json() == applied.json()
    s.clock.now = OPEN + 30 * MINUTE
    s.queue.append({'bars': {'AAPL': [{'t': '2026-10-12T13:30:00Z', 'o': 100, 'h': 102, 'l': 99, 'c': 101, 'v': 10}]}, 'next_page_token': None})
    result = client.post('/intraday/backfill', json={'profile_id': s.profile.profile_id, 'listing_ids': [s.listing],
        'start_at_ns': OPEN, 'end_at_ns': OPEN + MINUTE, 'types': ['BAR'], 'asof_date': '2026-10-12'})
    assert result.status_code == 202 and result.json()['status'] == 'SUCCEEDED', result.text
    with get_connection() as db:
        row = db.execute('SELECT data_mode,provenance,replay_grade FROM intraday_observations').fetchone()
        assert tuple(row) == ('REAL', 'HISTORICAL_CURRENT', 'RESEARCH_ONLY')
    s.db.close()


def test_metadata_queued_deduplicated_polled_and_cancelled_without_http(client, monkeypatch):
    from test_intraday_identity import system

    from backend.app.api import intraday_routes, lab_routes
    from backend.app.lab.jobs import JobService
    s = install_system(client, monkeypatch, system())
    service = JobService('thread')
    monkeypatch.setattr(intraday_routes, 'get_job_service', lambda: service)
    monkeypatch.setattr(lab_routes, 'get_job_service', lambda: service)
    body = {'profile_id': s.profile.profile_id, 'profile': json.loads(s.profile.config_json),
            'start_date': '2026-10-12', 'end_date': '2026-10-12'}
    first = client.post('/intraday/metadata/refresh', json=body)
    assert first.status_code == 202 and first.json()['status'] == 'QUEUED'
    second = client.post('/intraday/metadata/refresh', json=body)
    assert first.json()['id'] == second.json()['id']
    assert not s.requests
    assert client.get('/lab/jobs/' + str(first.json()['id'])).json()['status'] == 'QUEUED'
    assert client.post('/lab/jobs/' + str(first.json()['id']) + '/cancel').json()['status'] == 'CANCELLED'
    assert client.post('/lab/jobs/' + str(first.json()['id']) + '/cancel').status_code == 409
    s.db.close()


@pytest.mark.parametrize('missing', ('identity', 'calendar'))
def test_backfill_missing_prerequisites_do_not_enqueue_or_request(client, monkeypatch, missing):
    from test_intraday_identity import asset, capture, confirm, system
    from test_intraday_store import MINUTE, OPEN
    s = system()
    row = asset()
    batch = capture(s, [row])
    if missing == 'calendar':
        confirm(s, row, batch)
    s.clock.now = OPEN + 30 * MINUTE
    install_system(client, monkeypatch, s)
    calls = len(s.requests)
    response = client.post('/intraday/backfill', json={'profile_id': s.profile.profile_id, 'listing_ids': [s.listing],
        'start_at_ns': OPEN, 'end_at_ns': OPEN + MINUTE, 'types': ['BAR'], 'asof_date': '2026-10-12'})
    assert response.status_code == 409
    assert response.json()['detail']['reason_code'] == ('IDENTITY_UNVERIFIED' if missing == 'identity' else 'CALENDAR_MISSING')
    assert len(s.requests) == calls
    assert not client.get('/lab/jobs').json()
    s.db.close()


def test_frozen_snapshot_quality_and_paginated_get_are_read_only(client, monkeypatch):
    from test_intraday_store import SECOND, event, prepared

    from backend.app.database import get_connection
    from backend.app.intraday.snapshots import SnapshotService
    s = prepared()
    SnapshotService(s.store).register_policy()
    s.store.persist((event(s),))
    install_system(client, monkeypatch, s)
    response = client.post('/intraday/snapshots', json=snapshot_body(s))
    assert response.status_code == 202 and response.json()['status'] == 'SUCCEEDED', response.text
    ident = response.json()['result']['snapshot_id']
    query = {'profile_id': s.profile.profile_id, 'input_type': 'BAR', 'limit': 1}
    baseline = client.get(f'/intraday/snapshots/{ident}', params=query)
    assert baseline.status_code == 200 and baseline.json()['total'] == 1
    assert len(baseline.json()['inputs']) == 1 and 'timeline' not in baseline.json()
    assert baseline.json()['report']['outcome'] == 'INSUFFICIENTE'
    quality = client.post('/intraday/quality', json={'profile_id': s.profile.profile_id, 'snapshot_id': ident})
    assert quality.status_code == 202 and quality.json()['status'] == 'SUCCEEDED'
    assert quality.json()['result']['report'] == baseline.json()['report']
    with get_connection() as db:
        assert db.execute('SELECT COUNT(*) FROM intraday_quality_reports').fetchone()[0] == 1
        newer = copy.copy(s.archive.provider)
        newer.connection = db
        from backend.app.intraday.store import IntradayStore
        s.clock.now += SECOND
        IntradayStore(newer, clock_ns=lambda: s.clock.now).persist((event(s, change={'c': 99}),))
        before = db.total_changes
        assert client.get(f'/intraday/snapshots/{ident}', params=query).json() == baseline.json()
        assert client.get('/intraday/news', params={'profile_id': s.profile.profile_id, 'cutoff_ns': s.clock.now}).status_code == 200
        assert db.total_changes == before
    calls = len(s.requests)
    assert client.get('/intraday/status', params={'profile_id': s.profile.profile_id}).status_code == 200
    assert len(s.requests) == calls
    assert client.post('/intraday/quality', json={'profile_id': s.profile.profile_id, 'snapshot_id': 99999}).status_code == 404
    s.db.close()


@pytest.mark.parametrize('route', ('snapshots/1', 'news'))
def test_get_invalid_namespace_is_sanitized_422(client, monkeypatch, route):
    from test_intraday_store import prepared
    s = install_system(client, monkeypatch, prepared())
    params = {'profile_id': s.profile.profile_id, 'data_mode': 'DEMO', 'provenance': 'CAPTURED', 'cutoff_ns': s.clock.now}
    if route.startswith('snapshots'):
        params.pop('cutoff_ns')
    response = client.get('/intraday/' + route, params=params)
    assert response.status_code == 422
    assert response.json()['detail']['reason_code'] == 'INVALID_REQUEST'
    s.db.close()


def test_news_reads_versions_links_cutoff_and_rights_only(client, monkeypatch):
    from test_intraday_news import article, setup_news
    from test_intraday_store import SECOND
    s = setup_news()
    s.news.persist([article()], received_at_ns=s.clock.now)
    early = s.clock.now
    s.clock.now += SECOND
    s.news.persist([article(headline='Reports quarterly earnings', updated_at='2026-10-12T12:00:02Z')], received_at_ns=s.clock.now)
    install_system(client, monkeypatch, s)
    query = {'profile_id': s.profile.profile_id, 'listing_id': s.listing, 'cutoff_ns': early}
    early_result = client.get('/intraday/news', params=query)
    assert early_result.status_code == 200 and early_result.json()['total'] == 1, early_result.text
    result = client.get('/intraday/news', params=query | {'cutoff_ns': s.clock.now, 'revisions': True, 'limit': 1})
    assert result.status_code == 200 and result.json()['total'] == 2
    assert len(result.json()['items']) == 1 and result.json()['items'][0]['links']
    assert result.json()['items'][0]['payload']['content'] is None
    assert result.json()['items'][0]['payload']['content_state'] == 'RIGHTS_UNATTESTED'
    s.db.close()


@pytest.mark.parametrize('input_type', ('IDENTITY', 'CALENDAR', 'CAPTURE'))
def test_snapshot_filters_metadata_tables(client, monkeypatch, input_type):
    from test_intraday_snapshots import freeze, service
    from test_intraday_store import event, prepared
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    saved = freeze(s)
    install_system(client, monkeypatch, s)
    response = client.get(f'/intraday/snapshots/{saved.snapshot_id}', params={'profile_id': s.profile.profile_id, 'input_type': input_type})
    assert response.status_code == 200 and response.json()['total'] > 0, response.text
    assert all('lease_nonce' not in row and 'payload_json' not in row for row in response.json()['inputs'])
    s.db.close()


def test_large_frozen_timeline_is_not_serialized_before_pagination_or_quality(client, monkeypatch):
    from test_intraday_news import article
    from test_intraday_snapshots import freeze, service
    from test_intraday_store import event, prepared

    from backend.app.intraday.news import NewsStore
    s = prepared(max_archive_bytes=50000000)
    service(s).register_policy()
    s.store.persist((event(s),))
    NewsStore(s.archive.provider, clock_ns=lambda: s.clock.now).persist(
        [article(id=1000 + i, headline='Local fixture ' + str(i) + 'x' * 3000) for i in range(80)],
        received_at_ns=s.clock.now)
    saved = freeze(s)
    assert len(json.dumps(service(s).read(saved.snapshot_id))) > 1048576
    install_system(client, monkeypatch, s)
    response = client.get(f'/intraday/snapshots/{saved.snapshot_id}', params={'profile_id': s.profile.profile_id, 'limit': 1})
    assert response.status_code == 200 and len(response.json()['inputs']) == 1, response.text
    quality = client.post('/intraday/quality', json={'profile_id': s.profile.profile_id, 'snapshot_id': saved.snapshot_id})
    assert quality.status_code == 202 and quality.json()['status'] == 'SUCCEEDED', quality.text
    s.db.close()


@pytest.mark.parametrize('kind', ('NEWS', 'CORPORATE_ACTION'))
def test_nonmarket_backfill_chunks_eight_days_under_a_total_page_budget(client, monkeypatch, kind):
    from test_intraday_identity import asset, capture, confirm, ns, system
    from test_intraday_store import MINUTE, OPEN
    s = system()
    source = asset()
    batch = capture(s, [source])
    confirm(s, source, batch, valid_from_ns=ns('2026-10-01T00:00:00Z'), validity_source='OFFICIAL_NOTICE')
    s.calendar.record([{'date': '2026-10-12', 'open': '09:30', 'close': '16:00'}],
                      start='2026-10-04', end='2026-10-12', received_at_ns=s.clock.now)
    s.clock.now = OPEN + 30 * MINUTE
    install_system(client, monkeypatch, s)
    payload = {'news': [], 'next_page_token': None} if kind == 'NEWS' else {'corporate_actions': {}, 'next_page_token': None}
    s.queue.extend([payload, payload])
    before = len(s.requests)
    body = {'profile_id': s.profile.profile_id, 'listing_ids': [s.listing], 'start_at_ns': ns('2026-10-04T13:30:00Z'),
            'end_at_ns': OPEN + MINUTE, 'types': [kind], 'asof_date': '2026-10-12', 'max_pages': 2}
    response = client.post('/intraday/backfill', json=body)
    assert response.status_code == 202 and response.json()['status'] == 'SUCCEEDED', response.text
    assert len(s.requests) - before == 2
    assert response.json()['result']['types'][kind]['pages'] == 2
    s.queue.append(payload)
    limited = client.post('/intraday/backfill', json=body | {'max_pages': 1, 'start_at_ns': body['start_at_ns'] + 1})
    assert limited.status_code == 202 and limited.json()['status'] == 'FAILED'
    assert limited.json()['error_code'] == 'PAGE_LIMIT'
    assert len(s.requests) - before == 3
    s.db.close()


def test_large_news_archive_still_returns_small_page(client, monkeypatch):
    from test_intraday_news import article, setup_news

    from backend.app.intraday.news import NewsStore
    s = setup_news()
    s.news.persist([article()], received_at_ns=s.clock.now)
    install_system(client, monkeypatch, s)
    actual = NewsStore.read_as_of
    def large(self, **kwargs):
        rows = actual(self, **kwargs)
        return rows * 2000
    monkeypatch.setattr(NewsStore, 'read_as_of', large)
    response = client.get('/intraday/news', params={'profile_id': s.profile.profile_id, 'cutoff_ns': s.clock.now, 'limit': 1})
    assert response.status_code == 200 and response.json()['total'] == 2000, response.text
    assert len(response.json()['items']) == 1
    s.db.close()


@pytest.mark.parametrize('period', ('empty', 'after_cutoff'))
def test_invalid_snapshot_period_fails_before_enqueue(client, monkeypatch, period):
    from test_intraday_snapshots import service
    from test_intraday_store import prepared
    s = prepared()
    service(s).register_policy()
    install_system(client, monkeypatch, s)
    body = snapshot_body(s)
    if period == 'empty':
        body['end_at_ns'] = body['start_at_ns']
    else:
        body['end_at_ns'] = s.clock.now + 1
    response = client.post('/intraday/snapshots', json=body)
    assert response.status_code == 422, response.text
    assert not client.get('/lab/jobs').json()
    s.db.close()


def test_news_backfill_complete_is_success_not_tuple_serialization_error(client, monkeypatch):
    from test_intraday_news import article
    from test_intraday_store import MINUTE, OPEN, prepared
    s = install_system(client, monkeypatch, prepared())
    s.queue.append({'news': [article(created_at='2026-10-12T13:30:00Z', updated_at='2026-10-12T13:30:00Z')], 'next_page_token': None})
    response = client.post('/intraday/backfill', json={'profile_id': s.profile.profile_id, 'listing_ids': [s.listing],
        'start_at_ns': OPEN, 'end_at_ns': OPEN + MINUTE, 'types': ['NEWS'], 'asof_date': '2026-10-12'})
    assert response.status_code == 202 and response.json()['status'] == 'SUCCEEDED', response.text
    assert response.json()['result']['types']['NEWS']['news_count'] == 1
    s.db.close()


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    pytest.fail('offline collector did not reach expected state')


def runtime_system(client, monkeypatch):
    from test_intraday_collector import Factory, setup

    from backend.app.intraday import handlers
    from backend.app.intraday.collector import Collector
    s = install_system(client, monkeypatch, setup())
    class OwnedCollector(Collector):
        def __init__(self, provider, **kwargs):
            self.owner = threading.get_ident()
            factory = Factory(provider.connection)
            if threading.current_thread().name == 'intraday-collector':
                s.factory = factory
            super().__init__(provider, socket_factory=factory, clock_ns=lambda: s.clock.now,
                             monotonic_ns=lambda: s.clock.now)
        def receive(self, *args, **kwargs):
            assert threading.get_ident() == self.owner
            return super().receive(*args, **kwargs)
        def stop(self):
            assert threading.get_ident() == self.owner
            return super().stop()
    monkeypatch.setattr(handlers, 'Collector', OwnedCollector)
    return s


def test_collector_owned_thread_connects_acks_checkpoint_live_and_idempotent_stop(client, monkeypatch):
    from test_intraday_events import authority, checkpoint
    from test_intraday_store import SECOND

    from backend.app.database import get_connection
    from backend.app.intraday import handlers
    s = runtime_system(client, monkeypatch)
    body = {'profile_id': s.profile.profile_id, 'listing_ids': [s.listing], 'benchmark_listing_ids': []}
    first = client.post('/intraday/collector/start', json=body)
    assert first.status_code == 200 and first.json()['state'] == 'CONNECTING', first.text
    capture_id = first.json()['capture_id']
    assert client.post('/intraday/collector/start', json=body).json()['capture_id'] == capture_id
    assert len(s.factory.calls) == 2
    assert client.post('/intraday/collector/start', json=body | {'listing_ids': [s.listing, 999]}).status_code == 409
    fixture = Path(__file__).parent / 'fixtures/market_data/alpaca_stream_replay.jsonl'
    for line in fixture.read_text().splitlines():
        record = json.loads(line)
        s.factory.sockets[record['channel']].frames.append(json.dumps(record['rows']))
    def acked():
        with get_connection() as db:
            return db.execute("SELECT COUNT(*) FROM intraday_capture_events WHERE kind='ACK'").fetchone()[0] >= 2
    wait_until(acked)
    s.clock.now += 2 * SECOND
    document = checkpoint(s)
    request = {'profile_id': s.profile.profile_id, 'capture_id': capture_id,
               'document': document, 'authority': asdict(authority(document))}
    response = client.post('/intraday/status-checkpoints', json=request)
    assert response.status_code == 200 and response.json()['live_eligible'] is False, response.text
    wait_until(lambda: handlers._runtime.status()['state'] == 'LIVE')
    status = client.get('/intraday/status', params={'profile_id': s.profile.profile_id}).json()
    assert status['collector']['state'] == 'LIVE'
    assert status['collector']['g1_data'] == 'INSUFFICIENTE'
    stop = client.post('/intraday/collector/stop', json={'profile_id': s.profile.profile_id})
    assert stop.status_code == 200 and stop.json()['state'] == 'STOPPED'
    assert client.post('/intraday/collector/stop', json={'profile_id': s.profile.profile_id}).json() == stop.json()
    assert all(socket.closed for socket in s.factory.sockets.values())
    with get_connection() as db:
        row = db.execute('SELECT owner_nonce,connection_count FROM intraday_collector_state').fetchone()
        assert tuple(row) == (None, 0)
    s.db.close()


def test_runtime_terminal_failure_keeps_reason_and_releases_lease(client, monkeypatch):
    from backend.app.database import get_connection
    from backend.app.intraday import handlers
    s = runtime_system(client, monkeypatch)
    body = {'profile_id': s.profile.profile_id, 'listing_ids': [s.listing], 'benchmark_listing_ids': []}
    response = client.post('/intraday/collector/start', json=body)
    assert response.status_code == 200
    s.factory.sockets['market'].frames.append('[{"T":"error","code":402,"msg":"opaque"}]')
    wait_until(lambda: handlers._runtime.status()['state'] == 'FAILED')
    status = client.get('/intraday/status').json()['collector']
    assert status['state'] == 'FAILED' and status['reason_code'] == 'AUTHENTICATION_FAILED'
    assert 'opaque' not in json.dumps(status)
    with get_connection() as db:
        assert db.execute('SELECT owner_nonce FROM intraday_collector_state').fetchone()[0] is None
    handlers._runtime.stop()
    s.db.close()


def test_start_timeout_stops_after_current_open_releases_lease_and_keeps_failure(client, monkeypatch):
    from test_intraday_collector import Socket, setup

    from backend.app.database import get_connection
    from backend.app.intraday import handlers
    s = install_system(client, monkeypatch, setup())
    runtime = handlers.CollectorRuntime()
    monkeypatch.setattr(handlers, '_runtime', runtime)
    entered, release = threading.Event(), threading.Event()
    calls, sockets = [], []
    def open_one(**kwargs):
        calls.append(kwargs['channel'])
        entered.set()
        assert release.wait(5)
        socket = Socket()
        sockets.append(socket)
        return socket
    def deadline(timeout):
        assert timeout >= 20  # Both governed opens must fit the normal deadline.
        assert entered.wait(2)
        return False
    monkeypatch.setattr(handlers, 'open_socket', open_one)
    monkeypatch.setattr(runtime._ready, 'wait', deadline)
    try:
        response = client.post('/intraday/collector/start', json={'profile_id': s.profile.profile_id, 'listing_ids': [s.listing]})
        assert response.status_code == 409 and response.json()['detail']['reason_code'] == 'STREAM_FAILED'
    finally:
        release.set()
        runtime.stop()
    assert calls == ['market'] and all(socket.closed for socket in sockets)
    assert runtime.status()['state'] == 'FAILED' and runtime.status()['reason_code'] == 'STREAM_FAILED'
    with get_connection() as db:
        assert db.execute('SELECT owner_nonce FROM intraday_collector_state').fetchone()[0] is None
    s.db.close()


@pytest.mark.parametrize('namespace', (
    {'data_mode': 'DEMO', 'provenance': 'SYNTHETIC', 'replay_grade': 'RESEARCH_ONLY'},
    {'data_mode': 'REAL', 'provenance': 'HISTORICAL_CURRENT', 'replay_grade': 'RESEARCH_ONLY'},
))
def test_data_api_never_falls_back_across_namespace(client, monkeypatch, namespace):
    from test_intraday_news import article
    from test_intraday_snapshots import freeze, service
    from test_intraday_store import event, prepared

    from backend.app.intraday.news import NewsStore
    s = prepared()
    service(s).register_policy()
    s.store.persist((event(s),))
    NewsStore(s.archive.provider, clock_ns=lambda: s.clock.now).persist([article()], received_at_ns=s.clock.now)
    saved = freeze(s)
    install_system(client, monkeypatch, s)
    query = {'profile_id': s.profile.profile_id, **namespace}
    assert client.get(f'/intraday/snapshots/{saved.snapshot_id}', params=query).status_code == 409
    assert client.post('/intraday/quality', json=query | {'snapshot_id': saved.snapshot_id}).status_code == 409
    response = client.get('/intraday/news', params=query | {'cutoff_ns': s.clock.now})
    assert response.status_code == 200 and response.json()['total'] == 0
    assert response.json()['namespace'][1:] == list(namespace.values())
    s.db.close()


def test_status_does_not_reflect_old_public_value_that_is_now_a_credential(client, monkeypatch):
    from test_intraday_store import prepared

    from backend.app.intraday import handlers
    s = install_system(client, monkeypatch, prepared())
    private = uuid.uuid4().hex
    s.config = replace(s.config, alpaca_api_secret_key=private)
    s.archive.provider.settings = s.config
    state = {'state': 'STOPPED', 'capture_id': private, 'reason_code': None, 'pending_events': 0,
             'listing_states': {}, 'g1_data': 'INSUFFICIENTE'}
    monkeypatch.setattr(handlers, '_runtime', SimpleNamespace(_key=(s.profile.profile_id, (s.listing,)), status=lambda: state, stop=lambda: None))
    response = client.get('/intraday/status', params={'profile_id': s.profile.profile_id})
    assert response.status_code == 422
    assert private not in response.text
    s.db.close()


def test_status_shows_published_gaps_but_never_unpublished_raw(client, monkeypatch):
    from test_intraday_store import MINUTE, OPEN, prepared
    s = prepared()
    with s.archive.transaction():
        run = s.archive.begin_run()
    payload = {'reason_code': 'CAPTURE_GAP', 'start_at_ns': OPEN, 'end_at_ns': OPEN + MINUTE}
    published = s.store.append_capture('GAP', payload, run_id=run, capture_id=uuid.uuid4().hex,
                                      lease_nonce=uuid.uuid4().hex, received_at_ns=s.clock.now)
    begin = s.store._begin
    calls = 0
    def fail_publication():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('publication unavailable')
        return begin()
    monkeypatch.setattr(s.store, '_begin', fail_publication)
    with pytest.raises(RuntimeError, match='publication unavailable'):
        s.store.append_capture('GAP', payload, run_id=run, capture_id=uuid.uuid4().hex,
                               lease_nonce=uuid.uuid4().hex, received_at_ns=s.clock.now)
    install_system(client, monkeypatch, s)
    response = client.get('/intraday/status', params={'profile_id': s.profile.profile_id})
    assert response.status_code == 200
    gaps = response.json()['capture_gaps']
    assert [gap['id'] for gap in gaps] == [published]
    assert gaps[0]['reason_code'] == 'CAPTURE_GAP' and gaps[0]['publication_id'] > 0
    assert 'lease_nonce' not in json.dumps(gaps)
    s.db.close()


@pytest.mark.parametrize('stale_runtime', (False, True))
def test_stop_rejects_collector_owned_by_another_runtime(client, monkeypatch, stale_runtime):
    from test_intraday_collector import setup

    from backend.app.intraday import handlers
    s = setup()
    s.collector.start([s.listing])
    install_system(client, monkeypatch, s)
    if stale_runtime:
        old = handlers.CollectorRuntime()
        old._key = (s.profile.profile_id, (s.listing,))
        old._state['capture_id'] = uuid.uuid4().hex
        monkeypatch.setattr(handlers, '_runtime', old)
    response = client.post('/intraday/collector/stop', json={'profile_id': s.profile.profile_id})
    assert response.status_code == 409
    assert response.json()['detail']['reason_code'] == 'COLLECTOR_ALREADY_OWNED'
    status = client.get('/intraday/status', params={'profile_id': s.profile.profile_id}).json()['collector']
    assert status['capture_id'] == s.collector.capture_id
    s.collector.stop()
    s.db.close()


def test_news_missing_is_distinct_from_verified_research_covered_zero(client, monkeypatch):
    from test_intraday_store import MINUTE, OPEN, prepared
    s = install_system(client, monkeypatch, prepared())
    query = {'profile_id': s.profile.profile_id, 'listing_id': s.listing, 'cutoff_ns': s.clock.now,
             'start_at_ns': OPEN, 'end_at_ns': OPEN + MINUTE,
             'data_mode': 'REAL', 'provenance': 'HISTORICAL_CURRENT', 'replay_grade': 'RESEARCH_ONLY'}
    missing = client.get('/intraday/news', params=query)
    assert missing.status_code == 200
    assert missing.json()['coverage']['state'] == 'MISSING'
    s.queue.append({'news': [], 'next_page_token': None})
    body = {key: query[key] for key in ('profile_id', 'start_at_ns', 'end_at_ns', 'data_mode', 'provenance', 'replay_grade')}
    response = client.post('/intraday/backfill', json=body | {'listing_ids': [s.listing], 'types': ['NEWS'], 'asof_date': '2026-10-12'})
    assert response.status_code == 202 and response.json()['status'] == 'SUCCEEDED'
    covered = client.get('/intraday/news', params=query)
    assert covered.status_code == 200 and covered.json()['total'] == 0
    assert covered.json()['coverage']['state'] == 'COVERED_ZERO'
    assert covered.json()['coverage']['publication_id'] > 0
    assert covered.json()['coverage']['continuity_attested'] is False
    assert client.get('/intraday/news', params=query | {'start_at_ns': OPEN - MINUTE}).json()['coverage']['state'] == 'MISSING'
    s.db.close()


def test_news_coverage_rejects_incomplete_or_future_period(client, monkeypatch):
    from test_intraday_store import OPEN, prepared
    s = install_system(client, monkeypatch, prepared())
    query = {'profile_id': s.profile.profile_id, 'cutoff_ns': s.clock.now, 'start_at_ns': OPEN}
    assert client.get('/intraday/news', params=query).status_code == 422
    assert client.get('/intraday/news', params=query | {'end_at_ns': s.clock.now + 1}).status_code == 422
    s.db.close()
