# SP3s — gate documentale di fattibilità dati

Data: **2026-10-19**, Europe/Rome. Owner/writer: Codex. Branch: `investedge/sp3s-task-3`. Base pubblicata: `24907e5619c9afb489e13f9dfd160b3cb41e743e`, checkpoint delle approvazioni custode/beta dopo il software Task2 `222d60f13877d7a02681d9788e91a6318bdf9733`.

**G_SWING_FEAS: INSUFFICIENTE. Task3: BLOCCATO per prove dati mancanti. Task4–9: non avviabili.** La valutazione documentale richiesta è prodotta; il gate non è superato e il task non è FATTO. Mancano un pacchetto locale idoneo dichiarato/fornito per questo incarico, le relative prove di copertura/diritti/risorse e l’attestazione strutturale del custode. Non sono osservate qui provenienze incompatibili: non si attribuisce NON_IDONEO per la sola assenza di prove.

Fonti normative del progetto: [spec SP3s §3.2–3.5/§8/§9.2.1](../superpowers/specs/2026-10-15-investedge-sp3s-swing-research-design.md), [piano Task3](../superpowers/plans/2026-10-15-investedge-sp3s-swing-research.md), [programma operativo](../../PROGRAMMA-OPERATIVO.md), [inventario SP1/fonti](2026-10-15-swing-sp1-inventory.md). Le decisioni custode utente e beta IS congelato sono già approvate e non sono riaperte da questo rapporto.

## 1. Perimetro e prove ammesse

Letture: documenti versionati del progetto e documentazione pubblica primaria elencata sotto. Nessun import dell’app, chiamata a endpoint dati, export/download di serie, script di verifica del pacchetto, ricerca nelle directory dati, accesso a DB reale o holdout. Nessun account, credenziale, raccolta live, ordine, paper o spesa. Il confronto con le pagine pubbliche è ricerca documentale, non raccolta di mercato.

Non è stato fornito o identificato dall’utente un pacchetto da sottoporre a questo gate. Non si afferma che non esistano dati altrove sul suo computer: non sono stati cercati. Non si aprono i dati applicativi per colmare l’assenza. Nessun allegato/manifesto/attestazione dati REAL è stato consegnato con questo incarico; i riferimenti opachi dei test restano sintetici.

| Evidenza disponibile | Cosa dimostra | Cosa non dimostra |
|---|---|---|
| Spec/piano approvati, checkpoint custode/beta 24907e5 | Requisiti e metodo congelati ex ante | Presenza, qualità o gratuità di un pacchetto completo |
| Software Task1/2 pubblicato e prove storiche 175 mirati/2728 backend | Contratti, reader e domini verificati su fixture offline | Universo REAL completo, licenza, vintage o copertura del campione |
| Calendario documentale §9.1, hash `501470b59401bebd0a4613ef48e4b6ec839cc727a4856db0dc54321bb522c9bb` | Riferimento progettuale di date/conteggi | Calendario e hash del pacchetto fornito o misure di disponibilità |
| Pagine primarie consultate il 2026-10-19 | Capacità/limiti documentali delle fonti candidate | Accesso effettivo di un conto, esito di API o diritto di conservare gli input |
| Protocollo custode §3.5 approvato | Ruolo dell’utente e output aggregato/opaco consentito | Attestazione già prodotta, verificatore già idoneo o apertura del holdout |

Le quantità non misurate sono **ND (non dimostrate)**, non zero e non percentuali inventate. Assenza della prova non prova assenza di scambi, completezza o incompatibilità della fonte.

## 2. Fonti candidate: riscontri documentali attuali

