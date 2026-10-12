"""Finite intraday jobs and a lazy, independently owned collector thread."""
from __future__ import annotations

import copy
import json
import threading
import time
from contextlib import contextmanager, suppress
from datetime import UTC, date, datetime

from fastapi.encoders import jsonable_encoder

from backend.app.config import get_settings
from backend.app.data_providers.alpaca_events import AlpacaEventsProvider, StatusAuthority
from backend.app.data_providers.alpaca_market import AlpacaMarketProvider, format_ns
from backend.app.data_providers.alpaca_metadata import datetime_ns
from backend.app.data_providers.alpaca_stream import StreamError, open_socket
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import get_connection
from backend.app.intraday.collector import Collector
from backend.app.intraday.contracts import FeedProfile, ReasonCode
from backend.app.intraday.events import EventStore
from backend.app.intraday.identity import read_identity_as_of
from backend.app.intraday.news import NewsStore
from backend.app.intraday.profiles import configuration_reason
from backend.app.intraday.snapshots import SnapshotService
from backend.app.intraday.store import IntradayStore
from backend.app.lab.contracts import LabError
from backend.app.lab.jobs import JobCancelled, JobOutcome, register_job_handler

clock_ns = time.time_ns
_CODES = frozenset(code.value for code in ReasonCode) | frozenset({
    'INVALID_REQUEST', 'RESOURCE_NOT_FOUND', 'METADATA_INVALID', 'METADATA_MISSING', 'MAPPING_CHANGED',
    'MISSING_CREDENTIAL', 'BUDGET_UNATTESTED', 'BUDGET_EXHAUSTED', 'PROVIDER_COOLDOWN', 'ARCHIVE_LIMIT',
    'SYMBOL_LIMIT', 'CONNECTION_LIMIT', 'AUTHENTICATION_FAILED', 'STREAM_FAILED', 'PAGE_LIMIT', 'PAGE_INVALID',
    'NEWS_PAGE_INVALID', 'NEWS_INPUT_MISSING', 'EVENT_INPUT_MISSING', 'EVENT_PAGE_INVALID', 'POLICY_MISSING',
    'LEASE_LOST', 'STOP_TIMEOUT', 'COLLECTOR_NOT_RUNNING', 'INTERNAL_ERROR', 'CANCELLED', 'RATE_LIMITED',
})


class OperationError(LabError):
    def __init__(self, code):
        code = code if code in _CODES else 'INTERNAL_ERROR'
        super().__init__(code, 'Operazione intraday non disponibile.')


def safe_error(exc):
    return OperationError(getattr(exc, 'reason_code', getattr(exc, 'code', 'INTERNAL_ERROR')))


def public_response(payload):
    """Check the current secret inventory, including values archived before rotation."""
    settings = get_settings()
    secrets = tuple(value for name, value in vars(settings).items() if isinstance(value, str) and value and (
        name.endswith(('_api_key', '_token', '_chat_id')) or name in {'alpaca_api_key_id', 'alpaca_api_secret_key'}))
    encoded = jsonable_encoder(payload)
    if SafeProviderTransport._payload_contains_secret(encoded, secrets):
        raise OperationError('METADATA_INVALID')
    return encoded


def make_provider(connection, profile):
    return AlpacaMarketProvider(get_settings(), connection, profile)


def resolve_profile(connection, params):
    config = params.get('profile')
    if config is None:
        row = connection.execute('SELECT config_json FROM intraday_feed_profiles WHERE id=?', (params['profile_id'],)).fetchone()
        if row is None:
            raise OperationError('RESOURCE_NOT_FOUND')
        config = json.loads(row[0])
    else:
        config = dict(config)
    config = dict(config)
    for key in ('required_capabilities', 'attested_capabilities', 'quote_conditions'):
        config[key] = tuple(config[key])
    try:
        profile = FeedProfile(**config)
    except (ValueError, TypeError):
        raise OperationError('PROFILE_INVALID') from None
    if profile.profile_id != params['profile_id']:
        raise OperationError('PROFILE_INVALID')
    return profile


@contextmanager
def services(params):
    connection = get_connection()
    try:
        profile = resolve_profile(connection, params)
        provider = make_provider(connection, profile)
        options = {key: params[key] for key in ('data_mode', 'provenance', 'replay_grade') if key in params}
        store = IntradayStore(provider, clock_ns=lambda: clock_ns(), **options)
        store.archive.safe_json(params)
        yield store
    except JobCancelled:
        raise
    except OperationError:
        raise
    except Exception as exc:
        if getattr(exc, 'code', None) == 'CANCELLED':
            raise JobCancelled() from None
        raise safe_error(exc) from None
    finally:
        connection.close()


