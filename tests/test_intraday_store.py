from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_intraday_identity import asset, capture, confirm, ns, resolved, system

from backend.app.intraday.contracts import EventEnvelope, canonical_json

SECOND = 1_000_000_000
MINUTE = 60 * SECOND
OPEN = ns("2026-10-12T13:30:00Z")


def prepared(*, second=False, history=False, **overrides):
    s = system(**overrides)
    if s.profile.feed != s.config.alpaca_feed:
        s.config = replace(s.config, alpaca_feed=s.profile.feed)
        s.archive.settings = s.archive.provider.settings = s.config
    rows = [asset()]
    if second:
        _, s.second = resolved(s.db, ticker="MSFT", second=True)
        rows.append(asset(symbol="MSFT"))
    batch = capture(s, rows)
    confirm(s, rows[0], batch)
    if second:
        confirm(s, rows[1], batch, listing=s.second)
    s.calendar.record([{"date": "2026-10-12", "open": "09:30", "close": "16:00"}],
                      start="2026-10-12", end="2026-10-12", received_at_ns=s.clock.now)
    s.clock.now = OPEN + 30 * MINUTE
    module = importlib.import_module("backend.app.intraday.store")
    s.store = module.IntradayStore(s.archive.provider, clock_ns=lambda: s.clock.now,
                                  provenance="HISTORICAL_CURRENT" if history else "CAPTURED",
                                  replay_grade="RESEARCH_ONLY" if history else "STRICT_PIT")
    return s


def event(s, *, kind="BAR", at=OPEN, received=None, change=None, capture_id="local-capture", source="STREAM"):
    market = importlib.import_module("backend.app.data_providers.alpaca_market")
    row = {"t": market.format_ns(at), "o": 100, "h": 102, "l": 99, "c": 101, "v": 10, "vw": 100.5, "n": 2}
    if kind == "QUOTE":
        row = {"t": market.format_ns(at), "bp": 100, "ap": 101, "bs": 2, "as": 3, "c": [], "bx": "Q", "ax": "Q", "z": "C"}
    row.update(change or {})
    decoded = market.decode_market_row(kind, row, source=source)
    return EventEnvelope("alpaca", s.profile.feed, s.profile.profile_id, "REAL", s.store.provenance,
                         s.store.replay_grade, kind, s.listing, f"{kind}:{s.listing}:{at}", capture_id, 1,
                         at, received or s.clock.now, s.clock.now, None, canonical_json(decoded),
                         availability_floor_ns=at + MINUTE if kind == "BAR" else 0)


def read(s, cutoff=None, kind="BAR"):
    return s.store.read_as_of(kind, cutoff_ns=s.clock.now if cutoff is None else cutoff)


def test_cumulative_global_sequence_uses_two_indexed_maxima_without_scanning_history():
    s = prepared()
    s.store.persist((event(s), event(s, kind='QUOTE')))
    before = s.store._sequence(None)
    queries = []
    s.db.set_trace_callback(queries.append)
    assert s.store._sequence(None) == before
    s.db.set_trace_callback(None)
    query = queries[-1]
    plan = ' '.join(row['detail'] for row in s.db.execute('EXPLAIN QUERY PLAN ' + query))
    assert 'UNION' not in query.upper()
    assert 'SEARCH intraday_observations' in plan and 'SEARCH intraday_capture_events' in plan
    assert 'SCAN intraday_' not in plan
    values = [row[0] for row in s.db.execute('SELECT ingest_sequence FROM intraday_observations UNION ALL SELECT ingest_sequence FROM intraday_capture_events')]
    assert before == max(values) + 1


def test_cumulative_admission_and_duplicate_queries_use_exact_source_indexes():
    s = prepared()
    ids = s.store.persist((event(s),), admit=False)
    queries = []
    s.db.set_trace_callback(queries.append)
    s.store.admit(ids)
    s.store.persist((event(s),))
    s.db.set_trace_callback(None)
    admissions = [q for q in queries if 'SELECT 1 FROM intraday_capture_events' in q and 'observation_id=' in q]
    duplicates = [q for q in queries if 'SELECT * FROM intraday_observations WHERE' in q and 'logical_key=' in q]
    assert admissions and duplicates
    for query in admissions + duplicates:
        plan = ' '.join(row['detail'] for row in s.db.execute('EXPLAIN QUERY PLAN ' + query))
        assert 'SCAN intraday_' not in plan
        assert ('observation_id=?' in plan if query in admissions else 'logical_key=?' in plan), plan


