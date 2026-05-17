import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { apiGet, type Asset, type PriceHistory, type SignalRecord } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

export function AnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [prices, setPrices] = useState<PriceHistory | null>(null);
  const [signal, setSignal] = useState<SignalRecord | null>(null);
  const [loadingAssets, setLoadingAssets] = useState(true);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentSymbolParam = searchParams.get("symbol");
  const selectedSymbol = searchParams.get("symbol") ?? assets[0]?.symbol ?? "";
  const selectedAsset = assets.find((asset) => asset.symbol === selectedSymbol) ?? null;

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
        const [priceResponse, signalResponse] = await Promise.all([
          apiGet<PriceHistory>(`/prices/${selectedSymbol}`),
          apiGet<SignalRecord>(`/signals/${selectedSymbol}`),
        ]);
        setPrices(priceResponse);
        setSignal(signalResponse);
      } catch (err) {
        setPrices(null);
        setSignal(null);
        setError(err instanceof Error ? err.message : "Errore durante il caricamento dell'analisi.");
      } finally {
        setLoadingAnalysis(false);
      }
    }

    void loadAnalysis();
  }, [selectedSymbol]);

  const latestPoint = prices?.prices[prices.prices.length - 1];
  const scoreBreakdown = useMemo<Array<[string, number]>>(() => {
    const rsi = latestPoint?.rsi_14 ?? null;
    const macd = latestPoint?.macd_line != null && latestPoint?.macd_signal != null
      ? latestPoint.macd_line - latestPoint.macd_signal
      : null;
    return [
      ["Score", signal?.score ?? selectedAsset?.score ?? 0],
      ["RSI 14", rsi ?? 0],
      ["MACD spread", macd == null ? 0 : Math.max(0, Math.min(100, 50 + macd * 25))],
      ["Trend SMA", latestPoint?.sma_50 && latestPoint.close > latestPoint.sma_50 ? 76 : 42],
    ];
  }, [latestPoint, selectedAsset?.score, signal?.score]);

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
          <p className="mt-3 text-sm text-slate-500">Esegui `python scripts/seed_database.py --reset` e ricarica la pagina.</p>
        </Panel>
      </div>
    );
  }

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

      {error && <Panel title="Errore"><p className="text-sm text-rose-300">{error}</p></Panel>}

      {loadingAnalysis && <Panel title="Caricamento"><div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" /></Panel>}

      {!loadingAnalysis && prices && selectedAsset && (
        <>
          <div className="grid gap-4 md:grid-cols-3">
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
              <div className="mt-3">{signal ? <SignalBadge signal={signal.signal} /> : "N/D"}</div>
              <p className="mt-3 text-sm capitalize text-slate-400">Rischio {selectedAsset.risk_level.replace("_", " ")}</p>
            </article>
            <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
              <p className="text-xs font-medium uppercase text-slate-500">Score tecnico</p>
              <p className="mt-2 text-2xl font-semibold text-white">{signal?.score.toFixed(1) ?? "N/D"}/100</p>
              <p className="mt-3 text-sm text-slate-400">{selectedAsset.sector}</p>
            </article>
          </div>

          <div className="grid gap-6 xl:grid-cols-[1.5fr_0.8fr]">
            <Panel title={`${prices.symbol} - prezzo storico e medie`}>
              <div className="h-96">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={prices.prices} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                    <XAxis dataKey="date" stroke="#64748B" axisLine={false} tickLine={false} minTickGap={42} />
                    <YAxis stroke="#64748B" axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                    <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} />
                    <Line type="monotone" dataKey="close" name="Close" stroke="#22D3EE" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="sma_50" name="SMA 50" stroke="#F59E0B" strokeWidth={1.8} dot={false} connectNulls />
                    <Line type="monotone" dataKey="sma_200" name="SMA 200" stroke="#94A3B8" strokeWidth={1.8} dot={false} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel title="Score">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-5xl font-semibold text-white">{signal?.score.toFixed(0) ?? "N/D"}</p>
                  <p className="mt-2 text-sm text-slate-400">Trend, RSI, MACD e rischio</p>
                </div>
                {signal && <SignalBadge signal={signal.signal} />}
              </div>
              <p className="mt-5 text-sm text-slate-400">{signal?.technical_summary}</p>
              <div className="mt-6 space-y-4">
                {scoreBreakdown.map(([label, value]) => (
                  <div key={label}>
                    <div className="mb-2 flex justify-between text-sm">
                      <span className="text-slate-400">{label}</span>
                      <span className="font-medium text-white">{Number(value).toFixed(1)}</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-800">
                      <div className="h-2 rounded-full bg-cyan-300" style={{ width: `${Math.max(0, Math.min(100, Number(value)))}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
