from decimal import Decimal

import pytest
from swing_research_fixtures import (
    daily_history,
    data_record,
    listing_record,
    listing_record_without_domicile,
    synthetic_calendar,
    utc_ns,
)

from backend.app.swing_research.contracts import SwingError
from backend.app.swing_research.universe import ListingFact, build_monthly_universe, resolve_ticker


def build(names=100, facts=None, bars=None, **kwargs):
    calendar, on = synthetic_calendar()
    return build_monthly_universe(
        facts if facts is not None else (listing_record(f"L{i:03d}") for i in range(names)),
        bars if bars is not None else daily_history(calendar, names),
        calendar,
        on,
        cutoff_ns=utc_ns(on + "T20:20:00Z"),
        **kwargs,
    )


def test_review_identity_cannot_change_issuer_or_share_class():
    original = listing_record(valid_to="2020-01-03")
    reused_id = listing_record(valid_from="2020-01-03", issuer_id="DIFFERENT")
    with pytest.raises(SwingError):
        resolve_ticker([original, reused_id], reused_id.data["ticker"], "2020-02-03", utc_ns("2020-02-03T20:20:00Z"))


def test_review_resource_budget_precedes_identity_input():
    from backend.app.swing_research.contracts import ResourceLimits

    calendar, on = synthetic_calendar()

    def forbidden():
        pytest.fail("identity input consumed before resource check")
        yield listing_record()

    with pytest.raises(SwingError, match="^RESOURCE_LIMIT$"):
        build_monthly_universe(
            forbidden(),
            [],
            calendar,
            on,
            cutoff_ns=utc_ns(on + "T20:20:00Z"),
            resources=ResourceLimits(8_388_608, max_rss_bytes=1),
        )


def test_review_identity_late_old_version_cannot_replace_correction():
    old = listing_record()
    corrected = type(old).from_dict(
        old.to_dict() | {"version": 2, "available_ns": old.available_ns + 1, "data": old.data | {"domicile": "CAN"}}
    )
    late_old = type(old).from_dict(old.to_dict() | {"available_ns": old.available_ns + 10})
    result = resolve_ticker([corrected, late_old], old.data["ticker"], "2020-02-03", utc_ns("2020-02-03T20:20:00Z"))
    assert result.domicile == "CAN"


def test_review_price_late_old_version_cannot_reinflate_adv():
    calendar, on = synthetic_calendar()
    rows = list(daily_history(calendar, 1))
    old = rows.pop()
    corrected = type(old).from_dict(
        old.to_dict() | {"version": 2, "available_ns": old.available_ns + 1, "data": old.data | {"volume": "1000000"}}
    )
    late_old = type(old).from_dict(old.to_dict() | {"available_ns": old.available_ns + 10})
    result = build(names=1, bars=rows + [corrected, late_old])
    assert result.candidates[0].reason == "ADV_BELOW_20M"


def test_review_coverage_and_hash_ignore_callers_decimal_rounding():
    from decimal import ROUND_DOWN, ROUND_UP, localcontext

    calendar, _ = synthetic_calendar()
    rows = list(daily_history(calendar, 1))[1:]
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        first = build(names=1, bars=rows)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        second = build(names=1, bars=rows)
    assert first == second and first.universe_hash == second.universe_hash


def test_monthly_universe_uses_raw_previous_252_sessions_and_adv20():
    result = build()
    assert result.state == "READY_SYNTHETIC"
    assert len(result.selected) == 100 and result.selected[0] == "L000"
    assert result.candidates[0].adv20_usd == Decimal("20000000")
    assert result.daily_expected == result.daily_observed == 25200
    assert result.coverage == Decimal("1")
    assert len(result.candidates) == 100


def test_delisted_later_is_included_in_historical_universe():
    facts = [listing_record(f"L{i:03d}", delisted_session="2021-01-01") for i in range(100)]
    result = build(facts=facts)
    assert len(result.selected) == 100 and result.state == "READY_SYNTHETIC"


def test_current_catalog_or_survivor_filter_cannot_replace_asof():
    with pytest.raises(SwingError, match="^INSUFFICIENT_DATA$"):
        build(names=1, universe_basis="CURRENT")
    with pytest.raises(SwingError):
        build(names=1, universe_basis="SURVIVORS")