def test_cumulative_batch_decodes_identity_versions_once_per_knowledge_cutoff(monkeypatch):
    from backend.app.intraday import identity
    s = prepared(second=True)
    original, calls = identity._versions, []

    def measured(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(identity, '_versions', measured)
    quote = event(s, kind='QUOTE')
    s.store.persist((quote, replace(quote, listing_id=s.second, logical_key='QUOTE:second:one')))
    assert calls == [s.clock.now]
    s.clock.now += SECOND
    s.store.persist((replace(quote, received_at_ns=s.clock.now, persisted_at_ns=s.clock.now),))
    assert calls == [s.clock.now - SECOND, s.clock.now]


@pytest.mark.parametrize('external', [False, True])
def test_cumulative_batch_identity_reuse_invalidates_on_database_writes(monkeypatch, tmp_path, external):
    import copy
    import sqlite3

    from backend.app.intraday.identity import IdentityService
    from backend.app.models import AlpacaIdentityApplyIn, AlpacaIdentityPreviewIn

    s = prepared()
    if external:
        path = tmp_path / 'isolated.db'
        primary = sqlite3.connect(path)
        primary.row_factory = sqlite3.Row
        s.db.backup(primary)
        s.db.close()
        s.db = s.store.connection = s.store.archive.connection = s.store.provider.connection = primary
        writer = sqlite3.connect(path)
        writer.row_factory = sqlite3.Row
        writer.execute('PRAGMA foreign_keys=ON')
    else:
        writer = s.db
    archive = copy.copy(s.store.archive)
    archive.connection = writer
    service = IdentityService(archive)
    capture_id = writer.execute("SELECT id FROM intraday_capture_events WHERE json_extract(payload_json,'$.metadata_kind')='ASSETS' LIMIT 1").fetchone()[0]
    broker = archive.read_capture(capture_id, 'ASSETS')['assets'][0]['id']
    request = AlpacaIdentityPreviewIn(metadata_capture_id=capture_id, broker_asset_id=broker,
                                      capabilities=['NEWS'], evidence_hash='b' * 64)
    original, calls = s.store._prepare, []

    def change_after_first(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            preview = service.preview(s.listing, request)
            service.apply(s.listing, AlpacaIdentityApplyIn(**request.model_dump(), confirmation_token=preview.confirmation_token))
        return result

    monkeypatch.setattr(s.store, '_prepare', change_after_first)
    s.store.persist((event(s, kind='QUOTE'), event(s, kind='QUOTE', at=OPEN + 1)))
    assert [row[0] for row in s.db.execute('SELECT quality FROM intraday_observations ORDER BY id')] == ['VALID', 'QUARANTINED']
    if external:
        writer.close()
    s.db.close()


def test_cumulative_scoped_read_decodes_only_requested_listings(monkeypatch):
    from backend.app.intraday import snapshots
    s = prepared(second=True)
    quote = event(s, kind='QUOTE')
    s.store.persist((quote, replace(quote, listing_id=s.second, logical_key='QUOTE:second:one')))
    original, seen = snapshots._decode_evidence, []

    def measured(value):
        if 'listing_id' in value:
            seen.append(value['listing_id'])
        return original(value)

    expected = [row for row in read(s, kind='QUOTE') if row['listing_id'] == s.listing]
    monkeypatch.setattr(snapshots, '_decode_evidence', measured)
    assert s.store.read_as_of('QUOTE', cutoff_ns=s.clock.now, listing_ids=(s.listing, s.listing)) == expected
    assert set(seen) == {s.listing}
    seen.clear()
    assert s.store.read_as_of('QUOTE', cutoff_ns=s.clock.now, listing_ids=()) == []
    assert not seen


def pages(kind):
    return json.loads((Path(__file__).parent / "fixtures" / "market_data" / f"alpaca_{kind}_pages.json").read_text())


def test_capture_start_freezes_transport_policy_for_replay():
    from test_intraday_collector import handshake, setup
    s = setup(alpaca_stream_silence_seconds=5)
    s.collector.start((s.listing,))
    handshake(s)
    start = next(row for row in s.store.read_capture_as_of(cutoff_ns=s.clock.now) if row['kind'] == 'CAPTURE_START')
    assert start['payload']['continuity_policy']['socket_silence_ns'] == 5 * SECOND
    s.store.archive.settings = replace(s.config, alpaca_stream_silence_seconds=100)
    assert next(row for row in s.store.read_capture_as_of(cutoff_ns=s.clock.now) if row['kind'] == 'CAPTURE_START') == start


def test_raw_is_invisible_until_post_commit_admission_and_receipt_hash():
    s = prepared()
    stamp = s.clock.now
    ids = s.store.persist((event(s),), admit=False)
    assert not s.db.in_transaction and not read(s)
    raw = s.db.execute("SELECT * FROM intraday_observations WHERE id=?", ids).fetchone()
    assert raw["available_at_ns"] is None and raw["admitted_at_ns"] is None
    s.clock.now += 9 * SECOND
    s.store.admit(ids)
    assert not read(s, stamp)
    row = read(s)[0]
    assert row["available_at_ns"] == s.clock.now and row["received_at_ns"] == stamp
    assert {k: v for k, v in row["payload"].items() if k != "intake_sequence"} == event(s).payload
    assert s.store.admit(ids) == ()


def test_durable_clock_is_measured_after_raw_commit(monkeypatch):
    s = prepared()
    raw_stamp = s.clock.now
    original = s.store.admit
    def after_commit(ids):
        assert not s.db.in_transaction
        s.clock.now += SECOND
        return original(ids)
    monkeypatch.setattr(s.store, "admit", after_commit)
    s.store.persist((event(s),))
    assert not read(s, raw_stamp)
    assert read(s)[0]["available_at_ns"] == raw_stamp + SECOND


def test_revisions_prefix_and_a_b_a_and_first_received_are_immutable():
    s = prepared()
    first = s.clock.now
    a = event(s)
    ids_a = s.store.persist((a,))
    before = read(s, first)
    s.clock.now += SECOND
    assert s.store.persist((replace(a, received_at_ns=s.clock.now, persisted_at_ns=s.clock.now),)) == ids_a
    assert read(s)[0]["received_at_ns"] == first
    b = event(s, change={"c": 100})
    s.store.persist((b,))
    s.clock.now += SECOND
    ids_return = s.store.persist((event(s),))
    assert ids_return != ids_a
    assert s.db.execute("SELECT count(*) FROM intraday_observations").fetchone()[0] == 3
    assert read(s, first) == before
    assert len(read(s)) == 1 and read(s)[0]["id"] == ids_return[0]


def test_quarantined_revision_does_not_resurrect_valid_bar():
    s = prepared()
    s.store.persist((event(s),))
    cutoff = s.clock.now
    s.clock.now += SECOND
    s.store.persist((event(s, change={"l": 200}),))
    assert read(s, cutoff)[0]["quality"] == "VALID"
    assert read(s)[0]["quality"] == "QUARANTINED"
    assert read(s)[0]["reason_code"] == "BAR_INVALID"


@pytest.mark.parametrize("change,reason", [({"bp": 102}, "QUOTE_CROSSED"), ({"bs": 0}, "QUOTE_ZERO_SIZE"),
                                            ({"ap": 0}, "QUOTE_INVALID"), ({"c": ["R"]}, "QUOTE_CONDITION_UNATTESTED")])
def test_quotes_quarantine_and_original_round_lots(change, reason):
    s = prepared()
    s.store.persist((event(s, kind="QUOTE", change=change),))
    row = read(s, kind="QUOTE")[0]
    assert row["quality"] == "QUARANTINED" and row["reason_code"] == reason
    assert row["payload"]["size_unit"] == "ROUND_LOTS"
    assert "bid_size_shares" not in row["payload"]


def test_late_quote_does_not_regress_and_stale_state_is_explicit():
    s = prepared()
    now = s.clock.now
    s.store.persist((event(s, kind="QUOTE", at=now - SECOND),))
    s.clock.now += SECOND
    s.store.persist((event(s, kind="QUOTE", at=now - 2 * SECOND, change={"bp": 98}),))
    current = s.store.quote_state(s.listing, cutoff_ns=s.clock.now)
    assert current["event_time_ns"] == now - SECOND and current["payload"]["raw"]["bp"] == 100
    s.clock.now += 1
    assert s.store.quote_state(s.listing, cutoff_ns=s.clock.now)["reason_code"] == "QUOTE_STALE"


def test_ns_precision_is_not_collapsed():
    s = prepared()
    for at in (OPEN + 1, OPEN + 2):
        s.store.persist((event(s, kind="QUOTE", at=at),))
    assert [row["event_time_ns"] for row in read(s, kind="QUOTE")] == [OPEN + 1, OPEN + 2]


@pytest.mark.parametrize("field,value", [("feed", "iex"), ("data_mode", "DEMO"),
                                        ("provenance", "HISTORICAL_CURRENT"), ("profile_id", "a" * 64)])
def test_envelope_namespace_cannot_cross_store(field, value):
    s = prepared()
    args = {field: value}
    if field == "data_mode":
        args.update(provenance="SYNTHETIC", replay_grade="RESEARCH_ONLY")
    if field == "provenance":
        args.update(replay_grade="RESEARCH_ONLY")
    with pytest.raises(ValueError):
        s.store.persist((replace(event(s), **args),))
    assert not read(s)


def test_source_version_conflict_and_duplicate():
    s = prepared()
    a = replace(event(s), source_revision_id="revision-1")
    ids = s.store.persist((a,))
    assert s.store.persist((a,)) == ids
    with pytest.raises(ValueError, match="SOURCE_REVISION_CONFLICT"):
        s.store.persist((replace(event(s, change={"c": 100}), source_revision_id="revision-1"),))
    assert read(s)[0]["id"] == ids[0]


def test_secret_and_archive_limit_fail_before_raw_write():
    s = prepared()
    a = event(s)
    with pytest.raises(ValueError):
        s.store.persist((replace(a, payload_json=canonical_json({"raw": {"t": s.config.alpaca_api_secret_key}})),))
    s.store.archive.settings = replace(s.config, alpaca_max_archive_bytes=1)
    with pytest.raises(ValueError, match="ARCHIVE_LIMIT"):
        s.store.persist((a,))
    assert s.db.execute("SELECT count(*) FROM intraday_observations").fetchone()[0] == 0


def test_pagination_visits_second_symbol_and_is_idempotent():
    s = prepared(second=True, history=True)
    s.queue.extend(pages("bars"))
    kwargs = {"kind": "BAR", "listing_ids": (s.listing, s.second), "start": "2026-10-12T13:30:00Z",
                  "end": "2026-10-12T13:32:00Z", "asof": "2026-10-12"}
    result = s.store.backfill(**kwargs)
    assert result["state"] == "COMPLETE" and result["pages"] == 2
    rows = read(s)
    assert {row["listing_id"] for row in rows} == {s.listing, s.second}
    assert all(row["provenance"] == "HISTORICAL_CURRENT" and row["replay_grade"] == "RESEARCH_ONLY" for row in rows)
    requests = len(s.requests)
    assert s.store.backfill(**kwargs)["state"] == "COMPLETE"
    assert len(s.requests) == requests
    assert s.db.execute("SELECT count(*) FROM intraday_observations").fetchone()[0] == 2
    progress = s.store.progress_as_of(cutoff_ns=s.clock.now)
    assert any(row["payload"]["phase"] == "CHUNK" and row["payload"]["complete"] for row in progress)


@pytest.mark.parametrize("failure", ["loop", "cancel", "page_cap", "invalid", "http"])
def test_interrupted_backfill_is_partial_preserves_page_and_can_resume(failure):
    s = prepared(second=True, history=True)
    fixture = pages("bars")
    s.queue.append(fixture[0])
    if failure == "loop":
        s.queue.append({**fixture[1], "next_page_token": "page2"})
    elif failure == "invalid":
        s.queue.append({"bars": {"MSFT": [{"t": "2026-10-12T13:30:00Z"}]}, "next_page_token": None})
    elif failure == "http":
        s.queue.append({"wrong": []})
    kwargs = {"kind": "BAR", "listing_ids": (s.listing, s.second), "start": "2026-10-12T13:30:00Z",
                  "end": "2026-10-12T13:32:00Z", "asof": "2026-10-12"}
    extra = {"max_pages": 1} if failure == "page_cap" else {}
    if failure == "cancel":
        extra["cancel"] = lambda: not s.queue
    result = s.store.backfill(**kwargs, **extra)
    assert result["state"] == "PARTIAL" and result["reason_code"]
    assert read(s)
    assert not any(row["payload"]["complete"] for row in s.store.progress_as_of(cutoff_ns=s.clock.now)
                   if row["payload"]["phase"] == "CHUNK")
    s.queue.clear()
    s.queue.extend(fixture)
    assert s.store.backfill(**kwargs)["state"] == "COMPLETE"
    assert len(read(s)) == 2


def test_rest_cannot_certify_strict_pit_and_unverified_identity_prevents_http():
    s = prepared()
    before = len(s.requests)
    kwargs = {"kind": "BAR", "listing_ids": (s.listing,), "start": "2026-10-12T13:30:00Z",
                  "end": "2026-10-12T13:32:00Z", "asof": "2026-10-12"}
    with pytest.raises(ValueError, match="MODE_MISMATCH"):
        s.store.backfill(**kwargs)
    s = prepared(history=True)
    before = len(s.requests)
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        s.store.backfill(**{**kwargs, "listing_ids": (999999,)})
    assert len(s.requests) == before


def test_rest_quote_size_is_unattested_feed_semantics_are_explicit():
    s = prepared(history=True)
    s.queue.extend(pages("quotes"))
    result = s.store.backfill(kind="QUOTE", listing_ids=(s.listing,), start="2026-10-12T13:30:00Z",
                              end="2026-10-12T13:32:00Z", asof="2026-10-12")
    assert result["state"] == "COMPLETE"
    assert {row["payload"]["size_unit"] for row in read(s, kind="QUOTE")} == {"SOURCE_UNATTESTED"}
    assert all(row["payload"]["raw"]["bs"] == 2 for row in read(s, kind="QUOTE"))


def test_future_timestamp_is_archived_quarantined_and_never_retrodated():
    s = prepared()
    now = s.clock.now
    ids = s.store.persist((event(s, kind="QUOTE", at=now + SECOND),))
    assert not read(s, kind="QUOTE")
    raw = s.db.execute("SELECT * FROM intraday_observations WHERE id=?", ids).fetchone()
    assert raw["quality"] == "QUARANTINED" and raw["reason_code"] == "TIMESTAMP_FUTURE"
    s.clock.now += SECOND
    s.store.admit(ids)
    assert read(s, kind="QUOTE")[0]["quality"] == "QUARANTINED"


def test_missing_quote_conditions_are_explicitly_unusable():
    s = prepared()
    a = event(s, kind="QUOTE")
    payload = json.loads(a.payload_json)
    del payload["raw"]["c"]
    s.store.persist((replace(a, payload_json=canonical_json(payload)),))
    assert read(s, kind="QUOTE")[0]["reason_code"] == "QUOTE_CONDITIONS_MISSING"


def test_same_ns_revision_keeps_original_cross_run_order():
    s = prepared()
    # An earlier run has a high sequence; later run has sequence=1 at the same timestamp.
    values = [replace(event(s, at=OPEN + i * MINUTE), ingest_sequence=i + 1) for i in range(5)]
    s.store.persist(values)
    s.store.persist((event(s, at=OPEN + 4 * MINUTE, change={"c": 100}, capture_id="capture-after-restart"),))
    row = next(row for row in read(s) if row["event_time_ns"] == OPEN + 4 * MINUTE)
    assert row["payload"]["raw"]["c"] == 100


def test_unconfirmed_mapping_is_quarantined_even_for_stream_persist():
    s = prepared()
    _, other = resolved(s.db, ticker="MSFT", second=True)
    s.store.persist((replace(event(s), listing_id=other, logical_key=f"BAR:{other}:{OPEN}"),))
    assert read(s)[0]["reason_code"] == "IDENTITY_UNVERIFIED"


def test_cancel_during_last_page_is_partial_and_persisted_as_of():
    from test_alpaca_market_provider import response
    s = prepared(history=True)
    cancelled = [False]
    original = s.provider if hasattr(s, "provider") else s.store.provider
    def handler(request):
        cancelled[0] = True
        return response({"bars": {"AAPL": pages("bars")[0]["bars"]["AAPL"]}, "next_page_token": None})
    import httpx

    from backend.app.data_providers.transport import SafeProviderTransport
    original.transport = SafeProviderTransport(allowed_hosts={"data.alpaca.markets", "paper-api.alpaca.markets"},
                                               settings=s.config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = s.store.backfill(kind="BAR", listing_ids=(s.listing,), start="2026-10-12T13:30:00Z",
                              end="2026-10-12T13:32:00Z", asof="2026-10-12", cancel=lambda: cancelled[0])
    assert result["state"] == "PARTIAL" and result["reason_code"] == "CANCELLED"
    markers = [row["payload"] for row in s.store.progress_as_of(cutoff_ns=s.clock.now) if row["payload"]["phase"] == "CHUNK"]
    assert markers and not any(row["complete"] for row in markers)
    assert markers[0]["reason_code"] == "CANCELLED"


def test_archive_already_full_fails_before_http():
    s = prepared(history=True)
    s.store.archive.settings = replace(s.config, alpaca_max_archive_bytes=1)
    calls = len(s.requests)
    with pytest.raises(ValueError, match="ARCHIVE_LIMIT"):
        s.store.backfill(kind="BAR", listing_ids=(s.listing,), start="2026-10-12T13:30:00Z",
                         end="2026-10-12T13:32:00Z", asof="2026-10-12")
    assert len(s.requests) == calls


def test_rest_cannot_enter_strict_store_through_persist():
    s = prepared()
    with pytest.raises(ValueError, match="MODE_MISMATCH"):
        s.store.persist((event(s, source="REST"),))
    assert not read(s)


def test_early_bar_and_closed_equal_payload_are_distinct_quality_occurrences():
    s = prepared()
    s.clock.now = OPEN + 30 * SECOND
    early = s.store.persist((event(s),))
    assert not read(s)
    s.clock.now = OPEN + 62 * SECOND
    closed = s.store.persist((event(s),))
    assert closed != early
    assert read(s)[0]["quality"] == "VALID"


def test_source_event_and_revision_tuple_distinguishes_occurrences():
    s = prepared()
    first = s.store.persist((replace(event(s), source_event_id="event-one", source_revision_id="revision-common"),))
    second = s.store.persist((replace(event(s), source_event_id="event-two", source_revision_id="revision-common"),))
    assert first != second


def test_identifiable_source_event_duplicate_across_capture_keeps_first_receipt():
    s = prepared()
    first = replace(event(s), source_event_id="event-one")
    ids = s.store.persist((first,))
    s.clock.now += SECOND
    assert s.store.persist((replace(event(s, capture_id="other-capture"), source_event_id="event-one"),)) == ids
    assert read(s)[0]["received_at_ns"] == first.received_at_ns


@pytest.mark.parametrize("missing", ["bx", "ax", "z"])
def test_missing_quote_metadata_never_claims_executable(missing):
    s = prepared()
    a = event(s, kind="QUOTE", at=s.clock.now)
    payload = json.loads(a.payload_json)
    del payload["raw"][missing]
    s.store.persist((replace(a, payload_json=canonical_json(payload)),))
    state = s.store.quote_state(s.listing, cutoff_ns=s.clock.now)
    assert state["quality"] == "QUARANTINED" and not state["executable"]


def test_backfill_preserves_transport_receipt_despite_processing_backlog(monkeypatch):
    s = prepared(history=True)
    s.queue.append({"bars": pages("bars")[0]["bars"], "next_page_token": None})
    original = s.store.provider.get_bars_page
    receipt = s.clock.now
    def slow_processing(**kwargs):
        result = original(**kwargs)
        s.clock.now += 5 * SECOND
        return result
    monkeypatch.setattr(s.store.provider, "get_bars_page", slow_processing)
    assert s.store.backfill(kind="BAR", listing_ids=(s.listing,), start="2026-10-12T13:30:00Z",
                            end="2026-10-12T13:32:00Z", asof="2026-10-12")["state"] == "COMPLETE"
    row = read(s)[0]
    assert row["received_at_ns"] == receipt and row["persisted_at_ns"] == receipt + 5 * SECOND
    assert not read(s, receipt)


def test_empty_known_calendar_range_keeps_holiday_proof():
    s = prepared(history=True)
    s.calendar.record([], start="2026-10-13", end="2026-10-13", received_at_ns=s.clock.now)
    s.clock.now = ns("2026-10-13T14:00:00Z")
    s.queue.append({"bars": {}, "next_page_token": None})
    result = s.store.backfill(kind="BAR", listing_ids=(s.listing,), start="2026-10-13T13:30:00Z",
                              end="2026-10-13T13:32:00Z", asof="2026-10-13")
    assert result["state"] == "COMPLETE" and not read(s)
    markers = [row["payload"] for row in s.store.progress_as_of(cutoff_ns=s.clock.now) if row["payload"]["complete"]]
    proof = markers[0]["metadata"]["calendar_proofs"][0]
    assert proof["capture_id"] and proof["publication_id"] and len(proof["hash"]) == 64


def test_chunks_are_bounded_and_do_not_drop_nanosecond_boundary():
    s = prepared(history=True)
    s.calendar.record([], start="2026-10-12", end="2026-10-20", received_at_ns=s.clock.now)
    s.clock.now = ns("2026-10-20T15:00:00Z")
    start = ns("2026-10-12T13:30:00Z")
    boundary = start + 7 * 86400 * SECOND
    from backend.app.data_providers.alpaca_market import format_ns
    quote = {"bp": 100, "ap": 101, "bs": 2, "as": 3, "c": [], "bx": "Q", "ax": "Q", "z": "C"}
    s.queue.extend([{"quotes": {"AAPL": [{**quote, "t": format_ns(boundary)}]}, "next_page_token": None},
                    {"quotes": {"AAPL": [{**quote, "t": format_ns(boundary + 1)}]}, "next_page_token": None}])
    result = s.store.backfill(kind="QUOTE", listing_ids=(s.listing,), start=format_ns(start),
                              end="2026-10-20T13:30:00Z", asof="2026-10-20")
    assert result["state"] == "COMPLETE" and result["pages"] == 2
    assert [row["event_time_ns"] for row in read(s, kind="QUOTE")] == [boundary, boundary + 1]
    assert s.requests[-1].url.params["start"] == format_ns(boundary + 1)


@pytest.mark.parametrize("feed", ["iex", "delayed_sip"])
def test_feed_labels_and_original_size_are_explicit(feed):
    s = prepared(profile_overrides={"feed": feed})
    s.store.persist((event(s, kind="QUOTE", at=s.clock.now),))
    row = s.store.quote_state(s.listing, cutoff_ns=s.clock.now)
    assert row["nbbo"] is False and row["delayed"] == (feed == "delayed_sip")
    assert not row["executable"] and row["payload"]["raw"]["bs"] == 2


def test_missing_admission_survives_partial_failure_without_false_visibility(monkeypatch):
    s = prepared()
    def crash(ids):
        raise RuntimeError("offline-interruption")
    monkeypatch.setattr(s.store, "admit", crash)
    with pytest.raises(RuntimeError):
        s.store.persist((event(s),))
    assert s.db.execute("SELECT count(*) FROM intraday_observations").fetchone()[0] == 1
    assert not s.db.in_transaction and not read(s)


def test_derived_identity_change_keeps_identifiable_first_received():
    s = prepared()
    _, other = resolved(s.db, ticker="MSFT", second=True)
    a = replace(event(s), listing_id=other, logical_key=f"BAR:{other}:{OPEN}",
                source_event_id="one-event", source_revision_id="one-version")
    first = s.store.persist((a,))
    received = s.clock.now
    s.clock.now += SECOND
    row = asset(symbol="MSFT")
    batch = capture(s, [row])
    confirm(s, row, batch, listing=other, valid_from_ns=OPEN, validity_source="OFFICIAL_NOTICE")
    s.clock.now += SECOND
    ids = s.store.persist((replace(a, received_at_ns=s.clock.now, persisted_at_ns=s.clock.now),))
    assert ids == first and read(s)[0]["received_at_ns"] == received
    assert read(s)[0]["reason_code"] == "IDENTITY_UNVERIFIED"


def test_partial_progress_frame_limit_always_finishes_operational_run():
    s = prepared(history=True)
    narrowed = replace(s.config, alpaca_max_frame_bytes=600)
    s.store.archive.settings = s.store.provider.settings = narrowed
    s.queue.append({"bars": pages("bars")[0]["bars"], "next_page_token": None})
    result = s.store.backfill(kind="BAR", listing_ids=(s.listing,), start="2026-10-12T13:30:00Z",
                              end="2026-10-12T13:32:00Z", asof="2026-10-12")
    assert result["state"] == "PARTIAL"
    run = s.db.execute("SELECT state,finished_at_ns FROM intraday_ingest_runs WHERE id=?", (result["run_id"],)).fetchone()
    assert run["state"] == "PARTIAL" and run["finished_at_ns"] is not None


def test_backlogged_old_revision_does_not_regress_received_source_order():
    s = prepared()
    early = event(s, change={"c": 100})
    s.clock.now += SECOND
    s.store.persist((event(s),))
    cutoff = s.clock.now
    s.clock.now += SECOND
    s.store.persist((early,))
    assert read(s, cutoff)[0]["payload"]["raw"]["c"] == 101
    assert read(s)[0]["payload"]["raw"]["c"] == 101
    assert len(s.store.read_as_of("BAR", cutoff_ns=s.clock.now, revisions=True)) == 2


def test_alpaca_symbol_asof_requires_the_same_verified_entity_before_http():
    s = prepared(history=True)
    calls = len(s.requests)
    s.queue.append({"bars": pages("bars")[0]["bars"], "next_page_token": None})
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        s.store.backfill(kind="BAR", listing_ids=(s.listing,), start="2026-10-12T13:30:00Z",
                         end="2026-10-12T13:32:00Z", asof="2026-10-11")
    assert len(s.requests) == calls


def test_chunk_fingerprint_includes_distinct_identity_used_for_symbol_asof():
    from backend.app.intraday.identity import read_identity_as_of
    s = prepared(history=True)
    first = read_identity_as_of(s.db, s.listing, OPEN, s.clock.now, profile_id=s.profile.profile_id)
    row = asset(asset_id=first["broker_asset_id"])
    batch = capture(s, [row])
    result = confirm(s, row, batch, valid_from_ns=OPEN + 20 * MINUTE, validity_source="OFFICIAL_NOTICE")
    assert result.identity_version_id != first["id"]
    s.queue.append({"bars": pages("bars")[0]["bars"], "next_page_token": None})
    assert s.store.backfill(kind="BAR", listing_ids=(s.listing,), start="2026-10-12T13:30:00Z",
                            end="2026-10-12T13:32:00Z", asof="2026-10-12")["state"] == "COMPLETE"
    chunk = next(row["payload"] for row in s.store.progress_as_of(cutoff_ns=s.clock.now) if row["payload"]["complete"])
    assert {proof["id"] for proof in chunk["metadata"]["identities"]} == {first["id"], result.identity_version_id}
    assert all(len(proof["hash"]) == 64 and proof["publication_id"] for proof in chunk["metadata"]["identities"])


def test_backlogged_tied_revisions_preserve_intake_sequence():
    s = prepared()
    older = replace(event(s, change={"c": 100}), ingest_sequence=1)
    newer = replace(event(s, change={"c": 101}), ingest_sequence=2)
    s.store.persist((newer,))
    s.clock.now += SECOND
    s.store.persist((older,))
    assert read(s)[0]["payload"]["raw"]["c"] == 101


def test_backlogged_delivery_does_not_hide_a_b_a_transition():
    s = prepared()
    a = event(s, change={"c": 100})
    s.clock.now += SECOND
    b_id = s.store.persist((event(s, change={"c": 101}),))
    old_a_id = s.store.persist((a,))
    assert read(s)[0]["id"] == b_id[0]
    s.clock.now += SECOND
    new_a_id = s.store.persist((event(s, change={"c": 100}),))
    assert new_a_id != old_a_id
    assert read(s)[0]["payload"]["raw"]["c"] == 100



def test_interleaved_capture_with_tied_receipt_cannot_promote_older_intake():
    s = prepared()
    s.store.persist((replace(event(s, change={"c": 101}), ingest_sequence=2),))
    s.store.persist((replace(event(s, change={"c": 100.5}), capture_id="second-capture", ingest_sequence=1),))
    before = read(s)
    s.store.persist((replace(event(s, change={"c": 100}), ingest_sequence=1),))
    assert read(s) == before


def test_asof_reader_preserves_rows_without_materializing_sqlite_row_mappings():
    s = prepared()
    s.store.persist((event(s),event(s,kind='QUOTE')))
    expected = {kind:s.store.read_as_of(kind,cutoff_ns=s.clock.now) for kind in ('BAR','QUOTE')}
    original = s.db.row_factory
    class SlowMapping:
        def keys(self):
            raise AssertionError('SQLITE_ROW_MAPPING_MATERIALIZATION')
    s.db.row_factory = lambda cursor,values:SlowMapping()
    try:
        for kind in ('BAR','QUOTE'):
            assert s.store.read_as_of(kind,cutoff_ns=s.clock.now) == expected[kind]
    finally:
        s.db.row_factory = original


def test_asof_receipt_lookup_uses_covering_index_without_table_fetch():
    s = prepared()
    s.store.persist((event(s,kind='QUOTE'),))
    queries = []
    s.db.set_trace_callback(queries.append)
    try:
        assert s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now,listing_ids=(s.listing,))
    finally:
        s.db.set_trace_callback(None)
    query = next(sql for sql in queries if 'SELECT raw.*, proof.id AS proof_id' in sql)
    plan = s.db.execute('EXPLAIN QUERY PLAN '+query).fetchall()
    assert any('COVERING INDEX idx_intraday_observation_receipt_read' in row[3] for row in plan)


def test_asof_fetches_the_complete_raw_envelope_only_after_the_visible_receipt():
    s = prepared()
    s.store.persist((event(s,kind='QUOTE'),))
    queries = []
    s.db.set_trace_callback(queries.append)
    try:
        rows = s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now,listing_ids=(s.listing,))
    finally:
        s.db.set_trace_callback(None)
    assert len(rows) == 1 and rows[0]['payload']['raw']['bp'] == 100
    query = next(sql for sql in queries if 'SELECT raw.*, proof.id AS proof_id' in sql)
    plan = s.db.execute('EXPLAIN QUERY PLAN '+query).fetchall()
    details = [row[3] for row in plan]
    assert not any('idx_intraday_observation_source_read' in detail for detail in details)
    assert any('COVERING INDEX idx_intraday_observations_logical' in detail for detail in details)
    receipt = next(index for index,detail in enumerate(details) if 'SEARCH proof ' in detail)
    raw = next(index for index,detail in enumerate(details) if 'SEARCH raw ' in detail)
    assert receipt < raw


@pytest.mark.parametrize('bounds', [{'start_ns':OPEN+1}, {'end_ns':OPEN}])
def test_asof_validates_visible_raw_before_applying_event_time_bounds(bounds):
    s = prepared()
    ids = s.store.persist((event(s,kind='QUOTE'),))
    # Corruption is confined to this in-memory fixture. A late lookup must not
    # silently hide invalid evidence merely because its event is out of range.
    triggers = s.db.execute("SELECT name FROM sqlite_master WHERE type='trigger' "
                            "AND tbl_name='intraday_observations'").fetchall()
    for trigger in triggers:
        s.db.execute('DROP TRIGGER "'+trigger[0].replace('"','""')+'"')
    s.db.execute('UPDATE intraday_observations SET payload_hash=? WHERE id=?',('0'*64,ids[0]))
    with pytest.raises(ValueError,match='METADATA_INVALID|OBSERVATION_INVALID'):
        s.store.read_as_of('QUOTE',cutoff_ns=s.clock.now,listing_ids=(s.listing,),**bounds)
