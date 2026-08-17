from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from backend.app.config import get_settings
from backend.app.data_providers.openfigi import (
    OPENFIGI_MAPPING_PATH,
    OpenFigiCandidate,
    OpenFigiProvider,
)
from backend.app.data_providers.transport import SafeProviderTransport
from backend.app.database import BASE_SCHEMA, INDEX_SCHEMA
from backend.app.models import ListingMetadataApplyIn, ListingMetadataPreviewIn
from backend.app.services.instrument_resolution_service import (
    InstrumentResolutionService,
    ResolutionConflictError,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "catalogs"
SUCCESS_FIXTURE = FIXTURE_DIR / "openfigi_mapping_success.json"
AMBIGUOUS_FIXTURE = FIXTURE_DIR / "openfigi_mapping_ambiguous.json"
UNMATCHED_FIXTURE = FIXTURE_DIR / "openfigi_mapping_unmatched.json"
NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
ISIN = "US0378331005"


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


def _fixture(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _insert_entry(
    connection: sqlite3.Connection,
    *,
    isin: str = ISIN,
    instrument_id: int | None = None,
    instrument_type: str = "UNKNOWN",
    row_number: int = 1,
    retrieved_at: datetime = NOW,
) -> tuple[int, int, int]:
    if instrument_id is None:
        instrument_id = int(
            connection.execute(
                """
                INSERT INTO instruments (
                    canonical_name, instrument_type, asset_class, quality_tier, source
                )
                VALUES ('Synthetic Instrument', ?, 'UNKNOWN', 'REFERENCE_ONLY', 'TEST')
                """,
                (instrument_type,),
            ).lastrowid
        )
        connection.execute(
            """
            INSERT INTO instrument_identifiers (
                scheme, normalized_value, scope, instrument_id, listing_id
            )
            VALUES ('ISIN', ?, 'INSTRUMENT', ?, NULL)
            """,
            (isin, instrument_id),
        )
    digest = hashlib.sha256(
        f"snapshot:{isin}:{retrieved_at.isoformat()}:{row_number}".encode()
    ).hexdigest()
    snapshot_id = int(
        connection.execute(
            """
            INSERT INTO catalog_snapshots (
                source, source_url, content_sha256, retrieved_at, source_date,
                row_count, status, parser_version, failure_reason_code
            )
            VALUES ('TRADE_REPUBLIC_IT', 'https://example.test/catalog.pdf', ?, ?, NULL,
                    1, 'COMPLETE', 'test-v1', NULL)
            """,
            (digest, retrieved_at.isoformat()),
        ).lastrowid
    )
    entry_id = int(
        connection.execute(
            """
            INSERT INTO catalog_entries (
                snapshot_id, row_number, isin, name, parse_status, reason_code,
                raw_row_sha256, instrument_id, listing_id
            )
            VALUES (?, ?, ?, 'Synthetic Instrument', 'ACCEPTED', 'VALID_ISIN',
                    ?, ?, NULL)
            """,
            (snapshot_id, row_number, isin, "a" * 64, instrument_id),
        ).lastrowid
    )
    connection.commit()
    return snapshot_id, entry_id, instrument_id


def _provider(
    payloads: list[object],
    requests: list[httpx.Request] | None = None,
    *,
    statuses: list[int] | None = None,
) -> OpenFigiProvider:
    queue = list(payloads)
    status_queue = list(statuses or [200] * len(queue))

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        payload = queue.pop(0)
        status_code = status_queue.pop(0)
        headers = {"content-type": "application/json"}
        if status_code == 429:
            headers["retry-after"] = "0"
        return httpx.Response(status_code, json=payload, headers=headers)

    transport = SafeProviderTransport(
        allowed_hosts={"api.openfigi.com"}
    ).with_client(httpx.Client(transport=httpx.MockTransport(handler)))
    return OpenFigiProvider(
        transport=transport,
        clock=lambda: NOW,
        sleeper=lambda _delay: None,
    )


def _service(payload: object, requests: list[httpx.Request] | None = None):  # noqa: ANN202
    return InstrumentResolutionService(
        provider=_provider([payload], requests),
        clock=lambda: NOW,
    )


def _metadata(
    *,
    observed_at: datetime = NOW,
    evidence_hash: str = "b" * 64,
    venue_name: str = "Nasdaq Global Select Market",
    timezone: str = "America/New_York",
) -> ListingMetadataPreviewIn:
    return ListingMetadataPreviewIn(
        ticker=" aapl ",
        mic=" xnas ",
        venue_name=venue_name,
        currency=" usd ",
        timezone=timezone,
        instrument_type="STOCK",
        source="OFFICIAL_VENUE",
        observed_at=observed_at,
        evidence_hash=evidence_hash,
    )


def _apply_payload(
    payload: ListingMetadataPreviewIn,
    confirmation_token: str,
) -> ListingMetadataApplyIn:
    return ListingMetadataApplyIn(
        **payload.model_dump(),
        confirmation_token=confirmation_token,
    )


def test_openfigi_posts_at_most_five_isin_jobs_and_preserves_job_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "TEST_OPENFIGI_KEY")
    get_settings.cache_clear()
    requests: list[httpx.Request] = []
    slot = _fixture(SUCCESS_FIXTURE)[0]
    provider = _provider([[slot, slot, slot, slot, slot]], requests)
    connection = _initialize()
    isins = [ISIN, "US5949181045", "US67066G1040", "US0231351067", "US02079K3059"]

    results = provider.map_isins(connection, isins, now=NOW)

    assert [result.isin for result in results] == isins
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == OPENFIGI_MAPPING_PATH
    assert request.url.query == b""
    assert request.headers["X-OPENFIGI-APIKEY"] == "TEST_OPENFIGI_KEY"
    jobs = json.loads(request.content)
    assert jobs == [{"idType": "ID_ISIN", "idValue": isin} for isin in isins]
    assert all("exchCode" not in job for job in jobs)

    with pytest.raises(ValueError, match="at most 5"):
        provider.map_isins(connection, [*isins, "US30303M1027"], now=NOW)
    assert len(requests) == 1
    get_settings.cache_clear()


def test_openfigi_omits_optional_key_header_and_rejects_invalid_isin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENFIGI_API_KEY", raising=False)
    get_settings.cache_clear()
    requests: list[httpx.Request] = []
    provider = _provider([_fixture(SUCCESS_FIXTURE)], requests)
    connection = _initialize()

    provider.map_isins(connection, [ISIN], now=NOW)

    assert "X-OPENFIGI-APIKEY" not in requests[0].headers
    with pytest.raises(ValueError, match="valid ISIN"):
        provider.map_isins(connection, ["BTC"], now=NOW)
    assert len(requests) == 1


def test_openfigi_etp_type_is_compatible_only_with_exchange_traded_products() -> None:
    candidate = OpenFigiCandidate(
        figi="BBG000000001",
        ticker="SYNTH",
        exchange_code="XETR",
        market_sector="Equity",
        security_type="ETP",
        name="Synthetic ETP",
        currency_hint="EUR",
    )

    assert candidate.compatible_types() == frozenset({"ETF", "ETC", "ETN"})


@pytest.mark.parametrize("retry_status", [429, 500, 503])
def test_openfigi_retries_transient_statuses_through_safe_transport(
    retry_status: int,
) -> None:
    requests: list[httpx.Request] = []
    success = _fixture(SUCCESS_FIXTURE)
    provider = _provider(
        [{"error": "temporary"}, success],
        requests,
        statuses=[retry_status, 200],
    )

    results = provider.map_isins(_initialize(), [ISIN], now=NOW)

    assert len(requests) == 2
    assert results[0].candidates[0].figi == "BBG000B9XRY4"


@pytest.mark.parametrize(
    ("payload", "expected_invalid"),
    [
        ([{"data": [{"ticker": "AAPL", "securityType": "Common Stock"}]}], True),
        ([{"data": [{"figi": "BBG000B9XRY4", "ticker": 123}]}], True),
        ({"data": []}, True),
        ([{"data": "not-an-array"}], True),
    ],
)
def test_openfigi_marks_malformed_provider_slots_invalid(
    payload: object,
    expected_invalid: bool,
) -> None:
    result = _provider([payload]).map_isins(_initialize(), [ISIN], now=NOW)[0]

    assert result.invalid_payload is expected_invalid
    assert result.candidates == ()
    assert len(result.evidence_hash) == 64


def test_openfigi_cache_does_not_persist_ignored_raw_candidate_fields() -> None:
    connection = _initialize()
    payload = _fixture(SUCCESS_FIXTURE)
    payload[0]["data"][0]["ignoredRawField"] = "SENTINEL_RAW_PROVIDER_FIELD"

    _provider([payload]).map_isins(connection, [ISIN], now=NOW)

    cached = connection.execute(
        "SELECT response_json FROM api_cache WHERE provider = 'OPENFIGI'"
    ).fetchone()[0]
    assert "SENTINEL_RAW_PROVIDER_FIELD" not in cached


def test_unique_candidate_without_verified_metadata_fails_closed_without_listing() -> None:
    connection = _initialize()
    _, entry_id, instrument_id = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))

    result = service.resolve_catalog_entries(connection, [entry_id])[0]

    assert result.status == "REJECTED"
    assert result.reason_code == "MISSING_CURRENCY"
    assert result.instrument_id == instrument_id
    assert result.listing_id is None
    assert result.candidate_count == 1
    assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 0
    case = connection.execute("SELECT * FROM instrument_resolution_cases").fetchone()
    assert case["candidate_hash"] and case["evidence_hash"]
    assert not any(
        token in column[1].lower()
        for column in connection.execute("PRAGMA table_info(instrument_resolution_cases)")
        for token in ("raw_payload", "candidate_array", "source_url", "document")
    )


