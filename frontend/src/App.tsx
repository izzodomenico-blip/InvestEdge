import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { AnalysisPage } from "./pages/AnalysisPage";
import { BacktestPage } from "./pages/BacktestPage";
import { DataCenterPage } from "./pages/DataCenterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ImportPage } from "./pages/ImportPage";
import { MachineLearningPage } from "./pages/MachineLearningPage";
import { NewsPage } from "./pages/NewsPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ScenarioPage } from "./pages/ScenarioPage";
import { SimulatorPage } from "./pages/SimulatorPage";
import { TaxCenterPage } from "./pages/TaxCenterPage";
import { TodayPage } from "./pages/TodayPage";
import { UniversePage } from "./pages/UniversePage";
import { WatchlistPage } from "./pages/WatchlistPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<TodayPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />
        <Route path="/universe" element={<UniversePage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/simulator" element={<SimulatorPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/ml" element={<MachineLearningPage />} />
        <Route path="/scenarios" element={<ScenarioPage />} />
        <Route path="/tax" element={<TaxCenterPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/news" element={<NewsPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/data" element={<DataCenterPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
