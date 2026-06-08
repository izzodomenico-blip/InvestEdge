import type { Signal } from "../lib/api";

type SignalBadgeProps = {
  signal: Signal;
  size?: "sm" | "md";
};

const styles: Record<Signal, { wrap: string; dot: string }> = {
  STRONG_BUY: {
    wrap: "border-emerald-200/40 bg-emerald-300/15 text-emerald-100",
    dot: "bg-emerald-300 shadow-[0_0_8px_rgba(110,231,183,0.7)]",
  },
  BUY: {
    wrap: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
    dot: "bg-emerald-400",
  },
  HOLD: {
    wrap: "border-cyan-300/30 bg-cyan-400/10 text-cyan-200",
    dot: "bg-cyan-300",
  },
  REDUCE: {
    wrap: "border-amber-300/30 bg-amber-400/10 text-amber-200",
    dot: "bg-amber-300",
  },
  SELL: {
    wrap: "border-rose-300/30 bg-rose-400/10 text-rose-200",
    dot: "bg-rose-300 shadow-[0_0_8px_rgba(253,164,175,0.7)]",
  },
};

export function SignalBadge({ signal, size = "md" }: SignalBadgeProps) {
  const s = styles[signal];
  const sizing =
    size === "sm" ? "min-w-16 px-2 py-0.5 text-[10px]" : "min-w-20 px-2.5 py-1 text-[11px]";
  return (
    <span
      className={[
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-mono font-semibold uppercase tracking-[0.16em]",
        sizing,
        s.wrap,
      ].join(" ")}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${s.dot}`} aria-hidden="true" />
      {signal.replace("_", " ")}
    </span>
  );
}