**Alpaca Basic — candidato prezzi daily/minuti, non pacchetto dimostrato.** La pagina piani indica Basic gratuito, storico azionario dal 2016 e limitazione degli ultimi 15 minuti; realtime Basic riguarda IEX. Questo supporta la candidatura, non una verifica sul conto dell’utente o dei dati esportati. Il costo totale del pacchetto resta ND. [Piani ufficiali](https://docs.alpaca.markets/us/docs/about-market-data-api).

La FAQ ammette storico SIP senza abbonamento con termine della query arretrato almeno 15 minuti, distinguendolo da IEX. Indica inoltre un accesso OTC speciale per broker partner: non è dimostrata la copertura gratuita dei prezzi dopo delisting. Questo non rende indisponibile ogni titolo delistato; impedisce di presumere coperti tutti i recuperi. [FAQ ufficiale](https://docs.alpaca.markets/us/docs/market-data-faq).

Il riferimento barre supporta aggregazioni daily/minuto e rettifiche distinte; `asof` serve al mapping dei rename. **Inferenza di fattibilità:** ciò non attesta un universo storico, archivio delle revisioni o disponibilità conosciuta allora. Occorreranno fonte/feed espliciti, raw e identità proprie del pacchetto. Le pagine non vanno usate per inferire un feed dal default: il parametro e la ricevuta devono identificarlo. [Barre storiche](https://docs.alpaca.markets/us/reference/stockbars).

Il riferimento corporate action avverte di possibili ritardi e assenza di garanzia sul momento di creazione/disponibilità. Il filtro di qualità può escludere record incompleti: il nome del filtro non certifica la completezza economica dell’archivio. Occorrono anche stato e lacune, senza trasformare una risposta corrente in prova STRICT_PIT. [Corporate action](https://docs.alpaca.markets/us/reference/corporateactions-1).

**SEC EDGAR — riscontro documentale per attributi, non catalogo completo già ricostruito.** La documentazione descrive filing per emittente e metadati correnti/storici dei nomi. In questo incarico non si leggono filing o API. L’uso eventuale per domicilio, classe, identità e operazioni resta da provare per ogni intervallo rilevante; un identificatore emittente non sostituisce da solo classe/listing e membership as-of. [Documentazione EDGAR](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

**Calendario e settlement.** NYSE documenta seduta regolare e chiusure anticipate, ma la pagina corrente non fornisce qui un pacchetto storico verificato 2016–2026. Servono calendario applicabile e date esplicite. [NYSE](https://www.nyse.com/trade/hours-calendars). Per la maggior parte delle transazioni standard USA, le fonti SEC documentano il passaggio T+3→T+2 dal 2017-09-05 e T+2→T+1 dal 2024-05-28. Non si deve retrodatare T+1 all’intero campione, né trasferire automaticamente il regime USA a una sede TR diversa; l’applicabilità è parte della prova richiesta. [SEC T+2](https://www.sec.gov/newsroom/press-releases/2017-68-0), [SEC T+1](https://www.sec.gov/newsroom/press-releases/2023-29).

**BCE — candidata FX informativo.** I cambi di riferimento sono informativi, non prezzi eseguibili. Per la proxy servono serie locale, unità/inversione e disponibilità al cutoff; per TR servono le condizioni applicabili alla conversione effettiva. Nessun fixing o serie è scaricato o utilizzato nel gate. [BCE](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).

**Trade Republic — condizioni applicabili non fornite.** La Execution Policy pubblica tratta il cambio nella determinazione del prezzo; non dimostra il costo marginale, venue/valuta o supporto stop per il conto italiano e ciascun titolo/modalità. Le regole BASE/STRESS/SEVERE e FX condizionato §7.2 restano assunzioni approvate, senza nuova tariffa o misurazione. Nessun accesso/app/scraping o automazione TR. [Execution Policy 07/2026](https://assets.traderepublic.com/assets/files/EN_ExecutionPolicy.pdf).

**Stooq.** La base UNKNOWN registrata in SP1 resta UNKNOWN: non è prova di raw/total return o corporate action complete. Nessuna rivalutazione del provider o download in questo incarico. La regola della spec e l’inventario esistente sono le fonti locali, non una nuova attestazione Stooq.

## 3. Matrice di fattibilità per l’intero campione

L’esito di ciascuna riga è **INSUFFICIENTE**. Le fonti della sezione precedente sono candidate o riscontri di regole; nessuna sostituisce gli input locali/prove richiesti. I codici FEAS sotto sono etichette del rapporto, non nuovi enum software.

| ID / area | Requisito congelato e prova necessaria | Evidenza effettiva / lacuna attuale | Esito / codice |
|---|---|---|---|
| FEAS01 — Calendario e regolamento | Sedute 2016–2026-09-30, open/close UTC/NY, DST/Rome, half-day/chiusure straordinarie, giorni e regime settlement per data/venue; versione/hash del pacchetto | Solo riferimenti progettuali/pubblici; calendario locale, denominatori e regime applicabile non forniti | INSUFFICIENTE — CALENDAR_SETTLEMENT_PROOF_MISSING |
| FEAS02 — Universo e identità | Catena emittente/classe/listing, ticker valid_from/to, IPO/delisting, venue/valuta primaria e membership mensile as-of, inclusi titoli poi delistati; inventario inclusioni/esclusioni e relative ragioni | Nessun catalogo storico o catena dati forniti. Liste attuali TR/Alpaca/indici non sostitutive; nessun join su ticker riutilizzato | INSUFFICIENTE — ASOF_IDENTITY_MEMBERSHIP_MISSING |
| FEAS03 — Classificazione/domicilio | Common stock di emittenti USA con domicilio storico documentato e intervalli, classi escluse identificate, anche inattivi; valuta/venue non equivalgono a domicilio | Fonte primaria per singoli attributi candidata, anagrafica completa non dimostrata; i casi ignoti non si scartano per migliorare il campione | INSUFFICIENTE — HISTORICAL_CLASS_DOMICILE_MISSING |
| FEAS04 — Daily raw/liquidità | OHLCV/feed/USD, grain/versioni/tempi, raw e azioni societarie; precedente prezzo ≥5 USD, warm-up 252, ADV20 ≥20 milioni, top 500 con tie stabile, ≥100 eleggibili/mese e ≥99% daily attese | Nessuna partizione daily, hash/count o denominatore verificabile; UNKNOWN Stooq non sana la prova; copertura ND | INSUFFICIENTE — RAW_DAILY_COVERAGE_UNATTESTED |
| FEAS05 — Minuti/stop/halt | Prezzo SIP entro 5m dal cutoff C−55, dati disponibili a C−40, finestra C−55…C−10 e tutte le ore RTH delle posizioni potenziali, volumi, gap overnight e halt/reopen; distinguere missing da no-trades | Disponibilità teorica del prodotto documentata, nessuna partizione/stato storico o copertura locale; daily finale non è prezzo prima del close né fill | INSUFFICIENTE — MINUTE_HALT_COVERAGE_UNATTESTED |
| FEAS06 — Corporate action/uscite | Split/rename/spin-off/merger, termini cash/azioni e valuta, ex/pay-date, disponibilità/versioni; recuperi/prezzi terminali osservabili anche oltre il listing principale | Nessun archivio eventi/termini/recuperi e riconciliazione dei casi forniti; nessun prezzo terminale inventato a zero/ultima chiusura/−100%; OTC gratuito completo non dimostrato | INSUFFICIENTE — ACTION_TERMINAL_RECOVERY_MISSING |
| FEAS07 — FX/benchmark | Serie EUR per USD disponibile al cutoff, staleness≤7 giorni; universo EW mensile total return USD as-of/delistati e hash; unità/azioni terminali; successivi snapshot beta IS secondo §9.2.1 | Metodo beta approvato, input FX/benchmark locali non forniti; nessun beta stimato ora. Fonte informativa non è conversione TR eseguibile | INSUFFICIENTE — FX_BENCHMARK_INPUTS_MISSING |
| FEAS08 — Costi/trasferibilità TR | Best/Direct distinti, condizioni/versioni applicabili al conto, venue e valuta di prezzo/regolamento, fee/FX ordini e proventi, supporto/trigger/validità/orari stop per titolo/modalità, diritti e costi ricorrenti | Solo modello e policy pubblica, nessuna attestazione applicabile per titolo/modalità; SIP USA non attesta prezzi o stop TR. Zero extra FX resta condizionato all’assenza di conversione di cassa | INSUFFICIENTE — TR_TERMS_SUPPORT_UNATTESTED |
| FEAS09 — Conservazione/holdout/diritti | Manifesto immutabile/versionato, hash/count e grain per partizione, origine/licenza/diritti espliciti, budget disco attestato, batch 10.000/8 MiB e RAM 2 GiB; attestazione strutturale custode §3.5 | Nessun pacchetto/licenza/dimensionamento o attestazione prodotto; custode utente approvato, strumento idoneo non fornito/verificato; nessun dato holdout aperto | INSUFFICIENTE — PACKET_RIGHTS_RESOURCES_CUSTODY_MISSING |

Tutte le celle necessarie devono essere dimostrate. Il 99% non autorizza a ignorare il residuo se incide su decisione/posizione. Non si eliminano delistati, perdenti o classificazioni ignote dai denominatori e non si restringe il campione alle sole strategie già simulate. Disponibilità modellata, storico corrente e capture sono qualità distinte: etichetta REAL e hash coerenti non attestano STRICT_PIT, autenticità del publisher o completezza.

## 4. Quantità, diritti, costi e risorse: stato osservabile

| Quantità/prova | Riferimento richiesto | Osservato nel pacchetto |
|---|---|---|
| Finestra complessiva | 2016-01-04–2026-09-30; warm-up/fondazione 2016 | ND: nessun pacchetto fornito |
| IS iniziale / vero OOS | 2017-01-03–2019-12-31 / 2020-01-02–2023-12-29; OOS minimo 1.000 sedute | ND; 1006 è riferimento documentale §9.1, non misura del pacchetto |
| Holdout sealed | 2024-01-02–2026-09-30, minimo 630 sedute | ND; 689 è riferimento documentale §9.1. Nessun contenuto, path o membership richiesto/letto |
| Daily/minuti/eventi/identità/FX/benchmark | Conteggi attesi/osservati e lacune per requisito, grain, hash/versioni | Tutti ND; nessuna percentuale di copertura calcolabile |
| Universo mensile | ADV20/prezzo/warm-up/top 500, minimo 100 e copertura99% con denominatori completi | ND: nessuna membership storica o anagrafica fornita |
| Diritti | Fonte/versione e diritto applicabile a conservazione, export, ricerca e attestazione, senza segreti | ND: nessuna licenza/prova applicabile fornita; offerta gratuita non equivale a diritto dimostrato |
| Dati: costo totale e ricorrenze | Tutte le fonti necessarie a universo/eventi/recuperi/prezzi, non il solo prodotto daily | ND: Basic gratuito documentato non dimostra che l’intero pacchetto sia gratuito/idoneo |
| TR | Modalità/venue/valuta, costi ordini/proventi e stop documentati | ND per applicabilità concreta; assunzioni §7/§7.2 invariate |
| Disco | Byte/input/partizioni, inclusi byte holdout solo attestati dal custode, capacità/riserva sufficiente e nessuna retention distruttiva | ND; nessuna quota disco completa attestata |
| Memoria/streaming | RAM massimo 2 GiB; batch massimo 10.000 righe o 8 MiB decodificati, più restrittivo | Solo prove software sintetiche storiche Task2; nessuna misura o attestazione sul pacchetto REAL |

Il modello di costi/versioni, la scelta beta b e le soglie restano congelati. Non si modifica fee, ritardo, fonte, universo o cap per superare il gate. Nessuna spesa autorizzata in questo incarico; se servissero dati a pagamento, il costo e la decisione dell’utente sarebbero separati, senza attivazione automatica. Questo rapporto non raccomanda un acquisto e non certifica un’offerta completa gratuita o a pagamento.

## 5. Custodia e attestazione: protocollo approvato, prova non fornita

Custode umano: **utente**, secondo §3.5. La futura esecuzione personale offline avviene fuori dall’ambiente degli agenti su copia immutabile. L’unico output condivisibile è l’attestazione strutturale: versione/hash verificatore e pacchetto, intervallo, conteggi aggregati attesi/osservati e copertura/lacune per requisito, codici di insufficienza, prove non rivelatrici di fonte/diritti/risorse e conferma del digest.

Vietati in output, log ed errori: path o nomi rivelatori, identità/membership del holdout, OHLCV/prezzi, rendimenti, corrispettivi/cash flow, feature/segnali, trade, equity, Sharpe e risultati delle strategie. Le prove analitiche restano presso il custode. Il controllo strutturale non è apertura economica SEALED→OPENING e non autorizza training, diagnostico H=1 o selezione sul holdout. Nessun accesso neppure esplorativo in Task3.

**Attestazione ricevuta: NON FORNITA. Verificatore idoneo/versione/hash: NON FORNITI/VERIFICATI.** Non si genera una ricevuta fittizia, non si sostituisce con fixture o autodichiarazione generica. Se manca uno strumento idoneo, la sua eventuale realizzazione richiede prima proposta software separata, allowlist, incarico e TDD offline: non è codice da scrivere/eseguire dentro questo task documentale. Anche un’attestazione idonea non sostituisce tutti gli altri requisiti della matrice né la validazione dati finale.

## 6. Verdetto, blocchi e ripresa

**G_SWING_FEAS = INSUFFICIENTE**, per FEAS01–FEAS09 non dimostrati. **Task3 = BLOCCATO** dopo la pubblicazione del rapporto; Task4–9 non partono, Task10 non è autorizzato. G_SWING_DATA REAL / G_SWING_RESEARCH / G_TR_TRANSFER restano NON VALUTATI: non sono gate economici falliti e non è un’affermazione di impossibilità futura o redditività delle famiglie.

Le due decisioni metodologiche sono chiuse: custode utente e beta OLS con intercetta sulle sole 504 IS, congelato prima dei blocchi OOS e dell’intero holdout, conservato per posizione dall’ingresso; FX separato, beta 1 diagnostico, N14 invariato. Non si stima beta o si provano strategie qui. Limiti del benchmark, dipendenza/bootstrap e selezione finale M3 restano quelli approvati.

Per riesaminare il gate servono, nell’ordine:

1. **Proposta concreta di pacchetto/fonti e diritti**, con inventario storico as-of/delistati/domicilio e copertura dei recuperi; indicare esattamente cosa manca. Nessun token o segreto e nessun catalogo corrente usato come sostituto.
2. **Prove/pacchetto delle sole porzioni non holdout**, con manifesto e hash/count/denominatori/tempi/versioni di tutte le aree della matrice. Una successiva verifica dei contenuti userà soltanto dati non holdout esplicitamente forniti/individuati dall’utente per il gate; questo rapporto non l’ha eseguita e non estende il permesso a DB reale o holdout.
3. **Attestazione strutturale del custode** conforme a §3.5 e strumento idoneo verificabile, con output aggregato/opaco. Non consegnare dati, path o membership holdout agli agenti. Se lo strumento manca, presentare prima la proposta software distinta prevista.
4. **Dimensionamento e condizioni applicabili**, con byte/quote disco/RAM/diritti/costi ricorrenti e prove TR Best/Direct su valuta/conversioni/supporto stop. Eventuale costo o variazione di requisiti necessita decisione separata; nessun acquisto, raccolta o riduzione di soglie impliciti.

Solo dopo prove adeguate e riesame esplicito può cambiare il verdetto. Il gate non si sblocca implementando le strategie in anticipo, comprando dati senza incarico o reinterpretando la stessa documentazione come copertura osservata.

## 7. Review e verifica della consegna documentale

Review root conclusa senza rilievi bloccanti del rapporto; le nove insufficienze dati restano esplicite e aperte. Controlli documentali freschi `verify_documents.py --final`: **86/86 PASS**, 21 link locali validi, scanner dei tre Markdown con otto self-test e zero candidati inattesi; scope/diff, spec identica alla base, checklist coerente con BLOCCATO e task successivi non avviati. Nessuna verifica di dati REAL o esecuzione economica. Prove e ricevuta esterna in `sp3s-task3-verification`; pubblicazione/SHA remoto verificati dopo il commit.

Scope esatto: questo nuovo rapporto, stato/checklist in piano SP3s e `PROGRAMMA-OPERATIVO.md`. Spec approvata, codice, dipendenze, input e risultati precedenti invariati. Nessuna suite backend/frontend, Ruff o pip rieseguiti perché non ci sono cambi software; i conteggi Task2 citati sono storici. Il controllo documentale PASS non cambia G_SWING_FEAS INSUFFICIENTE.

Commit previsto: `docs: gate swing data feasibility before strategy implementation`. Push solo branch Task3 e gate SHA remoto dopo commit, nessun merge; il proprio SHA vive nella ricevuta esterna o nel passo successivo, non in questo documento.
