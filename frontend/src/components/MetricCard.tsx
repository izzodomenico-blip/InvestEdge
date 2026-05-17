import type { LucideIcon } from "lucide-react";

type MetricCardProps = {
  label: string;
  value: string;
  delta: string;
  tone: "green" | "cyan" | "amber" | "rose";
  icon: LucideIcon;
};

const tones = {
  green: "text-edge-green bg-emerald-400/10 border-emerald-300/20",
  cyan: "text-edge-cyan bg-cyan-400/10 border-cyan-300/20",
  amber: "text-edge-amber bg-amber-400/10 border-amber-300/20",
  rose: "text-edge-rose bg-rose-400/10 border-rose-300/20",
};

export function MetricCard({ label, value, delta, tone, icon: Icon }: MetricCardProps) {
  return (
    <article className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-5 shadow-panel">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase text-slate-500">{label}</p>
          <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
        </div>
        <span className={`inline-flex h-10 w-10 items-center justify-center rounded-md border ${tones[tone]}`}>
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
      </div>
      <p className="mt-4 text-sm text-slate-400">{delta}</p>
    </article>
  );
}
