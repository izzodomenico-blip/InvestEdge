import type { EffectiveObservationQuality, QualityTier } from "../lib/api";

type DataQualityBadgeProps = {
  tier: QualityTier;
  quality: EffectiveObservationQuality | null;
  observedAt?: string | null;
};

const tierStyles: Record<QualityTier, { label: string; className: string; hint: string }> = {
  QUALIFIED: {
    label: "Qualified",
    className: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
    hint: "Identità verificata, listing completo e storico EOD sufficiente.",
  },
  OBSERVABLE: {
    label: "Observable",
    className: "border-cyan-300/30 bg-cyan-400/10 text-cyan-200",
    hint: "Mapping univoco e almeno un dato valido, requisiti di qualificazione incompleti.",
  },
  REFERENCE_ONLY: {
    label: "Reference only",
    className: "border-slate-600 bg-slate-900 text-slate-300",
    hint: "Solo consultazione: identità, mapping o dati non sufficienti.",
  },
};

const freshnessStyles: Record<EffectiveObservationQuality, { label: string; className: string }> = {
  realtime: { label: "Tempo reale", className: "border-emerald-300/30 text-emerald-200" },
  delayed: { label: "Ritardato", className: "border-cyan-300/30 text-cyan-200" },
  eod: { label: "Fine giornata", className: "border-cyan-300/30 text-cyan-200" },
  reference: { label: "Riferimento", className: "border-slate-600 text-slate-300" },
  stale: { label: "Dato non aggiornato", className: "border-amber-300/40 text-amber-200" },
};

/** Tier di qualità e freschezza effettiva dell'ultima osservazione (mai indicazione di negoziabilità). */
export function DataQualityBadge({ tier, quality, observedAt }: DataQualityBadgeProps) {
  const tierStyle = tierStyles[tier];
  const freshness = quality ? freshnessStyles[quality] : null;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span
        title={tierStyle.hint}
        className={`rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tierStyle.className}`}
      >
        {tierStyle.label}
      </span>
      <span
        title={observedAt ? `Ultima osservazione: ${observedAt}` : undefined}
        className={`rounded-md border px-1.5 py-0.5 text-[10px] ${
          freshness ? freshness.className : "border-slate-700 text-slate-500"
        }`}
      >
        {freshness ? freshness.label : "Nessuna osservazione"}
      </span>
    </span>
  );
}
