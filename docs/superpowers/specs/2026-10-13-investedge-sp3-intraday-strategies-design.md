# InvestEdge — SP3: strategie candidate intraday con holding 15/30 minuti

**Stato: APPROVATA dall'utente il 2026-10-13, prima del Task1.** Le famiglie sono candidate; nessuna è dichiarata migliore o profittevole. Le soglie numeriche sotto sono scelte ex ante approvate per il progetto, non risultati empirici né requisiti imposti dalle fonti.

**Base verificata il 2026-10-13:** origin/main = origin/investedge/sp2b-task-12 = `12ca2c36a2fc19451e70a08e37514089f3e11bb6`, registro successivo alla feature `d182cd547562b933ed1a2c92d4cab78dc8ed1316`. G1_TECH PASS; **G1_DATA INSUFFICIENTE**, nessun manifest REAL verificato. SP2b resta IN CORSO; Task 13 dopo SP3/SP6a.

Riferimenti: [programma operativo](../../../PROGRAMMA-OPERATIVO.md), [spec di programma](2026-09-30-investedge-profit-engine-program-design.md), [SP1](2026-10-02-investedge-sp1-truth-lab-design.md), [spec SP2b](2026-10-10-investedge-sp2b-intraday-data-news-design.md), [piano SP2b](../plans/2026-10-10-investedge-sp2b-intraday-data-news.md), [gate dati misurato](../../reports/2026-10-12-sp2b-intraday-data-gate.md), [piano SP3](../plans/2026-10-13-investedge-sp3-intraday-strategies.md).

## 1. Risultato e confini

Produrre un percorso di ricerca riproducibile che applica regole congelate, misura tecnica/news e holding dal fill, e può concludere che nessuna policy supera G2. SP3 comprende software offline e, soltanto quando esistono input idonei forniti/configurati dall'utente, valutazione economica offline di dataset REAL congelati. Task1 implementa soltanto contratti, schema additivo e registry; nessuna esecuzione economica o apertura holdout.

Prima fase: azioni/ETF USA NMS, USD, long-only, sessione regolare del calendario versionato `America/New_York`, nessun overnight pianificato, short, prestito o ETF inverse/a leva. Trading, adapter ordini, collector live, credenziali, abbonamenti e runtime hosted restano fuori da questa proposta esecutiva. Trade Republic resta manuale.

Separare `G2_TECH` (software/test/review) da `G2` economico per policy e holding: `PASS`, `NON_VALIDATO`, `INSUFFICIENTE`, `NON_IDONEO`. Con DEMO/SYNTHETIC/RESEARCH_ONLY si possono verificare funzioni e ottenere report di ricerca; **G2 non può essere PASS**. SP6a paper senza leva richiede SP1 verificato, G1_DATA READY, G2 PASS per la policy scelta e la propria spec/rischio approvati. Reale e leva rimangono successivi alla validazione e alle azioni esplicite dell'utente.

## 2. Compatibilità verificata nel codice

| Contratto/chiamante alla base | Conseguenza SP3 |
|---|---|
| `intraday.contracts.EventEnvelope`; `store.read_as_of`; `replay.causal_order/select_versions/replay_frozen` | Conservare namespace, ns, receipt RAW/ADMISSION, revisioni e ordine totale. Mai latest globale, clock implicito o retrodatazione. |
| `aggregate.aggregate_as_of` | Riusare gruppi 1/5/15 completi ancorati all'open; `signal_eligible=False` e status UNKNOWN non sono autorizzazione a un segnale. Eleggibilità SP3 con prove SP2b esplicite. |
| `SnapshotService.freeze_dataset/read/replay`; `handlers.frozen`; `intraday_routes.read_snapshot` | Oggi materializzano il prefisso e/o proiezioni prima della pagina. La paginazione HTTP non limita il reader; introdurre il percorso timeline-only verificato. |
| `quote_state_from_rows` | Oggi `size_conversion_attested=False`; STREAM `ROUND_LOTS`, REST `SOURCE_UNATTESTED`. Nuova attestazione necessaria prima dei fill quantitativi. |
| `FeatureStore.refresh_asset/read_frame/signal_panel` | `features_daily` e `price_history` correnti non sono un archivio daily STRICT_PIT: SP3 non li consulta come storia causale. |
| `lab.costs.CostProfile`, simulator/harness/WFO/evidence SP1 | EUR/TR, D/W/M, orizzonti 1/5/21 sedute e griglie daily restano invariati. Non cambiare `engine-v1`, score-v1, `signals` o ML per ospitare SP3. |
| `lab.trials.record_trial/family_trial_sharpes` | Scartano tentativi senza Sharpe finito/DEMO e conservano l'ultimo Sharpe per config. Serve registro SP3 separato che non perda tentativi. |
| `lab.stats`; `lab.jobs`; client `jobs.ts` | Riusare statistiche pure con unità dichiarate e FIFO finito/202/cancel/restart. Kind `INTRADAY_*` conservano il controllo dell'inventario sensibile anche dopo rotazioni. |

Nuovo pacchetto `backend/app/intraday_research/`, che dipende dal livello dati `intraday/` e dalle sole statistiche pure SP1. Il livello dati non importa ricerca, score, simulatore daily o ML; preservare `test_intraday_boundaries.py`. Tabelle e API SP3 additive dedicate; report daily e relativi badge non diventano evidenza intraday.

## 3. Prerequisiti dati, memoria e conservazione

### 3.1 Timeline-only e finestre verificabili

**Addendum autorizzato il 2026-10-14 — `sealed-evidence-blocks-v3`.** Dopo la proposta a blocchi, l'utente richiede il completamento del Task2. Un job esplicito può importare evidenze validate dal reader RAW in blocchi autocontenuti, append-only e pubblicati atomicamente con una seal distinta. Nel nuovo formato i blocchi sono la fonte autorevole; i RAW originari restano conservati e auditabili separatamente. Le strutture SQLite sono additive, con riferimenti al namespace e al dataset/bundle originario; nessuna conversione automatica di v1/v2. Il wrapper mantiene byte/digest/denominatori e timeline logica degli input, identificando separatamente formato e root hash dei blocchi. Compressione standard bounded consentita, senza nuove dipendenze.

Ogni apertura rivalida contenuti canonici, SHA, binding dei member, header delle sorgenti, namespace, clock, count, digest, publication e dependency closure sulle evidenze sigillate. Gli indici per ordine e dipendenze sono verificati contro i blocchi prima di usarli: non sono prove persistenti di validazione. Per l'archivio market il seal dichiara la copertura fino a un ID admission; nuove admission, anche di RAW anteriori, sono lette dalla coda originale e unite prima della selezione delle versioni. Le query full-prefix, i cutoff e le venti query del gate rimangono invariati. GET non prepara blocchi, non scrive, non apre transazioni e non chiama provider/clock. Gli handle conservano fence DB/inventario sensibile. L'acceleratore a batch usa solo il DB-API pubblico e mantiene fallback Python; i casi non supportati non saltano validazioni.

