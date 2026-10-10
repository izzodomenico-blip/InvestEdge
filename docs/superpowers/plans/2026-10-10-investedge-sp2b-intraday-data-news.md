# InvestEdge — piano SP2b: dati e news intraday

**Stato:** proposta 2026-10-10 da approvare prima del Task 1. Task 0 solo documenti; nessun codice intraday implementato.
**Spec:** ../specs/2026-10-10-investedge-sp2b-intraday-data-news-design.md.
**Goal:** archivio versionato e replay condiviso per dati/news USA 1/5/15 minuti, idoneità point-in-time esplicita per SP3 e Alpaca paper successivo.
**Architettura:** backend/app/intraday separato dal laboratorio daily; adapter ufficiali e trasporto governato; SQLite additivo; collector bounded distinto dal FIFO lab; API /intraday e aggiunte alle viste correnti.
**Stack:** Python 3.14, FastAPI/Pydantic, SQLite, httpx, pandas/numpy, pytest/Ruff; React/TypeScript/Vitest. Una dipendenza WebSocket diretta può essere aggiunta solo nel Task 7 con compatibilità e motivazione documentate; niente SDK di trading.

## Protocollo vincolante

- AGENTS.md: primo task NON INIZIATO con tutte le dipendenze FATTE; root unico writer, review read-only; TDD RED (causa prevista) -> minimo codice -> GREEN -> review.
- Test solo offline, fixture locali/sintetiche, MockTransport/socket factory fake e clock fisso; DB temporanei tramite INVESTEDGE_DB_PATH. Non aprire data/investedge.db, .env o credenziali per i test.
- SP1 resta D/W/M; nessuna nuova strategia, feature predittiva, ordine, leva, abbonamento o runtime hosted in questo piano.
- Ogni task autorizza solo i file elencati più questo piano e PROGRAMMA-OPERATIVO.md per la chiusura. La spec è modificabile solo per correggere un'ambiguità senza cambiare decisioni approvate, con evidenza; decisioni materiali nuove si presentano prima del codice dipendente.
- Branch numerici investedge/sp2b-task-N. Task 0 da origin/main verificato d9a43eee2f35fcda558a1b8d58bacc08a4cd8994; Task 1 da origin/investedge/sp2b-task-0, Task N da origin/investedge/sp2b-task-(N-1). Pubblicare subito lock con git push -u origin HEAD.
- Prima del lock: git fetch origin, status pulito, SHA base locale == git ls-remote della base. Divergenza -> chiarimento, niente reset/rebase/force.
- Ogni task: test mirati, suite backend completa offline con JUnit, Ruff, pip check, git diff --check; task UI anche suite frontend/build offline e audit --audit-level=high (advisory consultati separatamente). Non dichiarare PASS dalle prove del task precedente.
- Review indipendente senza Critical/Important aperti prima del commit. Secret scan con pattern Fase 2 + classificazione dei candidati; sentinelle generate nel test e non salvate in fixture.
- Chiusura nello stesso commit: checkbox, riga FATTO con test/data/owner, SHA del precedente e Prossimo passo. Un commit per task, messaggio esatto sotto; checkpoint pubblicato e documentato se interruzione.
- Push solo branch task e gate SHA remoto == HEAD, worktree pulito. Merge fast-forward ai gate tecnici solo su richiesta esplicita. Il gate parziale non marca tutto SP2b VERIFICATO.
- G1_TECH e G1_DATA distinti. Task 12 può chiudere il software con G1_DATA INSUFFICIENTE se mancano capture reale/diritti; G2/promozione/paper restano bloccati da quel dato. Nessuna raccolta live in questo piano senza richiesta e configurazione utente.

