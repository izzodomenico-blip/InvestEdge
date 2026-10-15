# Swing 1–21 sedute — inventario SP1 e cambio di priorità

Data: 2026-10-15. Analisi di codice e documentazione pubblica, senza esecuzioni economiche, accesso al DB reale, credenziali o download di dati di mercato. Base verificata: `6c32bfa4559336d9903af0d30c03e7145586cd52`, già su origin/main e origin/investedge/sp3-task-5. Questo rapporto è un inventario e un brief di brainstorming: **non è la nuova spec né il piano di implementazione**. Le successive risposte al brainstorming sono recepite sotto; proposta [spec SP3s](../superpowers/specs/2026-10-15-investedge-sp3s-swing-research-design.md) e [piano SP3s](../superpowers/plans/2026-10-15-investedge-sp3s-swing-research.md) separati, ancora da approvare.

## Decisione e stato conservato

L’utente sospende il percorso intraday 15–30 minuti SP3/SP6a, senza cancellarlo. Task5 è operativo **BLOCCATO: sospeso per decisione utente 2026-10-15**. Il suo codice era già completato, pubblicato e integrato prima della richiesta: commit `6c32bfa`, 2564 test backend e 186 mirati verdi nella consegna precedente. Non sono nuove esecuzioni di test di questo inventario. Nessun codice SP2b/SP3, incluso Task5, viene rimosso o modificato; nessun reset, rebase o annullamento del merge passato.

