import { useEffect, useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Layers, Scale } from "lucide-react";

import { Panel } from "./Panel";
import {
  apiGet,
  apiPost,
  type AllocationMethod,
  type AllocationPlan,
  type AllocationPlanInput,
  type Asset,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const methodLabels: Record<AllocationMethod, string> = {
  EQUAL_WEIGHT: "Equal weight",
  RISK_PARITY: "Risk parity (inverse vol)",
  SCORE_WEIGHTED: "Score weighted",
  VOL_TARGET: "Volatility targeting",
};

const methodHints: Record<AllocationMethod, string> = {
  EQUAL_WEIGHT: "Stesso peso a ogni asset, semplice e robusto.",
  RISK_PARITY: "Peso inversamente proporzionale alla volatilita: ogni asset contribuisce un rischio simile.",
  SCORE_WEIGHTED: "Peso proporzionale allo score tecnico sopra 50.",
  VOL_TARGET: "Risk parity, poi scala l'investito per centrare una volatilita target tenendo cash a riserva.",
};

const sliceColors = ["#22D3EE", "#A78BFA", "#34D399", "#F59E0B", "#FB7185", "#60A5FA", "#E0B062", "#2DD4BF"];

export function AllocationPlanner() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [method, setMethod] = useState<AllocationMethod>("RISK_PARITY");
  const [totalCapital, setTotalCapital] = useState("100000");
  const [targetVol, setTargetVol] = useState("15");
  const [maxWeight, setMaxWeight] = useState("");
  const [plan, setPlan] = useState<AllocationPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const data = await apiGet<Asset[]>("/assets");
        setAssets(data);
        setSelected(data.slice(0, 5).map((asset) => asset.symbol));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Errore caricamento asset.");
      }
    })();
  }, []);

  function toggle(symbol: string) {
    setSelected((current) =>
      current.includes(symbol) ? current.filter((item) => item !== symbol) : [...current, symbol],
    );
  }

  async function runPlan() {
    setError(null);
    if (selected.length === 0) {
      setError("Seleziona almeno un asset.");
      return;
    }
    if (Number(totalCapital) <= 0) {
      setError("Il capitale deve essere positivo.");
      return;
    }
    setLoading(true);
    try {
      const payload: AllocationPlanInput = {
        symbols: selected,
        method,
        total_capital: Number(totalCapital),
        target_volatility: method === "VOL_TARGET" ? Number(targetVol) / 100 : null,
        max_weight: maxWeight.trim() === "" ? null : Number(maxWeight) / 100,
      };
      setPlan(await apiPost<AllocationPlan>("/portfolio/allocation/plan", payload));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il calcolo del piano.");
    } finally {
      setLoading(false);
    }
  }

  const pieData = useMemo(() => {
    if (!plan) {
      return [];
    }
    const slices = plan.allocations
      .filter((item) => item.weight_percent > 0)
      .map((item, index) => ({
        name: item.symbol,
        value: item.weight_percent,
        color: sliceColors[index % sliceColors.length],
      }));
    if (plan.cash_buffer > 0) {
      slices.push({
        name: "Cash",
        value: Number(((plan.cash_buffer / plan.total_capital) * 100).toFixed(2)),
        color: "#475569",
      });
    }
    return slices;
  }, [plan]);

  return (
    <Panel
      eyebrow="Gestione capitale"
      title="Pianificatore allocazione"
      action={
        <span className="inline-flex items-center gap-2 rounded-md border border-violet-300/30 bg-violet-400/10 px-3 py-1.5 text-xs font-semibold text-violet-100">
          <Scale className="h-3.5 w-3.5" aria-hidden="true" />
          Piano, non ordini
        </span>
      }
    >
      <div className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
        <div className="space-y-4">
          <label className="block space-y-2">
            <span className="text-sm text-slate-400">Metodo</span>
            <select
              value={method}
              onChange={(event) => setMethod(event.target.value as AllocationMethod)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-violet-300/60"
            >
              {Object.entries(methodLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <span className="block text-xs text-slate-500">{methodHints[method]}</span>
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Capitale</span>
              <input
                type="number"
                value={totalCapital}
                onChange={(event) => setTotalCapital(event.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-violet-300/60"
              />
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Peso max % (opz.)</span>
              <input
                type="number"
                value={maxWeight}
                placeholder="nessuno"
                onChange={(event) => setMaxWeight(event.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-violet-300/60"
              />
            </label>
            {method === "VOL_TARGET" && (
              <label className="space-y-2">
                <span className="text-sm text-slate-400">Volatilita target %</span>
                <input
                  type="number"
                  value={targetVol}
                  onChange={(event) => setTargetVol(event.target.value)}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-violet-300/60"
                />
              </label>
            )}
          </div>

          <div>
            <p className="mb-2 text-sm text-slate-400">Asset ({selected.length})</p>
            <div className="grid max-h-52 gap-2 overflow-y-auto rounded-md border border-slate-800 bg-slate-900/40 p-3 sm:grid-cols-2">
              {assets.map((asset) => (
                <label key={asset.symbol} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-slate-300 hover:bg-slate-800/70">
                  <input
                    type="checkbox"
                    checked={selected.includes(asset.symbol)}
                    onChange={() => toggle(asset.symbol)}
                    className="h-4 w-4 accent-violet-300"
                  />
                  <span className="font-semibold text-white">{asset.symbol}</span>
                  <span className="truncate text-slate-500">{asset.asset_type}</span>
                </label>
              ))}
            </div>
          </div>

          <button
            onClick={() => void runPlan()}
            disabled={loading}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-violet-300/30 bg-violet-400/15 px-4 py-2.5 text-sm font-semibold text-violet-100 transition hover:bg-violet-400/25 disabled:opacity-60"
          >
            <Layers className={`h-4 w-4 ${loading ? "animate-pulse" : ""}`} aria-hidden="true" />
            {loading ? "Calcolo..." : "Calcola allocazione"}
          </button>

          {error && <p className="text-sm text-rose-300">{error}</p>}
        </div>

        <div className="space-y-4">
          {plan ? (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase text-slate-500">Investito</p>
                  <p className="num mt-1 text-lg font-semibold text-white">{formatCurrency(plan.invested_capital, "EUR")}</p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase text-slate-500">Cash buffer</p>
                  <p className="num mt-1 text-lg font-semibold text-amber-200">{formatCurrency(plan.cash_buffer, "EUR")}</p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase text-slate-500">Vol stimata</p>
                  <p className="num mt-1 text-lg font-semibold text-cyan-200">{formatPercent(plan.estimated_volatility * 100)}</p>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={82} paddingAngle={2}>
                        {pieData.map((slice) => (
                          <Cell key={slice.name} fill={slice.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }}
                        formatter={(value) => [`${Number(value).toFixed(1)}%`, "Peso"]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full min-w-[360px] border-collapse">
                    <thead>
                      <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                        <th className="px-2 pb-2 pl-0 font-medium">Asset</th>
                        <th className="px-2 pb-2 text-right font-medium">Peso</th>
                        <th className="px-2 pb-2 text-right font-medium">Capitale</th>
                        <th className="px-2 pb-2 pr-0 text-right font-medium">Qty</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/80">
                      {plan.allocations.map((item) => (
                        <tr key={item.symbol} className="text-sm">
                          <td className="px-2 py-2 pl-0">
                            <span className="font-semibold text-white">{item.symbol}</span>
                            <span className="ml-2 text-xs text-slate-500">vol {formatPercent(item.volatility * 100)}</span>
                          </td>
                          <td className="num px-2 py-2 text-right text-slate-200">{item.weight_percent.toFixed(1)}%</td>
                          <td className="num px-2 py-2 text-right text-slate-300">{formatCurrency(item.capital, "EUR")}</td>
                          <td className="num px-2 py-2 pr-0 text-right font-semibold text-white">{item.suggested_quantity.toLocaleString("it-IT")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {plan.notes.length > 0 && (
                <ul className="space-y-1 rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-400">
                  {plan.notes.map((note) => (
                    <li key={note}>· {note}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <div className="flex h-full min-h-48 items-center justify-center rounded-lg border border-dashed border-slate-800 bg-slate-900/30 p-6 text-center text-sm text-slate-400">
              Scegli metodo, capitale e asset, poi calcola il piano di allocazione. Le quantita suggerite si applicano manualmente dal simulatore.
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
