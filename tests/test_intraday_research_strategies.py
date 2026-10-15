from __future__ import annotations

import copy
import importlib

import pytest
from intraday_research_fixtures import setup_common, setup_frames

from backend.app.intraday_research.contracts import CandidateConfig, canonical_hash, trial_grid


def news_view(frame, *, positive=False):
    body = {'version':'intraday-news-context-v1','namespace':frame['namespace'],'listing_id':1,'cutoff_ns':frame['cutoff_ns'],
        'positive':[{'event_id':'FACT_1','issuer_id':'ISSUER_FIXTURE','cluster_id':'cluster:1','kind':'GUIDANCE','available_at_ns':frame['cutoff_ns'],
            'first_available_at_ns':frame['cutoff_ns'],'decay':1,'novel':True}] if positive else [],
        'negative':[],'unknown':[],'coverage':'COVERED' if positive else 'COVERED_ZERO','g2':'NOT_EVALUATED'}
    return body | {'fingerprint':canonical_hash(body)}


def candidate(*,family='TREND_PULLBACK',arm='TECH_ONLY',frames=None,common=None,news=None,**options):
    frames = frames or setup_frames(family=family)
    return importlib.import_module('backend.app.intraday_research.strategies').evaluate_candidate(
        CandidateConfig(family,15,arm,'R0'),frames=frames,common=common or setup_common(frames[-1]),
        news=news or news_view(frames[-1]),**options)


@pytest.mark.parametrize('family',['TREND_PULLBACK','BREAKOUT_CONTINUATION'])
def test_positive_setup_levels_are_manual_and_no_execution(family):
    result = candidate(family=family)
    assert result['admitted'],result['reasons']
    assert result['entry_limit']==100.75 and result['atr_signal']==1
    assert result['structural_low']==99.9
    assert result['economic_status']=='NON_IDONEO' and result['execution_created'] is False


@pytest.mark.parametrize('change,reason',[('opened','BAR_NOT_CLOSED'),('spike','SPIKE'),('rvol','CONFIRMATION'),
    ('trend','TREND'),('pullback','PULLBACK'),('warmup','WARMUP_INSUFFICIENT')])
def test_setup_boundaries_fail_closed(change,reason):
    frames = copy.deepcopy(setup_frames())
    last = frames[-1]
    if change=='opened':
        last['bar']['end_at_ns']=last['cutoff_ns']+1
    elif change=='spike':
        last['bar'].update(close=102,high=102.1)
    elif change=='rvol':
        last['values']['rvol_1m']=1.1999
    elif change=='trend':
        last['values']['ema8_5m']=last['values']['ema20_5m']
    elif change=='pullback':
        for f in frames[-4:-1]:
            f['bar']['low']=100.15
    else:
        last['values']['ema20_5m']=None
    for f in frames:
        f['fingerprint']=canonical_hash({k:v for k,v in f.items() if k!='fingerprint'})
    assert reason in candidate(frames=frames)['reasons']


def test_opening_range_requires_all_first_three_closed_five_minute_bars():
    frames = copy.deepcopy(setup_frames(family='BREAKOUT_CONTINUATION'))
    frames[-1]['or_complete']=False
    frames[-1]['fingerprint']=canonical_hash({k:v for k,v in frames[-1].items() if k!='fingerprint'})
    assert 'OPENING_RANGE_INCOMPLETE' in candidate(family='BREAKOUT_CONTINUATION',frames=frames)['reasons']


def test_tech_news_uses_same_paired_key_and_no_retroactive_positive():
    frames = setup_frames()
    technical = candidate(frames=frames)
    combined = candidate(frames=frames,arm='TECH_NEWS',news=news_view(frames[-1],positive=True))
    assert technical['signal_key']==combined['signal_key'] and combined['admitted']
    late = news_view(frames[-1],positive=True)
    late['positive'][0]['available_at_ns']+=1
    late['fingerprint']=canonical_hash({k:v for k,v in late.items() if k!='fingerprint'})
    assert not candidate(frames=frames,arm='TECH_NEWS',news=late)['admitted']


def test_same_signal_key_is_not_emitted_twice():
    first = candidate()
    assert 'DUPLICATE_SIGNAL' in candidate(seen_keys=(first['signal_key'],))['reasons']


def test_news_only_does_not_wait_for_or_use_technical_confirmation():
    frames = copy.deepcopy(setup_frames())
    view = news_view(frames[-1],positive=True)
    first = candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,news=view,ask=100)
    for f in frames:
        for key in f['values']:
            if key!='atr14_1m':
                f['values'][key]=None
        f['fingerprint']=canonical_hash({k:v for k,v in f.items() if k!='fingerprint'})
    second = candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,news=view,ask=100)
    assert first==second and first['admitted'] and first['entry_limit']==100.25