@pytest.mark.parametrize(
    ("mic", "timezone", "expected_reason"),
    [
        (None, None, "MISSING_VENUE"),
        ("XNAS", None, "MISSING_TIMEZONE"),
    ],
)
def test_unique_candidate_reports_specific_missing_local_listing_metadata(
    mic: str | None,
    timezone: str | None,
    expected_reason: str,
) -> None:
    connection = _initialize()
    _, entry_id, instrument_id = _insert_entry(connection)
    connection.execute(
        """
        INSERT INTO instrument_listings (
            instrument_id, ticker, mic, venue_name, currency, timezone,
            listing_status, trade_republic_status, source
        )
        VALUES (?, 'AAPL', ?, ?, 'USD', ?, 'ACTIVE', 'NEVER_SEEN', 'TEST')
        """,
        (instrument_id, mic, "Nasdaq" if mic else None, timezone),
    )
    connection.commit()

    result = _service(_fixture(SUCCESS_FIXTURE)).resolve_catalog_entries(
        connection,
        [entry_id],
    )[0]

    assert result.status == "REJECTED"
    assert result.reason_code == expected_reason


@pytest.mark.parametrize(
    ("fixture", "expected_status", "expected_reason", "candidate_count"),
    [
        (AMBIGUOUS_FIXTURE, "AMBIGUOUS", "MULTIPLE_COMPATIBLE_CANDIDATES", 2),
        (UNMATCHED_FIXTURE, "UNMATCHED", "NO_PROVIDER_MATCH", 0),
    ],
)
def test_resolution_never_selects_the_first_candidate(
    fixture: Path,
    expected_status: str,
    expected_reason: str,
    candidate_count: int,
) -> None:
    connection = _initialize()
    _, entry_id, _ = _insert_entry(connection)

    result = _service(_fixture(fixture)).resolve_catalog_entries(connection, [entry_id])[0]

    assert result.status == expected_status
    assert result.reason_code == expected_reason
    assert result.candidate_count == candidate_count
    assert result.listing_id is None


