# InvestEdge — piano SP3: gate strategie intraday 15/30 minuti

**Stato: PROPOSTA da approvare prima del codice; Task 0 documentale FATTO.** Task 1–12 NON INIZIATI, dipendono dall'approvazione esplicita di spec/piano. Task 13 è addendum dopo SP6a e completamento del backlog SP2b. Nessuna implementazione SP3 in questa consegna.

**Spec:** [strategie intraday](../specs/2026-10-13-investedge-sp3-intraday-strategies-design.md). **Base Task 0:** origin/main verificato a `12ca2c36a2fc19451e70a08e37514089f3e11bb6`, uguale origin/investedge/sp2b-task-12; feature precedente `d182cd547562b933ed1a2c92d4cab78dc8ed1316` già integrata. Stato: G1_TECH PASS, G1_DATA INSUFFICIENTE; [report SP2b](../../reports/2026-10-12-sp2b-intraday-data-gate.md).

**Obiettivo:** software di ricerca con dati point-in-time, conversione attestata delle quote, contesto daily congelato, letture timeline-only e risorse bounded; due famiglie/tre ablation e holding dal fill; costi/fill conservativi, trial registry completo e validazione IS/OOS/holdout. Nessuna promessa di rendimento.

**Architettura:** `backend/app/intraday_research/` sopra i contratti dati `intraday/`; statistiche pure SP1 riusabili, tabelle/report dedicati, job finiti `INTRADAY_*`, API nuove e UI minima nel laboratorio. D/W/M, costi TR, engine-v1, score-v1, ML e report daily preservati.

## Protocollo e gate comuni

- Unico writer del task, reviewer read-only. Eseguire solo primo NON INIZIATO con dipendenze FATTE; task IN CORSO appartiene al registro. Niente scritture concorrenti o avanzamento ai task successivi nella stessa consegna non autorizzata.
- Task 0 branch `investedge/sp3-task-0` da origin/main sopra; Task N=1–12 branch `investedge/sp3-task-N`, base `origin/investedge/sp3-task-(N-1)` verificata, inclusi eventuali registri documentali. Non inventare SHA propri. Task 13/base remota da fissare nell'addendum al ritorno dalle fasi precedenti.
- Prima di modificare: leggere AGENTS/programma/spec/piano, fetch/status/branch/base SHA locale=remoto. Checkout originale main `96f7299a4aaef1c2074ed1f2afeae2ffbf5cf27d` intenzionalmente preservato; lavorare solo nel worktree gestito di questa chat. Non modificare il worktree della chat precedente. Divergenze nuove→chiarimento, nessun reset/rebase/amend/force.
- Pubblicare subito lock `git push -u origin HEAD`. Per ogni task codice: TDD **RED** per causa prevista → minimo → **GREEN** → review; output test/lint freschi prima di FATTO. Test **offline**, clock fissato, fixture locali/sintetiche/MockTransport/socket fake, guardia rete completa; `.env` non caricato. `INVESTEDGE_DB_PATH` soltanto scratch assoluto nuovo/DB RAM, mai `data/investedge.db` o copie del DB reale.
- Scope per task esattamente sotto. A ogni allowlist si aggiungono questo piano e PROGRAMMA-OPERATIVO.md per chiusura. Spec modificabile solo per chiarire ambiguità senza cambiare decisioni approvate; scelte materiali nuove prima del codice dipendente. Nessun file/dependency diverso senza evidenza e autorizzazione applicabile.
- Schema solo additivo/versionato, backup/compatibilità/idempotenza/rollback. No update/delete/replace delle evidenze; nessun riuso semantico delle tabelle daily. Nessun nuovo SDK o dipendenza proposti.
- Gate tecnico ordinario Task 1–12: mirati + suite backend completa con JUnit tramite wrapper di rete, Ruff backend/scripts/tests, pip check, secret scan con pattern/self-test Fase2 e classificazione puntuale, diff/scope e review senza Critical/Important. Task UI anche install/test/build offline e audit HC0 (advisory separati dai test). Conteggi da JUnit, non da precedenti run. Nuovi fix→RED/GREEN mirati e gate finale aggiornato.
- Chiusura stesso commit: checkbox, registro stato/data/owner/test, SHA del precedente e Prossimo passo; messaggio esatto. Push **solo branch task**, `git ls-remote origin refs/heads/<branch>`=HEAD e worktree pulito. Dopo gate/review, merge remoto main solo fast-forward autorizzato il 2026-10-13: fetch, ascendenza `git merge-base --is-ancestor origin/main HEAD`, push non forzato `git push origin HEAD:refs/heads/main`, gate main=HEAD. Non spostare main locale del checkout originale, non creare merge commit/commit vuoto. Il successivo task registra lo SHA appena consegnato; output remoto finale anche nella risposta.
- Interruzione: checkpoint documentato e pubblicato, nessun lavoro lasciato solo locale. Nessuna cattura live, credenziale, spesa, accesso DB reale, ordine, paper, reale o leva. G1_DATA READY e G2 non derivano da fixture/G2_TECH; non iniziare SP6a per aggirare dati insufficienti.

