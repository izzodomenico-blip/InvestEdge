# InvestEdge — piano SP3: gate strategie intraday 15/30 minuti

**Stato: APPROVATO dall'utente il 2026-10-13; Task0–4 FATTI.** Task4 chiuso il 2026-10-15 con 2476 backend offline PASS e58 focus finali, gate comune e review. Task3 `a8c39759ca9bf686415f8cdb497a2ec9d2da4e8f` pubblicato e integrato FF, verificato alla presa Task4. Task2 conserva i gate5/20/60 invariati PASS. Task5–12 NON INIZIATI; Task13 dopo SP6a e completamento del backlog SP2b. Nessuna raccolta live, credenziale, ordine o paper.

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
**Base verificata:** `9e493e6ee222645db1d86a823bedd0f22762cde6`; approvazione esplicita acquisita il 2026-10-13 prima del codice, lock pubblicato.
**File nuovi:** `backend/app/intraday_research/__init__.py`, `contracts.py`, `registry.py` nel medesimo pacchetto; `tests/intraday_research_fixtures.py`, `tests/test_intraday_research_contracts.py`, `tests/test_intraday_research_registry.py`, `tests/test_intraday_research_schema.py`.
**File modificati:** `backend/app/database.py`, `tests/test_database.py`, `tests/conftest.py` (solo fixture scratch/registry, guardia rete invariata).

- [x] RED: manifest/registry/tabelle assenti; ns/int64 non esatti, mixed namespace, cap non positivi, finite JSON; tutti i20 trial preregistrati prima del primo STARTED; FAILED/CANCELLED/REJECTED/no-trade non perduti; UPDATE/DELETE/REPLACE e FK cross-mode bloccati.
- [x] Implementare contratti versionati e tabelle §12, risorse/seed/split/costi/gate frozen, config_hash distinto da experiment_hash, eventi append-only di trial/holdout. Default nessuna promozione dati sintetici; nessun provider/job avviato.
- [x] GREEN: DB nuovo e fixture pre-SP2b/SP1/SP2b, backup fallito, rerun idempotente/rollback e righe/FK storiche identiche. Replica identica legata allo stesso esperimento, ipotesi nuova distinta; prova tamper e stato finale senza dati di esito inventati.
- [x] Mirati: test_intraday_research_contracts/registry/schema + test_database/config/lab_trials; gate comune e review. Policy capitale/risorse approvata ex ante non imposta il paper.

**Evidenza 2026-10-13:** RED iniziale3 collection error per package assente; GREEN88, poi RED delle review16/17+policykey1+clock2+referencebool1 e fix. Wrapper offline finale10 moduli mirati447 PASS e backend completo2027 PASS da JUnit (153 nuovi); zero external inattesi e due self-test intenzionali nel completo. Ruff backend/scripts/tests, pip check, scanner13 file con self-test Fase2/zero candidati, diff/scope e2 review read-only+root PASS senza Critical/Important. Migrazione/backup/rerun preservano righe e schema SP1/SP2b; race dueconnessioni e rollback batch20 verificati. No frontend modificato, gate UI non richiesto.

Il bootstrap congela minimo10000 e formula adattiva preregistrata su M; repliche effettive al Task8. Letture revalidano integralmente config e hash/header/ref/clock/seal; holdout_state corrente separato dal SEALED iniziale. Task1 controlla header/digest/namespace dataset; publication/closure Task2, import size/tick/news Task3/5 e protocollo apertura/attestazioni holdout Task9/10. Costi UNVERIFIED/economia NOT_EVALUATED, G1_DATA INSUFFICIENTE e G2 NON VALUTATO. Nessuna strategia/API/job/ordine/paper/avvio live introdotti.

Programma/checkbox chiusi nello stesso commit. Push del branch Task1/gate SHA, FF main/gate SHA e worktree pulito sono verifiche post-commit del protocollo autorizzato; esiti nella consegna, proprio SHA nel Task2. Prossimo Task2 NON INIZIATO.

**Commit:** `feat: preregister bounded intraday research experiments`

## Task 2 — Timeline-only, snapshot a finestre e bundle sostenibili

**Branch:** `investedge/sp3-task-2`; **Base:** origin/investedge/sp3-task-1.
**Dipendenze:** Task1 FATTO.
**Base verificata:** `7b708706c70a4d37d01bc10b73af299bc2052e25`; branch/main concordi e lock Task2 pubblicato il 2026-10-13.
**File nuovi:** `backend/app/intraday_research/datasets.py`, `tests/test_intraday_research_datasets.py`, `tests/test_intraday_timeline_reader.py`, `backend/scripts/intraday_timeline_smoke.py`.
**File modificati:** `backend/app/intraday/store.py`, `replay.py`, `snapshots.py`, `quality.py`, `handlers.py` nel medesimo pacchetto; `backend/app/api/intraday_routes.py`, `backend/app/database.py` (solo indici/formato v2 additive); `tests/test_intraday_store.py`, `tests/test_intraday_replay.py`, `tests/test_intraday_snapshots.py`, `tests/test_intraday_quality.py`, `tests/test_intraday_api.py`, `tests/test_intraday_collector.py` (solo benchmark runtime fake).

**Estensione autorizzata dall'utente il 2026-10-13:** `tests/test_database.py`, solo il test di migrazione additiva SP3: escludere anche le quattro nuove tabelle bundle dal confronto del grafo SP2b e verificarle vuote dopo migrazione/rerun; preservare controlli di backup, schema, dati e FK.

**Estensione autorizzata dall'utente il 2026-10-14:** prototipo offline opzionale nei soli `backend/app/intraday/_reader_native.c`, `backend/pyproject.toml`, `tests/test_intraday_native_reader.py`. Preservare fallback Python e tutti i controlli; adozione subordinata a parità byte, review e gate completi5/20/60. Con l'addendum B sotto, il reader v3 usa opzionalmente i batch pubblici dell'estensione API5; senza estensione compatibile mantiene il percorso Python completo. I test nativi sono esplicitamente skip quando l'estensione manca. La build richiede compilatore e setuptools; wheel/binari/build restano in scratch/venv ignorata. L'accesso sperimentale alla connessione tramite ABI privata è limitato a CPython3.14.7 Windows64, tipo e layout esatti, conversioni standard e thread owner; non è un'API supportata di CPython e non è adottato nel prodotto. Nessuna cache globale di valori, provider o clock; codec runtime con cache_strings=False.

- [x] RED: pagina/freeze costruiscono proiezioni o lista prefisso intero; cap RAM/chunk violati; start recente ancora full-prefix; bundle con finestre overlapping cambia denominatori; stato iniziale usa revisioni future o omette receipt/macro/carry-in.
- [x] Separare iterazione validata dalla proiezione; digest incrementale/count/hash/closure prima della pubblicazione, vecchio v1 intatto. Formato window-dependency-closure-v2 e bundle ordinato/riferimenti esatti §3.1; nessun DELETE/retention finita. Quality sul bundle conserva minimi20/10, raw99%, ogni cella90%/>0; non etichettare child5sedute READY.
- [x] GREEN: timeline vecchia/nuova byte-equivalenti ai cutoff, A→B→A/shuffle/tie/cross-capture, superseded/pre-periodo/audit orfani, missing/tamper/rollback/cancel, macro globali, revisione BAR/news dopo freeze invarianti; SQLite authorizer/clock/provider negati nei GET e total_changes invariato. Confrontare proiezioni/carry-in/closure col v1; equivalenza di feature/policy/fill sarà verificata ai Task4/7/12 quando tali componenti esistono.
- [x] Smoke30×20 e scalare5/20/60: p95≤250ms, timeline replay≤60s, RSS≤2GiB, crescita disco misurata, zero perdite. Runtime socketfake completo con checkpoint/status/reconcile per batch, budget/GAP/lag espliciti. Gate sostenibilità necessario prima di esperimenti grandi; se manca, task non FATTO per questa definizione, registrare blocco/limite senza abbassare soglie o passare al task dipendente.
- [x] Mirati: test_intraday_timeline_reader/research_datasets + store/replay/snapshots/quality/API/collector/boundaries; suite/gate comune e review compatibilità v1. Script smoke rifiuta target esistente/data/investedge.db, dotenv e socket esterni.

**Verifica funzionale finale 2026-10-13:** wrapper offline `run_offline_tests.py -q -o addopts= -p no:cacheprovider`: 363 mirati (`targeted-checkpoint.xml`) e 2089 backend (`full-checkpoint.xml`) PASS, 62 nuovi sul baseline Task1; zero failure/error/skip e chiamate esterne inattese, due self-test intenzionali della guardia nel completo. Ruff backend/scripts/tests, pip check, diff/scope e scanner sui 15 file PASS. Review read-only e root del diff PASS nel perimetro funzionale; gate prestazionale separato e ancora non superato. Il fallimento intermedio della migrazione è stato corretto nell'estensione autorizzata sopra, preservando backup, dati, schema e FK SP2b.

**Sostenibilità parziale:** 30×5 completo PASS: p95 119,175 ms, replay 38,839 s, picco RSS 417685504 B, disco 387702784 B; zero rete, perdite e GAP nel runtime fake. Nel 30×20, 228600 BAR e 228600 QUOTE, i replay delle quattro finestre sono 40,724 / 61,971 / 77,230 / 81,046 s: il limite approvato di 60 s è mancato. Smoke interrotto esplicitamente durante il freeze bundle prima di header/seal: p95 e replay dell'apertura nuova del bundle con validazione dei figli non misurati; 30×60 non eseguito. Sono misure precedenti all'ultimo fix di cancel/budget dello staging. Queste evidenze non chiudono il Task2 e non autorizzano Task3 o merge main; nessuna soglia viene abbassata.

**Fix finale di review:** TDD RED3 su cancellazione cooperativa/budget dei duplicati nello staging bundle; il contatore ora include ogni occurrence, poll ogni 1000 e ai confini child/fine, rollback/cleanup prima di RAW/seal. GREEN61 nei due moduli (`cancel-green2.xml`), re-review indipendente con 3 probe RAM e suite finali 363/2089 PASS. Il checkpoint conserva codice/evidenze con Task2 IN CORSO; ripresa sullo stesso branch, profiling separato di validation/from_frozen/open_bundle/iterazione, correzione verificata e nuovi smoke completi 5/20/60 prima del commit finale e FF.

