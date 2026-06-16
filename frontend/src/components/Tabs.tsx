import type { ReactNode } from "react";

export type TabItem = {
  id: string;
  label: string;
  badge?: ReactNode;
  icon?: ReactNode;
};

type TabsProps = {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
};

/**
 * Barra a schede compatta: mostra una cosa alla volta e tiene le pagine corte.
 * Il contenuto di ogni scheda lo gestisce la pagina in base a `active`.
 */
export function Tabs({ tabs, active, onChange, className = "" }: TabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Sezioni"
      className={[
        "flex flex-wrap items-center gap-1 rounded-xl border border-slate-800/60 bg-slate-950/55 p-1",
        className,
      ].join(" ")}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={[
              "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition",
              isActive
                ? "bg-cyan-400/15 text-cyan-50 shadow-glow ring-1 ring-cyan-300/30"
                : "text-slate-400 hover:bg-slate-900 hover:text-slate-200",
            ].join(" ")}
          >
            {tab.icon}
            {tab.label}
            {tab.badge != null && (
              <span
                className={[
                  "inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-[11px] font-semibold",
                  isActive ? "bg-cyan-300/20 text-cyan-100" : "bg-slate-800 text-slate-400",
                ].join(" ")}
              >
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
