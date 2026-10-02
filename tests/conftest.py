from __future__ import annotations

import gc
import shutil
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ambiente comune dei test API: dati reali, news reali, alert e import disattivati,
# nessuna chiave provider. Il template seed e la fixture `client` usano lo stesso.
CLIENT_ENV: dict[str, str] = {
    "ENABLE_REAL_DATA": "false",
    "ALPHA_VANTAGE_API_KEY": "",
    "COINGECKO_API_KEY": "",
    "FRED_API_KEY": "",
    "FINNHUB_API_KEY": "",
    "OPENFIGI_API_KEY": "",
    "ENABLE_REAL_NEWS": "false",
    "NEWS_DAILY_LIMIT": "20",
    "NEWS_CACHE_TTL_HOURS": "6",
    "NEWS_SENTIMENT_WEIGHT": "5",
    "ENABLE_ALERTS": "false",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "ENABLE_GOOGLE_SHEETS_IMPORT": "false",
    "GOOGLE_SHEETS_CSV_URL": "",
}

NETWORK_BLOCKED_MESSAGE = "NETWORK_BLOCKED_IN_TESTS"
# Il loopback resta ammesso: su Windows l'event loop asyncio di TestClient crea una
# socketpair su 127.0.0.1. Qualsiasi altro host e' bloccato.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_original_create_connection = socket.create_connection
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo


def _is_loopback(host: object) -> bool:
    return isinstance(host, str) and host in _LOOPBACK_HOSTS


def _guarded_create_connection(address, *args, **kwargs):
    if _is_loopback(address[0]):
        return _original_create_connection(address, *args, **kwargs)
    raise RuntimeError(NETWORK_BLOCKED_MESSAGE)


def _guarded_connect(self, address):
    if isinstance(address, tuple) and _is_loopback(address[0]):
        return _original_connect(self, address)
    raise RuntimeError(NETWORK_BLOCKED_MESSAGE)


def _guarded_connect_ex(self, address):
    if isinstance(address, tuple) and _is_loopback(address[0]):
        return _original_connect_ex(self, address)
    raise RuntimeError(NETWORK_BLOCKED_MESSAGE)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host is None or _is_loopback(host):
        return _original_getaddrinfo(host, *args, **kwargs)
    raise RuntimeError(NETWORK_BLOCKED_MESSAGE)


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nessun test puo' aprire connessioni di rete: i provider usano solo fixture locali."""
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)


def _apply_client_env(monkeypatch: pytest.MonkeyPatch, database_path: Path) -> None:
    from backend.app.config import get_settings

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(database_path))
    for name, value in CLIENT_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def seeded_db_template(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Database seed creato una sola volta per sessione e copiato da ogni test API."""
    from backend.app.config import get_settings

    template = tmp_path_factory.mktemp("seed-template") / "investedge.db"
    with pytest.MonkeyPatch.context() as monkeypatch:
        _apply_client_env(monkeypatch, template)

        from backend.scripts.seed_database import seed_database

        seed_database(reset=True)

        from backend.app.database import db_session

        with db_session() as connection:
            connection.execute(
                """
                INSERT INTO fx_rates (
                    from_currency, to_currency, rate, observed_at, provider, quality
                )
                VALUES ('USD', 'EUR', 0.92, date('now'), 'test', 'reference')
                """
            )
    # init_db e il seed lasciano connessioni gia' committate ma non chiuse: le si
    # raccoglie prima delle copie per non tenere handle aperti sul template (Windows).
    gc.collect()
    get_settings.cache_clear()
    yield template


@pytest.fixture()
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db_template: Path,
) -> Iterator[TestClient]:
    from backend.app.config import get_settings

    database_path = tmp_path / "investedge.db"
    shutil.copyfile(seeded_db_template, database_path)
    _apply_client_env(monkeypatch, database_path)

    from backend.app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()