def test_news_only_without_known_ask_is_nonfill_and_does_not_await_a_technical_bar():
    frames = setup_frames()
    result = candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,news=news_view(frames[-1],positive=True))
    assert not result['admitted'] and 'QUOTE_MISSING' in result['reasons']


def test_grid_has_twenty_configs_ten_policies_and_shared_news_only():
    grid = trial_grid()
    assert len(grid)==20 and len({c.policy_key for c in grid})==10
    assert len([c for c in grid if c.family=='NEWS_ONLY'])==4


def test_prefill_and_postfill_invalidation_use_frozen_levels():
    module = importlib.import_module('backend.app.intraday_research.strategies')
    signal = candidate()
    assert module.invalidation(signal,at_ns=signal['decision_at_ns']+1,bid=99.7,ask=100,common_valid=True)=='STRUCTURAL_INVALIDATION'
    assert module.invalidation(signal,at_ns=signal['decision_at_ns']+30_000_000_000,bid=100,ask=100,common_valid=True)=='ENTRY_TIMEOUT'


def test_actual_feature_frame_uses_canonical_numeric_bar_and_provenance():
    from intraday_research_fixtures import research_history
    from test_intraday_daily_context import context
    c = context(research_history(days=1))
    frame = importlib.import_module('backend.app.intraday_research.strategies').feature_frame(c)
    assert frame['listing_id']==c.listing_id and frame['bar']['member_ids']
    assert frame['fingerprint']==canonical_hash({k:v for k,v in frame.items() if k!='fingerprint'})


def test_missing_current_bar_is_blocked_without_exception():
    frames = copy.deepcopy(setup_frames())
    frames[-1]['bar']=None
    frames[-1]['fingerprint']=canonical_hash({k:v for k,v in frames[-1].items() if k!='fingerprint'})
    assert not candidate(frames=frames)['admitted']


def test_news_only_at_event_between_bar_closes_preserves_ten_second_delivery_limit():
    frames = copy.deepcopy(setup_frames())
    for frame in frames:
        frame['bar']['end_at_ns']-=30_000_000_000
        frame['bar']['available_at_ns']=frame['bar']['end_at_ns']+1
        frame['fingerprint']=canonical_hash({k:v for k,v in frame.items() if k!='fingerprint'})
    common = setup_common(frames[-1],reasons=('BAR_DELAY',))
    assert candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,common=common,news=news_view(frames[-1],positive=True),ask=100)['admitted']
    frames[-1]['bar']['available_at_ns']=frames[-1]['bar']['end_at_ns']+10_000_000_001
    frames[-1]['fingerprint']=canonical_hash({k:v for k,v in frames[-1].items() if k!='fingerprint'})
    assert not candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,common=common,news=news_view(frames[-1],positive=True),ask=100)['admitted']


def reseal(body):
    body['fingerprint']=canonical_hash({k:v for k,v in body.items() if k!='fingerprint'})
    return body


@pytest.mark.parametrize('scope',['listing_id','namespace','session_date','future'])
def test_postfill_cannot_use_a_foreign_or_future_bar(scope):
    from backend.app.intraday_research.strategies import invalidation
    signal = candidate()
    frame = copy.deepcopy(setup_frames()[-1])
    frame['bar'].update(close=90,low=89)
    if scope=='listing_id':
        frame['listing_id']=2
    elif scope=='namespace':
        frame['namespace']['profile_id']='foreign'
    elif scope=='session_date':
        frame['session_date']='2023-11-15'
    else:
        frame['bar']['available_at_ns']=frame['cutoff_ns']+2
    with pytest.raises(ValueError,match='INVALID_CONTRACT'):
        invalidation(signal,at_ns=signal['decision_at_ns']+1,bid=100,ask=100,common_valid=True,
                     postfill=True,closed_frame=reseal(frame))


def test_postfill_uses_current_closed_ema_and_frozen_structural_level():
    from backend.app.intraday_research.strategies import invalidation
    for family in ('TREND_PULLBACK','BREAKOUT_CONTINUATION'):
        signal = candidate(family=family)
        frame = copy.deepcopy(setup_frames(family=family)[-1])
        frame['bar']['close']=100
        if family=='TREND_PULLBACK':
            frame['values']['ema20_1m']=100.1
        assert invalidation(signal,at_ns=signal['decision_at_ns']+1,bid=100,ask=100,common_valid=True,
                            postfill=True,closed_frame=reseal(frame))=='STRUCTURAL_INVALIDATION'


