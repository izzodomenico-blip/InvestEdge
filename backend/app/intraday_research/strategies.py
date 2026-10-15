"""Frozen candidate setups and ablations. No simulator, provider or orders.

Frames are captured when their inputs become available; a later frame must
never be substituted for a past pullback or consolidation observation.
"""
from __future__ import annotations

import math
from dataclasses import asdict

from backend.app.intraday.aggregate import MINUTE_NS
from backend.app.intraday_research.context import sealed
from backend.app.intraday_research.contracts import (
    CandidateConfig,
    ResearchError,
    ResearchNamespace,
    canonical_hash,
    integer,
)


def _checked(value):
    if type(value) is not dict or value.get('fingerprint')!=canonical_hash({k:v for k,v in value.items() if k!='fingerprint'}):
        raise ResearchError('INVALID_CONTRACT')
    return value


def feature_frame(context,*,technical=True):
    bars = context.bars()
    bar = bars[-1] if bars and bars[-1]['session_date']==context.session_date else None
    if bar is not None:
        bar = dict(bar,namespace=list(bar['namespace']))
    if technical:
        from backend.app.intraday_research.features import compute_features
        values = compute_features(context)
        keys = ('ema8_1m','ema20_1m','vwap_session','atr14_1m','roc5_1m','rvol_1m','ema8_5m','ema20_5m',
            'ema20_5m_slope3','context15m_close','ema8_15m','context15m_roc2_sign','rs_market15m','rs_sector15m')
        values = {k:values[k] for k in keys}
    else:
        from backend.app.intraday_research.features import _atr, _current_segment
        values = {'atr14_1m':_atr(_current_segment(context,bars,1))}
    first = [b for b in context.bars(5) if b['session_date']==context.session_date and
             b['start_at_ns']<context.current['open_at_ns']+15*MINUTE_NS] if technical else []
    complete = len(first)==3 and [b['start_at_ns'] for b in first]==[context.current['open_at_ns']+i*5*MINUTE_NS for i in range(3)]
    return sealed({'version':'intraday-setup-frame-v1','namespace':asdict(context.namespace),'listing_id':context.listing_id,
        'session_date':context.session_date,'open_at_ns':context.current['open_at_ns'],'cutoff_ns':context.cutoff_ns,
        'input_hash':context.input_hash,'bar':bar,'values':values,'or_complete':complete,
        'or_high':max(b['high'] for b in first) if complete else None,
        'or_available_at_ns':max(b['available_at_ns'] for b in first) if complete else None})


def _finite(value):
    return type(value) in {int,float} and math.isfinite(value)


