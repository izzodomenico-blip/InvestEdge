from __future__ import annotations

import json

import pytest
from test_intraday_identity import SECOND, asset, capture, confirm, ns, resolved, system
from test_us_calendar import calendar


def prepare(s, **attestation):
    a = asset()
    c = capture(s, [a])
    identity = confirm(s, a, c, **attestation)
    calendar(s, [{"date": "2026-10-12", "open": "09:30", "close": "16:00"}], "2026-10-12", "2026-10-12")
    return a, identity


def freeze(s, **extra):
    return s.universe.freeze([s.listing], "2026-10-12", s.clock.now, **extra)


def test_prospective_universe_is_immutable_after_future_metadata_and_canonical_changes():
    s = system()
    a, identity = prepare(s)
    snapshot = freeze(s)
    before = s.universe.read(snapshot.snapshot_id)
    assert before["members"][0]["identity_version_id"] == identity.identity_version_id
    assert before["members"][0]["eligible"] is True
    assert before["manifest"]["kind"] == "PROSPECTIVE"
    s.clock.now += SECOND
    capture(s, [{**a, "status": "inactive", "tradable": False}])
    s.db.execute("UPDATE instrument_listings SET listing_status='DELISTED', ticker='RENAMED'")
    s.db.commit()
    assert s.universe.read(snapshot.snapshot_id) == before
    later = s.universe.read(freeze(s).snapshot_id)
    assert later["members"][0]["reason_code"] == "ASSET_INACTIVE"
    assert later["manifest"]["digest"] != before["manifest"]["digest"]


@pytest.mark.parametrize("leveraged,inverse,reason", [
    ("UNKNOWN", "UNKNOWN", "PRODUCT_LEVERAGE_UNKNOWN"), ("YES", "NO", "LEVERAGED_PRODUCT"),
    ("NO", "YES", "INVERSE_PRODUCT"), ("NO", "UNKNOWN", "PRODUCT_LEVERAGE_UNKNOWN"),
    ("NO", "NO", None),
])
def test_etf_requires_explicit_unleveraged_noninverse_attestation(leveraged, inverse, reason):
    s = system(instrument_type="ETF")
    prepare(s, leveraged=leveraged, inverse=inverse)
    member = s.universe.read(freeze(s).snapshot_id)["members"][0]
    assert member["reason_code"] == reason
    assert member["eligible"] is (reason is None)


def test_marginable_stock_is_not_inferred_to_be_a_leveraged_product():
    s = system()
    a = asset(marginable=True)
    c = capture(s, [a])
    confirm(s, a, c)
    calendar(s, [{"date": "2026-10-12", "open": "09:30", "close": "16:00"}], "2026-10-12", "2026-10-12")
    assert s.universe.read(freeze(s).snapshot_id)["members"][0]["eligible"] is True


def test_unconfirmed_and_unresolved_legacy_stays_explicitly_excluded():
    s = system()
    calendar(s, [{"date": "2026-10-12", "open": "09:30", "close": "16:00"}], "2026-10-12", "2026-10-12")
    result = s.universe.read(freeze(s).snapshot_id)
    assert result["members"] == []
    assert result["manifest"]["exclusions"] == [{"listing_id": s.listing, "reason_code": "IDENTITY_UNVERIFIED"}]
    assert s.db.execute("SELECT COUNT(*) FROM intraday_identity_versions").fetchone()[0] == 0


@pytest.mark.parametrize("when", ["2026-10-12T13:30:00Z", "2026-10-12T14:00:00Z"])
def test_strict_universe_cannot_be_constructed_at_or_after_open(when):
    s = system()
    prepare(s)
    s.clock.now = ns(when)
    with pytest.raises(ValueError, match="SNAPSHOT_NOT_PIT"):
        freeze(s)


