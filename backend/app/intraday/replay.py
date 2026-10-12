"""Pure causal reducers over validated, published archive occurrences.

No provider, database, implicit clock or mutable operational state. Archive
readers validate receipt dependencies; all versions remain in the timeline.
"""
from __future__ import annotations

import copy
import hashlib

from backend.app.intraday.contracts import MAX_NS, canonical_json

_SCOPE = ('profile_id', 'feed', 'data_mode', 'provenance', 'replay_grade')
_MARKET = ('BAR', 'QUOTE', 'STATUS', 'LULD')
_RANK = {'NORMAL': 1, 'UNKNOWN': 2, 'QUOTATION_ONLY': 3, 'HALTED': 4}


def check_ns(value):
    if type(value) is not int or not 0 <= value <= MAX_NS:
        raise ValueError('INVALID_TIMESTAMP')


def _family(row):
    table = row.get('table')
    if table == 'intraday_observations':
        return row['kind']
    return {'intraday_news_versions': 'NEWS', 'intraday_event_versions': 'EVENT',
            'intraday_identity_versions': 'IDENTITY', 'intraday_calendar_versions': 'CALENDAR',
            'intraday_universe_snapshots': 'UNIVERSE', 'intraday_universe_members': 'MEMBER',
            'intraday_capture_events': 'CONTROL'}.get(table, 'DEPENDENCY')


def _proof_id(row):
    return row.get('admission_id', row.get('publication_id', row['id']))


def _intake(row):
    return row.get('capture_ingest_sequence', row['payload'].get('intake_sequence', row['ingest_sequence']))


def visible_rows(rows, *, cutoff_ns, namespace=None):
    check_ns(cutoff_ns)
    result = []
    rows = [row for row in rows if row.get('available_at_ns') is not None and row['available_at_ns'] <= cutoff_ns]
    primary = next((row for row in rows if not row.get('metadata_dependency')), rows[0] if rows else None)
    expected = namespace or (tuple(primary[key] for key in _SCOPE) if primary else None)
    for row in rows:
        at = row.get('available_at_ns')
        if at is None or at > cutoff_ns:
            continue
        check_ns(at)
        current = tuple(row[key] for key in _SCOPE)
        if expected is None:
            expected = current
        dependency_scope = (*expected[:3], 'CAPTURED' if expected[2] == 'REAL' else 'SYNTHETIC',
                            'STRICT_PIT' if expected[2] == 'REAL' else 'RESEARCH_ONLY')
        dependency = row.get('metadata_dependency') is True and _family(row) in {
            'IDENTITY', 'CALENDAR', 'UNIVERSE', 'MEMBER', 'CONTROL'}
        if _family(row) == 'CONTROL':
            dependency = dependency and row['payload'].get('metadata_kind') in {'PUBLICATION', 'ASSETS', 'ASSET_CHUNK', 'CALENDAR'}
        if current != expected and not (dependency and current == dependency_scope):
            raise ValueError('MIXED_NAMESPACE')
        for key in ('received_at_ns', 'persisted_at_ns', 'ingest_sequence'):
            if key in row:
                check_ns(row[key])
        persisted = row.get('persisted_at_ns', row['received_at_ns'])
        if at < persisted or persisted < row['received_at_ns']:
            raise ValueError('REPLAY_INPUT_INVALID')
        if 'payload_json' in row and row.get('payload_hash') != hashlib.sha256(canonical_json(row['payload']).encode()).hexdigest():
            raise ValueError('REPLAY_INPUT_INVALID')
        result.append(copy.deepcopy(row))
    return result


def causal_order(rows, *, cutoff_ns, namespace=None):
    rows = visible_rows(rows, cutoff_ns=cutoff_ns, namespace=namespace)
    for row in rows:
        row.pop('capture_order', None)  # Derived ordinals from a later view are not evidence.
    anchors = {}
    for row in rows:
        key = (row['received_at_ns'], row['capture_id'])
        anchors[key] = min(anchors.get(key, _proof_id(row)), _proof_id(row))
    return sorted(rows, key=lambda row: (row['available_at_ns'], row['received_at_ns'],
        anchors[(row['received_at_ns'], row['capture_id'])], _intake(row), _proof_id(row),
        row['ingest_sequence'], row.get('table', ''), row['id']))