def test_multiple_compatible_candidates_stay_ambiguous_with_one_local_listing() -> None:
    connection = _initialize()
    _, first_entry, instrument_id = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(connection, [first_entry])
    payload = _metadata()
    preview = service.preview_listing_metadata(connection, first_entry, payload)
    service.apply_listing_metadata(
        connection,
        first_entry,
        _apply_payload(payload, preview.confirmation_token),
    )
    _, second_entry, _ = _insert_entry(
        connection,
        instrument_id=instrument_id,
        row_number=2,
        retrieved_at=NOW + timedelta(days=1),
    )
    connection.execute("DELETE FROM api_cache WHERE provider = 'OPENFIGI'")
    connection.commit()

    result = _service(_fixture(AMBIGUOUS_FIXTURE)).resolve_catalog_entries(
        connection,
        [second_entry],
    )[0]

    assert result.status == "AMBIGUOUS"
    assert result.reason_code == "MULTIPLE_COMPATIBLE_CANDIDATES"
    assert result.candidate_count == 2
    assert result.listing_id is None
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        connection.execute(
            """
            INSERT INTO instrument_resolution_cases (
                catalog_entry_id, provider, request_fingerprint, status,
                reason_code, candidate_count, candidate_hash, evidence_hash,
                selected_instrument_id, selected_listing_id,
                candidate_figi, candidate_ticker, candidate_exchange_code,
                candidate_market_sector, candidate_security_type, candidate_name,
                candidate_currency_hint, created_at
            )
            SELECT catalog_entry_id, provider, request_fingerprint, status,
                   reason_code, 2, candidate_hash, evidence_hash,
                   selected_instrument_id, selected_listing_id,
                   candidate_figi, candidate_ticker, candidate_exchange_code,
                   candidate_market_sector, candidate_security_type, candidate_name,
                   candidate_currency_hint, created_at
            FROM instrument_resolution_cases
            WHERE status = 'RESOLVED'
            ORDER BY id
            LIMIT 1
            """
        )


