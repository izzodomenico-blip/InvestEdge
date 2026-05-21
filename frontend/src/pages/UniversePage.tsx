import { useEffect, useMemo, useState } from "react";
import { DatabaseZap, Filter, RefreshCw, Star, Upload } from "lucide-react";

import { MetricCard } from "../components/MetricCard";
import { Panel } from "../components/Panel";
import {
  apiDelete,
  apiGet,
  apiPost,
  type DataRefreshResult,
  type UniverseAsset,
  type UniverseImportResult,
  type UniverseLevel,
  type UniverseSummary,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const levelTone: Record<UniverseLevel, string> = {
  CORE: "border-cyan-300/25 bg-cyan-400/10 text-cyan-100",
  EXTENDED: "border-emerald-300/25 bg-emerald-400/10 text-emerald-100",
  CANDIDATE: "border-slate-700 bg-slate-900 text-slate-300",
};

const csvOptions = ["core_universe.csv", "extended_universe.csv", "crypto_universe.csv", "etf_universe.csv"];

function buildUniversePath(filters: {
  level: UniverseLevel | "ALL";
  assetType: string;
  activeOnly: boolean;
  limit: string;
}) {
  const params = new URLSearchParams();
  if (filters.level !== "ALL") {
    params.set("level", filters.level);
  }
  if (filters.assetType !== "ALL") {
    params.set("asset_type", filters.assetType);
  }
  params.set("active_only", String(filters.activeOnly));
  if (filters.limit) {
    params.set("limit", filters.limit);
  }
  return `/universe?${params.toString()}`;
}

export function UniversePage() {
  const [summary, setSummary] = useState<UniverseSummary | null>(null);
  const [assets, setAssets] = useState<UniverseAsset[]>([]);
  const [refreshCandidates, setRefreshCandidates] = useState<UniverseAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    level: "ALL" as UniverseLevel | "ALL",
    assetType: "ALL",
    activeOnly: true,
    limit: "300",
    query: "",
  });
  const [importForm, setImportForm] = useState<{ file_name: string; universe_level: UniverseLevel }>({
    file_name: "core_universe.csv",
    universe_level: "CORE",
  });

  async function loadUniverse() {
    setLoading(true);
    setError(null);
    try {
      const [summaryResponse, assetResponse, candidateResponse] = await Promise.all([
        apiGet<UniverseSummary>("/universe/summary"),
        apiGet<UniverseAsset[]>(buildUniversePath(filters)),
        apiGet<UniverseAsset[]>("/universe/refresh-candidates?limit=10"),
      ]);
      setSummary(summaryResponse);
      setAssets(assetResponse);
      setRefreshCandidates(candidateResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento universe.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadUniverse();
  }, [filters.level, filters.assetType, filters.activeOnly, filters.limit]);

  const filteredAssets = useMemo(() => {
    const query = filters.query.trim().toLowerCase();
    if (!query) {
      return assets;
    }
    return assets.filter((asset) =>
      [asset.symbol, asset.name, asset.asset_type, asset.sector, asset.country, asset.exchange]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [assets, filters.query]);

  async function runAction(label: string, action: () => Promise<void>) {
    setActionLoading(label);
    setError(null);
    setMessage(null);
    try {
      await action();
      await loadUniverse();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Operazione universe non riuscita.");
    } finally {
      setActionLoading(null);
    }
  }

  async function toggleWatchlist(asset: UniverseAsset) {
    await runAction(`${asset.symbol}-watchlist`, async () => {
      if (asset.is_watchlisted) {
        await apiDelete<UniverseAsset>(`/universe/${asset.symbol}/watchlist`);
        setMessage(`${asset.symbol} rimosso dalla watchlist.`);
      } else {
        await apiPost<UniverseAsset>(`/universe/${asset.symbol}/watchlist`);
        setMessage(`${asset.symbol} aggiunto alla watchlist.`);
      }
    });
  }

  async function promote(asset: UniverseAsset, level: UniverseLevel) {
    await runAction(`${asset.symbol}-promote`, async () => {
      await apiPost<UniverseAsset>(`/universe/${asset.symbol}/promote`, { universe_level: level });
      setMessage(`${asset.symbol} aggiornato a ${level}.`);
    });
  }

  async function refreshAsset(asset: UniverseAsset) {
    await runAction(`${asset.symbol}-refresh`, async () => {
      const result = await apiPost<DataRefreshResult>(`/data/refresh/${asset.symbol}`);
      setMessage(`${asset.symbol}: ${result.message}`);
    });
  }

  async function importUniverse() {
    await runAction("import", async () => {
      const result = await apiPost<UniverseImportResult>("/universe/import", importForm);
      setMessage(`${result.file_name}: ${result.inserted} inseriti, ${result.updated} aggiornati, ${result.skipped} saltati.`);
    });
  }

  if (loading) {
    return (
      <Panel title="Universe">
        <div className="h-56 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">Universe Manager</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Universe / Screener</h1>
        </div>
        <button
          onClick={() => void loadUniverse()}
          className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20"
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Aggiorna
        </button>
      </header>

      {error && <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 p-4 text-sm text-rose-200">{error}</div>}
      {message && <div className="rounded-lg border border-cyan-300/20 bg-cyan-400/10 p-4 text-sm text-cyan-100">{message}</div>}

      {summary && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Universe totale" value={`${summary.total_assets}`} delta={`${summary.priced_assets_count} con storico`} tone="cyan" icon={DatabaseZap} />
          <MetricCard label="Core" value={`${summary.core_count}`} delta="Default ML" tone="green" icon={Star} />
          <MetricCard label="Extended" value={`${summary.extended_count}`} delta="Aggiornamento meno frequente" tone="cyan" icon={Filter} />
          <MetricCard label="Candidate" value={`${summary.candidate_count}`} delta={`${summary.refresh_candidates_count} candidati refresh`} tone="amber" icon={RefreshCw} />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <Panel title="Filtri">
          <div className="grid gap-4 md:grid-cols-5">
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Livello</span>
              <select
                value={filters.level}
                onChange={(event) => setFilters((current) => ({ ...current, level: event.target.value as UniverseLevel | "ALL" }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              >
                <option value="ALL">Tutti</option>
                <option value="CORE">Core</option>
                <option value="EXTENDED">Extended</option>
                <option value="CANDIDATE">Candidate</option>
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Asset type</span>
              <select
                value={filters.assetType}
                onChange={(event) => setFilters((current) => ({ ...current, assetType: event.target.value }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              >
                <option value="ALL">Tutti</option>
                {Object.keys(summary?.by_asset_type ?? {}).map((assetType) => (
                  <option key={assetType} value={assetType}>
                    {assetType}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Limite</span>
              <input
                type="number"
                min="1"
                max="1000"
                value={filters.limit}
                onChange={(event) => setFilters((current) => ({ ...current, limit: event.target.value }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={filters.activeOnly}
                onChange={(event) => setFilters((current) => ({ ...current, activeOnly: event.target.checked }))}
                className="h-4 w-4 accent-cyan-300"
              />
              Attivi
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Cerca</span>
              <input
                value={filters.query}
                onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
                placeholder="Ticker, settore, paese"
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none placeholder:text-slate-500 focus:border-cyan-300/60"
              />
            </label>
          </div>
        </Panel>

        <Panel title="Import CSV">
          <div className="grid gap-3 sm:grid-cols-[1fr_0.8fr_auto]">
            <select
              value={importForm.file_name}
              onChange={(event) => setImportForm((current) => ({ ...current, file_name: event.target.value }))}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
            >
              {csvOptions.map((fileName) => (
                <option key={fileName} value={fileName}>
                  {fileName}
                </option>
              ))}
            </select>
            <select
              value={importForm.universe_level}
              onChange={(event) => setImportForm((current) => ({ ...current, universe_level: event.target.value as UniverseLevel }))}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
            >
              <option value="CORE">CORE</option>
              <option value="EXTENDED">EXTENDED</option>
              <option value="CANDIDATE">CANDIDATE</option>
            </select>
            <button
              onClick={() => void importUniverse()}
              disabled={actionLoading === "import"}
              className="inline-flex items-center justify-center gap-2 rounded-md border border-emerald-300/30 bg-emerald-400/10 px-3 py-2 text-sm font-semibold text-emerald-100 disabled:opacity-60"
            >
              <Upload className="h-4 w-4" aria-hidden="true" />
              Import
            </button>
          </div>
        </Panel>
      </div>

      <Panel title="Refresh candidates">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {refreshCandidates.map((asset) => (
            <article key={asset.symbol} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold text-white">{asset.symbol}</p>
                <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${levelTone[asset.universe_level]}`}>{asset.universe_level}</span>
              </div>
              <p className="mt-2 text-xs text-slate-500">Priority {asset.refresh_priority} · freq {asset.refresh_frequency_days}d</p>
              <p className="mt-2 text-xs text-slate-500">{asset.last_price_refresh_at ?? "Mai aggiornato"}</p>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Asset universe">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1500px] border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                <th className="px-3 pb-3 pl-0 font-medium">Asset</th>
                <th className="px-3 pb-3 font-medium">Level</th>
                <th className="px-3 pb-3 font-medium">Type</th>
                <th className="px-3 pb-3 font-medium">Settore</th>
                <th className="px-3 pb-3 font-medium">Paese</th>
                <th className="px-3 pb-3 font-medium">Exchange</th>
                <th className="px-3 pb-3 text-right font-medium">Prezzo</th>
                <th className="px-3 pb-3 text-right font-medium">Giorno</th>
                <th className="px-3 pb-3 font-medium">Watch</th>
                <th className="px-3 pb-3 text-right font-medium">Priority</th>
                <th className="px-3 pb-3 font-medium">Provider</th>
                <th className="px-3 pb-3 pr-0 text-right font-medium">Azioni</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filteredAssets.map((asset) => (
                <tr key={asset.symbol} className="align-top text-sm">
                  <td className="px-3 py-4 pl-0">
                    <p className="font-semibold text-white">{asset.symbol}</p>
                    <p className="mt-1 max-w-56 truncate text-slate-500" title={asset.name}>{asset.name}</p>
                  </td>
                  <td className="px-3 py-4">
                    <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${levelTone[asset.universe_level]}`}>{asset.universe_level}</span>
                  </td>
                  <td className="px-3 py-4 text-slate-300">{asset.asset_type}</td>
                  <td className="px-3 py-4 text-slate-400">{asset.sector ?? "-"}</td>
                  <td className="px-3 py-4 text-slate-400">{asset.country ?? "-"}</td>
                  <td className="px-3 py-4 text-slate-400">{asset.exchange ?? "-"}</td>
                  <td className="px-3 py-4 text-right font-medium text-white">{asset.last_price == null ? "N/D" : formatCurrency(asset.last_price, asset.currency)}</td>
                  <td className={`px-3 py-4 text-right font-semibold ${(asset.daily_change_pct ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {asset.daily_change_pct == null ? "N/D" : formatPercent(asset.daily_change_pct)}
                  </td>
                  <td className="px-3 py-4">
                    <span className={asset.is_watchlisted || asset.is_portfolio_asset ? "text-emerald-300" : "text-slate-500"}>
                      {asset.is_portfolio_asset ? "Portfolio" : asset.is_watchlisted ? "Watchlist" : "-"}
                    </span>
                  </td>
                  <td className="px-3 py-4 text-right text-cyan-200">{asset.refresh_priority}</td>
                  <td className="px-3 py-4 text-slate-400">{asset.data_provider ?? asset.provider ?? "-"}</td>
                  <td className="px-3 py-4 pr-0">
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => void toggleWatchlist(asset)}
                        disabled={actionLoading === `${asset.symbol}-watchlist`}
                        className="rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-300 transition hover:border-cyan-300/30 hover:text-cyan-100 disabled:opacity-60"
                      >
                        {asset.is_watchlisted ? "Rimuovi" : "Watch"}
                      </button>
                      <button
                        onClick={() => void promote(asset, "CORE")}
                        disabled={asset.universe_level === "CORE" || actionLoading === `${asset.symbol}-promote`}
                        className="rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-300 transition hover:border-emerald-300/30 hover:text-emerald-100 disabled:opacity-40"
                      >
                        Core
                      </button>
                      <button
                        onClick={() => void refreshAsset(asset)}
                        disabled={actionLoading === `${asset.symbol}-refresh`}
                        className="rounded-md border border-slate-700 px-2 py-1 text-xs font-semibold text-slate-300 transition hover:border-amber-300/30 hover:text-amber-100 disabled:opacity-60"
                      >
                        Refresh
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredAssets.length === 0 && <p className="py-8 text-sm text-slate-400">Nessun asset trovato con i filtri correnti.</p>}
        </div>
      </Panel>
    </div>
  );
}
