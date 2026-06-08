import type { LucideIcon } from "lucide-react";

type MetricTone = "green" | "cyan" | "amber" | "rose" | "violet";

type MetricCardProps = {
  label: string;
  value: string;
  delta: string;
  tone: MetricTone;
  icon: LucideIcon;
};

const tones: Record<MetricTone, { wrap: string; icon: string; rule: string; delta: string }> = {
  green: {
    wrap: "from-emerald-400/[0.06] via-transparent to-transparent",
    icon: "border-emerald-300/25 bg-emerald-400/10 text-emerald-200",
    rule: "from-emerald-300/70",
    delta: "text-emerald-300",
  },
  cyan: {
    wrap: "from-cyan-400/[0.06] via-transparent to-transparent",
    icon: "border-cyan-300/25 bg-cyan-400/10 text-cyan-200",
    rule: "from-cyan-300/80",
    delta: "text-cyan-200",
  },
  amber: {
    wrap: "from-amber-400/[0.07] via-transparent to-transparent",
    icon: "border-amber-300/25 bg-amber-400/10 text-amber-200",
    rule: "from-amber-300/80",
    delta: "text-amber-200",
  },
  rose: {
    wrap: "from-rose-400/[0.07] via-transparent to-transparent",
    icon: "border-rose-300/25 bg-rose-400/10 text-rose-200",
    rule: "from-rose-300/80",
    delta: "text-rose-200",
  },
  violet: {
    wrap: "from-violet-400/[0.07] via-transparent to-transparent",
    icon: "border-violet-300/25 bg-violet-400/10 text-violet-200",
    rule: "from-violet-300/80",
    delta: "text-violet-200",
  },
};

export function MetricCard({ label, value, delta, tone, icon: Icon }: MetricCardProps) {
  const t = tones[tone];
  return (
    <article
      className={[
        "group relative overflow-hidden rounded-2xl border border-slate-800/60 bg-slate-950/55 p-5 shadow-panel transition-all duration-300",
        "hover:-translate-y-[2px] hover:border-slate-700/80",
      ].join(" ")}
    >
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${t.wrap} opacity-90`}
      />
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute left-0 top-0 h-px w-24 bg-gradient-to-r ${t.rule} to-transparent`}
      />
      <div className="relative flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="eyebrow-muted truncate">{label}</p>
          <p className="number-xl mt-3 truncate">{value}</p>
        </div>
        <span
          className={[
            "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border transition-transform duration-300 group-hover:scale-105",
            t.icon,
          ].join(" ")}
        >
          <Icon className="h-4 w-4" aria-hidden="true" strokeWidth={1.75} />
        </span>
      </div>
      <p className={`relative mt-4 font-mono text-[11px] uppercase tracking-[0.18em] ${t.delta}`}>
        {delta}
      </p>
    </article>
  );
}
