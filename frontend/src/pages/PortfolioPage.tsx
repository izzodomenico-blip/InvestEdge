import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Panel } from "../components/Panel";
import { formatCurrency, formatPercent } from "../lib/format";
import { portfolioPositions } from "../lib/mockData";

export function PortfolioPage() {
  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium text-cyan-300">Capitale e pesi</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">Portafoglio</h1>
      </header>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
        <Panel title="Posizioni">
          <div className="space-y-4">
            {portfolioPositions.map((position) => (
              <div key={position.symbol} className="grid gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4 sm:grid-cols-[1fr_auto_auto] sm:items-center">
                <div>
                  <p className="font-semibold text-white">{position.symbol}</p>
                  <p className="mt-1 text-sm text-slate-500">{position.type}</p>
                </div>
                <div className="text-left sm:text-right">
                  <p className="text-sm text-slate-500">Valore</p>
                  <p className="font-semibold text-white">{formatCurrency(position.value)}</p>
                </div>
                <div className="text-left sm:text-right">
                  <p className="text-sm text-slate-500">PnL</p>
                  <p className={position.pnl >= 0 ? "font-semibold text-emerald-300" : "font-semibold text-rose-300"}>
                    {formatPercent(position.pnl)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Pesi per asset class">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={portfolioPositions} layout="vertical" margin={{ left: 20, right: 12, top: 4, bottom: 4 }}>
                <XAxis type="number" stroke="#64748B" axisLine={false} tickLine={false} />
                <YAxis dataKey="symbol" type="category" stroke="#94A3B8" axisLine={false} tickLine={false} width={74} />
                <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} />
                <Bar dataKey="weight" fill="#22D3EE" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>
    </div>
  );
}
