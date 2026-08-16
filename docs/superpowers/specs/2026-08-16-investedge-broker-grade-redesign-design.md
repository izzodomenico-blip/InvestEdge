# InvestEdge — redesign broker-grade, paper automation e mobile readiness

**Stato:** approvato nel brainstorming del 16 agosto 2026

**Direzione visiva:** Calm Intelligence

**Ambiente iniziale:** PC Windows locale

**Valuta base:** EUR

## 1. Obiettivo

Trasformare InvestEdge in uno strumento locale affidabile per:

- seguire un portafoglio reale, inizialmente vuoto, senza mescolarlo con dati demo;
- creare più portafogli paper con budget virtuali indipendenti;
- offrire il più ampio universo possibile di azioni, ETF, obbligazioni, ETC/ETN, cripto e riferimenti FX compatibile con fonti gratuite e uso personale;
- acquistare e vendere strumenti reali usando prezzi di mercato osservati e costi simulati realistici;
- eseguire strategie automatiche solo nei portafogli demo;
- mostrare P/L giornaliero e totale, rischio, motivazioni e qualità dei dati;
- offrire un'interfaccia moderna, semplice e adattiva su PC;
- predisporre API, design system e contratti per futuri client iOS e Android;
- predisporre, ma non attivare, un adapter Trade Republic futuro.

InvestEdge rimane un sistema di analisi e simulazione. Non promette guadagni e non sostituisce un intermediario, un consulente finanziario o un professionista fiscale.

## 2. Decisioni approvate

| Area | Decisione |
|---|---|
| Portafoglio reale | Registro separato, inizialmente vuoto |
| Simulazioni | Più portafogli demo con budget indipendenti |
| Strumenti demo | Strumenti e prezzi reali; capitale e possesso virtuali |
| Ampiezza universo | Catalogo esteso, ricercabile e aggiornabile; automazione solo sugli strumenti qualificati |
| Operatività | Manuale e automatica, ma esclusivamente paper |
| Rischio predefinito | Profilo Bilanciato; disponibili Prudente e Aggressivo |
| Runtime iniziale | Servizio locale Windows; nessun costo hosting |
| Assenze del PC | Nessun ordine durante spegnimento/sospensione; recupero e riconciliazione al ritorno |
| Trade Republic | Adapter disabilitato e fail-closed; solo futura integrazione ufficiale |
| Navigazione | Cinque hub: Oggi, Portafogli, Mercati, Laboratorio, Dati e backup |
| Estetica | Calm Intelligence, con modalità chiara complementare |
| Grafici | Interattivi, leggibili, accessibili e sempre accompagnati da fonte/freschezza |
| Mobile | Futuro client condiviso iOS/Android; UI adattata alle convenzioni native |

## 3. Problemi da risolvere prima delle nuove funzionalità

Le nuove superfici non possono poggiare sui comportamenti critici rilevati nell'audit. La fase iniziale deve correggere e proteggere almeno:

1. conversioni multivaluta: nessuna somma diretta di EUR, USD o altre divise;
2. import e allocation: la sostituzione delle posizioni non deve conservare cash incompatibile o creare capitale;
3. short e cover: quantità firmate, lotti, P/L, scenari e fisco coerenti;
4. fiscalità: eventi short, aliquote configurate per anno/tipo e scadenza delle minusvalenze;
5. scenari: le passività short non possono essere azzerate;
6. ML: split temporale privo di leakage;
7. migrazioni legacy: backup prima della migrazione e indici creati solo dopo lo schema richiesto;
8. cancellazioni: niente cascade distruttiva implicita per asset usati da ordini o storico;
9. import remoto: blocco SSRF, redirect non fidati e download senza limiti;
10. segreti: token esclusi da URL, log ed errori;
11. avvio/Docker: binding locale, variabili frontend coerenti e nessuna API distruttiva non autenticata;
12. dipendenze frontend: vulnerabilità note risolte o motivate prima della consegna.

La compatibilità dei flussi già funzionanti è un requisito. Le correzioni saranno chirurgiche e protette da test di regressione.

## 4. Architettura logica

### 4.1 Instrument master

Un'identità strumento non può basarsi sul solo ticker. Il master usa una chiave interna e conserva:

- ISIN, quando esiste;
- FIGI e identificativi alternativi;
- ticker per provider e venue;
- MIC/venue, valuta di quotazione e timezone;
- tipo strumento e asset class;
- stato di negoziabilità e timestamp di verifica Trade Republic;
- sorgente e data del dato identificativo.

