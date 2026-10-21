import { useState } from 'react'
import { useAuth } from 'react-oidc-context'
import { authConfig, userManager } from './runtime'
import { logoutSession } from './logout'

export function SignOutButton() {
  const auth = useAuth()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  async function signOut() {
    if (busy || !authConfig) return
    setBusy(true)
    try {
      // Clear this app's local session before visiting Cognito. No ID-token hint
      // or other token is put in the logout URL. Google sessions are separate.
      await logoutSession(authConfig, {
        stopRenew: () => userManager?.stopSilentRenew(),
        removeUser: auth.removeUser,
        clearTransactions: async () => {
          const store = userManager?.settings.stateStore
          if (store) await Promise.all((await store.getAllKeys()).map(key => store.remove(key)))
        },
        redirect: url => window.location.assign(url),
      })
    } catch { setFailed(true); setBusy(false) }
  }
  return <><button className="secondary-button" disabled={busy} onClick={() => void signOut()}>{busy ? 'Signing out…' : 'Sign out'}</button>{failed && <span role="alert">Sign-out could not finish. Retry, or close this tab to clear its session.</span>}</>
}
