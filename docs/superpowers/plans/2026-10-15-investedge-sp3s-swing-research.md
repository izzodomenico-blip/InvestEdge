# InvestEdge — piano SP3s: laboratorio swing USA offline

**Stato: APPROVATO dall’utente il 2026-10-18, solo documenti. Task0 FATTO documentale; Task1–10 NON INIZIATI.** Scelte tecniche/numeriche congelate ex ante, nessuna evidenza di profitto. Task1 richiede incarico esplicito separato; nessun codice o merge main autorizzato da questa approvazione.

Spec: [SP3s swing 5/21 sedute, H=1 diagnostico](../specs/2026-10-15-investedge-sp3s-swing-research-design.md). Stato unico: [PROGRAMMA-OPERATIVO](../../../PROGRAMMA-OPERATIVO.md). Inventario: [SP1 e fonti](../../reports/2026-10-15-swing-sp1-inventory.md).

Prima proposta `b0566b0921eb004d5042a21b008107adbe9d70d8` (2026-10-15); questa revisione è un nuovo checkpoint, nessun amend/rebase/force. Stato Git prima della revisione 2026-10-16: branch/remote b0566b0 puliti, main remoto 6c32bfa; main locale originale pulito a 6c32bfa, preservazione confermata esplicitamente dall’utente il 2026-10-16 prima di applicare il checkpoint. Nessuno spostamento di main da parte di Codex.

Base Task0: `origin/investedge/sp3-task-5` = `3f37a44b76ba8f8c8182281dbe6301a9898bc11a`, checkpoint di sospensione del codice Task5 già integrato `6c32bfa`. Origin/main conservato a quest’ultimo commit; main originale `fb8ce92` pulito alla prima proposta; nuovo stato rilevato sopra, senza spostarlo. Branch Task0 pubblicato come lock da quella base. Nessun merge automatico: anche il merge documentale richiede nuova conferma esplicita dell’utente.

## Protocollo comune e criteri di chiusura

- Task sequenziali, Codex unico writer; review in sola lettura. Prima di ogni task: leggere programma e documenti applicabili, fetch/status/base; una divergenza non spiegata dalle consegne impone il chiarimento previsto da AGENTS.md.
- Ogni task autorizza soltanto i file elencati, più aggiornamenti di stato/checklist/Note di ripresa in questo piano e nel programma. Una modifica di regole, soglie, campione, griglia o formati pubblicati richiede proposta concreta e approvazione, non un aggiornamento di stato mascherato.
- Tutti i task software richiedono RED per la regressione concreta, GREEN, review del diff, test mirati e suite backend offline fresca prima di FATTO. Ruff `backend scripts tests` e `pip check`; nessuna nuova dipendenza. Il nuovo Task3 è gate documentale, non task di implementazione: link/scope/scanner/diff e prove del pacchetto, senza suite software in assenza di modifiche al codice. Conservare log/JUnit, tempi, hash dei file verificati e tentativi di rete inattesi fuori Git.
- Per test/smoke usare ambiente temporaneo senza credenziali e dotenv, DB soltanto temporanei e guard rete prima della raccolta dei test, riusando il launcher offline già verificato nella consegna SP3. Verificarne percorso/hash prima dell’uso; il wrapper storico `sp3-task2-verification/run_offline_tests.py` conta i tentativi di rete ma richiede anche la preparazione dell’ambiente prima di importare l’app. Vietato usare il solo flag REAL=false come garanzia di isolamento. Nuovi moduli puri non importano config, servizi DB, provider o clock implicito.
- Comandi logici di gate: `backend/.venv/Scripts/python.exe <launcher-offline-verificato> -q -o addopts= -p no:cacheprovider --junitxml=<scratch>/targeted.xml <moduli-mirati>`; stesso launcher senza filtro per il backend completo; `backend/.venv/Scripts/python.exe -m ruff check backend scripts tests --no-cache`; `backend/.venv/Scripts/python.exe -m pip check`; `git diff --check`; scanner segreti con self-test e allowlist esatta. Sostituire i segnaposto con path reali nel log prima di eseguire. Frontend invariato: non serve ci/build a ogni task; eseguirli solo se un impatto accertato cambia il perimetro con autorizzazione.
- Nessuna suite o fixture legge `data/investedge.db`, importa dati live o accede a TR. Fixture sintetiche chiaramente marcate, dati holdout REAL mai usati nei test.
- Commit con messaggio del task; programma/checklist/evidenza/Prossimo passo nello stesso commit. Un commit non registra il proprio SHA: usare task successivo/ricevuta fuori Git. Push solo branch task con `git push -u origin HEAD`, gate `git ls-remote origin refs/heads/<branch> = HEAD`, worktree pulito. Mai force/rebase/amend pubblicati. Merge FF main esclusivamente se richiesto esplicitamente; in mancanza, consegnare il branch senza merge.
- Nessuna modifica a SP1/SP2b/SP3, database/schema, requirements/pyproject, API, frontend o runner globale. Eventuali problemi fuori allowlist sono riportati, non corretti di nascosto. Le soglie intraday 5/20/60 restano invariate e sospese: non sono i gate dello swing.

