# SP1 — Laboratorio di verità: verifica finale

Data: 2026-10-10. Owner: Codex. Stato: **VERIFICATO — gate finale SP1 superato e merge fast-forward su main confermato/verificato**.

## Scope e base

Base cumulativa `origin/investedge/sp1-task-0` = `53fe614625fdd63277464a770f8d8c105fde894f`.
Base Task 16 `origin/investedge/sp1-task-15` = `e4481ccac33b0078ff844667804b8a95fd5e5f63`.
Branch di consegna: `investedge/sp1-task-16`, pubblicato immediatamente come lock alla base verificata.
Commit Task 16 pubblicato: `d9a43eee2f35fcda558a1b8d58bacc08a4cd8994`, registrato da questo lavoro successivo. Gate remoto branch e worktree pulito verificati alla consegna.

SP1 copre pipeline causale D/W/M, score unico, serie/segmenti/FX, cache incrementale, job,
simulatore EUR con costi TR, benchmark congelato, walk-forward, tentativi/DSR,
harness e report, ML condiviso, Backtest/Evidenza/badge e training su job.
Task 16 aggiunge smoke offline, audit cumulativo, README e questo report; corregge i rilievi finali nei soli file già SP1.

Il checkout originale è rimasto al Task 6 `96f7299a4aaef1c2074ed1f2afeae2ffbf5cf27d`.
Si è lavorato nel worktree gestito `intraday-program`. Nessun accesso al database reale dell'utente.
Merge confermato dall'utente il 2026-10-10: ascendenza main `a23aa62` -> Task 16 verificata, push fast-forward non forzato e main remoto uguale a `d9a43eee2f35fcda558a1b8d58bacc08a4cd8994`. La catena finale ha 22 commit lineari dopo Task 0, zero merge commit.

## Catena e perimetro

Prima del commit Task 16: **21 commit lineari**, ciascun parent coincide con il precedente, zero merge;
20 messaggi previsti più checkpoint Task 13 documentato. **90 file unici** fino al Task 15.

| Task | Commit pubblicato | File |
|---|---|---:|
| 1 | a115dab | 5 |
| 2 | 90b49ab | 7 |
| 3 | b76fff5 | 5 |
| 4 | 86d6f73 | 9 |
| 5 | 0bd6c0e | 8 |
| 6 | 96f7299 | 6 |
| 7 | bcd7179 | 16 |
| 8 | 346596a | 15 |
| 9 | c0f7bc2 | 9 |
| 10 | a23aa62 | 12 |
| 11 | c19c8d8 | 15 |
| P — priorità Alpaca/intraday | 1ae5a9e | 4 |
| R1 — causalità WFO | 7f0a790 | 6 |
| R2 — snapshot benchmark/FX | caf388c | 8 |
| R3 — contratti frontend | 75cef42 | 9 |
| R4 — dipendenze/stili | 4f8f280 | 7 |
| 12 | 23d9b86 | 14 |
| 13 checkpoint | 2f34a43 | 11 |
| 13 completamento | 835e83d | 3 |
| 14 | 14cacc1 | 6 |
| 15 | e4481cc | 15 |
| 16 | branch investedge/sp1-task-16 | smoke/report/README/registro e correzioni review |

Confronto commit per commit con le allowlist del piano: nessuna deviazione non documentata.
Tre estensioni storiche motivate nel programma: Task 7 `news_engine.py` (news solo informative e score zero),
Task 8 `tests/test_api.py` (lifespan senza DB utente), Task 11 `models/__init__.py` (export dei contratti nuovi).
Task 13 estende `tests/test_news_providers.py` per autorizzazione esplicita dell'utente.
Deroga audit R3 registrata, superata dal gate R4. Il checkpoint 13 non riscrive la storia.

Task 16 modifica soltanto i file nuovi/autorizzati e file già SP1: database e test, jobs e test,
series e test, test WFO/ML/segnali, spec (stato e correzioni della review), piano e programma.
Le modifiche alla spec risolvono la nota R3 obsoleta e documentano base per barra/cache legacy.

## Prestazioni offline

Comando: `python -m backend.scripts.lab_perf_smoke`, con `INVESTEDGE_DB_PATH` assoluto
su file nuovo nello scratch. Python 3.14.7, ambiente locale Windows; nessuna dipendenza nuova.

Fixture **SYNTHETIC_REAL**: 50 asset EUR × 1500 daily; seed fisso per asset.
La marcatura REAL esercita il contratto software e non trasforma prezzi sintetici in dati di mercato.
Materializzazione D/W/M: 75.000 / 15.000 / 3.450 righe, **93.450 totali**.
Incrementale: una nuova daily di un solo asset, una riga inserita.
Job EVIDENCE con handler di produzione ed executor inline: 2019-09-30 → 2024-09-30,
score D, orizzonti 1/5/21; SUCCEEDED, tre report NON_VALIDATO, nove trial.

