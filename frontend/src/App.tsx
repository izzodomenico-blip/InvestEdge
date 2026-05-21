import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { AnalysisPage } from "./pages/AnalysisPage";
import { BacktestPage } from "./pages/BacktestPage";
import { DataCenterPage } from "./pages/DataCenterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { MachineLearningPage } from "./pages/MachineLearningPage";
import { NewsPage } from "./pages/NewsPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { SimulatorPage } from "./pages/SimulatorPage";
import { UniversePage } from "./pages/UniversePage";
import { WatchlistPage } from "./pages/WatchlistPage";
import { SystemAuditPage } from "./pages/SystemAuditPage";
import { OperationalRankingPage } from "./pages/OperationalRankingPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/simulator" element={<SimulatorPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/news" element={<NewsPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/ranking" element={<OperationalRankingPage />} />
        <Route path="/audit" element={<SystemAuditPage />} />
        <Route path="/data" element={<DataCenterPage />} />
        <Route path="/universe" element={<UniversePage />} />
        <Route path="/ml" element={<MachineLearningPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
