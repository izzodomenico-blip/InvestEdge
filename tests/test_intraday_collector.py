from __future__ import annotations

import importlib
import json
from collections import deque
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest
from test_intraday_events import authority, checkpoint
from test_intraday_store import MINUTE, OPEN, SECOND, event, prepared


class Socket:
    def __init__(self):
        self.frames = deque()
        self.sent = []
        self.closed = False
        self.pong = True

    def send(self, frame):
        self.sent.append(json.loads(frame))

    def recv(self, timeout):
        if not self.frames:
            raise TimeoutError
        value = self.frames.popleft()
        if isinstance(value, Exception):
            raise value
        return value

    def ping(self):
        return self

    def wait(self, timeout):
        return self.pong

    def close(self):
        self.closed = True

    def has_pending(self):
        return bool(self.frames)


class Factory:
    def __init__(self, connection):
        self.connection = connection
        self.calls = []
        self.sockets = {}

    def __call__(self, **kwargs):
        assert not self.connection.in_transaction
        self.calls.append(kwargs)
        socket = Socket()
        self.sockets[kwargs['channel']] = socket
        return socket


def setup(**changes):
    s = prepared(second=changes.pop('second', False), profile_overrides={
        'attested_capabilities': ('bars', 'updated_bars', 'quotes', 'news', 'assets', 'calendar',
                                  'corporate_actions', 'status', 'luld'), 'max_connections': 2})
    s.config = replace(s.config, **{'enable_alpaca_collector': True, 'alpaca_max_connections': 2, **changes})
    s.archive.provider.settings = s.archive.settings = s.config
    s.events = importlib.import_module('backend.app.intraday.events').EventStore(
        s.archive.provider, clock_ns=lambda: s.clock.now)
    s.factory = Factory(s.db)
    module = importlib.import_module('backend.app.intraday.collector')
    s.collector = module.Collector(s.archive.provider, socket_factory=s.factory,
                                  clock_ns=lambda: s.clock.now, monotonic_ns=lambda: s.clock.now)
    return s


def deliver(s, channel, rows):
    s.factory.sockets[channel].frames.append(json.dumps(rows))
    return s.collector.receive(channel)


def handshake(s):
    fixture = Path(__file__).parent / 'fixtures/market_data/alpaca_stream_replay.jsonl'
    for line in fixture.read_text().splitlines():
        record = json.loads(line)
        deliver(s, record['channel'], record['rows'])


def boot(s, *, action=None):
    s.clock.now += 2 * SECOND
    document = checkpoint(s, action=action)
    return s.events.import_status_checkpoint(document, authority=authority(document),
        received_at_ns=s.clock.now, capture_id=s.collector.capture_id)


def rows(s, kind):
    return s.db.execute('SELECT * FROM intraday_capture_events WHERE kind=? ORDER BY id', (kind,)).fetchall()


def quote(s):
    return {'T': 'q', 'S': 'AAPL', **event(s, kind='QUOTE', at=s.clock.now).payload['raw']}


def status(s, code='H', at=None):
    from backend.app.data_providers.alpaca_market import format_ns
    return {'T': 's', 'S': 'AAPL', 'sc': code, 'sm': 'status', 'rc': 'T1', 'rm': 'reason',
            't': format_ns(s.clock.now if at is None else at), 'z': 'C'}


def test_constructor_imports_never_connect_and_disabled_start_has_no_side_effect():
    s = setup(enable_alpaca_collector=False)
    assert not s.factory.calls and not rows(s, 'CAPTURE_START')
    with pytest.raises(ValueError, match='REAL_DATA_DISABLED'):
        s.collector.start((s.listing,))
    assert not s.factory.calls and not rows(s, 'CAPTURE_START')


def test_start_stop_idempotent_with_private_auth_and_no_transaction_during_network():
    s = setup()
    s.collector.start((s.listing,))
    capture = s.collector.capture_id
    s.collector.start((s.listing,))
    assert s.collector.capture_id == capture and len(s.factory.calls) == 2
    handshake(s)
    assert all(socket.sent[0]['action'] == 'auth' for socket in s.factory.sockets.values())
    assert s.factory.sockets['market'].sent[1]['updatedBars'] == ['AAPL']
    assert s.collector.status()['state'] == 'CONNECTING'
    s.collector.stop()
    s.collector.stop()
    assert all(socket.closed for socket in s.factory.sockets.values())
    assert s.collector.status()['state'] == 'STOPPED' and len(rows(s, 'STOP')) == 1
    public = '\n'.join(row['payload_json'] for row in s.db.execute('SELECT payload_json FROM intraday_capture_events'))
    assert all(value not in public for value in (s.config.alpaca_api_key_id, s.config.alpaca_api_secret_key))
    assert not s.db.in_transaction


