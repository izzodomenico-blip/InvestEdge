"""Bounded official event decoders. No network bootstrap or trading activation.

Contracts: Alpaca corporateactions-1 / real-time-stock-pricing-data;
UTP Snap-Shot 4.0 (July 2026), SoupBinTCP 4.0. Unsupported frames fail closed.
"""
from __future__ import annotations

import base64
import hashlib
import math
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from backend.app.data_providers.alpaca_market import _CORPORATE_FIELDS, AlpacaProviderError, _ns
from backend.app.intraday.contracts import MAX_NS, canonical_json

SECOND = 1_000_000_000
SYMBOL = re.compile(r'[A-Z0-9][A-Z0-9.-]{0,31}')
DIGEST = re.compile(r'[a-f0-9]{64}')
DISCONTINUITIES = frozenset({'forward_splits', 'reverse_splits', 'unit_splits', 'reorganizations',
    'cash_mergers', 'stock_mergers', 'stock_and_cash_mergers', 'spin_offs', 'name_changes',
    'stock_dividends', 'worthless_removals', 'redemptions'})


class EventError(ValueError):
    def __init__(self, code):
        self.code = self.reason_code = code if code in {
            'EVENT_PAGE_INVALID', 'EVENT_ROW_INVALID', 'EVENT_CALENDAR_INVALID', 'EVENT_INPUT_MISSING',
            'EVENT_LIMIT', 'MODE_MISMATCH', 'TIMESTAMP_FUTURE', 'IDENTITY_UNVERIFIED',
            'STATUS_BOOTSTRAP_UNAVAILABLE', 'FEED_NOT_ENTITLED', 'TRANSACTION_ALREADY_OPEN',
        } else 'EVENT_INPUT_MISSING'
        super().__init__(self.code)


def day_bounds(value):
    """Economic date uncertainty: entire New York civil day, never a known time."""
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        raise ValueError
    from datetime import timedelta
    zone = ZoneInfo('America/New_York')
    start = datetime.combine(day, datetime.min.time(), zone)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), zone)
    left, right = _ns(start.astimezone(UTC).isoformat()), _ns(end.astimezone(UTC).isoformat())
    if not 0 <= left < right <= MAX_NS:
        raise ValueError
    return left, right


def decode_corporate_page(page):
    try:
        canonical_json(page)
        if ('next_page_token' not in page or type(page.get('corporate_actions')) is not dict or
                not set(page['corporate_actions']) <= set(_CORPORATE_FIELDS)):
            raise ValueError
        token = page['next_page_token']
        if token is not None and (type(token) is not str or re.fullmatch(r'[A-Za-z0-9_+/=-]{1,2048}', token) is None):
            raise ValueError
        result = []
        for family, rows in sorted(page['corporate_actions'].items()):
            if type(rows) is not list:
                raise ValueError
            for row in rows:
                if type(row) is not dict or not set(row) <= _CORPORATE_FIELDS[family]:
                    raise ValueError
                if type(row.get('id')) is not str or str(uuid.UUID(row['id'])) != row['id']:
                    raise ValueError
                symbol = row.get('old_symbol') or row.get('symbol') or row.get('source_symbol') or row.get('acquiree_symbol')
                if type(symbol) is not str or not SYMBOL.fullmatch(symbol):
                    raise ValueError
                day_bounds(row['process_date'])
                for key, value in row.items():
                    if key.endswith('_date') and value is not None:
                        day_bounds(value)
                    if (key.endswith('_rate') or key in {'rate', 'price'}) and (
                            type(value) not in {int, float} or not math.isfinite(value) or value < 0):
                        raise ValueError
                if family in {'forward_splits', 'reverse_splits', 'unit_splits'} and (
                        any(type(row.get(k)) not in {int, float} or row[k] <= 0 for k in ('old_rate', 'new_rate'))):
                    raise ValueError
                day = row.get('ex_date') or row.get('effective_date')
                start, end = day_bounds(day) if day is not None else (None, None)
                result.append({'version': 'alpaca-corporate-v1', 'event_type': 'CORPORATE_ACTION',
                    'source_event_id': row['id'], 'source_revision_id': None, 'family': family,
                    'symbol': symbol, 'raw': row, 'effective_at_ns': start, 'effective_end_ns': end,
                    'scheduled_at_ns': None, 'event_date': day, 'time_uncertainty': 'WHOLE_DAY' if day else 'UNKNOWN',
                    'discontinuity': family in DISCONTINUITIES, 'cancelled': False, 'cancellation_state': 'UNKNOWN',
                    'coverage': 'CURRENT_REST_RESEARCH', 'source': 'alpaca'})
        if len(result) > 1000:
            raise ValueError
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        raise EventError('EVENT_PAGE_INVALID') from None