La validazione di un bundle grande può eseguire due passaggi privati concorrenti su connessioni `mode=ro`: sorgenti/locator/unione/timeline e member/digest/closure dei child. I risultati sono provvisori fino al PASS di entrambi e alla fence del chiamante; ogni worker rilegge la stessa root/header/digest, e nessun indice pendente costituisce una prova di validazione. Avvio/attesa e tutte le letture/verifiche restano nel timer del gate. I worker non hanno provider o clock, negano rete, DML, DDL e transazioni e ricevono soltanto contesto pubblico in RAM, con ambiente minimo privo di credenziali. Con inventario sensibile non vuoto, transazione aperta, DB in memoria o acceleratore assente resta il percorso sequenziale completo. Il cap2GiB comprende il coordinatore e i worker: somma conservativa dei picchi individuali, limiti interni per processo e fallimento prima dell'handle se il totale supera il cap. Non si riusano risultati di validazione tra aperture.

Misure SP2b 30 listing ×20 sedute: replay **280,178 s**, query as-of p95 **1005,879 ms**, picco RAM **10,18 GiB**, DB circa 1,55 GiB, 914.531 membri. Snapshot/replay restano invarianti dopo revisioni future. Collector fake: 600 RAW/ADMISSION, zero perdite; non prova runtime LIVE completo né tick tape SIP. Le prestazioni sono ancora un limite aperto.

Il formato `full-published-prefix-v1` include tutta la storia pubblicata fino al cutoff; ridurre `start_at_ns` da solo non riduce prefisso, memoria o duplicazioni. Il primo lavoro implementativo deve:

1. Separare validazione/iterazione della timeline dalle proiezioni BAR/QUOTE/NEWS/status. Reader/freeze/pagina usano passaggi bounded, hash incrementale con framing e riferimenti esatti; nessuna lista di tutte le righe o copia profonda dell'archivio nel percorso nuovo.
2. Verificare count, digest, source/envelope hash, namespace, publication e dependency closure **prima di esporre un risultato valido**. Iterazione provvisoria interna non pubblica feature/report parziali. Errori/tamper/cancel mantengono il fail-closed corrente.
3. Preservare byte e digest dei manifest v1 già pubblicati. Ordine/tie/A→B→A, superseded, RAW audit-only, eventi globali e prove pre-periodo restano equivalenti al reader precedente. GET non scrive o crea cache persistente né usa provider.
4. Aggiungere un formato esplicito `window-dependency-closure-v2` solo dopo queste prove: finestra di calcolo fino a **5 sedute**, stato iniziale derivato dal prefisso già disponibile all'inizio, tutte le versioni che cambiano lo stato nella finestra, receipt/fonti dei carry-in, warm-up e dipendenze esatti. Nessuno stato iniziale ricostruito usando una revisione futura. Non reinterpretare un v1 come v2.
5. Un bundle di ricerca ordina snapshot child per calendario, congela hash/cutoff/namespace/ruoli e indice di tutte le dipendenze. Finestrelle con meno di 20 sedute non diventano G1 READY individualmente: G1 sul bundle conserva griglia e denominatori globali approvati, inclusi periodi sovrapposti contati una sola volta. Snapshot child, input e report old/new sono verificabili senza latest.

Profilo di risorse proposto: fino a 30 listing inclusi benchmark, una seduta attiva in RAM, blocchi di input di massimo 10.000 occurrence e 8 MiB decodificati (vale il limite più restrittivo), statistiche/barre numeriche bounded delle **30 sedute precedenti** per warm-up/RVOL, cache LRU di massimo 64 MiB. Se una dipendenza eccede il cap, interrompere con `RESOURCE_LIMIT`, senza scartarla. Indici scratch su disco ammessi solo per job espliciti e con quota; niente scritture degli input originali.

Gate di sostenibilità prima di esperimenti estesi: stesso fixture 30×20, query as-of p95 ≤250 ms, replay timeline-only ≤60 s, RSS ≤2 GiB e zero perdite; test scalare almeno 5/20/60 sedute con finestre fisse, dichiarando crescita del disco e massimo working set. Target query/replay SP2b **non abbassati**. Budget disco/free space e crescita per seduta devono essere espliciti e positivi nel manifesto; zero/non attestato blocca il job grande. Il valore del budget dipende dal disco scelto dall'utente, non viene inventato qui. Ripetere anche il percorso runtime fake completo con status/checkpoint/reconcile e admission a ogni batch; riportare burst, throughput, lag, GAP e perdita, separati dal benchmark receive+drain precedente. Non attivare socket live.

### 3.2 Retention

La finestra RAM non è retention dei dati. Le evidenze SP2b sono append-only con FK RESTRICT: **nessun DELETE/purge**, né finte finestre che perdono fonti referenziate. In SP3 v1 conservare input e prove di ogni esperimento/holdout e fermarsi alla quota; pianificare disco e backup per l'intero campione. I nuovi manifest possono evitare duplicazioni di riferimenti con formato versionato, ma non rimuovono evidenze pregresse.

Archiviazione fisica/partizionamento e retention finita di corpi news richiedono un addendum approvato con archivio immutabile, hash/closure/restore equivalenti, diritti e migrazione; non sono implementati da questo piano. Se quota/diritti non consentono il campione, esito INSUFFICIENTE e nessuna cattura automatica per colmare il limite.

### 3.3 Conversione attestata delle quote

Artefatto pubblico append-only `quote-size-attestation-v1`: fonte e contratto/hash, feed/schema, listing o scope verificabile, unità originale, fattore/lotto valido nel tempo economico, known/available time, evidenza e intervallo di applicabilità. Applicare solo attestazioni già disponibili al cutoff e nel namespace/scope corretto. STREAM ROUND_LOTS richiede il lotto specifico attestato; REST SOURCE_UNATTESTED non viene promosso a shares. Nessun fattore 100 implicito, nessun campo broker personale.

Il risultato deriva da quote originale + attestazione esatta, senza aggiornare la quote archiviata; entrambi entrano nell'impronta. Lotto revisionato dopo la decisione non cambia fill salvati. Quantità non intera, overflow, unità/lotto incerti, scope non coperto o attestazione successiva → `SIZE_UNIT_UNKNOWN`, zero fill quantitativi e promozione non idonea. Nessun convertitore usa il prezzo per indovinare il lotto. La size visibile non garantisce liquidità eseguibile.

