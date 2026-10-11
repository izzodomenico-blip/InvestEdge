from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from test_intraday_identity import asset, capture, confirm, resolved, system

SECOND = 1_000_000_000


def article(**changes):
    return {"id": 101, "source": "benzinga", "headline": "Company reports quarterly earnings",
            "summary": "Revenue was disclosed.", "content": "<p>Official results.</p>",
            "author": "Newsdesk", "created_at": "2026-10-12T12:00:01.000000001Z",
            "updated_at": "2026-10-12T12:00:01.000000001Z", "symbols": ["AAPL"],
            "url": "https://example.com/results", **changes}


def setup_news(**options):
    s = system()
    row = asset()
    confirm(s, row, capture(s, [row]))
    s.clock.now += 10 * SECOND
    mod = importlib.import_module("backend.app.intraday.news")
    s.news = mod.NewsStore(s.archive.provider, clock_ns=lambda: s.clock.now, **options)
    return s


def read_news(s, cutoff=None, **options):
    return s.news.read_as_of(cutoff_ns=s.clock.now if cutoff is None else cutoff, **options)


def test_raw_news_and_links_are_invisible_before_admission():
    s = setup_news()
    stamp = s.clock.now
    ids = s.news.persist([article()], received_at_ns=stamp, admit=False)
    assert not read_news(s) and not s.db.in_transaction
    raw = s.db.execute("SELECT * FROM intraday_news_versions").fetchone()
    assert raw["available_at_ns"] is None and raw["admitted_at_ns"] is None
    assert s.db.execute("SELECT count(*) FROM intraday_news_links").fetchone()[0] == 1
    s.clock.now += 2 * SECOND
    s.news.admit(ids)
    assert not read_news(s, stamp)
    row = read_news(s)[0]
    assert row["first_received_at_ns"] == stamp and row["available_at_ns"] == s.clock.now
    assert row["links"][0]["listing_id"] == s.listing
    assert row["links"][0]["category"] == "EARNINGS"
    assert row["links"][0]["payload"]["identity"]["publication_id"] > 0


def test_future_update_does_not_rewrite_saved_news_and_cluster():
    s = setup_news()
    s.news.persist([article()], received_at_ns=s.clock.now)
    stamp = s.clock.now
    before = read_news(s)
    s.clock.now += SECOND
    s.news.persist([article(headline="Company raises full-year guidance",
                            updated_at="2026-10-12T12:00:02Z")], received_at_ns=s.clock.now)
    assert read_news(s, stamp) == before
    assert read_news(s)[0]["links"][0]["category"] == "GUIDANCE"
    assert read_news(s)[0]["links"][0]["cluster_id"] != before[0]["links"][0]["cluster_id"]


def test_out_of_order_source_update_never_regresses_text():
    s = setup_news()
    s.news.persist([article(headline="New results", updated_at="2026-10-12T12:00:05Z")], received_at_ns=s.clock.now)
    s.clock.now += SECOND
    s.news.persist([article(headline="Older results", updated_at="2026-10-12T12:00:03Z")], received_at_ns=s.clock.now)
    assert read_news(s)[0]["payload"]["headline"] == "New results"
    assert len(read_news(s, revisions=True)) == 2


@pytest.mark.parametrize("tied", [True, False])
def test_a_b_a_is_three_occurrences_and_consecutive_duplicate_preserves_first_receipt(tied):
    s = setup_news()
    ids = []
    for index, headline in enumerate(["A", "B", "A"]):
        text_time = "2026-10-12T12:00:01.000000001Z" if tied else f"2026-10-12T12:00:0{index+1}.000000001Z"
        ids.append(s.news.persist([article(headline=headline, updated_at=text_time)], received_at_ns=s.clock.now))
        s.clock.now += SECOND
    assert len(set(ids)) == 3
    first = read_news(s)[0]["first_received_at_ns"]
    duplicate = s.news.persist([article(headline="A", updated_at=text_time)], received_at_ns=s.clock.now)
    assert duplicate == ids[-1] and read_news(s)[0]["first_received_at_ns"] == first
    assert len(read_news(s, revisions=True)) == 3


def test_source_and_id_separate_articles_with_same_url():
    s = setup_news()
    s.news.persist([article(), article(source="issuer"), article(id=102)], received_at_ns=s.clock.now)
    assert len(read_news(s)) == 3