Comandi (PowerShell, dalla radice del worktree; scratch temporaneo nuovo e flag live disabilitati):

    & '.\backend\.venv\Scripts\python.exe' -m pytest <moduli-del-task> -o addopts= -q -p no:cacheprovider --junitxml=<scratch>/targeted.xml
    & '.\backend\.venv\Scripts\python.exe' -m pytest -o addopts= -q -p no:cacheprovider --junitxml=<scratch>/full.xml
    & '.\backend\.venv\Scripts\python.exe' -m ruff check backend scripts tests --no-cache
    & '.\backend\.venv\Scripts\python.exe' -m pip check
    npm --prefix frontend ci --offline --no-audit --no-fund
    npm --prefix frontend run test:run
    npm --prefix frontend run build
    npm --prefix frontend audit --audit-level=high
    git diff --check

## Task 0 — Merge SP1, spec e piano proposti

**Branch:** investedge/sp2b-task-0; **Base:** origin/main al Task 16 SP1.
**Scope attuale:** PROGRAMMA-OPERATIVO.md, spec/piano/report SP1 (solo stato merge), questa spec e questo piano.
**Dipendenze:** merge SP1 esplicitamente confermato il 2026-10-10.
- [x] Verificare remoto e ascendenza; fast-forward main a d9a43eee2f35fcda558a1b8d58bacc08a4cd8994, gate remoto uguale.
- [x] Ricostruire confini esistenti e contratti ufficiali, scrivere proposta spec/piano e backlog separato.
- [x] Due review documentali indipendenti PASS senza Critical/Important residui; verifica Python offline 12/12 (scope/link/integrità/sequenza/allowlist/bootstrap/causalità/policy/stato), diff check PASS.
- [x] Commit, push del solo Task 0 e gate remoto SHA == HEAD; proposta consegnata all'utente per approvazione prima del Task 1.
**Commit:** docs: plan SP2b intraday data and news

## Task 1 — Contratti, schema additivo e fixture

**Branch:** investedge/sp2b-task-1; **Base:** origin/investedge/sp2b-task-0.
**Dipendenze:** Task 0 FATTO + approvazione esplicita spec/piano.
**Files create:** backend/app/intraday/__init__.py, backend/app/intraday/contracts.py, tests/intraday_fixtures.py, tests/test_intraday_contracts.py, tests/test_intraday_schema.py.
**Files modify:** backend/app/database.py, backend/app/config.py, .env.example, backend/.env.example, tests/conftest.py, tests/test_database.py, tests/test_config.py.
**Produces:** EventEnvelope versionato (tempi UTC ns, kind, profilo, provenance/grade, modalità, payload hash, admission), FeedProfile/QualityPolicy, reason codes; tabelle della spec §8 con CHECK/indici/trigger e metadati operativi collector. Freeze policy iniziale §11.
- [ ] RED: nanosecondi distinti, timestamp invalidi/futuri, modalità incompatibili, capture log append-only/tabella assente e UPDATE/DELETE/REPLACE bloccati, FK RESTRICT, JSON non finito.
- [ ] Implementare minimi contratti/schema. Clock/server skew esplicito; timestamp ricevuto prima della coda; nessun segreto nel profilo. Default ENABLE_ALPACA_DATA=false, collector disabilitato, cap/quote disco/budget attestati prima di live; nomi config documentati, chiavi vuote.
- [ ] GREEN: DB nuovo e migrazione da fixture legacy, rerun idempotente/backup fallito, preservazione dati/cache SP1; guardia rete esistente invariata.
- [ ] Review e chiusura con suite/lint/protocollo.
**Commit:** feat: define versioned intraday data contracts

## Task 2 — Trasporto Alpaca, capacità e budget sicuri

