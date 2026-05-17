import { RotateCcw } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Panel } from "../components/Panel";
import { backtestCurve } from "../lib/mockData";

export function BacktestPage() {
  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium text-cyan-300">Strategie simulate</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">Backtest</h1>
      </header>

      <div className="grid gap-6 xl:grid-cols-[0.8fr_1.4fr]">
        <Panel title="Parametri">
          <div className="space-y-4">
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Asset</span>
              <select className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                <option>VWCE</option>
                <option>MSFT</option>
                <option>BTC</option>
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Strategia</span>
              <select className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                <option>Media mobile 50/200</option>
                <option>Buy and hold</option>
                <option>Risk parity mock</option>
              </select>
            </label>
            <button className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20">
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Esegui backtest
            </button>
          </div>
        </Panel>

        <Panel title="Equity curve simulata">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={backtestCurve} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                <XAxis dataKey="period" stroke="#64748B" axisLine={false} tickLine={false} />
                <YAxis stroke="#64748B" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} />
                <Line type="monotone" dataKey="strategy" stroke="#22D3EE" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="benchmark" stroke="#94A3B8" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">CAGR</p>
              <p className="mt-1 text-xl font-semibold text-emerald-300">10,6%</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Max drawdown</p>
              <p className="mt-1 text-xl font-semibold text-amber-300">-11,8%</p>
            </div>
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Sharpe mock</p>
              <p className="mt-1 text-xl font-semibold text-cyan-300">0,92</p>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