## Task 0 — Brainstorming, spec e piano approvati — FATTO documentale

**Branch:** `investedge/sp3s-task-0`. **Base:** checkpoint `3f37a44b76ba8f8c8182281dbe6301a9898bc11a`. **Owner:** Codex, solo documenti. **Dipendenze:** sospensione salvata e brief acquisito; scelta c/FX e scelta b H=1 approvate; approvazione complessiva acquisita il 2026-10-18, solo documenti.

**Allowlist esatta:**

- `PROGRAMMA-OPERATIVO.md`
- `docs/reports/2026-10-15-swing-sp1-inventory.md`
- `docs/superpowers/specs/2026-10-15-investedge-sp3s-swing-research-design.md`
- `docs/superpowers/plans/2026-10-15-investedge-sp3s-swing-research.md`

- [x] Inventario SP1/fonti e sospensione pubblicati sul branch precedente; checkpoint conservato.
- [x] Acquisire una domanda alla volta: TR, capitale, universo as-of/delistati, finestra/DST/sedute ridotte, rischio, modalità costi, drawdown, stop e dieci posizioni.
- [x] Presentare approcci e proposta concreta: pacchetto isolato, tre famiglie/holding, execution manuale, dati/gate separati, campione e statistiche ex ante, allowlist e task.
- [x] Review prima proposta b0566b0: 50/50 verifiche e 10 link locali, scanner/diff/scope PASS; evidenze storiche in `sp3s-task0-verification`, non nuove prove della revisione.
- [x] Review/checkpoint 2026-10-16: costi/potenza/Monte Carlo ricalcolati, proposte beta/FX e gate fattibilità anticipato. `verify_applied.py` 60/60 PASS, 10 link locali validi, scope quattro Markdown, scanner/self-test zero candidati inattesi/placeholder e `git diff --check` PASS; registro/Note di ripresa aggiornati. Review del diff root conclusa; decisioni e approvazione restano pendenti. Evidenze fuori Git in `sp3s-task0-review-20261016`; suite software non rieseguite per soli documenti.
- [x] Scelta c SEVERE acquisita il 2026-10-18: gate necessario, proposta FX documentata prima dell’applicazione.
- [x] Approvazione esplicita e applicazione documentale §7.2 il 2026-10-18: extra 0 bps solo per ordini/regolamento interamente EUR senza conversione di cassa; altre conversioni documentate o INSUFFICIENTE. Riga SEVERE e tabelle aggiornate, minimo 50 bps/lato, fee 2/4 EUR e ritardo 15m invariati. RT nel solo caso EUR 14/18 EUR su 1.000 EUR; nessun codice.
- [x] Scelta b H=1 approvata il 2026-10-18: sei diagnostici separati, fuori selezione/N/varianza DSR/holdout; 12 candidati H=5/21 + 2 selettori, N14. Bonferroni 0,05/14 e quantile 1−0,05/14; B/seed/lunghezze e altri gate invariati.
- [x] Controlli freschi checkpoint 2026-10-18: `verify_documents.py` 72/72 PASS, 10 link locali validi; scope esatto quattro Markdown, scanner/self-test zero candidati inattesi/placeholder, diff e review root PASS. Programma/Note di ripresa aggiornati; nessuna suite software per soli documenti. Evidenze fuori Git in `sp3s-task0-fx-20261018`.
- [x] Controlli freschi applicazione FX approvata: `verify_documents.py` 44/44 PASS, 10 link locali validi; scanner4/self-test zero candidati inattesi/placeholder; diff/scope e review root PASS. Regole H=1, N20, campione e soglie statistiche identici a 86ffdf0. Programma/Note di ripresa aggiornati, prove fuori Git in `sp3s-task0-fx-approved-20261018`; suite software non rieseguite per soli documenti.
- [x] Review e controlli freschi H=1 diagnostico/N14: `verify_documents.py` 62/62 PASS, 10 link locali validi; scanner4/self-test zero candidati inattesi/placeholder, scope/diff/review root PASS. Bonferroni/MDE/Monte Carlo ricalcolati; soglie economiche, costi e date preservati. Programma/Note di ripresa aggiornati; evidenze fuori Git in `sp3s-task0-h1-20261018`, nessuna suite software per soli documenti.
- [x] Approvazione complessiva esplicita acquisita il 2026-10-18, solo documenti: ricerca H=5/21/N14, H=1 diagnostico, FX condizionato/SEVERE necessario, gate benchmark/USD e G_SWING_FEAS prima delle strategie. Task1 e merge main richiedono incarico esplicito separato.
- [x] Chiusura Task0: `verify_documents.py` 74/74 PASS, 10 link locali validi; scanner4/self-test zero candidati inattesi/placeholder, scope/diff e review root PASS. Formule/parametri/costi/campione identici alla versione approvata badbf90. Solo quattro Markdown; nessuna suite backend/frontend rieseguita. Evidenze fuori Git in `sp3s-task0-approved-20261018`; push/gate SHA post-commit, nessun merge.

