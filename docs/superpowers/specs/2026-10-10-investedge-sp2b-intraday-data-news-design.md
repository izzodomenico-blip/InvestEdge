# InvestEdge — SP2b «Dati per l'alpha»: gate dati e news intraday

**Stato:** proposta preparata il 2026-10-10, da approvare prima del codice. Nessun task di implementazione avviato.
**Base:** SP1 VERIFICATO, main remoto = d9a43eee2f35fcda558a1b8d58bacc08a4cd8994.
**Documenti:** attua la spec di programma 2026-09-30 (§2.1, §4–5) e la priorità intraday di PROGRAMMA-OPERATIVO.md. Piano: ../plans/2026-10-10-investedge-sp2b-intraday-data-news.md.

## 1. Risultato e confini

Fornire a SP3 lo stesso flusso causale di barre, quote, universo, news ed eventi sia in replay sia nella raccolta corrente. Ogni informazione ha provenienza, disponibilità, qualità e versione; un risultato congelato resta riproducibile dopo rettifiche o aggiornamenti.

La prima fase copre azioni/ETF USA, USD, sessione regolare, barre native 1 minuto e aggregazioni complete 5/15 minuti. **15/30 minuti è l'holding dal fill**, da implementare e validare in SP3/SP6a, non il timeframe della barra. Tecnica, strategie, sizing, costi/fill e verdetti economici restano SP3; ordini, risk engine 1× e runtime sempre acceso restano SP6a. Trading reale e leva opzionali restano SP6b dopo validazione.

SP2b ha un gate intraday prioritario (Task 1–12) e un backlog distinto (§13). Superare quel gate non completa l'intero SP2b. Dopo il gate tecnico si può progettare SP3; promozione di strategie e avvio paper richiedono anche dati reali idonei, G2 e G3. Nessun agente inserisce credenziali, sottoscrive piani o avvia raccolte live non richieste.

## 2. Stato verificato e riuso

| Componente esistente | Riuso | Confine da preservare |
|---|---|---|
| SafeProviderTransport, ProviderBudgetManager | HTTP sicuro, budget atomico, cache, timeout, cooldown, MockTransport | Le due credenziali Alpaca non sono oggi coperte integralmente dal detector degli header; correggere prima di qualunque adapter. Cache distinta per feed/configurazione pubblica, mai per segreto. |
| Instrument master, listing, provider_symbols, conferme versionate | ID interni, identità verificata, collisioni, evidence hash | Il mapping corrente non è una storia di tradabilità; aggiungere validità e conoscenza as-of. Il ticker da solo non identifica uno strumento. |
| MarketObservationService / price_history | Percorso EOD/quote attuale | La proiezione BAR riduce a una data locale e la lettura sceglie la revisione globale: non usare questo percorso per minute bars. |
| news_items / NewsEngine | Consultazione legacy e sentiment informativo | Il testo viene aggiornato in place e publication mancante può essere sostituita con now: non usare questa tabella come evidenza intraday. |
| lab.jobs e client frontend jobs.ts | Backfill/replay finiti, deduplica, progresso, cancel, terminali | Il singolo worker FIFO non ospita uno stream infinito. |
| SP1 / features_daily | Errori, hash canonici, metodologia e regressioni | D/W/M, score-v1, simulatore daily e ML non diventano intraday cambiando una stringa o √252. |

