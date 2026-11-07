import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppProvider } from './contexts/AppContext'
import { AdminLayout } from './layouts/AdminLayout'
const OverviewPage = lazy(() => import('./pages/overview/OverviewPage').then((module) => ({ default: module.OverviewPage })))
const AnalyticsPage = lazy(() => import('./pages/analytics/AnalyticsPage').then((module) => ({ default: module.AnalyticsPage })))
const ResourcePage = lazy(() => import('./pages/resource/ResourcePage').then((module) => ({ default: module.ResourcePage })))
const AuthPage = lazy(() => import('./pages/resource/AuthPage').then((module) => ({ default: module.AuthPage })))
const resources = ['stores', 'tenants', 'platform-users', 'roles', 'plans', 'subscriptions', 'billing', 'payments', 'promotions', 'monitoring', 'audit-logs', 'notifications', 'integrations', 'settings', 'security', 'support']
const authRoutes = ['login', 'forgot-password', 'reset-password', 'two-factor', 'unauthorized', 'session-expired']
function Loading() {
  return <div className="page-loading"><div className="spinner-border text-primary" role="status"><span className="visually-hidden">Loading…</span></div><span>Loading workspace</span></div>
}
export default function App() {
  return <AppProvider><BrowserRouter><Suspense fallback={<Loading />}><Routes>
    <Route element={<AdminLayout />}>
      <Route path="/" element={<OverviewPage />} />
      <Route path="/analytics" element={<AnalyticsPage />} />
      {resources.map((path) => <Route key={path} path={`/${path}`} element={<ResourcePage />} />)}
    </Route>
    {authRoutes.map((path) => <Route key={path} path={`/${path}`} element={<AuthPage />} />)}
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></Suspense></BrowserRouter></AppProvider>
}