def evaluate_candidate(config,*,frames,common,news,ask=None,seen_keys=(),seen_events=()):
    if type(config) is not CandidateConfig or type(frames) is not tuple or not 1<=len(frames)<=7:
        raise ResearchError('INVALID_CONTRACT')
    frame = _checked(frames[-1])
    _checked(common)
    _checked(news)
    namespace = ResearchNamespace(**frame['namespace'])
    at = frame['cutoff_ns']
    integer(at)
    if (common['input_hash']!=frame['input_hash'] or common['cutoff_ns']!=at or common['holding_minutes']!=config.holding_minutes or
        news['namespace']!=frame['namespace'] or news['listing_id']!=frame['listing_id'] or news['cutoff_ns']!=at):
        raise ResearchError('INVALID_CONTRACT')
    if type(common.get('technical_eligible')) is not bool or common['technical_eligible']!=(not common['reasons']):
        raise ResearchError('INVALID_CONTRACT')
    reasons = set(common['reasons'])
    bar,values = frame['bar'],frame['values']
    if config.arm=='NEWS_ONLY' and bar and 0<=at-bar['end_at_ns']<MINUTE_NS and 0<=bar['available_at_ns']-bar['end_at_ns']<=10_000_000_000:
        reasons.discard('BAR_DELAY')  # Delivery delay stays <=10s; news need not await a bar close.
    if news['coverage'] not in {'COVERED','COVERED_ZERO'}:
        reasons.add('NEWS_COVERAGE_UNKNOWN')
    if news['negative']:
        reasons.add('ADVERSE_NEWS')
    atr = values.get('atr14_1m')
    if not _finite(atr) or atr<=0:
        reasons.add('WARMUP_INSUFFICIENT')
    atr = atr if _finite(atr) and atr>0 else None
    structural,entry,event,bar_end,event_key,cluster_key = None,None,None,None,None,None
    positive = [v for v in news['positive'] if v['available_at_ns']<=at and
        0<=at-v['first_available_at_ns']<=60*MINUTE_NS and v['decay']>=.25]
    if config.arm=='NEWS_ONLY':
        def keys(value):
            scope = [asdict(namespace),frame['listing_id'],frame['session_date']]
            event_key = canonical_hash({'scope':scope,'issuer_id':value['issuer_id'],'event_id':value['event_id']})
            cluster_key = canonical_hash({'scope':scope,'cluster_id':value['cluster_id']}) if value.get('cluster_id') is not None else event_key
            return event_key,cluster_key
        known = set(seen_events)
        for value in (*positive,*news.get('expired',[])):
            event_token,cluster_token = keys(value)
            if event_token in known and value['available_at_ns']<=at:
                known.add(cluster_token)
        available = [v for v in positive if v['available_at_ns']==at and v['novel'] and not set(keys(v)).intersection(known)]
        if not available:
            reasons.add('NO_NEW_EVENT')
        else:
            event = min(available,key=lambda v:(v['available_at_ns'],v['issuer_id'],v['event_id']))
            event_key,cluster_key = keys(event)
        if not _finite(ask) or ask<=0:
            reasons.add('QUOTE_MISSING')
        elif atr is not None:
            entry = ask+.25*atr
        key_body = {'listing_id':frame['listing_id'],'session_date':frame['session_date'],'family':'NEWS_ONLY',
            'holding_minutes':config.holding_minutes,'event_key':event_key,'decision_at_ns':at}
        inputs = {'risk_atr':atr,'ask':ask,'news_hash':news['fingerprint'],'common_reasons':sorted(reasons)}
    else:
        needed = ('ema8_5m','ema20_5m','context15m_close','ema8_15m','rs_market15m','rs_sector15m','rvol_1m')
        if any(not _finite(values.get(k)) for k in needed):
            reasons.add('WARMUP_INSUFFICIENT')
        if bar is None or not bar['complete'] or bar['end_at_ns']>at or bar['available_at_ns']>at:
            reasons.add('BAR_NOT_CLOSED')
        elif at-bar['end_at_ns']>10_000_000_000:
            reasons.add('BAR_DELAY')
        bar_end = bar['end_at_ns'] if bar else None
        previous = frames[-4:-1] if config.family=='TREND_PULLBACK' else frames[-7:-1]
        required_count = 3 if config.family=='TREND_PULLBACK' else 6
        if len(previous)!=required_count:
            reasons.add('WARMUP_INSUFFICIENT')
        for ordinal,old in enumerate(reversed(previous),1):
            _checked(old)
            if (bar is None or old['namespace']!=frame['namespace'] or old['listing_id']!=frame['listing_id'] or old['session_date']!=frame['session_date'] or
                old['cutoff_ns']>=at or old['bar'] is None or not old['bar']['complete'] or old['bar']['end_at_ns']!=bar_end-ordinal*MINUTE_NS or
                old['bar']['available_at_ns']>old['cutoff_ns'] or old['bar']['segment']!=bar['segment']):
                reasons.add('WARMUP_INSUFFICIENT')
        if 'WARMUP_INSUFFICIENT' not in reasons and bar and atr:
            trend = (values['ema8_5m']>values['ema20_5m'] and values['context15m_close']>values['ema8_15m'] and
                     values['rs_market15m']>0 and values['rs_sector15m']>0)
            if config.family=='TREND_PULLBACK':
                extra = ('ema20_5m_slope3','context15m_roc2_sign','vwap_session','ema8_1m','roc5_1m')
                if any(not _finite(values.get(k)) for k in extra):
                    reasons.add('WARMUP_INSUFFICIENT')
                else:
                    trend = trend and values['ema20_5m_slope3']>0 and values['context15m_roc2_sign']>=0
                    valid = all(all(_finite(p['values'].get(k)) for k in ('vwap_session','ema8_1m','ema20_1m','atr14_1m','rvol_1m')) for p in previous)
                    touch = valid and any(min(abs(p['bar']['low']-p['values']['vwap_session']),abs(p['bar']['low']-p['values']['ema8_1m']))<=.1*p['values']['atr14_1m'] for p in previous)
                    valid = valid and all(p['bar']['close']>=p['values']['ema20_1m']-.25*p['values']['atr14_1m'] and p['values']['rvol_1m']<=1.5 for p in previous)
                    structural = min(p['bar']['low'] for p in previous)
                    if not touch or not valid or max(p['bar']['high'] for p in previous)-structural>1.5*atr:
                        reasons.add('PULLBACK')
                    if not (bar['close']>values['vwap_session'] and bar['close']>values['ema8_1m'] and
                        bar['close']>previous[-1]['bar']['high'] and values['roc5_1m']>0 and values['rvol_1m']>=1.2):
                        reasons.add('CONFIRMATION')
                    if bar['close']-values['vwap_session']>atr:
                        reasons.add('SPIKE')
            else:
                level = frame['or_high']
                if not frame['or_complete'] or not _finite(level) or frame['or_available_at_ns'] is None or frame['or_available_at_ns']>at:
                    reasons.add('OPENING_RANGE_INCOMPLETE')
                else:
                    structural = min(p['bar']['low'] for p in previous)
                    maximum = max(p['bar']['high'] for p in previous)
                    if (any(p['bar']['close']>level for p in previous) or maximum-structural>1.5*atr or not level-.25*atr<=maximum<=level):
                        reasons.add('CONSOLIDATION')
                    if not (bar['close']>level+.1*atr and previous[-1]['bar']['close']<=level and values['rvol_1m']>=1.5):
                        reasons.add('CONFIRMATION')
                    if bar['close']-level>.75*atr:
                        reasons.add('SPIKE')
            if not trend:
                reasons.add('TREND')
            entry = bar['close']+.25*atr
        if config.arm=='TECH_NEWS' and not positive:
            reasons.add('NO_POSITIVE_EVENT')
        key_body = {'listing_id':frame['listing_id'],'session_date':frame['session_date'],'bar_end_ns':bar_end,
                    'family':config.family,'holding_minutes':config.holding_minutes}
        inputs = {'frames':[f['fingerprint'] for f in frames],'common_hash':common['fingerprint'],'news_hash':news['fingerprint']}
    signal_key = canonical_hash(key_body)
    if signal_key in seen_keys:
        reasons.add('DUPLICATE_SIGNAL')
    return sealed({'version':'intraday-candidate-signal-v1','signal_key':signal_key,'config':config.to_dict(),
        'namespace':asdict(namespace),'listing_id':frame['listing_id'],'session_date':frame['session_date'],'decision_at_ns':at,
        'bar_end_ns':bar_end,'admitted':not reasons,'reasons':sorted(reasons),'entry_limit':entry,'atr_signal':atr,
        'structural_low':structural,'or_high':frame['or_high'] if config.family=='BREAKOUT_CONTINUATION' else None,
        'ema20_1m':values.get('ema20_1m') if config.family=='TREND_PULLBACK' else None,
        'event_id':event['event_id'] if event else None,'event_key':event_key,'cluster_key':cluster_key,'input_refs':inputs,'execution_created':False,
        'economic_status':'NOT_EVALUATED' if namespace.key[1:]==('sip','REAL','CAPTURED','STRICT_PIT') else 'NON_IDONEO'})


