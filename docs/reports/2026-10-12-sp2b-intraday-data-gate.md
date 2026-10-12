# SP2b Task 12 — gate tecnico intraday

Data: 2026-10-12. Base verificata: Task 11, `e5473166669043bfbc0f05baa4186ee966963b9f`; feature precedente `37194f2f34e63865c8104929695b7a7852c3cc1a`. Branch di consegna: `investedge/sp2b-task-12`.

## Esito e perimetro

**G1_TECH PASS**, con limiti di prestazione misurati e dichiarati. Suite completa, smoke funzionale su 30×20 e re-review dei fix sono verdi; nessun Critical/Important aperto. **G1_DATA INSUFFICIENTE**: questa consegna non contiene un manifest di cattura REAL verificato. Non sono state lette configurazioni sensibili né aperto il database dell'utente. Nessuna cattura live, credenziale reale, spesa, ordine o leva è stata attivata.

Il gate tecnico non valida una strategia intraday. SP2b resta IN CORSO per il backlog §13; il passo documentale successivo riguarda SP3, regole e validazione dei segnali per holding 15/30 minuti. SP6a paper senza leva richiede G1_DATA READY e G2; reale e leva restano nel percorso SP6b dopo validazione.

## Rilievi riprodotti e corretti

- **Stato collector:** una lease scaduta o un thread locale perso lasciavano esporre un vecchio LIVE. Inoltre la copia RAM poteva sopravvivere a checkpoint scaduto, silence del canale o rollback del clock. La lettura richiede ownership e lease valide; la copia scade con il minimo fra i checkpoint e le frontiere effettive dei due canali. Una nuova pubblicazione della copia non allunga la validità di una vecchia prova. Le deadline restano private e la lettura degrada/disabilita i listing senza modificare evidenze archiviate.
- **Job intraday:** le route condivise del laboratorio potevano esporre parametri/risultati archiviati divenuti sensibili dopo la rotazione della configurazione. Enqueue controlla l'inventario corrente prima di hash/scrittura; lettura, lista, deduplica e risposta di annullamento ricontrollano tutto il record. Il worker controlla parametri ed esito prima della persistenza. L'annullamento prende effetto anche se la risposta deve essere bloccata con errore fisso 422. I kind SP1 conservano il contratto precedente.
- **Ingestione:** il massimo globale della sequenza scandiva entrambe le tabelle a ogni inserimento; il lookup dell'ammissione scandiva tutti i capture events. Quattro indici additivi, non univoci, e due massimi indicizzati preservano ordinamento e transazioni. La ricerca dei duplicati usa scope/logical key/capture.
- **Identità nel batch:** ogni evento decodificava tutte le identità. Il riuso è locale alla singola `persist`, allo stesso namespace/cutoff e versione del DB; scritture locali o esterne invalidano la cache. La risoluzione mantiene tutti i controlli di collisione UUID/ticker/venue e l'effective time di ciascun evento.
- **Letture e replay:** il filtro SQL parametrico sui listing market limita le decodifiche conservando revisioni, receipt e availability; non anticipa filtri temporali o di qualità. Il replay raggruppa le quote soltanto dopo la validazione causale globale e conserva ogni revisione.
- **Capacità snapshot:** lo smoke di scala ha riprodotto un `COUNT(*)` a ogni INSERT dei membri, con costo quadratico: una sonda indipendente da 5.000/10.000/20.000 righe richiedeva 0,153/0,602/3,281 s; sul prefisso completo il freeze è stato interrotto dopo oltre 7.500 s CPU. Contatori operativi per parent, mantenuti dai trigger nella transazione dell'INSERT, conservano l'hard cap senza ricontare la storia. Decremento, cambio ID, delete e replace sono vietati; un incremento manuale può solo negare ulteriore capacità. Backfill dei contatori mancanti e installazione dei guard sono atomici sotto `BEGIN IMMEDIATE`; rollback e writer concorrente verificati. I contatori sono esclusi dall'evidenza congelata, che continua a validare riferimenti e cardinalità effettive.

TDD osservato: 8 RED iniziali per sicurezza/stato/sequenza; ulteriori RED per lookup, volume del replay, riuso identità, scope SQL, tre casi di scadenza della copia runtime e contatori di capacità. Le **22 regressioni** includono invalidazione da writer locale ed esterno; nessun test usa dati live. **62 test API/job e cinque regressioni contatori PASS**, con re-review indipendenti del runtime, sicurezza e migrazione atomica.