def test_past_cutoff_cannot_backdate_a_new_snapshot():
    s = system()
    prepare(s)
    before = s.clock.now
    s.clock.now += SECOND
    snapshot = s.universe.freeze([s.listing], "2026-10-12", before)
    row = s.db.execute("SELECT cutoff_ns, available_at_ns FROM intraday_universe_snapshots WHERE id=?",
                       (snapshot.snapshot_id,)).fetchone()
    assert row["cutoff_ns"] == before and row["available_at_ns"] > before
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        s.universe.read(snapshot.snapshot_id, cutoff_ns=before)


def test_research_universe_is_explicitly_retrospective_never_strict():
    s = system(provenance="HISTORICAL_CURRENT", replay_grade="RESEARCH_ONLY")
    prepare(s)
    s.clock.now = ns("2026-10-12T18:00:00Z")
    result = s.universe.read(freeze(s).snapshot_id)
    assert result["manifest"]["kind"] == "RETROSPECTIVE"
    assert result["replay_grade"] == "RESEARCH_ONLY"


def test_universe_is_atomic_on_member_failure_and_read_rejects_incomplete_header():
    s = system()
    prepare(s)
    s.db.execute("""CREATE TRIGGER injected_failure BEFORE INSERT ON intraday_universe_members
                    BEGIN SELECT RAISE(ABORT, 'fixture_failure'); END""")
    s.db.commit()
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        freeze(s)
    assert s.db.execute("SELECT COUNT(*) FROM intraday_universe_snapshots").fetchone()[0] == 0
    s.db.execute("DROP TRIGGER injected_failure")
    s.db.commit()
    snapshot = freeze(s)
    s.db.execute("DROP TRIGGER trg_intraday_universe_members_no_delete")
    s.db.execute("DELETE FROM intraday_universe_members WHERE snapshot_id=?", (snapshot.snapshot_id,))
    s.db.commit()
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        s.universe.read(snapshot.snapshot_id)


def test_deterministic_member_order_and_listing_limits():
    s = system()
    prepare(s)
    _, other = resolved(s.db, ticker="MSFT", second=True)
    first = s.universe.freeze([other, s.listing], "2026-10-12", s.clock.now)
    second = s.universe.freeze([s.listing, other], "2026-10-12", s.clock.now)
    assert s.universe.read(first.snapshot_id)["manifest"] == s.universe.read(second.snapshot_id)["manifest"]
    with pytest.raises(ValueError, match="METADATA_INVALID"):
        s.universe.freeze([s.listing] * 2, "2026-10-12", s.clock.now)
    payload = json.dumps(s.universe.read(first.snapshot_id))
    assert s.config.alpaca_api_key_id not in payload and s.config.alpaca_api_secret_key not in payload


def test_partial_mapping_is_excluded_from_first_operational_universe():
    s = system()
    a = asset()
    c = capture(s, [a])
    from test_intraday_identity import mapping

    from backend.app.models import AlpacaIdentityApplyIn
    request = mapping(s, a, c).model_copy(update={"capabilities": ["BAR"]})
    preview = s.identity.preview(s.listing, request)
    s.identity.apply(s.listing, AlpacaIdentityApplyIn(**request.model_dump(), confirmation_token=preview.confirmation_token))
    calendar(s, [{"date": "2026-10-12", "open": "09:30", "close": "16:00"}], "2026-10-12", "2026-10-12")
    member = s.universe.read(freeze(s).snapshot_id)["members"][0]
    assert member["eligible"] is False and member["reason_code"] == "CAPABILITY_UNVERIFIED"


def test_changed_asset_class_is_excluded():
    s = system()
    a, _ = prepare(s)
    s.clock.now += SECOND
    capture(s, [{**a, "class": "crypto"}])
    member = s.universe.read(freeze(s).snapshot_id)["members"][0]
    assert member["eligible"] is False and member["reason_code"] == "IDENTITY_UNVERIFIED"


