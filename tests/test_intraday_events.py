from __future__ import annotations

import base64
import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_intraday_store import SECOND, event, prepared

from backend.app.intraday.contracts import EventEnvelope, canonical_json


def api():
    return importlib.import_module('backend.app.data_providers.alpaca_events')


def setup(*, history=False, **kwargs):
    s = prepared(history=history, **kwargs)
    s.events = importlib.import_module('backend.app.intraday.events').EventStore(
        s.archive.provider, clock_ns=lambda: s.clock.now,
        data_mode=s.store.data_mode, provenance=s.store.provenance, replay_grade=s.store.replay_grade)
    return s


def corporate(**changes):
    page = json.loads((Path(__file__).parent / 'fixtures/market_data/alpaca_corporate_actions.json').read_text())
    page['corporate_actions']['forward_splits'][0].update(changes)
    return page


def import_actions(s, **changes):
    return s.events.import_corporate(corporate(**changes), received_at_ns=s.clock.now)


def read(s, cutoff=None, **kwargs):
    return s.events.read_as_of(cutoff_ns=s.clock.now if cutoff is None else cutoff, **kwargs)


def test_corporate_rest_never_certifies_historical_pit():
    s = setup()
    with pytest.raises(ValueError, match='MODE_MISMATCH'):
        import_actions(s)
    assert not read(s)


def test_corporate_effective_is_not_knowledge_and_late_revision_preserves_prefix():
    s = setup(history=True)
    stamp = s.clock.now
    ids = import_actions(s)
    before = read(s)
    assert not read(s, stamp - 1)
    assert before[0]['available_at_ns'] == stamp
    assert before[0]['effective_at_ns'] < stamp
    assert before[0]['source_revision_id'] is None
    assert before[0]['listing_id'] is None  # no historical mapping inferred from current assets
    assert before[0]['payload']['reason_code'] == 'IDENTITY_UNVERIFIED'
    s.clock.now += SECOND
    later = import_actions(s, new_rate=3)
    assert later != ids and read(s)[0]['supersedes_id'] == ids[0]
    assert read(s, stamp) == before
    s.clock.now += SECOND
    again = import_actions(s)
    assert again != ids and read(s)[0]['supersedes_id'] == later[0]
    assert len(read(s, revisions=True)) == 3


def test_corporate_resolves_only_frozen_identity_at_economic_date():
    s = setup(history=True)
    import_actions(s, ex_date='2026-10-13')
    assert read(s)[0]['listing_id'] == s.listing
    assert read(s)[0]['payload']['identity']['publication_id']


def test_event_raw_invisible_without_post_commit_receipt(monkeypatch):
    s = setup(history=True)
    stamp = s.clock.now
    ids = s.events.import_corporate(corporate(), received_at_ns=stamp, admit=False)
    assert not s.db.in_transaction and not read(s)
    s.clock.now += SECOND
    s.events.admit(ids)
    assert not read(s, stamp)
    row = read(s)[0]
    assert row['available_at_ns'] == s.clock.now
    doc = s.db.execute("SELECT * FROM intraday_capture_events WHERE kind='BOOTSTRAP'").fetchall()[-1]
    assert doc['available_at_ns'] is None and doc['payload_hash'] == row['payload']['document']['hash']


@pytest.mark.parametrize('change', [{'id': 'bad'}, {'ex_date': 'bad'}, {'new_rate': float('nan')},
                                   {'symbol': 'AAPL?secret'}, {'new_rate': -1}])
def test_corporate_malformed_pages_fail_atomically(change):
    s = setup(history=True)
    with pytest.raises(ValueError):
        import_actions(s, **change)
    assert not read(s)
    assert not s.db.execute('SELECT 1 FROM intraday_event_versions').fetchone()


def test_corporate_page_missing_terminal_token_is_rejected_before_cache():
    s = setup(history=True)
    page = corporate()
    page.pop('next_page_token')
    s.queue.append(page)
    adapter = api().AlpacaEventsProvider(s.archive.provider)
    with pytest.raises(ValueError, match='EVENT_PAGE_INVALID'):
        adapter.get_page(start='2026-10-10', end='2026-10-12')


