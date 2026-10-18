# InvestEdge — proposta SP3s: ricerca swing USA, holding 1/5/21 sedute

**Stato: PROPOSTA NON APPROVATA, revisione documentale 2026-10-18 (prima proposta 2026-10-15; review 2026-10-16). Nessuna autorizzazione al codice è implicita nelle risposte al brainstorming.** I numeri progettuali sotto sono proposti ex ante: non sono risultati di backtest o soglie prescritte dalle fonti. Nessuna famiglia è dichiarata redditizia.

Base documentale: `3f37a44b76ba8f8c8182281dbe6301a9898bc11a`, checkpoint SP3 Task5 pubblicato; origin/main resta `6c32bfa4559336d9903af0d30c03e7145586cd52`. Branch della proposta: `investedge/sp3s-task-0`. Il codice intraday già integrato resta intatto; SP3/SP6a sono sospesi, non cancellati.

Riferimenti: [programma](../../../PROGRAMMA-OPERATIVO.md), [inventario verificato SP1](../../reports/2026-10-15-swing-sp1-inventory.md), [spec generale](2026-09-30-investedge-profit-engine-program-design.md), [SP1](2026-10-02-investedge-sp1-truth-lab-design.md), [piano SP3s](../plans/2026-10-15-investedge-sp3s-swing-research.md).

## 1. Decisioni dell’utente e risultato richiesto

| Area | Decisione esplicita acquisita |
|---|---|
| Mercato | Sole azioni liquide USA. Universo storico as-of, incluse quelle poi delistate; liquidità fissata ex ante. Lista corrente TR solo per operatività futura. Europa/ETF come eventuali studi separati |
| Capitale | 10.000 EUR di riferimento; nessun movimento di denaro |
| Esecuzione | TR manuale dell’utente; Best Price e Direct Price confrontati separatamente |
| Finestra | Sempre da 45 a 10 minuti prima della chiusura USA, inclusi DST e chiusure anticipate. Normalmente 21:15–21:50 Europe/Rome, 20:15–20:50 nelle settimane disallineate |
| Segnale e fill | Dati disponibili poco prima, anche ritardati 15 minuti; prezzo nella finestra, spread/slippage conservativi, mai fill alla chiusura ufficiale |
| Holding | 1, 5 o 21 sedute dal fill effettivo |
| Rischio posizione | Massimo iniziale 1% del capitale, 100 EUR iniziali; i gap possono superarlo |
| Portafoglio | Massimo 10 posizioni, senza leva; rischio iniziale aggregato fino a 1.000 EUR |
| Drawdown | Soglia di accettazione OOS: 2.000 EUR, 20% del capitale di riferimento; non garanzia di perdita massima |
| SEVERE | Scelta c confermata il 2026-10-18: resta gate necessario; costo FX da ricalibrare su fonte documentata e proporre prima di applicarlo. Ricalibrazione numerica condizionata §7.2 approvata e applicata ai documenti il 2026-10-18 |
| Stop | Inseriti manualmente su TR e lasciati attivi, previa verifica del supporto per titolo e modalità Best/Direct |
| Vincoli | Nessuna credenziale, raccolta live, ordine, paper, spesa, scraping/automazione TR o accesso al DB reale. Solo documenti nel Task0; nuovi merge FF main soltanto con conferma esplicita |

Risultato: un laboratorio offline riproducibile, con piccoli insiemi di regole congelati, prezzi e identità verificabili, registro completo e possibilità esplicita di concludere INSUFFICIENTE o NON_VALIDATO. Le scelte restanti di questo documento sono proposte progettuali, da approvare insieme alla spec. Non vengono attribuite all’utente.

## 2. Approccio scelto e alternative esaminate

Estendere direttamente SP1 richiederebbe cambiare il suo significato di fill next-open, universo corrente e holding. Riutilizzare integralmente SP3 imporrebbe contratti e campione live intraday ormai sospesi. Si propone un pacchetto autonomo `backend/app/swing_research/`, con funzioni pure SP1 riusate soltanto quando unità e causalità coincidono. SP1, SP2b e SP3 mantengono comportamento, namespace, schema, API e test esistenti.

Livelli di evidenza distinti:

- **G_SWING_TECH:** software offline, fixture sintetiche, causalità, contabilità, conservazione e limiti verificati. Non dimostra rendimento.
- **G_SWING_DATA / G_SWING_RESEARCH:** dati storici idonei e risultati economici sotto il modello USA esplicitamente dichiarato. Una proxy SIP USA/FX può produrre soltanto `PASS_RICERCA_PROXY`, mai `VALIDATO_TR`.
- **G_TR_TRANSFER:** prezzi/valuta/venue, orari di negoziazione e stop effettivamente applicabili a TR attestati, con dati sufficienti. Se mancano, stato INSUFFICIENTE anche quando la ricerca proxy passa. Non autorizza trading o automazione.

Notizie, fondamentali, earnings filter, short, leva, ETF, Europa, ML, Telegram, frontend e adapter ordini sono fuori da SP3s v1. Un filtro su utili non entra senza calendario annunciato point-in-time e nuova preregistrazione.

## 3. Contratto dei dati e qualità

### 3.1 Pacchetto locale immutabile

Input esplicito in una directory dedicata, mai connessione al DB applicativo. Manifesto canonico con versione, fonte/feed, diritti, valuta, calendario, intervallo, hash/count dei file, grain, rettifiche, disponibilità e lacune. File UTF-8 JSON/NDJSON partizionati e ordinati per seduta/identità/timestamp; quantità e denaro serializzati come decimali, non float non finiti. Distinguere REAL, SYNTHETIC e RESEARCH_ONLY. Nessuna promozione mediante sola etichetta REAL.

Separare identità emittente/classe/listing, ticker con intervallo di validità, venue e valuta. Vietato collegare ticker riutilizzati senza identità stabile. Calendario USA e conversioni UTC/Europe/Rome versionati, comprese sedute ridotte e sospensioni. Il calendario è metadato: non espone gli esiti del holdout.

Ogni dato dichiara `event_time`, disponibilità provata o modellata, data di acquisizione e versione. Uno storico scaricato oggi non è una cattura STRICT_PIT né un archivio di revisioni noto allora. La disponibilità modellata resta una limitazione del verdetto proxy. Record tardivi o revisioni con disponibilità successiva non cambiano decisioni salvate. L’impronta include calendario, universo, prezzi, corporate action, FX, profilo costi e benchmark.

Reader streaming, massimo 10.000 righe o 8 MiB decodificati per batch, limite più restrittivo; working set massimo 2 GiB. Se il cap non basta, RESOURCE_LIMIT senza tagliare titoli o evidenze. Nessuna retention distruttiva. Input in sola lettura, output atomico in directory distinta; rifiutare path traversal, link fuori radice, sovrascritture e qualsiasi riferimento a `data/investedge.db`. Nessun caricamento implicito di dotenv o client di rete.

### 3.2 Universo as-of proposto

Al primo giorno di ogni mese, prima del segnale, determinare eleggibilità sul precedente close disponibile. Common stock di emittenti USA, listing primario NYSE/Nasdaq/NYSE American, USD; escludere ETF/fondi, ADR, preferred, warrant, unit e veicoli a leva mediante classificazione storica verificabile. Il criterio “emittenti USA” richiede inoltre domicilio storico dell’emittente con intervallo di validità e fonte, distinto da valuta, borsa di listing o luogo d’incorporazione non equivalente. Non si amplia silenziosamente a qualsiasi emittente con listing USA. Domicilio o classificazione mancanti sono lacune di G_SWING_FEAS/G_SWING_DATA, non titoli arbitrariamente scartabili.

