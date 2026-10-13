"""Strategy-independent, fixed-grid quality evidence over a frozen prefix only."""
from __future__ import annotations

import bisect
import json
from collections import Counter, OrderedDict, defaultdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from backend.app.intraday.aggregate import MINUTE_NS, _crosses_action, aggregate_as_of
from backend.app.intraday.contracts import FeedProfile, QualityPolicy
from backend.app.intraday.replay import (
    _family,
    capture_state_from_rows,
    causal_order,
    check_ns,
    quote_state_from_rows,
    select_versions,
    status_state_from_rows,
    visible_rows,
)


def validate_manifest(manifest):
    policy = QualityPolicy()
    frozen = manifest['policy']
    if (frozen['id'] != policy.version or frozen['hash'] != policy.policy_hash or
            frozen['config'] != json.loads(policy.config_json)):
        raise ValueError('QUALITY_POLICY_INVALID')
    for key in ('start_at_ns', 'end_at_ns', 'cutoff_ns'):
        check_ns(manifest[key])
    listings, benchmarks, namespace = manifest['listing_ids'], manifest['benchmarks'], manifest['namespace']
    if (manifest.get('version') not in {'intraday-dataset-v1', 'intraday-dataset-v2','intraday-bundle-quality-v1'} or
            not manifest['start_at_ns'] < manifest['end_at_ns'] <= manifest['cutoff_ns'] or
            manifest.get('version') != 'intraday-bundle-quality-v1' and manifest['end_at_ns'] - manifest['start_at_ns'] > 366 * 86400 * 1_000_000_000 or
            type(listings) is not list or not listings or listings != sorted(set(listings)) or
            any(type(item) is not int or item <= 0 for item in listings) or
            type(benchmarks) is not dict or not set(benchmarks) <= {'market', 'sector'} or
            any(type(item) is not int or item not in listings for item in benchmarks.values()) or
            type(namespace) is not list or len(namespace) != 5):
        raise ValueError('DATASET_INVALID')
    if manifest['version'] == 'intraday-dataset-v2' and (manifest.get('selection') != 'window-dependency-closure-v2'
            or type(manifest.get('carry_at_ns')) is not int
            or manifest['carry_at_ns'] != manifest['start_at_ns'] - 1
            or type(manifest.get('window_session_count')) is not int
            or not 0 <= manifest['window_session_count'] <= 5
            or type(manifest.get('history_sessions')) is not int
            or not 1 <= manifest['history_sessions'] <= 30):
        raise ValueError('DATASET_INVALID')
    if manifest['version']=='intraday-dataset-v2':
        caps = {'max_listings':30,'max_chunk_occurrences':10_000,'max_chunk_bytes':8_388_608,
                'max_cache_bytes':67_108_864,'max_rss_bytes':2_147_483_648,'window_sessions':5,'history_sessions':30}
        resources = manifest.get('resources')
        if (type(resources) is not dict or set(resources)!={*caps,'max_disk_bytes','min_free_bytes'}
            or any(type(value) is not int or value<=0 or key in caps and value>caps[key]
                   for key,value in resources.items())
            or len(listings)>resources['max_listings']
            or manifest['window_session_count']>resources['window_sessions']
            or manifest['history_sessions']!=resources['history_sessions']
            or type(manifest.get('support_start_at_ns')) is not int
            or not 0<=manifest['support_start_at_ns']<=manifest['start_at_ns']):
            raise ValueError('DATASET_INVALID')
    for item in (frozen, manifest['profile']):
        check_ns(item['created_at_ns'])
        if item['created_at_ns'] > manifest['cutoff_ns']:
            raise ValueError('DATASET_INVALID')
    profile = _profile(manifest)
    if manifest['version']=='intraday-bundle-quality-v1' and len(listings)>min(30,profile.max_symbols):
        raise ValueError('DATASET_INVALID')


def _profile(manifest):
    try:
        config = dict(manifest['profile']['config'])
        for key in ('required_capabilities', 'attested_capabilities', 'quote_conditions'):
            config[key] = tuple(config[key])
        profile = FeedProfile(**config)
        if (profile.profile_id != manifest['namespace'][0] or profile.feed != manifest['namespace'][1] or
                manifest['profile']['id'] != profile.profile_id or manifest['profile']['provider'] != profile.provider or
                manifest['profile']['feed'] != profile.feed):
            raise ValueError
        return profile
    except (ValueError, KeyError, TypeError):
        raise ValueError('QUALITY_PROFILE_INVALID') from None


