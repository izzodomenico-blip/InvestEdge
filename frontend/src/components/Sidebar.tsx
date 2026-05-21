import {
  Activity,
  BarChart3,
  BriefcaseBusiness,
  BrainCircuit,
  CandlestickChart,
  Database,
  Gauge,
  Layers3,
  Newspaper,
  Repeat2,
  Search,
  ShieldCheck,
  TrendingUp,
  Settings2,
  Bell,
  Clock,
  FileText,
  Scale,
  ShieldAlert,
} from "lucide-react";
import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/watchlist", label: "Watchlist", icon: Search },
  { to: "/portfolio", label: "Portafoglio", icon: BriefcaseBusiness },
  { to: "/simulator", label: "Simulatore", icon: Repeat2 },
  { to: "/analysis", label: "Analisi Asset", icon: CandlestickChart },
  { to: "/ranking", label: "Ranking", icon: TrendingUp },
  { to: "/optimizer", label: "Optimizer", icon: Scale },
  { to: "/scenarios", label: "Stress Test", icon: ShieldAlert },
  { to: "/strategy", label: "Strategy Center", icon: Settings2 },
  { to: "/alerts", label: "Alert Center", icon: Bell },
  { to: "/scheduler", label: "Operations", icon: Clock },
  { to: "/reports", label: "Report", icon: FileText },
  { to: "/audit", label: "Audit", icon: ShieldCheck },
  { to: "/news", label: "News", icon: Newspaper },
  { to: "/backtest", label: "Backtest", icon: BarChart3 },
  { to: "/data", label: "Dati", icon: Database },
  { to: "/universe", label: "Universe", icon: Layers3 },
  { to: "/ml", label: "AI Lab", icon: BrainCircuit },
];

export function Sidebar() {
  return (
    <aside className="border-b border-slate-800/80 bg-ink-950/95 px-4 py-4 backdrop-blur lg:fixed lg:inset-y-0 lg:left-0 lg:w-72 lg:border-b-0 lg:border-r lg:px-5">
      <div className="flex items-center gap-3 lg:mb-8">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-cyan-300/25 bg-cyan-400/10 text-cyan-300">
          <Activity className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="text-base font-semibold text-white">InvestEdge</p>
          <p className="text-xs text-slate-500">Local investment lab</p>
        </div>
      </div>

      <nav className="no-scrollbar mt-4 flex gap-2 overflow-x-auto pb-1 lg:mt-0 lg:flex-col lg:overflow-visible lg:pb-0">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              [
                "flex min-w-fit items-center gap-3 rounded-md border px-3 py-2.5 text-sm transition",
                isActive
                  ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-100"
                  : "border-transparent text-slate-400 hover:border-slate-700 hover:bg-slate-900/70 hover:text-slate-100",
              ].join(" ")
            }
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