def status(s, code='H', *, kind='STATUS', tape='C', at=None, capture_id='capture-status'):
    at = s.clock.now if at is None else at
    market = importlib.import_module('backend.app.data_providers.alpaca_market')
    raw = {'T': 's', 'S': 'AAPL', 'sc': code, 'sm': 'status', 'rc': 'T1', 'rm': 'reason',
           't': market.format_ns(at), 'z': tape}
    if kind == 'LULD':
        raw = {'T': 'l', 'S': 'AAPL', 'u': 110, 'd': 90, 'i': 'B', 't': market.format_ns(at), 'z': tape}
    payload = api().decode_status_row(kind, raw, source='STREAM')
    return EventEnvelope('alpaca', s.profile.feed, s.profile.profile_id, 'REAL', 'CAPTURED', 'STRICT_PIT',
                         kind, s.listing, f'{kind}:{s.listing}:{at}', capture_id, 1, at, s.clock.now,
                         s.clock.now, None, canonical_json(payload))


def entitled(**kwargs):
    return setup(profile_overrides={'attested_capabilities': ('bars', 'quotes', 'news', 'assets', 'calendar',
                        'corporate_actions', 'status', 'luld')}, **kwargs)


@pytest.mark.parametrize('tape,code,state', [('C', 'H', 'HALTED'), ('C', 'P', 'HALTED'),
    ('C', 'Q', 'QUOTATION_ONLY'), ('C', 'T', 'NORMAL'), ('A', '2', 'HALTED'), ('B', '3', 'NORMAL'),
    ('C', '?', 'UNKNOWN'), ('A', 'T', 'UNKNOWN')])
def test_status_decoder_preserves_distinct_trading_codes(tape, code, state):
    s = entitled()
    s.store.persist((status(s, code, tape=tape),))
    row = s.store.read_as_of('STATUS', cutoff_ns=s.clock.now)[0]
    assert row['payload']['state'] == state
    assert row['payload']['raw']['sc'] == code


def test_status_requires_entitlement_and_identity_and_luld_is_not_resume():
    s = setup()
    s.store.persist((status(s, 'T'),))
    row = s.store.read_as_of('STATUS', cutoff_ns=s.clock.now)[0]
    assert row['quality'] == 'QUARANTINED' and row['reason_code'] == 'FEED_NOT_ENTITLED'
    s = entitled()
    s.store.persist((status(s, kind='LULD'),))
    assert s.store.read_as_of('LULD', cutoff_ns=s.clock.now)[0]['payload']['state'] == 'UNKNOWN'
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['reason_code'] == 'STATUS_BOOTSTRAP_UNAVAILABLE'


def frame(kind, payload=b''):
    return (len(payload) + 1).to_bytes(2, 'big') + kind.encode() + payload


def wire(category, kind, body, now, origin=b'Q'):
    return b'1' + category.encode() + kind.encode() + origin + b' ' + now.to_bytes(8, 'big') * 2 + bytes(8) + body


def checkpoint(s, *, action=None, auth=b'P', truncate=False):
    request = s.clock.now - SECOND
    header = frame('A', b'session-01' + b'                   1')
    symbol = b'AAPL       '
    directory = symbol + bytes(11) + b'Apple'.ljust(30) + b'CS Q' + auth + b'N' + (100).to_bytes(2, 'big') + b'N'
    assert len(directory) == 61
    channels = []
    for channel in range(1, 7):
        raw = header
        if channel == 1:
            raw += frame('S', wire('A', 'B', directory, request))
            if action:
                body = symbol + action.encode() + (1).to_bytes(4, 'big') + (request - 86400*SECOND).to_bytes(8, 'big') + b'T1    '
                raw += frame('S', wire('A', 'H', body, request))
        if not truncate:
            raw += frame('S', wire('A', 'S', (700 + channel).to_bytes(8, 'big'), request, b'E'))
        channels.append({'channel': channel, 'binding_id': f'sip-channel-{channel}',
                         'request_sent_at_ns': request, 'received_at_ns': s.clock.now,
                         'original_b64': base64.b64encode(raw).decode(), 'original_sha256': hashlib.sha256(raw).hexdigest()})
    return {'version': 'utp-snapshot-import-v1', 'expires_at_ns': s.clock.now + 30*SECOND, 'channels': channels}


