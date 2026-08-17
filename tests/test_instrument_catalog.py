from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from backend.app.data_providers import trade_republic_catalog as catalog_parser
from backend.app.data_providers.trade_republic_catalog import (
    CATALOG_MAX_RESPONSE_BYTES,
    TRADE_REPUBLIC_CATALOG_PATH,
    TRADE_REPUBLIC_CATALOG_URL,
    TRADE_REPUBLIC_SOURCE,
    CatalogParseError,
    parse_trade_republic_pdf,
)
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import BASE_SCHEMA, INDEX_SCHEMA
from backend.app.services.catalog_service import (
    CatalogRefreshError,
    CatalogService,
    ingest_trade_republic_catalog,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "catalogs"
FIXTURE_PDF = FIXTURE_DIR / "trade_republic_it_excerpt.pdf"
EXPECTED_JSON = FIXTURE_DIR / "trade_republic_it_excerpt.expected.json"
NOW = datetime(2026, 8, 17, 10, 30, tzinfo=UTC)


def _connect(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(path) if path is not None else ":memory:",
        check_same_thread=False,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize(path: Path | None = None) -> sqlite3.Connection:
    connection = _connect(path)
    connection.executescript(BASE_SCHEMA)
    connection.executescript(INDEX_SCHEMA)
    return connection


def _fixture_payload() -> bytes:
    return FIXTURE_PDF.read_bytes()


def _expected_rows() -> list[dict[str, object]]:
    return json.loads(EXPECTED_JSON.read_text(encoding="utf-8"))


def _header_only_payload() -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(_fixture_payload()), strict=True)
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _payload_with_text_replacement(before: bytes, after: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    reader = PdfReader(io.BytesIO(_fixture_payload()), strict=True)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    replacements = 0
    for page in writer.pages:
        contents = page.get_contents()
        if contents is None:
            continue
        data = contents.get_data()
        replacements += data.count(before)
        if before not in data:
            continue
        stream = DecodedStreamObject()
        stream.set_data(data.replace(before, after))
        page[NameObject("/Contents")] = writer._add_object(stream)  # noqa: SLF001
    assert replacements == 1
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _different_valid_payload() -> bytes:
    return _payload_with_text_replacement(
        b"Synthetic Beta Fund",
        b"Synthetic Beta Bond",
    )


def _oversize_run_length_payload() -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import EncodedStreamObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    stream = EncodedStreamObject()
    stream._data = (  # noqa: SLF001 - costruisce intenzionalmente uno stream PDF ostile
        bytes((129, 32)) * (CATALOG_MAX_RESPONSE_BYTES // 128 + 1)
        + bytes((128,))
    )
    stream[NameObject("/Filter")] = NameObject("/RunLengthDecode")
    page[NameObject("/Contents")] = writer._add_object(stream)  # noqa: SLF001
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _pdf_response(payload: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(payload),
        headers={"content-type": "application/pdf"},
    )


def _service(handler) -> CatalogService:  # noqa: ANN001
    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = SafeProviderTransport(
        allowed_hosts={"assets.traderepublic.com"}
    ).with_client(client)
    return CatalogService(
        transport=transport,
        clock=lambda: NOW,
        sleeper=lambda _delay: None,
    )


def test_trade_republic_fixture_is_minimal_synthetic_and_parses_across_pages() -> None:
    payload = _fixture_payload()

    rows = parse_trade_republic_pdf(payload)

    assert len(payload) < 10_000
    assert [asdict(row) for row in rows] == _expected_rows()
    assert [row.row_number for row in rows] == [1, 2, 3, 4]
    assert sum(row.status == "ACCEPTED" for row in rows) == 2
    assert sum(row.status == "REJECTED" for row in rows) == 2
    assert sum(row.status == "AMBIGUOUS" for row in rows) == 0


def test_trade_republic_parser_validates_iso_6166_check_digit() -> None:
    invalid = _payload_with_text_replacement(b"FR0000000002", b"FR0000000003")

    rows = parse_trade_republic_pdf(invalid)

    assert rows[1].isin == "FR0000000003"
    assert rows[1].status == "REJECTED"
    assert rows[1].reason_code == "INVALID_ISIN"


def test_trade_republic_parser_rejects_unicode_casefold_in_isin_token() -> None:
    row = catalog_parser._parse_row(  # noqa: SLF001 - regressione del tokenizer
        "Synthetic Unicode KE0000000002",
        1,
        set(),
    )

    assert row.isin is None
    assert row.status == "REJECTED"
    assert row.reason_code == "MISSING_ISIN"


def test_trade_republic_parser_limits_decompressed_streams() -> None:
    payload = _oversize_run_length_payload()

    assert len(payload) < 1_000_000
    with pytest.raises(CatalogParseError) as exc_info:
        parse_trade_republic_pdf(payload)

    assert exc_info.value.reason_code == "PAYLOAD_TOO_LARGE"


def test_trade_republic_parser_rejects_oversize_malformed_and_empty_catalogs() -> None:
    with pytest.raises(CatalogParseError) as oversize:
        parse_trade_republic_pdf(b"%PDF-" + b"x" * CATALOG_MAX_RESPONSE_BYTES)
    with pytest.raises(CatalogParseError) as malformed:
        parse_trade_republic_pdf(b"%PDF-1.4\nnot-a-valid-pdf")

    assert oversize.value.reason_code == "PAYLOAD_TOO_LARGE"
    assert malformed.value.reason_code == "PARSER_ERROR"
    assert parse_trade_republic_pdf(_header_only_payload()) == []


def test_catalog_ingest_versions_checksum_and_reuses_instrument_identity() -> None:
    connection = _initialize()
    payload = _fixture_payload()
    different_payload = _different_valid_payload()

    first = ingest_trade_republic_catalog(connection, payload, NOW)
    unchanged = ingest_trade_republic_catalog(connection, payload, NOW + timedelta(minutes=1))
    second = ingest_trade_republic_catalog(
        connection,
        different_payload,
        NOW + timedelta(minutes=2),
    )

    assert asdict(first) == {
        "snapshot_id": first.snapshot_id,
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "accepted": 2,
        "rejected": 2,
        "ambiguous": 0,
        "unchanged": False,
    }
    assert unchanged.snapshot_id == first.snapshot_id
    assert unchanged.unchanged is True
    assert second.snapshot_id != first.snapshot_id
    assert second.content_sha256 == hashlib.sha256(different_payload).hexdigest()
    assert second.unchanged is False

    snapshots = connection.execute(
        """
        SELECT source, source_url, content_sha256, retrieved_at, source_date,
               row_count, status, parser_version, failure_reason_code
        FROM catalog_snapshots
        ORDER BY id
        """
    ).fetchall()
    assert len(snapshots) == 2
    assert all(row["source"] == TRADE_REPUBLIC_SOURCE for row in snapshots)
    assert all(row["source_url"] == TRADE_REPUBLIC_CATALOG_URL for row in snapshots)
    assert all(row["source_date"] is None for row in snapshots)
    assert all(row["row_count"] == 4 for row in snapshots)
    assert all(row["status"] == "COMPLETE" for row in snapshots)
    assert all(row["failure_reason_code"] is None for row in snapshots)
    assert len({row["parser_version"] for row in snapshots}) == 1

    assert connection.execute("SELECT COUNT(*) FROM catalog_entries").fetchone()[0] == 8
    assert connection.execute("SELECT COUNT(*) FROM instruments").fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'ISIN'"
    ).fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0

    first_entries = connection.execute(
        """
        SELECT row_number, parse_status, reason_code, instrument_id, listing_id
        FROM catalog_entries
        WHERE snapshot_id = ?
        ORDER BY row_number
        """,
        (first.snapshot_id,),
    ).fetchall()
    assert [row["reason_code"] for row in first_entries] == [
        "VALID_ISIN",
        "VALID_ISIN",
        "DUPLICATE_IN_SNAPSHOT",
        "MISSING_ISIN",
    ]
    assert [row["instrument_id"] is not None for row in first_entries] == [
        True,
        True,
        False,
        False,
    ]
    assert all(row["listing_id"] is None for row in first_entries)


def test_catalog_ingest_rolls_back_snapshot_entries_and_instruments_together() -> None:
    connection = _initialize()
    connection.executescript(
        """
        CREATE TRIGGER fail_second_catalog_entry
        BEFORE INSERT ON catalog_entries
        WHEN NEW.row_number = 2
        BEGIN
            SELECT RAISE(ABORT, 'synthetic entry failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="synthetic entry failure"):
        ingest_trade_republic_catalog(connection, _fixture_payload(), NOW)

    for table in (
        "catalog_snapshots",
        "catalog_entries",
        "instruments",
        "instrument_identifiers",
        "instrument_identifier_attestations",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("reason_code", "handler"),
    [
        ("DOWNLOAD_FAILED", lambda _request: _pdf_response(b"", status_code=404)),
        (
            "PAYLOAD_TOO_LARGE",
            lambda _request: _pdf_response(b"x" * (CATALOG_MAX_RESPONSE_BYTES + 1)),
        ),
        ("PARSER_ERROR", lambda _request: _pdf_response(b"%PDF-1.4\nbroken")),
        ("EMPTY_CATALOG", lambda _request: _pdf_response(_header_only_payload())),
    ],
)
def test_catalog_refresh_records_one_sanitized_failed_snapshot_without_entries(
    reason_code: str,
    handler,
) -> None:  # noqa: ANN001
    connection = _initialize()
    service = _service(handler)

    with pytest.raises(CatalogRefreshError) as exc_info:
        service.refresh(connection, force=False)

    assert exc_info.value.reason_code == reason_code
    assert str(exc_info.value) == f"trade_republic_catalog:{reason_code}"
    failures = connection.execute(
        """
        SELECT status, content_sha256, failure_reason_code
        FROM catalog_snapshots
        """
    ).fetchall()
    assert len(failures) == 1
    assert failures[0]["status"] == "FAILED"
    assert failures[0]["failure_reason_code"] == reason_code
    if reason_code in {"DOWNLOAD_FAILED", "PAYLOAD_TOO_LARGE"}:
        assert failures[0]["content_sha256"] is None
    else:
        assert len(failures[0]["content_sha256"]) == 64
    assert connection.execute("SELECT COUNT(*) FROM catalog_entries").fetchone()[0] == 0


def test_catalog_failure_does_not_replace_latest_complete_snapshot() -> None:
    connection = _initialize()
    complete = ingest_trade_republic_catalog(connection, _fixture_payload(), NOW)

    with pytest.raises(CatalogRefreshError) as exc_info:
        ingest_trade_republic_catalog(
            connection,
            b"%PDF-1.4\nmalformed",
            NOW + timedelta(minutes=1),
        )

    assert exc_info.value.reason_code == "PARSER_ERROR"
    latest_complete = connection.execute(
        """
        SELECT id FROM catalog_snapshots
        WHERE source = ? AND status = 'COMPLETE'
        ORDER BY retrieved_at DESC, id DESC
        LIMIT 1
        """,
        (TRADE_REPUBLIC_SOURCE,),
    ).fetchone()
    assert latest_complete["id"] == complete.snapshot_id
    assert connection.execute(
        "SELECT COUNT(*) FROM catalog_snapshots WHERE status = 'COMPLETE'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM catalog_snapshots WHERE status = 'FAILED'"
    ).fetchone()[0] == 1


def test_catalog_refresh_cache_force_and_fixed_official_request() -> None:
    connection = _initialize()
    payloads = [_fixture_payload(), _different_valid_payload()]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _pdf_response(payloads[len(requests) - 1])

    service = _service(handler)

    first = service.refresh(connection, force=False)
    cached = service.refresh(connection, force=False)
    forced = service.refresh(connection, force=True)
    cached_after_force = service.refresh(connection, force=False)

    assert first.unchanged is False
    assert cached.snapshot_id == first.snapshot_id
    assert cached.unchanged is True
    assert forced.snapshot_id != first.snapshot_id
    assert forced.unchanged is False
    assert cached_after_force.snapshot_id == forced.snapshot_id
    assert cached_after_force.unchanged is True
    assert len(requests) == 2
    assert all(str(request.url) == TRADE_REPUBLIC_CATALOG_URL for request in requests)
    assert all(request.method == "GET" for request in requests)
    assert all(request.url.path == TRADE_REPUBLIC_CATALOG_PATH for request in requests)
    assert connection.execute(
        "SELECT calls_count FROM api_usage WHERE provider = ?",
        (TRADE_REPUBLIC_SOURCE,),
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_request_log WHERE outcome = 'CACHE_HIT'"
    ).fetchone()[0] == 2


def test_two_concurrent_forced_catalog_refreshes_share_one_physical_request(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "catalog-concurrency.db"
    initial = _initialize(database_path)
    initial.close()
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=3)
        return _pdf_response(_fixture_payload())

    service = _service(handler)

    def run() -> object:
        with _connect(database_path) as connection:
            return service.refresh(connection, force=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run)
        assert entered.wait(timeout=3)
        second_future = executor.submit(run)
        time.sleep(0.05)
        release.set()
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    with _connect(database_path) as connection:
        usage = connection.execute(
            "SELECT calls_count FROM api_usage WHERE provider = ?",
            (TRADE_REPUBLIC_SOURCE,),
        ).fetchone()[0]
        complete_count = connection.execute(
            "SELECT COUNT(*) FROM catalog_snapshots WHERE status = 'COMPLETE'"
        ).fetchone()[0]

    assert calls == 1
    assert usage == 1
    assert complete_count == 1
    assert first.snapshot_id == second.snapshot_id
    assert sorted((first.unchanged, second.unchanged)) == [False, True]
