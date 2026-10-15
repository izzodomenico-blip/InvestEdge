from __future__ import annotations

import copy
import importlib

import pytest
from intraday_research_fixtures import research_history

MINUTE = 60_000_000_000


def context(history=None, *, elapsed=50, **options):
    ns,rows,day,opening = history or research_history()
    return importlib.import_module('backend.app.intraday_research.context').ResearchContext(
        rows,namespace=ns,listing_id=1,session_date=day,cutoff_ns=opening+elapsed*MINUTE+1_000_000_000,**options)


def rehash(row):
    from backend.app.intraday.contracts import canonical_json
    from backend.app.intraday_research.contracts import canonical_hash
    row['payload_hash'],row['payload_json'] = canonical_hash(row['payload']),canonical_json(row['payload'])


def test_daily_previous_complete_sessions_and_manual_values():
    c = context()
    daily = c.daily()
    assert len(daily['sessions'])==20
    assert daily['previous_close']==100 and daily['previous_high']==100.1 and daily['previous_low']==99.9
    assert daily['previous_range']==pytest.approx(.2)
    assert daily['median_dollar_volume20']==60_000_000
    assert daily['gap']==daily['return5']==0
    assert daily['sessions'][-1]['volume']==600000 and daily['sessions'][-1]['vwap']==100
    assert daily['reason_code'] is None
    assert all(r['session_date']!=c.session_date for r in daily['sessions'])


@pytest.mark.parametrize('days',[1,5,20])
def test_daily_warmup_has_no_progressive_current_day(days):
    assert context(research_history(days=days)).daily()['reason_code']=='WARMUP_INSUFFICIENT'


@pytest.mark.parametrize('mutation',['append','change','remove'])
def test_all_future_input_mutations_preserve_entire_context(mutation):
    history = research_history()
    before = context(history).daily()
    changed = copy.deepcopy(history)
    cutoff = context(history).cutoff_ns
    future = [r for r in changed[1] if r['available_at_ns']>cutoff]
    assert future
    if mutation=='remove':
        changed[1][:] = [r for r in changed[1] if r['available_at_ns']<=cutoff]
    elif mutation=='change':
        for r in future:
            r['payload'] = {'arbitrary':'future-only'}
            rehash(r)
    else:
        changed[1].append(copy.deepcopy(future[-1]))
    assert context(changed).daily()==before


def test_late_prior_revision_changes_today_only():
    history = research_history()
    before = context(history).daily()
    r = copy.deepcopy(next(r for r in reversed(history[1]) if r['kind']=='BAR' and r['event_time_ns']<history[3] and r['listing_id']==1))
    r.update(id=900001,received_at_ns=context(history).cutoff_ns+1,persisted_at_ns=context(history).cutoff_ns+1,
             available_at_ns=context(history).cutoff_ns+1,ingest_sequence=900001)
    r['payload']['raw'].update(c=100.05)
    rehash(r)
    history[1].append(r)
    assert context(history).daily()==before
    assert context(history,elapsed=51).daily()['previous_close']==100.05


def test_missing_prior_minute_and_split_reset_daily():
    history = research_history()
    history[1].remove(next(r for r in history[1] if r['kind']=='BAR' and r['listing_id']==1))
    assert context(history).daily()['reason_code']=='WARMUP_INSUFFICIENT'
    from test_intraday_replay import row
    split = row('EVENT',at=history[3],received=history[3],available=history[3],row_id=900001,
        data_mode='DEMO',provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY',effective_at_ns=history[3],
        payload={'discontinuity':True},listing_id=1,logical_key='split')
    history[1].append(split)
    assert context(history).daily()['sessions']==[]


def test_calendar_replacement_holiday_and_half_day_are_as_of():
    history = research_history()
    header = copy.deepcopy(history[1][-1])
    prior = sorted(header['payload']['session_ids'])[-2]
    del header['payload']['session_ids'][prior]
    header['payload']['member_count']-=1
    stamp = context(history).cutoff_ns+1
    header.update(id=900002,received_at_ns=stamp,persisted_at_ns=stamp,available_at_ns=stamp,ingest_sequence=900002)
    rehash(header)
    old = context(history).daily()
    history[1].append(header)
    assert context(history).daily()==old
    assert len(context(history,elapsed=51).daily()['sessions'])==19