def authority(document):
    return api().StatusAuthority(source='UTP_SNAPSHOT', contract_version='4.0',
            contract_sha256='c'*64, evidence_hash='d'*64, retention='ARCHIVE_ALLOWED',
            channel_bindings=tuple((i, f'sip-channel-{i}') for i in range(1, 7)),
            capture_sha256=hashlib.sha256(canonical_json(document).encode()).hexdigest())


@pytest.mark.parametrize('action,state', [(None, 'NORMAL'), ('H', 'HALTED'), ('P', 'HALTED'),
                                        ('Q', 'QUOTATION_ONLY')])
def test_complete_authoritative_checkpoint_is_connecting_only_including_overnight(action, state):
    s = entitled()
    doc = checkpoint(s, action=action)
    s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)
    result = s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)
    assert result['state'] == state and result['phase'] == 'CONNECTING'
    assert result['live_eligible'] is False
    assert result['next_sequence'] == 702
    s.clock.now += 31*SECOND
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['reason_code'] == 'STATUS_BOOTSTRAP_UNAVAILABLE'


@pytest.mark.parametrize('mutation', ['partial', 'test', 'corrupt', 'missing_channel', 'no_rights', 'rss'])
def test_unattested_or_incomplete_checkpoint_never_proves_normal(mutation):
    s = entitled()
    doc = checkpoint(s)
    rights = authority(doc)
    if mutation == 'partial':
        doc = checkpoint(s, truncate=True)
    elif mutation == 'test':
        doc = checkpoint(s, auth=b'T')
    elif mutation == 'corrupt':
        doc['channels'][0]['original_sha256'] = '0'*64
    elif mutation == 'missing_channel':
        doc['channels'].pop()
    elif mutation == 'no_rights':
        rights = None
    else:
        doc = {'source': 'NASDAQ_RSS', 'complete': True, 'status': 'NORMAL'}
    with pytest.raises(ValueError, match='STATUS_BOOTSTRAP_UNAVAILABLE'):
        s.events.import_status_checkpoint(doc, authority=rights, received_at_ns=s.clock.now)
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'UNKNOWN'


def test_checkpoint_receipt_cannot_fill_earlier_cutoff_or_use_assets_and_bars():
    s = entitled()
    s.store.persist((event(s), status(s, 'T')))
    cutoff = s.clock.now
    assert s.events.status_as_of(s.listing, cutoff_ns=cutoff)['state'] == 'UNKNOWN'
    s.clock.now += SECOND
    s.events.import_status_checkpoint(checkpoint(s), authority=authority(checkpoint(s)), received_at_ns=s.clock.now)
    assert s.events.status_as_of(s.listing, cutoff_ns=cutoff)['state'] == 'UNKNOWN'


def test_checkpoint_after_status_cannot_resurrect_older_resume_and_gap_is_unknown():
    s = entitled()
    s.events.import_status_checkpoint(checkpoint(s), authority=authority(checkpoint(s)), received_at_ns=s.clock.now)
    cutoff = s.clock.now
    s.clock.now += SECOND
    s.store.persist((status(s, 'Q'),))
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'QUOTATION_ONLY'
    assert s.events.status_as_of(s.listing, cutoff_ns=cutoff)['state'] == 'NORMAL'
    s.events.record_status_gap(listing_id=s.listing, received_at_ns=s.clock.now, reason='CAPTURE_GAP')
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'UNKNOWN'


