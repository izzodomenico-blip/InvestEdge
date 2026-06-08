import type { ReactNode } from "react";

import { Sidebar } from "./Sidebar";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="relative min-h-screen">
      <Sidebar />
      <main className="relative px-4 pb-16 pt-6 sm:px-6 lg:ml-72 lg:px-10 lg:pb-24 lg:pt-10">
        <div className="mx-auto max-w-[1400px] animate-fade-up">{children}</div>
        <footer className="mx-auto mt-20 max-w-[1400px] border-t border-slate-800/60 pt-6">
          <div className="flex flex-col gap-3 text-[11px] text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <p className="font-mono uppercase tracking-eyebrow">
              InvestEdge <span className="text-cyan-300/70">/</span> local edition
              <span className="ml-2 text-slate-600">v0.1</span>
            </p>
            <p className="font-mono uppercase tracking-eyebrow">
              <span className="text-slate-600">Local only</span> · no live trading · no broker
            </p>
          </div>
        </footer>
      </main>
    </div>
  );
}