@pytest.mark.parametrize("instrument_type", ["CRYPTO", "FX"])
def test_isin_backed_catalog_entry_rejects_crypto_and_fx_candidates(
    instrument_type: str,
) -> None:
    connection = _initialize()
    _, entry_id, _ = _insert_entry(connection)
    payload = _fixture(SUCCESS_FIXTURE)
    payload[0]["data"][0]["marketSector"] = instrument_type
    payload[0]["data"][0]["securityType"] = instrument_type

    result = _service(payload).resolve_catalog_entries(connection, [entry_id])[0]

    assert result.status == "REJECTED"
    assert result.reason_code == "TYPE_MISMATCH"
    assert result.listing_id is None
    assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'FIGI'"
    ).fetchone()[0] == 0


def test_resolution_rejects_provider_type_mismatch() -> None:
    connection = _initialize()
    _, entry_id, _ = _insert_entry(connection, instrument_type="BOND")

    result = _service(_fixture(SUCCESS_FIXTURE)).resolve_catalog_entries(
        connection,
        [entry_id],
    )[0]

    assert result.status == "REJECTED"
    assert result.reason_code == "TYPE_MISMATCH"


def test_resolution_rejects_currency_hint_conflicting_with_verified_listing() -> None:
    connection = _initialize()
    _, first_entry, instrument_id = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(connection, [first_entry])
    payload = _metadata()
    preview = service.preview_listing_metadata(connection, first_entry, payload)
    service.apply_listing_metadata(
        connection,
        first_entry,
        _apply_payload(payload, preview.confirmation_token),
    )
    _, second_entry, _ = _insert_entry(
        connection,
        instrument_id=instrument_id,
        row_number=2,
        retrieved_at=NOW + timedelta(days=1),
    )
    conflicting = _fixture(SUCCESS_FIXTURE)
    conflicting[0]["data"][0]["currency"] = "EUR"
    connection.execute("DELETE FROM api_cache WHERE provider = 'OPENFIGI'")
    connection.commit()

    result = _service(conflicting).resolve_catalog_entries(connection, [second_entry])[0]

    assert result.status == "REJECTED"
    assert result.reason_code == "CURRENCY_MISMATCH"