def select_versions(rows, *, family, cutoff_ns, listing_ids=None, revisions=False):
    rows = visible_rows(rows, cutoff_ns=cutoff_ns)
    def key(row):
        if family in _MARKET:
            return (row['provider'], row['kind'], row['listing_id'], row['event_time_ns'])
        if family == 'NEWS':
            return (row['provider'], row['article_id'])
        if family == 'IDENTITY':
            return (row['listing_id'], row['valid_from_ns'])
        if family == 'CALENDAR':
            return (row['session_date'],)
        if family == 'UNIVERSE':
            return (row['payload'].get('session_date'),)
        return (row['provider'], row['logical_key'])
    anchors = {}
    for row in rows:
        anchor = (*key(row), row.get('updated_at_ns') if family == 'NEWS' else None,
                  row['received_at_ns'], row['capture_id'])
        anchors[anchor] = min(anchors.get(anchor, row['id']), row['id'])
    def order(row):
        anchor = (*key(row), row.get('updated_at_ns') if family == 'NEWS' else None,
                  row['received_at_ns'], row['capture_id'])
        local = (row['received_at_ns'], anchors[anchor], _intake(row), row['ingest_sequence'], row['id'])
        if family == 'NEWS':
            return (row['updated_at_ns'], *local[:-2], row['id'])
        if family == 'IDENTITY':
            return (row['available_at_ns'], row['id'])
        if family == 'EVENT':
            return (*local[:-2], row['id'])
        return local
    for row in rows:
        if family in _MARKET or family == 'NEWS':
            anchor = (*key(row), row.get('updated_at_ns') if family == 'NEWS' else None,
                      row['received_at_ns'], row['capture_id'])
            row['capture_order'] = anchors[anchor]
    if not revisions:
        latest = {}
        for row in rows:
            identity = key(row)
            if identity not in latest or order(row) > order(latest[identity]):
                latest[identity] = row
        rows = list(latest.values())
    if listing_ids is not None:
        rows = [row for row in rows if (any(link['listing_id'] in listing_ids for link in row['links'])
                if family == 'NEWS' else row['listing_id'] in listing_ids)]
    if family in _MARKET:
        return sorted(rows, key=lambda row: (row['event_time_ns'], row['available_at_ns'], *order(row)))
    if family == 'NEWS':
        return sorted(rows, key=lambda row: (row['available_at_ns'], *order(row)[1:]))
    return sorted(rows, key=order)


def quote_state_from_rows(rows, *, listing_id, cutoff_ns, max_age_ns=2_000_000_000):
    check_ns(max_age_ns)
    rows = select_versions(rows, family='QUOTE', cutoff_ns=cutoff_ns, listing_ids=(listing_id,))
    if not rows:
        return None
    result = dict(rows[-1])
    result.pop('table', None)
    result.update(nbbo=result['feed'] == 'sip', delayed=result['feed'] == 'delayed_sip',
                  size_conversion_attested=False)
    if cutoff_ns - result['event_time_ns'] > max_age_ns:
        result.update(quality='QUARANTINED', reason_code='QUOTE_STALE')
    result['executable'] = result['quality'] == 'VALID' and result['nbbo'] and result['payload']['source'] == 'STREAM'
    return result


def status_state_from_rows(checkpoint, observations, *, cutoff_ns):
    payload = checkpoint['payload']
    if payload['expires_at_ns'] <= cutoff_ns or payload.get('reason_code') is not None:
        return 'UNKNOWN'
    rows = [row for row in visible_rows(observations, cutoff_ns=cutoff_ns)
            if row.get('kind') == 'STATUS' and row['listing_id'] == checkpoint['listing_id']
            and row['event_time_ns'] >= checkpoint['effective_at_ns']]
    state = payload['state']
    if rows:
        at = max(row['event_time_ns'] for row in rows)
        tied = [row['payload']['state'] if row['quality'] == 'VALID' else 'UNKNOWN'
                for row in rows if row['event_time_ns'] == at]
        if at == checkpoint['effective_at_ns']:
            tied.append(state)
        state = max(tied, key=_RANK.__getitem__)
    return state