**Checkpoint di questa consegna:** `chore: checkpoint SP3 Task2 sustainability gate`; push solo Task2/gate SHA e worktree pulito come verifiche post-commit riportate nella consegna, proprio SHA nel passo successivo. Nessun FF del checkpoint su main.

**Ripresa profiling/ottimizzazione autorizzata il 2026-10-13:** checkpoint precedente `d8768096ecdad53d05e48a8bc5cdf3d19a0ee319` verificato su origin/Task2; main resta alla base Task1. Root unico writer, reviewer read-only. Soglie e fixture invariati, nessuna raccolta live, credenziale, ordine o paper. Profiling diagnostico separato dai gate: validazione cold dei quattro child 30×20 da 153,709 s a 137,785 s e poi 96,862 s, ancora oltre60 prima del replay.

- Codec JSON riutilizzabile e nativo già disponibile nel runtime: i float usano native soltanto con esatta parità dei byte scalari contro float.__repr__, altrimenti fallback v1; fallback anche per profondità. Canonicalità, finitezza, int64 e hash esatti. Scope effimero di prove SHA/full-ref/dimensione/availability, LRU globale64MiB e fallback/eviction; mai catturato negli handle. Ogni child conserva digest, publication, namespace, proiezioni, disponibilità, count e closure completi. Flag PENDING promossi soltanto dopo intero child PASS, costruzione del risultato e fence finale; ogni failure li scarta. Availability RAW esatta conservata per receipt semplici senza projection, cutoff corrente e binding del singolo child sempre verificati.
- Indice additivo per l'ordine dei member e receipt lookup coperto; letture as-of con tuple, mapping dei primi alias e codec già verificato. Closure ADMISSION legge soltanto i binding necessari, mentre ogni receipt passa comunque la validazione integrale prima del risultato. Staging bundle deduplica ref già validate prima dell'idratazione, con min availability, identità canonica distinta True/1, fence e cancel/budget su tutte le occurrence.
- Staging TEMP del solo job: metadati prima dei grandi payload e indice covering della liveness, dopo RED EXPLAIN. Conteggio bundle sulle identità tipizzate senza ranking delle proiezioni; selezione/ordine delle reference invariati. Working set dei testi di riferimento limitato prima della decodifica (2MiB/1000), cap degli envelope esatti e inventario sensibile corrente applicato anche a digest/publication_hash derivati pubblici. Handle pin sull'epoch validato e fence dopo la costruzione, dopo RED2 sui costruttori. Getter memorizza soltanto accessori/nome, mai valori; rotazioni in-place rilevate.
- TDD RED osservati e GREEN; review funzionali finali senza Critical/Important, corpus617 JSON/float e probe RAM per cache/cutoff/namespace/receipt/failure. Finali405 mirati (`opt-targeted-v5.xml`,119,35s) e2131 backend (`opt-full-v5.xml`,588,67s) PASS,104 nuovi su Task1 e42 sul precedente checkpoint; rete inattesa0, due self-test intenzionali nel completo. Ruff/pip/scanner15/diff PASS. Memoria di quattro pagine317724B misurata contro320000B addebitati più4096B riservati; nessuna deroga64MiB/2GiB.
- Gate eseguiti in processi nuovi sui fixture completi: il timer bundle comprende nuova `open_bundle`, tutti i child e l'intero replay/checksum deduplicato. Le ri-misure isolate riusano soltanto dati sintetici congelati, senza handle già validati fuori dal timer. Nessuna soglia abbassata e nessun merge/Task3 prima del PASS complessivo.
- Ri-misure prima degli ultimi due micro-fix codec/getter: worker60 sospeso durante le letture5/20 e poi ripreso. Scala5 PASS (`isolated-final-5.log`): p95=210,486ms, replay27,763s, RSS418332672B, disco421883904B. Scala20 FAIL (`isolated-final-20.log`): p95=867,833ms, finestre33,535/42,589/56,297/69,664s, bundle181,392s incluse tutte le validazioni e915131 occurrence; BAR228600/QUOTE228600/NEWS2, checksum invariato dopo revisioni future, RSS letture225669120B, disco2515341312B. Runtime fake940/940, zero perdite/GAP/rete e due PONG durabili per scala. Freeze bundle aggiornato500,456s dopo riavvio del solo job su quattro child durabili, senza ricreare fonti o usare handle prevalidati nel timer. Profiling RAM codec40000 source0,2504→0,1888s e getter200000 chiamate0,1216→0,0831s: diagnostica, non PASS prestazionale.
- Scala60 source complete696600 BAR/QUOTE e1393200 admission,60 sedute/una mezza giornata, peak sorgenti132599808B e crescita disco misurata. Il tail originale dello smoke viene eseguito senza modifiche sulla sola fixture sintetica verificata:12 freeze, tutti i replay,20 query e runtime; in corso e ri-misure sul codice corrente da registrare. Task2 IN CORSO, prossimo ancora lo stesso gate; commit finale e FF solo dopo PASS complessivo.

**Ulteriore profiling 2026-10-13, gate finali ancora in corso:** RED sull'indice RAW covering e sugli sprechi UTF8/header/news, poi GREEN92 store/migrazione,105 reader/bundle e199 sui quattro moduli dopo la query news. Suite corrente2138 PASS (`opt-full-v7.xml`,645,42s),111 nuovi su Task1/49 sul checkpoint, zero failure/error/skip e rete inattesa, due self-test intenzionali nel completo; due warning preesistenti. Gate correnti5/20 in esecuzione sequenziale dopo la suite completa. Nessun risultato pendente viene dichiarato PASS.

- Indice RAW covering26 colonne, prefisso namespace/listing/kind/logical_key/capture_id preservato: risultati completi18 casi RAM con/senza indice identici, A→B→A, revisioni, namespace, alias e colonne aggiuntive con fallback. Il primo A/B20 sulla variante precedente dell'ordine indice misurava p95772,494→197,377ms, build4,000s e+267538432B: diagnostica, non gate del DDL finale. La ri-misura finale usa gli indici correnti e include il loro spazio.
- Il decoder riusa un solo buffer UTF8 bounded per parse/confronto canonico; il cap degli envelope conta esattamente quote/backslash senza creare un'altra copia escaped. Il codec C stdlib riusato soltanto per header SQLite/proiezioni fresche acicliche conserva byte v1 e fallback ordinario; caller default mantiene il controllo dei cicli. Probe64 header, quattro classi di errore con recupero, fallback e128 chiamate su quattro thread PASS; header20k81,78→70,86ms diagnostici.
- `_links` parte dai link della sola news e dai member tipizzati, mantenendo tutte le dependencies non vuote tramite indice parziale e ranking originale availability/lessicografico. A/B fixture20 su news1/2 e revisione futura3: tutti i byte identici, vecchie query4,7–4,8s e nuove2,6–3,7ms, due indici+8192B, zero DML sorgente/rete. Misura diagnostica con altri job; gate completo separato. Review16 probe PASS, incluse otto dependencies malformate respinte dal preflight pubblico e quattro fence durante callback. Nessuna scansione o validazione child rimossa.
- Contatori sul bundle completo:915751 cold source contro circa915131 sorgenti uniche,702180 completed hit, picco cache addebitato67044096B: l'evizione non spiega da sola il limite. Finestra20 più grande64,045s diagnostici (open32,868/replay31,177; SQL8,272/hydrate6,083/checksum5,207), sempre564191 occurrence/checksum identico. Varianti CTE materializzati, reducer e header nativo scartate perché più lente; niente ampliamento cache o riduzione del campione.
- Gate precedenti ultimi delta:5 PASS p95224,011ms/replay25,808s;20 FAIL p95709,798ms/window66,154s/bundle171,255s,915131 occurrence. Query60 completa p951324,331ms FAIL prima dell'indice RAW finale, runtime940/940 e zero perdite/GAP/rete; dodici finestre e replay ancora in corso. Soglie250ms/60s/2GiB immutate. Task2 IN CORSO e Task3 NON INIZIATO; nessun FF senza PASS complessivo.

**Scala5 del 2026-10-13, prima della correzione del runner scratch:** `isolated-v7-5.log`,p95138,811ms, nuova open+intero replay/checksum22,559s,212636 occurrence/hash identico,53100 BAR/QUOTE, RSS418332672B, disco484048896B inclusi gli indici finali. Runtime fake940/940,zero perdite/GAP/rete,due PONG durabili,5,408s; tutti i gate scala5 PASS. Scala20 corrente e60 restano in corso.

**Scala20 del 2026-10-13, prima della correzione del runner scratch:** `isolated-v7-20.log` FAIL,p95752,075ms, finestre27,004/36,859/49,816/65,422s e bundle152,953s includendo nuova apertura, tutti i child e915131 occurrence/checksum completo. BAR228600/QUOTE228600/NEWS2 e fingerprint identici; RSS letture224665600B,disco2782887936B, runtime940/940 in6,581s,zero perdite/GAP/rete,due PONG durabili. Indici finali inclusi nel disco. Probe successivo readonly del piano usa RAW e receipt COVERING e restituisce7620 righe in170ms: diagnostica, non sostituisce il p95 negativo. Soglie immutate; worker60 ripreso dopo il gate, sette finestre pubblicate al controllo intermedio, tail ancora in corso. JUnit completo corrente comprende412 casi dei dieci moduli mirati; non è dichiarato un run mirato separato412.

**Checkpoint intermedio del profiling:** `chore: checkpoint SP3 Task2 profiling and bounded reads`. Conserva codice, piano e programma con Task2 IN CORSO; push soltanto al branch Task2/gate SHA, nessun FF o Task3. Le misure60 e la sostenibilità restano da completare; il commit non registra il proprio SHA.