Architettura proposta: nuovo pacchetto **backend/app/intraday/** con contratti, archivio, identità/universo, calendario, aggregazioni, replay, qualità e snapshot; adapter ufficiali in data_providers. Tabelle additive separate, nessuna proiezione intraday in price_history o features_daily. Le API EOD/score/news attuali restano compatibili.

## 3. Modalità e tempi causali

Separare due dimensioni:

- data_mode = REAL / DEMO; fixture sintetiche marcate come tali, mai prova economica REAL;
- provenance = CAPTURED / HISTORICAL_CURRENT / SYNTHETIC, insieme a replay_grade = STRICT_PIT / RESEARCH_ONLY.

Per ogni versione conservare event_time_ns, received_at_ns (prima ricezione effettiva al processo, prima della coda), persisted_at_ns, admitted_at_ns (ammissione effettiva al reducer condiviso dopo durabilità), available_at_ns, provider, feed, schema_version, payload_hash e batch/capture_id. UTC in interi nanosecondi; RFC3339 solo rappresentazione API. Nessuna perdita per troncamento a microsecondi/date; timezone New York solo per sedute.

**available_at** è il massimo fra ricezione, persisted_at, admitted_at e vincoli di disponibilità (fine barra, pubblicazione/versione verificata). L'admission è un evento persistito della pipeline comune: il consumer corrente non può usare il dato prima di questo confine, e il replay usa lo stesso tempo. Un backlog fra ricezione 09:31:02 e admission 09:31:08 lascia il dato assente sia live sia replay al cutoff 09:31:05. received_at conserva la latenza di rete; admission - received misura la latenza interna. Crash prima dell'admission non produce un evento eleggibile; gap/admission mancanti sono conteggiati. Una revisione arrivata tardi si applica non prima della sua ricezione e admission; un timestamp futuro o incoerente viene quarantinato, non retrodatato. Ordinamento del replay: available_at_ns, received_at_ns, ingest_sequence; a parità, ordine originale locale conservato.

Uno storico scaricato oggi non rivela quando ogni versione fosse disponibile allora: received_at resta oggi. **HISTORICAL_CURRENT è RESEARCH_ONLY per il periodo antecedente alla cattura**, anche se la fonte fornisce created_at/updated_at o un parametro asof. Non inventare ricevimenti storici. Un eventuale archivio certificato della fonte richiede un contratto/documentazione separato prima di assegnare STRICT_PIT.

DEMO e SYNTHETIC possono verificare il software con clock fissato; non sbloccano G1_DATA né vengono mescolati in snapshot/esperimenti REAL.

## 4. Feed, capacità e sicurezza Alpaca

Usare API personali Trading/Market Data, non Broker API. Configurazione disabilitata di default; chiavi soltanto nell'ambiente locale configurato dall'utente. Nessun valore in documenti, parametri dei job, hash, cache, URL, fixture o errori. HTTP autenticato con i due header ufficiali, WebSocket con frame auth in memoria: vietato registrare frame/header completi.

Al 2026-10-10, Basic offre IEX realtime, copertura parziale; la documentazione indica limiti di sottoscrizione e accesso allo storico recente dipendenti dal piano. SIP realtime richiede diritti configurati. delayed_sip ha 15 minuti di ritardo. **Feed esplicito su ogni richiesta**, senza default implicito o fallback silenzioso. IEX non è NBBO né volume consolidato; gli esperimenti IEX non si confrontano con SIP come se fossero gli stessi dati. [Piani e autenticazione Alpaca](https://docs.alpaca.markets/us/docs/about-market-data-api).

Proposta per la promozione iniziale: **SIP realtime con quote consolidate**, dopo configurazione dell'utente. IEX resta supportato per raccolta e ricerca dichiarata; delayed SIP può essere consultato ma non sblocca ingressi realtime 15/30 minuti. Questo requisito non acquista un abbonamento. Un cambio di feed/diritti/versione crea un nuovo profilo e richiede nuova verifica.

Profilo pubblico versionato: feed, capacità richieste/attestate, delay dichiarato, max simboli (benchmark compresi), max connessioni, quote condizioni ammesse, limiti HTTP minuto/giorno/mese, limite bytes/disco e policy_version. Credenziali e identificativi personali esclusi. Contatori/connettività distinti dal profilo; 401/403 -> capacità indisponibile, mai upgrade automatico. Status/LULD possono avere diritti ulteriori: disponibilità non presunta dal solo accesso a SIP.

HTTP esclusivamente GET su host/path allowlist:
- data.alpaca.markets: /v2/stocks/bars, /v2/stocks/quotes, /v1beta1/news, /v1/corporate-actions;
- paper-api.alpaca.markets: /v2/assets e /v2/calendar, solo metadata in lettura.

WebSocket esclusivamente stream.data.alpaca.markets, /v2/iex o /v2/sip, e /v1beta1/news; delayed_sip solo profilo consultivo. Non usare trading stream/account/orders. Nessun endpoint POST ordini, nessuna query segreta, nessun redirect. La configurazione non accetta URL arbitrari.

Conservare i limiti governati HTTP esistenti e aggiungere limiti stream su connessioni, sottoscrizioni, frame, coda, bytes/disco, riconnessioni. Retry con backoff bounded, rate-limit/cooldown condiviso; 401/403 stop, 429 rinvio. Risposta/frame che riecheggia uno dei due segreti: scartare prima della persistenza. Nessuna transazione SQLite aperta durante rete o attesa.

## 5. Identità, calendario e universo

### 5.1 Identità

Alpaca asset UUID, instrument_id e listing_id distinti. Non confondere assets.id locale con UUID del broker. Conferma esplicita e versionata per mapping Alpaca BAR/QUOTE/NEWS; simboli e venue verificati, non equivalenza per nome. Eventi corporate con CUSIP/ISIN forniscono evidenza ma non autorizzano un merge automatico.

Versione identità: instrument/listing, UUID fonte, ticker/venue, valid_from/valid_to (tempo economico, anche UNKNOWN), known_at, evidenza e stato. Query as-of richiede conoscenza e validità compatibili; mapping ambiguo o non documentato -> esclusione. Alpaca asof serve al **symbol mapping**, non a restituire lo stato storico dei prezzi. Usare asof esplicito e conservare simbolo richiesto/restituito. Ticker riutilizzato con UUID diverso produce nuova identità. [Barre e asof](https://docs.alpaca.markets/us/reference/stockbars).

Snapshot universo acquisiti prima della seduta, append-only, con active/inactive, tradable, asset class/strumento a leva attestato, valuta/venue, feed disponibile, motivi d'esclusione e cutoff. La risposta corrente /assets non prova l'universo di anni passati. In assenza di storia usare universo prospettico catturato; mai ricostruire membri storici scegliendo sopravvissuti odierni o liquidità futura. Per ETF leva/inverse non attestata -> non eleggibile al primo paper. Filtri liquidità e ranking solo su sedute precedenti, definiti in SP3; quote stale bloccano entrate indipendentemente dal ranking.

Il ricollegamento legacy I3 resta nel backlog: il gate può lavorare con listing risolti nuovi/esistenti, senza riscrivere posizioni/import del portafoglio.

### 5.2 Calendario USA

Persistenza versionata del calendario ufficiale di trading: session_date, open/close UTC, America/New_York, known_at, fonte/hash/versione. Festivi, DST e chiusure anticipate effettivi; nessuna approssimazione con lun–ven. Fuori range disponibile -> CALENDAR_MISSING, nessuna seduta inventata. [Calendar API](https://docs.alpaca.markets/us/reference/legacycalendar).

Intervalli [open, close), close speciale della seduta. Il 5/15 minuti è ancorato all'open della seduta; nessun gruppo attraverso notti, halt o feed diversi. Barre pre/post-market archiviate ma escluse dal primo universo operativo. Il limite d'entrata vicino alla chiusura è funzione holding + margine d'uscita di SP3/SP6a.

## 6. Barre e quote

### 6.1 Acquisizione

REST: 1Min, adjustment=raw, currency=USD, start/end/asof/feed/sort espliciti; consumo di tutte le next_page_token, anche quando la prima pagina contiene un solo simbolo. Un ciclo di token o fine prematura produce batch PARTIAL, non COMPLETE. Limiti pagina/periodo/simboli/bytes prima della rete. Ripresa per chunk idempotente; righe complete già salvate conservate e conteggiate, snapshot solo di chunk completati.

STREAM: bars, updatedBars e quotes; status/LULD dove attestati. I timestamp delle barre descrivono l'inizio dell'intervallo, non disponibilità del close. Il messaggio originale e updatedBars sono versioni differenti. Una barra chiusa ricevuta, resa durable e admitted alle 09:31:02 diventa disponibile a quell'istante; con backlog vale il confine successivo del §3; la correzione ricevuta 09:31:31 non cambia il replay 09:31:05. [Canali, quote e revisioni](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data).

Nessuna promessa di tick tape completo: quote capture è il flusso realmente ricevuto con stato di gap; trades/corrections/cancelErrors non sono necessari per ricostruire barre già emesse. Se SP3 richiederà microstruttura basata su trades, servirà un addendum, con nuova capacità e test.

### 6.2 Validazione e aggregazione

OHLC positivi/finiti, low <= min(open,close) <= max(open,close) <= high, volume non negativo, intervallo coerente, fonte/feed/identità noti; finite JSON. Nessuna candela sintetica per un minuto senza transazioni: distinguere EMPTY_CONFIRMED (solo se attestato), MISSING, HALTED, NOT_SUBSCRIBED e OUT_OF_SESSION. Nessun forward-fill di OHLC/volume.

Quote: bid/ask, size, exchange, conditions/tape, timestamp nanosecondi. Prezzi positivi; bid > ask -> CROSSED e non eseguibile; zero size, stale e condizioni escluse -> reason code. Conservare la size originale con unità della fonte (lo stream dichiara round lots); la normalizzazione richiede lotto attestato, mai assumere sempre 100 azioni. Quote IEX marcate copertura venue, quote SIP consolidate secondo contratto; nessuna size trattata come garanzia di fill. Una quote tardiva con event_time precedente non sostituisce il mercato corrente con uno stato più vecchio.

Aggregatore puro as-of: usa versioni note al cutoff e intervalli chiusi; open primo, high max, low min, close ultimo, volume somma. Gruppo incompleto -> non eleggibile; niente riuso della barra precedente. VWAP aggregato da somma(vw * volume) / somma(volume) se tutti gli input hanno vw valido; volume zero -> null. Revisioni cambiano solo letture successive e nuovo digest, mai uno snapshot congelato. Reset sessione VWAP e caratteristiche tecniche sono SP3.

Daily di contesto SP3 ricostruita dalle sole barre complete di sedute precedenti del medesimo profilo, con copertura dichiarata; non usare il dailyBar progressivo come giorno concluso.

## 7. News e eventi point-in-time

Adapter storico/stream Alpaca news; conserva source article ID, source, created_at, updated_at, first_received_at, available_at, headline/summary/content consentiti dal diritto configurato, hash/versione, lingua se nota, simboli originali e mapping. Benzinga è la fonte dichiarata della news API; la copertura non equivale a tutte le notizie di mercato. [Storico](https://docs.alpaca.markets/us/docs/historical-news-data), [schema realtime](https://docs.alpaca.markets/us/docs/streaming-real-time-news).

Archivio append-only per (provider, article_id, versione/hash). Duplicate delivery identificabile con lo stesso ID/versione fonte, o ripetizione consecutiva invariata dello stato -> no nuova occurrence/nessuna modifica del first_received di quella occurrence; aggiornamento testo o simboli -> nuova occurrence. Un ritorno A→B→A con nuova versione/updated_at o dopo B conserva l'ultima occurrence A e la sua nuova availability: payload deduplicabile non significa timeline deduplicabile. Versioni fuori ordine conservate; la scelta non retrocede a updated_at più vecchio già superato. Publication/updated invalidi -> quarantena, non now inventato. Testo HTML sanitizzato/reso come testo, nessuna esecuzione o fetch dei link contenuti. Persistenza whitelist con limiti dimensioni; niente raw header/frame o HTML illimitato. Licenza/retention configurate prima di salvare corpi completi; headline/hash/provenienza bastano per stato di copertura, non per una feature che richieda testo assente.

Relazioni many-to-many fra versione, instrument/listing, mercato/settore ed event_id. Deduplica consegna per articolo; cluster deterministici versionati per evento senza cancellare i diversi resoconti. Conoscenza del cluster al cutoff: una correlazione scoperta domani non cambia il cluster di ieri. Simbolo ambiguo non assegnato al portafoglio per ticker. NEWS_MISSING/STALE/DISABLED sono stati distinti da «nessuna news in una finestra coperta».

Tassonomia fattuale v1: EARNINGS, GUIDANCE, M_AND_A, FINANCING_DILUTION, REGULATORY, SEC_FILING, SECTOR, MACRO, OTHER/UNKNOWN. Conservare categoria, regola/versione e evidenza; se l'articolo non documenta il fatto -> UNKNOWN. SP2b non converte categoria/sentiment in score o ordine; rilevanza predittiva, decadimento e ablation tecnica/news sono SP3. Confronti numerici con consensus solo quando le attese sono archiviate as-of.

Corporate actions: endpoint ufficiale /v1/corporate-actions, paginato; split/reverse split, dividendi, cambi nome, merger e delisting/reorganization conservati con known_at ed effective_at distinti, ID/versione/cancellazione se nota. La fonte non garantisce tempestività alla pubblicazione: data ex/process non prova disponibilità. REST tardivo è RESEARCH_ONLY per il passato. SSE corporate actions con storico mutation è un possibile successivo addendum, non presunto archivio già disponibile. [Contratto e limiti](https://docs.alpaca.markets/us/reference/corporateactions-1).

Prezzi raw sono la base del replay e dei fill futuri. Nel gate, **non attraversare split/reorganizzazioni non riconciliati**; segnare discontinuità e invalidare finestre di feature/etichette. Nessuna serie all-adjusted corrente usata per retrocorreggere decisioni passate. Dividendi non producono rettifica automatica del P&L; trattamento economico esplicito in SP3.

Halt/resume e LULD: timestamp e disponibilità, stato UNKNOWN se stream/canale non attestato. **Bootstrap obbligatorio:** prima di ammettere un listing in LIVE dopo startup/gap serve un checkpoint autorevole dello stato corrente, con fonte/contratto attestati, listing/venue coperti, snapshot_at/received/admitted/expiry e prova di completezza. Il Task 6 implementa il validatore/importatore di tale artefatto; non assume che Alpaca invii uno snapshot allo subscribe. NORMAL può essere inizializzato solo da stato esplicito o da lista di halt dichiaratamente completa (incluse sospensioni persistenti da sedute precedenti) entro expiry; non dal solo active/tradable di /assets, da ack o da assenza del ticker in una lista parziale. Resume quotation-only non equivale a trading resume. Senza checkpoint verificabile -> STATUS_BOOTSTRAP_UNAVAILABLE, listing escluso e G1_DATA INSUFFICIENTE. Fonte completa e diritti da verificare con l'utente prima della cattura reale, senza acquisti. La provenienza deve essere riscontrabile nel contratto della fonte e nell'artefatto originale: una dichiarazione arbitraria REAL/NORMAL non è un'attestazione. Un checkpoint importato dopo la cattura non risana il passato. Il feed RSS Nasdaq è una fonte di riscontro, ma non si presume completo per tale bootstrap: i filtri documentati per data possono omettere halt iniziati prima. [RSS Nasdaq e filtri](https://classic.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS), [semantica filtri](https://classic.nasdaqtrader.com/snippets/tradehaltaccordion.html). Nessun resume inferito da una barra o dal ritorno della connessione. Disconnessione/overflow/apertura della raccolta -> stato di continuità sconosciuta e niente nuove entrate; posizioni e protezioni saranno gestite da SP6a.

Calendari macro ufficiali BLS (CPI, employment) e Fed (FOMC), più import locale di annunci ufficiali di emittenti per earnings programmati. Snapshot versionato con scheduled_at (nullable se ora non pubblicata), known_at e fonte; date senza ora -> evento con incertezza per tutta la seduta, non orario inventato. Cambio calendario non modifica passato. Rilasci e numeri realizzati, fondamentali SEC/XBRL completi e sorprese macro sono backlog. [BLS](https://www.bls.gov/schedule/news_release/), [Fed](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).

## 8. Persistenza e replay condiviso

Schema additivo proposto; durante Task 1 definire CHECK/FK/indici esatti senza cambiare i contratti di questo documento:

| Tabella | Contenuto |
|---|---|
| intraday_ingest_runs | Metadati operativi, chunk/cursore, stato COMPLETE/PARTIAL/FAILED, contatori/limiti; nessun segreto |
| intraday_observations | Versioni BAR/QUOTE/STATUS/LULD con envelope §3, chiave evento, payload whitelist e qualità |
| intraday_capture_events | Log append-only CAPTURE_START/ACK/ADMISSION/GAP/BOOTSTRAP/CLOCK/STOP con tempi, lease/capture_id e scope listing/canali; nessuna auth frame |
| intraday_identity_versions | Relazione UUID/listing/ticker/validità/conoscenza e attestazioni |
| intraday_calendar_versions | Sedute ufficiali versionate, apertura/chiusura |
| intraday_universe_snapshots / intraday_universe_members | Header/hash/cutoff e membri/esclusi, identità/diritti congelati |
| intraday_news_versions / intraday_news_links | Articoli e mapping versionati; cluster/tassonomia con versione as-of |
| intraday_event_versions | Corporate actions, macro/earnings programmati, stato di halt come eventi tipizzati |
| intraday_dataset_snapshots / intraday_dataset_members | Manifest immutabile e riferimenti alle versioni effettive |
| intraday_quality_reports | Report congelato, metriche, policy, esito G1 e limiti |

Versioni, snapshot, membri e report append-only con trigger anti UPDATE/DELETE/REPLACE, FK RESTRICT rispetto alle identità. Gli ingest runs e stato corrente collector sono metadati operativi mutabili, non evidenza. Nessun purge a cascata dell'evidenza da assets legacy; cleanup/retention non inclusi nel gate (stop raccolta se quota disco superata). Backup pre-migrazione obbligatorio come prepare_database, smoke solo DB temporanei.

Logical event key include provider, feed, modalità, listing, kind e identità evento; BAR include start/end, QUOTE include timestamp + fingerprint/sequence fonte se disponibile. Il payload può essere deduplicato per hash, ma **le occurrence della timeline sono distinte**. Duplicato con event/revision ID fonte identico -> stessa occurrence; senza revision ID deduplicare soltanto ripetizioni consecutive invarianti della stessa logical key e posizione del capture. A→B→A conserva tre occurrence con le tre availability, anche se la prima e l'ultima condividono payload hash. Backfill e capture appartengono a provenance diverse; non usare un ID inventato come ID fonte. First_received immutato per occurrence; un backfill corrente non sostituisce l'originale catturato.

API interna condivisa proposta:
- ingest(envelopes, captured_clock) -> conteggi accettati/duplicati/quarantena;
- read_as_of(listing_ids, kind, cutoff_ns, profile_id, data_mode) -> versioni + esclusioni;
- aggregate_as_of(..., timeframe=1Min/5Min/15Min) -> barre chiuse/coverage;
- replay(snapshot_id) -> sequenza di eventi archiviati; niente rete;
- freeze_dataset(request) -> snapshot_id/digest/quality_report_id.

read_as_of filtra available_at <= cutoff e seleziona solo revisioni già note di ogni evento; quote state poi sceglie massimo event_time disponibile, senza regressione da late delivery. Per barre complete del passato una revisione può entrare nei calcoli successivi, ma non riscrive una decisione già salvata. Il manifest include **tutte le occurrence necessarie a riprodurre la timeline nell'intervallo e il suo stato iniziale**, comprese versioni superate già disponibili entro freeze: A@t2 e B@t8 congelate a t10 conservano A per una lettura t5. Non basta l'ultima versione al cutoff finale. Include feed/profilo, universo/mapping/calendario/news/cluster/eventi con loro timeline, capture log append-only (ack/admission/gap/bootstrap/skew/start/stop), cutoff, policy, aggregazione, limiti e schema version. Ingest runs e stato corrente collector mutabili non sono fonte di evidenza del replay o del digest. Corpi/source rows non vengono riletti dall'«ultimo» dopo congelamento; se assenti -> SNAPSHOT_INPUT_MISSING, nessun ricorso a fonti correnti.

## 9. Collector e job

Collector di dati separato dal worker lab: un gestore bounded, avvio/arresto **espliciti**, disabilitato al boot, una proprietà esclusiva per profilo/DB, clock e socket factory iniettabili. Non avvia ordini. Un'app seconda sul medesimo DB non può aprire un secondo collector: lock/lease locale e owner nonce; rinnovo/expiry testati con clock finto. Una dipendenza WebSocket diretta piccola può essere necessaria nel Task 7; non usare un SDK broker che aggiunge ordini al perimetro.

Stati STOPPED/CONNECTING/LIVE/DEGRADED/BACKOFF/FAILED. LIVE richiede auth + ack di tutte le sottoscrizioni previste, canali attestati, bootstrap status raccordato e nessun gap irrisolto; l'ack è congelato nel capture log. Disconnessione, socket silence timeout, queue overflow, clock skew, restart e quota disco -> DEGRADED/FAILED, gap registrato. Non scartare dati silenziosamente; stop nuove raccolte quando non possono essere archiviate integralmente.

Handshake status: start apre CONNECTING/DEGRADED e persiste il buffer di eventi dopo ack, senza ammettere listing al gate. Acquisire/importare poi il checkpoint autorevole con snapshot_at dentro l'intervallo continuo già catturato; raccordare tutti gli eventi status successivi allo snapshot fino all'admission del checkpoint, senza gap, prima di LIVE. Gli eventi tied/ambigui mantengono lo stato più restrittivo. Un checkpoint precedente al primo ack non può inizializzare NORMAL: NORMAL@t5/HALT@t8/ACK@t10 resta UNKNOWN; occorre un nuovo checkpoint raccordabile dopo ack. Ogni reconnect ripete il handshake e il capture log documenta intervallo, checkpoint e applicazione; expiry non sostituisce continuità.

Recovery: riconnessione bounded; risottoscrizione con ack, backfill del gap e controllo sovrapposizioni. Il backfill REST risolve copertura finale di ricerca ma **non ripristina la disponibilità storica STRICT_PIT**. Il report conserva finestre non osservate; non dichiarare LIVE/continuità precedente solo perché sono arrivate barre più recenti. Una nuova finestra sana può ricominciare dopo inizializzazione documentata; unknown halt resta esclusione.

Job finiti: INTRADAY_METADATA, INTRADAY_BACKFILL, INTRADAY_SNAPSHOT, INTRADAY_QUALITY; stesso cancel cooperativo/restart, nessuna transazione durante rete. Estendere CHECK/JobKind con migrazione compatibile; queued/running storici e handler SP1 conservati. Il cancel può lasciare chunk di dati acquisiti, mai un manifest/report parziale pubblicato come completo.

## 10. API e visibilità

Route nuove /intraday, listing IDs e profile ID, nessuna credenziale/URL nel body:

| Route | Contratto |
|---|---|
| GET /intraday/status | profili/capacità non sensibili, collector, gap, budget e qualità; zero rete |
| POST /intraday/metadata/refresh | 202 JobOut bounded per calendario/metadata e periodo; precheck config/profilo/budget senza richiedere calendario preesistente |
| POST /intraday/identity/preview, /apply | preview mapping su metadata salvati e applicazione esplicita della relazione UUID/listing; token versionato, nessuna conferma automatica |
| POST /intraday/status-checkpoints | import bounded di artefatto autorevole; validazione fonte/completezza/scope/expiry; nessun override manuale NORMAL |
| POST /intraday/backfill | 202 JobOut, listing_ids, tipi/periodo, profilo; limitati |
| POST /intraday/snapshots | 202 JobOut, periodo/cutoff, modalità, grade richiesto e policy |
| GET /intraday/snapshots/{id} | manifest congelato e quality_report; input paginati per tipo |
| POST /intraday/quality | 202 JobOut su snapshot esistente |
| GET /intraday/news | versioni/mapping paginati, filtro cutoff e listing; contenuto consentito |
| POST /intraday/collector/start, /stop | stato collector e risultato idempotente; start solo REAL_DATA abilitato e profilo valido |

Bootstrap su DB vuoto: metadata/refresh -> preview/apply identità -> start in CONNECTING con ack/cattura status -> checkpoint autorevole raccordato a quella cattura -> LIVE/nuova finestra eleggibile. Il backfill storico richiede metadata/identità/calendario, resta RESEARCH_ONLY e non richiede di inventare un checkpoint per il passato. Il refresh non conferma mapping né avvia stream; backfill/start successivi fanno precheck dei rispettivi prerequisiti prima della rete.

422 per parametri invalidi; 404 risorsa assente; 409 REAL_DATA_DISABLED, FEED_NOT_ENTITLED, IDENTITY_UNVERIFIED, CALENDAR_MISSING, CAPTURE_GAP, SNAPSHOT_NOT_PIT, COLLECTOR_ALREADY_OWNED; errori sanitizzati. GET non effettua refresh né scrive. Consenso alla raccolta non è consenso agli ordini.

Data Center: aggiunta di stato feed/diritti, copertura per seduta/listing, continuità, ritardi, quota disco/budget e snapshot/G1. News: consultazione as-of/versioni/categorie con origine e mapping, missing distinto da nessun evento. Riusare polling/cancel/AbortController e stili, niente redesign. Nessun badge VALIDATO di SP1 applicato all'intraday.

## 11. Gate e politica qualità ex ante

**G1_TECH** PASS soltanto con test offline, build/lint dove pertinenti, migrazione/compatibilità, replay e snapshot, collector fake, secret scan e review senza Critical/Important. Non richiede credenziali o chiamate live.

**G1_DATA** è un esito immutabile per dataset/profilo/periodo: READY / INSUFFICIENTE / NON_IDONEO. READY certifica dati idonei al successivo esperimento, non redditività. Policy proposta v1:

- almeno 20 sedute consecutive catturate, almeno 10 listing risolti per universo prospettico, benchmark mercato e settore con stesso profilo; copertura eligibility dichiarata per seduta, mai selezione sui trade redditizi;
- copertura raw: almeno 99% dei minuti attesi dell'universo pianificato coperti da barre 1 minuto, denominatore include gap e interruzioni, halt noti mostrati separatamente;
- griglia tecnica indipendente dalle strategie: punti 1/5/15 minuti ancorati all'open, a fine gruppo + 10 secondi, solo gruppi interamente nella seduta. Per **ogni listing pianificato (benchmark inclusi), seduta e timeframe**, almeno 90% dei punti pianificati deve essere congiuntamente usabile e il numero usabile deve essere >0. Un punto richiede barre chiuse complete, quote entro soglia, continuità dei canali news/status richiesta e bootstrap valido; assenza di articoli con copertura attestata è covered-zero, non gap. Gap, UNKNOWN, quote stale e gruppi incompleti restano nel denominatore: 100% dei soli blocchi ammessi non basta. Listing/sedute esclusi non concorrono ai minimi 10/20 e restano elencati nel report; nessuna selezione ex post del periodo per superare le soglie;
- quote SIP realtime nell'archivio, compatibili con barra/listing/feed e non crossed/zero size; età massima proposta 2 s al decision timestamp, bar delay massimo 10 s dalla fine intervallo. Valori configurabili solo in nuova policy congelata; distribuzioni p50/p95/max e quota esclusa registrate;
- timestamp verificabili, mapping/universo/calendario as-of, nessuna barra provvisoria nel set eleggibile, nessun split/halt UNKNOWN attraversato;
- news stream acquisito nelle finestre attese con continuità, ID/versioni e grado STRICT_PIT. Il numero di articoli può essere zero se la finestra è coperta; non è prova di assenza di notizie esterne alla fonte. Calendari obbligatori disponibili as-of; UNKNOWN conservato;
- REAL + CAPTURED, nessun SYNTHETIC/DEMO/RESEARCH_ONLY nel campione del gate; profilo operativo SIP realtime, quote/status richiesti attestati. Dataset IEX/delayed o storico corrente resta RESEARCH_ONLY/NON_IDONEO per questa promozione.

Minimi 20/10 e copertura sono requisiti tecnici proposti, **non campione sufficiente a validare una strategia**. SP3 fisserà separatamente ex ante sedute/trade IS/OOS/holdout, purge, embargo, incertezza e soglie nette. Nessun rilassamento a posteriori per fare passare G1; una modifica policy/diritti/feed genera nuovo report.

Senza configurazione dati reale dell'utente è possibile completare G1_TECH; G1_DATA resta INSUFFICIENTE. SP3 può sviluppare e verificare il proprio software offline; nessuna strategia passa G2 né accede al paper con soli fixture o storici RESEARCH_ONLY.

## 12. Verifica e prestazioni

| Proprietà / regressione | Prova offline prevista |
|---|---|
| Tempi causali e nanosecondi | Quote a 1 ns diverse, UTC/DST, timestamp future, backlog coda; ricevimenti mai riscritti |
| Causalità per cutoff | Append/remove/modify futuro di barre, news, identità/calendario/eventi non cambia prefisso né manifest precedente |
| Revisioni | updatedBars/news tardive/fuori ordine, duplicate delivery, backfill dopo capture, delete/correction event |
| Calendario | Holiday, DST USA/Europa non coincidenti, half-day, prima/ultima barra e gruppo incompleto |
| Universo | Ticker riutilizzato, rename, inactive/delisting e membri comparsi in futuro; nessun sopravvissuto scelto retroattivamente |
| Sicurezza/budget | Entrambi i segreti sentinella HTTP+WS, query/redirect/host arbitrario, response echo, 401/403/429, tutti i retry contati |
| Collector | Bootstrap assente/stale/parziale, halt overnight, NORMAL@t5/HALT@t8/ACK@t10, handshake checkpoint dopo ack, backlog admission e cutoff live/replay; Auth/ack parziale, symbol cap inclusi benchmark, socket silence, queue overflow, reconnect/gap/restart/lease; zero ordini |
| REAL/DEMO/SP1 | Nessuna minute bar in price_history; news legacy non alimenta evidenza; EOD/score/jobs daily invariati |
| Snapshot | Timeline A→B→A, superseded/pre-periodo e capture log congelati; UPDATE/DELETE/REPLACE rifiutati, missing source fail-closed; rivedere fonti non cambia digest/risultato congelato |
| Qualità | READY sintetico solo prova funzione, mai certificazione REAL; denominatore e minimi non vacui sulla griglia 1/5/15, quote tutte stale/status UNKNOWN mai READY, IEX/delayed non promosso |
| API/UI | 202, terminali/cancel, GET senza I/O, errori, abort, versioni e assenza di news distinti |

Smoke su DB temporaneo: 30 simboli × 20 sedute × 390 barre e quote sintetiche campionate, news con revisioni e mezzo giorno; misurare ingest, freeze, replay, dimensione DB, memoria, query as-of e lag coda. Target indicativi query as-of p95 <= 250 ms sul fixture, batch replay <= 60 s; throughput collector verificato contro input peak dichiarato, zero perdite silenziose. Non è benchmark di un SIP tick tape completo. Niente nuovo acquisto/hardware o retention illimitata implicita.

## 13. Backlog restante SP2b e passaggio

Dopo gate intraday -> SP3 gate strategie -> SP6a paper -> completamento SP2b/SP3. Il piano del gate non autorizza subito:
- ricollegamento legacy I3 con preview/apply/backup e conservazione import/posizioni;
- fondamentali SEC EDGAR XBRL point-in-time per accession/acceptance, restatement e facts; date fiscali non sono disponibilità. SEC non richiede API key per queste letture; configurazione fair-access da utente, nessuna email personale nei report. [SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces);
- fondamentali/eventi UE, consensus di revisioni e insider, rilasci/sorprese macro e universo IPO/S-1/F-1/424B;
- archive corporate-action SSE certificato, prezzi adjusted/total-return e fonte FX intraday/EUR con disponibilità effettiva (i FX daily SP1 non certificano conversione intraday);
- estensione crypto/UE/altri orizzonti.

Queste voci richiedono addendum con provider/diritti, contratti e allowlist/task dettagliati prima del codice; non restano un insieme implicito di «migliorie». Il programma conserva SP2b IN CORSO finché quel backlog non è verificato.

## 14. Decisioni proposte per approvazione

1. Archivio separato con tempi/versioni, raw prices e replay condiviso; compatibilità SP1.
2. IEX ricerca, SIP realtime come requisito del primo gate di promozione; nessun acquisto automatico.
3. Storico REST RESEARCH_ONLY prima della cattura; avviare futura raccolta prospettica solo su richiesta/configurazione dell'utente.
4. Gate tecnico distinto da dataset reale READY; policy v1 §11 e minimi dati separati dalla validazione SP3.
5. News versionate informative, calendari macro/earnings e corporate events con missing esplicito; tecnica/news/strategia a SP3.
6. Eseguire prima i 12 task intraday, poi la sequenza SP3/SP6a e backlog. Nessun ordine o leva in SP2b.

Capitale, rischio per trade/giorno, drawdown, runtime sempre acceso e idoneità conto restano decisioni SP6a/SP6b. Budget/diritti/feed e licenza news sono necessari prima delle raccolte reali; non impediscono progettazione e TDD offline.

Fonti ufficiali aggiuntive verificate il 2026-10-10: [quotes storiche](https://docs.alpaca.markets/us/reference/stockquotes-1), [news REST](https://docs.alpaca.markets/us/reference/news-3), [assets](https://docs.alpaca.markets/us/reference/get-v2-assets-1), [market WebSocket](https://docs.alpaca.markets/us/docs/streaming-market-data). Ricontrollare contratti e limiti alla loro implementazione; niente copie di prezzi commerciali nella configurazione.