def invalidation(signal,*,at_ns,bid,ask,common_valid,postfill=False,closed_frame=None):
    _checked(signal)
    integer(at_ns)
    if (not signal['admitted'] or not _finite(signal['entry_limit']) or not _finite(signal['atr_signal']) or
        at_ns<signal['decision_at_ns'] or type(common_valid) is not bool or type(postfill) is not bool):
        raise ResearchError('INVALID_CONTRACT')
    if not common_valid:
        return 'FILTER_INVALIDATED'
    if not postfill and at_ns>=signal['decision_at_ns']+30_000_000_000:
        return 'ENTRY_TIMEOUT'
    if not postfill and (not _finite(ask) or ask>signal['entry_limit']):
        return 'ENTRY_LIMIT_EXCEEDED'
    family = signal['config']['family']
    level = signal['or_high']-.1*signal['atr_signal'] if family=='BREAKOUT_CONTINUATION' else (
        signal['structural_low']-.1*signal['atr_signal'] if signal['structural_low'] is not None else None)
    if not postfill and level is not None and _finite(bid) and bid<level:
        return 'STRUCTURAL_INVALIDATION'
    if postfill and closed_frame is not None:
        frame = _checked(closed_frame)
        bar = frame['bar']
        if (any(frame[k]!=signal[k] for k in ('namespace','listing_id','session_date')) or
            not signal['decision_at_ns']<=frame['cutoff_ns']<=at_ns or not bar or not bar['complete'] or
            bar['end_at_ns']>frame['cutoff_ns'] or bar['available_at_ns']>frame['cutoff_ns']):
            raise ResearchError('INVALID_CONTRACT')
        if bar:
            if family=='BREAKOUT_CONTINUATION' and bar['close']<level:
                return 'STRUCTURAL_INVALIDATION'
            if family=='TREND_PULLBACK' and (bar['close']<signal['structural_low'] or
                _finite(frame['values'].get('ema20_1m')) and bar['close']<frame['values']['ema20_1m']):
                return 'STRUCTURAL_INVALIDATION'
    return None
