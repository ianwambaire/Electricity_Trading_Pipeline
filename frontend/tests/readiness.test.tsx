import './dom-environment.ts'
import { afterEach, test, mock } from 'node:test'
import assert from 'node:assert/strict'
import React, { Suspense, act } from 'react'
import { render, renderHook, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext, type AuthContextProps } from 'react-oidc-context'
import App, { WorkspaceRoutes } from '../src/App.tsx'
import { ServerAccountContext } from '../src/auth/serverAccountContext.ts'
import { useApi } from '../src/hooks/useApi.ts'
import { ApiError, request } from '../src/api/client.ts'
import { bindApiSession } from '../src/api/accessToken.ts'
import { ErrorBoundary } from '../src/components/ui/ErrorBoundary.tsx'
import { DownloadStatus } from '../src/components/ui/DownloadStatus.tsx'
import { downloadCsv } from '../src/api/csv.ts'
import { DateRangeFilter } from '../src/components/ui/DateRangeFilter.tsx'

window.scrollTo=()=>undefined
window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}} as unknown as MediaQueryList)
// JSDOM has no native top-layer/focus trapping. Test modal semantics, not browser implementation.
Object.defineProperty(window.HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(){this.open=true}})
Object.defineProperty(window.HTMLDialogElement.prototype,'close',{configurable:true,value:function(){this.open=false}})
const originalFetch=globalThis.fetch
const auth={isAuthenticated:true,isLoading:false,activeNavigator:undefined,user:{profile:{sub:'fixture-subject',name:'Test Analyst'},access_token:'test-only'},removeUser:async()=>undefined,signinRedirect:async()=>undefined} as unknown as AuthContextProps
const roles=(role:'Analyst'|'Admin')=>({account:{subject:'fixture-subject',role,email:null,display_name:null},loading:false,error:null,retry(){}})
afterEach(()=>{cleanup();mock.restoreAll();globalThis.fetch=originalFetch})

for(const [path,title] of [['/','Executive Overview'],['/analytics','Market Intelligence'],['/forecasting','Forecast Intelligence'],['/anomalies','Anomaly Detection'],['/models','Model Insights'],['/pipeline','Pipeline Operations'],['/profile','My Profile']]) {
 test(`real workspace route ${path} renders heading and sanitized API failure in isolation`,async()=>{
  globalThis.fetch=async()=>new Response('private diagnostic',{status:503})
  const view=render(<AuthContext.Provider value={auth}><ServerAccountContext.Provider value={roles('Analyst')}><MemoryRouter initialEntries={[path]}><Suspense fallback={<p>Loading test route</p>}><WorkspaceRoutes/></Suspense></MemoryRouter></ServerAccountContext.Provider></AuthContext.Provider>)
  await waitFor(()=>assert.ok(view.getByRole('heading',{level:1,name:title})))
  await waitFor(()=>assert.ok(view.getAllByRole('alert').length))
  assert.ok(!view.container.textContent?.includes('private diagnostic'))
  assert.ok(view.getAllByRole('link',{name:title}).some(link=>link.getAttribute('aria-current')==='page'))
  assert.equal(document.title,`${title} · PowerFlow`)
  assert.equal(document.activeElement?.id,'main-content')
 })
}

test('Analyst does not request Admin reports; Admin requests protected endpoints and displays safe denial',async()=>{
 const calls:string[]=[]
 globalThis.fetch=async(input)=>{calls.push(String(input));return new Response('',{status:403})}
 const view=render(<AuthContext.Provider value={auth}><ServerAccountContext.Provider value={roles('Analyst')}><MemoryRouter initialEntries={['/pipeline']}><Suspense><WorkspaceRoutes/></Suspense></MemoryRouter></ServerAccountContext.Provider></AuthContext.Provider>)
 await waitFor(()=>assert.ok(view.getByRole('heading',{name:'Pipeline Operations'})))
 await waitFor(()=>assert.ok(view.getAllByRole('alert').length))
 assert.ok(!calls.some(x=>x.startsWith('/api/admin/')))
 view.unmount();calls.length=0
 const admin=render(<AuthContext.Provider value={auth}><ServerAccountContext.Provider value={roles('Admin')}><MemoryRouter initialEntries={['/pipeline']}><Suspense><WorkspaceRoutes/></Suspense></MemoryRouter></ServerAccountContext.Provider></AuthContext.Provider>)
 await waitFor(()=>assert.ok(calls.includes('/api/admin/operations')&&calls.includes('/api/admin/monitoring/forecast-vintages')))
 await waitFor(()=>assert.ok(admin.getAllByText('Access denied').length))
 assert.ok(!calls.includes('/api/monitoring/forecast-vintages'))
})

