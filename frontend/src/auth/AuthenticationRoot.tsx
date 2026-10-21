import { useEffect, useLayoutEffect, type ReactNode } from 'react'
import { AuthProvider, useAuth } from 'react-oidc-context'
import { bindApiSession } from '../api/accessToken'
import { sessionUsable } from './identity'
import { authConfig, userManager, finishSignin, cleanCallbackUrl } from './runtime'
import { markSessionEnded } from './sessionStatus'
import { Brand } from '../components/layout/Brand'

function SessionLifecycle({ children }: { children: ReactNode }) {
  const { user, removeUser, events, error } = useAuth()
  useLayoutEffect(() => {
    let rejected = false
    return bindApiSession(
      () => !rejected && authConfig && sessionUsable(user, authConfig) ? user!.access_token : null,
      () => { rejected = true; markSessionEnded(); void removeUser().catch(() => undefined) },
    )
  }, [user, removeUser])
  useEffect(() => {
    const expire = () => { markSessionEnded(); void removeUser().catch(() => undefined) }
    events.addAccessTokenExpired(expire)
    events.addSilentRenewError(expire)
    return () => {
      events.removeAccessTokenExpired(expire)
      events.removeSilentRenewError(expire)
    }
  }, [events, removeUser])
  useEffect(() => { if (error) cleanCallbackUrl() }, [error])
  return children
}

export function AuthenticationRoot({ children }: { children: ReactNode }) {
  if (!authConfig || !userManager) return <main className="auth-page"><section className="auth-card"><Brand /><h1>Authentication setup required</h1><p role="alert">PowerFlow cannot initialize secure sign-in. Check the public frontend environment settings and enable browser session storage, then reload.</p><p>No dashboard data is loaded until sign-in is available. See the frontend authentication guide.</p><button className="secondary-button" onClick={() => window.location.reload()}>Reload</button></section></main>
  return <AuthProvider userManager={userManager} onSigninCallback={finishSignin} skipSigninCallback={window.location.pathname !== '/auth/callback'}><SessionLifecycle>{children}</SessionLifecycle></AuthProvider>
}