@pytest.mark.parametrize('missing', ['updatedBars', 'quotes', 'statuses', 'lulds'])
def test_partial_ack_never_connects_or_promotes(missing):
    s = setup()
    s.collector.start((s.listing,))
    deliver(s, 'market', [{'T': 'success', 'msg': 'connected'}])
    deliver(s, 'market', [{'T': 'success', 'msg': 'authenticated'}])
    ack = {'T': 'subscription', **{k: ['AAPL'] for k in ('bars', 'updatedBars', 'quotes', 'statuses', 'lulds')}}
    ack[missing] = []
    deliver(s, 'market', [ack])
    assert s.collector.status()['state'] != 'LIVE' and not rows(s, 'ACK')


def test_checkpoint_before_ack_does_not_resurrect_normal():
    s = setup()
    s.collector.start((s.listing,))
    doc = checkpoint(s)
    deliver(s, 'market', [status(s, 'H')])
    s.collector.drain()
    s.clock.now += 2 * SECOND
    handshake(s)
    s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now,
                                     capture_id=s.collector.capture_id)
    s.collector.reconcile()
    assert s.collector.status()['state'] != 'LIVE'
    assert s.collector.status()['listing_states'][s.listing]['state'] == 'UNKNOWN'


def test_post_ack_checkpoint_then_all_backlog_status_controls_live_eligibility():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    deliver(s, 'market', [status(s, 'H')])
    s.collector.reconcile()
    assert s.collector.status()['state'] != 'LIVE'
    s.clock.now += SECOND
    s.collector.drain()
    s.collector.reconcile()
    result = s.collector.status()
    assert result['state'] == 'LIVE'
    assert result['listing_states'][s.listing]['state'] == 'HALTED'
    assert not result['listing_states'][s.listing]['live_eligible']
    assert rows(s, 'BOOTSTRAP')[-1]['capture_id'] == s.collector.capture_id


def test_normal_checkpoint_with_both_acks_becomes_live_only_after_bootstrap_proof():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    assert s.collector.status()['state'] == 'CONNECTING'
    boot(s)
    s.collector.reconcile()
    assert s.collector.status()['state'] == 'LIVE'
    assert s.collector.status()['listing_states'][s.listing]['live_eligible']
    s.clock.now += 31 * SECOND
    s.collector.reconcile()
    assert s.collector.status()['state'] != 'LIVE'


def test_receive_prequeue_and_raw_commit_pre_admission_preserve_cutoffs(monkeypatch):
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    stamp = s.clock.now
    deliver(s, 'market', [quote(s)])
    assert not s.store.read_as_of('QUOTE', cutoff_ns=stamp)
    s.clock.now += SECOND
    original = s.collector.store.admit
    def admit(ids):
        assert not s.db.in_transaction
        raw = s.db.execute('SELECT received_at_ns,available_at_ns FROM intraday_observations WHERE id=?', (ids[0],)).fetchone()
        assert raw['received_at_ns'] == stamp and raw['available_at_ns'] is None
        s.clock.now += SECOND
        return original(ids)
    monkeypatch.setattr(s.collector.store, 'admit', admit)
    s.collector.drain()
    assert not s.store.read_as_of('QUOTE', cutoff_ns=stamp + SECOND)
    row = s.store.read_as_of('QUOTE', cutoff_ns=s.clock.now)[0]
    assert row['available_at_ns'] == stamp + 2 * SECOND and row['received_at_ns'] == stamp


def test_symbol_limit_counts_benchmarks_before_any_socket():
    s = setup(second=True, alpaca_max_symbols=1)
    with pytest.raises(ValueError, match='SYMBOL_LIMIT'):
        s.collector.start((s.listing,), benchmark_listing_ids=(s.second,))
    assert not s.factory.calls


def test_market_and_news_connections_count_together_before_socket():
    s = setup(alpaca_max_connections=1)
    with pytest.raises(ValueError, match='CONNECTION_LIMIT'):
        s.collector.start((s.listing,))
    assert not s.factory.calls


