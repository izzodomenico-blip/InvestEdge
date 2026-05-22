import React, { useState, useEffect } from "react";
import { api, Portfolio } from "../lib/api";
import { Wallet, ChevronDown, Plus, LayoutGrid, Check } from "lucide-react";

interface PortfolioSelectorProps {
  onPortfolioChange?: (portfolio: Portfolio) => void;
}

export const PortfolioSelector: React.FC<PortfolioSelectorProps> = ({ onPortfolioChange }) => {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [activePortfolio, setActivePortfolio] = useState<Portfolio | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPortfolios();
  }, []);

  const fetchPortfolios = async () => {
    try {
      setLoading(true);
      const list = await api.listPortfolios();
      setPortfolios(list);
      
      const active = list.find(p => p.is_active) || list[0];
      if (active) {
        setActivePortfolio(active);
        // Persist active portfolio ID in localStorage for easy access across pages
        localStorage.setItem("activePortfolioId", active.id.toString());
      }
    } catch (error) {
      console.error("Failed to fetch portfolios", error);
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (p: Portfolio) => {
    if (activePortfolio?.id === p.id) {
      setIsOpen(false);
      return;
    }

    try {
      await api.activatePortfolio(p.id);
      setActivePortfolio(p);
      localStorage.setItem("activePortfolioId", p.id.toString());
      setIsOpen(false);
      
      if (onPortfolioChange) {
        onPortfolioChange(p);
      }
      
      // Refresh page to update all components using active portfolio
      window.location.reload();
    } catch (error) {
      console.error("Failed to activate portfolio", error);
    }
  };

  if (loading && !activePortfolio) {
    return <div className="h-10 w-48 bg-slate-800 animate-pulse rounded-md"></div>;
  }

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-3 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg border border-slate-700 transition-colors min-w-[200px] justify-between"
      >
        <div className="flex items-center gap-2 overflow-hidden">
          <Wallet size={18} className="text-blue-400 shrink-0" />
          <span className="font-medium truncate text-sm">
            {activePortfolio?.portfolio_name || "Seleziona Portafoglio"}
          </span>
        </div>
        <ChevronDown size={16} className={`transition-transform shrink-0 ${isOpen ? "rotate-180" : ""}`} />
      </button>

      {isOpen && (
        <>
          <div 
            className="fixed inset-0 z-40" 
            onClick={() => setIsOpen(false)}
          ></div>
          <div className="absolute top-full left-0 mt-2 w-64 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 overflow-hidden">
            <div className="p-2 border-b border-slate-700">
              <span className="text-xs font-semibold text-slate-400 uppercase px-2">I miei Portafogli</span>
            </div>
            
            <div className="max-h-60 overflow-y-auto py-1">
              {portfolios.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleSelect(p)}
                  className="w-full flex items-center justify-between px-4 py-2 hover:bg-slate-700 text-left transition-colors"
                >
                  <div className="flex flex-col overflow-hidden">
                    <span className={`text-sm font-medium truncate ${p.is_active ? "text-blue-400" : "text-slate-200"}`}>
                      {p.portfolio_name}
                    </span>
                    <span className="text-xs text-slate-500 truncate">{p.portfolio_type} • {p.base_currency}</span>
                  </div>
                  {p.is_active && <Check size={16} className="text-blue-400 shrink-0" />}
                </button>
              ))}
            </div>

            <div className="p-2 border-t border-slate-700 bg-slate-800/50">
              <a
                href="/portfolios"
                className="flex items-center gap-2 px-3 py-2 text-sm text-slate-300 hover:text-white hover:bg-slate-700 rounded-md transition-colors"
                onClick={() => setIsOpen(false)}
              >
                <LayoutGrid size={16} />
                Gestisci Portafogli
              </a>
              <button
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-blue-400 hover:text-blue-300 hover:bg-slate-700 rounded-md transition-colors mt-1"
                onClick={() => {
                   setIsOpen(false);
                   window.location.href = "/portfolios?action=new";
                }}
              >
                <Plus size={16} />
                Nuovo Portafoglio
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
