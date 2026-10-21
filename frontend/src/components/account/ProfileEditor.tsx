import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import type { AccountProfile } from '../../api/profile'
import { profileUpdateError, validateProfileField } from '../../api/profile'

export function ProfileEditor({ profile, onSaved, onCancel }: { profile: AccountProfile; onSaved: () => void; onCancel: () => void }) {
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if(busy)return
    const values=new FormData(event.currentTarget)
    const changes:{name?:string;preferred_username?:string}={}
    if(profile.name_editable && String(values.get('name')??'').trim()!==(profile.name??''))changes.name=String(values.get('name')??'').trim()
    if(String(values.get('preferred_username')??'').trim()!==(profile.preferred_username??''))changes.preferred_username=String(values.get('preferred_username')??'').trim()
    if(!Object.keys(changes).length){onCancel();return}
    for(const value of Object.values(changes)){const problem=validateProfileField(value);if(problem){setError(problem);return}}
    setBusy(true);setError('')
    try {await api.updateProfile(changes);onSaved()} catch(error) {setError(profileUpdateError(error))} finally {setBusy(false)}
  }
  return <form className="account-form" onSubmit={event=>void submit(event)} aria-label="Edit personal information" aria-busy={busy}>
    {profile.name_editable?<label>Display name<input name="name" defaultValue={profile.name??''} maxLength={128} autoComplete="name" disabled={busy}/></label>:<p className="account-note">Your display name is managed by Google.</p>}
    <label>Preferred username<input name="preferred_username" defaultValue={profile.preferred_username??''} maxLength={128} autoComplete="nickname" disabled={busy}/><span className="account-field-help">A profile label. Continue to use your email address to sign in.</span></label>
    {error&&<p className="account-message is-error" role="alert">{error}</p>}
    <div className="account-form-actions"><button className="account-primary" disabled={busy} type="submit">{busy?'Saving…':'Save changes'}</button><button className="secondary-button" disabled={busy} type="button" onClick={onCancel}>Cancel</button></div>
  </form>
}
