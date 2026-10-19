import hashlib
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest
from swing_research_fixtures import data_record, local_packet, utc_ns

from backend.app.swing_research.calendar import Session, TradingCalendar, fx_at
from backend.app.swing_research.contracts import (
    DataContext,
    DatasetManifest,
    ResourceLimits,
    SwingError,
)
from backend.app.swing_research.datasets import Dataset


def open_packet(tmp_path, rows=None, limits=None, **changes):
    root, manifest = local_packet(tmp_path, rows if rows is not None else [data_record()], **changes)
    return Dataset(
        root, manifest, expected_hash=manifest.dataset_hash, resources=limits or ResourceLimits(8_388_608)
    ), root


def test_review_actual_basis_overrides_optimistic_manifest_label(tmp_path):
    row = data_record()
    unknown = type(row).from_dict(row.to_dict() | {"data": row.data | {"basis": "UNKNOWN"}})
    dataset, _ = open_packet(tmp_path, [unknown])
    report = dataset.verify()
    assert report.state == "INSUFFICIENTE" and "UNKNOWN_ADJUSTMENT" in report.issues


def test_review_revisions_do_not_inflate_daily_coverage(tmp_path):
    row = data_record()
    revision = type(row).from_dict(row.to_dict() | {"version": 2, "available_ns": row.available_ns + 1})
    dataset, _ = open_packet(tmp_path, [row, revision], expected_daily_rows=1)
    report = dataset.verify()
    assert report.rows == 2 and report.daily_observed == report.daily_expected == 1


def test_review_daily_same_version_different_timestamp_is_duplicate(tmp_path):
    row = data_record()
    duplicate = type(row).from_dict(
        row.to_dict() | {"event_ns": row.event_ns + 1, "available_ns": row.available_ns + 1}
    )
    dataset, _ = open_packet(tmp_path, [row, duplicate])
    with pytest.raises(SwingError):
        dataset.verify()


def test_review_partition_bounds_match_observed_bounds(tmp_path):
    root, manifest = local_packet(tmp_path, [data_record()])
    part = replace(manifest.partitions[0], first_session="2019-12-31")
    changed = replace(manifest, partitions=(part,))
    dataset = Dataset(root, changed, expected_hash=changed.dataset_hash, resources=ResourceLimits(8_388_608))
    with pytest.raises(SwingError):
        dataset.verify()


def test_review_calendar_revision_changes_same_logical_session(tmp_path):
    day = "2020-11-27"
    payload = {"open_ns": utc_ns(day + "T14:30:00Z"), "close_ns": utc_ns(day + "T21:00:00Z"), "source_hash": "a" * 64}
    original = data_record("SESSION", "NYSE", day, event_ns=payload["close_ns"], available_ns=10, data=payload)
    revised = type(original).from_dict(
        original.to_dict()
        | {
            "event_ns": utc_ns(day + "T18:00:00Z"),
            "version": 2,
            "available_ns": 20,
            "data": payload | {"close_ns": utc_ns(day + "T18:00:00Z")},
        }
    )
    dataset, _ = open_packet(tmp_path, [original, revised])
    assert list(dataset.as_of("SESSION", 15)) == [original]
    assert list(dataset.as_of("SESSION", 20)) == [revised]


def test_review_settlement_calendar_must_be_known_at_cutoff():
    calendar = TradingCalendar(
        (Session("2020-11-25", utc_ns("2020-11-25T14:30:00Z"), utc_ns("2020-11-25T21:00:00Z"), 20),),
        ("2020-11-25", "2020-11-27"),
        "a" * 64,
    )
    with pytest.raises(SwingError):
        calendar.settlement("2020-11-25", asof_ns=19)
    assert calendar.settlement("2020-11-25", asof_ns=20) == "2020-11-27"


def test_review_calendar_rejects_wrong_pinned_calendar_hash(tmp_path):
    day = "2020-11-27"
    row = data_record(
        "SESSION",
        "NYSE",
        day,
        available_ns=1,
        data={"open_ns": utc_ns(day + "T14:30:00Z"), "close_ns": utc_ns(day + "T18:00:00Z"), "source_hash": "a" * 64},
    )
    dataset, _ = open_packet(tmp_path, [row])
    with pytest.raises(SwingError, match="^MANIFEST_MISMATCH$"):
        dataset.calendar(settlement_days=(day,), source_hash="a" * 64, cutoff_ns=2)


