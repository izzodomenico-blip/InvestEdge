# InvestEdge SP1 "Laboratorio di verità" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un laboratorio che produce evidenza riproducibile fuori campione, al netto dei costi Trade Republic e in EUR, solo su dati reali, con un verdetto dichiarato per segnale × timeframe × orizzonte; uno score unico, identico in interfaccia, backtest e ML.

**Architecture:** Nuovo pacchetto `backend/app/lab/` di unità pure e piccole (feature causali a finestra limitata, score v1, serie e segmenti, simulatore, statistiche, harness, walk-forward, evidenza, job). La tabella `features_daily` è l'unica fonte di feature e score; `ScoringEngine`, `BacktestEngine`, `MLDatasetService` e il servizio di analisi tecnica diventano adattatori sottili. Le operazioni lunghe girano come job asincroni in un thread locale.

**Tech Stack:** Python 3.14 (`backend/.venv`), FastAPI, Pydantic, SQLite, pandas, numpy, scikit-learn, `statistics.NormalDist`, pytest, Ruff; React 18, TypeScript, Vite, Vitest, Testing Library; PowerShell e Git/GitHub. Nessuna nuova dipendenza.

**Spec:** `docs/superpowers/specs/2026-10-02-investedge-sp1-truth-lab-design.md` (autoritativa). Contesto: spec di programma `2026-09-30-investedge-profit-engine-program-design.md` §4–§7, report Fase 2 `docs/reports/2026-08-16-phase-2-verification.md` (*Residual risks*).

## Global Constraints

- Regole di `AGENTS.md` sempre valide: TDD (RED per il motivo previsto, GREEN, review), test **offline** con sole fixture locali o sintetiche, modifiche chirurgiche ai soli file autorizzati del task, un solo writer per task.
- Nessun segreto in git, URL, query string, log, eccezioni, fixture, report, risposte API, job o messaggi. Nessuna credenziale inserita dagli agenti, nessun trading reale, nessuno scraping o automazione di Trade Republic, nessuna spesa.
- Mai aprire o modificare `data/investedge.db`: test e smoke usano `INVESTEDGE_DB_PATH` su file temporanei.
- Dati DEMO mai mescolati con dati REAL: un run, una serie, una riga di `features_daily` hanno un solo `data_mode`. Harness, verdetti e registro dei tentativi accettano solo `REAL`.
- Versioni dichiarate: `PIPELINE_VERSION = "features-v1"`, `SCORE_VERSION = "score-v1"`, `engine_version = "v1"` per i nuovi run di backtest (`"v0"` per quelli esistenti).
- Default di configurazione (spec §16): `LAB_MIN_NAMES=10`, `LAB_MIN_IC_DATES=252`, `LAB_MIN_OOS_SESSIONS=252`, `LAB_MIN_T_STAT=2.0`, `LAB_MIN_DSR=0.95`, `LAB_WF_IS_SESSIONS=504`, `LAB_WF_OOS_SESSIONS=126`, `LAB_SEGMENT_MAX_GAP_SESSIONS=5`, `LAB_SPLIT_TOLERANCE=0.03`, `LAB_ORDER_MAX_PENDING_SESSIONS=5`, `LAB_REFERENCE_CAPITAL_EUR=10000`, `TR_COMMISSION_EUR=1.00`, `TR_COST_BPS_EQUITY=10`, `TR_COST_BPS_CRYPTO=50`, `BACKTEST_FRACTIONAL_SHARES=false`, `BACKTEST_MIN_TRADE_EUR=100`, `ECB_FX_MAX_AGE_DAYS=7` (esistente).
- Orizzonti dell'harness: 1, 5, 21 sedute. Timeframe: `D`, `W`, `M`. Verdetti in codice: `VALIDATO`, `NON_VALIDATO`, `INSUFFICIENTE` (UI: "VALIDATO", "NON VALIDATO", "INSUFFICIENTE", più "NON MISURATO" senza report).
- Errori API: 409 con `detail={"reason_code": ...}` (stesso formato delle route Fase 2), 422 per parametri non validi, 404 per risorse assenti; messaggi senza percorsi, URL, tracce o segreti.
- Migrazioni solo additive in `backend/app/database.py` (`BASE_SCHEMA`, `INDEX_SCHEMA`, `MIGRATIONS`), con il backup pre-migrazione esistente di `prepare_database`. Tabelle append-only protette da trigger come quelle della Fase 2.
- `TechnicalAnalysisService.enrich_price_history` resta solo per le sovrapposizioni del grafico; un test di confine vieta agli altri moduli di importarlo (Task 7).
- Vietati: force-push, rebase/amend di commit pubblicati, reset distruttivi, cancellazione di branch remoti, `npm audit fix --force`.

## Protocollo per ogni task

1. Nuova chat con contesto pulito per ogni task, salvo deroga esplicita dell'utente. Leggere `AGENTS.md`, `PROGRAMMA-OPERATIVO.md`, la spec SP1 e questo piano. Eseguire solo il primo task `NON INIZIATO` con dipendenze `FATTO`.
2. Branch: `investedge/sp1-task-N`. Base del Task 1: `origin/investedge/sp1-task-0`; base del Task N: `origin/investedge/sp1-task-(N-1)`. Pubblicare subito il branch (lock di presa in carico).
3. Verifica della base (sostituire solo i due valori):

```powershell
$taskBaseRef = "origin/investedge/sp1-task-0"
$taskBaseRemoteRef = "refs/heads/investedge/sp1-task-0"
git fetch origin
$taskBaseSha = (git rev-parse $taskBaseRef).Trim()
$taskRemoteSha = ((git ls-remote origin $taskBaseRemoteRef) -split "\s+")[0]
if ($LASTEXITCODE -ne 0 -or -not $taskRemoteSha -or $taskBaseSha -ne $taskRemoteSha) { throw "Base remota non verificata" }
git switch -c investedge/sp1-task-N $taskBaseRef
git push -u origin HEAD
git status --short
```

   Expected: working tree pulito, `HEAD == $taskBaseSha`. Se Git o registro divergono, fermarsi e chiedere all'utente.
4. TDD con `superpowers:test-driven-development`; per failure inattese `superpowers:systematic-debugging`.
5. Prima del commit: test mirati del task, suite completa `pytest -p no:cacheprovider --junitxml=<scratch>\junit.xml` (conteggi dal JUnit XML: `pytest.ini` ha già `addopts = -q`), `ruff check backend scripts tests`, per i task frontend `npm --prefix frontend run test:run` e `npm --prefix frontend run build`, `git diff --check`, review del diff e `superpowers:requesting-code-review`. Ogni rilievo Critical o Important va corretto e riverificato nel task.
6. Chiusura nello stesso commit del task (AGENTS.md §5): checkbox del task spuntate in questo piano; riga del task in `PROGRAMMA-OPERATIVO.md` a `FATTO` con data ed evidenza (comandi e numero di test verdi); colonna *Commit* del task precedente con il suo SHA; sezione *Prossimo passo* aggiornata.
7. Un commit per task con il messaggio indicato, più eventuali commit `chore: checkpoint sp1 task N ...` documentati in *Note di ripresa* se il lavoro si interrompe. Push con `git push -u origin HEAD`, poi gate: `git ls-remote origin refs/heads/investedge/sp1-task-N` deve coincidere con `git rev-parse HEAD` e il working tree deve essere pulito.
8. Merge fast-forward su `main` al gate finale di SP1 (Task 16), previa conferma dell'utente. L'autorizzazione al merge per task del registro decisioni (2026-09-30) resta utilizzabile solo su richiesta esplicita dell'utente.

Comandi di riferimento (radice del worktree, PowerShell):

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_lab_features.py -p no:cacheprovider
& '.\backend\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider --junitxml=$env:TEMP\sp1-junit.xml
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests
npm --prefix frontend run test:run
npm --prefix frontend run build
git diff --check
```

## Mappa della baseline e confini

- `price_history` (per `asset_id`, con `is_real_data`, `provider`, `observation_id`) è il read model dei prezzi; le righe seed hanno `is_real_data = 0`. Stooq salva `adjusted_close = close`.
- `ScoringEngine.score_prices` (UI), `BacktestEngine._score_row` (backtest) e `MLDatasetService._trend_score` e collegati (ML) sono le tre formule da sostituire con `score_v1`. `MarketDataService._recalculate_signal` e `backend/scripts/seed_database.py` scrivono `signals`.
- `TechnicalAnalysisService.enrich_price_history` serve `prices_service` (grafico) e oggi alimenta score, backtest e ML.
- `EcbFxProvider.fetch_rate` scarica 2 osservazioni; `FXService.get_rate` risolve diretto/inverso dalla tabella `fx_rates`.
- Route sincrone in `backend/app/api/routes.py`; il lifespan dell'app è in `backend/app/main.py`.
- Frontend: `BacktestPage.tsx` (modalità singola, confronto, walk-forward), `MachineLearningPage.tsx`; score mostrato in `AnalysisPage`, `WatchlistPage`, `DashboardPage`, `TodayPage`; client in `frontend/src/lib/api.ts` (`apiGet`, `apiPost`, `ApiError`, `apiReasonCode`).
- Schemi con score da estendere con `data_mode`: `AssetOut`, `SignalOut`, `TechnicalAnalysisOut`, `ActionItemOut` (`backend/app/models/schemas.py`).

## Contratti condivisi (riferimento per tutti i task)

```text
# backend/app/lab/contracts.py (Task 2)
DataMode = Literal["REAL", "DEMO"]
Timeframe = Literal["D", "W", "M"]
PIPELINE_VERSION = "features-v1"
SCORE_VERSION = "score-v1"
PERIODS_PER_YEAR: dict[Timeframe, int] = {"D": 252, "W": 52, "M": 12}
class LabError(ValueError):            # errore atteso e sicuro da mostrare
    code: str                          # reason code stabile, es. "LAB_NO_REAL_SERIES"
    message: str                       # messaggio italiano senza dati sensibili