def test_tied_halt_and_resume_is_restrictive_even_across_capture_order():
    s = entitled()
    s.events.import_status_checkpoint(checkpoint(s), authority=authority(checkpoint(s)), received_at_ns=s.clock.now)
    s.clock.now += SECOND
    s.store.persist((status(s, 'H', capture_id='halt'), status(s, 'T', capture_id='resume')))
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'HALTED'


def test_halt_between_snapshot_request_and_checkpoint_admission_is_not_lost():
    s = entitled()
    doc = checkpoint(s)
    s.store.persist((status(s, 'H', at=s.clock.now-SECOND//2),))
    s.clock.now += SECOND
    s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'HALTED'


def test_gap_between_snapshot_request_and_admission_is_unknown():
    s = entitled()
    doc = checkpoint(s)
    s.events.record_status_gap(listing_id=s.listing, received_at_ns=s.clock.now)
    s.clock.now += SECOND
    s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['reason_code'] == 'CAPTURE_GAP'


def test_future_original_snapshot_timestamp_is_rejected():
    s = entitled()
    doc = checkpoint(s)
    raw = bytearray(base64.b64decode(doc['channels'][0]['original_b64']))
    raw[-32:-24] = (s.clock.now + 86400*SECOND).to_bytes(8, 'big')
    doc['channels'][0].update(original_b64=base64.b64encode(raw).decode(), original_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='STATUS_BOOTSTRAP_UNAVAILABLE'):
        s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)


def test_market_wide_circuit_breaker_in_other_channel_blocks_all_listings():
    s = entitled()
    doc = checkpoint(s)
    item = doc['channels'][1]
    raw = base64.b64decode(item['original_b64'])
    end = frame('S', wire('A', 'S', (702).to_bytes(8, 'big'), s.clock.now-SECOND, b'E'))
    raw = raw[:-len(end)] + frame('S', wire('A', 'D', b'1', s.clock.now-SECOND, b'E')) + end
    item.update(original_b64=base64.b64encode(raw).decode(), original_sha256=hashlib.sha256(raw).hexdigest())
    s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] in {'UNKNOWN', 'HALTED'}


def test_older_delayed_checkpoint_does_not_resurrect_normal():
    s = entitled()
    old = checkpoint(s)
    s.clock.now += 2*SECOND
    s.events.import_status_checkpoint(checkpoint(s, action='H'), authority=authority(checkpoint(s, action='H')), received_at_ns=s.clock.now)
    cutoff = s.clock.now
    s.clock.now += SECOND
    for channel in old['channels']:
        channel['received_at_ns'] = s.clock.now
    s.events.import_status_checkpoint(old, authority=authority(old), received_at_ns=s.clock.now)
    assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'HALTED'
    assert s.events.status_as_of(s.listing, cutoff_ns=cutoff)['state'] == 'HALTED'


def test_duplicate_import_keeps_first_knowledge_and_does_not_expand_versions():
    s = setup(history=True)
    ids = import_actions(s)
    before = read(s)
    s.clock.now += SECOND
    assert import_actions(s) == ids
    assert read(s) == before and len(read(s, revisions=True)) == 1


def test_offline_receipt_rejects_document_hash_tampering():
    s = setup(history=True)
    ids = import_actions(s)
    s.db.execute('DROP TRIGGER trg_intraday_capture_events_no_update')
    row = s.db.execute("SELECT * FROM intraday_capture_events WHERE event_version_id=?", ids).fetchone()
    payload = json.loads(row['payload_json'])
    payload['document']['hash'] = '0'*64
    text = canonical_json(payload)
    s.db.execute('UPDATE intraday_capture_events SET payload_json=?,payload_hash=? WHERE id=?',
                 (text, hashlib.sha256(text.encode()).hexdigest(), row['id']))
    s.db.commit()
    with pytest.raises(ValueError, match='EVENT_INPUT_MISSING'):
        read(s)


def test_encoded_wire_credential_echo_is_rejected_without_any_event():
    s = entitled()
    doc = checkpoint(s)
    raw = base64.b64decode(doc['channels'][0]['original_b64']) + frame('+', s.config.alpaca_api_secret_key.encode())
    doc['channels'][0]['original_b64'] = base64.b64encode(raw).decode()
    doc['channels'][0]['original_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match='STATUS_BOOTSTRAP_UNAVAILABLE'):
        s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)
    assert not read(s)


@pytest.mark.parametrize('kind,appendage,valid', [('D', 'none', True), ('B', 'levels', True),
                                              ('D', 'truncate', False), ('B', 'unknown', False)])
def test_snapshot_quote_frames_are_bounded_and_do_not_prove_status(kind, appendage, valid):
    s = entitled()
    doc = checkpoint(s, action='H')
    raw = base64.b64decode(doc['channels'][0]['original_b64'])
    quote = bytearray(83 if kind == 'D' else 53)
    quote[:29] = wire('Q', kind, b'', s.clock.now)
    quote[37:48] = b'AAPL       '
    if kind == 'D':
        quote[76] = quote[78] = quote[79] = quote[80] = ord('0')
    else:
        quote[49] = quote[50] = ord('0')
    if appendage == 'levels':
        quote[50], quote[51:53] = ord('2'), (1).to_bytes(2, 'big')
        quote.extend(b'QB' + bytes(4))
    elif appendage == 'truncate':
        quote[79] = ord('3')
    elif appendage == 'unknown':
        quote[49] = ord('?')
    end = frame('S', wire('A', 'S', (701).to_bytes(8, 'big'), s.clock.now-SECOND, b'E'))
    raw = raw[:-len(end)] + frame('S', bytes(quote)) + end
    doc['channels'][0].update(original_b64=base64.b64encode(raw).decode(), original_sha256=hashlib.sha256(raw).hexdigest())
    if valid:
        s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)
        assert s.events.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'HALTED'
    else:
        with pytest.raises(ValueError, match='STATUS_BOOTSTRAP_UNAVAILABLE'):
            s.events.import_status_checkpoint(doc, authority=authority(doc), received_at_ns=s.clock.now)


