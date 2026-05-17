import { Newspaper } from "lucide-react";

import { Panel } from "../components/Panel";
import { newsItems } from "../lib/mockData";

const toneBySentiment: Record<string, string> = {
  positivo: "border-emerald-300/30 bg-emerald-400/10 text-emerald-300",
  neutrale: "border-cyan-300/30 bg-cyan-400/10 text-cyan-300",
  negativo: "border-rose-300/30 bg-rose-400/10 text-rose-300",
};

export function NewsPage() {
  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium text-cyan-300">News e sentiment</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">News</h1>
      </header>

      <Panel>
        <div className="space-y-4">
          {newsItems.map((item) => (
            <article key={item.title} className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="flex gap-3">
                  <span className="mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-700 bg-slate-950 text-slate-300">
                    <Newspaper className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <div>
                    <p className="text-xs uppercase text-slate-500">{item.source} · {item.time}</p>
                    <h2 className="mt-2 text-base font-semibold text-white">{item.title}</h2>
                  </div>
                </div>
                <span className={`inline-flex w-fit rounded-md border px-2.5 py-1 text-xs font-semibold ${toneBySentiment[item.sentiment]}`}>
                  {item.sentiment} {item.score > 0 ? "+" : ""}{item.score}
                </span>
              </div>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}
