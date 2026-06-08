import { useEffect, useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { apiGet, type Asset, type PortfolioRecommendation } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const assetTypeLabels: Record<string, string> = {
  stock: "Azione",
  etf: "ETF",
  crypto: "Crypto",
  bond: "Bond",
  bond_etf: "Bond ETF",
};

function recommendationTone(value: string | null | undefined) {
  if (value?.includes("BLOCK") || value === "SELL") {
    return "border-rose-300/20 bg-rose-400/10 text-rose-200";
  }
  if (value === "REDUCE") {
    return "border-amber-300/20 bg-amber-400/10 text-amber-200";
  }
  if (value === "BUY_ALLOWED") {
    return "border-emerald-300/20 bg-emerald-400/10 text-emerald-200";
  }
  return "border-slate-700 bg-slate-900 text-slate-300";
}

export function WatchlistPage() {
  const navigate = useNavigate();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [recommendations, setRecommendations] = useState<PortfolioRecommendation[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadAssets() {
      setLoading(true);
      setError(null);
      try {
        const [assetData, recommendationData] = await Promise.all([
          apiGet<Asset[]>("/assets"),
          apiGet<PortfolioRecommendation[]>("/portfolio/recommendations"),
        ]);
        setAssets(assetData);
        setRecommendations(recommendationData);
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

  const recommendationBySymbol = useMemo(
    () => new Map(recommendations.map((item) => [item.symbol, item])),
    [recommendations],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Multi-asset / universe"
        index="02"
        title="Watchlist"
        subtitle="Ogni asset del database con prezzo, segnale, score e raccomandazione contestualizzata sul portafoglio."
        actions={
          <PageHeaderAction icon={<Plus className="h-4 w-4" aria-hidden="true" />} onClick={() => navigate("/universe")}>
            Aggiungi asset
          </PageHeaderAction>
        }
      />

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
            <p className="mt-2 text-sm text-slate-300">Esegui `backend\.venv\Scripts\python.exe scripts\seed_database.py --reset` e ricarica la pagina.</p>
          </div>
        )}

        {!loading && !error && assets.length > 0 && (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filteredAssets.map((asset) => {
              const recommendation = recommendationBySymbol.get(asset.symbol);
              const change = asset.daily_change_pct ?? 0;
              return (
                <button
                  key={asset.symbol}
                  onClick={() => navigate(`/analysis?symbol=${asset.symbol}`)}
                  className="group flex flex-col gap-3 rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 text-left shadow-panel transition-all duration-200 hover:-translate-y-[2px] hover:border-cyan-300/25"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-mono text-base font-semibold text-white">{asset.symbol}</p>
                      <p className="mt-0.5 truncate text-xs text-slate-500">{asset.name}</p>
                    </div>
                    {asset.signal ? <SignalBadge signal={asset.signal} size="sm" /> : null}
                  </div>

                  <div className="flex items-end justify-between">
                    <div>
                      <p className="eyebrow-muted">Prezzo</p>
                      <p className="num mt-1 text-lg font-semibold text-white">
                        {asset.last_price == null ? "N/D" : formatCurrency(asset.last_price, asset.currency)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="eyebrow-muted">Giorno</p>
                      <p className={`num mt-1 text-sm font-semibold ${change >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                        {asset.daily_change_pct == null ? "N/D" : formatPercent(change)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="eyebrow-muted">Score</p>
                      <p className="num mt-1 text-sm font-semibold text-cyan-200">
                        {asset.score == null ? "N/D" : `${asset.score.toFixed(0)}`}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`inline-flex rounded-md border px-2 py-0.5 text-[11px] font-semibold ${recommendationTone(recommendation?.final_recommendation)}`}>
                      {recommendation?.final_recommendation ?? "HOLD"}
                    </span>
                    <span className="rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-300">
                      {assetTypeLabels[asset.asset_type] ?? asset.asset_type}
                    </span>
                    <span className="rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] capitalize text-slate-400">
                      {asset.risk_level.replace("_", " ")}
                    </span>
                    {recommendation && recommendation.portfolio_weight > 0 && (
                      <span className="rounded-md border border-cyan-300/20 bg-cyan-400/10 px-2 py-0.5 text-[11px] text-cyan-200">
                        in ptf {recommendation.portfolio_weight.toFixed(0)}%
                      </span>
                    )}
                  </div>

                  {recommendation?.reason && (
                    <p className="line-clamp-2 text-xs text-slate-500">{recommendation.reason}</p>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