Probe indipendenti in RAM, indicativi: lookup ADMISSION da 0,2013 a 0,000767 ms su 3.000 quote; replay 30 listing × 100 quote da 1,5275 a 0,1403 s con output integrale identico; query di un listing da 116,16 a 4,21 ms con 100 righe identiche. Questi probe spiegano i fix e non sostituiscono lo smoke completo.

## Matrice spec §12 → evidenza offline

| Proprietà | Test e percorso verificato |
|---|---|
| Tempi/nanosecondi, ricezione/durabilità | `test_intraday_contracts.py`, `test_intraday_store.py`, transcript collector; RAW invisibile prima di ADMISSION, backlog senza retrodatazione |
| Prefissi causali | `test_intraday_replay.py::test_future_occurrences_never_change_any_prefix`, famiglie di eventi append/change/remove, batch/tie/shuffle |
| Revisioni | store/news/event/replay: A→B→A, duplicate delivery, source update fuori ordine, ultima revisione non valida senza fallback |
| Calendario/aggregati | `test_intraday_identity.py`, `test_intraday_aggregate.py`: holiday, DST, half-day, bordi 1/5/15 e gruppi incompleti |
| Identità/universo | `test_intraday_identity.py`, snapshot/replay: conferma, collisioni, ticker reuse, inactive e dipendenze congelate |
| Budget/segreti | provider/transport/stream/API/job: sentinelle generate, redirect/host/query/echo, 401/403/429/retry e rotazione inventario |
| Collector | `test_intraday_collector.py`: auth/ack, bootstrap, halt, queue overflow, silence, reconnect/gap/restart/lease; stato locale scaduto mai LIVE |
| Confini REAL/DEMO/SP1 | `test_intraday_boundaries.py`, suite daily/lab/ML: nessuna minute bar in price_history, nessun daily score o legacy news nell'evidenza intraday |
| Snapshot immutabile | `test_intraday_snapshots.py`: prefisso completo incluse occurrence superseded/pre-periodo, missing source e tamper fail-closed, cancel senza pubblicazione; smoke aggiunge revisioni future |
| Qualità | `test_intraday_quality.py`: minimi/denominatori/griglia 20×10, exclusions, benchmark, stale/status UNKNOWN/news coverage, IEX/delayed/research mai promossi |
| API/UI | `test_intraday_api.py`, `test_intraday_jobs.py`, frontend status/DataCenter/News: 202/polling, terminali/cancel, GET senza rete, abort, namespace e covered-zero distinti |

News coverage resta conservativa: il replay richiede barriere durevoli coerenti con ciascun punto della griglia; un PONG futuro non certifica retroattivamente un intervallo senza evidenza.

## Smoke riproducibile

Da una shell nel checkout gestito, con Python 3.14 e dipendenze già installate:

```powershell
$env:INVESTEDGE_DB_PATH = '<scratch-assoluto>/sp2b-smoke-nuovo.db'
& './backend/.venv/Scripts/python.exe' -m backend.scripts.intraday_data_smoke
```

Il target deve essere assoluto e nuovo: un file esistente, `investedge.db` o la directory `data/` del checkout sono rifiutati prima dell'apertura SQLite. Creazione esclusiva `xb`, dotenv disabilitato e guardia socket/DNS. `--quick` percorre gli stessi servizi con 3 listing e due sedute ridotte; è un controllo rapido, non la misura di scala. Per la verifica di scala, dopo il difetto di capacità, l'archivio sintetico già acquisito è stato recuperato e copiato con SQLite backup in un **nuovo** file di scratch, poi migrato e verificato con i servizi corretti; l'entry point ordinario continua a rifiutare file esistenti.

Fixture principale **DEMO/SYNTHETIC/RESEARCH_ONLY**: 30 listing, inclusi due benchmark, 19 sedute da 390 minuti e una da 210: **228.600 barre e 228.600 quote campionate**. Calendario, listing e news sono sintetici. Bootstrap metadata/identity preview/apply/calendar/universe, ingestione RAW+ADMISSION, freeze del prefisso completo e replay usano i servizi di produzione. News con due versioni prima del cutoff; nuova revisione BAR/news dopo il freeze deve lasciare invariati digest, manifest e risultato letto.