def test_unknown_class_still_blocks_when_domicile_is_not_required():
    calendar, _ = synthetic_calendar()
    facts = [listing_record("L000", domicile=None), listing_record("L001", security_type=None)]
    result = build(names=2, facts=facts, bars=daily_history(calendar, 2))
    assert result.state == "INSUFFICIENTE"
    assert {candidate.reason for candidate in result.candidates} == {"INCLUDED", "CLASSIFICATION_UNKNOWN"}
    assert result.selected == ("L000",)
    assert "CLASSIFICATION_UNKNOWN" in result.issues
    assert result.daily_expected == result.daily_observed == 504


def test_foreign_common_stock_is_included_but_adr_is_still_excluded():
    result = build(names=2, facts=[listing_record("L000", domicile="CAN"), listing_record("L001", security_type="ADR")])
    assert result.selected == ("L000",)
    assert {row.reason for row in result.candidates} == {"INCLUDED", "NOT_COMMON_STOCK"}


def test_ipo_warmup_nominal_price_and_liquidity_are_fixed_exante():
    calendar, _ = synthetic_calendar()
    facts = [
        listing_record("L000", listed_session=calendar.sessions[-100].day),
        listing_record("L001"),
        listing_record("L002"),
    ]
    bars = daily_history(
        calendar, 3, L001={"open": "4", "high": "4", "low": "4", "close": "4"}, L002={"volume": "1999999"}
    )
    result = build(names=3, facts=facts, bars=bars)
    assert {row.reason for row in result.candidates} == {"WARMUP_LT252", "PRICE_BELOW_5", "ADV_BELOW_20M"}
    assert not result.selected


def test_missing_bar_remains_in_denominator_and_blocks_even_above_99_percent():
    calendar, _ = synthetic_calendar()
    missing_day = calendar.sessions[-3].day
    bars = (row for row in daily_history(calendar, 2) if (row.key, row.session) != ("L000", missing_day))
    result = build(names=2, bars=bars)
    assert result.daily_expected == 504 and result.daily_observed == 503
    assert result.coverage > Decimal("0.99")
    assert result.state == "INSUFFICIENTE" and "REQUIRED_DAILY_GAP" in result.issues
    assert len(result.candidates) == 2


def test_future_current_session_and_late_revision_do_not_change_old_membership():
    calendar, on = synthetic_calendar()
    previous = calendar.sessions[-2]
    normal = list(daily_history(calendar, 2))
    late = data_record(
        key="L000",
        session=previous.day,
        event_ns=previous.close_ns,
        available_ns=utc_ns(on + "T21:00:00Z"),
        version=2,
        data=normal[-2].data | {"volume": "1"},
    )
    today = data_record(key="L000", session=on, data=late.data)
    before = build(names=2, bars=iter(normal))
    after = build(names=2, bars=iter(normal + [late, today]))
    assert before == after


def test_top500_ties_are_stable_and_exclusions_are_retained():
    result = build(names=501)
    assert len(result.selected) == 500 and result.selected == tuple(f"L{i:03d}" for i in range(500))
    assert len(result.candidates) == 501 and result.candidates[-1].reason == "OUTSIDE_TOP500"


def test_ticker_reuse_and_rename_resolve_by_stable_listing_and_interval():
    old = listing_record("L000", ticker="OLD", valid_to="2020-01-03")
    renamed = listing_record("L000", ticker="NEW", valid_from="2020-01-03")
    reused = listing_record("L001", ticker="OLD", valid_from="2020-02-01")
    cutoff = utc_ns("2020-03-01T00:00:00Z")
    assert resolve_ticker([old, renamed, reused], "OLD", "2020-01-02", cutoff).listing_id == "L000"
    assert resolve_ticker([old, renamed, reused], "NEW", "2020-01-03", cutoff).issuer_id == "IL000"
    assert resolve_ticker([old, renamed, reused], "OLD", "2020-02-03", cutoff).listing_id == "L001"
    with pytest.raises(SwingError):
        resolve_ticker([old, renamed, reused], "OLD", "2020-01-10", cutoff)


def test_unknown_adjustment_never_becomes_raw_price_or_total_return():
    calendar, _ = synthetic_calendar()
    result = build(names=1, bars=daily_history(calendar, 1, L000={"basis": "UNKNOWN"}))
    assert result.state == "INSUFFICIENTE" and result.candidates[0].reason == "RAW_BASIS_REQUIRED"


