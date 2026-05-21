import { useEffect, useMemo, useState } from "react";
import { Plus, Search, Bell } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { api, apiGet, type NewsItem, type PortfolioRecommendation, type SentimentLabel, type ImpactLevel, type UniverseAsset, type DataQualityCheck } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";


type NewsBadge = {
  sentiment: SentimentLabel | null;
  impact: ImpactLevel | null;
};

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

function sourceTone(asset: UniverseAsset) {
  if (asset.is_real_data) {
    return "border-emerald-300/20 bg-emerald-400/10 text-emerald-200";
  }
  if (asset.last_source === "seed") {
    return "border-amber-300/20 bg-amber-400/10 text-amber-200";
  }
  return "border-slate-700 bg-slate-900 text-slate-300";
}

export function WatchlistPage() {
  const navigate = useNavigate();
  const [assets, setAssets] = useState<UniverseAsset[]>([]);
  const [recommendations, setRecommendations] = useState<PortfolioRecommendation[]>([]);
  const [newsBySymbol, setNewsBySymbol] = useState<Map<string, NewsBadge>>(new Map());
  const [qualityBySymbol, setQualityBySymbol] = useState<Map<string, DataQualityCheck>>(new Map());
  const [alertsBySymbol, setAlertsBySymbol] = useState<Map<string, number>>(new Map());
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadAssets() {
      setLoading(true);
      setError(null);
      try {
        const [assetData, recommendationData, newsData, qualityData, alertSummary] = await Promise.all([
          apiGet<UniverseAsset[]>("/universe?active_only=true&limit=1000"),
          apiGet<PortfolioRecommendation[]>("/portfolio/recommendations"),
          apiGet<NewsItem[]>("/news?limit=200").catch(() => [] as NewsItem[]),
          api.getAllDataQuality().catch(() => [] as DataQualityCheck[]),
          api.getAlertSummary().catch(() => null),
        ]);
        setAssets(assetData.filter((asset: UniverseAsset) => asset.is_watchlisted || asset.is_portfolio_asset));
        setRecommendations(recommendationData);
        setQualityBySymbol(new Map(qualityData.map((q: DataQualityCheck) => [q.symbol, q])));
        
        const alertMap = new Map<string, number>();
        alertSummary?.latest_alerts.forEach(a => {
          if (a.symbol) {
            alertMap.set(a.symbol, (alertMap.get(a.symbol) || 0) + 1);
          }
        });
        setAlertsBySymbol(alertMap);
        const aggregated = new Map<string, NewsBadge>();
        for (const item of newsData) {
          if (!item.symbol) {
            continue;
          }
          if (aggregated.has(item.symbol)) {
            continue;
          }
          aggregated.set(item.symbol, {
            sentiment: item.sentiment_label,
            impact: item.impact_level,
          });
        }
        setNewsBySymbol(aggregated);
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
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">Multi-asset</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Watchlist</h1>
        </div>
        <button
          onClick={() => navigate("/universe")}
          className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:border-cyan-300/30 hover:text-cyan-100"
        >
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
            <p className="mt-2 text-sm text-slate-300">Esegui `backend\.venv\Scripts\python.exe scripts\seed_database.py --reset` e ricarica la pagina.</p>
          </div>
        )}

        {!loading && !error && assets.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1840px] border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="px-3 pb-3 pl-0 font-medium">Asset</th>
                  <th className="px-3 pb-3 font-medium">Tipo</th>
                  <th className="px-3 pb-3 font-medium">Settore</th>
                  <th className="px-3 pb-3 text-right font-medium">Prezzo</th>
                  <th className="px-3 pb-3 text-right font-medium">Giorno</th>
                  <th className="px-3 pb-3 text-center font-medium">Segnale</th>
                  <th className="px-3 pb-3 text-right font-medium">Score</th>
                  <th className="px-3 pb-3 font-medium">Confidenza</th>
                  <th className="px-3 pb-3 font-medium">Rischio</th>
                  <th className="px-3 pb-3 text-right font-medium">Peso ptf</th>
                  <th className="px-3 pb-3 font-medium">Raccomandazione</th>
                  <th className="px-3 pb-3 font-medium">Source</th>
                  <th className="px-3 pb-3 font-medium">Qualità</th>
                  <th className="px-3 pb-3 font-medium">Provider</th>
                  <th className="px-3 pb-3 font-medium">Data prezzo</th>
                  <th className="px-3 pb-3 font-medium">News</th>
                  <th className="px-3 pb-3 text-right font-medium">ML prob</th>
                  <th className="px-3 pb-3 font-medium">ML label</th>
                  <th className="px-3 pb-3 font-medium">ML conf.</th>
                  <th className="px-3 pb-3 pr-0 font-medium">Sintesi tecnica</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {filteredAssets.map((asset) => {
                  const recommendation = recommendationBySymbol.get(asset.symbol);
                  const newsBadge = newsBySymbol.get(asset.symbol);
                  return (
                    <tr
                      key={asset.symbol}
                      onClick={() => navigate(`/analysis?symbol=${asset.symbol}`)}
                      className="cursor-pointer align-top text-sm transition hover:bg-cyan-400/5"
                    >
                      <td className="px-3 py-4 pl-0">
                        <div className="flex items-center gap-2">
                          <div>
                            <p className="font-semibold text-white">{asset.symbol}</p>
                            <p className="mt-1 text-slate-500">{asset.name}</p>
                          </div>
                          {alertsBySymbol.get(asset.symbol) && (
                            <Bell className="w-3 h-3 text-rose-500 animate-pulse" />
                          )}
                        </div>
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
                      <td className="px-3 py-4 text-slate-300">{asset.confidence ?? "N/D"}</td>
                      <td className="px-3 py-4 capitalize text-slate-400">{asset.risk_level.replace("_", " ")}</td>
                      <td className="px-3 py-4 text-right text-cyan-200">{recommendation ? `${recommendation.portfolio_weight.toFixed(2)}%` : "0.00%"}</td>
                      <td className="px-3 py-4">
                        <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${recommendationTone(recommendation?.final_recommendation)}`}>
                          {recommendation?.final_recommendation ?? "HOLD"}
                        </span>
                        <p className="mt-2 max-w-56 truncate text-xs text-slate-500" title={recommendation?.reason}>
                          {recommendation?.reason ?? "Nessuna posizione aperta."}
                        </p>
                      </td>
                      <td className="px-3 py-4">
                        <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${sourceTone(asset)}`}>
                          {asset.is_real_data ? "real" : asset.last_source ?? "N/D"}
                        </span>
                      </td>
                      <td className="px-3 py-4">
                        {qualityBySymbol.get(asset.symbol) ? (
                          <span className={`inline-flex rounded-md border px-2 py-1 text-[11px] font-bold ${
                            qualityBySymbol.get(asset.symbol)!.score >= 80 ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' :
                            qualityBySymbol.get(asset.symbol)!.score >= 50 ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' :
                            'border-rose-500/30 bg-rose-500/10 text-rose-400'
                          }`}>
                            {qualityBySymbol.get(asset.symbol)!.grade} ({qualityBySymbol.get(asset.symbol)!.score.toFixed(0)}%)
                          </span>
                        ) : (
                          <span className="text-[11px] text-slate-500">N/D</span>
                        )}
                      </td>
                      <td className="px-3 py-4 text-slate-300">{asset.provider ?? "Locale"}</td>
                      <td className="px-3 py-4 text-slate-400">{asset.last_price_date ?? "N/D"}</td>
                      <td className="px-3 py-4">
                        {newsBadge ? (
                          <div className="flex flex-col gap-1">
                            <span
                              className={`inline-flex w-fit rounded-md border px-2 py-0.5 text-[11px] font-semibold ${
                                newsBadge.sentiment === "POSITIVE"
                                  ? "border-emerald-300/30 bg-emerald-400/10 text-emerald-200"
                                  : newsBadge.sentiment === "NEGATIVE"
                                    ? "border-rose-300/30 bg-rose-400/10 text-rose-200"
                                    : "border-slate-700 bg-slate-900 text-slate-300"
                              }`}
                            >
                              {newsBadge.sentiment ?? "NEUTRAL"}
                            </span>
                            <span className="text-[11px] text-slate-500">Impact {newsBadge.impact ?? "LOW"}</span>
                          </div>
                        ) : (
                          <span className="text-[11px] text-slate-500">N/D</span>
                        )}
                      </td>
                      <td className="px-3 py-4 text-right text-cyan-200">
                        {asset.ml_probability == null ? "N/D" : `${(asset.ml_probability * 100).toFixed(1)}%`}
                      </td>
                      <td className="px-3 py-4 text-slate-300">{asset.ml_label ?? "N/D"}</td>
                      <td className="px-3 py-4 text-slate-400">{asset.ml_confidence ?? "N/D"}</td>
                      <td className="max-w-80 px-3 py-4 pr-0 text-slate-400">
                        <span className="block max-w-80 truncate" title={asset.technical_summary ?? "N/D"}>
                          {asset.technical_summary ?? "N/D"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