Attestazione separata `price-increment-attestation-v1`: fonte/authority e contratto verificabile, evidenza/hash, listing/feed/ambito prezzo, incremento Decimal positivo, validità economica e known/available time. Nessun default di un centesimo. `PRICE_INCREMENT_UNKNOWN` impedisce fill e promozione; una futura revisione non modifica il passato. Rounding conservativo: limite buy verso il basso, prezzo fill buy verso l'alto, fill sell e stop verso il basso, target verso l'alto al tick attestato. Ricalcolare rischio/residui dopo rounding; buy mai oltre il limite. Vendite di uscita market simulate, senza prezzo minimo artificiale. Test con due incrementi diversi e bordi as-of; validità ordini broker ulteriormente verificata in SP6a.

### 3.4 Contesto daily point-in-time

Derivare daily dalle sole barre 1 minuto complete delle **sedute precedenti** nello stesso profilo/listing, con calendario, copertura e corporate events già noti. Daily disponibile solo dopo chiusura + disponibilità dell'ultimo input/receipt; giornata corrente mai usata come conclusa. Aggregare OHLC/volume/VWAP, source refs/digest e versione. Prima dello split/reorganizzazione non riconciliato non trasferire livelli, volumi o warm-up nella nuova scala.

Una revisione arrivata oggi può aggiornare il contesto della decisione di oggi, mai quello di ieri. Non leggere `features_daily` corrente o adjusted daily scaricata oggi come STRICT_PIT. Non aggiungere un provider daily alternativo in questo piano. Campione iniziale richiede 20 precedenti daily validi; RVOL può cercare al massimo 30 sedute precedenti per trovare 20 osservazioni della stessa fascia disponibile. Se non ci sono, `WARMUP_INSUFFICIENT`.

### 3.5 G1 ed eleggibilità

Policy G1 invariata: almeno **20 sedute** consecutive catturate e **10 listing** risolti, benchmark inclusi nella griglia; raw ≥**99%**, ogni cella listing/seduta/1-5-15 minuti ≥**90%** e usable>0. Quote SIP realtime age≤2 s, bar delay≤10 s, universo pre-open, calendari e status/news durabili coerenti. REAL/CAPTURED/STRICT_PIT soltanto; IEX, delayed SIP, storico corrente e sintetico non promossi.

SP3 controlla l'eleggibilità anche al proprio istante di decisione/uscita, non soltanto ai punti della griglia G1. All'ingresso richiede esclusivamente continuità nota fino alla decisione e nel warm-up, stato NORMAL verificato, calendario/identità/corporate, quote/size/tick attestati e news `COVERED` o `COVERED_ZERO`. La continuità dell'holding è valutata successivamente per uscite e gate operativo: gap/halt/stale futuri non eliminano retroattivamente ingressi, sizing, trade o denominatori. Append di un GAP futuro deve lasciare invariato il precedente ingresso. `DURABLE_EVIDENCE_ONLY` non prova la coda RAM operativa; per una futura integrazione corrente servirà la guardia operativa SP6a. Il bootstrap status oggi implementato copre Nasdaq/tape C: nessuna tradabilità/status di altre venue o benchmark è presunta; authority e tutti i listing/benchmark devono essere realmente coperti nel dataset idoneo.

## 4. Feature e filtri congelati v1

Decisioni tecniche sulla barra 1 minuto appena chiusa, al tempo in cui tutti gli input necessari sono disponibili. Richiedere close delay≤10 s. Join as-of sull'ultima barra **completa** 5 minuti e sul contesto **15 minuti**; niente ricalcolo con barre non chiuse. Un intervallo mancante intraday resetta il segmento/warm-up; una notte prevista dal calendario può collegare barre RTH precedenti, con finestre espresse in numero di barre, mai interpolazione di minuti notturni.

| Feature | Definizione/unità e warm-up |
|---|---|
| VWAP di seduta | Σ(vw_1m × volume)/Σvolume dal primo minuto della sessione; USD. Tutti i minuti richiesti con VWAP/volume validi; reset all'open, volume zero o input assente → null. |
| EMA8/EMA20 su 1/5 minuti | Pesi α=2/(n+1), finestra troncata 5n barre, pesi normalizzati; USD. EMA20 richiede 100 barre complete nel segmento; EMA8 40. Pendenza EMA20 5m = (EMA_t/EMA_t−3−1), frazione su 3 barre concluse. |
| Contesto 15m | Close/EMA8 (40 barre), segno ROC su due barre chiuse, senza barra 15m corrente parziale. |
| ROC5 1m | C_t/C_t−5−1, frazione; sei close completi. Momento misurato, non score daily. |
| ATR14 1m e 5m | TR=max(H−L, abs(H−Cprev), abs(L−Cprev)); prima barra di ogni seduta usa H−L, gap overnight separato. Media Wilder troncata α=1/14 su 70 TR, normalizzata; USD e ATR/C frazione. |
| RVOL 1m/5m | Volume corrente diviso mediana di 20 sedute precedenti allo stesso offset dall'open e durata. Solo fascia effettiva; half-day non inventa slot pomeridiani. Baseline non positiva/meno di 20 osservazioni nei 30 giorni precedenti → null. |
| RS mercato/settore | ROC15m del listing meno ROC15m di ciascun benchmark, frazione, sui medesimi intervalli 1m completi. Benchmark congelati per listing prima della seduta; nessuna scelta in base ai rendimenti futuri. |
| Daily | Close/high/low/range della precedente seduta, mediana dollar-volume20, gap=open corrente/close precedente−1 e rendimento5 sedute. USD/frazioni con refs as-of. |

Niente MACD/ADX/score composito, LLM sentiment o pesi appresi nella v1; un challenger richiede nuova preregistrazione prima dei dati OOS e nuovo holdout futuro se quello corrente è già stato visto.

Filtri comuni: identità/tradabilità/prodotto verificate; prezzo 5–500 USD; mediana dollar-volume20 ≥20 milioni USD; spread=(ask−bid)/mid≤10 bps; quote valida con size bid e ask positive/attestate; ATR14_1m/C fra 0,0005 e 0,01; abs(gap daily)≤8%; nessun gap/status/evento corporate irrisolto. Questi limiti sono ipotesi di ricerca, non prove di liquidità reale.

Nessun ingresso prima di open+45 minuti. Ultima decisione ammessa solo se `decision_at + entry_timeout + latency + H + 3 minuti < close` conosciuto; H=15 o 30 minuti. Half-day usa close effettivo. Nessuna posizione aggiuntiva sullo stesso listing, cooldown 15 minuti dall'uscita completa; massimo cinque posizioni. Filtri puramente esecutivi comuni non diventano timing tecnico di NEWS_ONLY.

Macro BLS/Fed e earnings programmati: bloccare nuove entrate da evento−15 minuti a evento+15 minuti per ambito interessato; ora ignota → tutta la seduta. Se known schedule cade dentro holding+buffer, nessun ingresso. Evento imprevisto noto dopo il fill produce invalidazione prudenziale/ordine di uscita simulato al timestamp di conoscenza. Calendari `ANNOUNCED_EVENTS_ONLY` restano un limite; omissione non certifica assenza di rischi.

