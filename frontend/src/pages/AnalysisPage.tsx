import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, AlertTriangle, XCircle, Info, ShieldCheck, Zap, Bell } from "lucide-react";

import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import {
  api,
  apiGet,
  type Asset,
  type NewsSentimentSummary,
  type PriceHistory,
  type TechnicalAnalysis,
  type ValidatedSignal,
  type DataQualityCheck,
  type Alert,
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
  const [newsSummary, setNewsSummary] = useState<NewsSentimentSummary | null>(null);
  const [validatedSignal, setValidatedSignal] = useState<ValidatedSignal | null>(null);
  const [dataQuality, setDataQuality] = useState<DataQualityCheck | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
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
        const [priceResponse, analysisResponse, sentimentResponse, validationResponse, qualityResponse, alertsResponse] = await Promise.all([
          apiGet<PriceHistory>(`/prices/${selectedSymbol}`),
          apiGet<TechnicalAnalysis>(`/technical-analysis/${selectedSymbol}`),
          apiGet<NewsSentimentSummary>(`/news/sentiment/${selectedSymbol}?lookback_days=7`).catch(() => null),
          api.getAssetValidatedSignal(selectedSymbol).catch(() => null),
          api.getAssetDataQuality(selectedSymbol).catch(() => null),
          api.listAlerts("OPEN", undefined, selectedSymbol).catch(() => [] as Alert[]),
        ]);
        setPrices(priceResponse);
        setAnalysis(analysisResponse);
        setNewsSummary(sentimentResponse);
        setValidatedSignal(validationResponse);
        setDataQuality(qualityResponse);
        setAlerts(alertsResponse);
      } catch (err) {
        setPrices(null);
        setAnalysis(null);
        setNewsSummary(null);
        setValidatedSignal(null);
        setDataQuality(null);
        setAlerts([]);
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

          <Panel title="Signal Validation & Data Quality" icon={<ShieldCheck className="w-5 h-5 text-indigo-400" />}>
            <div className="grid gap-6 md:grid-cols-2">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-400">Validazione Operativa</span>
                  <span className={`px-2 py-1 rounded text-xs font-bold ${
                    validatedSignal?.action_suggested === 'BUY' ? 'bg-emerald-500/20 text-emerald-400' :
                    validatedSignal?.action_suggested === 'WATCH' ? 'bg-amber-500/20 text-amber-400' :
                    validatedSignal?.action_suggested === 'EXCLUDE' ? 'bg-rose-500/20 text-rose-400' :
                    'bg-slate-800 text-slate-400'
                  }`}>
                    {validatedSignal?.action_suggested || 'N/D'}
                  </span>
                </div>
                <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800">
                  <p className="text-xs text-slate-500 mb-1 flex items-center gap-1"><Info className="w-3 h-3"/> Rationale di Validazione</p>
                  <p className="text-sm text-slate-300">{validatedSignal?.reason || 'Analisi di validazione non disponibile.'}</p>
                </div>
              </div>

              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-400">Data Quality Score</span>
                  <div className="flex items-center gap-2">
                    <span className={`text-lg font-bold ${
                      (dataQuality?.score || 0) >= 80 ? 'text-emerald-400' : 
                      (dataQuality?.score || 0) >= 50 ? 'text-amber-400' : 'text-rose-400'
                    }`}>
                      {dataQuality?.score.toFixed(1)}%
                    </span>
                    <span className="text-xs text-slate-500">Grade {dataQuality?.grade}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {dataQuality && Object.entries(dataQuality.checks).map(([check, passed]) => (
                    <div key={check} className="flex items-center gap-2 text-[10px] text-slate-400">
                      {passed ? <CheckCircle2 className="w-3 h-3 text-emerald-500"/> : <XCircle className="w-3 h-3 text-rose-500"/>}
                      <span className="capitalize">{check.replace('_', ' ')}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Panel>

          {alerts.length > 0 && (
            <Panel title="Alert Attivi" icon={<Bell className="w-5 h-5 text-rose-400" />}>
              <div className="space-y-2">
                {alerts.map(alert => (
                  <div key={alert.id} className="p-3 rounded-lg bg-slate-900/40 border border-slate-800 flex gap-3">
                     {alert.severity === 'CRITICAL' ? <XCircle className="w-4 h-4 text-rose-500 mt-0.5" /> : <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5" />}
                     <div>
                        <p className="text-sm font-bold text-slate-200">{alert.title}</p>
                        <p className="text-xs text-slate-400">{alert.message}</p>
                     </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <Panel title="Machine Learning">
            {analysis.latest_ml_prediction ? (
              <div className="space-y-4">
                <div className="grid gap-3 md:grid-cols-4">
                  <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                    <p className="text-xs uppercase text-slate-500">Target</p>
                    <p className="mt-2 text-sm font-semibold text-white">
                      {analysis.latest_ml_prediction.target_type} {analysis.latest_ml_prediction.horizon_days}d
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                    <p className="text-xs uppercase text-slate-500">Probabilita</p>
                    <p className="mt-2 text-xl font-semibold text-cyan-200">
                      {(
                        (analysis.latest_ml_prediction.probability_positive ??
                          analysis.latest_ml_prediction.probability_outperform ??
                          analysis.latest_ml_prediction.probability_drawdown ??
                          0) * 100
                      ).toFixed(1)}
                      %
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                    <p className="text-xs uppercase text-slate-500">Label</p>
                    <p className="mt-2 text-sm font-semibold text-white">{analysis.latest_ml_prediction.predicted_label}</p>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                    <p className="text-xs uppercase text-slate-500">Confidence</p>
                    <p className="mt-2 text-sm font-semibold text-white">{analysis.latest_ml_prediction.confidence}</p>
                  </div>
                </div>
                <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
                  ML sperimentale, non garanzia di rendimento. Usa questa probabilita insieme a score tecnico, news e rischio.
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <p className="mb-2 text-sm text-slate-400">Feature principali positive</p>
                    <div className="space-y-2">
                      {(analysis.latest_ml_prediction.explanation.top_features_positive ?? []).slice(0, 5).map((item) => (
                        <div key={item.feature} className="flex justify-between rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2 text-sm">
                          <span className="text-slate-300">{item.feature}</span>
                          <span className="text-emerald-300">{item.importance.toFixed(4)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-sm text-slate-400">Warning</p>
                    {analysis.latest_ml_prediction.warnings.length > 0 ? (
                      <div className="space-y-2">
                        {analysis.latest_ml_prediction.warnings.map((warning) => (
                          <div key={warning} className="rounded-md border border-amber-300/20 bg-amber-400/10 px-3 py-2 text-sm text-amber-100">
                            {warning}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-slate-500">Nessun warning ML salvato.</p>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-400">Nessun modello ML disponibile. Addestra un modello da AI Lab.</p>
            )}
          </Panel>

          <Panel title="News e sentiment asset">
            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Technical score</p>
                <p className="mt-2 text-xl font-semibold text-white">
                  {analysis.technical_score?.toFixed(1) ?? analysis.score.toFixed(1)}/100
                </p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">News score</p>
                <p
                  className={`mt-2 text-xl font-semibold ${
                    analysis.news_score > 0
                      ? "text-emerald-300"
                      : analysis.news_score < 0
                        ? "text-rose-300"
                        : "text-white"
                  }`}
                >
                  {analysis.news_score >= 0 ? "+" : ""}
                  {analysis.news_score.toFixed(1)}
                </p>
                <p className="mt-1 text-xs text-slate-500">Max ±{Math.abs(analysis.news_score).toFixed(0)} reale</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Final score</p>
                <p className="mt-2 text-xl font-semibold text-white">
                  {(analysis.final_score ?? analysis.score).toFixed(1)}/100
                </p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">Sentiment / impact</p>
                <p className="mt-2 text-sm font-semibold text-white">
                  {analysis.news_sentiment_label ?? "NEUTRAL"} · {analysis.news_impact_level ?? "LOW"}
                </p>
                <p className="mt-1 text-xs text-slate-500">{analysis.news_count} news ultimi 7gg</p>
              </div>
            </div>

            {newsSummary && newsSummary.news_count === 0 && (
              <p className="mt-4 text-sm text-slate-400">
                Nessuna news recente per questo asset. Aggiorna le news dal modulo News o abilita real news in `.env`.
              </p>
            )}

            {newsSummary && newsSummary.latest_news.length > 0 && (
              <div className="mt-4 space-y-3">
                {newsSummary.latest_news.map((item) => (
                  <article key={item.id} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                    <p className="text-xs uppercase text-slate-500">
                      {item.source ?? "fonte"} · {item.published_at ?? "N/D"}
                    </p>
                    <p className="mt-1 text-sm font-semibold text-white">{item.title}</p>
                    {item.summary && <p className="mt-1 text-sm text-slate-300">{item.summary}</p>}
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <span
                        className={`inline-flex rounded-md border px-2 py-1 font-semibold ${
                          item.sentiment_label === "POSITIVE"
                            ? "border-emerald-300/30 bg-emerald-400/10 text-emerald-200"
                            : item.sentiment_label === "NEGATIVE"
                              ? "border-rose-300/30 bg-rose-400/10 text-rose-200"
                              : "border-slate-700 bg-slate-900 text-slate-200"
                        }`}
                      >
                        {item.sentiment_label} {item.sentiment_score >= 0 ? "+" : ""}
                        {item.sentiment_score.toFixed(2)}
                      </span>
                      <span className="inline-flex rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-slate-300">
                        Impact {item.impact_level}
                      </span>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="inline-flex rounded-md border border-cyan-300/30 bg-cyan-400/10 px-2 py-1 font-semibold text-cyan-100"
                        >
                          Apri
                        </a>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}

            {!newsSummary && (
              <p className="mt-4 text-sm text-slate-400">
                Caricamento sentiment in corso. Se non arriva, le news potrebbero essere disattivate o il database vuoto.
              </p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
