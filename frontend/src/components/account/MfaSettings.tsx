import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api/client'
import { validMfaCode, type MfaSetup } from '../../api/mfa'
import type { AccountProfile } from '../../api/profile'

export function MfaSettings({profile,onRefresh,onReauthenticate}:{profile:AccountProfile;onRefresh:()=>void;onReauthenticate:()=>void}) {
  const [confirm,setConfirm]=useState(false)
  const [setup,setSetup]=useState<MfaSetup|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [fresh,setFresh]=useState(false)
  const [notice,setNotice]=useState('')
  const [uncertain,setUncertain]=useState(false)
  const input=useRef<HTMLInputElement>(null)
  const action=useRef<HTMLButtonElement>(null)
  const active=useRef<AbortController|null>(null)
  const ticket=useRef<string|null>(null)
  const mounted=useRef(false)
  const setupTicket=setup?.setup_ticket
  const setupLifetime=setup?.expires_in
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;active.current?.abort();ticket.current=null}},[])
  useEffect(()=>{
    if(!setupTicket||!setupLifetime)return
    input.current?.focus()
    function clear(){
      // Erase the key/code when hidden, but retain the memory-only ticket and
      // original expiry so returning from an authenticator can finish setup.
      if(document.visibilityState==='hidden'){
        if(input.current)input.current.value=''
        setSetup(current=>current?.secret?{...current,secret:''}:current)
        setNotice('Setup key hidden. Use the code from the authenticator you just added to finish setup.')
      }
    }
    const timer=window.setTimeout(()=>{
      active.current?.abort();ticket.current=null;setSetup(null);setBusy(false)
      setUncertain(true);setNotice('Setup expired. Refresh your security settings before continuing.')
    },setupLifetime*1000)
    document.addEventListener('visibilitychange',clear)
    clear()
    return()=>{window.clearTimeout(timer);document.removeEventListener('visibilitychange',clear)}
  },[setupTicket,setupLifetime])

  function failure(error:unknown){
    setFresh(error instanceof ApiError&&error.code==='FRESH_SIGN_IN_REQUIRED')
    setError(error instanceof ApiError?error.message:'Account services could not complete this action. Please try again.')
    if(error instanceof ApiError&&error.code==='MFA_SETUP_IN_PROGRESS'&&!ticket.current){
      setConfirm(false);setUncertain(true)
    }
    if(!(error instanceof ApiError)||error.status===null||error.status===503||error.code==='MFA_SETUP_EXPIRED'){
      ticket.current=null;setSetup(null);setUncertain(true)
    }
  }
  async function start(){
    if(busy)return
    setBusy(true);setError('');setFresh(false);setNotice('')
    const controller=new AbortController();active.current=controller
    try{
      const result=await api.startMfa(controller.signal)
      if(!mounted.current||controller.signal.aborted)return
      ticket.current=result.setup_ticket;setSetup(result);setConfirm(false)
    }catch(error){if(mounted.current&&!controller.signal.aborted)failure(error)}
    finally{if(mounted.current&&!controller.signal.aborted)setBusy(false)}
  }
  async function verify(event:FormEvent<HTMLFormElement>){
    event.preventDefault();if(busy||!setup)return
    const form=event.currentTarget, code=String(new FormData(form).get('code')??'')
    if(!validMfaCode(code)){setError('Enter the six-digit code from your authenticator.');input.current?.focus();return}
    setBusy(true);setError('');form.reset()
    const controller=new AbortController();active.current=controller
    try{
      await api.verifyMfa(setup.setup_ticket,code,controller.signal)
      if(!mounted.current||controller.signal.aborted)return
      ticket.current=null;setSetup(null);setNotice('Authenticator enabled. Your next native sign-in will ask for a code.');onRefresh()
    }catch(error){if(mounted.current&&!controller.signal.aborted){failure(error);input.current?.focus()}}
    finally{if(mounted.current&&!controller.signal.aborted)setBusy(false)}
  }
  async function cancel(){
    if(busy)return
    const current=ticket.current
    // Erase display immediately, even if cancel cannot reach the server.
    ticket.current=null;setSetup(null);setConfirm(false);setError('');setFresh(false)
    action.current?.focus()
    if(!current)return
    setBusy(true)
    const controller=new AbortController();active.current=controller
    try{await api.cancelMfa(current,controller.signal)}catch{if(mounted.current)setNotice('Setup closed. Wait five minutes before starting again if it cannot be resumed.')}
    finally{if(mounted.current)setBusy(false)}
  }

  const provider=profile.mfa_management==='provider_managed'||profile.connected_providers.includes('Google')
  const enabled=profile.mfa_status==='enabled'
  return <div className="account-mfa" aria-label="Two-step verification">
    <div className="account-security-row"><div><h3>Two-step verification</h3><p>{provider?'Managed by your sign-in provider. Use its security settings to manage two-step verification.':enabled?'Authenticator enabled for native sign-in.':profile.mfa_status==='unknown'?'Authenticator status could not be confirmed.':profile.mfa_status==='other_factor'?'Another authentication factor is configured.':'An authenticator adds a six-digit code to your native sign-in.'}</p></div>
      {!provider&&!enabled&&profile.mfa_management==='available'&&!confirm&&!setup&&!uncertain&&<button ref={action} className="secondary-button" disabled={busy} onClick={()=>{setConfirm(true);setError('')}}>Set up authenticator</button>}
    </div>
    {!provider&&profile.mfa_management==='unavailable'&&!enabled&&<p className="account-note">Authenticator setup is not available in this workspace yet.</p>}
    {!provider&&profile.mfa_status==='unknown'&&<button className="secondary-button" onClick={onRefresh}>Refresh security settings</button>}
    {!provider&&enabled&&<p className="account-note">Keep access to your authenticator. Removal and lost-device recovery are not available in PowerFlow; resetting a password does not remove an authenticator.</p>}
    {notice&&<p role="status" className="account-note">{notice}</p>}
    {error&&<p role="alert" className="account-message is-error">{error}</p>}
    {fresh&&<button className="secondary-button" disabled={busy} onClick={onReauthenticate}>Confirm identity</button>}
    {uncertain&&<button className="secondary-button" onClick={()=>{setUncertain(false);setConfirm(false);setError('');onRefresh()}}>Refresh security settings</button>}
    {confirm&&!setup&&<div className="account-confirmation" aria-label="Confirm authenticator setup">
      <p>Use an authenticator app you control. PowerFlow does not provide backup codes or self-service lost-device recovery. Keep your verified recovery email accessible.</p>
      <button className="account-primary" disabled={busy} onClick={()=>void start()}>{busy?'Starting…':'Continue setup'}</button><button className="secondary-button" disabled={busy} onClick={()=>void cancel()}>Cancel</button>
    </div>}
    {setup&&<form className="account-form" aria-label="Verify authenticator" aria-busy={busy} onSubmit={e=>void verify(e)}>
      <p>In your authenticator, add an account using a setup key. Choose time-based, six-digit codes and label it PowerFlow.</p>
      {setup.secret&&<><label>Setup key<output className="account-setup-key">{setup.secret}</output></label>
      <p className="account-field-help">Keep this key private. It is shown only during setup and cleared when you leave or hide this page, cancel, or after five minutes.</p></>}
      <label>Authenticator code<input ref={input} name="code" inputMode="numeric" autoComplete="off" pattern="[0-9]{6}" minLength={6} maxLength={6} required disabled={busy} aria-describedby="mfa-code-help"/></label>
      <span className="account-field-help" id="mfa-code-help">Enter the current six-digit code. Codes are never saved.</span>
      <div className="account-form-actions"><button className="account-primary" disabled={busy} type="submit">{busy?'Verifying…':'Verify and enable'}</button><button className="secondary-button" disabled={busy} type="button" onClick={()=>void cancel()}>Cancel setup</button></div>
    </form>}
  </div>
}