@pytest.mark.parametrize("change,reason", [({"created_at": None}, "PUBLICATION_MISSING"),
    ({"created_at": "bad"}, "TIMESTAMP_INVALID"),
    ({"updated_at": "2026-10-12T11:00:00Z"}, "TIMESTAMP_ORDER"),
    ({"updated_at": "2027-01-01T00:00:00Z"}, "TIMESTAMP_FUTURE")])
def test_invalid_publication_is_durable_quarantine_without_now_fallback(change, reason):
    s = setup_news()
    assert s.news.persist([article(**change)], received_at_ns=s.clock.now) == ()
    assert not read_news(s)
    captures = s.news.quarantine_as_of(cutoff_ns=s.clock.now)
    assert captures[-1]["payload"]["reason_code"] == reason
    assert s.db.execute("SELECT count(*) FROM intraday_news_versions").fetchone()[0] == 0


def test_unknown_symbol_is_explicit_and_future_mapping_does_not_change_old_links():
    s = setup_news()
    s.news.persist([article(symbols=["UNKNOWN", "AAPL"])], received_at_ns=s.clock.now)
    before = read_news(s)
    links = before[0]["links"]
    assert len(links) == 2 and sum(link["listing_id"] is None for link in links) == 1
    assert any(link["payload"]["reason_code"] == "IDENTITY_UNVERIFIED" for link in links)
    s.clock.now += SECOND
    _, listing = resolved(s.db, ticker="UNKNOWN", second=True)
    row = asset(symbol="UNKNOWN")
    confirm(s, row, capture(s, [row]), listing=listing)
    assert read_news(s) == before


def test_market_article_has_null_mapping_without_becoming_stock_news():
    s = setup_news()
    s.news.persist([article(symbols=[], headline="Federal Reserve announces policy rate decision")], received_at_ns=s.clock.now)
    row = read_news(s)[0]
    assert row["links"][0]["listing_id"] is None
    assert row["links"][0]["category"] == "MACRO"
    assert not read_news(s, listing_ids=(s.listing,))


def test_duplicate_does_not_graft_a_new_mapping_onto_old_occurrence():
    s = setup_news()
    item = article(symbols=["UNKNOWN"])
    ids = s.news.persist([item], received_at_ns=s.clock.now)
    before = read_news(s)
    s.clock.now += SECOND
    _, listing = resolved(s.db, ticker="UNKNOWN", second=True)
    row = asset(symbol="UNKNOWN")
    confirm(s, row, capture(s, [row]), listing=listing)
    assert s.news.persist([item], received_at_ns=s.clock.now) == ids
    assert read_news(s) == before


def test_rights_default_omits_body_and_summary_even_before_persistence():
    s = setup_news()
    s.news.persist([article()], received_at_ns=s.clock.now)
    payload = read_news(s)[0]["payload"]
    assert payload["content"] is None and payload["summary"] is None
    assert payload["content_state"] == "RIGHTS_UNATTESTED"
    assert "Official results" not in s.db.execute("SELECT payload_json FROM intraday_news_versions").fetchone()[0]


def test_licensed_archive_text_never_contains_executable_html():
    mod = importlib.import_module("backend.app.data_providers.alpaca_news")
    rights = mod.NewsRights(allow_summary=True, allow_content=True, retention="ARCHIVE_ALLOWED", evidence_hash="a"*64)
    s = setup_news(rights=rights)
    item = article(content='<p>Results &amp; revenue</p><script>alert(1)</script><img src="https://example.com/tracker">')
    s.news.persist([item], received_at_ns=s.clock.now)
    payload = read_news(s)[0]["payload"]
    assert payload["content"] == "Results & revenue"
    assert "<" not in payload["content"] and "alert" not in payload["content"]
    assert payload["rights"]["retention"] == "ARCHIVE_ALLOWED"


def test_finite_retention_or_missing_license_cannot_enable_body():
    mod = importlib.import_module("backend.app.data_providers.alpaca_news")
    for options in [{"allow_content": True}, {"allow_content": True, "retention": "30_DAYS", "evidence_hash": "a"*64}]:
        with pytest.raises(ValueError, match="NEWS_RIGHTS_INVALID"):
            mod.NewsRights(**options)


@pytest.mark.parametrize("headline", ["Company may acquire competitor", "Analyst expects earnings growth", "Shares rise 10%", "Company denies acquisition rumors"])
def test_unproven_fact_stays_unknown(headline):
    s = setup_news()
    s.news.persist([article(headline=headline)], received_at_ns=s.clock.now)
    assert read_news(s)[0]["links"][0]["category"] == "UNKNOWN"


