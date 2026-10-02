from __future__ import annotations

import socket

import httpx
import pytest


def test_network_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="NETWORK_BLOCKED_IN_TESTS"):
        socket.create_connection(("example.com", 443), timeout=1)


def test_loopback_socketpair_is_allowed() -> None:
    # Su Windows l'event loop asyncio (TestClient) usa una socketpair sul loopback.
    left, right = socket.socketpair()
    try:
        left.sendall(b"ok")
        assert right.recv(2) == b"ok"
    finally:
        left.close()
        right.close()


def test_httpx_real_transport_is_blocked() -> None:
    with pytest.raises(Exception) as error:
        httpx.get("https://example.com", timeout=1)
    assert "NETWORK_BLOCKED_IN_TESTS" in repr(error.value) or "NETWORK_BLOCKED_IN_TESTS" in repr(
        error.value.__cause__
    )


def test_seeded_template_is_copied_per_test(client, seeded_db_template) -> None:
    from backend.app.config import get_settings

    assert get_settings().database_path != seeded_db_template
    assert get_settings().database_path.exists()