Cripto e coppie FX non ricevono ISIN inventati. ETF, ETC, ETN o altri prodotti che rappresentano crypto, valute o materie prime usano invece il proprio ISIN.

Il catalogo ufficiale Trade Republic Italia costituisce una base versionata, non una garanzia permanente. `trade_republic_verified_at` distingue una verifica recente da una semplice presenza storica nel catalogo.

#### 4.1.1 Copertura massima senza degradare l'affidabilità

Il catalogo metadata viene mantenuto molto più ampio dell'insieme di strumenti caricati attivamente nei provider di prezzo. Questo consente di cercare molte opportunità senza consumare quote API per migliaia di titoli inutilizzati.

Gli strumenti sono classificati in tre livelli:

1. **Qualified** — identificativi risolti, valuta/venue note, prezzo e storico sufficienti, qualità compatibile con la strategia; utilizzabili dall'automazione paper;
2. **Observable** — ricercabili e consultabili, ma con dati delayed/EOD o storico insufficiente; utilizzabili per watchlist, analisi compatibili e completamento dati;
3. **Reference only** — indici, FX, tassi, macro o strumenti non mappati in modo univoco; mai passati al paper broker.

L'ingestione include azioni, ETF, obbligazioni e strumenti quotati presenti nell'universo Trade Republic Italia, oltre a cripto supportate, riferimenti valutari e prodotti ETC/ETN con identificativi validi. Duplicati fra ticker, venue e classi dello stesso emittente vengono risolti tramite ISIN/FIGI/venue; non vengono fusi strumenti economicamente diversi.

La copertura è misurata e visibile, non dichiarata genericamente. Il Data Center mostra:

- numero di strumenti catalogati per asset class e mercato;
- percentuale con ISIN/FIGI/venue risolti;
- percentuale Qualified, Observable e Reference only;
- percentuale verificata Trade Republic e data dell'ultimo catalogo;
- strumenti scartati o ambigui con motivazione;
- copertura intraday, delayed ed EOD per provider.

Non viene fissato un numero statico di titoli: il catalogo è dinamico e versionato. L'obiettivo è importare tutto ciò che le fonti autorizzate rendono disponibile, mantenendo qualità e provenienza verificabili.

### 4.2 Market data layer

Ogni osservazione conserva almeno:

- provider;
- timestamp osservato dal provider;
- timestamp di ingestione;
- timezone e sessione di mercato;
- valuta;
- ritardo dichiarato o stimato;
- livello di qualità (`realtime`, `delayed`, `eod`, `reference`, `stale`);
- eventuale bid, ask, last, OHLC e volume;
- motivo del fallback.

Gerarchia iniziale gratuita:

| Esigenza | Fonte primaria | Fallback/nota |
|---|---|---|
| Catalogo Trade Republic Italia | PDF ufficiale versionato | verifica manuale/app per negoziabilità corrente |
| Mapping identificativi | OpenFIGI | disambiguazione per venue, valuta e tipo |
| EOD multi-asset | Stooq per uso personale | Alpha Vantage solo a basso volume |
| Intraday azioni USA | Finnhub free | entro copertura e limiti del piano |
| Cripto | CoinGecko Demo | attribuzione, cache e budget mensile |
| FX contabile EUR | BCE | riferimento giornaliero, non tick operativo |
| Tassi e macro | FRED/BCE | proxy, non prezzo di un bond specifico |
| News | Finnhub | Alpha Vantage come fallback limitato |

Yahoo Finance non è il backend automatico principale perché non offre una API pubblica supportata con SLA e autorizzazione generale alla raccolta automatizzata.

Le quote gratuite vengono assegnate in modo prioritario e lazy:

1. posizioni reali e demo;
2. ordini aperti e candidati delle strategie attive;
3. watchlist dell'utente;
4. strumenti visualizzati o richiesti;
5. aggiornamenti bulk/EOD del resto del catalogo.

Un budget manager per provider applica batching, cache, deduplicazione, backoff e quote giornaliere/mensili. L'ampiezza del catalogo non deve provocare refresh indiscriminati né bloccare i titoli già posseduti.

### 4.3 Portafogli e ledger

Ogni portafoglio ha:

- tipo immutabile: `REAL` oppure `PAPER`;
- valuta base EUR;
- cash ledger separato;
- posizioni, ordini, esecuzioni, commissioni e snapshot propri;
- configurazione di rischio e strategia versionata;
- benchmark;
- stato (`ACTIVE`, `PAUSED`, `ARCHIVED`).

Un portafoglio demo non può essere convertito in reale. Una futura configurazione reale richiederà una nuova entità broker, credenziali separate e una procedura esplicita.

