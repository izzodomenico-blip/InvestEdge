import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { technicalSeries } from "../lib/mockData";

export function AnalysisPage() {
  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">Technical analysis</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Analisi Asset</h1>
        </div>
        <select className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
          <option>MSFT</option>
          <option>VWCE</option>
          <option>BTC</option>
          <option>AGGH</option>
        </select>
      </header>

      <div className="grid gap-6 xl:grid-cols-[1.5fr_0.8fr]">
        <Panel title="Prezzo e media mobile">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={technicalSeries} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                <XAxis dataKey="day" stroke="#64748B" axisLine={false} tickLine={false} />
                <YAxis stroke="#64748B" axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} />
                <Line type="monotone" dataKey="price" stroke="#22D3EE" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="sma" stroke="#F59E0B" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Score">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-5xl font-semibold text-white">78</p>
              <p className="mt-2 text-sm text-slate-400">Momentum, trend e rischio aggregati</p>
            </div>
            <SignalBadge signal="BUY" />
          </div>
          <div className="mt-6 space-y-4">
            {[
              ["Trend", 84],
              ["Momentum", 76],
              ["Volatilita", 58],
              ["Qualita", 81],
            ].map(([label, value]) => (
              <div key={label}>
                <div className="mb-2 flex justify-between text-sm">
                  <span className="text-slate-400">{label}</span>
                  <span className="font-medium text-white">{value}</span>
                </div>
                <div className="h-2 rounded-full bg-slate-800">
                  <div className="h-2 rounded-full bg-cyan-300" style={{ width: `${value}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