**Probe successivi al checkpoint `92590d97ee1bde13cbb593b0196028d38996524b`:** `profile-queries-current-v7.log` diagnostico,p95803,546ms sulle venti query,senza DML/rete; worker60 isolato durante freeze untimed e ripreso in finally. `probe-query-phases-v7.log`: query1/18/20 con RAW e receipt COVERING,execute1,844/1,004/0,818ms e fetch823,237/701,823/139,895ms. Il costo SQL residuo è osservato anche prima della decodifica; nessuna misura favorevole isolata sostituisce il gate20 FAIL. Variante codec RAM non adottata: circa0,02s su20000 righe senza tutti i controlli finiti,nessuna prova sufficiente del target. Codice e soglie invariati dopo la suite2138; scala60 completa ancora in esecuzione.

**Ri-misure corrette 2026-10-14:** runner scratch RED3/GREEN4 e re-review PASS; timer delle venti query comprende tutte le verifiche originali, ogni finestra confronta ID/digest/count del log originale. `isolated-v8-5.log` PASS: p95 150,942ms, open+replay22,786s, RSS418332672B, disco484048896B. `isolated-v8-20.log` FAIL: p95 760,325ms, finestre27,249/37,425/53,107/67,576s, bundle165,369s con tutti i child e915131 occurrence/checksum identico; RSS letture225091584B, disco2782887936B. Runtime940/940, zero perdite/GAP/rete e due PONG durabili su entrambe; niente soglie ridotte. Worker60 ripreso dopo le misure, 11/12 finestre pubblicate; esecuzione completa e recheck corrente60 ancora pendenti. Codice invariato dopo suite2138; il GREEN4 del runner scratch è distinto dai test backend. Task2 IN CORSO, Task3 NON INIZIATO, nessun FF.

**Esito finale delle misure corrette, 2026-10-14:** codice prodotto al checkpoint `92590d97ee1bde13cbb593b0196028d38996524b`,199 mirati/2138 backend PASS; GREEN4 del runner scratch separato dopo RED3/re-review. Nessuna nuova modifica al prodotto dopo la suite completa.

| Scala | Fixture BAR/QUOTE | p95 query (limite250ms) | Open+replay massimo (limite60s) | Bundle20 completo (limite60s) | RSS B | Disco B | Esito |
|---|---|---|---|---|---|---|---|
| 5 | 53100/53100 | 150,942ms | 22,786s | — | 418332672 | 484048896 | PASS |
| 20 | 228600/228600 | 760,325ms | 67,576s | 165,369s,915131 occurrence | 225091584 (letture) | 2782887936 | FAIL |
| 60 | 696600/696600 | 1389,677ms | 111,860s | — | 432586752 (complessivo) | 12298117120 | FAIL |

Log finali:`isolated-v8-5.log`,`isolated-v8-20.log`,`current-final-60.log` nello scratch di verifica già indicato nel programma. Nuova apertura per ogni finestra e per bundle20 con tutti i child dentro il timer; tutti i replay/checksum completi, venti query per scala con gli assert originali dentro il timer, nessun handle prevalidato o campione ridotto. Tutti i conteggi/digest confrontati con i log originali; bundle20 invariato dopo revisioni future. Scala20 conserva la provenienza della ripresa: ingest completo/quattro child/bundle verificati, il solo job originale fu interrotto prima della summary. Non è dichiarata una nuova generazione20 integrale o un picco generazione20 misurato.

Scala60: dodici nuove aperture/replay39,647/39,350/51,472/65,693/75,128/87,890/105,118/111,206/111,860/101,707/104,207/101,978s,con count/digest originali identici; cinque indici finali verificati readonly. Source60 completa1393200 admission,nessuna quarantena,60 sedute/una mezza; crescita sorgenti per tutte le sedute51257344→2840793088B,disco finale incluse finestre/indici12298117120B. Peak sorgenti132599808B inferiore al massimo complessivo432586752B del freeze; nuovi reader185810944B al controllo intermedio. Budget32GiB e free512MiB rispettati. Runtime fake per ciascuna scala940 eventi/940 admission,zero perdite/GAP/rete,due PONG durabili,coda massima91/1000; durata5/20/60=6,806/6,678/6,503s. Nessun worker residuo o sospeso al termine. Tail originale60,p95 1839,562ms/replay123,789s,è una misura della versione precedentemente caricata e non sostituisce il gate corrente.

Task2 resta IN CORSO e la checkbox sostenibilità resta aperta; Task3 NON INIZIATO. Nessuna soglia250ms/60s/2GiB abbassata e nessun merge FF. Checkpoint documentale di consegna:`chore: checkpoint SP3 Task2 complete offline performance measurements`,push soltanto Task2/gate SHA; il commit non anticipa il proprio SHA. Prossimo:profiling dei fetch SQL e della validazione integrale,ottimizzazione verificata e nuovi gate completi prima del commit finale/FF. Le misure di avanzamento precedenti sono storiche.

**Commit finale dopo sostenibilità:** `perf: bound intraday timeline and dataset reads`

Ulteriore prova scratch non adottata: cache SQLite volatile16MiB,stesse venti query e controlli offline,`profile-query-cache16m.log` p95 diagnostico854,041ms. Non dimostra miglioramento o PASS; nessuna configurazione cache del prodotto modificata e nessuna soglia ampliata.

**Ripresa corrente 2026-10-14 dal checkpoint `b0acdc3d02a60f60b1a35d0ac9eb2ebe0848be16`:** fetch RAW tardivo con CTE di soli ID, receipt visibile prima del lookup completo, stessi controlli prima dei bounds event-time; scansione dependencies snapshot/bundle limitata agli array non vuoti tramite indice parziale esistente. Nessun nuovo indice/formato/cache/dipendenza. RED1 previsto sul piano SQL e GREEN63 store; RED2 sugli indici dependencies e GREEN172 store/reader/bundle. Suite completa fresca2142 PASS (`resume-20261014/full.xml`,742,58s),115 nuovi su Task1 e4 sul checkpoint precedente; zero failure/error/skip e rete inattesa, due self-test intenzionali. Ruff/pip/scanner15/diff PASS. Review read-only del delta e root senza rilievi:180 confronti/360 chiamate contro b0acdc3 equivalenti, tre probe RAW/receipt/bounds e due dependencies/index, sei forme di dependencies malformate respinte prima di snapshot/bundle e senza DML nei GET.

Nuova misura integrale5 PASS: p95=199,331ms, apertura/replay32,942s,53100 BAR/QUOTE,212636 occurrence/checksum invariati,RSS418332672B/disco484048896B. Nuova misura20 FAIL: p95=1080,650ms,finestre37,102/53,060/82,253/76,995s,bundle184,987s con tutti i child e915131 occurrence/checksum invariati,BAR228600/QUOTE228600/NEWS2,RSS letture223461376B/disco2782887936B. La query-only20 diagnostica225,143ms non sostituisce il gate integrale negativo; l'A/B SQL precedente era ordinato old→new e non prova un miglioramento stabile su cache fredda. Profilo cProfile bundle separato dai gate: costi principali apertura/idratazione/ordinamento; varianti decoder/encoder non adottate per guadagno insufficiente con tutti i controlli.

Nuova misura60 completa FAIL (`resume-20261014/gate-60.log`):30 listing,696600 BAR/QUOTE,12 nuove aperture/replay con conteggi e checksum identici;tempi60,486/71,243/68,739/96,893/116,923/114,328/167,117/143,267/148,422/162,898/118,735/165,714s,p95=1122,793ms,RSS432586752B/disco12298117120B. Crescita sorgenti60 misurata51257344→2840793088B. Tutte le scale:20 query originali con assert nel timer,runtime940/940,zero perdite/GAP/rete,due PONG durabili,coda91/1000,budget32GiB/free512MiB rispettati. Fixture completi riutilizzati,nessuna validazione o checksum escluso dai timer;20 mantiene il limite storico di provenienza già documentato,picco storico di generazione20 ignoto. Runner tutti conclusi,nessun processo residuo/sospeso. Review metodologica PASS. Checkpoint `chore: checkpoint SP3 Task2 late RAW lookup and offline gates`,push solo Task2 e gate SHA;nessun FATTO/FF/Task3. Prossimo:diagnostica A/B bilanciata e ottimizzazione del percorso complessivo di validazione/ordinamento,poi tutti i gate invariati;questo delta funzionalmente equivalente non dimostra il miglioramento stabile richiesto.

**Ripresa dal checkpoint `5a03a0b88bdc2020c1507a25f6f291ade45893fe` (2026-10-14):** ranking bundle per identità/rango canonico, sort dei soli locator interi e fetch reference tardivo; conteggio e duplicati su chiavi typed (audit inclusi), sesto indice additivo `idx_intraday_dataset_member_replay_keys`. Cursor member sulle18 colonne utilizzate; canonical proof riusata soltanto dopo promozione del child, mantenendo76B per voce e64MiB complessivi, SHA member/digest/header/FK/publication/closure sempre verificati. Codec stdlib C per il caso normale e fallback finito per309 cifre/runtime senza encoder. Fence sensibile legge i valori correnti senza allocare coppie a ogni hit; TEMP archive shadow rifiutato a ogni fence, incluse view/case/rollback ABA, scratch timeline_* lecite. Nessuna nuova dipendenza/cache persistente/formato e nessuna modifica al database reale.

TDD RED previsti su ranking/proof/cursor/codec/locator/count/indice/TEMP/duplicati/fence, GREEN143 reader/bundle (`resume-20261014b/fence-green.xml`),103 reader/snapshot dopo duplicate scan e5 TEMP dopo RED2 rollback ABA. Suite backend completa fresca **2176 PASS**,822,40s (`full-final.xml` nello stesso scratch),34 nuovi sul checkpoint e149 su Task1; zero failure/error/skip/rete inattesa e due self-test intenzionali. Ruff/pip/scanner15 PASS, review read-only/root senza Critical/Important residui; corpus617 e probe float/int64/audit/dependency/promotion/evizione/TEMP/getter PASS. Frontend e dipendenze invariati, build omessa; due deprecazioni preesistenti.