Commit della proposta: `docs: propose SP3s swing research specification and plan`. Checkpoint di revisione pubblicato `35871ec3e9936e4ae17edc5ca02e533d28915d88`: `chore: checkpoint SP3s Task0 review costs and data feasibility`. Proposta numerica pubblicata `86ffdf07d2d2dc6efb435739dc27beddddc36391`: `chore: checkpoint SP3s Task0 propose documented FX recalibration`. Applicazione FX pubblicata `1a025cffd199e7481c28125633d643f205994a16`: `chore: checkpoint SP3s Task0 apply approved FX recalibration`. Checkpoint H=1/N14 pubblicato `badbf90e4104db73b6769affcf09d2c5f671d16a`: `chore: checkpoint SP3s Task0 isolate H1 diagnostics and freeze N14`. Checkpoint di chiusura: `chore: checkpoint SP3s Task0 record document approval`. Task0 FATTO documentale con approvazione acquisita e verifiche fresche; Task1 non avviato. Push e gate SHA sono verifiche post-commit; nessun merge incluso. Eventuali ulteriori commit di revisione/approvazione documentale sono checkpoint tracciati, senza riscrittura della storia.

## Task 1 — Contratti, registro e confini offline

**Branch:** `investedge/sp3s-task-1`. **Base:** origin/investedge/sp3s-task-0 approvato e SHA verificato. **Dipendenze:** Task0 FATTO e incarico esplicito di implementazione.

**Nuovi:** `backend/app/swing_research/__init__.py`, `contracts.py`, `registry.py`; `tests/swing_research_fixtures.py`, `tests/test_swing_research_contracts.py`, `tests/test_swing_research_registry.py`, `tests/test_swing_research_boundaries.py`. I nomi abbreviati di moduli nei task seguenti sono nello stesso pacchetto.

