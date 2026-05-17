import { Calculator, Play } from "lucide-react";

import { Panel } from "../components/Panel";
import { formatCurrency } from "../lib/format";

const estimatedValue = 12 * 427.18;

export function SimulatorPage() {
  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium text-cyan-300">Paper trading</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">Simulatore</h1>
      </header>

      <div className="grid gap-6 xl:grid-cols-[1fr_0.9fr]">
        <Panel title="Ordine simulato">
          <form className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Asset</span>
              <select className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                <option>MSFT - Microsoft Corp.</option>
                <option>VWCE - Vanguard FTSE All-World</option>
                <option>BTC - Bitcoin</option>
                <option>AGGH - Global Aggregate Bond</option>
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Lato</span>
              <select className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                <option>BUY</option>
                <option>SELL</option>
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Quantita</span>
              <input className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" defaultValue="12" />
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Prezzo limite</span>
              <input className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" defaultValue="427.18" />
            </label>
            <button className="md:col-span-2 mt-2 inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20">
              <Play className="h-4 w-4" aria-hidden="true" />
              Simula ordine
            </button>
          </form>
        </Panel>

        <Panel title="Anteprima rischio">
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <span className="text-sm text-slate-400">Controvalore</span>
              <span className="font-semibold text-white">{formatCurrency(estimatedValue)}</span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <span className="text-sm text-slate-400">Peso dopo trade</span>
              <span className="font-semibold text-amber-300">23%</span>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <span className="text-sm text-slate-400">Cash residuo</span>
              <span className="font-semibold text-white">{formatCurrency(4500 - estimatedValue)}</span>
            </div>
            <div className="rounded-lg border border-emerald-300/20 bg-emerald-400/10 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-emerald-200">
                <Calculator className="h-4 w-4" aria-hidden="true" />
                Esito simulazione
              </div>
              <p className="mt-2 text-sm text-slate-300">Ordine compatibile con il limite di concentrazione mock.</p>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
