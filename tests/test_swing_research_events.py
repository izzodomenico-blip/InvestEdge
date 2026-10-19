from decimal import Decimal, localcontext

import pytest
from swing_research_fixtures import action_record, data_record, utc_ns

from backend.app.swing_research.contracts import SwingError
from backend.app.swing_research.events import (
    CorporateAction,
    dividend_credit,
    split_adjust,
    split_position,
    terminal_resolution,
)
from backend.app.swing_research.universe import RawBar


def test_review_pay_date_argument_cannot_advance_actual_cutoff():
    action = CorporateAction.from_record(action_record("DIVIDEND"))
    credit = dividend_credit(action, Decimal("10"), basis="RAW")
    with pytest.raises(SwingError, match="^INSUFFICIENT_DATA$"):
        credit.cash_at("2020-01-10", utc_ns("2020-01-09T22:00:00Z"))


def test_review_split_revisions_are_not_applied_twice():
    action = action_record()
    revised = type(action).from_dict(action.to_dict() | {"version": 2, "available_ns": action.available_ns + 1})
    bar = RawBar.from_record(data_record())
    result = split_adjust(
        bar, [CorporateAction.from_record(action), CorporateAction.from_record(revised)], utc_ns("2020-01-06T00:00:00Z")
    )
    assert result.close == Decimal("5") and result.action_hashes == (revised.record_hash,)


def test_review_late_old_split_cannot_replace_known_correction():
    original = action_record()
    corrected = type(original).from_dict(
        original.to_dict()
        | {"version": 2, "available_ns": original.available_ns + 1, "data": original.data | {"ratio": "4"}}
    )
    late_old = type(original).from_dict(original.to_dict() | {"available_ns": original.available_ns + 10})
    bar = RawBar.from_record(data_record())
    result = split_adjust(
        bar,
        [CorporateAction.from_record(corrected), CorporateAction.from_record(late_old)],
        utc_ns("2020-01-06T00:00:00Z"),
    )
    assert result.close == Decimal("2.5")


def test_split_adjusts_only_effective_known_history_price_and_volume_together():
    bar = RawBar.from_record(data_record())
    action = CorporateAction.from_record(action_record())
    before = split_adjust(bar, [action], utc_ns("2020-01-02T22:00:00Z"))
    after = split_adjust(bar, [action], utc_ns("2020-01-03T22:00:00Z"))
    assert before.close == Decimal("10") and before.volume == Decimal("2000000")
    assert after.close == Decimal("5") and after.volume == Decimal("4000000")
    assert after.close * after.volume == before.close * before.volume
    assert after.action_hashes == (action.record.record_hash,)


def test_future_or_late_split_cannot_rewrite_previous_features():
    bar = RawBar.from_record(data_record())
    action = action_record()
    late = type(action).from_dict(action.to_dict() | {"available_ns": utc_ns("2020-01-06T00:00:00Z")})
    assert split_adjust(bar, [CorporateAction.from_record(late)], utc_ns("2020-01-03T22:00:00Z")).close == Decimal("10")


def test_split_position_preserves_quantity_times_stop_and_decimal_context():
    action = CorporateAction.from_record(action_record())
    with localcontext() as context:
        context.prec = 2
        quantity, stop = split_position(Decimal("123"), Decimal("9.25"), action, utc_ns("2020-01-03T22:00:00Z"))
    assert quantity == Decimal("246") and stop == Decimal("4.625")
    assert quantity * stop == Decimal("123") * Decimal("9.25")


def test_dividend_creates_credit_at_ex_date_but_cash_only_at_pay_date():
    action = CorporateAction.from_record(action_record("DIVIDEND"))
    credit = dividend_credit(action, Decimal("10"), basis="RAW")
    assert credit.gross == Decimal("10")
    assert credit.cash_at("2020-01-09", utc_ns("2020-01-09T22:00:00Z")) == 0
    assert credit.cash_at("2020-01-10", utc_ns("2020-01-10T22:00:00Z")) == Decimal("8.50")


def test_unknown_dividend_terms_or_adjusted_total_return_cannot_invent_net_cash():
    action = CorporateAction.from_record(action_record("DIVIDEND", withholding_rate=None))
    credit = dividend_credit(action, Decimal("10"), basis="RAW")
    with pytest.raises(SwingError, match="^INSUFFICIENT_DATA$"):
        credit.cash_at("2020-01-10", utc_ns("2020-01-10T22:00:00Z"))
    with pytest.raises(SwingError):
        dividend_credit(action, Decimal("10"), basis="TOTAL_RETURN")


def test_dividend_is_not_a_split_and_never_back_adjusts_prices():
    bar = RawBar.from_record(data_record())
    dividend = CorporateAction.from_record(action_record("DIVIDEND"))
    assert split_adjust(bar, [dividend], utc_ns("2020-01-10T22:00:00Z")).close == Decimal("10")


@pytest.mark.parametrize("kind", ["DELISTING", "MERGER", "SPINOFF"])
def test_missing_terminal_recovery_is_insufficient_not_zero_or_last_close(kind):
    action = CorporateAction.from_record(action_record(kind))
    result = terminal_resolution(action, utc_ns("2020-01-06T00:00:00Z"))
    assert result.state == "INSUFFICIENTE" and result.cash_per_share is None


def test_attested_cash_and_stock_merger_preserves_successor_identity_and_terms():
    action = CorporateAction.from_record(
        action_record("MERGER", cash_per_share="5", new_listing_id="SUCCESSOR", share_ratio="0.5")
    )
    terms = terminal_resolution(action, utc_ns("2020-01-06T00:00:00Z"))
    assert terms.state == "RESOLVED" and terms.cash_per_share == Decimal("5")
    assert terms.new_listing_id == "SUCCESSOR" and terms.share_ratio == Decimal("0.5")


def test_documented_zero_recovery_is_distinct_from_unknown():
    action = CorporateAction.from_record(action_record("DELISTING", cash_per_share="0", share_ratio="0"))
    assert terminal_resolution(action, utc_ns("2020-01-06T00:00:00Z")).cash_per_share == 0


@pytest.mark.parametrize("ratio", ["0", "-1", "NaN", "Infinity", True, 2.0])
def test_split_ratios_must_be_finite_positive_decimal_strings(ratio):
    with pytest.raises(SwingError):
        CorporateAction.from_record(action_record(ratio=ratio))


def test_adjusted_or_unknown_input_cannot_be_adjusted_again():
    for basis in ["TOTAL_RETURN", "UNKNOWN", "SPLIT_ADJUSTED"]:
        row = data_record()
        bar = RawBar.from_record(type(row).from_dict(row.to_dict() | {"data": row.data | {"basis": basis}}))
        with pytest.raises(SwingError):
            split_adjust(bar, [], utc_ns("2020-01-03T00:00:00Z"))


def test_unknown_currency_cannot_create_usd_dividend():
    action = CorporateAction.from_record(action_record("DIVIDEND", currency=None))
    with pytest.raises(SwingError, match="^INSUFFICIENT_DATA$"):
        dividend_credit(action, Decimal("10"), basis="RAW")


@pytest.mark.parametrize("kind", ["DELISTING", "MERGER", "SPINOFF"])
def test_unknown_currency_cannot_resolve_terminal_cash(kind):
    action = CorporateAction.from_record(action_record(kind, currency=None, cash_per_share="1", share_ratio="0"))
    result = terminal_resolution(action, utc_ns("2020-01-06T00:00:00Z"))
    assert result.state == "INSUFFICIENTE"
    assert result.cash_per_share is None