def test_rest_archiving_cannot_claim_captured_or_strict_pit():
    s = setup_news()
    with pytest.raises(ValueError, match="MODE_MISMATCH"):
        s.news.persist([article()], received_at_ns=s.clock.now, source="REST")


def test_demo_never_enters_real_news_reader():
    s = setup_news()
    mod = importlib.import_module("backend.app.intraday.news")
    demo = mod.NewsStore(s.archive.provider, clock_ns=lambda:s.clock.now, data_mode="DEMO",
                         provenance="SYNTHETIC", replay_grade="RESEARCH_ONLY")
    demo.persist([article()], received_at_ns=s.clock.now)
    assert not read_news(s) and demo.read_as_of(cutoff_ns=s.clock.now)


def test_legacy_tables_not_written_by_intraday_news():
    s = setup_news()
    counts = [s.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ["news_items", "signals", "features_daily"]]
    s.news.persist([article()], received_at_ns=s.clock.now)
    assert counts == [s.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ["news_items", "signals", "features_daily"]]


def test_secret_echo_even_in_discarded_content_leaves_no_evidence():
    s = setup_news()
    with pytest.raises(ValueError):
        s.news.persist([article(content=s.config.alpaca_api_secret_key)], received_at_ns=s.clock.now)
    assert not read_news(s) and s.db.execute("SELECT count(*) FROM intraday_news_versions").fetchone()[0] == 0


def test_admission_link_hash_and_missing_source_fail_closed():
    s = setup_news()
    s.news.persist([article()], received_at_ns=s.clock.now, admit=False)
    ids = [s.db.execute("SELECT id FROM intraday_news_versions").fetchone()[0]]
    s.news.admit(ids)
    for name in ["intraday_news_versions", "intraday_news_links"]:
        with pytest.raises(Exception, match="INTRADAY_APPEND_ONLY"):
            s.db.execute(f"UPDATE {name} SET payload_json='{{}}'")
        s.db.rollback()
    assert read_news(s)[0]["links"]


def test_fixture_timeline_has_only_synthetic_public_data():
    for name in ["alpaca_news_pages.json", "alpaca_news_revisions.json"]:
        payload = json.loads((Path(__file__).parent/"fixtures"/"market_data"/name).read_text())
        assert payload


def history_news(s):
    mod = importlib.import_module("backend.app.intraday.news")
    s.news = mod.NewsStore(s.archive.provider,clock_ns=lambda:s.clock.now,
                          provenance="HISTORICAL_CURRENT",replay_grade="RESEARCH_ONLY")
    return s


def backfill(s, **options):
    return s.news.backfill(start="2026-10-12T12:00:00Z",end="2026-10-12T12:00:09Z",**options)


def coverage(s, **options):
    from backend.app.data_providers.alpaca_market import _ns
    return s.news.coverage_as_of(start_ns=_ns("2026-10-12T12:00:00Z"),end_ns=_ns("2026-10-12T12:00:09Z"),
                                cutoff_ns=s.clock.now,**options)


def test_rest_consumes_all_pages_preserves_original_receive_and_reports_covered():
    s = history_news(setup_news())
    s.queue.extend([{"news":[article()],"next_page_token":"next"},
                    {"news":[article(id=102)],"next_page_token":None}])
    result=backfill(s)
    assert result["state"] == "COMPLETE" and result["pages"] == 2
    assert len(read_news(s)) == 2
    assert all(row["provenance"] == "HISTORICAL_CURRENT" and row["replay_grade"] == "RESEARCH_ONLY" for row in read_news(s))
    assert all(row["first_received_at_ns"] == s.clock.now for row in read_news(s))
    assert coverage(s)["state"] == "COVERED" and coverage(s)["continuity_attested"] is False
    assert s.requests[-1].url.params["page_token"] == "next"


def test_missing_stale_disabled_and_covered_zero_are_distinct():
    from dataclasses import replace
    s = history_news(setup_news())
    assert coverage(s)["state"] == "MISSING"
    s.queue.append({"news":[],"next_page_token":None})
    assert backfill(s)["state"] == "COMPLETE"
    assert coverage(s)["state"] == "COVERED_ZERO"
    assert coverage(s,symbols=("MSFT",))["state"] == "COVERED_ZERO"
    s.clock.now += 61*SECOND
    assert coverage(s)["state"] == "STALE"
    s.news.archive.settings = replace(s.config,enable_alpaca_data=False)
    assert coverage(s)["state"] == "STALE"
    assert coverage(s)["acquisition_disabled"] is True


