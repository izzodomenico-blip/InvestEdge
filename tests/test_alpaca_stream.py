from __future__ import annotations

import importlib
import json
import logging
import uuid
from types import SimpleNamespace

import pytest


def api():
    return importlib.import_module('backend.app.data_providers.alpaca_stream')


def decode(rows, **changes):
    return api().decode_frame(json.dumps(rows), channel='market', max_bytes=4096,
                              max_events=10, secrets=(), **changes)


def test_control_frames_are_sanitized_and_subscription_is_full_snapshot():
    assert decode([{'T': 'success', 'msg': 'connected'}])[0] == {'kind': 'CONNECTED'}
    assert decode([{'T': 'success', 'msg': 'authenticated'}])[0] == {'kind': 'AUTHENTICATED'}
    row = decode([{'T': 'subscription', 'bars': ['AAPL'], 'quotes': ['AAPL'], 'updatedBars': ['AAPL'],
                   'statuses': ['AAPL'], 'lulds': ['AAPL'], 'trades': []}])[0]
    assert row['kind'] == 'ACK' and row['subscriptions']['updatedBars'] == ['AAPL']
    assert 'msg' not in row


@pytest.mark.parametrize('code,reason', [(401, 'AUTHENTICATION_FAILED'), (402, 'AUTHENTICATION_FAILED'),
    (404, 'AUTHENTICATION_FAILED'), (405, 'SYMBOL_LIMIT'), (406, 'CONNECTION_LIMIT'),
    (407, 'QUEUE_OVERFLOW'), (409, 'FEED_NOT_ENTITLED'), (410, 'CHANNEL_INVALID'),
    (500, 'STREAM_FAILED'), (999, 'STREAM_FAILED')])
def test_error_text_never_escapes(code, reason):
    assert decode([{'T': 'error', 'code': code, 'msg': 'opaque server text'}]) == (
        {'kind': 'ERROR', 'reason_code': reason},)


@pytest.mark.parametrize('escaped', [False, True])
def test_both_credentials_rejected_in_error_echo_and_omitted_fields(escaped, caplog):
    values = (uuid.uuid4().hex, uuid.uuid4().hex)
    for secret in values:
        frame = json.dumps([{'T': 'error', 'code': 500, 'msg': secret}])
        if escaped:
            frame = frame.replace(secret, ''.join(f'\\u{ord(c):04x}' for c in secret))
        with pytest.raises(ValueError, match='SECRET_ECHO') as exc:
            api().decode_frame(frame, channel='market', max_bytes=4096, max_events=10, secrets=values)
        assert all(value not in str(exc.value) + caplog.text for value in values)


@pytest.mark.parametrize('frame', ['{}', '[]', '[{"T":"auth","key":"discarded"}]',
    '[{"T":"success","msg":"connected","T":"success"}]', '[{"T":"q","bp":NaN}]',
    '[{"T":"success","msg":"connected"},{"T":"success","msg":"authenticated"}]'])
def test_malformed_or_mixed_control_frames_fail_closed(frame):
    with pytest.raises(ValueError, match='FRAME_INVALID'):
        api().decode_frame(frame, channel='market', max_bytes=4096, max_events=10, secrets=())


def test_frame_and_batch_caps_are_hard_limits():
    with pytest.raises(ValueError, match='FRAME_LIMIT'):
        api().decode_frame(' ' * 4097, channel='market', max_bytes=4096, max_events=10, secrets=())
    with pytest.raises(ValueError, match='QUEUE_OVERFLOW'):
        api().decode_frame(json.dumps([{'T': 'q'}] * 11), channel='market', max_bytes=4096,
                           max_events=10, secrets=())


def test_bar_and_updated_bar_have_same_economic_kind_distinct_channel():
    raw = {'S': 'AAPL', 't': '2026-10-12T13:30:00.000000001Z', 'o': 100,
           'h': 101, 'l': 99, 'c': 100, 'v': 10}
    rows = decode([{'T': 'b', **raw}, {'T': 'u', **raw}])
    assert [row['kind'] for row in rows] == ['BAR', 'BAR']
    assert [row['channel'] for row in rows] == ['bars', 'updatedBars']
    assert rows[0]['row']['t'] == raw['t']


@pytest.mark.parametrize('wire', ['t', 'c', 'x', 'd'])
def test_trades_corrections_cancels_and_daily_are_not_supported(wire):
    with pytest.raises(ValueError, match='CHANNEL_INVALID'):
        decode([{'T': wire, 'S': 'AAPL'}])