def test_review_incompatible_rights_refuse_contents_before_open(tmp_path, monkeypatch):
    dataset, root = open_packet(tmp_path, rights="INCOMPATIBLE")

    def forbidden(*args, **kwargs):
        pytest.fail("incompatible contents opened")

    monkeypatch.setattr(type(root), "open", forbidden)
    with pytest.raises(SwingError, match="^NON_IDONEO$"):
        dataset.verify()


def test_review_late_older_version_cannot_resurrect_corrected_bar(tmp_path):
    row = data_record()
    old = type(row).from_dict(row.to_dict() | {"available_ns": row.available_ns + 100})
    newer = type(row).from_dict(
        row.to_dict() | {"version": 2, "available_ns": row.available_ns + 10, "data": row.data | {"close": "9"}}
    )
    dataset, _ = open_packet(tmp_path, [old, newer])
    assert list(dataset.as_of("DAILY", row.available_ns + 20)) == [newer]
    assert list(dataset.as_of("DAILY", row.available_ns + 200)) == [newer]


def test_review_fx_older_version_cannot_replace_corrected_fix():
    payload = {"base": "USD", "quote": "EUR", "eur_per_usd": "0.9", "source_hash": "a" * 64}
    old = data_record("FX", "USDEUR", event_ns=100, available_ns=150, data=payload)
    newer = type(old).from_dict(
        old.to_dict() | {"version": 2, "available_ns": 120, "data": payload | {"eur_per_usd": "0.8"}}
    )
    assert fx_at([newer, old], 200).eur_per_usd == Decimal("0.8")


def test_review_no_trade_bar_cannot_supply_invented_flat_ohlc(tmp_path):
    row = data_record()
    no_trade = type(row).from_dict(row.to_dict() | {"data": row.data | {"status": "NO_TRADES", "volume": "0"}})
    dataset, _ = open_packet(tmp_path, [no_trade])
    with pytest.raises(SwingError):
        dataset.verify()


def test_public_packet_integrates_calendar_identity_fx_and_split_without_writes(tmp_path, monkeypatch):
    from swing_research_fixtures import action_record, listing_record

    from backend.app.swing_research.events import CorporateAction, split_adjust
    from backend.app.swing_research.universe import RawBar, resolve_ticker

    days = ("2019-12-31", "2020-01-02", "2020-01-03")
    known = utc_ns("2018-01-01T00:00:00Z")
    sessions = tuple(Session(day, utc_ns(day + "T14:30:00Z"), utc_ns(day + "T21:00:00Z"), known) for day in days)
    expected = TradingCalendar(sessions, days, "a" * 64)
    rows = [data_record(), listing_record(), action_record()]
    rows.extend(
        data_record(
            "SESSION",
            "NYSE",
            s.day,
            event_ns=s.close_ns,
            available_ns=known,
            data={"open_ns": s.open_ns, "close_ns": s.close_ns, "source_hash": "a" * 64},
        )
        for s in sessions
    )
    rows.append(
        data_record("FX", "USDEUR", data={"base": "USD", "quote": "EUR", "eur_per_usd": "0.9", "source_hash": "a" * 64})
    )
    dataset, root = open_packet(tmp_path, rows, calendar_hash=expected.calendar_hash)
    original_open = type(root).open

    def readonly(path, mode="r", *args, **kwargs):
        assert mode in ("r", "rb")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(type(root), "open", readonly)
    cutoff = utc_ns("2020-01-03T20:20:00Z")
    calendar = dataset.calendar(settlement_days=days, source_hash="a" * 64, cutoff_ns=cutoff)
    assert calendar == expected
    assert resolve_ticker(dataset.as_of("IDENTITY", cutoff), "TL000", "2020-01-03", cutoff).listing_id == "L000"
    bar = RawBar.from_record(next(dataset.as_of("DAILY", cutoff)))
    actions = [CorporateAction.from_record(record) for record in dataset.as_of("ACTION", cutoff)]
    assert split_adjust(bar, actions, cutoff).close == Decimal("5")
    assert fx_at(dataset.as_of("FX", cutoff), cutoff).eur_per_usd == Decimal("0.9")
    assert dataset.verify().economic_gate == "NOT_EVALUATED"


