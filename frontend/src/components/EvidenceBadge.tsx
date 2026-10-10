import { useEffect, useId, useState } from "react";
import { getEvidenceLatest, type DataMode, type EvidenceLatest, type EvidenceSummary, type Verdict } from "../lib/api";

export const verdictLabels: Record<Verdict, string> = {
  VALIDATO: "VALIDATO", NON_VALIDATO: "NON VALIDATO", INSUFFICIENTE: "INSUFFICIENTE",
};
const tones: Record<Verdict, string> = {
  VALIDATO: "border-emerald-300/30 bg-emerald-400/10 text-emerald-100",
  NON_VALIDATO: "border-rose-300/30 bg-rose-400/10 text-rose-100",
  INSUFFICIENTE: "border-amber-300/30 bg-amber-400/10 text-amber-100",
};
export function EvidenceBadge({ latest, dataMode, unavailable = false, loading = false, report }: {
  latest: EvidenceLatest | null; dataMode?: DataMode | null; unavailable?: boolean; loading?: boolean; report?: EvidenceSummary;
}) {
  const id = useId();
  const best = report ?? latest?.best;
  const demo = dataMode === "DEMO";
  const label = demo ? "DEMO · non misurabile" : unavailable ? "EVIDENZA NON DISPONIBILE" :
    loading ? "EVIDENZA IN CARICAMENTO" : best ? verdictLabels[best.verdict] + " · " + best.horizon + "g" : "NON MISURATO";
  const scope = "verdetto sul segnale nell'universo, non sul singolo titolo";
  const tooltip = demo ? "Dati DEMO: il segnale non è misurabile con evidenza REAL." :
    unavailable ? "Report non raggiungibile. Ricarica la pagina per riprovare." :
    [scope, ...(report ? [report.horizon + "g: " + verdictLabels[report.verdict] + " · " + report.created_at] : [1, 5, 21].map(h => {
      const value = latest?.horizons[String(h)];
      return h + "g: " + (value ? verdictLabels[value.verdict] + " · " + value.created_at : "NON MISURATO");
    })), "Orizzonti in sedute: non validano intraday 15–30 minuti."].join("\n");
  return <span tabIndex={0} title={tooltip} aria-describedby={id}
    className={"inline-flex max-w-full rounded-md border px-2 py-1 text-xs font-semibold focus:outline-2 focus:outline-cyan-300 " +
      (demo ? tones.INSUFFICIENTE : !unavailable && !loading && best ? tones[best.verdict] : "border-slate-600 bg-slate-900 text-slate-200")}>
    {label}<span id={id} className="sr-only">{tooltip}</span>
  </span>;
}
export function DemoMarker({ dataMode }: { dataMode?: DataMode | null }) {
  return dataMode === "DEMO" ? <span className="inline-flex rounded-md border border-amber-300/30 bg-amber-400/10 px-2 py-0.5 text-xs font-semibold text-amber-100">DEMO</span> : null;
}
// Una richiesta per montaggio, condivisa da tutti i badge della pagina.
export function useScoreEvidence() {
  const [latest, setLatest] = useState<EvidenceLatest | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    void getEvidenceLatest("score", "D", controller.signal).then(value => {
      if (!controller.signal.aborted) setLatest(value);
    }).catch(() => {
      if (!controller.signal.aborted) setUnavailable(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, []);
  return { latest, unavailable, loading };
}