def test_real_factory_only_uses_fixed_data_url_and_bounded_private_logger(monkeypatch):
    captured = []
    def connect(url, **kwargs):
        captured.append((url, kwargs))
        return object()
    monkeypatch.setattr(api(), '_dial', connect)
    api().open_socket(channel='market', feed='sip', max_size=4096, max_queue=5,
                      open_timeout=3, close_timeout=2)
    url, options = captured[0]
    assert url == 'wss://stream.data.alpaca.markets/v2/sip'
    assert options['compression'] is None and options['proxy'] is None
    assert options['max_size'] == 4096 and options['max_queue'] == 5
    assert options['logger'].disabled and not options['logger'].propagate
    assert options['logger'].isEnabledFor(logging.DEBUG) is False
    assert isinstance(options['create_connection'], type)
    with pytest.raises(ValueError, match='CHANNEL_INVALID'):
        api().open_socket(channel='orders', feed='sip', max_size=4096, max_queue=5,
                          open_timeout=3, close_timeout=2)
    assert len(captured) == 1


def test_real_factory_external_exception_is_static(monkeypatch):
    marker = uuid.uuid4().hex
    def fail(*args, **kwargs):
        raise RuntimeError(marker)
    monkeypatch.setattr(api(), '_dial', fail)
    with pytest.raises(ValueError, match='STREAM_FAILED') as exc:
        api().open_socket(channel='news', feed='sip', max_size=4096, max_queue=5,
                          open_timeout=3, close_timeout=2)
    assert marker not in str(exc.value) and exc.value.__cause__ is None


def test_real_factory_rejects_redirect_before_any_foreign_physical_attempt(monkeypatch):
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    from websockets.sync.client import reconnect
    attempts = []
    def opened(connector, deadline):
        attempts.append(connector.uri)
        if len(attempts) == 1:
            raise InvalidStatus(Response(302, 'Found', Headers({'Location': 'wss://untrusted.example/arbitrary'})))
        return SimpleNamespace(start_keepalive=lambda: None)
    monkeypatch.setattr(reconnect, 'open_connection', opened)
    with pytest.raises(ValueError, match='STREAM_FAILED'):
        api().open_socket(channel='market', feed='sip', max_size=4096, max_queue=5,
                          open_timeout=3, close_timeout=2)
    assert attempts == ['wss://stream.data.alpaca.markets/v2/sip']


@pytest.mark.parametrize('http,reason', [(401, 'AUTHENTICATION_FAILED'), (403, 'FEED_NOT_ENTITLED'),
                                       (429, 'RATE_LIMITED')])
def test_http_handshake_failures_keep_static_nonretry_policy(monkeypatch, http, reason):
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    from websockets.sync.client import reconnect
    def opened(connector, deadline):
        raise InvalidStatus(Response(http, 'private', Headers({'Retry-After': '5'})))
    monkeypatch.setattr(reconnect, 'open_connection', opened)
    with pytest.raises(ValueError, match=reason):
        api().open_socket(channel='market', feed='sip', max_size=4096, max_queue=5,
                          open_timeout=3, close_timeout=2)


def test_real_receive_clock_is_captured_before_internal_queue(monkeypatch):
    from websockets.client import ClientProtocol
    from websockets.frames import Frame, Opcode
    from websockets.uri import parse_uri
    monkeypatch.setattr('threading.Thread.start', lambda self: None)
    stamp = [100]
    cls = api().capture_connection_class(received_clock_ns=lambda: stamp[0], max_messages=2)
    connection = cls(object(), ClientProtocol(parse_uri('wss://stream.data.alpaca.markets/v2/sip')))
    connection.pending_legacy_warning = False
    connection.response = object()
    connection.process_event(Frame(Opcode.TEXT, b'[]'))
    stamp[0] = 900
    value = connection.recv(timeout=0)
    assert value.data == '[]' and value.received_at_ns == 100


def test_real_socket_write_has_deadline_even_when_peer_stalls(monkeypatch):
    import threading

    from websockets.client import ClientProtocol
    from websockets.uri import parse_uri
    original_start = threading.Thread.start
    monkeypatch.setattr(threading.Thread, 'start', lambda self: None)
    class Peer:
        def __init__(self):
            self.closed = threading.Event()
        def sendall(self, value):
            assert self.closed.wait(0.5), 'Write remained unbounded'
            raise TimeoutError
        def shutdown(self, how):
            self.closed.set()
    peer = Peer()
    cls = api().capture_connection_class(received_clock_ns=lambda: 100, max_messages=2, write_timeout=0.01)
    connection = cls(peer, ClientProtocol(parse_uri('wss://stream.data.alpaca.markets/v2/sip')))
    monkeypatch.setattr(threading.Thread, 'start', original_start)
    monkeypatch.setattr(connection.protocol, 'data_to_send', lambda: [b'bounded'])
    with connection.protocol_mutex, pytest.raises(TimeoutError):
        connection.send_data()
    assert peer.closed.is_set()


def test_duplicate_retry_after_header_still_creates_static_rate_limit(monkeypatch):
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    from websockets.sync.client import reconnect
    def opened(connector, deadline):
        raise InvalidStatus(Response(429, 'private', Headers([('Retry-After', '5'), ('Retry-After', '7')])))
    monkeypatch.setattr(reconnect, 'open_connection', opened)
    with pytest.raises(ValueError, match='RATE_LIMITED'):
        api().open_socket(channel='market', feed='sip', max_size=4096, max_queue=5,
                          open_timeout=3, close_timeout=2)