**Branch:** investedge/sp2b-task-2; **Base:** origin/investedge/sp2b-task-1.
**Files create:** backend/app/data_providers/alpaca_market.py, backend/app/intraday/profiles.py, tests/test_alpaca_market_provider.py.
**Files modify:** backend/app/data_providers/transport.py, backend/app/data_providers/base.py, backend/app/data_providers/provider_registry.py, backend/app/data_providers/__init__.py, backend/app/services/provider_budget_service.py, backend/app/models/market_data.py, backend/app/config.py, tests/test_provider_budget.py, tests/test_config.py.
**Produces:** bounded REST client per host/path GET della spec; profilo pubblico/capacità e scope cache separati per feed/diritti; policy budget del singolo account.
- [ ] RED: i due header Alpaca e response echo sentinella non protetti, missing config prima di rete, feed implicito/fallback, cache di profilo differente, host/redirect/query vietati; 401/403/429/retry.
- [ ] Implementare riconoscimento esplicito dei due segreti prima di log/cache/risposta; payload whitelist, limiti bytes/timeout, retry fisici governati. Nessuna fingerprint del segreto/account personale.
- [ ] GREEN su MockTransport: header auth solo in memoria, params feed/currency/adjustment/asof espliciti, budget condiviso per capacità quando previsto; caps configurati mai elevati da un errore.
- [ ] Gate completo e review; nessuna chiamata Alpaca live né registrazione credenziali.
**Commit:** feat: add governed Alpaca market data transport

## Task 3 — Identità Alpaca, calendario e universo prospettico

**Branch:** investedge/sp2b-task-3; **Base:** origin/investedge/sp2b-task-2.
**Files create:** backend/app/data_providers/alpaca_metadata.py, backend/app/intraday/identity.py, backend/app/intraday/calendar.py, backend/app/intraday/universe.py, tests/test_intraday_identity.py, tests/test_us_calendar.py, tests/test_historical_universe.py.
**Files modify:** backend/app/services/instrument_service.py, backend/app/models/schemas.py, backend/app/models/__init__.py, tests/test_instrument_catalog.py, tests/test_instrument_resolution.py.
**Produces:** metadata GET paper /assets,/calendar con servizio bounded di bootstrap esposto nel Task 10; preview/apply espliciti della conferma mapping Alpaca versionata, read_identity_as_of, session_as_of e universo congelato prima della seduta.
- [ ] RED: UUID diverso per ticker riusato, mapping ambiguo/non confermato, delisting/rename futuri che modificano universo passato; legacy non risolto resta escluso.
- [ ] Implementare as-of su validità e known_at; nessuna attestazione storica inventata dalla risposta corrente /assets. UNKNOWN leva/inverse ETF escluso dal primo universo operativo.
- [ ] GREEN: DST USA/Europa non coincidenti, holiday/half-day, calendar missing/future version, gruppi ancorati all'open; universo contemporaneo/pit distinto da retrospettivo.
- [ ] Review e gate, I3 legacy conservato fuori scope.
**Commit:** feat: snapshot intraday identities sessions and universe

## Task 4 — Archivio barre/quote e aggregazioni complete

**Branch:** investedge/sp2b-task-4; **Base:** origin/investedge/sp2b-task-3.
**Files create:** backend/app/intraday/store.py, backend/app/intraday/aggregate.py, tests/test_intraday_store.py, tests/test_intraday_aggregate.py, tests/fixtures/market_data/alpaca_bars_pages.json, tests/fixtures/market_data/alpaca_quotes_pages.json.
**Files modify:** backend/app/data_providers/alpaca_market.py, tests/test_alpaca_market_provider.py, tests/test_market_data_observations.py.
**Produces:** persist(envelopes) e read_as_of; backfill paginato/chunk idempotente; 1/5/15 minuti closed/as-of.
- [ ] RED: pagina iniziale solo primo simbolo, next token loop, interruzione, timestamp ns persi, BAR sovrascritta, late/crossed/zero-size quote, revised raw bar retroattiva; ritorno A→B→A perso dalla deduplica globale del payload.
- [ ] Implementare raw USD, feed distinti, ns e payload hash; PARTIAL distinto da COMPLETE, first_received immutato, quarantine reason codes. Storico corrente RESEARCH_ONLY prima della cattura.
- [ ] GREEN: warm-up/gruppo incompleto/missing minuto, sessioni e feed separati, OHLC/VWAP attesi a mano, delayed/non NBBO dichiarati; size round lots non convertita senza attestazione.
- [ ] Regressione: minuto non proiettato in price_history/features_daily, percorso EOD invariato; suite e review.
**Commit:** feat: archive minute bars quotes and causal aggregates