def test_listing_metadata_preview_normalizes_and_apply_resolves_without_network() -> None:
    connection = _initialize()
    _, entry_id, instrument_id = _insert_entry(connection)
    requests: list[httpx.Request] = []
    service = _service(_fixture(SUCCESS_FIXTURE), requests)
    initial = service.resolve_catalog_entries(connection, [entry_id])[0]
    assert initial.reason_code == "MISSING_CURRENCY"
    payload = _metadata()

    preview = service.preview_listing_metadata(connection, entry_id, payload)

    assert preview.catalog_entry_id == entry_id
    assert preview.normalized_ticker == "AAPL"
    assert preview.normalized_mic == "XNAS"
    assert preview.normalized_currency == "USD"
    assert preview.normalized_timezone == "America/New_York"
    assert preview.current_version is None
    assert len(preview.confirmation_token) == 64

    class ForbiddenProvider:
        def map_isins(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("listing metadata apply must not call OpenFIGI")

    apply_service = InstrumentResolutionService(
        provider=ForbiddenProvider(),
        clock=lambda: NOW,
    )
    applied = apply_service.apply_listing_metadata(
        connection,
        entry_id,
        _apply_payload(payload, preview.confirmation_token),
    )

    assert applied.status == "RESOLVED"
    assert applied.reason_code == "EXACT_ISIN_TYPE_CURRENCY_MIC_TIMEZONE"
    assert applied.instrument_id == instrument_id
    assert applied.listing_id is not None
    assert len(requests) == 1
    listing = connection.execute(
        "SELECT * FROM instrument_listings WHERE id = ?",
        (applied.listing_id,),
    ).fetchone()
    assert {
        "ticker": listing["ticker"],
        "mic": listing["mic"],
        "currency": listing["currency"],
        "timezone": listing["timezone"],
        "trade_republic_status": listing["trade_republic_status"],
    } == {
        "ticker": "AAPL",
        "mic": "XNAS",
        "currency": "USD",
        "timezone": "America/New_York",
        "trade_republic_status": "CATALOGED",
    }
    assert listing["trade_republic_verified_at"] is None
    assert connection.execute(
        "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'FIGI'"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM instrument_identifiers WHERE scheme = 'OPENFIGI_TICKER'"
    ).fetchone()[0] == 1


def test_listing_metadata_validation_source_hash_timezone_currency_and_type() -> None:
    connection = _initialize()
    _, entry_id, _ = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(connection, [entry_id])

    with pytest.raises(ValidationError):
        ListingMetadataPreviewIn(
            **{
                **_metadata().model_dump(),
                "source": "https://example.test/factsheet",
            }
        )
    for field, value in (
        ("evidence_hash", "https://example.test/evidence"),
        ("timezone", "Europe/Not_A_Zone"),
        ("currency", "ZZZ"),
        ("mic", "NASDAQ"),
        ("instrument_type", "BOND"),
    ):
        values = _metadata().model_dump()
        values[field] = value
        candidate = ListingMetadataPreviewIn(**values)
        with pytest.raises(ValueError):
            service.preview_listing_metadata(connection, entry_id, candidate)


def test_listing_metadata_apply_uses_compare_digest_and_rejects_stale_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.app.services.instrument_resolution_service as resolution_module

    connection = _initialize()
    _, entry_id, _ = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(connection, [entry_id])
    payload = _metadata()
    preview = service.preview_listing_metadata(connection, entry_id, payload)
    calls: list[tuple[str, str]] = []
    real_compare = resolution_module.hmac.compare_digest

    def compare(left: str, right: str) -> bool:
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(resolution_module.hmac, "compare_digest", compare)
    stale = _apply_payload(payload, "0" * 64)
    before = connection.total_changes

    with pytest.raises(ResolutionConflictError):
        service.apply_listing_metadata(connection, entry_id, stale)

    assert calls
    assert connection.total_changes == before
    assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 0
    assert len(preview.confirmation_token) == 64


def test_listing_metadata_versions_supersede_and_repeat_is_idempotent() -> None:
    connection = _initialize()
    _, entry_id, _ = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(connection, [entry_id])
    first_payload = _metadata()
    first_preview = service.preview_listing_metadata(connection, entry_id, first_payload)
    first_apply = _apply_payload(first_payload, first_preview.confirmation_token)

    first = service.apply_listing_metadata(connection, entry_id, first_apply)
    repeated = service.apply_listing_metadata(connection, entry_id, first_apply)

    assert repeated == first
    assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM listing_metadata_versions").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM catalog_listing_attestations").fetchone()[0] == 1

    second_payload = _metadata(
        observed_at=NOW + timedelta(days=1),
        evidence_hash="c" * 64,
        venue_name="Nasdaq Stock Market",
    )
    second_preview = service.preview_listing_metadata(connection, entry_id, second_payload)
    second = service.apply_listing_metadata(
        connection,
        entry_id,
        _apply_payload(second_payload, second_preview.confirmation_token),
    )

    assert second.listing_id == first.listing_id
    versions = connection.execute(
        """
        SELECT id, status, version, supersedes_listing_metadata_version_id
        FROM listing_metadata_versions
        ORDER BY version
        """
    ).fetchall()
    assert [(row["status"], row["version"]) for row in versions] == [
        ("RETIRED", 1),
        ("VERIFIED", 2),
    ]
    assert versions[1]["supersedes_listing_metadata_version_id"] == versions[0]["id"]
    assert connection.execute("SELECT COUNT(*) FROM catalog_listing_attestations").fetchone()[0] == 2


def test_listing_metadata_apply_preserves_an_existing_caller_transaction() -> None:
    connection = _initialize()
    _, entry_id, instrument_id = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(connection, [entry_id])
    payload = _metadata()
    preview = service.preview_listing_metadata(connection, entry_id, payload)
    connection.execute(
        "UPDATE instruments SET canonical_name = 'Outer transaction marker' WHERE id = ?",
        (instrument_id,),
    )
    assert connection.in_transaction

    result = service.apply_listing_metadata(
        connection,
        entry_id,
        _apply_payload(payload, preview.confirmation_token),
    )

    assert result.status == "RESOLVED"
    assert connection.in_transaction
    assert connection.execute(
        "SELECT canonical_name FROM instruments WHERE id = ?",
        (instrument_id,),
    ).fetchone()[0] == "Outer transaction marker"