def test_duplicate_owner_and_expired_nonce_are_fenced():
    s = setup()
    s.collector.start((s.listing,))
    module = importlib.import_module('backend.app.intraday.collector')
    other = module.Collector(s.archive.provider, socket_factory=s.factory,
        clock_ns=lambda: s.clock.now, monotonic_ns=lambda: s.clock.now)
    with pytest.raises(ValueError, match='COLLECTOR_ALREADY_OWNED'):
        other.start((s.listing,))
    old = s.collector.capture_id
    s.clock.now += (s.config.alpaca_collector_lease_seconds + 1) * SECOND
    other.start((s.listing,))
    assert other.capture_id != old
    with pytest.raises(ValueError, match='LEASE_LOST'):
        s.collector.drain()
    s.collector.stop()
    assert other.status()['state'] == 'CONNECTING'
    assert any(json.loads(row['payload_json'])['reason_code'] == 'RESTART' for row in rows(s, 'GAP'))


@pytest.mark.parametrize('reason', ['QUEUE_OVERFLOW', 'SOCKET_SILENCE', 'CLOCK_SKEW'])
def test_overflow_silence_and_clock_rollback_record_gap(reason):
    s = setup(alpaca_max_queue_events=1 if reason == 'QUEUE_OVERFLOW' else 1000)
    s.collector.start((s.listing,))
    handshake(s)
    if reason == 'QUEUE_OVERFLOW':
        deliver(s, 'market', [quote(s)])
        deliver(s, 'market', [quote(s)])
    elif reason == 'CLOCK_SKEW':
        s.clock.now -= SECOND
        s.collector.step()
    else:
        s.clock.now += (s.config.alpaca_stream_silence_seconds + 1) * SECOND
        s.collector.step()
    assert s.collector.status()['state'] != 'LIVE'
    assert any(json.loads(row['payload_json'])['reason_code'] == reason for row in rows(s, 'GAP'))
    assert all(socket.closed for socket in s.factory.sockets.values())


def test_disconnect_bounded_reconnect_new_capture_and_resubscription():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    s.collector.reconcile()
    old = s.collector.capture_id
    s.factory.sockets['market'].frames.append(ConnectionError('private remote close'))
    s.collector.receive('market')
    assert s.collector.status()['state'] == 'BACKOFF'
    s.clock.now += 2 * SECOND
    s.collector.step()
    assert s.collector.capture_id != old and s.collector.status()['state'] == 'CONNECTING'
    handshake(s)
    s.collector.reconcile()
    assert s.collector.status()['state'] != 'LIVE'
    assert len(rows(s, 'GAP')) >= 1 and len(rows(s, 'CAPTURE_START')) == 2
    assert len(s.factory.calls) == 4


@pytest.mark.parametrize('credential', ['alpaca_api_key_id', 'alpaca_api_secret_key'])
def test_secret_echo_hard_stops_and_nothing_sensitive_is_persisted(credential, caplog):
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    value = getattr(s.config, credential)
    deliver(s, 'market', [{'T': 'error', 'code': 500, 'msg': value}])
    assert s.collector.status()['state'] == 'FAILED'
    public = json.dumps([tuple(row) for row in s.db.execute('SELECT * FROM intraday_capture_events')])
    assert value not in public + caplog.text + str(s.collector.status())


def test_stream_budget_shared_with_rest_and_every_socket_attempt_reserved():
    s = setup()
    before = s.db.execute("SELECT SUM(used_count) FROM provider_usage_windows WHERE provider='alpaca' AND window_kind='MINUTE'").fetchone()[0]
    s.collector.start((s.listing,))
    after = s.db.execute("SELECT SUM(used_count) FROM provider_usage_windows WHERE provider='alpaca' AND window_kind='MINUTE'").fetchone()[0]
    assert after - before == 2
    assert len(s.factory.calls) == 2


def test_tied_halt_resume_is_restrictive():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    deliver(s, 'market', [status(s, 'H'), status(s, 'T')])
    s.collector.drain()
    s.collector.reconcile()
    assert s.collector.status()['listing_states'][s.listing]['state'] == 'HALTED'