## Task 5 — News versionate e mapping degli eventi

**Branch:** investedge/sp2b-task-5; **Base:** origin/investedge/sp2b-task-4.
**Files create:** backend/app/data_providers/alpaca_news.py, backend/app/intraday/news.py, tests/test_alpaca_news_provider.py, tests/test_intraday_news.py, tests/fixtures/market_data/alpaca_news_pages.json, tests/fixtures/market_data/alpaca_news_revisions.json.
**Files modify:** backend/app/data_providers/__init__.py, tests/test_news_providers.py.
**Produces:** historical news reader + decoder stream, archivio versioni, relazioni articolo/listing/evento e tassonomia fattuale v1.
- [ ] RED: testo rivisto retrodatato, updated_at fuori ordine/uguale con hash diverso, duplicate consegna, ritorno A→B→A con updated_at successivo, URL stesso per due fonti, publication assente, seed confluito in REAL, mapping ambiguo.
- [ ] Implementare articolo ID fonte/hash/versione/tre tempi, many-to-many e cluster deterministico versionato; raw HTML mai eseguito, testo consentito bounded. Licenza/retention prima del corpo, missing esplicito.
- [ ] GREEN: news/cluster futuro invarianti al cutoff, missing/stale/disabled/covered-zero distinti, categoria UNKNOWN quando prove insufficienti; niente score/sentiment predittivo.
- [ ] Preservare consultazione e sentiment legacy REAL/DEMO; non migrare retroattivamente news_items in STRICT_PIT. Gate e review.
**Commit:** feat: archive point-in-time news versions and events

## Task 6 — Corporate actions, halt e calendari eventi

**Branch:** investedge/sp2b-task-6; **Base:** origin/investedge/sp2b-task-5.
**Files create:** backend/app/data_providers/alpaca_events.py, backend/app/data_providers/official_event_calendar.py, backend/app/intraday/events.py, tests/test_intraday_events.py, tests/test_official_event_calendar.py, tests/fixtures/market_data/alpaca_corporate_actions.json, tests/fixtures/market_data/us_events_calendar.json.
**Files modify:** backend/app/intraday/contracts.py, backend/app/intraday/store.py, backend/app/intraday/aggregate.py, backend/app/intraday/identity.py, tests/test_intraday_aggregate.py.
**Produces:** versioni eventi, invalidazioni split/merger, decode STATUS/LULD, snapshot calendari BLS/Fed e import locale earnings da fonte ufficiale; validatore/importatore di checkpoint status con provenienza riscontrabile, completezza/scope/expiry, mai NORMAL automatico.
- [ ] RED: ex/process date trattata come availability, evento tardivo anticipato, split/reorganization attraversata, halt UNKNOWN inferito come resume, calendario aggiornato che muta il passato; bootstrap assente/stale/parziale, halt overnight e quotation-only scambiato per trading resume.
- [ ] Implementare known/effective separati; REST corrente non certifica il passato. Status/LULD necessari ma diritti da attestare; assenza/gap -> UNKNOWN. Checkpoint autorevole necessario al bootstrap; RSS parziale, /assets, ack e barre non provano NORMAL. Checkpoint pre-ack abilita solo CONNECTING; il handshake del Task 7 raccorda lo stato prima di LIVE. Fonte/capacità assente -> STATUS_BOOTSTRAP_UNAVAILABLE, G1_DATA non READY. No automatic adjustment dei raw.
- [ ] GREEN: report evento/quarantena, holiday/DST, ora macro/earnings sconosciuta -> intera seduta, corpo calendario deterministico da fixture/import, nessuna surprise senza consensus.
- [ ] Gate e review; corporate SSE e fondamentali/realized macro restano addendum.
**Commit:** feat: version intraday corporate and scheduled events

## Task 7 — Collector WebSocket controllato

