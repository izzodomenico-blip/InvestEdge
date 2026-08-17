from __future__ import annotations

import traceback
from collections.abc import Callable, Iterator

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.services import google_sheets_import_service
from backend.app.services.instrument_resolution_service import InstrumentResolutionService
from backend.app.services.provider_budget_service import ProviderBudgetExceeded


@pytest.fixture(autouse=True)
def enabled_google_sheets_import(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ENABLE_GOOGLE_SHEETS_IMPORT", "true")
    monkeypatch.setenv("GOOGLE_SHEETS_IMPORT_MAX_BYTES", str(5 * 1024 * 1024))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    real_client = httpx.Client

    def client_factory(*args, **kwargs) -> httpx.Client:
        assert kwargs.get("follow_redirects") is False
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(google_sheets_import_service.httpx, "Client", client_factory)


def _streaming_text_response(request: httpx.Request, text: str) -> httpx.Response:
    return httpx.Response(
        200,
        stream=httpx.ByteStream(text.encode("utf-8")),
        request=request,
    )


def _assert_exception_chain_is_sanitized(error: BaseException, sentinel: str) -> None:
    formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert sentinel not in formatted
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.google.com/spreadsheets/d/test/export?format=csv",
        "https://localhost/sheet.csv",
        "https://127.0.0.1/sheet.csv",
        "https://10.0.0.1/sheet.csv",
        "https://user:password@docs.google.com/spreadsheets/d/test/export?format=csv",
        "https://docs.google.com.evil.test/sheet.csv",
        "https://evilgoogleusercontent.com/sheet.csv",
        "https://googleusercontent.com/sheet.csv",
        "https://.googleusercontent.com/sheet.csv",
        "https://drive.google.com:444/sheet.csv",
    ],
)
def test_fetch_csv_rejects_untrusted_urls(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _install_transport(
        monkeypatch,
        lambda request: _streaming_text_response(request, "symbol,quantity,average_price\n"),
    )

    with pytest.raises(ValueError, match="attendibile"):
        google_sheets_import_service.fetch_csv(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.google.com/spreadsheets/d/test/export?format=csv",
        "https://drive.google.com:443/uc?export=download&id=test",
        "https://lh3.googleusercontent.com/final.csv",
    ],
)
def test_fetch_csv_accepts_trusted_https_google_hosts(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    csv_text = "symbol,quantity,average_price\nAAPL,1,150\n"
    _install_transport(
        monkeypatch,
        lambda request: _streaming_text_response(request, csv_text),
    )

    result = google_sheets_import_service.fetch_csv(url)

    assert result == csv_text


def test_fetch_csv_rejects_redirect_to_untrusted_host(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://evil.test/private"}, request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match="attendibile"):
        google_sheets_import_service.fetch_csv("https://docs.google.com/spreadsheets/d/test/export?format=csv")

    assert requested_hosts == ["docs.google.com"]


def test_fetch_csv_follows_at_most_three_trusted_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path.endswith("/export"):
            return httpx.Response(302, headers={"Location": "/redirect-one"}, request=request)
        if request.url.path == "/redirect-one":
            return httpx.Response(
                307,
                headers={"Location": "https://drive.google.com/redirect-two"},
                request=request,
            )
        if request.url.path == "/redirect-two":
            return httpx.Response(
                308,
                headers={"Location": "https://lh3.googleusercontent.com/final.csv"},
                request=request,
            )
        return _streaming_text_response(request, "symbol,quantity,average_price\nAAPL,1,150\n")

    _install_transport(monkeypatch, handler)

    google_sheets_import_service.fetch_csv(
        "https://docs.google.com/spreadsheets/d/test/export?format=csv"
    )

    assert requested_urls == [
        "https://docs.google.com/spreadsheets/d/test/export?format=csv",
        "https://docs.google.com/redirect-one",
        "https://drive.google.com/redirect-two",
        "https://lh3.googleusercontent.com/final.csv",
    ]


def test_fetch_csv_rejects_a_fourth_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    requests_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests_count
        requests_count += 1
        return httpx.Response(302, headers={"Location": f"/redirect-{requests_count}"}, request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match="reindirizzamenti"):
        google_sheets_import_service.fetch_csv("https://docs.google.com/spreadsheets/d/test/export?format=csv")

    assert requests_count == 4


class _OversizedStream(httpx.SyncByteStream):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.chunks_requested = 0

    def __iter__(self) -> Iterator[bytes]:
        self.chunks_requested += 1
        yield b"x" * (self.limit + 1)
        self.chunks_requested += 1
        raise AssertionError("Il downloader ha continuato dopo avere superato il limite.")


def test_fetch_csv_stops_streaming_above_five_mib(monkeypatch: pytest.MonkeyPatch) -> None:
    max_bytes = 5 * 1024 * 1024
    stream = _OversizedStream(max_bytes)
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(200, stream=stream, request=request),
    )

    with pytest.raises(ValueError, match="5 MiB"):
        google_sheets_import_service.fetch_csv("https://docs.google.com/spreadsheets/d/test/export?format=csv")

    assert stream.chunks_requested == 1


def test_fetch_csv_keeps_five_mib_as_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    hard_cap = 5 * 1024 * 1024
    monkeypatch.setenv("GOOGLE_SHEETS_IMPORT_MAX_BYTES", str(10 * 1024 * 1024))
    get_settings.cache_clear()
    stream = _OversizedStream(hard_cap)
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(200, stream=stream, request=request),
    )

    with pytest.raises(ValueError, match="5 MiB"):
        google_sheets_import_service.fetch_csv("https://docs.google.com/spreadsheets/d/test/export?format=csv")

    assert stream.chunks_requested == 1


