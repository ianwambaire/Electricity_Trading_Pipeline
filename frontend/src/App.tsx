import { ProtectedRoutes, AuthCallbackPage } from './auth/ProtectedRoutes'
import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'

import { lazy, Suspense } from 'react'
import { LoadingState } from './components/ui/States'

const MarketOverview = lazy(() => import('./pages/MarketOverview').then(m => ({ default: m.MarketOverview })))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage').then(m => ({ default: m.AnalyticsPage })))
const ForecastingPage = lazy(() => import('./pages/ForecastingPage').then(m => ({ default: m.ForecastingPage })))
const AnomaliesPage = lazy(() => import('./pages/AnomaliesPage').then(m => ({ default: m.AnomaliesPage })))
const ModelsPage = lazy(() => import('./pages/ModelsPage').then(m => ({ default: m.ModelsPage })))
const PipelinePage = lazy(() => import('./pages/PipelinePage').then(m => ({ default: m.PipelinePage })))
const ProfilePage = lazy(() => import('./pages/ProfilePage').then(m => ({ default: m.ProfilePage })))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then(m => ({ default: m.NotFoundPage })))

// Shared route tree for the authenticated application and isolated UI tests.
// Production entry always reaches it through ProtectedRoutes below.
export function WorkspaceRoutes() {
  return <Routes><Route element={<AppLayout />}>
    <Route index element={<MarketOverview />} />
    <Route path="forecasting" element={<ForecastingPage />} />
    <Route path="anomalies" element={<AnomaliesPage />} />
    <Route path="analytics" element={<AnalyticsPage />} />
    <Route path="pipeline" element={<PipelinePage />} />
    <Route path="models" element={<ModelsPage />} />
    <Route path="profile" element={<ProfilePage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Route></Routes>
}

export default function App() {
  return <Suspense fallback={<LoadingState label="Loading page…" />}><Routes>
    <Route path="auth/callback" element={<AuthCallbackPage />} />
    <Route element={<ProtectedRoutes />}><Route path="*" element={<WorkspaceRoutes />} /></Route>
  </Routes></Suspense>
}