## 5. Regole delle due famiglie candidate

Parametri fissi salvo le due tuple rischio del §7. Nessuna somma arbitraria di indicatori. Ogni candidato conserva signal key=(listing, sessione, bar end, famiglia, holding), input refs, valori, ragioni, livello d'ingresso massimo, invalidazione e stato dei filtri.

### 5.1 TREND_PULLBACK

1. Trend: ultima 5m completa EMA8>EMA20, pendenza EMA20 su 3 barre>0; 15m close>EMA8 e ROC2≥0; RS15m mercato e settore>0.
2. Pullback: nelle tre barre 1m chiuse precedenti alla conferma, almeno un low tocca VWAP o EMA8 1m entro 0,1 ATR1m. Nessun close di queste tre barre sotto EMA20 1m−0,25 ATR1m; ampiezza max(high)−min(low)≤1,5 ATR1m; RVOL di ciascuna≤1,5. Livelli/ATR sono quelli as-of di ciascuna barra, non valori futuri.
3. Conferma: close1m sopra VWAP ed EMA8, sopra high della barra precedente, ROC5>0 e RVOL1m≥1,2. Close−VWAP≤1 ATR1m, per evitare inseguimento dopo spike. Decisione soltanto dopo barra completa disponibile; limite d'acquisto `C_signal+0,25 ATR_signal`.
4. Invalidazione pre-fill: filtro non valido, deadline/entry timeout, quotazione bid sotto il minimo dei tre low del pullback−0,1 ATR_signal oppure ask dopo slippage oltre limite. Non creare un nuovo ingresso dallo stesso signal key.
5. Dopo fill: stop/target §6; close1m completo sotto EMA20 1m oppure sotto il minimo pullback causa uscita per invalidazione. Revisione disponibile dopo può causare soltanto una nuova decisione, non retrodatare l'uscita.

### 5.2 BREAKOUT_CONTINUATION

1. Livello OR: massimo delle prime tre barre 5m complete (opening range 15m). Disponibile soltanto dopo tutte le receipt; invariato nella decisione salvata. Nessuna variante di durata OR nella v1.
2. Consolidazione: le sei barre 1m precedenti alla conferma hanno close≤OR_high, range complessivo≤1,5 ATR1m e massimo entro 0,25 ATR1m sotto OR_high; minima consolidazione è il livello d'invalidazione strutturale. Nessun high futuro nel livello.
3. Breakout: conferma close1m>OR_high+0,1 ATR1m; barra precedente close≤OR_high; close−OR_high≤0,75 ATR1m; RVOL1m≥1,5. Trend di contesto 5m EMA8>EMA20, 15m close>EMA8, RS15m mercato e settore>0. Limite d'ingresso `C_signal+0,25 ATR_signal`.
4. Invalidazione pre-fill: filtri/deadline/timeout, bid sotto OR_high−0,1 ATR_signal o limite superato. Dopo fill, close1m<OR_high−0,1 ATR_signal causa uscita prudenziale; stop/target §6.

Una famiglia senza segnali sufficienti è INSUFFICIENTE. Non cambiare definizione del setup dopo OOS per ottenere operazioni.

## 6. Esecuzione, stop/target e capitale simulato

### 6.1 Contratto degli eventi successivi

`decision_at` è la disponibilità effettiva della decisione; `eligible_after=decision_at+latency`. Un fill richiede una **nuova occurrence quote** con `event_time` e `available_at` entrambi strettamente successivi a eligible_after, stato/namespace validi e quote age≤2s. Un evento tied, una quote storica ricevuta tardi o l'OHLC della barra del segnale non riempiono un ordine.

Ingresso marketable limit, timeout **30 secondi dalla decisione**: buy ad ask+slippage avverso, entro limite dopo slippage; prezzo/quantità/costi Decimal con regola di tick/unità attestata. Size normalizzata e partecipazione massima 10% della size del lato (quote non riutilizzata per aumentare capacità; budget condiviso fra intenzioni allo stesso evento). Parte non eseguita resta pending fino a timeout o invalidazione, poi cancellata. Nessun fill passivo da touch OHLC senza trades/coda; microstruttura trades richiederebbe addendum.

Primo fill positivo = `first_fill`; **deadline=first_fill+H**, H15/30 minuti. I fill parziali successivi non resettano il timer; niente pyramiding. Stop iniziale e deadline attivi dal primo fill, target ricalcolato sul prezzo medio effettivo senza allargare lo stop. Alla prima uscita richiesta cancellare il residuo d'ingresso; quantity delle vendite≤posizione realmente riempita.

### 6.2 Rischio e uscite

ATR_signal e livello strutturale sono congelati alla decisione. Prima di accettare il primo fill, per il prezzo candidato P dopo slippage/tick, calcolare `R=max(k×ATR_signal, P−(structural_low−0,1×ATR_signal))`; per news-only structural_low assente e R=k×ATR_signal. Stop=floor_tick(P−R), rischio effettivo R=P−stop. Richiedere R fra 0,5 e 2 ATR_signal e ≤2% di P **prima** di creare cash movement, posizione o first_fill; candidato invalido cancella il residuo e registra rifiuto, nessun fill viene eliminato dopo l'esecuzione. Stop congelato dal primo fill, mai allargato; target=ceil_tick(average_fill+g×(average_fill−stop)). Le due tuple (k,g) sono nel §7. Tutte le ablation condividono il controllo rischio.

Stop quando bid≤stop, target quando bid≥target; invalidazione su barra chiusa, deadline o close−2 minuti richiedono uscita. Priorità a pari timestamp: stato/halt/gap → stop → invalidazione → tempo/chiusura → target. Il trigger crea un'intenzione; **il fill d'uscita** avviene su evento quote successivo a trigger+latency, bid−slippage avverso, con parziali e budget size. Nessun fill sul medesimo trigger; gap può peggiorare il prezzo oltre lo stop. Se è disponibile solo una barra con stop e target toccati, nessuna liquidazione viene inventata: `EXECUTION_PATH_UNOBSERVED`.

Alla deadline il tempo trascorso non garantisce esecuzione. Halt/stale/gap/no quote lascia `UNRESOLVED` e il residuo aperto fino a una nuova quote realmente idonea; conservare ritardo, esposizione oltre H/close e perdita/mark prudenziale separato. Un trade con uscita irrisolta non viene cancellato dalle metriche. Campione terminale senza uscita/valorizzazione verificabile → INSUFFICIENTE; uno sforamento verificato del requisito sessione/continuità → NON_VALIDATO operativo anche se il P&L finale è positivo.