Il portafoglio reale parte vuoto e viene popolato solo da inserimenti/importazioni esplicite o, in futuro, da una riconciliazione broker ufficiale. Il seed non deve contaminarlo.

### 4.4 Paper broker

Il paper broker implementa lo stesso contratto previsto per un adapter reale:

- submit, cancel e replace order;
- stato ordine e idempotency key;
- fill completo o parziale;
- posizioni e cash;
- riconciliazione;
- market, limit e stop order.

Il prezzo di esecuzione simulato usa la migliore informazione disponibile:

1. bid/ask osservati, quando disponibili;
2. last price più spread stimato documentato;
3. slippage configurato in base a liquidità e volatilità;
4. commissione Trade Republic simulata e costi di cambio applicabili.

Nessun fill viene creato con quotazioni stale o fuori sessione, salvo una regola esplicita per mercati realmente aperti 24/7.

### 4.5 Strategie automatiche

Il ciclo automatico è:

1. scheduler e calendario di mercato;
2. controllo qualità dati;
3. generazione segnali;
4. proposta ordine;
5. valutazione del risk engine;
6. esecuzione paper;
7. riconciliazione;
8. misurazione e audit.

Le strategie sono versionate e dichiarano orizzonte (`INTRADAY`, `SWING`, `LONG`), universo, frequenza, capitale assegnato, dipendenze dati e regole di uscita. Più strategie nello stesso portafoglio usano sleeve di capitale separate per mantenere attribuzione e limiti comprensibili.

L'intraday viene abilitato solo dove la qualità gratuita lo consente. Titoli europei senza quote intraday affidabili restano su strategie delayed/EOD; non vengono trattati come realtime.

### 4.6 Risk engine

Limiti iniziali approvati per i portafogli demo:

| Limite | Prudente | Bilanciato | Aggressivo |
|---|---:|---:|---:|
| Peso massimo singolo strumento | 10% | 15% | 20% |
| Peso massimo crypto | 5% | 10% | 20% |
| Stop perdita giornaliera | 1% | 2% | 3% |
| Ordini massimi al giorno | 4 | 8 | 12 |
| Liquidità target minima | 30% | 15% | 5% |

I profili sono preset di simulazione, non raccomandazioni finanziarie. Ogni modifica produce una nuova versione; ogni ordine conserva la versione usata.

Guardrail comuni:

- posizione e valore ordine massimi;
- limite per asset class, valuta e strategia;
- stop-loss/take-profit configurabili;
- perdita massima giornaliera e drawdown massimo;
- cooldown dopo anomalie o perdite consecutive;
- limite ordini/frequenza;
- kill switch globale e per portafoglio;
- blocco in presenza di dati stale, provider divergenti o FX mancante.

### 4.7 Broker adapter futuro

Il contratto broker è definito ora, ma `TradeRepublicBroker` resta `UNAVAILABLE` e fail-closed. Non vengono usati scraping, automazione dell'interfaccia, PIN, sessioni private o API non supportate.

Lo shadow mode produce e misura gli ordini che sarebbero stati proposti senza trasmetterli. Un adapter reale sarà valutato solo se esisteranno:

- integrazione ufficiale/supportata;
- autorizzazioni e requisiti legali applicabili;
- autenticazione e custodia credenziali adeguate;
- consenso e attivazione separati;
- test di idempotenza, riconciliazione e failure recovery.

## 5. Calcoli di performance

Per una posizione con quantità firmata:

```text
P/L non realizzato oggi = quantità_firmata × (mark_price − previous_close)
P/L oggi = realizzato_oggi + non_realizzato_oggi − fee_oggi − slippage_oggi
valore_EUR = valore_nativo × FX(nativo→EUR, timestamp documentato)
```

Il report separa:

- realizzato oggi;
- non realizzato oggi;
- commissioni, spread/slippage e cambio;
- P/L totale dalla creazione;
- contributo per strumento, strategia e asset class;
- benchmark e differenziale;
- qualità/freschezza del mark price.

Il valore visualizzato è una stima di mercato per un portafoglio virtuale, non un prezzo di esecuzione garantito.

## 6. Runtime locale e continuità

La prima versione usa un processo locale avviato automaticamente con Windows, senza finestra tecnica visibile. Il runtime espone health e stato di ciclo.

Se il PC è spento o sospeso:

- non vengono simulati ordini come se il motore fosse rimasto online;
- al ritorno vengono recuperati i dati mancanti compatibili con i provider;
- ordini, cash e posizioni vengono riconciliati;
- il gap operativo viene mostrato nell'interfaccia e nei report.

