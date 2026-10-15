"""Bounded, causal context over published frozen occurrences; no current daily tables.

The caller supplies archive-validated rows (or uses DatasetService). Pure calls
are useful for offline research, and never certify source authenticity or G1.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta
from statistics import median
from types import SimpleNamespace

from backend.app.intraday.aggregate import MINUTE_NS, _crosses_action, aggregate_as_of
from backend.app.intraday.contracts import canonical_json
from backend.app.intraday.quality import _Index
from backend.app.intraday.replay import _family, select_versions, visible_rows
from backend.app.intraday_research.contracts import ResearchError, ResearchNamespace, canonical_hash, digest, integer

_COMMON = {'table','id','provider','profile_id','feed','data_mode','provenance','replay_grade','listing_id',
    'kind','capture_id','ingest_sequence','received_at_ns','persisted_at_ns','available_at_ns','event_time_ns',
    'admission_id','publication_id','publication_hash','payload','payload_hash','quality','logical_key','metadata_dependency'}
_FIELDS = {'BAR':{'bar_end_ns'},'QUOTE':set(),'EVENT':{'event_type','effective_at_ns','scheduled_at_ns'},
    'IDENTITY':{'confirmed','valid_from_ns','valid_to_ns'},'CALENDAR':{'session_date','open_at_ns','close_at_ns'},
    'UNIVERSE':set(),'CONTROL':set(),'STATUS':set(),'LULD':set(),'NEWS':{'article_id','updated_at_ns','links'}}


def sealed(value):
    value['fingerprint'] = canonical_hash(value)
    return value


class ResearchContext:
    """One decision, at most 30 previous sessions and 30 listings, no implicit clock.

    Numeric history and metadata are charged before copying them (2 GiB cap);
    the revision/context cache separately retains the unchanged 64 MiB cap.
    excess raises RESOURCE_LIMIT instead of producing an incomplete context.
    """
    def __init__(self, rows, *, namespace, listing_id, session_date, cutoff_ns, benchmarks=None,
                 benchmarks_known_at_ns=None, benchmark_evidence_hash=None, max_bytes=2_147_483_648):
        integer(cutoff_ns)
        integer(listing_id,positive=True)
        try:
            if type(session_date) is not str or date.fromisoformat(session_date).isoformat()!=session_date:
                raise ValueError
        except (ValueError,TypeError):
            raise ResearchError('INVALID_CONTRACT') from None
        if type(namespace) is not ResearchNamespace or type(max_bytes) is not int or not 0<max_bytes<=2_147_483_648:
            raise ResearchError('INVALID_CONTRACT')
        self.namespace,self.listing_id,self.session_date,self.cutoff_ns = namespace,listing_id,session_date,cutoff_ns
        visible,total = [],0
        for row in rows:
            at = row.get('available_at_ns')
            if at is None or at>cutoff_ns:
                continue  # Future payloads, even malformed, cannot affect a prefix.
            family = _family(row)
            if family=='BAR' and (row['payload'].get('currency')!='USD' or row['payload'].get('adjustment')!='raw'):
                raise ResearchError('INVALID_CONTRACT')
            projected = {k:v for k,v in row.items() if k in _COMMON|_FIELDS.get(family,set())}
            size = len(canonical_json(projected).encode())*16
            if total+size>max_bytes:
                raise ResearchError('RESOURCE_LIMIT')
            total += size
            checked = visible_rows([row],cutoff_ns=cutoff_ns,namespace=namespace.key)[0]
            visible.append({k:v for k,v in checked.items() if k in projected})
        self.rows = visible
        self.index = _Index(visible,max_cache_bytes=min(max_bytes,67_108_864))
        if len({r['listing_id'] for r in visible if r.get('listing_id') is not None})>30:
            raise ResearchError('RESOURCE_LIMIT')
        self.sessions = self._sessions()[-31:]
        self.current = next((s for s in self.sessions if s['session_date']==session_date),None)
        if self.current is None:
            raise ResearchError('INPUT_MISSING')
        universes = select_versions(self.index.family['UNIVERSE'],family='UNIVERSE',cutoff_ns=min(cutoff_ns,self.current['open_at_ns']-1))
        universe = next((r for r in universes if r['payload'].get('session_date')==session_date),None)
        self.benchmarks = dict(universe['payload'].get('benchmarks',{})) if universe else {}
        if benchmarks is not None:
            integer(benchmarks_known_at_ns)
            digest(benchmark_evidence_hash)
            if benchmarks_known_at_ns>=self.current['open_at_ns'] or benchmarks_known_at_ns>cutoff_ns:
                raise ResearchError('INPUT_MISSING')
            self.benchmarks = dict(benchmarks)
        if (not set(self.benchmarks)<={'market','sector'} or any(type(i) is not int or i<=0 for i in self.benchmarks.values())):
            raise ResearchError('INVALID_CONTRACT')
        self.events = self.index.event_versions(cutoff_ns)
        self._bars = {}
        refs = hashlib.sha256()
        for table,source_id,payload_hash,available in sorted([[r['table'],r['id'],r['payload_hash'],r['available_at_ns']] for r in visible]):
            refs.update(canonical_json({'table':table,'id':source_id,'hash':payload_hash,'available_at_ns':available}).encode())
        self.input_hash = canonical_hash({'namespace':list(namespace.key),'listing_id':listing_id,
            'session_date':session_date,'cutoff_ns':cutoff_ns,'benchmarks':self.benchmarks,
            'benchmarks_known_at_ns':benchmarks_known_at_ns,
            'benchmark_evidence_hash':benchmark_evidence_hash,
            'refs_hash':refs.hexdigest()})

    def _sessions(self):
        headers = [r for r in self.index.family['CONTROL'] if r['payload'].get('metadata_kind')=='CALENDAR']
        calendars = select_versions(self.index.family['CALENDAR'],family='CALENDAR',cutoff_ns=self.cutoff_ns)
        for header in headers:
            payload = header['payload']
            if payload.get('complete') is True:
                for day,ref in payload.get('session_ids',{}).items():
                    if day<=self.session_date and not any(r['session_date']==day and r['id']==ref for r in self.index.family['CALENDAR']):
                        raise ResearchError('INPUT_MISSING')
        result = []
        for row in calendars:
            day = row['session_date']
            if day>self.session_date:
                continue
            batch = max((r for r in headers if r['payload'].get('start','')<=day<=r['payload'].get('end','')),
                        key=lambda r:(r['received_at_ns'],r['id']),default=None)
            payload = batch['payload'] if batch else {}
            if payload.get('complete') is not True or payload.get('member_count')!=len(payload.get('session_ids',{})):
                raise ResearchError('INPUT_MISSING')
            if day not in payload['session_ids']:
                continue  # Complete replacement explicitly declares a closed day.
            if payload['session_ids'][day]!=row['id']:
                raise ResearchError('INPUT_MISSING')
            opening,closing = row['open_at_ns'],row['close_at_ns']
            if not opening<closing or (closing-opening)%MINUTE_NS or closing-opening>390*MINUTE_NS:
                raise ResearchError('INVALID_CONTRACT')
            result.append(dict(row,known_at_ns=max(row['available_at_ns'],batch['available_at_ns'])))
        result.sort(key=lambda r:r['open_at_ns'])
        if result:
            first,last = date.fromisoformat(result[-31:][0]['session_date']),date.fromisoformat(self.session_date)
            if (last-first).days>366:
                raise ResearchError('RESOURCE_LIMIT')
            day = first
            while day<=last:
                matching = [r for r in headers if r['payload'].get('start','')<=day.isoformat()<=r['payload'].get('end','')]
                batch = max(matching,key=lambda r:(r['received_at_ns'],r['id']),default=None)
                if batch is None or batch['payload'].get('complete') is not True:
                    raise ResearchError('INPUT_MISSING')
                day += timedelta(days=1)
        return result

    def corporate(self, listing):
        return [r for r in self.events if r['event_type']=='CORPORATE_ACTION' and r['listing_id'] in (None,listing)
                and r['payload'].get('discontinuity') and not r['payload'].get('cancelled')]

    def bars(self, minutes=1, *, listing_id=None):
        listing = self.listing_id if listing_id is None else listing_id
        key = listing,minutes
        if key in self._bars:
            return self._bars[key]
        sources = [r for (i,_),bucket in self.index.bars.items() if i==listing for r in bucket]
        events = self.corporate(listing)
        statuses = select_versions(self.index.family['STATUS'],family='STATUS',cutoff_ns=self.cutoff_ns,listing_ids=(listing,))
        boundaries = [r['available_at_ns'] for r in self.index.family['CONTROL'] if r['kind'] in {'GAP','STOP','CAPTURE_START'}]
        boundaries += [r['event_time_ns'] for r in statuses if
            (r['quality']!='VALID' or r['payload'].get('state')!='NORMAL')]
        bars,segment,previous = [],0,None
        prior_session = None
        for session in self.sessions:
            opening,closing = session['open_at_ns'],session['close_at_ns']
            calendar = SimpleNamespace(open_at_ns=opening,close_at_ns=closing,known_at_ns=session['known_at_ns'],version_id=session['id'])
            result = aggregate_as_of([r for r in sources if opening<=r['event_time_ns']<closing],calendar,
                cutoff_ns=self.cutoff_ns,minutes=minutes,events=events)
            expected = opening
            # An overnight bridge requires explicit complete calendar coverage.
            if prior_session is not None and (previous is None or previous['end_at_ns']!=prior_session['close_at_ns']):
                segment += 1
            for bar in result['bars']:
                status = self.index.context(bar['end_at_ns'])
                known = [r for r in statuses if opening<=r['event_time_ns']<=bar['end_at_ns']]
                interrupted = bool(known and (known[-1]['quality']!='VALID' or known[-1]['payload'].get('state')!='NORMAL'))
                if interrupted or status['state']!='LIVE' or not status['listing_states'].get(listing,{}).get('live_eligible'):
                    segment += 1
                    continue
                if (bar['start_at_ns']!=expected or any(_crosses_action(e,previous['end_at_ns'] if previous else opening,bar['end_at_ns']) for e in events)
                    or any(max(opening,previous['end_at_ns'] if previous else opening)<=stamp<bar['end_at_ns'] for stamp in boundaries)):
                    segment += 1
                bar = dict(bar,session_date=session['session_date'],session_open_ns=opening,session_close_ns=closing,segment=segment)
                bars.append(bar)
                expected,previous = bar['end_at_ns'],bar
            prior_session = session
        self._bars[key] = bars
        return bars

    def daily(self):
        sessions = []
        source_hashes = {r['id']:r['payload_hash'] for (listing,_),values in self.index.bars.items()
                         if listing==self.listing_id for r in values}
        corporate = self.corporate(self.listing_id)
        resets = [e['effective_at_ns'] for e in corporate if e['effective_at_ns'] is not None and e['effective_at_ns']<=self.current['open_at_ns']]
        reset = max(resets,default=0)
        unknown = any(e['effective_at_ns'] is None for e in corporate)
        bars = self.bars()
        for session in self.sessions[:-1]:
            opening,closing = session['open_at_ns'],session['close_at_ns']
            selected = [r for r in bars if r['session_date']==session['session_date']]
            if (unknown or opening<reset or closing>self.cutoff_ns or len(selected)!=(closing-opening)//MINUTE_NS
                or any(_crosses_action(e,opening,closing) for e in corporate)):
                continue
            available = max(closing,session['known_at_ns'],*(r['available_at_ns'] for r in selected))
            if self.index.continuity(self.listing_id,opening,closing,closing) is not None:
                continue
            volume = math.fsum(r['volume'] for r in selected)
            if volume<=0 or any(r['vwap'] is None or r['volume']<=0 for r in selected):
                continue
            vwap = math.fsum(r['vwap']*(r['volume']/volume) for r in selected)
            dollar = vwap*volume
            if not math.isfinite(dollar):
                raise ResearchError('INVALID_CONTRACT')
            member_ids = [i for r in selected for i in r['member_ids']]
            source_digest = hashlib.sha256()
            for source_id in member_ids:
                source_digest.update(canonical_json({'table':'intraday_observations','id':source_id,'hash':source_hashes[source_id]}).encode())
            sessions.append({'version':'intraday-daily-bar-v1','source_digest':source_digest.hexdigest(),
                'session_date':session['session_date'],'open':selected[0]['open'],'high':max(r['high'] for r in selected),
                'low':min(r['low'] for r in selected),'close':selected[-1]['close'],'volume':volume,'vwap':vwap,
                'dollar_volume':dollar,'available_at_ns':available,'calendar_ref':[session['id'],session['payload_hash']],
                'member_ids':member_ids})
        previous_day = self.sessions[-2]['session_date'] if len(self.sessions)>1 else None
        previous = next((s for s in sessions if s['session_date']==previous_day),None)
        last6 = [s['session_date'] for s in self.sessions[-7:-1]]
        returns = len(last6)==6 and [s['session_date'] for s in sessions[-6:]]==last6
        current = [r for r in bars if r['session_date']==self.session_date]
        initial = current[0] if current and current[0]['start_at_ns']==self.current['open_at_ns'] else None
        return sealed({'version':'intraday-daily-context-v1','input_hash':self.input_hash,'cutoff_ns':self.cutoff_ns,
            'sessions':sessions,'previous_close':previous['close'] if previous else None,
            'previous_high':previous['high'] if previous else None,'previous_low':previous['low'] if previous else None,
            'previous_range':previous['high']-previous['low'] if previous else None,
            'median_dollar_volume20':median(s['dollar_volume'] for s in sessions[-20:]) if len(sessions)>=20 else None,
            'gap':initial['open']/previous['close']-1 if initial and previous else None,
            'return5':sessions[-1]['close']/sessions[-6]['close']-1 if returns else None,
            'reason_code':None if len(sessions)>=20 and previous is not None and returns else 'WARMUP_INSUFFICIENT'})