def test_dst_uses_calendar_open_not_fixed_utc_offset():
    history = research_history()
    c = context(history)
    opens = [s['open_at_ns'] for s in c.sessions]
    assert any((b-a)//1_000_000_000==3*86400+3600 for a,b in zip(opens,opens[1:],strict=False))
    assert c.daily()['reason_code'] is None


def test_missing_calendar_member_never_bridges_unknown_session():
    history = research_history()
    history[1].remove(next(r for r in history[1] if r['table']=='intraday_calendar_versions'))
    with pytest.raises(ValueError,match='INPUT_MISSING'):
        context(history)


def test_invalid_previous_session_does_not_substitute_older_prior_levels():
    history = research_history(days=22)
    previous = max(r['event_time_ns'] for r in history[1] if r['kind']=='BAR' and r['event_time_ns']<history[3])
    history[1].remove(next(r for r in history[1] if r['kind']=='BAR' and r['listing_id']==1 and r['event_time_ns']==previous))
    daily = context(history).daily()
    assert daily['previous_close'] is None and daily['gap'] is None and daily['return5'] is None


def test_resource_cap_is_fail_closed():
    with pytest.raises(ValueError,match='RESOURCE_LIMIT'):
        context(research_history(days=1),max_bytes=100)


def test_bundle_context_is_read_only_and_preserves_original_digest():
    from test_intraday_research_datasets import _small_bundle
    s,service,bundle = _small_bundle()
    changes = s.db.total_changes
    row = next(r for r in bundle.timeline if r['table']=='intraday_calendar_versions')
    c = service.research_context(bundle.bundle_id,listing_id=s.listing,session_date=row['session_date'],
        cutoff_ns=bundle.manifest['cutoff_ns'])
    assert c.daily()['reason_code']=='WARMUP_INSUFFICIENT'
    assert c.benchmarks=={}  # a post-session freeze cannot attest pre-open selection
    assert s.db.total_changes==changes
    assert service.open_bundle(bundle.bundle_id).digest==bundle.digest
    with pytest.raises(ValueError,match='INPUT_MISSING'):
        service.research_context(bundle.bundle_id,listing_id=s.listing,session_date=row['session_date'],
            cutoff_ns=bundle.manifest['cutoff_ns'],benchmark_bundle_id=bundle.bundle_id)


@pytest.mark.parametrize('field,value',[('currency','EUR'),('adjustment','all')])
def test_bar_units_cannot_masquerade_as_raw_usd(field,value):
    history = research_history(days=1)
    row = next(r for r in history[1] if r['kind']=='BAR')
    row['payload'][field] = value
    rehash(row)
    with pytest.raises(ValueError,match='INVALID_CONTRACT'):
        context(history)


def test_overnight_bridge_requires_complete_calendar_range_between_sessions():
    history = research_history(days=6)
    header = history[1].pop()
    days = sorted(header['payload']['session_ids'])
    for ordinal,subset in enumerate((days[:5],days[5:])):
        replacement = copy.deepcopy(header)
        replacement['id'] = 920000+ordinal
        replacement['payload'].update(start=subset[0],end=subset[-1],
            session_ids={d:header['payload']['session_ids'][d] for d in subset},member_count=len(subset))
        rehash(replacement)
        history[1].append(replacement)
    with pytest.raises(ValueError,match='INPUT_MISSING'):
        context(history)


def test_late_historical_halt_invalidates_today_prior_context_only():
    from test_intraday_replay import row
    history = research_history(days=22)
    before = context(history).daily()
    previous = sorted((r for r in history[1] if r['table']=='intraday_calendar_versions'),key=lambda r:r['open_at_ns'])[-2]
    stamp = context(history).cutoff_ns+1
    history[1].append(row('STATUS',at=previous['open_at_ns']+40*MINUTE,received=stamp,available=stamp,row_id=930001,
        data_mode='DEMO',provenance='SYNTHETIC',replay_grade='RESEARCH_ONLY',
        capture=f"fixture-{previous['session_date']}",payload={'state':'HALTED'}))
    assert context(history).daily()==before
    assert context(history,elapsed=51).daily()['previous_close'] is None
