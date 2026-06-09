import { useEffect, useMemo, useState } from "react";
import { Check, Plus, Search, TrendingDown, TrendingUp } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { TradeButton } from "../components/TradeButton";
import { apiGet, type Asset, type PortfolioRecommendation } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const assetTypeLabels: Record<string, string> = {
  stock: "Azione",
  etf: "ETF",
  crypto: "Crypto",
  bond: "Bond",
  bond_etf: "Bond ETF",
};

type Trend = "up" | "flat" | "down";
type FilterKey = "all" | Trend;

// Mappa il segnale tecnico in 3 gruppi leggibili.
function trendOf(signal: string | null | undefined): Trend {
  if (signal === "STRONG_BUY" || signal === "BUY") return "up";
  if (signal === "SELL" || signal === "REDUCE") return "down";
  return "flat";
}

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
  const [filter, setFilter] = useState<FilterKey>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function toggleSel(symbol: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }

  function createPlan() {
    if (selected.size === 0) return;
    navigate(`/portfolio?symbols=${[...selected].join(",")}`);
  }

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

  const counts = useMemo(() => {
    const acc = { up: 0, flat: 0, down: 0 };
    for (const asset of assets) acc[trendOf(asset.signal)] += 1;
    return acc;
  }, [assets]);

  const filteredAssets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return assets
      .filter((asset) => (filter === "all" ? true : trendOf(asset.signal) === filter))
      .filter((asset) =>
        !normalized
          ? true
          : [asset.symbol, asset.name, asset.asset_type, asset.sector, asset.country]
              .filter(Boolean)
              .some((value) => String(value).toLowerCase().includes(normalized)),
      )
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  }, [assets, query, filter]);

  const recommendationBySymbol = useMemo(
    () => new Map(recommendations.map((item) => [item.symbol, item])),
    [recommendations],
  );

  const filters: { key: FilterKey; label: string; count: number; active: string }[] = [
    { key: "all", label: "Tutti", count: assets.length, active: "border-cyan-300/40 bg-cyan-400/15 text-cyan-100" },
    { key: "up", label: "📈 Al rialzo", count: counts.up, active: "border-emerald-300/40 bg-emerald-400/15 text-emerald-100" },
    { key: "flat", label: "Neutri", count: counts.flat, active: "border-slate-500/40 bg-slate-500/15 text-slate-100" },
    { key: "down", label: "📉 Al ribasso", count: counts.down, active: "border-rose-300/40 bg-rose-400/15 text-rose-100" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Selezione titoli / screener"
        index="02"
        title="Watchlist"
        subtitle="Filtra per capire su cosa il sistema vede forza (al rialzo) e su cosa vede debolezza (al ribasso). Ordinati per punteggio."
        actions={
          <PageHeaderAction icon={<Plus className="h-4 w-4" aria-hidden="true" />} onClick={() => navigate("/universe")}>
            Aggiungi asset
          </PageHeaderAction>
        }
      />

      {/* Legenda: cosa significano i colori */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="flex items-start gap-3 rounded-2xl border border-emerald-300/20 bg-emerald-400/[0.06] p-4">
          <TrendingUp className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-emerald-100">Al rialzo (BUY)</p>
            <p className="mt-0.5 text-xs text-slate-400">Forza tecnica: candidati all'acquisto. Score alto (≥70).</p>
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-2xl border border-slate-600/30 bg-slate-500/[0.06] p-4">
          <span className="mt-0.5 h-5 w-5 shrink-0 rounded-full border-2 border-slate-400" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-slate-200">Neutri (HOLD)</p>
            <p className="mt-0.5 text-xs text-slate-400">Nessun segnale netto: meglio attendere. Score medio.</p>
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-2xl border border-rose-300/20 bg-rose-400/[0.06] p-4">
          <TrendingDown className="mt-0.5 h-5 w-5 shrink-0 text-rose-300" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-rose-100">Al ribasso (SELL/REDUCE)</p>
            <p className="mt-0.5 text-xs text-slate-400">Debolezza: da evitare o vendere se in portafoglio. Score basso (&lt;40).</p>
          </div>
        </div>
      </div>

      <Panel>
        {/* Barra filtri + ricerca */}
        <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {filters.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-semibold transition ${
                  filter === f.key ? f.active : "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
                }`}
              >
                {f.label}
                <span className="num rounded-md bg-slate-950/60 px-1.5 text-[11px]">{f.count}</span>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 lg:w-72">
            <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
              placeholder="Cerca ticker, ETF, crypto"
            />
          </div>
        </div>

        {loading && <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />}

        {error && <p className="text-sm text-rose-300">{error}</p>}

        {!loading && !error && assets.length === 0 && (
          <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 p-5">
            <h2 className="font-semibold text-amber-100">Database non inizializzato</h2>
            <p className="mt-2 text-sm text-slate-300">Esegui il seed e ricarica la pagina.</p>
          </div>
        )}

        {!loading && !error && assets.length > 0 && (
          <>
            {filteredAssets.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-400">Nessun asset in questo gruppo.</p>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {filteredAssets.map((asset) => {
                  const recommendation = recommendationBySymbol.get(asset.symbol);
                  const change = asset.daily_change_pct ?? 0;
                  return (
                    <div
                      key={asset.symbol}
                      role="button"
                      tabIndex={0}
                      onClick={() => navigate(`/analysis?symbol=${asset.symbol}`)}
                      className={`group flex cursor-pointer flex-col gap-3 rounded-2xl border bg-slate-950/55 p-4 text-left shadow-panel transition-all duration-200 hover:-translate-y-[2px] hover:border-cyan-300/25 ${
                        selected.has(asset.symbol) ? "border-cyan-300/50 ring-1 ring-cyan-300/30" : "border-slate-800/60"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 items-start gap-2">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleSel(asset.symbol);
                            }}
                            aria-label={`Seleziona ${asset.symbol}`}
                            className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded border transition ${
                              selected.has(asset.symbol)
                                ? "border-cyan-300 bg-cyan-400/20 text-cyan-200"
                                : "border-slate-600 text-transparent hover:border-cyan-300/50"
                            }`}
                          >
                            <Check className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          <div className="min-w-0">
                            <p className="font-mono text-base font-semibold text-white">{asset.symbol}</p>
                            <p className="mt-0.5 truncate text-xs text-slate-500">{asset.name}</p>
                          </div>
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

                      <div className="mt-1 flex items-center gap-2 border-t border-slate-800/60 pt-3">
                        <TradeButton symbol={asset.symbol} price={asset.last_price} currency={asset.currency} />
                        <span className="text-[11px] text-slate-600">aggiungi al portafoglio simulato</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </Panel>

      {selected.size > 0 && (
        <div className="fixed inset-x-0 bottom-4 z-30 flex justify-center px-4">
          <div className="flex items-center gap-3 rounded-full border border-cyan-300/30 bg-slate-900/95 px-5 py-3 shadow-xl backdrop-blur">
            <span className="text-sm text-slate-200">
              <b className="text-cyan-200">{selected.size}</b> selezionati
            </span>
            <button onClick={() => setSelected(new Set())} className="text-xs text-slate-400 transition hover:text-slate-200">
              Deseleziona
            </button>
            <button
              onClick={createPlan}
              className="inline-flex items-center gap-1.5 rounded-full border border-cyan-300/40 bg-cyan-400/20 px-4 py-1.5 text-sm font-semibold text-cyan-50 transition hover:bg-cyan-400/30"
            >
              Crea piano con questi →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
