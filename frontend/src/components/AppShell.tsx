import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { PortfolioSelector } from "./PortfolioSelector";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-slate-950">
      <Sidebar />
      
      {/* Header with Portfolio Selector */}
      <header className="lg:ml-72 h-16 border-b border-slate-800 flex items-center justify-between px-4 sm:px-6 lg:px-8 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-30">
        <div className="flex items-center gap-4">
          <PortfolioSelector />
        </div>
        <div className="hidden sm:flex items-center gap-4">
          {/* Future user profile / notifications info could go here */}
          <span className="text-xs text-slate-500 bg-slate-800 px-2 py-1 rounded border border-slate-700">Simulated Environment</span>
        </div>
      </header>

      <main className="px-4 py-6 sm:px-6 lg:ml-72 lg:px-8 lg:py-8">
        <div className="mx-auto max-w-7xl">{children}</div>
      </main>
    </div>
  );
}
