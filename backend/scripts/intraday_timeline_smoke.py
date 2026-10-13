"""Offline SP3 timeline sustainability. Run each scale in a fresh process/DB.

The 30x20 fixture is the original 19 regular sessions plus one half-day,
with one BAR and sampled QUOTE per listing/minute. Every measured timeline
is fully validated before any output. Explicit scratch budgets are mandatory.
Synthetic results never certify G1_DATA or economics.
"""
from __future__ import annotations

import argparse
import base64
import gc
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.scripts.intraday_data_smoke import FakeSocket, emit, envelope, peak_memory_bytes

SECOND, MINUTE = 1_000_000_000, 60_000_000_000


def target_path():
    raw = os.environ.get('INVESTEDGE_DB_PATH','')
    path = Path(raw)
    root = Path(__file__).resolve().parents[2]
    if (not raw or not path.is_absolute() or path.exists() or path.name.lower()=='investedge.db'
        or path.resolve().is_relative_to(root/'data')):
        raise ValueError('TARGET_MUST_BE_NEW_ABSOLUTE_SCRATCH')
    return path


@contextmanager
def blocked_network():
    attempts = {'count':0}
    def deny(*args,**kwargs):
        attempts['count'] += 1
        raise RuntimeError('NETWORK_BLOCKED_IN_TIMELINE_SMOKE')
    with (patch.object(socket,'create_connection',deny),patch.object(socket,'getaddrinfo',deny),
          patch.object(socket,'gethostbyname',deny),patch.object(socket,'gethostbyname_ex',deny),
          patch.object(socket,'gethostbyaddr',deny),patch.object(socket.socket,'connect',deny),
          patch.object(socket.socket,'connect_ex',deny),patch.object(socket.socket,'sendto',deny)):
        yield attempts


def disk_bytes(path):
    return sum(item.stat().st_size for item in path.parent.glob(path.name+'*') if item.is_file())


def frame(kind,payload=b''):
    return (len(payload)+1).to_bytes(2,'big')+kind.encode()+payload


def wire(category,kind,body,at,origin=b'Q'):
    return b'1'+category.encode()+kind.encode()+origin+b' '+at.to_bytes(8,'big')*2+bytes(8)+body


def checkpoint(symbols,at):
    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday.events import StatusAuthority
    request,channels = at-SECOND,[]
    for channel in range(1,7):
        raw = frame('A',b'session-01'+b'                   1')
        if channel==1:
            for symbol in symbols:
                encoded = symbol.encode()
                directory = encoded.ljust(11)+bytes(11)+encoded.ljust(30)+b'CS QPN'+(100).to_bytes(2,'big')+b'N'
                assert len(directory)==61
                raw += frame('S',wire('A','B',directory,request))
        raw += frame('S',wire('A','S',(700+channel).to_bytes(8,'big'),request,b'E'))
        channels.append({'channel':channel,'binding_id':f'sip-channel-{channel}',
            'request_sent_at_ns':request,'received_at_ns':at,'original_b64':base64.b64encode(raw).decode(),
            'original_sha256':hashlib.sha256(raw).hexdigest()})
    document = {'version':'utp-snapshot-import-v1','expires_at_ns':at+30*SECOND,'channels':channels}
    authority = StatusAuthority(source='UTP_SNAPSHOT',contract_version='4.0',contract_sha256='c'*64,
        evidence_hash='d'*64,retention='ARCHIVE_ALLOWED',
        channel_bindings=tuple((i,f'sip-channel-{i}') for i in range(1,7)),
        capture_sha256=hashlib.sha256(canonical_json(document).encode()).hexdigest())
    return document,authority


