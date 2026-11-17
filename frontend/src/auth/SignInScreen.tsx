import { authErrorMessage } from './authErrorMessage'
import { useState } from 'react'
import { useAuth } from 'react-oidc-context'
import { sessionHasEnded } from './sessionStatus'
import { Brand } from '../components/layout/Brand'
import { authConfig } from './runtime'
import { safeDestination } from './config'

export function SignInScreen({ returnTo = '/', error = false, expired = false }: { returnTo?: string; error?: boolean; expired?: boolean }) {
  const auth = useAuth()
  const [starting, setStarting] = useState(false)
  const [failed, setFailed] = useState(false)
  const correctOrigin = !!authConfig && window.location.origin === new URL(authConfig.redirectUri).origin
  async function signIn() {
    if (starting || !correctOrigin) return
    setStarting(true)
    setFailed(false)
    try {
      await auth.signinRedirect({ state: { returnTo: safeDestination(returnTo) }, nonce: crypto.randomUUID() })
    } catch { setFailed(true); setStarting(false) }
  }
  return <main className="auth-page"><section className="auth-card" aria-labelledby="signin-title"><Brand subtitle={false} /><h1 id="signin-title">Sign in</h1><p>Sign in to access your dashboard.</p>
    {(error || failed) && <p className="notice notice-error" role="alert">{authErrorMessage(auth.error)}</p>}
    {(expired || sessionHasEnded()) && !error && <p className="notice notice-warning" role="status">Your session has ended. Sign in again to continue.</p>}
    {!correctOrigin ? <p className="notice notice-warning">Use the configured application address for secure callback handling. <a href={authConfig?.logoutUri}>Open PowerFlow at the configured address</a>.</p> : <button className="auth-primary" disabled={starting || !!auth.activeNavigator} onClick={() => void signIn()}>{starting || auth.activeNavigator ? 'Opening secure sign-in…' : 'Continue to sign in'}</button>}
  </section></main>
}
