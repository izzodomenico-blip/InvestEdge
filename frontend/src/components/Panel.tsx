import type { ReactNode } from "react";

type PanelProps = {
  title?: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  innerClassName?: string;
  bare?: boolean;
};

export function Panel({
  title,
  eyebrow,
  action,
  children,
  className = "",
  innerClassName = "",
  bare = false,
}: PanelProps) {
  return (
    <section
      className={[
        "relative overflow-hidden rounded-2xl border border-slate-800/60 bg-slate-950/55 shadow-panel",
        "before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-cyan-300/25 before:to-transparent",
        className,
      ].join(" ")}
    >
      {(title || action || eyebrow) && (
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-800/60 px-6 py-5">
          <div className="min-w-0">
            {eyebrow && <p className="eyebrow-muted">{eyebrow}</p>}
            {title && (
              <h2 className="mt-1 font-display text-lg font-medium leading-tight text-white">
                {title}
              </h2>
            )}
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={[bare ? "" : "p-6", innerClassName].join(" ")}>{children}</div>
    </section>
  );
}