Il benchmark collector separato usa soltanto socket fake e DB RAM, 10 burst × 60 quote su 3 listing. Il namespace nominale REAL è richiesto dal contratto del collector ma **non è una cattura reale** e non viene unito al dataset DEMO. Misura `receive + drain` in CONNECTING, con peak sintetico dichiarato 100 eventi/s, RAW/ADMISSION/perdite e lag rispetto alla ricezione dell'observation. Non misura il costo di un runtime LIVE completo con status checkpoint/reconcile a ogni batch, né un SIP tick tape completo.

| Misura finale 30×20 | Risultato |
|---|---:|
| Ingest RAW + ADMISSION | 716,170 s per 457.200 osservazioni |
| Freeze corretto | 634,755 s; 914.531 membri tipizzati |
| Replay completo | 280,178 s; 915.131 occurrence incluse le dipendenze |
| Query as-of, 20 cutoff/listing | p95 1.005,879 ms |
| Database finale | 1.667.592.192 byte, circa 1,55 GiB |
| Picco working set processo | 10.935.476.224 byte, circa 10,18 GiB |
| Collector fake, receive + drain | 642,918 eventi/s; peak dichiarato 100/s |
| RAW / ADMISSION collector | 600 / 600, coda massima 60, zero perdite |
| Lag admission sul clock sintetico | max 0 ns; drain wall medio 93,325 ms/batch |
| Snapshot dopo nuove revisioni BAR/news | fingerprint completo identico |
| Rete esterna | 0 tentativi |

Digest dello snapshot sintetico: `3afc504c5778cd4907901e77e555194ebe31677f47aa209d69942beabbd4cda9`. Esito quality della fixture **NON_IDONEO**; non certifica un campione REAL. Il contatore finale coincide con la cardinalità effettiva.

**Target indicativi non raggiunti**: query p95 ≤250 ms e replay ≤60 s. Sono obiettivi indicativi della spec, non soglie economiche né un'autorizzazione operativa. Il freeze non ha più il costo quadratico, ma il prefisso completo e le copie/proiezioni del reader richiedono ancora tempo e RAM elevati. Da includere nel prossimo piano il percorso timeline-only e un profilo sostenibile di finestra/retention; il benchmark corrente non dimostra sostenibilità del runtime LIVE completo. Nessuna soglia della policy G1 è stata ridotta.

Misure locali in ambiente condiviso; parte dei controlli offline è stata eseguita in parallelo. Il clock sintetico non misura latenza di rete Alpaca; il tempo wall del drain è riportato separatamente. Lo smoke di scala è ripreso da backup fresco dell'archivio di questa sessione dopo il fix dei contatori; quick e protezione dell'entry point finale: **due contratti PASS**.

## Audit e controlli

- Catena fino alla base: 18 commit lineari da SP1 `d9a43ee`, nessun merge commit, 11 feature e registri documentali nei perimetri autorizzati; estensioni esplicitamente autorizzate nei Task 5/6 conservate.
- Review indipendenti causalità/esecuzione/sicurezza e re-review dei fix: PASS, nessun Critical/Important residuo nei perimetri già verificati. Causalità: 224 test iniziali e 157 finali sul delta; runtime: 123 iniziali e quattro regressioni; sicurezza: 332 iniziali e sette regressioni più probe del worker. Gruppi sovrapposti, non sommati come suite unica.
- Frontend: **162 test / 11 file PASS**, installazione `npm ci --offline --no-audit --no-fund` e build TypeScript/Vite con guardia senza connessioni. Nessuna dipendenza o stile modificati. Audit separato: **0 high/critical, 1 low** @babel/core, già noto e fuori perimetro; consultazione degli advisory distinta dai test offline.
- Backend completo finale: **1.874 test PASS**, 22 nuove regressioni; `pytest -q -o addopts= -p no:cacheprovider --tb=short --junitxml=<scratch>/task12-backend-final-v3.xml` tramite guardia offline, zero rete esterna inattesa e due chiamate di self-test intenzionali. Durata 427,03 s. Ruff e pip check PASS; smoke completo funzionale PASS. Scan finale Fase 2 con self-test JSON/YAML/Bearer/mixed/path e classificazione AST esatta dei soli identificatori di codice, scope e diff prima dello staging.
- Warning preesistenti conservati: chunk Vite >500 kB e deprecazioni Starlette/Pydantic. Nessuna modifica delle soglie della policy G1.

Gli output grezzi/JUnit/JSON sono nello scratch della sessione, esterni a Git e senza database reale. Questo report riporta gli esiti osservati; il branch remoto e `PROGRAMMA-OPERATIVO.md` registrano la consegna e il fast-forward dopo il gate SHA.
