import { useEffect, useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { apiGet, type Asset } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const assetTypeLabels: Record<string, string> = {
  stock: "Azione",
  etf: "ETF",
  crypto: "Crypto",
  bond: "Bond",
  bond_etf: "Bond ETF",
};

export function WatchlistPage() {
  const navigate = useNavigate();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadAssets() {
      setLoading(true);
      setError(null);
      try {
        setAssets(await apiGet<Asset[]>("/assets"));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore durante il caricamento degli asset.");
      } finally {
        setLoading(false);
      }
    }

    void loadAssets();
  }, []);

  const filteredAssets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return assets;
    }
    return assets.filter((asset) =>
      [asset.symbol, asset.name, asset.asset_type, asset.sector, asset.country]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    );
  }, [assets, query]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">Multi-asset</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Watchlist</h1>
        </div>
        <button className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-300">
          <Plus className="h-4 w-4" aria-hidden="true" />
          Aggiungi asset
        </button>
      </header>

      <Panel>
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
          <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
            placeholder="Cerca ticker, ETF, crypto, bond ETF"
          />
        </div>

        {loading && <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />}

        {error && <p className="text-sm text-rose-300">{error}</p>}

        {!loading && !error && assets.length === 0 && (
          <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-5">
            <h2 className="font-semibold text-amber-100">Database non inizializzato</h2>
            <p className="mt-2 text-sm text-slate-300">Esegui `python scripts/seed_database.py --reset` e ricarica la pagina.</p>
          </div>
        )}

        {!loading && !error && assets.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="px-3 pb-3 pl-0 font-medium">Asset</th>
                  <th className="px-3 pb-3 font-medium">Tipo</th>
                  <th className="px-3 pb-3 font-medium">Settore</th>
                  <th className="px-3 pb-3 text-right font-medium">Prezzo</th>
                  <th className="px-3 pb-3 text-right font-medium">Giorno</th>
                  <th className="px-3 pb-3 text-center font-medium">Segnale</th>
                  <th className="px-3 pb-3 text-right font-medium">Score</th>
                  <th className="px-3 pb-3 pr-0 font-medium">Rischio</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {filteredAssets.map((asset) => (
                  <tr
                    key={asset.symbol}
                    onClick={() => navigate(`/analysis?symbol=${asset.symbol}`)}
                    className="cursor-pointer text-sm transition hover:bg-cyan-400/5"
                  >
                    <td className="px-3 py-4 pl-0">
                      <p className="font-semibold text-white">{asset.symbol}</p>
                      <p className="mt-1 text-slate-500">{asset.name}</p>
                    </td>
                    <td className="px-3 py-4 text-slate-300">{assetTypeLabels[asset.asset_type] ?? asset.asset_type}</td>
                    <td className="px-3 py-4 text-slate-400">{asset.sector ?? "-"}</td>
                    <td className="px-3 py-4 text-right font-medium text-white">
                      {asset.last_price == null ? "N/D" : formatCurrency(asset.last_price, asset.currency)}
                    </td>
                    <td className={`px-3 py-4 text-right font-semibold ${(asset.daily_change_pct ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                      {asset.daily_change_pct == null ? "N/D" : formatPercent(asset.daily_change_pct)}
                    </td>
                    <td className="px-3 py-4 text-center">{asset.signal ? <SignalBadge signal={asset.signal} /> : "N/D"}</td>
                    <td className="px-3 py-4 text-right text-slate-200">{asset.score == null ? "N/D" : `${asset.score.toFixed(1)}/100`}</td>
                    <td className="px-3 py-4 pr-0 capitalize text-slate-400">{asset.risk_level.replace("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
