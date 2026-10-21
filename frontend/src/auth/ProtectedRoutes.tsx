import { useAuth } from 'react-oidc-context'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { LoadingState } from '../components/ui/States'
import { useClock } from '../hooks/useClock'
import { authGateState, sessionUsable } from './identity'
import { authConfig } from './runtime'
import { safeDestination } from './config'
import { SignInScreen } from './SignInScreen'

export function ProtectedRoutes() {
  const auth = useAuth()
  const location = useLocation()
  const now = useClock()
  const usable = !!authConfig && sessionUsable(auth.user, authConfig, now)
  const state = authGateState(auth.isLoading || !!auth.activeNavigator, !!auth.error, auth.isAuthenticated, usable)
  if (state === 'loading') return <main className="auth-page"><LoadingState label="Checking your secure session…" /></main>
  if (state === 'error') return <SignInScreen error returnTo={location.pathname} />
  if (state !== 'authenticated') return <SignInScreen expired={!!auth.user} returnTo={location.pathname} />
  return <Outlet />
}

// AuthProvider alone exchanges the authorization code. This route never calls
// signinCallback itself, including during StrictMode effect replay.
export function AuthCallbackPage() {
  const auth = useAuth()
  if (auth.isLoading) return <main className="auth-page"><LoadingState label="Completing secure sign-in…" /></main>
  if (auth.error || !authConfig || !sessionUsable(auth.user, authConfig)) return <SignInScreen error />
  const state = auth.user?.state as { returnTo?: unknown } | undefined
  return <Navigate to={safeDestination(state?.returnTo)} replace />
}
