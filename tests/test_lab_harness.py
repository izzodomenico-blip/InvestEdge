"""Regressioni offline del segnale: fixture predittiva deliberatamente sintetica."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from backend.app.lab.costs import CostProfile
from backend.app.lab.harness import evaluate_signal, forward_open_returns
from backend.app.lab.simulator import AssetMarket
from backend.app.lab.universe import UniverseInputs

COSTS = CostProfile(1, 10, 50, True, 0)


def synthetic_inputs(assets=20, sessions=1100, *, predictive=True, horizon=1):
    rng = np.random.default_rng(731)
    calendar = list(pd.bdate_range("2018-01-01", periods=sessions).strftime("%Y-%m-%d"))
    markets = {}
    for asset in range(1, assets + 1):
        prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.025, sessions)))
        bars = pd.DataFrame(
            {
                "open_eur": prices,
                "high_eur": prices * 1.01,
                "low_eur": prices * 0.99,
                "close_eur": prices,
                "segment_id": 0,
            },
            index=calendar,
        )
        markets[asset] = AssetMarket(asset, f"A{asset}", "stock", bars)
    labels = forward_open_returns(markets, calendar, horizon)
    # Oracolo di test: usa deliberatamente il futuro, MAI un segnale di produzione.
    rng = np.random.default_rng(912)
    noise = pd.DataFrame(rng.normal(size=labels.shape), index=calendar, columns=labels.columns)
    signals = labels + noise * float(labels.stack().std()) if predictive else noise
    return UniverseInputs(
        markets,
        signals,
        calendar,
        {},
        {},
        0,
        "0" * 64,
        dict.fromkeys(markets, "stock"),
        dict.fromkeys(markets, "UNKNOWN"),
    )


def evaluate(inputs, horizon=1):
    return evaluate_signal(
        inputs.signals,
        forward_open_returns(inputs.markets, inputs.calendar, horizon),
        horizon,
        min_names=10,
        costs=COSTS,
        asset_types=inputs.asset_types,
        reference_capital_eur=10_000,
    )


def test_constructed_predictive_signal_has_positive_ic_and_tstat():
    result = evaluate(synthetic_inputs())
    assert result.ic_mean > 0
    assert result.t_nw >= 2
    assert result.spread_net > 0


def test_random_signal_ic_is_not_significant():
    # Seed fisso 731 per prezzi, 912 per segnale indipendente.
    result = evaluate(synthetic_inputs(predictive=False))
    assert abs(result.t_nw) < 2


def test_labels_use_next_open_to_open():
    inputs = synthetic_inputs(assets=1, sessions=7)
    bars = inputs.markets[1].bars.copy()
    bars["open_eur"] = [1, 2, 6, 12, 24, 48, 96]
    bars["close_eur"] = 999
    market = replace(inputs.markets[1], bars=bars)
    labels = forward_open_returns({1: market}, inputs.calendar, 1)
    assert labels.iloc[0, 0] == 2
    assert labels.iloc[1, 0] == 1
    assert labels.iloc[-2:, 0].isna().all()


def test_labels_never_cross_segments_or_missing_open():
    inputs = synthetic_inputs(assets=1, sessions=9)
    bars = inputs.markets[1].bars.copy()
    bars.loc[inputs.calendar[4] :, "segment_id"] = 1
    bars.loc[inputs.calendar[6], "open_eur"] = np.nan
    labels = forward_open_returns({1: replace(inputs.markets[1], bars=bars)}, inputs.calendar, 1)
    assert labels.iloc[[2, 3, 4, 5], 0].isna().all()
    assert pd.notna(labels.iloc[0, 0])


@pytest.mark.parametrize("names,buckets", [(20, 5), (49, 5), (50, 10), (60, 10)])
def test_quintiles_below_fifty_names_and_deciles_above(names, buckets):
    assert evaluate(synthetic_inputs(assets=names, sessions=80)).bucket_count == buckets


def test_net_spread_subtracts_turnover_costs():
    dates = ["2024-01-01", "2024-01-02"]
    signals = pd.DataFrame([range(10), reversed(range(10))], index=dates, columns=range(10))
    labels = pd.DataFrame([np.arange(10) / 100, np.arange(10)[::-1] / 100], index=dates, columns=range(10))
    result = evaluate_signal(
        signals,
        labels,
        1,
        min_names=10,
        costs=COSTS,
        asset_types=dict.fromkeys(range(10), "stock"),
        reference_capital_eur=10_000,
    )
    # Due nomi per gamba, turnover iniziale e ricambio completo = 1.
    per_leg = 2 * (1 / (10_000 / 2) + 0.001)
    assert result.spread_gross == pytest.approx(0.08)
    assert result.spread_net == pytest.approx(0.08 - 2 * per_leg)
    assert result.turnover_top == 1
    assert result.rank_autocorr == pytest.approx(-1)


def test_missing_and_constant_pairs_have_no_defined_statistics():
    inputs = synthetic_inputs(assets=8, sessions=50)
    result = evaluate(replace(inputs, signals=inputs.signals * 0))
    assert result.ic_dates == 0
    assert result.mean_names == 8
    assert result.ic_mean is result.t_nw is result.spread_net is None


def test_nonoverlapping_rebalances_ignore_intermediate_signal():
    inputs = synthetic_inputs(sessions=100, horizon=5)
    result = evaluate(inputs, 5)
    changed = inputs.signals.copy()
    changed.iloc[[i for i in range(len(changed)) if i % 5], :] *= -1
    other = evaluate(replace(inputs, signals=changed), 5)
    assert result.spread_net == other.spread_net
    assert result.turnover_top == other.turnover_top


def test_bucket_means_use_all_dates_and_spread_only_rebalance_dates():
    inputs = synthetic_inputs(sessions=70, horizon=5)
    before = evaluate(inputs, 5)
    changed = inputs.signals.copy()
    changed.iloc[[i for i in range(len(changed)) if i % 5], :] *= -1
    after = evaluate(replace(inputs, signals=changed), 5)
    assert before.spread_net == after.spread_net
    assert before.bucket_returns != after.bucket_returns


def test_three_names_can_have_ic_without_empty_bucket_crash():
    inputs = synthetic_inputs(assets=3, sessions=30)
    result = evaluate_signal(
        inputs.signals,
        forward_open_returns(inputs.markets, inputs.calendar, 1),
        1,
        min_names=3,
        costs=COSTS,
        asset_types=inputs.asset_types,
        reference_capital_eur=10_000,
    )
    assert result.ic_dates > 0
    assert result.spread_net is None


def test_newey_west_preserves_gap_distances():
    from backend.app.lab.stats import newey_west_tstat, spearman_ic

    dates = list(pd.bdate_range("2024-01-01", periods=9).strftime("%Y-%m-%d"))
    signals = pd.DataFrame([range(10)] * 9, index=dates, columns=range(10), dtype=float)
    labels = signals.copy() * np.nan
    permutations = [
        list(range(10)),
        list(range(10))[::-1],
        [0, 2, 4, 6, 8, 1, 3, 5, 7, 9],
        [1, 0, 3, 2, 5, 4, 7, 6, 9, 8],
    ]
    for i, values in zip([0, 2, 6, 8], permutations, strict=True):
        labels.iloc[i] = values
    result = evaluate_signal(
        signals,
        labels,
        5,
        min_names=10,
        costs=COSTS,
        asset_types=dict.fromkeys(range(10), "stock"),
        reference_capital_eur=10_000,
    )
    ic = np.array([spearman_ic(signals.iloc[i], labels.iloc[i]) for i in [0, 2, 6, 8]])
    residuals = np.zeros(9)
    residuals[[0, 2, 6, 8]] = ic - ic.mean()
    lrv = (residuals @ residuals + sum(2 * (1 - j / 5) * (residuals[j:] @ residuals[:-j]) for j in range(1, 5))) / 4
    assert result.ic_mean == pytest.approx(ic.mean())
    assert result.t_nw == pytest.approx(ic.mean() / np.sqrt(lrv / 4))
    assert result.t_nw != pytest.approx(newey_west_tstat(ic, 4))


def test_common_calendar_metadata_keeps_exact_horizon_rebalances():
    inputs = synthetic_inputs(sessions=85, horizon=5)
    labels = forward_open_returns(inputs.markets, inputs.calendar, 5)
    with_metadata = evaluate(inputs, 5)
    labels.attrs = {}
    without_metadata = evaluate_signal(
        inputs.signals,
        labels,
        5,
        min_names=10,
        costs=COSTS,
        asset_types=inputs.asset_types,
        reference_capital_eur=10_000,
    )
    assert with_metadata.spread_net == without_metadata.spread_net
    assert with_metadata.turnover_top == without_metadata.turnover_top


def test_mixed_calendars_do_not_overlap_holding_periods():
    calendar = list(pd.date_range("2024-01-01", periods=35).strftime("%Y-%m-%d"))
    markets = {}
    for asset in range(20):
        days = calendar if asset >= 10 else [day for day in calendar if pd.Timestamp(day).dayofweek < 5]
        opens = np.array([100 * (1 + asset / 1000) ** i for i in range(len(days))])
        bars = pd.DataFrame(
            {"open_eur": opens, "high_eur": opens, "low_eur": opens, "close_eur": opens, "segment_id": 0}, index=days
        )
        markets[asset] = AssetMarket(asset, f"M{asset}", "crypto" if asset >= 10 else "stock", bars)
    labels = forward_open_returns(markets, calendar, 5)
    signals = pd.DataFrame([range(20)] * 35, index=calendar, columns=range(20))
    # Primo campione: decisione lunedi 1, ingresso martedi 2, ultima exit martedi 9.
    assert labels.attrs["entry_dates"][calendar[0]][0] == "2024-01-02"
    assert labels.attrs["exit_dates"][calendar[0]][0] == "2024-01-09"
    # Candidato sabato6: ingresso crypto domenica7 < exit martedi9: deve essere saltato.
    assert labels.attrs["entry_dates"][calendar[5]][19] == "2024-01-07"
    original = evaluate_signal(
        signals,
        labels,
        5,
        min_names=10,
        costs=COSTS,
        asset_types={a: m.asset_type for a, m in markets.items()},
        reference_capital_eur=10_000,
    )
    signals.loc[calendar[5]] *= -1
    changed = evaluate_signal(
        signals,
        labels,
        5,
        min_names=10,
        costs=COSTS,
        asset_types={a: m.asset_type for a, m in markets.items()},
        reference_capital_eur=10_000,
    )
    assert changed.spread_net == original.spread_net
    assert changed.turnover_top == original.turnover_top


@pytest.mark.parametrize("horizon", [5, 21])
def test_longer_horizon_labels_match_manual_open_ratio(horizon):
    inputs = synthetic_inputs(assets=1, sessions=25)
    bars = inputs.markets[1].bars.copy()
    bars["open_eur"] = np.arange(100, 125, dtype=float)
    labels = forward_open_returns({1: replace(inputs.markets[1], bars=bars)}, inputs.calendar, horizon)
    assert labels.iloc[0, 0] == pytest.approx(horizon / 101)
    assert labels.iloc[-horizon - 1 :, 0].isna().all()


def test_constant_signal_with_enough_names_has_undefined_ic():
    inputs = synthetic_inputs(assets=20, sessions=30)
    result = evaluate(replace(inputs, signals=inputs.signals * 0))
    assert result.ic_dates == 0
    assert result.ic_mean is result.t_nw is result.ic_ir is None


def test_partial_turnover_and_crypto_costs_are_subtracted_on_both_legs():
    dates = ["2024-01-01", "2024-01-02"]
    first, second = list(range(10)), list(range(10))
    second[7], second[8] = second[8], second[7]
    second[0], second[2] = second[2], second[0]
    signals = pd.DataFrame([first, second], index=dates, columns=range(10))
    labels = pd.DataFrame([np.arange(10) / 100] * 2, index=dates, columns=range(10))
    result = evaluate_signal(
        signals,
        labels,
        1,
        min_names=10,
        costs=COSTS,
        asset_types={i: "crypto" if i == 9 else "stock" for i in range(10)},
        reference_capital_eur=10_000,
    )
    assert result.turnover_top == pytest.approx(0.75)
    assert result.spread_net == pytest.approx((0.08 - 0.0088 + 0.065 - 0.0044) / 2)


def test_bucket_count_is_stable_when_name_count_crosses_fifty():
    inputs = synthetic_inputs(assets=50, sessions=30)
    signals = inputs.signals.copy()
    signals.iloc[0, 0] = np.nan
    assert evaluate(replace(inputs, signals=signals)).bucket_count == 5


def test_column_order_does_not_change_rank_ties_or_costs():
    inputs = synthetic_inputs(assets=20, sessions=30)
    tied = replace(inputs, signals=(inputs.signals * 0).fillna(0))
    before = evaluate(tied)
    after = evaluate(replace(tied, signals=tied.signals.iloc[:, ::-1]))
    assert before == after
