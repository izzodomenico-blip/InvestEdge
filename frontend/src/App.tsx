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
import { StrategyControlPage } from "./pages/StrategyControlPage";
import { AlertCenterPage } from "./pages/AlertCenterPage";
import { SchedulerPage } from "./pages/SchedulerPage";
import { ReportsPage } from "./pages/ReportsPage";
import { PortfolioOptimizerPage } from "./pages/PortfolioOptimizerPage";
import { ScenarioAnalysisPage } from "./pages/ScenarioAnalysisPage";
import { BackupManagementPage } from "./pages/BackupManagementPage";
import { SettingsPage } from "./pages/SettingsPage";
import PortfolioManagerPage from "./pages/PortfolioManagerPage";
import GoogleSheetsImportPage from "./pages/GoogleSheetsImportPage";
import { TaxCenterPage } from "./pages/TaxCenterPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/portfolios" element={<PortfolioManagerPage />} />
        <Route path="/google-sheets" element={<GoogleSheetsImportPage />} />
        <Route path="/tax" element={<TaxCenterPage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />

        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/simulator" element={<SimulatorPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/news" element={<NewsPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/ranking" element={<OperationalRankingPage />} />
        <Route path="/strategy" element={<StrategyControlPage />} />
        <Route path="/optimizer" element={<PortfolioOptimizerPage />} />
        <Route path="/scenarios" element={<ScenarioAnalysisPage />} />
        <Route path="/backup" element={<BackupManagementPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/tax" element={<TaxCenterPage />} />
        <Route path="/alerts" element={<AlertCenterPage />} />
        <Route path="/scheduler" element={<SchedulerPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/audit" element={<SystemAuditPage />} />
        <Route path="/data" element={<DataCenterPage />} />
        <Route path="/universe" element={<UniversePage />} />
        <Route path="/ml" element={<MachineLearningPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