test('mobile navigation opens labelled dialog and closes on route selection; desktop collapse remains accessible',async()=>{
 globalThis.fetch=async()=>new Response('',{status:404})
 const view=render(<AuthContext.Provider value={auth}><MemoryRouter><Suspense><WorkspaceRoutes/></Suspense></MemoryRouter></AuthContext.Provider>)
 await waitFor(()=>assert.ok(view.getByRole('heading',{name:'Executive Overview'})))
 fireEvent.click(view.getByRole('button',{name:'Collapse sidebar'}));assert.ok(view.getByRole('button',{name:'Expand sidebar'}))
 fireEvent.click(view.getByRole('button',{name:'Open navigation'}))
 assert.ok(view.getByRole('dialog',{name:'Workspace navigation'}))
 const links=view.getAllByRole('link',{name:'Market Intelligence'})
 fireEvent.click(links.at(-1)!)
 await waitFor(()=>assert.ok(view.getByRole('heading',{name:'Market Intelligence'})))
 assert.equal(view.queryByRole('dialog'),null)
})

test('late successful authenticated response is discarded after identity replacement',async()=>{
 let resolve:(r:Response)=>void=()=>undefined
 const stop=bindApiSession(()=> 'old-test-token',()=>undefined)
 globalThis.fetch=()=>new Promise(r=>{resolve=r})
 const pending=request('/auth/me',v=>v)
 const fresh=bindApiSession(()=> 'new-test-token',()=>undefined)
 resolve(Response.json({display_name:'previous account'}))
 await assert.rejects(pending,/session changed/)
 fresh();stop()
})

test('hook aborts old loads and never paints a late response from a replaced query',async()=>{
 let resolve:(v:string)=>void=()=>undefined,signal:AbortSignal|undefined
 const old=(s:AbortSignal)=>{signal=s;return new Promise<string>(r=>{resolve=r})}
 const fresh=async()=> 'current query'
 const view=renderHook(({load})=>useApi(load,0),{initialProps:{load:old as (s:AbortSignal)=>Promise<string>}})
 view.rerender({load:fresh});assert.equal(signal?.aborted,true)
 await waitFor(()=>assert.equal(view.result.current.data,'current query'))
 await act(async()=>resolve('obsolete result'))
 assert.equal(view.result.current.data,'current query')
})

test('hook polls only after completion and retries errors without retaining previous data',async()=>{
 let finish:(v:string)=>void=()=>undefined
 const load=mock.fn(()=>new Promise<string>(r=>{finish=r}))
 const view=renderHook(()=>useApi(load,15))
 await act(async()=>{await new Promise(r=>setTimeout(r,40))})
 assert.equal(load.mock.callCount(),1)
 await act(async()=>finish('first'))
 await waitFor(()=>assert.equal(load.mock.callCount(),2))
 assert.equal(view.result.current.data,null)
 view.unmount()
 const failing=mock.fn(async()=>{throw new ApiError('Temporary report error',503)})
 const retry=renderHook(()=>useApi(failing,0))
 await waitFor(()=>assert.equal(retry.result.current.error?.status,503))
 act(()=>retry.result.current.retry());await waitFor(()=>assert.equal(failing.mock.callCount(),2))
})

test('CSV errors are announced, and object URLs/links are cleaned without claiming saved files',()=>{
 const revoke=mock.method(URL,'revokeObjectURL',()=>undefined)
 mock.method(URL,'createObjectURL',()=>{throw new Error('private storage details')})
 const view=render(<DownloadStatus/>)
 act(()=>assert.equal(downloadCsv('test.csv',[['a']]),false))
 assert.match(view.getByRole('alert').textContent??'',/could not be started/)
 assert.ok(!view.container.textContent?.includes('private'))
 fireEvent.click(view.getByRole('button',{name:'Dismiss download message'}));assert.equal(view.queryByRole('alert'),null)
 assert.equal(document.querySelector('a[download]'),null);assert.equal(revoke.mock.callCount(),0)
})

test('accessible date filters validate input and preserve explicit UTC semantics',()=>{
 const apply=mock.fn();const view=render(<DateRangeFilter onApply={apply}/>)
 fireEvent.change(view.getByLabelText('From (UTC)'),{target:{value:'2026-10-02'}})
 fireEvent.click(view.getByRole('button',{name:'Apply dates'}));assert.ok(view.getByRole('alert'));assert.equal(apply.mock.callCount(),0)
 fireEvent.change(view.getByLabelText('Through (UTC)'),{target:{value:'2026-10-03'}})
 fireEvent.click(view.getByRole('button',{name:'Apply dates'}));assert.match(apply.mock.calls[0].arguments[0],/00%3A00%3A00Z/)
})

