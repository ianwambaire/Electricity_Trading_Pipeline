import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../../api/client'
import { validatePasswordChange } from '../../api/profile'

export function PasswordForm({onChanged,onCancel}:{onChanged:()=>void;onCancel:()=>void}) {
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if(busy)return
    const form=event.currentTarget
    const values=new FormData(form)
    const current=String(values.get('current')??''), next=String(values.get('next')??''), confirm=String(values.get('confirm')??'')
    const problem=validatePasswordChange(current,next,confirm)
    if(problem){setError(problem);return}
    setBusy(true);setError('')
    try {await api.changePassword({current_password:current,new_password:next});form.reset();onChanged()} catch(error) {form.reset();setError(error instanceof ApiError?error.message:'Password change could not be completed. Please try again.')} finally {setBusy(false)}
  }
  return <form className="account-form" onSubmit={e=>void submit(e)} aria-label="Change Cognito password" aria-busy={busy}>
    <label>Current password<input name="current" type="password" autoComplete="current-password" maxLength={256} required disabled={busy}/></label>
    <label>New password<input name="next" type="password" autoComplete="new-password" minLength={8} maxLength={256} required disabled={busy}/><span className="account-field-help">At least 8 characters, with uppercase and lowercase letters, a number and a symbol.</span></label>
    <label>Confirm new password<input name="confirm" type="password" autoComplete="new-password" minLength={8} maxLength={256} required disabled={busy}/></label>
    {error&&<p className="account-message is-error" role="alert">{error}</p>}
    <div className="account-form-actions"><button className="account-primary" disabled={busy} type="submit">{busy?'Changing password…':'Change password'}</button><button className="secondary-button" disabled={busy} type="button" onClick={onCancel}>Cancel</button></div>
  </form>
}
