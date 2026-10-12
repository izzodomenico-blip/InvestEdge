"""Alpaca data-only WebSocket boundary; no connection at import or construction.

Official control messages are singleton arrays; subscriptions are full snapshots.
Never retain auth or opaque server error text. Socket logging is private/disabled.
"""
from __future__ import annotations

import json
import logging
import math
import re
import socket
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field

from backend.app.data_providers.alpaca_news import NewsRights, decode_news_row
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.intraday.contracts import canonical_json

_CHANNELS = {'b': ('BAR', 'bars'), 'u': ('BAR', 'updatedBars'), 'q': ('QUOTE', 'quotes'),
             's': ('STATUS', 'statuses'), 'l': ('LULD', 'lulds'), 'n': ('NEWS', 'news')}
_SUBSCRIPTIONS = frozenset(('bars', 'updatedBars', 'quotes', 'statuses', 'lulds', 'news',
                            'trades', 'dailyBars', 'corrections', 'cancelErrors'))
_CODES = frozenset(('FRAME_INVALID', 'FRAME_LIMIT', 'QUEUE_OVERFLOW', 'SECRET_ECHO', 'CHANNEL_INVALID',
    'STREAM_FAILED', 'AUTHENTICATION_FAILED', 'SYMBOL_LIMIT', 'CONNECTION_LIMIT', 'FEED_NOT_ENTITLED',
    'REAL_DATA_DISABLED', 'PROFILE_INVALID', 'BUDGET_UNATTESTED', 'MISSING_CREDENTIAL', 'LEASE_LOST',
    'COLLECTOR_ALREADY_OWNED', 'IDENTITY_UNVERIFIED', 'CALENDAR_MISSING', 'SOCKET_SILENCE',
    'CLOCK_SKEW', 'ARCHIVE_LIMIT', 'ACK_INCOMPLETE', 'HANDSHAKE_TIMEOUT', 'RESTART', 'STOPPED',
    'BUDGET_EXHAUSTED', 'RATE_LIMITED', 'CAPTURE_GAP', 'STATUS_BOOTSTRAP_UNAVAILABLE'))


class StreamError(ValueError):
    def __init__(self, code, *, retry_after_seconds=1):
        self.code = self.reason_code = code if code in _CODES else 'STREAM_FAILED'
        self.retry_after_seconds = retry_after_seconds
        super().__init__(self.code)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise StreamError('FRAME_INVALID')
        result[key] = value
    return result


def decode_frame(frame, *, channel, max_bytes, max_events, secrets, rights=None):
    """Reject secrets on original and decoded input, then emit bounded whitelist rows."""
    try:
        if channel not in {'market', 'news'} or type(frame) not in {str, bytes}:
            raise StreamError('FRAME_INVALID')
        raw = frame.encode('utf-8') if isinstance(frame, str) else frame
        if len(raw) > max_bytes or max_bytes <= 0:
            raise StreamError('FRAME_LIMIT')
        text = raw.decode('utf-8')
        if any(value and value in text for value in secrets):
            raise StreamError('SECRET_ECHO')
        values = json.loads(text, object_pairs_hook=_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(StreamError('FRAME_INVALID')))
        if SafeProviderTransport._payload_contains_secret(values, secrets):
            raise StreamError('SECRET_ECHO')
        if type(values) is not list or not values or any(type(row) is not dict for row in values):
            raise StreamError('FRAME_INVALID')
        if len(values) > max_events:
            raise StreamError('QUEUE_OVERFLOW')
        result = []
        for row in values:
            canonical_json(row)
            wire = row.get('T')
            if wire == 'auth':
                raise StreamError('FRAME_INVALID')
            if wire in {'success', 'subscription', 'error'}:
                if len(values) != 1:
                    raise StreamError('FRAME_INVALID')
                if wire == 'success':
                    kind = {'connected': 'CONNECTED', 'authenticated': 'AUTHENTICATED'}.get(row.get('msg'))
                    if kind is None:
                        raise StreamError('FRAME_INVALID')
                    result.append({'kind': kind})
                elif wire == 'error':
                    code = row.get('code')
                    if type(code) is not int:
                        raise StreamError('FRAME_INVALID')
                    reason = {401: 'AUTHENTICATION_FAILED', 402: 'AUTHENTICATION_FAILED',
                        404: 'AUTHENTICATION_FAILED', 405: 'SYMBOL_LIMIT', 406: 'CONNECTION_LIMIT',
                        407: 'QUEUE_OVERFLOW', 409: 'FEED_NOT_ENTITLED', 410: 'CHANNEL_INVALID'}.get(code, 'STREAM_FAILED')
                    result.append({'kind': 'ERROR', 'reason_code': reason})
                else:
                    subscriptions = {}
                    if set(row) - _SUBSCRIPTIONS - {'T'}:
                        raise StreamError('FRAME_INVALID')
                    for key in _SUBSCRIPTIONS & set(row):
                        symbols = row[key]
                        if (type(symbols) is not list or len(symbols) > 10_000 or
                            any(type(symbol) is not str or re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,31}', symbol) is None
                                for symbol in symbols) or len(set(symbols)) != len(symbols)):
                            raise StreamError('FRAME_INVALID')
                        subscriptions[key] = sorted(symbols)
                    result.append({'kind': 'ACK', 'subscriptions': subscriptions})
            else:
                if wire not in _CHANNELS:
                    raise StreamError('CHANNEL_INVALID')
                kind, name = _CHANNELS[wire]
                if (channel == 'news') != (kind == 'NEWS'):
                    raise StreamError('CHANNEL_INVALID')
                if kind == 'NEWS':
                    policy = rights or NewsRights()
                    payload = decode_news_row(row, source='STREAM', rights=policy)
                    selected = {key: row[key] for key in ('T', 'id', 'source', 'headline', 'symbols',
                        'created_at', 'updated_at', 'author') if key in row}
                    if payload['url'] is not None:
                        selected['url'] = payload['url']
                    for key, allowed in (('summary', policy.allow_summary), ('content', policy.allow_content)):
                        if allowed and payload[key] is not None:
                            selected[key] = payload[key]
                else:
                    if type(row.get('S')) is not str or re.fullmatch(r'[A-Z0-9][A-Z0-9.-]{0,31}', row['S']) is None:
                        raise StreamError('FRAME_INVALID')
                    fields = {'BAR': ('S','t','o','h','l','c','v','vw','n'),
                        'QUOTE': ('S','t','bp','ap','bs','as','bx','ax','c','z'),
                        'STATUS': ('T','S','t','sc','sm','rc','rm','z'),
                        'LULD': ('T','S','t','u','d','i','z')}[kind]
                    selected = {key: row[key] for key in fields if key in row}
                result.append({'kind': kind, 'channel': name, 'row': selected})
        return tuple(result)
    except StreamError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        raise StreamError('FRAME_INVALID') from None