test('render errors show generic recovery without exception details',()=>{
 const original=console.error;console.error=()=>undefined
 function Broken():React.ReactNode{throw new Error('private diagnostic')}
 try {const view=render(<ErrorBoundary><Broken/></ErrorBoundary>);assert.ok(view.getByRole('button',{name:'Reload PowerFlow'}));assert.ok(!view.container.textContent?.includes('private diagnostic'));assert.equal(document.activeElement,view.getByRole('heading',{name:'Unable to display this page'}))}finally{console.error=original}
})

test('network timeout and partial API responses fail safely without exposing diagnostics',async()=>{
 globalThis.fetch=async()=>{throw new DOMException('private proxy address','TimeoutError')}
 await assert.rejects(request('/health',v=>v),error=>error instanceof ApiError && /timed out/.test(error.message) && !error.message.includes('private'))
 globalThis.fetch=async()=>Response.json({status:'ok'})
 const {parseHealth}=await import('../src/api/contracts.ts')
 await assert.rejects(request('/health',parseHealth),/unexpected or invalid/)
})

test('a session change during response-body reading cannot reveal previous account details',async()=>{
 let finish:(v:unknown)=>void=()=>undefined
 const stop=bindApiSession(()=> 'first-test',()=>undefined)
 const response=Response.json({})
 response.json=()=>new Promise(r=>{finish=r})
 globalThis.fetch=async()=>response
 const pending=request('/account/profile',v=>v)
 await new Promise(r=>setTimeout(r,0))
 const fresh=bindApiSession(()=> 'second-test',()=>undefined)
 finish({name:'previous account'})
 await assert.rejects(pending,/session changed/)
 fresh();stop()
})

test('successful CSV initiation revokes the object URL and removes its temporary anchor',()=>{
 mock.method(URL,'createObjectURL',()=> 'blob:test-only')
 const revoke=mock.method(URL,'revokeObjectURL',()=>undefined)
 const click=mock.method(window.HTMLAnchorElement.prototype,'click',()=>undefined)
 let release:(()=>void)|undefined
 mock.method(window,'setTimeout',((fn:()=>void)=>{release=fn;return 1}) as typeof window.setTimeout)
 assert.equal(downloadCsv('fixture.csv',[['price'],[-12.5]]),true)
 assert.equal(click.mock.callCount(),1);assert.equal(document.querySelector('a[download]'),null)
 release?.();assert.equal(revoke.mock.calls[0].arguments[0],'blob:test-only')
})

test('same-origin API requests reject redirects instead of following an unexpected login/proxy target',async()=>{
 globalThis.fetch=async(input,options)=>{assert.equal(input,'/api/health');assert.equal(options?.redirect,'error');assert.equal(options?.credentials,'omit');return Response.json({ok:true})}
 assert.deepEqual(await request('/health',v=>v),{ok:true})
})

test('production callback configuration is HTTPS and incomplete public settings fail closed',async()=>{
 const {readAuthConfig,safeDestination}=await import('../src/auth/config.ts')
 const env={VITE_COGNITO_AUTHORITY:'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool',VITE_COGNITO_DOMAIN:'https://test.auth.us-east-1.amazoncognito.com',VITE_COGNITO_CLIENT_ID:'fixtureclient',VITE_COGNITO_REDIRECT_URI:'https://powerflowenergy.dev/auth/callback',VITE_COGNITO_POST_LOGOUT_REDIRECT_URI:'https://powerflowenergy.dev/'}
 assert.ok(readAuthConfig(env))
 assert.equal(readAuthConfig({...env,VITE_COGNITO_CLIENT_ID:''}),null)
 assert.equal(readAuthConfig({...env,VITE_COGNITO_REDIRECT_URI:'http://powerflowenergy.dev/auth/callback'}),null)
 assert.equal(readAuthConfig({...env,VITE_COGNITO_POST_LOGOUT_REDIRECT_URI:'https://other.example/'}),null)
 assert.equal(safeDestination('https://other.example/'),'/')
})


test('production route gate loads no workspace data when signed out, expired or authentication failed',async()=>{
 const fetcher=mock.fn(async()=>Response.json({}));globalThis.fetch=fetcher
 for(const state of [
  {...auth,isAuthenticated:false,user:null},
  {...auth,user:{...auth.user,expired:true}},
  {...auth,isAuthenticated:false,user:null,error:new Error('private provider diagnostic')},
 ]) {
  const view=render(<AuthContext.Provider value={state as AuthContextProps}><MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter></AuthContext.Provider>)
  await waitFor(()=>assert.ok(view.getByRole('heading',{name:'Sign in'})))
  assert.ok(!view.container.textContent?.includes('private provider diagnostic'));view.unmount()
 }
 assert.equal(fetcher.mock.callCount(),0)
 const view=render(<AuthContext.Provider value={{...auth,isLoading:true}}><MemoryRouter><App/></MemoryRouter></AuthContext.Provider>)
 assert.match(view.getByRole('status').textContent??'',/Checking your secure session/)
})
