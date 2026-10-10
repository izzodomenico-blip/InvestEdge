# InvestEdge — SP1 "Laboratorio di verità"

**Stato:** design approvato dall'utente per sezioni nel brainstorming del 1–2 ottobre 2026; correzioni R1–R3 prioritarie approvate il 10 ottobre 2026. Requisiti aggiornati; implementazione delle correzioni ancora da eseguire.

**Relazione:** attua SP1 della spec di programma `2026-09-30-investedge-profit-engine-program-design.md` (§4, principi §5, difetti §7). Dove questa spec è più precisa, prevale per SP1.

**Base:** `main` = `6acd3c4` (Fase 2 verificata). Branch documenti: `investedge/sp1-task-0`.

## 1. Obiettivo

Un laboratorio che, per ogni segnale o strategia e per ogni orizzonte, produce **evidenza riproducibile fuori campione, al netto dei costi, solo su dati reali**, e un **verdetto** dichiarato. Lo score è uno solo e ha lo stesso valore in interfaccia, backtest e ML.

SP1 misura e dichiara; non blocca decisioni. L'applicazione del verdetto ad action board, alert e ordini arriva con il risk engine di SP6a/SP6b.

La priorità intraday approvata il 2026-10-10 non modifica timeframe D/W/M e orizzonti 1/5/21 di SP1. Dati/news intraday e validazione holding 15/30 minuti appartengono ai gate SP2b/SP3; Alpaca paper senza leva a SP6a. I verdetti daily non autorizzano il paper intraday.

## 2. Decisioni approvate

| Area | Decisione |
|---|---|
| Gate | Misura + verdetto `VALIDATO` / `NON VALIDATO` / `INSUFFICIENTE` (più `NON MISURATO` in assenza di report). Nessun blocco operativo prima di SP6. |
| Score unico v1 | Solo tecnico: formula attuale dell'interfaccia (sottopunteggi, pesi, soglie, confidenza, motivazioni) su indicatori corretti, calcolata per riga. La correzione news esce dal `final_score` e resta informativa fino a SP3. |
| Indicatori | Causali e a finestra limitata: via `chikou_span` dai dati di calcolo, RSI di Wilder, ricorsivi su finestra troncata, drawdown su 252 barre, OBV relativo. Versione dichiarata `features-v1` / `score-v1`. |
| Timeframe | D, W, M ricostruiti dalle daily, allineati point-in-time; orizzonti dell'harness 1, 5, 21 sedute; pipeline predisposta per l'intraday (SP2b). |
| Rettifiche | Base di rettifica dichiarata per provider + guardia split fail-closed; dividendi mancanti dichiarati; fonte eventi societari in SP2b. |
| Cambi | Backfill storico BCE nel provider governato esistente; età massima `ECB_FX_MAX_AGE_DAYS` (7). |
| Backlog SP1 | Entrano tutte e tre le voci: fixture di test veloce, tabella `features_daily`, job asincroni. |
| Rilievo I3 | Rinviato a SP2b. SP1 non ne dipende: `features_daily` è indicizzata per `asset_id` come `price_history`. |
| Interfaccia | Adattamento minimo della pagina Backtest, modalità **Evidenza**, badge del verdetto accanto allo score, pagina ML adattata ai job. Stile attuale, nessun redesign (SP8). |
| Soglie del verdetto | Standard: IC medio > 0 con t di Newey-West ≥ 2, spread netto > 0, DSR ≥ 0,95; minimi 252 date/sedute e 10 asset per data. Configurabili. |
| ML | Feature = colonne adimensionali della pipeline v1 + score v1 e sottopunteggi; via news e portafoglio dalle feature; versione della pipeline nel modello. Target, metriche e split restano a SP4. |
| Architettura | Approccio A: pacchetto `backend/app/lab/` con unità pure; `features_daily` unica fonte; servizi esistenti come adattatori sottili. |
| Branch | `investedge/sp1-task-0` per spec e piano; task di implementazione `investedge/sp1-task-M`. |

## 3. Stato attuale verificato nel codice

| Difetto | Dove |
|---|---|
| Tre formule di score | `ScoringEngine.score_prices` (UI), `BacktestEngine._score_row` (backtest), `MLDatasetService._trend_score` e funzioni collegate (ML); `MarketDataService._recalculate_signal` somma la correzione news |
| Prezzi futuri nei dati di calcolo | `TechnicalAnalysisService.enrich_price_history`: `chikou_span = close.shift(-26)` |
| Indicatori dipendenti dall'inizio serie | `max_drawdown` con `cummax`/`cummin`, OBV come somma cumulata, EMA con `min_periods=1`, Supertrend ricorsivo; RSI con media semplice |
| Fill sulla barra del segnale | `BacktestEngine._simulate`: segnale e fill sulla chiusura dello stesso giorno; stop valutati sulla chiusura |
| Costi e valuta | `fee_percent` (0,1%) invece di 1 €; nessuna conversione EUR (asset in USD ed EUR nella stessa cassa); `close` invece del prezzo rettificato |
| Walk-forward e test multipli | il "walk-forward" divide il periodo senza ottimizzazione in-sample; il confronto ordina per rendimento senza correzione per i tentativi |
| Rettifiche | `StooqEodProvider` salva `adjusted_close = close` |
| Cambi storici | `EcbFxProvider.fetch_rate` scarica `lastNObservations=2`: nessuna serie storica |
| Lentezza | route sincrone; indicatori ricalcolati a ogni richiesta |
| ML | `portfolio_weight` e `current_recommendation_encoded` valgono 0 in training e il valore reale in previsione; feature a scala di prezzo (`macd_line`, `atr_14`) |

## 4. Architettura

