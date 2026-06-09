import { useState } from "react";
import { ShoppingCart, TrendingDown, X } from "lucide-react";

import { apiPost, type OrderSimulationResponse, type SimulatedOrderInput } from "../lib/api";
import { formatCurrency } from "../lib/format";

type Props = {
  symbol: string;
  price: number | null | undefined;
  side?: "BUY" | "SELL";
  maxQuantity?: number;
  currency?: string;
  onDone?: () => void;
  className?: string;
  label?: string;
};

export function TradeButton({
  symbol,
  price,
  side = "BUY",
  maxQuantity,
  currency = "EUR",
  onDone,
  className,
  label,
}: Props) {
  const isBuy = side === "BUY";
  const px = price ?? 0;
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("1000");
  const [qty, setQty] = useState(maxQuantity ? String(maxQuantity) : "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const buyQty = px > 0 ? Number(amount) / px : 0;

  function openModal(e: React.MouseEvent) {
    e.stopPropagation();
    setErr(null);
    setMsg(null);
    setQty(maxQuantity ? String(maxQuantity) : "");
    setOpen(true);
  }

  function close(e: React.MouseEvent) {
    e.stopPropagation();
    setOpen(false);
  }

  async function confirm(e: React.MouseEvent) {
    e.stopPropagation();
    setErr(null);
    setMsg(null);
    if (!(px > 0)) {
      setErr("Prezzo non disponibile: aggiorna i dati dal Data Center.");
      return;
    }
    const quantity = isBuy ? buyQty : Number(qty);
    if (!(quantity > 0)) {
      setErr("Quantità non valida.");
      return;
    }
    setBusy(true);
    try {
      const payload: SimulatedOrderInput = { symbol, order_type: side, quantity };
      await apiPost<OrderSimulationResponse>("/orders/simulate", payload);
      setMsg(
        isBuy
          ? `Comprato ✓ ${quantity.toFixed(4)} quote di ${symbol}. È nel tuo portafoglio.`
          : `Venduto ✓ ${quantity.toFixed(4)} quote di ${symbol}.`,
      );
      onDone?.();
      setTimeout(() => setOpen(false), 1100);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Operazione non riuscita.");
    } finally {
      setBusy(false);
    }
  }

  const defaultClass = isBuy
    ? "inline-flex items-center gap-1.5 rounded-md border border-emerald-300/30 bg-emerald-400/15 px-3 py-1.5 text-xs font-semibold text-emerald-100 transition hover:bg-emerald-400/25"
    : "inline-flex items-center gap-1.5 rounded-md border border-rose-300/30 bg-rose-400/15 px-3 py-1.5 text-xs font-semibold text-rose-100 transition hover:bg-rose-400/25";

  return (
    <>
      <button type="button" onClick={openModal} className={className ?? defaultClass}>
        {isBuy ? <ShoppingCart className="h-3.5 w-3.5" aria-hidden="true" /> : <TrendingDown className="h-3.5 w-3.5" aria-hidden="true" />}
        {label ?? (isBuy ? "Compra" : "Vendi")}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={close}>
          <div className="w-full max-w-sm rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="font-display text-lg font-semibold text-white">
                {isBuy ? "Compra" : "Vendi"} {symbol}
              </h3>
              <button onClick={close} className="text-slate-400 transition hover:text-white" aria-label="Chiudi">
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Prezzo attuale {price != null ? formatCurrency(price, currency) : "N/D"} · operazione simulata nel tuo portafoglio
            </p>

            {isBuy ? (
              <label className="mt-4 block space-y-1">
                <span className="text-xs text-slate-400">Quanto investire (€)</span>
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-emerald-300/60"
                />
                <span className="block text-xs text-slate-500">≈ {buyQty > 0 ? buyQty.toFixed(4) : "0"} quote</span>
              </label>
            ) : (
              <label className="mt-4 block space-y-1">
                <span className="text-xs text-slate-400">
                  Quante quote vendere{maxQuantity ? ` (max ${maxQuantity.toLocaleString("it-IT")})` : ""}
                </span>
                <input
                  type="number"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                  className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-rose-300/60"
                />
                {maxQuantity ? (
                  <button onClick={(e) => { e.stopPropagation(); setQty(String(maxQuantity)); }} className="text-xs text-cyan-300 hover:text-cyan-200">
                    Vendi tutto
                  </button>
                ) : null}
              </label>
            )}

            {err && <p className="mt-3 text-xs text-rose-300">{err}</p>}
            {msg && <p className="mt-3 text-xs text-emerald-300">{msg}</p>}

            <div className="mt-5 flex justify-end gap-2">
              <button onClick={close} className="rounded-md border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-300 transition hover:bg-slate-800">
                Annulla
              </button>
              <button
                onClick={confirm}
                disabled={busy}
                className={
                  isBuy
                    ? "rounded-md border border-emerald-300/40 bg-emerald-400/20 px-4 py-2 text-sm font-semibold text-emerald-50 transition hover:bg-emerald-400/30 disabled:opacity-60"
                    : "rounded-md border border-rose-300/40 bg-rose-400/20 px-4 py-2 text-sm font-semibold text-rose-50 transition hover:bg-rose-400/30 disabled:opacity-60"
                }
              >
                {busy ? "..." : isBuy ? "Conferma acquisto" : "Conferma vendita"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
