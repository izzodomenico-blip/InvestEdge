from __future__ import annotations

import importlib
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_alpaca_market_provider import profile, provider, response, settings
from test_instrument_resolution import (
    SUCCESS_FIXTURE,
    _fixture,
    _initialize,
    _insert_entry,
    _metadata,
    _service,
)

from backend.app.models import ListingMetadataApplyIn

SECOND = 1_000_000_000


def ns(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    delta = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * SECOND + delta.microseconds * 1000


def resolved(connection=None, *, ticker="AAPL", instrument_type="STOCK", second=False):
    connection = connection or _initialize()
    _, entry, _ = _insert_entry(connection, isin="US5949181045" if second else "US0378331005",
                                 instrument_type=instrument_type)
    candidate = _fixture(SUCCESS_FIXTURE)
    if second:
        candidate[0]["data"][0]["figi"] = "BBG000B9XRZ5"
    if instrument_type == "ETF":
        candidate[0]["data"][0]["securityType"] = "ETP"
    service = _service(candidate)
    service.resolve_catalog_entries(connection, [entry])
    request = _metadata().model_copy(update={"ticker": ticker, "instrument_type": instrument_type})
    preview = service.preview_listing_metadata(connection, entry, request)
    result = service.apply_listing_metadata(
        connection, entry, ListingMetadataApplyIn(**request.model_dump(), confirmation_token=preview.confirmation_token),
    )
    return connection, result.listing_id


def asset(*, symbol="AAPL", asset_id=None, status="active", tradable=True, **extra):
    return {"id": asset_id or str(uuid.uuid4()), "class": "us_equity", "symbol": symbol,
            "exchange": "NASDAQ", "status": status, "tradable": tradable, **extra}


def system(*, instrument_type="STOCK", data_mode="REAL", provenance="CAPTURED", replay_grade="STRICT_PIT",
           max_archive_bytes=10_485_760, frame_bytes=1_048_576, profile_overrides=None):
    metadata = importlib.import_module("backend.app.data_providers.alpaca_metadata")
    identity = importlib.import_module("backend.app.intraday.identity")
    calendar = importlib.import_module("backend.app.intraday.calendar")
    universe = importlib.import_module("backend.app.intraday.universe")
    connection, listing = resolved(instrument_type=instrument_type)
    from backend.app.database import INTRADAY_INDEX_SCHEMA
    connection.executescript(INTRADAY_INDEX_SCHEMA)
    clock = SimpleNamespace(now=ns("2026-10-12T12:00:00Z"))
    config = settings(alpaca_max_archive_bytes=max_archive_bytes, alpaca_max_frame_bytes=frame_bytes)
    prof = profile(config, **(profile_overrides or {}))
    queue, requests = [], []
    def handler(request):
        requests.append(request)
        return response(queue.pop(0))
    client = provider(connection, config, handler, prof=prof)
    client.clock = lambda: datetime.fromtimestamp(clock.now // SECOND, UTC)
    archive = metadata.AlpacaMetadataService(
        client, clock_ns=lambda: clock.now, data_mode=data_mode, provenance=provenance, replay_grade=replay_grade,
    )
    return SimpleNamespace(db=connection, listing=listing, clock=clock, config=config, profile=prof,
                           queue=queue, requests=requests, archive=archive,
                           identity=identity.IdentityService(archive), calendar=calendar.CalendarService(archive),
                           universe=universe.UniverseService(archive))


def capture(s, rows):
    if s.archive.data_mode == "DEMO":
        return s.archive.record_assets(rows, received_at_ns=s.clock.now)
    s.queue.extend([[row for row in rows if row.get("status") != "inactive"],
                    [row for row in rows if row.get("status") == "inactive"]])
    return s.archive.refresh_assets()


def mapping(s, row, capture_id, **extra):
    models = importlib.import_module("backend.app.models")
    return models.AlpacaIdentityPreviewIn(
        metadata_capture_id=capture_id, broker_asset_id=row["id"], capabilities=["BAR", "QUOTE", "NEWS"],
        evidence_hash="b" * 64, **extra,
    )


def confirm(s, row, capture_id, *, listing=None, **extra):
    models = importlib.import_module("backend.app.models")
    request = mapping(s, row, capture_id, **extra)
    listing = listing or s.listing
    preview = s.identity.preview(listing, request)
    return s.identity.apply(listing, models.AlpacaIdentityApplyIn(
        **request.model_dump(), confirmation_token=preview.confirmation_token,
    ))


def read(s, *, effective=None, cutoff=None, listing=None):
    module = importlib.import_module("backend.app.intraday.identity")
    return module.read_identity_as_of(
        s.db, listing or s.listing, effective or s.clock.now, cutoff or s.clock.now,
        profile_id=s.profile.profile_id, data_mode=s.archive.data_mode,
        provenance=s.archive.provenance, replay_grade=s.archive.replay_grade,
    )


def test_bootstrap_on_empty_intraday_schema_and_confirmation_has_own_knowledge_time():
    s = system()
    a = asset(name="discarded descriptive name")
    received = s.clock.now
    capture_id = capture(s, [a])
    request = mapping(s, a, capture_id)
    before = s.db.total_changes
    preview = s.identity.preview(s.listing, request)
    assert s.db.total_changes == before and len(s.requests) == 2
    assert read(s) is None
    s.clock.now += 3 * SECOND
    result = confirm(s, a, capture_id)
    assert read(s, effective=received, cutoff=received) is None
    row = read(s, effective=received, cutoff=s.clock.now)
    assert row["id"] == result.identity_version_id and row["available_at_ns"] == s.clock.now
    assert row["valid_from_ns"] == received
    assert row["payload"]["currency"] == "USD"
    assert preview.confirmation_token and "descriptive" not in json.dumps(row)
    assert [dict(request.url.params) for request in s.requests] == [
        {"asset_class": "us_equity", "status": "active"}, {"asset_class": "us_equity", "status": "inactive"},
    ]


def test_confirmation_is_idempotent_and_stale_preview_does_not_write():
    s = system()
    a = asset()
    capture_id = capture(s, [a])
    request = mapping(s, a, capture_id)
    models = importlib.import_module("backend.app.models")
    preview = s.identity.preview(s.listing, request)
    applied = models.AlpacaIdentityApplyIn(**request.model_dump(), confirmation_token=preview.confirmation_token)
    first = s.identity.apply(s.listing, applied)
    assert s.identity.apply(s.listing, applied) == first
    changed = applied.model_copy(update={"inverse": "NO"})
    before = s.db.total_changes
    with pytest.raises(ValueError, match="MAPPING_CHANGED"):
        s.identity.apply(s.listing, changed)
    assert s.db.total_changes == before


@pytest.mark.parametrize("mutation", [
    {"exchange": "NYSE"}, {"symbol": "OTHER"}, {"class": "crypto"},
])
def test_mapping_requires_verified_symbol_venue_and_equity_class(mutation):
    s = system()
    a = asset(**mutation) if "symbol" not in mutation else asset(symbol="OTHER")
    capture_id = capture(s, [a])
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        s.identity.preview(s.listing, mapping(s, a, capture_id))


def test_metadata_does_not_allow_backdating_current_master_list():
    s = system()
    a = asset()
    capture_id = capture(s, [a])
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        s.identity.preview(s.listing, mapping(s, a, capture_id, valid_from_ns=s.clock.now - SECOND))
    assert read(s, effective=s.clock.now - SECOND) is None


def test_uuid_reuse_is_a_new_identity_and_overlapping_ticker_is_rejected():
    s = system()
    a = asset()
    c1 = capture(s, [a])
    first = confirm(s, a, c1)
    _, second_listing = resolved(s.db, second=True)
    b = asset()
    c2 = capture(s, [a, b])
    with pytest.raises(ValueError, match="IDENTITY_AMBIGUOUS"):
        confirm(s, b, c2, listing=second_listing)
    s.clock.now += 2 * SECOND
    end = s.clock.now + SECOND
    confirm(s, a, c1, valid_to_ns=end)
    s.clock.now = end
    c3 = capture(s, [b])
    second = confirm(s, b, c3, listing=second_listing)
    assert second.identity_version_id != first.identity_version_id
    assert read(s, listing=second_listing)["broker_asset_id"] == b["id"]
    assert read(s) is None


def test_same_uuid_cannot_be_assigned_to_two_canonical_listings():
    s = system()
    a = asset()
    c = capture(s, [a])
    confirm(s, a, c)
    _, other = resolved(s.db, second=True)
    with pytest.raises(ValueError, match="IDENTITY_AMBIGUOUS"):
        confirm(s, a, c, listing=other)


def test_known_closure_does_not_resurrect_old_open_ended_version():
    s = system()
    a = asset()
    c = capture(s, [a])
    start = s.clock.now
    first = confirm(s, a, c)
    s.clock.now += 10 * SECOND
    confirm(s, a, c, valid_to_ns=start + 5 * SECOND)
    assert read(s, effective=start + 7 * SECOND) is None
    assert read(s, effective=start + 7 * SECOND, cutoff=start)["id"] == first.identity_version_id


def test_future_effective_transition_keeps_old_mapping_before_transition():
    s = system()
    a = asset()
    c = capture(s, [a])
    first = confirm(s, a, c)
    start = s.clock.now
    s.clock.now += SECOND
    transition = start + 10 * SECOND
    second = confirm(s, a, c, valid_from_ns=transition, validity_source="OFFICIAL_NOTICE")
    assert read(s, effective=start + 5 * SECOND)["id"] == first.identity_version_id
    assert read(s, effective=transition)["id"] == second.identity_version_id


def test_future_canonical_rename_and_delisting_do_not_change_asof_identity():
    s = system()
    a = asset()
    c = capture(s, [a])
    confirm(s, a, c)
    before = read(s)
    s.db.execute("UPDATE instrument_listings SET ticker='FUTURE', listing_status='DELISTED' WHERE id=?", (s.listing,))
    s.db.execute("UPDATE instruments SET instrument_type='UNKNOWN'")
    s.db.commit()
    assert read(s) == before


def test_unresolved_and_ambiguous_legacy_listings_cannot_be_confirmed():
    s = system()
    a = asset()
    c = capture(s, [a])
    s.db.execute("UPDATE listing_metadata_versions SET status='RETIRED' WHERE instrument_listing_id=?", (s.listing,))
    s.db.commit()
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        confirm(s, a, c)
    assert read(s) is None


@pytest.mark.parametrize("invalid", [
    {"id": "invalid"}, {"tradable": 1}, {"status": "unverified"}, {"symbol": " aapl "},
])
def test_invalid_metadata_rolls_back_without_a_completed_capture(invalid):
    s = system()
    a = asset()
    a.update(invalid)
    with pytest.raises(ValueError, match="METADATA_INVALID"):
        capture(s, [a])
    assert s.db.execute("SELECT COUNT(*) FROM intraday_capture_events").fetchone()[0] == 0


def test_secrets_in_metadata_or_mapping_never_enter_evidence_or_errors():
    s = system()
    a = asset()
    with pytest.raises(ValueError) as error:
        s.archive.record_assets([{**a, "name": s.config.alpaca_api_secret_key}], received_at_ns=s.clock.now)
    assert s.config.alpaca_api_secret_key not in str(error.value)
    c = capture(s, [a])
    request = mapping(s, a, c).model_copy(update={"evidence_hash": s.config.alpaca_api_secret_key})
    with pytest.raises(ValueError) as error:
        s.identity.preview(s.listing, request)
    evidence = "".join(row[0] for row in s.db.execute("SELECT payload_json FROM intraday_capture_events"))
    assert s.config.alpaca_api_secret_key not in evidence + str(error.value)


def test_archive_budget_failure_leaves_no_partial_metadata():
    s = system(max_archive_bytes=64)
    with pytest.raises(ValueError, match="ARCHIVE_LIMIT"):
        capture(s, [asset()])
    assert s.db.execute("SELECT COUNT(*) FROM intraday_capture_events").fetchone()[0] == 0


def test_real_and_demo_identity_reads_are_disjoint():
    s = system(data_mode="DEMO", provenance="SYNTHETIC", replay_grade="RESEARCH_ONLY")
    a = asset()
    c = capture(s, [a])
    confirm(s, a, c)
    assert read(s) is not None
    module = importlib.import_module("backend.app.intraday.identity")
    assert module.read_identity_as_of(s.db, s.listing, s.clock.now, s.clock.now,
                                     profile_id=s.profile.profile_id, data_mode="REAL") is None


@pytest.mark.parametrize("mutation", [{"capabilities": ["INVALID"]}, {"valid_from_ns": True}, {"leveraged": "invented"}])
def test_bypassed_input_validation_is_sanitized(mutation):
    s = system()
    a = asset()
    c = capture(s, [a])
    request = mapping(s, a, c).model_copy(update=mutation)
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        s.identity.preview(s.listing, request)


def test_arca_aliases_do_not_allow_two_identities_for_same_verified_venue():
    s = system()
    _, other = resolved(s.db, second=True)
    s.db.execute("UPDATE instrument_listings SET mic='ARCX' WHERE id IN (?,?)", (s.listing, other))
    s.db.commit()
    a, b = asset(exchange="ARCA"), asset(exchange="NYSEARCA")
    c = capture(s, [a, b])
    confirm(s, a, c)
    with pytest.raises(ValueError, match="IDENTITY_AMBIGUOUS"):
        confirm(s, b, c, listing=other)


def test_ambiguous_canonical_resolution_blocks_confirmation():
    s = system()
    a = asset()
    c = capture(s, [a])
    case = dict(s.db.execute("SELECT * FROM instrument_resolution_cases ORDER BY id DESC LIMIT 1").fetchone())
    case.pop("id")
    case.update(status="AMBIGUOUS", reason_code="MULTIPLE_COMPATIBLE_CANDIDATES",
                selected_listing_id=None, candidate_count=2, evidence_hash="c" * 64)
    s.db.execute(f"INSERT INTO instrument_resolution_cases ({','.join(case)}) VALUES ({','.join('?' for _ in case)})",
                 tuple(case.values()))
    s.db.commit()
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        confirm(s, a, c)


class CommitClock:
    def __init__(self, connection, clock, increment=1_000_000):
        self.connection, self.clock, self.increment = connection, clock, increment

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def commit(self):
        self.connection.commit()
        self.clock.now += self.increment


def test_identity_and_metadata_are_not_known_before_actual_raw_commit():
    s = system()
    a = asset()
    original = s.clock.now
    proxy = CommitClock(s.db, s.clock)
    s.archive.connection = proxy
    s.identity.connection = proxy
    c = capture(s, [a])
    with pytest.raises(ValueError, match="METADATA_MISSING"):
        s.archive.read_capture(c, "ASSETS", original)
    before = s.clock.now
    result = confirm(s, a, c)
    assert read(s, cutoff=before) is None
    current = read(s)
    assert current["id"] == result.identity_version_id and current["available_at_ns"] > before


def test_missing_publication_never_exposes_raw_identity():
    s = system()
    a = asset()
    c = capture(s, [a])
    confirm(s, a, c)
    publications = s.db.execute("""SELECT id FROM intraday_capture_events
        WHERE json_extract(payload_json,'$.metadata_kind')='PUBLICATION'""").fetchall()
    assert len(publications) == 2
    s.db.execute("DROP TRIGGER trg_intraday_capture_events_no_delete")
    s.db.execute("DELETE FROM intraday_capture_events WHERE id=?", (publications[-1][0],))
    s.db.commit()
    assert read(s) is None


def test_local_record_obeys_the_frozen_frame_bound():
    s = system(frame_bytes=64)
    with pytest.raises(ValueError, match="METADATA_INVALID"):
        s.archive.record_assets([asset()], received_at_ns=s.clock.now)
    assert s.db.execute("SELECT COUNT(*) FROM intraday_capture_events").fetchone()[0] == 0


def test_full_asset_master_is_chunked_with_an_immutable_complete_header():
    s = system(frame_bytes=16 * 1024 * 1024)
    rows = [asset(symbol=f"S{i}") for i in range(8000)]
    c = s.archive.record_assets(rows, received_at_ns=s.clock.now)
    metadata = s.archive.read_capture(c, "ASSETS")
    assert len(metadata["assets"]) == len(rows)
    assert len(metadata["payload"]["chunks"]) > 1
    assert len(metadata["payload_json"].encode()) <= 1_048_576
    for row in s.db.execute("SELECT payload_json FROM intraday_capture_events"):
        assert len(row[0].encode()) <= 1_048_576
    a = rows[0]
    s.db.execute("UPDATE instrument_listings SET ticker=? WHERE id=?", (a["symbol"], s.listing))
    s.db.commit()
    confirm(s, a, c)
    assert read(s)["broker_asset_id"] == a["id"]
    chunk_id = metadata["payload"]["chunks"][0]["id"]
    s.db.execute("DROP TRIGGER trg_intraday_capture_events_no_delete")
    s.db.execute("DELETE FROM intraday_capture_events WHERE id=?", (chunk_id,))
    s.db.commit()
    with pytest.raises(ValueError, match="METADATA_MISSING"):
        s.archive.read_capture(c, "ASSETS")