Motore, scheduler e client comunicano tramite contratti versionati, così il runtime potrà essere trasferito in futuro su NAS, mini-PC o cloud senza riscrivere strategie e risk engine.

## 7. Architettura informativa e UX

La navigazione globale passa da 15 destinazioni concorrenti a cinque hub:

1. **Oggi** — P/L intraday, priorità, decisioni automatiche, anomalie e guardrail;
2. **Portafogli** — reale e demo, posizioni, ordini, rischio, scenari, fiscalità, import/export;
3. **Mercati** — ricerca, watchlist/universe, ISIN, scheda asset e news;
4. **Laboratorio** — strategie, backtest, robustezza, ML e shadow mode;
5. **Dati e backup** — provider, cache, limiti, freschezza, chiavi e copie di sicurezza.

Le vecchie URL vengono mantenute tramite redirect finché necessario.

### 7.1 Ricerca e discovery dell'universo

Mercati offre una ricerca globale per nome, ticker, ISIN e FIGI, con filtri combinabili per:

- asset class e sottotipo;
- Paese, mercato, venue e valuta;
- stato Trade Republic e data di verifica;
- qualità/freschezza disponibile;
- capitalizzazione, liquidità, volatilità e volume quando forniti;
- rendimento, rischio, score e compatibilità con il profilo demo;
- distribuente/accumulazione e TER per ETF quando disponibili.

I risultati separano chiaramente “disponibile nel catalogo”, “dati sufficienti” e “idoneo all'automazione”. Watchlist e screener salvati permettono di restringere migliaia di strumenti senza trasformare la home in un elenco ingestibile.

### 7.2 Home Oggi

Ordine dei contenuti:

1. selettore portafoglio e stato dati;
2. valore, P/L oggi, cash e profilo rischio;
3. grafico intraday;
4. decisioni automatiche e ordini aperti;
5. priorità/anomalie;
6. guardrail e kill switch;
7. massimo tre news rilevanti per le posizioni.

### 7.3 Scheda strumento e grafici

Ogni scheda mostra:

- nome, ticker, ISIN, venue, valuta e stato Trade Republic;
- ultimo prezzo, variazione e stato mercato;
- periodi 1G, 1S, 1M, 3M, 1A, 5A, MAX;
- modalità prezzo, rendimento, candele e confronto benchmark;
- zoom, crosshair e tooltip;
- fonte, timestamp, ritardo e valuta sempre visibili;
- dati essenziali prima degli indicatori avanzati;
- riepilogo testuale accessibile del grafico.

## 8. Design system Calm Intelligence

Principi:

- sfondo navy/obsidian, superfici stratificate e contrasto elevato;
- cyan per informazione/serie principali, verde per positivo, corallo per negativo, violetto per automazione/AI;
- il colore non è mai l'unico portatore di significato;
- trasparenze/glass riservate a navigazione e controlli, non alle superfici dati;
- tipografia con gerarchia netta e numeri tabulari;
- animazioni brevi e informative, con `prefers-reduced-motion`;
- modalità chiara complementare;
- target touch minimi 44×44 px e WCAG 2.2 AA;
- sidebar desktop, bottom navigation mobile, rail/tablet adattivo.

## 9. Predisposizione iOS e Android

La fase attuale non pubblica ancora app native. Prepara:

- API versionata e autenticata;
- SDK TypeScript generato dai contratti;
- design token condivisi;
- separazione completa fra motore e rendering;
- pairing sicuro del dispositivo con il runtime;
- privacy inventory e minimizzazione dei dati;
- layout compact/medium/expanded.

Il client futuro consigliato è React Native/Expo per iOS e Android, con componenti di navigazione e accessibilità adattati alla piattaforma. Non sarà un semplice wrapper della pagina web.

La versione store iniziale rimane paper/analisi. Apple richiede privacy label e pone requisiti specifici alle app di trading/investimento reale; Google Play richiede Data Safety e Financial Features Declaration. Qualsiasi trading reale richiederà una nuova verifica tecnica, legale e di store policy.

## 10. Error handling e sicurezza

Principio generale: fail-closed per ordini e fail-soft per consultazione.

- Dato stale o mancante: nessun ordine; UI continua a mostrare l'ultimo valore marcato come obsoleto.
- Provider limitato: cache/fallback ammesso solo se compatibile con la strategia.
- Divergenza provider: simbolo sospeso e incidente registrato.
- Migrazione fallita: avvio interrotto e database ripristinabile dal backup pre-migrazione.
- Ordine duplicato: idempotency key impedisce un secondo fill.
- Recovery: riconciliazione prima di riprendere nuove decisioni.
- Segreti: file locali esclusi da git, URL e log; errori sanitizzati.
- API locale: bind loopback per default, operazioni amministrative protette.
- Azioni distruttive: diff, conferma esplicita, backup e possibilità di recupero.