def capture_state_from_rows(controls, events, observations, *, cutoff_ns, news=()):
    controls = causal_order(controls, cutoff_ns=cutoff_ns)
    starts = [row for row in controls if row['kind'] == 'CAPTURE_START']
    default = {'state': 'STOPPED', 'capture_id': None, 'listing_states': {}, 'news_coverage': 'UNKNOWN',
               'basis': 'DURABLE_EVIDENCE_ONLY'}
    if not starts:
        return default
    start = starts[-1]
    capture = start['capture_id']
    result = {**default, 'state': 'CONNECTING', 'capture_id': capture}
    controls = [row for row in controls if row['capture_id'] == capture]
    if any(row['kind'] in {'GAP', 'STOP'} for row in controls):
        last = next(row for row in reversed(controls) if row['kind'] in {'GAP', 'STOP'})
        result['state'] = ('STOPPED' if last['payload'].get('reason_code') == 'STOPPED' else
                           'FAILED' if last['payload'].get('terminal') else 'BACKOFF')
        return result
    proofs = {row['id']: row for row in controls}
    handshake = [row for row in controls if row['kind'] == 'BOOTSTRAP'
                 and row['payload'].get('metadata_kind') == 'COLLECTOR_HANDSHAKE']
    if not handshake:
        return result
    policy = start['payload'].get('continuity_policy')
    if not isinstance(policy, dict) or policy.get('version') != 'collector-continuity-v1':
        return result  # Legacy capture has no frozen timeout; never infer today's config.
    silence, lease = policy.get('socket_silence_ns'), policy.get('lease_ns')
    if type(silence) is not int or type(lease) is not int or not 0 < silence <= 300_000_000_000 or not 0 < lease <= 300_000_000_000:
        return result
    boot = handshake[-1]
    barrier = boot['payload'].get('barrier_at_ns')
    if type(barrier) is not int or not 0 <= barrier <= boot['received_at_ns']:
        return result
    acks = {}
    ack_refs = boot['payload'].get('ack_refs', [])
    if len(ack_refs) != 2:
        return result
    for ref in ack_refs:
        row = proofs.get(ref.get('id'))
        if row is None or row['kind'] != 'ACK' or any(row.get(key) != ref.get(key) for key in ('publication_id', 'publication_hash')):
            return result
        if row['payload_hash'] != ref.get('hash') or row['available_at_ns'] > barrier:
            return result
        channel = row['payload']['channel']
        if channel in acks or row['received_at_ns'] < start['received_at_ns']:
            return result
        if row['payload']['subscriptions'] != start['payload']['subscriptions'].get(channel):
            return result
        acks[channel] = row
    if set(acks) != {'market', 'news'} or boot['payload'].get('continuity_attested') is not True:
        return result
    event_refs = {row['id']: row for row in events if row['capture_id'] == capture}
    observation_refs = {row['id']: row for row in observations if row['capture_id'] == capture}
    states = {}
    for ref in boot['payload'].get('listings', []):
        checkpoint = event_refs.get(ref.get('checkpoint_id'))
        if checkpoint is None or checkpoint['payload_hash'] != ref.get('checkpoint_hash') or checkpoint['admission_id'] != ref.get('checkpoint_admission_id'):
            return result
        if (checkpoint['available_at_ns'] > barrier or checkpoint['effective_at_ns'] < acks['market']['available_at_ns']
            or checkpoint['listing_id'] != ref['listing_id'] or checkpoint['payload'].get('version') != 'utp-status-checkpoint-v1'
            or checkpoint['effective_at_ns'] != ref['snapshot_at_ns'] or checkpoint['payload']['expires_at_ns'] != ref['expires_at_ns']):
            return result
        for status_ref in ref.get('status_refs', []):
            row = observation_refs.get(status_ref.get('id'))
            if (row is None or row['payload_hash'] != status_ref.get('hash') or row['admission_id'] != status_ref.get('admission_id')
                or row['available_at_ns'] > barrier or row['kind'] != 'STATUS' or row['listing_id'] != ref['listing_id']):
                return result
        listing = ref['listing_id']
        state = status_state_from_rows(checkpoint, [row for row in observations if row['capture_id'] == capture], cutoff_ns=cutoff_ns)
        states[listing] = {'state': state, 'live_eligible': state == 'NORMAL',
                          'expires_at_ns': checkpoint['payload']['expires_at_ns'],
                          'reason_code': 'STATUS_UNKNOWN' if state == 'UNKNOWN' else None}
    if set(states) != set(start['payload']['listing_ids']):
        return result
    result.update(state='LIVE' if all(item['state'] != 'UNKNOWN' for item in states.values()) else 'DEGRADED', listing_states=states)
    transport = {channel: row['payload']['received_at_ns'] for channel, row in acks.items()}
    for row in observations:
        if row['capture_id'] == capture:
            transport['market'] = max(transport['market'], row['received_at_ns'])
    for row in news:
        if row['capture_id'] == capture:
            transport['news'] = max(transport['news'], row['received_at_ns'])
    valid_news_clocks = []
    for row in controls:
        if row['kind'] == 'CLOCK' and row['payload'].get('metadata_kind') == 'TRANSPORT_LIVENESS':
            payload = row['payload']
            channel = payload.get('channel')
            ping, pong = payload.get('ping_sent_at_ns'), payload.get('pong_received_at_ns')
            if channel not in transport or type(ping) is not int or type(pong) is not int or not 0 <= ping <= pong <= row['received_at_ns']:
                result['state'] = 'DEGRADED'
                continue
            transport[channel] = max(transport[channel], pong)
            if channel == 'news':
                valid_news_clocks.append(pong)
    latest_owner_evidence = max(row['available_at_ns'] for row in controls if row['kind'] in {'CAPTURE_START', 'ACK', 'CLOCK'}
        or row['payload'].get('metadata_kind') == 'COLLECTOR_HANDSHAKE')
    if any(cutoff_ns - stamp > silence for stamp in transport.values()) or cutoff_ns - latest_owner_evidence >= lease:
        result['state'] = 'DEGRADED'
    if result['state'] != 'LIVE':
        for item in states.values():
            item['live_eligible'] = False
    # A successful durable handshake is a barrier for both subscriptions.
    covered = max([barrier, *valid_news_clocks])
    result['news_coverage'] = 'COVERED' if result['state'] == 'LIVE' and cutoff_ns <= covered else 'UNKNOWN'
    return result


