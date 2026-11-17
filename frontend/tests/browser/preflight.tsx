// TEST ENTRY ONLY: never included by the production index/build.
// Actual local observations use FastAPI; identity is always a fixture, not OIDC.
import { Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext, type AuthContextProps } from 'react-oidc-context'
import { WorkspaceRoutes } from '../../src/App'
import { ServerAccountContext } from '../../src/auth/serverAccountContext'
import '../../src/index.css'
const params=new URLSearchParams(window.location.search)
const mode=params.get('mode')??'actual'
const fixture=mode!=='actual'
const role=params.get('role')==='Admin'?'Admin':'Analyst'
const routes=new Set(['/','/analytics','/forecasting','/anomalies','/models','/pipeline','/profile'])
const route=params.get('route')??'/'
const network=window.fetch.bind(window)
window.fetch=async(input,init)=>{
 const url=new URL(input instanceof Request?input.url:String(input),window.location.origin)
 if(url.pathname.startsWith('/api/')&&init?.method&&init.method!=='GET')return Response.json({detail:{code:'ACTION_UNAVAILABLE'}},{status:405})
 if(url.pathname==='/api/account/profile')return Response.json({name:'Preflight fixture',email:'fixture@example.test',email_verified:true,preferred_username:'fixture',role,connected_providers:[],name_editable:true,preferred_username_editable:true,email_editable:false,password_configured:false,mfa_management:'unavailable',mfa_status:'not_enabled'})
 if(!fixture||!url.pathname.startsWith('/api/'))return network(input,init)
 const path=url.pathname.slice(4)
 const response=await network(`/api/__fixtures${path}${url.search}`,init)
 if(response.ok&&mode==='stale'&&path==='/forecast/next24'){
  const body=await response.json()
  for(const row of body.forecasts){row.issue_time=new Date(Date.parse(row.issue_time)-4*3600000).toISOString();row.target_time=new Date(Date.parse(row.target_time)-4*3600000).toISOString()}
  return Response.json(body)
 }
 if(response.ok&&['withheld','failed'].includes(mode)&&['/pipeline/status','/operations/summary'].includes(path)){
  const body=await response.json();body.forecast_status='WITHHELD'
  if(path==='/pipeline/status'&&mode==='failed')body.latest_run_status='FAILED'
  if(path==='/operations/summary'){body.health=mode==='failed'?'Degraded':'Warning';body.forecast_reason='Synthetic preflight withholding scenario';body.explanation='Synthetic preflight scenario, not a production incident.'}
  return Response.json(body)
 }
 return response
}
const auth={isAuthenticated:true,isLoading:false,user:{profile:{sub:'preflight-fixture',name:'Preflight fixture'}},removeUser:async()=>undefined,signinRedirect:async()=>undefined} as unknown as AuthContextProps
createRoot(document.getElementById('root')!).render(<><p style={{margin:0,padding:8,background:'#EAF2FF',position:'relative',zIndex:50}}>LOCAL PREFLIGHT ONLY — {fixture?'SYNTHETIC market/forecast/operations; copied model metadata':'ACTUAL local market/model/database snapshot; missing reports stay missing'}. Identity/profile is simulated {role}; no Cognito, passwords or mutations. Mode: {mode}.</p><AuthContext.Provider value={auth}><ServerAccountContext.Provider value={{account:{subject:'preflight-fixture',role,email:null,display_name:null},loading:false,error:null,retry(){}}}><MemoryRouter initialEntries={[routes.has(route)?route:'/']}><Suspense fallback={<p>Loading preflight…</p>}><WorkspaceRoutes/></Suspense></MemoryRouter></ServerAccountContext.Provider></AuthContext.Provider></>)