- [ ] RED: manifest/config mutabile, hash non comprende FX/benchmark/rischio, ordine variabile dei 12 candidati/2 selettori, diagnostici H=1 confusi con ricerca/N14, tentativi falliti non contati, start prima della preregistrazione o input REAL/SYNTHETIC confusi.
- [ ] Implementare dataclass/versioni canoniche, stati e reason code, capitale/rischio/finestra/holding/griglia ex ante, ruoli RESEARCH (14) e DIAGNOSTIC_ONLY (6) distinti; registro su file separato dal DB con eventi append-only e pubblicazione atomica sotto lock. Nessun import/provider o simulazione.
- [ ] GREEN: replay/idempotenza/concorrenza/rollback/cancel senza righe orfane, tentativi no-trade/failed/cancelled conservati, seal/contaminazione metadata; protezione path e input/output separati. Nessuna promessa di isolamento globale del filesystem.
- [ ] Confini statici e import smoke offline: niente DB/config/dotenv/provider/trading né dipendenza inversa da SP1/intraday; nessun modulo esistente modificato.
- [ ] Mirati contracts/registry/boundaries e gate comune; programma e prossimo Task2.

**Commit:** `feat: define offline swing research contracts and registry`.

## Task 2 — Dataset locale, universo storico e corporate action

**Branch:** `investedge/sp3s-task-2`. **Base:** origin/investedge/sp3s-task-1. **Dipendenze:** Task1 FATTO.

**Nuovi:** `datasets.py`, `universe.py`, `calendar.py`, `events.py`; `tests/test_swing_research_datasets.py`, `tests/test_swing_research_universe.py`, `tests/test_swing_research_events.py`. **Modificabili:** `contracts.py`, `tests/swing_research_fixtures.py`, `tests/test_swing_research_boundaries.py` soltanto per raccordi necessari del contratto approvato.

- [ ] RED: lista corrente TR/asset catalog al posto di as-of, sopravvissuti selezionati, ticker riutilizzato, disponibilità futura, Stooq UNKNOWN trattato come total return, duplicati incoerenti, barra/FX/azione futura usata al cutoff.
- [ ] Reader locale read-only/streaming e quality report §3: grain/feed/diritti, hash/count, copertura e denominatori; universo mensile ADV20/prezzo 5/252 sedute/top 500, tie stabile, nessuna esclusione opportunistica.
- [ ] GREEN con IPO/delistato/merger/rename/split/dividendo e recupero mancante; l’assenza genera insufficienza e non liquidazione a prezzo inventato. Corporate action e prezzo/volume coerenti; cassa a pay-date, nessun doppio total return.
- [ ] Calendario/FX a cutoff, DST e half-day; manifest con metadati holdout opachi, reader senza accesso a esiti non autorizzati. Letture a batch 10.000/8MiB e risorse fail-closed; nessun download.
- [ ] Mirati dataset/universe/events + registry/boundaries e regressioni SP1 series; gate comune. G_SWING_DATA REAL resta NON VALUTATO in assenza di pacchetto idoneo. Prossimo Task3: gate documentale G_SWING_FEAS; vietato saltarlo per iniziare feature/simulazione.

**Commit:** `feat: validate offline swing datasets and as-of universes`.

## Task 3 — Fattibilità dati, prima delle strategie

**Branch:** `investedge/sp3s-task-3`. **Base:** origin/investedge/sp3s-task-2. **Dipendenze:** Task2 FATTO; spec/piano e decisioni aperte approvati. Task documentale, nessun codice.

**Nuovo:** `docs/reports/sp3s-swing-data-feasibility-gate.md`; aggiornamenti di stato in piano/programma. Input/prove del pacchetto fuori Git, nessuna chiave o dato sensibile nei documenti.

