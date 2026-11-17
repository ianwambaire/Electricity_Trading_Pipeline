// Development-only visual fixture, excluded from Vite's production index entry.
// No real OIDC login, tokens, accounts, market values or API operations.
import { Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { AuthContext, type AuthContextProps } from 'react-oidc-context'
import { WorkspaceRoutes } from '../../src/App'
import { ServerAccountContext } from '../../src/auth/serverAccountContext'
import '../../src/index.css'
const allowed=new Set(['/','/analytics','/forecasting','/anomalies','/models','/pipeline','/profile'])
const route=new URLSearchParams(window.location.search).get('route')??'/'
// Deliberately show sanitized missing-report states, never fabricated market values.
window.fetch=async()=>new Response('',{status:503})
const auth={isAuthenticated:true,isLoading:false,user:{profile:{sub:'visual-fixture',name:'UI fixture'}},removeUser:async()=>undefined,signinRedirect:async()=>undefined} as unknown as AuthContextProps
createRoot(document.getElementById('root')!).render(<><p style={{margin:0,padding:8,background:'#EAF2FF',position:'relative',zIndex:50}}>Isolated UI test — Analyst fixture; API unavailable; no real account or market data.</p><AuthContext.Provider value={auth}><ServerAccountContext.Provider value={{account:{subject:'visual-fixture',role:'Analyst',email:null,display_name:null},loading:false,error:null,retry(){}}}><MemoryRouter initialEntries={[allowed.has(route)?route:'/']}><Suspense fallback={<p>Loading fixture…</p>}><WorkspaceRoutes/></Suspense></MemoryRouter></ServerAccountContext.Provider></AuthContext.Provider></>)