```
price_history (asset_id) ──► lab.series ──► lab.features ──► lab.score_v1
   + fx_rates storici          serie reale     D/W/M causali     score + motivazioni
                               segmenti        features-v1            │
                                    │                                 ▼
                                    │                    lab.feature_store (features_daily)
                                    │                     │        │          │
                                    ▼                     ▼        ▼          ▼
                              lab.simulator ◄── lab.strategies   signals   dataset ML
                              (EUR, costi TR)
                                    │
                  lab.harness ◄─────┴────► lab.walk_forward ──► lab.trials (DSR)
                                    └──► lab.evidence (verdetto) ──► lab.jobs ──► API / UI
```

### 4.1 Unità

Ogni unità è una funzione o classe piccola con un solo scopo. Solo `series`, `feature_store`, `trials`, `evidence` e `jobs` toccano SQLite.

| Unità | Responsabilità | Dipende da |
|---|---|---|
| `lab/features.py` | `compute_features(bars, timeframe)`: indicatori `features-v1`, warm-up esplicito | pandas, numpy |
| `lab/resample.py` | barre W/M dalle daily con `available_at` di calendario | — |
| `lab/score_v1.py` | `score_frame(features, risk_level)` vettoriale; `explain(row)` per motivazioni, condizioni e sintesi UI | `features` |
| `lab/series.py` | serie per `data_mode`, segmenti, base di rettifica, guardia split, conversione EUR | DB |
| `lab/feature_store.py` | `features_daily`: calcolo incrementale e lettura as-of | `features`, `resample`, `score_v1`, `series` |
| `lab/costs.py` | profilo costi Trade Republic | config |
| `lab/strategies.py` | pesi obiettivo alla chiusura di *t*: `SCORE_THRESHOLD`, `TOP_N_SCORE`, `BUY_AND_HOLD` | — |
| `lab/simulator.py` | esecuzione all'apertura successiva, stop sulla barra, contabilità EUR, metriche | `costs`, `series` |
| `lab/stats.py` | Spearman, Newey-West, PSR/DSR, momenti | numpy, `statistics.NormalDist` |
| `lab/harness.py` | IC, bucket, spread, turnover | `stats`, `feature_store`, `series`, `costs` |
| `lab/walk_forward.py` | finestre, griglia, selezione in-sample, simulazione OOS con calendario dei parametri | `simulator`, `trials` |
| `lab/trials.py` | registro append-only dei tentativi | DB |
| `lab/evidence.py` | report immutabile e verdetto | `harness`, `walk_forward`, `stats` |
| `lab/jobs.py` | coda e worker asincrono | DB |

Nessuna nuova dipendenza Python o npm.

### 4.2 Adattatori

- `ScoringEngine.score_prices` e `MarketDataService._recalculate_signal` leggono `score_v1` tramite il feature store. `final_score = score`; `news_score` resta come informazione.
- `technical_analysis_service` (endpoint `/technical-analysis/{symbol}`) usa `features` e `score_v1.explain` per indicatori, condizioni e sintesi.
- `BacktestEngine` diventa orchestratore di `strategies`, `simulator`, `walk_forward` e persistenza dei run.
- `MLDatasetService` legge `features_daily`.

### 4.3 Confini

- `TechnicalAnalysisService.enrich_price_history` resta **solo** per le sovrapposizioni del grafico (`prices_service`). Lì `chikou_span` è legittimo perché è disegnato spostato all'indietro.
- Un test di confine sugli import vieta a `lab/`, `scoring_engine`, `backtest_engine`, `ml_dataset_service` e `ml_engine` di importare `technical_analysis`.

## 5. Pipeline di feature e score v1

### 5.1 Ingresso e prezzi

- Barre daily OHLCV di **un segmento** di serie (§6.2), ordinate per data.
- Rettifica: fattore `f = adjusted_close / close`; O, H, L, C rettificati = valore × `f`. Con base `UNKNOWN` il fattore vale 1.
- Le feature si calcolano nella **valuta del listing**. L'EUR serve solo al simulatore e alle etichette dell'harness.

### 5.2 Regola di causalità

1. Il valore alla riga *i* dipende solo dalle barre `[i − W + 1, i]`, dove `W` è la finestra di dipendenza dichiarata della feature.
2. Prima di `W` barre disponibili il valore è NaN (warm-up).
3. Ogni indicatore ricorsivo si calcola su una **finestra troncata di L barre**:
   - medie esponenziali: pesi `(1 − α)^k`, `k = 0..L−1`, normalizzati;
   - Supertrend: macchina a stati ricalcolata da zero sulle ultime L barre.

Due test di proprietà su serie generate con seed fissi, per ogni feature:

- **futuro:** aggiungere barre dopo *i* non cambia il valore alla riga *i*;
- **inizio serie:** togliere barre prima di `i − W + 1` non cambia il valore alla riga *i*.

### 5.3 Feature `features-v1`