Diagnostica A/B SQL bilanciata separata dai gate: ranking20,124–21,159→14,171–16,799s; sort locator30,111–31,539→23,266–24,682s sulle915131 reference in ordine identico; duplicati0,961–1,532→0,481–0,489s. Varianti GROUP anchor e RAW covering non adottate perché senza vantaggio stabile. Preparazione sola DDL sulle tre fixture DEMO/SYNTHETIC, total_changes0, sei indici inclusi nel disco5/20/60=489512960/2826297344/12535291904B. Runner prepara anche il sesto indice; gate completi nuovi conclusi in sequenza con fresh conn/scope, tutti i child/replay/checksum/assert nei timer. Cache OS non svuotata, limite storico/picco generazione20 ignoto conservato: RSS20 è delle sole letture. Soglie e campione invariati, nessun FATTO/FF/Task3 prima del PASS complessivo.

Nuovi esiti sul reader aggiornato (`resume-20261014b/gate-{5,20,60}.log`):

| Scala | p95 query (limite250ms) | Open+replay massimo (limite60s) | Bundle20 completo (limite60s) | RSS B | Disco B | Esito |
|---|---|---|---|---|---|---|
| 5 | 288,390ms | 35,640s | — | 418332672 | 489512960 | FAIL |
| 20 | 637,045ms | 77,578s | 164,951s,915131 occurrence | 224120832 (letture) | 2826297344 | FAIL |
| 60 | 2501,072ms | 149,170s | — | 432586752 | 12535291904 | FAIL |

Tutte17 finestre e bundle20 con count/checksum originali identici; BAR/QUOTE53100/228600/696600 sulle tre scale, NEWS2 nel bundle. Scala60 dodici aperture/replay29,466/28,356/41,073/96,206/104,672/118,061/149,170/82,504/75,442/75,932/74,557/71,118s; crescita sorgenti60 misurata51257344→2840793088B. Runtime940/940 per ogni scala,zero perdite/GAP/rete,due PONG durabili,coda91/1000,lag sintetico0,tempi9,209/5,024/10,093s. RSS/disco/budget32GiB/free512MiB rispettati nelle misure disponibili, limite storico20 conservato. Tutti i runner conclusi.

I guadagni dei singoli sort/codec non bastano al percorso integrale. Profilo strumentato separato:915751 sorgenti decodificate,2532849 evidenze all'apertura e5989513 scope check nel bundle. Prossimo: misurare fetch/validazione delle sorgenti uniche e receipt e ridurre passaggi duplicati, mantenendo tutti i controlli e senza dedurre un PASS da microbenchmark. Task2 IN CORSO e sostenibilità aperta; nessun Task3 o FF. Checkpoint `chore: checkpoint SP3 Task2 canonical proofs and locator reads`, con programma/piano/codice nello stesso commit, push soltanto Task2 e gate remoto SHA; il proprio SHA sarà registrato dal passo successivo. Nessuna cattura live, credenziale, ordine o paper.

**Ripresa dal checkpoint `e32163875be411d662d233243c169d41ed65cbe2` (2026-10-14):** visibilità in batch bounded e classificazione dipendenze evitata soltanto per righe owned già validate nella stessa scope; reducer pubblico e namespace diverse conservano tutti i controlli. Iterazione chunk privata con fence prima/dopo hydration, dopo newslinks e prima di ogni output pubblico; iter_rows pubblico conserva il fence per riga. Nessun formato/indice/cache/dipendenza nuovi. RED1/20/3/1 previsti, GREEN332 sui cinque moduli reader/datasets/replay/snapshot/store (`resume-20261014c/chunk-green.xml`), zero rete inattesa. Review read-only/root senza Critical/Important,766 differenziali reducer e fault/sospensioni/parità byte/cap. Il primo setup del test CONTROL falliva nella fixture; la prova valida è `public-red-v2.xml`, seguita dal GREEN.

Profiling SQL completo separato dai gate: apertura bundle110,885s/totale194,796s con tutte915131 occurrence e hash originale. Fetch member/preflight/RAW in apertura6,439/4,503/4,693s: il costo non si risolve eliminando soltanto il doppio fetch. Probe receipt-key narrow A/B senza vantaggio stabile, non adottato; microbenchmark visibilità200000 righe0,286–0,288→0,144s con stessa impronta, senza dedurre miglioramenti integrali. Review strutturale:919022 fetch RAW in open contro915131 occurrence finali; il riuso è già vicino a una validazione per sorgente distinta. Il doppio `_children` del freeze è fuori dal timer. Bitmap union, rimozione del duplicate scan root e helper threads restano ipotesi non adottate, senza prova di beneficio integrale e con obbligo di preservare budget/vincoli/fallback.

Nuovi gate completi sullo stesso codice (`resume-20261014c/gate-{5,20,60}.log`):

| Scala | p95 query (limite250ms) | Open+replay massimo (limite60s) | Bundle20 completo (limite60s) | RSS B | Disco B | Esito |
|---|---|---|---|---|---|---|
| 5 | 199,882ms | 23,810s | — | 418332672 | 489512960 | PASS |
| 20 | 886,257ms | 72,435s | 174,857s,915131 occurrence | 224313344 (letture) | 2826297344 | FAIL |
| 60 | 3274,402ms | 164,460s | — | 432586752 | 12535291904 | FAIL |

Tutte17 finestre e bundle20 con count/checksum originali identici,20 query originali/assert nei timer per scala. Nuove connessioni/scope, tutti i child e ogni riga/checksum inclusi; cache OS non svuotata, provenienza20/picco generazione20 ignoto conservati. Finestre60:58,308/53,766/50,125/73,571/98,546/135,924/164,460/135,013/156,943/150,453/159,620/149,517s. Runtime940/940,zero perdite/GAP/rete,due PONG durabili,coda91/1000,lag sintetico0,tempi5/20/60=6,801/10,618/7,761s; crescita sorgenti60 misurata51257344→2840793088B,budget32GiB/free512MiB rispettati. Task2 IN CORSO, sostenibilità aperta, nessun FF o Task3. Soglie250ms/60s/2GiB e campione invariati.

Suite backend finale fresca **2214 PASS**,881,35s (`resume-20261014c/full-final.xml`),38 nuovi sul checkpoint e187 su Task1; zero failure/error/skip/rete inattesa,due self-test intenzionali. Ruff/pip/scanner16/diff/scope e review read-only/root PASS. Audit indipendente dei report/JUnit `collect_evidence.py` PASS,17 finestre/bundle e20 query per scala; nessun risultato pendente dichiarato PASS. Due warning preesistenti,frontend invariato/build omessa. Checkpoint di consegna:`chore: checkpoint SP3 Task2 batched validation and chunk fences`,codice/piano/programma nello stesso commit,push soltanto Task2/gate SHA e nessun FF; proprio SHA nel passo successivo. Prossimo:ridurre il costo della validazione e dell'ordinamento integrali con beneficio misurato,poi ripetere TDD/gate invariati prima della chiusura. Nessuna attività live,credenziale,ordine o paper.

Ulteriore esperimento SQLite,nessuna modifica al prodotto: ABBA threads0/4/4/0 sul solo ordinamento/fetch/checksum delle915131 reference,stesso hash per tutte,31,708–47,071s con0 contro18,221–20,566s con4,picco152367104B/zero DML/rete. La verifica completa30×20 con4 thread solo in RAM (`probe-full-threads.log`) resta FAIL:p95856,184ms,finestre33,544/48,438/74,292/78,944s,bundle141,477s includendo tutti i child e915131 occurrence/hash originale;RSS letture225828864B,zero DML/rete/perdite/GAP. Non dimostra il miglioramento complessivo necessario: configurazione non adottata,gli esiti standard sopra restano quelli del checkpoint. Tutti i runner conclusi,nessun worker di test/gate/profiling residuo.

**Ripresa dal checkpoint 3edd796 (2026-10-14):**

- HEAD/origin Task2 precedente `3edd796077d78fbbcf97ac3b36aec8d62021d830`; main remoto/Task1 `7b708706c70a4d37d01bc10b73af299bc2052e25`. Root unico writer. Autorizzazione utente acquisita per il prototipo nei soli `backend/app/intraday/_reader_native.c`, `backend/pyproject.toml`, `tests/test_intraday_native_reader.py`; adozione subordinata a parità byte, review e gate completi invariati. Il codice prodotto non importa il modulo nativo: percorso Python preservato.
- Nuovo controllo closure per reference già promosse nel medesimo epoch: riusa il binding attestato dal child precedente e verifica in batch la membership della receipt nel child corrente, anche audit. Ogni member/receipt del child corrente conserva validazione canonica/SHA, typed FK, clock, namespace, pubblicazione, digest e count prima dell'handle. RED1 previsto (`red.xml`), GREEN175 reader/bundle/snapshot (`green-v2.xml`), tre regressioni nuove su riuso, receipt assente e body corrotto; review read-only/root senza difetti concreti.
- Prototipo opzionale: codec/certificato canonico conservativo con fallback all'oracolo Python, SHA ricalcolata, selezione/ranking market, verifica integrale RAW/receipt prima dei bounds, cursore sulla stessa connessione SQLite. Nessuna cache persistente o globale dei valori, `cache_strings=False`. Il cursore sperimentale usa ABI privata CPython3.14.7 Windows64, tipo/layout/conversione/owner verificati: rifiuta i contesti non supportati, la futura integrazione dovrà scegliere il fallback. Build e test opzionali non sono richiesti dal percorso Python.
- TDD e review del prototipo: RED su metodo assente/parità e quattro bounds NaN; tre PRAGMA respinti prima di prepare per impedire effetti di preparazione, statement finalizzato/esaurito dopo errore senza riesecuzione, adapter builtin registrati rifiutati prima della query. RED effettivi in `pragma-red.xml`, `query-review-red.xml` (step), `adapter-red.xml`; GREEN58 `native-v4.xml`, riconfermato58 dopo compilazione rigorosa del sorgente finale (`native-final.xml`), corpus float/Unicode/revisioni/corruzione, snapshot WAL, transaction e owner/authorizer inclusi. Re-review indipendente dei tre fix con probe RAM PASS, nessun Critical/Important residuo nel perimetro verificato.
- Build offline da copie dei due sorgenti autorizzati nello scratch: LLVM-mingw già disponibile, setuptools84 locale, wheel installata soltanto nel venv ignorato, nessun download o binario in Git. `backend/pyproject.toml` descrive solo il pacchetto opzionale; la configurazione ext-modules è sperimentale in setuptools. Compilazione C rigorosa con `-O3 -Wall -Wextra -Werror` PASS. Suite fresca `run_offline_tests.py -q -o addopts= -p no:cacheprovider tests`: **2275 PASS**,716,42s (`full.xml`),393 mirati (`targeted.xml`),61 nuovi sul checkpoint/248 su Task1. Zero failure/error/skip/rete inattesa, due self-test intenzionali. Ruff/pip/scanner20/diff/scope PASS, tre classificazioni AST esatte e rifiuti ABI/test negativi classificati puntualmente. Due warning preesistenti; frontend invariato, build omessa.
- Diagnostica nativa separata dai gate: primo wrapper codec senza riuso `_member_scope`, totale175,532s, non confrontabile con il reader completo. Verifica corretta che preserva il riuso (`native-bundle-scope.log`): apertura121,628s, replay66,061s, totale187,689s; tutte915131 occurrence e checksum originale, zero DML/rete. Non dimostra adozione o PASS, mancano i gate completi del prototipo. Varianti packing/covering/receipt partition/cache non adottate. I tre indici scratch sperimentali sono stati rimossi senza toccare le sorgenti; il disco60 del gate include conservativamente le pagine libere rimaste, nessun VACUUM.
- Gate standard nuovi sul prodotto effettivo, in processi separati dopo la suite e la diagnostica, senza sovrapporre benchmark pesanti:

| Scala | p95 query ms (limite250) | Open+replay max s (limite60) | Bundle20 s (limite60) | RSS B | Disco B | Esito |
|---|---|---|---|---|---|---|
| 5 | 235,510 | 25,549 | — | 418332672 | 489512960 | PASS |
| 20 | 861,019 | 63,072 | 179,907 | 222097408 (letture) | 2826297344 | FAIL |
| 60 | 1318,956 | 133,217 | — | 432586752 | 14413910016 | FAIL |

- Tutte17 finestre e bundle20 con conteggi e checksum originali; 915131 occurrence nel bundle, BAR228600/QUOTE228600/NEWS2. Ogni timer comprende nuova apertura, tutti i child/controlli e replay/checksum completi; venti query/assert originali dentro il timer per scala. Nuove connessioni/scope, cache OS non svuotata, fixture complete riutilizzate; provenienza20/picco storico di generazione20 ignoto conservati, RSS20 riguarda le letture. Runtime940 eventi/940 admission per scala, zero perdite/GAP/rete, due PONG durabili e coda91/1000; budget32GiB/free512MiB rispettati. Finestre20: 31,742, 45,501, 60,319, 63,072s; finestre60: 51,580, 48,020, 56,817, 73,555, 86,608, 133,217, 121,846, 122,042, 83,738, 72,480, 72,403, 69,199s. Crescita sorgenti60 misurata51257344→2840793088B. Audit indipendente dei report/JUnit (`collect_evidence.py`, `evidence.json`) PASS. Prove sotto lo scratch `sp3-task2-verification/resume-20261014d` già registrato.
- Task2 resta IN CORSO: sostenibilità non superata, nessun FATTO/FF/Task3. Soglie250ms/60s/2GiB e campione invariati. Checkpoint `chore: checkpoint SP3 Task2 native reader prototype and offline gates`, codice/piano/programma nello stesso commit, push solo Task2 e gate remoto SHA; proprio SHA nel passo successivo. Prossimo: verificare un batch C su dati già letti dal DB-API standard, entro1000 reference/2MiB, dell'intera validazione member/sorgenti; oracolo, fence prima/dopo batch, flag PENDING/promozione dopo il child, fallback senza perdita o duplicazione di righe/digest e memoria64MiB/8MiB preservati. Il beneficio resta un'ipotesi da misurare; ripetere tutti i gate prima della chiusura. Nessuna raccolta live, credenziale, DB reale, ordine o paper.

### Proposta Task2: lettura per blocchi (approvata per l'esecuzione il 2026-10-14)

L'utente ha richiesto di procedere al completamento dopo la proposta B. Per questa esecuzione B è adottata con blocchi sigillati come fonte autorevole del nuovo formato `sealed-evidence-blocks-v3`, importati esclusivamente da job espliciti dopo validazione del reader originale. Il wrapper v3 conserva manifest, digest, report e ordine logico v1/v2 come input attestati; la sua seal separata identifica l'autorità nuova. Nessuna migrazione converte automaticamente gli archivi precedenti. Senza wrapper v3 resta il reader RAW precedente; l'audit dei RAW è distinto dalla validità delle copie sigillate. Estensione autorizzata: addendum spec§3.1, `backend/app/intraday/frozen_blocks.py`, `tests/test_intraday_frozen_blocks.py`, tabelle/indici/trigger additivi in database.py e relativi test di migrazione; integrazione nei file già autorizzati. Nessuna nuova dipendenza.

- [x] RED/GREEN sul formato: parità completa, appends e nuovi admission dopo il seal, corruzione con hash esterno ricalcolato, closure/namespace/clock, source authority, rollback/cancel, immutabilità/FK e limiti di decompressione.
- [x] Validazione fresca di tutti i blocchi/member/sorgenti e degli indici di dipendenza prima dell'handle; nessun risultato di validazione persistente considerato prova. Reader pubblico DB-API; acceleratore opzionale con fallback Python identico, senza cursore ABI privato.
- [x] Preparazione e disco misurati separatamente; i timer di lettura comprendono apertura nuova, tutti i child e validazione completa. Query archivio full-prefix comprendono la coda non sigillata, senza perdere revisioni o cambiare i venti casi originali.
- [x] Gate originali5/20/60,17 finestre,bundle915131 occurrence, suite offline/review e chiusura senza soglie ridotte. Le misure storiche sotto rimangono FAIL storici.

**Implementazione in verifica:** pool sorgenti deduplicato nel bundle, member originali di ogni child conservati; ogni snapshot autonomo conserva le proprie evidenze. Preparazione esplicita via `freeze_window(...,evidence_blocks=True)`, `freeze_bundle(...,evidence_blocks=True)` e import market. Il runner ufficiale prepara il formato, riporta separatamente costi/disco e include avvio/attesa dei tre worker readonly nella lettura del bundle grande. Tutti i passaggi sorgenti/child/timeline sono provvisori fino al PASS congiunto, alla concordanza dei conteggi e alla fence, senza riuso tra aperture; RAM2GiB comprende la somma conservativa dei picchi dei processi. Inventario sensibile non vuoto, transazione aperta, DB in memoria o nativo assente mantengono il percorso sequenziale completo. API nativa5/pubblico DB-API, build offline `-O3` senza fast-math e con warning strict; nessuna adozione del cursore ABI privato. V1/v2 restano RAW, anche se un child possiede un wrapper: conversione del bundle sempre esplicita.

TDD mirato309 PASS e quick funzionale20 sedute/3 listing concluso `NOT_EVALUATED_QUICK`, escluso dal gate; primo backend2328 PASS/1 FAIL riprodotto e corretto sul `row_factory` delle query as-of. Seconda suite completa **2344 PASS**,606,371s da JUnit (`full-v29.xml`), zero failure/error/skip/rete inattesa e due self-test intenzionali; ultimo focus69 PASS (`final-focused.xml`). Preparazione5/20/60 completa, conteggi RAW immutati, picco di preparazione148791296B. Prove in `sp3-task2-verification/blocks-20261014`. Il checkpoint precedente verificato è b3013b03909e31550704edbca5243be7143d1558; main rimane Task1.

**Gate ufficiali v29, build nativa API4 strict, processi separati/sequenziali dopo la suite:**

| Scala | p95 query ms (limite250) | Open+replay max s (limite60) | Bundle20 s (limite60) | RSS B | Disco B | Esito |
|---|---|---|---|---|---|---|
| 5 | 14,332 | 11,110 | — | 418332672 | 724058112 | PASS |
| 20 | 57,564 | 30,530 | 66,619 | 421834752 | 8919609344 | FAIL |
| 60 | 315,579 | 63,868 | — | 432586752 | 21591322624 | FAIL |

Tutte17 finestre e bundle915131 occurrence conservano count/checksum originali; venti query full-prefix/assert originali nel timer per scala. Avvio/attesa dei worker, validazioni integrali e checksum inclusi. Runtime fake940 eventi/940 admission,zero perdite/GAP/rete,due PONG,coda91/1000,lag sintetico0; RAM dei worker aggregata conservativamente, budget32GiB/free512MiB rispettato. Fixture originali complete riutilizzate; cache OS non svuotata e picco storico della generazione20 ignoto, come nei gate precedenti: RSS20 misura le letture correnti. Questi risultati prevalgono sulla diagnostica55,754s precedente agli ultimi fix.

Profilo completo SOURCES46,304s, batch C15,728s e binding SQL6,701s. Prova di cursori tuple-only ritirata: misura97,003s con batch C invariati37,149s, confronto inconcludente. ABBA di affinità soltanto nei processi diagnostici, mai adottata nel prodotto/gate: p95 default273,686/249,935ms e core più veloci294,078/239,177ms; tutti gli80 digest query identici. Variabilità da approfondire senza attribuire automaticamente il costo a una singola modifica. Candidato certificato numerico con129 test verdi ritirato dopo ABBA senza beneficio stabile; nessun cambio GC, affinità, priorità o policy energetica adottato. Task2 resta IN CORSO, nessun FF/Task3.

**Checkpoint operativo:** `chore: checkpoint SP3 Task2 sealed blocks and unchanged gates`. Ultimo mirato sul codice ripristinato311 PASS (`targeted-checkpoint-v31.xml`,100,52s), rete inattesa0; le due nuove prove numeriche restano come differenziali sull'oracolo originale. Ruff/pip/scanner23/diff/scope e review funzionale root senza Critical/Important; gate prestazionale negativo dichiarato separatamente. Push solo Task2 e gate SHA/worktree pulito dopo commit; nessun proprio SHA nel contenuto, nessun FATTO/FF/Task3. Proseguire sullo stesso branch con diagnosi, TDD e gate5/20/60 invariati.

