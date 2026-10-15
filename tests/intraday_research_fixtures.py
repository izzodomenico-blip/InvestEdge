"""Synthetic research metadata only; no captured data or economic evidence."""
from __future__ import annotations

from intraday_fixtures import HASH, NS, PROFILE, seed_graph

RESEARCH_TABLES = (
    "intraday_research_manifests", "intraday_research_trials",
    "intraday_research_trial_events", "intraday_research_results",
    "intraday_research_holdout_events", "intraday_quote_size_attestations",
    "intraday_price_increment_attestations", "intraday_news_source_attestations",
    "intraday_research_manifest_datasets", "intraday_research_manifest_attestations",
)


def manifest(**changes):
    from backend.app.intraday_research.contracts import (
        DatasetRef,
        ResearchManifest,
        ResearchNamespace,
        ResourceLimits,
    )

    values = {
        "namespace": ResearchNamespace(PROFILE, "sip", "REAL", "CAPTURED", "STRICT_PIT"),
        "resources": ResourceLimits(max_disk_bytes=4_294_967_296, min_free_bytes=536_870_912),
        "datasets": (DatasetRef(1, HASH),),
        "start_at_ns": NS, "end_at_ns": NS + 1_000_000, "cutoff_ns": NS + 2_000_000,
        "code_revision": "c" * 40,
    }
    return ResearchManifest(**(values | changes))


def seed_research_inputs(connection):
    rows = seed_graph(connection)
    connection.commit()
    return rows


def quote_terms_fixture(connection, *, lots='100', tick='0.01', namespace=None, available=NS+10,
                        known=NS-20, received=NS-10, valid_from=NS-100, valid_to=None,
                        authorities=(), price_min='0', price_max=None):
    """Independently pinned synthetic publication, never an official-source claim."""
    from dataclasses import asdict

    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import AttestationAuthority, canonical_hash
    from backend.app.intraday_research.registry import Registry
    namespace = namespace or manifest().namespace
    contract = {'version':'quote-source-contract-v1','provider':'alpaca','feed':namespace.feed,
                'schema':'alpaca-market-row-v1','source':'STREAM','size_unit':'ROUND_LOTS'}
    common = {'listing_id':1,'valid_from_ns':valid_from,'valid_to_ns':valid_to,
              'known_at_ns':known,'first_received_at_ns':received}
    documents = [dict(common,version='quote-size-attestation-v1',shares_per_unit=lots),
                 dict(common,version='price-increment-attestation-v1',increment=tick,price_min=price_min,price_max=price_max)]
    evidence = {'version':'quote-terms-publication-v1','publisher':'SYNTHETIC_FIXTURE',
                'namespace':asdict(namespace),'contract_hash':canonical_hash(contract),'terms':documents}
    authority = AttestationAuthority(namespace,'SYNTHETIC_FIXTURE',canonical_json(contract),canonical_hash(evidence))
    registry = Registry(connection,attestation_authorities=(*authorities,authority))
    refs = tuple(registry.import_attestation(document,namespace=namespace,evidence=evidence,
                   authority_hash=authority.authority_hash,now_ns=available) for document in documents)
    return registry,refs,authority,evidence


def quote_input(namespace=None, **changes):
    from dataclasses import asdict

    from backend.app.intraday_research.contracts import canonical_hash
    namespace = namespace or manifest().namespace
    payload = {'version':'alpaca-market-row-v1','source':'STREAM','currency':'USD','adjustment':'raw',
               'raw':{'bp':100,'ap':101,'bs':2,'as':3},'reason_code':None,'size_unit':'ROUND_LOTS'}
    return dict(asdict(namespace),table='intraday_observations',id=1,provider='alpaca',kind='QUOTE',listing_id=1,
                event_time_ns=NS,received_at_ns=NS+1,first_received_at_ns=NS+1,persisted_at_ns=NS+2,
                available_at_ns=NS+3,quality='VALID',payload=payload,payload_hash=canonical_hash(payload)) | changes


