"""SP2b offline smoke: synthetic DEMO archive; never certifies REAL data.

Run as a module with INVESTEDGE_DB_PATH pointing to a NEW absolute scratch file.
Full fixture: 30 symbols, 19 regular sessions + one half-day, sampled quotes.
--quick exercises the same path with three symbols and two short sessions.
Time targets are indicative. Correctness assertions and network attempts fail.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import json
import os
import socket
import sqlite3
import sys
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

SECOND = 1_000_000_000
MINUTE = 60 * SECOND


def emit(phase, **values):
    print(json.dumps({'phase': phase, **values}, allow_nan=False), flush=True)


def target_path():
    raw = os.environ.get('INVESTEDGE_DB_PATH', '')
    path = Path(raw)
    root = Path(__file__).resolve().parents[2]
    if (not raw or not path.is_absolute() or path.name.lower() == 'investedge.db'
            or path.exists() or path.resolve().is_relative_to(root / 'data')):
        raise ValueError('TARGET_MUST_BE_NEW_ABSOLUTE_SCRATCH')
    return path


@contextmanager
def blocked_network():
    attempts = {'count': 0}

    def deny(*args, **kwargs):
        attempts['count'] += 1
        raise RuntimeError('NETWORK_BLOCKED_IN_INTRADAY_SMOKE')

    with (patch.object(socket, 'create_connection', deny), patch.object(socket, 'getaddrinfo', deny),
          patch.object(socket.socket, 'connect', deny), patch.object(socket.socket, 'connect_ex', deny)):
        yield attempts


def peak_memory_bytes():
    if os.name != 'nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)

    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong),
                    *[(name, ctypes.c_size_t) for name in ('peak', 'working', 'paged_peak', 'paged',
                                                         'nonpaged_peak', 'nonpaged', 'pagefile', 'pagefile_peak')]]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel, psapi = ctypes.WinDLL('kernel32'), ctypes.WinDLL('psapi')
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise RuntimeError('MEMORY_MEASUREMENT_UNAVAILABLE')
    return counters.peak


def bootstrap(connection, count, sessions, clock, *, nominal_real=False):
    """Seed only canonical fixture identities; intraday evidence uses production APIs."""
    import httpx

    from backend.app.config import Settings
    from backend.app.data_providers.alpaca_market import AlpacaMarketProvider
    from backend.app.data_providers.alpaca_metadata import AlpacaMetadataService
    from backend.app.data_providers.transport import SafeProviderTransport
    from backend.app.intraday.calendar import CalendarService
    from backend.app.intraday.contracts import FeedProfile
    from backend.app.intraday.identity import IdentityService
    from backend.app.intraday.store import IntradayStore
    from backend.app.models import AlpacaIdentityApplyIn, AlpacaIdentityPreviewIn

    def deny_http(request):
        raise RuntimeError('HTTP_NOT_ALLOWED_IN_INTRADAY_SMOKE')

    config = Settings(app_name='offline-smoke', app_env='test', api_version='v1', database_path=Path(':memory:'),
        cors_origins=[], alpaca_feed='sip', alpaca_max_symbols=30, alpaca_max_connections=2,
        alpaca_http_minute_limit=100, alpaca_http_daily_limit=1000, alpaca_http_monthly_limit=10000,
        alpaca_max_frame_bytes=1048576, alpaca_max_queue_events=1000, alpaca_max_archive_bytes=4 * 1024**3)
    if nominal_real:
        # Generated sentinels live only in the isolated fake-socket protocol benchmark.
        config = replace(config, enable_real_data=True, enable_alpaca_data=True, enable_alpaca_collector=True,
                         alpaca_api_key_id=uuid.uuid4().hex, alpaca_api_secret_key=uuid.uuid4().hex)
    profile = FeedProfile('sip', required_capabilities=('bars', 'quotes', 'news', 'status'),
        attested_capabilities=('bars', 'updated_bars', 'quotes', 'news', 'status', 'luld', 'assets', 'calendar'),
        max_symbols=30, max_connections=2, http_minute_limit=100, http_daily_limit=1000,
        http_monthly_limit=10000, max_frame_bytes=1048576, max_queue_events=1000, max_archive_bytes=4 * 1024**3)
    transport = SafeProviderTransport(allowed_hosts={'data.alpaca.markets', 'paper-api.alpaca.markets'},
        settings=config, client=httpx.Client(transport=httpx.MockTransport(deny_http)))
    provider = AlpacaMarketProvider(config, connection, profile, transport=transport,
        clock=lambda: datetime.fromtimestamp(clock.now // SECOND, UTC))
    namespace = {'data_mode': 'REAL', 'provenance': 'CAPTURED', 'replay_grade': 'STRICT_PIT'} if nominal_real else {
        'data_mode': 'DEMO', 'provenance': 'SYNTHETIC', 'replay_grade': 'RESEARCH_ONLY'}
    archive = AlpacaMetadataService(provider, clock_ns=lambda: clock.now, **namespace)
    digest = hashlib.sha256(b'synthetic canonical identity fixture').hexdigest()
    stamp = '2026-10-01T00:00:00Z'
    snapshot = connection.execute("""INSERT INTO catalog_snapshots
        (source,source_url,content_sha256,retrieved_at,row_count,status,parser_version)
        VALUES ('synthetic','https://example.invalid/synthetic',?,?,?,'COMPLETE','smoke-v1')""", (digest, stamp, count)).lastrowid
    assets, listings = [], []
    for number in range(1, count + 1):
        symbol = f'SYN{number:02}'
        instrument = connection.execute("INSERT INTO instruments(canonical_name,instrument_type,asset_class,source) VALUES (?,'STOCK','EQUITY','synthetic')", (symbol,)).lastrowid
        listing = connection.execute("""INSERT INTO instrument_listings(instrument_id,ticker,mic,venue_name,currency,timezone,source)
            VALUES (?,?,'XNAS','NASDAQ','USD','America/New_York','synthetic')""", (instrument, symbol)).lastrowid
        entry = connection.execute("""INSERT INTO catalog_entries(snapshot_id,row_number,name,parse_status,reason_code,raw_row_sha256,instrument_id,listing_id)
            VALUES (?,?,?,'ACCEPTED','VALID_ISIN',?,?,?)""", (snapshot, number, symbol, digest, instrument, listing)).lastrowid
        connection.execute("""INSERT INTO instrument_resolution_cases(catalog_entry_id,provider,request_fingerprint,status,reason_code,candidate_count,candidate_hash,evidence_hash,selected_instrument_id,selected_listing_id,created_at)
            VALUES (?,'synthetic',?,'RESOLVED','EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE',1,?,?,?,?,?)""",
            (entry, digest, digest, digest, instrument, listing, stamp))
        connection.execute("""INSERT INTO listing_metadata_versions(instrument_listing_id,venue_name,timezone,instrument_type,source_code,observed_at,evidence_hash,status,version)
            VALUES (?,'NASDAQ','America/New_York','STOCK','OFFICIAL_VENUE',?,?,'VERIFIED',1)""", (listing, stamp, digest))
        assets.append({'id': str(uuid.UUID(int=number)), 'class': 'us_equity', 'symbol': symbol,
                       'exchange': 'NASDAQ', 'status': 'active', 'tradable': True})
        listings.append(listing)
    connection.commit()
    capture = archive.record_assets(assets, received_at_ns=clock.now)
    identities = IdentityService(archive)
    for listing, asset in zip(listings, assets, strict=True):
        request = AlpacaIdentityPreviewIn(metadata_capture_id=capture, broker_asset_id=asset['id'],
            capabilities=['BAR', 'QUOTE', 'NEWS'], evidence_hash=digest)
        preview = identities.preview(listing, request)
        identities.apply(listing, AlpacaIdentityApplyIn(**request.model_dump(), confirmation_token=preview.confirmation_token))
    CalendarService(archive).record(sessions, start=sessions[0]['date'], end=sessions[-1]['date'], received_at_ns=clock.now)
    return IntradayStore(provider, clock_ns=lambda: clock.now, **namespace), listings


def envelope(store, listing, kind, at, received, number, *, revision=False):
    from backend.app.data_providers.alpaca_market import decode_market_row, format_ns
    from backend.app.intraday.contracts import EventEnvelope, canonical_json
    row = {'t': format_ns(at), 'o': 100, 'h': 102, 'l': 99, 'c': 100 if revision else 101,
           'v': 1000, 'vw': 100.5, 'n': 10} if kind == 'BAR' else {
        't': format_ns(at), 'bp': 100, 'ap': 100.01, 'bs': 20, 'as': 30, 'c': [], 'bx': 'Q', 'ax': 'Q', 'z': 'C'}
    return EventEnvelope('alpaca', store.profile.feed, store.profile.profile_id, store.data_mode, store.provenance,
        store.replay_grade, kind, listing, f'{kind}:{listing}:{at}', 'synthetic-sampled', number,
        at, received, received, None, canonical_json(decode_market_row(kind, row, source='STREAM')),
        availability_floor_ns=at + MINUTE if kind == 'BAR' else 0)


class FakeSocket:
    def __init__(self):
        self.frames = deque()

    def send(self, frame):
        return None  # Never retain authentication values.

    def recv(self, timeout):
        if not self.frames:
            raise TimeoutError
        return self.frames.popleft()

    def ping(self):
        return self

    def wait(self, timeout):
        return True

    def close(self):
        pass

    def has_pending(self):
        return bool(self.frames)


def collector_smoke(schema, sessions, opening):
    from backend.app.data_providers.alpaca_market import format_ns
    from backend.app.intraday.collector import Collector
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.executescript(schema)
    clock = SimpleNamespace(now=opening - MINUTE)
    store, listings = bootstrap(connection, 3, sessions[:1], clock, nominal_real=True)
    sockets = {}

    def factory(**options):
        assert not connection.in_transaction
        sockets[options['channel']] = FakeSocket()
        return sockets[options['channel']]

    clock.now = opening + SECOND
    collector = Collector(store.provider, socket_factory=factory, clock_ns=lambda: clock.now, monotonic_ns=lambda: clock.now)
    assert collector.start(listings)['state'] == 'CONNECTING'
    symbols = [f'SYN{number:02}' for number in range(1, 4)]
    for channel in ('market', 'news'):
        ack = {'T': 'subscription', **dict.fromkeys(('bars', 'updatedBars', 'quotes', 'statuses', 'lulds'), symbols)} if channel == 'market' else {'T': 'subscription', 'news': symbols}
        for frame in ([{'T': 'success', 'msg': 'connected'}], [{'T': 'success', 'msg': 'authenticated'}], [ack]):
            sockets[channel].frames.append(json.dumps(frame))
            collector.receive(channel)
    clock.now = opening + SECOND
    start, max_pending = perf_counter(), 0
    for _batch in range(10):
        frames = [{'T': 'q', 'S': symbols[index % 3], 't': format_ns(clock.now + index),
                   'bp': 100, 'ap': 100.01, 'bs': 20, 'as': 30, 'c': [], 'bx': 'Q', 'ax': 'Q', 'z': 'C'} for index in range(60)]
        clock.now += 60
        sockets['market'].frames.append(json.dumps(frames))
        collector.receive('market')
        max_pending = max(max_pending, collector.status()['pending_events'])
        collector.drain()
        clock.now += SECOND
    elapsed = perf_counter() - start
    raw = connection.execute("SELECT count(*) FROM intraday_observations WHERE kind='QUOTE'").fetchone()[0]
    admitted = connection.execute("SELECT count(*) FROM intraday_capture_events WHERE observation_id IS NOT NULL AND kind='ADMISSION'").fetchone()[0]
    lag = connection.execute("""SELECT MAX(proof.available_at_ns-raw.received_at_ns)
        FROM intraday_capture_events proof JOIN intraday_observations raw ON raw.id=proof.observation_id
        WHERE proof.kind='ADMISSION'""").fetchone()[0]
    assert raw == admitted == 600 and collector.status()['pending_events'] == 0
    assert collector.status()['reason_code'] != 'ARCHIVE_LIMIT'
    collector.stop()
    store.provider.transport._client.close()
    connection.close()
    return {'fixture': 'SYNTHETIC_FAKE_SOCKETS_NOMINAL_REAL_CONTRACT_ONLY', 'events': raw, 'admissions': admitted,
        'seconds': elapsed, 'events_per_second': raw / elapsed, 'declared_input_peak_per_second': 100,
        'peak_supported': raw / elapsed >= 100, 'max_pending': max_pending, 'silent_losses': 0,
        'fixture_admission_lag_max_ns': lag, 'wall_drain_batch_mean_ms': elapsed * 1000 / 10,
        'live_eligible': False, 'g1_data': 'INSUFFICIENTE'}


def run(path, quick, attempts):
    from backend.app.data_providers.alpaca_market import format_ns
    from backend.app.database import SCHEMA, migrate_db
    from backend.app.intraday.calendar import session_as_of
    from backend.app.intraday.news import NewsStore
    from backend.app.intraday.snapshots import SnapshotService
    from backend.app.intraday.universe import UniverseService
    count, days = (3, 2) if quick else (30, 20)
    calendar, day = [], date(2026, 10, 5)
    while len(calendar) < days:
        if day.weekday() < 5:
            close = ('09:33' if quick else '13:00') if len(calendar) == days - 1 else ('09:35' if quick else '16:00')
            calendar.append({'date': day.isoformat(), 'open': '09:30', 'close': close})
        day += timedelta(days=1)
    opening = int(datetime.combine(date.fromisoformat(calendar[0]['date']), datetime.min.time(), ZoneInfo('America/New_York')).timestamp()) * SECOND + (9 * 60 + 30) * MINUTE
    clock = SimpleNamespace(now=opening - 5 * MINUTE)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    migrate_db(connection)
    store, listings = bootstrap(connection, count, calendar, clock)
    snapshots = SnapshotService(store)
    snapshots.register_policy()
    universe = UniverseService(store.archive)
    sessions = []
    for row in calendar:
        session = session_as_of(connection, row['date'], clock.now, profile_id=store.profile.profile_id,
            data_mode='DEMO', provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY')
        sessions.append(session)
        universe.freeze(listings, row['date'], clock.now)
    total = count * sum((session.close_at_ns - session.open_at_ns) // MINUTE for session in sessions)
    emit('fixture', symbols=count, sessions=days, half_days=1, expected_bars=total, sampled_quotes=total,
         data_mode='DEMO', provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY', calendar='SYNTHETIC_NOT_OFFICIAL')
    ingest_start, number, accepted = perf_counter(), 0, 0
    for session in sessions:
        batch = []
        for at in range(session.open_at_ns, session.close_at_ns, MINUTE):
            clock.now = at + MINUTE + 10 * SECOND
            for listing in listings:
                for kind, event_time in (('BAR', at), ('QUOTE', at + MINUTE + 9 * SECOND)):
                    number += 1
                    batch.append(envelope(store, listing, kind, event_time, clock.now, number))
            if len(batch) + 2 * count > 1000:
                accepted += len(store.persist(batch))
                batch = []
        if batch:
            accepted += len(store.persist(batch))
        emit('ingest_session', session=session.session_date, accepted=accepted, elapsed_seconds=perf_counter() - ingest_start)
    ingest_seconds = perf_counter() - ingest_start
    assert accepted == total * 2
    assert connection.execute("SELECT count(*) FROM intraday_observations WHERE quality='QUARANTINED'").fetchone()[0] == 0
    news = NewsStore(store.provider, clock_ns=lambda: clock.now, data_mode='DEMO', provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY')
    publication = format_ns(sessions[0].open_at_ns + SECOND)
    article = {'id': 1, 'source': 'synthetic', 'headline': 'Company reports earnings', 'summary': 'Synthetic results',
        'created_at': publication, 'updated_at': publication, 'symbols': ['SYN01'], 'url': 'https://example.invalid/synthetic'}
    news.persist([article], received_at_ns=clock.now)
    clock.now += SECOND
    article.update(headline='Company updates guidance', updated_at=format_ns(clock.now))
    news.persist([article], received_at_ns=clock.now)
    assert len(news.read_as_of(cutoff_ns=clock.now, revisions=True)) == 2
    benchmarks = {'market': listings[-2], 'sector': listings[-1]}
    start = perf_counter()
    saved = snapshots.freeze_dataset(start_at_ns=sessions[0].open_at_ns, end_at_ns=sessions[-1].close_at_ns,
        cutoff_ns=clock.now, listing_ids=listings, benchmarks=benchmarks)
    freeze_seconds = perf_counter() - start
    emit('freeze', seconds=freeze_seconds, snapshot_id=saved.snapshot_id, digest=saved.digest, peak_memory_bytes=peak_memory_bytes())
    start = perf_counter()
    replay = snapshots.replay(saved.snapshot_id)
    replay_seconds = perf_counter() - start
    assert len(replay['observations']['BAR']) == total and len(replay['observations']['QUOTE']) == total
    timeline_count = len(replay['timeline'])
    del replay
    gc.collect()
    queries = []
    for index in range(20):
        cutoff = sessions[index % len(sessions)].close_at_ns + 10 * SECOND
        start = perf_counter()
        rows = store.read_as_of('QUOTE', cutoff_ns=cutoff, listing_ids=(listings[index % count],))
        assert rows
        queries.append((perf_counter() - start) * 1000)
        del rows
    query_p95 = sorted(queries)[18]
    emit('queries', p95_ms=query_p95, count=len(queries))
    # Fingerprint read without retaining two full timelines simultaneously.
    def fingerprint():
        value = snapshots.read(saved.snapshot_id)
        digest = hashlib.sha256()
        for chunk in json.JSONEncoder(sort_keys=True, separators=(',', ':')).iterencode(value):
            digest.update(chunk.encode())
        result = digest.hexdigest()
        report = value['report']
        del value
        gc.collect()
        return result, report
    before, report = fingerprint()
    clock.now += SECOND
    store.persist([envelope(store, listings[0], 'BAR', sessions[0].open_at_ns, clock.now, number + 1, revision=True)])
    article.update(headline='Later revision', updated_at=format_ns(clock.now))
    news.persist([article], received_at_ns=clock.now)
    after, _ = fingerprint()
    assert before == after
    assert report['outcome'] != 'READY'
    connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    connection.close()
    store.provider.transport._client.close()
    size = path.stat().st_size
    collector = collector_smoke(SCHEMA, calendar, opening)
    assert attempts['count'] == 0
    emit('summary', symbols=count, sessions=days, half_days=1, bars=total, sampled_quotes=total,
        data_mode='DEMO', ingest_seconds=ingest_seconds, ingest_events_per_second=accepted / ingest_seconds,
        freeze_seconds=freeze_seconds, replay_seconds=replay_seconds, query_asof_p95_ms=query_p95,
        db_bytes=size, peak_memory_bytes=peak_memory_bytes(), timeline_count=timeline_count,
        frozen_unchanged=before == after, network_attempts=attempts['count'], collector=collector,
        indicative_targets_met={'query_asof': query_p95 <= 250, 'replay': replay_seconds <= 60},
        g1_data='INSUFFICIENTE', fixture_report_outcome=report['outcome'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    try:
        path = target_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb'):
            pass
    except (ValueError, FileExistsError):
        emit('refused', reason_code='TARGET_MUST_BE_NEW_ABSOLUTE_SCRATCH')
        return 2
    with blocked_network() as attempts, patch.dict(os.environ, {
        'PYTHON_DOTENV_DISABLED': '1', 'ENABLE_REAL_DATA': 'false', 'ENABLE_ALPACA_DATA': 'false',
        'ENABLE_ALPACA_COLLECTOR': 'false', 'ENABLE_ALERTS': 'false', 'ENABLE_TELEGRAM': 'false'}):
        run(path, args.quick, attempts)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
