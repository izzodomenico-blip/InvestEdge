import {
  BarChart3,
  Brain,
  BriefcaseBusiness,
  CandlestickChart,
  Database,
  FileSpreadsheet,
  FileText,
  Gauge,
  Newspaper,
  Receipt,
  Repeat2,
  Search,
  Siren,
  Sparkles,
  Telescope,
  type LucideIcon,
} from "lucide-react";
import { NavLink } from "react-router-dom";

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  kbd?: string;
};

type NavSection = {
  label: string;
  index: string;
  items: NavItem[];
};

const sections: NavSection[] = [
  {
    label: "Cockpit",
    index: "01",
    items: [
      { to: "/", label: "Cosa fare oggi", icon: Sparkles },
      { to: "/dashboard", label: "Dashboard", icon: Gauge },
      { to: "/watchlist", label: "Watchlist", icon: Search },
      { to: "/universe", label: "Universe", icon: Telescope },
    ],
  },
  {
    label: "Operativo",
    index: "02",
    items: [
      { to: "/portfolio", label: "Portafoglio", icon: BriefcaseBusiness },
      { to: "/import", label: "Importa posizioni", icon: FileSpreadsheet },
      { to: "/simulator", label: "Simulatore", icon: Repeat2 },
      { to: "/analysis", label: "Analisi Asset", icon: CandlestickChart },
    ],
  },
  {
    label: "Intelligence",
    index: "03",
    items: [
      { to: "/ml", label: "Machine Learning", icon: Brain },
      { to: "/scenarios", label: "Scenari", icon: Siren },
      { to: "/tax", label: "Centro fiscale", icon: Receipt },
      { to: "/reports", label: "Reports", icon: FileText },
      { to: "/news", label: "News", icon: Newspaper },
      { to: "/backtest", label: "Backtest", icon: BarChart3 },
      { to: "/data", label: "Dati", icon: Database },
    ],
  },
];

function Mark() {
  return (
    <span className="relative inline-flex h-11 w-11 items-center justify-center rounded-xl border border-cyan-300/30 bg-gradient-to-br from-cyan-400/15 via-cyan-400/5 to-violet-400/10 shadow-glow">
      <svg
        viewBox="0 0 24 24"
        className="h-5 w-5 text-cyan-300"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3 17 L9 11 L13 14 L21 5" />
        <path d="M15 5 L21 5 L21 11" />
      </svg>
      <span className="absolute inset-0 -z-10 rounded-xl bg-cyan-400/20 blur-xl" aria-hidden="true" />
    </span>
  );
}

export function Sidebar() {
  return (
    <aside className="relative z-20 border-b border-slate-800/60 bg-ink-975/85 px-4 py-4 backdrop-blur-xl lg:fixed lg:inset-y-0 lg:left-0 lg:w-72 lg:border-b-0 lg:border-r lg:px-5 lg:py-7">
      <div className="flex items-center gap-3">
        <Mark />
        <div>
          <p className="font-display text-lg font-semibold leading-none tracking-tight text-white">
            InvestEdge
          </p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-eyebrow text-slate-500">
            Investment intelligence
          </p>
        </div>
      </div>

      <div className="mt-6 hidden h-px w-full bg-gradient-to-r from-cyan-300/40 via-slate-800/40 to-transparent lg:block" />

      <nav className="no-scrollbar mt-4 flex gap-2 overflow-x-auto pb-1 lg:mt-6 lg:flex-col lg:gap-6 lg:overflow-visible lg:pb-0">
        {sections.map((section) => (
          <div key={section.label} className="flex shrink-0 gap-2 lg:flex-col lg:gap-1">
            <div className="hidden items-center gap-2 px-1 lg:flex">
              <span className="font-mono text-[10px] text-cyan-300/70">{section.index}</span>
              <span className="eyebrow-muted">{section.label}</span>
              <span className="h-px flex-1 bg-slate-800/60" />
            </div>
            {section.items.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  [
                    "group relative flex min-w-fit items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-all duration-200",
                    isActive
                      ? "border-cyan-300/25 bg-cyan-400/10 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                      : "border-transparent text-slate-400 hover:border-slate-800/80 hover:bg-slate-900/60 hover:text-slate-100",
                  ].join(" ")
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      aria-hidden="true"
                      className={[
                        "absolute left-0 top-1/2 hidden h-5 -translate-y-1/2 rounded-r-full transition-all duration-300 lg:block",
                        isActive ? "w-[3px] bg-cyan-300 shadow-glow" : "w-0 bg-transparent",
                      ].join(" ")}
                    />
                    <span
                      className={[
                        "relative inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors duration-200",
                        isActive
                          ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-200"
                          : "border-slate-800/80 bg-slate-950/60 text-slate-400 group-hover:text-slate-200",
                      ].join(" ")}
                    >
                      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                    </span>
                    <span className="flex-1 truncate font-medium tracking-tight">{label}</span>
                    {isActive && (
                      <span
                        aria-hidden="true"
                        className="hidden h-1.5 w-1.5 rounded-full bg-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.8)] lg:block"
                      />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="mt-8 hidden rounded-xl border border-slate-800/60 bg-slate-950/40 p-4 lg:block">
        <div className="flex items-center gap-2">
          <span className="relative inline-flex h-2 w-2 items-center justify-center">
            <span className="absolute inset-0 animate-pulse-soft rounded-full bg-emerald-400/70" />
            <span className="relative h-1.5 w-1.5 rounded-full bg-emerald-300" />
          </span>
          <p className="font-mono text-[10px] uppercase tracking-eyebrow text-emerald-300/90">
            Local · online
          </p>
        </div>
        <p className="mt-3 font-display text-sm leading-snug text-slate-300">
          Nessuna chiamata esterna automatica.
        </p>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-eyebrow text-slate-500">
          Refresh manuale dal Data Center
        </p>
      </div>
    </aside>
  );
}
