"""Statistiche del laboratorio (spec SP1 §8.2, §8.5): Spearman, Newey-West, Sharpe, momenti, PSR e DSR.

- `spearman_ic`: correlazione di Pearson dei ranghi medi (parita gestite), sulle coppie finite allineate per indice.
- `newey_west_tstat`: t della media con varianza di lungo periodo di Newey-West (1987), pesi di Bartlett
  `1 - j / (lag + 1)` e autocovarianze `gamma_j = (1/n) sum (x_t - mu)(x_{t-j} - mu)`.
- `sharpe_daily`: media / deviazione standard campionaria (ddof 1) dei rendimenti giornalieri, tasso privo di
  rischio 0, non annualizzato (stessa definizione dei tentativi del registro).
- `return_moments`: asimmetria e curtosi non in eccesso con gli stimatori di popolazione `m3 / m2^1.5` e `m4 / m2^2`
  (come in Bailey e Lopez de Prado): con questi `1 - g3 S + (g4 - 1) / 4 S^2 >= (1 - g3 S / 2)^2 >= 0`.
- PSR e DSR di Bailey e Lopez de Prado (2014), con `statistics.NormalDist` per Phi e Phi^-1.

Valori non definiti (meno osservazioni del necessario, varianza nulla, input non finiti) -> `None`, mai NaN.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

EULER_MASCHERONI = 0.5772156649015329
_NORMAL = NormalDist()


def _as_array(values: Sequence[float] | pd.Series) -> np.ndarray:
    return np.asarray(values, dtype=float).reshape(-1)


def _varies(values: np.ndarray) -> bool:
    """Almeno due valori diversi: una serie costante ha varianza nulla anche se l'arrotondamento dice altro."""
    return values.shape[0] >= 2 and float(np.ptp(values)) > 0


def spearman_ic(signal: pd.Series, label: pd.Series) -> float | None:
    """IC di rango; None con meno di 3 coppie finite o con ranghi senza variazione."""
    frame = pd.DataFrame({"signal": signal.astype(float), "label": label.astype(float)})
    frame = frame[np.isfinite(frame.to_numpy()).all(axis=1)]
    if len(frame) < 3:
        return None
    ranks = frame.rank(method="average").to_numpy(dtype=float)
    x = ranks[:, 0] - ranks[:, 0].mean()
    y = ranks[:, 1] - ranks[:, 1].mean()
    denominator = math.sqrt(float(x @ x) * float(y @ y))
    if not math.isfinite(denominator) or denominator <= 0:
        return None
    return max(-1.0, min(1.0, float(x @ y) / denominator))


def newey_west_tstat(values: Sequence[float], lag: int) -> float | None:
    """t di Newey-West della media; None con meno di 2 valori o varianza di lungo periodo nulla."""
    if lag < 0:
        raise ValueError("Il lag di Newey-West non puo essere negativo.")
    x = _as_array(values)
    if not np.isfinite(x).all():
        raise ValueError("La serie di Newey-West deve contenere solo valori finiti.")
    n = x.shape[0]
    if not _varies(x):
        return None
    mean = float(x.mean())
    deviations = x - mean
    variance = float(deviations @ deviations) / n
    for j in range(1, min(lag, n - 1) + 1):
        gamma = float(deviations[j:] @ deviations[:-j]) / n
        variance += 2 * (1 - j / (lag + 1)) * gamma
    if not math.isfinite(variance) or variance <= 0:
        return None
    return mean / math.sqrt(variance / n)


def sharpe_daily(returns: pd.Series) -> float | None:
    """Sharpe giornaliero (tasso privo di rischio 0, non annualizzato); None se non definito."""
    values = _as_array(returns)
    if not np.isfinite(values).all() or not _varies(values):
        return None
    deviation = float(np.std(values, ddof=1))
    if not math.isfinite(deviation) or deviation <= 0:
        return None
    return float(np.mean(values)) / deviation


def return_moments(returns: pd.Series) -> tuple[float, float]:
    """(asimmetria, curtosi non in eccesso) dei rendimenti, stimatori di popolazione."""
    values = _as_array(returns)
    if not np.isfinite(values).all() or not _varies(values):
        raise ValueError("Momenti non definiti: servono almeno 2 rendimenti finiti con varianza positiva.")
    deviations = values - values.mean()
    m2 = float(np.mean(deviations**2))
    m3 = float(np.mean(deviations**3))
    m4 = float(np.mean(deviations**4))
    return m3 / m2**1.5, m4 / m2**2


def probabilistic_sharpe(sr: float, sr0: float, n_obs: int, skew: float, kurt: float) -> float:
    """PSR: Phi((sr - sr0) sqrt(n_obs - 1) / sqrt(1 - skew sr + (kurt - 1) / 4 sr^2)); NaN se non definito."""
    if n_obs < 2:
        raise ValueError("Servono almeno 2 osservazioni.")
    denominator = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if not math.isfinite(denominator) or denominator <= 0:
        return math.nan
    return _NORMAL.cdf((sr - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denominator))


def expected_max_sharpe(trial_sharpes: Sequence[float]) -> float:
    """SR0 = sqrt(V) ((1 - g) Phi^-1(1 - 1/N) + g Phi^-1(1 - 1/(N e))); 0 con N <= 1 o V = 0 (V campionaria)."""
    values = _as_array(trial_sharpes)
    if not np.isfinite(values).all():
        raise ValueError("Gli Sharpe dei tentativi devono essere finiti.")
    n = values.shape[0]
    if n <= 1 or not _varies(values):
        return 0.0
    variance = float(np.var(values, ddof=1))
    if not math.isfinite(variance) or variance <= 0:
        return 0.0
    return math.sqrt(variance) * (
        (1 - EULER_MASCHERONI) * _NORMAL.inv_cdf(1 - 1 / n)
        + EULER_MASCHERONI * _NORMAL.inv_cdf(1 - 1 / (n * math.e))
    )


@dataclass(frozen=True)
class DsrResult:
    dsr: float
    sr: float          # Sharpe giornaliero dei rendimenti valutati
    sr0: float         # massimo atteso degli Sharpe dei tentativi (giornaliero)
    n_trials: int
    n_obs: int
    skew: float
    kurtosis: float    # non in eccesso


def deflated_sharpe(returns: pd.Series, trial_sharpes: Sequence[float]) -> DsrResult | None:
    """DSR dei rendimenti (T = osservazioni) contro N = `len(trial_sharpes)` tentativi; None se non definito."""
    sr = sharpe_daily(returns)
    if sr is None:
        return None
    skew, kurtosis = return_moments(returns)
    n_obs = int(_as_array(returns).shape[0])
    sr0 = expected_max_sharpe(trial_sharpes)
    dsr = probabilistic_sharpe(sr, sr0, n_obs, skew, kurtosis)
    if not math.isfinite(dsr):
        return None
    return DsrResult(
        dsr=dsr, sr=sr, sr0=sr0, n_trials=len(trial_sharpes), n_obs=n_obs, skew=skew, kurtosis=kurtosis
    )
