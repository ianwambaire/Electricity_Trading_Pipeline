import { useServerAccount } from '../auth/serverAccountContext'
import { useState } from 'react'
import { useAuth } from 'react-oidc-context'
import { identityFromProfile } from '../auth/identity'
import { SignOutButton } from '../auth/SignOutButton'
import { PageHeading } from '../components/ui/PageHeading'
import { Panel } from '../components/ui/Panel'
import { Facts } from '../components/data/ApiPanel'

export function ProfilePage() {
  const auth = useAuth()
  const server = useServerAccount()
  const identity = identityFromProfile(auth.user?.profile ?? {})
  const [failed, setFailed] = useState(false)
  const [opening, setOpening] = useState(false)
  async function openManagedLogin() {
    if (opening) return
    setOpening(true)
    setFailed(false)
    try {
      await auth.signinRedirect({ prompt: 'login', nonce: crypto.randomUUID(), state: { returnTo: '/profile' } })
    } catch { setFailed(true); setOpening(false) }
  }
  return <><PageHeading category="Account" title="My Profile" description="Read-only identity information supplied by Amazon Cognito." />
    <div className="profile-grid"><Panel title="Authenticated account"><Facts items={[
      ['Display name', identity.name ?? 'Not supplied'], ['Email address', identity.email ?? 'Not supplied'],
      ['Email verification', identity.emailVerified === null ? 'Not supplied' : identity.emailVerified ? 'Verified by identity provider' : 'Not verified'],
      ['Application role · server verified', server.account?.role ?? (server.loading ? 'Verifying…' : 'Unavailable')], ['Identity provider', identity.provider], ['Federated identity link', identity.federatedProvider ?? 'Not supplied'], ['Account reference · abbreviated', identity.accountReference],
    ]} /><p className="data-note">A linked identity does not establish which sign-in method was used for this session. Role is confirmed by FastAPI from the verified access token. Restricted reports also enforce Admin permissions on the server.</p>{server.error && <p className="notice notice-warning" role="alert">{server.error.message} <button className="text-link" onClick={server.retry}>Retry account verification</button></p>}<SignOutButton /></Panel>
    <Panel title="Account management"><div className="profile-info"><h3>Managed by your identity provider</h3><p>For accounts with a Cognito password, open managed sign-in and choose password recovery if it is offered. Google account recovery is managed by Google.</p><button className="secondary-button" disabled={opening || !!auth.activeNavigator} onClick={() => void openManagedLogin()}>{opening ? 'Opening managed sign-in…' : 'Open Cognito sign-in for recovery'}</button>{failed && <p role="alert">Managed sign-in could not be opened. Try again.</p>}<p>Registration and recovery depend on existing Cognito policies. Direct profile editing and password changes are not provided by PowerFlow.</p></div></Panel></div>
  </>
}