def test_second_snapshot_reuses_instrument_listing_metadata_and_adds_attestation() -> None:
    connection = _initialize()
    _, first_entry, instrument_id = _insert_entry(connection)
    requests: list[httpx.Request] = []
    service = _service(_fixture(SUCCESS_FIXTURE), requests)
    service.resolve_catalog_entries(connection, [first_entry])
    payload = _metadata()
    preview = service.preview_listing_metadata(connection, first_entry, payload)
    first = service.apply_listing_metadata(
        connection,
        first_entry,
        _apply_payload(payload, preview.confirmation_token),
    )
    _, second_entry, reused_instrument = _insert_entry(
        connection,
        instrument_id=instrument_id,
        row_number=2,
        retrieved_at=NOW + timedelta(days=1),
    )

    second = service.resolve_catalog_entries(connection, [second_entry])[0]

    assert reused_instrument == instrument_id
    assert second.status == "RESOLVED"
    assert second.listing_id == first.listing_id
    assert len(requests) == 1
    assert connection.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM listing_metadata_versions").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM catalog_listing_attestations").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM instrument_resolution_cases").fetchone()[0] == 3
    assert connection.execute(
        "SELECT trade_republic_cataloged_at FROM instrument_listings WHERE id = ?",
        (first.listing_id,),
    ).fetchone()[0] == (NOW + timedelta(days=1)).isoformat()


def test_two_concurrent_metadata_applies_create_one_listing_version_and_attestation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "resolution-concurrency.db"
    setup = _initialize(database_path)
    _, entry_id, _ = _insert_entry(setup)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(setup, [entry_id])
    payload = _metadata()
    preview = service.preview_listing_metadata(setup, entry_id, payload)
    apply_payload = _apply_payload(payload, preview.confirmation_token)
    setup.close()
    barrier = threading.Barrier(2)

    class ForbiddenProvider:
        def map_isins(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("concurrent apply must remain local")

    apply_service = InstrumentResolutionService(
        provider=ForbiddenProvider(),
        clock=lambda: NOW,
    )

    def worker():  # noqa: ANN202
        connection = _connect(database_path)
        try:
            barrier.wait(timeout=5)
            return apply_service.apply_listing_metadata(connection, entry_id, apply_payload)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: worker(), range(2)))

    assert results[0] == results[1]
    check = _connect(database_path)
    assert check.execute("SELECT COUNT(*) FROM instrument_listings").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM listing_metadata_versions").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM catalog_listing_attestations").fetchone()[0] == 1
    check.close()


def test_stable_listing_key_includes_instrument_and_blocks_duplicate_within_instrument() -> None:
    connection = _initialize()
    _, _, first_instrument = _insert_entry(connection)
    _, _, second_instrument = _insert_entry(
        connection,
        isin="US5949181045",
        retrieved_at=NOW + timedelta(minutes=1),
    )
    statement = """
        INSERT INTO instrument_listings (
            instrument_id, ticker, mic, venue_name, currency, timezone, source
        )
        VALUES (?, 'SAME', 'XNAS', 'Nasdaq', 'USD', 'America/New_York', 'TEST')
    """

    connection.execute(statement, (first_instrument,))
    connection.execute(statement, (second_instrument,))
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(statement, (first_instrument,))


def test_require_resolved_listing_rejects_unresolved_and_returns_verified_current() -> None:
    connection = _initialize()
    _, entry_id, _ = _insert_entry(connection)
    service = _service(_fixture(SUCCESS_FIXTURE))
    service.resolve_catalog_entries(connection, [entry_id])
    with pytest.raises(ValueError):
        service.require_resolved_listing(connection, 999)
    payload = _metadata()
    preview = service.preview_listing_metadata(connection, entry_id, payload)
    result = service.apply_listing_metadata(
        connection,
        entry_id,
        _apply_payload(payload, preview.confirmation_token),
    )

    row = service.require_resolved_listing(connection, result.listing_id)

    assert row["id"] == result.listing_id
    assert row["metadata_version"] == 1
