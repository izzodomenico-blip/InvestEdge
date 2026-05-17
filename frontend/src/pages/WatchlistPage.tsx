import { Plus, Search } from "lucide-react";

import { Panel } from "../components/Panel";
import { SignalBadge } from "../components/SignalBadge";
import { formatCurrency, formatPercent } from "../lib/format";
import { watchlist } from "../lib/mockData";

export function WatchlistPage() {
  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">Multi-asset</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Watchlist</h1>
        </div>
        <button className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20">
          <Plus className="h-4 w-4" aria-hidden="true" />
          Aggiungi asset
        </button>
      </header>

      <Panel>
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
          <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
          <input
            className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
            placeholder="Cerca ticker, ETF, crypto, bond ETF"
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                <th className="pb-3 font-medium">Asset</th>
                <th className="pb-3 font-medium">Tipo</th>
                <th className="pb-3 text-right font-medium">Prezzo</th>
                <th className="pb-3 text-right font-medium">Giorno</th>
                <th className="pb-3 text-center font-medium">Segnale</th>
                <th className="pb-3 text-right font-medium">Score</th>
                <th className="pb-3 font-medium">Esposizione</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {watchlist.map((asset) => (
                <tr key={asset.symbol} className="text-sm">
                  <td className="py-4">
                    <p className="font-semibold text-white">{asset.symbol}</p>
                    <p className="mt-1 text-slate-500">{asset.name}</p>
                  </td>
                  <td className="py-4 text-slate-300">{asset.type}</td>
                  <td className="py-4 text-right font-medium text-white">{formatCurrency(asset.price)}</td>
                  <td className={`py-4 text-right font-semibold ${asset.change >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                    {formatPercent(asset.change)}
                  </td>
                  <td className="py-4 text-center">
                    <SignalBadge signal={asset.signal} />
                  </td>
                  <td className="py-4 text-right text-slate-200">{asset.score}/100</td>
                  <td className="py-4 text-slate-400">{asset.exposure}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
