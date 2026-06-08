import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDownRight,
  CheckCircle2,
  Eye,
  RefreshCw,
  ShoppingCart,
  TrendingDown,
  type LucideIcon,
} from "lucide-react";

import { Send } from "lucide-react";

import { PageHeader, PageHeaderAction } from "../components/PageHeader";
import { Panel } from "../components/Panel";
import {
  apiGet,
  apiPost,
  type ActionBoard,
  type ActionItem,
  type ActionType,
  type AlertSendResult,
  type AlertStatus,
} from "../lib/api";

type Style = {
  icon: LucideIcon;
  badge: string;
  ring: string;
  label: string;
  cta: string | null;
};

const styles: Record<ActionType, Style> = {
  BUY: {
    icon: ShoppingCart,
    badge: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
    ring: "border-emerald-300/25",
    label: "Da comprare",
    cta: "Apri in Trade Republic",
  },
  REDUCE: {
    icon: ArrowDownRight,
    badge: "border-amber-300/30 bg-amber-400/10 text-amber-200",
    ring: "border-amber-300/25",
    label: "Da alleggerire",
    cta: "Rivedi posizione",
  },
  SELL: {
    icon: TrendingDown,
    badge: "border-rose-300/30 bg-rose-400/10 text-rose-200",
    ring: "border-rose-300/25",
    label: "Da vendere",
    cta: "Rivedi posizione",
  },
  WATCH: {
    icon: Eye,
    badge: "border-cyan-300/30 bg-cyan-400/10 text-cyan-200",
    ring: "border-cyan-300/25",
    label: "Da osservare",
    cta: null,
  },
  RISK: {
    icon: AlertTriangle,
    badge: "border-rose-300/30 bg-rose-400/10 text-rose-200",
    ring: "border-rose-300/25",
    label: "Rischio",
    cta: null,
  },
  OK: {
    icon: CheckCircle2,
    badge: "border-emerald-300/30 bg-emerald-400/10 text-emerald-200",
    ring: "border-emerald-300/20",
    label: "Tutto ok",
    cta: null,
  },
};

const priorityLabel: Record<string, string> = {
  HIGH: "Priorità alta",
  MEDIUM: "Priorità media",
  LOW: "Priorità bassa",
};

