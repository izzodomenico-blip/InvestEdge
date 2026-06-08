import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Calculator, CheckCircle2, Play, RefreshCw } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  type Asset,
  type OrderSimulationResponse,
  type PortfolioSummary,
  type SimulatedOrder,
  type SimulatedOrderInput,
} from "../lib/api";
import { formatCurrency } from "../lib/format";

type OrderSide = "BUY" | "SELL";

type FormState = {
  symbol: string;
  order_type: OrderSide;
  quantity: string;
  price: string;
  fees: string;
  note: string;
  strategy_tag: string;
};

const initialForm: FormState = {
  symbol: "",
  order_type: "BUY",
  quantity: "",
  price: "",
  fees: "",
  note: "",
  strategy_tag: "",
};

const assetTypeLabels: Record<string, string> = {
  stock: "Azione",
  etf: "ETF",
  crypto: "Crypto",
  bond: "Bond",
  bond_etf: "Bond ETF",
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
      const [assetData, portfolioData, orderData] = await Promise.all([
        apiGet<Asset[]>("/assets"),
        apiGet<PortfolioSummary>("/portfolio"),
        apiGet<SimulatedOrder[]>("/orders"),
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

  const selectedAsset = useMemo(
    () => assets.find((asset) => asset.symbol === form.symbol) ?? null,
    [assets, form.symbol],
  );

  const selectedPosition = useMemo(
    () => portfolio?.positions.find((position) => position.symbol === form.symbol) ?? null,
    [portfolio?.positions, form.symbol],
  );

  const quantity = Number(form.quantity);
  const effectivePrice = form.price ? Number(form.price) : selectedAsset?.last_price ?? 0;
  const grossAmount = Number.isFinite(quantity * effectivePrice) ? quantity * effectivePrice : 0;
  const effectiveFees = form.fees
    ? Number(form.fees)
    : grossAmount * ((portfolio?.settings.default_fee_percent ?? 0.1) / 100);
  const netAmount = form.order_type === "BUY" ? grossAmount + effectiveFees : grossAmount - effectiveFees;
  const projectedCash = (portfolio?.cash ?? 0) + (form.order_type === "BUY" ? -netAmount : netAmount);
  const projectedWeight =
    portfolio && form.order_type === "BUY" && grossAmount > 0
      ? ((selectedPosition?.current_value ?? 0) + grossAmount) / Math.max(portfolio.total_value, 1) * 100
      : selectedPosition?.weight_percent ?? 0;

  const validationError = useMemo(() => {
    if (!form.symbol) {
      return "Seleziona un asset.";
    }
    if (!quantity || quantity <= 0) {
      return "La quantita deve essere maggiore di zero.";
    }
    if (form.price && (!effectivePrice || effectivePrice <= 0)) {
      return "Il prezzo deve essere maggiore di zero.";
    }
    if (form.fees && Number(form.fees) < 0) {
      return "Le commissioni non possono essere negative.";
    }
    if (form.order_type === "BUY" && portfolio && netAmount > portfolio.cash) {
      return "Cash insufficiente per questo BUY simulato.";
    }
    if (form.order_type === "SELL" && (!selectedPosition || quantity > selectedPosition.quantity)) {
      return "Quantita insufficiente per questo SELL simulato.";
    }
    return null;
  }, [effectivePrice, form.fees, form.order_type, form.price, form.symbol, netAmount, portfolio, quantity, selectedPosition]);

  const previewWarnings = useMemo(() => {
    const warnings: string[] = [];
    if (!portfolio || !selectedAsset) {
      return warnings;
    }
    if (form.order_type === "BUY" && projectedWeight > portfolio.settings.max_single_asset_weight) {
      warnings.push(`Peso stimato ${projectedWeight.toFixed(1)}%, oltre il limite per singolo asset.`);
    }
    if (selectedAsset.asset_type === "crypto") {
      const currentCrypto = portfolio.allocation_by_asset_type.crypto ?? 0;
      const projectedCrypto = form.order_type === "BUY"
        ? currentCrypto + (grossAmount / Math.max(portfolio.total_value, 1)) * 100
        : currentCrypto;
      if (projectedCrypto > portfolio.settings.crypto_max_weight) {
        warnings.push(`Esposizione crypto stimata ${projectedCrypto.toFixed(1)}%, oltre la soglia configurata.`);
      }
    }
    return warnings;
  }, [form.order_type, grossAmount, portfolio, projectedWeight, selectedAsset]);

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
      const payload: SimulatedOrderInput = {
        symbol: form.symbol,
        order_type: form.order_type,
        quantity,
        price: form.price ? effectivePrice : undefined,
        fees: form.fees ? Number(form.fees) : undefined,
        note: form.note || undefined,
        strategy_tag: form.strategy_tag || undefined,
      };
      const result = await apiPost<OrderSimulationResponse>("/orders/simulate", payload);
      setPortfolio(result.updated_portfolio_summary);
      setOrders(await apiGet<SimulatedOrder[]>("/orders"));
      setSuccess(`${result.order.order_type} simulato su ${result.order.symbol} completato.`);
      setForm((current) => ({ ...initialForm, symbol: current.symbol, order_type: current.order_type }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante la simulazione ordine.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <Panel title="Simulatore">
        <div className="h-56 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Paper trading"
        index="04"
        title="Simulatore"
        subtitle="Inserisci ordini BUY/SELL simulati: aggiornano cash, prezzo medio e P/L senza inviare nulla a broker reali."
        actions={
          <PageHeaderAction
            onClick={() => void loadData()}
            icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
          >
            Ricarica
          </PageHeaderAction>
        }
      />

      {error && (
        <div className="rounded-lg border border-rose-300/20 bg-rose-400/10 p-4 text-sm text-rose-200">
          {error}
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-300/20 bg-emerald-400/10 p-4 text-sm text-emerald-200">
          <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          {success}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1fr_0.9fr]">
        <Panel title="Ordine simulato">
          <form onSubmit={(event) => void submitOrder(event)} className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Asset</span>
              <select
                value={form.symbol}
                onChange={(event) => setForm((current) => ({ ...current, symbol: event.target.value }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              >
                {assets.map((asset) => (
                  <option key={asset.symbol} value={asset.symbol}>
                    {asset.symbol} - {asset.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Operazione</span>
              <select
                value={form.order_type}
                onChange={(event) => setForm((current) => ({ ...current, order_type: event.target.value as OrderSide }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Quantita</span>
              <input
                value={form.quantity}
                onChange={(event) => setForm((current) => ({ ...current, quantity: event.target.value }))}
                type="number"
                min="0"
                step="any"
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Prezzo opzionale</span>
              <input
                value={form.price}
                onChange={(event) => setForm((current) => ({ ...current, price: event.target.value }))}
                type="number"
                min="0"
                step="any"
                placeholder={selectedAsset?.last_price ? `${selectedAsset.last_price.toFixed(2)}` : "Ultimo close"}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Commissioni opzionali</span>
              <input
                value={form.fees}
                onChange={(event) => setForm((current) => ({ ...current, fees: event.target.value }))}
                type="number"
                min="0"
                step="any"
                placeholder={`${portfolio?.settings.default_fee_percent ?? 0.1}% default`}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <label className="space-y-2">
              <span className="text-sm text-slate-400">Strategy tag</span>
              <input
                value={form.strategy_tag}
                onChange={(event) => setForm((current) => ({ ...current, strategy_tag: event.target.value }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <label className="space-y-2 md:col-span-2">
              <span className="text-sm text-slate-400">Note</span>
              <textarea
                value={form.note}
                onChange={(event) => setForm((current) => ({ ...current, note: event.target.value }))}
                rows={3}
                className="w-full resize-none rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <button
              disabled={submitting || Boolean(validationError)}
              className="md:col-span-2 mt-2 inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              {submitting ? "Simulazione..." : "Conferma simulazione"}
            </button>
          </form>
        </Panel>

        <Panel title="Preview operazione">
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-sm text-slate-500">Asset selezionato</p>
              <p className="mt-1 font-semibold text-white">
                {selectedAsset ? `${selectedAsset.symbol} - ${assetTypeLabels[selectedAsset.asset_type] ?? selectedAsset.asset_type}` : "N/D"}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-sm text-slate-500">Controvalore</p>
                <p className="mt-1 font-semibold text-white">{formatCurrency(grossAmount, selectedAsset?.currency ?? "USD")}</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-sm text-slate-500">Commissioni</p>
                <p className="mt-1 font-semibold text-white">{formatCurrency(effectiveFees, selectedAsset?.currency ?? "USD")}</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-sm text-slate-500">Cash dopo trade</p>
                <p className={`mt-1 font-semibold ${projectedCash >= 0 ? "text-white" : "text-rose-300"}`}>{formatCurrency(projectedCash, "EUR")}</p>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-sm text-slate-500">Peso stimato</p>
                <p className="mt-1 font-semibold text-cyan-200">{projectedWeight.toFixed(2)}%</p>
              </div>
            </div>

            {validationError && (
              <div className="flex items-start gap-2 rounded-lg border border-rose-300/20 bg-rose-400/10 p-4 text-sm text-rose-200">
                <AlertTriangle className="mt-0.5 h-4 w-4" aria-hidden="true" />
                {validationError}
              </div>
            )}
            {!validationError && previewWarnings.length === 0 && (
              <div className="flex items-start gap-2 rounded-lg border border-emerald-300/20 bg-emerald-400/10 p-4 text-sm text-emerald-200">
                <Calculator className="mt-0.5 h-4 w-4" aria-hidden="true" />
                Operazione compatibile con i limiti configurati.
              </div>
            )}
            {previewWarnings.map((warning) => (
              <div key={warning} className="flex items-start gap-2 rounded-lg border border-amber-300/20 bg-amber-400/10 p-4 text-sm text-amber-100">
                <AlertTriangle className="mt-0.5 h-4 w-4" aria-hidden="true" />
                {warning}
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Storico ordini simulati">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                <th className="px-3 pb-3 pl-0 font-medium">Data</th>
                <th className="px-3 pb-3 font-medium">Symbol</th>
                <th className="px-3 pb-3 font-medium">Tipo</th>
                <th className="px-3 pb-3 text-right font-medium">Quantita</th>
                <th className="px-3 pb-3 text-right font-medium">Prezzo</th>
                <th className="px-3 pb-3 text-right font-medium">Netto</th>
                <th className="px-3 pb-3 pr-0 font-medium">Tag</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {orders.map((order) => (
                <tr key={order.id} className="text-sm">
                  <td className="px-3 py-4 pl-0 text-slate-400">{new Date(order.order_date).toLocaleString("it-IT")}</td>
                  <td className="px-3 py-4 font-semibold text-white">{order.symbol}</td>
                  <td className={`px-3 py-4 font-semibold ${order.order_type === "BUY" ? "text-emerald-300" : "text-rose-300"}`}>{order.order_type}</td>
                  <td className="px-3 py-4 text-right text-slate-300">{order.quantity.toLocaleString("it-IT")}</td>
                  <td className="px-3 py-4 text-right text-slate-300">{formatCurrency(order.price, "USD")}</td>
                  <td className="px-3 py-4 text-right text-white">{formatCurrency(order.net_amount, "USD")}</td>
                  <td className="px-3 py-4 pr-0 text-slate-400">{order.strategy_tag ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {orders.length === 0 && <p className="py-8 text-sm text-slate-400">Nessun ordine simulato.</p>}
        </div>
      </Panel>
    </div>
  );
}
