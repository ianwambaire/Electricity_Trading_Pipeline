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
  return <main className="auth-page"><section className="auth-card" aria-labelledby="signin-title"><Brand /><p className="auth-eyebrow">POWERFLOW WORKSPACE</p><h1 id="signin-title">Sign in to PowerFlow</h1><p>Access electricity market analysis, forecasts, anomaly detection and pipeline monitoring.</p>
    {(error || failed) && <p className="notice notice-error" role="alert">Sign-in could not be completed or the session could not be renewed. Start again using the button below.</p>}
    {(expired || sessionHasEnded()) && !error && <p className="notice notice-warning" role="status">Your session has ended. Sign in again to continue.</p>}
    {!correctOrigin ? <p className="notice notice-warning">Use the configured application address for secure callback handling. <a href={authConfig?.logoutUri}>Open PowerFlow at the configured address</a>.</p> : <button className="auth-primary" disabled={starting || !!auth.activeNavigator} onClick={() => void signIn()}>{starting || auth.activeNavigator ? 'Opening secure sign-in…' : 'Sign In'}</button>}
    <p className="auth-help">Choose Google or email on Amazon Cognito’s managed sign-in page. Registration and password recovery are available there only if enabled for your account.</p><p className="auth-footnote">Passwords are handled by your identity provider. PowerFlow does not collect or store them.</p>
  </section></main>
}