def seed_registered_evidence(connection):
    from backend.app.intraday_research.registry import Registry

    seed_research_inputs(connection)
    saved = manifest()
    registry = Registry(connection)
    ref = registry.preregister(saved, now_ns=NS + 3_000_000)
    registry._insert("intraday_research_results", saved.namespace, {}, NS + 4_000_000,
        {"manifest_id": ref["manifest_id"], "trial_id": ref["trial_ids"][0]})
    for table, column in zip(RESEARCH_TABLES[5:8], ("quote_size_id", "price_increment_id", "news_source_id"), strict=True):
        row_id = registry._insert(table, saved.namespace, {}, NS + 1_000_000,
            {"attestation_hash": HASH, "source_hash": HASH, "authority_hash": HASH,
             "listing_id": 1, "valid_from_ns": NS, "available_at_ns": NS + 1_000_000})
        registry._insert("intraday_research_manifest_attestations", saved.namespace, {}, NS + 3_000_000,
            {"manifest_id": ref["manifest_id"], column: row_id, "attestation_hash": HASH})
    connection.commit()
    return ref


def research_history(*, days=21, minutes=60):
    """Synthetic published rows; UTC opens explicitly model the DST change."""
    from datetime import UTC, date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from test_intraday_replay import row

    from backend.app.intraday_research.contracts import ResearchNamespace

    minute, second = 60_000_000_000, 1_000_000_000
    namespace = ResearchNamespace('a'*64,'sip','DEMO','SYNTHETIC','RESEARCH_ONLY')
    dates, day = [], date(2026,10,12)
    while len(dates)<days:
        if day.weekday()<5:
            dates.append(day)
        day += timedelta(days=1)
    openings = [int(datetime(d.year,d.month,d.day,9,30,tzinfo=ZoneInfo('America/New_York')).astimezone(UTC).timestamp())*second
                for d in dates]
    rows = []
    def add(family, stamp, payload, **fields):
        value = row(family,at=stamp,received=stamp,available=stamp,row_id=len(rows)+1,
                    data_mode='DEMO',provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY',payload=payload,**fields)
        rows.append(value)
        return value
    identities = {i:add('IDENTITY',openings[0]-100*second,{'mic':'XNAS'},listing_id=i) for i in (1,2,3)}
    for source in ('bls','fed','issuer'):
        document = add('CONTROL',openings[0]-90*second,{'metadata_kind':'EVENT_DOCUMENT'},kind='BOOTSTRAP',provider=source)
        add('EVENT',openings[0]-80*second,{'version':'official-event-calendar-v1','source':source,
            'coverage':'ANNOUNCED_EVENTS_ONLY','authenticity_basis':'LOCAL_OFFICIAL_COPY',
            'document':{'id':document['id'],'hash':document['payload_hash']}},provider=source,
            logical_key=source,listing_id=1 if source=='issuer' else None,
            event_type='EARNINGS' if source=='issuer' else 'MACRO',scheduled_at_ns=openings[-1]+500*minute)
    session_ids = {}
    for day, opening in zip(dates,openings,strict=True):
        closing, capture = opening+minutes*minute,f'fixture-{day}'
        cal = add('CALENDAR',openings[0]-70*second,{'source':'ALPACA_CALENDAR'},session_date=day.isoformat(),
                  open_at_ns=opening,close_at_ns=closing,logical_key=f'calendar:{day}')
        session_ids[day.isoformat()] = cal['id']
        add('UNIVERSE',opening-60*second,{'kind':'PROSPECTIVE','session_date':day.isoformat(),
            'calendar_version_id':cal['id'],'calendar_hash':cal['payload_hash'],'open_at_ns':opening,'close_at_ns':closing,
            'benchmarks':{'market':2,'sector':3},'members':[{'listing_id':i,'eligible':True,
                'identity_version_id':v['id'],'identity_hash':v['payload_hash']} for i,v in identities.items()]})
        subscriptions = {'market':{'bars':['fixture'],'quotes':['fixture'],'statuses':['fixture']},'news':{'news':['fixture']}}
        add('CONTROL',opening-5*second,{'listing_ids':[1,2,3],'subscriptions':subscriptions,
            'continuity_policy':{'version':'collector-continuity-v1','socket_silence_ns':300*second,'lease_ns':300*second}},
            kind='CAPTURE_START',capture=capture)
        acks = [add('CONTROL',opening-(4-i)*second,{'channel':ch,'subscriptions':subscriptions[ch],
            'received_at_ns':opening-(4-i)*second},kind='ACK',capture=capture)
                for i,ch in enumerate(('market','news'))]
        checkpoints = [add('EVENT',opening-2*second,{'version':'utp-status-checkpoint-v1','state':'NORMAL',
            'expires_at_ns':closing+30*second,'reason_code':None},capture=capture,listing_id=i,
            event_type='RESUME',effective_at_ns=opening-2*second,logical_key=f'status:{day}:{i}') for i in (1,2,3)]
        add('CONTROL',opening-second,{'metadata_kind':'COLLECTOR_HANDSHAKE','continuity_attested':True,
            'barrier_at_ns':opening-second,'ack_refs':[{'id':r['id'],'hash':r['payload_hash'],
                'publication_id':r['publication_id'],'publication_hash':r['publication_hash']} for r in acks],
            'listings':[{'listing_id':r['listing_id'],'checkpoint_id':r['id'],'checkpoint_hash':r['payload_hash'],
                'checkpoint_admission_id':r['admission_id'],'snapshot_at_ns':opening-2*second,
                'expires_at_ns':closing+30*second,'status_refs':[]} for r in checkpoints]},kind='BOOTSTRAP',capture=capture)
        for offset in range(minutes+1):
            stamp = opening+offset*minute
            for clock in (stamp,stamp+second):
                add('CONTROL',clock,{'metadata_kind':'TRANSPORT_LIVENESS','channel':'news',
                    'ping_sent_at_ns':clock-1,'pong_received_at_ns':clock},kind='CLOCK',capture=capture)
            if offset==minutes:
                continue
            for listing in (1,2,3):
                add('BAR',stamp+minute+second,{'version':'alpaca-market-row-v1','source':'STREAM','currency':'USD','adjustment':'raw',
                    'raw':{'o':100,'h':100.1,'l':99.9,'c':100,'v':10000,'vw':100}},capture=capture,
                    listing_id=listing,event_time_ns=stamp,bar_end_ns=stamp+minute,logical_key=f'bar:{day}:{listing}:{offset}')
        decision = closing+second
        add('QUOTE',decision,{'version':'alpaca-market-row-v1','source':'STREAM','currency':'USD','adjustment':'raw',
            'size_unit':'ROUND_LOTS','reason_code':None,'raw':{'bp':99.99,'ap':100.01,'bs':2,'as':3}},
            capture=capture,event_time_ns=closing,listing_id=1)
    add('CONTROL',openings[0]-70*second,{'metadata_kind':'CALENDAR','complete':True,'start':dates[0].isoformat(),
        'end':dates[-1].isoformat(),'session_ids':session_ids,'member_count':len(session_ids)},kind='BOOTSTRAP')
    return namespace,rows,dates[-1].isoformat(),openings[-1]


def news_terms_fixture(connection, *, fact=None, previous=None, origin=None, article_id=101,
                       available=NS+10, article_available=NS+3, authorities=(), namespace=None):
    """Independently pinned SYNTHETIC primary original and exact archived article."""
    from dataclasses import asdict

    from intraday_fixtures import common_row, insert

    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import AttestationAuthority, canonical_hash
    from backend.app.intraday_research.registry import Registry
    namespace = namespace or manifest().namespace
    fact = fact or {'kind':'GUIDANCE','event_id':f'GUIDANCE_{article_id}','issuer_id':'ISSUER_FIXTURE',
        'listing_id':1,'status':'CONFIRMED','statement':'Issuer raises revenue guidance for FY2026.',
        'period':'FY2026','units':{'revenue':'USD_MILLION','eps':'USD_PER_SHARE'},
        'metrics':{'revenue':{'low':'110','high':'120'},'eps':{'low':'2','high':'3'}}}
    rights = {'allow_summary':False,'allow_content':False,'retention':'NONE','evidence_hash':None,'version':'news-rights-v1'}
    payload = {'version':'alpaca-news-row-v1','wire_source':'STREAM','source':'fixture',
        'source_article_id':str(article_id),'headline':fact['statement'],'summary':None,'content':None,
        'content_state':'RIGHTS_UNATTESTED','url':None,'author':None,'symbols':['FIX'],'language':None,
        'published_at_ns':article_available-3,'updated_at_ns':article_available-3,'rights':rights}
    stored = common_row(**asdict(namespace),id=article_id,article_id=canonical_hash({'article':article_id}),
        published_at_ns=article_available-3,updated_at_ns=article_available-3,supersedes_id=None,
        received_at_ns=article_available-2,persisted_at_ns=article_available-1,admitted_at_ns=article_available,
        available_at_ns=article_available,event_time_ns=article_available-3,ingest_sequence=article_id,
        availability_floor_ns=article_available-3,
        payload_json=canonical_json(payload),payload_hash=canonical_hash(payload),logical_key=f'news:{article_id}')
    insert(connection,'intraday_news_versions',stored)
    connection.commit()
    document = {'version':'news-source-attestation-v1','listing_id':1,'issuer_id':'ISSUER_FIXTURE',
        'article_version_id':article_id,'article_id':stored['article_id'],'article_hash':stored['payload_hash'],
        'fact_id':fact['event_id'],'previous_ref':asdict(previous) if previous else None,
        'origin_ref':asdict(origin) if origin else None,
        'valid_from_ns':article_available-100,'valid_to_ns':None,'known_at_ns':article_available-1,
        'first_received_at_ns':article_available}
    original = {'version':'issuer-facts-v1','issuer_id':'ISSUER_FIXTURE','published_at_ns':article_available-3,'facts':[fact]}
    contract = {'version':'news-primary-contract-v1','schema':'issuer-facts-v1','issuer_id':'ISSUER_FIXTURE',
        'listing_ids':[1],'archive_originals':True,'research_use':True}
    evidence = {'version':'news-primary-publication-v1','publisher':'SYNTHETIC_FIXTURE','namespace':asdict(namespace),
        'contract_hash':canonical_hash(contract),'original_json':canonical_json(original),'bindings':[document]}
    authority = AttestationAuthority(namespace,'SYNTHETIC_FIXTURE',canonical_json(contract),canonical_hash(evidence))
    registry = Registry(connection,attestation_authorities=(*authorities,authority))
    reference = registry.import_attestation(document,namespace=namespace,evidence=evidence,
        authority_hash=authority.authority_hash,now_ns=available)
    row = stored | {'table':'intraday_news_versions','kind':'NEWS','payload':payload,'first_received_at_ns':stored['received_at_ns'],
        'links':[{'id':article_id,'listing_id':1,'available_at_ns':article_available,'cluster_id':f'cluster:{fact["event_id"]}',
                  'payload_hash':canonical_hash({'mapping':article_id}), 'payload':{'symbol':'FIX','reason_code':None,'identity':{'id':1}}}]}
    return registry,reference,authority,row,document,evidence


def setup_frames(*, family='TREND_PULLBACK', namespace=None):
    """Manual frozen numeric frames; no market or economic evidence."""
    from dataclasses import asdict

    from backend.app.intraday_research.contracts import ResearchNamespace, canonical_hash
    namespace = namespace or ResearchNamespace(PROFILE,'sip','DEMO','SYNTHETIC','RESEARCH_ONLY')
    minute = 60_000_000_000
    opening = NS
    frames = []
    for offset in range(44,51):
        close = 100.2 if family=='TREND_PULLBACK' else 100
        bar = {'start_at_ns':opening+(offset-1)*minute,'end_at_ns':opening+offset*minute,
            'available_at_ns':opening+offset*minute+1,'open':close,'high':close+.1,'low':99.9,
            'close':close,'complete':True,'segment':0}
        f = {'ema8_1m':100,'ema20_1m':99.8,'vwap_session':100,'atr14_1m':1,'roc5_1m':.001,
            'rvol_1m':1,'ema8_5m':101,'ema20_5m':100,'ema20_5m_slope3':.001,
            'context15m_close':101,'ema8_15m':100,'context15m_roc2_sign':0,'rs_market15m':.001,'rs_sector15m':.002}
        if offset==50:
            bar.update(close=100.5,high=100.6)
            f['rvol_1m']=1.5
        body = {'version':'intraday-setup-frame-v1','namespace':asdict(namespace),'listing_id':1,'session_date':'2023-11-14',
            'open_at_ns':opening,'cutoff_ns':bar['available_at_ns'],'input_hash':HASH,'bar':bar,'values':f,
            'or_high':100.25,'or_available_at_ns':opening+15*minute+1,'or_complete':True}
        body['fingerprint']=canonical_hash(body)
        frames.append(body)
    return tuple(frames)


def setup_common(frame, *, holding=15, reasons=()):
    from backend.app.intraday_research.contracts import canonical_hash
    body = {'input_hash':frame['input_hash'],'cutoff_ns':frame['cutoff_ns'],'holding_minutes':holding,
        'technical_eligible':not reasons,'reasons':list(reasons),'news_coverage':'COVERED_ZERO',
        'quote_conversion':{'size_conversion_attested':True,'bid_shares':100,'ask_shares':100},
        'economic_status':'NON_IDONEO'}
    return body | {'fingerprint':canonical_hash(body)}
