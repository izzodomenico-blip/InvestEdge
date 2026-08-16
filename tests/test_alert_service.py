from __future__ import annotations

import runpy
import traceback
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services import alert_service
from scripts import send_daily_alert


@contextmanager
def _db_session():
    yield object()


def _assert_sanitized(text: str, token: str) -> None:
    if token in text or "https://" in text or "?" in text:
        pytest.fail("Il messaggio contiene dettagli sensibili della richiesta.")


def _assert_no_exception_chain(error: BaseException) -> None:
    if error.__cause__ is not None or error.__context__ is not None:
        pytest.fail("L'errore pubblico conserva una catena di eccezioni non sanitizzata.")


def test_send_telegram_sanitizes_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "SENTINEL_SECRET_TOKEN"
    monkeypatch.setattr(
        alert_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token=token, telegram_chat_id="123"),
    )
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=401, request=request)

        return real_client(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(alert_service.httpx, "Client", client_factory)

    with pytest.raises(RuntimeError) as exc_info:
        alert_service.send_test_message()

    message = str(exc_info.value)
    _assert_sanitized(message, token)
    formatted_traceback = "".join(
        traceback.format_exception(type(exc_info.value), exc_info.value, exc_info.value.__traceback__)
    )
    _assert_sanitized(formatted_traceback, token)
    _assert_no_exception_chain(exc_info.value)


def test_send_telegram_sanitizes_rejected_response(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "SENTINEL_SECRET_TOKEN"
    monkeypatch.setattr(
        alert_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token=token, telegram_chat_id="123"),
    )
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                request=request,
                json={"ok": False, "description": f"rejected at https://example.test/?token={token}"},
            )

        return real_client(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(alert_service.httpx, "Client", client_factory)

    with pytest.raises(RuntimeError) as exc_info:
        alert_service.send_test_message()

    _assert_sanitized(str(exc_info.value), token)


def test_send_telegram_sanitizes_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "SENTINEL_SECRET_TOKEN"
    monkeypatch.setattr(
        alert_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token=token, telegram_chat_id="123"),
    )
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                request=request,
                headers={"content-type": "application/json"},
                content=f"invalid response containing {token}".encode(),
            )

        return real_client(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(alert_service.httpx, "Client", client_factory)

    with pytest.raises(RuntimeError) as exc_info:
        alert_service.send_test_message()

    _assert_sanitized(str(exc_info.value), token)
    _assert_no_exception_chain(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"ok": True},
        {"ok": True, "result": {}},
        {"ok": True, "result": {"message_id": "https://example.test/?secret=hidden"}},
    ],
)
def test_send_telegram_rejects_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    token = "SENTINEL_SECRET_TOKEN"
    monkeypatch.setattr(
        alert_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token=token, telegram_chat_id="123"),
    )
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=200, request=request, json=payload)

        return real_client(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(alert_service.httpx, "Client", client_factory)

    with pytest.raises(RuntimeError) as exc_info:
        alert_service.send_test_message()

    _assert_sanitized(str(exc_info.value), token)


@pytest.mark.parametrize(
    "error",
    [
        send_daily_alert.AlertNotConfigured("Telegram non configurato."),
        RuntimeError("request failed at https://provider.example/path?secret=hidden"),
    ],
)
def test_main_returns_failure_for_send_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    monkeypatch.setattr(send_daily_alert, "get_settings", lambda: SimpleNamespace(enable_alerts=True))
    monkeypatch.setattr(send_daily_alert, "_refresh_prices", lambda: None)
    monkeypatch.setattr(send_daily_alert, "db_session", _db_session)

    def fail_send(connection):
        raise error

    monkeypatch.setattr(send_daily_alert, "send_today_alert", fail_send)

    assert send_daily_alert.main() == 1
    output = capsys.readouterr().out
    assert "https://" not in output
    assert "?secret=" not in output


def test_main_returns_success_when_alerts_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(send_daily_alert, "get_settings", lambda: SimpleNamespace(enable_alerts=False))

    assert send_daily_alert.main() == 0


def test_main_returns_success_after_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(send_daily_alert, "get_settings", lambda: SimpleNamespace(enable_alerts=True))
    monkeypatch.setattr(send_daily_alert, "_refresh_prices", lambda: None)
    monkeypatch.setattr(send_daily_alert, "db_session", _db_session)
    monkeypatch.setattr(
        send_daily_alert,
        "send_today_alert",
        lambda connection: {"message_id": 42, "actions_sent": 3},
    )

    assert send_daily_alert.main() == 0


def test_main_sanitizes_settings_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_settings():
        raise RuntimeError("private configuration details")

    monkeypatch.setattr(send_daily_alert, "get_settings", fail_settings)

    assert send_daily_alert.main() == 1
    assert "private configuration details" not in capsys.readouterr().out


def test_script_entrypoint_uses_main_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(enable_alerts=False))
    script_path = Path(send_daily_alert.__file__)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(script_path), run_name="__main__")

    assert exc_info.value.code == 0


def test_refresh_prices_logs_a_sanitized_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(send_daily_alert, "get_settings", lambda: SimpleNamespace(enable_real_data=True))
    monkeypatch.setattr(send_daily_alert, "db_session", _db_session)

    class FailingMarketDataService:
        def refresh_all_watchlist(self, connection, *, limit, force):
            raise RuntimeError("request failed at https://provider.example/path?api_key=hidden")

    monkeypatch.setattr(send_daily_alert, "MarketDataService", FailingMarketDataService)

    send_daily_alert._refresh_prices()

    output = capsys.readouterr().out
    assert "Refresh prezzi fallito" in output
    assert "https://" not in output
    assert "?api_key=" not in output


def test_refresh_prices_handles_settings_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_settings():
        raise RuntimeError("private configuration details")

    monkeypatch.setattr(send_daily_alert, "get_settings", fail_settings)

    send_daily_alert._refresh_prices()

    output = capsys.readouterr().out
    assert "Refresh prezzi fallito" in output
    assert "private configuration details" not in output


def test_format_board_escapes_dynamic_html_fields() -> None:
    board = {
        "data_mode": "REAL",
        "headline": "Mercato <incerto> & volatile",
        "actions": [
            {
                "type": "BUY",
                "symbol": "A<&B>",
                "title": "Compra <ora> & valuta",
                "reason": "Score > 50 & rischio < medio",
            }
        ],
    }

    message = alert_service._format_board(board)

    assert "<b>InvestEdge - Cosa fare oggi</b>" in message
    assert "Mercato &lt;incerto&gt; &amp; volatile" in message
    assert "<b>A&lt;&amp;B&gt;</b>" in message
    assert "Compra &lt;ora&gt; &amp; valuta" in message
    assert "<i>Score &gt; 50 &amp; rischio &lt; medio</i>" in message
