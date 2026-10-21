import { useState } from 'react'
import { useAuth } from 'react-oidc-context'
import { CircleUserRound } from 'lucide-react'
import { useServerAccount } from '../auth/serverAccountContext'
import { profileDetails } from '../auth/profilePresentation'
import { accountSigninRequest } from '../auth/oidcSettings'
import { SignOutButton } from '../auth/SignOutButton'
import { signOutCurrentSession } from '../auth/signOutCurrentSession'
import { api, ApiError } from '../api/client'
import { useApi } from '../hooks/useApi'
import { PageHeading } from '../components/ui/PageHeading'
import { AccountSection, AccountField } from '../components/account/AccountSection'
import { ProfileEditor } from '../components/account/ProfileEditor'
import { PasswordForm } from '../components/account/PasswordForm'

export function ProfilePage() {
  const auth=useAuth()
  const server=useServerAccount()
  const state=useApi(api.accountProfile,0)
  const account=state.data
  const fallback=profileDetails(auth.user?.profile??{})
  const profile=account?profileDetails({name:account.name,email:account.email,email_verified:account.email_verified,preferred_username:account.preferred_username,identities:account.connected_providers.map(providerName=>({providerName}))}):fallback
  const [editing,setEditing]=useState(false)
  const [changingPassword,setChangingPassword]=useState(false)
  const [opening,setOpening]=useState(false)
  const [confirmingSignOut,setConfirmingSignOut]=useState(false)
  const [revoking,setRevoking]=useState(false)
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')
  const [reauthRequired,setReauthRequired]=useState(false)

  async function openManagedLogin() {
    if(opening||auth.activeNavigator)return
    setOpening(true);setError('')
    try {await auth.signinRedirect(accountSigninRequest())} catch {setError('Sign-in options could not be opened. Please try again.');setOpening(false)}
  }
  function saved() {
    setEditing(false);setNotice('Your personal information has been saved.');state.retry();server.retry()
    // Refresh the library-managed identity so navigation reflects changed attributes.
    void auth.signinSilent().catch(()=>setNotice('Changes saved. Sign in again to refresh your account details.'))
  }
  async function revokeSessions() {
    if(revoking)return
    setRevoking(true);setError('')
    try {await api.signOutAll();await signOutCurrentSession(auth.removeUser)} catch(error) {
      if(error instanceof ApiError&&error.code==='FRESH_SIGN_IN_REQUIRED')setReauthRequired(true)
      setError(error instanceof ApiError?error.message:'Session sign-out could not finish. Please try again.')
      setRevoking(false)
    }
  }
  const verification=profile.emailVerified===true?'Verified':profile.emailVerified===false?'Not verified':'Verification unavailable'
  return <>
    <PageHeading category="Account" title="My Profile" description="Your account details and sign-in options."/>
    <div className="account-settings">
      <section className="account-overview" aria-label="Profile overview">
        <div className="account-avatar" aria-hidden="true">{profile.initials??<CircleUserRound size={28}/>}</div>
        <div className="account-overview-identity"><h2>{profile.name??'Your account'}</h2><p>{profile.email??'Email not provided'}</p></div>
        <span className="account-role">{account?.role??server.account?.role??(server.loading?'Verifying access…':'Access unavailable')}</span>
      </section>
      {notice&&<p className="account-notice" role="status">{notice}</p>}
      {error&&<p className="account-message is-error" role="alert">{error}</p>}
      {state.loading&&<p className="account-note" role="status">Loading your current account settings…</p>}
      {state.error&&<div className="account-connection" role="alert"><h2>{state.error.code==='ACCOUNT_RECONNECT_REQUIRED'?'Enable account settings':'Account settings unavailable'}</h2><p>{state.error.message}</p>{state.error.code==='ACCOUNT_RECONNECT_REQUIRED'?<button className="account-primary" disabled={opening||!!auth.activeNavigator} onClick={()=>void openManagedLogin()}>{opening?'Opening sign-in…':'Sign in again'}</button>:<button className="secondary-button" onClick={state.retry}>Try again</button>}</div>}
      <div className="account-settings-columns">
        <AccountSection title="Personal information" description="Keep your account details up to date.">
          {editing&&account?<ProfileEditor profile={account} onSaved={saved} onCancel={()=>setEditing(false)}/>:<><dl className="account-fields"><AccountField label="Display name" value={profile.name??'Not provided'} status={profile.googleConnected?<span className="account-verification">Managed by Google</span>:undefined}/><AccountField label="Email address" value={profile.email??'Not provided'} status={<span className={`account-verification ${profile.emailVerified===true?'is-verified':''}`}>{verification}</span>}/><AccountField label="Preferred username" value={profile.preferredUsername??'Not set'}/></dl>{account&&<div className="account-form-actions"><button className="secondary-button" onClick={()=>{setEditing(true);setNotice('')}}>Edit personal information</button></div>}<p className="account-note">Sign in with your email address. Email changes are not currently available in PowerFlow.</p></>}
        </AccountSection>
        <AccountSection title="Sign-in and security">
          {account&&<><div className="account-security-row"><div><h3>Password</h3><p>{account.password_configured===true?'Manage your PowerFlow password.':account.password_configured===false&&profile.googleConnected?'Your Google password is managed by Google.':'Password availability could not be confirmed. Use sign-in options for recovery.'}</p></div>{account.password_configured===true&&!changingPassword&&<button className="secondary-button" onClick={()=>{setChangingPassword(true);setNotice('')}}>Change password</button>}</div>{changingPassword&&account.password_configured===true&&<PasswordForm onChanged={()=>{setChangingPassword(false);setNotice('Your password has been changed.')}} onCancel={()=>setChangingPassword(false)}/>}</>}
          <div className="account-security-row"><div><h3>Sign-in and recovery</h3><p>Open secure sign-in for the recovery options available to your account.</p></div><button className="secondary-button" disabled={opening||!!auth.activeNavigator} onClick={()=>void openManagedLogin()}>{opening?'Opening sign-in…':'Open sign-in options'}</button></div>
          <div className="account-security-row"><div><h3>Two-step verification</h3><p>Not enabled for PowerFlow. Google account protection is managed separately.</p></div></div>
          <div className="account-security-row"><div><h3>This browser</h3><p>Sign out of your current PowerFlow session.</p></div><div className="account-signout"><SignOutButton/></div></div>
          {account&&<div className="account-security-row"><div><h3>Other devices</h3><p>Sign out across all PowerFlow sessions, including this browser.</p></div>{!confirmingSignOut?<button className="secondary-button" onClick={()=>setConfirmingSignOut(true)}>Sign out across devices</button>:<div className="account-confirmation" aria-label="Confirm sign-out across devices"><p>All PowerFlow sessions will need to sign in again. Your Google session is separate.</p>{reauthRequired?<button className="account-primary" disabled={opening} onClick={()=>void openManagedLogin()}>Confirm identity</button>:<button className="account-primary" disabled={revoking} onClick={()=>void revokeSessions()}>{revoking?'Signing out…':'Confirm sign-out'}</button>}<button className="secondary-button" disabled={revoking} onClick={()=>{setConfirmingSignOut(false);setReauthRequired(false)}}>Cancel</button></div>}</div>}
        </AccountSection>
      </div>
      {profile.googleConnected&&<AccountSection title="Connected accounts"><div className="account-connected"><div className="account-provider-label"><strong>Google</strong><span>Connected</span></div><p>Your Google name and security are managed with Google.</p><a className="text-link" href="https://myaccount.google.com/security" target="_blank" rel="noopener noreferrer">Manage Google account<span className="sr-only"> (opens in a new tab)</span></a></div></AccountSection>}
    </div>
  </>
}