def require_transport(store, capabilities):
    for capability in capabilities:
        reason = configuration_reason(store.archive.settings, store.profile, capability)
        if reason is not None:
            raise OperationError(reason)
        availability = store.provider.availability(capability)
        if availability.state != 'AVAILABLE':
            raise OperationError(availability.reason_code or 'BUDGET_EXHAUSTED')


def precheck_backfill(store, params):
    capabilities = {'BAR': 'bars', 'QUOTE': 'quotes', 'NEWS': 'news', 'CORPORATE_ACTION': 'corporate_actions'}
    require_transport(store, [capabilities[kind] for kind in params['types']])
    cutoff = store.archive.now()
    if params['end_at_ns'] > cutoff:
        raise OperationError('INVALID_REQUEST')
    day = date.fromisoformat(params['asof_date'])
    asof = datetime_ns(datetime.combine(day, datetime.min.time(), UTC))
    if asof > cutoff:
        raise OperationError('INVALID_REQUEST')
    ids = tuple(params['listing_ids'])
    if len(ids) > min(store.profile.max_symbols, store.archive.settings.alpaca_max_symbols):
        raise OperationError('SYMBOL_LIMIT')
    # Validate all required identities/calendars before the first provider request.
    result = None
    for kind in params['types']:
        mapped_kind = kind if kind in ('BAR', 'QUOTE') else 'NEWS' if kind == 'NEWS' else 'BAR'
        result = store._mappings(mapped_kind, ids, params['start_at_ns'], params['end_at_ns'], cutoff,
                                 min(asof + 86400 * 10**9 - 1, cutoff))
    symbols = tuple(sorted(result[0]))
    # Every final request shape and boundary must be valid before any type starts HTTP.
    for left, right in _windows(params):
        start, end = format_ns(left), format_ns(right)
        for kind in params['types']:
            capability = capabilities[kind]
            request = {'symbols': ','.join(symbols), 'start': start, 'end': end, 'sort': 'asc'}
            if kind in ('BAR', 'QUOTE'):
                request.update(asof=params['asof_date'], limit='1000', currency='USD',
                               feed='sip' if store.profile.feed == 'delayed_sip' else store.profile.feed)
                if kind == 'BAR':
                    request.update(timeframe='1Min', adjustment='raw')
            elif kind == 'NEWS':
                request.update(limit='50', include_content='false', exclude_contentless='false')
            else:
                request.update(start=start[:10], end=end[:10], limit='1000', region='us', data_quality='complete')
            store.provider._validate_params(capability, request, store.provider.clock())
    return symbols


def _windows(params):
    left = params['start_at_ns']
    while left <= params['end_at_ns']:
        right = min(params['end_at_ns'], left + params['chunk_days'] * 86400 * 10**9)
        yield left, right
        left = right + 1


def precheck_snapshot(store, params):
    if params['cutoff_ns'] > store.archive.now():
        raise OperationError('SNAPSHOT_NOT_PIT')
    if len(params['listing_ids']) > min(store.profile.max_symbols, store.archive.settings.alpaca_max_symbols):
        raise OperationError('SYMBOL_LIMIT')
    # Registration is explicit at metadata bootstrap; evaluation never creates policy evidence.
    SnapshotService(store)._policy()


def frozen(store, snapshot_id):
    row = store.connection.execute('SELECT profile_id,data_mode,provenance,replay_grade FROM intraday_dataset_snapshots WHERE id=?', (snapshot_id,)).fetchone()
    if row is None:
        raise OperationError('RESOURCE_NOT_FOUND')
    if tuple(row) != store.namespace:
        raise OperationError('MODE_MISMATCH')
    result = SnapshotService(store).read(snapshot_id)
    for key in ('manifest', 'report'):
        store.archive.safe_json(result[key])
    return result


def _finish(store, result):
    if result.get('state') != 'COMPLETE':
        if result.get('reason_code') == 'CANCELLED':
            raise JobCancelled()
        raise OperationError(result.get('reason_code') or 'PAGE_LIMIT')
    summary = {key: result[key] for key in ('run_id', 'state', 'reason_code', 'pages') if key in result}
    if 'news_ids' in result:
        summary['news_count'] = len(result['news_ids'])
    store.archive.safe_json(summary)
    return summary


