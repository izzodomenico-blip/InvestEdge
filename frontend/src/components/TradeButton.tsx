import { useState } from "react";
import { createPortal } from "react-dom";
import { Lightbulb, ShoppingCart, TrendingDown, X } from "lucide-react";

import { apiGet, apiPost, type OrderSimulationResponse, type PortfolioSummary, type SimulatedOrderInput } from "../lib/api";
import { formatCurrency } from "../lib/format";

type Props = {
  symbol: string;
  price: number | null | undefined;
  side?: "BUY" | "SELL";
  maxQuantity?: number;
  currency?: string;
  assetType?: string;
  riskLevel?: string;
  onDone?: () => void;
  className?: string;
  label?: string;
};

// Peso target per posizione secondo il rischio (strategia di affidabilità: diversifica,
// meno capitale sugli asset volatili, tetto per posizione).
function targetWeight(assetType?: string, riskLevel?: string): number {
  const t = (assetType ?? "").toLowerCase();
  if (t === "crypto") return 0.05;
  const r = (riskLevel ?? "").toLowerCase();
  if (r.includes("high")) return 0.08;
  if (r.includes("low")) return 0.18;
  if (r.includes("medium")) return 0.12;
  return 0.1;
}

export function TradeButton({
  symbol,
  price,
  side = "BUY",
  maxQuantity,
  currency = "EUR",
  assetType,
  riskLevel,
  onDone,
  className,
  label,
}: Props) {
  const isBuy = side === "BUY";
  const px = price ?? 0;
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [qty, setQty] = useState(maxQuantity ? String(maxQuantity) : "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [suggested, setSuggested] = useState<number | null>(null);
  const [cash, setCash] = useState<number | null>(null);
  const [pctOfPortfolio, setPctOfPortfolio] = useState<number | null>(null);

  const buyQty = px > 0 && amount ? Number(amount) / px : 0;

  async function openModal(e: React.MouseEvent) {
    e.stopPropagation();
    setErr(null);
    setMsg(null);
    setQty(maxQuantity ? String(maxQuantity) : "");
    setOpen(true);

    if (isBuy) {
      // Suggerisce l'importo "giusto" in base a capitale disponibile + rischio.
      setAmount("");
      try {
        const ptf = await apiGet<PortfolioSummary>("/portfolio");
        const base = ptf.total_value > 0 ? ptf.total_value : ptf.cash;
        const weight = targetWeight(assetType, riskLevel);
        let target = base * weight;
        target = Math.min(target, ptf.cash * 0.98); // non superare la liquidità
        target = Math.max(0, Math.floor(target / 10) * 10);
        setCash(ptf.cash);
        setSuggested(target);
        setPctOfPortfolio(base > 0 ? (target / base) * 100 : null);
        setAmount(target > 0 ? String(target) : "1000");
      } catch {
        setSuggested(null);
        setCash(null);
        setAmount("1000");
      }
    }
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

  const modal = (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={close}>
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="font-display text-xl font-semibold text-white">
            {isBuy ? "Compra" : "Vendi"} {symbol}
          </h3>
          <button onClick={close} className="text-slate-400 transition hover:text-white" aria-label="Chiudi">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <p className="mt-1 text-sm text-slate-500">
          Prezzo attuale {price != null ? formatCurrency(price, currency) : "N/D"} · operazione simulata
        </p>

        {isBuy ? (
          <>
            {suggested != null && suggested > 0 && (
              <div className="mt-4 flex items-start gap-3 rounded-xl border border-emerald-300/25 bg-emerald-400/[0.07] p-3">
                <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-emerald-300" aria-hidden="true" />
                <div className="text-sm text-slate-200">
                  <p>
                    Importo consigliato: <b className="text-emerald-200">{formatCurrency(suggested, currency)}</b>
                    {pctOfPortfolio != null && <> (~{pctOfPortfolio.toFixed(0)}% del portafoglio)</>}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Calibrato sul rischio dell'asset per restare diversificato. Liquidità disponibile{" "}
                    {cash != null ? formatCurrency(cash, currency) : "N/D"}.
                  </p>
                </div>
              </div>
            )}

            <label className="mt-4 block space-y-1.5">
              <span className="text-sm text-slate-300">Quanto investire (€)</span>
              <input
                type="number"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-base text-white outline-none focus:border-emerald-300/60"
              />
              <span className="block text-xs text-slate-500">≈ {buyQty > 0 ? buyQty.toFixed(4) : "0"} quote</span>
            </label>

            {suggested != null && suggested > 0 && Number(amount) !== suggested && (
              <button
                onClick={(e) => { e.stopPropagation(); setAmount(String(suggested)); }}
                className="mt-2 text-xs font-semibold text-emerald-300 hover:text-emerald-200"
              >
                Usa l'importo consigliato
              </button>
            )}
          </>
        ) : (
          <label className="mt-4 block space-y-1.5">
            <span className="text-sm text-slate-300">
              Quante quote vendere{maxQuantity ? ` (max ${maxQuantity.toLocaleString("it-IT")})` : ""}
            </span>
            <input
              type="number"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-base text-white outline-none focus:border-rose-300/60"
            />
            {maxQuantity ? (
              <button onClick={(e) => { e.stopPropagation(); setQty(String(maxQuantity)); }} className="text-xs font-semibold text-cyan-300 hover:text-cyan-200">
                Vendi tutto
              </button>
            ) : null}
          </label>
        )}

        {err && <p className="mt-3 rounded-lg border border-rose-300/20 bg-rose-400/10 px-3 py-2 text-sm text-rose-200">{err}</p>}
        {msg && <p className="mt-3 rounded-lg border border-emerald-300/20 bg-emerald-400/10 px-3 py-2 text-sm text-emerald-200">{msg}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={close} className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm text-slate-300 transition hover:bg-slate-800">
            Annulla
          </button>
          <button
            onClick={confirm}
            disabled={busy}
            className={
              isBuy
                ? "rounded-lg border border-emerald-300/40 bg-emerald-400/20 px-5 py-2.5 text-sm font-semibold text-emerald-50 transition hover:bg-emerald-400/30 disabled:opacity-60"
                : "rounded-lg border border-rose-300/40 bg-rose-400/20 px-5 py-2.5 text-sm font-semibold text-rose-50 transition hover:bg-rose-400/30 disabled:opacity-60"
            }
          >
            {busy ? "..." : isBuy ? "Conferma acquisto" : "Conferma vendita"}
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <button type="button" onClick={openModal} className={className ?? defaultClass}>
        {isBuy ? <ShoppingCart className="h-3.5 w-3.5" aria-hidden="true" /> : <TrendingDown className="h-3.5 w-3.5" aria-hidden="true" />}
        {label ?? (isBuy ? "Compra" : "Vendi")}
      </button>
      {open && createPortal(modal, document.body)}
    </>
  );
}