**Ripresa 2026-10-15 dal checkpoint `e4e36e7b40c526481c8de69ae167c72c2c29179a`:** parametri SQL/unione del blocco corrente preparati dal batch nativo API5 sulle sole evidenze appena validate, stesso SQL e fallback Python; RED3/GREEN132. L'inventario dei metadati è verificato una volta nella singola apertura e riusato soltanto a parità di epoch/set/seal; la scope viene eliminata prima dell'handle. Corpi/SHA/sorgenti/member/closure sono sempre freschi. RED3 su modifiche body/metadati/seal tra domini, GREEN320; ulteriore RED1 sul confine seal1MiB e fix senza ridurre il cap. Ultimi321 mirati PASS (`targeted-v36.xml`,47,14s), rete inattesa0. Il caso anchor iniziale aveva un'aspettativa errata nella fixture: reducer v1 preservato, differenziale corretto incluso nei mirati; non è un bug corretto del prodotto.

Profilo API5 separato dai gate: SOURCES88,722s/bundle completo91,598s sotto condizioni variabili,915131 occurrence/checksum originale; nessun PASS dedotto. Prova QoS solo nello scratch ripristinata, non risolutiva e non adottata. Suite `full-v35` invalida per esaurimento di C: (0B liberi), nessun risultato usato come gate. Rimosse esclusivamente le copie temporanee verificate `full-v24-temp`, `full-v29-temp` e `full-v35-temp`, preservando log/JUnit e fixture dei gate; circa19GB recuperati. Suite `full-v36` conclusa2356 PASS/590,25s; gate5 PASS (p9514,183ms/replay11,625s),20 FAIL soltanto bundle64,376s (p9561,481ms/window30,563s),60 PASS (p95224,182ms/replay50,072s). Soglie e campione invariati.

**Ottimizzazione successiva:** la timeline del bundle è verificata da un terzo worker provvisorio, composto con i controlli integrali delle sorgenti/locator e dei child. Nessuna verifica eliminata; tutti devono passare con stessa root/header/digest e conteggio concorde prima dell'handle. Il preflight metadata usa anche il limite512MiB del singolo worker. RED3 (ruolo mancante, due soli worker, parsing prima del budget), GREEN142 sui moduli frozen/native; aggiunti casi negativi di composizione e invalidazione senza cambio schema. Gate completo20 `gate-v37-20.log` PASS: p9559,926ms,window30,251s,bundle55,720s,RSS540106752B,disco8919609344B,915131 occurrence/checksum originale,runtime940/940,zero perdite/GAP/rete. Ulteriore RED1 sulla duplicazione delle colonne market dopo riparazione degli hash esterni: rifiuto esplicito, GREEN140 precedente. Review finale e suite/gate5/20/60 sul codice aggiornato ancora da completare; Task2 IN CORSO.

**Chiusura Task2 — evidenza finale v38, 2026-10-15.** Tutti i gate seguenti PASS sul codice finale, dopo suite completa e in processi sequenziali senza profiler o altri test concorrenti. Le misure v29–v37 sopra sono storiche; nessuna soglia o denominatore ridotto.

| Scala | p95 query ms (limite250) | Open+replay max s (limite60) | Bundle20 s (limite60) | RSS B | Disco B | Esito |
|---|---|---|---|---|---|---|
| 5 | 14,577 | 11,293 | — | 418332672 | 724058112 | PASS |
| 20 | 59,837 | 30,320 | 54,199 | 538877952 | 8919609344 | PASS |
| 60 | 216,307 | 50,281 | — | 432586752 | 21591322624 | PASS |

`run_offline_tests.py tests -q -o addopts= -p no:cacheprovider` = **2364 PASS**,612,93s (`full-v38.xml`),337 oltre Task1; cinque moduli mirati = **329 PASS**,53,34s (`targeted-v38.xml`). Zero failure/error/skip e tentativi esterni inattesi; due self-test intenzionali della guardia nel completo. I cinque nuovi casi negativi del coordinatore sono inclusi nei329: ogni ruolo deve passare, conteggi diversi o bool rifiutati. Ruff `check backend scripts tests --no-cache`, pip check e review finale root del diff PASS, nessun Critical/Important residuo; scanner23 con self-test e tre classificazioni AST esatte, diff/scope PASS sul contenuto documentale finale. Due warning preesistenti Starlette/httpx/HTTP422; frontend invariato, build/test frontend non ripetuti.

Audit indipendente dei report `collect_final.py` PASS:17 finestre con ID/count/checksum originali,20 query full-prefix originali e assert dentro il timer per scala, bundle915131 occurrence/hash `20aaa7a090e8e2870ab3dd845128e9b1286ff7bd6c2cfc32d9f0d0e030616059`,BAR/QUOTE228600 eNEWS2. Timer comprensivi di apertura nuova, tutti i child, verifica sorgenti/locator/closure/timeline, avvio/attesa dei worker e replay/checksum JSON standard. Runtime fake940/940,zero perdite/GAP/rete,due PONG,coda91/1000,10 batch con checkpoint/status/reconcile,lag sintetico0; tempi5/20/60=5,353/5,365/5,000s. RAM worker aggregata conservativamente; budget32GiB/free512MiB rispettato.

Preparazione iniziale dei blocchi misurata separatamente (`prepare-all-v24.log`): somme delle fasi5/20/60=53,646/280,870/2075,250s, picchi142135296/144850944/148791296B; conteggi sorgenti conservati. Le fixture complete sono riutilizzate, con limite storico20 invariato: ingest e bundle verificati, picco della generazione originale20 ignoto; RSS20 qui misura la lettura corrente con worker. Aperture/connessioni nuove, cache OS non svuotata. CPython3.14.7/SQLite3.50.4 Windows64, nativo API5 strict `-O3` senza fast-math; hash sorgente `d0900ea95effd494ea975d27bd15b4c8c1d71c553ac66b92767f061c0e0f1c54`, binario installato uguale alla build strict v34 verificato dall'audit. Fallback Python funzionalmente verificato; questi tempi non attestano lo stesso SLO senza acceleratore o su altro hardware.

Task2 FATTO nello stesso commit `perf: bound intraday timeline and dataset reads`: programma/checkbox aggiornati e prossimo Task3 quote-size/tick NON INIZIATO, base origin/investedge/sp3-task-2. Checkpoint precedente e4e36e7 registrato, nessun proprio SHA anticipato. Push del solo Task2/gate SHA e FF main non forzato/gate SHA sono le verifiche post-commit autorizzate, con esito nella consegna e SHA registrato dal prossimo task. G1_DATA INSUFFICIENTE e G2 NON VALUTATO; nessuna raccolta live, credenziale, DB reale, ordine, paper, leva o spesa.

**Evidenza storica seguente, precedente all'approvazione B:**

La spec vigente e i gate di rilascio restano invariati:5 PASS,20/60 FAIL. Nessun codice di produzione modificato in questa indagine. Checkpoint precedente `ec21b810d3c27987ff50dd58cb5e795179b87d43`, verificato sul remoto; main resta Task1.

**Nuova evidenza diagnostica:** sulla fixture originale30 listing/60 sedute, stesso insieme delle20 query QUOTE full-prefix, confronto Python→blocchi→blocchi→Python. P95 Python723,002/723,761ms; blocchi211,334/259,812ms. Tutti gli assert originali dentro il timer e hash dei risultati completi identici per tutti i confronti. Preparazione fuori dal timer:464400 coppie RAW/receipt,10,133s,file blocchi su disco463212544B, blocchi256 righe,255745B codificati/532280B input decodificato massimi. Letture con SHA del blocco e controllo canonico/hash/binding/clock/ranking del reader nativo esistente; non usato il cursore ABI privato. Blocco alterato respinto; ulteriori due probe con SHA del blocco ricalcolata respingono RAW payload_hash errato e receipt con observation_id incoerente. Zero modifiche alle sorgenti, zero rete; database del prototipo solo nello scratch.

Queste misure non sono un PASS del gate attuale: il prototipo usa una copia preparata dei dati e non implementa pubblicazione, closure e validazione completa dei child/bundle, copertura/staleness rispetto all'archivio o il protocollo di sorgente autorevole. Una delle due ripetizioni manca ancora250ms. Prove: `sp3-task2-verification/solution-20261014/{probe_query_blocks.py,query-blocks.log,check_blocks.py,block-negative.log}` sotto lo scratch già registrato. La preparazione non può essere nascosta fuori dal timer come cache di prove validate.

**A — Contratto corrente, senza nuova fonte:** batch C sull'intera catena di member/sorgenti/receipt, DB-API standard sulla connessione corrente, RAW SQLite rivalidati a ogni apertura e nessun riuso persistente di prove. Stessi limiti1000 reference/2MiB, LRU64MiB, chunk8MiB/10000 e RSS2GiB. Il beneficio necessario non è ancora dimostrato; il solo codec non basta. Provare prima i due casi discriminanti:20 query60 full-prefix con p95≤250ms e nuova apertura+validazione completa+replay/checksum del bundle30×20≤60s. Solo dopo parità e queste prove, suite completa e tutti i gate5/20/60.

**B — Cambio di formato raccomandato, da approvare:** blocchi di evidenze congelate autocontenuti e versionati, con RAW originali, receipt, riferimenti, namespace, clock e hash; indice dell'ordine causale e dell'unione esatta preparato dai job. Pubblicazione atomica solo dopo verifica completa, checkpoint/cancel e budget; GET in sola lettura, verifiche logiche equivalenti sulle evidenze dei blocchi e decoder/validator C a batch. SQLite BLOB tramite API pubbliche, inizialmente con le dipendenze già presenti; nessuna necessità di adottare l'ABI privata CPython. Blocchi condivisi fra finestre e riferimenti compatti per limitare la duplicazione del warm-up.