Comandi gate da worktree (ambiente Python3.14 già verificato/installato offline, scratch assoluto nuovo):

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
$env:INVESTEDGE_DB_PATH = '<scratch-assoluto-nuovo>/test-only.db'
& './backend/.venv/Scripts/python.exe' '<scratch>/run_offline_tests.py' <test-del-task> -q -o addopts= -p no:cacheprovider --junitxml='<scratch>/targeted.xml'
& './backend/.venv/Scripts/python.exe' '<scratch>/run_offline_tests.py' tests -q -o addopts= -p no:cacheprovider --junitxml='<scratch>/full.xml'
& './backend/.venv/Scripts/python.exe' -m ruff check backend scripts tests --no-cache
& './backend/.venv/Scripts/python.exe' -m pip check
npm --prefix frontend ci --offline --no-audit --no-fund
npm --prefix frontend run test:run
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=high
git diff --check
```

Wrapper nello scratch replica guardia socket/DNS/flags SP2b, loopback ammesso solo per TestClient; i suoi self-test intenzionali distinti dalle chiamate inattese. Prima di usarlo, verificarne il blocco rete. Task 0 è documentale: RED/GREEN di completezza/link/sequenza nello scratch, diff/scan/review freschi; nessuna suite codice/build ripetuta sul codice invariato, nessuna finta validazione economica.

## Task 0 — Proposta spec/piano e registro SP2b verificato

**Branch:** `investedge/sp3-task-0`; **Base:** origin/main `12ca2c36a2fc19451e70a08e37514089f3e11bb6`.
**Dipendenze:** SP2b Task12 FATTO/G1_TECH PASS, incarico documentale e commit/push/FF autorizzati. Approvazione della proposta resta successiva.
**File nuovi:** questa spec/piano SP3, `docs/reports/2026-10-13-sp3-proposal-review.md`.
**File modificati:** `PROGRAMMA-OPERATIVO.md` soltanto. Script/check/output nello scratch fuori Git, nessun codice di prodotto.

- [x] Leggere programma completo alla base corrente, spec programma/SP2b e piano/report; rivedere contratti/chiamanti SP1/SP2b e fonti primarie necessarie.
- [x] Worktree gestito isolato da origin/main, originali preservati; branch/lock remoto pubblicato con SHA base verificato.
- [x] Proporre prerequisiti size/daily/timeline-only, setup/ablation/H/costi/fill/registry/split/stress/gate ex ante e task sequenziali con allowlist/test.
- [x] Review indipendenti e re-review delle correzioni PASS: nessun Critical/Important residuo;24/24 controlli documentali GREEN, secret/placeholder scan con self-test e diff/scope PASS. Programma/report aggiornati; nessun test economico.
- [x] Preparare la consegna documentale in questo commit: push branch/gate SHA, FF main/gate SHA e worktree pulito sono verifiche post-commit del protocollo autorizzato e verranno riportate nella consegna. Proposta da presentare prima del codice; proprio SHA nel task successivo.

**Commit:** `docs: propose SP3 intraday strategies and validation plan`

## Task 1 — Contratti di ricerca, risorse e registry preregistrato

**Branch:** `investedge/sp3-task-1`; **Base:** origin/investedge/sp3-task-0.
**Dipendenze:** Task0 FATTO + approvazione esplicita spec/piano.
**File nuovi:** `backend/app/intraday_research/__init__.py`, `contracts.py`, `registry.py` nel medesimo pacchetto; `tests/intraday_research_fixtures.py`, `tests/test_intraday_research_contracts.py`, `tests/test_intraday_research_registry.py`, `tests/test_intraday_research_schema.py`.
**File modificati:** `backend/app/database.py`, `tests/test_database.py`, `tests/conftest.py` (solo fixture scratch/registry, guardia rete invariata).

- [ ] RED: manifest/registry/tabelle assenti; ns/int64 non esatti, mixed namespace, cap non positivi, finite JSON; tutti i20 trial preregistrati prima del primo STARTED; FAILED/CANCELLED/REJECTED/no-trade non perduti; UPDATE/DELETE/REPLACE e FK cross-mode bloccati.
- [ ] Implementare contratti versionati e tabelle §12, risorse/seed/split/costi/gate frozen, config_hash distinto da experiment_hash, eventi append-only di trial/holdout. Default nessuna promozione dati sintetici; nessun provider/job avviato.
- [ ] GREEN: DB nuovo e fixture pre-SP2b/SP1/SP2b, backup fallito, rerun idempotente/rollback e righe/FK storiche identiche. Replica identica legata allo stesso esperimento, ipotesi nuova distinta; prova tamper e stato finale senza dati di esito inventati.
- [ ] Mirati: test_intraday_research_contracts/registry/schema + test_database/config/lab_trials; gate comune e review. Policy capitale/risorse proposta non imposta il paper.

**Commit:** `feat: preregister bounded intraday research experiments`

## Task 2 — Timeline-only, snapshot a finestre e bundle sostenibili

**Branch:** `investedge/sp3-task-2`; **Base:** origin/investedge/sp3-task-1.
**Dipendenze:** Task1 FATTO.
**File nuovi:** `backend/app/intraday_research/datasets.py`, `tests/test_intraday_research_datasets.py`, `tests/test_intraday_timeline_reader.py`, `backend/scripts/intraday_timeline_smoke.py`.
**File modificati:** `backend/app/intraday/store.py`, `replay.py`, `snapshots.py`, `quality.py`, `handlers.py` nel medesimo pacchetto; `backend/app/api/intraday_routes.py`, `backend/app/database.py` (solo indici/formato v2 additive); `tests/test_intraday_store.py`, `tests/test_intraday_replay.py`, `tests/test_intraday_snapshots.py`, `tests/test_intraday_quality.py`, `tests/test_intraday_api.py`, `tests/test_intraday_collector.py` (solo benchmark runtime fake).

- [ ] RED: pagina/freeze costruiscono proiezioni o lista prefisso intero; cap RAM/chunk violati; start recente ancora full-prefix; bundle con finestre overlapping cambia denominatori; stato iniziale usa revisioni future o omette receipt/macro/carry-in.
- [ ] Separare iterazione validata dalla proiezione; digest incrementale/count/hash/closure prima della pubblicazione, vecchio v1 intatto. Formato window-dependency-closure-v2 e bundle ordinato/riferimenti esatti §3.1; nessun DELETE/retention finita. Quality sul bundle conserva minimi20/10, raw99%, ogni cella90%/>0; non etichettare child5sedute READY.
- [ ] GREEN: timeline vecchia/nuova byte-equivalenti ai cutoff, A→B→A/shuffle/tie/cross-capture, superseded/pre-periodo/audit orfani, missing/tamper/rollback/cancel, macro globali, revisione BAR/news dopo freeze invarianti; SQLite authorizer/clock/provider negati nei GET e total_changes invariato. Confrontare proiezioni/carry-in/closure col v1; equivalenza di feature/policy/fill sarà verificata ai Task4/7/12 quando tali componenti esistono.
- [ ] Smoke30×20 e scalare5/20/60: p95≤250ms, timeline replay≤60s, RSS≤2GiB, crescita disco misurata, zero perdite. Runtime socketfake completo con checkpoint/status/reconcile per batch, budget/GAP/lag espliciti. Gate sostenibilità necessario prima di esperimenti grandi; se manca, task non FATTO per questa definizione, registrare blocco/limite senza abbassare soglie o passare al task dipendente.
- [ ] Mirati: test_intraday_timeline_reader/research_datasets + store/replay/snapshots/quality/API/collector/boundaries; suite/gate comune e review compatibilità v1. Script smoke rifiuta target esistente/data/investedge.db, dotenv e socket esterni.

**Commit:** `perf: bound intraday timeline and dataset reads`

## Task 3 — Quote-size e incremento prezzo attestati point-in-time

**Branch:** `investedge/sp3-task-3`; **Base:** origin/investedge/sp3-task-2.
**Dipendenze:** Task2 FATTO/sostenibilità verificata.
**File nuovi:** `backend/app/intraday_research/quote_units.py`, `tests/test_intraday_quote_units.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `registry.py`, `datasets.py`; `tests/intraday_research_fixtures.py`, `tests/test_intraday_research_datasets.py`.

