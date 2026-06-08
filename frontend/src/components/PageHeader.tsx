import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow: string;
  index?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  meta?: ReactNode;
};

export function PageHeader({ eyebrow, index, title, subtitle, actions, meta }: PageHeaderProps) {
  return (
    <header className="relative overflow-hidden rounded-2xl border border-slate-800/60 bg-gradient-to-br from-slate-950/70 via-slate-950/40 to-slate-950/70 px-6 py-7 shadow-panel sm:px-8 sm:py-8">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-24 -top-32 h-72 w-72 rounded-full bg-cyan-400/10 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-20 -bottom-24 h-72 w-72 rounded-full bg-violet-400/8 blur-3xl"
      />
      <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 max-w-3xl">
          <div className="flex items-center gap-3">
            {index && (
              <span className="font-mono text-[11px] uppercase tracking-eyebrow text-cyan-300/80">
                {index}
              </span>
            )}
            <span className="eyebrow">{eyebrow}</span>
            <span className="hidden h-px flex-1 max-w-[7rem] bg-gradient-to-r from-cyan-300/40 to-transparent sm:block" />
          </div>
          <h1 className="display-1 mt-4">{title}</h1>
          {subtitle && (
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-slate-400">{subtitle}</p>
          )}
          {meta && (
            <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[11px] uppercase tracking-eyebrow text-slate-500">
              {meta}
            </div>
          )}
        </div>
        {actions && (
          <div className="flex flex-wrap items-center gap-2 lg:shrink-0 lg:justify-end">
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}

type PageHeaderActionProps = {
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "ghost";
  icon?: ReactNode;
  children: ReactNode;
  type?: "button" | "submit";
};

export function PageHeaderAction({
  onClick,
  disabled,
  variant = "ghost",
  icon,
  children,
  type = "button",
}: PageHeaderActionProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium tracking-tight transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50";
  const styles =
    variant === "primary"
      ? "border border-cyan-300/40 bg-cyan-400/15 text-cyan-50 hover:border-cyan-300/60 hover:bg-cyan-400/25 hover:shadow-glow"
      : "border border-slate-800/80 bg-slate-950/60 text-slate-200 hover:border-slate-700 hover:bg-slate-900 hover:text-white";
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${styles}`}>
      {icon}
      {children}
    </button>
  );
}