| Operazione | Tempo osservato | Obiettivo indicativo | Esito |
|---|---:|---:|---|
| features_daily completa, D/W/M | 9,0016 s | ≤ 60 s | raggiunto |
| una barra di un asset | 0,0410 s | ≤ 5 s | raggiunto |
| job Evidenza su cinque anni | 21,1231 s | ≤ 120 s | raggiunto |

Sono misure di questa macchina, non SLA. I tempi includono il lavoro concreto del motore;
il job è misurato con cache già calcolata, coerentemente con la sequenza prevista.
Rete bloccata su risoluzione/connessione socket: **0 tentativi**.
Lo script rifiuta target esistenti, relativi o `investedge.db`; riserva il file con apertura esclusiva.
Cinque test di contratto nello scratch: RED per modulo assente, GREEN **5/5**.

## Review e regressioni

Review cumulativa indipendente read-only, workflow
[`requesting-code-review`](C:/Users/izzod/.claude/superpowers/skills/requesting-code-review/SKILL.md),
con verifica separata metodologia, esecuzione e storia; ulteriore reviewer con contesto nuovo per il delta finale.

Quattro aree Important corrette, con RED osservato prima del fix e GREEN/rereview:

| Finding | Correzione | Prova |
|---|---|---|
| REPLACE aggirava append-only dei trial | trigger BEFORE INSERT che rifiuta ID già presente | `test_lab_trials_are_append_only`, riga invariata |
| stop/start poteva duplicare il worker o abbandonare la coda | riferimento conservato, recovery salta worker vivo; decisione d'uscita e start sotto stesso lock | `test_stop_start_keeps_one_worker_and_does_not_interrupt_live_job`, `test_restart_after_worker_observes_stop_drains_queue` |
| provider OOS cambiava retroattivamente rettifica/split IS | fattore per barra; nuovo segmento al cambio di base; split solo tra UNKNOWN confrontabili | `test_future_provider_change_cannot_rewrite_past_features`, `test_engine_is_selection_ignores_future_provider[replace/append]` |
| cache scoring legacy veniva mostrata come score corrente | invalidati soltanto source=scoring_engine e data_mode NULL; ricalcolo esplicito | `test_migration_invalidates_unclassified_legacy_score[100/320]`, migrazioni rebuild/alter |