| Feature | Definizione | Finestra di dipendenza W |
|---|---|---|
| `sma_20`, `sma_50`, `sma_200` | media semplice | 20, 50, 200 |
| `price_vs_sma50`, `price_vs_sma200`, `sma50_vs_sma200` | rapporti − 1 | 50, 200, 200 |
| `rsi_14` | Wilder (α = 1/14) troncato, L = 100 | 101 |
| `macd_line`, `macd_signal`, `macd_histogram` | EMA 12 (L = 48) − EMA 26 (L = 104); segnale EMA 9 (L = 36) | 139 |
| `macd_line_pct`, `macd_histogram_pct` | diviso per il close | 139 |
| `stochastic_k`, `stochastic_d` | 14, media 3 | 16 |
| `roc_12` | variazione percentuale a 12 barre | 13 |
| `close_return_1d`, `_5d`, `_20d` | rendimenti | 2, 6, 21 |
| `volatility_30d` | dev. std dei rendimenti × √252 | 31 |
| `atr_14`, `atr_14_pct` | media semplice del true range; diviso per il close | 15 |
| `plus_di`, `minus_di` | Wilder troncato, L = 100 | 101 |
| `adx_14` | Wilder troncato del DX, L = 100 | 200 |
| `supertrend_10_3` | ATR 10 semplice, moltiplicatore 3, stato su L = 100 | 110 |
| `bollinger_percent_b` | SMA 20 ± 2σ | 20 |
| `max_drawdown_252` | drawdown massimo dentro le ultime 252 barre | 252 |
| `drawdown_60` | close / massimo delle ultime 60 − 1 | 60 |
| `volume_ratio_20` | volume / media a 20 | 20 |
| `obv_ratio_20` | Σ(segno Δclose × volume) / Σ volume su 20 barre, in [−1, 1] | 21 |
| `support_distance_pct`, `resistance_distance_pct` | pivot ±2 barre nelle ultime 180, usati solo se confermati (indice ≤ *i* − 2) | 180 |

Escono dal calcolo (restano nel grafico): EMA 50/200, CCI, Ichimoku, SMA 10/100, OBV assoluto, `max_drawdown` da inizio serie.

Il test sull'RSI verifica che la versione troncata differisca dal Wilder classico (con inizializzazione standard) di meno di 0,1 punti dopo il warm-up, su una serie lunga.

### 5.4 Timeframe W e M

- Barra W/M: open = primo open, high = massimo, low = minimo, close = ultimo close, volume = somma; fattore di rettifica dell'ultima barra.
- `available_at` = fine periodo di calendario (domenica per W, ultimo giorno del mese per M). Un periodo non chiuso non produce barra.
- Le feature W/M usano la stessa `compute_features` sulle barre W/M.
- Alla data daily *t* il valore W/M è l'ultima riga con `available_at ≤ t` (`merge_asof`). Ne deriva un giorno di ritardo conservativo, mai uno sguardo al futuro.

### 5.5 Score v1

- Stessa logica di `ScoringEngine.score_prices` oggi: sottopunteggi trend (30%), momentum (25%), volatilità (15%), volume (10%), supporti/resistenze (10%), penalità di rischio (−10%), clamp 0–100, segnale da `signal_from_score`, livello di rischio, confidenza, motivazioni, condizioni e sintesi.
- Sostituzioni di input: `max_drawdown` → `max_drawdown_252`; `obv ≥ 0` → `obv_ratio_20 ≥ 0`; RSI di Wilder; supporti e resistenze dalle feature confermate.
- Calcolato per D, W e M. L'interfaccia mostra lo score D.
- **Warm-up dello score:** la formula gestisce input mancanti come oggi, ma una riga ha `warmup_complete = 1` solo quando tutti gli input dello score sono disponibili (252 barre del timeframe; supporti e resistenze possono restare vuoti). Harness, backtest, ML e interfaccia usano solo righe complete: l'interfaccia mostra "storico insufficiente" invece di uno score parziale. Per W e M servono 252 barre settimanali o mensili: l'evidenza M sarà spesso `INSUFFICIENTE`, ed è dichiarato.
- `SCORE_VERSION = "score-v1"`, `PIPELINE_VERSION = "features-v1"`.

### 5.6 `features_daily`

| Colonna | Note |
|---|---|
| `id` | chiave |
| `asset_id` | FK `assets`, `ON DELETE CASCADE` come `price_history` |
| `timeframe` | `D`, `W`, `M` |
| `date` | data della barra (D) o `available_at` (W/M) |
| `segment_id` | progressivo del segmento nella serie |
| `pipeline_version`, `score_version` | versioni |
| `data_mode` | `REAL`, `DEMO` |
| `window_hash` | SHA-256 delle barre di input nella finestra di dipendenza massima della riga |
| `warmup_complete` | 1 se tutti gli input dello score sono disponibili (§5.5) |
| `score`, `trend_score`, `momentum_score`, `volatility_score`, `volume_score`, `support_resistance_score`, `risk_penalty` | REAL |
| `features_json` | tutte le feature della riga |
| `computed_at` | timestamp |

Vincolo univoco: `(asset_id, timeframe, date, pipeline_version, data_mode)`.

**Calcolo incrementale.** Per ogni asset e `data_mode` si calcolano gli hash delle finestre di tutte le righe candidate. Si ricalcolano solo le righe nuove o con `window_hash` diverso: nuove barre, revisioni, nuovi segmenti. Le righe che non esistono più (per esempio una data uscita da un segmento) vengono rimosse. Un test verifica che il risultato incrementale sia identico a un ricalcolo completo.

**Quando si aggiorna:**

- `_recalculate_signal` aggiorna in modo incrementale il solo asset rinfrescato;
- `FEATURE_REFRESH` (job) aggiorna una lista di asset o tutti;
- backtest, harness e ML aggiornano gli asset del proprio universo prima di leggere.

**Test d'uguaglianza ("una sola verità").** Per la stessa serie, lo score in `signals`, quello usato dal simulatore alla data *t* e quello nel dataset ML alla data *t* coincidono con la riga di `features_daily`.

## 6. Serie reale, rettifiche e cambi

### 6.1 `data_mode`

- **REAL:** solo righe di `price_history` con `is_real_data = 1`, mai completate con righe seed.
- **DEMO:** solo righe con `is_real_data = 0`.
- Un run usa una sola modalità. Default: `REAL`.
- In modalità REAL gli asset senza serie reale vengono esclusi ed elencati; se non ne resta nessuno → 409 `LAB_NO_REAL_SERIES`.
- I run DEMO sono possibili ed etichettati, non producono verdetto e non vengono registrati come tentativi.
- **Score in interfaccia:** serie REAL se l'asset ne ha una, altrimenti DEMO. La scelta viene salvata nel segnale (`signals.data_mode`). Una serie REAL troppo corta per il warm-up dello score (§5.5) produce "Storico reale insufficiente (N barre, servono 252).", senza ripiegare sul seed.