def test_documented_no_trade_is_preserved_as_absence_not_imputed_ohlc(tmp_path):
    row = data_record()
    data = row.data | {"open": None, "high": None, "low": None, "close": None, "volume": "0", "status": "NO_TRADES"}
    no_trade = type(row).from_dict(row.to_dict() | {"data": data})
    dataset, _ = open_packet(tmp_path, [no_trade])
    result = next(dataset.as_of("DAILY", no_trade.available_ns))
    assert result.data["close"] is None and result.data["status"] == "NO_TRADES"


def test_review_holdout_gaps_cannot_expose_per_listing_metadata(tmp_path):
    from backend.app.swing_research.contracts import DataGap

    _, manifest = local_packet(tmp_path, [data_record()])
    with pytest.raises(SwingError, match="^HOLDOUT_SEALED$"):
        replace(manifest, gaps=(DataGap("DAILY", "L000", "2024-01-02", "2024-01-03", "HALT"),))


def test_review_wrong_event_date_cannot_hide_behind_public_partition_label(tmp_path):
    row = data_record()
    wrong = type(row).from_dict(
        row.to_dict() | {"event_ns": utc_ns("2025-01-02T21:00:00Z"), "available_ns": utc_ns("2025-01-02T21:00:00Z")}
    )
    dataset, _ = open_packet(tmp_path, [wrong])
    with pytest.raises(SwingError):
        dataset.verify()


def test_review_calendar_source_must_match_pinned_snapshot(tmp_path):
    day = "2020-11-27"
    session = Session(day, utc_ns(day + "T14:30:00Z"), utc_ns(day + "T18:00:00Z"), 1)
    expected = TradingCalendar((session,), (day,), "a" * 64)
    row = data_record(
        "SESSION",
        "NYSE",
        day,
        event_ns=session.close_ns,
        available_ns=1,
        data={"open_ns": session.open_ns, "close_ns": session.close_ns, "source_hash": "b" * 64},
    )
    dataset, _ = open_packet(tmp_path, [row], calendar_hash=expected.calendar_hash)
    with pytest.raises(SwingError, match="^MANIFEST_MISMATCH$"):
        dataset.calendar(settlement_days=(day,), source_hash="a" * 64, cutoff_ns=2)


def test_review_decoded_charge_covers_retained_python_object_graph(tmp_path):
    import sys

    dataset, _ = open_packet(
        tmp_path, [data_record(key=f"L{i:03d}") for i in range(25)], ResourceLimits(8_388_608, max_batch_bytes=5000)
    )

    def retained_size(value, seen):
        if id(value) in seen:
            return 0
        seen.add(id(value))
        result = sys.getsizeof(value)
        if isinstance(value, dict):
            result += sum(retained_size(key, seen) + retained_size(item, seen) for key, item in value.items())
        elif isinstance(value, (tuple, list)):
            result += sum(retained_size(item, seen) for item in value)
        elif hasattr(value, "__dict__"):
            result += retained_size(vars(value), seen)
        return result

    for batch in dataset.iter_batches("DAILY"):
        assert retained_size(batch.records, set()) <= batch.decoded_bytes <= 5000


def test_manifest_frozen_roundtrip_and_hash_covers_all_metadata(tmp_path):
    root, manifest = local_packet(tmp_path, [data_record()])
    with pytest.raises(FrozenInstanceError):
        manifest.currency = "EUR"
    assert DatasetManifest.from_dict(manifest.to_dict()) == manifest
    for changes in [
        {"calendar_hash": "e" * 64},
        {"price_basis": "UNKNOWN"},
        {"universe_basis": "CURRENT"},
        {"holdout": replace(manifest.holdout, sha256="f" * 64)},
    ]:
        assert replace(manifest, **changes).dataset_hash != manifest.dataset_hash
    with pytest.raises(SwingError):
        Dataset(root, manifest, expected_hash="a" * 64, resources=ResourceLimits(8_388_608))


def test_readonly_verified_stream_and_exact_row_byte_limits(tmp_path, monkeypatch):
    rows = [data_record(key=f"L{i:03d}") for i in range(25)]
    dataset, root = open_packet(tmp_path, rows, ResourceLimits(8_388_608, max_batch_rows=7, max_batch_bytes=5000))
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    report = dataset.verify()
    batches = list(dataset.iter_batches("DAILY"))
    assert sum(len(batch.records) for batch in batches) == 25
    assert all(0 < len(batch.records) <= 7 and batch.decoded_bytes <= 5000 for batch in batches)
    assert report.rows == 25 and report.daily_observed == 25 and report.daily_expected == 25
    assert report.state == "SYNTHETIC_ONLY"
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