- [ ] RED: ROUND_LOTS×100 implicito, SOURCE_UNATTESTED come shares, lotto/tick futuro cambia passato; scope errato, valid-time vs known-time, overflow/size zero/non intera; incremento prezzo UNKNOWN o rounding favorevole/oltre limite.
- [ ] Implementare import locale esplicito quote-size-attestation-v1 e price-increment-attestation-v1 nelle tabelle Task1, fonte/hash/contratto/lotto/tick/scope/tempi/ref frozen. Nessuna attestazione automatica da flag libero o deduzione prezzo; authority con prova verificabile, non solo URL/hash. Conservare originali, derivati keyed per hash/ref. Rounding Decimal conservativo della spec§3.3, nessun centesimo default.
- [ ] GREEN: conversioni a mano con due fattori di lotto e due incrementi prezzo sintetici diversi, nanosecondo al cutoff, A→B→A e first_received; UNKNOWN→zero fill/NON_IDONEO, synthetic non promuove G1. Bundle include attestazioni senza modificare digest dataset vecchi.
- [ ] Mirati: test_intraday_quote_units/research_datasets/contracts/registry; regressioni store/replay/aggregate/snapshots, gate comune e review.

**Commit:** `feat: attest point-in-time intraday quote units`

## Task 4 — Daily point-in-time, feature e filtri