### 6.2 Segmenti

Una serie si divide in segmenti:

- a ogni buco di più di `LAB_SEGMENT_MAX_GAP_SESSIONS` (5) sedute: giorni lavorativi per azioni/ETF, giorni di calendario per le crypto;
- a ogni split sospetto (§6.3).

Ogni segmento ha il proprio warm-up. Rendimenti futuri ed etichette non attraversano mai il confine di un segmento. Una posizione del simulatore aperta al confine viene chiusa alla chiusura dell'ultima barra valida del segmento, con i costi, e marcata `SEGMENT_EXIT` nel run: dopo uno split sospetto il prezzo successivo non è confrontabile.

### 6.3 Base di rettifica e guardia split

| Base | Significato | Provider |
|---|---|---|
| `NOT_APPLICABLE` | nessun evento societario | `coingecko` |
| `UNKNOWN` | rettifica non verificata | `stooq`, righe reali senza provider noto |
| `SPLIT` / `SPLIT_DIVIDEND` | rettifica dichiarata dalla fonte | provider futuri (SP2b) |

La base è una costante nel codice per provider; la cambia solo un commit dopo una verifica documentata della fonte.

**Guardia split** (solo base `UNKNOWN`). Alla barra *t* c'è uno split sospetto se, per un rapporto *k* ∈ {2, 3, 4, 5, 10, 3/2}:

- `close_{t−1} / close_t` oppure `close_t / close_{t−1}` dista meno di `LAB_SPLIT_TOLERANCE` (3%) da *k*;
- e `open_t / close_{t−1}` è compatibile con lo stesso rapporto entro la stessa tolleranza.

L'evento apre un nuovo segmento e compare nel report con data e rapporto. Un crollo reale scambiato per split costa solo un nuovo warm-up.

### 6.4 Cambi BCE storici

- `EcbFxProvider.fetch_history(currency, start, end)`: CSV ECB Data Portal `EXR D.<VAL>.EUR.SP00.A` con `startPeriod`/`endPeriod`, una chiamata per valuta, bucket di budget `ecb` e trasporto governato esistenti, rifiuto delle date future.
- Inserimento idempotente in `fx_rates` sul vincolo univoco esistente.
- Avvio solo esplicito: job `FX_BACKFILL` (`POST /data/fx/backfill`) e script. 409 `REAL_DATA_DISABLED` con `ENABLE_REAL_DATA=false`, come la route FX esistente.
- **Conversione:** `prezzo_EUR(t) = prezzo_locale(t) × cambio_verso_EUR(t)`, dove il cambio è l'ultima osservazione BCE con data ≤ *t* e età ≤ `ECB_FX_MAX_AGE_DAYS`. Oltre, la barra non si usa né per la contabilità né per le etichette, e il conteggio delle barre escluse compare nel report. EUR = 1.

### 6.5 Benchmark

In modalità REAL il benchmark è una serie reale convertita in EUR; altrimenti "benchmark non disponibile". Mai seed in un run REAL.

R2: per ogni nuovo run congelare gli input benchmark e FX effettivamente usati, anche se il benchmark è esterno all'universo tradato. Curva, rendimento e alpha letti devono riferirsi allo stesso snapshot del calcolo. Se uno storico v0/v1 non ha snapshot, dichiarare la non riproducibilità e la fonte di eventuali valori ricalcolati; non presentare curva nuova e summary vecchio come coerenti né modificare in silenzio il run.

### 6.6 Limiti dichiarati in ogni report

