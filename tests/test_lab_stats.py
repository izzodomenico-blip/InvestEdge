"""Statistiche del laboratorio (spec SP1 §8.2, §8.5): Spearman, Newey-West, Sharpe, momenti, PSR e DSR.

I valori attesi sono calcolati a mano nei commenti (somme dei casi piccoli) o con le formule della spec scritte nel
test con `statistics.NormalDist`, mai copiati dall'output del codice sotto test.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pandas as pd
import pytest

from backend.app.lab.stats import (
    EULER_MASCHERONI,
    deflated_sharpe,
    expected_max_sharpe,
    newey_west_tstat,
    probabilistic_sharpe,
    return_moments,
    sharpe_daily,
    spearman_ic,
)


def test_newey_west_known_values() -> None:
    assert newey_west_tstat([1, 2, 3, 4], lag=0) == pytest.approx(2.5 / math.sqrt(1.25 / 4))
    assert newey_west_tstat([1, 2, 3, 4], lag=1) == pytest.approx(4.0)


def test_newey_west_hand_computed_lag_two() -> None:
    # x = [2, 4, 1, 3, 5]: media 3, scarti d = [-1, 1, -2, 0, 2], n = 5.
    # gamma_0 = (1 + 1 + 4 + 0 + 4) / 5 = 2
    # gamma_1 = (d2 d1 + d3 d2 + d4 d3 + d5 d4) / 5 = (-1 - 2 + 0 + 0) / 5 = -3/5
    # gamma_2 = (d3 d1 + d4 d2 + d5 d3) / 5 = (2 + 0 - 4) / 5 = -2/5
    # Bartlett, lag 2: LRV = 2 + 2 (2/3 · (-3/5) + 1/3 · (-2/5)) = 2 - 16/15 = 14/15
    # t = 3 / sqrt((14/15) / 5) = 3 sqrt(75/14)
    assert newey_west_tstat([2, 4, 1, 3, 5], lag=2) == pytest.approx(3 * math.sqrt(75 / 14))
    # lag 0: t = 3 / sqrt(2 / 5)
    assert newey_west_tstat([2, 4, 1, 3, 5], lag=0) == pytest.approx(3 / math.sqrt(2 / 5))


def test_newey_west_undefined_and_invalid_inputs() -> None:
    assert newey_west_tstat([0.1] * 30, lag=4) is None      # serie costante: varianza nulla
    assert newey_west_tstat([0.3], lag=0) is None
    assert newey_west_tstat([], lag=0) is None
    with pytest.raises(ValueError):
        newey_west_tstat([1, 2, 3], lag=-1)
    with pytest.raises(ValueError):
        newey_west_tstat([1, math.nan, 3], lag=1)


def test_spearman_ic_known_values() -> None:
    assert spearman_ic(pd.Series([1, 2, 3, 4]), pd.Series([10, 20, 30, 40])) == pytest.approx(1.0)
    assert spearman_ic(pd.Series([1, 2, 3, 4]), pd.Series([40, 30, 20, 10])) == pytest.approx(-1.0)
    assert spearman_ic(pd.Series([1, 2]), pd.Series([1, 2])) is None


def test_spearman_ic_hand_computed_with_ties_alignment_and_missing_values() -> None:
    # Senza parita: ranghi [1..5] e [2, 1, 4, 3, 5], d = [-1, 1, -1, 1, 0], sum d^2 = 4:
    # rho = 1 - 6 · 4 / (5 · (25 - 1)) = 0,8.
    assert spearman_ic(pd.Series([1, 2, 3, 4, 5]), pd.Series([2, 1, 4, 3, 5])) == pytest.approx(0.8)
    # Con parita (ranghi medi): segnale [1, 2, 2, 3] -> [1; 2,5; 2,5; 4], etichetta [10, 30, 20, 40] -> [1, 3, 2, 4].
    # Scarti dalla media 2,5: [-1,5; 0; 0; 1,5] e [-1,5; 0,5; -0,5; 1,5]; somma prodotti 4,5;
    # somme dei quadrati 4,5 e 5: rho = 4,5 / sqrt(22,5) = sqrt(0,9).
    assert spearman_ic(pd.Series([1, 2, 2, 3]), pd.Series([10, 30, 20, 40])) == pytest.approx(math.sqrt(0.9))
    # Allineamento per indice (asset_id) e coppie incomplete scartate: restano a, b, c, d come nel caso con parita.
    signal = pd.Series({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0, "e": math.nan, "f": 9.0})
    label = pd.Series({"d": 40.0, "c": 20.0, "b": 30.0, "a": 10.0, "e": 50.0, "g": 1.0})
    assert spearman_ic(signal, label) == pytest.approx(math.sqrt(0.9))
    # Varianza nulla di uno dei due ranghi: IC non definito.
    assert spearman_ic(pd.Series([5, 5, 5, 5]), pd.Series([1, 2, 3, 4])) is None


def test_sharpe_daily_and_moments_hand_computed() -> None:
    # r = [0,03; -0,01; 0,02; 0]: media 0,01, scarti [0,02; -0,02; 0,01; -0,01], somma dei quadrati 0,001.
    returns = pd.Series([0.03, -0.01, 0.02, 0.0])
    # Sharpe = 0,01 / sqrt(0,001 / 3) = sqrt(0,3) (deviazione standard campionaria, tasso privo di rischio 0).
    assert sharpe_daily(returns) == pytest.approx(math.sqrt(0.3))
    # Momenti centrali (stimatori di popolazione): m2 = 0,001/4; m3 = (8 - 8 + 1 - 1)e-6 / 4 = 0;
    # m4 = (16 + 16 + 1 + 1)e-8 / 4 = 8,5e-8 -> asimmetria 0, curtosi 8,5e-8 / (2,5e-4)^2 = 1,36.
    skew, kurtosis = return_moments(returns)
    assert skew == pytest.approx(0.0, abs=1e-12)
    assert kurtosis == pytest.approx(1.36)
    # x = [1, 2, 3, 10]: media 4, scarti [-3, -2, -1, 6]; m2 = 50/4, m3 = 180/4, m4 = 1394/4.
    skew, kurtosis = return_moments(pd.Series([1.0, 2.0, 3.0, 10.0]))
    assert skew == pytest.approx(45 / 12.5**1.5)
    assert kurtosis == pytest.approx(348.5 / 12.5**2)


def test_sharpe_daily_is_undefined_without_variation() -> None:
    assert sharpe_daily(pd.Series([0.01])) is None
    assert sharpe_daily(pd.Series([0.0, 0.0, 0.0])) is None
    assert sharpe_daily(pd.Series([0.001] * 7)) is None
    assert sharpe_daily(pd.Series([0.01, math.nan, 0.02])) is None
    with pytest.raises(ValueError):
        return_moments(pd.Series([0.002] * 5))


def test_probabilistic_sharpe_formula() -> None:
    expected = NormalDist().cdf(0.1 * math.sqrt(252) / math.sqrt(1 + 0.5 * 0.01))
    assert probabilistic_sharpe(0.1, 0.0, 253, 0.0, 3.0) == pytest.approx(expected)


def test_expected_max_sharpe_formula_and_edge_cases() -> None:
    sharpes = [0.02, 0.04, 0.06, 0.08]
    n = len(sharpes)
    variance = pd.Series(sharpes).var(ddof=1)
    inv = NormalDist().inv_cdf
    expected = math.sqrt(variance) * (
        (1 - EULER_MASCHERONI) * inv(1 - 1 / n) + EULER_MASCHERONI * inv(1 - 1 / (n * math.e))
    )
    assert expected_max_sharpe(sharpes) == pytest.approx(expected)
    assert expected_max_sharpe([0.05]) == 0.0
    assert expected_max_sharpe([0.05, 0.05]) == 0.0
    assert expected_max_sharpe([]) == 0.0


def test_dsr_hand_computed_reference() -> None:
    # Rendimenti OOS del caso a mano: S = sqrt(0,3), asimmetria 0, curtosi 1,36, T = 4.
    returns = pd.Series([0.03, -0.01, 0.02, 0.0])
    # Tentativi [0,1; 0,3]: N = 2, V = (0,1^2 + 0,1^2) / 1 = 0,02; Phi^-1(1 - 1/2) = 0, quindi
    # SR0 = sqrt(0,02) · gamma · Phi^-1(1 - 1/(2e)).
    inv = NormalDist().inv_cdf
    sr = math.sqrt(0.3)
    sr0 = math.sqrt(0.02) * EULER_MASCHERONI * inv(1 - 1 / (2 * math.e))
    # Denominatore: 1 - 0 · S + (1,36 - 1) / 4 · S^2 = 1 + 0,09 · 0,3.
    expected = NormalDist().cdf((sr - sr0) * math.sqrt(4 - 1) / math.sqrt(1 + 0.09 * 0.3))

    result = deflated_sharpe(returns, [0.1, 0.3])

    assert result is not None
    assert result.dsr == pytest.approx(expected)
    assert result.sr == pytest.approx(sr)
    assert result.sr0 == pytest.approx(sr0)
    assert (result.n_trials, result.n_obs) == (2, 4)
    assert result.skew == pytest.approx(0.0, abs=1e-12)
    assert result.kurtosis == pytest.approx(1.36)
    # Un solo tentativo (o varianza nulla): SR0 = 0 e il DSR coincide con il PSR rispetto a 0.
    single = deflated_sharpe(returns, [0.2])
    assert single is not None
    assert single.sr0 == 0.0
    assert single.dsr == pytest.approx(NormalDist().cdf(sr * math.sqrt(3) / math.sqrt(1 + 0.09 * 0.3)))


def test_dsr_decreases_when_more_trials_are_counted() -> None:
    # Sharpe giornaliero ~0,025: lontano dalla saturazione di Phi, cosi' i due DSR restano distinti.
    returns = pd.Series([0.01, -0.009, 0.004, -0.004, 0.002, -0.002] * 60)
    few = deflated_sharpe(returns, [-0.03, 0.03])
    many = deflated_sharpe(returns, [-0.03, 0.03] * 20)
    assert many.dsr < few.dsr
    assert many.n_trials == 40


def test_dsr_is_undefined_without_oos_variation() -> None:
    assert deflated_sharpe(pd.Series([0.0] * 20), [0.01, 0.02]) is None
    assert deflated_sharpe(pd.Series([0.01]), [0.01, 0.02]) is None