def test_updated_bars_are_causal_and_never_projected_daily():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    raw = event(s, at=OPEN + MINUTE).payload['raw']
    deliver(s, 'market', [{'T': 'b', 'S': 'AAPL', **raw}])
    s.collector.drain()
    stamp = s.clock.now
    first = s.store.read_as_of('BAR', cutoff_ns=stamp)
    s.clock.now += SECOND
    deliver(s, 'market', [{'T': 'u', 'S': 'AAPL', **raw, 'c': 100}])
    s.collector.drain()
    assert s.store.read_as_of('BAR', cutoff_ns=stamp) == first
    assert s.store.read_as_of('BAR', cutoff_ns=s.clock.now)[0]['payload']['raw']['c'] == 100
    assert s.db.execute('SELECT count(*) FROM price_history').fetchone()[0] == 0
    assert s.db.execute('SELECT count(*) FROM features_daily').fetchone()[0] == 0


def test_reconcile_checks_silence_without_depending_on_step():
    s = setup(alpaca_stream_silence_seconds=5)
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    s.collector.reconcile()
    assert s.collector.status()['state'] == 'LIVE'
    s.clock.now += 6 * SECOND
    s.collector.reconcile()
    assert s.collector.status()['state'] != 'LIVE'
    assert any(json.loads(row['payload_json'])['reason_code'] == 'SOCKET_SILENCE' for row in rows(s, 'GAP'))


def test_quiet_news_with_timely_pongs_keeps_transport_alive_and_data_time_separate():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    s.collector.reconcile()
    news_frame_at = s.collector._last_frame['news']
    for _ in range(4):
        s.clock.now += 10 * SECOND
        s.factory.sockets['market'].frames.append(json.dumps([quote(s)]))
        s.collector.step()
        assert s.collector.status()['state'] not in {'BACKOFF', 'FAILED'}
    assert s.collector._last_frame['news'] == news_frame_at
    assert not rows(s, 'GAP')


def test_terminal_backlog_error_does_not_reopen_sockets():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    bad = quote(s)
    bad.pop('ap')
    deliver(s, 'market', [bad])
    s.factory.sockets['market'].frames.append(ConnectionError('opaque'))
    s.collector.receive('market')
    s.clock.now += 2 * SECOND
    s.collector.step()
    assert s.collector.status()['state'] == 'FAILED'
    assert len(s.factory.calls) == 2 and not s.collector.sockets


def test_bootstrap_barrier_consumes_all_frames_already_buffered_at_cutoff():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    s.factory.sockets['market'].frames.extend([json.dumps([quote(s)]), json.dumps([status(s, 'H')])])
    s.collector.step()
    assert s.collector.status()['listing_states'][s.listing]['state'] == 'HALTED'
    assert not s.collector.status()['listing_states'][s.listing]['live_eligible']


def test_status_after_lease_expiry_cannot_return_live_eligibility():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    s.collector.reconcile()
    s.clock.now += 61 * SECOND
    result = s.collector.status()
    assert result['state'] != 'LIVE'
    assert not any(row['live_eligible'] for row in result['listing_states'].values())


def test_failed_bootstrap_publication_never_leaves_live_listing(monkeypatch):
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    original = s.collector._log
    def log(kind, payload, **kwargs):
        if kind == 'BOOTSTRAP':
            raise importlib.import_module('backend.app.data_providers.alpaca_stream').StreamError('ARCHIVE_LIMIT')
        return original(kind, payload, **kwargs)
    monkeypatch.setattr(s.collector, '_log', log)
    with suppress(ValueError):
        s.collector.reconcile()
    result = s.collector.status()
    assert result['state'] != 'LIVE'
    assert not any(row['live_eligible'] for row in result['listing_states'].values())


def test_reconnect_reacquires_account_slots_before_new_socket():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    s.factory.sockets['market'].frames.append(ConnectionError('opaque'))
    s.collector.receive('market')
    other_profile = replace(s.profile, quote_conditions=('R',))
    s.db.execute('INSERT INTO intraday_feed_profiles(id,provider,feed,config_json,created_at_ns) VALUES (?,?,?,?,?)',
                 (other_profile.profile_id, 'alpaca', 'sip', other_profile.config_json, s.clock.now))
    s.db.execute('''INSERT INTO intraday_collector_state(profile_id,data_mode,state,owner_nonce,
        lease_expires_at_ns,connection_count) VALUES (?, 'REAL','CONNECTING','other',?,2)''',
        (other_profile.profile_id, s.clock.now + 60 * SECOND))
    s.db.commit()
    s.clock.now += 2 * SECOND
    s.collector.step()
    assert len(s.factory.calls) == 2
    assert s.db.execute('SELECT SUM(connection_count) FROM intraday_collector_state').fetchone()[0] == 2