- Universo = asset attivi oggi: bias di sopravvivenza (snapshot dell'universo in SP2b).
- Dividendi assenti con base `UNKNOWN`.
- Storico CoinGecko di circa 365 giorni.
- Costi di esecuzione ipotizzati (§7.3).

## 7. Backtester onesto

### 7.1 Tempi

- Decisione alla chiusura di *t* con la riga as-of *t* (con warm-up completo) del segnale scelto (`signal_name`, default `score`; `signal_timeframe`, default `D`).
- Ordini all'apertura della **barra successiva dello stesso listing**. Se manca, l'ordine attende fino a `LAB_ORDER_MAX_PENDING_SESSIONS` (5) sedute, poi viene annullato e registrato.
- Calendario del portafoglio: unione dei calendari dei listing. Ogni asset agisce solo sulle proprie barre; alla data *t* sono idonei solo gli asset con una barra a *t*.

### 7.2 Prezzi di esecuzione e stop

- Acquisto: `open_{t+1} × (1 + costo_per_lato)`; vendita: `open_{t+1} × (1 − costo_per_lato)`; poi conversione in EUR al cambio di *t+1*.
- Stop loss e take profit, con livelli fissati dal prezzo di esecuzione:
  - `low ≤ stop` → esecuzione a `min(open, stop)`;
  - `high ≥ tp` → esecuzione a `max(open, tp)`;
  - entrambi nella stessa barra → vince lo stop.
- Un test garantisce che nessun fill avvenga sulla barra del segnale.

### 7.3 Profilo costi Trade Republic

| Voce | Default (config) |
|---|---|
| Commissione | `TR_COMMISSION_EUR` = 1,00 € per ordine eseguito, stop inclusi |
| Costo per lato (spread + slippage) | `TR_COST_BPS_EQUITY` = 10 (azioni, ETF, ETC/ETN, obbligazioni); `TR_COST_BPS_CRYPTO` = 50 |
| Cambio | nessuna commissione esplicita: TR quota in EUR, la conversione è inclusa nel costo per lato |
| Quantità | quote intere per azioni ed ETF (`BACKTEST_FRACTIONAL_SHARES` = false); frazionarie per le crypto |
| Ordine minimo | `BACKTEST_MIN_TRADE_EUR` = 100: nessun ordine sotto soglia |
| Bollo e imposte | costanti esistenti (0,2% annuo; 26% / 12,5% sulle plusvalenze realizzate), calcolati **in EUR**, quindi utili e perdite di cambio inclusi |

Il profilo è sovrascrivibile per run e salvato nel run.

### 7.4 Strategie

Funzioni pure "pesi obiettivo alla chiusura di *t*" con la semantica attuale:

- `SCORE_THRESHOLD`: soglie buy/sell, peso massimo per asset;
- `TOP_N_SCORE`: primi N per segnale, peso uguale entro il peso massimo, ribilanciamento;
- `BUY_AND_HOLD`: acquisto iniziale a peso uguale.

### 7.5 Metriche

In EUR, con valutazione giornaliera al close rettificato × cambio:

- rendimento totale, CAGR, drawdown massimo;
- Sharpe annualizzato con tasso privo di rischio 0 (dichiarato);
- turnover, costi per voce, esposizione media;
- profit factor e win rate;
- analisi netta come oggi (imposte, bollo).

### 7.6 Persistenza, API e storico

- `BacktestRunIn`: via `fee_percent`; aggiunti profilo costi, `data_mode`, `signal_name`, `signal_timeframe`.
- `backtest_runs`: colonne additive `engine_version` (`v0` per i run esistenti, `v1` per i nuovi), `data_mode`, `signal_name`, `signal_timeframe`, `cost_profile_json`, `fingerprint`, `warnings_json`. I run `v0` restano e sono mostrati come "motore precedente".
- **Impronta:** SHA-256 canonico di config, versioni, `data_mode`, universo e hash di tutti gli input effettivi, inclusi barre/FX del benchmark separato (§6.5). Stessi input → stesso risultato; una revisione del benchmark cambia l'impronta di un nuovo run (test R2). Risultati salvati letti dal proprio snapshot.

## 8. Harness, walk-forward, DSR e verdetto

### 8.1 Etichetta

Per la terna (segnale, timeframe, orizzonte *h* ∈ {1, 5, 21}):

`r(t, h) = open_EUR(t + 1 + h) / open_EUR(t + 1) − 1`

Ingresso e uscita all'apertura (stesso fill del simulatore), prezzi rettificati in EUR. Etichetta assente se attraversa un segmento o manca un cambio valido.

### 8.2 Metriche dell'harness

- **IC di rango** (Spearman) per data, solo dove ci sono almeno `LAB_MIN_NAMES` (10) asset con segnale (riga con warm-up completo) ed etichetta. Media, deviazione standard, IR, quota di date con IC > 0.
- **t di Newey-West** sulla serie degli IC: varianza di lungo periodo con pesi di Bartlett e lag *h* − 1 (corregge la sovrapposizione delle etichette).
- **Bucket:** decili con almeno 50 asset per data, altrimenti quintili (dichiarati). Rendimento medio per bucket (monotonia).
- **Spread alto − basso** su ribilanciamenti non sovrapposti ogni *h* sedute: lordo e netto. Costo per gamba = `2 × turnover × (TR_COMMISSION_EUR / nozionale_per_posizione + bps_per_lato)`, con `nozionale_per_posizione = LAB_REFERENCE_CAPITAL_EUR / asset_nel_bucket` (default 10.000 €).
- **Turnover** del bucket alto e **autocorrelazione di rango** del segnale fra ribilanciamenti.

Lo spread long-short è diagnostico: su TR non si va short. L'implementabilità la misura il walk-forward long-only.

### 8.3 Walk-forward

- Finestre mobili: in-sample `LAB_WF_IS_SESSIONS` (504), OOS `LAB_WF_OOS_SESSIONS` (126), passo = OOS.
- **Griglie:**
  - `SCORE_THRESHOLD`: buy ∈ {60, 65, 70, 75} × sell ∈ {35, 40, 45};
  - `TOP_N_SCORE`: N ∈ {3, 5, 8} × ribilanciamento ∈ {settimanale, mensile};
  - `BUY_AND_HOLD`: nessuna griglia.
  - Stop e altri parametri restano quelli del run.
- **Procedura:**
  1. per ogni cutoff IS, valutare la griglia con soli input disponibili entro `is_end`, inclusa la conoscenza di segmenti, split e gap; nessun costo/liquidazione IS può dipendere dalla prima barra OOS. Una simulazione globale eventualmente mantenuta per il registro dei tentativi (§8.4) è distinta e non alimenta la selezione;
  2. per ogni finestra si sceglie la configurazione con lo Sharpe netto più alto calcolato **sui soli rendimenti giornalieri dentro la finestra in-sample** (a parità vince la configurazione che precede nell'ordine della griglia);
  3. il periodo OOS è **un'unica simulazione** in cui i parametri cambiano all'inizio di ogni segmento OOS e il portafoglio prosegue senza liquidazioni forzate.
- **Output:** parametri scelti per finestra, Sharpe in-sample medio, Sharpe OOS, degrado IS→OOS, metriche OOS complete, DSR e *N*.
- Test R1: con input fino a `is_end` invariati, modifica/aggiunta/rimozione dei dati OOS lascia identici tutti gli Sharpe IS e i parametri scelti; includere perturbazioni che creano/eliminano split e gap al confine (§6.2), non solo variazioni senza segmentazione. Conservare la storia precedente e la semantica della finestra dichiarate nel run.

### 8.4 Registro dei tentativi

Tabella `lab_trials` (append-only, trigger contro UPDATE e DELETE):

- `family_key` = (`signal_name`, `signal_timeframe`);
- `config_hash`, `fingerprint` dei dati, `kind` (`BACKTEST`, `COMPARE`, `WF_GRID`);
- `sharpe_daily`, `n_obs`, riferimento al job, `created_at`.

*N* = numero di **configurazioni distinte** (`config_hash`) registrate nella famiglia; per ciascuna vale lo Sharpe più recente. Rieseguire la stessa configurazione non fa crescere *N*. I run DEMO non vengono registrati.

### 8.5 DSR

Con Ŝ = Sharpe giornaliero OOS, *T* osservazioni, γ₃ asimmetria e γ₄ curtosi (non in eccesso) dei rendimenti OOS, *V* varianza degli Sharpe dei tentativi della famiglia e γ = 0,5772 (Eulero-Mascheroni):

- `SR₀ = √V × ((1 − γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N e)))`; `SR₀ = 0` se *N* = 1 oppure *V* = 0;
- `DSR = Φ((Ŝ − SR₀) √(T − 1) / √(1 − γ₃ Ŝ + (γ₄ − 1)/4 × Ŝ²))`.

Φ e Φ⁻¹ da `statistics.NormalDist`. Test: valori di riferimento calcolati a mano; a parità del resto, il DSR scende al crescere di *N*.

### 8.6 Report di evidenza e verdetto

Un job `EVIDENCE` per (segnale, timeframe, orizzonti, periodo, universo opzionale; default = tutti gli asset con serie REAL) produce, per ogni orizzonte:

- le metriche dell'harness (§8.2);
- il walk-forward `TOP_N_SCORE` sullo stesso segnale con ribilanciamento coerente con *h* (1 → giornaliero, 5 → settimanale, 21 → mensile), griglia N ∈ {3, 5, 8}, capitale `LAB_REFERENCE_CAPITAL_EUR`, nessuno stop;
- il verdetto.

| Verdetto | Condizione |
|---|---|
| `INSUFFICIENTE` | date IC < `LAB_MIN_IC_DATES` (252), oppure sedute OOS < `LAB_MIN_OOS_SESSIONS` (252), oppure media asset per data < `LAB_MIN_NAMES` (10) |
| `VALIDATO` | IC medio > 0, t NW ≥ `LAB_MIN_T_STAT` (2), spread netto > 0, DSR ≥ `LAB_MIN_DSR` (0,95) |
| `NON VALIDATO` | altrimenti |

Tabella `lab_evidence_reports` (immutabile, trigger contro UPDATE e DELETE), una riga per orizzonte:

- segnale, timeframe, orizzonte, verdetto;
- metriche, soglie, versioni;
- universo ed esclusi, eventi split, barre escluse per cambio;
- impronta, limiti dichiarati, job, `created_at`.

Un ricalcolo crea un report nuovo.

### 8.7 Badge del verdetto

`EvidenceBadge` mostra il verdetto di (`score`, `D`):

- testo: verdetto migliore fra gli orizzonti del report più recente, con orizzonte (per esempio "NON VALIDATO · 5g");
- tooltip: i tre orizzonti, la data del report, la nota "verdetto sul segnale nell'universo, non sul singolo titolo";
- `NON MISURATO` se non esiste un report.

Ordine "migliore": `VALIDATO` > `NON VALIDATO` > `INSUFFICIENTE`.

Posizione (il verdetto è del segnale, non del titolo: una volta per sezione, non per riga):

| Vista | Badge | Per riga |
|---|---|---|
| Analisi (`AnalysisPage`) | accanto allo score dell'asset | — |
| Watchlist (`WatchlistPage`) | intestazione della colonna score | marcatore "DEMO" se `signals.data_mode = DEMO` |
| Dashboard (`DashboardPage`) | intestazione delle sezioni con score | marcatore "DEMO" |
| Oggi (`TodayPage`) | intestazione dell'elenco azioni | marcatore "DEMO" |

In Analisi, per un asset DEMO il badge dice "DEMO · non misurabile".

## 9. Job asincroni

Tabella `lab_jobs`:

| Colonna | Note |
|---|---|
| `kind` | `BACKTEST`, `COMPARE`, `WALK_FORWARD`, `EVIDENCE`, `FEATURE_REFRESH`, `FX_BACKFILL`, `ML_TRAIN` |
| `status` | `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `INTERRUPTED` |
| `params_json`, `params_hash` | parametri validati e loro hash canonico |
| `progress` | 0..1 |
| `result_ref` / `result_json` | riferimento (run backtest, report, modello) oppure risultato inline (confronto, walk-forward) |
| `error_code` | reason code sanitizzato |
| `cancel_requested` | flag |
| `created_at`, `started_at`, `finished_at` | timestamp |

Regole:

- un solo thread worker, avviato nel lifespan dell'app, ordine FIFO;
- all'avvio ogni job `RUNNING` diventa `INTERRUPTED`;
- annullamento cooperativo fra un passo e l'altro: `QUEUED` → `CANCELLED` subito, `RUNNING` → `CANCELLED` al passo successivo;
- ogni job usa una propria connessione con transazioni brevi, mai una transazione aperta durante il calcolo;
- un job con lo stesso `kind` e `params_hash` già `QUEUED` o `RUNNING` viene restituito invece di crearne un altro;
- l'esecutore è sostituibile: nei test è sincrono (inline).

## 10. API

| Route | Comportamento |
|---|---|
| `POST /backtests/run`, `/backtests/compare`, `/backtests/walk-forward` | 202 `{job_id, status}` |
| `GET /backtests`, `GET /backtests/{id}`, `DELETE /backtests/{id}` | invariate nella forma, campi additivi |
| `GET /lab/jobs`, `GET /lab/jobs/{id}` | elenco limitato e stato con risultato |
| `POST /lab/jobs/{id}/cancel` | 200; 409 `JOB_NOT_CANCELLABLE` se già concluso |
| `POST /lab/evidence` | 202; parametri: segnale, timeframe, orizzonti, periodo, simboli opzionali |
| `GET /lab/evidence`, `GET /lab/evidence/{id}` | elenco filtrabile e report completo |
| `GET /lab/evidence/latest?signal_name=&timeframe=` | verdetti più recenti per orizzonte (badge) |
| `GET /lab/signals` | segnali valutabili: `score`, sottopunteggi, feature numeriche |
| `POST /lab/features/refresh` | 202 |
| `POST /data/fx/backfill` | 202; 409 `REAL_DATA_DISABLED` |
| `POST /ml/train` | 202 |

Errori: 409 con reason code (`LAB_NO_REAL_SERIES`, `MODEL_PIPELINE_MISMATCH`, `JOB_NOT_CANCELLABLE`, `REAL_DATA_DISABLED`); 422 per parametri non validi; 404 per risorse assenti. Nessun segreto, percorso, URL o traccia nei messaggi.

## 11. ML

- Il dataset legge `features_daily` (D) nel `data_mode` del training (default `REAL`, salvato nel modello).
- `FEATURE_COLUMNS` v1 (colonne adimensionali della pipeline più score e sottopunteggi): `close_return_1d`, `close_return_5d`, `close_return_20d`, `volatility_30d`, `rsi_14`, `macd_line_pct`, `macd_histogram_pct`, `price_vs_sma50`, `price_vs_sma200`, `sma50_vs_sma200`, `atr_14_pct`, `adx_14`, `plus_di`, `minus_di`, `bollinger_percent_b`, `max_drawdown_252`, `drawdown_60`, `volume_ratio_20`, `obv_ratio_20`, `stochastic_k`, `stochastic_d`, `roc_12`, `support_distance_pct`, `resistance_distance_pct`, `score`, `trend_score`, `momentum_score`, `volatility_score`, `volume_score`, `support_resistance_score`, `risk_penalty`.
- Via news, `portfolio_weight` e `current_recommendation_encoded`.
- Target invariati nella definizione (SP4), calcolati sulla serie del laboratorio: prezzi rettificati, mai attraverso un segmento.
- `ml_models` aggiunge `pipeline_version` e `data_mode`. Previsione con modello di versione diversa o senza versione → 409 `MODEL_PIPELINE_MISMATCH` ("riaddestra").
- Training come job `ML_TRAIN`. Metriche, split e walk-forward ML restano come oggi (SP4).

## 12. Interfaccia

Stile attuale; test Vitest; tipi di `api.ts` omologhi agli schemi Pydantic.

- **Pagina Backtest:**
  - profilo costi (commissione, bps per classe, ordine minimo, frazioni), `data_mode`, segnale e timeframe;
  - job con stato, progresso, polling (`AbortController`) e annullamento;
  - walk-forward con parametri per finestra, Sharpe IS/OOS, degrado, DSR e *N*;
  - etichetta "motore precedente" per i run `v0`;
  - modalità **Evidenza**: form (segnale, timeframe, orizzonti, periodo) e report (IC e t, bucket, spread lordo/netto, turnover, walk-forward, DSR, verdetto, universo ed esclusi, limiti).
- **`EvidenceBadge`** e marcatore DEMO nelle viste del §8.7 (Analisi, Watchlist, Dashboard, Oggi). In Analisi lo "score finale" coincide con lo score; la correzione news resta visibile come informazione separata.
- **Pagina ML:** training come job con stato; messaggio 409 "riaddestra"; nessuna feature news o portafoglio mostrata.

## 13. Errori e sicurezza

- Fail-closed per l'evidenza: barre senza cambio valido, segmenti, esclusi e split sono contati e mostrati, mai colmati.
- Fail-soft per la consultazione: lo score in interfaccia mostra "dati insufficienti" o "DEMO" invece di un numero inventato.
- Nessun segreto in log, eccezioni, report, risposte API o job; `error_code` stabili e sanitizzati.
- Nessuna chiamata di rete nei test; il backfill BCE usa fixture CSV offline.
- Nessuna scrittura su `data/investedge.db` durante test o smoke: `INVESTEDGE_DB_PATH` su file temporanei.
- Migrazioni additive con backup pre-migrazione esistente; trigger di immutabilità su `lab_trials` e `lab_evidence_reports`.

## 14. Strategia di verifica

- **Proprietà:** causalità futuro/inizio serie per ogni feature, su serie generate con seed fissi (§5.2); incrementale = completo (§5.6).
- **Valori noti:** RSI di Wilder; Newey-West, Spearman e DSR su casi piccoli calcolati a mano; scenario del simulatore a 3 asset (USD, EUR, crypto) con fill, costi, stop con gap, cambio, quote intere e imposte attesi.
- **Uguaglianza:** score in `signals` = simulatore(*t*) = dataset ML(*t*) = `features_daily`.
- **Confine:** test sugli import (§4.3); nessun `chikou_span` in `features_daily`.
- **Harness su fixture sintetiche:**
  - un segnale costruito per anticipare il rendimento (rendimento futuro + rumore) → IC > 0 e `VALIDATO`;
  - un segnale casuale con seed fissi → `NON VALIDATO`;
  - un campione corto → `INSUFFICIENTE`.
- **Walk-forward:** R1, invarianti di tutti gli Sharpe IS e della selezione anche con split/gap al confine; *N* che cresce solo con configurazioni nuove.
- **Benchmark:** R2, revisione della sola serie esterna cambia l'impronta nuova; rilettura del run conserva curva/summary/alpha coerenti; compatibilità storici esplicita.
- **Separazione demo/reale:** run DEMO mai in `lab_trials` né in `lab_evidence_reports`; run REAL senza righe seed.
- **Job:** 202, deduplica, annullamento, `INTERRUPTED` al riavvio, errori sanitizzati.
- **Frontend:** Vitest per Backtest (modalità, job, Evidenza), `EvidenceBadge`, ML.
- **Fixture veloce:** DB seed creato una volta per sessione (`tmp_path_factory`) e copiato per test; guardia di rete globale in `conftest.py` (risolve il Minor 15 della Fase 2). Tempi della suite prima e dopo registrati.
- **Prestazioni** (misurate e registrate, obiettivi indicativi non bloccanti): universo sintetico di 50 asset × 1500 barre × 3 timeframe; calcolo completo ≤ 60 s; incrementale di una barra ≤ 5 s; job di evidenza su 5 anni ≤ 120 s.

## 15. Criteri di successo (gate di fine SP1)

1. Test d'uguaglianza dello score verde (UI, backtest, ML, `features_daily`).
2. Test di proprietà sulla causalità verdi per ogni feature v1; `chikou_span` assente dai dati di calcolo; test di confine verde.
3. Scenario del simulatore calcolato a mano verde; nessun fill sulla barra del segnale.
4. Harness: segnale costruito → `VALIDATO`, casuale → `NON VALIDATO`, corto → `INSUFFICIENTE`.
5. DSR: valori di riferimento e monotonia in *N* verdi.
6. Walk-forward: tutti gli Sharpe IS e parametri invarianti a modifica/aggiunta/rimozione OOS, anche con split/gap al confine (R1); benchmark riproducibile con impronta completa e curva/summary/alpha coerenti (R2).
7. DEMO mai nei tentativi né nei verdetti; report e tentativi immutabili.
8. Job da 202, annullabili, `INTERRUPTED` al riavvio.
9. Incrementale identico al completo; tempi misurati e registrati.
10. Gate finale: `pytest` completo, `ruff check backend scripts tests`, `npm run test:run`, `npm run build`, `npm audit --audit-level=high` verdi, con rete bloccata (0 tentativi di rete); `git diff --check` verde; review indipendente senza Critical né Important aperti.

## 16. Configurazione

| Variabile | Default |
|---|---|
| `LAB_MIN_NAMES` | 10 |
| `LAB_MIN_IC_DATES` | 252 |
| `LAB_MIN_OOS_SESSIONS` | 252 |
| `LAB_MIN_T_STAT` | 2.0 |
| `LAB_MIN_DSR` | 0.95 |
| `LAB_WF_IS_SESSIONS` | 504 |
| `LAB_WF_OOS_SESSIONS` | 126 |
| `LAB_SEGMENT_MAX_GAP_SESSIONS` | 5 |
| `LAB_SPLIT_TOLERANCE` | 0.03 |
| `LAB_ORDER_MAX_PENDING_SESSIONS` | 5 |
| `LAB_REFERENCE_CAPITAL_EUR` | 10000 |
| `TR_COMMISSION_EUR` | 1.00 |
| `TR_COST_BPS_EQUITY` | 10 |
| `TR_COST_BPS_CRYPTO` | 50 |
| `BACKTEST_FRACTIONAL_SHARES` | false |
| `BACKTEST_MIN_TRADE_EUR` | 100 |
| `ECB_FX_MAX_AGE_DAYS` | 7 (esistente) |

## 17. Fuori ambito e destinazione

| Tema | SP |
|---|---|
| Fonte di eventi societari (split, dividendi), snapshot dell'universo, barre intraday, ricollegamento asset legacy (I3) | SP2b |
| Contenuto dello score (penalità sulla volatilità, famiglie trend/breakout), news classificate e pesate | SP3 |
| Target e metriche ML, ranking cross-sezionale, purge ed embargo, calibrazione, champion/challenger | SP4 |
| Applicazione del verdetto a decisioni e ordini, runtime sempre acceso, schedulazione | SP6 |
| Redesign dell'interfaccia | SP8 |

## 18. Rischi e limiti residui

| Rischio | Mitigazione |
|---|---|
| Universo piccolo: molti verdetti `INSUFFICIENTE` | verdetto esplicito, nessun numero spacciato per evidenza; l'utente può attivare altri listing dal catalogo |
| Base Stooq `UNKNOWN`: dividendi assenti, falsi split | limite dichiarato; segmentazione fail-closed |
| Bias di sopravvivenza | dichiarato in ogni report; snapshot in SP2b |
| CoinGecko circa 365 giorni | walk-forward crypto quasi sempre `INSUFFICIENTE`, dichiarato |
| Costi per lato ipotizzati | configurabili e salvati nel run |
| Medie esponenziali troncate diverse dal classico | differenza limitata e testata (RSI < 0,1 punti) |
| Supertrend su finestra con costo O(n × L) | calcolo incrementale; tempi misurati |
| Un solo worker: job in coda | stato e progresso visibili; annullamento |
| Crash durante un job | `INTERRUPTED` al riavvio, rilancio manuale |
| Modello fiscale semplificato (nessun riporto delle minusvalenze fra anni) | invariato rispetto a oggi, dichiarato nell'analisi netta |

## 19. Fonti di riferimento

- D. H. Bailey, M. López de Prado, "The Deflated Sharpe Ratio", *Journal of Portfolio Management*, 2014.
- W. K. Newey, K. D. West, "A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix", *Econometrica*, 1987.
- J. W. Wilder, *New Concepts in Technical Trading Systems*, 1978 (RSI, ADX/DI).
- C. R. Harvey, Y. Liu, H. Zhu, "… and the Cross-Section of Expected Returns", *Review of Financial Studies*, 2016 (soglie per test multipli).
- ECB Data Portal, API di consultazione delle serie `EXR`.
