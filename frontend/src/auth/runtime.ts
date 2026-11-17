import { oidcSettings } from './oidcSettings'
import { Log, UserManager } from 'oidc-client-ts'
import { clearSessionEnded } from './sessionStatus'
import { readAuthConfig } from './config.ts'
import { sessionUsable } from './identity.ts'

// Library logs can include protocol payloads; never enable them in the application.
Log.setLevel(Log.NONE)
export const authConfig = readAuthConfig(import.meta.env)

function createManager(): UserManager | null {
  if (!authConfig) return null
  try {
    // A singleton survives StrictMode's effect replay. OIDC state and the PKCE
    // verifier belong to this tab; no tokens are placed in localStorage.
    const store = window.sessionStorage
    const probe = 'powerflow.storage-check'
    store.setItem(probe, '1')
    store.removeItem(probe)
    return new UserManager(oidcSettings(authConfig, store))
  } catch { return null }
}
export const userManager = createManager()

export function cleanCallbackUrl(): void {
  if (window.location.pathname === '/auth/callback') window.history.replaceState(null, '', '/auth/callback')
}

export async function finishSignin(user: import('oidc-client-ts').User | undefined): Promise<void> {
  cleanCallbackUrl()
  if (!authConfig || !sessionUsable(user, authConfig)) {
    await userManager?.removeUser()
    throw new Error('Sign-in could not be verified. Please start again.')
  }
  clearSessionEnded()
}