Capitale di ricerca proposto **10.000 USD**, unità intere, ordine minimo 100 USD, rischio teorico per trade≤0,25% equity, peso listing≤10%, massimo cinque posizioni. Prima dell'ordine calcolare stop/rischio conservativo al prezzo massimo entry_limit dopo rounding e quantità=floor(min(risk_budget/R_max, weight_budget/entry_limit, cash_available/entry_limit)), con fee avverse riservate; limite che non passa il preflight → nessuna intenzione eseguibile. Prima di **ogni** partial, ridurre quantità al minimo fra size residua, cassa/peso residui e budget di rischio dopo rounding: `qty_existing×(average_fill−stop) + qty_new×(P−stop) + fee_reserved ≤ risk_budget`. Anche il residuo pending riserva cash/peso/rischio al suo limite; non duplicare riserve passando da pending a fill. Riduzione lascia pending entro timeout; meno di una share o budget esaurito cancella il residuo. Cassa/esposizione comprensive ordini pendenti≤equity/cassa interna (1×). Perdite realizzate+mark prudenziale giornaliero≤−1% bloccano nuovi ingressi; uscite attive. Quote/stop non garantiscono perdita massima in gap. Nessun capitale paper/live impostato: SP6a richiederà capitale e limiti rappresentativi scelti dall'utente.

Simulare ogni policy/holding in un portafoglio autonomo con medesimo capitale. Eventi simultanei: prima uscite, poi ingressi in ordine `decision_at, listing_id, signal_key`; non ordinare per risultato futuro. Nessuna miscela dei portafogli per dichiarare un vincitore.

## 7. News, ablation e griglia dei tentativi

News/eventi versionati SP2b sono contesto verificabile: fonte, article/event ID, mapping/cluster, categoria, version/hash, publication/first_received/available, diritti e regola conservati. `headline` non è direzione del rendimento. Nessun testo aggiornato retrodatato, news_items legacy, seed, offset fisso ±5 o sentiment LLM.

Regola fattuale positiva `news-context-v1`, identica per NEWS_ONLY e TECH_NEWS: (a) guidance numerica di revenue/EPS alzata rispetto alla precedente guidance dello stesso periodo/unità già nota, senza alcuna metrica abbassata; oppure (b) accordo vincolante annunciato per acquisizione interamente cash con prezzo d'offerta almeno 5% sopra il precedente close as-of **del target acquisito**, stesso listing/classe/valuta/unità. Il mapping many-to-many non trasferisce il premio all'acquirente o ad altre classi. Termini/deal ID/parti/versioni e close target sono riferimenti as-of. Fonte primaria richiesta come sotto; parsing deterministico conservativo. Rumour, negazione, futuro ipotetico, unità/periodi non confrontabili, semplice categoria GUIDANCE/M_AND_A o testo assente → UNKNOWN. Headline utilizzabile solo con tutte le prove; non scaricare link o acquistare testo. Surprise earnings/macro senza **consensus** archiviato PIT è assente, non zero.

SP2b conserva una stringa `source` e classificazione headline, **non** un'attestazione emittente. Aggiungere import locale pubblico `news-source-attestation-v1` append-only: authority/fonte primaria/contratto/prova verificabile, originali consentiti bounded con hash/diritti, issuer/listing/article-version/fact binding, validità/known/available time e ref della precedente guidance o termini del deal. Nessun source/author/URL/menzione testuale equivale a issuer verificato. Semplice dichiarazione o hash senza prova indipendente non bastano; assenza → UNKNOWN. L'artefatto non retrodata disponibilità: una prova importata domani non sblocca il catalizzatore di ieri, e i riferimenti entrano nel manifesto. Nessun fetch automatico; testo mancante resta tale. Il limite può rendere news-only/combo insufficienti senza impedire TDD offline.

Deduplicare intenzioni per cluster/evento già conosciuto al cutoff; modifica futura del cluster non cancella un precedente trial. Novità rispetto agli eventi disponibili nella seduta, fonte/affidabilità fattuale e età separate. Decadimento `2^(−age_minutes/30)` dall'available iniziale del fatto; TTL60 minuti/decay≥0,25, nessun refresh della TTL per semplice duplicate delivery. Diluzione/filing/regolatorio avversi verificati o evento uncertain impediscono nuove entrate per 30 minuti nell'ambito interessato; missing/stale/disabilitato sono stati distinti da COVERED_ZERO.

| Arm | Ingresso | Uso delle feature |
|---|---|---|
| TECH_ONLY | Setup §5 | News soltanto copertura e filtri comuni di evento/rischio; nessun requisito di catalizzatore positivo. |
| TECH_NEWS | Stesso signal key tecnico ammesso solo con evento positivo verificato TTL60 | Nessun cambiamento del setup o dei livelli; decisione sul signal tecnico corrente, mai backfill di un segnale scaduto quando arriva la news. |
| NEWS_ONLY | Una intenzione alla prima disponibilità di un evento positivo nuovo, poi quote future §6 | **Nessun EMA/VWAP/ROC/RVOL/RS per generare o temporizzare ingresso**; ATR serve solo rischio e volatilità comune, daily solo liquidità/sessione. Limite dall'ask già noto all'evento+0,25 ATR; se assente, non-fill, non attesa di conferma tecnica. |

Confronto stesso universo/periodo/feed/capitale/costi/split, opportunità proprie dichiarate. TECH_ONLY vs TECH_NEWS anche paired sui signal key comuni; NEWS_ONLY condivisa tra le due famiglie, non duplicata per gonfiare N. Report motivi blocked/no-event/UNKNOWN/no-fill, copertura testo e campione per ciascun arm.

**20 configurazioni uniche, ordine congelato:** famiglie TREND_PULLBACK poi BREAKOUT_CONTINUATION × H15 poi H30 × TECH_ONLY poi TECH_NEWS × tuple R0=(k1, g1,5) poi R1=(k1,5, g2) =16; NEWS_ONLY condivisa ×H15/H30 ×R0/R1 =4. **10 policy** di selezione rischio: 8 famiglia/holding/arm +2 NEWS_ONLY/holding. Ogni policy seleziona soltanto R0/R1 sui propri IS; nessuna selezione tra famiglie/arm/holding basata su OOS. Filtri, warm-up, setup e soglie non sono altre dimensioni di griglia.

## 8. Costi Alpaca e rendicontazione

Profili separati `ALPACA_PERSONAL_US_EQUITIES` e `TR_MANUAL`; non importare TR_COMMISSION_EUR o il suo spread aggregato nel percorso Alpaca. Cost profile pubblico immutabile: currency USD, scope personale retail/NMS/route, fonte/hash/revisione/verifica, periodo economico attestato, commissioni, SEC/TAF/CAT e rounding, dati/news ricorrenti e regola di allocazione. Nessun ID conto o credenziale. Applicabilità storica mancante/scaduta/contrastante → `COST_PROFILE_UNVERIFIED`, fixture possibili ma promozione bloccata; una fee UNKNOWN non diventa zero.