- [ ] Inventario per ogni campo della spec §3.4 sull’intero campione: anagrafica as-of/delistati, classi e domicilio storico, raw daily/minuti SIP/cutoff/stop RTH, eventi/recuperi terminali, FX/benchmark, calendario e settlement, diritti/costi e risorse.
- [ ] Identificare fonti candidate e prove effettivamente fornite; Basic richiede una chiave eventualmente configurata solo dall’utente per un suo export, non dagli agenti. Nessuna API/download o spesa del writer. Il fatto che una fonte sia configurabile non dimostra il pacchetto.
- [ ] PASS G_SWING_FEAS soltanto con copertura documentata di ogni requisito, dati locali non-holdout verificabili e attestazione strutturale del custode per holdout sigillato/opaco. Non leggere rendimenti o feature holdout; nessun tentativo economico. Fattibilità non sostituisce G_SWING_DATA finale.
- [ ] Assenza, diritto non dimostrato, recuperi non osservati, sole liste correnti, domicilio ignoto o budget non attestato -> INSUFFICIENTE; eventuale provenienza incompatibile -> NON_IDONEO. Registrare costo/azione eventualmente richiesti all’utente senza attivarli. Non reinterpretare la lista TR corrente o eliminare i delistati per passare.
- [ ] Review/link/scope/scanner/diff e programma. Se INSUFFICIENTE, Task3 BLOCCATO e **Task4–9 non partono**, senza proclamare completato tutto il software prima di verificare i dati. Nessuna modifica silenziosa delle soglie o del campione.

**Commit:** `docs: gate swing data feasibility before strategy implementation`.

## Task 4 — Feature e tre famiglie congelate

**Branch:** `investedge/sp3s-task-4`. **Base:** origin/investedge/sp3s-task-3. **Dipendenze:** Task3 FATTO e G_SWING_FEAS PASS; Task2 software FATTO.

**Nuovi:** `features.py`, `strategies.py`; `tests/test_swing_research_features.py`, `tests/test_swing_research_strategies.py`. **Modificabili:** `contracts.py`, `tests/swing_research_fixtures.py`, `tests/test_swing_research_boundaries.py` per contratti già fissati.

- [ ] RED: daily odierna completa prima del close, SMA/breakout includono futuro o giorno sbagliato, volume non split-coerente, prezzo con ritardo diverso da 15m o stale, feature non valida riempita da score/ML.
- [ ] Implementare §4–5: decisione C−40, cutoff C−55, daily fino a x, MOM/PULLBACK/BREAKOUT esatti, ranking e tie comuni; sei family/holding di ricerca H=5/21 per modalità; tre H=1 diagnostiche per modalità con le medesime regole e nessun selettore. Riutilizzare solo funzioni pure SP1 semanticamente compatibili.
- [ ] GREEN: esempi positivi/negativi a mano e ai confini, warm-up, split nel giorno del segnale, ore legali/sedute ridotte, segnale invariato modificando soltanto dati futuri. Nessun ordine o valutazione economica REAL.
- [ ] Mirati features/strategies/datasets/boundaries + feature SP1; gate comune, programma e prossimo Task5.

**Commit:** `feat: implement preregistered swing candidate signals`.

## Task 5 — Costi, rischio e ledger EUR

**Branch:** `investedge/sp3s-task-5`. **Base:** origin/investedge/sp3s-task-4. **Dipendenze:** Task4 FATTO.

**Nuovi:** `costs.py`, `risk.py`; `tests/test_swing_research_costs.py`, `tests/test_swing_research_risk.py`. **Modificabili:** `contracts.py`, `tests/swing_research_fixtures.py`.

- [ ] RED: fee Best/Direct mescolate, costi stressati applicati solo alla curva finale, fee/FX duplicati o ignorati, rischio/cassa su prezzo futuro, frazioni azionarie, limite per posizione rispettato ma aggregato/pendenti violato.
- [ ] Implementare Decimal e arrotondamenti, profili separati BASE/STRESS/SEVERE, quote intere, cap 10 nomi/10% nozionale, rischio min 100 EUR/1% e aggregato min 1.000 EUR/10%, cassa con settlement e riserva fee. Nessun collegamento al ledger reale.
- [ ] GREEN con calcoli manuali per commissioni, fill parziale, stop, split, dividendi, FX e settlement; uscita totale sotto 100 EUR consentita, nessuna perdita tagliata al budget teorico; valori ignoti generano insufficienza.
- [ ] Mirati cost/risk/contracts/events e regressioni SP1 costi/simulatore senza modificarli; gate comune e programma.