class AlpacaEventsProvider:
    def __init__(self, market):
        self.market = market

    def get_page(self, *, start, end, symbols=(), limit=1000, page_token=None, bypass_cache=False):
        if type(symbols) is not tuple or type(limit) is not int or not 1 <= limit <= 1000:
            raise EventError('EVENT_PAGE_INVALID')
        params = {'start': start, 'end': end, 'limit': str(limit), 'sort': 'asc', 'region': 'us', 'data_quality': 'complete'}
        if symbols:
            if any(type(s) is not str or not SYMBOL.fullmatch(s) for s in symbols):
                raise EventError('EVENT_PAGE_INVALID')
            params['symbols'] = ','.join(symbols)
        if page_token is not None:
            params['page_token'] = page_token
        try:
            response = self.market.request_page('corporate_actions', params, bypass_cache=bypass_cache)
        except AlpacaProviderError as exc:
            if exc.code == 'INVALID_PAYLOAD':
                raise EventError('EVENT_PAGE_INVALID') from None
            raise
        if len(decode_corporate_page(response.payload)) > limit:
            raise EventError('EVENT_PAGE_INVALID')
        return response


def decode_status_row(kind, row, *, source):
    try:
        canonical_json(row)
        fields = {'T', 'S', 'sc', 'sm', 'rc', 'rm', 't', 'z'} if kind == 'STATUS' else {'T', 'S', 'u', 'd', 'i', 't', 'z'}
        if (kind not in {'STATUS', 'LULD'} or source != 'STREAM' or type(row) is not dict or
                not set(row) <= fields or row.get('T') != ('s' if kind == 'STATUS' else 'l') or
                type(row.get('S')) is not str or not SYMBOL.fullmatch(row['S']) or
                type(row.get('t')) is not str or 'T' not in row['t'] or not 0 <= _ns(row['t']) <= MAX_NS):
            raise ValueError
        tape = row.get('z')
        if tape not in {'A', 'B', 'C', 'O'}:
            raise ValueError
        state = 'UNKNOWN'
        if kind == 'STATUS':
            for key in ('sc', 'sm', 'rc', 'rm'):
                if type(row.get(key)) is not str or not row[key] or len(row[key].encode()) > 512:
                    raise ValueError
            codes = {'2': 'HALTED', '3': 'NORMAL'} if tape in {'A', 'B'} else {
                'H': 'HALTED', 'P': 'HALTED', 'Q': 'QUOTATION_ONLY', 'T': 'NORMAL'}
            state = codes.get(row['sc'], 'UNKNOWN')
        else:
            if (any(type(row.get(k)) not in {int, float} or not math.isfinite(row[k]) or row[k] <= 0 for k in ('u', 'd')) or
                    row['d'] > row['u'] or type(row.get('i')) is not str or not 1 <= len(row['i']) <= 16):
                raise ValueError
        return {'version': 'alpaca-status-v1', 'source': 'STREAM', 'raw': row, 'state': state,
                'reason_code': 'STATUS_UNKNOWN' if kind == 'STATUS' and state == 'UNKNOWN' else None}
    except (ValueError, TypeError, KeyError, OverflowError):
        raise EventError('EVENT_ROW_INVALID') from None