def metadata_job(context, params):
    context.raise_if_cancelled()
    with services(params) as store:
        require_transport(store, ('assets', 'calendar'))
        SnapshotService(store).register_policy()
        archive = store.archive
        assets = archive.refresh_assets()
        context.raise_if_cancelled()
        context.set_progress(.65)
        calendar = archive.refresh_calendar(params['start_date'], params['end_date'])
        context.raise_if_cancelled()
        return JobOutcome(result={'profile_id': store.profile.profile_id, 'assets_capture_id': assets,
                                  'calendar_capture_id': calendar, 'policy_id': 'intraday-quality-v1'})


def backfill_job(context, params):
    context.raise_if_cancelled()
    with services(params) as store:
        symbols = precheck_backfill(store, params)
        start, end = format_ns(params['start_at_ns']), format_ns(params['end_at_ns'])
        def cancelled():
            try:
                context.raise_if_cancelled()
            except JobCancelled:
                return True
            return False
        results = {}
        for index, kind in enumerate(params['types']):
            context.raise_if_cancelled()
            if kind in ('BAR', 'QUOTE'):
                results[kind] = _finish(store, store.backfill(kind=kind, listing_ids=tuple(params['listing_ids']),
                    start=start, end=end, asof=params['asof_date'], chunk_days=params['chunk_days'],
                    max_pages=params['max_pages'], cancel=cancelled))
            elif kind == 'NEWS':
                news = NewsStore(store.provider, clock_ns=lambda: clock_ns(), data_mode=store.data_mode,
                                 provenance=store.provenance, replay_grade=store.replay_grade)
                pages, count = 0, 0
                for left, right in _windows(params):
                    if pages >= params['max_pages']:
                        raise OperationError('PAGE_LIMIT')
                    summary = _finish(store, news.backfill(start=format_ns(left), end=format_ns(right), symbols=symbols,
                        max_pages=params['max_pages'] - pages, cancel=cancelled))
                    pages += summary['pages']
                    count += summary['news_count']
                results[kind] = {'state': 'COMPLETE', 'pages': pages, 'news_count': count}
            else:
                adapter, events = AlpacaEventsProvider(store.provider), EventStore(store.provider, clock_ns=lambda: clock_ns(),
                    data_mode=store.data_mode, provenance=store.provenance, replay_grade=store.replay_grade)
                pages, count = 0, 0
                for left, right in _windows(params):
                    token, seen = None, set()
                    while True:
                        context.raise_if_cancelled()
                        if pages >= params['max_pages']:
                            raise OperationError('PAGE_LIMIT')
                        response = adapter.get_page(start=format_ns(left)[:10], end=format_ns(right)[:10], symbols=symbols,
                                                    limit=1000, page_token=token, bypass_cache=True)
                        pages += 1
                        context.raise_if_cancelled()
                        count += len(events.import_corporate(response.payload, received_at_ns=datetime_ns(response.fetched_at),
                                                            capture_id=f'job-{context.job_id}'))
                        token = response.payload.get('next_page_token')
                        if token is None:
                            break
                        if token in seen:
                            raise OperationError('PAGE_INVALID')
                        seen.add(token)
                results[kind] = {'state': 'COMPLETE', 'pages': pages, 'event_count': count}
            context.raise_if_cancelled()
            context.set_progress((index + 1) / len(params['types']) * .95)
        store.archive.safe_json(results)
        return JobOutcome(result={'namespace': list(store.namespace), 'types': results})


def snapshot_job(context, params):
    context.raise_if_cancelled()
    with services(params) as store:
        precheck_snapshot(store, params)
        def cancelled(stage):
            try:
                context.raise_if_cancelled()
            except JobCancelled:
                return True
            return False
        saved = SnapshotService(store).freeze_dataset(start_at_ns=params['start_at_ns'], end_at_ns=params['end_at_ns'],
            cutoff_ns=params['cutoff_ns'], listing_ids=params['listing_ids'], benchmarks=params['benchmarks'], cancelled=cancelled)
        context.raise_if_cancelled()
        result = frozen(store, saved.snapshot_id)
        return JobOutcome(result_ref=str(saved.snapshot_id), result={'snapshot_id': saved.snapshot_id,
            'digest': saved.digest, 'report': result['report']})


