import { useEffect, useMemo, useState } from "react";
import { Plus, Search, Telescope, Trash2 } from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { apiDelete, apiGet, apiPost, type Asset } from "../lib/api";

const assetTypes = [
  { value: "stock", label: "Azione" },
  { value: "etf", label: "ETF" },
  { value: "crypto", label: "Crypto" },
  { value: "bond", label: "Bond" },
  { value: "bond_etf", label: "ETF obbligazionario" },
];

const typeLabels: Record<string, string> = Object.fromEntries(assetTypes.map((t) => [t.value, t.label]));

export function UniversePage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    setError(null);
    setMessage(null);
    try {
      await apiDelete(`/assets/${target}`);
      setMessage(`${target} rimosso.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rimozione non riuscita.");
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
        subtitle="Gestisci la lista degli asset che l'app monitora. Aggiungi i ticker che ti interessano e rimuovi quelli che non segui."
        meta={<span>Asset tracciati <span className="text-cyan-300/80">{assets.length}</span></span>}
      />

      {error && <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}
      {message && <div className="rounded-2xl border border-emerald-300/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">{message}</div>}

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
                <button onClick={() => void removeAsset(asset.symbol)} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-slate-700 text-slate-400 transition hover:border-rose-300/40 hover:text-rose-200" aria-label={`Rimuovi ${asset.symbol}`}>
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            ))}
            {filtered.length === 0 && <p className="text-sm text-slate-400">Nessun asset trovato.</p>}
          </div>
        )}
      </Panel>
    </div>
  );
}