**Branch:** `investedge/sp3-task-4`; **Base:** origin/investedge/sp3-task-3.
**Dipendenze:** Task3 FATTO.
**File nuovi:** `backend/app/intraday_research/context.py`, `features.py`, `eligibility.py`; `tests/test_intraday_daily_context.py`, `tests/test_intraday_research_features.py`, `tests/test_intraday_research_eligibility.py`, `tests/test_intraday_research_boundaries.py`.
**File modificati:** `tests/intraday_research_fixtures.py`, `backend/app/intraday_research/contracts.py`, `datasets.py`.

- [ ] RED: features_daily corrente usata, dailyBar progressiva conclusa, rettifica futura/overnight/gap/half-day/slot RVOL/benchmark future; finestre W−1 dichiarate complete, trailing join con barra 5/15m aperta, quote stale/status UNKNOWN/contesto insufficienti ammessi.
- [ ] Implementare daily dalle precedenti sedute complete e feature/units/warm-up/filtri esatti §3.4/4. VWAP session reset, EMA/ATR truncated bounded, ROC/RVOL stessa fascia, RS mercato+settore as-of, event filters; niente score/ML/news legacy.
- [ ] GREEN: OHLC/VWAP/EMA/ATR/ROC/RVOL/RS manuali; scalare/full/finestre equivalenti; mutation futuro append/change/remove su tutti input invariance bit-per-bit del prefisso; split reset, DST/half-day/calendario revisionato, covered-zero/news-disabled/UNKNOWN e causale known-time.
- [ ] AST confini: nessun import features_daily/score/technical_analysis/ML/provider nella ricerca pura, nessun import ricerca dal livello dati. Mirati nuovi quattro moduli + aggregate/quality/boundaries/lab_features/feature_store; gate comune e review.

**Commit:** `feat: compute point-in-time intraday research features`

## Task 5 — Setup deterministici e news ablation

**Branch:** `investedge/sp3-task-5`; **Base:** origin/investedge/sp3-task-4.
**Dipendenze:** Task4 FATTO.
**File nuovi:** `backend/app/intraday_research/strategies.py`, `news_features.py`; `tests/test_intraday_research_strategies.py`, `tests/test_intraday_research_news.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `registry.py`, `datasets.py` nel medesimo pacchetto; `tests/intraday_research_fixtures.py`, `tests/test_intraday_research_registry.py`, `tests/test_intraday_research_datasets.py`.

- [ ] RED: ingresso su barra aperta/OR incompleto, pullback/spike/invalidazione non rispettati; TECH_NEWS retroattivo, NEWS_ONLY richiede EMA/VWAP/momentum, duplicazione news-only nelle due famiglie gonfia le 20 configurazioni; parsing guidance/M&A senza prova/diritti, TTL rinnovata da duplicati.
- [ ] Implementare regole §5/7, livelli e motivi, griglia20/policy10 nell'ordine fissato; fatti news positivi verificabili o UNKNOWN, TTL60 e decadimento con emivita30, filtri negativi. Nessun LLM, sentiment±5 o consensus inventato. Setup puro, nessun simulatore/provider/ordine.
- [ ] Import locale esplicito news-source-attestation-v1 con authority primaria/prova/originali consentiti/hash/diritti/issuer/listing/article-version/fact binding/tempi nelle tabelle Task1; nessuna inferenza di issuer verificato da source/author/link/menzione. Assenza o prova tardiva→UNKNOWN al cutoff passato; refs nel manifesto. M&A solo target/classe/valuta/termini compatibili, mai premium assegnato all'acquirente.
- [ ] GREEN: casi positivi e mancati a mano per ogni famiglia/confine, ingresso a 1ns, revisioni mapping/cluster/authority, rumour/negazioni/unità/periodo/diritti; articolo mappato target+acquirer positivo solo target; signal key paired TECH_NEWS; NEWS_ONLY invariato cambiando soltanto timing tecnico. Holding distinto dal timeframe; sintetico positivo non prova economia.
- [ ] Mirati: strategies/news/features/eligibility/daily_context/boundaries, regressioni intraday_news/events e news legacy; gate comune e review.

**Commit:** `feat: define intraday candidate setups and news ablations`

## Task 6 — Fee Alpaca versionate e ledger costi

**Branch:** `investedge/sp3-task-6`; **Base:** origin/investedge/sp3-task-5.
**Dipendenze:** Task5 FATTO.
**File nuovi:** `backend/app/intraday_research/costs.py`, `tests/test_intraday_research_costs.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `registry.py`, `tests/intraday_research_fixtures.py`.

