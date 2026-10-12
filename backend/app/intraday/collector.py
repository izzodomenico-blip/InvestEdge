"""Explicit bounded collector, driven by its owner through step/receive/drain.

No boot hook, lab worker, orders or implicit live capture. Socket factory and both
clocks are injectable. LIVE describes current capture continuity; G1_DATA remains
an independent dataset verdict. Restart/reconnect always creates a new epoch.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import time
import uuid
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.app.data_providers.alpaca_events import decode_status_row
from backend.app.data_providers.alpaca_market import _ns, decode_market_row
from backend.app.data_providers.alpaca_metadata import check_ns
from backend.app.data_providers.alpaca_news import NewsRights
from backend.app.data_providers.alpaca_stream import ReceivedFrame, StreamError, decode_frame, open_socket
from backend.app.intraday.calendar import session_as_of
from backend.app.intraday.contracts import EventEnvelope, canonical_json
from backend.app.intraday.events import EventStore
from backend.app.intraday.identity import read_identity_as_of
from backend.app.intraday.news import NewsStore
from backend.app.intraday.profiles import account_budget_policy, configuration_reason
from backend.app.intraday.store import IntradayStore
from backend.app.services.provider_budget_service import ProviderBudgetExceeded

SECOND = 1_000_000_000
_MARKET = {'bars': 'bars', 'updated_bars': 'updatedBars', 'quotes': 'quotes',
           'status': 'statuses', 'luld': 'lulds'}
_RANK = {'NORMAL': 1, 'UNKNOWN': 2, 'QUOTATION_ONLY': 3, 'HALTED': 4}


class _LeaseConnection:
    """Fence every evidence/run DML and commit under SQLite's writer lock.

    Also covers NewsStore quarantine/publication and final operational updates,
    which otherwise bypass IntradayStore._begin. Reads and rollback stay available.
    """
    def __init__(self, connection, guard):
        self._connection, self._guard = connection, guard

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def execute(self, sql, parameters=()):
        command = sql.lstrip().split(None, 1)[0].upper()
        try:
            if command in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}:
                if not self._connection.in_transaction:
                    self._connection.execute('BEGIN IMMEDIATE')
                self._guard()
            result = self._connection.execute(sql, parameters)
            if command == 'BEGIN':
                self._guard()
            return result
        except Exception:
            self._connection.rollback()
            raise

    def commit(self):
        try:
            if self._connection.in_transaction:
                self._guard()
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise


class Collector:
    def __init__(self, provider, *, socket_factory=None, clock_ns=time.time_ns,
                 monotonic_ns=time.monotonic_ns, news_rights=None, data_mode='REAL',
                 provenance='CAPTURED', replay_grade='STRICT_PIT'):
        self.provider, self.connection, self.profile = provider, provider.connection, provider.profile
        self.settings = provider.settings
        self.clock_ns, self.monotonic_ns = clock_ns, monotonic_ns
        self.socket_factory = socket_factory or open_socket
        self.rights = news_rights or NewsRights()
        self.data_mode, self.provenance, self.replay_grade = data_mode, provenance, replay_grade
        self.owner_nonce = self.capture_id = self.run_id = None
        self.state, self.reason_code = 'STOPPED', None
        self.queue, self.sockets, self.acks, self.authenticated = deque(), {}, {}, set()
        self.connected, self.listing_states = set(), {}
        self._last_wall = self._last_mono = None
        self._emergency, self._terminal, self._reconnects = False, False, 0
        self._next_attempt_ns, self._intake, self._bootstrap_digest = 0, 0, None
        self._unfenced_store = IntradayStore(provider, clock_ns=self._storage_now, data_mode=data_mode,
                                            provenance=provenance, replay_grade=replay_grade)
        storage_provider = copy.copy(provider)
        storage_provider.connection = _LeaseConnection(self.connection, self._write_guard)
        self.store = IntradayStore(storage_provider, clock_ns=self._storage_now, data_mode=data_mode,
                                   provenance=provenance, replay_grade=replay_grade)
        self.news = NewsStore(storage_provider, clock_ns=self._storage_now, rights=self.rights,
                             data_mode=data_mode, provenance=provenance, replay_grade=replay_grade)
        self.events = EventStore(storage_provider, clock_ns=self._storage_now, data_mode=data_mode,
                                 provenance=provenance, replay_grade=replay_grade)
        self._original_page_limit = None

    def _storage_now(self):
        value = self.clock_ns()
        check_ns(value)
        return max(value, self._last_wall or 0)

    def _tick(self):
        wall, mono = self.clock_ns(), self.monotonic_ns()
        check_ns(wall)
        check_ns(mono)
        if self._last_wall is not None:
            delta = abs((wall - self._last_wall) - (mono - self._last_mono))
            if wall < self._last_wall or mono < self._last_mono or delta > self.settings.alpaca_stream_clock_skew_seconds * SECOND:
                self._fail('CLOCK_SKEW', terminal=True, detail={'observed_clock_ns': wall})
                return None
        self._last_wall, self._last_mono = wall, mono
        return wall

    def _owned(self, now=None):
        row = self.connection.execute('''SELECT * FROM intraday_collector_state
            WHERE profile_id=? AND data_mode=?''', (self.profile.profile_id, self.data_mode)).fetchone()
        return (row is not None and self.owner_nonce is not None and row['owner_nonce'] == self.owner_nonce
                and row['capture_id'] == self.capture_id and row['ingest_run_id'] == self.run_id
                and row['lease_expires_at_ns'] > (self._storage_now() if now is None else now))

    def _write_guard(self):
        if not self._owned():
            raise StreamError('LEASE_LOST')
        self._quota(emergency=self._emergency)

    def archive_size(self):
        allocated = self.connection.execute('PRAGMA page_count').fetchone()[0] * self.connection.execute('PRAGMA page_size').fetchone()[0]
        row = next((row for row in self.connection.execute('PRAGMA database_list') if row[1] == 'main'), None)
        if row is None or not row[2]:
            return allocated, 0
        path = Path(row[2])
        base = path.stat().st_size if path.exists() else 0
        auxiliary = sum(Path(str(path) + suffix).stat().st_size for suffix in ('-wal', '-journal', '-shm')
                        if Path(str(path) + suffix).exists())
        return max(allocated, base) + auxiliary, auxiliary

    def _quota(self, expected=0, *, emergency=False):
        cap = min(self.profile.max_archive_bytes, self.settings.alpaca_max_archive_bytes)
        reserve = self.settings.alpaca_stream_control_reserve_bytes
        usage, auxiliary = self.archive_size()
        threshold = cap if emergency else cap - reserve
        if cap <= 0 or reserve < 65536 or reserve >= cap or usage + expected > threshold:
            raise StreamError('ARCHIVE_LIMIT')
        # Reserve a second page image for rollback/WAL, plus emergency control log.
        page = self.connection.execute('PRAGMA page_size').fetchone()[0]
        pages = ((threshold - auxiliary - 65536) // page if emergency
                 else (threshold - auxiliary) // (2 * page))
        current = self.connection.execute('PRAGMA page_count').fetchone()[0]
        if pages < current:
            raise StreamError('ARCHIVE_LIMIT')
        if self._original_page_limit is None:
            self._original_page_limit = self.connection.execute('PRAGMA max_page_count').fetchone()[0]
        self.connection.execute(f'PRAGMA max_page_count={pages}')

    def _precheck(self, listing_ids, benchmarks):
        if (self.data_mode, self.provenance, self.replay_grade) != ('REAL', 'CAPTURED', 'STRICT_PIT'):
            raise StreamError('PROFILE_INVALID')
        if not self.settings.enable_alpaca_collector:
            raise StreamError('REAL_DATA_DISABLED')
        reason = configuration_reason(self.settings, self.profile, 'bars')
        if reason is not None:
            raise StreamError(reason)
        if self.profile.feed not in {'sip', 'iex'} or not self.profile.ready_for_capture:
            raise StreamError('PROFILE_INVALID')
        required = set(self.profile.required_capabilities) | {'bars', 'updated_bars', 'quotes', 'news'}
        if not required <= set(self.profile.attested_capabilities):
            raise StreamError('FEED_NOT_ENTITLED')
        caps = ('alpaca_collector_lease_seconds', 'alpaca_stream_silence_seconds',
                'alpaca_stream_backoff_seconds', 'alpaca_stream_backoff_cap_seconds',
                'alpaca_stream_clock_skew_seconds')
        if (any(type(getattr(self.settings, key)) is not int or not 0 < getattr(self.settings, key) <= 300 for key in caps)
            or not 0 <= self.settings.alpaca_stream_max_reconnects <= 10
            or self.settings.alpaca_collector_lease_seconds <= 10
            or self.settings.alpaca_stream_backoff_seconds > self.settings.alpaca_stream_backoff_cap_seconds):
            raise StreamError('PROFILE_INVALID')
        input_cap = min(10_000, self.settings.alpaca_max_symbols, self.profile.max_symbols)
        try:
            planned = tuple(islice(iter(listing_ids), input_cap + 1))
            benchmark = tuple(islice(iter(benchmarks), input_cap + 1))
        except TypeError:
            raise StreamError('IDENTITY_UNVERIFIED') from None
        if len(planned) > input_cap or len(benchmark) > input_cap:
            raise StreamError('SYMBOL_LIMIT')
        values = planned + benchmark
        if not values or any(type(value) is not int or value <= 0 for value in values):
            raise StreamError('IDENTITY_UNVERIFIED')
        values = tuple(sorted(set(values)))
        if len(values) > min(self.settings.alpaca_max_symbols, self.profile.max_symbols):
            raise StreamError('SYMBOL_LIMIT')
        if min(self.settings.alpaca_max_connections, self.profile.max_connections) < 2:
            raise StreamError('CONNECTION_LIMIT')
        now = self._storage_now()
        self.identities = {}
        metadata_scope = {'profile_id': self.profile.profile_id, 'data_mode': self.data_mode,
                          'provenance': 'CAPTURED' if self.data_mode == 'REAL' else 'SYNTHETIC',
                          'replay_grade': 'STRICT_PIT' if self.data_mode == 'REAL' else 'RESEARCH_ONLY'}
        for listing in values:
            identity = read_identity_as_of(self.connection, listing, now, now, **metadata_scope)
            if identity is None or not {'BAR', 'QUOTE', 'NEWS'} <= set(identity['payload']['capabilities']):
                raise StreamError('IDENTITY_UNVERIFIED')
            self.identities[listing] = identity
        if len({row['ticker'] for row in self.identities.values()}) != len(values):
            raise StreamError('IDENTITY_UNVERIFIED')
        date = datetime.fromtimestamp(now // SECOND, UTC).astimezone(ZoneInfo('America/New_York')).date().isoformat()
        if session_as_of(self.connection, date, now, **metadata_scope) is None:
            raise StreamError('CALENDAR_MISSING')
        self.listing_ids, self.symbols = values, tuple(sorted(row['ticker'] for row in self.identities.values()))
        self.expected = {'market': {wire: list(self.symbols) for cap, wire in _MARKET.items()
                                   if cap in self.profile.attested_capabilities}, 'news': {'news': list(self.symbols)}}
        self._quota(expected=65536)

    def _claim(self):
        now = self._storage_now()
        if self.connection.in_transaction:
            raise StreamError('PROFILE_INVALID')
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            active = self.connection.execute('''SELECT state.*, profiles.config_json FROM intraday_collector_state state
                JOIN intraday_feed_profiles profiles ON profiles.id=state.profile_id
                WHERE owner_nonce IS NOT NULL AND lease_expires_at_ns>?''', (now,)).fetchall()
            if any(row['profile_id'] == self.profile.profile_id for row in active):
                raise StreamError('COLLECTOR_ALREADY_OWNED')
            limit = min(self.settings.alpaca_max_connections, self.profile.max_connections,
                        *(json.loads(row['config_json'])['max_connections'] for row in active))
            if sum(row['connection_count'] for row in active) + 2 > limit:
                raise StreamError('CONNECTION_LIMIT')
            previous = self.connection.execute('SELECT * FROM intraday_collector_state WHERE profile_id=? AND data_mode=?',
                                               (self.profile.profile_id, self.data_mode)).fetchone()
            self.owner_nonce, self.capture_id = uuid.uuid4().hex, uuid.uuid4().hex
            self.run_id = self._unfenced_store.archive.begin_run()
            self.connection.execute('''INSERT INTO intraday_collector_state
                (profile_id,data_mode,state,owner_nonce,lease_expires_at_ns,capture_id,ingest_run_id,connection_count)
                VALUES (?,?,'CONNECTING',?,?,?,?,2)
                ON CONFLICT(profile_id,data_mode) DO UPDATE SET state='CONNECTING',owner_nonce=excluded.owner_nonce,
                    lease_expires_at_ns=excluded.lease_expires_at_ns,capture_id=excluded.capture_id,
                    ingest_run_id=excluded.ingest_run_id,connection_count=2''',
                (self.profile.profile_id, self.data_mode, self.owner_nonce,
                 now + self.settings.alpaca_collector_lease_seconds * SECOND, self.capture_id, self.run_id))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        if previous is not None and previous['owner_nonce'] is not None and previous['capture_id'] and previous['ingest_run_id']:
            self._log('GAP', {'reason_code': 'RESTART', **self._gap_bounds(previous['capture_id'], now)},
                      capture_id=previous['capture_id'], run_id=previous['ingest_run_id'])
        self._log('CAPTURE_START', {'listing_ids': list(self.listing_ids), 'subscriptions': self.expected,
                                  'continuity_attested': False})

    def _log(self, kind, payload, *, listing_id=None, capture_id=None, run_id=None):
        if self._emergency and (kind not in {'GAP', 'CLOCK', 'STOP'} or len(canonical_json(payload).encode()) > 4096):
            raise StreamError('ARCHIVE_LIMIT')
        return self.store.append_capture(kind, {'version': 'collector-v1', **payload},
            run_id=self.run_id if run_id is None else run_id, capture_id=capture_id or self.capture_id,
            lease_nonce=self.owner_nonce, received_at_ns=self._storage_now(), listing_id=listing_id)

    def _set_state(self, state, *, connections=None):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            now = self._storage_now()
            if not self._owned(now):
                raise StreamError('LEASE_LOST')
            self.connection.execute('''UPDATE intraday_collector_state SET state=?,lease_expires_at_ns=?,
                connection_count=COALESCE(?,connection_count) WHERE profile_id=? AND data_mode=? AND owner_nonce=?''',
                (state, now + self.settings.alpaca_collector_lease_seconds * SECOND, connections,
                 self.profile.profile_id, self.data_mode, self.owner_nonce))
            self.connection.commit()
            self.state = state
        except Exception:
            self.connection.rollback()
            raise

    def _open(self):
        self.authenticated, self.connected, self.acks = set(), set(), {}
        self.listing_states, self._bootstrap_digest = {}, None
        self._opened_at, self._last_frame, self._last_ping, self._last_transport = {}, {}, {}, {}
        for channel in ('market', 'news'):
            if not self._owned():
                raise StreamError('LEASE_LOST')
            if self.connection.in_transaction:
                raise StreamError('PROFILE_INVALID')
            policy = account_budget_policy(self.settings, self.profile)
            budget = self.provider.transport.budget_manager
            stamp = datetime.fromtimestamp(self._storage_now() // SECOND, UTC)
            fingerprint = hashlib.sha256(canonical_json({'profile_id': self.profile.profile_id,
                'channel': channel, 'operation': 'STREAM_CONNECT'}).encode()).hexdigest()
            reservation = budget.reserve(self.connection, policy, 'alpaca', 'STREAM_CONNECT', fingerprint, stamp)
            try:
                if not self._owned():
                    raise StreamError('LEASE_LOST')
                socket = self.socket_factory(channel=channel, feed=self.profile.feed,
                    max_size=min(1_048_576, self.profile.max_frame_bytes, self.settings.alpaca_max_frame_bytes),
                    max_queue=min(10_000, self.profile.max_queue_events, self.settings.alpaca_max_queue_events),
                    open_timeout=min(10, self.settings.provider_http_connect_timeout_seconds), close_timeout=2,
                    received_clock_ns=self.clock_ns)
                self.sockets[channel] = socket
                if not self._owned():
                    raise StreamError('LEASE_LOST')
                # Only ever in memory; private logger is disabled by real factory.
                socket.send(json.dumps({'action': 'auth', 'key': self.settings.alpaca_api_key_id,
                                        'secret': self.settings.alpaca_api_secret_key}))
                now = self._storage_now()
                self._opened_at[channel] = self._last_frame[channel] = self._last_ping[channel] = now
                self._last_transport[channel] = now
                budget.complete(self.connection, reservation, 'SUCCEEDED', None, 0, None)
            except StreamError as exc:
                cooldown = None
                if exc.code == 'RATE_LIMITED':
                    delay = max(1, min(60, self.settings.provider_retry_after_cap_seconds, exc.retry_after_seconds))
                    cooldown = datetime.fromtimestamp(self._storage_now() // SECOND, UTC) + timedelta(seconds=delay)
                    budget.restrict(self.connection, 'alpaca', datetime.fromtimestamp(self._storage_now() // SECOND, UTC),
                                    minute_limit=None, remaining=None, cooldown_until=cooldown, policy=policy)
                budget.complete(self.connection, reservation, 'RATE_LIMITED' if cooldown else 'REJECTED',
                                429 if cooldown else None, 0, cooldown)
                raise
            except Exception:
                budget.complete(self.connection, reservation, 'REJECTED', None, 0, None)
                raise StreamError('STREAM_FAILED') from None

    def start(self, listing_ids, *, benchmark_listing_ids=()):
        if self.sockets and self._owned():
            if tuple(sorted(set(tuple(listing_ids) + tuple(benchmark_listing_ids)))) != self.listing_ids:
                raise StreamError('COLLECTOR_ALREADY_OWNED')
            return self.status()
        if self._terminal:
            raise StreamError(self.reason_code)
        self._precheck(listing_ids, benchmark_listing_ids)
        self._last_wall, self._last_mono = self.clock_ns(), self.monotonic_ns()
        self._claim()
        self.state, self.reason_code = 'CONNECTING', None
        try:
            self._open()
        except ProviderBudgetExceeded as exc:
            self._fail(exc.reason_code)
        except StreamError as exc:
            self._fail(exc.code, terminal=exc.code in {'AUTHENTICATION_FAILED', 'FEED_NOT_ENTITLED', 'LEASE_LOST'})
        except Exception:
            self._fail('STREAM_FAILED')
        return self.status()

    def _close_sockets(self):
        for socket in self.sockets.values():
            with suppress(Exception):
                socket.close()
        self.sockets = {}

    def _gap_bounds(self, capture_id, end):
        """Only immutable, published control proofs delimit transport coverage.

        Quiet news remains covered by PONG, never inferred from article count or
        mutable collector state. Missing channels fall back to capture start.
        """
        controls = self.store.read_capture_as_of(cutoff_ns=end, capture_id=capture_id)
        proofs, starts = {}, []
        for row in controls:
            payload = row['payload']
            if row['kind'] == 'CAPTURE_START':
                starts.append(row)
            channel = payload.get('channel')
            if channel not in {'market', 'news'}:
                continue
            if row['kind'] == 'ACK':
                stamp = payload['received_at_ns']
            elif row['kind'] == 'CLOCK' and payload.get('metadata_kind') == 'TRANSPORT_LIVENESS':
                stamp = payload['pong_received_at_ns']
            else:
                continue
            if channel not in proofs or stamp >= proofs[channel][0]:
                proofs[channel] = (stamp, row)
        start = min(starts, key=lambda row: row['received_at_ns']) if starts else None
        fallback = start['received_at_ns'] if start else 0
        def reference(row):
            return {key: row[key] for key in ('id', 'payload_hash', 'publication_id', 'publication_hash')}
        bounds = {'start_at_ns': min(proofs.get(channel, (fallback, None))[0] for channel in ('market', 'news')),
                'end_at_ns': end, 'transport_proofs': {channel: reference(row) for channel, (_, row) in proofs.items()},
                'missing_transport_channels': sorted({'market', 'news'} - proofs.keys()),
                'capture_start_proof': reference(start) if start else None}
        pending = [received for _, received, _, capture in self.queue if capture == capture_id]
        bounds['pending_received_at_ns'] = min(pending) if pending else None
        if pending:
            bounds['start_at_ns'] = min(bounds['start_at_ns'], min(pending))
        # A crashed owner's RAM is unavailable. RAW without visible admission is
        # retained as a conservative floor, never promoted by later PONG.
        orphans = []
        for table, column in (('intraday_observations', 'observation_id'), ('intraday_news_versions', 'news_version_id')):
            row = self.connection.execute(f'''SELECT raw.id,raw.payload_hash,raw.received_at_ns FROM {table} raw
                WHERE raw.profile_id=? AND raw.data_mode=? AND raw.provenance=? AND raw.replay_grade=?
                AND raw.capture_id=? AND raw.persisted_at_ns<=? AND NOT EXISTS(
                    SELECT 1 FROM intraday_capture_events pub WHERE pub.kind='ADMISSION' AND pub.{column}=raw.id
                    AND pub.available_at_ns<=? AND json_extract(pub.payload_json,'$.payload_hash')=raw.payload_hash)
                ORDER BY raw.received_at_ns,raw.id LIMIT 1''', (*self.store.namespace, capture_id, end, end)).fetchone()
            if row is not None:
                orphans.append({'table': table, **dict(row)})
        orphan = min(orphans, key=lambda row: row['received_at_ns']) if orphans else None
        bounds['orphan_raw_proof'] = orphan
        if orphan is not None:
            bounds['start_at_ns'] = min(bounds['start_at_ns'], orphan['received_at_ns'])
        return bounds

    def _fail(self, reason, *, terminal=False, detail=None):
        self._close_sockets()
        self.reason_code, self.listing_states, self.acks = StreamError(reason).code, {}, {}
        self._bootstrap_digest = None
        if not self._owned():
            self.state, self._terminal = 'FAILED', True
            return
        self._emergency = True
        try:
            if reason == 'CLOCK_SKEW':
                self._log('CLOCK', {'reason_code': reason, **(detail or {})})
            self._log('GAP', {'reason_code': self.reason_code, **self._gap_bounds(self.capture_id, self._storage_now()),
                              'pending_events': len(self.queue)})
            state = 'FAILED' if terminal or self._reconnects >= self.settings.alpaca_stream_max_reconnects else 'BACKOFF'
            self._log('STOP', {'reason_code': self.reason_code, 'terminal': state == 'FAILED'})
            self._set_state(state, connections=0)
            self._terminal = state == 'FAILED'
            delay = min(self.settings.alpaca_stream_backoff_cap_seconds,
                        self.settings.alpaca_stream_backoff_seconds * (2 ** self._reconnects))
            self._next_attempt_ns = self._storage_now() + delay * SECOND
            if self.reason_code == 'RATE_LIMITED':
                availability = self.provider.transport.budget_manager.availability(self.connection,
                    account_budget_policy(self.settings, self.profile), 'alpaca',
                    datetime.fromtimestamp(self._storage_now() // SECOND, UTC))
                if availability.cooldown_until is not None:
                    delta = availability.cooldown_until.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
                    cooldown_ns = (delta.days * 86400 + delta.seconds) * SECOND + delta.microseconds * 1000
                    self._next_attempt_ns = max(self._next_attempt_ns, cooldown_ns)
        except Exception:
            self.state, self._terminal = 'FAILED', True
            with suppress(Exception):
                self._set_state('FAILED', connections=0)
        finally:
            self._emergency = False

    def receive(self, channel, *, timeout=0.05):
        if not self._owned():
            self._close_sockets()
            raise StreamError('LEASE_LOST')
        if channel not in self.sockets:
            return 0
        if self._tick() is None:
            return 0
        try:
            frame = self.sockets[channel].recv(timeout=timeout)
            received = self.clock_ns()  # Immediately after receipt, before decode/application queue.
            if isinstance(frame, ReceivedFrame):
                frame, received = frame.data, frame.received_at_ns
            check_ns(received)
            if received > self.clock_ns():
                raise StreamError('CLOCK_SKEW')
            if self._tick() is None:
                return 0
            secrets = tuple(value for name, value in vars(self.settings).items()
                if (name.endswith(('_api_key', '_token', '_chat_id')) or name in
                    {'alpaca_api_key_id', 'alpaca_api_secret_key'}) and isinstance(value, str) and value)
            decoded = decode_frame(frame, channel=channel,
                max_bytes=min(1_048_576, self.profile.max_frame_bytes, self.settings.alpaca_max_frame_bytes),
                max_events=min(10_000, self.profile.max_queue_events, self.settings.alpaca_max_queue_events),
                secrets=secrets, rights=self.rights)
            self._last_frame[channel] = received
            self._last_transport[channel] = max(self._last_transport[channel], received)
            for value in decoded:
                kind = value['kind']
                if kind == 'CONNECTED':
                    self.connected.add(channel)
                elif kind == 'AUTHENTICATED':
                    if channel not in self.connected:
                        raise StreamError('FRAME_INVALID')
                    self.authenticated.add(channel)
                    self.sockets[channel].send(json.dumps({'action': 'subscribe', **self.expected[channel]}))
                elif kind == 'ERROR':
                    self._fail(value['reason_code'], terminal=value['reason_code'] != 'STREAM_FAILED')
                    return 0
                elif kind == 'ACK':
                    actual = {key: items for key, items in value['subscriptions'].items() if items}
                    if channel not in self.authenticated or actual != self.expected[channel]:
                        self._fail('ACK_INCOMPLETE', terminal=True)
                        return 0
                    row_id = self._log('ACK', {'channel': channel, 'subscriptions': actual,
                                              'received_at_ns': received})
                    proof = next(row for row in self.store.read_capture_as_of(cutoff_ns=self._storage_now(),
                                capture_id=self.capture_id) if row['id'] == row_id)
                    self.acks[channel] = proof
                else:
                    cap = min(10_000, self.profile.max_queue_events, self.settings.alpaca_max_queue_events)
                    if len(self.queue) >= cap:
                        self._fail('QUEUE_OVERFLOW', terminal=True)
                        return 0
                    if value['channel'] not in self.expected[channel]:
                        raise StreamError('CHANNEL_INVALID')
                    self._intake += 1
                    self.queue.append((value, received, self._intake, self.capture_id))
            self._set_state(self.state)
            return len(decoded)
        except TimeoutError:
            return 0
        except StreamError as exc:
            self._fail(exc.code, terminal=True)
            return 0
        except Exception:
            self._fail('STREAM_FAILED')
            return 0

    def drain(self):
        if not self._owned():
            self._close_sockets()
            raise StreamError('LEASE_LOST')
        count = 0
        try:
            while self.queue:
                value, received, intake, capture = self.queue[0]
                self._quota(expected=len(canonical_json(value['row']).encode()) * 4 + 65536)
                kind, row = value['kind'], value['row']
                if kind == 'NEWS':
                    ids = self.news.persist((row,), received_at_ns=received, capture_id=capture,
                                            admit=False, intake_sequence=intake)
                    if ids:
                        self.news.admit(ids)
                else:
                    at = _ns(row['t'])
                    identity = next((r for r in self.identities.values() if r['ticker'] == row['S']), None)
                    if identity is None:
                        raise StreamError('IDENTITY_UNVERIFIED')
                    current = read_identity_as_of(self.connection, identity['listing_id'], at, received,
                        profile_id=self.profile.profile_id, data_mode=self.data_mode,
                        provenance='CAPTURED', replay_grade='STRICT_PIT')
                    if (current is None or current['ticker'] != row['S'] or
                        current['broker_asset_id'] != identity['broker_asset_id'] or current['venue'] != identity['venue']):
                        raise StreamError('IDENTITY_UNVERIFIED')
                    payload = (decode_status_row(kind, row, source='STREAM') if kind in {'STATUS', 'LULD'}
                               else decode_market_row(kind, row, source='STREAM'))
                    envelope = EventEnvelope('alpaca', self.profile.feed, self.profile.profile_id,
                        self.data_mode, self.provenance, self.replay_grade, kind, identity['listing_id'],
                        f'{kind}:{identity["listing_id"]}:{at}', capture, intake, at, received,
                        self._storage_now(), None, canonical_json(payload),
                        at + 60 * SECOND if kind == 'BAR' else 0)
                    ids = self.store.persist((envelope,), run_id=self.run_id, admit=False)
                    self.store.admit(ids)
                self.queue.popleft()
                count += 1
            self._set_state(self.state)
            return count
        except StreamError as exc:
            if exc.code == 'LEASE_LOST':
                self._close_sockets()
                raise
            self._fail(exc.code, terminal=True)
        except Exception as exc:
            code = 'ARCHIVE_LIMIT' if isinstance(exc, sqlite3.DatabaseError) or getattr(exc, 'code', None) in {'ARCHIVE_LIMIT', 'NEWS_LIMIT'} else 'FRAME_INVALID'
            self._fail(code, terminal=True)
        return count

    def reconcile(self):
        if not self._owned():
            raise StreamError('LEASE_LOST')
        now = self._tick()
        if now is None:
            return self.status()
        if not self.sockets or self._terminal or not self._health(now):
            return self.status()
        if self.queue or set(self.acks) != {'market', 'news'}:
            self._set_state('CONNECTING')
            return self.status()
        if not self._socket_barrier():
            self.listing_states = {}
            if self.sockets:
                self._set_state('CONNECTING')
            return self.status()
        now = self._storage_now()
        records = self.events.read_as_of(cutoff_ns=now, listing_ids=self.listing_ids, revisions=True)
        captures = self.store.read_capture_as_of(cutoff_ns=now, capture_id=self.capture_id)
        if any(row['kind'] == 'GAP' for row in captures):
            self._set_state('DEGRADED')
            return self.status()
        refs, states = [], {}
        for listing in self.listing_ids:
            unknown = {'state': 'UNKNOWN', 'live_eligible': False, 'reason_code': 'STATUS_BOOTSTRAP_UNAVAILABLE'}
            candidates = [r for r in records if r['listing_id'] == listing and r['capture_id'] == self.capture_id
                and r['payload'].get('version') == 'utp-status-checkpoint-v1'
                and r['effective_at_ns'] >= self.acks['market']['available_at_ns']]
            if not candidates:
                states[listing] = unknown
                continue
            checkpoint = max(candidates, key=lambda row: (row['effective_at_ns'], _RANK[row['payload']['state']], row['id']))
            payload = checkpoint['payload']
            if payload['expires_at_ns'] <= now or payload.get('reason_code') is not None:
                states[listing] = unknown
                continue
            pending = self.connection.execute('''SELECT 1 FROM intraday_observations raw
                WHERE capture_id=? AND listing_id=? AND kind IN ('STATUS','LULD') AND event_time_ns>=?
                AND NOT EXISTS(SELECT 1 FROM intraday_capture_events proof WHERE kind='ADMISSION'
                    AND proof.observation_id=raw.id AND proof.available_at_ns<=?) LIMIT 1''',
                (self.capture_id, listing, checkpoint['effective_at_ns'], now)).fetchone()
            if pending:
                states[listing] = unknown
                continue
            status_rows = [r for r in self.store.read_as_of('STATUS', cutoff_ns=now, listing_ids=(listing,), revisions=True)
                           if r['capture_id'] == self.capture_id and r['event_time_ns'] >= checkpoint['effective_at_ns']]
            state = payload['state']
            if status_rows:
                last = max(row['event_time_ns'] for row in status_rows)
                tied = [row['payload']['state'] if row['quality'] == 'VALID' else 'UNKNOWN'
                        for row in status_rows if row['event_time_ns'] == last]
                if last == checkpoint['effective_at_ns']:
                    tied.append(state)
                state = max(tied, key=_RANK.__getitem__)
            states[listing] = {'state': state, 'live_eligible': state == 'NORMAL',
                              'expires_at_ns': payload['expires_at_ns'],
                              'reason_code': 'STATUS_UNKNOWN' if state == 'UNKNOWN' else None}
            refs.append({'listing_id': listing, 'checkpoint_id': checkpoint['id'],
                'checkpoint_hash': checkpoint['payload_hash'], 'checkpoint_admission_id': checkpoint['admission_id'],
                'snapshot_at_ns': checkpoint['effective_at_ns'], 'expires_at_ns': payload['expires_at_ns'],
                'status_refs': [{'id': row['id'], 'hash': row['payload_hash'], 'admission_id': row['admission_id']} for row in status_rows]})
        ready = len(refs) == len(self.listing_ids) and all(row['state'] != 'UNKNOWN' for row in states.values())
        if ready:
            if self._transport_pending():
                self.listing_states = {}
                self._set_state('CONNECTING')
                return self.status()
            proof = {'metadata_kind': 'COLLECTOR_HANDSHAKE', 'ack_refs': [
                {'id': row['id'], 'hash': row['payload_hash'], 'publication_id': row['publication_id'],
                 'publication_hash': row['publication_hash']} for row in self.acks.values()],
                'listings': refs, 'continuity_attested': True, 'barrier_at_ns': now}
            digest = hashlib.sha256(canonical_json({k: v for k, v in proof.items() if k != 'barrier_at_ns'}).encode()).hexdigest()
            if digest != self._bootstrap_digest:
                try:
                    self._log('BOOTSTRAP', proof)
                except Exception:
                    self._fail('ARCHIVE_LIMIT', terminal=True)
                    return self.status()
                self._bootstrap_digest = digest
            self._set_state('LIVE')
            self.listing_states = states
        else:
            self._set_state('CONNECTING')
            self.listing_states = states
        return self.status()

    def _health(self, now):
        for channel in tuple(self.sockets):
            if now - self._opened_at[channel] > 10 * SECOND and channel not in self.acks:
                self._fail('HANDSHAKE_TIMEOUT', terminal=True)
                return False
            if now - self._last_transport[channel] > self.settings.alpaca_stream_silence_seconds * SECOND:
                self._fail('SOCKET_SILENCE')
                return False
            interval = min(10, max(1, self.settings.alpaca_stream_silence_seconds // 3)) * SECOND
            if now - self._last_ping[channel] >= interval:
                try:
                    drained = not self.queue and not self._transport_pending()
                    if not self.sockets[channel].ping().wait(timeout=1):
                        raise StreamError('SOCKET_SILENCE')
                    stamp = self._tick()
                    if stamp is None:
                        return False
                    if drained and not self.queue and not self._transport_pending():
                        self._log('CLOCK', {'metadata_kind': 'TRANSPORT_LIVENESS', 'channel': channel,
                                           'ping_sent_at_ns': now, 'pong_received_at_ns': stamp})
                    self._last_ping[channel] = self._last_transport[channel] = stamp
                except StreamError as exc:
                    self._fail(exc.code, terminal=True)
                    return False
                except Exception:
                    self._fail('SOCKET_SILENCE')
                    return False
        return True

    def _socket_barrier(self):
        """Drain messages already in the transport buffer before the status barrier.

        A continuous burst exceeding this bound can't produce a LIVE proof.
        Partial wire messages likewise keep the capture in CONNECTING.
        """
        cap = min(10_000, self.profile.max_queue_events, self.settings.alpaca_max_queue_events)
        for channel in tuple(self.sockets):
            empty = False
            for _ in range(cap):
                if self.receive(channel, timeout=0) == 0:
                    empty = True
                    break
                if self.queue:
                    self.drain()
                if not self.sockets or self._terminal:
                    return False
            if not empty or not self.sockets:
                return False
            pending = getattr(self.sockets[channel], 'has_pending', None)
            if pending is not None and pending():
                return False
        # A market frame may have arrived while the news socket was being drained.
        return not self.queue and not self._transport_pending()

    def _transport_pending(self, sockets=None):
        for source in (self.sockets.values() if sockets is None else sockets):
            method = getattr(source, 'has_pending', None)
            try:
                if method is not None and method():
                    return True
            except Exception:
                return True
        return False

    def _new_epoch(self):
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            now = self._storage_now()
            if not self._owned(now):
                raise StreamError('LEASE_LOST')
            active = self.connection.execute('''SELECT state.*, profiles.config_json FROM intraday_collector_state state
                JOIN intraday_feed_profiles profiles ON profiles.id=state.profile_id
                WHERE owner_nonce IS NOT NULL AND lease_expires_at_ns>?''', (now,)).fetchall()
            limit = min(self.settings.alpaca_max_connections, self.profile.max_connections,
                        *(json.loads(row['config_json'])['max_connections'] for row in active))
            if sum(row['connection_count'] for row in active if row['owner_nonce'] != self.owner_nonce) + 2 > limit:
                raise StreamError('CONNECTION_LIMIT')
            capture = uuid.uuid4().hex
            run = self._unfenced_store.archive.begin_run()
            self.connection.execute('''UPDATE intraday_collector_state SET capture_id=?,ingest_run_id=?,
                state='CONNECTING',connection_count=2,lease_expires_at_ns=?
                WHERE profile_id=? AND data_mode=? AND owner_nonce=?''',
                (capture, run, now + self.settings.alpaca_collector_lease_seconds * SECOND,
                 self.profile.profile_id, self.data_mode, self.owner_nonce))
            self.connection.commit()
            self.capture_id, self.run_id, self.state = capture, run, 'CONNECTING'
        except Exception:
            self.connection.rollback()
            raise

    def step(self):
        if self.state == 'STOPPED' or self._terminal:
            return self.status()
        if not self._owned():
            self._close_sockets()
            self.state = 'FAILED'
            raise StreamError('LEASE_LOST')
        now = self._tick()
        if now is None:
            return self.status()
        if self.state == 'BACKOFF':
            if now < self._next_attempt_ns:
                self._set_state('BACKOFF', connections=0)
                return self.status()
            # Preserve queued originals before the next epoch; no data loss on reconnect.
            if self.queue:
                self.drain()
                if self._terminal or self.state == 'FAILED' or self.queue:
                    return self.status()
            self._reconnects += 1
            try:
                self._new_epoch()
                self._log('CAPTURE_START', {'listing_ids': list(self.listing_ids), 'subscriptions': self.expected,
                                          'continuity_attested': False, 'reconnect': self._reconnects})
                self._open()
            except ProviderBudgetExceeded as exc:
                self._fail(exc.reason_code)
            except StreamError as exc:
                self._fail(exc.code, terminal=exc.code in {'AUTHENTICATION_FAILED', 'FEED_NOT_ENTITLED', 'LEASE_LOST'})
            except Exception:
                self._fail('STREAM_FAILED')
            return self.status()
        if not self._health(now):
            return self.status()
        self._socket_barrier()
        if not self.sockets:
            return self.status()
        self.drain()
        return self.reconcile()

    def status(self):
        state, reason = self.state, self.reason_code
        states = copy.deepcopy(self.listing_states)
        if state == 'LIVE' and any(row.get('expires_at_ns', 0) <= self._storage_now() for row in states.values()):
            state, reason = 'DEGRADED', 'STATUS_BOOTSTRAP_UNAVAILABLE'
            for row in states.values():
                if row.get('expires_at_ns', 0) <= self._storage_now():
                    row['state'] = 'UNKNOWN'
        if state == 'LIVE' and (not self._owned() or any(self._storage_now() - value > self.settings.alpaca_stream_silence_seconds * SECOND
                                                       for value in self._last_transport.values())):
            state, reason = 'DEGRADED', 'CAPTURE_GAP'
        if state != 'LIVE':
            for row in states.values():
                row['live_eligible'] = False
        return {'state': state, 'reason_code': reason, 'capture_id': self.capture_id,
                'pending_events': len(self.queue), 'listing_states': states,
                'g1_data': 'INSUFFICIENTE'}

    def stop(self):
        if self.state == 'STOPPED':
            return self.status()
        if not self._owned():
            self._close_sockets()
            self.state = 'STOPPED'
            return self.status()
        if self.queue:
            self.drain()
        if self.sockets:
            complete = self._socket_barrier()
            sources = tuple(self.sockets.values())
            self._close_sockets()
            if not complete or self._transport_pending(sources):
                self._fail('CAPTURE_GAP', terminal=True)
        self._emergency = True
        try:
            self._log('STOP', {'reason_code': 'STOPPED', 'pending_events': len(self.queue)})
            self.connection.execute('BEGIN IMMEDIATE')
            if not self._owned():
                raise StreamError('LEASE_LOST')
            self.connection.execute('''UPDATE intraday_collector_state SET state='STOPPED',owner_nonce=NULL,
                lease_expires_at_ns=0,connection_count=0 WHERE profile_id=? AND data_mode=? AND owner_nonce=?''',
                (self.profile.profile_id, self.data_mode, self.owner_nonce))
            self.connection.commit()
            self.state, self.reason_code, self.listing_states = 'STOPPED', None, {}
        except Exception:
            self.connection.rollback()
            self.state = 'FAILED'
        finally:
            self._emergency = False
            if self._original_page_limit is not None:
                self.connection.execute(f'PRAGMA max_page_count={self._original_page_limit}')
        return self.status()
