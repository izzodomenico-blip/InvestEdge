import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, Search, Telescope, Trash2 } from "lucide-react";

import { DataQualityBadge } from "../components/DataQualityBadge";
import { InstrumentIdentity, tradeRepublicLabels } from "../components/InstrumentIdentity";
import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { Tabs } from "../components/Tabs";
import {
  ApiError,
  activateListing,
  apiDelete,
  apiGet,
  apiPost,
  apiReasonCode,
  getInstrument,
  getInstruments,
  markListingViewed,
  type Asset,
  type AssetClass,
  type InstrumentDetail,
  type InstrumentFilters,
  type InstrumentListing,
  type InstrumentListItem,
  type InstrumentSearch,
  type QualityTier,
  type ResolutionStatus,
  type TradeRepublicStatus,
} from "../lib/api";

const assetTypes = [
  { value: "stock", label: "Azione" },
  { value: "etf", label: "ETF" },
  { value: "crypto", label: "Crypto" },
  { value: "bond", label: "Bond" },
  { value: "bond_etf", label: "ETF obbligazionario" },
];

const typeLabels: Record<string, string> = Object.fromEntries(assetTypes.map((t) => [t.value, t.label]));

export function UniversePage() {
  const [tab, setTab] = useState<"active" | "catalog">("active");
  const [assets, setAssets] = useState<Asset[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removingSymbol, setRemovingSymbol] = useState<string | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<string | null>(null);
  const [confirmSymbol, setConfirmSymbol] = useState("");
  const removalInFlight = useRef(false);

  const [symbol, setSymbol] = useState("");
  const [name, setName] = useState("");
  const [assetType, setAssetType] = useState("stock");
  const [currency, setCurrency] = useState("USD");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setAssets(await apiGet<Asset[]>("/assets"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore caricamento universe.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function addAsset() {
    if (!symbol.trim() || !name.trim()) {
      setError("Inserisci almeno simbolo e nome.");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await apiPost("/assets", {
        symbol: symbol.trim().toUpperCase(),
        name: name.trim(),
        asset_type: assetType,
        currency: currency.trim().toUpperCase() || "USD",
      });
      setMessage(`${symbol.trim().toUpperCase()} aggiunto. Aggiorna i dati dal Data Center per popolarlo.`);
      setSymbol("");
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Aggiunta non riuscita (forse esiste già).");
    } finally {
      setBusy(false);
    }
  }

  async function removeAsset(target: string) {
    if (removalInFlight.current || purgeTarget) {
      return;
    }
    removalInFlight.current = true;
    setRemovingSymbol(target);
    setError(null);
    setMessage(null);
    try {
      await apiDelete(`/assets/${encodeURIComponent(target)}`);
      setPurgeTarget(null);
      setConfirmSymbol("");
      setMessage(`${target} rimosso.`);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.message.includes("dipendenze presenti")) {
        setPurgeTarget(target);
        setConfirmSymbol("");
      }
      setError(err instanceof Error ? err.message : "Rimozione non riuscita.");
    } finally {
      removalInFlight.current = false;
      setRemovingSymbol(null);
    }
  }

  async function purgeAsset() {
    if (removalInFlight.current) {
      return;
    }
    if (!purgeTarget || confirmSymbol !== purgeTarget) {
      setError(`Digita esattamente ${purgeTarget ?? "il ticker"} per confermare.`);
      return;
    }
    removalInFlight.current = true;
    setRemovingSymbol(purgeTarget);
    setError(null);
    setMessage(null);
    try {
      await apiDelete(
        `/assets/${encodeURIComponent(purgeTarget)}?purge=true&confirm_symbol=${encodeURIComponent(confirmSymbol)}`,
      );
      setMessage(`${purgeTarget} e tutte le dipendenze collegate sono stati rimossi dopo il backup.`);
      setPurgeTarget(null);
      setConfirmSymbol("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rimozione completa non riuscita.");
    } finally {
      removalInFlight.current = false;
      setRemovingSymbol(null);
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return assets;
    return assets.filter((a) => `${a.symbol} ${a.name} ${a.asset_type}`.toLowerCase().includes(q));
  }, [assets, query]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Multi-asset / universe"
        index="02"
        title="Universe"
        subtitle="Gestisci la lista degli asset che l'app monitora e cerca nel catalogo gli strumenti da attivare esplicitamente."
        meta={<span>Asset tracciati <span className="text-cyan-300/80">{assets.length}</span></span>}
      />

      {error && <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}
      {message && <div className="rounded-2xl border border-emerald-300/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">{message}</div>}

      <Tabs
        tabs={[
          { id: "active", label: "Attivi", badge: assets.length },
          { id: "catalog", label: "Catalogo" },
        ]}
        active={tab}
        onChange={(id) => setTab(id === "catalog" ? "catalog" : "active")}
      />

      {tab === "active" && (
        <>
          {purgeTarget && (
            <Panel eyebrow="Rimozione protetta" title={`Rimuovi definitivamente ${purgeTarget}?`}>
              <p className="text-sm text-slate-300">
                Verranno rimossi l'asset e i dati collegati: storico prezzi, posizioni, ordini simulati, segnali e news.
                Il backend creerà un backup prima della cancellazione e interromperà l'operazione se il backup fallisce.
              </p>
              <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="space-y-1">
                  <span className="text-xs text-slate-400">Digita esattamente {purgeTarget} per confermare</span>
                  <input
                    value={confirmSymbol}
                    onChange={(event) => setConfirmSymbol(event.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    className="block min-h-11 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-rose-300/60 sm:w-64"
                  />
                </label>
                <button
                  onClick={() => void purgeAsset()}
                  disabled={confirmSymbol !== purgeTarget || removingSymbol === purgeTarget}
                  className="inline-flex min-h-11 items-center justify-center rounded-md border border-rose-300/30 bg-rose-400/15 px-4 py-2 text-sm font-semibold text-rose-100 transition hover:bg-rose-400/25 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {removingSymbol === purgeTarget ? "Rimozione..." : `Rimuovi ${purgeTarget} e i dati collegati`}
                </button>
                <button
                  onClick={() => {
                    setPurgeTarget(null);
                    setConfirmSymbol("");
                    setError(null);
                  }}
                  disabled={removingSymbol === purgeTarget}
                  className="inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-800 disabled:opacity-50"
                >
                  Annulla
                </button>
              </div>
            </Panel>
          )}

          <Panel eyebrow="Aggiungi" title="Nuovo asset da tracciare">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <label className="space-y-1">
                <span className="text-xs text-slate-400">Simbolo</span>
                <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="es. NVDA" className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-1 xl:col-span-2">
                <span className="text-xs text-slate-400">Nome</span>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="es. NVIDIA Corp." className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-slate-400">Tipo</span>
                <select value={assetType} onChange={(e) => setAssetType(e.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                  {assetTypes.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-xs text-slate-400">Valuta</span>
                <input value={currency} onChange={(e) => setCurrency(e.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
              </label>
            </div>
            <button onClick={() => void addAsset()} disabled={busy} className="mt-3 inline-flex items-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/15 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/25 disabled:opacity-60">
              <Plus className="h-4 w-4" aria-hidden="true" />
              {busy ? "Aggiunta..." : "Aggiungi asset"}
            </button>
          </Panel>

          <Panel
            eyebrow="Tracciati"
            title="Asset nell'universe"
            action={
              <span className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5">
                <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cerca" className="w-32 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500" />
              </span>
            }
          >
            {loading ? (
              <div className="h-32 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
            ) : (
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {filtered.map((asset) => (
                  <div key={asset.symbol} className="flex items-center justify-between rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Telescope className="h-3.5 w-3.5 text-cyan-300" aria-hidden="true" />
                        <span className="font-mono text-sm font-semibold text-white">{asset.symbol}</span>
                        <span className="rounded-md border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-400">{typeLabels[asset.asset_type] ?? asset.asset_type}</span>
                      </div>
                      <p className="mt-0.5 truncate text-xs text-slate-500">{asset.name}</p>
                    </div>
                    <button
                      onClick={() => void removeAsset(asset.symbol)}
                      disabled={removingSymbol !== null || purgeTarget !== null}
                      className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-slate-700 text-slate-400 transition hover:border-rose-300/40 hover:text-rose-200 disabled:cursor-not-allowed disabled:opacity-50"
                      aria-label={`Rimuovi ${asset.symbol}`}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                ))}
                {filtered.length === 0 && <p className="text-sm text-slate-400">Nessun asset trovato.</p>}
              </div>
            )}
          </Panel>
        </>
      )}

      {tab === "catalog" && <CatalogTab onActivated={load} />}
    </div>
  );
}

const CATALOG_PAGE_SIZE = 50;
const CATALOG_DEBOUNCE_MS = 300;

type CatalogFilterState = {
  asset_class: AssetClass | "";
  quality_tier: QualityTier | "";
  trade_republic_status: TradeRepublicStatus | "";
  currency: string;
  mic: string;
};

const emptyCatalogFilters: CatalogFilterState = {
  asset_class: "",
  quality_tier: "",
  trade_republic_status: "",
  currency: "",
  mic: "",
};

const assetClassOptions: { value: AssetClass; label: string }[] = [
  { value: "EQUITY", label: "Azioni" },
  { value: "FUND", label: "Fondi / ETF" },
  { value: "FIXED_INCOME", label: "Obbligazioni" },
  { value: "COMMODITY", label: "Materie prime" },
  { value: "CRYPTO", label: "Crypto" },
  { value: "FX", label: "Valute" },
  { value: "REFERENCE", label: "Riferimento" },
  { value: "UNKNOWN", label: "Non classificato" },
];

const qualityTierOptions: { value: QualityTier; label: string }[] = [
  { value: "QUALIFIED", label: "Qualified" },
  { value: "OBSERVABLE", label: "Observable" },
  { value: "REFERENCE_ONLY", label: "Reference only" },
];

const tradeRepublicOptions: TradeRepublicStatus[] = ["NEVER_SEEN", "CATALOGED", "VERIFIED", "UNAVAILABLE"];

const resolutionLabels: Record<ResolutionStatus, string> = {
  RESOLVED: "Risolto",
  AMBIGUOUS: "Ambiguo",
  UNMATCHED: "Non risolto",
  REJECTED: "Scartato",
};

const activationErrors: Record<string, string> = {
  LEGACY_SYMBOL_CONFLICT: "Simbolo già attivo su un altro listing: attivazione bloccata.",
  LISTING_NOT_RESOLVED: "Listing non risolto: completa prima la risoluzione.",
  AMBIGUOUS_IDENTITY: "Identità ambigua: attivazione bloccata.",
  UNSUPPORTED_INSTRUMENT_TYPE: "Tipo di strumento non supportato dall'universe.",
  UNSUPPORTED_TICKER: "Ticker non supportato dall'universe.",
  LISTING_NOT_FOUND: "Listing non trovato.",
};

function isAbort(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

function catalogRequest(query: string, filters: CatalogFilterState, offset: number): InstrumentFilters {
  const request: InstrumentFilters = {};
  if (query) request.q = query;
  if (filters.asset_class) request.asset_class = filters.asset_class;
  if (filters.quality_tier) request.quality_tier = filters.quality_tier;
  if (filters.trade_republic_status) request.trade_republic_status = filters.trade_republic_status;
  // Valuta e MIC entrano nella query solo quando sono codici completi.
  const currency = filters.currency.trim().toUpperCase();
  if (/^[A-Z]{3}$/.test(currency)) request.currency = currency;
  const mic = filters.mic.trim().toUpperCase();
  if (/^[A-Z0-9]{4}$/.test(mic)) request.mic = mic;
  request.limit = CATALOG_PAGE_SIZE;
  request.offset = offset;
  return request;
}

const fieldClass =
  "w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60";

function CatalogTab({ onActivated }: { onActivated: () => Promise<void> }) {
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<CatalogFilterState>(emptyCatalogFilters);
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<InstrumentSearch | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<InstrumentListItem | null>(null);
  const viewedListings = useRef(new Set<number>());

  useEffect(() => {
    const next = queryInput.trim();
    if (next === query) return;
    const timer = window.setTimeout(() => {
      setQuery(next);
      setOffset(0);
    }, CATALOG_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [queryInput, query]);

  // Una sola pagina per richiesta; la richiesta precedente viene abortita.
  const requestKey = JSON.stringify(catalogRequest(query, filters, offset));
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getInstruments(JSON.parse(requestKey) as InstrumentFilters, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setResult(data);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted || isAbort(err)) return;
        setResult(null);
        setError(
          err instanceof ApiError && err.status === 422
            ? "Filtri del catalogo non validi."
            : "Catalogo non disponibile. Riprova più tardi.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [requestKey]);

  function updateFilter<K extends keyof CatalogFilterState>(name: K, value: CatalogFilterState[K]) {
    setFilters((current) => ({ ...current, [name]: value }));
    setOffset(0);
  }

  function openDetail(item: InstrumentListItem) {
    setSelected(item);
    // Segnala la visualizzazione una sola volta per listing: accoda VIEWED, nessun refresh immediato.
    if (item.listing_id !== null && !viewedListings.current.has(item.listing_id)) {
      viewedListings.current.add(item.listing_id);
      void markListingViewed(item.listing_id).catch(() => undefined);
    }
  }

  const total = result?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / CATALOG_PAGE_SIZE));
  const page = Math.floor(offset / CATALOG_PAGE_SIZE) + 1;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
      <Panel
        eyebrow="Catalogo"
        title="Strumenti disponibili nel catalogo"
        action={
          result && <span className="text-xs text-slate-400">{total === 1 ? "1 strumento" : `${total} strumenti`}</span>
        }
      >
        <p className="text-xs text-slate-500">
          Il catalogo è più ampio dell'universe attivo. La presenza nel catalogo non indica che uno strumento sia negoziato oggi.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <label className="space-y-1 sm:col-span-2 xl:col-span-3">
            <span className="text-xs text-slate-400">Cerca nel catalogo</span>
            <input
              value={queryInput}
              onChange={(event) => setQueryInput(event.target.value)}
              placeholder="Nome, ticker, ISIN o FIGI"
              maxLength={100}
              className={fieldClass}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Classe</span>
            <select
              value={filters.asset_class}
              onChange={(event) => updateFilter("asset_class", event.target.value as AssetClass | "")}
              className={fieldClass}
            >
              <option value="">Tutte</option>
              {assetClassOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Tier qualità</span>
            <select
              value={filters.quality_tier}
              onChange={(event) => updateFilter("quality_tier", event.target.value as QualityTier | "")}
              className={fieldClass}
            >
              <option value="">Tutti</option>
              {qualityTierOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Stato Trade Republic</span>
            <select
              value={filters.trade_republic_status}
              onChange={(event) =>
                updateFilter("trade_republic_status", event.target.value as TradeRepublicStatus | "")
              }
              className={fieldClass}
            >
              <option value="">Tutti</option>
              {tradeRepublicOptions.map((status) => (
                <option key={status} value={status}>{tradeRepublicLabels[status]}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">Valuta listing</span>
            <input
              value={filters.currency}
              onChange={(event) => updateFilter("currency", event.target.value)}
              placeholder="es. EUR"
              maxLength={3}
              className={fieldClass}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-400">MIC</span>
            <input
              value={filters.mic}
              onChange={(event) => updateFilter("mic", event.target.value)}
              placeholder="es. XETR"
              maxLength={4}
              className={fieldClass}
            />
          </label>
        </div>

        <div className="mt-5 space-y-3">
          {loading && (
            <div role="status" className="text-sm text-slate-400">
              Caricamento catalogo…
            </div>
          )}
          {error && (
            <div role="alert" className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
              {error}
            </div>
          )}
          {result && (
            <>
              <ul aria-label="Risultati catalogo" className="space-y-2">
                {result.items.map((item) => (
                  <li
                    key={`${item.instrument_id}-${item.listing_id ?? "none"}`}
                    className="flex flex-col gap-2 rounded-xl border border-slate-800/60 bg-slate-950/55 p-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0 space-y-1">
                      <p className="truncate text-sm font-medium text-white">{item.canonical_name}</p>
                      <InstrumentIdentity
                        identifierScheme={item.primary_identifier_scheme}
                        identifier={item.primary_identifier}
                        ticker={item.ticker}
                        mic={item.mic}
                        venueName={item.venue_name}
                        currency={item.currency}
                        tradeRepublicStatus={item.trade_republic_status}
                      />
                      <DataQualityBadge
                        tier={item.quality_tier}
                        quality={item.observation_quality}
                        observedAt={item.observed_at}
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => openDetail(item)}
                      aria-label={["Apri dettaglio", item.canonical_name, item.ticker, item.mic]
                        .filter(Boolean)
                        .join(" ")}
                      className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 transition hover:border-cyan-300/40"
                    >
                      Dettaglio
                    </button>
                  </li>
                ))}
              </ul>
              {result.items.length === 0 && (
                <p className="text-sm text-slate-400">Nessuno strumento del catalogo corrisponde alla ricerca.</p>
              )}
              <nav aria-label="Paginazione catalogo" className="flex items-center justify-between gap-3">
                <button
                  type="button"
                  aria-label="Pagina precedente"
                  onClick={() => setOffset((current) => Math.max(0, current - CATALOG_PAGE_SIZE))}
                  disabled={offset === 0 || loading}
                  className="inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Precedente
                </button>
                <span className="text-xs text-slate-400">{`Pagina ${page} di ${pageCount}`}</span>
                <button
                  type="button"
                  aria-label="Pagina successiva"
                  onClick={() => setOffset((current) => current + CATALOG_PAGE_SIZE)}
                  disabled={offset + CATALOG_PAGE_SIZE >= total || loading}
                  className="inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Successiva
                </button>
              </nav>
            </>
          )}
        </div>
      </Panel>

      {selected && (
        <InstrumentDetailPanel
          key={`${selected.instrument_id}-${selected.listing_id ?? "none"}`}
          item={selected}
          onClose={() => setSelected(null)}
          onActivated={onActivated}
        />
      )}
    </div>
  );
}

function InstrumentDetailPanel({
  item,
  onClose,
  onActivated,
}: {
  item: InstrumentListItem;
  onClose: () => void;
  onActivated: () => Promise<void>;
}) {
  const [detail, setDetail] = useState<InstrumentDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activating, setActivating] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getInstrument(item.instrument_id, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setDetail(data);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted || isAbort(err)) return;
        setLoadError("Dettaglio non disponibile. Riprova più tardi.");
      });
    return () => controller.abort();
  }, [item.instrument_id]);

  async function activate(listing: InstrumentListing) {
    setActivating(listing.listing_id);
    setMessage(null);
    setActionError(null);
    try {
      const asset = await activateListing(listing.listing_id);
      setMessage(`${asset.symbol} attivato nell'universe.`);
      await onActivated();
    } catch (err) {
      const reason = apiReasonCode(err);
      setActionError(
        (reason && activationErrors[reason]) ||
          (err instanceof Error ? err.message : "Attivazione non riuscita."),
      );
    } finally {
      setActivating(null);
    }
  }

  const identityAmbiguous = detail?.quality_reasons.includes("AMBIGUOUS_IDENTITY") ?? false;

  return (
    <section aria-label={`Dettaglio ${item.canonical_name}`}>
      <Panel
        eyebrow="Dettaglio"
        title={item.canonical_name}
        action={
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-11 items-center justify-center rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800"
          >
            Chiudi dettaglio
          </button>
        }
      >
        {loadError && (
          <div role="alert" className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
            {loadError}
          </div>
        )}
        {!detail && !loadError && <p className="text-sm text-slate-400">Caricamento dettaglio…</p>}
        {detail && (
          <div className="space-y-5">
            <DataQualityBadge tier={detail.quality_tier} quality={detail.observation_quality} observedAt={detail.observed_at} />
            <div>
              <p className="eyebrow-muted">Identificativi</p>
              <ul aria-label="Identificativi" className="mt-2 space-y-1 text-xs">
                {detail.identifiers.map((identifier) => (
                  <li key={`${identifier.scheme}-${identifier.value}`} className="flex flex-wrap gap-2 text-slate-400">
                    <span className="text-slate-500">{identifier.scheme}</span>
                    <span className="font-mono text-slate-200">{identifier.value}</span>
                    <span>fonti: {identifier.sources.join(", ")}</span>
                  </li>
                ))}
                {detail.identifiers.length === 0 && <li className="text-slate-500">Nessun identificativo attestato.</li>}
              </ul>
            </div>
            <div>
              <p className="eyebrow-muted">Listing</p>
              <ul aria-label="Listing" className="mt-2 space-y-2">
                {detail.listings.map((listing) => {
                  const ambiguous = identityAmbiguous || listing.resolution_status === "AMBIGUOUS";
                  const activatable = !ambiguous && listing.resolution_status === "RESOLVED";
                  const venue = listing.mic ?? listing.venue_name;
                  const activationLabel = venue ? `Attiva ${listing.ticker} su ${venue}` : `Attiva ${listing.ticker}`;
                  return (
                    <li key={listing.listing_id} className="space-y-2 rounded-xl border border-slate-800/60 p-3 text-xs text-slate-400">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono font-semibold text-white">{listing.ticker}</span>
                        {listing.mic && <span className="font-mono text-slate-300">{listing.mic}</span>}
                        {listing.venue_name && <span>{listing.venue_name}</span>}
                        <span className="font-mono text-slate-300">{listing.currency}</span>
                        <span>{resolutionLabels[listing.resolution_status]}</span>
                        <span>{tradeRepublicLabels[listing.trade_republic_status]}</span>
                      </div>
                      {activatable ? (
                        <button
                          type="button"
                          onClick={() => void activate(listing)}
                          disabled={activating !== null}
                          className="inline-flex min-h-11 items-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/15 px-3 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/25 disabled:opacity-60"
                        >
                          <Plus className="h-4 w-4" aria-hidden="true" />
                          {activating === listing.listing_id ? "Attivazione..." : activationLabel}
                        </button>
                      ) : (
                        <p className="text-amber-200/80">
                          {ambiguous ? "Mapping ambiguo: non attivabile" : "Listing non risolto: non attivabile"}
                        </p>
                      )}
                    </li>
                  );
                })}
                {detail.listings.length === 0 && <li className="text-xs text-slate-500">Nessun listing risolto.</li>}
              </ul>
            </div>
            {message && (
              <p role="status" className="text-sm text-emerald-200">
                {message}
              </p>
            )}
            {actionError && (
              <div role="alert" className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
                {actionError}
              </div>
            )}
          </div>
        )}
      </Panel>
    </section>
  );
}