def test_slow_connect_cannot_authenticate_after_lease_expiry():
    s = setup()
    opened = []
    def factory(**kwargs):
        socket = s.factory(**kwargs)
        opened.append(socket)
        s.clock.now += 61 * SECOND
        return socket
    s.collector.socket_factory = factory
    s.collector.start((s.listing,))
    assert len(opened) == 1 and opened[0].closed
    assert not opened[0].sent


def test_checkpoint_does_not_graft_future_identity_on_old_stream_symbol():
    from test_intraday_identity import asset, capture, confirm
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    original = s.collector.identities[s.listing]
    renamed = asset(symbol='RENAMED', asset_id=original['broker_asset_id'])
    s.clock.now += SECOND
    batch = capture(s, [renamed])
    s.db.execute("UPDATE instrument_listings SET ticker='RENAMED' WHERE id=?", (s.listing,))
    s.db.commit()
    confirm(s, renamed, batch)
    deliver(s, 'market', [quote(s)])
    s.collector.drain()
    assert s.collector.status()['state'] == 'FAILED'
    assert not s.store.read_as_of('QUOTE', cutoff_ns=s.clock.now)


def test_missing_status_attestation_never_allows_live_from_external_checkpoint():
    s = setup()
    s.collector.profile = replace(s.profile, attested_capabilities=tuple(
        value for value in s.profile.attested_capabilities if value != 'luld'))
    with pytest.raises(ValueError):
        s.collector.start((s.listing,))
    assert not s.factory.calls


def test_news_received_and_admitted_with_body_rights_denied():
    from backend.app.data_providers.alpaca_market import format_ns
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    stamp = s.clock.now
    raw = {'T': 'n', 'id': 1, 'source': 'benzinga', 'headline': 'Company releases earnings',
        'symbols': ['AAPL'], 'created_at': format_ns(stamp - SECOND), 'updated_at': format_ns(stamp),
        'summary': 'restricted summary', 'content': '<p>restricted body</p>'}
    deliver(s, 'news', [raw])
    assert not s.collector.news.read_as_of(cutoff_ns=stamp)
    s.clock.now += SECOND
    s.collector.drain()
    saved = s.collector.news.read_as_of(cutoff_ns=s.clock.now)[0]
    assert saved['received_at_ns'] == stamp and saved['available_at_ns'] == s.clock.now
    assert saved['capture_id'] == s.collector.capture_id
    assert saved['payload']['summary'] is None and saved['payload']['content'] is None
    assert 'restricted body' not in saved['payload_json']


def test_takeover_between_raw_and_publication_preserves_orphan_without_visibility(monkeypatch):
    s = setup()
    s.collector.start((s.listing,))
    original = s.collector.store._begin
    calls = []
    def begin():
        calls.append(True)
        if len(calls) == 2:
            s.clock.now += 61 * SECOND
        return original()
    monkeypatch.setattr(s.collector.store, '_begin', begin)
    with pytest.raises(ValueError, match='LEASE_LOST'):
        s.collector._log('ACK', {'channel': 'market', 'subscriptions': s.collector.expected['market']})
    assert rows(s, 'ACK')
    assert not [row for row in s.store.read_capture_as_of(cutoff_ns=s.clock.now) if row['kind'] == 'ACK']
    assert not s.db.in_transaction


def test_expired_lease_cannot_write_news_quarantine():
    from backend.app.data_providers.alpaca_market import format_ns
    s = setup()
    s.collector.start((s.listing,))
    stamp = s.clock.now
    s.clock.now += 61 * SECOND
    raw = {'T': 'n', 'id': 1, 'source': 'benzinga', 'headline': 'Company releases earnings',
        'symbols': ['AAPL'], 'created_at': format_ns(stamp), 'updated_at': format_ns(s.clock.now + SECOND)}
    before = s.db.total_changes
    with pytest.raises(ValueError, match='LEASE_LOST'):
        s.collector.news.persist((raw,), received_at_ns=s.clock.now, capture_id=s.collector.capture_id)
    assert s.db.total_changes == before and not s.db.in_transaction