```

---

### Task 1: Fixture seed condivisa e guardia di rete globale

**Branch:** `investedge/sp1-task-1` — **Base:** `origin/investedge/sp1-task-0`

**Files:**
- Create: `tests/conftest.py`, `tests/test_test_infrastructure.py`
- Modify: `tests/test_api.py` (solo la fixture `client`)
- Modify: `docs/superpowers/plans/2026-10-02-investedge-sp1-truth-lab.md`, `PROGRAMMA-OPERATIVO.md`

**Caller da preservare:** tutti i test che usano `client` (173 in `tests/test_api.py`), i test che chiamano `seed_database` direttamente (`test_database.py`, `test_portfolio_accounting.py`) restano invariati.

**Interfaces — Produces:**

```text
# tests/conftest.py
fixture (session) seeded_db_template -> Path      # DB seed creato una volta, con la riga fx USD->EUR della fixture client
fixture (autouse) block_network                    # socket.create_connection, socket.socket.connect, socket.getaddrinfo -> RuntimeError("NETWORK_BLOCKED_IN_TESTS")
CLIENT_ENV: dict[str, str]                         # variabili d'ambiente oggi impostate nella fixture client
```

- [x] **Step 1: Misurare la baseline**

```powershell
Measure-Command { & '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_api.py -p no:cacheprovider } | Select-Object TotalSeconds
```

Annotare i secondi per l'evidenza del task.

- [x] **Step 2: Scrivere i test RED**

Creare `tests/test_test_infrastructure.py` (guardia e template; `tests/conftest.py` arriva allo Step 4):

```python
import socket

import httpx
import pytest


def test_network_is_blocked_in_tests() -> None:
    with pytest.raises(RuntimeError, match="NETWORK_BLOCKED_IN_TESTS"):
        socket.create_connection(("example.com", 443), timeout=1)


def test_httpx_real_transport_is_blocked() -> None:
    with pytest.raises(Exception) as error:
        httpx.get("https://example.com", timeout=1)
    assert "NETWORK_BLOCKED_IN_TESTS" in repr(error.value) or "NETWORK_BLOCKED_IN_TESTS" in repr(error.value.__cause__)


def test_seeded_template_is_copied_per_test(client, seeded_db_template) -> None:
    from backend.app.config import get_settings

    assert get_settings().database_path != seeded_db_template
    assert get_settings().database_path.exists()
```

Aggiungere `tests/test_test_infrastructure.py` all'elenco Files.

- [x] **Step 3: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_test_infrastructure.py -p no:cacheprovider
```

Expected: FAIL (nessuna guardia, fixture `seeded_db_template` inesistente).

- [x] **Step 4: Implementare** in `tests/conftest.py`

- `block_network` (autouse, function scope) con `monkeypatch.setattr` su `socket.create_connection`, `socket.socket.connect` e `socket.getaddrinfo`. Nessuna eccezione per localhost: `TestClient` non usa socket.
- `seeded_db_template` (session scope, `tmp_path_factory`): dentro `pytest.MonkeyPatch.context()` imposta `INVESTEDGE_DB_PATH` sul file template e le stesse variabili della fixture `client` (`CLIENT_ENV`), `get_settings.cache_clear()`, `seed_database(reset=True)`, inserisce la riga `fx_rates` USD→EUR 0.92 `date('now')` della fixture attuale, chiude le connessioni, `get_settings.cache_clear()`.
- Fixture `client` in `tests/test_api.py`: copia il template in `tmp_path / "investedge.db"` con `shutil.copyfile`, imposta `CLIENT_ENV` e `INVESTEDGE_DB_PATH` sul file copiato, `get_settings.cache_clear()`, `TestClient(create_app())` come oggi. Rimuovere solo il seed e l'insert ora duplicati.

- [x] **Step 5: GREEN e regressione**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_test_infrastructure.py tests\test_api.py -p no:cacheprovider
Measure-Command { & '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_api.py -p no:cacheprovider } | Select-Object TotalSeconds
& '.\backend\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider --junitxml=$env:TEMP\sp1-junit.xml
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests
```

Expected: tutti verdi; tempo di `test_api.py` inferiore alla baseline; nessun test con tentativo di rete.

- [x] **Step 6: Chiusura** (protocollo punti 5–7)

Commit: `test: share seeded database and block network in tests`

---

### Task 2: Pipeline di feature causale a finestra limitata (D)

**Branch:** `investedge/sp1-task-2` — **Base:** `origin/investedge/sp1-task-1`

**Files:**
- Create: `backend/app/lab/__init__.py`, `backend/app/lab/contracts.py`, `backend/app/lab/features.py`
- Create: `tests/lab_fixtures.py`, `tests/test_lab_features.py`
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
# backend/app/lab/features.py
FEATURE_COLUMNS_V1: tuple[str, ...] = (
  "sma_20", "sma_50", "sma_200", "price_vs_sma50", "price_vs_sma200", "sma50_vs_sma200",
  "rsi_14", "macd_line", "macd_signal", "macd_histogram", "macd_line_pct", "macd_histogram_pct",
  "stochastic_k", "stochastic_d", "roc_12", "close_return_1d", "close_return_5d", "close_return_20d",
  "volatility_30d", "atr_14", "atr_14_pct", "plus_di", "minus_di", "adx_14", "supertrend_10_3",
  "bollinger_percent_b", "max_drawdown_252", "drawdown_60", "volume_ratio_20", "obv_ratio_20",
  "nearest_support", "nearest_resistance", "support_distance_pct", "resistance_distance_pct",
)
FEATURE_WINDOWS: Mapping[str, int]     # finestra di dipendenza W per colonna (spec §5.3)
NULLABLE_AFTER_WARMUP: frozenset[str]  # nearest_support, nearest_resistance, support_distance_pct, resistance_distance_pct
MAX_FEATURE_WINDOW: int = 252
def truncated_ewm_mean(values: np.ndarray, alpha: float, length: int) -> np.ndarray
def compute_features(bars: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame
    # input: date (YYYY-MM-DD), open, high, low, close, adjusted_close, volume; un solo segmento, ordinato
    # output: date, close_adj + FEATURE_COLUMNS_V1, stesso numero di righe; NaN prima del warm-up

# tests/lab_fixtures.py
def synthetic_bars(n: int, seed: int, start: str = "2018-01-01", freq: str = "B") -> pd.DataFrame
```

Finestre (spec §5.3): `sma_20` 20, `sma_50` 50, `sma_200` 200, `price_vs_sma50` 50, `price_vs_sma200` 200, `sma50_vs_sma200` 200, `rsi_14` 101 (Wilder α=1/14, L=100), `macd_line` 104 (EMA 12 L=48, EMA 26 L=104), `macd_signal`/`macd_histogram`/`macd_*_pct` 139 (EMA 9 L=36), `stochastic_k` 14, `stochastic_d` 16, `roc_12` 13, `close_return_1d/5d/20d` 2/6/21, `volatility_30d` 31 (× √`PERIODS_PER_YEAR[timeframe]`), `atr_14`/`atr_14_pct` 15 (media semplice del true range), `plus_di`/`minus_di` 101 (Wilder L=100), `adx_14` 200 (Wilder L=100 sul DX), `supertrend_10_3` 110 (ATR 10 semplice, stato ricalcolato sulle ultime L=100 barre), `bollinger_percent_b` 20, `max_drawdown_252` 252, `drawdown_60` 60, `volume_ratio_20` 20, `obv_ratio_20` 21, `nearest_*` e `*_distance_pct` 180 (pivot ±2, solo indici ≤ *i*−2). Prezzi rettificati: O/H/L/C × `adjusted_close/close`.

- [x] **Step 1: Scrivere i test RED**

`tests/lab_fixtures.py`:

```python
from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_bars(n: int, seed: int, start: str = "2018-01-01", freq: str = "B") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    volume = rng.integers(100_000, 2_000_000, n).astype(float)
    dates = pd.date_range(start, periods=n, freq=freq).strftime("%Y-%m-%d")
    return pd.DataFrame(
        {"date": dates, "open": open_, "high": high, "low": low, "close": close,
         "adjusted_close": close, "volume": volume}
    )
```

`tests/test_lab_features.py`:

```python
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.lab.features import (
    FEATURE_COLUMNS_V1,
    FEATURE_WINDOWS,
    NULLABLE_AFTER_WARMUP,
    compute_features,
    truncated_ewm_mean,
)
from tests.lab_fixtures import synthetic_bars


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_feature_value_does_not_change_when_future_bars_are_added(seed: int) -> None:
    bars = synthetic_bars(720, seed)
    full = compute_features(bars, "D").set_index("date")
    for cut in (300, 512, 719):
        partial = compute_features(bars.iloc[: cut + 1].reset_index(drop=True), "D").set_index("date")
        pd.testing.assert_frame_equal(
            partial[list(FEATURE_COLUMNS_V1)],
            full.loc[partial.index, list(FEATURE_COLUMNS_V1)],
            check_exact=False, rtol=1e-9, atol=1e-12,
        )


@pytest.mark.parametrize("seed", [7, 11])
def test_feature_value_depends_only_on_its_declared_window(seed: int) -> None:
    bars = synthetic_bars(720, seed)
    full = compute_features(bars, "D")
    row = 700
    for column in FEATURE_COLUMNS_V1:
        window = FEATURE_WINDOWS[column]
        start = row - window + 1
        trimmed = compute_features(bars.iloc[start : row + 1].reset_index(drop=True), "D")
        expected = full.loc[row, column]
        actual = trimmed.iloc[-1][column]
        if column not in NULLABLE_AFTER_WARMUP:
            assert np.isfinite(actual), f"{column}: warm-up oltre la finestra dichiarata {window}"
        if np.isnan(expected):
            assert np.isnan(actual), column
        else:
            assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12), column


def test_feature_is_nan_before_warmup() -> None:
    features = compute_features(synthetic_bars(300, 3), "D")
    for column in FEATURE_COLUMNS_V1:
        window = FEATURE_WINDOWS[column]
        if window > 1:
            assert features[column].iloc[: window - 1].isna().all(), column


def test_chikou_span_is_not_a_feature() -> None:
    assert "chikou_span" not in FEATURE_COLUMNS_V1
    assert "chikou_span" not in compute_features(synthetic_bars(260, 1), "D").columns


def _classic_wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).to_numpy()
    loss = (-delta.clip(upper=0)).to_numpy()
    avg_gain = np.full(len(close), np.nan)
    avg_loss = np.full(len(close), np.nan)
    avg_gain[period] = gain[1 : period + 1].mean()
    avg_loss[period] = loss[1 : period + 1].mean()
    for index in range(period + 1, len(close)):
        avg_gain[index] = (avg_gain[index - 1] * (period - 1) + gain[index]) / period
        avg_loss[index] = (avg_loss[index - 1] * (period - 1) + loss[index]) / period
    return pd.Series(100 - 100 / (1 + avg_gain / avg_loss), index=close.index)


def test_truncated_wilder_rsi_matches_classic_after_warmup() -> None:
    bars = synthetic_bars(1200, 5)
    features = compute_features(bars, "D")
    classic = _classic_wilder_rsi(bars["close"])
    assert (features["rsi_14"] - classic).iloc[400:].abs().max() < 0.1


def test_truncated_ewm_mean_uses_exactly_length_bars() -> None:
    values = np.arange(1.0, 11.0)
    result = truncated_ewm_mean(values, alpha=0.5, length=3)
    expected_last = (10 * 1.0 + 9 * 0.5 + 8 * 0.25) / 1.75
    assert np.isnan(result[:2]).all()
    assert result[-1] == pytest.approx(expected_last)


def test_obv_ratio_is_bounded_and_prices_are_adjusted() -> None:
    bars = synthetic_bars(400, 9)
    features = compute_features(bars, "D")
    ratio = features["obv_ratio_20"].dropna()
    assert ((ratio >= -1) & (ratio <= 1)).all()
    halved = bars.assign(adjusted_close=bars["close"] / 2)
    adjusted = compute_features(halved, "D")
    assert adjusted["sma_20"].iloc[-1] == pytest.approx(features["sma_20"].iloc[-1] / 2)
    assert adjusted["price_vs_sma50"].iloc[-1] == pytest.approx(features["price_vs_sma50"].iloc[-1])
```

- [x] **Step 2: Eseguire RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_lab_features.py -p no:cacheprovider
```

Expected: FAIL in import (`backend.app.lab.features` inesistente).

- [x] **Step 3: Implementare**

`contracts.py` con il blocco dei contratti condivisi. `features.py` vettoriale con numpy/pandas: `truncated_ewm_mean` con pesi `(1-α)^k`, `k = 0..L-1` normalizzati (convoluzione), NaN finché mancano `length` valori; ogni indicatore secondo la tabella; Supertrend con ciclo sulle ultime 100 barre per riga; `max_drawdown_252` esatto sulla finestra; pivot confermati. Nessun import da `backend.app.services.technical_analysis`.

- [x] **Step 4: GREEN**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_lab_features.py -p no:cacheprovider
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests
```

- [x] **Step 5: Chiusura** (suite completa, review, protocollo)

Commit: `feat: add causal window-bounded feature pipeline`

---

### Task 3: Barre W/M e score v1

**Branch:** `investedge/sp1-task-3` — **Base:** `origin/investedge/sp1-task-2`

**Files:**
- Create: `backend/app/lab/resample.py`, `backend/app/lab/score_v1.py`, `tests/test_lab_score.py`
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Consumes:** `compute_features`, `FEATURE_COLUMNS_V1`, `PERIODS_PER_YEAR`.

**Interfaces — Produces:**

```text
# resample.py
def resample_bars(daily: pd.DataFrame, timeframe: Literal["W", "M"], as_of: date) -> pd.DataFrame
    # colonne: date (= available_at, fine periodo di calendario: domenica o ultimo giorno del mese),
    # open, high, low, close, adjusted_close, volume; solo periodi con fine <= as_of
# score_v1.py
SUBSCORE_COLUMNS = ("trend_score", "momentum_score", "volatility_score", "volume_score",
                    "support_resistance_score", "risk_penalty")
SCORE_INPUT_COLUMNS: tuple[str, ...]   # colonne feature lette dalla formula
def explain(row: Mapping[str, Any], risk_level: str) -> dict[str, Any]
    # chiavi come l'output attuale di ScoringEngine.score_prices senza asset_id/symbol:
    # latest_close, score, signal, risk_level, confidence, technical_summary, reasons, subscores,
    # indicators, conditions, support_resistance, summaries
def score_frame(features: pd.DataFrame, risk_level: str) -> pd.DataFrame
    # colonne: score, signal, confidence, *SUBSCORE_COLUMNS, warmup_complete (bool: tutti gli SCORE_INPUT_COLUMNS non NaN,
    # esclusi NULLABLE_AFTER_WARMUP); calcolata riga per riga con la stessa funzione interna di explain
```

`explain` porta la logica di `ScoringEngine.score_prices` e di `TechnicalAnalysisService` (condizioni, sintesi trend/momentum/volatilità/volume, bias, `_risk_level`, `_confidence`) con le sostituzioni di input: `max_drawdown` → `max_drawdown_252`, `obv ≥ 0` → `obv_ratio_20 ≥ 0`, `volatility_annualized_30d` → `volatility_30d`, `close` → `close_adj`, supporti e resistenze da `nearest_*`/`*_distance_pct`. Le condizioni che usano la riga precedente (golden/death cross) non entrano nello score e restano fuori da `explain`.

- [x] **Step 1: Catturare i valori di riferimento dalla formula attuale**

Prima di scrivere `score_v1`, in uno script temporaneo nello scratchpad costruire 6 casi `analysis` (trend rialzista pieno, ribassista, laterale con RSI 70, volatilità alta con drawdown −0,40, dati parziali senza SMA200, vicino a resistenza) e calcolare l'output attuale con:

```python
from unittest.mock import patch

from backend.app.services.scoring_engine import ScoringEngine
from backend.app.services.technical_analysis import TechnicalAnalysisService


def legacy_score(analysis: dict, risk_level: str) -> dict:
    with patch.object(TechnicalAnalysisService, "calculate_full_technical_analysis", return_value=analysis):
        return ScoringEngine().score_prices(None, asset_id=1, symbol="X", risk_level=risk_level)
```

Copiare in `tests/test_lab_score.py` come letterali `GOLDEN_CASES` gli input (`indicators`, `support_resistance`, `latest_close`, `risk_level`) e gli output attesi (`score`, `signal`, `subscores`, `risk_level`, `confidence`, testi di `reasons`).

- [x] **Step 2: Scrivere i test RED**

```python
from __future__ import annotations

from datetime import date

import pytest

from backend.app.lab.features import compute_features
from backend.app.lab.resample import resample_bars
from backend.app.lab.score_v1 import explain, score_frame
from tests.lab_fixtures import synthetic_bars

GOLDEN_CASES: list[dict] = [...]  # letterali catturati allo Step 1


def _row_from_legacy(case: dict) -> dict:
    indicators = case["indicators"]
    row = {name: value for name, value in indicators.items()}
    row["close_adj"] = case["latest_close"]
    row["max_drawdown_252"] = indicators.get("max_drawdown")
    row["obv_ratio_20"] = None if indicators.get("obv") is None else (1.0 if indicators["obv"] >= 0 else -1.0)
    row["volatility_30d"] = indicators.get("volatility_annualized_30d")
    row["nearest_support"] = case["support_resistance"]["nearest_support"]
    row["nearest_resistance"] = case["support_resistance"]["nearest_resistance"]
    row["support_distance_pct"] = case["support_resistance"]["support_distance_percent"]
    row["resistance_distance_pct"] = case["support_resistance"]["resistance_distance_percent"]
    return row


@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_score_v1_reproduces_legacy_formula_on_identical_inputs(case: dict) -> None:
    result = explain(_row_from_legacy(case), case["risk_level"])
    assert result["score"] == case["expected"]["score"]
    assert result["signal"] == case["expected"]["signal"]
    assert result["subscores"] == case["expected"]["subscores"]
    assert result["confidence"] == case["expected"]["confidence"]
    assert result["risk_level"] == case["expected"]["risk_level"]
    assert [reason["message"] for reason in result["reasons"]] == case["expected"]["reason_messages"]


def test_score_frame_matches_explain_row_by_row() -> None:
    features = compute_features(synthetic_bars(400, 2), "D")
    scored = score_frame(features, "medium")
    for index in (260, 300, 399):
        assert explain(features.iloc[index].to_dict(), "medium")["score"] == scored.loc[index, "score"]
    assert not scored.loc[:250, "warmup_complete"].any()
    assert scored.loc[260:, "warmup_complete"].all()


def test_weekly_bar_exists_only_after_period_end() -> None:
    daily = synthetic_bars(30, 1)  # lunedi 2018-01-01
    weekly = resample_bars(daily, "W", as_of=date(2018, 1, 12))
    assert list(weekly["date"]) == ["2018-01-07"]
    first_week = daily.iloc[:5]
    row = weekly.iloc[0]
    assert row["open"] == first_week["open"].iloc[0]
    assert row["high"] == first_week["high"].max()
    assert row["low"] == first_week["low"].min()
    assert row["close"] == first_week["close"].iloc[-1]
    assert row["volume"] == first_week["volume"].sum()


def test_monthly_bar_uses_calendar_month_end_and_crypto_weekends() -> None:
    daily = synthetic_bars(70, 4, start="2024-01-01", freq="D")
    monthly = resample_bars(daily, "M", as_of=date(2024, 3, 10))
    assert list(monthly["date"]) == ["2024-01-31", "2024-02-29"]
    weekly = resample_bars(daily, "W", as_of=date(2024, 1, 7))
    assert weekly.iloc[0]["close"] == daily.loc[daily["date"] == "2024-01-07", "close"].iloc[0]
```

- [x] **Step 3: RED**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest tests\test_lab_score.py -p no:cacheprovider
```

Expected: FAIL in import.

- [x] **Step 4: Implementare `resample.py` e `score_v1.py`**, poi GREEN con lo stesso comando, più `tests\test_lab_features.py` e Ruff.

- [x] **Step 5: Chiusura**

Commit: `feat: add timeframe resampling and score v1`

---

### Task 4: Serie reale/demo, segmenti, guardia split e conversione EUR

**Branch:** `investedge/sp1-task-4` — **Base:** `origin/investedge/sp1-task-3`

**Files:**
- Create: `backend/app/lab/series.py`, `tests/test_lab_series.py`
- Modify: `backend/app/config.py` (impostazioni `LAB_SEGMENT_MAX_GAP_SESSIONS`, `LAB_SPLIT_TOLERANCE`), `.env.example`, `backend/.env.example`
- Modify: `tests/lab_fixtures.py` (helper DB), `tests/conftest.py` (fixture `lab_connection`)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Consumes:** tabelle `assets`, `price_history`, `fx_rates`; `init_db`, `get_connection`; `FXService.get_rate` (solo nel test di coerenza).

**Interfaces — Produces:**

```text
AdjustmentBasis = Literal["NOT_APPLICABLE", "UNKNOWN", "SPLIT", "SPLIT_DIVIDEND"]
PROVIDER_ADJUSTMENT_BASIS: Mapping[str, AdjustmentBasis] = {"coingecko": "NOT_APPLICABLE", "stooq": "UNKNOWN"}
SPLIT_RATIOS = (2.0, 3.0, 4.0, 5.0, 10.0, 1.5)
@dataclass(frozen=True) class SplitEvent: date: str; ratio: float; direction: Literal["FORWARD", "REVERSE"]
@dataclass(frozen=True) class SeriesSegment: segment_id: int; bars: pd.DataFrame
@dataclass(frozen=True) class LabSeries:
    asset_id: int; symbol: str; asset_type: str; currency: str; risk_level: str
    data_mode: DataMode; adjustment_basis: AdjustmentBasis
    segments: tuple[SeriesSegment, ...]; split_events: tuple[SplitEvent, ...]; gap_starts: tuple[str, ...]
    def bar_count(self) -> int
def available_data_modes(connection, asset_id: int) -> frozenset[DataMode]
def preferred_data_mode(connection, asset_id: int) -> DataMode | None      # REAL se esiste, altrimenti DEMO
def split_into_segments(bars, *, asset_type: str, basis: AdjustmentBasis, max_gap_sessions: int,
                        split_tolerance: float) -> tuple[list[pd.DataFrame], list[SplitEvent], list[str]]
def load_series(connection, asset_id: int, data_mode: DataMode) -> LabSeries | None
class EurConverter:
    def __init__(self, connection, *, max_age_days: int) -> None
    def rate_on(self, currency: str, on_date: str) -> float | None          # EUR -> 1.0
    def convert_bars(self, bars: pd.DataFrame, currency: str) -> tuple[pd.DataFrame, int]
        # aggiunge open_eur, high_eur, low_eur, close_eur (prezzi rettificati x cambio); NaN se cambio
        # mancante o piu vecchio di max_age_days; ritorna anche il numero di barre escluse

# tests/lab_fixtures.py
def insert_asset(connection, symbol: str, *, asset_type: str = "stock", currency: str = "EUR",
                 risk_level: str = "medium") -> int
def insert_bars(connection, asset_id: int, bars: pd.DataFrame, *, real: bool, provider: str | None) -> None
def insert_fx(connection, currency: str, rows: Sequence[tuple[str, float]], *, provider: str = "ecb") -> None
# tests/conftest.py
fixture lab_connection -> sqlite3.Connection     # DB temporaneo inizializzato, nessun seed
```

Regole: righe di `data_mode` REAL = `is_real_data = 1`, DEMO = `is_real_data = 0`; con più righe per data nello stesso modo vince quella con `id` maggiore. Base della serie: `NOT_APPLICABLE` solo se tutte le righe hanno provider `coingecko`, altrimenti `UNKNOWN`. Buco: più di `max_gap_sessions` giorni lavorativi (`numpy.busday_count`) per azioni/ETF, giorni di calendario per `asset_type == "crypto"`. Split sospetto solo con base `UNKNOWN`: per un `k` in `SPLIT_RATIOS`, `close_{t-1}/close_t` (FORWARD) o `close_t/close_{t-1}` (REVERSE) entro `split_tolerance` relativa da `k`, e lo stesso rapporto per `close_{t-1}/open_t` o `open_t/close_{t-1}`. Cambio: ultima osservazione con data ≤ `on_date`, stessa direzione e reciprocità di `FXService.get_rate` (riga diretta `X→EUR` oppure inversa `EUR→X` con reciproco).

- [x] **Step 1: Test RED** in `tests/test_lab_series.py`:
  - `test_real_series_never_contains_seed_rows`: asset con righe seed 2018–2019 e righe reali dal 2019-06-03; `load_series(REAL)` contiene solo date reali, `load_series(DEMO)` solo seed; `preferred_data_mode` = `REAL`.
  - `test_business_day_gap_over_limit_opens_new_segment`: buco di 6 giorni lavorativi → 2 segmenti e `gap_starts` con la prima data dopo il buco; buco di 5 → 1 segmento.
  - `test_crypto_gap_counts_calendar_days`.
  - `test_unknown_basis_split_opens_segment`: close e open dimezzati a una data → evento `FORWARD` con `ratio == 2.0`, 2 segmenti; reverse 1:10 rilevato come `REVERSE`.
  - `test_intraday_crash_is_not_a_split`: open normale e close −50% → nessun evento.
  - `test_coingecko_basis_skips_split_guard`.
  - `test_eur_converter_uses_latest_rate_within_max_age`: tassi venerdì; barra lunedì usa venerdì; barra con ultimo tasso a 8 giorni → NaN e conteggio 1; EUR → 1.0.
  - `test_eur_converter_matches_fx_service_direction`: con riga diretta e con riga inversa, `rate_on(oggi)` == `FXService().get_rate(conn, currency).rate`.
- [x] **Step 2: RED** `pytest tests\test_lab_series.py` → FAIL in import.
- [x] **Step 3: Implementare** `series.py`, impostazioni (`lab_segment_max_gap_sessions: int = 5`, `lab_split_tolerance: float = 0.03`) con documentazione nei due `.env.example`, helper e fixture.
- [x] **Step 4: GREEN** con `tests\test_lab_series.py`, `tests\test_config.py`, `tests\test_fx_service.py` e Ruff.
- [x] **Step 5: Chiusura**

Commit: `feat: load real and demo series with segments and EUR conversion`

---

### Task 5: Backfill storico dei cambi BCE

**Branch:** `investedge/sp1-task-5` — **Base:** `origin/investedge/sp1-task-4`

**Files:**
- Modify: `backend/app/data_providers/ecb.py`, `backend/app/services/fx_service.py` (`FxBackfillResult` è un dataclass del servizio)
- Create: `backend/scripts/backfill_fx_history.py`
- Create: `tests/fixtures/market_data/ecb_exr_usd_eur_history.csv`
- Modify: `tests/test_fx_service.py`, `tests/test_reference_providers.py`
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
EcbFxProvider.fetch_history(connection, from_currency: str, start: date, end: date, now: datetime) -> list[FXQuote]
    # GET /service/data/EXR/D.<VAL>.EUR.SP00.A con format=csvdata, startPeriod, endPeriod; nessun lastNObservations;
    # stesso bucket "ecb", stesso trasporto governato, cache_scope f"fx-history:{VAL}:{start}:{end}";
    # righe con TIME_PERIOD futuro scartate (ecb:FX:FUTURE_TIMESTAMP non blocca le altre)
@dataclass(frozen=True) class FxBackfillResult:
    currency: str; inserted: int; existing: int; first_observed_at: str | None; last_observed_at: str | None
FXService.backfill_history(connection, currency: str, start: date, now: datetime | None = None) -> FxBackfillResult
    # inserimento idempotente in fx_rates (ON CONFLICT DO NOTHING), stessa direzione e qualità di refresh_currency
```

Script: `python -m backend.scripts.backfill_fx_history --currency USD --start 2015-01-01` mostra l'anteprima (valute, intervallo, nessuna chiamata); con `--apply` esegue; rifiuta con exit 2 se `ENABLE_REAL_DATA` è falso.

- [ ] **Step 1: Fixture** `ecb_exr_usd_eur_history.csv`: stesso header di `ecb_exr_usd_eur.csv`, 10 righe sintetiche dal 2024-01-02 al 2024-01-15 più una riga con data futura (2099-01-01).
- [ ] **Step 2: Test RED**:
  - in `test_reference_providers.py`: `fetch_history` invia `startPeriod`/`endPeriod` e non `lastNObservations` (asserzione sulla richiesta del `httpx.MockTransport`), consuma 1 unità del budget `ecb`, scarta la riga futura e ritorna 10 quote `reference`;
  - in `test_fx_service.py`: `backfill_history` inserisce 10 righe, il rerun inserisce 0 e conta 10 `existing`; dopo il backfill `EurConverter.rate_on("USD", "2024-01-10")` è coerente con la riga diretta inserita; lo script con `ENABLE_REAL_DATA=false` esce con codice 2 senza rete.
- [ ] **Step 3: RED** `pytest tests\test_reference_providers.py tests\test_fx_service.py -k "history or backfill"` → FAIL (metodi assenti).
- [ ] **Step 4: Implementare**, poi **GREEN** con i due file completi e Ruff.
- [ ] **Step 5: Chiusura**

Commit: `feat: backfill historical ECB FX rates`

---

### Task 6: Feature store `features_daily` incrementale

**Branch:** `investedge/sp1-task-6` — **Base:** `origin/investedge/sp1-task-5`

**Files:**
- Modify: `backend/app/database.py` (tabella e indici)
- Create: `backend/app/lab/feature_store.py`, `tests/test_lab_feature_store.py`
- Modify: `tests/test_database.py` (test di schema)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Schema (`BASE_SCHEMA`):**

```sql
CREATE TABLE IF NOT EXISTS features_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    timeframe TEXT NOT NULL CHECK(timeframe IN ('D', 'W', 'M')),
    date TEXT NOT NULL,
    segment_id INTEGER NOT NULL,
    pipeline_version TEXT NOT NULL,
    score_version TEXT NOT NULL,
    data_mode TEXT NOT NULL CHECK(data_mode IN ('REAL', 'DEMO')),
    window_hash TEXT NOT NULL CHECK(length(window_hash) = 64),
    warmup_complete INTEGER NOT NULL CHECK(warmup_complete IN (0, 1)),
    score REAL,
    trend_score REAL,
    momentum_score REAL,
    volatility_score REAL,
    volume_score REAL,
    support_resistance_score REAL,
    risk_penalty REAL,
    features_json TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE,
    UNIQUE(asset_id, timeframe, date, pipeline_version, data_mode)
);
```

Indice in `INDEX_SCHEMA`: `idx_features_daily_lookup ON features_daily(asset_id, data_mode, timeframe, pipeline_version, date)`.

**Interfaces — Produces:**

```text
@dataclass(frozen=True) class FeatureRefreshResult:
    asset_id: int; data_mode: DataMode; inserted: int; updated: int; deleted: int; unchanged: int
class FeatureStore:
    def compute_rows(self, series: LabSeries, as_of: date) -> pd.DataFrame        # pura: righe D, W, M con window_hash
    def refresh_asset(self, connection, asset_id: int, data_mode: DataMode, now: datetime) -> FeatureRefreshResult | None
    def read_frame(self, connection, asset_ids: Sequence[int], timeframe: Timeframe, data_mode: DataMode, *,
                   start: str | None = None, end: str | None = None, complete_only: bool = True) -> pd.DataFrame
        # colonne: asset_id, date, segment_id, warmup_complete, score, *SUBSCORE_COLUMNS, *FEATURE_COLUMNS_V1
    def signal_panel(self, connection, asset_ids: Sequence[int], timeframe: Timeframe, data_mode: DataMode,
                     signal_name: str, dates: Sequence[str]) -> pd.DataFrame
        # index = dates, colonne = asset_id; D: valore solo se esiste la riga a quella data;
        # W/M: ultima riga con date <= data (merge_asof); solo righe warmup_complete
    def latest_row(self, connection, asset_id: int, data_mode: DataMode) -> dict[str, Any] | None   # D, ultima data
```

`window_hash` di una riga: digest per barra `d = int.from_bytes(sha256(f"{date}|{open!r}|{high!r}|{low!r}|{close!r}|{adjusted_close!r}|{volume!r}").digest()[:8], "big")`; aggregato `(somma dei d nella finestra) mod 2**64` sulle barre del timeframe in `[max(inizio segmento, i - MAX_FEATURE_WINDOW + 1), i]`; `window_hash = sha256(f"{PIPELINE_VERSION}|{SCORE_VERSION}|{timeframe}|{segment_id}|{risk_level}|{prima_data}|{ultima_data}|{n}|{aggregato}").hexdigest()`. Somme cumulative: costo O(n). Refresh: calcola gli hash candidati, ricalcola le feature solo per le righe nuove o cambiate (slice del segmento da `prima riga da ricalcolare − MAX_FEATURE_WINDOW + 1`, valori identici grazie alla proprietà del Task 2), cancella le righe non più candidate, una transazione breve per asset. W/M con `resample_bars(..., as_of=now.date())` per segmento.

- [ ] **Step 1: Test RED** in `tests/test_lab_feature_store.py` (con `lab_connection` e helper):
  - `test_refresh_inserts_d_w_m_rows_with_versions`;
  - `test_second_refresh_changes_nothing` (`unchanged` = totale, `inserted = updated = deleted = 0`);
  - `test_revised_bar_updates_only_rows_whose_window_contains_it`: si modifica il close di una barra a metà serie; le righe D aggiornate sono le 252 righe dalla barra rivista in avanti (meno se il segmento finisce prima), più le righe W/M la cui finestra contiene la barra; nessuna riga precedente cambia;
  - `test_incremental_equals_full_recompute`: dopo la revisione, confronto colonna per colonna con un DB in cui la stessa serie viene calcolata da zero;
  - `test_backfilled_older_bars_change_only_early_rows`;
  - `test_real_and_demo_rows_are_separate`;
  - `test_signal_panel_weekly_uses_last_closed_week` (il lunedì vede la riga della domenica precedente, il venerdì la settimana prima);
  - `test_read_frame_complete_only_filters_warmup`.
  In `tests/test_database.py`: tabella, vincolo univoco e `ON DELETE CASCADE` dalla cancellazione protetta dell'asset.
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** con `tests\test_lab_feature_store.py tests\test_database.py tests\test_lab_features.py tests\test_lab_score.py tests\test_lab_series.py` e Ruff.
- [ ] **Step 5: Chiusura**

Commit: `feat: persist incremental features_daily store`

---

### Task 7: Score unico in segnali e analisi tecnica

**Branch:** `investedge/sp1-task-7` — **Base:** `origin/investedge/sp1-task-6`

**Files:**
- Modify: `backend/app/services/signals_service.py` (nuova `recalculate_signal`), `backend/app/services/market_data_service.py` (`_recalculate_signal` delega), `backend/app/services/scoring_engine.py`, `backend/app/services/technical_analysis_service.py`, `backend/app/services/assets_service.py`, `backend/app/services/action_board_service.py`
- Modify: `backend/app/database.py` (colonna `signals.data_mode`), `backend/app/models/schemas.py` (`data_mode` additivo su `SignalOut`, `TechnicalAnalysisOut`, `ActionItemOut`; `signal_data_mode` e `score_unavailable_reason` su `AssetOut`)
- Modify: `backend/app/api/routes.py` (409 `INSUFFICIENT_REAL_HISTORY` su `/technical-analysis/{symbol}`)
- Modify: `backend/scripts/seed_database.py` (segnali seed via `recalculate_signal`)
- Create: `tests/test_lab_boundaries.py`, `tests/test_lab_signals.py`
- Modify: `tests/test_api.py` (solo test di segnali, analisi tecnica e news che cambiano contratto)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
# signals_service.py
def recalculate_signal(connection, asset_id: int, now: datetime | None = None) -> None
    # data_mode = preferred_data_mode; FeatureStore.refresh_asset; riga D più recente con warmup_complete;
    # explain(row, asset.risk_level); news solo informative: news_score = sentiment medio 7 giorni x peso (come oggi),
    # final_score = score; signals.data_mode valorizzato; senza riga completa: nessun segnale (quello vecchio rimosso)
def score_unavailable_reason(connection, asset_id: int) -> str | None
    # "Storico reale insufficiente (N barre, servono 252)." oppure None
# ScoringEngine.score_prices(prices, asset_id, symbol, risk_level) -> dict
    # stessa firma: compute_features sul frame (un segmento) + explain dell'ultima riga; niente TechnicalAnalysisService
```

Migrazione: `("data_mode", "ALTER TABLE signals ADD COLUMN data_mode TEXT CHECK(data_mode IS NULL OR data_mode IN ('REAL', 'DEMO'))")` in `MIGRATIONS["signals"]`; `SIGNALS_REBUILD_SQL` e la `CREATE TABLE signals` di `BASE_SCHEMA` includono la colonna.

- [ ] **Step 1: Test RED**
  - `tests/test_lab_boundaries.py`: con `ast` sui file di `backend/app/lab/` e su `scoring_engine.py`, `backtest_engine.py`, `ml_dataset_service.py`, `ml_engine.py`, `technical_analysis_service.py`, `signals_service.py`, `market_data_service.py`: nessun import di `backend.app.services.technical_analysis`. (Fallisce oggi su `scoring_engine`, `backtest_engine`, `ml_dataset_service`.)
  - `tests/test_lab_signals.py`:
    - `test_signal_score_equals_features_daily_latest_row` (asset REAL con 400 barre sintetiche reali): `signals.score == features_daily.score` dell'ultima riga D completa e `data_mode == "REAL"`;
    - `test_news_no_longer_changes_final_score`: con news reali positive, `final_score == score` e `news_score != 0`;
    - `test_demo_asset_signal_is_marked_demo`;
    - `test_short_real_history_yields_no_signal_and_reason`: 100 barre reali → nessun segnale e `score_unavailable_reason` = "Storico reale insufficiente (100 barre, servono 252).";
    - `test_score_prices_keeps_signature_and_uses_score_v1`.
  - `tests/test_api.py`: `/signals` e `/assets` espongono `data_mode`/`signal_data_mode`; `/technical-analysis/{symbol}` per asset REAL corto risponde 409 `INSUFFICIENT_REAL_HISTORY`; il test esistente `test_provider_failure_fallback_to_demo_does_not_change_final_score` resta verde.
- [ ] **Step 2: RED** `pytest tests\test_lab_boundaries.py tests\test_lab_signals.py tests\test_api.py -k "signal or technical or boundary or news"` → FAIL per i motivi previsti.
- [ ] **Step 3: Implementare.** `backtest_engine.py` e `ml_dataset_service.py` sono riscritti nei Task 10 e 13: in questo task il test di confine li elenca in `PENDING_BOUNDARY = {"backtest_engine.py", "ml_dataset_service.py"}` con un `xfail(strict=True)` per ciascuno; i Task 10 e 13 rimuovono la voce.
- [ ] **Step 4: GREEN** con suite completa e Ruff.
- [ ] **Step 5: Chiusura**

Commit: `feat: serve the single score v1 to signals and analysis`

---

### Task 8: Job asincroni del laboratorio

**Branch:** `investedge/sp1-task-8` — **Base:** `origin/investedge/sp1-task-7`

**Files:**
- Modify: `backend/app/database.py` (tabella `lab_jobs`), `backend/app/config.py` (`LAB_JOBS_EXECUTOR`), `.env.example`, `backend/.env.example`
- Create: `backend/app/lab/jobs.py`, `backend/app/lab/handlers.py`, `backend/app/api/lab_routes.py`, `backend/app/models/lab.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py` (lifespan e `include_router`; `/data/fx/backfill` vive in `lab_routes.py`)
- Create: `tests/test_lab_jobs.py`
- Modify: `tests/conftest.py` (`LAB_JOBS_EXECUTOR=inline` in `CLIENT_ENV`)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS lab_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('BACKTEST', 'COMPARE', 'WALK_FORWARD', 'EVIDENCE',
                                      'FEATURE_REFRESH', 'FX_BACKFILL', 'ML_TRAIN')),
    status TEXT NOT NULL CHECK(status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'INTERRUPTED')),
    params_json TEXT NOT NULL,
    params_hash TEXT NOT NULL CHECK(length(params_hash) = 64),
    progress REAL NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 1),
    result_ref TEXT,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0, 1)),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
```

Indici: `idx_lab_jobs_status_created ON lab_jobs(status, created_at, id)`; `uq_lab_jobs_open ON lab_jobs(kind, params_hash) WHERE status IN ('QUEUED', 'RUNNING')` (univoco parziale).

**Interfaces — Produces:**

```text
JobKind = Literal["BACKTEST", "COMPARE", "WALK_FORWARD", "EVIDENCE", "FEATURE_REFRESH", "FX_BACKFILL", "ML_TRAIN"]
JobStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"]
class JobCancelled(Exception)
class JobNotCancellable(LabError)       # code "JOB_NOT_CANCELLABLE"
@dataclass(frozen=True) class JobRecord:
    id: int; kind: JobKind; status: JobStatus; params: dict[str, Any]; progress: float
    result_ref: str | None; result: dict[str, Any] | None; error_code: str | None; error_message: str | None
    cancel_requested: bool; created_at: str; started_at: str | None; finished_at: str | None
@dataclass(frozen=True) class JobOutcome: result_ref: str | None = None; result: dict[str, Any] | None = None
class JobContext:
    job_id: int
    def set_progress(self, value: float) -> None
    def raise_if_cancelled(self) -> None              # solleva JobCancelled se cancel_requested
JobHandler = Callable[[JobContext, Mapping[str, Any]], JobOutcome]
def register_job_handler(kind: JobKind, handler: JobHandler) -> None
class JobService:
    def __init__(self, executor: Literal["thread", "inline"]) -> None
    def enqueue(self, kind: JobKind, params: Mapping[str, Any]) -> JobRecord      # dedupe su (kind, params_hash) aperti
    def get(self, job_id: int) -> JobRecord | None
    def list(self, *, limit: int = 20, status: JobStatus | None = None) -> list[JobRecord]
    def cancel(self, job_id: int) -> JobRecord
    def recover_interrupted(self) -> int                                          # RUNNING -> INTERRUPTED
    def start(self) -> None
    def stop(self) -> None
def get_job_service() -> JobService
# models/lab.py
JobOut (campi di JobRecord), FeatureRefreshIn {asset_ids: list[int] | None, data_mode: DataMode | None},
FxBackfillIn {currencies: list[str] (1..10), start_date: str (YYYY-MM-DD)}
```

Regole: un thread worker FIFO; ogni job usa `get_connection()` propria e transazioni brevi; `LabError` → `FAILED` con `error_code`/`error_message` del `LabError`; altre eccezioni → `FAILED`, `INTERNAL_ERROR`, messaggio generico "Errore interno del job." (mai il testo dell'eccezione); `JobCancelled` → `CANCELLED`. Lifespan: dopo `prepare_database` chiama `recover_interrupted()` e `start()`; allo shutdown `stop()`. In modalità `inline` `enqueue` esegue subito il job nella stessa chiamata.

Handler registrati in `handlers.py` in questo task:
- `FEATURE_REFRESH`: per ogni asset (tutti gli asset attivi se `asset_ids` è nullo) e `data_mode` (preferito se nullo) chiama `FeatureStore.refresh_asset`; risultato `{assets: n, inserted, updated, deleted, unchanged}`; `raise_if_cancelled` fra un asset e l'altro.
- `FX_BACKFILL`: `FXService.backfill_history` per ogni valuta; risultato per valuta.

Route in `lab_routes.py`: `GET /lab/jobs?limit=1..100&status=`, `GET /lab/jobs/{job_id}` (404), `POST /lab/jobs/{job_id}/cancel` (409 `JOB_NOT_CANCELLABLE`), `POST /lab/features/refresh` (202), `POST /data/fx/backfill` (202; 409 `REAL_DATA_DISABLED` se `ENABLE_REAL_DATA` è falso, controllato prima di accodare; 422 per valuta non BCE).

- [ ] **Step 1: Test RED** in `tests/test_lab_jobs.py`:
  - `test_inline_job_runs_and_stores_result`;
  - `test_identical_open_job_is_deduplicated` (executor `thread` non avviato: due `enqueue` uguali → stesso id `QUEUED`);
  - `test_cancel_queued_job` e `test_cancel_finished_job_raises_not_cancellable`;
  - `test_running_job_cancels_cooperatively` (executor `thread`, handler che attende un `threading.Event` e chiama `raise_if_cancelled`);
  - `test_recover_interrupted_marks_running_jobs`;
  - `test_lab_error_is_reported_with_code` e `test_unexpected_error_hides_exception_text` (eccezione con testo `"secret-token-123"` assente dal record);
  - API: 404, 409 cancel, `POST /lab/features/refresh` → 202 e job `SUCCEEDED` con conteggi, `POST /data/fx/backfill` → 409 `REAL_DATA_DISABLED` di default e 202 con `ENABLE_REAL_DATA=true` e `FXService.backfill_history` sostituito da un fake.
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** (`tests\test_lab_jobs.py`, suite completa, Ruff).
- [ ] **Step 5: Chiusura**

Commit: `feat: add asynchronous lab jobs`

---

### Task 9: Costi Trade Republic, strategie e simulatore

**Branch:** `investedge/sp1-task-9` — **Base:** `origin/investedge/sp1-task-8`

**Files:**
- Create: `backend/app/lab/costs.py`, `backend/app/lab/strategies.py`, `backend/app/lab/simulator.py`, `tests/test_lab_simulator.py`
- Modify: `backend/app/config.py` (`TR_COMMISSION_EUR`, `TR_COST_BPS_EQUITY`, `TR_COST_BPS_CRYPTO`, `BACKTEST_FRACTIONAL_SHARES`, `BACKTEST_MIN_TRADE_EUR`, `LAB_ORDER_MAX_PENDING_SESSIONS`), `.env.example`, `backend/.env.example`
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
@dataclass(frozen=True) class CostProfile:
    commission_eur: float; cost_bps_equity: float; cost_bps_crypto: float; fractional_shares: bool; min_trade_eur: float
    @classmethod def from_settings(cls) -> CostProfile
    def cost_rate(self, asset_type: str) -> float          # bps / 10_000; crypto -> cost_bps_crypto
    def allows_fraction(self, asset_type: str) -> bool     # crypto sempre True
StrategyName = Literal["SCORE_THRESHOLD", "TOP_N_SCORE", "BUY_AND_HOLD"]
RebalanceFrequency = Literal["DAILY", "WEEKLY", "MONTHLY"]
@dataclass(frozen=True) class StrategyParams:
    name: StrategyName; buy_threshold: float = 70; sell_threshold: float = 40; max_asset_weight: float = 0.15
    top_n: int = 5; rebalance_frequency: RebalanceFrequency = "WEEKLY"
def rebalance_key(day: str, frequency: RebalanceFrequency) -> str
def target_weights(params: StrategyParams, signals: Mapping[int, float], current_weights: Mapping[int, float],
                   *, first_rebalance: bool) -> dict[int, float] | None   # None = nessun cambio
@dataclass(frozen=True) class AssetMarket:
    asset_id: int; symbol: str; asset_type: str
    bars: pd.DataFrame       # index = date; open_eur, high_eur, low_eur, close_eur, segment_id
@dataclass(frozen=True) class SimulationConfig:
    initial_cash_eur: float; costs: CostProfile
    params_schedule: tuple[tuple[str, StrategyParams], ...]    # (data di inizio, parametri), ordinato
    stop_loss_percent: float | None; take_profit_percent: float | None; max_pending_sessions: int
TradeReason = Literal["SIGNAL", "REBALANCE", "STOP_LOSS", "TAKE_PROFIT", "SEGMENT_EXIT"]
@dataclass(frozen=True) class TradeRecord:
    date: str; asset_id: int; symbol: str; side: Literal["BUY", "SELL"]; quantity: float; price_eur: float
    commission_eur: float; spread_cost_eur: float; gross_eur: float; net_eur: float; pnl_eur: float; reason: TradeReason
@dataclass(frozen=True) class SimulationResult:
    equity: pd.DataFrame     # date, value_eur, cash_eur, invested_eur, drawdown
    trades: tuple[TradeRecord, ...]; cancelled_orders: tuple[dict[str, Any], ...]
    daily_returns: pd.Series; costs: dict[str, float]; turnover: float; exposure: float
def simulate(markets: Mapping[int, AssetMarket], signals: pd.DataFrame, calendar: Sequence[str],
             config: SimulationConfig) -> SimulationResult
def compute_metrics(result: SimulationResult, initial_cash_eur: float) -> dict[str, float]
    # total_return_percent, cagr, max_drawdown, sharpe_ratio (rf 0, x sqrt(252)), profit_factor, win_rate,
    # total_trades, turnover, exposure, commission_eur, spread_cost_eur
```

Semantica (spec §7): giorno *d* per asset con barra: (1) apertura: ordini pendenti eseguiti a `open_eur × (1 ± costo)`; vendite prima degli acquisti; quantità intera per azioni/ETF salvo `fractional_shares`; acquisto limitato dalla cassa (commissione inclusa); ordine sotto `min_trade_eur` non creato; (2) stop/tp con i livelli dal prezzo di esecuzione: `low ≤ stop` → `min(open, stop)`, `high ≥ tp` → `max(open, tp)`, entrambi → stop, sempre con costo per lato e commissione; (3) chiusura: se la barra successiva dell'asset ha `segment_id` diverso, vendita `SEGMENT_EXIT` al `close_eur × (1 − costo)`; valutazione; decisione quando cambia `rebalance_key` del calendario: `target_weights` sugli asset con barra a *d* e segnale non NaN, importi = peso × valore del portafoglio alla chiusura di *d*. Ordine non eseguibile entro `max_pending_sessions` barre → annullato e registrato. Le strategie riproducono la semantica attuale (`SCORE_THRESHOLD`: vende con segnale ≤ sell, compra/integra con segnale ≥ buy fino al peso massimo; `TOP_N_SCORE`: primi N, gli altri venduti, peso `min(max, 1/N)`; `BUY_AND_HOLD`: solo al primo ribilanciamento).

- [ ] **Step 1: Test RED** in `tests/test_lab_simulator.py`. Scenario calcolato a mano (azione A, EUR, calendario 2024-01-01…2024-01-05, segnale 80 ogni giorno, `SCORE_THRESHOLD` buy 70 sell 40 peso massimo 0,5 ribilanciamento `WEEKLY`, stop 8%, capitale 10.000 €, commissione 1 €, 10 bps, quote intere, ordine minimo 100 €):

| Data | open | high | low | close |
|---|---|---|---|---|
| 2024-01-01 | 100 | 101 | 99 | 100 |
| 2024-01-02 | 102 | 103 | 101 | 102 |
| 2024-01-03 | 104 | 105 | 103 | 104 |
| 2024-01-04 | 103 | 104 | 90 | 95 |
| 2024-01-05 | 96 | 97 | 95 | 96 |

```python
def test_hand_computed_scenario() -> None:
    result = simulate(markets, signals, calendar, config)
    buy, stop = result.trades
    assert (buy.date, buy.side, buy.quantity) == ("2024-01-02", "BUY", 48)        # decisione il 1°, fill il 2
    assert buy.price_eur == pytest.approx(102.102)
    assert buy.spread_cost_eur == pytest.approx(4.896)
    assert buy.commission_eur == pytest.approx(1.0)
    assert (stop.date, stop.reason) == ("2024-01-04", "STOP_LOSS")
    assert stop.price_eur == pytest.approx(93.93384 * 0.999)                       # stop 102.102 x 0,92, poi costo
    assert stop.pnl_eur == pytest.approx(48 * 93.93384 * 0.999 - 1 - (48 * 102.102 + 1))
    values = result.equity.set_index("date")["value_eur"]
    assert values["2024-01-01"] == pytest.approx(10_000)
    assert values["2024-01-02"] == pytest.approx(10_000 - 48 * 102.102 - 1 + 48 * 102)
    assert values["2024-01-03"] == pytest.approx(10_000 - 48 * 102.102 - 1 + 48 * 104)
    assert values["2024-01-05"] == pytest.approx(10_000 - 48 * 102.102 - 1 + 48 * 93.93384 * 0.999 - 1)
    assert result.costs["commission_eur"] == pytest.approx(2.0)
```

  Altri test: `test_no_fill_on_signal_bar` (nessun trade con data uguale alla prima decisione); `test_gap_down_stop_fills_at_open` (open 92 < stop → prezzo `92 × 0,999`); `test_take_profit_fills_at_level`; `test_stop_wins_when_both_levels_hit`; `test_crypto_quantity_is_fractional` (open 20.000, importo 5.000 → quantità `5000 / (20000 × 1.005)`); `test_order_below_min_trade_is_not_created`; `test_missing_next_bar_keeps_order_pending_then_cancels` (6 sedute senza barra → annullato e registrato); `test_segment_exit_sells_at_last_close_of_segment`; `test_top_n_and_buy_and_hold_follow_legacy_semantics`; `test_params_schedule_switches_without_liquidation` (posizione mantenuta al cambio di parametri); `test_metrics_known_values` (sharpe e drawdown su una curva costruita).
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** (`tests\test_lab_simulator.py`, `tests\test_config.py`, Ruff).
- [ ] **Step 5: Chiusura**

Commit: `feat: add next-open simulator with Trade Republic costs`

---

### Task 10: Backtest onesto in EUR come job, con registro dei tentativi

**Branch:** `investedge/sp1-task-10` — **Base:** `origin/investedge/sp1-task-9`

**Files:**
- Create: `backend/app/lab/universe.py`, `backend/app/lab/trials.py`, `tests/test_lab_backtest.py`
- Modify: `backend/app/services/backtest_engine.py` (riscrittura attorno a `simulate`; restano `list_backtests`, `get_backtest`, `delete_backtest`, `_net_analysis` con importi EUR), `backend/app/database.py` (`lab_trials`, colonne additive di `backtest_runs` e `backtest_trades`), `backend/app/models/schemas.py` (`BacktestRunIn`, `BacktestCompareIn`, `BacktestSummaryOut`, `BacktestTradeOut`), `backend/app/models/__init__.py`, `backend/app/lab/handlers.py` (`BACKTEST`, `COMPARE`), `backend/app/api/routes.py` (`/backtests/run`, `/backtests/compare` → 202)
- Modify: `tests/test_api.py` (test backtest esistenti al nuovo contratto), `tests/test_lab_boundaries.py` (rimuovere `backtest_engine.py` da `PENDING_BOUNDARY`)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS lab_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('BACKTEST', 'COMPARE', 'WF_GRID')),
    config_hash TEXT NOT NULL CHECK(length(config_hash) = 64),
    fingerprint TEXT NOT NULL CHECK(length(fingerprint) = 64),
    sharpe_daily REAL NOT NULL,
    n_obs INTEGER NOT NULL CHECK(n_obs > 1),
    job_id INTEGER,
    created_at TEXT NOT NULL
);
```

Trigger `trg_lab_trials_no_update` e `trg_lab_trials_no_delete` (RAISE ABORT). Indice `idx_lab_trials_family ON lab_trials(family_key, config_hash, created_at)`. `MIGRATIONS["backtest_runs"]`: `engine_version TEXT NOT NULL DEFAULT 'v0'`, `data_mode TEXT`, `signal_name TEXT`, `signal_timeframe TEXT`, `cost_profile_json TEXT`, `fingerprint TEXT`, `warnings_json TEXT`. `MIGRATIONS["backtest_trades"]`: `commission REAL`, `spread_cost REAL`. Nuovi run: `engine_version='v1'`, `fee_percent=0`.

**Interfaces — Produces:**

```text
# universe.py
@dataclass(frozen=True) class UniverseInputs:
    markets: dict[int, AssetMarket]; signals: pd.DataFrame; calendar: list[str]
    excluded: dict[str, str]                        # simbolo -> motivo ("NO_REAL_SERIES", "NO_FEATURES", "NO_FX")
    split_events: dict[str, list[SplitEvent]]; fx_excluded_bars: int; inputs_hash: str
    asset_types: dict[int, str]
def build_universe_inputs(connection, symbols: Sequence[str] | None, *, data_mode: DataMode, signal_name: str,
                          signal_timeframe: Timeframe, start: str, end: str, now: datetime) -> UniverseInputs
    # simboli None = tutti gli asset attivi con serie nel data_mode; aggiorna features_daily prima di leggere;
    # LabError("LAB_NO_REAL_SERIES") se l'universo REAL resta vuoto
def benchmark_curve(connection, symbol: str, *, data_mode: DataMode, calendar: Sequence[str]) -> pd.Series | None
# trials.py
def family_key(signal_name: str, signal_timeframe: Timeframe) -> str          # f"{signal_name}|{signal_timeframe}"
def canonical_hash(payload: Mapping[str, Any]) -> str                         # sha256 di json.dumps(sort_keys=True, separators=(",", ":"))
def record_trial(connection, *, data_mode: DataMode, family: str, kind: Literal["BACKTEST", "COMPARE", "WF_GRID"],
                 config_hash: str, fingerprint: str, sharpe_daily: float, n_obs: int, job_id: int | None) -> bool
    # DEMO o n_obs < 2 o sharpe non finito -> False, nessuna riga
def family_trial_sharpes(connection, family: str) -> list[float]               # ultimo per config_hash
# BacktestEngine
def run_backtest(self, connection, config: BacktestRunIn, *, job_id: int | None = None, now: datetime | None = None) -> BacktestResultOut
def compare_strategies(self, connection, payload: BacktestCompareIn, *, job_id: int | None = None, now: datetime | None = None) -> dict[str, Any]
def precheck(self, connection, symbols: Sequence[str], data_mode: DataMode) -> None   # LabError LAB_NO_REAL_SERIES prima di accodare
```

Modifiche agli schemi: `BacktestRunIn` senza `fee_percent`; nuovi campi `data_mode: DataMode = "REAL"`, `signal_name: str = "score"` (validato su `score`, `SUBSCORE_COLUMNS`, `FEATURE_COLUMNS_V1`), `signal_timeframe: Timeframe = "D"`, `commission_eur`, `cost_bps_equity`, `cost_bps_crypto`, `fractional_shares`, `min_trade_eur` (tutti `| None`, default dalle settings). `BacktestCompareIn` uguale. `BacktestSummaryOut`: `fee_percent: float | None`, più `engine_version`, `data_mode`, `signal_name`, `signal_timeframe`, `cost_profile: dict | None`, `warnings: list[str]`, `excluded: dict[str, str]`, `commission_eur`, `spread_cost_eur`, `turnover`, `exposure`. Fingerprint = `canonical_hash` di config normalizzata, versioni, `data_mode`, `inputs_hash`. Ogni run REAL registra un tentativo `BACKTEST` (o `COMPARE` per strategia) nella famiglia `(signal_name, signal_timeframe)`.

- [ ] **Step 1: Test RED** in `tests/test_lab_backtest.py` e `tests/test_api.py`:
  - `test_usd_asset_trades_are_converted_to_eur` (cambio 0,9: prezzo di esecuzione `open × 0,9 × 1,001`);
  - `test_real_run_excludes_assets_without_real_series_and_lists_them`;
  - `test_real_universe_empty_is_rejected_before_enqueue` (409 `LAB_NO_REAL_SERIES`);
  - `test_demo_run_is_labeled_and_not_recorded_as_trial`;
  - `test_same_inputs_produce_same_fingerprint_and_metrics`;
  - `test_existing_runs_are_marked_v0_after_migration`;
  - `test_trials_count_distinct_configs_only` (stesso config due volte → `family_trial_sharpes` di lunghezza 1);
  - `test_lab_trials_are_append_only` (UPDATE e DELETE sollevano);
  - API: `POST /backtests/run` → 202 con `job_id`; `GET /lab/jobs/{id}` → `SUCCEEDED` con `result_ref` = id del run; `GET /backtests/{id}` con `engine_version == "v1"`; confronto → 202 e `result` con le strategie ordinate per Sharpe netto (il confronto non corregge per i tentativi: l'evidenza viene dal walk-forward, che lo dichiara nella UI del Task 14).
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** (`tests\test_lab_backtest.py`, `tests\test_lab_boundaries.py`, suite completa, Ruff).
- [ ] **Step 5: Chiusura**

Commit: `feat: run honest EUR backtests as jobs with trial registry`

---

### Task 11: Statistiche, walk-forward vero e DSR

**Branch:** `investedge/sp1-task-11` — **Base:** `origin/investedge/sp1-task-10`

**Files:**
- Create: `backend/app/lab/stats.py`, `backend/app/lab/walk_forward.py`, `tests/test_lab_stats.py`, `tests/test_lab_walk_forward.py`
- Modify: `backend/app/services/backtest_engine.py` (`walk_forward`), `backend/app/models/schemas.py` (`WalkForwardIn`, `WalkForwardOut` v1), `backend/app/lab/handlers.py` (`WALK_FORWARD`), `backend/app/api/routes.py` (`/backtests/walk-forward` → 202), `backend/app/config.py` (`LAB_WF_IS_SESSIONS`, `LAB_WF_OOS_SESSIONS`), `.env.example`, `backend/.env.example`
- Modify: `tests/test_api.py` (test walk-forward esistenti al nuovo contratto)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
# stats.py
EULER_MASCHERONI = 0.5772156649015329
def spearman_ic(signal: pd.Series, label: pd.Series) -> float | None        # None con meno di 3 coppie o varianza nulla
def newey_west_tstat(values: Sequence[float], lag: int) -> float | None
    # gamma_j = (1/n) sum (x_t - mu)(x_{t-j} - mu); LRV = gamma_0 + 2 sum_{j=1..lag} (1 - j/(lag+1)) gamma_j; t = mu / sqrt(LRV/n)
def sharpe_daily(returns: pd.Series) -> float | None
def return_moments(returns: pd.Series) -> tuple[float, float]               # asimmetria, curtosi (non in eccesso)
def probabilistic_sharpe(sr: float, sr0: float, n_obs: int, skew: float, kurt: float) -> float
    # Phi((sr - sr0) * sqrt(n_obs - 1) / sqrt(1 - skew*sr + (kurt - 1)/4 * sr^2))
def expected_max_sharpe(trial_sharpes: Sequence[float]) -> float
    # N = len; N <= 1 o var = 0 -> 0; sqrt(var) * ((1-g) inv(1-1/N) + g inv(1-1/(N e)))
@dataclass(frozen=True) class DsrResult: dsr: float; sr: float; sr0: float; n_trials: int; n_obs: int; skew: float; kurtosis: float
def deflated_sharpe(returns: pd.Series, trial_sharpes: Sequence[float]) -> DsrResult | None
# walk_forward.py
def parameter_grid(strategy: StrategyName, base: StrategyParams) -> list[StrategyParams]
    # SCORE_THRESHOLD: buy (60, 65, 70, 75) x sell (35, 40, 45); TOP_N_SCORE: top_n (3, 5, 8) x (WEEKLY, MONTHLY);
    # BUY_AND_HOLD: [base]
def build_windows(calendar: Sequence[str], is_sessions: int, oos_sessions: int) -> list[tuple[int, int, int, int]]
    # (is_start, is_end, oos_start, oos_end) indici inclusivi; passo = oos_sessions; ultima finestra OOS troncata a fine calendario
@dataclass(frozen=True) class WalkForwardWindow:
    index: int; is_start: str; is_end: str; oos_start: str; oos_end: str; chosen: StrategyParams; is_sharpe: float | None
def simulate_grid(inputs: UniverseInputs, base: SimulationConfig, grid: Sequence[StrategyParams]) -> list[tuple[StrategyParams, SimulationResult]]
def select_parameters(grid_results, calendar: Sequence[str], windows) -> list[WalkForwardWindow]
    # Sharpe netto sui soli rendimenti giornalieri in [is_start, is_end]; parità -> ordine della griglia
def simulate_oos(inputs: UniverseInputs, base: SimulationConfig, windows: Sequence[WalkForwardWindow]) -> SimulationResult
    # un'unica simulazione da oos_start della prima finestra, params_schedule = [(oos_start, chosen)]
```

`BacktestEngine.walk_forward(connection, payload, *, job_id, now)`: universo → griglia → `record_trial` per ogni configurazione REAL (`WF_GRID`, config_hash della configurazione) → selezione → OOS → `deflated_sharpe(oos.daily_returns, family_trial_sharpes(family))`. `WalkForwardIn` = `BacktestRunIn` + `is_sessions: int | None`, `oos_sessions: int | None` (via `folds`). `WalkForwardOut`: `strategy_name`, `data_mode`, `windows`, `grid_size`, `is_sharpe_mean`, `oos_sharpe`, `degradation` (= `is_sharpe_mean − oos_sharpe`), `oos_metrics`, `oos_sessions`, `dsr` (`DsrResult` serializzato o null), `n_trials`, `excluded`, `warnings`. Periodo troppo corto per una finestra → `LabError("LAB_PERIOD_TOO_SHORT")`.

- [ ] **Step 1: Test RED** in `tests/test_lab_stats.py`:

```python
from statistics import NormalDist
import math

import pandas as pd
import pytest

from backend.app.lab.stats import (
    EULER_MASCHERONI, deflated_sharpe, expected_max_sharpe, newey_west_tstat,
    probabilistic_sharpe, spearman_ic,
)


def test_newey_west_known_values() -> None:
    assert newey_west_tstat([1, 2, 3, 4], lag=0) == pytest.approx(2.5 / math.sqrt(1.25 / 4))
    assert newey_west_tstat([1, 2, 3, 4], lag=1) == pytest.approx(4.0)


def test_spearman_ic_known_values() -> None:
    assert spearman_ic(pd.Series([1, 2, 3, 4]), pd.Series([10, 20, 30, 40])) == pytest.approx(1.0)
    assert spearman_ic(pd.Series([1, 2, 3, 4]), pd.Series([40, 30, 20, 10])) == pytest.approx(-1.0)
    assert spearman_ic(pd.Series([1, 2]), pd.Series([1, 2])) is None


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


def test_dsr_decreases_when_more_trials_are_counted() -> None:
    # Sharpe giornaliero ~0,025: lontano dalla saturazione di Phi, cosi' i due DSR restano distinti.
    returns = pd.Series([0.01, -0.009, 0.004, -0.004, 0.002, -0.002] * 60)
    few = deflated_sharpe(returns, [-0.03, 0.03])
    many = deflated_sharpe(returns, [-0.03, 0.03] * 20)
    assert many.dsr < few.dsr
    assert many.n_trials == 40
```

  In `tests/test_lab_walk_forward.py`: `test_build_windows_rolls_by_oos_length`; `test_grid_sizes` (12, 6, 1); `test_selection_ignores_oos_perturbation` (si perturbano i prezzi dopo `is_end` della finestra 0: parametro scelto della finestra 0 invariato); `test_tie_breaks_on_grid_order`; `test_oos_is_one_simulation_with_parameter_schedule` (nessuna `SEGMENT_EXIT` né vendita forzata al cambio di finestra); `test_walk_forward_records_one_trial_per_grid_config_and_reports_dsr`; `test_period_too_short_raises`. In `tests/test_api.py`: `POST /backtests/walk-forward` → 202, risultato del job con `windows`, `dsr`, `n_trials`.
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** (`tests\test_lab_stats.py`, `tests\test_lab_walk_forward.py`, suite completa, Ruff).
- [ ] **Step 5: Chiusura**

Commit: `feat: add true walk-forward with deflated Sharpe`

---

### Task 12: Harness di valutazione, report di evidenza e verdetto

**Branch:** `investedge/sp1-task-12` — **Base:** `origin/investedge/sp1-task-11`

**Files:**
- Create: `backend/app/lab/harness.py`, `backend/app/lab/evidence.py`, `tests/test_lab_harness.py`, `tests/test_lab_evidence.py`
- Modify: `backend/app/database.py` (`lab_evidence_reports`), `backend/app/config.py` (`LAB_MIN_NAMES`, `LAB_MIN_IC_DATES`, `LAB_MIN_OOS_SESSIONS`, `LAB_MIN_T_STAT`, `LAB_MIN_DSR`, `LAB_REFERENCE_CAPITAL_EUR`), `.env.example`, `backend/.env.example`, `backend/app/models/lab.py`, `backend/app/models/__init__.py`, `backend/app/lab/handlers.py` (`EVIDENCE`), `backend/app/api/lab_routes.py`
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS lab_evidence_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    signal_name TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK(timeframe IN ('D', 'W', 'M')),
    horizon INTEGER NOT NULL CHECK(horizon IN (1, 5, 21)),
    verdict TEXT NOT NULL CHECK(verdict IN ('VALIDATO', 'NON_VALIDATO', 'INSUFFICIENTE')),
    metrics_json TEXT NOT NULL,
    walk_forward_json TEXT,
    config_json TEXT NOT NULL,
    universe_json TEXT NOT NULL,
    limits_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL CHECK(length(fingerprint) = 64),
    created_at TEXT NOT NULL
);
```

Trigger no update / no delete; indice `idx_lab_evidence_signal ON lab_evidence_reports(signal_name, timeframe, horizon, created_at DESC, id DESC)`.

**Interfaces — Produces:**

```text
# harness.py
HORIZONS = (1, 5, 21)
def forward_open_returns(markets: Mapping[int, AssetMarket], calendar: Sequence[str], horizon: int) -> pd.DataFrame
    # index = calendar, colonne = asset_id; per l'asset con barra a t: open_eur della sua barra t+1+h / open_eur della barra t+1 - 1;
    # NaN se mancano barre, se cambia segment_id o se un open_eur e' NaN
@dataclass(frozen=True) class HarnessResult:
    horizon: int; ic_dates: int; ic_mean: float | None; ic_std: float | None; ic_ir: float | None
    ic_positive_share: float | None; t_nw: float | None; mean_names: float; bucket_count: int
    bucket_returns: list[float | None]; spread_gross: float | None; spread_net: float | None
    turnover_top: float | None; rank_autocorr: float | None
def evaluate_signal(signals: pd.DataFrame, labels: pd.DataFrame, horizon: int, *, min_names: int, costs: CostProfile,
                    asset_types: Mapping[int, str], reference_capital_eur: float) -> HarnessResult
    # IC per data con >= min_names coppie; t_nw con lag = horizon - 1; bucket: 10 se >= 50 asset, altrimenti 5;
    # spread e turnover su date di ribilanciamento ogni horizon sedute (non sovrapposte);
    # costo gamba = 2 x turnover x (commission_eur / (reference_capital_eur / asset_nel_bucket) + cost_rate medio)
# evidence.py
Verdict = Literal["VALIDATO", "NON_VALIDATO", "INSUFFICIENTE"]
@dataclass(frozen=True) class EvidenceThresholds:
    min_names: int; min_ic_dates: int; min_oos_sessions: int; min_t_stat: float; min_dsr: float
    @classmethod def from_settings(cls) -> EvidenceThresholds
def decide_verdict(harness: HarnessResult, wf_oos_sessions: int, dsr: float | None, thresholds: EvidenceThresholds) -> Verdict
@dataclass(frozen=True) class EvidenceOutcome:
    horizon: int; verdict: Verdict; harness: HarnessResult; walk_forward: dict[str, Any] | None
def evaluate_evidence(inputs: UniverseInputs, horizons: Sequence[int], *, thresholds: EvidenceThresholds,
                      costs: CostProfile, reference_capital_eur: float,
                      trial_sharpes: Callable[[list[tuple[StrategyParams, SimulationResult]]], list[float]]) -> list[EvidenceOutcome]
    # pura: per ogni orizzonte harness + walk-forward TOP_N (N in 3, 5, 8; ribilanciamento 1->DAILY, 5->WEEKLY, 21->MONTHLY;
    # nessuno stop; capitale reference_capital_eur); trial_sharpes riceve i risultati della griglia e restituisce gli Sharpe della famiglia;
    # periodo troppo corto per il walk-forward -> walk_forward None, oos 0 sedute, verdetto INSUFFICIENTE (il job non fallisce)
def run_evidence(connection, request: EvidenceIn, *, job_id: int | None, now: datetime) -> list[int]   # id dei report
def latest_verdicts(connection, signal_name: str, timeframe: Timeframe) -> dict[int, dict[str, Any] | None]
# models/lab.py
EvidenceIn {signal_name: str, timeframe: Timeframe = "D", horizons: list[int] = [1, 5, 21], start_date: str, end_date: str,
            symbols: list[str] | None = None}
EvidenceReportOut, EvidenceSummaryOut, EvidenceLatestOut {signal_name, timeframe, horizons: dict[str, EvidenceSummaryOut | None],
            best: EvidenceSummaryOut | None}
```

Route: `POST /lab/evidence` (202; sempre `REAL`; 409 `LAB_NO_REAL_SERIES`; 422 per segnale o orizzonte non validi), `GET /lab/evidence?signal_name=&timeframe=&limit=`, `GET /lab/evidence/{id}` (404), `GET /lab/evidence/latest?signal_name=score&timeframe=D`, `GET /lab/signals` (`["score", *SUBSCORE_COLUMNS, *FEATURE_COLUMNS_V1]`). Ordine del migliore: `VALIDATO` > `NON_VALIDATO` > `INSUFFICIENTE`. `limits_json` contiene: bias di sopravvivenza, base di rettifica per asset, eventi split, barre escluse per cambio, nota CoinGecko se presente, costi ipotizzati.

- [ ] **Step 1: Test RED.** Fixture sintetica in `tests/test_lab_harness.py`: 20 asset × 1100 sedute, `AssetMarket` con prezzi EUR casuali con seed fisso.
  - `test_constructed_predictive_signal_has_positive_ic_and_tstat`: segnale = rendimento futuro a *h* + rumore (σ uguale al rendimento) → `ic_mean > 0`, `t_nw >= 2`, `spread_net > 0`;
  - `test_random_signal_ic_is_not_significant` (segnale casuale con seed fisso dichiarato nel test: `abs(t_nw) < 2`);
  - `test_labels_never_cross_segments` e `test_labels_use_next_open_to_open`;
  - `test_quintiles_below_fifty_names_and_deciles_above`;
  - `test_net_spread_subtracts_turnover_costs` (valore atteso con la formula sui conteggi noti).
  In `tests/test_lab_evidence.py`:
  - `test_constructed_signal_is_validato` (con `evaluate_evidence` e la fixture: DSR ≥ 0,95);
  - `test_random_signal_is_non_validato`;
  - `test_short_sample_is_insufficiente` (300 sedute);
  - `test_few_names_is_insufficiente` (8 asset);
  - `test_reports_are_immutable` (UPDATE e DELETE sollevano);
  - `test_evidence_refuses_demo_only_universe` (409);
  - API: `POST /lab/evidence` su DB con 12 asset reali sintetici (400 barre) → 202, job `SUCCEEDED`, 3 report `INSUFFICIENTE`; `GET /lab/evidence/latest` con migliore e orizzonti; `GET /lab/signals`.
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** (`tests\test_lab_harness.py`, `tests\test_lab_evidence.py`, suite completa, Ruff).
- [ ] **Step 5: Chiusura**

Commit: `feat: add signal evaluation harness and evidence verdicts`

---

### Task 13: ML sulla pipeline condivisa

**Branch:** `investedge/sp1-task-13` — **Base:** `origin/investedge/sp1-task-12`

**Files:**
- Modify: `backend/app/services/ml_dataset_service.py`, `backend/app/services/ml_engine.py`, `backend/app/database.py` (`ml_models.pipeline_version`, `ml_models.data_mode`), `backend/app/models/schemas.py` (`MLTrainIn.data_mode`, `pipeline_version`/`data_mode` nei modelli in uscita), `backend/app/lab/handlers.py` (`ML_TRAIN`), `backend/app/api/routes.py` (`/ml/train` → 202; 409 `MODEL_PIPELINE_MISMATCH` su predict)
- Modify: `tests/test_ml_dataset.py`, `tests/test_api.py` (test ML), `tests/test_lab_boundaries.py` (rimuovere `ml_dataset_service.py` da `PENDING_BOUNDARY`)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
FEATURE_COLUMNS (ml_dataset_service) = [
  "close_return_1d", "close_return_5d", "close_return_20d", "volatility_30d", "rsi_14", "macd_line_pct",
  "macd_histogram_pct", "price_vs_sma50", "price_vs_sma200", "sma50_vs_sma200", "atr_14_pct", "adx_14",
  "plus_di", "minus_di", "bollinger_percent_b", "max_drawdown_252", "drawdown_60", "volume_ratio_20",
  "obv_ratio_20", "stochastic_k", "stochastic_d", "roc_12", "support_distance_pct", "resistance_distance_pct",
  "score", "trend_score", "momentum_score", "volatility_score", "volume_score", "support_resistance_score", "risk_penalty",
]
MLDatasetService.build_ml_dataset(connection, symbols, horizon_days, target_type, benchmark_symbol="SPY", data_mode="REAL") -> pd.DataFrame
    # feature da FeatureStore.read_frame(D, complete_only=True); target invariati nella definizione, calcolati sui close rettificati
    # della serie del laboratorio, senza attraversare segmenti; validate_no_lookahead invariato
MLDatasetService.build_features_for_symbol(connection, symbol, data_mode, as_of_date=None) -> dict[str, float]
MLEngine.predict_for_symbol(...)  # modello senza pipeline_version o con versione/elenco feature diversi -> LabError("MODEL_PIPELINE_MISMATCH")
```

Il bundle `joblib` salva `pipeline_version`, `data_mode` e `features`; la previsione usa le feature dell'asset nel `data_mode` del modello (asset senza righe in quel modo → avviso per asset in `predict-all`). Nessuna feature news o di portafoglio.

- [ ] **Step 1: Test RED**: `test_dataset_columns_are_pipeline_v1_only` (nessuna colonna `news_*`, `portfolio_weight`, `current_recommendation_encoded`); `test_ml_row_equals_features_daily_row` (score e `rsi_14` alla data *t* uguali alla riga di `features_daily`); `test_targets_do_not_cross_segments`; `test_model_without_pipeline_version_is_rejected` (409 `MODEL_PIPELINE_MISMATCH`); `test_demo_model_predicts_only_demo_features`; API `POST /ml/train` → 202 e job `SUCCEEDED` con `model_id`; i test esistenti di look-ahead e walk-forward ML restano verdi.
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** (`tests\test_ml_dataset.py`, `tests\test_lab_boundaries.py`, suite completa, Ruff).
- [ ] **Step 5: Chiusura**

Commit: `feat: train ML on the shared feature pipeline`

---

### Task 14: Pagina Backtest su job, costi TR ed EUR

**Branch:** `investedge/sp1-task-14` — **Base:** `origin/investedge/sp1-task-13`

**Files:**
- Modify: `frontend/src/lib/api.ts` (tipi e client), `frontend/src/pages/BacktestPage.tsx`
- Create: `frontend/src/lib/jobs.ts`, `frontend/src/pages/BacktestPage.test.tsx`
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
// api.ts — tipi omologhi a JobOut, BacktestRunIn/BacktestCompareIn/WalkForwardIn v1, BacktestSummaryOut v1, WalkForwardOut v1
export type DataMode = "REAL" | "DEMO";
export type Timeframe = "D" | "W" | "M";
export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export interface LabJob { id: number; kind: string; status: JobStatus; progress: number; result_ref: string | null;
  result: Record<string, unknown> | null; error_code: string | null; error_message: string | null; created_at: string;
  started_at: string | null; finished_at: string | null; cancel_requested: boolean; params: Record<string, unknown> }
export function getJob(id: number, signal?: AbortSignal): Promise<LabJob>
export function cancelJob(id: number): Promise<LabJob>
// jobs.ts
export async function waitForJob(id: number, options: { signal: AbortSignal; intervalMs?: number;
  onUpdate?: (job: LabJob) => void }): Promise<LabJob>   // polling ogni 2000 ms finché lo stato non è terminale
```

UI: form con profilo costi (commissione €, bps azioni/ETF, bps crypto, ordine minimo €, quote frazionarie), `data_mode` (REAL predefinito, DEMO etichettato), segnale (da `GET /lab/signals`) e timeframe; stop/take profit invariati; campo `fee_percent` rimosso. Esecuzione: stato del job con progresso, pulsante "Annulla" (`cancelJob`), errori 409 spiegati via `apiReasonCode` (`LAB_NO_REAL_SERIES`, `LAB_PERIOD_TOO_SHORT`, `JOB_NOT_CANCELLABLE`); polling interrotto allo smontaggio. Risultati: importi in EUR, nota "Esecuzione all'apertura della barra successiva", costi per voce, turnover, esclusi e avvisi; nel confronto la nota "Confronto senza correzione per i tentativi: per l'evidenza usa il walk-forward"; storico con etichetta "motore precedente" per `engine_version == "v0"`. Walk-forward: tabella per finestra (IS, OOS, parametri scelti, Sharpe IS), Sharpe OOS, degrado, DSR con *N* tentativi.

- [ ] **Step 1: Test RED** in `BacktestPage.test.tsx` (fetch mockato, fuso fissato con `vi.stubEnv("TZ", "Europe/Rome")`): invio run → `POST /backtests/run` con il nuovo payload senza `fee_percent`; polling fino a `SUCCEEDED` e risultato mostrato in EUR; annullamento chiama `POST /lab/jobs/{id}/cancel`; 409 `LAB_NO_REAL_SERIES` mostra il messaggio guida; run `v0` etichettato; walk-forward mostra DSR e *N*; `waitForJob` si ferma con `AbortSignal`.
- [ ] **Step 2: RED** `npm --prefix frontend run test:run -- BacktestPage.test.tsx` → FAIL.
- [ ] **Step 3: Implementare**, **Step 4: GREEN** con test frontend completi, `npm --prefix frontend run build`, `npm --prefix frontend audit --audit-level=high`.
- [ ] **Step 5: Chiusura**

Commit: `feat: adapt the backtest page to lab jobs and costs`

---

### Task 15: Evidenza, badge del verdetto e pagina ML

**Branch:** `investedge/sp1-task-15` — **Base:** `origin/investedge/sp1-task-14`

**Files:**
- Create: `frontend/src/components/EvidenceBadge.tsx`, `frontend/src/components/EvidencePanel.tsx`, `frontend/src/components/EvidenceBadge.test.tsx`, `frontend/src/pages/MachineLearningPage.test.tsx`, `frontend/src/pages/EvidenceBadgePlacement.test.tsx`
- Modify: `frontend/src/lib/api.ts`, `frontend/src/pages/BacktestPage.tsx` (modalità "Evidenza"), `frontend/src/pages/BacktestPage.test.tsx`, `frontend/src/pages/AnalysisPage.tsx`, `frontend/src/pages/WatchlistPage.tsx`, `frontend/src/pages/DashboardPage.tsx`, `frontend/src/pages/TodayPage.tsx`, `frontend/src/pages/MachineLearningPage.tsx`
- Modify: piano, `PROGRAMMA-OPERATIVO.md`

**Interfaces — Produces:**

```text
export type Verdict = "VALIDATO" | "NON_VALIDATO" | "INSUFFICIENTE";
export function getEvidenceLatest(signalName: string, timeframe: Timeframe, signal?: AbortSignal): Promise<EvidenceLatest>
export function startEvidence(payload: EvidenceRequest): Promise<LabJob>
export function getEvidenceReport(id: number): Promise<EvidenceReport>
EvidenceBadge props: { latest: EvidenceLatest | null; dataMode?: DataMode | null }
    // testo: "VALIDATO · 5g" / "NON VALIDATO · 1g" / "INSUFFICIENTE · 21g" / "NON MISURATO"; DEMO -> "DEMO · non misurabile";
    // tooltip: tre orizzonti, data del report, "verdetto sul segnale nell'universo, non sul singolo titolo"
DemoMarker props: { dataMode?: DataMode | null }   // "DEMO" solo se dataMode === "DEMO"
```

Posizioni (spec §8.7): Analisi accanto allo score (lo "score finale" coincide con lo score; correzione news mostrata a parte come informazione); Watchlist nell'intestazione della colonna score più `DemoMarker` per riga; Dashboard nell'intestazione delle sezioni con score più `DemoMarker`; Oggi nell'intestazione dell'elenco azioni più `DemoMarker`. Una sola richiesta `getEvidenceLatest("score", "D")` per pagina. Modalità Evidenza: form (segnale, timeframe, orizzonti, periodo, simboli opzionali), job con stato e annullamento, report con IC e t, quota IC > 0, bucket, spread lordo/netto, turnover, walk-forward (finestre, Sharpe OOS, DSR, *N*), verdetto, universo ed esclusi, limiti. Pagina ML: training come job con stato; 409 `MODEL_PIPELINE_MISMATCH` → "Modello creato con una pipeline precedente: riaddestralo."; nessuna feature news o di portafoglio mostrata.

- [ ] **Step 1: Test RED**: `EvidenceBadge.test.tsx` (quattro stati, ordine del migliore, DEMO, tooltip); `BacktestPage.test.tsx` (modalità Evidenza: avvio, polling, report con verdetto e limiti); `MachineLearningPage.test.tsx` (training via job, messaggio 409); `EvidenceBadgePlacement.test.tsx` (un test per ciascuna di Analisi, Watchlist, Dashboard e Oggi con fetch mockato: una sola chiamata a `/lab/evidence/latest`, badge nella posizione prevista, marcatore DEMO solo sulle righe DEMO).
- [ ] **Step 2: RED**, **Step 3: implementare**, **Step 4: GREEN** con test frontend completi, build, audit.
- [ ] **Step 5: Chiusura**

Commit: `feat: show evidence reports and verdict badges`

---

### Task 16: Prestazioni, documentazione e verifica finale SP1

**Branch:** `investedge/sp1-task-16` — **Base:** `origin/investedge/sp1-task-15`

**Files:**
- Create: `backend/scripts/lab_perf_smoke.py`, `docs/reports/<data>-sp1-truth-lab-verification.md`
- Modify: `README.md` (sezione "Laboratorio di verità": modalità REAL/DEMO, backfill FX, job, evidenza e limiti)
- Modify: piano, `PROGRAMMA-OPERATIVO.md`; correzioni nei soli file già toccati da SP1 per rilievi della review finale

**Interfaces:** nessuna nuova interfaccia pubblica.

- [ ] **Step 1: Smoke prestazioni** `python -m backend.scripts.lab_perf_smoke` su DB temporaneo (`INVESTEDGE_DB_PATH` nello scratchpad), 50 asset sintetici REAL × 1500 barre, rete bloccata: tempi di calcolo completo di `features_daily`, incrementale di una barra, job di evidenza su 5 anni. Obiettivi indicativi (non bloccanti): ≤ 60 s, ≤ 5 s, ≤ 120 s. Registrare i tempi nel report.
- [ ] **Step 2: Audit cumulativo**: elenco commit `origin/investedge/sp1-task-0..HEAD`, file fuori elenco per task, secret scan come in Fase 2 (classificazione riga per riga), verifica dei 10 criteri di successo della spec §15 con il test che li copre.
- [ ] **Step 3: Review indipendente** (sola lettura, `superpowers:requesting-code-review`) dell'intero SP1; correggere con TDD ogni Critical e Important nei file di SP1, ripetere la review sul delta.
- [ ] **Step 4: Gate finale**

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider --junitxml=$env:TEMP\sp1-final.xml
& '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests
npm --prefix frontend ci
npm --prefix frontend run test:run
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
git diff --check
```

Expected: tutto verde; 0 tentativi di rete (guardia del Task 1); conteggi dal JUnit XML nel report.
- [ ] **Step 5: Report e chiusura**: report di verifica (scope, catena dei commit, criteri §15, prestazioni, review, rischi residui della spec §18 aggiornati); `PROGRAMMA-OPERATIVO.md` con SP1 `FATTO` e *Prossimo passo* = merge fast-forward su `main` previa conferma dell'utente, poi SP2b.

Commit: `chore: verify SP1 truth lab`

---

## Copertura della spec

| Spec | Task |
|---|---|
| §4 Architettura, unità e confini | 2, 3, 4, 6, 7 (test di confine), 8–12 |
| §5.1–5.3 Feature e causalità | 2 |
| §5.4 W/M | 3, 6 (`signal_panel`) |
| §5.5 Score v1, news fuori dal punteggio | 3, 7 |
| §5.6 `features_daily` incrementale e uguaglianza | 6, 7, 10, 13 |
| §6.1 REAL/DEMO | 4, 7, 10, 12 |
| §6.2–6.3 Segmenti, base di rettifica, guardia split | 4, 9 (`SEGMENT_EXIT`), 12 (etichette) |
| §6.4 Cambi BCE storici | 4 (conversione), 5 (backfill), 8 (job e route) |
| §6.5–6.6 Benchmark e limiti dichiarati | 10, 12 |
| §7 Backtester | 9, 10, 14 |
| §8.1–8.2 Harness | 12 |
| §8.3–8.5 Walk-forward, tentativi, DSR | 10 (registro), 11 |
| §8.6–8.7 Report, verdetto, badge | 12, 15 |
| §9 Job | 8 (+ handler in 10–13) |
| §10 API | 8, 10, 11, 12, 13 |
| §11 ML | 13, 15 |
| §12 Interfaccia | 14, 15 |
| §13 Errori e sicurezza | 1 (rete), 8 (errori dei job), tutti |
| §14–15 Verifica e criteri di successo | 1–16, gate nel 16 |
| §16 Configurazione | 4, 9, 11, 12 |