def replay_as_of(rows, *, cutoff_ns, listing_ids=None, namespace=None, quote_max_age_ns=2_000_000_000):
    timeline = causal_order(rows, cutoff_ns=cutoff_ns, namespace=namespace)
    families = {}
    for row in timeline:
        families.setdefault(_family(row), []).append(row)
    observations = {kind: select_versions(families.get(kind, []), family=kind, cutoff_ns=cutoff_ns,
                                         listing_ids=listing_ids) for kind in _MARKET}
    quote_listings = {row['listing_id'] for row in observations['QUOTE']}
    quotes = {listing: quote_state_from_rows(families.get('QUOTE', []), listing_id=listing,
              cutoff_ns=cutoff_ns, max_age_ns=quote_max_age_ns) for listing in sorted(quote_listings)}
    news = select_versions(families.get('NEWS', []), family='NEWS', cutoff_ns=cutoff_ns, listing_ids=listing_ids)
    events = select_versions(families.get('EVENT', []), family='EVENT', cutoff_ns=cutoff_ns)
    if listing_ids is not None:
        events = [row for row in events if row['listing_id'] is None or row['listing_id'] in listing_ids]
    calendars = select_versions(families.get('CALENDAR', []), family='CALENDAR', cutoff_ns=cutoff_ns)
    batches = [row for row in families.get('CONTROL', []) if row['payload'].get('metadata_kind') == 'CALENDAR']
    if batches:
        calendars = [row for row in calendars if any(row['id'] == batch['payload']['session_ids'].get(row['session_date'])
            for batch in [max((item for item in batches if item['payload']['start'] <= row['session_date'] <= item['payload']['end']),
                             key=lambda item: (item['received_at_ns'], item['id']), default={'payload': {'session_ids': {}}})])]
    capture = capture_state_from_rows(families.get('CONTROL', []), families.get('EVENT', []),
        [row for kind in _MARKET for row in families.get(kind, [])], cutoff_ns=cutoff_ns, news=families.get('NEWS', []))
    if capture['news_coverage'] == 'COVERED' and not news:
        capture['news_coverage'] = 'COVERED_ZERO'
    return {'version': 'intraday-replay-v1', 'cutoff_ns': cutoff_ns,
            'namespace': namespace or (tuple(next((row for row in timeline if not row.get('metadata_dependency')), timeline[0])[key]
                                      for key in _SCOPE) if timeline else namespace),
            'timeline': timeline, 'observations': observations, 'quotes': quotes, 'news': news, 'events': events,
            'identities': select_versions(families.get('IDENTITY', []), family='IDENTITY', cutoff_ns=cutoff_ns),
            'calendars': calendars,
            'universes': select_versions(families.get('UNIVERSE', []), family='UNIVERSE', cutoff_ns=cutoff_ns),
            'capture': capture}


class ReplayReducer:
    """Finite inputs may be supplied in arbitrary batches; as_of never uses the tail."""
    def __init__(self, *, namespace=None):
        self.namespace, self._rows = namespace, []

    def extend(self, rows):
        self._rows.extend(copy.deepcopy(list(rows)))

    def as_of(self, cutoff_ns, *, listing_ids=None):
        return replay_as_of(self._rows, cutoff_ns=cutoff_ns, listing_ids=listing_ids, namespace=self.namespace)


def replay_frozen(manifest, rows, *, cutoff_ns=None, listing_ids=None):
    """Pure snapshot adapter; the caller has validated the exact persisted references."""
    frozen_cutoff = manifest['cutoff_ns']
    check_ns(frozen_cutoff)
    cutoff = frozen_cutoff if cutoff_ns is None else cutoff_ns
    check_ns(cutoff)
    if cutoff > frozen_cutoff:
        raise ValueError('SNAPSHOT_CUTOFF')
    planned = manifest['listing_ids']
    if listing_ids is not None and any(item not in planned for item in listing_ids):
        raise ValueError('SNAPSHOT_SCOPE')
    return replay_as_of(rows, cutoff_ns=cutoff, listing_ids=planned if listing_ids is None else listing_ids,
                        namespace=tuple(manifest['namespace']),
                        quote_max_age_ns=manifest['policy']['config']['quote_max_age_ns'])
