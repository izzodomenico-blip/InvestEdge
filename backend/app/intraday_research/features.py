"""Frozen v1 feature definitions; numbers of complete bars, never wall-clock padding."""
from __future__ import annotations

import math
from statistics import median

from backend.app.intraday.aggregate import MINUTE_NS
from backend.app.intraday_research.context import sealed


def truncated_average(values, period, *, wilder=False):
    width = 5*period
    if len(values)<width:
        return None
    alpha = 1/period if wilder else 2/(period+1)
    weights = [(1-alpha)**i for i in range(width)]
    return math.fsum(v*w for v,w in zip(reversed(values[-width:]),weights,strict=True))/math.fsum(weights)


def _segment(bars):
    return [b for b in bars if b['segment']==bars[-1]['segment']] if bars else []


def _current_segment(context,bars,minutes):
    end = min(context.cutoff_ns,context.current['close_at_ns'])
    expected = context.current['open_at_ns']+((end-context.current['open_at_ns'])//(minutes*MINUTE_NS))*minutes*MINUTE_NS
    return _segment(bars) if bars and bars[-1]['end_at_ns']==expected else []


def _atr(bars):
    tr,previous = [],None
    for b in bars:
        tr.append(max(b['high']-b['low'],abs(b['high']-previous['close']),abs(b['low']-previous['close']))
            if previous and previous['session_date']==b['session_date'] else b['high']-b['low'])
        previous = b
    return truncated_average(tr,14,wilder=True)


def _rvol(context,bars):
    if not bars:
        return None
    last = bars[-1]
    events = context.corporate(context.listing_id)
    if last['session_date']!=context.session_date or any(e['effective_at_ns'] is None for e in events):
        return None
    reset = max((e['effective_at_ns'] for e in events if e['effective_at_ns']<=last['start_at_ns']),default=0)
    offset = last['start_at_ns']-last['session_open_ns']
    prior = [b['volume'] for b in bars if b['session_date']<last['session_date'] and b['session_open_ns']>=reset
             and b['start_at_ns']-b['session_open_ns']==offset]
    baseline = median(prior[-20:]) if len(prior)>=20 else None
    return last['volume']/baseline if baseline and baseline>0 else None


def _relative(context,listing):
    if listing is None:
        return None
    left = context.bars()
    if len(left)<16:
        return None
    left = left[-16:]
    right = {b['start_at_ns']:b for b in context.bars(listing_id=listing)}
    if (len({b['segment'] for b in left})!=1 or len({b['session_date'] for b in left})!=1
        or any(b['start_at_ns'] not in right for b in left)):
        return None
    matched = [right[b['start_at_ns']] for b in left]
    if len({b['segment'] for b in matched})!=1:
        return None
    return (left[-1]['close']/left[0]['close']-1)-(matched[-1]['close']/matched[0]['close']-1)


def compute_features(context):
    result = {'version':'intraday-features-v1','input_hash':context.input_hash,'cutoff_ns':context.cutoff_ns}
    all_bars = {m:context.bars(m) for m in (1,5,15)}
    for m in (1,5):
        bars = _current_segment(context,all_bars[m],m)
        closes = [b['close'] for b in bars]
        result.update({f'ema8_{m}m':truncated_average(closes,8),f'ema20_{m}m':truncated_average(closes,20),
                       f'atr14_{m}m':_atr(bars),f'rvol_{m}m':_rvol(context,all_bars[m]) if bars else None,
                       f'bar_end_{m}m':bars[-1]['end_at_ns'] if bars else None})
        result[f'atr14_{m}m_fraction'] = result[f'atr14_{m}m']/closes[-1] if closes and result[f'atr14_{m}m'] is not None else None
        if m==5:
            prior = truncated_average(closes[:-3],20)
            result['ema20_5m_slope3'] = result['ema20_5m']/prior-1 if prior and result['ema20_5m'] is not None else None
    bars = _current_segment(context,all_bars[1],1)
    result['roc5_1m'] = bars[-1]['close']/bars[-6]['close']-1 if len(bars)>=6 else None
    session = [b for b in all_bars[1] if b['session_date']==context.session_date]
    volume = math.fsum(b['volume'] for b in session)
    complete = bool(bars and session and session[0]['start_at_ns']==context.current['open_at_ns'] and
        len(session)==(session[-1]['end_at_ns']-context.current['open_at_ns'])//MINUTE_NS)
    result['vwap_session'] = math.fsum(b['vwap']*(b['volume']/volume) for b in session) if (complete and volume>0
        and all(b['vwap'] is not None and b['volume']>0 for b in session)) else None
    bars15 = _current_segment(context,all_bars[15],15)
    result['bar_end_15m'] = bars15[-1]['end_at_ns'] if bars15 else None
    result['context15m_close'] = bars15[-1]['close'] if bars15 else None
    result['ema8_15m'] = truncated_average([b['close'] for b in bars15],8)
    roc = bars15[-1]['close']/bars15[-3]['close']-1 if len(bars15)>=3 else None
    result['context15m_roc2_sign'] = (roc>0)-(roc<0) if roc is not None else None
    for name in ('market','sector'):
        result[f'rs_{name}15m'] = _relative(context,context.benchmarks.get(name)) if bars else None
    result['daily'] = context.daily()
    result['units'] = {key:('USD' if key.startswith(('ema8_','ema20_','atr14_','context15m_close','vwap_')) and
        key not in {'ema20_5m_slope3','atr14_1m_fraction','atr14_5m_fraction'} else
        'ratio' if key.startswith('rvol_') else 'ns' if key.startswith('bar_end_') else 'fraction')
        for key in result if key not in {'version','input_hash','cutoff_ns','daily'}}
    result['reason_code'] = None if all(result[k] is not None for k in ('ema20_1m','ema20_5m','ema8_15m','atr14_1m',
        'atr14_5m','rvol_1m','rvol_5m','rs_market15m','rs_sector15m','vwap_session')) and result['daily']['reason_code'] is None else 'WARMUP_INSUFFICIENT'
    return sealed(result)