def test_blocked_setup_cannot_be_used_for_entry_invalidation():
    from backend.app.intraday_research.strategies import invalidation
    frames = copy.deepcopy(setup_frames())
    frames[-1]['bar']=None
    signal = candidate(frames=tuple(reseal(f) for f in frames))
    with pytest.raises(ValueError,match='INVALID_CONTRACT'):
        invalidation(signal,at_ns=signal['decision_at_ns'],bid=100,ask=100,common_valid=True)


def test_news_only_deduplicates_known_cluster_and_exposes_scoped_keys():
    frames = setup_frames()
    first = candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,news=news_view(frames[-1],positive=True),ask=100)
    view = news_view(frames[-1],positive=True)
    view['positive'][0]['event_id']='FACT_2'
    view=reseal(view)
    assert not candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,news=view,ask=100,
                         seen_events=(first['cluster_key'],))['admitted']
    assert first['event_key']!=first['cluster_key']


def test_common_reasons_and_eligibility_flag_must_agree():
    common = setup_common(setup_frames()[-1])
    common['technical_eligible']=False
    with pytest.raises(ValueError,match='INVALID_CONTRACT'):
        candidate(common=reseal(common))


@pytest.mark.parametrize('coverage',['MISSING','STALE','DISABLED','UNKNOWN'])
def test_news_coverage_is_distinct_from_covered_zero(coverage):
    view = news_view(setup_frames()[-1])
    view['coverage']=coverage
    assert 'NEWS_COVERAGE_UNKNOWN' in candidate(news=reseal(view))['reasons']


def test_holding_is_independent_of_bar_timeframe_and_risk_pair_key():
    from backend.app.intraday_research.strategies import evaluate_candidate
    frames = setup_frames()
    first = candidate(frames=frames)
    risk = evaluate_candidate(CandidateConfig('TREND_PULLBACK',15,'TECH_ONLY','R1'),frames=frames,
        common=setup_common(frames[-1]),news=news_view(frames[-1]))
    long = evaluate_candidate(CandidateConfig('TREND_PULLBACK',30,'TECH_ONLY','R0'),frames=frames,
        common=setup_common(frames[-1],holding=30),news=news_view(frames[-1]))
    assert risk['signal_key']==first['signal_key'] and long['signal_key']!=first['signal_key']
    assert long['bar_end_ns']==first['bar_end_ns'] and long['admitted']


@pytest.mark.parametrize('name',['strategies','news_features'])
def test_new_setup_modules_have_no_provider_legacy_execution_or_clock_import(name):
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1]/'backend/app/intraday_research'/f'{name}.py').read_text())
    forbidden = {'data_providers','features_daily','feature_store','score','technical_analysis','ml','socket','sqlite3',
                 'time','os','lab_simulator','backtest','orders','execution'}
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
        assert all(not forbidden.intersection(n.split('.')) for n in names)


def test_future_cluster_revision_preserves_prior_trial_and_blocks_new_duplicate():
    frames = setup_frames()
    first = candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,news=news_view(frames[-1],positive=True),ask=100)
    view = news_view(frames[-1],positive=True)
    old = view['positive'][0]
    old['cluster_id']='cluster:revised'
    old['available_at_ns']-=1
    view['positive'].append(dict(old,event_id='FACT_2',available_at_ns=frames[-1]['cutoff_ns']))
    later = candidate(family='NEWS_ONLY',arm='NEWS_ONLY',frames=frames,news=reseal(view),ask=100,
        seen_events=(first['event_key'],first['cluster_key']))
    assert first['admitted'] and not later['admitted'] and 'NO_NEW_EVENT' in later['reasons']


def test_late_closed_bar_revision_can_only_invalidate_at_new_decision_time():
    from backend.app.intraday_research.strategies import invalidation
    signal = candidate()
    frame = copy.deepcopy(setup_frames()[-1])
    frame['cutoff_ns']+=5
    frame['bar'].update(close=90,low=89,available_at_ns=frame['cutoff_ns'])
    frame=reseal(frame)
    with pytest.raises(ValueError,match='INVALID_CONTRACT'):
        invalidation(signal,at_ns=signal['decision_at_ns']+1,bid=100,ask=100,common_valid=True,postfill=True,closed_frame=frame)
    assert invalidation(signal,at_ns=frame['cutoff_ns'],bid=100,ask=100,common_valid=True,
                        postfill=True,closed_frame=frame)=='STRUCTURAL_INVALIDATION'


@pytest.mark.parametrize('feed',['iex','delayed_sip'])
def test_non_sip_capture_is_economically_non_idoneo(feed):
    from intraday_research_fixtures import PROFILE

    from backend.app.intraday_research.contracts import ResearchNamespace
    frames = setup_frames(namespace=ResearchNamespace(PROFILE,feed,'REAL','CAPTURED','STRICT_PIT'))
    assert candidate(frames=frames)['economic_status']=='NON_IDONEO'