**Branch:** investedge/sp2b-task-7; **Base:** origin/investedge/sp2b-task-6.
**Files create:** backend/app/data_providers/alpaca_stream.py, backend/app/intraday/collector.py, tests/test_alpaca_stream.py, tests/test_intraday_collector.py, tests/fixtures/market_data/alpaca_stream_replay.jsonl.
**Files modify:** backend/app/intraday/store.py, backend/app/database.py, backend/app/config.py, backend/requirements.txt, .env.example, backend/.env.example, tests/test_config.py, tests/test_provider_budget.py.
**Produces:** socket factory fake/reale, gestore esplicito bounded + lease/nonce, stato/gap e cattura durable; nessun avvio al boot.
- [ ] RED: auth frame segreto loggato, ack parziale LIVE, symbol cap senza benchmark, duplicate collector/lease scaduta, socket silence/overflow/restart, reconnect che finge continuità; NORMAL@t5/HALT@t8/ACK@t10 erroneamente LIVE.
- [ ] Implementare una dipendenza WS diretta compatibile se necessaria, dichiarata/pinnata; solo host/path dati, frame bounded/sanitizzati prima del DB, quota disco hard-stop. Client differente dal FIFO lab.
- [ ] GREEN con transcript fake: received_at prima della coda, admission dopo durabilità e backlog identico live/replay al cutoff, ack/capacità e stato LIVE coerenti, backoff, resubscription, record gap persistito; start CONNECTING con buffer durable -> checkpoint con snapshot_at interno alla cattura continua dopo ack -> applicazione di tutti gli eventi successivi -> LIVE. Checkpoint vecchio/gap richiede nuovo bootstrap e resta UNKNOWN; REST recovery non ricrea availability passata.
- [ ] Leak test entrambi i segreti in auth/error/echo; stop/start idempotenti e shutdown pulito. Gate/review, zero socket reale/ordine.
**Commit:** feat: capture Alpaca streams with explicit continuity

## Task 8 — Replay as-of unico e invarianti causali

**Branch:** investedge/sp2b-task-8; **Base:** origin/investedge/sp2b-task-7.
**Files create:** backend/app/intraday/replay.py, tests/test_intraday_replay.py, tests/test_intraday_boundaries.py.
**Files modify:** backend/app/intraday/store.py, backend/app/intraday/aggregate.py, backend/app/intraday/news.py, backend/app/intraday/events.py, tests/test_intraday_store.py.
**Produces:** stesso reducer per eventi collector e replay ordinati da disponibilità; selezione revisioni per cutoff, no «latest globale».
- [ ] RED: append/change/remove futuro in ogni tipo cambia prefisso; quote tardiva riporta mercato indietro; riordino tied timestamps non deterministico; news update futuro riclassifica ieri.
- [ ] Implementare ordine §3 e revision selection §8; conservative completeness/gap/UNKNOWN e retention first_received; rifiuto dataset mixed REAL/DEMO/feed.
- [ ] GREEN: stream transcript == replay a ogni cutoff, batch boundaries/chunk variati identici, aggregati e news/eventi/identità coerenti; test proprietà seed fisso.
- [ ] Confini AST: nessun import score-v1/daily simulator/legacy news nell'evidenza intraday, nessun provider in replay, nessun trading adapter. Gate e review.
**Commit:** feat: replay intraday data with causal as-of semantics

## Task 9 — Dataset congelati e gate di qualità