La decisione materiale per B è l'autorità della fonte: un blocco sigillato può essere evidenza autorevole del nuovo formato, oppure deve restare una replica verificata contro i RAW originali a ogni lettura. Nel secondo caso la sola materializzazione non elimina quel costo. Per le query sull'archivio deve essere definita e verificata la copertura del prefisso e la gestione di nuovi admission/coda; un reader limitato ai soli dataset congelati non sostituisce il gate corrente su `store.read_as_of`. V1/v2, byte/digest pubblicati e i loro controlli restano compatibili. Nuovo formato e audit dei RAW originari devono essere distinti esplicitamente nella spec, senza trasformare il FAIL storico in PASS.

**Perimetro proposto per B, non ancora autorizzato:** addendum spec§3.1 e pianoTask2; estendere database.py dalle sole modifiche ammesse oggi a tabelle additive per blocchi/locator/seal; modulo nuovo `backend/app/intraday/frozen_blocks.py` e test `tests/test_intraday_frozen_blocks.py`; estendere i test di migrazione alle nuove strutture. Integrazione nei reader/freeze già ammessi e nell'acceleratore nativo. Niente migrazione distruttiva, cancellazione degli originali o nuove dipendenze nella prima prova.

**Criteri prima dell'adozione:** TDD e differenziali su tutti i byte/denominatori, cutoff, A→B→A, revisioni future, audit/closure e warm-up30/carry start−1; source authority/coverage/append/tamper espliciti, ogni hash/manifest/pubblicazione/FK/clock/namespace verificato; fence DB/segreti, fallback senza perdita o duplicazione di righe/digest, crash/rollback/cancel e limiti reali di memoria/disco inclusa la preparazione. Poi gate completi originali5/20/60, tutte17 finestre e bundle915131 occurrence. Soglie250ms/60s/2GiB, fixture30 simboli e query full-prefix restano uguali. Se falliscono, nessun FATTO/FF/Task3.