@dataclass(frozen=True)
class ReceivedFrame:
    data: str | bytes = field(repr=False)
    received_at_ns: int


def capture_connection_class(*, received_clock_ns, max_messages, write_timeout=2):
    """Pinned 17.2 hook: timestamp before assembler queue; deadline every write.

    A bounded watchdog closes a stalled socket, unblocking both sendall and recv;
    it doesn't change the socket timeout shared by the receiving thread.
    """
    from websockets.frames import Frame, Opcode
    from websockets.sync.client import ClientConnection

    class CaptureConnection(ClientConnection):
        def __init__(self, *args, **kwargs):
            self._capture_times = deque()
            self._capture_mutex = threading.Lock()
            self._capture_partial, self._capture_error = False, False
            super().__init__(*args, **kwargs)

        def process_event(self, event):
            if isinstance(event, Frame) and event.opcode in {Opcode.TEXT, Opcode.BINARY, Opcode.CONT}:
                stamp = received_clock_ns()
                with self._capture_mutex:
                    self._capture_partial = not event.fin
                    if event.fin:
                        if type(stamp) is not int or not 0 <= stamp <= 2**63 - 1 or len(self._capture_times) >= max_messages:
                            self._capture_error = True
                            raise StreamError('QUEUE_OVERFLOW')
                        self._capture_times.append(stamp)
            super().process_event(event)

        def recv(self, timeout=None, decode=None):
            data = super().recv(timeout=timeout, decode=decode)
            with self._capture_mutex:
                if self._capture_error or not self._capture_times:
                    raise StreamError('FRAME_INVALID')
                return ReceivedFrame(data, self._capture_times.popleft())

        def has_pending(self):
            with self._capture_mutex:
                return bool(self._capture_times) or self._capture_partial or self._capture_error

        def send_data(self):
            assert self.protocol_mutex.locked()
            for data in self.protocol.data_to_send():
                if data:
                    def shutdown():
                        with suppress(OSError):
                            self.socket.shutdown(socket.SHUT_RDWR)
                    timer = threading.Timer(write_timeout, shutdown)
                    timer.daemon = True
                    timer.start()
                    try:
                        if self.close_deadline is not None:
                            self.socket.settimeout(self.close_deadline.timeout())
                        self.socket.sendall(data)
                    finally:
                        timer.cancel()
                        timer.join(timeout=write_timeout)
                else:
                    with suppress(OSError):
                        self.socket.shutdown(socket.SHUT_WR)

    return CaptureConnection


def _dial(url, **kwargs):
    from websockets.sync.client import reconnect

    class NoRedirect(reconnect):
        def process_redirect(self, exc):
            return exc  # Every redirect, including same-host/path, is rejected.

    connection = NoRedirect(url, **kwargs).connect()  # One physical attempt; never iterate reconnect.
    connection.pending_legacy_warning = False
    return connection


def open_socket(*, channel, feed, max_size, max_queue, open_timeout, close_timeout,
                received_clock_ns=time.time_ns):
    """One physical attempt. Retry/leases/account budgets belong to Collector."""
    if channel not in {'market', 'news'} or feed not in {'iex', 'sip'}:
        raise StreamError('CHANNEL_INVALID')
    from websockets.exceptions import InvalidStatus
    logger = logging.Logger('investedge.alpaca.private')
    logger.disabled, logger.propagate = True, False
    url = 'wss://stream.data.alpaca.markets/' + ('v1beta1/news' if channel == 'news' else f'v2/{feed}')
    try:
        return _dial(url, proxy=None, compression=None, logger=logger,
                       create_connection=capture_connection_class(received_clock_ns=received_clock_ns,
                                                                  max_messages=max_queue),
                       max_size=max_size, max_queue=max_queue, open_timeout=open_timeout,
                       close_timeout=close_timeout, ping_interval=None, ping_timeout=None)
    except InvalidStatus as exc:
        code = exc.response.status_code
        reason = {401: 'AUTHENTICATION_FAILED', 403: 'FEED_NOT_ENTITLED', 429: 'RATE_LIMITED'}.get(code, 'STREAM_FAILED')
        retry = 1
        if code == 429:
            with suppress(ValueError, TypeError, OverflowError, LookupError):
                value = float(exc.response.headers.get('Retry-After', '1'))
                if math.isfinite(value):
                    retry = max(1, min(60, value))
        raise StreamError(reason, retry_after_seconds=retry) from None
    except Exception:
        raise StreamError('STREAM_FAILED') from None