def quality_job(context, params):
    context.raise_if_cancelled()
    with services(params) as store:
        result = frozen(store, params['snapshot_id'])
        context.raise_if_cancelled()
        return JobOutcome(result_ref=str(params['snapshot_id']), result={'snapshot_id': params['snapshot_id'],
            'digest': result['digest'], 'report': result['report']})


for _kind, _handler in (('INTRADAY_METADATA', metadata_job), ('INTRADAY_BACKFILL', backfill_job),
                       ('INTRADAY_SNAPSHOT', snapshot_job), ('INTRADAY_QUALITY', quality_job)):
    register_job_handler(_kind, _handler)


class CollectorRuntime:
    """One writer owns connection and sockets on its thread; no FIFO worker occupied."""
    def __init__(self):
        self._control = threading.Lock()
        self._state_lock = threading.Lock()
        self._thread = None
        self._key = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._state = {'state': 'STOPPED', 'reason_code': None, 'capture_id': None,
                       'pending_events': 0, 'listing_states': {}, 'g1_data': 'INSUFFICIENTE'}

    def status(self):
        with self._state_lock:
            return copy.deepcopy(self._state)

    def owns_capture(self, profile_id, capture_id):
        return (self._key is not None and self._key[0] == profile_id and self._thread is not None
                and self._thread.is_alive() and self.status()['capture_id'] == capture_id)

    def _publish(self, state):
        with self._state_lock:
            self._state = copy.deepcopy(state)

    def start(self, params):
        key = (params['profile_id'], tuple(sorted(set(params['listing_ids'] + params['benchmark_listing_ids']))))
        with self._control:
            if self._thread is not None and self._thread.is_alive():
                if key != self._key:
                    raise OperationError('COLLECTOR_ALREADY_OWNED')
                return self.status()
            self._key, self._error = key, None
            self._stop.clear()
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, args=(dict(params),), name='intraday-collector', daemon=True)
            self._thread.start()
            # Two governed socket opens (<=10s each), plus database/cleanup margin.
            if not self._ready.wait(30):
                self._stop.set()
                self._error = OperationError('STREAM_FAILED')
                self._publish({'state': 'FAILED', 'reason_code': 'STREAM_FAILED', 'capture_id': self.status()['capture_id'],
                               'pending_events': 0, 'listing_states': {}, 'g1_data': 'INSUFFICIENTE'})
                raise OperationError('STREAM_FAILED')
            if self._error is not None:
                raise self._error
            return self.status()

    def _run(self, params):
        collector = None
        try:
            with services(params) as store:
                if self._stop.is_set():
                    return
                def guarded_open(**kwargs):
                    if self._stop.is_set():
                        raise StreamError('STREAM_FAILED')
                    return open_socket(**kwargs)
                collector = Collector(store.provider, clock_ns=lambda: clock_ns(), socket_factory=guarded_open)
                try:
                    self._publish(collector.start(params['listing_ids'], benchmark_listing_ids=params['benchmark_listing_ids']))
                    if self.status()['state'] == 'FAILED':
                        raise OperationError(self.status()['reason_code'])
                    self._ready.set()
                    while not self._stop.wait(.01):
                        settings = get_settings()
                        if not settings.enable_real_data or not settings.enable_alpaca_data or not settings.enable_alpaca_collector:
                            break
                        for channel in ('market', 'news'):
                            collector.receive(channel, timeout=.05)
                        self._publish(collector.step())
                        if self.status()['state'] in ('STOPPED', 'FAILED'):
                            break
                finally:
                    terminal = collector.status()
                    stopped = collector.stop()
                    if self._error is not None:
                        terminal.update(state='FAILED', reason_code=self._error.code)
                    self._publish(terminal if terminal['state'] == 'FAILED' else stopped)
                    collector = None
        except Exception as exc:
            self._error = safe_error(exc)
            self._publish({'state': 'FAILED', 'reason_code': self._error.code, 'capture_id': self.status().get('capture_id'),
                           'pending_events': 0, 'listing_states': {}, 'g1_data': 'INSUFFICIENTE'})
        finally:
            if collector is not None:
                with suppress(Exception):
                    collector._close_sockets()
            self._ready.set()

    def stop(self, profile_id=None):
        with self._control:
            if profile_id is not None and self._key is not None and profile_id != self._key[0]:
                raise OperationError('COLLECTOR_ALREADY_OWNED')
            self._stop.set()
            if self._thread is not None:
                self._thread.join(35)
                if self._thread.is_alive():
                    raise OperationError('STOP_TIMEOUT')
            return self.status()