Regole congelate: prezzo raw dell’ultima seduta almeno 5 USD; almeno 252 sedute precedenti valide dopo quotazione; ADV20 in USD almeno 20 milioni, calcolato come media dei 20 controvalori `raw_close × raw_volume` precedenti, senza volume del giorno del segnale. Fra gli eleggibili, primi 500 per ADV20, tie su identità stabile. Nessuna lista odierna TR/S&P500/Alpaca sostituisce l’anagrafica storica. La soglia di 252 sedute esclude IPO recenti per una regola stabilita prima dei test, non perché poi fallite.

Conservare l’elenco completo di candidati, inclusioni/esclusioni e ragioni di ogni mese. Requisiti di liquidità regolano nuove entrate; una posizione non viene liquidata perché il mese successivo esce dai primi 500. Delisting, fallimento, merger e halt non cancellano posizioni o perdite. Servono prezzi eseguibili, corrispettivi e recuperi documentati anche oltre la quotazione principale. Nessun valore terminale inventato a zero, ultima chiusura o −100%; un recupero non osservato rende l’evidenza insufficiente. La sola uscita dal listino non è un fill.

G_SWING_DATA richiede: catena di identità e membership completa, corporate action rilevanti e risoluzione di tutte le posizioni osservabili; zero buchi non spiegati nelle finestre usate per decisione, esecuzione o valutazione di posizioni. Distinguere assenza documentata di scambi da dati mancanti. Ogni mese almeno 100 titoli eleggibili e almeno il 99% delle barre daily attese dell’universo selezionato; il residuo non può essere imputato, eliminato dai denominatori o ignorato se incide su una decisione/posizione. Una cella necessaria non osservata blocca il relativo gate, non diventa un no-trade favorevole.

### 3.3 Rettifiche, dividendi, fonti

Raw per prezzi eseguibili e filtri nominali; serie per feature rettificate soltanto per split effettivi e disponibili entro il cutoff. Stessa base per storia e prezzo di confronto. Nessuna rettifica futura altera filtri nominali, quantità o ranking passati. Dividendi: diritto alla ex-date, credito alla pay-date, ritenute/costi solo se attestati; non contare sia dividendo cash sia total return rettificato. Split trasformano quantità e stop senza profitto; merger e cambio ticker preservano identità/posizioni e tracciano cash/azioni ricevuti.

Stooq `UNKNOWN` rimane UNKNOWN: il fattore 1 e la guardia split di SP1 non attestano total return o corporate action complete. Non usarlo per promuovere risultati economici se quei requisiti non sono dimostrati.

