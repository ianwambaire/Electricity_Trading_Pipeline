import { ProtectedRoutes, AuthCallbackPage } from './auth/ProtectedRoutes'
import { AnomaliesPage } from './pages/AnomaliesPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { ModelsPage } from './pages/ModelsPage'
import { ForecastingPage } from './pages/ForecastingPage'
import { PipelinePage } from './pages/PipelinePage'
import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { MarketOverview } from './pages/MarketOverview'
import { ProfilePage } from './pages/ProfilePage'
import { NotFoundPage } from './pages/NotFoundPage'

export default function App() {
  return <Routes><Route path="auth/callback" element={<AuthCallbackPage />} /><Route element={<ProtectedRoutes />}><Route element={<AppLayout />}>
    <Route index element={<MarketOverview />} />
    <Route path="forecasting" element={<ForecastingPage />} />
    <Route path="anomalies" element={<AnomaliesPage />} />
    <Route path="analytics" element={<AnalyticsPage />} />
    <Route path="pipeline" element={<PipelinePage />} />
    <Route path="models" element={<ModelsPage />} />
    <Route path="profile" element={<ProfilePage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Route></Route></Routes>
}