def test_quota_uses_actual_sqlite_file_and_keeps_gap_stop_reserve(tmp_path):
    import sqlite3
    s = setup()
    path = tmp_path / 'capture.db'
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    s.db.backup(connection)
    s.db = connection
    s.archive.provider.connection = connection
    s.factory = Factory(connection)
    s.collector = importlib.import_module('backend.app.intraday.collector').Collector(
        s.archive.provider, socket_factory=s.factory, clock_ns=lambda: s.clock.now,
        monotonic_ns=lambda: s.clock.now)
    s.collector.start((s.listing,))
    handshake(s)
    usage, _ = s.collector.archive_size()
    cap = s.config.alpaca_max_archive_bytes
    # Simulates on-disk WAL pressure on the actual DB, not Settings.database_path.
    auxiliary = Path(str(path) + '-wal')
    auxiliary.write_bytes(bytes(cap - s.config.alpaca_stream_control_reserve_bytes - usage + 4096))
    deliver(s, 'market', [quote(s)])
    s.collector.drain()
    assert s.collector.status()['state'] == 'FAILED'
    assert any(json.loads(row['payload_json'])['reason_code'] == 'ARCHIVE_LIMIT' for row in rows(s, 'GAP'))
    assert rows(s, 'STOP')
    assert s.collector.archive_size()[0] <= cap
    connection.close()
    auxiliary.unlink(missing_ok=True)


def test_previous_collector_schema_migrates_preserving_rows_and_fk():
    import sqlite3

    from backend.app.database import MIGRATIONS
    connection = sqlite3.connect(':memory:')
    connection.execute('''CREATE TABLE intraday_collector_state(id INTEGER PRIMARY KEY,profile_id TEXT,
        data_mode TEXT,state TEXT,owner_nonce TEXT,lease_expires_at_ns INTEGER)''')
    connection.execute("INSERT INTO intraday_collector_state VALUES(1,'fixture','REAL','CONNECTING','old',100)")
    for _, statement in MIGRATIONS['intraday_collector_state']:
        connection.execute(statement)
    assert connection.execute('SELECT id,state,owner_nonce,capture_id,ingest_run_id,connection_count FROM intraday_collector_state').fetchone() == (
        1, 'CONNECTING', 'old', None, None, 0)
    assert not connection.execute('PRAGMA foreign_key_check').fetchall()
    connection.close()


def test_cross_channel_barrier_never_promotes_with_halt_already_received(monkeypatch):
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    boot(s)
    news = s.factory.sockets['news']
    original = news.recv
    inserted = []
    def receive(timeout):
        if not inserted:
            inserted.append(True)
            s.factory.sockets['market'].frames.append(json.dumps([status(s, 'H')]))
        return original(timeout)
    monkeypatch.setattr(news, 'recv', receive)
    s.collector.reconcile()
    result = s.collector.status()
    assert result['state'] != 'LIVE'
    assert not any(row['live_eligible'] for row in result['listing_states'].values())
    s.collector.step()
    assert s.collector.status()['listing_states'][s.listing]['state'] == 'HALTED'


def test_clean_stop_drains_data_already_in_transport_queue():
    from backend.app.data_providers.alpaca_stream import ReceivedFrame
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    stamp = s.clock.now
    s.factory.sockets['market'].frames.append(ReceivedFrame(json.dumps([quote(s)]), stamp))
    s.clock.now += SECOND
    s.collector.stop()
    saved = s.store.read_as_of('QUOTE', cutoff_ns=s.clock.now)
    assert len(saved) == 1 and saved[0]['received_at_ns'] == stamp
    assert not rows(s, 'GAP')


def healthy_quiet_period(s):
    s.collector.start((s.listing,))
    handshake(s)
    for _ in range(180):
        s.clock.now += 10 * SECOND
        s.collector.step()
    return s.clock.now


def test_quiet_news_gap_starts_at_last_published_transport_proof():
    s = setup()
    healthy = healthy_quiet_period(s)
    prefix = s.store.read_capture_as_of(cutoff_ns=healthy)
    s.clock.now += SECOND
    s.factory.sockets['market'].frames.append(ConnectionError('opaque'))
    s.collector.receive('market')
    gap = json.loads(rows(s, 'GAP')[-1]['payload_json'])
    assert gap['start_at_ns'] == healthy and gap['end_at_ns'] == healthy + SECOND
    assert s.store.read_capture_as_of(cutoff_ns=healthy) == prefix
    visible = {row['id']: row for row in prefix}
    for ref in gap['transport_proofs'].values():
        row = visible[ref['id']]
        assert ref == {key: row[key] for key in ('id', 'payload_hash', 'publication_id', 'publication_hash')}
        assert row['payload']['metadata_kind'] == 'TRANSPORT_LIVENESS'
        assert row['payload']['pong_received_at_ns'] == healthy