@dataclass(frozen=True)
class StatusAuthority:
    """External public contract/rights evidence, never credentials or self-attested payload flags."""
    source: str
    contract_version: str
    contract_sha256: str
    evidence_hash: str
    retention: str
    channel_bindings: tuple[tuple[int, str], ...]
    capture_sha256: str

    def __post_init__(self):
        if (self.source != 'UTP_SNAPSHOT' or self.contract_version != '4.0' or self.retention != 'ARCHIVE_ALLOWED' or
                not all(type(v) is str and DIGEST.fullmatch(v) for v in (self.contract_sha256, self.evidence_hash, self.capture_sha256)) or
                type(self.channel_bindings) is not tuple or len(self.channel_bindings) != 6 or
                any(type(v) is not tuple or len(v) != 2 or type(v[0]) is not int or type(v[1]) is not str or
                    re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', v[1]) is None for v in self.channel_bindings) or
                {v[0] for v in self.channel_bindings} != set(range(1, 7)) or
                len({v[1] for v in self.channel_bindings}) != 6):
            raise EventError('STATUS_BOOTSTRAP_UNAVAILABLE')

    def public(self):
        result = asdict(self)
        result['channel_bindings'] = [list(pair) for pair in self.channel_bindings]
        return result


def _snapshot_channel(raw, received):
    """Server-only Soup transcript: complete directory + current halts + terminal AS.

    SIP message production times are not the snapshot-request instant. AH action
    time may precede the current day. Scope is Nasdaq-listed production tape C.
    """
    at, login, done, sequence = 0, False, False, None
    directory, actions, restricted = {}, {}, set()
    while at < len(raw):
        if at + 3 > len(raw):
            raise ValueError
        size = int.from_bytes(raw[at:at+2], 'big')
        if size < 1 or at + 2 + size > len(raw):
            raise ValueError
        typ, payload = raw[at+2:at+3], raw[at+3:at+2+size]
        at += 2 + size
        if typ == b'A':
            if login or len(payload) != 30 or not payload[:10].strip() or payload[10:].strip() != b'1':
                raise ValueError
            login = True
        elif typ in {b'H', b'Z'}:
            if payload or not login or (typ == b'Z' and not done):
                raise ValueError
        elif typ == b'+':
            if len(payload) > 4096:
                raise ValueError
        elif typ == b'S':
            if not login or done or len(payload) < 29 or payload[0:1] != b'1' or payload[4:5] != b' ':
                raise ValueError
            cat, kind, origin = payload[1:2], payload[2:3], payload[3:4]
            if origin not in {bytes((c,)) for c in b'ABCDEFGHIJKLMNPQUVWXYZ'}:
                raise ValueError
            if any(int.from_bytes(payload[left:right], 'big') > min(received, MAX_NS) for left, right in ((5, 13), (13, 21))):
                raise ValueError
            if cat == b'A' and kind == b'B':
                if len(payload) != 90:
                    raise ValueError
                symbol = payload[29:40].decode('ascii').rstrip(' ')
                if not SYMBOL.fullmatch(symbol) or symbol in directory or payload[84:85] not in {b'Q', b'G', b'S'}:
                    raise ValueError
                directory[symbol] = payload[85:86] == b'P'
            elif cat == b'A' and kind in {b'H', b'K'}:
                if (kind == b'H' and origin != b'Q') or len(payload) != (59 if kind == b'H' else 50):
                    raise ValueError
                symbol = payload[29:40].decode('ascii').rstrip(' ')
                if not SYMBOL.fullmatch(symbol):
                    raise ValueError
                if kind == b'H':
                    if int.from_bytes(payload[45:53], 'big') > min(received, MAX_NS):
                        raise ValueError
                    if symbol in actions:
                        raise ValueError
                    actions[symbol] = {b'H': 'HALTED', b'P': 'HALTED', b'Q': 'QUOTATION_ONLY', b'T': 'NORMAL'}.get(payload[40:41], 'UNKNOWN')
                else:
                    if int.from_bytes(payload[41:49], 'big') > min(received, MAX_NS):
                        raise ValueError
                    restricted.add(symbol)  # Exchange-specific restriction never proves global trading resume.
            elif cat == b'A' and kind == b'S':
                if len(payload) != 37 or origin != b'E':
                    raise ValueError
                sequence = int.from_bytes(payload[29:37], 'big')
                if not 0 <= sequence < MAX_NS:
                    raise ValueError
                done = True
            elif cat == b'A' and kind == b'D':
                if len(payload) != 30 or origin != b'E' or payload[29:30] not in {b'1', b'2', b'3'}:
                    raise ValueError
                restricted.add('*')
            elif cat == b'A' and kind in {b'V', b'P', b'C', b'E'}:
                if (len(payload) != {b'V': 41, b'P': 65, b'C': 53, b'E': 69}[kind] or
                        origin != (b'Q' if kind in {b'V', b'E'} else b'E')):
                    raise ValueError
            elif cat == b'A' and kind == b'A':
                if len(payload) < 31 or int.from_bytes(payload[29:31], 'big') != len(payload) - 31:
                    raise ValueError
            elif cat == b'Q' and kind in {b'D', b'B'}:
                # Output 4.1: bounded status-only skip, exact optional appendage lengths.
                base = 83 if kind == b'D' else 53
                if len(payload) < base or not SYMBOL.fullmatch(payload[37:48].decode('ascii').rstrip(' ')):
                    raise ValueError
                if int.from_bytes(payload[29:37], 'big') > min(received, MAX_NS):
                    raise ValueError
                length = base
                if kind == b'D':
                    length += {48: 0, 49: 0, 52: 0, 50: 11, 51: 27}[payload[76]]
                    length += {32: 0, 48: 0, 49: 0, 50: 8}[payload[78]]
                    bolo, level, count = payload[79], payload[80], int.from_bytes(payload[81:83], 'big')
                else:
                    bolo, level, count = payload[49], payload[50], int.from_bytes(payload[51:53], 'big')
                length += {48: 0, 49: 0, 50: 10, 51: 22, 53: 30}[bolo]
                length += {48: 0, 50: 6, 51: 12, 53: 16}[level] * count
                if (level == 48 and count != 0) or len(payload) != length:
                    raise ValueError
            elif cat == b'C' and kind in {b'I', b'O', b'C', b'J', b'Z'}:
                if len(payload) != 29 or (kind in {b'I', b'J', b'Z'} and origin != b'E'):
                    raise ValueError
            else:
                raise ValueError  # Unsupported quote appendages/frames cannot certify completeness.
        else:
            raise ValueError  # In particular no client/auth frames may enter the archive.
    if not login or not done or not set(actions) <= set(directory) or not (restricted - {'*'}) <= set(directory):
        raise ValueError
    return directory, actions, restricted, sequence + 1


def decode_status_checkpoint(document, *, authority, received_at_ns):
    try:
        canonical_json(document)
        if not isinstance(authority, StatusAuthority) or document.get('version') != 'utp-snapshot-import-v1':
            raise ValueError
        if hashlib.sha256(canonical_json(document).encode()).hexdigest() != authority.capture_sha256:
            raise ValueError
        expires = document['expires_at_ns']
        if type(received_at_ns) is not int or type(expires) is not int or not 0 <= received_at_ns < expires <= received_at_ns + 300*SECOND:
            raise ValueError
        channels = document['channels']
        if type(channels) is not list or len(channels) != 6 or {c['channel'] for c in channels} != set(range(1, 7)):
            raise ValueError
        results, seen, market_wide_restriction = [], set(), False
        for item in channels:
            request, receipt = item['request_sent_at_ns'], item['received_at_ns']
            if (type(item['channel']) is not int or type(request) is not int or type(receipt) is not int or
                    not 0 <= request <= receipt <= received_at_ns or received_at_ns - request > 300*SECOND or
                    item.get('binding_id') != dict(authority.channel_bindings)[item['channel']]):
                raise ValueError
            raw = base64.b64decode(item['original_b64'], validate=True)
            if len(raw) > 524288 or hashlib.sha256(raw).hexdigest() != item['original_sha256']:
                raise ValueError
            directory, actions, restricted, next_sequence = _snapshot_channel(raw, receipt)
            market_wide_restriction |= '*' in restricted
            for symbol, production in directory.items():
                if symbol in seen:
                    raise ValueError
                seen.add(symbol)
                if not production:
                    continue  # Test/demo/deleted directory entries never initialize production status.
                state = 'UNKNOWN' if symbol in restricted or '*' in restricted else actions.get(symbol, 'NORMAL')
                results.append({'version': 'utp-status-checkpoint-v1', 'event_type': 'RESUME' if state == 'NORMAL' else 'HALT',
                    'state': state, 'symbol': symbol, 'source': 'utp', 'scope': 'NASDAQ_TAPE_C', 'channel': item['channel'],
                    'source_event_id': None, 'source_revision_id': None, 'effective_at_ns': request,
                    'scheduled_at_ns': None, 'expires_at_ns': expires, 'next_sequence': next_sequence,
                    'authority': authority.public(), 'reason_code': None if state != 'UNKNOWN' else 'STATUS_UNKNOWN',
                    'phase': 'CONNECTING', 'live_eligible': False})
        if not results:
            raise ValueError
        if market_wide_restriction:
            for result in results:
                result.update(state='UNKNOWN', event_type='HALT', reason_code='STATUS_UNKNOWN')
        return results
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        raise EventError('STATUS_BOOTSTRAP_UNAVAILABLE') from None
