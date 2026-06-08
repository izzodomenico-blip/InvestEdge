import { useState } from "react";
import { AlertTriangle, ShieldAlert, Siren, Zap } from "lucide-react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import { apiPost, type ScenarioResult, type ScenarioType } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/format";

const scenarios: { type: ScenarioType; label: string; desc: string }[] = [
  { type: "MARKET_CRASH", label: "Crollo di mercato", desc: "Ribasso ampio su azioni ed ETF, cripto in forte calo." },
  { type: "TECH_SELLOFF", label: "Sell-off tech", desc: "Vendite sui titoli growth/tecnologici." },
  { type: "CRYPTO_WINTER", label: "Inverno cripto", desc: "Cripto -55%, resto contenuto." },
  { type: "RATE_HIKE", label: "Rialzo tassi", desc: "Bond e ETF obbligazionari sotto pressione." },
  { type: "INFLATION_SHOCK", label: "Shock inflazione", desc: "Pressione su tutte le classi." },
  { type: "MILD_CORRECTION", label: "Correzione moderata", desc: "Ribasso lieve e diffuso." },
];

const riskTone: Record<string, string> = {
  LOW: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
  MEDIUM: "border-amber-300/30 bg-amber-400/10 text-amber-200",
  HIGH: "border-rose-300/30 bg-rose-400/10 text-rose-200",
  EXTREME: "border-rose-300/40 bg-rose-500/15 text-rose-100",
};

export function ScenarioPage() {
  const [selected, setSelected] = useState<ScenarioType>("MARKET_CRASH");
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(type: ScenarioType) {
    setSelected(type);
    setRunning(true);
    setError(null);
    try {
      setResult(await apiPost<ScenarioResult>("/scenarios/run", { scenario_type: type }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulazione non riuscita.");
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  const chartData = result
    ? result.class_impacts.map((c) => ({ name: c.asset_class, loss: c.absolute_impact }))
    : [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Stress test"
        index="08"
        title="Scenari"
        subtitle="Simula cosa succederebbe al tuo portafoglio in condizioni di mercato avverse. Solo stima, non una previsione."
        actions={
          <PageHeaderAction
            variant="primary"
            icon={<Siren className={`h-4 w-4 ${running ? "animate-pulse" : ""}`} aria-hidden="true" />}
            onClick={() => void run(selected)}
            disabled={running}
          >
            {running ? "Simulazione..." : "Rilancia scenario"}
          </PageHeaderAction>
        }
      />

      {error && (
        <div className="rounded-2xl border border-rose-300/30 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {scenarios.map((scenario) => (
          <button
            key={scenario.type}
            onClick={() => void run(scenario.type)}
            disabled={running}
            className={`rounded-2xl border p-4 text-left shadow-panel transition-all duration-200 hover:-translate-y-[2px] disabled:opacity-60 ${
              selected === scenario.type ? "border-cyan-300/40 bg-cyan-400/[0.07]" : "border-slate-800/60 bg-slate-950/55"
            }`}
          >
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-cyan-300" aria-hidden="true" />
              <span className="font-display text-base font-medium text-white">{scenario.label}</span>
            </div>
            <p className="mt-1 text-xs text-slate-400">{scenario.desc}</p>
          </button>
        ))}
      </div>

      {result && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Tile label="Valore attuale" value={formatCurrency(result.current_value, "EUR")} tone="text-white" />
            <Tile label="Valore sotto stress" value={formatCurrency(result.stressed_value, "EUR")} tone="text-amber-200" />
            <Tile label="Perdita stimata" value={formatCurrency(result.absolute_loss, "EUR")} tone="text-rose-300" />
            <div className="rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 shadow-panel">
              <p className="eyebrow-muted">Rischio scenario</p>
              <span className={`mt-2 inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-sm font-semibold ${riskTone[result.risk_level] ?? riskTone.MEDIUM}`}>
                <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                {result.risk_level} · {formatPercent(result.percentage_loss)}
              </span>
            </div>
          </div>

          <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
            <Panel eyebrow="Impatto per classe" title="Perdita per asset class">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} layout="vertical" margin={{ left: 12, right: 16, top: 8, bottom: 8 }}>
                    <XAxis type="number" stroke="#64748B" axisLine={false} tickLine={false} />
                    <YAxis dataKey="name" type="category" stroke="#94A3B8" axisLine={false} tickLine={false} width={80} />
                    <Tooltip contentStyle={{ background: "#0F172A", border: "1px solid #1E293B", borderRadius: 8 }} formatter={(v) => [formatCurrency(Number(v), "EUR"), "Impatto"]} />
                    <Bar dataKey="loss" radius={[0, 6, 6, 0]}>
                      {chartData.map((item) => (
                        <Cell key={item.name} fill={item.loss < 0 ? "#FB7185" : "#34D399"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>

            <Panel eyebrow="Cosa puoi fare" title="Mitigazioni suggerite">
              <ul className="space-y-3">
                {result.mitigation.map((tip) => (
                  <li key={tip} className="flex items-start gap-3 text-sm text-slate-300">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" />
                    {tip}
                  </li>
                ))}
              </ul>
            </Panel>
          </div>

          <Panel eyebrow="Dettaglio" title="Impatto per asset">
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {result.asset_impacts.map((impact) => (
                <div key={impact.symbol} className="rounded-xl border border-slate-800/60 bg-slate-950/55 p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-semibold text-white">{impact.symbol}</span>
                    <span className="num text-xs font-semibold text-rose-300">{formatPercent(impact.shock_percent)}</span>
                  </div>
                  <p className="num mt-1 text-sm text-slate-300">
                    {formatCurrency(impact.current_value, "EUR")} → {formatCurrency(impact.stressed_value, "EUR")}
                  </p>
                  <p className="num mt-0.5 text-xs text-rose-300">{formatCurrency(impact.absolute_impact, "EUR")}</p>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}

      {!result && !error && (
        <Panel title="Stress test del portafoglio">
          <p className="text-sm text-slate-400">Scegli uno scenario qui sopra per vedere la perdita stimata, l'impatto per classe e i suggerimenti di mitigazione. Serve un portafoglio con posizioni.</p>
        </Panel>
      )}
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 shadow-panel">
      <p className="eyebrow-muted">{label}</p>
      <p className={`number-lg mt-2 ${tone}`}>{value}</p>
    </div>
  );
}