function ActionCard({ action }: { action: ActionItem }) {
  const style = styles[action.type] ?? styles.WATCH;
  const Icon = style.icon;
  const trUrl = action.symbol
    ? `https://traderepublic.com/`
    : null;
  return (
    <article className={`relative overflow-hidden rounded-2xl border bg-slate-950/55 p-5 shadow-panel transition-all duration-300 hover:-translate-y-[2px] ${style.ring}`}>
      <div className="flex items-start gap-4">
        <span className={`inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border ${style.badge}`}>
          <Icon className="h-5 w-5" aria-hidden="true" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.16em] ${style.badge}`}>
              {style.label}
            </span>
            {action.symbol && <span className="font-mono text-sm font-semibold text-white">{action.symbol}</span>}
            {action.score != null && (
              <span className="num text-xs text-slate-500">score {action.score.toFixed(0)}/100</span>
            )}
          </div>
          <h3 className="mt-2 font-display text-lg font-medium leading-snug text-white">{action.title}</h3>
          <p className="mt-1 text-sm leading-relaxed text-slate-400">{action.reason}</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-600">
              {priorityLabel[action.priority] ?? action.priority}
            </span>
            {style.cta && action.type === "BUY" && trUrl && (
              <a
                href={trUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md border border-emerald-300/30 bg-emerald-400/10 px-3 py-1.5 text-xs font-semibold text-emerald-100 transition hover:bg-emerald-400/20"
              >
                {style.cta}
              </a>
            )}
            {style.cta && action.type !== "BUY" && action.symbol && (
              <Link
                to={`/analysis?symbol=${action.symbol}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-slate-800"
              >
                {style.cta}
              </Link>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

export function TodayPage() {
  const [board, setBoard] = useState<ActionBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alert, setAlert] = useState<AlertStatus | null>(null);
  const [sending, setSending] = useState(false);
  const [sendMessage, setSendMessage] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [boardData, alertData] = await Promise.all([
        apiGet<ActionBoard>("/action-board"),
        apiGet<AlertStatus>("/alerts/status").catch(() => null),
      ]);
      setBoard(boardData);
      setAlert(alertData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento.");
    } finally {
      setLoading(false);
    }
  }

  async function sendToTelegram() {
    setSending(true);
    setSendMessage(null);
    try {
      const result = await apiPost<AlertSendResult>("/alerts/send-today");
      setSendMessage(
        result.ok ? "Inviato su Telegram ✓ Controlla il telefono." : "Invio non riuscito.",
      );
    } catch (err) {
      setSendMessage(err instanceof Error ? err.message : "Invio non riuscito.");
    } finally {
      setSending(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (loading) {
    return (
      <Panel title="Cosa fare oggi">
        <div className="h-48 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60" />
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="InvestEdge / Oggi"
        index="00"
        title="Cosa fare oggi"
        subtitle={board?.headline ?? "Le azioni più importanti per il tuo portafoglio, in ordine di priorità."}
        actions={
          <>
            {alert?.configured && (
              <PageHeaderAction
                icon={<Send className={`h-4 w-4 ${sending ? "animate-pulse" : ""}`} aria-hidden="true" />}
                onClick={() => void sendToTelegram()}
                disabled={sending}
              >
                {sending ? "Invio..." : "Inviami su Telegram"}
              </PageHeaderAction>
            )}
            <PageHeaderAction
              variant="primary"
              icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
              onClick={() => void load()}
            >
              Analizza oggi
            </PageHeaderAction>
          </>
        }
      />

      {sendMessage && (
        <div className="rounded-lg border border-cyan-300/20 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">
          {sendMessage}
        </div>
      )}

      {error && (
        <Panel title="Errore">
          <p className="text-sm text-rose-300">{error}</p>
        </Panel>
      )}

      {board && board.data_mode === "SEED" && (
        <div className="flex flex-col gap-3 rounded-2xl border border-amber-300/30 bg-amber-400/[0.08] p-4 text-sm text-amber-100 sm:flex-row sm:items-center sm:justify-between">
          <p>
            <span className="font-semibold">Stai vedendo dati simulati.</span> Le indicazioni qui sotto sono solo dimostrative
            finché non attivi i dati reali.
          </p>
          <Link
            to="/data"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-amber-300/40 bg-amber-400/15 px-3 py-2 text-xs font-semibold text-amber-50 transition hover:bg-amber-400/25"
          >
            Attiva dati reali →
          </Link>
        </div>
      )}

      {board && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <CountTile label="Da comprare" value={board.counts.buy ?? 0} tone="text-emerald-300" />
          <CountTile label="Da alleggerire" value={board.counts.reduce ?? 0} tone="text-amber-300" />
          <CountTile label="Da vendere" value={board.counts.sell ?? 0} tone="text-rose-300" />
          <CountTile label="Avvisi rischio" value={board.counts.risk ?? 0} tone="text-rose-300" />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {board?.actions.map((action, index) => (
          <ActionCard key={`${action.type}-${action.symbol ?? index}`} action={action} />
        ))}
      </div>

      <p className="text-center text-xs text-slate-600">
        Le indicazioni sono un supporto decisionale, non consigli finanziari. Gli ordini li esegui tu su Trade Republic.
      </p>
    </div>
  );
}

function CountTile({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-2xl border border-slate-800/60 bg-slate-950/55 p-4 shadow-panel">
      <p className="eyebrow-muted">{label}</p>
      <p className={`number-lg mt-2 ${value > 0 ? tone : "text-slate-600"}`}>{value}</p>
    </div>
  );
}
