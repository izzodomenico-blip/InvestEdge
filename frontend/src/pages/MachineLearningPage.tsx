import { useEffect, useRef, useState } from "react";
import { Brain, FlaskConical, Info, Sparkles, TrendingDown, TrendingUp, TriangleAlert } from "lucide-react";
import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  apiReasonCode,
  type DataMode,
  type JobOut,
  type Asset,
  type MLModelType,
  type MLPrediction,
  type MLStatus,
  type MLTargetType,
  type MLTrainInput,
  type MLTrainResult,
} from "../lib/api";

import { cancelJob, getInlineJobResult, waitForJob } from "../lib/jobs";

const modelLabels: Record<MLModelType, string> = {
  HIST_GRADIENT_BOOSTING: "Gradient Boosting (consigliato)",
  RANDOM_FOREST: "Random Forest",
  LOGISTIC_REGRESSION: "Regressione logistica",
};

const targetLabels: Record<MLTargetType, string> = {
  POSITIVE_RETURN: "Rendimento positivo",
  OUTPERFORM_BENCHMARK: "Batte il benchmark",
  DRAWDOWN_RISK: "Rischio forte ribasso",
};

const targetEvent: Record<MLTargetType, string> = {
  POSITIVE_RETURN: "che il prezzo salga",
  OUTPERFORM_BENCHMARK: "che batta il mercato",
  DRAWDOWN_RISK: "di un forte ribasso (-8% o più)",
};

const confidenceInfo: Record<string, { label: string; level: number; tone: string; hint: string }> = {
  HIGH: { label: "Alta", level: 3, tone: "text-emerald-200", hint: "Segnale deciso e metriche del modello solide." },
  MEDIUM: { label: "Media", level: 2, tone: "text-cyan-200", hint: "Segnale presente ma da confermare con altri indicatori." },
  LOW: { label: "Bassa", level: 1, tone: "text-slate-300", hint: "Probabilità vicina al 50/50: poco affidabile, quasi un caso." },
};

function pct(value: unknown): string {
  const n = typeof value === "number" ? value : NaN;
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "N/D";
}

function num(value: unknown, digits = 3): string {
  const n = typeof value === "number" ? value : NaN;
  return Number.isFinite(n) ? n.toFixed(digits) : "N/D";
}

type Verdict = { tone: "up" | "down" | "flat"; fill: string; text: string; title: string };

function verdictOf(target: MLTargetType, probability: number): Verdict {
  const strength = Math.max(probability, 1 - probability);
  const event = targetEvent[target] ?? "che l'evento accada";
  const weak = strength < 0.55;
  // Per il rischio ribasso, alta probabilità = negativo (rosso).
  const highIsBad = target === "DRAWDOWN_RISK";
  if (weak) {
    return { tone: "flat", fill: "#F59E0B", title: "Segnale incerto", text: `Il modello è quasi indeciso ${event}.` };
  }
  const favourable = highIsBad ? probability < 0.5 : probability >= 0.5;
  if (favourable) {
    return {
      tone: highIsBad ? "up" : "up",
      fill: "#34D399",
      title: highIsBad ? "Rischio contenuto" : "Segnale favorevole",
      text: `Il modello stima una probabilità ${pct(probability)} ${event}.`,
    };
  }
  return {
    tone: "down",
    fill: "#FB7185",
    title: highIsBad ? "Rischio elevato" : "Segnale sfavorevole",
    text: `Il modello stima una probabilità ${pct(probability)} ${event}.`,
  };
}

function ProbabilityGauge({ probability, fill }: { probability: number; fill: string }) {
  const value = Math.round(probability * 100);
  const data = [{ name: "p", value, fill }];
  return (
    <div className="relative h-40 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <RadialBarChart
          innerRadius="78%"
          outerRadius="100%"
          data={data}
          startAngle={180}
          endAngle={0}
          barSize={20}
        >
          <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
          <RadialBar background={{ fill: "#1E293B" }} dataKey="value" cornerRadius={12} angleAxisId={0} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-end pb-6">
        <span className="num text-4xl font-semibold text-white">{value}%</span>
        <span className="text-[11px] uppercase tracking-[0.16em] text-slate-500">probabilità</span>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-1 flex justify-between px-2 text-[10px] text-slate-600">
        <span>0%</span>
        <span className="text-slate-500">50% = caso</span>
        <span>100%</span>
      </div>
    </div>
  );
}

