import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Calculator, CheckCircle2, Play, RefreshCw, Info } from "lucide-react";

import { Panel } from "../components/Panel";
import {
  api,
  type Asset,
  type PortfolioSummary,
  type SimulatedOrder,
  type SimulatedOrderInput,
} from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

type FormState = {
  symbol: string;
  order_type: "BUY" | "SELL";
  quantity: string;
  price: string;
  use_market_price: boolean;
  fees: string;
  note: string;
  strategy_tag: string;
};

const initialForm: FormState = {
  symbol: "",
  order_type: "BUY",
  quantity: "",
  price: "",
  use_market_price: true,
  fees: "0.1",
  note: "",
  strategy_tag: "Manual Trade",
};

export function SimulatorPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [orders, setOrders] = useState<SimulatedOrder[]>([]);
  const [form, setForm] = useState<FormState>(initialForm);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const [assetData, portfolioData, orderData] = await Promise.all([
        api.getAssets(),
        api.getPortfolio(pId),
        api.listOrders(pId),
      ]);
      setAssets(assetData);
      setPortfolio(portfolioData);
      setOrders(orderData);
      setForm((current) => ({
        ...current,
        symbol: current.symbol || assetData[0]?.symbol || "",
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento del simulatore.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const selectedAsset = useMemo(() => assets.find((a) => a.symbol === form.symbol), [assets, form.symbol]);

  const effectivePrice = useMemo(() => {
    if (form.use_market_price) {
      return selectedAsset?.last_price || 0;
    }
    return Number(form.price) || 0;
  }, [form.use_market_price, form.price, selectedAsset]);

  const quantity = Number(form.quantity) || 0;
  const grossAmount = quantity * effectivePrice;
  const fees = grossAmount * (Number(form.fees) / 100);
  const netAmount = form.order_type === "BUY" ? grossAmount + fees : grossAmount - fees;

  const isReadOnly = useMemo(() => portfolio?.settings?.portfolio_type === "EXTERNAL_TRACKER", [portfolio]);

  const validationError = useMemo(() => {
    if (isReadOnly) return "Portafoglio importato in sola lettura. Clonalo in un paper portfolio per simulare operazioni.";
    if (!form.symbol) return "Seleziona un asset.";
    if (quantity <= 0) return "La quantità deve essere maggiore di zero.";
    if (effectivePrice <= 0) return "Il prezzo deve essere maggiore di zero.";
    if (form.order_type === "BUY" && portfolio && portfolio.cash < netAmount) {
      return `Liquidità insufficiente. Disponibile: ${formatCurrency(portfolio.cash)}`;
    }
    if (form.order_type === "SELL" && portfolio) {
      const pos = portfolio.positions.find((p) => p.symbol === form.symbol);
      if (!pos || pos.quantity < quantity) {
        return `Quantità insufficiente in portafoglio. Disponibile: ${pos?.quantity || 0}`;
      }
    }
    return null;
  }, [form.symbol, form.order_type, quantity, effectivePrice, netAmount, portfolio]);

  async function submitOrder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSuccess(null);
    setError(null);
    if (validationError) {
      setError(validationError);
      return;
    }
    setSubmitting(true);
    try {
      const pIdStr = localStorage.getItem("activePortfolioId");
      const pId = pIdStr ? parseInt(pIdStr) : undefined;

      const payload: SimulatedOrderInput = {
        symbol: form.symbol,
        order_type: form.order_type,
        quantity,
        price: form.price ? effectivePrice : undefined,
        fees: form.fees ? Number(form.fees) : undefined,
        note: form.note || undefined,
        strategy_tag: form.strategy_tag || undefined,
      };
      const result = await api.simulateOrder(payload, pId);
      setPortfolio(result.updated_portfolio_summary);
      setOrders(await api.listOrders(pId));
      setSuccess(`${result.order.order_type} simulato su ${result.order.symbol} completato.`);
      setForm((current) => ({ ...initialForm, symbol: current.symbol, order_type: current.order_type }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante la simulazione ordine.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading && assets.length === 0) {
    return <div className="p-8 text-center text-slate-500 italic">Caricamento simulatore...</div>;
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end border-b border-slate-800 pb-6">
        <div>
          <p className="text-sm font-medium text-cyan-300">Paper trading</p>
          <h1 className="mt-2 text-3xl font-bold text-white tracking-tight">Simulatore Ordini</h1>
          <p className="text-slate-500 text-sm mt-1">Sperimenta operazioni sul portafoglio attivo senza rischi.</p>
        </div>
        <div className="flex gap-2">
           <button
            onClick={() => void loadData()}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:border-cyan-300/40 hover:text-cyan-100"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Ricarica
          </button>
        </div>
      </header>

      {error && (
        <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 p-4 text-sm text-rose-200 flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-rose-400" />
          {error}
        </div>
      )}

      {success && (
        <div className="rounded-lg border border-emerald-300/20 bg-emerald-400/10 p-4 text-sm text-emerald-200 flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
          {success}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Nuovo ordine simulato" icon={<Play className="h-4 w-4 text-cyan-400" />}>
          {isReadOnly && (
            <div className="mb-6 p-4 bg-blue-900/20 border border-blue-800 rounded-lg flex items-start gap-3">
              <Info className="h-5 w-5 text-blue-400 shrink-0" />
              <div>
                <p className="text-sm font-bold text-blue-200">Modalità Sola Lettura</p>
                <p className="text-xs text-blue-300/80 mt-1">
                  Questo portafoglio è sincronizzato con Google Sheets. 
                  Per simulare nuovi ordini, vai alla gestione portafogli e usa la funzione "Clona" 
                  per creare una copia Paper Trading modificabile.
                </p>
              </div>
            </div>
          )}
          <form onSubmit={submitOrder} className={`space-y-6 ${isReadOnly ? 'opacity-50 pointer-events-none' : ''}`}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Asset</label>
                <select
                  value={form.symbol}
                  onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-400"
                >
                  {assets.map((a) => (
                    <option key={a.symbol} value={a.symbol}>
                      {a.symbol} - {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Tipo operazione</label>
                <div className="flex gap-2 p-1 bg-slate-900 rounded-md border border-slate-800">
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, order_type: "BUY" })}
                    className={`flex-1 rounded py-1.5 text-xs font-bold transition ${form.order_type === "BUY" ? "bg-emerald-500 text-white" : "text-slate-500 hover:text-slate-300"}`}
                  >
                    ACQUISTO
                  </button>
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, order_type: "SELL" })}
                    className={`flex-1 rounded py-1.5 text-xs font-bold transition ${form.order_type === "SELL" ? "bg-rose-500 text-white" : "text-slate-500 hover:text-slate-300"}`}
                  >
                    VENDITA
                  </button>
                </div>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Quantità</label>
                <input
                  type="number"
                  step="any"
                  value={form.quantity}
                  onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                  placeholder="0.00"
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-400 font-mono"
                  required
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Prezzo</label>
                  <label className="flex items-center gap-1.5 text-[10px] text-slate-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.use_market_price}
                      onChange={(e) => setForm({ ...form, use_market_price: e.target.checked })}
                      className="rounded border-slate-700 bg-slate-900 text-cyan-500"
                    />
                    Prezzo mercato
                  </label>
                </div>
                <input
                  type="number"
                  step="any"
                  value={form.use_market_price ? (selectedAsset?.last_price || 0) : form.price}
                  onChange={(e) => setForm({ ...form, price: e.target.value })}
                  disabled={form.use_market_price}
                  placeholder="0.00"
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-400 font-mono disabled:opacity-50"
                  required
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 pt-2 border-t border-slate-800">
               <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Commissioni (%)</label>
                <input
                  type="number"
                  step="0.01"
                  value={form.fees}
                  onChange={(e) => setForm({ ...form, fees: e.target.value })}
                  className="w-full rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2 text-slate-300 outline-none focus:border-cyan-400 text-sm"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Tag Strategia</label>
                <input
                  type="text"
                  value={form.strategy_tag}
                  onChange={(e) => setForm({ ...form, strategy_tag: e.target.value })}
                  className="w-full rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2 text-slate-300 outline-none focus:border-cyan-400 text-sm"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wider text-slate-500">Nota ordine</label>
              <textarea
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-400 text-sm"
                rows={2}
                placeholder="Perché stai facendo questa operazione?"
              />
            </div>

            <button
              type="submit"
              disabled={submitting || !!validationError}
              className="w-full rounded-md bg-cyan-500 py-3 text-sm font-bold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50 disabled:grayscale flex items-center justify-center gap-2"
            >
              {submitting ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              ESEGUI SIMULAZIONE
            </button>
          </form>
        </Panel>

        <div className="space-y-6">
          <Panel title="Riepilogo operazione" icon={<Calculator className="h-4 w-4 text-slate-400" />}>
            <div className="space-y-4">
              <div className="flex items-center justify-between py-2 border-b border-slate-800/50">
                <span className="text-sm text-slate-400">Controvalore lordo</span>
                <span className="text-sm font-mono text-white">{formatCurrency(grossAmount)}</span>
              </div>
              <div className="flex items-center justify-between py-2 border-b border-slate-800/50">
                <span className="text-sm text-slate-400">Commissioni stimative</span>
                <span className="text-sm font-mono text-rose-400">-{formatCurrency(fees)}</span>
              </div>
              <div className="flex items-center justify-between py-3 border-b border-slate-700">
                <span className="text-sm font-bold text-slate-200">Totale netto operazione</span>
                <span className="text-lg font-bold text-white">{formatCurrency(netAmount)}</span>
              </div>
              
              <div className="mt-2 rounded bg-slate-900/50 p-3">
                 <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-slate-500 uppercase">Liquidità dopo ordine</span>
                    <span className="font-bold text-emerald-400">
                       {portfolio ? formatCurrency(portfolio.cash - (form.order_type === 'BUY' ? netAmount : -netAmount)) : "N/D"}
                    </span>
                 </div>
              </div>

              {validationError && (
                <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-400/5 p-3 rounded border border-rose-500/20">
                   <AlertTriangle className="h-4 w-4 shrink-0" />
                   {validationError}
                </div>
              )}
            </div>
          </Panel>

          <Panel title="Stato portafoglio" icon={<RefreshCw className="h-4 w-4 text-slate-400" />}>
            {portfolio ? (
              <div className="space-y-4">
                 <div>
                    <span className="text-[10px] uppercase font-bold text-slate-500">Valore totale</span>
                    <p className="text-2xl font-bold text-white">{formatCurrency(portfolio.total_value)}</p>
                 </div>
                 <div className="grid grid-cols-2 gap-4">
                    <div>
                       <span className="text-[10px] uppercase font-bold text-slate-500">Cash disponibile</span>
                       <p className="text-sm font-semibold text-emerald-400">{formatCurrency(portfolio.cash)}</p>
                    </div>
                    <div>
                       <span className="text-[10px] uppercase font-bold text-slate-500">Esposizione</span>
                       <p className="text-sm font-semibold text-white">{formatPercent((portfolio.invested_value / portfolio.total_value) * 100)}</p>
                    </div>
                 </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500 italic">Dati portafoglio non disponibili.</p>
            )}
          </Panel>
        </div>
      </div>

      <Panel title="Ultimi ordini simulati" className="mt-8">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-800 text-[10px] uppercase text-slate-500 tracking-wider">
                <th className="px-3 pb-3">Data</th>
                <th className="px-3 pb-3">Tipo</th>
                <th className="px-3 pb-3">Asset</th>
                <th className="px-3 pb-3 text-right">Quantità</th>
                <th className="px-3 pb-3 text-right">Prezzo</th>
                <th className="px-3 pb-3 text-right">Netto</th>
                <th className="px-3 pb-3">Nota</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {orders.map((order) => (
                <tr key={order.id} className="text-sm hover:bg-slate-800/20">
                  <td className="px-3 py-3 text-slate-400 text-xs">{new Date(order.order_date).toLocaleDateString()}</td>
                  <td className="px-3 py-3">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${order.order_type === 'BUY' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                      {order.order_type}
                    </span>
                  </td>
                  <td className="px-3 py-3 font-bold text-white">{order.symbol}</td>
                  <td className="px-3 py-3 text-right font-mono text-xs">{order.quantity.toLocaleString()}</td>
                  <td className="px-3 py-3 text-right font-mono text-xs">{formatCurrency(order.price)}</td>
                  <td className="px-3 py-3 text-right font-mono text-xs text-white">{formatCurrency(order.net_amount)}</td>
                  <td className="px-3 py-3 text-slate-500 text-xs truncate max-w-[200px]">{order.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {orders.length === 0 && <p className="py-8 text-center text-sm text-slate-500 italic">Nessun ordine simulato trovato per questo portafoglio.</p>}
        </div>
      </Panel>
    </div>
  );
}
