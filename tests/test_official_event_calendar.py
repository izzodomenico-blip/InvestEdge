from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_intraday_events import read, setup
from test_intraday_identity import ns
from test_intraday_store import OPEN, SECOND


def artifact(*, day='2026-10-12', time='08:30', source='BLS', event_type='MACRO', listing=None,
             cancelled=False):
    doc = json.loads((Path(__file__).parent / 'fixtures/market_data/us_events_calendar.json').read_text())
    doc['source'] = source
    doc['source_url'] = {'BLS': 'https://www.bls.gov/schedule/2026/home.htm',
        'FED': 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
        'ISSUER_OFFICIAL': 'https://investor.example.com/earnings'}[source]
    row = doc['rows'][0]
    row.update(event_date=day, local_time=time, event_type=event_type, listing_id=listing, cancelled=cancelled)
    text = f"{day} {time or ''} {row['name']}" + (' CANCELLED' if cancelled else '')
    row['source_row_text'] = doc['original_text'] = text
    doc['original_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    doc['rows'] = [row]
    return doc


def api():
    return importlib.import_module('backend.app.data_providers.official_event_calendar')


def test_calendar_revisions_and_cancel_are_selected_before_economic_date_filter():
    s = setup()
    stamp = s.clock.now
    s.events.import_calendar(artifact(), received_at_ns=stamp)
    before = read(s)
    assert before[0]['provider'] == 'bls'
    assert before[0]['scheduled_at_ns'] == ns('2026-10-12T12:30:00Z')
    assert before[0]['available_at_ns'] == stamp
    assert not read(s, stamp-1)
    s.clock.now += SECOND
    s.events.import_calendar(artifact(day='2026-10-13'), received_at_ns=s.clock.now)
    assert not s.events.scheduled_risks('2026-10-12', cutoff_ns=s.clock.now)
    assert read(s, stamp) == before
    s.clock.now += SECOND
    s.calendar.record([{'date': '2026-10-13', 'open': '09:30', 'close': '16:00'}],
                      start='2026-10-13', end='2026-10-13', received_at_ns=s.clock.now)
    s.events.import_calendar(artifact(day='2026-10-13', cancelled=True), received_at_ns=s.clock.now)
    assert not s.events.scheduled_risks('2026-10-13', cutoff_ns=s.clock.now)
    assert read(s)[0]['payload']['cancelled'] is True
    assert len(read(s, revisions=True)) == 3


@pytest.mark.parametrize('day,expected', [('2026-03-06', '2026-03-06T13:30:00Z'),
    ('2026-03-11', '2026-03-11T12:30:00Z'), ('2026-10-30', '2026-10-30T12:30:00Z'),
    ('2026-11-02', '2026-11-02T13:30:00Z')])
def test_calendar_local_time_uses_dst(day, expected):
    payload = api().decode_calendar(artifact(day=day))[0]
    assert payload['scheduled_at_ns'] == ns(expected)


@pytest.mark.parametrize('day,time', [('2026-03-08', '02:30'), ('2026-11-01', '01:30')])
def test_dst_nonexistent_or_ambiguous_times_rejected(day, time):
    with pytest.raises(ValueError, match='EVENT_CALENDAR_INVALID'):
        api().decode_calendar(artifact(day=day, time=time))


def test_unknown_macro_time_blocks_whole_actual_session_and_holiday_is_empty():
    s = setup()
    s.events.import_calendar(artifact(time=None, source='FED'), received_at_ns=s.clock.now)
    row = read(s)[0]
    assert row['scheduled_at_ns'] is None and row['payload']['time_uncertainty'] == 'WHOLE_SESSION'
    risks = s.events.scheduled_risks('2026-10-12', cutoff_ns=s.clock.now)
    assert risks[0]['start_at_ns'] == OPEN and risks[0]['end_at_ns'] == ns('2026-10-12T20:00:00Z')
    assert risks[0]['consensus'] is None and risks[0]['surprise'] is None
    s.calendar.record([], start='2026-10-13', end='2026-10-13', received_at_ns=s.clock.now)
    s.events.import_calendar(artifact(day='2026-10-13', time=None), received_at_ns=s.clock.now)
    assert not s.events.scheduled_risks('2026-10-13', cutoff_ns=s.clock.now)


def test_calendar_raw_is_invisible_until_durable_and_import_is_deterministic():
    s = setup()
    doc = artifact()
    assert api().decode_calendar(doc) == api().decode_calendar(deepcopy(doc))
    stamp = s.clock.now
    ids = s.events.import_calendar(doc, received_at_ns=stamp, admit=False)
    assert not read(s)
    s.clock.now += SECOND
    s.events.admit(ids)
    assert not read(s, stamp) and read(s)[0]['available_at_ns'] == s.clock.now


@pytest.mark.parametrize('change', ['bad_hash', 'time_not_in_source', 'row_not_in_source', 'unofficial', 'query', 'fake_cancel'])
def test_original_calendar_evidence_must_agree_with_projection(change):
    doc = artifact()
    if change == 'bad_hash':
        doc['original_sha256'] = '0'*64
    elif change == 'time_not_in_source':
        doc['rows'][0]['local_time'] = '14:00'
    elif change == 'row_not_in_source':
        doc['rows'][0]['source_row_text'] = 'invented'
    elif change == 'unofficial':
        doc['source_url'] = 'https://news.example.org/calendar'
    elif change == 'query':
        doc['source_url'] += '?credential=bad'
    else:
        doc['rows'][0]['cancelled'] = True
    with pytest.raises(ValueError, match='EVENT_CALENDAR_INVALID'):
        api().decode_calendar(doc)


def test_issuer_requires_separate_attestation_and_no_conference_time_as_earnings():
    s = setup()
    doc = artifact(source='ISSUER_OFFICIAL', event_type='EARNINGS', listing=s.listing, time=None)
    with pytest.raises(ValueError, match='EVENT_CALENDAR_INVALID'):
        s.events.import_calendar(doc, received_at_ns=s.clock.now)
    policy = api().IssuerAuthority(listing_id=s.listing, hostname='investor.example.com', evidence_hash='e'*64)
    s.events.import_calendar(doc, received_at_ns=s.clock.now, issuer_authority=policy)
    row = read(s)[0]
    assert row['listing_id'] == s.listing and row['scheduled_at_ns'] is None
    assert row['payload']['issuer_authority']['evidence_hash'] == 'e'*64
    assert s.events.scheduled_risks('2026-10-12', cutoff_ns=s.clock.now)[0]['time_uncertainty'] == 'WHOLE_SESSION'


def test_partial_import_does_not_infer_cancellation_or_complete_coverage():
    s = setup()
    s.events.import_calendar(artifact(), received_at_ns=s.clock.now)
    doc = artifact(day='2026-10-13')
    doc['rows'][0]['event_id'] = 'jobs-2026-10'
    s.clock.now += SECOND
    s.events.import_calendar(doc, received_at_ns=s.clock.now)
    assert len(read(s)) == 2
    assert all(row['payload']['coverage'] == 'ANNOUNCED_EVENTS_ONLY' for row in read(s))


@pytest.mark.parametrize('suffix', [' PM', ' PT', ' PDT'])
def test_source_time_qualifier_cannot_be_silently_changed_to_eastern_morning(suffix):
    doc = artifact()
    doc['original_text'] = doc['rows'][0]['source_row_text'] = doc['original_text'].replace('08:30', '08:30'+suffix)
    doc['original_sha256'] = hashlib.sha256(doc['original_text'].encode()).hexdigest()
    with pytest.raises(ValueError, match='EVENT_CALENDAR_INVALID'):
        api().decode_calendar(doc)


def test_different_issuers_can_use_the_same_local_earnings_id():
    s = setup(second=True)
    for listing in (s.listing, s.second):
        doc = artifact(source='ISSUER_OFFICIAL', event_type='EARNINGS', listing=listing, time=None)
        policy = api().IssuerAuthority(listing_id=listing, hostname='investor.example.com', evidence_hash='e'*64)
        s.events.import_calendar(doc, received_at_ns=s.clock.now, issuer_authority=policy)
    assert {row['listing_id'] for row in read(s)} == {s.listing, s.second}