**Commit:** `feat: account for manual TR swing costs and risk limits`.

## Task 6 — Coda manuale, stop e holding dal fill

**Branch:** `investedge/sp3s-task-6`. **Base:** origin/investedge/sp3s-task-5. **Dipendenze:** Task5 FATTO.

**Nuovi:** `execution.py`, `simulator.py`; `tests/test_swing_research_execution.py`, `tests/test_swing_research_simulator.py`. **Modificabili:** `contracts.py`, `tests/swing_research_fixtures.py`.

- [ ] RED: fill al close/sul record del segnale/prima dell’arrivo, dieci ingressi senza tempo per stop, stop retroattivo, gap liquidato al livello teorico, timer da segnale anziché primo fill, deadline che impone un prezzo non osservato.
- [ ] Implementare slot sell/buy+conferma, prezzi conservativi §4, capacità/fill parziali/no-fill, ritardi dei tre scenari e cutoff C−10; holding d+H, invalidazione, stop 2ATR e revisione solo per eventi societari approvati.
- [ ] GREEN: ingresso tardivo e intervallo senza stop, supporto/orari/valuta per modalità, gap/halt/reopen/delisting, uscita oltreH e coda alla seduta seguente. Proxy USA distinta dall’esecuzione TR attestata; nessuna API o ordine vero.
- [ ] P&L e drawdown a mano, giorni flat/settlement, commissioni ed eventi in ledger immutabile, cassa mai negativa; tutte le serie di scenario realmente risimulate.
- [ ] Mirati execution/simulator/risk/strategies/events + regressioni SP1 simulator; gate comune, programma e prossimo Task7.

**Commit:** `feat: simulate manual swing execution and overnight stops`.

## Task 7 — Walk-forward e protocollo holdout sealed

**Branch:** `investedge/sp3s-task-7`. **Base:** origin/investedge/sp3s-task-6. **Dipendenze:** Task6 FATTO.

**Nuovi:** `walk_forward.py`, `holdout.py`; `tests/test_swing_research_walk_forward.py`, `tests/test_swing_research_holdout.py`. **Modificabili:** `registry.py`, `contracts.py`, `tests/swing_research_fixtures.py`, `tests/test_swing_research_registry.py`.

- [ ] RED R1: cambiare split/prezzi/membership nella prima seduta OOS cambia score/scelta IS; fold creati dai dati anziché calendario, perdita al cambio policy nascosta, trial senza Sharpe perso, holdout letto durante selezione o riaperto per nuovo candidato, diagnostico H=1 che ottiene capability holdout o entra nel selettore di ricerca.
- [ ] Implementare date e split §8, IS 504/OOS 126, purge/embargo 21, selettori per modalità IS-only, portafoglio OOS continuo con vecchie posizioni immutabili; ultimo resto di calendario incluso.
- [ ] Congelare candidato finale e manifesti prima dell’apertura unica; reader capability distinto per batch holdout; stati append-only, contaminazione e crash/retry idempotente senza output economici intermedi. Nessuna lettura REAL in questi test.
- [ ] GREEN: invarianti dei prefissi, nessun candidato idoneo->cash, ultimoH/campione irrisolto->insufficiente, accesso/esito futuro non cambia decisioni passate; stesso batch ripetibile e report non sostituibile; H=1 rifiutato dal reader holdout e dal selettore H=5/21.
- [ ] Mirati WFO/holdout/registry/simulator + WFO SP1 R1; gate comune, programma e prossimo Task8.

**Commit:** `feat: add causal swing walk-forward and sealed holdout`.

## Task 8 — Statistica dipendente e verdetti

**Branch:** `investedge/sp3s-task-8`. **Base:** origin/investedge/sp3s-task-7. **Dipendenze:** Task7 FATTO.

