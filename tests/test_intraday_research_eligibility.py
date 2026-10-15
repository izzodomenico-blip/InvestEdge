from __future__ import annotations

import copy
import importlib

import pytest
from intraday_research_fixtures import quote_terms_fixture, research_history
from test_intraday_daily_context import MINUTE, context, rehash


@pytest.fixture(autouse=True)
def database(research_connection):
    from intraday_research_fixtures import seed_research_inputs
    global CONNECTION
    CONNECTION = research_connection
    seed_research_inputs(CONNECTION)


def evaluate(c, **options):
    from backend.app.intraday_research.quote_units import QuoteUnits
    db = CONNECTION
    registry,refs,_,_ = quote_terms_fixture(db,namespace=c.namespace,available=c.cutoff_ns-1,
        known=c.current['open_at_ns']-30,received=c.current['open_at_ns']-20,valid_from=c.current['open_at_ns']-100)
    return importlib.import_module('backend.app.intraday_research.eligibility').evaluate_entry(
        c,quote_units=QuoteUnits(registry,c.namespace),references=refs,holding_minutes=15,**options)


def test_covered_zero_and_synthetic_never_promote_economic_gate():
    c = context(research_history(minutes=120),elapsed=50)
    result = evaluate(c)
    assert result['economic_status']=='NON_IDONEO'
    assert result['event_calendar_basis']=='ANNOUNCED_EVENTS_ONLY'
    assert result['operational_basis']=='DURABLE_EVIDENCE_ONLY'
    assert 'QUOTE_INVALID' in result['reasons']  # previous session's quote is stale


@pytest.mark.parametrize('elapsed,reason',[(44,'BEFORE_ENTRY_WINDOW'),(102,'AFTER_ENTRY_WINDOW')])
def test_entry_time_uses_actual_known_close(elapsed,reason):
    assert reason in evaluate(context(research_history(minutes=120),elapsed=elapsed))['reasons']


