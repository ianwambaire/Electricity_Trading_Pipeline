import { AnomaliesPage } from './pages/AnomaliesPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { ModelsPage } from './pages/ModelsPage'
import { ForecastingPage } from './pages/ForecastingPage'
import { PipelinePage } from './pages/PipelinePage'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { MarketOverview } from './pages/MarketOverview'
import { ProfilePage } from './pages/WorkspacePages'
import { NotFoundPage } from './pages/NotFoundPage'

export default function App() {
  return <BrowserRouter><Routes><Route element={<AppLayout />}>
    <Route index element={<MarketOverview />} />
    <Route path="forecasting" element={<ForecastingPage />} />
    <Route path="anomalies" element={<AnomaliesPage />} />
    <Route path="analytics" element={<AnalyticsPage />} />
    <Route path="pipeline" element={<PipelinePage />} />
    <Route path="models" element={<ModelsPage />} />
    <Route path="profile" element={<ProfilePage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Route></Routes></BrowserRouter>
}