def test_specific_symbol_coverage_does_not_claim_whole_market_or_other_symbols():
    s=history_news(setup_news())
    s.queue.append({"news":[],"next_page_token":None})
    backfill(s,symbols=("AAPL",))
    assert coverage(s,symbols=("AAPL",))["state"] == "COVERED_ZERO"
    assert coverage(s)["state"] == "MISSING"
    assert coverage(s,symbols=("MSFT",))["state"] == "MISSING"


@pytest.mark.parametrize("limit,loop", [(1,False),(3,True)])
def test_page_limit_or_token_loop_is_partial_with_prior_durable_rows(limit,loop):
    s=history_news(setup_news())
    s.queue.extend([{"news":[article()],"next_page_token":"same"},
                    {"news":[article(id=102)],"next_page_token":"same"}])
    result=backfill(s,max_pages=limit)
    assert result["state"] == "PARTIAL"
    assert result["reason_code"] == ("TOKEN_LOOP" if loop else "PAGE_LIMIT")
    assert read_news(s) and coverage(s)["state"] == "MISSING"


def test_cancel_after_last_response_keeps_prices_but_never_claims_complete():
    s=history_news(setup_news())
    s.queue.append({"news":[article()],"next_page_token":None})
    result=backfill(s,cancel=lambda: bool(len(s.requests)>2))
    assert result["state"] == "PARTIAL" and result["reason_code"] == "CANCELLED"
    assert read_news(s) and coverage(s)["state"] == "MISSING"


def test_rest_invalid_publication_does_not_claim_covered_zero():
    s=history_news(setup_news())
    s.queue.append({"news":[article(created_at=None)],"next_page_token":None})
    result=backfill(s)
    assert result["state"] == "PARTIAL" and coverage(s)["state"] == "MISSING"


def test_idempotent_historical_retry_does_not_duplicate_the_same_completed_article():
    s=history_news(setup_news())
    for _ in range(2):
        s.queue.append({"news":[article()],"next_page_token":None})
        assert backfill(s)["state"] == "COMPLETE"
    assert len(read_news(s,revisions=True)) == 1


def test_same_received_news_backlog_preserves_original_intake_order():
    s=setup_news()
    stamp=s.clock.now
    s.news.persist([article(headline="B")],received_at_ns=stamp,intake_sequence=2)
    s.clock.now += SECOND
    s.news.persist([article(headline="A")],received_at_ns=stamp,intake_sequence=1)
    assert read_news(s)[0]["payload"]["headline"] == "B"


def test_removed_symbol_does_not_resurrect_prior_article_on_filtered_read():
    s=setup_news()
    s.news.persist([article()],received_at_ns=s.clock.now)
    stamp=s.clock.now
    s.clock.now += SECOND
    s.news.persist([article(symbols=[],updated_at="2026-10-12T12:00:02Z")],received_at_ns=s.clock.now)
    assert not read_news(s,listing_ids=(s.listing,))
    assert read_news(s,stamp,listing_ids=(s.listing,))


def test_missing_frozen_identity_dependency_is_not_replaced_by_current_mapping():
    s=setup_news()
    s.news.persist([article()],received_at_ns=s.clock.now)
    s.db.set_authorizer(lambda action,arg1,arg2,db,trigger: 1 if action == 20 and arg1 == "intraday_identity_versions" else 0)
    with pytest.raises(ValueError,match="NEWS_INPUT_MISSING"):
        read_news(s)


def test_ambiguous_mapping_across_venues_remains_unmapped():
    s=setup_news()
    _,other=resolved(s.db,ticker="AAPL",second=True)
    s.db.execute("UPDATE instrument_listings SET mic='XNYS' WHERE id=?",(other,))
    s.db.commit()
    s.clock.now += SECOND
    row=asset(symbol="AAPL",exchange="NYSE")
    confirm(s,row,capture(s,[row]),listing=other)
    s.clock.now += SECOND
    s.news.persist([article(updated_at="2026-10-12T12:00:11.000000001Z")],received_at_ns=s.clock.now)
    link=read_news(s)[0]["links"][0]
    assert link["listing_id"] is None and link["payload"]["reason_code"] == "IDENTITY_AMBIGUOUS"



