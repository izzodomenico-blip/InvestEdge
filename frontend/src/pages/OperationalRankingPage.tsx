import { useEffect, useState } from "react";
import { TrendingUp, Eye, ArrowDownCircle, XCircle, Info, CheckCircle2 } from "lucide-react";
import { Panel } from "../components/Panel";
import { api, type OperationalRanking, type ValidatedSignal } from "../lib/api";

export function OperationalRankingPage() {
  const [ranking, setRanking] = useState<OperationalRanking | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadRanking() {
    setLoading(true);
    setError(null);
    try {
      setRanking(await api.getOperationalRanking());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore durante il caricamento del ranking operativo.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRanking();
  }, []);

  if (loading) return <div className="p-8 text-center">Caricamento ranking operativo...</div>;
  if (error) return <div className="p-8 text-center text-red-500">{error}</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <TrendingUp className="w-6 h-6 text-emerald-500" />
          Operational Ranking
        </h1>
        <button
          onClick={loadRanking}
          className="px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition-colors text-sm font-medium"
        >
          Aggiorna Ranking
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6">
        <RankingSection 
          title="BUY Candidates" 
          signals={ranking?.buy_candidates || []} 
          icon={<TrendingUp className="w-5 h-5 text-emerald-500" />}
          colorClass="text-emerald-400"
        />
        
        <RankingSection 
          title="WATCH (Confirmation Required)" 
          signals={ranking?.watch_candidates || []} 
          icon={<Eye className="w-5 h-5 text-amber-500" />}
          colorClass="text-amber-400"
        />

        <RankingSection 
          title="REDUCE / SELL Candidates" 
          signals={ranking?.reduce_candidates || []} 
          icon={<ArrowDownCircle className="w-5 h-5 text-rose-500" />}
          colorClass="text-rose-400"
        />

        <RankingSection 
          title="EXCLUDED (Low Data Quality)" 
          signals={ranking?.excluded_candidates || []} 
          icon={<XCircle className="w-5 h-5 text-slate-500" />}
          colorClass="text-slate-400"
        />
      </div>
    </div>
  );
}

function RankingSection({ title, signals, icon, colorClass }: { 
  title: string; 
  signals: ValidatedSignal[]; 
  icon: React.ReactNode;
  colorClass: string;
}) {
  if (signals.length === 0) return null;

  return (
    <Panel title={title} icon={icon}>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400 text-sm">
              <th className="pb-3 font-medium">Symbol</th>
              <th className="pb-3 font-medium">Technical</th>
              <th className="pb-3 font-medium">Validated</th>
              <th className="pb-3 font-medium">Data Quality</th>
              <th className="pb-3 font-medium">ML / News</th>
              <th className="pb-3 font-medium">Portfolio</th>
              <th className="pb-3 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {signals.map((s) => (
              <tr key={s.symbol} className="hover:bg-slate-800/50 transition-colors">
                <td className={`py-4 font-bold ${colorClass}`}>{s.symbol}</td>
                <td className="py-4">
                  <span className="text-xs px-2 py-0.5 bg-slate-700 rounded text-slate-300">
                    {s.original_signal}
                  </span>
                </td>
                <td className="py-4">
                  <span className={`text-xs px-2 py-0.5 rounded font-bold ${
                    s.validated_signal.includes('BUY') ? 'bg-emerald-500/20 text-emerald-400' :
                    s.validated_signal === 'HOLD' ? 'bg-amber-500/20 text-amber-400' :
                    'bg-rose-500/20 text-rose-400'
                  }`}>
                    {s.validated_signal}
                  </span>
                </td>
                <td className="py-4">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium ${s.data_quality_score >= 80 ? 'text-emerald-400' : s.data_quality_score >= 50 ? 'text-amber-400' : 'text-rose-400'}`}>
                      {s.data_quality_score.toFixed(0)}%
                    </span>
                  </div>
                </td>
                <td className="py-4">
                  <div className="flex flex-col gap-1">
                    {s.ml_confidence && (
                      <span className={`text-[10px] px-1 rounded ${s.ml_confidence === 'HIGH' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-slate-700 text-slate-400'}`}>
                        ML: {s.ml_confidence}
                      </span>
                    )}
                    {s.news_sentiment && (
                      <span className={`text-[10px] px-1 rounded ${s.news_sentiment === 'POSITIVE' ? 'bg-emerald-500/10 text-emerald-500' : s.news_sentiment === 'NEGATIVE' ? 'bg-rose-500/10 text-rose-500' : 'bg-slate-700 text-slate-400'}`}>
                        News: {s.news_sentiment}
                      </span>
                    )}
                  </div>
                </td>
                <td className="py-4 text-sm">
                  {s.portfolio_weight?.toFixed(1)}%
                </td>
                <td className="py-4">
                  <div className="group relative">
                    <Info className="w-4 h-4 text-slate-500 cursor-help" />
                    <div className="invisible group-hover:visible absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 bg-slate-900 border border-slate-700 rounded text-xs text-slate-300 z-10 shadow-xl">
                      {s.reason}
                    </div>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