@pytest.mark.parametrize("source", ["calendar", "calendar_capture", "assets_capture"])
def test_snapshot_read_rejects_missing_frozen_sources(source):
    s = system()
    prepare(s)
    result = freeze(s)
    manifest = s.universe.read(result.snapshot_id)["manifest"]
    if source == "calendar":
        table, row_id = "intraday_calendar_versions", manifest["calendar_version_id"]
    else:
        table = "intraday_capture_events"
        row_id = manifest["calendar_capture_id" if source == "calendar_capture" else "metadata_capture_id"]
    s.db.execute(f"DROP TRIGGER trg_{table}_no_delete")
    s.db.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
    s.db.commit()
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        s.universe.read(result.snapshot_id)


def test_prospective_freeze_with_advancing_clock_keeps_actual_availability():
    s = system()
    prepare(s)
    cutoff = s.clock.now
    def advancing():
        s.clock.now += 1000
        return s.clock.now
    s.archive.clock_ns = advancing
    snapshot = s.universe.freeze([s.listing], "2026-10-12", cutoff)
    row = s.db.execute("SELECT available_at_ns, cutoff_ns FROM intraday_universe_snapshots WHERE id=?",
                       (snapshot.snapshot_id,)).fetchone()
    assert row["available_at_ns"] > cutoff and row["cutoff_ns"] == cutoff
    assert s.universe.read(snapshot.snapshot_id)["manifest"]["kind"] == "PROSPECTIVE"


def test_whole_snapshot_is_known_only_after_all_members_are_durable():
    from test_intraday_identity import CommitClock
    s = system()
    prepare(s)
    before = s.clock.now
    proxy = CommitClock(s.db, s.clock)
    s.archive.connection = proxy
    s.universe.connection = proxy
    result = s.universe.freeze([s.listing], "2026-10-12", before)
    raw = s.db.execute("SELECT available_at_ns FROM intraday_universe_snapshots WHERE id=?",
                       (result.snapshot_id,)).fetchone()[0]
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        s.universe.read(result.snapshot_id, cutoff_ns=raw)
    assert s.universe.read(result.snapshot_id)["known_at_ns"] > raw


def test_raw_commit_crossing_open_cannot_publish_prospective_universe():
    from test_intraday_identity import CommitClock
    s = system()
    prepare(s)
    s.clock.now = ns("2026-10-12T13:30:00Z") - 1000
    proxy = CommitClock(s.db, s.clock, increment=10_000)
    s.archive.connection = proxy
    s.universe.connection = proxy
    with pytest.raises(ValueError, match="SNAPSHOT_NOT_PIT"):
        s.universe.freeze([s.listing], "2026-10-12", s.clock.now)
    row = s.db.execute("SELECT id FROM intraday_universe_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if row is not None:
        with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
            s.universe.read(row[0])


@pytest.mark.parametrize("ids", [[{}], [True], [None], list(range(1, 32))])
def test_invalid_or_oversized_universe_is_sanitized(ids):
    s = system()
    with pytest.raises(ValueError, match="METADATA_INVALID"):
        s.universe.freeze(ids, "2026-10-12", s.clock.now)


def test_profile_without_market_news_rights_is_not_operational():
    s = system(profile_overrides={"attested_capabilities": ("assets", "calendar")})
    prepare(s)
    member = s.universe.read(freeze(s).snapshot_id)["members"][0]
    assert member["eligible"] is False and member["reason_code"] == "CAPABILITY_UNVERIFIED"


def test_failed_publication_leaves_unreadable_raw_snapshot():
    s = system()
    prepare(s)
    s.db.execute("""CREATE TRIGGER fail_publication BEFORE INSERT ON intraday_capture_events
        WHEN json_extract(NEW.payload_json,'$.metadata_kind')='PUBLICATION'
        BEGIN SELECT RAISE(ABORT, 'fixture_publication_failure'); END""")
    s.db.commit()
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        freeze(s)
    row = s.db.execute("SELECT id FROM intraday_universe_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    with pytest.raises(ValueError, match="SNAPSHOT_INPUT_MISSING"):
        s.universe.read(row[0])
