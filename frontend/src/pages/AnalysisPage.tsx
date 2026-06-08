import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PageHeader } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import {
  apiGet,
  type Asset,
  type NewsSentimentSummary,
  type NewsStatus,
  type PriceHistory,
  type TechnicalAnalysis,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const subscoreLabels: Record<string, string> = {
  trend_score: "Trend",
  momentum_score: "Momentum",
  volatility_score: "Volatilita",
  volume_score: "Volume",
  support_resistance_score: "Supporti/resistenze",
  risk_penalty: "Penalita rischio",
};

const indicatorLabels: Array<[string, string, "number" | "percent"]> = [
  ["rsi_14", "RSI 14", "number"],
  ["macd_line", "MACD", "number"],
  ["adx_14", "ADX", "number"],
  ["atr_14", "ATR", "number"],
  ["volatility_annualized_30d", "Volatilita", "percent"],
  ["max_drawdown", "Max drawdown", "percent"],
];

const sentimentTone: Record<string, string> = {
  POSITIVE: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
  NEUTRAL: "border-cyan-300/30 bg-cyan-400/10 text-cyan-200",
  NEGATIVE: "border-rose-300/30 bg-rose-400/10 text-rose-200",
};

const impactTone: Record<string, string> = {
  HIGH: "border-rose-300/30 bg-rose-400/10 text-rose-200",
  MEDIUM: "border-amber-300/30 bg-amber-400/10 text-amber-200",
  LOW: "border-slate-700 bg-slate-900 text-slate-300",
};

function formatIndicator(value: number | null | undefined, kind: "number" | "percent" = "number") {
  if (value == null || Number.isNaN(value)) {
    return "N/D";
  }
  if (kind === "percent") {
    return `${(value * 100).toFixed(1)}%`;
  }
  return value.toFixed(2);
}

export function AnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [prices, setPrices] = useState<PriceHistory | null>(null);
  const [analysis, setAnalysis] = useState<TechnicalAnalysis | null>(null);
  const [newsStatus, setNewsStatus] = useState<NewsStatus | null>(null);
  const [newsSummary, setNewsSummary] = useState<NewsSentimentSummary | null>(null);
  const [loadingAssets, setLoadingAssets] = useState(true);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentSymbolParam = searchParams.get("symbol");
  const selectedSymbol = currentSymbolParam ?? assets[0]?.symbol ?? "";
  const selectedAsset = assets.find((asset) => asset.symbol === selectedSymbol) ?? analysis?.asset ?? null;
  const latestPoint = prices?.prices[prices.prices.length - 1];

  useEffect(() => {
    async function loadAssets() {
      setLoadingAssets(true);
      setError(null);
      try {
        const response = await apiGet<Asset[]>("/assets");
        setAssets(response);
        if (!currentSymbolParam && response[0]) {
          setSearchParams({ symbol: response[0].symbol }, { replace: true });
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore durante il caricamento degli asset.");
      } finally {
        setLoadingAssets(false);
      }
    }

    void loadAssets();
  }, [currentSymbolParam, setSearchParams]);

  useEffect(() => {
    if (!selectedSymbol) {
      return;
    }

    async function loadAnalysis() {
      setLoadingAnalysis(true);
      setError(null);
      try {
        const [priceResponse, analysisResponse] = await Promise.all([
          apiGet<PriceHistory>(`/prices/${selectedSymbol}`),
          apiGet<TechnicalAnalysis>(`/technical-analysis/${selectedSymbol}`),
        ]);
        const [newsStatusResponse, newsSummaryResponse] = await Promise.all([
          apiGet<NewsStatus>("/news/status").catch(() => null),
          apiGet<NewsSentimentSummary>(`/news/sentiment/${selectedSymbol}`).catch(() => null),
        ]);
        setPrices(priceResponse);
        setAnalysis(analysisResponse);
        setNewsStatus(newsStatusResponse);
        setNewsSummary(newsSummaryResponse);
      } catch (err) {
        setPrices(null);
        setAnalysis(null);
        setNewsStatus(null);
        setNewsSummary(null);
        setError(err instanceof Error ? err.message : "Asset non trovato o analisi non disponibile.");
      } finally {
        setLoadingAnalysis(false);
      }
    }

    void loadAnalysis();
  }, [selectedSymbol]);

  if (loadingAssets) {
    return (
      <Panel title="Analisi Asset">
        <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  if (!loadingAssets && assets.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Technical analysis"
          index="05"
          title="Analisi Asset"
          subtitle="Indicatori, segnali e scoring spiegabile per ogni asset in watchlist."
        />
        <Panel title="Database non inizializzato">
          <p className="text-slate-300">Database non inizializzato.</p>
          <p className="mt-3 text-sm text-slate-500">Esegui `backend\.venv\Scripts\python.exe scripts\seed_database.py --reset` e ricarica la pagina.</p>
        </Panel>
      </div>
    );
  }

  const positiveReasons = analysis?.reasons.filter((reason) => reason.type === "positive") ?? [];
  const negativeReasons = analysis?.reasons.filter((reason) => reason.type === "negative") ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Technical analysis"
        index="05"
        title="Analisi Asset"
        subtitle="Indicatori, scoring spiegabile, supporti/resistenze e sentiment news per asset."
        meta={
          <>
            <span>
              Asset selezionato <span className="text-cyan-300/80">{selectedSymbol}</span>
            </span>
            <span>
              Universo <span className="text-cyan-300/80">{assets.length}</span>
            </span>
          </>
        }
        actions={
          <select
            value={selectedSymbol}
            onChange={(event) => setSearchParams({ symbol: event.target.value })}
            className="rounded-lg border border-slate-800/80 bg-slate-950/60 px-3 py-2.5 font-mono text-sm tracking-tight text-white outline-none transition-colors focus:border-cyan-300/60"
          >
            {assets.map((asset) => (
              <option key={asset.symbol} value={asset.symbol}>
                {asset.symbol} — {asset.name}
              </option>
            ))}
          </select>
        }
      />

      {error && (
        <Panel title="Errore">
          <p className="text-sm text-rose-300">{error}</p>
        </Panel>
      )}

      {loadingAnalysis && (
        <Panel title="Caricamento">
          <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
        </Panel>
      )}

      {!loadingAnalysis && prices && analysis && selectedAsset && (
        <>
          {!latestPoint?.is_real_data && (
            <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
              Dati reali disattivati o non disponibili. Stai usando dati seed/demo per questo asset.
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-4">
            <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
              <p className="text-xs font-medium uppercase text-slate-500">Ultimo prezzo</p>
              <p className="mt-2 text-2xl font-semibold text-white">
                {latestPoint ? formatCurrency(latestPoint.close, prices.currency) : "N/D"}
              </p>
              <p className={`mt-3 text-sm font-semibold ${(selectedAsset.daily_change_pct ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                {selectedAsset.daily_change_pct == null ? "Variazione N/D" : formatPercent(selectedAsset.daily_change_pct)}
              </p>
            </article>
            <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
              <p className="text-xs font-medium uppercase text-slate-500">Segnale</p>
              <div className="mt-3">
                <SignalBadge signal={analysis.signal} />
              </div>
              <p className="mt-3 text-sm text-slate-400">Confidenza {analysis.confidence}</p>
            </article>
            <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
              <p className="text-xs font-medium uppercase text-slate-500">Score tecnico</p>
              <p className="mt-2 text-2xl font-semibold text-white">{analysis.score.toFixed(1)}/100</p>
              <p className="mt-3 text-sm text-slate-400">{analysis.summaries.overall_technical_bias}</p>
            </article>
            <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
              <p className="text-xs font-medium uppercase text-slate-500">Rischio</p>
              <p className="mt-2 text-2xl font-semibold text-white">{analysis.risk_level}</p>
              <p className="mt-3 text-sm text-slate-400">{selectedAsset.sector}</p>
            </article>
          </div>

          <Panel title="Origine dati">
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Source</p>
                <p className={latestPoint?.is_real_data ? "mt-2 font-semibold text-emerald-300" : "mt-2 font-semibold text-amber-300"}>
                  {latestPoint?.is_real_data ? "real" : latestPoint?.source ?? "N/D"}
                </p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Provider</p>
                <p className="mt-2 font-semibold text-white">{latestPoint?.provider ?? selectedAsset.provider ?? "Locale"}</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Ultima data prezzo</p>
                <p className="mt-2 font-semibold text-white">{latestPoint?.date ?? "N/D"}</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Last fetch</p>
                <p className="mt-2 font-semibold text-white">{latestPoint?.fetched_at ?? "N/D"}</p>
              </div>
            </div>
          </Panel>

          <Panel title="News asset">
            {!newsStatus?.enable_real_news && (
              <div className="mb-4 rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
                News reali disattivate. Stai usando news demo/locali.
              </div>
            )}
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Sentiment 7 giorni</p>
                <p className="mt-2 font-semibold text-white">{newsSummary?.sentiment_label ?? "NEUTRAL"}</p>
                <p className="mt-1 text-sm text-slate-500">{newsSummary?.news_count ?? 0} news</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">News score</p>
                <p className={(analysis.news_score ?? 0) >= 0 ? "mt-2 font-semibold text-emerald-300" : "mt-2 font-semibold text-rose-300"}>
                  {(analysis.news_score ?? 0) > 0 ? "+" : ""}{(analysis.news_score ?? 0).toFixed(2)}
                </p>
                <p className="mt-1 text-sm text-slate-500">max +/- 5</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Final score</p>
                <p className="mt-2 font-semibold text-white">{(analysis.final_score ?? analysis.score).toFixed(1)}/100</p>
                <p className="mt-1 text-sm text-slate-500">Score tecnico + news</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Impatto</p>
                <span className={`mt-2 inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold ${impactTone[newsSummary?.impact_level ?? "LOW"] ?? impactTone.LOW}`}>
                  {newsSummary?.impact_level ?? "LOW"}
                </span>
              </div>
            </div>
            <div className="mt-5 space-y-3">
              {(newsSummary?.latest_news ?? []).slice(0, 5).map((item) => (
                <article key={`${item.id}-${item.title}`} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <p className="text-xs uppercase text-slate-500">{item.source ?? "N/D"} - {item.published_at ?? "N/D"}</p>
                      <h3 className="mt-2 text-sm font-semibold text-white">{item.title}</h3>
                    </div>
                    <span className={`inline-flex w-fit rounded-md border px-2.5 py-1 text-xs font-semibold ${sentimentTone[item.sentiment_label ?? "NEUTRAL"] ?? sentimentTone.NEUTRAL}`}>
                      {item.sentiment_label ?? "NEUTRAL"}
                    </span>
                  </div>
                </article>
              ))}
              {(newsSummary?.latest_news ?? []).length === 0 && (
                <p className="text-sm text-slate-500">Nessuna news recente salvata per questo asset.</p>
              )}
            </div>
          </Panel>

          <div className="grid gap-6 xl:grid-cols-[1.45fr_0.85fr]">
            <Panel title={`${prices.symbol} - prezzo, medie e Bollinger`}>
              <div className="h-96">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={prices.prices} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                    <XAxis dataKey="date" stroke="#64748B" axisLine={false} tickLine={false} minTickGap={42} />
                    <YAxis stroke="#64748B" axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                    <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} />
                    <Line type="monotone" dataKey="close" name="Close" stroke="#22D3EE" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="sma_50" name="SMA 50" stroke="#F59E0B" strokeWidth={1.8} dot={false} connectNulls />
                    <Line type="monotone" dataKey="sma_200" name="SMA 200" stroke="#94A3B8" strokeWidth={1.8} dot={false} connectNulls />
                    <Line type="monotone" dataKey="bollinger_upper" name="Bollinger upper" stroke="#64748B" strokeWidth={1} dot={false} connectNulls />
                    <Line type="monotone" dataKey="bollinger_lower" name="Bollinger lower" stroke="#64748B" strokeWidth={1} dot={false} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel title="Sotto-score">
              <div className="space-y-4">
                {Object.entries(analysis.subscores).map(([key, value]) => {
                  const isPenalty = key === "risk_penalty";
                  return (
                    <div key={key}>
                      <div className="mb-2 flex justify-between text-sm">
                        <span className="text-slate-400">{subscoreLabels[key] ?? key}</span>
                        <span className={isPenalty ? "font-medium text-rose-300" : "font-medium text-white"}>{value.toFixed(1)}</span>
                      </div>
                      <div className="h-2 rounded-full bg-slate-800">
                        <div
                          className={`h-2 rounded-full ${isPenalty ? "bg-rose-300" : "bg-cyan-300"}`}
                          style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <Panel title="Motivazioni positive">
              <div className="space-y-3">
                {positiveReasons.map((reason) => (
                  <div key={reason.message} className="rounded-lg border border-emerald-300/20 bg-emerald-400/10 p-3 text-sm text-emerald-100">
                    {reason.message}
                  </div>
                ))}
                {positiveReasons.length === 0 && <p className="text-sm text-slate-500">Nessuna motivazione positiva forte.</p>}
              </div>
            </Panel>

            <Panel title="Motivazioni negative">
              <div className="space-y-3">
                {negativeReasons.map((reason) => (
                  <div key={reason.message} className="rounded-lg border border-rose-300/20 bg-rose-400/10 p-3 text-sm text-rose-100">
                    {reason.message}
                  </div>
                ))}
                {negativeReasons.length === 0 && <p className="text-sm text-slate-500">Nessuna criticita tecnica forte.</p>}
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 xl:grid-cols-[1fr_0.9fr]">
            <Panel title="Indicatori principali">
              <div className="grid gap-3 md:grid-cols-2">
                {indicatorLabels.map(([key, label, kind]) => (
                  <div key={key} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                    <p className="text-xs uppercase text-slate-500">{label}</p>
                    <p className="mt-2 text-xl font-semibold text-white">{formatIndicator(analysis.indicators[key], kind)}</p>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Supporti e resistenze">
              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <span className="text-sm text-slate-400">Supporto vicino</span>
                  <span className="font-semibold text-white">{formatIndicator(analysis.support_resistance.nearest_support)}</span>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <span className="text-sm text-slate-400">Distanza supporto</span>
                  <span className="font-semibold text-emerald-300">{formatIndicator(analysis.support_resistance.support_distance_percent)}%</span>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <span className="text-sm text-slate-400">Resistenza vicina</span>
                  <span className="font-semibold text-white">{formatIndicator(analysis.support_resistance.nearest_resistance)}</span>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <span className="text-sm text-slate-400">Distanza resistenza</span>
                  <span className="font-semibold text-amber-300">{formatIndicator(analysis.support_resistance.resistance_distance_percent)}%</span>
                </div>
              </div>
            </Panel>
          </div>

          <Panel title="Sintesi tecnica">
            <p className="text-sm leading-6 text-slate-300">{analysis.technical_summary}</p>
          </Panel>
        </>
      )}
    </div>
  );
}