La migrazione invalida segnali derivati, senza classificare l'origine e senza ricalcolo automatico.
Segnali v1 classificati e record indipendenti restano conservati. L'aspettativa del vecchio test di migrazione
che richiedeva la cache obsoleta è stata adeguata dopo la prima suite (1009 verdi, una failure su quell'aspettativa). Una sentinella con source manuale e score/rationale intatti è verificata separatamente: legacy-preservation.xml, 1 test verde.

Chiusa anche la lacuna di prova dello score: `test_ml_row_equals_features_daily_row`
confronta direttamente Backtest/dataset/store a ogni data e UI/Backtest/store/previsione ML sull'ultima.
Le finestre del nuovo test WFO richiedono Sharpe IS definiti: confronti non vacui.
Regressioni finali mirate: **11 passate**; suite mirata precedente su cinque moduli: **149 passate**.
README latest corretto ai parametri effettivi `signal_name` e `timeframe`.

Esito finale review: **PASS, nessun Critical/Important aperto**.

## Dieci criteri della spec §15

Ogni test indicato appartiene alla suite offline finale, senza xfail pendenti.

| # | Criterio | Evidenza verificabile |
|---|---|---|
| 1 | score unico UI/Backtest/ML/store | `test_signal_score_equals_features_daily_latest_row`, `test_technical_analysis_serves_the_signal_score`, `test_ml_row_equals_features_daily_row`, `test_score_frame_matches_explain_row_by_row` |
| 2 | causalità, finestre, no chikou/import di calcolo | `test_feature_value_does_not_change_when_future_bars_are_added`, `test_feature_value_depends_only_on_its_declared_window`, `test_chikou_span_is_not_a_feature`, `test_module_does_not_import_technical_analysis`; nuove regressioni provider |
| 3 | contabilità manuale e fill successivo | `test_hand_computed_scenario`, `test_hand_scenario_accounting_turnover_and_exposure`, `test_no_fill_on_signal_bar` |
| 4 | verdetti predittivo/casuale/corto | `test_constructed_signal_is_validato`, `test_random_signal_is_non_validato`, `test_short_sample_is_insufficiente` |
| 5 | DSR riferimento e monotonia N | `test_dsr_hand_computed_reference`, `test_dsr_decreases_when_more_trials_are_counted` |
| 6 | IS indipendente OOS, benchmark/FX congelati | `test_is_results_ignore_oos_segment_changes`, `test_engine_oos_warmup_cannot_change_is_eligibility_or_calendar`; regressioni snapshot/revisioni in test_lab_backtest e WFO |
| 7 | DEMO senza trial/verdetti, append-only | `test_demo_walk_forward_has_no_trials_and_no_dsr`, `test_evidence_refuses_demo_only_universe`, `test_reports_are_immutable`, `test_saved_reports_survive_source_revision`, `test_lab_trials_are_append_only` |
| 8 | job 202/cancel/recovery | test API e `test_recover_interrupted_marks_running_jobs`, nuove regressioni restart |
| 9 | incrementale = completo e tempi | `test_incremental_equals_full_recompute`; smoke misurato sopra |
| 10 | suite/lint/build/audit/review/rete | gate e file di prova sotto; zero Critical/Important aperti al codice |

## Gate e prove

| Controllo | Risultato |
|---|---|
| pytest integrale finale, JUnit | **1010/1010 PASS**, zero failure/error/skip, 359,34 s |
| rete pytest | **0 chiamate esterne inattese**; 2 sonde intenzionali della guardia, entrambe bloccate |
| Ruff backend/scripts/tests | PASS |
| pip check | PASS, nessun requisito rotto |
| npm ci --offline --no-audit --no-fund | PASS, lock invariato |
| npm run test:run | **134/134 PASS**, zero failure |
| npm run build (tsc + Vite) | PASS |
| npm audit --audit-level=high | exit 0; **0 high / 0 critical / 0 moderate**, 1 low @babel/core dev |
| git diff --check | PASS |
| secret scan cumulativo finale | PASS; 3 espressioni classificate, 0 segreti letterali inattesi |

Test e smoke usano solo fixture locali/sintetiche e DB temporanei. L'audit npm consulta il registry
per advisory aggiornati, separatamente dai test offline. Nessuna chiamata live ai provider.

Comandi backend: `python -m pytest -o addopts= -q -p no:cacheprovider --junitxml=...`,
`python -m ruff check backend scripts tests --no-cache`, `python -m pip check`.
Un wrapper esterno nello scratch conta le chiamate negate dalla guardia del Task 1 e distingue
le due sonde intenzionali di test_test_infrastructure dalle chiamate inattese.

Prove locali non versionate:
`C:/Users/izzod/.codex/visualizations/2026/10/10/01a12426-1877-7ea2-86f8-9a7c6a04e505/task16-verification`.
File principali: `perf-final.jsonl`, `backend-full-final.xml/log`, `targeted-final.xml`,
`review-regressions.xml`, `legacy-preservation.xml`, `frontend-full.json`, log ci/build e `npm-audit.json`.
Il solo report riassuntivo è versionato; fixture, DB, modelli e node_modules restano fuori Git.

## Audit segreti finale

Stesso pattern PCRE2, sentinelle e self-test della Fase 2: self-test PASS (5 valori, 6 match,
5 inattesi previsti). Scope finale: **93 file cumulativi, 92 scansionati** escluso il lockfile.
Tre candidati classificati individualmente sulla sorgente:

| File e riga | Classificazione |
|---|---|
| tests/test_api.py:935 | espressione preview_response.json(), nessun valore letterale |
| tests/test_api.py:5497 | chiamata _post_trade_republic(...), nessun valore letterale |
| tests/test_api.py:5703 | attributo preview.confirmation_token, nessun valore letterale |

**0 segreti letterali inattesi, 0 sentinelle, 0 placeholder**. Controllo aggiuntivo sulle 16.380
righe aggiunte nei 21 commit precedenti: zero candidati. Il pattern non è stato attenuato per i falsi positivi.
Task 16: **16 file**, tutti autorizzati o già SP1 per correzioni della review.
Scan finale del report/delta e chiusura delle note PASS prima del commit.

## Rischi residui e prossimo gate

- Universo attivo attuale, con survivorship bias; snapshot point-in-time in SP2b.
- Base UNKNOWN, dividendi non verificati e guardia split euristica. Un cambio di base interrompe il segmento;
  gli eventi societari affidabili restano al gate dati.
- FX as-of giornaliero, scadenza massima e barre escluse: nessuna interpolazione inventata.
- Storico corto (incluso limite CoinGecko dichiarato nella spec) e warm-up W/M spesso insufficienti.
- Costi TR ipotizzati, spread diagnostico long-short e calendari misti; prestazioni reali non provate.
- N conta configurazioni distinte con Sharpe definito, prendendo l'ultimo valore nella famiglia;
  il DSR usa la formula approvata senza una correzione aggiuntiva della dipendenza seriale OOS.
- Coda con un worker, cancel cooperativo, recupero manuale dei job interrotti. Cache feature può essere
  aggiornata prima di un annullamento; run/trial/report annullati non sono pubblicati.
- Fiscalità dei backtest semplificata, senza riporto delle perdite tra anni.
- Feature RSI ricorsive troncate e costo Supertrend dichiarati; test e smoke proteggono i contratti attuali.
- ML sperimentale: target/metriche/split economici restano SP4. Vecchi modelli richiedono riaddestramento.
- Warning preesistenti: due deprecazioni Starlette, chunk Vite >500 kB, advisory low dev @babel/core.
  Nessuna deroga high/critical nel gate finale.

SP1 verifica il software e produce evidenza sui dati configurati; non dimostra redditività
né valida holding intraday di 15–30 minuti. Merge SP1 eseguito. Prossimo passo: approvazione della
proposta spec/piano SP2b con gate dati/news intraday; seguono strategie SP3 e Alpaca paper senza leva.
Trading reale e leva restano ai gate e alle azioni esplicite previsti nel programma.