def test_restart_gap_recovers_frozen_transport_proofs_from_previous_capture():
    s = setup()
    healthy = healthy_quiet_period(s)
    previous = s.collector.capture_id
    prefix = s.store.read_capture_as_of(cutoff_ns=healthy, capture_id=previous)
    s.clock.now += 61 * SECOND
    other = importlib.import_module('backend.app.intraday.collector').Collector(
        s.archive.provider, socket_factory=s.factory, clock_ns=lambda: s.clock.now,
        monotonic_ns=lambda: s.clock.now)
    other.start((s.listing,))
    gap = json.loads(rows(s, 'GAP')[-1]['payload_json'])
    assert gap['reason_code'] == 'RESTART'
    assert gap['start_at_ns'] == healthy and gap['end_at_ns'] == s.clock.now
    assert set(gap['transport_proofs']) == {'market', 'news'}
    assert not gap['missing_transport_channels']
    assert s.store.read_capture_as_of(cutoff_ns=healthy, capture_id=previous) == prefix


def test_restart_without_ack_uses_published_capture_start_conservatively():
    s = setup()
    start = s.clock.now
    s.collector.start((s.listing,))
    s.clock.now += 61 * SECOND
    other = importlib.import_module('backend.app.intraday.collector').Collector(
        s.archive.provider, socket_factory=s.factory, clock_ns=lambda: s.clock.now,
        monotonic_ns=lambda: s.clock.now)
    other.start((s.listing,))
    gap = json.loads(rows(s, 'GAP')[-1]['payload_json'])
    assert gap['start_at_ns'] == start
    assert gap['missing_transport_channels'] == ['market', 'news']
    assert gap['capture_start_proof']['id'] == rows(s, 'CAPTURE_START')[0]['id']


def test_pong_without_durable_publication_cannot_move_gap_start(monkeypatch):
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    ack_at = s.clock.now
    original = s.collector._log
    def log(kind, payload, **kwargs):
        if kind == 'CLOCK' and payload.get('metadata_kind') == 'TRANSPORT_LIVENESS':
            raise importlib.import_module('backend.app.data_providers.alpaca_stream').StreamError('ARCHIVE_LIMIT')
        return original(kind, payload, **kwargs)
    monkeypatch.setattr(s.collector, '_log', log)
    s.clock.now += 10 * SECOND
    s.collector.step()
    assert s.collector.status()['state'] != 'CONNECTING'
    gap = json.loads(rows(s, 'GAP')[-1]['payload_json'])
    assert gap['start_at_ns'] == ack_at and gap['reason_code'] == 'ARCHIVE_LIMIT'


def test_overflow_after_pong_keeps_unadmitted_backlog_inside_gap():
    s = setup(alpaca_max_queue_events=1)
    s.collector.start((s.listing,))
    handshake(s)
    pending_at = s.clock.now
    deliver(s, 'market', [quote(s)])
    s.clock.now += 10 * SECOND
    s.factory.sockets['market'].frames.append(json.dumps([quote(s)]))
    s.collector.step()
    gap = json.loads(rows(s, 'GAP')[-1]['payload_json'])
    assert gap['reason_code'] == 'QUEUE_OVERFLOW'
    assert gap['start_at_ns'] <= pending_at
    assert gap['pending_received_at_ns'] == pending_at


def test_restart_keeps_orphan_raw_inside_gap_even_after_transport_liveness():
    s = setup()
    s.collector.start((s.listing,))
    handshake(s)
    pending_at = s.clock.now
    raw = event(s, kind='QUOTE', at=pending_at)
    raw = replace(raw, capture_id=s.collector.capture_id)
    ids = s.collector.store.persist((raw,), run_id=s.collector.run_id, admit=False)
    s.clock.now += 10 * SECOND
    s.collector.step()
    s.clock.now += 61 * SECOND
    other = importlib.import_module('backend.app.intraday.collector').Collector(
        s.archive.provider, socket_factory=s.factory, clock_ns=lambda: s.clock.now,
        monotonic_ns=lambda: s.clock.now)
    other.start((s.listing,))
    gap = json.loads(rows(s, 'GAP')[-1]['payload_json'])
    assert gap['start_at_ns'] <= pending_at
    assert gap['orphan_raw_proof']['id'] == ids[0]
    assert gap['orphan_raw_proof']['table'] == 'intraday_observations'
