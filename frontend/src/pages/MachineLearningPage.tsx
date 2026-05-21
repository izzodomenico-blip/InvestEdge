import { useEffect, useMemo, useState } from "react";
import { BrainCircuit, Play, RefreshCw, Sparkles } from "lucide-react";

import { MetricCard } from "../components/MetricCard";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  type Asset,
  type MLModelSummary,
  type MLModelType,
  type MLPrediction,
  type MLStatus,
  type MLTargetType,
  type MLTrainInput,
  type MLTrainingRun,
  type MLTrainResult,
  type UniverseAsset,
  type UniverseLevel,
} from "../lib/api";
import { formatPercent } from "../lib/format";

const targetLabels: Record<MLTargetType, string> = {
  POSITIVE_RETURN: "Positive return",
  OUTPERFORM_BENCHMARK: "Outperform benchmark",
  DRAWDOWN_RISK: "Drawdown risk",
};

function metricValue(value: unknown) {
  return typeof value === "number" ? value : null;
}

function probabilityValue(prediction: MLPrediction | null) {
  if (!prediction) {
    return null;
  }
  if (prediction.target_type === "POSITIVE_RETURN") {
    return prediction.probability_positive;
  }
  if (prediction.target_type === "OUTPERFORM_BENCHMARK") {
    return prediction.probability_outperform;
  }
  if (prediction.target_type === "DRAWDOWN_RISK") {
    return prediction.probability_drawdown;
  }
  return null;
}

function confidenceTone(value: string | null | undefined) {
  if (value === "HIGH") {
    return "border-emerald-300/20 bg-emerald-400/10 text-emerald-200";
  }
  if (value === "MEDIUM") {
    return "border-cyan-300/20 bg-cyan-400/10 text-cyan-200";
  }
  return "border-amber-300/20 bg-amber-400/10 text-amber-200";
}