_runtime = None
_runtime_lock = threading.Lock()


def get_collector_runtime():
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = CollectorRuntime()
        return _runtime


def stop_active_collector():
    if _runtime is not None:
        _runtime.stop()


def collector_status(connection, profile_id=None):
    sql = 'SELECT state,capture_id,lease_expires_at_ns FROM intraday_collector_state'
    params = ()
    if profile_id is not None:
        sql += ' WHERE profile_id=?'
        params = (profile_id,)
    row = connection.execute(sql + ' ORDER BY id DESC LIMIT 1', params).fetchone()
    if _runtime is not None and (profile_id is None or _runtime._key is not None and _runtime._key[0] == profile_id):
        local = _runtime.status()
        if row is None or row['lease_expires_at_ns'] <= clock_ns() or row['capture_id'] == local['capture_id']:
            return local
    state = {'state': 'STOPPED', 'reason_code': None, 'capture_id': None,
             'pending_events': 0, 'listing_states': {}, 'g1_data': 'INSUFFICIENTE'}
    if row is not None:
        state.update({key: row[key] for key in ('state', 'capture_id')})
        if state['state'] != 'STOPPED' and row['lease_expires_at_ns'] <= clock_ns():
            state.update(state='DEGRADED', reason_code='CAPTURE_GAP')
    return state


def import_checkpoint(store, params):
    state = collector_status(store.connection, params['profile_id'])
    active = store.connection.execute('''SELECT id FROM intraday_collector_state
        WHERE profile_id=? AND data_mode='REAL' AND capture_id=? AND owner_nonce IS NOT NULL AND lease_expires_at_ns>?''',
        (params['profile_id'], params['capture_id'], clock_ns())).fetchone()
    if active is None or state['state'] not in ('CONNECTING', 'LIVE', 'DEGRADED') or state['capture_id'] != params['capture_id']:
        raise OperationError('COLLECTOR_NOT_RUNNING')
    authority = dict(params['authority'])
    authority['channel_bindings'] = tuple(tuple(item) for item in authority['channel_bindings'])
    events = EventStore(store.provider, clock_ns=lambda: clock_ns())
    ids = events.import_status_checkpoint(params['document'], authority=StatusAuthority(**authority),
        received_at_ns=clock_ns(), capture_id=params['capture_id'])
    return {'event_ids': ids, 'capture_id': params['capture_id'], 'live_eligible': False}


def page(store, rows, offset, limit):
    """Bound response bytes as well as count; validate only records being disclosed."""
    selected, used = [], 2
    for row in rows[offset:offset + limit]:
        public = {key: value for key, value in row.items() if key not in ('lease_nonce', 'payload_json')}
        size = len(store.archive.safe_json(public).encode()) + 1
        if selected and used + size > 1048576:
            break
        selected.append(public)
        used += size
    return {'items': selected, 'total': len(rows), 'offset': offset, 'limit': limit,
            'next_offset': offset + len(selected) if offset + len(selected) < len(rows) else None}


def news_coverage(store, reader, *, start_ns, end_ns, cutoff_ns, listing_id):
    if start_ns is None:
        return {'state': 'MISSING', 'continuity_attested': False, 'reason_code': 'PERIOD_NOT_REQUESTED'}
    symbols = ()
    if listing_id is not None:
        metadata = {'profile_id': store.profile.profile_id, 'data_mode': store.data_mode,
            'provenance': 'CAPTURED' if store.data_mode == 'REAL' else 'SYNTHETIC',
            'replay_grade': 'STRICT_PIT' if store.data_mode == 'REAL' else 'RESEARCH_ONLY'}
        first = read_identity_as_of(store.connection, listing_id, start_ns, cutoff_ns, **metadata)
        last = read_identity_as_of(store.connection, listing_id, end_ns, cutoff_ns, **metadata)
        if first is None or last is None or first['id'] != last['id']:
            return {'state': 'MISSING', 'continuity_attested': False, 'reason_code': 'IDENTITY_UNVERIFIED'}
        symbols = (first['ticker'],)
    result = reader.coverage_as_of(start_ns=start_ns, end_ns=end_ns, cutoff_ns=cutoff_ns, symbols=symbols)
    store.archive.safe_json(result)
    return result