**Nuovi:** `stats.py`, `evidence.py`; `tests/test_swing_research_stats.py`, `tests/test_swing_research_evidence.py`. **Modificabili:** `contracts.py`, `tests/swing_research_fixtures.py`.

- [ ] RED: trade/minuti trattati come indipendenti, drop giorni flat/perdenti, bootstrap indipendente per titolo/curva, solo blocco favorevole, Bonferroni senza tutti 14 tentativi di ricerca o con diagnostici H=1 inclusi nella varianza DSR/selezione, DSR scambiato per correzione seriale o non definito trasformato in zero.
- [ ] Implementare bootstrap stationary congiunto 10.000/seed 20261015, lunghezze medie 63/21, N14 e LB al quantile 1−0,05/14 (senza troncare). Alpha famiglia 0,05 e DSR>=0,95 invariati; H=1 fuori indici inferenziali e varianza DSR. Nuova funzione DSR swing con N e varianza separati: quella SP1 usa len(trial_sharpes) e varianza della lista, rifiuta non finiti. Dispersione OOS dei soli 14 percorsi di ricerca congelata per holdout, nessuno Sharpe fittizio o modifica SP1. Riportare precisione Monte Carlo del quantile N14/statistiche d’ordine 9952/9976 e limite dei circa 11 blocchi holdout; nessun verdetto inferenziale H=1.
- [ ] GREEN con processi sintetici dipendenti/nulli, costi/ritardi/rischio e minimi campione verificabili a mano; separare insufficienza da gate fallito e proxy da VALIDATO_TR. Nessuna fixture positiva diventa evidenza economica.
- [ ] Gate §9 invarianti su OOS e holdout separati; curve fisse finali scelte dall’IS 2021-11-29–2023-11-29 sono screening retrospettivo in parte in-sample, holdout unica prova pulita del candidato finale. Gate §9.2 benchmark/USD approvati e necessari: benchmark EW as-of con esposizione laggata, ledger locale/FX/interazione e gate USD sullo stesso bootstrap, tutti congiunti e senza aumentare N. Gate OOS attuali: OOS PASS sia per selettore sia per candidato finale scelto IS, nessun ripescaggio dopo un fallimento; concentrazione consolidata per emittente, otto fold/sei positivi, holdout due periodi positivi su tre; snapshot benchmark e FX R2 immutabili.
- [ ] Mirati stats/evidence/WFO/holdout + stats/evidence SP1; gate comune, programma e prossimo Task9.

**Commit:** `feat: evaluate swing evidence with dependent return statistics`.

## Task 9 — Report, CLI offline e audit software

**Branch:** `investedge/sp3s-task-9`. **Base:** origin/investedge/sp3s-task-8. **Dipendenze:** Task8 FATTO.

**Nuovi:** `reports.py`, `backend/scripts/swing_research.py`, `tests/test_swing_research_reports.py`, `tests/test_swing_research_cli.py`, `docs/reports/sp3s-swing-software-gate.md`. **Modificabili:** `contracts.py`, `tests/swing_research_fixtures.py`, `tests/test_swing_research_boundaries.py`.