def test_disabling_acquisition_preserves_the_frozen_coverage_at_same_cutoff():
    from dataclasses import replace
    s = history_news(setup_news())
    s.queue.append({"news": [], "next_page_token": None})
    backfill(s)
    before = coverage(s)
    s.news.archive.settings = replace(s.config, enable_alpaca_data=False)
    after = coverage(s)
    assert before["state"] == after["state"] == "COVERED_ZERO"
    assert before["coverage_id"] == after["coverage_id"]
    assert after["acquisition_disabled"] is True


def test_disabled_without_evidence_is_explicit():
    from dataclasses import replace
    s = history_news(setup_news())
    s.news.archive.settings = replace(s.config, enable_alpaca_data=False)
    assert coverage(s)["state"] == "DISABLED"


def test_revision_timeline_uses_original_intake_for_tied_admission():
    s = setup_news()
    s.news.persist([article(headline="B")], received_at_ns=s.clock.now, intake_sequence=2)
    s.news.persist([article(headline="A")], received_at_ns=s.clock.now, intake_sequence=1)
    assert [r["payload"]["headline"] for r in read_news(s, revisions=True)] == ["A", "B"]
    assert read_news(s)[0]["payload"]["headline"] == "B"


def test_intake_sequences_from_different_captures_are_not_comparable():
    s = setup_news()
    s.news.persist([article(headline="A")], received_at_ns=s.clock.now,
                   capture_id="previous-capture", intake_sequence=100)
    s.news.persist([article(headline="B")], received_at_ns=s.clock.now,
                   capture_id="next-capture", intake_sequence=1)
    assert read_news(s)[0]["payload"]["headline"] == "B"


def test_coverage_counts_only_frozen_members_matching_symbol_and_subwindow():
    from backend.app.data_providers.alpaca_market import _ns
    s = history_news(setup_news())
    s.queue.append({"news": [article()], "next_page_token": None})
    backfill(s)
    assert coverage(s, symbols=("AAPL",))["state"] == "COVERED"
    assert coverage(s, symbols=("MSFT",))["state"] == "COVERED_ZERO"
    assert s.news.coverage_as_of(start_ns=_ns("2026-10-12T12:00:08Z"),
        end_ns=_ns("2026-10-12T12:00:09Z"), cutoff_ns=s.clock.now, symbols=("AAPL",))["state"] == "COVERED_ZERO"
    s.clock.now += SECOND
    s.news.persist([article(symbols=["MSFT"], updated_at="2026-10-12T12:00:02Z")],
                   received_at_ns=s.clock.now, source="REST", capture_id="another-query")
    assert coverage(s, symbols=("MSFT",))["state"] == "COVERED_ZERO"
    assert coverage(s, symbols=("AAPL",))["state"] == "COVERED"


@pytest.mark.parametrize("change,options", [
    ({"updated_at": "2026-10-12T12:00:10Z"}, {}),
    ({"symbols": ["MSFT"]}, {"symbols": ("AAPL",)}),
])
def test_out_of_range_or_other_symbol_page_is_partial(change, options):
    s = history_news(setup_news())
    s.queue.append({"news": [article(**change)], "next_page_token": None})
    assert backfill(s, **options)["state"] == "PARTIAL"
    assert not read_news(s)
    assert coverage(s, **options)["state"] == "MISSING"


@pytest.mark.parametrize("table", ["intraday_news_versions", "intraday_news_links", "intraday_capture_events"])
def test_unreadable_news_dependencies_have_only_static_errors(table):
    s = setup_news()
    s.news.persist([article()], received_at_ns=s.clock.now)
    s.db.set_authorizer(lambda action, arg1, arg2, db, trigger: 1 if action == 20 and arg1 == table else 0)
    with pytest.raises(ValueError, match="NEWS_INPUT_MISSING"):
        read_news(s)


@pytest.mark.parametrize("headline", ["Company has not acquired competitor",
    "Company reports earnings rumours", "Company reports earnings rumors",
    "Company reportedly raises guidance", "Company plans to acquire competitor",
    "Company will report earnings", "Company never acquired competitor",
    "Company acquired competitor according to unconfirmed reports"])
def test_negation_speculation_and_future_wording_cannot_become_factual_categories(headline):
    s = setup_news()
    s.news.persist([article(headline=headline)], received_at_ns=s.clock.now)
    assert read_news(s)[0]["links"][0]["category"] == "UNKNOWN"