- [ ] RED: costo fisso TR trasferito, UNKNOWN come zero/tariffa corrente retroattiva, fee arrotondate per fill anziché giorno/conto/tipo, doppio addebito spread/slippage; ricorrenti divisi per20config o cancellati nei giorni flat, riserva cash insufficiente.
- [ ] Implementare profilo pubblico/fonte/hash/revisione/applicabilità/scope separato, ledger Decimal e allocazione esatta §8, scenari §8.1. Verificare fonte primaria solo documentale, nessuna chiamata broker/live; costi mancanti COST_PROFILE_UNVERIFIED, nessun acquisto.
- [ ] GREEN: buys/sells/partial e molti piccoli fill su più giorni, SEC/TAF/CAT e ceiling a mano; ricorrenti/repliche standalone, valori negativi/non finiti invalidi, tre versioni tariffa e invarianza del prefisso alle modifiche future. Fiscalità/EUR mancanti dichiarate; TR daily invariato.
- [ ] Mirati: research_costs/contracts/registry + lab_simulator/backtest/config; gate comune e review. Fotografia2026-10-01 non è automaticamente una vintage storica.

**Commit:** `feat: version Alpaca research costs separately from TR`

## Task 7 — Simulatore quote-eventi, rischio e holding dal fill

**Branch:** `investedge/sp3-task-7`; **Base:** origin/investedge/sp3-task-6.
**Dipendenze:** Task6 FATTO.
**File nuovi:** `backend/app/intraday_research/execution.py`, `simulator.py`; `tests/test_intraday_research_execution.py`, `tests/test_intraday_research_simulator.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `tests/intraday_research_fixtures.py`.

- [ ] RED: fill sul medesimo evento/barra, quote tied/tardiva, ask/bid invertiti o limite ignorato dopo slippage; budget quote riutilizzato/size sconosciuta; partial cambia first_fill/deadline, uscita inventata o oversell; ingresso vicino close/half-day, stop gap/ambiguità OHLC/no quote/halt/gap/irrisolto.
- [ ] RED preflight: R oltre2ATR/2% o tick/riserve invalide non creano fill/posizione/cash; partial successivo a prezzo peggiore non supera rischio0,25%/cash/peso e non allarga stop. GAP futuro non modifica ingresso/sizing già noti.
- [ ] Implementare BASE/stress su eventi successivi, pending30s/budget partial, ordine e priorità stabili, sizing intero/cassa riservata entro1×, rischio/cooldown/sessione §6. Stop mai allargato; H15/30 dal first_fill, residuo conserva versione; nessun clock/Trading API.
- [ ] GREEN: scenari manuali USD con più listing, target/stop/invalidazione/tempo/chiusura, partial/non-fill/latency/limit/gap/unità size e fee EOD; cassa/esposizione sempre entro limiti, UNRESOLVED conservato fino a evento realmente eseguibile e motivo in audit. Rerun stress cambia percorso/non-fill, non semplice sottrazione.
- [ ] Parità downstream v1/v2: stessi input causali producono feature, decisioni, fill, curve e hash equivalenti; ripetere al gate Task12. Preflight al limite conservativo e controllo prima di ogni partial includono riserve pending senza doppio conteggio.
- [ ] Mirati: execution/simulator/costs/quote_units/strategies/features + lab_simulator e intraday_boundaries; gate comune e review. Nessuna simulazione paper/live Alpaca.

**Commit:** `feat: replay conservative intraday fills and timed exits`

## Task 8 — Harness, metriche dipendenti e confronto ablation

**Branch:** `investedge/sp3-task-8`; **Base:** origin/investedge/sp3-task-7.
**Dipendenze:** Task7 FATTO.
**File nuovi:** `backend/app/intraday_research/harness.py`, `statistics.py`; `tests/test_intraday_research_harness.py`, `tests/test_intraday_research_statistics.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `registry.py`, `tests/intraday_research_fixtures.py`.