def test_future_gap_does_not_change_past_filter():
    history = research_history(minutes=120)
    before = evaluate(context(history))
    from test_intraday_replay import row
    stamp = context(history).cutoff_ns+1
    history[1].append(row('CONTROL',at=stamp,received=stamp,available=stamp,row_id=900001,kind='GAP',
        data_mode='DEMO',provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY',payload={},capture=f'fixture-{history[2]}'))
    assert evaluate(context(history))==before
    assert 'STATUS_OR_CAPTURE_UNKNOWN' in evaluate(context(history,elapsed=51))['reasons']


def test_known_unknown_time_event_blocks_session():
    history = research_history(minutes=120)
    event = next(r for r in history[1] if r['event_type']=='EARNINGS' and r['table']=='intraday_event_versions')
    event['scheduled_at_ns'] = None
    event['payload']['event_date'] = history[2]
    rehash(event)
    assert 'EVENT_WINDOW' in evaluate(context(history))['reasons']


def test_news_disabled_or_unknown_cannot_pass_even_tech_only():
    history = research_history(minutes=120)
    history[1][:] = [r for r in history[1] if r['payload'].get('channel')!='news' or r['kind']=='ACK']
    assert 'NEWS_COVERAGE_UNKNOWN' in evaluate(context(history))['reasons']


def test_future_benchmark_selection_cannot_replace_preopen_choice():
    history = research_history(minutes=120)
    universe = copy.deepcopy(next(r for r in reversed(history[1]) if r['table']=='intraday_universe_snapshots'))
    universe.update(id=900001,received_at_ns=history[3]+MINUTE,persisted_at_ns=history[3]+MINUTE,
                    available_at_ns=history[3]+MINUTE,ingest_sequence=900001)
    universe['payload']['benchmarks'] = {'market':3,'sector':2}
    rehash(universe)
    history[1].append(universe)
    assert context(history).benchmarks=={'market':2,'sector':3}


def fresh_quote(history, *, elapsed=50):
    quote = copy.deepcopy(next(r for r in reversed(history[1]) if r['kind']=='QUOTE'))
    stamp = history[3]+elapsed*MINUTE+1_000_000_000
    quote.update(id=900005,event_time_ns=stamp-1_000_000_000,received_at_ns=stamp,persisted_at_ns=stamp,
                 available_at_ns=stamp,ingest_sequence=900005)
    history[1].append(quote)
    return quote


def test_positive_common_filters_with_fresh_attested_quote_are_research_only():
    history = research_history(minutes=120)
    fresh_quote(history)
    result = evaluate(context(history))
    assert result['technical_eligible'], result['reasons']
    assert result['economic_status']=='NON_IDONEO'
    assert result['quote_conversion']['bid_shares']==200
    assert result['news_coverage']=='COVERED_ZERO'
    assert result['g1_data']=='NOT_EVALUATED' and result['portfolio_evaluated'] is False


@pytest.mark.parametrize('kind',['stale','spread','zero_size','unknown_status','event'])
def test_each_common_filter_rejects_an_otherwise_valid_entry(kind):
    history = research_history(minutes=120)
    quote = fresh_quote(history)
    expected,options = {'stale':'QUOTE_INVALID','spread':'SPREAD_FILTER','zero_size':'SIZE_UNIT_UNKNOWN',
        'unknown_status':'STATUS_OR_CAPTURE_UNKNOWN','event':'EVENT_WINDOW'}[kind],{}
    if kind=='stale':
        quote['event_time_ns']-=2_000_000_001
    elif kind=='spread':
        quote['payload']['raw']['ap']=101
        rehash(quote)
    elif kind=='zero_size':
        quote['payload']['raw']['bs']=0
        rehash(quote)
    elif kind=='unknown_status':
        for r in history[1]:
            if r['payload'].get('version')=='utp-status-checkpoint-v1' and r['capture_id']==f'fixture-{history[2]}':
                r['payload']['state']='UNKNOWN'
                rehash(r)
    elif kind=='event':
        r = next(r for r in history[1] if r['table']=='intraday_event_versions' and r['event_type']=='EARNINGS')
        r['scheduled_at_ns']=history[3]+60*MINUTE
        rehash(r)
    assert expected in evaluate(context(history),**options)['reasons']


def test_frozen_timeout_is_30_seconds():
    assert evaluate(context(research_history(minutes=120)))['entry_timeout_ns']==30_000_000_000


@pytest.mark.parametrize('options',[{'entry_timeout_ns':1},{'latency_ns':0}])
def test_frozen_execution_parameters_cannot_be_relaxed(options):
    with pytest.raises(ValueError,match='INVALID_CONTRACT'):
        evaluate(context(research_history(minutes=120)),**options)


def test_every_future_metadata_family_is_inert_at_the_old_decision():
    history = research_history(minutes=120)
    fresh_quote(history)
    before = evaluate(context(history))
    future = []
    seen = set()
    stamp = context(history).cutoff_ns+1
    for value in history[1]:
        family = value['table'],value['kind']
        if family in seen:
            continue
        seen.add(family)
        changed = copy.deepcopy(value)
        changed.update(id=910000+len(seen),available_at_ns=stamp,received_at_ns=stamp,persisted_at_ns=stamp)
        changed['payload'] = {'future_only':'arbitrary change'}
        rehash(changed)
        future.append(changed)
    history[1].extend(future)
    assert evaluate(context(history))==before


def test_event_outside_holding_buffer_does_not_add_an_extra_fifteen_minutes():
    history = research_history(minutes=120)
    fresh_quote(history)
    event = next(r for r in history[1] if r['table']=='intraday_event_versions' and r['event_type']=='EARNINGS')
    event['scheduled_at_ns'] = history[3]+80*MINUTE
    assert 'EVENT_WINDOW' not in evaluate(context(history))['reasons']
