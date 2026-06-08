import { useEffect, useState } from "react";
import { Brain, FlaskConical, Info, Sparkles, TrendingDown, TrendingUp, TriangleAlert } from "lucide-react";
import { PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer } from "recharts";

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
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "N/D";
}

function num(value: unknown, digits = 3): string {
  const n = typeof value === "number" ? value : Number(value);
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
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-end pb-2">
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
  const accuracyValue = Number(metrics.accuracy);
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

              <AccuracyScale accuracy={accuracyValue} />

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

            {prediction && probability != null && verdict && (
              <div className="mt-4 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/55">
                <div className="flex items-center justify-between border-b border-slate-800/70 px-4 py-3">
                  <span className="font-mono text-lg font-semibold text-white">{prediction.symbol}</span>
                  <span className="text-xs text-slate-500">orizzonte {prediction.horizon_days} giorni</span>
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
                      {" "}{targetEvent[predTarget]} entro {prediction.horizon_days} giorni. <b>50% = come lanciare una moneta.</b>
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

      <Panel eyebrow="Capire i numeri" title="Accuratezza ~50%? Si può arrivare al 70-80%?">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2 text-sm text-slate-300">
            <p>
              L'<b>accuratezza</b> è la % di volte in cui il modello indovina la direzione. <b>50% = caso puro</b> (testa o croce).
              Sui dati simulati esce ~48-50%: è la prova che il modello <b>non sta barando</b> — non esiste segnale da imparare in prezzi finti.
            </p>
            <p className="text-amber-200">
              ⚠️ Il <b>70-80% non è un obiettivo realistico</b> sui mercati veri. I fondi quantitativi professionali lavorano col
              ~52-55% e guadagnano grazie a volumi e gestione del rischio. Chi mostra 70-80% sulla direzione di un prezzo, di solito,
              sta sovra-adattando (overfitting) o ha un errore nei dati.
            </p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <p className="eyebrow-muted">Cosa migliora davvero (verso 53-56%)</p>
            <ul className="mt-2 space-y-1.5 text-sm text-slate-300">
              <li>✓ <b>Dati reali</b> al posto dei simulati (in corso)</li>
              <li>✓ <b>Più storico</b>: il piano free Alpha Vantage dà solo ~100 giorni → poco. Più anni = meglio</li>
              <li>✓ <b>Orizzonti più lunghi</b> (14-30 gg) sono più prevedibili del giorno dopo</li>
              <li>✓ <b>Più titoli</b> nel training = più esempi, meno overfitting</li>
              <li>✓ Fidarsi solo quando la <b>walk-forward</b> conferma (AUC &gt; 0.55)</li>
            </ul>
          </div>
        </div>
      </Panel>

      <p className="flex items-center justify-center gap-2 text-center text-xs text-slate-600">
        <FlaskConical className="h-3.5 w-3.5" aria-hidden="true" />
        Modulo sperimentale. Le probabilità non sono consigli finanziari.
      </p>
    </div>
  );
}

function AccuracyScale({ accuracy }: { accuracy: number }) {
  if (!Number.isFinite(accuracy)) return null;
  const pctValue = accuracy * 100;
  const clamped = Math.max(40, Math.min(70, pctValue));
  const left = ((clamped - 40) / 30) * 100; // scala 40%..70%
  const verdict =
    pctValue < 51 ? { t: "≈ caso casuale", c: "text-slate-400" }
      : pctValue < 55 ? { t: "leggero segnale", c: "text-cyan-200" }
        : pctValue < 60 ? { t: "buono per i mercati", c: "text-emerald-200" }
          : { t: "molto alto: verifica overfitting", c: "text-amber-200" };
  return (
    <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>Dove si colloca l'accuratezza</span>
        <span className={verdict.c}>{verdict.t}</span>
      </div>
      <div className="relative mt-3 h-2.5 rounded-full bg-gradient-to-r from-slate-700 via-cyan-500/40 to-emerald-400/60">
        <span className="absolute top-1/2 h-4 w-1 -translate-y-1/2 rounded-full bg-white shadow-glow" style={{ left: `${left}%` }} aria-hidden="true" />
        {/* linea del 50% = caso */}
        <span className="absolute top-1/2 h-4 w-px -translate-y-1/2 bg-slate-400/70" style={{ left: `${((50 - 40) / 30) * 100}%` }} aria-hidden="true" />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-600">
        <span>40%</span>
        <span>50% caso</span>
        <span>60%</span>
        <span>70%</span>
      </div>
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