## 11. Strategia di verifica

### Test unitari finanziari

- conversioni FX e arrotondamenti;
- P/L long/short, realizzato e giornaliero;
- fee, spread, slippage e partial fill;
- sizing e tutti i limiti rischio;
- lotti, tax events e scadenze;
- scenari e snapshot.

### Test provider e contratti

- fixture registrate senza chiamate reali in CI;
- rate limit, timeout, retry e fallback;
- mapping ISIN/ticker/venue ambiguo;
- import catalogo su larga scala, deduplicazione e versionamento;
- promozione/declassamento fra Qualified, Observable e Reference only;
- prioritizzazione quote per posizioni, ordini, strategie e watchlist;
- quote delayed/EOD incompatibili con intraday;
- contratti API e migrazioni compatibili.

### Test integrazione e operatività

- scheduler e calendari;
- stop/ripartenza e gap del PC;
- idempotenza e riconciliazione;
- backup/restore reale;
- launcher Windows one-click;
- soak test del paper broker.

### Test interfaccia

- component test e route test;
- E2E dei flussi critici;
- responsive desktop/mobile/tablet;
- accessibilità automatica e manuale;
- stati loading, vuoto, stale, errore e dati corrotti;
- regression screenshot delle schermate principali.

## 12. Fasi di consegna

Il programma è troppo ampio per un'unica modifica. Il lavoro procede in sei fasi autonome, ciascuna con piano e gate propri:

1. **Fondamenta affidabili** — correzioni audit, sicurezza, migrazioni e test;
2. **Strumenti e dati reali** — catalogo più ampio possibile, instrument master, fonti gratuite, FX, quality tier e budget provider;
3. **Portafogli multipli** — reale vuoto, demo, ledger, paper orders e P/L;
4. **Automazione locale** — scheduler, strategie, risk engine, recovery e shadow mode;
5. **Calm Intelligence** — cinque hub, grafici, responsive e accessibilità;
6. **Mobile/store readiness** — API auth, pairing, SDK, token e contratti mobile.

Trade Republic reale e client store pubblicati sono evoluzioni separate successive, non parte implicita delle sei fasi.

## 13. Definition of Done per fase

Una fase è completa solo quando:

- test mirati e suite completa sono verdi;
- il diff è stato revisionato per regressioni e scope creep;
- non restano problemi critici/alti noti nell'area modificata;
- backup e rollback pertinenti sono stati provati;
- dati validi, mancanti, stale e corrotti sono gestiti;
- copertura catalogo e quota di strumenti Qualified/Observable sono misurate e visibili;
- segreti e dati personali non compaiono nei log;
- documentazione e avvio locale sono aggiornati;
- il risultato è verificabile dall'interfaccia o da un test riproducibile.

## 14. Fonti esterne di riferimento

- Trade Republic, universo strumenti Italia: <https://assets.traderepublic.com/assets/files/IT/Instrument_Universe_IT_en.pdf>
- OpenFIGI API: <https://www.openfigi.com/api/documentation>
- BCE Data API: <https://data.ecb.europa.eu/help/api/data>
- Alpha Vantage: <https://www.alphavantage.co/documentation/>
- Finnhub: <https://finnhub.io/docs/api>
- CoinGecko API: <https://www.coingecko.com/en/api/pricing>
- FRED API: <https://fred.stlouisfed.org/docs/api/fred/fred/>
- Apple Human Interface Guidelines: <https://developer.apple.com/design/human-interface-guidelines>
- Apple App Review Guidelines: <https://developer.apple.com/app-store/review/guidelines/>
- Material Design 3: <https://m3.material.io/>
- Android adaptive navigation: <https://developer.android.com/design/ui/mobile/guides/layout-and-content/layout-and-nav-patterns>
- Google Play Financial Features Declaration: <https://support.google.com/googleplay/android-developer/answer/13849271>
- WCAG 2.2: <https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/>

## 15. Fuori ambito senza nuova approvazione

- invio di ordini reali;
- conservazione delle credenziali Trade Republic;
- scraping o automazione dell'app/web Trade Republic;
- leva, derivati complessi o opzioni binarie;
- pubblicazione immediata su App Store o Google Play;
- server cloud a pagamento;
- promessa o ottimizzazione orientata a un rendimento garantito.
