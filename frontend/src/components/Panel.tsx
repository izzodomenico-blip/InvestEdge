import type { ReactNode } from "react";

type PanelProps = {
  title?: string;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function Panel({ title, icon, action, children, className = "" }: PanelProps) {
  return (
    <section className={`rounded-lg border border-slate-800/80 bg-slate-950/60 shadow-panel ${className}`}>
      {(title || action) && (
        <div className="flex min-h-14 items-center justify-between border-b border-slate-800/80 px-5 py-4">
          {title ? (
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              {icon}
              {title}
            </h2>
          ) : (
            <span />
          )}
          {action}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}