class _TrackedBytearray(bytearray):
    oversized_extend = False
    hard_cap = 5 * 1024 * 1024

    def extend(self, value: bytes) -> None:
        if len(self) + len(value) > self.hard_cap:
            type(self).oversized_extend = True
        super().extend(value)


def test_fetch_csv_checks_chunk_size_before_extending_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    _TrackedBytearray.oversized_extend = False
    monkeypatch.setattr(
        google_sheets_import_service,
        "bytearray",
        _TrackedBytearray,
        raising=False,
    )
    stream = _OversizedStream(5 * 1024 * 1024)
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(200, stream=stream, request=request),
    )

    with pytest.raises(ValueError, match="5 MiB"):
        google_sheets_import_service.fetch_csv("https://docs.google.com/spreadsheets/d/test/export?format=csv")

    assert _TrackedBytearray.oversized_extend is False


def test_fetch_csv_disables_and_rejects_response_compression(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_encoding: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_encoding.append(request.headers["accept-encoding"])
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"compressed payload"),
            headers={"Content-Encoding": "gzip"},
            request=request,
        )

    _install_transport(monkeypatch, handler)

    with pytest.raises(ValueError, match="compressione"):
        google_sheets_import_service.fetch_csv("https://docs.google.com/spreadsheets/d/test/export?format=csv")

    assert requested_encoding == ["identity"]


@pytest.mark.parametrize("failure", ["timeout", "http_error"])
def test_fetch_csv_sanitizes_network_errors(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    secret_url = "https://docs.google.com/spreadsheets/d/test/export?format=csv&token=SENTINEL_SECRET"

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout(f"timeout while reading {request.url}", request=request)
        return httpx.Response(502, text="upstream token SENTINEL_SECRET", request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(ValueError) as captured:
        google_sheets_import_service.fetch_csv(secret_url)

    assert str(captured.value) == "Impossibile leggere il foglio Google Sheets."
    assert "SENTINEL_SECRET" not in str(captured.value)
    assert "token=" not in str(captured.value)
    assert secret_url not in str(captured.value)
    _assert_exception_chain_is_sanitized(captured.value, "SENTINEL_SECRET")


def test_fetch_csv_sanitizes_malformed_url_errors() -> None:
    secret = "SENTINEL_SECRET_PORT"
    malformed_url = f"https://docs.google.com:{secret}/spreadsheets/d/test/export"

    with pytest.raises(ValueError) as captured:
        google_sheets_import_service.fetch_csv(malformed_url)

    assert str(captured.value) == "URL Google Sheets non valida o non attendibile."
    _assert_exception_chain_is_sanitized(captured.value, secret)


def test_resolution_snapshot_stays_local_when_provider_budget_is_exhausted(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.database import db_session, init_db

    monkeypatch.setenv("INVESTEDGE_DB_PATH", str(tmp_path / "resolution-snapshot.db"))
    get_settings.cache_clear()
    init_db()

    class ExhaustedProvider:
        def map_isins(self, *args: object, **kwargs: object) -> object:
            raise ProviderBudgetExceeded("openfigi", "mapping", "DAY")

    service = InstrumentResolutionService(provider=ExhaustedProvider())
    with db_session() as connection:
        snapshot = service.snapshot_for_reference(
            connection,
            " legacy ",
            {"currency": " eur ", "asset_type": " STOCK "},
        )
        normalized_snapshot = service.snapshot_for_reference(
            connection,
            "LEGACY",
            {"asset_type": "stock", "currency": "EUR"},
        )
        service.assert_snapshot_current(connection, snapshot)

    assert snapshot.status == "UNMAPPED"
    assert snapshot.instrument_id is None
    assert snapshot.listing_id is None
    assert snapshot.resolution_case_id is None
    assert snapshot.candidate_count == 0
    assert len(snapshot.evidence_hash) == 64
    assert snapshot == normalized_snapshot