@pytest.mark.parametrize("fault", ["hash", "count", "order", "duplicate", "truncated", "float", "unknown_field"])
def test_corruption_rejected_before_first_batch(tmp_path, fault):
    dataset, root = open_packet(tmp_path, [data_record(key="L001"), data_record(key="L002")])
    manifest = dataset.manifest
    part = manifest.partitions[0]
    path = root / part.path
    raw = path.read_bytes()
    if fault == "hash":
        path.write_bytes(raw.replace(b'"close":"10"', b'"close":"12"'))
    elif fault == "count":
        manifest = replace(manifest, partitions=(replace(part, rows=3),))
    else:
        lines = raw.splitlines(keepends=True)
        if fault == "order":
            raw = b"".join(reversed(lines))
        elif fault == "duplicate":
            raw = lines[0] + lines[0]
        elif fault == "truncated":
            raw = raw[:-2]
        elif fault == "float":
            raw = raw.replace(b'"close":"10"', b'"close":10.0')
        else:
            raw = raw.replace(b'"data":{', b'"data":{"extra":true,')
        path.write_bytes(raw)
        manifest = replace(
            manifest, partitions=(replace(part, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)),)
        )
    checked = Dataset(root, manifest, expected_hash=manifest.dataset_hash, resources=ResourceLimits(8_388_608))
    with pytest.raises(SwingError):
        next(checked.iter_batches("DAILY"))


def test_revision_asof_and_future_bar_cannot_change_old_result(tmp_path):
    original = data_record()
    revised = data_record(
        version=2, available_ns=original.available_ns + 3600_000_000_000, data=original.data | {"close": "9"}
    )
    future = data_record(session="2020-01-03")
    dataset, _ = open_packet(tmp_path, [original, revised, future])
    assert list(dataset.as_of("DAILY", original.available_ns)) == [original]
    assert list(dataset.as_of("DAILY", revised.available_ns)) == [revised]


def test_late_mutation_never_returns_an_unverified_batch(tmp_path):
    dataset, root = open_packet(
        tmp_path, [data_record(key=f"L{i:03d}") for i in range(4)], ResourceLimits(8_388_608, max_batch_rows=1)
    )
    stream = dataset.iter_batches("DAILY")
    assert next(stream).records[0].key == "L000"
    path = root / dataset.manifest.partitions[0].path
    path.write_bytes(path.read_bytes().replace(b'"close":"10"', b'"close":"12"'))
    with pytest.raises(SwingError):
        next(stream)


@pytest.mark.parametrize(
    "change,issue",
    [
        ({"price_basis": "UNKNOWN"}, "UNKNOWN_ADJUSTMENT"),
        ({"universe_basis": "CURRENT"}, "UNIVERSE_NOT_ASOF"),
        ({"rights": "UNKNOWN", "rights_hash": None}, "RIGHTS_UNATTESTED"),
        ({"coverage_hash": None}, "COVERAGE_UNATTESTED"),
    ],
)
def test_metadata_gaps_never_promote_source_or_survivors(tmp_path, change, issue):
    dataset, _ = open_packet(tmp_path, **change)
    report = dataset.verify()
    assert report.state == "INSUFFICIENTE" and issue in report.issues


def test_real_label_and_modeled_availability_do_not_attest_pit(tmp_path):
    dataset, _ = open_packet(tmp_path, context=DataContext("REAL", "HISTORICAL_CURRENT", "SIP"), rights="ALLOWED")
    report = dataset.verify()
    assert report.state == "INSUFFICIENTE" and "MODELED_AVAILABILITY" in report.issues
    assert report.economic_gate == "NOT_EVALUATED"


def test_holdout_is_only_opaque_metadata_and_cannot_be_read(tmp_path, monkeypatch):
    dataset, root = open_packet(tmp_path)
    (root / "holdout.ndjson").write_text("synthetic forbidden sentinel", encoding="utf-8")
    original = type(root).open

    def guarded(path, *args, **kwargs):
        if path.name == "holdout.ndjson":
            pytest.fail("holdout content was opened")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(type(root), "open", guarded)
    assert dataset.verify().rows == 1
    with pytest.raises(SwingError, match="^HOLDOUT_SEALED$"):
        next(dataset.iter_batches("HOLDOUT"))
    part = replace(dataset.manifest.partitions[0], first_session="2024-01-02", last_session="2024-01-02")
    with pytest.raises(SwingError):
        replace(dataset.manifest, partitions=(part,))