def _day(stamp):
    return datetime.fromtimestamp(stamp // 1_000_000_000, UTC).astimezone(ZoneInfo('America/New_York')).date()


def _percentiles(values):
    if not values:
        return {'count': 0, 'p50_ns': None, 'p95_ns': None, 'max_ns': None}
    histogram = values if isinstance(values, Counter) else Counter(values)
    count = sum(histogram.values())
    ranks = ((count - 1) // 2, ((count - 1) * 95 + 99) // 100)
    selected, cumulative = [], 0
    for value, occurrences in sorted(histogram.items()):
        cumulative += occurrences
        while len(selected) < 2 and cumulative > ranks[len(selected)]:
            selected.append(value)
    return {'count': count, 'p50_ns': selected[0], 'p95_ns': selected[1], 'max_ns': max(histogram)}


class _Index:
    """Small revision buckets and prefix maxima; never replay all market ticks per grid point."""
    def __init__(self, rows, *, max_cache_bytes=67_108_864):
        self.max_cache_bytes,self.cache_bytes,self.cache_sizes = max_cache_bytes,0,{}
        self.family = defaultdict(list)
        self.bars = defaultdict(list)
        self.quotes = defaultdict(list)
        self.controls = defaultdict(list)
        self.status = defaultdict(list)
        self.events = defaultdict(list)
        self.receipts = defaultdict(list)
        for row in rows:
            family = _family(row)
            self.family[family].append(row)
            if family == 'BAR':
                self.bars[row['listing_id'], row['event_time_ns']].append(row)
            if family == 'QUOTE':
                self.quotes[row['listing_id']].append(row)
            if family == 'CONTROL':
                self.controls[row['capture_id']].append(row)
            if family == 'STATUS':
                self.status[row['capture_id']].append(row)
            if family == 'EVENT':
                self.events[row['capture_id']].append(row)
            if family in {'BAR', 'QUOTE', 'STATUS', 'LULD', 'NEWS'}:
                self.receipts[row['capture_id'], 'news' if family == 'NEWS' else 'market'].append(row)
        self.starts = sorted((row for row in self.family['CONTROL'] if row['kind'] == 'CAPTURE_START'),
                             key=lambda row: (row['available_at_ns'], row['received_at_ns'], row['id']))
        self.start_times = [row['available_at_ns'] for row in self.starts]
        self.maxima = {}
        for key, scope, values in [*(('quote', listing, rows) for listing, rows in self.quotes.items()),
                            *(('receipt', scope, rows) for scope, rows in self.receipts.items())]:
            ordered = sorted(values, key=lambda row: row['available_at_ns'])
            stamps, top, best = [], [], None
            field = 'event_time_ns' if key == 'quote' else 'received_at_ns'
            for row in ordered:
                if best is None or row[field] > best[field]:
                    best = row
                stamps.append(row['available_at_ns'])
                top.append(best)
            self.maxima[key, scope] = (stamps, top)
        self.quote_buckets = defaultdict(list)
        for listing, values in self.quotes.items():
            for row in values:
                self.quote_buckets[listing, row['event_time_ns']].append(row)
        self.contexts = OrderedDict()
        self.event_cache = OrderedDict()
        self.controls_received = defaultdict(list)
        for row in self.family['CONTROL']:
            self.controls_received[row['received_at_ns']].append(row)

    def event_versions(self, cutoff):
        if cutoff not in self.event_cache:
            self._cache('event_cache',cutoff,select_versions(self.family['EVENT'], family='EVENT', cutoff_ns=cutoff))
        self.event_cache.move_to_end(cutoff)
        return self.event_cache[cutoff]

    def _cache(self, label, key, value):
        size = len(json.dumps(value,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())
        if size>self.max_cache_bytes:
            raise ValueError('RESOURCE_LIMIT')
        for name in (label,'contexts' if label=='event_cache' else 'event_cache'):
            cache = getattr(self,name)
            while cache and self.cache_bytes+size>self.max_cache_bytes:
                evicted,_ = cache.popitem(last=False)
                self.cache_bytes -= self.cache_sizes.pop((name,evicted))
        getattr(self,label)[key] = value
        self.cache_sizes[label,key] = size
        self.cache_bytes += size

    def maximum(self, key, cutoff):
        stamps, top = self.maxima.get(key, ([], []))
        at = bisect.bisect_right(stamps, cutoff) - 1
        return top[at] if at >= 0 else None

    def quote(self, listing, cutoff, policy):
        latest = self.maximum(('quote', listing), cutoff)
        return None if latest is None else quote_state_from_rows(self.quote_buckets[listing, latest['event_time_ns']],
            listing_id=listing, cutoff_ns=cutoff, max_age_ns=policy.quote_max_age_ns)

    def context(self, cutoff):
        if cutoff in self.contexts:
            self.contexts.move_to_end(cutoff)
            return self.contexts[cutoff]
        index = bisect.bisect_right(self.start_times, cutoff) - 1
        if index < 0:
            result = {'state': 'STOPPED', 'capture_id': None, 'listing_states': {}, 'news_coverage': 'UNKNOWN'}
        else:
            stamp = self.starts[index]['available_at_ns']
            tied = self.starts[bisect.bisect_left(self.start_times, stamp):index + 1]
            anchors = {row['received_at_ns'] for row in tied}
            ordered = causal_order([row for received in anchors for row in self.controls_received[received]], cutoff_ns=cutoff)
            capture = next(row for row in reversed(ordered) if row['kind'] == 'CAPTURE_START')['capture_id']
            controls = [row for row in self.controls[capture] if row['available_at_ns'] <= cutoff]
            # Keep every invalid clock (it degrades the epoch), plus the latest valid clock per channel.
            clocks, compact = {}, []
            for row in controls:
                payload = row['payload']
                if row['kind'] != 'CLOCK' or payload.get('metadata_kind') != 'TRANSPORT_LIVENESS':
                    compact.append(row)
                    continue
                channel, ping, pong = payload.get('channel'), payload.get('ping_sent_at_ns'), payload.get('pong_received_at_ns')
                if (channel not in {'market', 'news'} or type(ping) is not int or type(pong) is not int or
                        not 0 <= ping <= pong <= row['received_at_ns']):
                    compact.append(row)
                elif channel not in clocks or pong > clocks[channel]['payload']['pong_received_at_ns']:
                    clocks[channel] = row
            compact.extend(clocks.values())
            latest_clock = max((row for row in controls if row['kind'] == 'CLOCK'),
                               key=lambda row: row['available_at_ns'], default=None)
            if latest_clock is not None and latest_clock not in compact:
                compact.append(latest_clock)
            observations = [row for row in self.status[capture] if row['available_at_ns'] <= cutoff]
            market = self.maximum(('receipt', (capture, 'market')), cutoff)
            if market is not None and market not in observations:
                observations.append(market)
            news = self.maximum(('receipt', (capture, 'news')), cutoff)
            result = capture_state_from_rows(compact, self.events[capture], observations, cutoff_ns=cutoff,
                                             news=() if news is None else (news,))
        self._cache('contexts',cutoff,result)
        return result

    def continuity(self, listing, start, end, decision):
        context = self.context(decision)
        if context['state'] != 'LIVE' or not context['listing_states'].get(listing, {}).get('live_eligible'):
            return 'STATUS_OR_CAPTURE_UNKNOWN'
        if context['news_coverage'] not in {'COVERED', 'COVERED_ZERO'}:
            return 'NEWS_COVERAGE_UNKNOWN'
        capture = context['capture_id']
        # Do not join two otherwise valid captures, or overlook an outage in the middle of a group.
        points = {start, end, *range(start, end, MINUTE_NS)}
        for row in self.controls[capture]:
            at = row['available_at_ns']
            if start <= at <= end:
                points.add(at)
        for point in sorted(points):
            prior = self.context(point)
            if (prior['capture_id'] != capture or prior['state'] != 'LIVE' or
                    not prior['listing_states'].get(listing, {}).get('live_eligible')):
                return 'CAPTURE_DISCONTINUITY'
            if prior['news_coverage'] not in {'COVERED', 'COVERED_ZERO'}:
                return 'NEWS_COVERAGE_UNKNOWN'
        statuses = select_versions(self.status[capture], family='STATUS', cutoff_ns=decision, listing_ids=(listing,))
        if any(start <= row['event_time_ns'] < end and
               (row['quality'] != 'VALID' or row['payload'].get('state') != 'NORMAL') for row in statuses):
            return 'STATUS_INTERRUPTION'
        checkpoints = [row for row in self.events[capture] if row['listing_id'] == listing and
                       row['payload'].get('version') == 'utp-status-checkpoint-v1' and row['available_at_ns'] <= decision]
        if not checkpoints:
            return 'STATUS_OR_CAPTURE_UNKNOWN'
        checkpoint = max(checkpoints, key=lambda row: (row['effective_at_ns'], row['available_at_ns'], row['id']))
        if status_state_from_rows(checkpoint, [row for row in statuses if row['event_time_ns'] <= start], cutoff_ns=decision) != 'NORMAL':
            return 'STATUS_INTERRUPTION'
        return None


def _sessions(manifest, index, reasons):
    start, end, cutoff = (manifest[key] for key in ('start_at_ns', 'end_at_ns', 'cutoff_ns'))
    groups = defaultdict(list)
    for row in index.family['CALENDAR']:
        groups[row['session_date']].append(row)
    headers = [row for row in index.family['CONTROL'] if row['payload'].get('metadata_kind') == 'CALENDAR'
               and row['payload'].get('complete') is True]
    sessions = []
    for day, versions in sorted(groups.items()):
        anchor = min(versions, key=lambda row: (row['received_at_ns'], row['id']))
        planning_cutoff = min(cutoff, anchor['open_at_ns'] - 1)
        known = select_versions([row for row in versions if row['available_at_ns'] < row['open_at_ns']],
                                family='CALENDAR', cutoff_ns=planning_cutoff)
        selected = known[-1] if known else anchor
        batches = [row for row in headers if row['payload']['start'] <= day <= row['payload']['end']
                   and row['available_at_ns'] <= planning_cutoff]
        batch = max(batches, key=lambda row: (row['received_at_ns'], row['id']), default=None)
        if batch and day not in batch['payload']['session_ids']:
            continue  # An explicit complete pre-open replacement may certify a holiday.
        if selected['close_at_ns'] <= start or selected['open_at_ns'] >= end:
            continue
        valid = bool(known and batch and batch['payload']['session_ids'].get(day) == selected['id'] and
                     batch['payload'].get('member_count') == len(batch['payload']['session_ids']))
        if not valid:
            reasons.add('CALENDAR_COVERAGE_UNKNOWN')
        if selected['open_at_ns'] < start or selected['close_at_ns'] > end:
            reasons.add('PERIOD_PARTIAL_SESSION')
            valid = False
        sessions.append((selected, valid))
    # A complete frozen range is required also for dates with no session (explicit holidays).
    day, last = _day(start), _day(end - 1)
    while day <= last:
        session = next((row for row, _ in sessions if row['session_date'] == day.isoformat()), None)
        boundary = session['open_at_ns'] - 1 if session else int(datetime.combine(
            day + timedelta(days=1), datetime.min.time(), ZoneInfo('America/New_York')).timestamp()) * 1_000_000_000 - 1
        matching = [row for row in headers if row['payload']['start'] <= day.isoformat() <= row['payload']['end']
                    and row['available_at_ns'] <= min(boundary, cutoff)]
        if not matching:
            reasons.add('CALENDAR_COVERAGE_UNKNOWN')
        else:
            batch = max(matching, key=lambda row: (row['received_at_ns'], row['id']))
            expected = batch['payload']['session_ids'].get(day.isoformat())
            if (batch['payload'].get('member_count') != len(batch['payload']['session_ids']) or
                    (expected is not None and not any(row['id'] == expected for row in groups.get(day.isoformat(), [])))):
                reasons.add('CALENDAR_COVERAGE_UNKNOWN')
        day += timedelta(days=1)
    if not sessions:
        reasons.add('CALENDAR_COVERAGE_UNKNOWN')
    return sorted(sessions, key=lambda item: item[0]['open_at_ns'])


def _eligibility(index, calendar, listing, valid_calendar):
    opening = calendar['open_at_ns']
    universes = select_versions(index.family['UNIVERSE'], family='UNIVERSE', cutoff_ns=opening - 1)
    universe = next((row for row in universes if row['payload']['session_date'] == calendar['session_date']), None)
    if not valid_calendar or universe is None or universe['payload'].get('kind') != 'PROSPECTIVE':
        return 'UNIVERSE_NOT_PROSPECTIVE'
    if (universe['payload'].get('calendar_version_id') != calendar['id'] or
            universe['payload'].get('calendar_hash') != calendar['payload_hash'] or
            universe['payload'].get('open_at_ns') != calendar['open_at_ns'] or
            universe['payload'].get('close_at_ns') != calendar['close_at_ns']):
        return 'CALENDAR_UNIVERSE_MISMATCH'
    members = universe['payload'].get('members', [])
    member = next((item for item in members if item['listing_id'] == listing), None)
    if member is None or not member.get('eligible'):
        return (member or {}).get('reason_code') or 'IDENTITY_UNVERIFIED'
    identities = select_versions(index.family['IDENTITY'], family='IDENTITY', cutoff_ns=opening - 1)
    identity = next((row for row in identities if row['id'] == member['identity_version_id']), None)
    if (identity is None or identity['payload_hash'] != member['identity_hash'] or
            identity['listing_id'] != listing or not identity.get('confirmed') or
            not identity['valid_from_ns'] <= opening or
            (identity['valid_to_ns'] is not None and opening >= identity['valid_to_ns'])):
        return 'IDENTITY_UNVERIFIED'
    return None


def _calendars_available(index, listing, opening):
    documents = [row for row in index.family['CONTROL'] if row['payload'].get('metadata_kind') == 'EVENT_DOCUMENT'
                 and row['available_at_ns'] < opening]
    docs = {row['id']: row for row in documents}
    sources, earnings = set(), False
    for row in index.event_versions(opening - 1):
        payload, reference = row['payload'], row['payload'].get('document', {})
        document = docs.get(reference.get('id'))
        if (document is None or document['payload_hash'] != reference.get('hash') or
                payload.get('version') != 'official-event-calendar-v1' or
                payload.get('coverage') != 'ANNOUNCED_EVENTS_ONLY' or
                payload.get('authenticity_basis') != 'LOCAL_OFFICIAL_COPY'):
            continue
        source = payload.get('source')
        sources.add(source)
        if source == 'issuer' and row['listing_id'] == listing and row['event_type'] == 'EARNINGS':
            earnings = True
    return {'bls', 'fed'} <= sources and earnings


def planned_listing_ids(manifest, rows):
    """Prospective requests define denominators, including exclusions omitted by the caller."""
    index = _Index(rows)
    planned = set(manifest['listing_ids'])
    for calendar, _ in _sessions(manifest, index, set()):
        universes = select_versions(index.family['UNIVERSE'], family='UNIVERSE', cutoff_ns=calendar['open_at_ns'] - 1)
        for row in universes:
            if row['payload']['session_date'] == calendar['session_date']:
                requested = row['payload'].get('requested_listing_ids', [])
                if type(requested) is not list or any(type(item) is not int or item <= 0 for item in requested):
                    raise ValueError('DATASET_INVALID')
                planned.update(requested)
    return sorted(planned)


def quality_report(manifest, rows, *, row_factory=None,resource_guard=None):
    validate_manifest(manifest)
    policy = QualityPolicy()
    rows = visible_rows(rows, cutoff_ns=manifest['cutoff_ns'], namespace=tuple(manifest['namespace']))
    index = _Index(rows)
    reasons, ineligible = set(), []
    listings = planned_listing_ids(manifest, rows)
    if listings != manifest['listing_ids']:
        reasons.add('DATASET_SCOPE_INCOMPLETE')
    namespace, profile = manifest['namespace'], manifest['profile']
    compatible = namespace[1:] == ['sip', 'REAL', 'CAPTURED', 'STRICT_PIT']
    caps = set(profile['config'].get('attested_capabilities', []))
    if not {'bars', 'quotes', 'news', 'status'} <= caps:
        reasons.add('CAPABILITY_UNVERIFIED')
    if not _profile(manifest).ready_for_capture:
        reasons.add('BUDGET_UNATTESTED')
    if profile['created_at_ns'] >= manifest['start_at_ns'] or manifest['policy']['created_at_ns'] >= manifest['start_at_ns']:
        reasons.add('POLICY_OR_PROFILE_NOT_EX_ANTE')
    if set(manifest['benchmarks']) != {'market', 'sector'} or len(set(manifest['benchmarks'].values())) != 2:
        reasons.add('BENCHMARKS_MISSING')
    sessions = _sessions(manifest, index, reasons)
    raw_planned = raw_valid = eligible_sessions = 0
    grid, ages, delays = [], Counter(), Counter()
    status_exclusions = Counter()
    for calendar, valid_calendar in sessions:
        if resource_guard is not None:
            resource_guard()
        if row_factory is not None:
            index = _Index(row_factory(calendar),max_cache_bytes=manifest.get('resources',{}).get('max_cache_bytes',67_108_864))
        opening, closing = calendar['open_at_ns'], calendar['close_at_ns']
        eligibility = {listing: _eligibility(index, calendar, listing, valid_calendar) for listing in listings}
        eligible_count = sum(reason is None for reason in eligibility.values())
        if eligible_count >= policy.min_listings:
            eligible_sessions += 1
        else:
            reasons.add('LISTINGS_INSUFFICIENT')
        for listing, exclusion in eligibility.items():
            if exclusion:
                ineligible.append({'listing_id': listing, 'session_date': calendar['session_date'], 'reason_code': exclusion})
            if not _calendars_available(index, listing, opening):
                reasons.add('CALENDAR_EVENTS_UNKNOWN')
            raw_points = (closing - opening) // MINUTE_NS
            raw_planned += raw_points
            for minute in range(raw_points):
                at = opening + minute * MINUTE_NS
                decision = at + MINUTE_NS + policy.decision_delay_ns
                selected = select_versions(index.bars[listing, at], family='BAR', cutoff_ns=min(decision, manifest['cutoff_ns']))
                if selected and selected[-1]['quality'] == 'VALID' and selected[-1]['bar_end_ns'] == at + MINUTE_NS:
                    delay = selected[-1]['available_at_ns'] - (at + MINUTE_NS)
                    delays[max(0, delay)] += 1
                    if 0 <= delay <= policy.bar_max_delay_ns and decision <= manifest['cutoff_ns']:
                        raw_valid += 1
            for minutes in policy.timeframes_minutes:
                width = minutes * MINUTE_NS
                planned, usable, excluded = (closing - opening) // width, 0, Counter()
                for number in range(planned):
                    start, end = opening + number * width, opening + (number + 1) * width
                    decision = end + policy.decision_delay_ns
                    reason = exclusion
                    if decision > manifest['cutoff_ns']:
                        reason = 'DECISION_NOT_CAPTURED'
                    candidates = [row for offset in range(minutes) for row in index.bars[listing, start + offset * MINUTE_NS]]
                    events = index.event_versions(min(decision, manifest['cutoff_ns']))
                    events = [row for row in events if row['listing_id'] in {None, listing}]
                    session = SimpleNamespace(open_at_ns=start, close_at_ns=end,
                        known_at_ns=calendar['available_at_ns'], version_id=calendar['id'])
                    if reason is None:
                        aggregate = aggregate_as_of(candidates, session, cutoff_ns=decision, minutes=minutes, events=events)
                        if not aggregate['bars']:
                            reason = aggregate['exclusions'][0]['reason_code'] if aggregate['exclusions'] else 'MISSING_MINUTE'
                        elif any(row['available_at_ns'] - row['bar_end_ns'] > policy.bar_max_delay_ns
                                 for row in select_versions(candidates, family='BAR', cutoff_ns=decision)):
                            reason = 'BAR_DELAY'
                    quote = index.quote(listing, min(decision, manifest['cutoff_ns']), policy)
                    if quote is not None:
                        ages[max(0, decision - quote['event_time_ns'])] += 1
                    if reason is None and (quote is None or not quote['executable']):
                        reason = 'QUOTE_MISSING' if quote is None else quote['reason_code'] or 'QUOTE_INVALID'
                    if reason is None:
                        reason = index.continuity(listing, start, end, decision)
                    if reason is None and any(row['event_type'] == 'CORPORATE_ACTION' and _crosses_action(row, start, end) for row in events):
                        reason = 'CORPORATE_ACTION_WINDOW'
                    if reason:
                        excluded[reason] += 1
                        status_exclusions[reason] += 1
                    else:
                        usable += 1
                coverage = usable / planned if planned else 0
                grid.append({'listing_id': listing, 'session_date': calendar['session_date'], 'minutes': minutes,
                             'planned': planned, 'usable': usable, 'coverage': coverage, 'exclusions': dict(sorted(excluded.items()))})
                if not planned or not usable or coverage < policy.usable_grid_min:
                    reasons.add('GRID_INSUFFICIENT')
    if len(sessions) < policy.min_sessions or eligible_sessions != len(sessions):
        reasons.add('SESSIONS_INSUFFICIENT')
    raw_coverage = raw_valid / raw_planned if raw_planned else 0
    if not raw_planned or raw_coverage < policy.raw_coverage_min:
        reasons.add('RAW_COVERAGE_INSUFFICIENT')
    if not compatible:
        reasons.add('NAMESPACE_NON_IDONEO')
    technical_reasons = reasons - {'NAMESPACE_NON_IDONEO'}
    halts = defaultdict(list)
    if row_factory is not None:
        index = _Index(rows)
    for row in select_versions(index.family['STATUS'], family='STATUS', cutoff_ns=manifest['cutoff_ns']):
        if (row['listing_id'] in listings and manifest['start_at_ns'] <= row['event_time_ns'] < manifest['end_at_ns'] and
                row['payload'].get('state') == 'HALTED'):
            halts[row['listing_id'], _day(row['event_time_ns']).isoformat()].append(row)
    known_halts = [{'listing_id': listing, 'session_date': day, 'occurrences': len(values),
                    'source': 'STATUS', 'carried_in': False,
                    'first_event_at_ns': min(row['event_time_ns'] for row in values),
                    'last_event_at_ns': max(row['event_time_ns'] for row in values),
                    'first_version_id': values[0]['id'], 'first_hash': values[0]['payload_hash']}
                   for (listing, day), values in sorted(halts.items())]
    carried = []
    for calendar, _ in sessions:
        if row_factory is not None:
            index = _Index(row_factory(calendar))
        opening = calendar['open_at_ns']
        checkpoints = defaultdict(list)
        for row in index.event_versions(opening - 1):
            if (row['listing_id'] in listings and row['payload'].get('version') == 'utp-status-checkpoint-v1'
                    and row['effective_at_ns'] <= opening):
                checkpoints[row['listing_id']].append(row)
        for listing, values in sorted(checkpoints.items()):
            row = max(values, key=lambda item: (item['effective_at_ns'], item['available_at_ns'], item['id']))
            status = select_versions(index.status[row['capture_id']], family='STATUS', cutoff_ns=opening - 1,
                                     listing_ids=(listing,))
            if status_state_from_rows(row, status, cutoff_ns=opening) == 'HALTED':
                carried.append({'listing_id': listing, 'session_date': calendar['session_date'], 'occurrences': 1,
                    'source': 'CHECKPOINT_AND_STATUS' if status else 'CHECKPOINT', 'carried_in': True,
                    'status_refs': [{'id': item['id'], 'hash': item['payload_hash']} for item in status],
                    'first_event_at_ns': row['effective_at_ns'],
                    'last_event_at_ns': row['effective_at_ns'], 'first_version_id': row['id'],
                    'first_hash': row['payload_hash'], 'expires_at_ns': row['payload']['expires_at_ns']})
    known_halts = [*carried, *known_halts]
    return {'version': 'intraday-quality-report-v1', 'outcome': 'NON_IDONEO' if not compatible else
            'INSUFFICIENTE' if reasons else 'READY', 'g1_tech': 'NOT_EVALUATED',
            'technical_result': 'INSUFFICIENTE' if technical_reasons else 'READY', 'reasons': sorted(reasons),
            'metrics': {'sessions': len(sessions), 'eligible_sessions': eligible_sessions,
                        'planned_listings': len(listings), 'benchmarks': manifest['benchmarks'],
                        'raw': {'planned': raw_planned, 'valid': raw_valid, 'coverage': raw_coverage}, 'grid': grid,
                        'listing_exclusions': ineligible, 'point_exclusions': dict(sorted(status_exclusions.items())),
                        'known_halts': known_halts,
                        'quote_age': _percentiles(ages), 'bar_delay': _percentiles(delays)},
            'limits': {'policy_id': policy.version, 'policy_hash': policy.policy_hash,
                       'news_coverage': 'DURABLE_BARRIERS_ONLY', 'event_calendars': 'ANNOUNCED_EVENTS_ONLY',
                       'source_authenticity': 'LOCAL_ATTESTATION', 'size_conversion': 'NOT_ATTESTED',
                       'profitability': 'NOT_EVALUATED', 'release_evidence': 'SEPARATE_BUNDLE'}}