def collector_smoke(schema,calendar,opening,budget):
    from backend.app.data_providers.alpaca_market import format_ns
    from backend.app.intraday.collector import Collector
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(schema)
    clock = SimpleNamespace(now=opening-MINUTE)
    store,listings = _bootstrap(db,30,calendar[:1],clock,nominal_real=True,max_archive_bytes=budget)
    symbols,sockets = [f'SYN{i:02}' for i in range(1,31)],{}
    def factory(**options):
        assert not db.in_transaction
        sockets[options['channel']] = FakeSocket()
        return sockets[options['channel']]
    clock.now = opening+SECOND
    collector = Collector(store.provider,socket_factory=factory,clock_ns=lambda:clock.now,monotonic_ns=lambda:clock.now)
    collector.start(listings)
    for channel in ('market','news'):
        ack = {'T':'subscription',**dict.fromkeys(('bars','updatedBars','quotes','statuses','lulds'),symbols)} if channel=='market' else {'T':'subscription','news':symbols}
        for value in ({'T':'success','msg':'connected'},{'T':'success','msg':'authenticated'},ack):
            sockets[channel].frames.append(json.dumps([value]))
            collector.receive(channel)
    clock.now += 2*SECOND
    document,authority = checkpoint(symbols,clock.now)
    collector.events.import_status_checkpoint(document,authority=authority,received_at_ns=clock.now,capture_id=collector.capture_id)
    sockets['market'].frames.append(json.dumps([{'T':'s','S':symbol,'t':format_ns(clock.now),
        'sc':'T','sm':'fixture','rc':'T1','rm':'fixture','z':'C'} for symbol in symbols]))
    collector.receive('market')
    collector.drain()
    collector.reconcile()
    assert collector.status()['state']=='LIVE'
    max_pending,start = 0,perf_counter()
    for batch in range(10):
        clock.now += SECOND
        document,authority = checkpoint(symbols,clock.now)
        collector.events.import_status_checkpoint(document,authority=authority,received_at_ns=clock.now,capture_id=collector.capture_id)
        values = [{'T':'q','S':symbols[index%30],'t':format_ns(clock.now+index),
            'bp':100,'ap':100.01,'bs':20,'as':30,'c':[],'bx':'Q','ax':'Q','z':'C'} for index in range(60)]
        values.extend({'T':'s','S':symbol,'t':format_ns(clock.now+60),'sc':'T','sm':'Trading','rc':'T1','rm':'fixture','z':'C'} for symbol in symbols)
        clock.now += 61
        sockets['market'].frames.append(json.dumps(values))
        collector.receive('market')
        sockets['news'].frames.append(json.dumps([{'T':'n','id':batch+1,'headline':'Synthetic fixture',
            'created_at':format_ns(clock.now),'updated_at':format_ns(clock.now),'symbols':['SYN01'],
            'source':'synthetic','url':'https://example.invalid/synthetic'}]))
        collector.receive('news')
        max_pending = max(max_pending,collector.status()['pending_events'])
        collector.drain()
        collector.reconcile()
        state = collector.status()
        assert state['state']=='LIVE' and len(state['listing_states'])==30
        assert all(value['live_eligible'] for value in state['listing_states'].values())
        assert state['pending_events']==0
        clock.now += 10*SECOND
        collector.step()
        assert collector.status()['state']=='LIVE'
    elapsed = perf_counter()-start
    raw = db.execute('SELECT COUNT(*) FROM intraday_observations').fetchone()[0]
    admitted = db.execute("SELECT COUNT(*) FROM intraday_capture_events WHERE kind='ADMISSION' AND observation_id IS NOT NULL").fetchone()[0]
    news = db.execute('SELECT COUNT(*) FROM intraday_news_versions').fetchone()[0]
    news_admitted = db.execute("SELECT COUNT(*) FROM intraday_capture_events WHERE kind='ADMISSION' AND news_version_id IS NOT NULL").fetchone()[0]
    gaps = db.execute("SELECT COUNT(*) FROM intraday_capture_events WHERE kind='GAP'").fetchone()[0]
    lag = db.execute('''SELECT MAX(proof.available_at_ns-raw.received_at_ns) FROM intraday_capture_events proof
        JOIN intraday_observations raw ON raw.id=proof.observation_id WHERE proof.kind='ADMISSION' ''').fetchone()[0]
    clocks = db.execute("""SELECT COUNT(DISTINCT json_extract(payload_json,'$.channel')) FROM intraday_capture_events
        WHERE kind='CLOCK' AND json_extract(payload_json,'$.metadata_kind')='TRANSPORT_LIVENESS'""").fetchone()[0]
    quarantine = db.execute("SELECT COUNT(*) FROM intraday_observations WHERE quality='QUARANTINED'").fetchone()[0]
    assert raw==admitted==930 and news==news_admitted==10 and gaps==quarantine==0 and clocks==2
    collector.stop()
    store.provider.transport._client.close()
    db.close()
    return {'fixture':'SYNTHETIC_FAKE_SOCKETS_NOMINAL_REAL_CONTRACT_ONLY','events':raw+news,
            'admissions':admitted+news_admitted,'silent_losses':0,'gaps':gaps,'max_pending':max_pending,
            'seconds':elapsed,'fixture_admission_lag_max_ns':lag,'durable_pong_channels':clocks,
            'events_per_second_including_checkpoint_reconcile':(raw+news-30)/elapsed,
            'batch_events':91,'batch_count':10,'mean_batch_wall_seconds':elapsed/10,
            'max_queue_events':store.profile.max_queue_events,
            'per_batch_receive_drain_reconcile_status':True,'g1_data':'INSUFFICIENTE'}


