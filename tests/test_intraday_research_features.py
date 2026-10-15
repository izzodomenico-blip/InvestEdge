from __future__ import annotations

import importlib
import math

import pytest
from intraday_research_fixtures import research_history
from test_intraday_daily_context import MINUTE, context, rehash


def features(c):
    return importlib.import_module('backend.app.intraday_research.features').compute_features(c)


def test_constant_manual_features_and_units():
    f = features(context(research_history(minutes=120)))
    assert f['vwap_session']==100
    assert all(f[key]==pytest.approx(100) for key in ('ema8_1m','ema20_1m','ema8_5m','ema20_5m'))
    assert f['ema20_5m_slope3']==pytest.approx(0,abs=1e-14)
    assert f['atr14_1m']==f['atr14_5m']==pytest.approx(.2)
    assert f['atr14_1m_fraction']==pytest.approx(.002)
    assert f['roc5_1m']==f['rvol_1m']-1==f['rvol_5m']-1==0
    assert f['rs_market15m']==f['rs_sector15m']==0
    assert f['context15m_close']==pytest.approx(100) and f['ema8_15m']==pytest.approx(100)
    assert f['context15m_roc2_sign']==0
    assert f['units']['vwap_session']=='USD' and f['units']['roc5_1m']=='fraction'


def test_truncated_normalized_ema_manual_nonconstant():
    module = importlib.import_module('backend.app.intraday_research.features')
    values = list(range(1,101))
    weights = [(1-2/21)**i for i in range(100)]
    expected = math.fsum(v*w for v,w in zip(reversed(values),weights,strict=True))/math.fsum(weights)
    assert module.truncated_average(values,20)==expected
    assert module.truncated_average(values[:-1],20) is None
    assert module.truncated_average([99999,*values],20)==expected


def test_partial_5_and_15_minute_join_is_never_used():
    c = context(research_history(minutes=120),elapsed=47)
    f = features(c)
    assert f['bar_end_5m']==f['bar_end_15m']==c.current['open_at_ns']+45*MINUTE
    assert f['bar_end_1m']==c.current['open_at_ns']+47*MINUTE


def test_gap_resets_ema_but_scheduled_overnight_does_not():
    history = research_history(minutes=120)
    assert features(context(history))['ema20_1m'] is not None
    history[1].remove(next(r for r in history[1] if r['kind']=='BAR' and r['listing_id']==1 and r['event_time_ns']==history[3]+40*MINUTE))
    f = features(context(history))
    assert f['ema8_1m'] is None and f['ema20_1m'] is None and f['vwap_session'] is None


def test_overnight_true_range_uses_high_low_not_prior_close():
    history = research_history(minutes=120)
    for r in history[1]:
        if r['kind']=='BAR' and r['listing_id']==1 and r['event_time_ns']>=history[3]:
            r['payload']['raw'].update(o=200,h=200.1,l=199.9,c=200,vw=200)
            rehash(r)
    assert features(context(history))['atr14_1m']==pytest.approx(.2)


def test_rvol_missing_same_slot_uses_at_most_30_prior_sessions():
    history = research_history(days=21,minutes=120)
    history[1].remove(next(r for r in history[1] if r['kind']=='BAR' and r['listing_id']==1))
    assert features(context(history))['rvol_1m']==1  # another offset is unaffected
    c = context(history,elapsed=1)
    assert features(c)['rvol_1m'] is None


def test_benchmark_missing_interval_never_interpolates():
    history = research_history(minutes=120)
    history[1].remove(next(r for r in history[1] if r['kind']=='BAR' and r['listing_id']==2 and r['event_time_ns']==history[3]+40*MINUTE))
    f = features(context(history))
    assert f['rs_market15m'] is None and f['rs_sector15m']==0


def test_full_scalar_and_generator_inputs_are_identical():
    history = research_history(minutes=120)
    before = features(context(history))
    ns,rows,day,opening = history
    c = importlib.import_module('backend.app.intraday_research.context').ResearchContext(
        (r for r in rows),namespace=ns,listing_id=1,session_date=day,cutoff_ns=opening+50*MINUTE+1_000_000_000)
    assert features(c)==before


def test_known_status_interruption_resets_numeric_warmup():
    history = research_history(minutes=120)
    from test_intraday_replay import row
    stamp = history[3]+40*MINUTE
    history[1].append(row('STATUS',at=stamp,received=stamp,available=stamp,row_id=900001,
        data_mode='DEMO',provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY',
        payload={'state':'HALTED'},capture=f'fixture-{history[2]}'))
    assert features(context(history))['ema20_1m'] is None


def test_split_discards_old_scale_rvol_and_warmup():
    history = research_history(minutes=120)
    from test_intraday_replay import row
    stamp = history[3]
    history[1].append(row('EVENT',at=stamp,received=stamp,available=stamp,row_id=900001,
        data_mode='DEMO',provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY',
        payload={'discontinuity':True},effective_at_ns=stamp,logical_key='split'))
    f = features(context(history))
    assert f['ema20_1m'] is None and f['rvol_1m'] is None and f['rvol_5m'] is None


@pytest.mark.parametrize('mutation',['append','change','remove'])
def test_future_mutations_leave_all_features_bit_identical(mutation):
    history = research_history()
    before = features(context(history))
    cutoff = context(history).cutoff_ns
    future = [r for r in history[1] if r['available_at_ns']>cutoff]
    if mutation=='remove':
        history[1][:] = [r for r in history[1] if r['available_at_ns']<=cutoff]
    elif mutation=='change':
        for r in future:
            r['payload'] = {'future':'changed'}
            rehash(r)
    else:
        history[1].extend(future)
    assert features(context(history))==before


def test_nonconstant_vwap_roc_rvol_relative_strength_and_atr_by_hand():
    history = research_history(minutes=120)
    for r in history[1]:
        if r['kind']=='BAR' and r['listing_id']==1 and r['event_time_ns']>=history[3]:
            offset = (r['event_time_ns']-history[3])//MINUTE
            price = 100+offset/100
            r['payload']['raw'].update(o=price,h=price+.1,l=price-.1,c=price,vw=price,v=20000)
            rehash(r)
    f = features(context(history))
    assert f['vwap_session']==pytest.approx(100.245)
    assert f['roc5_1m']==100.49/100.44-1
    assert f['rvol_1m']==f['rvol_5m']==2
    assert f['rs_market15m']==f['rs_sector15m']==100.49/100.34-1
    assert f['atr14_1m']==pytest.approx(.2)
    assert f['atr14_5m']>f['atr14_1m']


def test_half_day_does_not_supply_afternoon_rvol_slot():
    history = research_history(minutes=390)
    prior = sorted({r['session_date'] for r in history[1] if r['table']=='intraday_calendar_versions'})[-2]
    cal = next(r for r in history[1] if r['table']=='intraday_calendar_versions' and r['session_date']==prior)
    cal['close_at_ns'] = cal['open_at_ns']+210*MINUTE
    f = features(context(history,elapsed=220))
    assert f['rvol_1m'] is None and f['rvol_5m'] is None
    assert context(history,elapsed=220).daily()['sessions'][-1]['volume']==2100000