**Branch:** investedge/sp2b-task-9; **Base:** origin/investedge/sp2b-task-8.
**Files create:** backend/app/intraday/snapshots.py, backend/app/intraday/quality.py, tests/test_intraday_snapshots.py, tests/test_intraday_quality.py.
**Files modify:** backend/app/intraday/universe.py, backend/app/intraday/replay.py.
**Produces:** freeze_dataset/report con manifest e digest completo; G1_TECH distinto da G1_DATA e policy immutabile §11.
- [ ] RED: feed/news/event/calendar/universe revision non entra nel digest; GET/read fonte latest cambia un vecchio snapshot; incomplete batch pubblicato completo; token futuro nel manifest.
- [ ] Implementare riferimenti immutabili a tutte le occurrence della timeline, incluse superseded/pre-periodo e capture log append-only, e policy, timestamp cutoff e profilo; salvataggio atomico, cancellazione prima della pubblicazione; missing source errore senza fallback. A@t2/B@t8 congelate a t10 restituiscono A al cutoff t5; A→B→A mantiene tutte le availability.
- [ ] GREEN: stesso manifest/replay -> stesso digest, ogni input revision nuovo -> nuovo digest; test READY/INSUFFICIENTE/NON_IDONEO e denominatori includono gap/exclusions. Griglia fissa 1/5/15 con minimi per listing/seduta/timeframe e >0; barre complete con sole quote stale/gap news/status UNKNOWN non danno READY. Synthetic verifica funzione, mai certifica campione reale.
- [ ] SIP/quote/status/news diritti e soglie attestate, storico corrente/IEX/delayed non promossi. Tutte le esclusioni e limiti nel report. Gate e review.
**Commit:** feat: freeze intraday datasets and quality evidence

## Task 10 — Job finiti e API intraday

**Branch:** investedge/sp2b-task-10; **Base:** origin/investedge/sp2b-task-9.
**Files create:** backend/app/intraday/handlers.py, backend/app/api/intraday_routes.py, backend/app/models/intraday.py, tests/test_intraday_api.py, tests/test_intraday_jobs.py.
**Files modify:** backend/app/database.py, backend/app/main.py, backend/app/lab/jobs.py, backend/app/models/lab.py, backend/app/models/__init__.py, tests/test_lab_jobs.py, tests/test_api.py.
**Produces:** route della spec §10, quattro nuovi kind job e schema migrate compatibile; stato collector distinto dai JobOut.
- [ ] RED: kind CHECK rifiuta nuovo job, migration perde queued/running, 202 trattato sincrono, cancel pubblica snapshot parziale; start al boot/GET compie rete.
- [ ] Implementare rebuild controllato del solo CHECK lab_jobs se necessario, preservando ID/FK/risultati/deduplica e trigger/indici; test DB storico con job di tutti gli stati.
- [ ] GREEN: DB vuoto -> metadata/refresh (config/budget, senza calendario preesistente) -> preview/apply identità -> backfill RESEARCH_ONLY; start CONNECTING con ack/cattura -> checkpoint status raccordato senza gap -> LIVE/nuova capture. Precheck dei prerequisiti per le operazioni successive prima della rete, 422/404/409 sanitizzati, terminali/restart/cancel/dedup, GET senza side effect; no params segreti/URL.
- [ ] Import con flag disabilitati non avvia collector/socket; SP1 worker continua FIFO e regressioni restart conservate. Gate completo/review.
**Commit:** feat: expose bounded intraday jobs and data APIs

## Task 11 — Stato dati e news nelle viste esistenti

**Branch:** investedge/sp2b-task-11; **Base:** origin/investedge/sp2b-task-10.
**Files create:** frontend/src/pages/NewsPage.test.tsx, frontend/src/components/IntradayDataStatus.tsx, frontend/src/components/IntradayDataStatus.test.tsx.
**Files modify:** frontend/src/lib/api.ts, frontend/src/pages/DataCenterPage.tsx, frontend/src/pages/DataCenterPage.test.tsx, frontend/src/pages/NewsPage.tsx.
**Produces:** consultazione feed/capacità/gap/qualità, manifest/periodi e news versionate al cutoff; comandi espliciti bounded via API nuove, inclusi refresh iniziale metadata/calendario, preview/conferma mapping e import checkpoint status verificabile.
- [ ] RED: missing mostrato zero articoli, IEX/NON_PIT indicati READY, date versioni confuse, errore nascosto, risposta obsoleta e cancel tardivo; DB nuovo senza comando bootstrap o conferma automatica del mapping.
- [ ] Implementare tipi omologhi a Pydantic, riuso jobs.ts invariato, AbortController, labels su feed/grade/capture e badge G1 distinto dal VALIDATO di SP1; loading/empty/error propri.
- [ ] GREEN: polling/terminali/annullamento, filtro as-of, news versione/mapping, covered-zero, accessibilità tastiera e narrow viewport.
- [ ] Test frontend completi/build offline/audit HC0; backend gate completo. Smoke locale con fixture/API sintetiche e rete esterna bloccata, nessun DB reale. Nessun CSS redesign/dipendenza frontend. Review e chiusura.
**Commit:** feat: show intraday data quality and versioned news