def test_midmonth_recomputation_is_rejected():
    calendar, _ = synthetic_calendar()
    with pytest.raises(SwingError):
        build_monthly_universe(
            [listing_record()], [], calendar, calendar.sessions[-2].day, cutoff_ns=utc_ns("2020-02-03T20:20:00Z")
        )


@pytest.mark.parametrize("domicile", ["USA", "CAN", None, "OMITTED"])
def test_optional_domicile_does_not_rewrite_identity_record(domicile):
    record = listing_record_without_domicile() if domicile == "OMITTED" else listing_record(domicile=domicile)
    before = record.to_dict()
    before_hash = record.record_hash
    fact = ListingFact.from_record(record)
    assert fact.domicile == (None if domicile == "OMITTED" else domicile)
    assert fact.record is record
    assert record.to_dict() == before
    assert record.record_hash == before_hash
    assert ("domicile" in record.data) is (domicile != "OMITTED")


def test_monthly_minimum_is_met_by_foreign_and_unattributed_primary_us_listings():
    facts = [
        listing_record(f"L{i:03d}", domicile="CAN")
        if i % 2
        else listing_record_without_domicile(f"L{i:03d}")
        for i in range(100)
    ]
    result = build(facts=facts)
    assert result.state == "READY_SYNTHETIC"
    assert len(result.selected) == 100
    assert result.daily_expected == result.daily_observed == 25200
    assert result.coverage == Decimal("1")
    assert result.issues == ()


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"security_type": "ADR"}, "NOT_COMMON_STOCK"),
        ({"security_type": "ETF"}, "NOT_COMMON_STOCK"),
        ({"security_type": "FUND"}, "NOT_COMMON_STOCK"),
        ({"security_type": "PREFERRED"}, "NOT_COMMON_STOCK"),
        ({"security_type": "WARRANT"}, "NOT_COMMON_STOCK"),
        ({"security_type": "UNIT"}, "NOT_COMMON_STOCK"),
        ({"security_type": "LEVERAGED"}, "NOT_COMMON_STOCK"),
        ({"primary": False}, "LISTING_NOT_ELIGIBLE"),
        ({"venue": "OTC"}, "LISTING_NOT_ELIGIBLE"),
        ({"venue": "LSE"}, "LISTING_NOT_ELIGIBLE"),
        ({"currency": "EUR"}, "LISTING_NOT_ELIGIBLE"),
        ({"security_type": None}, "CLASSIFICATION_UNKNOWN"),
    ],
)
def test_listing_rule_preserves_class_venue_currency_and_primary_filters(changes, reason):
    result = build(names=1, facts=[listing_record_without_domicile(**changes)])
    assert result.selected == ()
    assert result.candidates[0].reason == reason


@pytest.mark.parametrize("field", ["security_type", "primary", "venue", "currency", "source_hash", "valid_from"])
def test_only_domicile_is_optional_in_identity_payload(field):
    record = listing_record_without_domicile()
    data = record.data
    del data[field]
    invalid = type(record).from_dict(record.to_dict() | {"data": data})
    with pytest.raises(SwingError, match="^INVALID_CONTRACT$"):
        ListingFact.from_record(invalid)


@pytest.mark.parametrize("domicile", ["CAN", None, "OMITTED"])
def test_required_daily_gap_blocks_foreign_or_unknown_domicile_above_99_percent(domicile):
    calendar, _ = synthetic_calendar()
    fact = listing_record_without_domicile() if domicile == "OMITTED" else listing_record(domicile=domicile)
    bars = list(daily_history(calendar, 1))[1:]
    result = build(names=1, facts=[fact], bars=bars)
    assert result.daily_expected == 252
    assert result.daily_observed == 251
    assert result.coverage > Decimal("0.99")
    assert result.candidates[0].reason == "REQUIRED_DAILY_GAP"
    assert "REQUIRED_DAILY_GAP" in result.issues
    assert result.state == "INSUFFICIENTE"


def test_future_class_revision_cannot_remove_foreign_common_stock_at_old_cutoff():
    original = listing_record(domicile="CAN")
    revision = type(original).from_dict(
        original.to_dict()
        | {
            "version": 2,
            "available_ns": utc_ns("2020-02-03T21:00:00Z"),
            "data": original.data | {"security_type": "ADR"},
        }
    )
    before = build(names=1, facts=[original])
    after = build(names=1, facts=[original, revision])
    assert before.selected == ("L000",)
    assert after == before