export function MachineLearningPage() {
  const [status, setStatus] = useState<MLStatus | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [universeAssets, setUniverseAssets] = useState<UniverseAsset[]>([]);
  const [models, setModels] = useState<MLModelSummary[]>([]);
  const [trainingRuns, setTrainingRuns] = useState<MLTrainingRun[]>([]);
  const [trainingResult, setTrainingResult] = useState<MLTrainResult | null>(null);
  const [prediction, setPrediction] = useState<MLPrediction | null>(null);
  const [loading, setLoading] = useState(true);
  const [training, setTraining] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [form, setForm] = useState<MLTrainInput>({
    model_name: "InvestEdge logistic 14d",
    model_type: "LOGISTIC_REGRESSION",
    target_type: "POSITIVE_RETURN",
    horizon_days: 14,
    symbols: [],
    benchmark_symbol: "SPY",
    test_size_time_percent: 25,
    min_samples: 200,
  });
  const [universeScope, setUniverseScope] = useState<UniverseLevel | "CUSTOM">("CORE");
  const [selectedModelId, setSelectedModelId] = useState<number | "latest">("latest");
  const [selectedSymbol, setSelectedSymbol] = useState("AAPL");

  async function loadLab() {
    setLoading(true);
    setError(null);
    try {
      const [statusResponse, assetResponse, universeResponse, modelResponse, runResponse] = await Promise.all([
        apiGet<MLStatus>("/ml/status"),
        apiGet<Asset[]>("/assets"),
        apiGet<UniverseAsset[]>("/universe?active_only=true&limit=1000"),
        apiGet<MLModelSummary[]>("/ml/models"),
        apiGet<MLTrainingRun[]>("/ml/training-runs"),
      ]);
      setStatus(statusResponse);
      setAssets(assetResponse);
      setUniverseAssets(universeResponse);
      setModels(modelResponse);
      setTrainingRuns(runResponse);
      const coreSymbols = universeResponse
        .filter((asset) => asset.universe_level === "CORE" && asset.last_price != null)
        .map((asset) => asset.symbol)
        .slice(0, 75);
      setForm((current) => (current.symbols.length > 0 ? current : { ...current, symbols: coreSymbols }));
      if (!selectedSymbol && assetResponse[0]) {
        setSelectedSymbol(assetResponse[0].symbol);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento AI Lab.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadLab();
  }, []);

  const selectedModelPayload = useMemo(
    () => (selectedModelId === "latest" ? {} : { model_id: selectedModelId }),
    [selectedModelId],
  );
  const trainingAssets = useMemo(() => {
    const priced = universeAssets.filter((asset) => asset.last_price != null);
    if (universeScope === "CUSTOM") {
      return priced;
    }
    return priced.filter((asset) => asset.universe_level === universeScope);
  }, [universeAssets, universeScope]);

  async function trainModel() {
    setTraining(true);
    setError(null);
    setMessage(null);
    try {
      const result = await apiPost<MLTrainResult>("/ml/train", form);
      setTrainingResult(result);
      setMessage(`Modello addestrato: ID ${result.model_id}`);
      setSelectedModelId(result.model_id);
      await loadLab();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Training non riuscito.");
    } finally {
      setTraining(false);
    }
  }

  async function runPrediction() {
    setPredicting(true);
    setError(null);
    setMessage(null);
    try {
      setPrediction(await apiPost<MLPrediction>(`/ml/predict/${selectedSymbol}`, selectedModelPayload));
    } catch (err) {
      setPrediction(null);
      setError(err instanceof Error ? err.message : "Prediction non riuscita.");
    } finally {
      setPredicting(false);
    }
  }

  function toggleSymbol(symbol: string) {
    setForm((current) => {
      const hasSymbol = current.symbols.includes(symbol);
      return {
        ...current,
        symbols: hasSymbol ? current.symbols.filter((item) => item !== symbol) : [...current.symbols, symbol],
      };
    });
  }

  function updateUniverseScope(nextScope: UniverseLevel | "CUSTOM") {
    setUniverseScope(nextScope);
    if (nextScope === "CUSTOM") {
      return;
    }
    const symbols = universeAssets
      .filter((asset) => asset.universe_level === nextScope && asset.last_price != null)
      .map((asset) => asset.symbol)
      .slice(0, nextScope === "CORE" ? 75 : 50);
    setForm((current) => ({ ...current, symbols }));
  }

  const latestModel = status?.latest_model ?? models[0] ?? null;
  const probability = probabilityValue(prediction);
  const trainingMetrics = trainingResult?.metrics ?? latestModel?.metrics ?? {};
  const featureImportance = (trainingMetrics.feature_importance as Array<{ feature: string; importance: number }> | undefined) ?? [];
  const confusionMatrix = trainingMetrics.confusion_matrix as number[][] | undefined;

  if (loading) {
    return (
      <Panel title="AI Lab">
        <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">Machine Learning probabilistico</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">AI Lab</h1>
        </div>
        <button
          onClick={() => void loadLab()}
          className="inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20"
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Aggiorna
        </button>
      </header>

      {error && (
        <Panel title="Errore">
          <p className="text-sm text-rose-300">{error}</p>
        </Panel>
      )}

      {message && (
        <div className="rounded-lg border border-cyan-300/20 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">
          {message}
        </div>
      )}

      {status && !status.ml_ready && (
        <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
          Nessun modello ML disponibile. Addestra un modello da AI Lab.
        </div>
      )}

      {status && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Modelli" value={`${status.models_count}`} delta={status.ml_ready ? "ML pronto" : "Da addestrare"} tone={status.ml_ready ? "green" : "amber"} icon={BrainCircuit} />
          <MetricCard label="Ultimo modello" value={latestModel?.model_name ?? "N/D"} delta={latestModel ? `${latestModel.model_type} ${latestModel.horizon_days}d` : status.message} tone="cyan" icon={Sparkles} />
          <MetricCard label="Ultimo target" value={latestModel?.target_type ?? "N/D"} delta="Output probabilistico" tone="cyan" icon={Play} />
          <MetricCard label="Campioni ultimo run" value={`${status.latest_training_run?.samples_count ?? 0}`} delta={status.latest_training_run?.created_at ?? "Nessun training"} tone="green" icon={RefreshCw} />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <Panel title="Training">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Nome modello</span>
              <input
                value={form.model_name}
                onChange={(event) => setForm((current) => ({ ...current, model_name: event.target.value }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Model type</span>
              <select
                value={form.model_type}
                onChange={(event) => setForm((current) => ({ ...current, model_type: event.target.value as MLModelType }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              >
                <option value="LOGISTIC_REGRESSION">Logistic Regression</option>
                <option value="RANDOM_FOREST">Random Forest</option>
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Target</span>
              <select
                value={form.target_type}
                onChange={(event) => setForm((current) => ({ ...current, target_type: event.target.value as MLTargetType }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              >
                {(Object.keys(targetLabels) as MLTargetType[]).map((target) => (
                  <option key={target} value={target}>
                    {targetLabels[target]}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Horizon days</span>
              <select
                value={form.horizon_days}
                onChange={(event) => setForm((current) => ({ ...current, horizon_days: Number(event.target.value) }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              >
                {[7, 14, 30, 60].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Benchmark</span>
              <input
                value={form.benchmark_symbol}
                onChange={(event) => setForm((current) => ({ ...current, benchmark_symbol: event.target.value.toUpperCase() }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Min samples</span>
              <input
                type="number"
                value={form.min_samples}
                onChange={(event) => setForm((current) => ({ ...current, min_samples: Number(event.target.value) }))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              />
            </label>
          </div>

          <div className="mt-5">
            <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-400">Asset</p>
              <select
                value={universeScope}
                onChange={(event) => updateUniverseScope(event.target.value as UniverseLevel | "CUSTOM")}
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
              >
                <option value="CORE">Core universe default</option>
                <option value="EXTENDED">Extended universe esplicito</option>
                <option value="CUSTOM">Custom selection</option>
              </select>
            </div>
            {universeScope === "EXTENDED" && (
              <p className="mb-2 text-xs text-amber-300">Extended universe: limite pratico 50 asset e solo ticker con storico prezzi disponibile.</p>
            )}
            <div className="grid max-h-52 gap-2 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/50 p-3 sm:grid-cols-2 lg:grid-cols-3">
              {trainingAssets.map((asset) => (
                <label key={asset.symbol} className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={form.symbols.includes(asset.symbol)}
                    onChange={() => toggleSymbol(asset.symbol)}
                    className="h-4 w-4 accent-cyan-300"
                  />
                  <span>{asset.symbol}</span>
                  <span className="text-xs text-slate-500">{asset.universe_level}</span>
                </label>
              ))}
              {trainingAssets.length === 0 && <p className="text-sm text-slate-500">Nessun asset prezzato disponibile per questa sorgente.</p>}
            </div>
          </div>

          <button
            onClick={() => void trainModel()}
            disabled={training || form.symbols.length === 0}
            className="mt-5 inline-flex items-center justify-center gap-2 rounded-md border border-emerald-300/30 bg-emerald-400/10 px-4 py-2 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-400/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <BrainCircuit className="h-4 w-4" aria-hidden="true" />
            {training ? "Training..." : "Train model"}
          </button>
        </Panel>

        <Panel title="Risultati training">
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ["Accuracy", metricValue(trainingMetrics.accuracy)],
              ["Precision", metricValue(trainingMetrics.precision)],
              ["Recall", metricValue(trainingMetrics.recall)],
              ["F1", metricValue(trainingMetrics.f1_score)],
              ["ROC AUC", metricValue(trainingMetrics.roc_auc)],
              ["Samples", metricValue(trainingMetrics.samples_count)],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="text-xs uppercase text-slate-500">{label}</p>
                <p className="mt-2 text-xl font-semibold text-white">
                  {typeof value === "number" ? (label === "Samples" ? value.toFixed(0) : value.toFixed(3)) : "N/D"}
                </p>
              </div>
            ))}
          </div>

          {confusionMatrix && (
            <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
              <p className="text-xs uppercase text-slate-500">Confusion matrix</p>
              <div className="mt-3 grid max-w-xs grid-cols-2 gap-2 text-center text-sm">
                {confusionMatrix.flat().map((value, index) => (
                  <span key={index} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white">
                    {value}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="mt-4">
            <p className="mb-2 text-sm text-slate-400">Feature importance</p>
            <div className="space-y-2">
              {featureImportance.slice(0, 8).map((item) => (
                <div key={item.feature}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-slate-400">{item.feature}</span>
                    <span className="text-white">{item.importance.toFixed(4)}</span>
                  </div>
                  <div className="h-2 rounded-full bg-slate-800">
                    <div className="h-2 rounded-full bg-cyan-300" style={{ width: `${Math.min(100, Math.abs(item.importance) * 100)}%` }} />
                  </div>
                </div>
              ))}
              {featureImportance.length === 0 && <p className="text-sm text-slate-500">Nessuna feature importance disponibile.</p>}
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Panel title="Prediction">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Modello</span>
              <select
                value={selectedModelId}
                onChange={(event) => setSelectedModelId(event.target.value === "latest" ? "latest" : Number(event.target.value))}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              >
                <option value="latest">Ultimo compatibile</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    #{model.id} {model.model_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-slate-400">Asset</span>
              <select
                value={selectedSymbol}
                onChange={(event) => setSelectedSymbol(event.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-white outline-none focus:border-cyan-300/60"
              >
                {assets.map((asset) => (
                  <option key={asset.symbol} value={asset.symbol}>
                    {asset.symbol} - {asset.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            onClick={() => void runPrediction()}
            disabled={predicting || models.length === 0}
            className="mt-5 inline-flex items-center justify-center gap-2 rounded-md border border-cyan-300/30 bg-cyan-400/10 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Play className="h-4 w-4" aria-hidden="true" />
            {predicting ? "Predicting..." : "Predict"}
          </button>
        </Panel>

        <Panel title="Output prediction">
          {prediction ? (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-4">
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase text-slate-500">Probabilita</p>
                  <p className="mt-2 text-2xl font-semibold text-white">
                    {probability == null ? "N/D" : formatPercent(probability * 100)}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase text-slate-500">Label</p>
                  <p className="mt-2 text-sm font-semibold text-white">{prediction.predicted_label}</p>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase text-slate-500">Confidence</p>
                  <span className={`mt-2 inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${confidenceTone(prediction.confidence)}`}>
                    {prediction.confidence}
                  </span>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                  <p className="text-xs uppercase text-slate-500">Target</p>
                  <p className="mt-2 text-sm font-semibold text-white">
                    {prediction.target_type} {prediction.horizon_days}d
                  </p>
                </div>
              </div>

              {prediction.warnings.length > 0 && (
                <div className="rounded-lg border border-amber-300/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
                  {prediction.warnings.join(" ")}
                </div>
              )}

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-2 text-sm text-slate-400">Feature positive</p>
                  <div className="space-y-2">
                    {(prediction.explanation.top_features_positive ?? []).slice(0, 6).map((item) => (
                      <div key={item.feature} className="flex justify-between rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2 text-sm">
                        <span className="text-slate-300">{item.feature}</span>
                        <span className="text-emerald-300">{item.importance.toFixed(4)}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="mb-2 text-sm text-slate-400">Feature negative</p>
                  <div className="space-y-2">
                    {(prediction.explanation.top_features_negative ?? []).slice(0, 6).map((item) => (
                      <div key={item.feature} className="flex justify-between rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2 text-sm">
                        <span className="text-slate-300">{item.feature}</span>
                        <span className="text-rose-300">{item.importance.toFixed(4)}</span>
                      </div>
                    ))}
                    {(prediction.explanation.top_features_negative ?? []).length === 0 && <p className="text-sm text-slate-500">Non disponibile per questo modello.</p>}
                  </div>
                </div>
              </div>
              <p className="text-xs text-slate-500">ML sperimentale, non garanzia di rendimento e non sostituisce score tecnico o gestione rischio.</p>
            </div>
          ) : (
            <p className="text-sm text-slate-400">
              {models.length === 0 ? "Nessun modello ML disponibile. Addestra un modello da AI Lab." : "Seleziona modello e asset, poi esegui una prediction."}
            </p>
          )}
        </Panel>
      </div>

      <Panel title="Modelli addestrati">
        {models.length === 0 ? (
          <p className="text-sm text-slate-400">Nessun modello ML disponibile. Addestra un modello da AI Lab.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-left text-xs uppercase text-slate-500">
                  <th className="px-3 pb-3 pl-0 font-medium">Model</th>
                  <th className="px-3 pb-3 font-medium">Type</th>
                  <th className="px-3 pb-3 font-medium">Target</th>
                  <th className="px-3 pb-3 text-right font-medium">Horizon</th>
                  <th className="px-3 pb-3 text-right font-medium">F1</th>
                  <th className="px-3 pb-3 text-right font-medium">ROC AUC</th>
                  <th className="px-3 pb-3 font-medium">Trained at</th>
                  <th className="px-3 pb-3 pr-0 text-right font-medium">Azione</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {models.map((model) => (
                  <tr key={model.id} className="text-sm">
                    <td className="px-3 py-4 pl-0">
                      <p className="font-semibold text-white">#{model.id} {model.model_name}</p>
                      <p className="mt-1 text-xs text-slate-500">{model.symbols_scope.join(", ")}</p>
                    </td>
                    <td className="px-3 py-4 text-slate-300">{model.model_type}</td>
                    <td className="px-3 py-4 text-slate-300">{model.target_type}</td>
                    <td className="px-3 py-4 text-right text-slate-300">{model.horizon_days}d</td>
                    <td className="px-3 py-4 text-right text-slate-200">{metricValue(model.metrics.f1_score)?.toFixed(3) ?? "N/D"}</td>
                    <td className="px-3 py-4 text-right text-slate-200">{metricValue(model.metrics.roc_auc)?.toFixed(3) ?? "N/D"}</td>
                    <td className="px-3 py-4 text-slate-400">{model.trained_at ?? "N/D"}</td>
                    <td className="px-3 py-4 pr-0 text-right">
                      <button
                        onClick={() => setSelectedModelId(model.id)}
                        className="rounded-md border border-cyan-300/30 bg-cyan-400/10 px-3 py-1.5 text-xs font-semibold text-cyan-100"
                      >
                        Usa modello
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {trainingRuns.length > 0 && (
        <Panel title="Training history">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {trainingRuns.slice(0, 8).map((run) => (
              <article key={run.id} className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
                <p className="font-semibold text-white">{run.model_name}</p>
                <p className="mt-1 text-xs text-slate-500">{run.target_type} {run.horizon_days}d</p>
                <p className="mt-3 text-sm text-slate-300">F1 {run.f1_score?.toFixed(3) ?? "N/D"} · {run.samples_count} campioni</p>
              </article>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