Fonti primarie consultate: [SQLite query planning](https://www.sqlite.org/queryplanner.html), [API pubblica sqlite3 BLOB](https://docs.python.org/3.14/library/sqlite3.html#sqlite3.Connection.blobopen). Supportano la fattibilità dei meccanismi, non garantiscono il guadagno del nuovo reader.

## Task 3 — Quote-size e incremento prezzo attestati point-in-time

**Branch:** `investedge/sp3-task-3`; **Base:** origin/investedge/sp3-task-2.
**Dipendenze:** Task2 FATTO/sostenibilità verificata.
**File nuovi:** `backend/app/intraday_research/quote_units.py`, `tests/test_intraday_quote_units.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `registry.py`, `datasets.py`; `tests/intraday_research_fixtures.py`, `tests/test_intraday_research_datasets.py`.

- [x] RED: ROUND_LOTS×100 implicito, SOURCE_UNATTESTED come shares, lotto/tick futuro cambia passato; scope errato, valid-time vs known-time, overflow/size zero/non intera; incremento prezzo UNKNOWN o rounding favorevole/oltre limite.
- [x] Implementare import locale esplicito quote-size-attestation-v1 e price-increment-attestation-v1 nelle tabelle Task1, fonte/hash/contratto/lotto/tick/scope/tempi/ref frozen. Nessuna attestazione automatica da flag libero o deduzione prezzo; authority con prova verificabile, non solo URL/hash. Conservare originali, derivati keyed per hash/ref. Rounding Decimal conservativo della spec§3.3, nessun centesimo default.
- [x] GREEN: conversioni a mano con due fattori di lotto e due incrementi prezzo sintetici diversi, nanosecondo al cutoff, A→B→A e first_received; UNKNOWN→zero fill/NON_IDONEO, synthetic non promuove G1. Bundle include attestazioni senza modificare digest dataset vecchi.
- [x] Mirati: test_intraday_quote_units/research_datasets/contracts/registry; regressioni store/replay/aggregate/snapshots, gate comune e review.

**Esecuzione 2026-10-15:** base Task2/main `5733c49aed2cfb15be2c734550c954799e138405` verificata dopo fetch; branch/lock Task3 pubblicato subito, root unico writer nel worktree gestito, checkout originale main96f7299 preservato. Solo i sette file di codice/test autorizzati sopra, piano/programma e precisazione della spec sul confine di fiducia locale. Nessuna nuova dipendenza, tabella o migrazione.

TDD: RED iniziale collection per modulo assente;24 GREEN iniziali. RED2 manifesto/RED2 wrapper bundle, poi integrazione nelle tabelle Task1 e riferimenti opzionali omessi dai manifesti legacy per conservarne gli hash. Regressione iniziale31 failure sui collegamenti ausiliari legacy riprodotta e corretta: non diventano authority implicite;265 core PASS successivi. Review RED3 su compatibilità/identità dei derivati, RED1 budget64MiB, RED1 disponibilità reale nell'hash, RED3 contratto raw USD/ID bool, RED1 Decimal con divisione periodica e trap ambientale;50 focus PASS. RED1/GREEN2 sul float oltre2^53 conserva invece gli int64 esatti. Primo completo interrotto perché avviato prima dell'ultimo fix, escluso dall'evidenza; copie temporanee proprie rimosse dopo verifica percorso/processi, log conservato. Suite sostitutiva `full-final-v2` avviata dopo il fix con hash dei sette file congelati.

**Gate finali PASS:**521 mirati estesi/230,79s prima dell'ultimo guard float, GREEN2 aggiuntivo sul guard finale. Completo fresco via `run_offline_tests.py tests -q -o addopts= -p no:cacheprovider` = **2418 PASS**,1077,71s (`full-final-v2.xml`),54 oltre Task2; include52 prove quote-size/tick e69 dataset/bundle. Zero failure/error/skip e tentativi esterni inattesi, due self-test intenzionali della guardia nel completo. Hash dei sette file di codice/test registrati prima dell'avvio e invariati alla fine, source mtime anteriore alla creazione del log. Ruff backend/scripts/tests, pip check, scanner10 con self-test/zero candidati inattesi/zero classificazioni, diff/scope e audit `collect_evidence.py` PASS. Root review funzionale senza Critical/Important residui. Due warning preesistenti Starlette/httpx/HTTP422; frontend e reader Task2 invariati, build frontend e benchmark5/20/60 non ripetuti per questo task metadata.

Import idempotente append-only, originali/namespace/authority/contratto/tempi conservati e riverificati alla lettura; hash dell'attestazione comprensivo della disponibilità effettiva, derivati quote/rounding legati anche agli input e al ruolo. Cache metadata64MiB con preflight prima del parse aggregato; nessun DML/clock/provider nelle letture. ROUND_LOTS senza prova e REST SOURCE_UNATTESTED restano UNKNOWN, entrambe le size quantitative a zero se manca size/tick. I float oltre2^53-1 non attestano quantità; gli interi esatti restano int64. Contesto Decimal isolato, cinque rounding conservativi e buy-limit verificato quando fornito; nessuna esecuzione simulata o reale aggiunta. Vecchi manifesti/digest dataset/bundle invariati; nuovi riferimenti tipizzati e contesto `attested-intraday-bundle-v1` con propria impronta.

Task3 FATTO nello stesso commit `feat: attest point-in-time intraday quote units`, con checkbox/programma/Prossimo passo aggiornati e SHA precedente5733c49 registrato. Push del solo Task3/gate SHA, FF main non forzato/gate SHA e worktree pulito sono verifiche post-commit autorizzate, con esito nella consegna; proprio SHA al task successivo. Solo pubblicazioni sintetiche: l'autenticazione della radice locale resta un prerequisito del configuratore, nessuna authority ufficiale o unità reale attestata automaticamente. G1_DATA INSUFFICIENTE/G2 NON VALUTATO. Prossimo Task4 daily PIT/feature/filtri NON INIZIATO, base origin/investedge/sp3-task-3. Nessuna raccolta live, credenziale, DB reale, ordine, paper, leva o spesa.

**Commit:** `feat: attest point-in-time intraday quote units`

## Task 4 — Daily point-in-time, feature e filtri

**Branch:** `investedge/sp3-task-4`; **Base:** origin/investedge/sp3-task-3.
**Dipendenze:** Task3 FATTO.
**File nuovi:** `backend/app/intraday_research/context.py`, `features.py`, `eligibility.py`; `tests/test_intraday_daily_context.py`, `tests/test_intraday_research_features.py`, `tests/test_intraday_research_eligibility.py`, `tests/test_intraday_research_boundaries.py`.
**File modificati:** `tests/intraday_research_fixtures.py`, `backend/app/intraday_research/contracts.py`, `datasets.py`.

- [x] RED: features_daily corrente usata, dailyBar progressiva conclusa, rettifica futura/overnight/gap/half-day/slot RVOL/benchmark future; finestre W−1 dichiarate complete, trailing join con barra 5/15m aperta, quote stale/status UNKNOWN/contesto insufficienti ammessi.
- [x] Implementare daily dalle precedenti sedute complete e feature/units/warm-up/filtri esatti §3.4/4. VWAP session reset, EMA/ATR truncated bounded, ROC/RVOL stessa fascia, RS mercato+settore as-of, event filters; niente score/ML/news legacy.
- [x] GREEN: OHLC/VWAP/EMA/ATR/ROC/RVOL/RS manuali; scalare/full/finestre equivalenti; mutation futuro append/change/remove su tutti input invariance bit-per-bit del prefisso; split reset, DST/half-day/calendario revisionato, covered-zero/news-disabled/UNKNOWN e causale known-time.
- [x] AST confini: nessun import features_daily/score/technical_analysis/ML/provider nella ricerca pura, nessun import ricerca dal livello dati. Mirati nuovi quattro moduli + aggregate/quality/boundaries/lab_features/feature_store; gate comune e review.

**Commit:** `feat: compute point-in-time intraday research features`

**Esecuzione e chiusura 2026-10-15:** base Task3/main `a8c39759ca9bf686415f8cdb497a2ec9d2da4e8f` verificata con fetch/status e SHA remoto; lock Task4 pubblicato subito. Codex unico writer nel worktree gestito, checkout originale96f7299 preservato. Nove file di codice/test autorizzati sopra, piano e programma; contratti e spec non richiedono modifiche. Nessuna dipendenza, schema, provider, API, frontend o percorso del reader Task2 cambiato.

`ResearchContext` consuma occurrence già validate e pubblicate; il raccordo `DatasetService.research_context` apre il bundle, usa esclusivamente il prefisso timeline-only, seleziona una seduta e30 precedenti, mantiene i metadati e soltanto le revisioni della quote più recente con limiti10000/8MiB. Nessun DML o espansione RAW. Working set numerico/metadata con addebito conservativo16× e tetto2GiB, contesti/revisioni LRU64MiB invariati; superamento→RESOURCE_LIMIT. I limiti dichiarati restano limiti del processo, non una misura di prestazioni su30 listing per l'intero campione SP3.

Daily solo dalle precedenti sedute integralmente coperte, status/continuità durabili, OHLC/volume/VWAP/dollar-volume e disponibilità effettiva dell'ultimo input; versione, ref calendario, membri e source digest dedicati. Una precedente seduta invalida non è sostituita da una più vecchia per livelli/gap/return5. Nessuna lettura delle tabelle daily correnti. EMA8/20 e ATR14 troncate/normalizzate, VWAP reset, ROC/RVOL per slot, RS su intervalli identici e join5/15m completi. Gap/status/split resettano segmenti e warm-up; notte collegata soltanto con copertura completa del calendario, inclusi giorni chiusi. Il budget numerico conserva al massimo30 sedute precedenti, nessun minuto fabbricato per notte o half-day.

Benchmark dal documento universo pubblicato prima dell'open oppure da un bundle precedente già pubblicato prima dell'open, con namespace/mapping/listing/digest/known-time verificati; il bundle retrospettivo non prova quella scelta e da solo lascia RS mancante. Filtri comuni in sola lettura, quote-size/tick Task3, news COVERED/COVERED_ZERO e calendari ANNOUNCED_EVENTS_ONLY; timeout30s e sole latenze500/2000ms della spec. Il blocco evento±15m alla decisione è distinto dall'evento noto dentro holding+buffer, senza aggiungere una finestra extra. Nessuna decisione retroattiva da gap/status/calendari/eventi ricevuti dopo il cutoff. `technical_eligible` riguarda questi filtri dati, non il rischio di portafoglio Task7; G1 resta NOT_EVALUATED nel risultato, dati sintetici NON_IDONEO, base operativa DURABLE_EVIDENCE_ONLY.

TDD: RED iniziale29 failure per moduli assenti; RED review4 su calendario mancante, sostituzione del previous, status e RVOL oltre split; RED adapter1, parametri esecutivi3, campo effettivo event_date1, valuta/rettifica2, finestra eventi1, range calendario1 e status storico tardivo1. Correzioni di fixture ACK/FK e confronti float approssimati dichiarate nei log, nessuna soglia economica o prestazionale cambiata. Primo tentativo del gate esteso non avviato per nome errato del file feature-store, escluso dall'evidenza. Mirati estesi257/199,23s e259/202,13s precedono l'ultimo fix di status; **58 focus finali PASS**,101,45s, sui quattro moduli nuovi dopo quel fix. Tutti zero tentativi esterni inattesi. Test manuali costanti/non costanti, mutazioni future append/change/remove e famiglie metadata, revised calendar/holiday, DST, half-day210/390min, split, stale/spread/size/status/news/eventi e confini AST. Ruff/pip e scanner11 con self-test/zero candidati inattesi PASS. Suite backend completa avviata soltanto dopo il focus finale, con hash dei nove file congelati prima dell'avvio: **2476 PASS**, 746.62s, zero failure/error/skip e rete inattesa, due self-test intenzionali della guardia. JUnit `full-final.xml` include tutti i58 nuovi casi; hash dei nove file invariati alla fine.

**Gate conclusivi:** Ruff backend/scripts/tests, pip check, scanner11/self-test/zero candidati inattesi, diff/scope e audit `verify_evidence.py` PASS. Review root in sola lettura senza Critical/Important aperti. Due warning preesistenti Starlette/httpx/HTTP422; frontend e percorso di apertura/replay Task2 invariati, build frontend e benchmark5/20/60 non ripetuti. Evidenze nello scratch `sp3-task4-verification`, nessun log di un run precedente spacciato per verifica finale.

Task4 FATTO nello stesso commit `feat: compute point-in-time intraday research features`, checkbox/programma/Prossimo passo aggiornati e SHA Task3 registrato. Push del solo Task4/gate SHA e FF main non forzato/gate SHA sono verifiche post-commit autorizzate; esito nella consegna, proprio SHA al task successivo. Prossimo Task5 setup/news ablation NON INIZIATO, base origin/investedge/sp3-task-4. G1_DATA INSUFFICIENTE/G2 NON VALUTATO; nessuna raccolta live, credenziale, DB reale, ordine, paper, leva o spesa.

## Task 5 — Setup deterministici e news ablation

**Branch:** `investedge/sp3-task-5`; **Base:** origin/investedge/sp3-task-4.
**Dipendenze:** Task4 FATTO.
**File nuovi:** `backend/app/intraday_research/strategies.py`, `news_features.py`; `tests/test_intraday_research_strategies.py`, `tests/test_intraday_research_news.py`.
**File modificati:** `backend/app/intraday_research/contracts.py`, `registry.py`, `datasets.py` nel medesimo pacchetto; `tests/intraday_research_fixtures.py`, `tests/test_intraday_research_registry.py`, `tests/test_intraday_research_datasets.py`.

- [x] RED: ingresso su barra aperta/OR incompleto, pullback/spike/invalidazione non rispettati; TECH_NEWS retroattivo, NEWS_ONLY richiede EMA/VWAP/momentum, duplicazione news-only nelle due famiglie gonfia le 20 configurazioni; parsing guidance/M&A senza prova/diritti, TTL rinnovata da duplicati.
- [x] Implementare regole §5/7, livelli e motivi, griglia20/policy10 nell'ordine fissato; fatti news positivi verificabili o UNKNOWN, TTL60 e decadimento con emivita30, filtri negativi. Nessun LLM, sentiment±5 o consensus inventato. Setup puro, nessun simulatore/provider/ordine.
- [x] Import locale esplicito news-source-attestation-v1 con authority primaria/prova/originali consentiti/hash/diritti/issuer/listing/article-version/fact binding/tempi nelle tabelle Task1; nessuna inferenza di issuer verificato da source/author/link/menzione. Assenza o prova tardiva→UNKNOWN al cutoff passato; refs nel manifesto. M&A solo target/classe/valuta/termini compatibili, mai premium assegnato all'acquirente.
- [x] GREEN: casi positivi e mancati a mano per ogni famiglia/confine, ingresso a 1ns, revisioni mapping/cluster/authority, rumour/negazioni/unità/periodo/diritti; articolo mappato target+acquirer positivo solo target; signal key paired TECH_NEWS; NEWS_ONLY invariato cambiando soltanto timing tecnico. Holding distinto dal timeframe; sintetico positivo non prova economia.
- [x] Mirati: strategies/news/features/eligibility/daily_context/boundaries, regressioni intraday_news/events e news legacy; gate comune e review.

**Evidenza e chiusura 2026-10-15:** base Task4 `fb8ce92f173b22450d284d51d1167112832cde70`, push/FF precedenti verificati, lock remoto Task5 pubblicato. Main locale originale fb8ce92 preservato su conferma dell’utente; Codex unico writer, scope12 file senza dipendenze/schema/API/frontend/reader. RED/GREEN sui setup e sulle prove news, revisioni/TTL/cluster/scope/precisione/wording/feed; ultimo RED repin dello stesso articolo→origin_ref obbligatorio salvo replay identico, lookup bounded LIMIT1. Guidance/M&A richiedono l’originale strutturato locale issuer-facts-v1 indipendentemente pinnato e il binding esatto all’articolo archiviato con diritti: solo fixture sintetiche, nessuna autenticazione primaria reale automatica. Ritrattazioni/mapping invalidi scelti prima dei filtri, nessun fallback positivo; duplicati non rinnovano TTL. NEWS_ONLY indipendente dalle feature/timing tecnici, dedup evento/cluster per seduta; 20config/10policy invariate. Frame storici as-of, invalidazione tardiva soltanto alla nuova disponibilità; raccordo bundle read-only e nessuna esecuzione.

Wrapper offline finale quattro moduli **186 PASS**/112.25s (`targeted-closed.xml`); mirati estesi509 prima degli ultimi fix. Backend completo fresco **2564 PASS**/1121.59s (`full-final-v2.xml`), zero failure/error/skip/rete inattesa, due sonde intenzionali bloccate. Primo completo interrotto prima del fix repin, escluso. Hash10 file identici fra avvio/fine full e commit; Ruff/pip/scanner12/self-test Fase2/diff/scope/audit verify_task5.py e review root senza Critical/Important PASS. Warning Starlette preesistenti; gate frontend e5/20/60 non ripetuti su percorsi invariati. Evidenze fuori Git in sp3-task5-verification. Fixture non provano economia; G1_DATA INSUFFICIENTE/G2 NON VALUTATO.

Task5 FATTO con checkbox/programma/Prossimo passo e SHA Task4 nello stesso commit; proprio SHA al Task6. Push solo Task5/gate SHA e FF main non forzato/gate SHA restano verifiche post-commit autorizzate, esito nella consegna. Prossimo Task6 fee Alpaca/ledger NON INIZIATO. Nessuna raccolta live, credenziale, DB reale, ordine, paper, leva o spesa.

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

**Prossimo:** riprendere Task2 IN CORSO dal checkpoint sul branch `investedge/sp3-task-2`; base storica Task1 `7b708706c70a4d37d01bc10b73af299bc2052e25`, main fermo al Task1. Sostenibilità non superata, Task3 e SP2b Task13 NON INIZIATI. Approvazione spec/piano acquisita e Task1 FATTO. G1_DATA INSUFFICIENTE rimane prerequisito aperto per economia/SP6a; nessuna cattura live, credenziale, ordine o paper in questa consegna.
