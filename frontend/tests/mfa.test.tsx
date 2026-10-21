import { dom } from './dom-environment.ts'
import { afterEach, test, mock } from 'node:test'
import assert from 'node:assert/strict'
import React, { act } from 'react'
import { render, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { MfaSettings } from '../src/components/account/MfaSettings.tsx'
import { api, ApiError } from '../src/api/client.ts'
import { parseMfaSetup, parseMfaAction, validMfaCode } from '../src/api/mfa.ts'
import { parseProfile, type AccountProfile } from '../src/api/profile.ts'

const profile:AccountProfile={name:'Test Analyst',email:'test@example.test',email_verified:true,preferred_username:'analyst',role:'Analyst',connected_providers:[],name_editable:true,preferred_username_editable:true,email_editable:false,password_configured:true,mfa_management:'available',mfa_status:'not_enabled'}
const setup={secret:'JBSWY3DPEHPK3PXP',setup_ticket:'a'.repeat(43),expires_in:300}
afterEach(()=>{cleanup();mock.restoreAll();window.localStorage.clear();window.sessionStorage.clear();Object.defineProperty(document,'visibilityState',{value:'visible',configurable:true})})
function mount(p=profile){const refresh=mock.fn(),reauth=mock.fn();return {...render(<MfaSettings profile={p} onRefresh={refresh} onReauthenticate={reauth}/>),refresh,reauth}}
async function begin(view:ReturnType<typeof mount>){fireEvent.click(view.getByRole('button',{name:'Set up authenticator'}));fireEvent.click(view.getByRole('button',{name:'Continue setup'}));await waitFor(()=>assert.ok(view.getByText(setup.secret)))}

test('MFA contracts reject malformed responses and retain only necessary fields',()=>{
 assert.deepEqual(parseMfaSetup({...setup,private:'never-display'}),setup)
 for(const value of [{...setup,secret:'bad key'},{...setup,expires_in:301},{...setup,setup_ticket:'bad'}])assert.throws(()=>parseMfaSetup(value))
 assert.equal(parseMfaAction({status:'mfa_enabled'}).status,'mfa_enabled');assert.throws(()=>parseMfaAction({status:'enabled'}))
 assert.equal(validMfaCode('123456'),true);assert.equal(validMfaCode('１２３４５６'),false)
 assert.equal(parseProfile(profile).mfa_management,'available')
 for(const change of [{connected_providers:['Google'],name_editable:false},{password_configured:null},{email_verified:false},{mfa_status:'unknown'}])assert.throws(()=>parseProfile({...profile,...change}))
})

test('native enrollment uses authenticated client, enables after code submission and clears key',async()=>{
 const start=mock.method(api,'startMfa',async()=>setup)
 const verify=mock.method(api,'verifyMfa',async()=>({status:'mfa_enabled' as const}))
 const view=mount();await begin(view)
 assert.equal(start.mock.callCount(),1)
 const input=view.getByRole('textbox',{name:'Authenticator code'}) as HTMLInputElement
 assert.equal(document.activeElement,input)
 fireEvent.change(input,{target:{value:'123456'}});fireEvent.submit(view.getByRole('form',{name:'Verify authenticator'}))
 await waitFor(()=>assert.equal(view.refresh.mock.callCount(),1))
 assert.equal(verify.mock.calls[0].arguments[0],setup.setup_ticket);assert.equal(verify.mock.calls[0].arguments[1],'123456')
 assert.equal(view.queryByText(setup.secret),null)
 assert.equal(window.localStorage.length,0);assert.equal(window.sessionStorage.length,0)
 assert.ok(view.getByRole('status').textContent?.includes('Authenticator enabled'))
})

test('provider-managed, unknown and release-gated accounts have no enrollment control',()=>{
 for(const p of [{...profile,connected_providers:['Google'],name_editable:false,mfa_management:'provider_managed'}, {...profile,mfa_management:'unavailable',mfa_status:'unknown'}, {...profile,mfa_management:'unavailable'}] as AccountProfile[]){
  const view=mount(p);assert.equal(view.queryByRole('button',{name:'Set up authenticator'}),null);view.unmount()
 }
 const view=mount({...profile,mfa_status:'enabled'});assert.ok(view.getByText('Authenticator enabled for native sign-in.'))
 assert.equal(view.queryByRole('button',{name:/remove|disable/i}),null)
})

test('cancel clears setup immediately and calls metadata-only cancellation',async()=>{
 mock.method(api,'startMfa',async()=>setup);const cancel=mock.method(api,'cancelMfa',async()=>({status:'setup_cancelled' as const}))
 const view=mount();await begin(view);fireEvent.click(view.getByRole('button',{name:'Cancel setup'}))
 assert.equal(view.queryByText(setup.secret),null)
 await waitFor(()=>assert.equal(cancel.mock.callCount(),1))
 assert.equal(cancel.mock.calls[0].arguments[0],setup.setup_ticket)
})

test('wrong codes allow correction without falsely enabling and duplicate submit is blocked',async()=>{
 mock.method(api,'startMfa',async()=>setup)
 let reject:(reason:unknown)=>void=()=>undefined
 const verify=mock.method(api,'verifyMfa',()=>new Promise((_,no)=>{reject=no}))
 const view=mount();await begin(view)
 const form=view.getByRole('form',{name:'Verify authenticator'}),input=view.getByRole('textbox',{name:'Authenticator code'}) as HTMLInputElement
 fireEvent.change(input,{target:{value:'12345'}});fireEvent.submit(form)
 assert.equal(verify.mock.callCount(),0);assert.match(view.getByRole('alert').textContent??'',/six-digit/)
 fireEvent.change(input,{target:{value:'123456'}});fireEvent.submit(form);fireEvent.submit(form)
 assert.equal(verify.mock.callCount(),1);assert.equal(input.value,'')
 await act(async()=>reject(new ApiError('The code was not accepted.',400,'MFA_INVALID_CODE')))
 assert.equal(view.refresh.mock.callCount(),0);assert.ok(view.getByText(setup.secret))
 assert.match(view.getByRole('alert').textContent??'',/not accepted/)
})

test('fresh authentication failures expose a reauthentication action and no key',async()=>{
 mock.method(api,'startMfa',async()=>{throw new ApiError('Confirm your identity.',403,'FRESH_SIGN_IN_REQUIRED')})
 const view=mount();fireEvent.click(view.getByRole('button',{name:'Set up authenticator'}));fireEvent.click(view.getByRole('button',{name:'Continue setup'}))
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Confirm identity'})))
 fireEvent.click(view.getByRole('button',{name:'Confirm identity'}));assert.equal(view.reauth.mock.callCount(),1)
 assert.equal(view.queryByText(setup.secret),null)
})

test('an abandoned pending setup offers refresh instead of another association attempt',async()=>{
 const start=mock.method(api,'startMfa',async()=>{throw new ApiError('A setup is already in progress.',409,'MFA_SETUP_IN_PROGRESS')})
 const view=mount();fireEvent.click(view.getByRole('button',{name:'Set up authenticator'}));fireEvent.click(view.getByRole('button',{name:'Continue setup'}))
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Refresh security settings'})))
 assert.equal(view.queryByRole('button',{name:'Continue setup'}),null)
 assert.equal(start.mock.callCount(),1)
 assert.equal(view.queryByText(setup.secret),null)
})

test('network uncertainty clears setup and requires status refresh, never optimistic enrollment',async()=>{
 mock.method(api,'startMfa',async()=>setup)
 mock.method(api,'verifyMfa',async()=>{throw new ApiError('Could not reach the API.')})
 const view=mount();await begin(view)
 fireEvent.change(view.getByRole('textbox',{name:'Authenticator code'}),{target:{value:'123456'}})
 fireEvent.submit(view.getByRole('form',{name:'Verify authenticator'}))
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Refresh security settings'})))
 assert.equal(view.queryByText(setup.secret),null);assert.equal(view.refresh.mock.callCount(),0)
 fireEvent.click(view.getByRole('button',{name:'Refresh security settings'}));assert.equal(view.refresh.mock.callCount(),1)
})

test('hiding or unmounting removes setup material; late responses cannot redisplay it',async()=>{
 mock.method(api,'startMfa',async()=>setup)
 const view=mount();await begin(view)
 Object.defineProperty(document,'visibilityState',{value:'hidden',configurable:true})
 fireEvent(document,new dom.window.Event('visibilitychange'))
 assert.equal(view.queryByText(setup.secret),null)
 Object.defineProperty(document,'visibilityState',{value:'visible',configurable:true})
 view.unmount();assert.ok(!document.body.textContent?.includes(setup.secret))
 let resolve:(v:typeof setup)=>void=()=>undefined
 mock.restoreAll();mock.method(api,'startMfa',()=>new Promise(ok=>{resolve=ok}))
 const later=mount();fireEvent.click(later.getByRole('button',{name:'Set up authenticator'}));fireEvent.click(later.getByRole('button',{name:'Continue setup'}));later.unmount()
 await act(async()=>resolve(setup));assert.ok(!document.body.textContent?.includes(setup.secret))
})

test('returning from an authenticator preserves verification without keeping the key or extending expiry',async()=>{
 const start=mock.method(api,'startMfa',async()=>setup)
 const verify=mock.method(api,'verifyMfa',async()=>({status:'mfa_enabled' as const}))
 const original=window.setTimeout.bind(window);let timers=0
 mock.method(window,'setTimeout',(callback:TimerHandler,delay?:number,...args:unknown[])=>{
  if(delay===300000)timers++
  return original(callback,delay,...args)
 })
 const view=mount();await begin(view)
 fireEvent.change(view.getByRole('textbox',{name:'Authenticator code'}),{target:{value:'123456'}})
 Object.defineProperty(document,'visibilityState',{value:'hidden',configurable:true})
 fireEvent(document,new dom.window.Event('visibilitychange'))
 assert.equal(view.queryByText(setup.secret),null)
 assert.equal((view.getByRole('textbox',{name:'Authenticator code'}) as HTMLInputElement).value,'')
 Object.defineProperty(document,'visibilityState',{value:'visible',configurable:true})
 fireEvent(document,new dom.window.Event('visibilitychange'))
 assert.equal(view.queryByText(setup.secret),null)
 assert.equal(view.queryByRole('button',{name:'Continue setup'}),null)
 assert.equal(start.mock.callCount(),1);assert.equal(timers,1)
 fireEvent.change(view.getByRole('textbox',{name:'Authenticator code'}),{target:{value:'654321'}})
 fireEvent.submit(view.getByRole('form',{name:'Verify authenticator'}))
 await waitFor(()=>assert.equal(view.refresh.mock.callCount(),1))
 assert.equal(verify.mock.calls[0].arguments[0],setup.setup_ticket)
 assert.equal(window.localStorage.length,0);assert.equal(window.sessionStorage.length,0)
})

test('setup expires locally and sensitive output is removed',async()=>{
 mock.method(api,'startMfa',async()=>setup)
 const original=window.setTimeout.bind(window)
 let expire:()=>void=()=>{throw Error('Expiry timer not installed')}
 mock.method(window,'setTimeout',(callback:TimerHandler,delay?:number,...args:unknown[])=>{
  if(delay===300000&&typeof callback==='function'){expire=callback as ()=>void;return 0}
  return original(callback,delay,...args)
 })
 const view=mount();await begin(view)
 await act(async()=>expire())
 assert.equal(view.queryByText(setup.secret),null)
 assert.match(view.getByRole('status').textContent??'',/expired/)
})