Le Data Policies UTP pubblicate a settembre 2023 riportano 2.500 USD/mese per firm per il Direct Access e includono Snap-Shot in tale accesso; l’amministrazione pubblica richiede accordi e procedure vendor. È una tariffa documentale datata, non una certificazione dei costi complessivi applicabili oggi o dell’impossibilità di ogni alternativa per ogni privato. La decisione dell’utente è la non sostenibilità del percorso progettato. La spec SP3 richiede 446 sedute più warm-up 30, circa 476: quasi 1,9 anni a 252 sedute/anno, non una promessa di calendario o copertura. Le evidenze storiche incomplete non diventano catture STRICT_PIT. Fonti: [UTP2023](https://www.utpplan.com/doc/DataPolicies.pdf), [procedure vendor](https://www.utpplan.com/data_admin); spec SP3 §§10–11.

## Brief acquisito, non ancora spec approvata

| Decisione | Valore scelto dall’utente |
|---|---|
| Orizzonte | Swing, holding 1/5/21 sedute; distinto dai timeframe D/W/M |
| Capitale | 10.000 EUR di riferimento, nessun denaro movimentato |
| Broker/esecuzione | Trade Republic, manuale dell’utente; nessuna automazione TR |
| Costi TR | Confrontare separatamente Best Price e Direct Price, senza scegliere il migliore dopo OOS |
| Universo | Sole azioni liquide USA, ricostruite as-of, incluse quelle poi delistate |
| Liquidità | Criteri da fissare ex ante e calcolare sul solo passato; nessuna lista corrente usata come universo storico |
| Disponibilità TR attuale | Solo filtro per operatività futura, non filtro retrospettivo dei test |
| Finestra | 45–10 minuti prima della chiusura regolare USA: normalmente 21:15–21:50 Europe/Rome; 20:15–20:50 nelle settimane DST disallineate |
| Sedute ridotte | Stessa finestra relativa alla chiusura anticipata, su conferma dell’utente |
| Informazione al segnale | Solo quella disponibile poco prima, anche con 15 minuti di ritardo; non daily definitiva del giorno ancora aperto |
| Prezzo di esecuzione | Nella finestra manuale con spread/slippage conservativi; mai sostituito dalla chiusura ufficiale |
| Rischio iniziale per posizione | 1% del capitale, 100 EUR sui 10.000 EUR iniziali; perdita da gap può superarlo |
| Drawdown OOS | Massimo 2.000 EUR, 20% del capitale di riferimento, come soglia di accettazione |
| Stop | Inseriti manualmente su TR e lasciati attivi, previa verifica del supporto per titolo e modalità Best/Direct |
| Portafoglio | Massimo 10 posizioni senza leva, rischio iniziale aggregato fino a 1.000 EUR |
| Europa/ETF | Eventuali studi separati successivi |

Identificativo proposto: **SP3s — Strategie swing USA 1–21 sedute**. Branch documentale proposto: `investedge/sp3s-task-0`. Creato dopo il checkpoint di sospensione `3f37a44b76ba8f8c8182281dbe6301a9898bc11a`; le domande materiali sono risolte e la proposta documentale è pronta per review/approvazione, senza codice. Famiglie proposte nella nuova spec: trend/momentum, pullback in trend e breakout su più giorni. Non sono ancora regole approvate o strategie redditizie.

## Dati daily REAL: cosa esiste e cosa manca

| Area | Codice esistente | Limite per la nuova ricerca |
|---|---|---|
| EOD azioni | `data_providers/stooq.py`, `ProviderRegistry.providers_for`, `MarketDataService`: percorso governato Stooq su listing e provider symbol verificati | Disponibilità del provider non prova che il DB locale contenga dati sufficienti; DB non ispezionato |
| Rettifiche | `lab/series.py:PROVIDER_ADJUSTMENT_BASIS`: Stooq UNKNOWN, CoinGecko NOT_APPLICABLE. Stooq conserva adjusted_close=close | UNKNOWN non significa né raw verificato né split/dividend-adjusted verificato. Il lab usa fattore 1; dividendi non accreditati come total return verificato |
| Split/gap | Segmenti per buchi oltre 5 sedute, cambi di base e split sospetti su rapporti discreti | Guardia euristica, non ricostruzione degli eventi. Una segmentazione non sostituisce il rendimento del delisting e non deve eliminare perdite storiche |
| Valuta | `EurConverter`, backfill BCE governato, FX as-of per data con età massima 7 giorni, seed esclusi | Servono ancora identità/listing/venue e timestamp disponibili coerenti con la finestra manuale. FX daily non equivale automaticamente al prezzo TR eseguito |
| Universo | `lab/universe.py:_resolve_assets` usa gli asset oggi presenti; risolve ambiguità e congela input/esclusi | Non ricostruisce l’universo storico richiesto; mancano prova completa di ingressi/uscite, identità, delistati e recuperi finali |
| Fonti legacy | Classe Yahoo Finance presente, ma non selezionata dal percorso EOD corrente azionario governato; Alpha Vantage EOD DISABLED per SECRET_IN_QUERY_POLICY | Non sono fallback già pronti o fonti di rettifica attestate. Nessuna riattivazione in questo lavoro |
| Fonte intraday | SP2b ha adapter Alpaca ufficiale e metadata/calendar/eventi versionati | L’adapter accetta soltanto 1Min/raw e non è un adapter daily per price_history/SP1; non basta cambiare un’opzione |

**Dati delistati e survivorship sono un gate aperto.** La lista attuale dei titoli, l’asset catalog corrente Alpaca o l’assenza di barre non provano un universo as-of. Servono un’anagrafica storica verificabile, liquidità laggata, operazioni societarie, ticker riutilizzati/rename, prezzi prima/dopo delisting e modalità di liquidazione/recupero. Un titolo eleggibile in passato non scompare dal campione perché oggi inattivo o non disponibile su TR. Prezzo terminale mancante non è zero, −100% o ultima chiusura senza prova: conservare l’esito mancante e dichiarare insufficienza. Le fonti gratuite consultate **non dimostrano ancora la completezza** di questo pacchetto; non si autorizza un ripiego su un universo di sopravvissuti.

### Alpaca Basic come candidato daily

La documentazione ufficiale consultata il 2026-10-15 indica Basic gratuito, azioni/ETF USA, storico dal 2016 e 200 richieste storiche/minuto. Il limite SIP senza abbonamento riguarda gli ultimi 15 minuti, non tutto lo storico: la FAQ mostra barre 1Day SIP e richiede un end sufficientemente arretrato. Quindi **può essere una fonte daily candidata senza 99 USD/mese**, documentalmente; accesso effettivo, diritti, copertura, delistati e qualità non sono stati provati tramite API. Realtime Basic è IEX, non mercato consolidato: specificare il feed, non usarne il default. La stessa FAQ limita i dati OTC a un abbonamento speciale disponibile ai broker partner: non presumere quindi la copertura gratuita dei prezzi di uscita dopo un delisting. Fonti: [piani](https://docs.alpaca.markets/us/docs/about-market-data-api), [FAQ storico](https://docs.alpaca.markets/us/docs/market-data-faq).

L’endpoint barre supporta raw, split, dividend, spin-off e all; split rettifica anche i volumi. Il parametro asof gestisce l’identità del simbolo e i rename: **non certifica la vintage dei prezzi/rettifiche o la composizione storica dell’universo**. Preservare dati raw e operazioni societarie, distinguere serie per segnali/total return da prezzi eseguibili e cash dividend, evitare doppio conteggio e rettifiche future sui filtri di prezzo/size. L’API corporate actions dichiara ritardi e nessuna garanzia sul momento di disponibilità degli eventi: un download attuale non diventa archivio di annunci noto allora. Fonti: [barre](https://docs.alpaca.markets/us/reference/stockbars), [corporate actions](https://docs.alpaca.markets/us/reference/corporateactions-1).

Per 21:15–21:50 non bastano le sole daily: occorrono prezzi storici nella finestra e, se usato nel segnale, un prefisso del giorno tagliato al cutoff informativo. Con ritardo di 15 minuti un evento di mercato a t non entra automaticamente nel segnale a t. Non usare il massimo/minimo/close definitivo della daily prima della chiusura; non scegliere ex post il miglior minuto. Orari/eventi/fill devono essere congelati ex ante. Resta da verificare se una proxy USA sia accettabile per ciascuna modalità TR: una barra SIP non è una quotazione Best Price TR né un fill manuale garantito.

## Laboratorio SP1: già implementato e differenze materiali

| Capacità | Implementazione verificata in lettura | Estensione richiesta |
|---|---|---|
| Feature/score | `lab/features.py`, `resample.py`, `score_v1.py`, `feature_store.py`: feature causali, finestre finite, D/W/M chiusi as-of, score unico tecnico e warm-up 252 barre del timeframe | Valutare feature necessarie per ciascuna famiglia; non ereditare automaticamente tutti i pesi dello score. Nessun uso della daily ancora incompleta come chiusa |
| Strategie | `lab/strategies.py`: SCORE_THRESHOLD, TOP_N_SCORE, BUY_AND_HOLD; ribilanciamenti daily/weekly/monthly | Nuovi setup swing e invalidazioni ex ante; frequenza di rebalance non è un timer di holding |
| Simulazione | `lab/simulator.py`: long-only, cassa/EUR, quantità, ordini minimi, segnale al close e fill al prossimo open del listing; stop prudente min(open,stop), priorità stop se stop/target entrambi toccati | Prezzo nella finestra manuale, ritardo umano/informativo e non-fill; holding 1/5/21 dal fill effettivo, gestione gap/overnight ed eventi societari/uscite non osservate |
| Etichette | `lab/harness.py:HORIZONS=(1,5,21)`, rendimento open(t+1+h)/open(t+1)−1; non attraversa segmenti, IC/bucket/turnover | Etichette non impongono quelle durate al portafoglio. Riallacciarle al nuovo contratto di prezzo/finestra senza spacciare diagnostica long-short per strategia TR eseguibile |
| WFO | `lab/walk_forward.py`: IS 504, OOS 126, scelta solo IS sui prefissi, OOS continuo; griglie 12 score e 6 TOP_N | Purge/embargo coerenti con holding 21 e dipendenze; holdout finale separato; famiglie/griglie e calendario congelati prima dei test |
| Evidenza | `lab/evidence.py`: REAL-only, IC medio>0, t NW≥2, spread netto>0, DSR≥0,95; min 252 date IC, 252 sedute OOS e 10 nomi medi | Non è una validazione economica delle nuove strategie. Soglie SP1 restano; nuove soglie/campione per policy/holding e stress vanno proposti e approvati ex ante |
| Statistica | `lab/stats.py`: Spearman, Newey–West; harness lag h−1 per overlap, momenti/PSR/DSR | DSR non corregge da solo dipendenza seriale. Bootstrap a blocchi congiunto per seduta, costi/giorni flat e correzione di tutti i tentativi sono ancora da progettare/implementare |
| Tentativi/report | `lab/trials.py`, report immutabili e snapshot benchmark/FX/input hash, job cancellabili, UI Evidenza | SP1 registra risultati REAL con Sharpe finito: non preregistra tutti i falliti/cancellati/no-trade. Serve registro completo e namespace swing; snapshot di run non prova la disponibilità storica originaria |

Il valore SP1 VERIFICATO è software/storia del progetto, non evidenza fresca di profitto. Non è stata eseguita ricerca REAL in questa analisi e non è stato letto alcun report dal DB dell’utente.

## Costi TR manuale e confronto Alpaca

SP1 implementa `CostProfile` con 1 EUR per eseguito, 10 bps per lato equity e 50 bps crypto; quote intere di default, minimo 100 EUR, profilo salvato nel run. Spread/slippage sono **assunzioni**, non misure TR. Contabilità/tassazione e bollo sono semplificati; non è un ledger broker versionato/Decimal con piena riconciliazione. Non copre integralmente riporto minusvalenze e distribuzioni societarie.

Il listino italiano TR consultato distingue 1 EUR per operazione e 2 EUR se si seleziona una borsa Direct Price, oltre spread/costi terzi. L’utente richiede due modalità separate: la costante SP1 da 1 EUR non copre automaticamente entrambe né tutte le date storiche. Esempio puramente aritmetico, con 1.000 EUR di nozionale e l’ipotesi SP1 di 10 bps/lato: 2 EUR di costi variabili round-trip più 2 EUR Best Price = 4 EUR / 40 bps; oppure più 4 EUR Direct Price = 6 EUR / 60 bps. Non sono preventivi o costi misurati. Vanno congelati profilo, data/regime tariffario, venue/valuta, ritardo manuale e stress per lato; niente selezione opportunistica del canale dopo OOS. [Listino TR](https://traderepublic.com/it-it?openModal=pricing-scheme).

Alpaca è un confronto distinto: per account self-directed idonei la documentazione descrive commission-free con oneri regolatori applicabili, e non un costo totale zero. SEC/TAF/CAT, cambio USD/EUR, conto/paese e tariffe storiche restano da verificare se quel confronto sarà richiesto; il modello TR non va trasferito. Basic storico come fonte non impone Alpaca come broker. Nessun conto/API trading/paper viene attivato. [Account](https://alpaca.markets/support/types-accounts-alpaca-offers), [oneri](https://docs.alpaca.markets/us/docs/regulatory-fees).

## Riuso SP2b/SP3: codice contro progetto non realizzato

| Componente | Già presente | Riuso possibile/limite |
|---|---|---|
| SP2b dati | Identità listing/versioni, calendari, corporate action, archive/snapshot/timeline e guardie, job governati | Riutilizzare primitive/fencing/hash; gli snapshot acquisiti ora non ricostruiscono da soli un universo storico e un’attestazione di disponibilità passata |
| SP3 Task1 | Manifest/config hash, preregistrazione 20 trial/10 policy, eventi append-only e riferimenti tipizzati | Principi riusabili. Namespace, griglia e vincoli intraday non vanno mutati o imposti al daily; nuova versione/scopo approvati |
| Holdout Task1 | Stato iniziale SEALED e registro eventi di integrità nel manifesto | Solo metadati: protocollo di accesso/apertura/contaminazione/evaluation era Task9–10, ancora NON INIZIATO. Nessuna promessa di isolamento globale del filesystem |
| Task2 | Reader timeline-only, blocchi sigillati, budget/fence/test prestazioni | Eventuale riuso tecnico senza importare i gate G1 intraday o gli stessi cap per un universo swing diverso |
| Task3–5 | Quote/tick e news source attestati, contesto daily PIT, setup puri e dedup | Primitive causali/identità/provenienza utili; nessun trasferimento di OR/VWAP/holding 15–30 minuti alla nuova ricerca. Codice conservato intatto |
| Statistica dipendente | Progettata nella spec SP3; Newey–West/DSR implementati in SP1 | Bootstrap congiunto e multiplicità SP3 erano Task8, NON INIZIATO: non c’è un motore già pronto da riusare |
| Ledger costi | SP1 ha contabilità simulata e profilo TR; SP3 Task6 era il prossimo task | Ledger Alpaca versionato e aritmetica relativa NON IMPLEMENTATI. Riprendere il disegno utile, non affermare riuso di codice inesistente |

## Proposta di sequenza, prima della spec

1. Decisioni materiali raccolte una alla volta e completate con drawdown, stop e dieci posizioni; le risposte non approvano automaticamente la proposta tecnica.
2. SP3s Task0 documentale: proposta spec e piano con allowlist/branch/base espliciti e gate ex ante, in attesa di approvazione; nessun merge senza conferma esplicita dell’utente.
3. Nella proposta separare gate dati (universo as-of/delistati/rettifiche/prezzi in finestra) e software offline da risultati economici. Mancanze non si risolvono eliminando perdenti o riducendo soglie; restano INSUFFICIENTE.
4. Congelare famiglie, holding 1/5/21, regole/rischio/gap, scenari Best/Direct e costi stressati, IS/OOS/holdout e tutti i tentativi prima dei test economici. Il campione swing sarà storico validato, non 476 nuove sedute live; dimensione e periodi proposti nella spec restano da approvare.
5. Solo dopo approvazione di spec e piano, implementare i task autorizzati con TDD offline. Nessuna raccolta live, credenziale, ordine, paper o spesa; eventuali import di dataset richiederanno incarico esplicito e mai il DB reale nei test.

Fonti di codice: `backend/app/lab/{series,features,resample,feature_store,score_v1,strategies,simulator,harness,walk_forward,evidence,stats,trials,universe,costs}.py`, `backend/app/data_providers/{stooq,provider_registry,alpaca_market,alpha_vantage,yahoo_finance}.py`, `backend/app/intraday_research/{contracts,registry,datasets,context,quote_units,news_features,strategies}.py`. Spec/piani SP1 e SP3 e PROGRAMMA-OPERATIVO letti. Calendario ufficiale: [NYSE](https://www.nyse.com/trade/hours-calendars), orario di chiusura 16:00 New York e sedute ridotte 13:00; conversione Europe/Rome dipendente dalla data. Solo letture del repository e pagine pubbliche, nessuna chiamata agli endpoint dati.