def _bootstrap(connection, count, sessions, clock, *, nominal_real=False, max_archive_bytes=4 * 1024**3):
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
        alpaca_max_frame_bytes=1048576, alpaca_max_queue_events=1000, alpaca_max_archive_bytes=max_archive_bytes)
    if nominal_real:
        # Generated sentinels live only in the isolated fake-socket protocol benchmark.
        config = replace(config, enable_real_data=True, enable_alpaca_data=True, enable_alpaca_collector=True,
                         alpaca_api_key_id=uuid.uuid4().hex, alpaca_api_secret_key=uuid.uuid4().hex)
    profile = FeedProfile('sip', required_capabilities=('bars', 'quotes', 'news', 'status'),
        attested_capabilities=('bars', 'updated_bars', 'quotes', 'news', 'status', 'luld', 'assets', 'calendar'),
        max_symbols=30, max_connections=2, http_minute_limit=100, http_daily_limit=1000,
        http_monthly_limit=10000, max_frame_bytes=1048576, max_queue_events=1000, max_archive_bytes=max_archive_bytes)
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


def run(path,days,budget,min_free,quick,attempts):
    from backend.app.data_providers.alpaca_market import format_ns
    from backend.app.database import SCHEMA, migrate_db
    from backend.app.intraday.calendar import session_as_of
    from backend.app.intraday.news import NewsStore
    from backend.app.intraday.snapshots import SnapshotService
    from backend.app.intraday.universe import UniverseService
    from backend.app.intraday_research.contracts import ResearchNamespace
    from backend.app.intraday_research.datasets import DatasetBundle, DatasetChild, DatasetService
    count = 3 if quick else 30
    calendar,day = [],date(2026,10,5)
    while len(calendar)<days:
        if day.weekday()<5:
            calendar.append({'date':day.isoformat(),'open':'09:30',
                'close':('09:33' if quick else '13:00') if len(calendar)==days-1 else ('09:35' if quick else '16:00')})
        day += timedelta(days=1)
    opening = int(datetime.combine(date.fromisoformat(calendar[0]['date']),datetime.min.time(),ZoneInfo('America/New_York')).timestamp())*SECOND+(9*60+30)*MINUTE
    clock = SimpleNamespace(now=opening-5*MINUTE)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    migrate_db(db)
    store,listings = _bootstrap(db,count,calendar,clock,max_archive_bytes=budget)
    snapshots,universe = SnapshotService(store),UniverseService(store.archive)
    snapshots.register_policy()
    sessions = []
    for entry in calendar:
        session = session_as_of(db,entry['date'],clock.now,profile_id=store.profile.profile_id,
                               data_mode='DEMO',provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY')
        sessions.append(session)
        universe.freeze(listings,entry['date'],clock.now)
    total = count*sum((session.close_at_ns-session.open_at_ns)//MINUTE for session in sessions)
    emit('fixture',symbols=count,sessions=days,half_days=1,expected_bars=total,sampled_quotes=total,
         data_mode='DEMO',explicit_max_disk_bytes=budget,min_free_bytes=min_free)
    accepted,number,start = 0,0,perf_counter()
    growth = []
    for session in sessions:
        batch = []
        for at in range(session.open_at_ns,session.close_at_ns,MINUTE):
            clock.now = at+MINUTE+10*SECOND
            for listing in listings:
                for kind,event_time in (('BAR',at),('QUOTE',at+MINUTE+9*SECOND)):
                    number += 1
                    batch.append(envelope(store,listing,kind,event_time,clock.now,number))
            if len(batch)+2*count>1000:
                accepted += len(store.persist(batch))
                batch = []
        if batch:
            accepted += len(store.persist(batch))
        size = disk_bytes(path)
        growth.append(size)
        assert size<=budget and shutil.disk_usage(path.parent).free>=min_free
        emit('ingest_session',session=session.session_date,accepted=accepted,db_bytes=size,seconds=perf_counter()-start)
    assert accepted==2*total
    for kind in ('BAR','QUOTE'):
        assert db.execute('SELECT COUNT(*) FROM intraday_observations WHERE kind=?',(kind,)).fetchone()[0]==total
    assert db.execute("SELECT COUNT(*) FROM intraday_observations WHERE quality='QUARANTINED'").fetchone()[0]==0
    assert db.execute("SELECT COUNT(DISTINCT observation_id) FROM intraday_capture_events WHERE kind='ADMISSION' AND observation_id IS NOT NULL").fetchone()[0]==2*total
    news = NewsStore(store.provider,clock_ns=lambda:clock.now,data_mode='DEMO',
                     provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY')
    stamp = format_ns(sessions[0].open_at_ns+SECOND)
    article = {'id':1,'source':'synthetic','headline':'Company reports earnings','summary':'Synthetic results',
        'created_at':stamp,'updated_at':stamp,'symbols':['SYN01'],'url':'https://example.invalid/synthetic'}
    news.persist([article],received_at_ns=clock.now)
    clock.now += SECOND
    article.update(headline='Company updates guidance',updated_at=format_ns(clock.now))
    news.persist([article],received_at_ns=clock.now)
    assert len(news.read_as_of(cutoff_ns=clock.now,revisions=True))==2
    benchmarks = {'market':listings[-2],'sector':listings[-1]}
    resources = {'max_disk_bytes':budget,'min_free_bytes':min_free}
    windows,children = [],[]
    for index in range(0,days,5):
        child = snapshots.freeze_window(start_at_ns=sessions[index].open_at_ns,
            end_at_ns=sessions[min(index+4,days-1)].close_at_ns,
            cutoff_ns=max(sessions[min(index+4,days-1)].close_at_ns+10*SECOND,
                          clock.now if index+5>=days else 0),
            listing_ids=listings,benchmarks=benchmarks,resources=resources)
        windows.append(child)
        emit('window',ordinal=len(windows),snapshot_id=child.snapshot_id,db_bytes=disk_bytes(path))
    replay_seconds = 0
    for child in windows:
        start = perf_counter()
        dataset = snapshots.open(child.snapshot_id)
        children.append(DatasetChild(dataset.snapshot_id,dataset.digest,dataset.manifest['start_at_ns'],
            dataset.manifest['end_at_ns'],dataset.manifest['cutoff_ns'],dataset.known_at_ns,
            dataset.publication_id,dataset.publication_hash))
        checksum,seen = hashlib.sha256(),0
        for chunk in dataset.timeline.chunks():
            for row in chunk:
                checksum.update(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())
                seen += 1
        elapsed = perf_counter()-start
        replay_seconds = max(replay_seconds,elapsed)
        assert seen==len(dataset.timeline)
        emit('timeline',snapshot_id=child.snapshot_id,seconds=elapsed,count=seen,digest=checksum.hexdigest())
        del dataset
        gc.collect()
    bundle_seconds,frozen_unchanged = None,None
    if days==20:
        research = DatasetService(snapshots)
        request = DatasetBundle(tuple(children),ResearchNamespace(*snapshots.open(children[0].snapshot_id).manifest['namespace']),
                                max_disk_bytes=budget,min_free_bytes=min_free)
        bundle = research.freeze_bundle(request)
        bundle_id = bundle.bundle_id
        del bundle
        gc.collect()
        def bundle_fingerprint():
            result = research.open_bundle(bundle_id)
            checksum = hashlib.sha256(json.dumps({'manifest':result.manifest,'report':result.report},
                sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
            seen,counts = 0,{'BAR':0,'QUOTE':0,'NEWS':0}
            for chunk in result.timeline.chunks():
                for row in chunk:
                    checksum.update(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())
                    seen += 1
                    if row['table']=='intraday_observations' and row['kind'] in counts:
                        counts[row['kind']] += 1
                    elif row['table']=='intraday_news_versions':
                        counts['NEWS'] += 1
            assert seen==len(result.timeline)
            assert counts=={'BAR':total,'QUOTE':total,'NEWS':2}
            return checksum.hexdigest(),seen
        start = perf_counter()
        before,seen = bundle_fingerprint()
        bundle_seconds = perf_counter()-start
        emit('bundle_timeline',bundle_id=bundle_id,seconds=bundle_seconds,count=seen,digest=before)
        clock.now += SECOND
        store.persist([envelope(store,listings[0],'BAR',sessions[0].open_at_ns,clock.now,number+1,revision=True)])
        article.update(headline='Later revision',updated_at=format_ns(clock.now))
        news.persist([article],received_at_ns=clock.now)
        after,_ = bundle_fingerprint()
        frozen_unchanged = before==after
        assert frozen_unchanged
    queries = []
    # Preserve the original twenty prefix queries for the 30x20 comparison.
    for index in range(20):
        session_index = index%len(sessions) if days<=20 else index*(days-1)//19
        cutoff = sessions[session_index].close_at_ns+10*SECOND
        start = perf_counter()
        rows = store.read_as_of('QUOTE',cutoff_ns=cutoff,listing_ids=(listings[index%count],))
        expected = sum((session.close_at_ns-session.open_at_ns)//MINUTE for session in sessions[:session_index+1])
        assert len(rows)==expected
        assert all(row['kind']=='QUOTE' and row['listing_id']==listings[index%count]
                   and row['available_at_ns']<=cutoff for row in rows)
        assert rows[0]['event_time_ns']==sessions[0].open_at_ns+MINUTE+9*SECOND
        assert rows[-1]['event_time_ns']==sessions[session_index].close_at_ns+9*SECOND
        queries.append((perf_counter()-start)*1000)
        del rows
    p95 = sorted(queries)[18]
    runtime = collector_smoke(SCHEMA,calendar,opening,budget)
    assert attempts['count']==0
    rss,size = peak_memory_bytes(),disk_bytes(path)
    gates = {'query_p95':p95<=250,'window_timeline_replay':replay_seconds<=60,
             'original_30x20_bundle_replay':None if days!=20 or quick else bundle_seconds<=60,'rss':rss<=2*1024**3,
             'zero_loss':accepted==2*total and runtime['silent_losses']==0,'disk':size<=budget}
    emit('summary',sessions=days,symbols=count,bars=total,quotes=total,query_asof_p95_ms=p95,
         timeline_replay_max_seconds=replay_seconds,peak_memory_bytes=rss,db_bytes=size,
         original_30x20_bundle_replay_seconds=bundle_seconds,frozen_unchanged=frozen_unchanged,
         quick_fixture=quick,sustainability_status='NOT_EVALUATED_QUICK' if quick else
            ('PASS' if all(value is not False for value in gates.values()) else 'FAIL'),
         source_disk_growth_per_session_bytes=growth,network_attempts=attempts['count'],runtime=runtime,
         gates=gates,g1_data='INSUFFICIENTE',economic_result='NOT_EVALUATED')
    store.provider.transport._client.close()
    db.close()
    return all(value is not False for value in gates.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sessions',type=int,choices=(5,20,60),required=True)
    parser.add_argument('--max-disk-bytes',type=int,required=True)
    parser.add_argument('--min-free-bytes',type=int,required=True)
    parser.add_argument('--quick',action='store_true')
    args = parser.parse_args()
    path = target_path()
    if args.max_disk_bytes<=0 or args.min_free_bytes<=0 or shutil.disk_usage(path.parent).free<args.min_free_bytes:
        raise ValueError('RESOURCE_LIMIT')
    with path.open('xb'):
        pass
    with blocked_network() as attempts,patch.dict(os.environ,{'PYTHON_DOTENV_DISABLED':'1','ENABLE_REAL_DATA':'false',
        'ENABLE_ALPACA_DATA':'false','ENABLE_ALPACA_COLLECTOR':'false','ENABLE_REAL_NEWS':'false','ENABLE_ALERTS':'false','ENABLE_TELEGRAM':'false'}):
        success = run(path,args.sessions,args.max_disk_bytes,args.min_free_bytes,args.quick,attempts)
    return 0 if success else 1


if __name__=='__main__':
    raise SystemExit(main())