@pytest.mark.parametrize('mutation', ['binding', 'unattested_bytes', 'channel_id'])
def test_original_channel_capture_requires_external_digest_and_binding(mutation):
    s = entitled()
    doc = checkpoint(s)
    rights = authority(doc)
    if mutation == 'binding':
        doc['channels'][0]['binding_id'] = 'wrong-source'
        rights = authority(doc)  # Valid external bytes digest still cannot overrule the channel contract.
    elif mutation == 'channel_id':
        doc['channels'][0]['channel'] = 2
    else:
        doc['expires_at_ns'] += 1
    with pytest.raises(ValueError, match='STATUS_BOOTSTRAP_UNAVAILABLE'):
        s.events.import_status_checkpoint(doc, authority=rights, received_at_ns=s.clock.now)
    assert not read(s)


def test_archive_budget_exhaustion_is_atomic_and_does_not_damage_saved_prefix():
    s = setup(history=True)
    import_actions(s)
    before = read(s)
    used = s.events.archive._archive_bytes()
    s.events.archive.settings = replace(s.events.archive.settings, alpaca_max_archive_bytes=used+100)
    s.clock.now += SECOND
    with pytest.raises(ValueError, match='ARCHIVE_LIMIT'):
        import_actions(s, new_rate=4)
    assert read(s) == before and not s.db.in_transaction


def test_demo_calendar_cannot_enter_real_event_reader():
    from test_official_event_calendar import artifact
    s = setup()
    module = importlib.import_module('backend.app.intraday.events')
    demo = module.EventStore(s.archive.provider, clock_ns=lambda: s.clock.now, data_mode='DEMO',
                            provenance='SYNTHETIC', replay_grade='RESEARCH_ONLY')
    demo.import_calendar(artifact(), received_at_ns=s.clock.now)
    assert len(demo.read_as_of(cutoff_ns=s.clock.now)) == 1 and not read(s)
    assert demo.status_as_of(s.listing, cutoff_ns=s.clock.now)['state'] == 'UNKNOWN'