function ConfidenceMeter({ confidence }: { confidence: string }) {
  const info = confidenceInfo[confidence] ?? confidenceInfo.LOW;
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">Confidenza</span>
        <span className={`text-sm font-semibold ${info.tone}`}>{info.label}</span>
        <div className="flex gap-1">
          {[1, 2, 3].map((i) => (
            <span
              key={i}
              className={`h-1.5 w-6 rounded-full ${
                i <= info.level
                  ? info.level === 3
                    ? "bg-emerald-300"
                    : info.level === 2
                      ? "bg-cyan-300"
                      : "bg-slate-400"
                  : "bg-slate-800"
              }`}
            />
          ))}
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-500">{info.hint}</p>
    </div>
  );
}

export function MachineLearningPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [status, setStatus] = useState<MLStatus | null>(null);
  const [modelType, setModelType] = useState<MLModelType>("HIST_GRADIENT_BOOSTING");
  const [targetType, setTargetType] = useState<MLTargetType>("POSITIVE_RETURN");
  const [horizon, setHorizon] = useState("14");
  const [training, setTraining] = useState(false);
  const [result, setResult] = useState<MLTrainResult | null>(null);
  const [predictSymbol, setPredictSymbol] = useState("AAPL");
  const [prediction, setPrediction] = useState<MLPrediction | null>(null);
  const [predicting, setPredicting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [dataMode, setDataMode] = useState<DataMode>("REAL");
  const [job, setJob] = useState<JobOut | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const trainingController = useRef<AbortController | null>(null);
  const predictionController = useRef<AbortController | null>(null);
  const trainingInFlight = useRef(false);
  const predictionInFlight = useRef(false);

  const statusRequestId = useRef(0);

  async function loadStatus(signal: AbortSignal) {
    const requestId = ++statusRequestId.current;
    try {
      const [statusData, assetData] = await Promise.all([
        apiGet<MLStatus>("/ml/status", { signal }), apiGet<Asset[]>("/assets", { signal }),
      ]);
      signal.throwIfAborted();
      if (requestId !== statusRequestId.current) return;
      setStatus(statusData); setAssets(assetData);
      setPredictSymbol(current => assetData.some(asset => asset.symbol === current) ? current : assetData[0]?.symbol ?? "");
    } catch (err) {
      if (requestId === statusRequestId.current) throw err;
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    void loadStatus(controller.signal).catch(err => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Stato ML non disponibile. Ricarica la pagina.");
    });
    return () => {
      controller.abort(); trainingController.current?.abort(); predictionController.current?.abort();
    };
  }, []);

  async function train() {
    if (trainingInFlight.current || predictionInFlight.current) return;
    if (!Number.isInteger(Number(horizon)) || Number(horizon) < 1 || Number(horizon) > 120) {
      setError("Orizzonte non valido: scegli da 1 a 120 sedute."); return;
    }
    trainingInFlight.current = true;
    const controller = new AbortController();
    trainingController.current = controller;
    const signal = controller.signal;
    setTraining(true); setError(null); setResult(null); setPrediction(null); setJob(null); setCancelling(false);
    try {
      const payload: MLTrainInput = {
        model_name: modelLabels[modelType] + " · " + targetLabels[targetType],
        model_type: modelType, target_type: targetType, horizon_days: Number(horizon),
        symbols: [], min_samples: 100, cv_folds: 4, data_mode: dataMode,
      };
      const initial = await apiPost<JobOut>("/ml/train", payload, { signal });
      signal.throwIfAborted();
      if (initial.kind !== "ML_TRAIN") throw new Error("Tipo di elaborazione inatteso.");
      const completed = await waitForJob(initial, { signal, onUpdate: value => {
        if (!signal.aborted) setJob(value);
      } });
      const next = getInlineJobResult<MLTrainResult>(completed);
      if (!Number.isSafeInteger(next.model_id) || next.model_id <= 0 || !next.metrics ||
        !Array.isArray(next.features_used) || !Array.isArray(next.warnings)) throw new Error("Risultato training non disponibile.");
      signal.throwIfAborted(); setResult(next);
      try { await loadStatus(signal); }
      catch (err) {
        if (!signal.aborted) setError("Training salvato, ma lo stato ML non è aggiornato. Ricarica la pagina. " +
          (err instanceof Error ? err.message : ""));
      }
    } catch (err) {
      if (!signal.aborted) setError(err instanceof Error ? err.message : "Training non riuscito.");
    } finally {
      if (trainingController.current === controller) {
        trainingInFlight.current = false; trainingController.current = null;
        if (!signal.aborted) { setTraining(false); setCancelling(false); }
      }
    }
  }
  async function requestCancellation() {
    const controller = trainingController.current;
    if (!controller || !job || cancelling) return;
    setCancelling(true);
    try {
      const next = await cancelJob(job.id, controller.signal);
      if (!controller.signal.aborted && trainingController.current === controller) setJob(next);
    } catch (err) {
      if (!controller.signal.aborted && trainingController.current === controller) {
        setCancelling(false); setError(err instanceof Error ? err.message : "Annullamento non riuscito.");
      }
    }
  }
  async function predict() {
    if (predictionInFlight.current || trainingInFlight.current || !predictSymbol || !status?.ml_ready) return;
    predictionInFlight.current = true;
    const controller = new AbortController(); predictionController.current = controller;
    const signal = controller.signal;
    setPredicting(true); setError(null); setPrediction(null);
    try {
      const next = await apiPost<MLPrediction>("/ml/predict/" + encodeURIComponent(predictSymbol), {}, { signal });
      signal.throwIfAborted(); setPrediction(next);
    } catch (err) {
      if (!signal.aborted) setError(apiReasonCode(err) === "MODEL_PIPELINE_MISMATCH"
        ? "Modello creato con una pipeline precedente: riaddestralo."
        : err instanceof Error ? err.message : "Predizione non riuscita.");
    } finally {
      if (predictionController.current === controller) {
        predictionInFlight.current = false; predictionController.current = null;
        if (!signal.aborted) setPredicting(false);
      }
    }
  }

  const metrics = result?.metrics ?? {};
  const walkForward = (metrics.walk_forward as Record<string, unknown> | null) ?? null;
  const allowedFeatures = new Set(result?.features_used.filter(name => !/news|sentiment|portfolio/i.test(name)) ?? []);
  const topFeatures = ((metrics.top_features_positive as Array<{ feature: string; importance: number }>) ?? [])
    .filter(item => allowedFeatures.has(item.feature));
  const probability =
    prediction?.probability_positive ?? prediction?.probability_outperform ?? prediction?.probability_drawdown ?? null;
  const predTarget = (prediction?.target_type as MLTargetType) ?? targetType;
  const verdict = prediction && probability != null ? verdictOf(predTarget, probability) : null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="AI Lab"
        index="10"
        title="Machine Learning"
        subtitle="Addestra un modello sui dati storici e ottieni una probabilità per le prossime sedute. Strumento sperimentale di supporto, non una previsione certa."
        meta={
          status ? (
            <>
              <span>Modelli <span className="text-cyan-300/80">{status.models_count}</span></span>
              <span>Stato <span className="text-cyan-300/80">{status.ml_ready ? "pronto" : "vuoto"}</span></span>
            </>
          ) : undefined
        }
      />

      <div className="flex items-start gap-3 rounded-2xl border border-amber-300/30 bg-amber-400/[0.07] p-4 text-sm text-amber-100">
        <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" aria-hidden="true" />
        <p>
          Training REAL e DEMO restano separati. Il modello usa la pipeline tecnica condivisa;
          news e dati di portafoglio non sono feature ML. Questi risultati in sedute non validano l'intraday di 15–30 minuti.
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      {training && job && <Panel title="Training in corso">
        <div role="status" aria-live="polite" className="space-y-3 text-sm text-slate-200">
          <p>{({ QUEUED:"Accodato",RUNNING:"In esecuzione",SUCCEEDED:"Completato",FAILED:"Non riuscito",CANCELLED:"Annullato",INTERRUPTED:"Interrotto" })[job.status]} · {Math.round(Math.max(0,Math.min(1,job.progress))*100)}%</p>
          <progress aria-label="Avanzamento training" value={job.progress} max={1} className="w-full" />
          {(cancelling || job.cancel_requested) && <p>Annullamento richiesto: attendo la conferma.</p>}
        </div>
        <button type="button" onClick={() => void requestCancellation()} disabled={cancelling || job.cancel_requested || !["QUEUED","RUNNING"].includes(job.status)}
          className="mt-3 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50">Annulla training</button>
      </Panel>}

      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Panel eyebrow="Passo 1" title="Addestra un modello">
          <fieldset disabled={training || predicting} className="space-y-4">
            <label className="block space-y-2"><span className="text-sm text-slate-300">Modalità training</span>
              <select value={dataMode} onChange={e => setDataMode(e.target.value as DataMode)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white">
                <option value="REAL">REAL · dati reali</option><option value="DEMO">DEMO · simulazione separata</option>
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Modello</span>
              <select value={modelType} onChange={(e) => setModelType(e.target.value as MLModelType)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white outline-none focus:border-cyan-300/60">
                {Object.entries(modelLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Cosa prevedere</span>
              <select value={targetType} onChange={(e) => setTargetType(e.target.value as MLTargetType)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white outline-none focus:border-cyan-300/60">
                {Object.entries(targetLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Orizzonte (sedute)</span>
              <input type="number" min="1" max="120" value={horizon} onChange={(e) => setHorizon(e.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white outline-none focus:border-cyan-300/60" />
            </label>
            <p className="text-xs text-slate-500">Il training usa tutti gli asset con storico locale e validazione walk-forward a 4 periodi.</p>
            <button onClick={() => void train()} disabled={training} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-violet-300/30 bg-violet-400/15 px-4 py-2.5 text-sm font-semibold text-violet-100 transition hover:bg-violet-400/25 disabled:opacity-60">
              <Brain className={`h-4 w-4 ${training ? "animate-pulse" : ""}`} aria-hidden="true" />
              {training ? "Addestramento..." : "Addestra modello"}
            </button>
          </fieldset>
        </Panel>

        <div className="min-w-0 space-y-6">
          {result ? (
            <Panel eyebrow="Risultato training" title="Performance del modello">
              <p className="mb-3 text-sm text-slate-300">Training salvato: {result.data_mode ?? "N/D"} · Modello #{result.model_id} · Pipeline: {result.pipeline_version ?? "N/D"}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Stat label="Accuratezza" value={pct(metrics.accuracy)} />
                <Stat label="F1" value={num(metrics.f1_score)} />
                <Stat label="ROC AUC" value={num(metrics.roc_auc)} />
                <Stat label="Campioni" value={String(metrics.samples_count ?? "N/D")} />
              </div>



              {walkForward && (
                <div className="mt-4 rounded-lg border border-cyan-300/20 bg-cyan-400/[0.06] p-4">
                  <p className="eyebrow text-cyan-200">Validazione walk-forward ({String(walkForward.folds)} periodi)</p>
                  <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
                    <div><span className="text-slate-500">Accuratezza media</span><p className="num font-semibold text-white">{pct(walkForward.accuracy_mean)}</p></div>
                    <div><span className="text-slate-500">F1 media</span><p className="num font-semibold text-white">{num(walkForward.f1_mean)}</p></div>
                    <div><span className="text-slate-500">AUC media</span><p className="num font-semibold text-white">{num(walkForward.roc_auc_mean)}</p></div>
                  </div>
                </div>
              )}

              {topFeatures.length > 0 && (
                <div className="mt-4">
                  <p className="eyebrow-muted">Fattori più influenti</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {topFeatures.slice(0, 6).map((f) => (
                      <span key={f.feature} className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300">{f.feature}</span>
                    ))}
                  </div>
                </div>
              )}

              {result.warnings.length > 0 && (
                <ul className="mt-4 space-y-1 rounded-lg border border-amber-300/20 bg-amber-400/10 p-3 text-xs text-amber-200">
                  {result.warnings.map((w) => <li key={w}>· {w}</li>)}
                </ul>
              )}
            </Panel>
          ) : (
            <Panel title="Risultato training">
              <p className="text-sm text-slate-400">Addestra un modello per vedere accuratezza, validazione walk-forward e fattori più influenti.</p>
            </Panel>
          )}

          <Panel eyebrow="Passo 2" title="Previsione per un asset" action={
            <PageHeaderAction onClick={() => void predict()} disabled={predicting || training || !status?.ml_ready || !predictSymbol} icon={<Sparkles className="h-4 w-4" aria-hidden="true" />}>
              {predicting ? "Calcolo..." : "Prevedi"}
            </PageHeaderAction>
          }>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <select aria-label="Asset da prevedere" disabled={training || predicting} value={predictSymbol} onChange={(e) => { setPredictSymbol(e.target.value); setPrediction(null); }} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-base text-white outline-none focus:border-cyan-300/60 sm:max-w-xs">
                {assets.map((a) => <option key={a.symbol} value={a.symbol}>{a.symbol} — {a.name}</option>)}
              </select>
            </div>
            {!status?.ml_ready && <p className="mt-3 text-xs text-slate-500">Addestra prima un modello.</p>}

            {prediction && <p className="mt-3 text-sm text-slate-300">Previsione salvata: {prediction.data_mode ?? "N/D"} · Modello #{prediction.model_id} · Pipeline: {prediction.pipeline_version ?? "N/D"}</p>}
            {prediction && probability == null && <p className="mt-3 text-sm text-slate-300">Probabilità N/D per questa previsione.</p>}
            {prediction && probability != null && verdict && (
              <div className="mt-4 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/55">
                <div className="flex items-center justify-between border-b border-slate-800/70 px-4 py-3">
                  <span className="font-mono text-lg font-semibold text-white">{prediction.symbol}</span>
                  <span className="text-xs text-slate-500">orizzonte {prediction.horizon_days} sedute</span>
                </div>

                <div className="grid gap-4 p-4 sm:grid-cols-[1fr_1fr] sm:items-center">
                  <ProbabilityGauge probability={probability} fill={verdict.fill} />

                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      {verdict.tone === "up" && <TrendingUp className="h-5 w-5 text-emerald-300" aria-hidden="true" />}
                      {verdict.tone === "down" && <TrendingDown className="h-5 w-5 text-rose-300" aria-hidden="true" />}
                      {verdict.tone === "flat" && <Info className="h-5 w-5 text-amber-300" aria-hidden="true" />}
                      <span className={`text-base font-semibold ${
                        verdict.tone === "up" ? "text-emerald-200" : verdict.tone === "down" ? "text-rose-200" : "text-amber-200"
                      }`}>{verdict.title}</span>
                    </div>
                    <p className="text-sm leading-relaxed text-slate-300">{verdict.text}</p>
                    <p className="text-xs text-slate-500">
                      Obiettivo: <b className="text-slate-300">{targetLabels[predTarget]}</b>. La % è la probabilità stimata
                      {" "}{targetEvent[predTarget]} entro {prediction.horizon_days} sedute. <b>50% = come lanciare una moneta.</b>
                    </p>
                    <ConfidenceMeter confidence={prediction.confidence} />
                  </div>
                </div>

                {prediction.warnings.length > 0 && (
                  <ul className="space-y-0.5 border-t border-slate-800/70 px-4 py-3 text-xs text-amber-300">
                    {prediction.warnings.map((w) => <li key={w}>· {w}</li>)}
                  </ul>
                )}
              </div>
            )}
          </Panel>
        </div>
      </div>

      <Panel title="Leggere il risultato">
        <p className="max-w-prose text-sm leading-6 text-slate-300">Le metriche descrivono il campione salvato e la validazione temporale del modello. L'accuratezza da sola non misura il rendimento dopo i costi. Consulta la modalità Evidenza del Backtest per il verdetto del segnale e i limiti dell'universo.</p>
      </Panel>

      <p className="flex items-center justify-center gap-2 text-center text-xs text-slate-600">
        <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
        Modulo sperimentale. Le probabilità non sono consigli finanziari.
      </p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <p className="eyebrow-muted">{label}</p>
      <p className="num mt-1 text-lg font-semibold text-white">{value}</p>
    </div>
  );
}