- [ ] RED: etichetta H confusa col rendimento stop, exit mancante→0/eliminata, fill trattati come trade indipendenti, Sharpe di minuti annualizzato daily, giorni flat/cost-only spariscono, IC/bucket inventati su campione sparso; bootstrap per trade/listing perde dipendenza, trial falliti rimossi da M.
- [ ] Implementare harness §9, curve/metriche/drawdown/CVaR/concentrazione/fill rate, confronto paired tecnica/news e cassa; benchmark passivo mercato open+45min/peso10%/H15-30 e stessi filtri esecutivi/costi/refs, senza stop/target tecnico (diagnosi, non griglia selezionabile). Bootstrap §11 con seed/blocchi/repliche/molteplicità frozen e sensitivity1/10; statistiche pure SP1 read-only.
- [ ] GREEN: P&L/quantili a mano, repliche congiunte e seed stabili fra chunk/ordini, autocorrelazione sintetica, missing/nonfinite/replica senza trade, medie ponderate/non ponderate/code/concentrazione. Replay identico→risultati/hash identici; DEMO non aumenta M REAL, DSR_INCOMPLETE non inventa V.
- [ ] Test statistico: round-trip netti di esecuzione con lower bound positivo ma curva giornaliera dopo ricorrenti con lower bound≤0 non passa; flat/cost-only days entrano nelle repliche e nella media portafoglio.
- [ ] Mirati: harness/statistics/simulator/registry, lab_stats/harness/evidence regressioni; gate comune e review statistica indipendente.

**Commit:** `feat: measure intraday ablations with dependent uncertainty`

## Task 9 — Walk-forward IS-only, purge/embargo e holdout sealed