## Task 12 — Audit e gate intraday parziale SP2b

**Branch:** investedge/sp2b-task-12; **Base:** origin/investedge/sp2b-task-11.
**Files create:** backend/scripts/intraday_data_smoke.py, docs/reports/<data>-sp2b-intraday-data-gate.md.
**Files modify:** README.md; correzioni nei soli file toccati da Task 1–11 per rilievi review cumulativa; spec/piano/programma per evidenze e stato.
**Produces:** report tecnico G1_TECH, stato reale G1_DATA con motivazione/manifest se disponibile, prestazioni e backlog restante.
- [ ] Smoke offline §12 della spec, DB nuovo/protetto, rete bloccata; tempi/dimensione DB/memoria/throughput/lag/as-of registrati.
- [ ] Audit cumulativo catena/allowlist/sentinelle/migrazioni, matrice §12 -> test; independent review causale/esecuzione/sicurezza e re-review dei fix TDD.
- [ ] Suite backend/frontend completa, Ruff/pip check, build/install offline, audit HC0, diff check; nessun confronto con dati live nei test.
- [ ] Verdetto separato: G1_TECH PASS/FAIL; G1_DATA READY/INSUFFICIENTE/NON_IDONEO su dati configurati e catturati, mai REAL dai fixture. Non avviare capture/attendere 20 sedute automaticamente.
- [ ] Documentare richiesta di eventuale ff merge tecnico su main, poi spec/piano SP3; G1_DATA aperto resta prerequisito economico, SP6a richiede G1_DATA + G2. SP2b intero resta IN CORSO.
**Commit:** chore: verify SP2b intraday data gate

## Dopo il gate: addendum e completamento restante

Riservare **Task 13 documentale**, dipendenze gate SP3 e SP6a completati nel percorso approvato. Nessun branch base oltre Task 12 è inventato oggi: il programma selezionerà la base remota verificata al ritorno da SP6a.
Task 13 produrrà spec/piano dettagliati e allowlist per I3 legacy, fondamentali SEC/UE, insider/revisioni/consensus, macro realizzata, IPO e altri orizzonti, corporate archive certificato/total-return/FX intraday (§13 della spec). Stato NON INIZIATO; non eseguirlo durante il gate corrente.

## Copertura della spec e checkpoint

| Spec | Task |
|---|---|
| §1–3 confini/modalità/tempi | 1, 4–9, 12 |
| §4 feed/trasporto/budget/segreti | 2, 7, 10, 12 |
| §5 identità/calendario/universo | 3, 6, 8–9 |
| §6 barre/quote/aggregazioni | 4, 7–9 |
| §7 news/corporate/halt/calendari | 5–8 |
| §8 archivio/replay/snapshot | 1, 4–9 |
| §9 collector/job | 7, 10 |
| §10 API/UI | 10–11 |
| §11 policy G1 | 1, 9, 12 |
| §12 verifiche/prestazioni | ogni RED/GREEN, audit 12 |
| §13 backlog/resto programma | Task 13 addendum successivo |
| §14 decisioni | approvazione prima Task 1; configurazione reale prima capture |

**Primo passo dopo approvazione:** Task 1. La preparazione di questa proposta non è approvazione automatica, né autorizza ordini, credenziali, spese, raccolta live o riduzione dei gate.