- [ ] RED: report rilegge latest e cambia benchmark/FX lasciando hash uguale, proxy presentata come TR validato, CLI scrive nell’input o nel DB reale, output parziale promosso dopo errore/cancel, raccolta di rete avviata implicitamente.
- [ ] CLI esplicita su pacchetto locale e output dedicato, comandi di verifica/ricerca sintetica/report con errori redatti; nessun comando fetch/live/trade/paper. Report JSON/Markdown immutabile, unità/fonti/proxy/lacune/costi/non-fill/verdetti visibili.
- [ ] GREEN end-to-end sintetico: fixture realistica per tutte le famiglie/holding/modalità/scenari, DST/half-day/gap/delistato, incompatibilità e cancellazione; fingerprint invariato a rilettura e diverso a revisione futura degli input; H=1 solo calcolo/report descrittivo separato dopo freeze/verdetto ricerca, senza accesso holdout o effetto su selezione/N14, come §9.4.
- [ ] Profiling offline streaming su 100 e 500 identità per 21 e 63 sedute: includere minuto per tutte le posizioni, input/righe/disco/tempo/RSS aggregati, cap 2GiB, zero perdite. Numero di sedute/names deriva dal fixture dichiarato; nessuna soglia intraday importata o abbassata. Test bounded prima della scala grande e fail-closed al cap.
- [ ] Suite completa offline, mirati e regressioni SP1/SP2b/SP3, Ruff/pip/scanner/scope/diff, review cumulativa senza rilievi bloccanti. Report G_SWING_TECH PASS soltanto con prove fresche; G_SWING_DATA/RESEARCH/TR non valutati per sola fixture.
- [ ] Aggiornare programma: software FATTO distinto da SP3s economico; Task10 non avviabile senza incarico e dataset idoneo.

**Commit:** `feat: expose auditable offline swing research reports`.

## Task 10 — Gate dati ed economico REAL, condizionale e fuori dall’incarico attuale

**Branch:** `investedge/sp3s-task-10`. **Base:** origin/investedge/sp3s-task-9. **Dipendenze:** Task9 FATTO, G_SWING_FEAS PASS del Task3, dataset locale idoneo fornito, incarico esplicito di valutazione offline. In assenza, BLOCCATO con ragione/evidenza, senza raccolte automatiche. L’approvazione documentale non apre il holdout REAL.

**Nuovo documento autorizzabile:** `docs/reports/sp3s-swing-data-economic-gate.md`. Input/output economici fuori Git; nessuna modifica di codice, parametri o soglie per correggere un risultato sfavorevole.

- [ ] Verificare G_SWING_DATA senza leggere esiti holdout: fonti/diritti/universo as-of/delistati/rendimenti terminali, prezzi in finestra e stop, corporate action/FX/calendario/hash/costi. Identificare proxy e limiti TR. Se il pacchetto gratuito è incompleto, fermarsi a INSUFFICIENTE.
- [ ] Congelare registro/tutti 14 percorsi di ricerca e sei ID diagnostici H=1 separati, versioni software/input/metodo e holdout opaco; eseguire IS/OOS e i tre scenari. Niente revisione opportunistica di campione o griglia.
- [ ] Aprire il solo batch finale idoneo una volta secondo §8, dopo PASS OOS del selettore e del candidato finale scelto IS e freeze; nessun candidato successivo sullo stesso holdout se fallisce. Conservare anche no-trade/errori/risultati negativi. Nessuna apertura holdout per H=1; diagnostica soltanto sui dati non holdout dopo report/verdetto ricerca congelato, senza retuning.
- [ ] Documentare tutti i gate separatamente per Best/Direct e OOS/holdout; se nessuna policy passa, nessuna promossa. PASS_RICERCA_PROXY non è VALIDATO_TR. Nessuna raccomandazione di rendimento futuro, ordine, paper o spesa.
- [ ] Review del rapporto, riproducibilità offline, programma/Prossimo passo/evidenze e commit/push del solo documento. Nessun merge senza nuova conferma FF esplicita; nessuna riattivazione SP3/SP6a implicita.

**Commit:** `docs: record SP3s swing data and economic gate`.

## Condizioni che non si risolvono modificando il codice

Un universo gratuito completo con delistati e recuperi finali non è stato dimostrato. L’accesso Basic storico SIP non prova anagrafica as-of, disponibilità storica delle revisioni o prezzi/stop TR. La finestra manuale richiede dati a granularità più fine del daily, e stop attivi richiedono dati anche fuori da quella finestra negli orari applicabili. La fattibilità è approvata come Task3 bloccante prima dei Task4–9: oggi INSUFFICIENTE per assenza del pacchetto, non promessa di soluzione. Nessun gate economico viene dichiarato superato prima di queste prove. Nessuna richiesta di acquisto, credenziali o raccolta live è inclusa come rimedio automatico.