**Branch:** `investedge/sp3-task-9`; **Base:** origin/investedge/sp3-task-8.
**Dipendenze:** Task8 FATTO.
**File nuovi:** `backend/app/intraday_research/walk_forward.py`, `holdout.py`; `tests/test_intraday_research_walk_forward.py`, `tests/test_intraday_research_holdout.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `datasets.py`, `registry.py`, `tests/intraday_research_fixtures.py`.

- [ ] RED: OOS futuro/split/gap/prima barra cambia Sharpe/scelte IS; etichette/pending oltre cutoff non purged; reset capitale fra OOS, parametri cambiati a posizione aperta, embargo di minuti anziché seduta; leak holdout da preview/reader/benchmark/job, apertura implicita/ripetuta/tuning dopo OPENED.
- [ ] Implementare calendario446sedute+warm-up, quattro fold126/63, embarghi espliciti, intervalli reali e bound ex ante, selezione solo R0/R1 per policy e astensione se inammissibili; OOS continuo; IS finale ultime126 dichiarato, SEALED→OPENED batch unico dopo freeze del manifesto autorizzato.
- [ ] Sharpe/minimi/vincoli di selezione solo nei126giorni IS correnti, prefisso precedente solo warm-up/stato. Test in cui miglior Sharpe dell'intero prefisso differisce da miglior Sharpe rollingIS, scelta determinata soltanto dal secondo.
- [ ] Seal limitata al workflow SP3, nessuna promessa contro API dati SP2b/filesystem. Registro CONTAMINATED per ispezione esterna, anche da Data Center/news/snapshot/reader diretto; dichiarazione d'integrità del responsabile necessaria, assente→INSUFFICIENTE/contaminata→G2 bloccato. Prove con refs ottenuti dai reader SP2b, senza modificarne i contratti; GET non scrive dichiarazioni.
- [ ] GREEN: proprietà future append/change/remove su tutte le finestre/benchmark/attestazioni/corporate, nessun calendario/NO_FEATURES deciso dal futuro; purge esempi sovrapposti e exit irrisolte; ledger continuo, minimi trade/sedute attive/pareggi; access guard holdout per ruolo/namespace ed errore/crash che non lo richiude.
- [ ] Mirati: walk_forward/holdout/registry/datasets/harness, SP1R1 lab_walk_forward/backtest invariati; gate comune e review causalità/metodo. Dati sintetici verificano protocollo, nessun esperimento REAL avviato.

**Commit:** `feat: isolate intraday selection and sealed holdout evaluation`

## Task 10 — Evidenze immutabili, job e API di ricerca

**Branch:** `investedge/sp3-task-10`; **Base:** origin/investedge/sp3-task-9.
**Dipendenze:** Task9 FATTO.
**File nuovi:** `backend/app/intraday_research/evidence.py`, `handlers.py`; `backend/app/api/intraday_research_routes.py`, `backend/app/models/intraday_research.py`; `tests/test_intraday_research_evidence.py`, `tests/test_intraday_research_api.py`, `tests/test_intraday_research_jobs.py`.
**File modificati:** `backend/app/database.py`, `backend/app/lab/jobs.py`, `backend/app/main.py`, `backend/app/models/__init__.py`; `tests/test_lab_jobs.py`, `tests/test_database.py`, `tests/test_api.py`.

- [ ] RED: G2 PASS con DEMO/storico corrente/G1 insufficiente, costo/size UNKNOWN, stress/metriche/minimi mancanti; trial cancel perso o report parziale pubblicato; migrazione CHECK kind perde job/FK; GET fa DML/rete, 202 sincrono, errore raw/echo segreti dopo rotazione; holdout aperto senza manifesto/accesso autorizzato.
- [ ] Implementare gate §11 e ragioni per policy/H, report config/dataset/costi/curve/fill/limiti versionati; checkpoint e pubblicazione atomica. Kind INTRADAY_RESEARCH/HOLDOUT e migrazione CHECK col metodo SP2b compatibile. API §12, input/namespace bounded, guardia sensibile anche su output durabili; niente provider/ordini.
- [ ] GREEN: nessun G2 non consentito, ogni soglia FAIL/INSUFFICIENTE al confine, tutti stress e condizioni congiunte, immutabilità/cancel/crash/restart; migrazione kind/stati storici/indici/view/sequence/PRAGMA/rollback; HTTP422/404/409/202 e GET read-only, preview holdout sealed senza leak.
- [ ] Contaminazione holdout e dichiarazione assente impediscono G2 anche con P&L positivo; endpoint POST registra esplicitamente integrità/contaminazione sul manifesto, nessun reset a SEALED. API generiche SP2b non sono garanzia di isolamento globale.
- [ ] Mirati: evidence/API/jobs/holdout/registry + intraday_API/jobs/lab_jobs/database/API; schemi generici conservati, gate comune e review. Su fixture tecnicamente positiva il badge resta non economico.

**Commit:** `feat: expose immutable intraday research evidence jobs`

## Task 11 — Consultazione minima SP3 nel laboratorio

**Branch:** `investedge/sp3-task-11`; **Base:** origin/investedge/sp3-task-10.
**Dipendenze:** Task10 FATTO.
**File nuovi:** `frontend/src/components/IntradayResearchPanel.tsx`, `IntradayResearchPanel.test.tsx` nel medesimo folder.
**File modificati:** `frontend/src/lib/api.ts`, `frontend/src/pages/BacktestPage.tsx`, `frontend/src/pages/BacktestPage.test.tsx`.

- [ ] RED: JobOut letto come sincrono, ns/source ID in Number, gate daily applicato a G2, seed etichettato REAL, metrica null→0, news/costi mancanti nascosti, cancel/risposta obsoleta dopo cambio namespace, holdout aperto da GET/default.
- [ ] UI minima §12: manifesto/dataset/regole/famiglia/arm/H, registry/costi/stress/campione/gate/ragioni e stato sealed; apertura holdout batch esplicita sul manifesto congelato con testo informativo, mai ordine. Serializer esatto esteso alle nuove route, jobs.ts invariato, abort/owner/polling/terminali; tab SP1 invariati.
- [ ] GREEN: fixture API locali per tutti i terminali, data_mode/grade/namespace/cost_profile, 15/30 dal fill, input ID/hash/int64, campione insufficiente/news UNKNOWN/COVERED_ZERO; ragioni leggibili, tastiera a375/1440 e nessun overflow.
- [ ] Suite frontend/build/install offline/auditHC0, suite backend e gate comune; browser offline con API in RAM/origini esterne bloccate, zero DB/rete provider. Nessun CSS/shared style/dipendenza modificati; review API/UX circoscritta.

**Commit:** `feat: inspect intraday research evidence in the lab`

## Task 12 — Audit tecnico e stato economico del gate intraday

**Branch:** `investedge/sp3-task-12`; **Base:** origin/investedge/sp3-task-11.
**Dipendenze:** Task11 FATTO. Valutazione economica richiede separatamente dataset/budget REAL forniti e G1_DATA READY; non sono disponibili oggi.
**File nuovi:** `backend/scripts/intraday_research_smoke.py`, `tests/test_intraday_research_smoke.py`, `docs/reports/<data>-sp3-intraday-strategy-gate.md` (data della consegna).
**File modificati:** `README.md`; correzioni TDD soltanto nei file Task1–11 SP3 sopra; spec/piano/programma per evidenze e stato.

- [ ] Smoke end-to-end20config/10policy su fixture DEMO offline, valori noti, novità/revisioni/size/daily/holding/stress/purge/holdout/cancel, output immutabili dopo revisioni future. Scratch nuovo/xb, guard target esistente/data folder e zero socket; mini-fixture funzionale non sostituisce campione G2.
- [ ] Audit cumulativo Git/allowlist/contratti SP1/SP2b/migrazioni/risorse/segreti/causalità; mapping test per ogni criterio della spec e output freschi. Tre review read-only causalità/esecuzione/statistica e re-review finale dei fix, nessun Critical/Important residuo.
- [ ] Suite backend/frontend, Ruff/pip, install/build offline/auditHC0 e scope/scan/diff; profilo sostenibilità Task2 conservato, smoke ripetuto se cambia il reader. Report G2_TECH PASS/FAIL e G1/G2 economici con motivazioni separate.
- [ ] Se G1_DATA manca: G2 INSUFFICIENTE, nessun trial economico/holdout REAL aperto, Task12 tecnico può essere FATTO; niente attesa/cattura live automatica. Se dataset READY e incarico economico esplicito: congelare manifest/versioni costi/limiti/date e valutare offline, poi applicare gate senza tuning/estensioni. Apertura holdout REAL esplicita per manifesto; approvazione generica del piano non consuma un holdout sconosciuto.
- [ ] Consegna report tecnico/stato, push/gate e FF autorizzato; SP3 IN CORSO per addendum, G2 non PASS blocca SP6a. Se G2 PASS: prossimo spec/piano SP6a prima di codice/ordini con capitale/rischio/runtime scelti dall'utente. Se nessuna policy PASS, nessun paper; ulteriori ricerche richiedono nuova preregistrazione/holdout.

**Commit:** `chore: verify SP3 intraday research gate`

## Task 13 — Addendum SP3 dopo il percorso prioritario

**Branch/base:** da fissare nell'addendum sul remoto verificato al ritorno da SP6a e completamento restante SP2b; nessun branch esecutivo inventato oggi.
**Dipendenze:** gate intraday SP3 + SP6a completati secondo programma + prerequisiti backlog SP2b pertinenti FATTI; approvazione addendum prima del codice successivo.
**File nuovi:** spec/piano addendum SP3 datati alla futura consegna, report documentale di review.
**File modificati:** `PROGRAMMA-OPERATIVO.md`, questo piano per collegamenti/stato, spec SP3 solo per stato/rinvii.

- [ ] Definire task/allowlist/test per weekly/monthly/altri mercati/pesi/fondamentali/challenger, con dati PIT disponibili e nuove validazioni; nessuna promozione ereditata dall'intraday.
- [ ] Review/check documentali/commit/push/FF secondo autorizzazione applicabile e proposta per approvazione; parte restante SP3 non FATTA finché il gate addendum non è verificato.

**Commit:** `docs: propose remaining SP3 signal work` (da confermare nel futuro addendum con branch/base/allowlist concreti).

## Copertura della spec e prossimo passo

| Spec | Task responsabile |
|---|---|
| §1–2 confini e compatibilità | 0,1,4,10,12 |
| §3.1 timeline-only/v2/bundle e risorse | 1–2,12 |
| §3.2 conservazione/retention | 1–2; addendum distinto per eventuale archiviazione fisica |
| §3.3 quote attestate | 3,7,10,12 |
| §3.4 daily PIT / §4 indicatori e filtri | 4,12 |
| §3.5 G1 e decision eligibility | 2,4,10,12 |
| §5 setup e §7 ablation | 5,8–9,12 |
| §6 fill/rischio/holding | 7–9,12 |
| §8 costi/stress | 6–10,12 |
| §9 registry/harness | 1,8–10,12 |
| §10 IS/purge/embargo/holdout | 9–10,12 |
| §11 minimi/statistica/promozione | 8–10,12 |
| §12 persistenza/API/UI | 1,10–11 |
| §13 verifica/approvazione/backlog | ogni task,0,12–13 |

**Prossimo:** Approvazione spec/piano SP3 dopo consegna documentale Task0. Poi, solo su approvazione, Task1 da origin/investedge/sp3-task-0 verificato. Non eseguire SP2b Task13 adesso. G1_DATA INSUFFICIENTE rimane prerequisito aperto per economia/SP6a; nessuna cattura live o ordine in questa proposta.