@pytest.mark.parametrize("limit", ["disk", "batch", "rss"])
def test_resources_fail_closed_without_truncation(tmp_path, monkeypatch, limit):
    import backend.app.swing_research.datasets as module

    limits = (
        ResourceLimits(1)
        if limit == "disk"
        else ResourceLimits(8_388_608, max_batch_bytes=1)
        if limit == "batch"
        else ResourceLimits(8_388_608, max_rss_bytes=1)
    )
    if limit == "rss":
        monkeypatch.setattr(module, "current_rss", lambda: 100)
    with pytest.raises(SwingError, match="^RESOURCE_LIMIT$"):
        dataset, _ = open_packet(tmp_path, limits=limits)
        list(dataset.iter_batches("DAILY"))


@pytest.mark.parametrize(
    "path",
    ["../outside.ndjson", "/outside.ndjson", "data/investedge.db", ".env", r"\\synthetic.invalid\share\data.ndjson"],
)
def test_partition_paths_rejected_syntactically(tmp_path, path):
    _, manifest = local_packet(tmp_path, [data_record()])
    with pytest.raises(SwingError):
        replace(manifest.partitions[0], path=path)


def test_hardlinked_input_is_rejected(tmp_path):
    import os

    dataset, root = open_packet(tmp_path)
    os.link(root / dataset.manifest.partitions[0].path, tmp_path / "alias")
    with pytest.raises(SwingError):
        dataset.verify()


@pytest.mark.parametrize(
    "day,close,italian",
    [("2020-10-19", "20:00", "21:15"), ("2020-10-26", "20:00", "20:15"), ("2020-11-27", "18:00", "18:15")],
)
def test_calendar_explicit_close_dst_halfday_and_relative_windows(day, close, italian):
    session = Session(day, utc_ns(day + "T14:30:00Z"), utc_ns(day + "T" + close + ":00Z"), 1)
    calendar = TradingCalendar((session,), (day,), "a" * 64)
    window = calendar.window(day, asof_ns=session.open_ns)
    assert window.information_ns == session.close_ns - 55 * 60_000_000_000
    assert window.decision_ns == session.close_ns - 40 * 60_000_000_000
    assert window.italian_window()[0].strftime("%H:%M") == italian
    with pytest.raises(SwingError):
        calendar.get("2020-12-25", asof_ns=session.open_ns)


def test_calendar_or_fx_not_available_at_cutoff_is_not_backfilled():
    day = "2020-01-02"
    calendar = TradingCalendar(
        (Session(day, utc_ns(day + "T14:30:00Z"), utc_ns(day + "T21:00:00Z"), 10),), (day,), "a" * 64
    )
    with pytest.raises(SwingError):
        calendar.get(day, asof_ns=9)
    fix = data_record(
        "FX",
        "USDEUR",
        day,
        event_ns=100,
        available_ns=110,
        data={"base": "USD", "quote": "EUR", "eur_per_usd": "0.9", "source_hash": "a" * 64},
    )
    future = data_record(
        "FX", "USDEUR", day, event_ns=101, available_ns=200, version=2, data=fix.data | {"eur_per_usd": "0.5"}
    )
    assert fx_at([fix, future], 150).eur_per_usd == Decimal("0.9")
    with pytest.raises(SwingError):
        fx_at([fix], 109)
    with pytest.raises(SwingError):
        fx_at([fix], 110 + 8 * 86400_000_000_000)


def test_explicit_settlement_days_are_used_not_weekday_arithmetic():
    calendar = TradingCalendar(
        (Session("2020-11-25", utc_ns("2020-11-25T14:30:00Z"), utc_ns("2020-11-25T21:00:00Z"), 0),),
        ("2020-11-25", "2020-11-27", "2020-11-30"),
        "a" * 64,
    )
    assert calendar.settlement("2020-11-25", lag=1, asof_ns=utc_ns("2020-11-25T22:00:00Z")) == "2020-11-27"
    with pytest.raises(SwingError):
        calendar.settlement("2020-11-30", lag=1, asof_ns=utc_ns("2020-11-30T22:00:00Z"))
