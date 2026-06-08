import { useEffect, useMemo, useState } from "react";
import { Brain, FlaskConical, Sparkles, TriangleAlert } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  type Asset,
  type MLModelType,
  type MLPrediction,
  type MLStatus,
  type MLTargetType,
  type MLTrainInput,
  type MLTrainResult,
} from "../lib/api";

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

function pct(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return "N/D";
  return `${(num * 100).toFixed(1)}%`;
}

function num(value: unknown, digits = 3): string {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "N/D";
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

  async function loadStatus() {
    try {
      const [statusData, assetData] = await Promise.all([
        apiGet<MLStatus>("/ml/status"),
        apiGet<Asset[]>("/assets"),
      ]);
      setStatus(statusData);
      setAssets(assetData);
      if (assetData[0]) setPredictSymbol(assetData[0].symbol);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    void loadStatus();
  }, []);

  async function train() {
    setTraining(true);
    setError(null);
    try {
      const payload: MLTrainInput = {
        model_name: `${modelLabels[modelType]} · ${targetLabels[targetType]}`,
        model_type: modelType,
        target_type: targetType,
        horizon_days: Number(horizon),
        symbols: [],
        min_samples: 100,
        cv_folds: 4,
      };
      setResult(await apiPost<MLTrainResult>("/ml/train", payload));
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Training non riuscito.");
    } finally {
      setTraining(false);
    }
  }

  async function predict() {
    setPredicting(true);
    setError(null);
    try {
      setPrediction(await apiPost<MLPrediction>(`/ml/predict/${predictSymbol}`, {}));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Predizione non riuscita.");
      setPrediction(null);
    } finally {
      setPredicting(false);
    }
  }

  const metrics = result?.metrics ?? {};
  const walkForward = (metrics.walk_forward as Record<string, unknown> | null) ?? null;
  const topFeatures = (metrics.top_features_positive as Array<{ feature: string; importance: number }>) ?? [];
  const probability =
    prediction?.probability_positive ?? prediction?.probability_outperform ?? prediction?.probability_drawdown ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="AI Lab"
        index="10"
        title="Machine Learning"
        subtitle="Addestra un modello sui dati storici e ottieni una probabilità per i prossimi giorni. Strumento sperimentale di supporto, non una previsione certa."
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
          Onestà prima di tutto: l'ML qui dà una <b>probabilità</b>, non una certezza. Su dati simulati l'accuratezza è
          vicina al caso (~50%). Guarda sempre la <b>validazione walk-forward</b>: se è debole, il modello non generalizza.
          Diventa più utile con dati reali, ma non garantisce guadagni.
        </p>
      </div>

      {error && (
        <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel eyebrow="Passo 1" title="Addestra un modello">
          <div className="space-y-4">
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Modello</span>
              <select value={modelType} onChange={(e) => setModelType(e.target.value as MLModelType)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                {Object.entries(modelLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Cosa prevedere</span>
              <select value={targetType} onChange={(e) => setTargetType(e.target.value as MLTargetType)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60">
                {Object.entries(targetLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="block space-y-2">
              <span className="text-sm text-slate-400">Orizzonte (giorni)</span>
              <input type="number" min="1" max="120" value={horizon} onChange={(e) => setHorizon(e.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60" />
            </label>
            <p className="text-xs text-slate-500">Il training usa tutti gli asset con storico locale e validazione walk-forward a 4 periodi.</p>
            <button onClick={() => void train()} disabled={training} className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-violet-300/30 bg-violet-400/15 px-4 py-2.5 text-sm font-semibold text-violet-100 transition hover:bg-violet-400/25 disabled:opacity-60">
              <Brain className={`h-4 w-4 ${training ? "animate-pulse" : ""}`} aria-hidden="true" />
              {training ? "Addestramento..." : "Addestra modello"}
            </button>
          </div>
        </Panel>

        <div className="space-y-6">
          {result ? (
            <Panel eyebrow="Risultato training" title="Performance del modello">
              <div className="grid gap-3 sm:grid-cols-4">
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
            <PageHeaderAction onClick={() => void predict()} disabled={predicting || !status?.ml_ready} icon={<Sparkles className="h-4 w-4" aria-hidden="true" />}>
              {predicting ? "Calcolo..." : "Prevedi"}
            </PageHeaderAction>
          }>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <select value={predictSymbol} onChange={(e) => setPredictSymbol(e.target.value)} className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60 sm:max-w-xs">
                {assets.map((a) => <option key={a.symbol} value={a.symbol}>{a.symbol} — {a.name}</option>)}
              </select>
            </div>
            {!status?.ml_ready && <p className="mt-3 text-xs text-slate-500">Addestra prima un modello.</p>}
            {prediction && (
              <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-lg font-semibold text-white">{prediction.symbol}</span>
                  <span className={`rounded-md border px-2.5 py-1 text-xs font-semibold ${
                    prediction.confidence === "HIGH" ? "border-emerald-300/30 bg-emerald-400/10 text-emerald-200"
                      : prediction.confidence === "MEDIUM" ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-200"
                      : "border-slate-700 bg-slate-900 text-slate-400"
                  }`}>confidenza {prediction.confidence}</span>
                </div>
                <p className="num mt-3 text-3xl font-semibold text-white">{probability != null ? pct(probability) : "N/D"}</p>
                <p className="mt-1 text-sm text-slate-400">probabilità · {targetLabels[prediction.target_type as MLTargetType] ?? prediction.target_type} · {prediction.horizon_days} giorni</p>
                {prediction.warnings.length > 0 && (
                  <ul className="mt-3 space-y-0.5 text-xs text-amber-300">
                    {prediction.warnings.map((w) => <li key={w}>· {w}</li>)}
                  </ul>
                )}
              </div>
            )}
          </Panel>
        </div>
      </div>

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
