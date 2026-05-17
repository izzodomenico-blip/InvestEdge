import type { Signal } from "../lib/mockData";

type SignalBadgeProps = {
  signal: Signal;
};

const styles: Record<Signal, string> = {
  BUY: "border-emerald-300/30 bg-emerald-400/10 text-emerald-300",
  HOLD: "border-cyan-300/30 bg-cyan-400/10 text-cyan-300",
  REDUCE: "border-amber-300/30 bg-amber-400/10 text-amber-300",
  SELL: "border-rose-300/30 bg-rose-400/10 text-rose-300",
};

export function SignalBadge({ signal }: SignalBadgeProps) {
  return (
    <span className={`inline-flex min-w-20 justify-center rounded-md border px-2.5 py-1 text-xs font-semibold ${styles[signal]}`}>
      {signal}
    </span>
  );
}
