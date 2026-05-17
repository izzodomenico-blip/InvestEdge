import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { apiGet, type Asset, type PriceHistory, type TechnicalAnalysis } from "../lib/api";
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
        setPrices(priceResponse);
        setAnalysis(analysisResponse);
      } catch (err) {
        setPrices(null);
        setAnalysis(null);
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
        <header>
          <p className="text-sm font-medium text-cyan-300">Technical analysis</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Analisi Asset</h1>
        </header>
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
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">Technical analysis</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Analisi Asset</h1>
        </div>
        <select
          value={selectedSymbol}
          onChange={(event) => setSearchParams({ symbol: event.target.value })}
          className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
        >
          {assets.map((asset) => (
            <option key={asset.symbol} value={asset.symbol}>
              {asset.symbol} - {asset.name}
            </option>
          ))}
        </select>
      </header>

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