Il [tariffario canonico Alpaca](https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf), collegato dalla [Disclosure Library](https://alpaca.markets/disclosures) e verificato il 2026-10-13, è revisionato il 1 ottobre 2026. Per equities: SEC sells `0,0000206 × trade value`, TAF sells `0 USD/share`, CAT buy/sell `0,000003 USD/equivalent share` (NMS: una share equivalente). Fee separate aggregate per conto/giorno, poi ceiling al centesimo, quantità esatte. Commissioni ordinarie assenti con eccezioni partner/Elite Smart Router/flusso non retail. Questa è una fotografia documentale: la revisione non dimostra da sola le date di applicabilità di ogni tariffa; non applicarla retroattivamente a tutto lo storico. Riconfermare fonte/scope prima di esperimenti REAL.

Ledger giornaliero Decimal comune ai fill della singola policy, attribuzione proporzionale alla base della fee con residui di centesimi per ordine stabile; somma per trade=totale giornaliero. Ask/bid incorporano lo spread una sola volta; slippage già nel fill, fee separata. Riservare fee per non rendere negativa la cassa prima del rounding EOD.

P&L base netto di esecuzione (spread/slippage/fee) e P&L dopo costi dati/news entrambi obbligatori. Costi ricorrenti effettivi attestati ripartiti sulle sedute del periodo, poi sui trade pro rata controvalore; sedute senza trade mantengono costo nel portafoglio. Ogni policy standalone sostiene il costo completo del profilo, non un ventesimo perché ci sono 20 test. Zero costo ricorrente valido solo se attestato. Capitale/fee/feed diversi richiedono nuovo manifesto; non scegliersi il capitale che rende favorevole il costo fisso dopo OOS.

Valuta economica del gate USD. Rendicontazione EUR soltanto con FX/digest/availability attestati; FX daily SP1 non dimostra conversione intraday. Se assente, EUR N/D e motivo, senza conversione inventata. Fiscalità è stima separata dal gate netto di esecuzione, da specificare/verificare in SP6a/SP6b prima dell'operatività; nessuna consulenza normativa aggiunta a SP3.

### 8.1 Stress congelati

BASE: latency500 ms per ingresso/uscita, slippage2 bps per lato, spread osservato, partecipazione size10%, fee/pubblici costi attestati. Sono ipotesi prudenti da misurare, non latenza reale dimostrata.

| Scenario | Modifica rispetto a BASE |
|---|---|
| STRESS_COST | Slippage10 bps per lato, spread2× attorno al mid; fee base più5 bps avversi per lato, anche se TAF base è zero. |
| STRESS_LATENCY | **2.000 ms** per ogni intenzione; quote sempre successive, non spostare artificialmente timestamp dei dati. |
| STRESS_LIQUIDITY | Size disponibile **50%**, cap partecipazione5%, scartare deterministicamente **5%** delle quote eleggibili con hash di occurrence+seed preregistrato. |
| STRESS_COMBINED | COST+LATENCY+LIQUIDITY insieme; limiti e timeout invariati. |

Ricalcolare ogni percorso, incluso no-fill/partial/stop/time; non sottrarre soltanto una fee dal P&L già noto. Scenari estremi halt/gap/no exit sono anche prove operative, con esiti irrisolti espliciti.

## 9. Harness e registro completo

Harness distingue: (a) etichetta predittiva fixed-H da first_fill alla prima quote eseguibile oltre deadline+latency, senza stop/target; (b) P&L implementabile della policy con stop/target/tempo §6. La seconda determina promozione. Etichetta senza uscita o senza fill è mancante con ragione/denominatore, non rendimento zero. IC/bucket condizionali sono diagnostici se almeno10 listing confrontabili allo stesso istante; non imporre soglie daily SP1 a segnali sparsi né usare spread long-short per giustificare short.

Benchmark diagnostici congelati: cassa con risk-free0 e medesimi costi ricorrenti; portafoglio passivo sul listing mercato già scelto nell'universo pre-open, una entrata simulata per seduta a open+45min, peso10% del capitale, holdingH15/30, stessa latenza/quote-size/fee/filtri esecutivi, uscita temporale e nessuno stop/target tecnico. No-fill/exit irrisolta mostrati senza fallback close. Il benchmark non è selezionabile e non determina gli ingressi dei candidati. Curve/input/digest congelati; assenza di benchmark non diventa alpha positivo inventato.

Report: intenzioni, ammessi/bloccati, fill rate, partial/non-fill, slippage/costi, rendimento netto bps per round-trip, P&L USD, curva giornaliera/equity intraday, esposizione, turnover, profit factor (null se indefinito), drawdown, peggior seduta, CVaR95 giornaliero, concentrazione, exit delay e violazioni. Trade = intera posizione dal first_fill all'ultimo exit, non ogni fill; annotare quantity/nozionale/costi. Media trade in bps non ponderata e ponderata entrambe, con denominatori. Tutte le sedute pianificate, anche flat/escluse/cost-only, restano nella curva. Statistica round-trip usa netto di esecuzione; statistica/curva del portafoglio usano netto dopo ricorrenti, anche nei giorni senza trade. Etichette/unità diverse esplicite, mai due netti indistinguibili.

Trial registry SP3 preregistra **prima dell'esecuzione** ogni ipotesi e budget: `REGISTERED`, poi eventi append-only `STARTED`, `COMPLETED`, `REJECTED`, `FAILED`, `CANCELLED`, `INTERRUPTED`, con reason code sicuri; errore/cancel non eliminano l'ipotesi. Policy, codice/versioni, config_hash, experiment_hash, namespace/feed/dataset digest, costi/size attestazioni, capitale, split, seed, benchmark, soglie, arm/famiglia/H, ruolo IS/OOS/HOLDOUT e stato di accesso entrano nell'evidenza. Falliti/scartati/no-trade/NaN restano visibili. DEMO ha registro distinto e non modifica M o statistiche REAL.

`config_hash` identifica la configurazione canonica; `experiment_hash` anche dataset/periodo/costi/split/versioni. Replica identica non è nuova ipotesi; cambio dopo esiti è un nuovo tentativo e resta nel registro cumulativo del programma di ricerca. Un blocco di 20 config è preregistrato insieme; non cancellare quelli senza Sharpe. Incidenti di software hanno log/esito e rerun legato al medesimo esperimento, senza nascondere l'accesso già avvenuto a OOS/holdout.

## 10. Selezione IS, purge/embargo e holdout

Dates/universo/feed e finestre fissati prima degli esiti. Proposta campione: warm-up20 sedute precedenti (+ricerca RVOL fino30), iniziale **IS126 sedute**, quattro blocchi **OOS63** (=**252** sedute), **holdout63** finale. IS rolling126 prima di ciascun OOS. Fra ultimo IS e primo OOS, e fra development e holdout, **embargo di una seduta intera**, senza nuove entrate; giorni embargo esclusi dalle metriche OOS e mostrati. Ordine di calendario proposto: 126 IS +1 embargo +63 OOS1 +1 embargo +63 OOS2 +1 embargo +63 OOS3 +1 embargo +63 OOS4 +1 embargo +63 holdout =446 sedute, oltre warm-up. Le finestre IS successive usano i 126 giorni precedenti il rispettivo embargo, comprese vecchie sedute OOS divenute passato; questa regola è preregistrata, non tuning dopo esiti.

Split per seduta intera, nessuna divisione casuale di minuti/listing. Ogni etichetta/trade ha intervallo `[decision_at, last_exit]`; pending/unresolved mantiene endpoint aperto. Purge dal campione di selezione degli esempi che attraversano cutoff o embargo. Interval bound conservativo almeno H30 +timeout30s +latency stress2s per entrambe le intenzioni; stop/target non accorciano ex ante il purge. Embargo esteso se c'è un residuo non chiuso: non inventare liquidazione per iniziare OOS; esperimento insufficiente finché non si ricostruisce il confine. Warm-up con solo dati passati è lecito; niente fit su OOS o ritorni che ne attraversano il cutoff.

Per ogni policy e finestra, simulare R0/R1 sul **prefisso disponibile fino al cutoff IS**, con stesso calendario/filtri. Il prefisso precedente alimenta solo warm-up/stato causale; Sharpe di selezione, minimi trade/sedute attive e vincoli di ammissibilità sono calcolati **esclusivamente nelle 126 sedute della finestra IS corrente**, senza rendimento/etichetta che attraversi cutoff. Selezionare Sharpe netto dopo ricorrenti per seduta più alto, pareggio R0 prima di R1. Se nessuna tupla ammissibile, astensione/INSUFFICIENTE, non fallback con Sharpe nullo. Perturbare/aggiungere/rimuovere OOS/holdout, anche split/gap alla prima barra futura, deve lasciare identici tutti gli Sharpe IS e le scelte (regressione R1).

OOS è una sola simulazione per policy, equity prosegue fra finestre; niente reset per cancellare perdite, nessuna liquidazione arbitraria al cambio parametri. Posizioni pendenti mantengono la versione di ingresso fino all'uscita; embargo senza ingressi non garantisce chiusura. Costi giornalieri e stato dei trial continui. Le policy delle due holding restano separate; un holding non compensa l'altro.

Holdout sealed **nel percorso di ricerca SP3**: access guard per ruoli, digest dei dati/date e registro di `SEALED → OPENED` una sola volta per il batch di tutte le policy, dopo freeze del codice/policy/costi/rischio e delle tuple finali scelte sul prefisso IS dichiarato delle ultime126 sedute prima dell'embargo holdout. Gli input storici del prefisso possono già essere stati OOS nei fold precedenti; ruolo finale IS dichiarato prima dell'esperimento. Reader/preview/elenco/job/benchmark SP3 di sviluppo non emettono righe/feature/metriche holdout.

Le API dati SP2b e l'accesso diretto al filesystem non sono un sistema di sicurezza contro ispezioni esterne: nessuna promessa di sigillo globale. Ogni ispezione di input/outcome holdout fuori dal workflow SP3 (anche Data Center/snapshot/news/reader diretto o altro strumento) per la ricerca deve essere dichiarata con evento append-only `CONTAMINATED`, scope/date/refs e motivo; blocca G2 per quel batch e richiede holdout futuro nuovo. Il manifesto registra accessi già avvenuti prima della seal. Prima di OPENED/gate, una dichiarazione esplicita del responsabile della ricerca di assenza d'ispezione/uso esterno del holdout deve essere archiviata; senza attestazione d'integrità del processo, INSUFFICIENTE. Non è prova tecnica di assenza di accessi non osservabili e tale limite resta nel report. Dati non tornano intatti cambiando nome al dataset. Test contaminazione anche per refs ottenuti dal reader/API SP2b e assenza della dichiarazione; GET non acquisisce dichiarazioni né scrive.

Nessuna scelta tra famiglie/arm guardando OOS; il gate applica le condizioni alle policy preregistrate. Dopo OPENED non modificare soglie/strategia e rieseguire fino a PASS; una modifica materiale richiede nuova ricerca e nuovo holdout futuro mai visto.

## 11. Campione, incertezza e promozione ex ante

| Segmento, per policy/holding | Minimi obbligatori |
|---|---|
| Ogni selezione IS | 126 sedute; ≥200 round-trip, ≥40 sedute con trade per tuple ammissibile |
| OOS complessivo | 252 sedute pianificate; ≥400 round-trip e ≥100 sedute con trade |
| Ogni OOS63 | ≥50 round-trip e ≥15 sedute con trade |
| Holdout | 63 sedute; ≥100 round-trip e ≥30 sedute con trade |

Minimi insufficienti → INSUFFICIENTE; non estendere a posteriori fino al successo né pescare il sottoperiodo migliore. Confronto ablation può essere inconcludente per arm scarso anche se un'altra policy supera il proprio gate: non dichiarare vincitore tecnica/news/combo senza campione comparabile. Un G2_PASS identifica esattamente la policy/feed/H/dataset/capitale/rischio, non tutte le strategie della famiglia.

Bootstrap a blocchi circolari di **5 sedute intere**, 10.000 repliche, seed137 fissato. Resampling congiunto delle stesse sedute per tutti i listing/arm mantiene dipendenza cross-section; calcolare mean-bps round-trip come somma dei bps/somma del conteggio su ciascun campione, non media di medie giornaliere. OOS e holdout separati; blocchi1/10 come sensitivity obbligatoria, mai scelta del blocco più favorevole. Dipendenza oltre dieci sedute o regime scarsamente rappresentato è limite esplicito, non prova di indipendenza. Un blocco senza trade non produce una stima finta; quota di repliche indefinite riportata e, se >1%, incertezza INSUFFICIENTE.

Controllo tentativi: lower confidence bound unilaterale al quantile `0,05/M` (**Bonferroni**), M≥20 config preregistrate REAL dell'intero programma incluse fallite/scartate; aumentare M per nuove ipotesi, mai azzerarlo cambiando arm/periodo. Usare M congelato prima dell'apertura holdout, con divieto di nuove ipotesi nello stesso batch. Se il quantile richiede meno di20 repliche di coda, aumentare il numero ex ante secondo `ceil(20*M/0,05)` prima dell'esecuzione, non sulla base del valore del CI.

Sharpe/DSR sulle **serie dei rendimenti netti per seduta**, tutte le sedute flat incluse, tasso risk-free0 dichiarato; Sharpe annualizzato√252 soltanto per esposizione. DSR e N/varianza/tentativi con Sharpe mancante resi espliciti: la formula SP1 è diagnostica per multiple testing/non-normalità e non corregge da sola dipendenza seriale. Non attribuire Sharpe0 a trial falliti/no-trade per inventare V. Con V/N non rappresentativi, `DSR_INCOMPLETE`; nessuna affermazione di correzione completa. La soglia statistica vincolante SP3 è il bootstrap dipendente corretto su M, non il badge/DSR daily SP1. Le soglie SP1 restano invariate.

G2 PASS per una policy solo con **tutte** queste condizioni sia OOS sia holdout (dove specificato):

- Dataset REAL/CAPTURED/STRICT_PIT, G1_DATA READY e tutte le attestazioni/costi/risorse/preprocessing idonei; codice G2_TECH PASS; holdout aperto col protocollo e minimi raggiunti.
- Media round-trip netta **di esecuzione** ≥**5 bps** e lower bound corretto >0 nel caso BASE; P&L/rendimento portafoglio **dopo costi ricorrenti** >0 e lower bound corretto della media dei rendimenti giornalieri del portafoglio >0. Bootstrap congiunto/Bonferroni anche per quest'ultima media, tutti i giorni flat/cost-only inclusi. Le tre lunghezze bootstrap devono mantenere entrambi i lower bound>0; trade profittevoli con costo dati che rende incerta/non positiva la curva non passano.
- Ogni scenario separato e **STRESS_COMBINED** con media netta round-trip e P&L dopo ricorrenti ≥0; nessun errore di campione/uscita occultato. Minimi trade OOS/holdout anche negli stress, altrimenti INSUFFICIENTE, non PASS per zero trade.
- Max drawdown≤**10%**, peggior seduta≥−**2%**, CVaR95 riportato; almeno3 dei4 fold OOS con P&L netto dopo ricorrenti>0.
- Nel singolo OOS e holdout, massimo contributo di un listing e di una seduta≤25% della somma dei P&L positivi; profitto non dimostrato da un unico nome/giorno. Report per mesi e quartili del regime ATR del benchmark con soglie di quartile fit soltanto IS; gruppo scarsamente campionato esplicito, senza pretesa di robustezza a tutti i regimi.
- Zero commistioni REAL/DEMO, fill futuri/impossibili, cassa/esposizione oltre1×, vendite oltre quantità, exit UNRESOLVED o attraversamento non riconciliato di halt/gap/close/corporate. Ritardo positivo della sola uscita oltre H è riportato; se porta oltre il margine di sessione o violazione di continuità fallisce il criterio operativo.

Input non idoneo → NON_IDONEO; campione/metriche non definite o dati mancanti → INSUFFICIENTE; campione idoneo sufficiente che non supera soglie → NON_VALIDATO. Report append-only con tutte le ragioni; il risultato software SUCCEEDED non equivale a G2 PASS. Se nessuna policy supera tutto, nessuna viene promossa e SP6a non parte.

## 12. Persistenza, job e presentazione

Tabelle additive `intraday_research_manifests`, `intraday_research_trials`, `intraday_research_trial_events`, `intraday_research_results`, `intraday_research_holdout_events`, `intraday_quote_size_attestations`, `intraday_price_increment_attestations`, `intraday_news_source_attestations` e riferimenti tipizzati ai dataset/attestazioni; trigger anti UPDATE/DELETE/REPLACE. Operativo job mutabile distinto dall'evidenza; nessun backfill su run daily. Report/curve/fill bounded o child chunk immutabili, pubblicazione completa atomica dopo checkpoint cancellabile. Trial preregistrato resta visibile su cancel; risultato incompleto mai pubblicato come valido.

Nuovi job finiti `INTRADAY_RESEARCH`, `INTRADAY_HOLDOUT` con parametri ID/config pubblica; 202 JobOut e GET/cancel esistenti. Precheck REAL non idoneo/holdout sealed/scopo incompatibile prima di accodare. Nuove API sotto `/intraday/research`: POST manifesto/preregistrazione, POST run, POST holdout/open esplicito, GET manifesto/trial/report/lista con pagine bounded. Aprire holdout è azione esplicita di ricerca, mai implicita in GET/run/boot; non avvia trading o rete. Status/errori fissi senza payload/URL sensibili, input extra respinto.

UI minima nel laboratorio esistente: dataset/feed/namespace, versioni/costi, split e contatori trial, arm/H, risultati OOS/holdout, stress e motivo del gate. Nessun bottone ordine/promozione paper, redesign o nuovo badge daily. Riusare `jobs.ts`, AbortController e serializer di ns esatti estendendone esplicitamente lo scope alle route ricerca. Un report sintetico mostra DEMO/RESEARCH e G2 non valutabile; risultati saved indipendenti da fonti latest. Campione/news/costo insufficienti sono informazioni di prodotto pertinenti, non stack trace.

## 13. Verifica e decisioni approvate

TDD obbligatorio e test esclusivamente offline: valori manuali feature/fee/fill; future-prefix invariance di prezzi/news/daily/attestazioni/split; bundle vs reader v1, timeline e closure; ns tied/quote late/latency; size e scope; warm-up/sessioni/half-day/DST; parziali/timeouts/no exit; confronto ablation senza timing tecnico news-only; registry/cancel/crash; purge/embargo/holdout sealed; bootstrap dipendente/multiplicity/metriche non finite; migrazione legacy/API/UI e zero rete. Il piano specifica allowlist e test per task. Nessun accesso al DB reale `data/investedge.db`.

Decisioni approvate dall'utente il 2026-10-13: regole §4–7, profilo conservativo costi/fill/capitale di ricerca §6/8, campione/split/holdout/soglie §10–11, formato bounded e prerequisiti §3, sequenza del piano. Il consenso documentale non configura dati né avvia cattura/ordini. Budget/diritti/authority quote/status reali e campione sufficiente restano necessari prima della validazione economica; capitale/rischio/runtime del paper saranno scelti in SP6a.

Backlog SP3 oltre il gate intraday: segnali weekly/monthly, fondamentali/macro realizzata, pesi appresi, altri mercati e indicatori challenger dopo SP6a/completamento SP2b; addendum documentale dedicato prima del codice. SP3 intero non diventa VERIFICATO solo col gate intraday.

Fonti primarie verificate il 2026-10-13: [Alpaca quote/barre/revisioni](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data), [feed e piani](https://docs.alpaca.markets/us/docs/about-market-data-api), [limiti paper](https://docs.alpaca.markets/us/docs/paper-trading), tariffario e disclosure §8; [Bailey/López de Prado, DSR](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf), [Politis/Romano, stationary bootstrap](https://statistics.stanford.edu/technical-reports/stationary-bootstrap). Il bootstrap circolare5 del progetto è una scelta proposta per dipendenza a blocchi, non una trascrizione dell'algoritmo stationary bootstrap. Il paper Alpaca omette impatto, coda e slippage da latenza, non limita fill alla size NBBO e non incorpora fee regolamentari: non copiarlo come modello economico. Nessun dettaglio live/margine normativo è necessario per questa proposta; ricontrollarlo nella fase competente.