Alpaca Basic è fonte candidata: la documentazione permette storico SIP con `end` almeno 15 minuti arretrato e barre `1Day`; Basic realtime è IEX. Le barre supportano rettifiche e `asof` per rename, non vintage o universo storico. La FAQ limita OTC a un abbonamento speciale per broker partner: uscita di titoli delistati e copertura gratuita completa restano da dimostrare. Nessuna API viene interrogata da questo piano. [Piani Alpaca](https://docs.alpaca.markets/us/docs/about-market-data-api), [FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), [barre](https://docs.alpaca.markets/us/reference/stockbars), [corporate action](https://docs.alpaca.markets/us/reference/corporateactions-1).

FX EUR: serie storica identificata e disponibile entro il cutoff; nessun fixing pubblicato dopo il segnale usato retroattivamente per size o cassa. La proxy USA usa ultimo FX verificabile precedente, massimo 7 giorni, e dichiara rischio di conversione e differenza rispetto al prezzo TR. Per G_TR_TRANSFER servono valuta e conversione realmente applicabili, anche agli stop e ai costi.

### 3.4 Fattibilità dati prima delle strategie — proposta G_SWING_FEAS

Prima dei nuovi Task4–9 (già Task3–8) serve il Task3 documentale G_SWING_FEAS, dopo i soli contratti/reader dei Task1–2. Il gate non è soddisfatto dalla disponibilità teorica di un endpoint o da fixture sintetiche. **Stato alla revisione: INSUFFICIENTE**, nessun pacchetto completo fornito/verificato. Nessun proseguimento alle strategie finché non passa; nessun agente configura chiavi, interroga API dati o scarica dataset. G_SWING_DATA finale resta separato dalla fattibilità iniziale.

| Dato minimo | Campi/prova necessari prima del PASS di fattibilità | Fonte candidata e limite documentale |
|---|---|---|
| Calendario e regolamento | Tutte le sedute 2016–2026-09-30, open/close UTC/NY, half-day, chiusure straordinarie, giorni settlement, versione/hash | Calendari ufficiali NYSE; calendario applicabile al listing e regolamento non inferiti da lunedì–venerdì |
| Universo e identità | ID emittente/classe/listing, ticker valid_from/to, IPO/delisting, venue/valuta primaria, membership as-of anche dei poi delistati | Catalogo corrente Alpaca non prova universo storico completo; nessuna fonte gratuita completa già dimostrata |
| Classificazione/domicilio | Common stock vs ADR/preferred/fondo/unit/leva, domicilio USA storico con fonte/date, inclusi titoli inattivi | Filing storici SEC possono supportare singoli attributi, non sono automaticamente un catalogo di tutte le azioni/delistati; incorporazione non sostituisce domicilio |
| Daily raw e liquidità | OHLCV/valuta/feed, warm-up252, ADV20 e filtro nominale, chiavi/grain univoci, rettifiche/versioni/lacune | Alpaca storico candidato; Stooq UNKNOWN non attesta rettifiche o corporate action |
| Minuti e stop | Prezzo entro5m dal cutoff C−55, copertura C−55…C−10 e tutte le ore RTH delle posizioni potenziali, volume SIP, halt/reopen e missingness distinguibili | Basic permette storico SIP arretrato, realtime IEX è parziale; prezzi/minuti e diritti completi del pacchetto non verificati |
| Corporate action/uscite | Split/rename/spin-off/merger, ex/pay-date e cash/azioni, recuperi/prezzi terminali, tempi di disponibilità | Corporate action Alpaca con ritardi dichiarati; OTC è riservato a speciale abbonamento broker partner, quindi non presumere recuperi gratuiti completi |
| FX e benchmark | EUR/USD con unità e disponibilità, benchmark as-of total return e prezzi/azioni terminali, metodo di esposizione laggata §9.2 | BCE è un fixing informativo, non prezzo eseguibile TR; benchmark non costruito da sopravvissuti |
| Costi e trasferibilità TR | Best/Direct separati, valuta quotazione/regolamento, fee/dividendi/FX, supporto/orari stop, diritti e costi ricorrenti | Materiali pubblici e documenti ex-ante forniti dall’utente; non inferire copertura dal solo listino |
| Conservazione/holdout | Pacchetto locale immutabile, hash/count per partizione, quote disco/RAM, prova strutturale del holdout opaco senza ritorni visibili | Dati fuori Git; attestazione di copertura del custode separata da esiti/feature; nessuna apertura esplorativa holdout |

PASS soltanto con evidenza per ogni campo e per l’intero campione richiesto, inventario inclusioni/esclusioni e tutte le quantità/costi/diritti tracciabili. Sulla parte non holdout, verifica locale dei contenuti necessaria oltre ai metadati; sul holdout, proof di copertura/diritti/identità del custode indipendente e hash opachi, senza esiti nella ricerca. G_SWING_DATA finale rivalida poi i dati nel protocollo autorizzato: la fattibilità non garantisce assenza di ogni errore nascosto. Campi ignoti, delistati/uscite non coperti, solo lista corrente, prova gratuita incompleta o budget disco assente -> INSUFFICIENTE, non esclusione dei casi difficili. Eventuale NON_IDONEO per provenienza/diritti incompatibili. Le soglie di copertura §3.2 restano necessarie.

Cosa occorre dall’utente: un pacchetto storico locale con prove/licenza e custodia del holdout; per produrlo tramite Alpaca, eventuale chiave configurata soltanto dall’utente fuori dalla chat/processi degli agenti. Non consegnare credenziali agli agenti. Se la sola fonte idonea fosse a pagamento, serve una decisione separata dell’utente: nessuna spesa o attivazione automatica. Senza pacchetto idoneo non implementare otto task sperando di risolvere i dati alla fine. Fonti documentali: [Alpaca piani](https://docs.alpaca.markets/us/docs/about-market-data-api), [FAQ su accesso/SIP/OTC](https://docs.alpaca.markets/us/docs/market-data-faq), [SEC EDGAR](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [BCE](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).

## 4. Segnale, coda manuale e prezzi

Sia C la chiusura della seduta USA nel calendario congelato. Una decisione per seduta a **C−40 minuti**. Dati di mercato per il segnale soltanto se evento completo entro **C−55 minuti** e disponibilità entro C−40: il ritardo modellato è 15 minuti. Il segnale usa feature daily fino alla precedente seduta chiusa e il più recente prezzo SIP del giorno entro quel cutoff, non il close/high/low/volume definitivi della seduta aperta. Prezzo assente o più vecchio di 5 minuti rispetto al cutoff informativo: dato insufficiente, nessuna sostituzione con l’open o il close.

Prima i sell manuali dovuti, ordinati per seduta di scadenza e identità; poi i nuovi buy per ranking. Base: primo slot a C−35; uno slot di un minuto per vendita, due consecutivi per acquisto e conferma dello stop. Gli slot terminano entro C−10. Un buy richiede spazio per entrambe le attività; ciò può impedire il ricambio completo di dieci posizioni. Segnali e ranking restano quelli di C−40, senza scegliere ex post minuto o titolo migliore.

Ogni slot inizia su un confine di minuto t. L’ordine, già determinato all’arrivo t, usa soltanto per il fill la barra completa [t,t+1 minuto), con fill contabilizzato a t+1; per un buy lo stop è confermato a t+2, dopo il secondo slot. Entrambi devono terminare entro C−10. Nessun fill sul record che ha generato il segnale. Proxy conservativa: buy al massimo della barra più costo per lato, sell al minimo meno costo per lato; quote idonee più sfavorevoli prevalgono. Valori di barra usati solo per eseguire un ordine già determinato, mai per selezionarlo. Capacità massima 0,1% del volume consolidato della barra: quantità intere, eventuale fill parziale e resto cancellato al termine dello slot, senza assumere profondità/coda TR. Volume nullo e halt documentati producono mancato fill; una barra necessaria mancante è lacuna.

Un nuovo buy è cancellato se il prezzo eseguibile supera il prezzo informativo di 0,5 ATR14, se size/cassa/stop diventano invalidi o manca la prova richiesta; ragione e opportunity loss salvate. Vendite dovute non si cancellano per preservare un rendimento favorevole: restano pendenti e vengono ritentate nel primo slot idoneo della successiva finestra, con stop già attivo dove attestato. Nessuna liquidazione inventata al close. Coda completa, latenze e operazioni rimandate sono nel report. Calendario ufficiale di riferimento: [NYSE](https://www.nyse.com/trade/hours-calendars).

## 5. Famiglie candidate e griglia congelata

Si propongono **tre famiglie tecniche, un solo set di parametri per famiglia, tre holding**. Nessuna ricerca libera di soglie dopo aver visto OOS. Definire x come ultima seduta completa precedente, P come prezzo informativo disponibile, A come ATR14 su quella base; ROC63 = close(x)/close(x−63)−1. Warm-up di 252 sedute valide, SMA semplici e ATR secondo formula SP1 attestata; niente somma dello score-v1 o normalizzazione sull’intero campione.

Filtro comune: titoli eleggibili §3, `close(x) > SMA200(x)`, A finito/positivo e `close(x) <= P <= close(x) + 0,5A`. Nessun filtro news o accesso al futuro.

| ID | Ingresso proposto, oltre al filtro comune |
|---|---|
| MOM | ROC63(x) > 0; SMA50(x) > SMA200(x) |
| PULLBACK | SMA50(x) > SMA200(x); minimo dei low delle ultime 5 sedute <= SMA20(x); 0 <= close(x)−SMA20(x) <= A |
| BREAKOUT | close(x) > massimo degli high delle 20 sedute precedenti x, esclusa x; volume(x) >= 1,5 volte la media dei volumi di quelle 20 sedute, con base split coerente |

Ranking per tutte: ROC63(x) / [A / close(x)], decrescente, tie su identità stabile. Una posizione per emittente/classe, niente pyramiding; dopo uscita niente reingresso nella stessa seduta. Ciascuna policy gestisce il proprio portafoglio, non mescola famiglie scelte a posteriori.

H in {1,5,21}: una posizione con primo fill nella seduta d ha uscita temporale dovuta nella finestra della seduta d+H, contando le sedute del calendario, non giorni civili o numero di barre presenti. Fill parziali successivi non rinnovano H. Uscita anticipata per stop o invalidazione `close(x) < SMA200(x)`, quest’ultima soltanto nella finestra manuale. Nessun take-profit, trailing stop o mediazione in perdita in v1. Ordini non eseguibili possono durare oltre H: l’eccesso è registrato e non nascosto.

**18 configurazioni candidate** = 3 famiglie × 3 holding × 2 modalità TR. Due selettori WFO, uno per modalità, portano a **20 percorsi registrati**. BASE/STRESS/SEVERE sono controlli obbligatori degli stessi percorsi, non nuove configurazioni tra cui scegliere. Nessuna ablation extra in v1.

## 6. Size, stop, gap e contabilità

Proposte di implementazione del rischio, ulteriori rispetto alle decisioni esplicite: cap nozionale per emittente 10% dell’equity corrente; quote intere, minimo buy 100 EUR; nessun minimo impedisce la chiusura completa. Rischio iniziale per posizione <= min(100 EUR, 1% equity), aggregato di posizioni e buy pendenti <= min(1.000 EUR, 10% equity). Massimo dieci emittenti; acquisti coperti da cassa comprensiva di commissioni e riserva per uscita. Nessun saldo negativo, short, prestito o liquidità futura da dividendi/vendite non regolati. Cassa soggetta a settlement attestato, senza assumere riutilizzo immediato. Nella proxy USA si propone T+1 su calendario di regolamento USA per l’intero campione, come ipotesi controfattuale del regime 2026 insieme ai costi; non si attribuisce T+1 alle transazioni storiche prima del 2024. G_TR_TRANSFER richiede invece il regime applicabile a ciascuna modalità/valuta. [SEC: T+1 dal 28 maggio 2024](https://www.sec.gov/newsroom/press-releases/2024-62).

Stop iniziale fisso a `prezzo del primo fill − 2A` nella valuta del listing. Quantità limitata sia dal nozionale sia dal rischio fino allo stop, includendo costi previsti di entrata/uscita; A <= 0 o stop <= 0 impediscono l’ingresso. Il limite è un massimo, non obbligo di utilizzare 100 EUR di rischio. Prezzo effettivo e fill parziale possono solo ridurre la quantità autorizzata. Dividend/split e valuta del contratto stop devono essere espliciti; nessuna trasformazione dello stop USD in uno stop EUR mobile tramite fixing futuro.

Lo stop diventa attivo dopo lo slot di conferma manuale. Se la conferma fallisce dopo un fill, registrare posizione non protetta e richiesta di uscita d’emergenza nel primo slot manuale consentito; nessuna attivazione o esecuzione retroattiva e nessuna apertura successiva mentre quella condizione resta irrisolta. L’intervallo precedente resta esposto e simulato: una rottura durante quell’intervallo genera uscita d’emergenza nel primo slot utile, non un fill retroattivo. Per G_TR_TRANSFER occorre prova per titolo/modalità di ordine supportato, trigger, venue, valuta, validità e orari; nessuna supposizione che tutti i titoli abbiano identico stop-market. Supporto sconosciuto: non idoneo all’operatività TR, senza riscrivere l’universo storico USA.

Nella proxy USA lo stop lavora nelle ore RTH documentate. Gap sotto stop: prima barra successiva effettivamente negoziabile, prezzo non migliore di min(open, stop, low della barra), meno costi; trigger dentro barra: ipotesi prudente non migliore di min(stop, low). Non inferire un trigger da un minimo avvenuto prima dell’ingresso. Halt, reopen e delisting seguono eventi/prezzi osservati; la mancanza non crea fill. Le ore TR fuori RTH richiedono dati propri per G_TR_TRANSFER. Perdita oltre rischio teorico, insolvenza e ritardo d’uscita rimangono nel ledger; nessun cap artificiale a −100 EUR/posizione o −2.000 EUR/portafoglio.

Ledger append-only per valuta con quantità, cash flow, fee, slippage, FX e corporate action; Decimal per denaro e arrotondamento conservativo per lato a centesimi EUR. Rendimenti su equity comprensiva del capitale iniziale e giorni flat. Valutazione dopo gli eventi: daily e controllo avverso a granularità minuto per posizioni aperte, con FX/base dichiarati. Close ufficiale ammesso per mark-to-market dopo la seduta, mai come prezzo di ordine nella finestra.

Drawdown di accettazione = massimo del precedente picco equity, capitale iniziale compreso, meno equity successiva, in EUR: **<= 2.000 EUR** su OOS e holdout, per tutti gli scenari costi. La percentuale dal picco corrente è riportata separatamente; non viene confusa con il 20% del capitale iniziale. Anche la serie di mark avversi deve rispettare la soglia, se osservabile; dati insufficienti impediscono PASS. Non è un interruttore che cancella perdite eccedenti.

## 7. Costi e scenari obbligatori

Listino pubblico consultato: Best Price 1 EUR/eseguito, Direct Price 2 EUR/eseguito, più spread/costi terzi. Applicabilità a conto italiano, date, modalità e stop va attestata nel profilo costi; nessun trasferimento automatico da Alpaca. [Listino TR](https://traderepublic.com/it-it?openModal=pricing-scheme). Le cifre sotto sono ipotesi conservative di ricerca da approvare, non misure TR.

| Scenario | Fee per eseguito Best / Direct | Spread+slippage proxy per lato | Prima attività dopo decisione |
|---|---|---|---|
| BASE | 1 / 2 EUR | almeno 10 bps | 5 minuti |
| STRESS | 2 / 4 EUR | almeno 25 bps | 10 minuti |
| SEVERE | 2 / 4 EUR | almeno 50 bps; extra FX 0 bps solo per ordini/regolamento interamente EUR senza conversione di cassa; altre conversioni documentate §7.2 o INSUFFICIENTE | 15 minuti |

Valori osservati/provati peggiori prevalgono sui minimi. Ogni scenario ricalcola cassa, size, coda, fill, stop e rendimenti: non sottrae soltanto una percentuale alla curva BASE. Lo slot finale resta C−10; maggior ritardo può impedire entrate o rinviare uscite. Fee su ciascun eseguito effettivo, compresi stop e frazionamenti secondo tariffa attestata. Nessun costo dati/strumento/servizio necessario ignorato: profilo gratuito deve provarne l’assenza; costo ricorrente noto detratto per seduta, ignoto -> insufficiente.

Il confronto storico applica il profilo economico 2026 ipotizzato all’intero campione, etichettandolo come simulazione controfattuale di costi correnti; non afferma che quelle tariffe esistessero in tutte le date. Settlement, dividendi e conversioni non duplicati. Rendimenti economici netti di costi operativi ma prima della fiscalità personale italiana; fiscalità/bollo stimati in un pannello separato con ipotesi esplicite, senza attribuire accuratezza fiscale al modello semplificato SP1. Alpaca è solo fonte candidata/confronto documentale, non broker da attivare.

### 7.1 Impatto dei costi aggiornato e decisione aperta H=1

Analisi aritmetica, non backtest: nozionale costante 1.000 EUR (10% dei 10.000 iniziali, non nozionale medio misurato), due soli eseguiti, nessun profitto lordo ipotizzato. Costo RT in bps = 2×costo variabile per lato + 10.000×2×fee/nozionale. Drag annuo lineare sul nozionale riutilizzato = costoRT×252/H; non CAGR o previsione di perdita sul capitale. Ignora pause, settlement, cooldown, slot mancanti, fill parziali, dividendi e componente max/min della barra; con esposizione più bassa il drag sul portafoglio cambia, con nozionale minore l’incidenza della fee cresce. Valori oltre 100% sono somma di frizioni teoriche, non perdite realizzate né capitale negativo simulato.

| Scenario/modalità (SEVERE: solo caso EUR senza conversione) | Costo RT EUR | Costo RT bps | Drag H=1 % | Drag H=5 % | Drag H=21 % |
|---|---|---|---|---|---|
| BASE Best | 4,00 | 40 | 100,80 | 20,16 | 4,80 |
| BASE Direct | 6,00 | 60 | 151,20 | 30,24 | 7,20 |
| STRESS Best | 9,00 | 90 | 226,80 | 45,36 | 10,80 |
| STRESS Direct | 13,00 | 130 | 327,60 | 65,52 | 15,60 |
| SEVERE Best | 14,00 | 140 | 352,80 | 70,56 | 16,80 |
| SEVERE Direct | 18,00 | 180 | 453,60 | 90,72 | 21,60 |

Dopo la ricalibrazione FX approvata il 2026-10-18, il caso EUR senza conversione ha 140/180 bps RT SEVERE e drag teorico H=21 16,80/21,60%, H=5 70,56/90,72%. Il precedente profilo con extra FX 100 bps/lato aveva 340/380 bps e rimane soltanto confronto storico §7.2. BASE H=1: 100,80/151,20%; STRESS H=5: 45,36/65,52%. Non prova che tutte le configurazioni siano matematicamente impossibili o NON_VALIDATO prima dei dati: non è stato imposto un limite superiore ai rendimenti lordi. Documenta una barriera economica molto alta e il rischio di respingere strategie per uno shock arbitrario.

**Verifica pubblica TR al 2026-10-16:** il [listino italiano](https://traderepublic.com/it-it?openModal=pricing-scheme) documenta 1 EUR/2 EUR e spread/costi terzi; la [FAQ ex-post](https://support.traderepublic.com/en-de/809-Cosa-sono-le-informazioni-sui-costi-ex_post) menziona conversioni di dividendi esteri e rimanda ai costi dell’ordine. Non è stata trovata una tariffa esplicita di 100 bps per lato per l’acquisto/vendita di titoli USA quotati e regolati in EUR. Per un’operazione interamente EUR non va inventata una conversione USD del conto: l’esposizione economica al dollaro rimane incorporata nel prezzo EUR, che può includere spread/basis del market maker. Quest’ultima è una distinzione di modello, non prova che tutti i canali abbiano costo FX nullo. Direct Price/valuta effettiva e conversioni di dividendi richiedono documenti applicabili al conto. La frase del sito sui cambi carta non prova costi di trading azionario. I 100 bps del profilo precedente erano quindi uno **shock ipotetico non attestato**, con possibile sovrapposizione al costo spread già previsto. Questa analisi documentale del 2026-10-16 è aggiornata dalla ricalibrazione condizionata §7.2 approvata dall’utente il 2026-10-18; nessuna conversione effettiva può essere ignorata.

Decisione SEVERE acquisita il 2026-10-18: l’utente sceglie **c**, mantenere il gate necessario e ricevere prima dell’applicazione una proposta FX documentata. La ricalibrazione numerica condizionata §7.2 è **APPROVATA E APPLICATA AI DOCUMENTI** il 2026-10-18: riga SEVERE e analisi d’impatto aggiornate, nessun codice implementato. SEVERE resta gate necessario. Prossima decisione: H=1, una domanda alla volta; fino alla risposta griglia e N20 invariati.

Decisione H=1 successiva: **(a)** resta in griglia e in N; **(b)** soltanto diagnostico, fuori selezione e N: 18→12 configurazioni,20→14 percorsi; **(c)** eliminato, senza curva diagnostica. Nell’opzione(b) nessun uso dei risultati H=1 per modificare le altre regole; altrimenti è un nuovo tentativo. Fino alla risposta **H=1 resta in griglia e N=20**; anche H=5 resta invariato.

| Disegno | Configurazioni/percorsi N | Alpha unilaterale per percorso | z=Phi^-1(1−0,05/N) |
|---|---|---|---|
| Attuale, H=1 incluso |18/20 |0,002500 |2,807034 |
| Solo ipotesi H=1 fuori dalla ricerca selettiva |12/14 |0,003571 |2,690110 |

A parità di varianza i.i.d. la soglia z scende di circa 4,17%, non azzera la barriera dei costi. Cambierebbe anche il massimo atteso del DSR a parità di dispersione. Sono confronti di sensibilità, non modifiche al conteggio attuale.

### 7.2 Ricalibrazione FX approvata, condizionata alla valuta — 2026-10-18

**Approvata esplicitamente dall’utente e applicata ai documenti il 2026-10-18. La spec/piano complessivi restano NON APPROVATI e non si implementa codice.** SEVERE resta gate necessario. Il precedente extra di 100 bps FX avversi per lato è sostituito con **0 bps di extra FX sul nozionale dell’ordine soltanto quando prezzo e regolamento di entrata/uscita sono interamente in EUR e non avviene una conversione di cassa**. Non è una tariffa generale “TR FX gratis”: è una regola contabile per non aggiungere una conversione assente o già incorporata nel prezzo. Spread, basis valutaria e slippage restano nel prezzo EUR e nel minimo SEVERE di 50 bps per lato; valori peggiori documentati prevalgono. Restano fee SEVERE 2 EUR Best/4 EUR Direct per eseguito, ritardo 15 minuti, fill conservativi, rischio e tutti i gate. Nessuna variazione BASE/STRESS.

Fonte primaria: [TR Execution Policy 07/2026, pagina 2](https://assets.traderepublic.com/assets/files/EN_ExecutionPolicy.pdf) include la conversione valutaria nella determinazione del prezzo offerto per operazioni a prezzo fissato. È la base documentale della separazione tra prezzo EUR complessivo e ulteriore addebito FX; il valore 0 è una **regola di modello condizionata approvata**, non un costo totale misurato. La policy pubblica non attesta le condizioni del conto italiano o l’adeguatezza dei 50 bps per ogni titolo/finestra: G_TR_TRANSFER resta necessario.

La [FAQ Direct Price](https://support.traderepublic.com/de-de/835f9deb-b864-4587-b428-7facfc55296c), versione pubblica tedesca consultata il 2026-10-18, indica conversione al momento dell’esecuzione per ordini su borse non EUR. Non estendere quindi lo zero separato a Direct su Nasdaq/NYSE in USD né presumere che ogni Best abbia regolamento EUR. Per ordini con effettiva conversione, applicare cambio bid/ask e margine documentati nel profilo specifico, al momento corretto, una sola volta. Se tasso, formula, unità, margine o applicabilità al conto non sono attestati: **FX_COST_UNKNOWN -> INSUFFICIENTE**, nessun PASS con extra FX inventato a zero o a 100 bps. Nessuna scelta ex post della sede/valuta che fa passare il backtest: profilo venue/valuta congelato ex ante, medesimi 20 percorsi, nessuna variante selettiva nascosta.

Dividendi e altri proventi USD restano flussi distinti, convertiti alla data pertinente con costo documentato: lo zero sul nozionale degli ordini EUR **non azzera il costo FX dei dividendi**. La [FAQ italiana conversioni](https://support.traderepublic.com/it-it/880) descrive conversioni di redditi esteri tramite bid/ask e margini; riporta USD 0,0014. Questo valore non è una percentuale o automaticamente 14 bps: non usarlo come margine degli ordini Direct né convertirlo in bps senza unità, base di quotazione e applicabilità provate. In mancanza, costo insufficiente. Nessun riferimento ai cambi della carta come prova dei costi titoli.

Confronto aritmetico a nozionale costante 1.000 EUR, due eseguiti, stesse ipotesi §7.1: le righe approvate valgono **solo nel caso senza conversione di cassa**, non per tutti gli ordini Best/Direct. Nessun risultato economico è stato calcolato.

| Profilo SEVERE | Extra FX per lato | RT EUR | RT bps | Drag H=1 % | Drag H=5 % | Drag H=21 % |
|---|---|---|---|---|---|---|
| Precedente Best | 100 bps | 34,00 | 340 | 856,80 | 171,36 | 40,80 |
| Approvato Best, ordine/regolamento EUR | 0 bps | 14,00 | 140 | 352,80 | 70,56 | 16,80 |
| Precedente Direct | 100 bps | 38,00 | 380 | 957,60 | 191,52 | 45,60 |
| Approvato Direct, sede e regolamento EUR | 0 bps | 18,00 | 180 | 453,60 | 90,72 | 21,60 |

La riduzione è 20 EUR/200 bps per RT su 1.000 EUR, equivalente ai due extra da 100 bps rimossi; non certifica redditività e lascia frizioni elevate soprattutto su H=1. Eventuali conversioni di proventi, costi terzi e ricorrenti restano da sommare ai flussi reali senza duplicazioni. Il rischio economico EUR/USD e la scomposizione §9.2 restano invariati. L’approvazione della regola non dimostra dati o trasferibilità TR. Il confronto precedente è storico, non un ulteriore scenario/candidato da scegliere dopo i risultati. H=1/N20, soglie statistiche e gate necessario SEVERE restano invariati.

## 8. Campione, walk-forward e holdout proposti

Date congelate prima di qualsiasi lettura di risultati; sessioni risolte dal calendario, non da disponibilità dei titoli:

| Ruolo | Intervallo incluso | Regola |
|---|---|---|
| Warm-up/fondazione | 2016-01-04–2016-12-30 | Solo storia causale, nessun rendimento di validazione |
| Sviluppo/IS iniziale | 2017-01-03–2019-12-31 | Decisioni e selezione solo su prefissi ammessi |
| OOS WFO | 2020-01-02–2023-12-29 | Minimo 1.000 sedute; blocchi consecutivi di 126 sedute, ultimo resto incluso senza spostare le date |
| Holdout finale sealed | 2024-01-02–2026-09-30 | Minimo 630 sedute; unico ciclo di apertura dopo congelamento del candidato e dei gate |

Ogni blocco OOS usa le 504 sedute IS immediatamente precedenti una separazione di 21 sedute. Purge deterministico: nessuna nuova entrata IS il cui termine pianificato superi il cutoff IS; risultati IS troncati e valutati con soli eventi disponibili a quel cutoff. Gap/posizioni irrisolte non vengono rimossi in base a esiti futuri; se impediscono uno score verificabile, quel trial è insufficiente. La separazione di 21 sedute è embargo operativo e non estende i dati IS con OOS. Non fare purge del test scegliendo a posteriori quali sedute furono sfavorevoli.

Per ciascuna modalità, selettore WFO sceglie fra le nove configurazioni tramite Sharpe giornaliero netto IS BASE; minimo 30 round-trip e 126 giorni con esposizione IS, score non definito -> ineleggibile. Tie: minor drawdown IS, poi ID canonico. Nessuna configurazione idonea -> cash nel blocco, trial comunque registrato. Tutte le simulazioni IS hanno prefisso fisico al cutoff, senza leggere OOS per scoprire split/gap/liquidazioni; test R1 obbligatorio.

OOS del selettore è continuo, senza liquidazione a ogni fold. Cambia solo la regola delle nuove entrate; posizione aperta conserva famiglia/H/stop originari. Le nove curve candidate sono preregistrate, non nove possibilità tra cui scegliere il migliore dopo OOS. Quella selezionata per il holdout deve superare anch’essa tutti i gate OOS sull’intero OOS congelato, oltre al selettore continuo; se fallisce non si ripiega sulla seconda classificata. Minimo otto blocchi, almeno sei con P&L netto BASE positivo; nessuna parte finale ignorata.

Per il holdout congelare una sola configurazione per modalità, scelta con lo stesso selettore sulle ultime 504 sedute IS che terminano 21 sedute prima del holdout. Non scegliere il miglior OOS. La configurazione deve appartenere alla griglia; sia la sua curva fissa sia il relativo selettore devono aver superato i gate OOS. L’OOS può respingere la scelta IS, non sostituirla con una più favorevole. **Limite M3:** il calendario di controllo dà IS finale 504 dal 2021-11-29 al 2023-11-29, embargo 21 dal 2023-11-30 al 2023-12-29. Questo IS cade dentro l’intervallo denominato OOS 2020–2023: il gate sulla curva fissa del candidato scelto su quel periodo è uno screening retrospettivo in parte in-sample, non una seconda prova indipendente. Il WFO del selettore resta causale fold per fold; per la configurazione finale il holdout è l’unica conferma temporale pulita. Niente retuning o reselezione dentro holdout. Inizio OOS e holdout con capitale 10.000 EUR e senza posizioni ereditate da training; valori e statistiche dei due campioni non sommati per mascherare un fallimento.

A fine campione, niente nuove entrate nelle ultime 21 sedute, regola nota in anticipo; posizioni non risolte non vengono liquidate all’ultimo close per chiudere il report. Esito INSUFFICIENTE se manca la risoluzione entro il campione, senza estendere le date dopo aver visto i risultati.

Holdout: riferimento/hash opaco, stato SEALED; codice di training/OOS non riceve reader né prezzi/membership con data holdout. Un job finale dedicato verifica prerequisiti, congela artefatti e apre una sola volta il batch finale, al massimo due candidati idonei e relativi stress, senza mostrare risultati intermedi. Eventi SEALED/OPENING/EVALUATED/CONTAMINATED append-only; crash/retry solo idempotente sul medesimo batch, senza permettere una nuova selezione. Letture esplorative esterne dichiarate contaminano il campione. Nessuna promessa di isolamento globale del filesystem.

## 9. Statistica e soglie economiche proposte

Unità primaria: rendimento netto del portafoglio per seduta, giorni flat inclusi, simultaneità tra titoli conservata. Nessuna moltiplicazione dei minuti/trade per creare osservazioni indipendenti. Report: rendimento cumulato/CAGR, media giornaliera, Sharpe, DSR, drawdown EUR e percentuale, code, turnover, esposizione, costi, fill/non-fill, ritardo e concentrazione. Benchmark congelati: cash con rendimento assunto zero; universo as-of equiponderato mensile, total return documentato e costi dichiarati, diagnostico non necessariamente investibile con 10.000 EUR. Hash benchmark/FX nel report, regressione R2 obbligatoria.

Registro: 18 configurazioni + 2 selettori = 20 percorsi nella famiglia di ricerca. Tutti i tentativi, compresi failed/cancelled/no-trade, sono preregistrati e non diminuiscono il denominatore. Nessun nuovo tentativo dopo ispezione OOS viene presentato come la stessa prova; modifiche di griglia/costi/fonte/campione richiedono nuova versione e rendono inutilizzabile un holdout già aperto per conferma indipendente.

Bootstrap stationary con indici congiunti per tutte le curve, 10.000 repliche, seed 20261015; lunghezza media blocco primaria 63 sedute, sensibilità obbligatoria 21. Per ogni lunghezza, limite inferiore unilaterale sulla media giornaliera: media osservata meno quantile 0,9975 delle differenze bootstrap media_risamplata−media_osservata. Bonferroni conservativo 0,05/20; richiedere LB > 0 in entrambe le lunghezze, separatamente su OOS e holdout. Il resampling circolare e geometrico va dichiarato; assunzioni di dipendenza debole/stazionarietà sono limiti, non prove garantite in ogni regime. Fonte metodologica: [Politis–Romano, Stationary Bootstrap](https://www.tandfonline.com/doi/abs/10.1080/01621459.1994.10476870).

DSR >= 0,95 sullo stesso snapshot preregistrato è controllo aggiuntivo. Il numero di tentativi rimane 20 anche se alcuni Sharpe non sono definiti: serve una **nuova funzione DSR nel pacchetto swing, Task8 (già Task7)**, con argomenti espliciti N e snapshot della varianza degli Sharpe. `lab.stats.deflated_sharpe` ricava N da `len(trial_sharpes)` e la varianza dalla medesima lista; `expected_max_sharpe` rifiuta non finiti. Non è quindi riusabile invariata per N=20 con trial non definiti e dispersione OOS congelata; nessuna modifica a SP1 o Sharpe fittizi per riempire la lista. La dispersione degli Sharpe è stimata dai percorsi OOS definiti, almeno due, e congelata prima del holdout; nel holdout usare quella dispersione e N=20, senza valutare gli altri percorsi sul holdout. Se la dispersione non è stimabile, il controllo è insufficiente e niente PASS. Il DSR non corregge da solo la dipendenza seriale. Sharpe/DSR e numero di tentativi distinguono valori non definiti da zero; non inventare Sharpe per no-trade o trial falliti. [Bailey–López de Prado, Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf). Le soglie SP1 esistenti restano invariate e non sono sostituite dai nuovi gate.

Tutte le condizioni sotto, per modalità, sono necessarie:

| Condizione | OOS | Holdout |
|---|---|---|
| Dati e integrità | G_SWING_DATA idoneo, zero contaminazioni | Stessi requisiti, batch finale sigillato |
| Campione | >= 1.000 sedute, >= 200 round-trip, >= 252 giorni con esposizione | >= 630 sedute, >= 100 round-trip, >= 126 giorni con esposizione |
| Rendimento BASE | P&L netto > 0, LB bootstrap > 0 per entrambe le lunghezze medie di blocco (63 e 21 sedute), DSR >= 0,95 | Stesse condizioni indipendentemente |
| Costi stressati | P&L netto STRESS e SEVERE > 0 | Stesse condizioni |
| Rischio | Drawdown <= 2.000 EUR in ogni scenario; nessuna violazione di cassa/size | Stesse condizioni |
| Stabilità | >= 6 blocchi OOS positivi su almeno 8; nessun singolo emittente oltre 25% del P&L positivo lordo per emittente | Almeno 2 dei 3 periodi 2024/2025/2026 parziale positivi BASE; stesso limite di concentrazione |

I gate OOS si applicano sia al selettore sia alla configurazione finale scelta IS; i gate holdout solo alla configurazione finale, senza alternare family/holding. Una modalità non idonea prima dell’apertura non viene aperta o ripescata successivamente sullo stesso holdout. Contare una posizione parzialmente eseguita come un round-trip logico, non molti trade indipendenti. Concentration share = contributo positivo di quell’emittente / somma dei contributi positivi di tutti gli emittenti, consolidando rename; denominatore nullo -> non validato. Le soglie sono proposte restrittive, non garanzia che il campione disponibile le renda raggiungibili.

Verdetti: INSUFFICIENTE per dati/campione/statistica mancanti; NON_IDONEO per provenienza/violazioni; NON_VALIDATO per gate economico osservato e fallito; PASS_RICERCA_PROXY solo se tutti i gate di ricerca passano con limiti proxy visibili. VALIDATO_TR richiede anche G_TR_TRANSFER su prezzi, FX, fill/stop e orari idonei, non un’etichetta del provider. Nessun verdetto abilita ordini o afferma redditività futura.

### 9.1 Effetto minimo rilevabile e potenza — analisi preliminare

Il calendario documentale di controllo 2020–2026-09-30 è ricostruito dalle tabelle ufficiali, include Juneteenth dal 2022 e chiusura Carter 2025-01-09; le sedute ridotte contano una seduta. Conteggi: 2020=253,2021=252,2022=251,2023=250 (OOS 1006, otto fold 126 con ultimo 124);2024=252,2025=250,2026 fino 09-30=187 (holdout 689). Lista date/open/close UTC congelata nelle evidenze di review con SHA256 `501470b59401bebd0a4613ef48e4b6ec839cc727a4856db0dc54321bb522c9bb` e framing `date|open_utc|close_utc` con newline LF. È un controllo documentale riproducibile, non un calendario REAL del DB né G_SWING_DATA già superato; il Task3 deve attestare il calendario del pacchetto senza cambiare date o minimi per farlo passare. Fonti: [NYSE2020–2022](https://ir.theice.com/press/news-details/2019/NYSE-Group-Announces-2020-2021-and-2022-Holiday-and-Early-Closings-Calendar/default.aspx), [NYSE2022–2024](https://ir.theice.com/press/news-details/2021/NYSE-Group-Announces-2022-2023-and-2024-Holiday-and-Early-Closings-Calendar/default.aspx), [NYSE2023–2025](https://ir.theice.com/press/news-details/2022/NYSE-Group-Announces-2023-2024-and-2025-Holiday-and-Early-Closings-Calendar/default.aspx), [Carter](https://www.ice.com/insights/conversations/inside-the-ice-house/market-storylines/01-06-2025), [NYSE2026](https://www.nyse.com/trade/hours-calendars).

In approssimazione normale i.i.d., Sharpe annualizzato di soglia = z×sqrt(252/n), con z=2,807034 per N20. È la frontiera puntuale del test, circa 50% di potenza quando il vero effetto coincide con la soglia, **non MDE con potenza 80%**. Per quest’ultima: SR80=(z+Phi^-1(0,8))×sqrt(252/n), con Phi^-1(0,8)=0,841621. Le formule sono analisi di ordine di grandezza per una media standardizzata, non equivalenti esatti del bootstrap/DSR.

| Campione | n | SR soglia N20 | MDE SR potenza 80% N20 | SR soglia N14, solo alternativa |
|---|---|---|---|---|
| OOS WFO | 1006 | 1.405 | 1.826 | 1.346 |
| Holdout completo | 689 | 1.698 | 2.207 | 1.627 |
| Minimo holdout | 630 | 1.775 | 2.308 | 1.701 |

Con autocorrelazione positiva, il fattore approssimato di lungo periodo è sqrt(1+2×somma rho_k); per AR(1) rho=0,3 è circa 1,363. È un esempio teorico, non stima sui dati: la soglia cresce e non basta sostituire il numero di trade a n. DSR>=0,95, sei fold positivi su otto, due anni positivi su tre, rischio/concentrazione e scenari stressati sono condizioni congiunte: la potenza complessiva può essere molto inferiore a quella del solo test sulla media. Le loro probabilità non si moltiplicano assumendole indipendenti. Non si deduce la potenza reale senza una distribuzione congiunta e dati idonei. Nessuna soglia viene abbassata dalla revisione.

### 9.2 Proposta preregistrabile: eccesso sul mercato e componente locale USD

I gate attuali contro cash zero non distinguono rendimento da beta, drift valutario e selezione titoli. Si propone, da approvare prima dei test, un confronto unico: **universo as-of equiponderato mensile, total return USD, scalato con esposizione della strategia al precedente close**. Stesso universo storico/delistati, niente indice di sopravvissuti. Sia w_(t−1) il nozionale delle azioni USD (esclusi cassa/crediti) convertito in EUR / equity totale al precedente close, noto prima del rendimento t. Non usare esposizione di fine giornata o del futuro, né media full-sample. Il benchmark è lordo di commissioni per un confronto severo contro la strategia netta; non è presentato come portafoglio 500 nomi eseguibile con 10.000 EUR. La scala laggata approssima l’esposizione giornaliera: dichiarare la differenza dovuta ai fill intraday e i rischi settoriali residui, senza chiamarla prova di alpha priva di ogni beta.

Con x_t EUR per 1 USD e R_U,t^USD total return dell’universo, R_U,t^EUR=(1+R_U,t^USD)×x_t/x_(t−1)−1. Eccesso netto proposto a_t=r_S,t^EUR−w_(t−1)×R_U,t^EUR, adimensionale per seduta. Gate aggiuntivo proposto: media(a)>0 e LB bootstrap(a)>0 inBASE, sia sul vero OOS WFO sia sul holdout; la curva fissa retrospettiva rimane screening non indipendente. Il null a ingressi casuali non viene aggiunto come seconda opportunità: sarebbe un’alternativa da scegliere ex ante, non da selezionare dopo il risultato.

Scomposizione esatta del ledger, per intervalli i delimitati da ogni flusso/fill/mark: U_i valore della sleeve USD (posizioni, cassa e crediti USD), F_i flusso netto di capitale nella sleeve contabilizzato al cambio x_i, P_i^USD=U_i−U_(i−1)−F_i P&L locale netto di costi USD. La cassa EUR varia di −x_iF_i−fee_i^EUR. Allora DeltaE_i^EUR = x_(i−1)P_i^USD + U_(i−1)Delta x_i + P_i^USD Delta x_i − fee_i^EUR. Riportare separatamente locale, FX, interazione e costi EUR, sommando gli intervalli; non attribuire al solo FX tutto il profitto in EUR, né usare il P&L di un portafoglio interamente finanziato inUSD come replica della strategia con cassaEUR.

Gate locale proposto: K0^USD=10.000EUR/x0 e g_t=[somma_i(P_i^USD−fee_i^EUR/x_i)]/K0^USD. È P&L USD normalizzato al capitale iniziale USD, non un nuovo portafoglio/size o un rendimento euro nuovamente convertito; giorni flat inclusi. Richiedere media(g)>0 e LB bootstrap(g)>0 inBASE su WFO OOS e holdout. Usare lo **stesso bootstrap congiunto** per (rEUR,a,g), indici comuni tra metriche e percorsi e entrambe le lunghezze 63/21, alpha 0,05/N corrente. I nuovi gate sono una congiunzione obbligatoria proposta sugli stessi 20 percorsi, non nuovi candidati, seed/benchmark opzionali o occasioni di PASS: **N non aumenta**, purché non si scelga quale metrica far passare dopo i test. Adottarli richiede approvazione della proposta; nessuna prova economica è stata eseguita ora.

Verifica del solo drift BCE con estremi dichiarati:1,2271USD/EUR al 2020-12-31 e 1,0666 al 2022-12-30 danno un rendimento EUR del dollaro pari a 1,2271/1,0666−1=**+15,05%** nel 2021–22 (non un +20% generico senza date). Nel 2025: 1,0389 al 2024-12-31 e 1,1750 al 2025-12-31 -> **−11,58%**. Non sono P&L della strategia, che ha esposizione variabile, e non validano un’intera serie FX. Valori verificati su documenti pubblici BCE, senza API o download di serie: [fine2020](https://www.ecb.europa.eu/press/annual-reports-financial-statements/wfs/2021/html/ecb.fs210106.en.html), [fine2022](https://www.ecb.europa.eu/press/annual-reports-financial-statements/wfs/2023/html/ecb.fs230104.fi.html), [2024/2025](https://www.ecb.europa.eu/press/annual-reports-financial-statements/annual/annual-accounts/html/ecb.annualaccounts2025~ba3b593c99.en.html).

### 9.3 Precisione del quantile bootstrap e limite M5

Con 689 sedute e blocco medio 63 si hanno circa 10,94 blocchi medi (non osservazioni indipendenti garantite). Il quantile 0,9975 con 10.000 repliche ha soltanto 25 estrazioni attese oltre soglia. Errore standard Monte Carlo sulla probabilità = sqrt[p(1−p)/B]=0,0004994 (0,04994 punti percentuali). Intervallo binomiale 95% per il quantile condizionale ai dati, in termini di statistiche d’ordine delle 10.000 medie centrate, circa[Delta_(9965),Delta_(9985)]. Riportare questi due valori e il corrispondente intervallo del LB=[media−Delta_(9985),media−Delta_(9965)] nelle unità del rendimento giornaliero; SE del quantile in rendimento richiederebbe densità locale stimata, non è numericamente conoscibile senza dati. Un LB vicino a zero può essere instabile rispetto alla sola simulazione Monte Carlo.

Aumentare repliche ridurrebbe errore Monte Carlo ma non crea più informazione o blocchi storici e non risolve da solo non-stazionarietà/pochi blocchi. Questo limite deve apparire nel report con una misura dell’incertezza del quantile; non si sceglie dopo il risultato un seed, una lunghezza o un numero di repliche più favorevole. B=10.000, seed 20261015 e gate attuali restano invariati fino a nuova decisione esplicita.

## 10. Confini software, verifiche e avanzamento

Nessuna tabella o migrazione sul DB applicativo, nessun job/API/frontend nuovo in v1. Output ricerca su file immutabili e CLI locale esplicita; un eventuale collegamento alla UI sarà una proposta successiva. Riuso SP1 di funzioni pure statistiche/indicatori con contratti verificati; riuso SP3 di principi registry/seal/causalità, non di ledger/holdout/bootstrap non ancora implementati nei Task6–10 sospesi. Nessuna modifica ai moduli intraday o alle loro soglie 5/20/60.

Ogni task software: RED offline per il comportamento concreto, implementazione minima, GREEN, review del diff e controlli di regressione pertinenti; suite backend offline prima della chiusura, Ruff e dipendenze senza nuove installazioni. Database dei test solo temporanei, rete e dotenv negati; nessuna lettura DB reale anche negli smoke. Le fixture di holdout sono sintetiche e non aprono il holdout REAL.

Causalità obbligatoria: cambiare prezzi, split, membership, FX e corrispettivi successivi al cutoff non cambia segnali, size, IS o selezione; conservare gap e delistati, evitare il close ufficiale nei fill; contabilità a mano per stop/gap/dividendi/FX/settlement; stato del holdout e snapshot benchmark immutabili. Verifiche scalari di streaming/RAM e profiling offline senza attenuare i cap dopo un fallimento.

L’implementazione autorizzabile finisce al software offline; nessuna valutazione REAL, import esterno o apertura del holdout in questa consegna documentale. Il nuovo Task3 richiede dataset/prove di fattibilità prima dei Task4–9; la fase economica finale Task10 richiederà dataset locale idoneo e incarico dedicato. Se nessun pacchetto gratuito soddisfa universo/delistati/finestra, dichiarare il limite e fermare quel gate: non comprare dati, raccogliere live o sostituire sopravvissuti. Il piano specifica task sequenziali, allowlist e commit; Ricalibrazione FX §7.2 approvata e applicata ai documenti; decisione H=1 ancora aperta, una domanda alla volta; approvazione complessiva della presente spec e del piano richiesta prima del Task1. Merge FF su main soltanto dopo conferma esplicita dell’utente, anche per Task0.
