import './dom-environment.ts'
import { afterEach, test, mock } from 'node:test'
import assert from 'node:assert/strict'
import React, { act } from 'react'
import { cleanup, fireEvent, render, renderHook, waitFor, within } from '@testing-library/react'
import { AuthContext, type AuthContextProps } from 'react-oidc-context'
import { AnalyticsPage } from '../src/pages/AnalyticsPage'
import { AnomaliesPage } from '../src/pages/AnomaliesPage'
import { ModelsPage } from '../src/pages/ModelsPage'
import { ProfilePage } from '../src/pages/ProfilePage'
import { ServerAccountContext } from '../src/auth/serverAccountContext'
import { bindApiSession } from '../src/api/accessToken'
import { useHistoricalApi } from '../src/hooks/useHistoricalApi'
import { useApi } from '../src/hooks/useApi'
import { ApiError } from '../src/api/client'
import { MarketChart } from '../src/components/data/MarketChart'
import { generationKeys } from '../src/api/publicData'

const originalFetch=globalThis.fetch
const chartGlobals=['ResizeObserver','requestAnimationFrame','cancelAnimationFrame']as const
const originalChartGlobals=Object.fromEntries(chartGlobals.map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]))
let unbind=()=>undefined
// Only synthetic fixtures are used. Any unmatched request fails locally.
afterEach(()=>{cleanup();unbind();mock.restoreAll();globalThis.fetch=originalFetch;for(const key of chartGlobals){const original=originalChartGlobals[key];if(original)Object.defineProperty(globalThis,key,original);else Reflect.deleteProperty(globalThis,key)}})
const timestamp='2026-09-01T00:00:00Z', digest='a'.repeat(64)
const coverage={source:'Fixture Silver',market_area:'DE-LU',resolution:'hourly',snapshot_id:'fixture',row_count:1001,first_observation:timestamp,latest_observation:'2026-10-12T16:00:00Z',missing_hours_in_span:0,renewable_definition:'Aggregate solar, wind, biomass and hydro; selected-source denominator.'}
const marketRow=(hour:number)=>({timestamp:new Date(Date.parse(timestamp)+hour*3600000).toISOString(),price_eur_mwh:hour===0?-12.5:hour,load_mw:100,generation:Object.fromEntries(generationKeys.map(key=>[key,key==='gas_mw'?null:10])),renewable_generation_mw:40,renewable_share:.5})
const point=(hour:number)=>({timestamp:marketRow(hour).timestamp,price_eur_mwh:hour===0?-12.5:hour,load_mw:100,wind_solar_mw:20,gap_before:false})
const summary={coverage,matched_rows:1001,latest_observation:point(2),mean_load_mw:100,minimum_price:-12.5,maximum_price:1000,average_price:50,sample_price_std:10,recent:[point(2)]}
const exploration={coverage,matched_rows:1001,generation:[{source:'gas_mw',average_mw:null,observations:0}],weather:[{timestamp,temperature_2m:20,wind_speed_10m:8,gap_before:false}],sampling:'Fixture original first/last/extrema, not averages'}
type Call={path:string;query:URLSearchParams;method:string;body:unknown}
function apiFixture(handler:(call:Call)=>Response|Promise<Response>){
 unbind=bindApiSession(()=> 'synthetic-local-session',()=>undefined)
 const calls:Call[]=[]
 globalThis.fetch=async(input,options)=>{
  const u=new URL(String(input),'https://fixture.example.test')
  assert.equal(u.origin,'https://fixture.example.test')
  const call={path:u.pathname,query:u.searchParams,method:options?.method??'GET',body:options?.body?JSON.parse(String(options.body)):null}
  calls.push(call);return handler(call)
 }
 return calls
}
function marketResponse(c:Call):Response{
 if(c.path==='/api/market/coverage')return Response.json(coverage)
 if(c.path==='/api/market/summary')return Response.json(summary)
 if(c.path==='/api/market/exploration')return Response.json(exploration)
 if(c.path==='/api/market/history'){
  const offset=Number(c.query.get('offset')??0), rows=offset===0?Array.from({length:1000},(_,i)=>marketRow(i)):[marketRow(1000)]
  return Response.json({coverage,start:timestamp,end:coverage.latest_observation,matched_rows:1001,row_count:rows.length,limit:1000,offset,next_offset:offset===0?1000:null,observations:rows})
 }
 throw Error('Unexpected fixture endpoint')
}
function panel(container:HTMLElement,title:string){const heading=within(container).getByRole('heading',{name:title});return heading.closest('section')!}
function captureDownload(){
 const blobs:Blob[]=[];const filenames:string[]=[]
 mock.method(URL,'createObjectURL',(blob:Blob)=>{blobs.push(blob);return 'blob:fixture'})
 mock.method(URL,'revokeObjectURL',()=>undefined)
 mock.method(window.HTMLAnchorElement.prototype,'click',function(this:HTMLAnchorElement){filenames.push(this.download)})
 return {blobs,filenames}
}
function clockPolls(){
 const pending=new Map<number,()=>void>();let id=-1
 const set=window.setTimeout.bind(window),clear=window.clearTimeout.bind(window)
 mock.method(window,'setTimeout',(fn:()=>void,delay?:number,...args:unknown[])=>{
  if(delay===60000){pending.set(id,fn);return id--}
  return set(fn,delay,...args)
 })
 mock.method(window,'clearTimeout',(key:number)=>{if(!pending.delete(key))clear(key)})
 return async()=>{const calls=[...pending.values()];pending.clear();await act(async()=>{for(const call of calls)call()})}
}
function chartDimensions(){
 // JSDOM has no layout engine. Supply dimensions only; actual chart components
 // and SVG series remain real, including independent anomaly markers.
 function dimensions(target:Element){
  const text=target.id==='recharts_measurement_span',legend=target.classList.contains('recharts-legend-wrapper')
  const width=text?(target.textContent?.length??0)*7:900,height=text?14:legend?32:320
  return {width,height,x:0,y:0,top:0,left:0,right:width,bottom:height,toJSON(){return {}}}
 }
 mock.method(window.HTMLElement.prototype,'getBoundingClientRect',function(this:HTMLElement){return dimensions(this)})
 class Observer {
  callback:ResizeObserverCallback
  constructor(callback:ResizeObserverCallback){this.callback=callback}
  observe(target:Element){this.callback([{target,contentRect:dimensions(target)} as ResizeObserverEntry],this as unknown as ResizeObserver)}
  unobserve(){}
  disconnect(){}
 }
 Object.defineProperty(globalThis,'ResizeObserver',{configurable:true,writable:true,value:Observer})
 Object.defineProperty(globalThis,'requestAnimationFrame',{configurable:true,writable:true,value:(callback:FrameRequestCallback)=>window.setTimeout(()=>callback(performance.now()),0)})
 Object.defineProperty(globalThis,'cancelAnimationFrame',{configurable:true,writable:true,value:(id:number)=>window.clearTimeout(id)})
}
const role=(value:'Admin'|'Analyst')=>({account:{subject:'fixture-user',role:value,email:null,display_name:'Fixture User'},loading:false,error:null,retry(){}})
const profile={name:'Fixture User',email:'fixture@example.test',email_verified:true,preferred_username:'analyst',role:'Analyst',connected_providers:[],name_editable:true,preferred_username_editable:true,email_editable:false,password_configured:true,mfa_management:'unavailable',mfa_status:'not_enabled'}
function profileView(signinSilent=async()=>undefined){
 const auth={isAuthenticated:true,isLoading:false,user:{profile:{sub:'fixture-user'}},signinSilent,signinRedirect:async()=>undefined,removeUser:async()=>undefined}as unknown as AuthContextProps
 return render(<AuthContext.Provider value={auth}><ServerAccountContext.Provider value={role('Analyst')}><ProfilePage/></ServerAccountContext.Provider></AuthContext.Provider>)
}

test('Market Intelligence applies UTC filters, paginates and exports exactly the displayed historical page',async()=>{
 const calls=apiFixture(marketResponse),download=captureDownload();const view=render(<AnalyticsPage/>)
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Export displayed page (up to 1,000 rows)'})))
 fireEvent.change(view.getByLabelText('From date (UTC)'),{target:{value:'2026-09-01'}})
 fireEvent.change(view.getByLabelText('Through date (UTC)'),{target:{value:'2026-10-12'}})
 fireEvent.click(view.getByRole('button',{name:'Apply date range'}))
 await waitFor(()=>assert.ok(calls.some(c=>c.path==='/api/market/history'&&c.query.get('start')==='2026-09-01T00:00:00Z'&&c.query.get('end')==='2026-10-12T23:59:59.999Z'&&c.query.get('offset')==='0')))
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Next page'})))
 fireEvent.click(view.getByRole('button',{name:'Next page'}))
 await waitFor(()=>assert.ok(view.getByText('Records 1001–1001 of 1001')))
 assert.equal((view.getByRole('button',{name:'Next page'})as HTMLButtonElement).disabled,true)
 fireEvent.click(view.getByRole('button',{name:'Export displayed page (up to 1,000 rows)'}))
 const csv=await download.blobs[0].text();assert.equal(csv.trim().split('\r\n').length,2)
 assert.ok(csv.includes(marketRow(1000).timestamp)&&csv.includes('renewable_share_fraction'))
 assert.equal(download.filenames[0],'powerflow_displayed_market_page.csv')
 fireEvent.click(view.getByRole('button',{name:'Previous page'}))
 await waitFor(()=>assert.ok(view.getByText('Records 1–1000 of 1001')))
 assert.ok(view.getByText(/historical, not live market readings or forecasts/))
})

test('Market filters reject incomplete, inverted and excessive ranges without API changes',async()=>{
 const calls=apiFixture(marketResponse);const view=render(<AnalyticsPage/>)
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Next page'})))
 const before=calls.length
 fireEvent.change(view.getByLabelText('From date (UTC)'),{target:{value:'2026-09-02'}});fireEvent.click(view.getByRole('button',{name:'Apply date range'}))
 assert.match(view.getByRole('alert').textContent??'',/both dates/)
 fireEvent.change(view.getByLabelText('Through date (UTC)'),{target:{value:'2026-09-01'}});fireEvent.click(view.getByRole('button',{name:'Apply date range'}))
 assert.match(view.getByRole('alert').textContent??'',/ordered range/)
 fireEvent.change(view.getByLabelText('Through date (UTC)'),{target:{value:'2028-09-01'}});fireEvent.click(view.getByRole('button',{name:'Apply date range'}))
 assert.equal(calls.length,before)
})

test('Market historical polls preserve expanded table DOM and selected source while updating real rows',async()=>{
 const poll=clockPolls();let held=false;const finish:Array<()=>void>=[]
 async function response(c:Call){
  const result=marketResponse(c)
  if(held&&c.path==='/api/market/history'){
   const body=await result.json();body.observations[0].price_eur_mwh=-99;return Response.json(body)
  }
  return result
 }
 apiFixture(c=>held?new Promise<Response>(resolve=>finish.push(()=>{void response(c).then(resolve)})):response(c))
 const view=render(<AnalyticsPage/>);await waitFor(()=>assert.ok(view.getByLabelText('Source')))
 const details=view.getByText('Exact observations for this page (UTC · EUR/MWh · MW)').closest('details')!
 details.open=true;fireEvent.change(view.getByLabelText('Source'),{target:{value:'solar_mw'}})
 held=true;await poll()
 assert.equal(view.getByText('Exact observations for this page (UTC · EUR/MWh · MW)').closest('details'),details)
 assert.equal(details.open,true);assert.equal((view.getByLabelText('Source')as HTMLSelectElement).value,'solar_mw')
 assert.ok(view.getAllByText(/Refreshing historical data/).length)
 await act(async()=>{for(const done of finish)done()})
 assert.equal(details.open,true);assert.equal((view.getByLabelText('Source')as HTMLSelectElement).value,'solar_mw')
 assert.equal(view.queryByText(/Refreshing historical data/),null)
 assert.ok(within(details).getByRole('cell',{name:'-99'}))
})

test('historical refresh failures clear old evidence; changed queries abort late results; live defaults still clear on poll',async()=>{
 const poll=clockPolls();let reject:(e:Error)=>void=()=>undefined
 let count=0;const load=()=>++count===1?Promise.resolve('historical value'):new Promise<string>((_,r)=>{reject=r})
 const historical=renderHook(()=>useHistoricalApi(load));await waitFor(()=>assert.equal(historical.result.current.data,'historical value'))
 const received=historical.result.current.receivedAt;await poll()
 assert.equal(historical.result.current.data,'historical value');assert.equal(historical.result.current.receivedAt,received)
 await act(async()=>reject(new ApiError('Report failed',503)))
 assert.equal(historical.result.current.data,null);assert.equal(historical.result.current.error?.status,503);historical.unmount()
 let finish:(s:string)=>void=()=>undefined,signal:AbortSignal|undefined
 const old=(s:AbortSignal)=>{signal=s;return new Promise<string>(r=>{finish=r})}, fresh=async()=> 'new query'
 const changed=renderHook(({load})=>useHistoricalApi(load),{initialProps:{load:old}})
 changed.rerender({load:fresh});await waitFor(()=>assert.equal(changed.result.current.data,'new query'));assert.equal(signal?.aborted,true)
 await act(async()=>finish('obsolete'));assert.equal(changed.result.current.data,'new query');changed.unmount()
 let times=0;const liveLoad=()=>++times===1?Promise.resolve('live'):new Promise<string>(()=>undefined)
 const live=renderHook(()=>useApi(liveLoad));await waitFor(()=>assert.equal(live.result.current.data,'live'));await poll()
 assert.equal(live.result.current.data,null);assert.equal(live.result.current.loading,true)
})

test('renewable share tooltip label is aggregate and independent of generation selection',()=>{
 function series(source:'solar_mw'|'gas_mw'){
  const chart=MarketChart({rows:[marketRow(0)],kind:'renewable',source})
  const container=chart.props.children
  const plot=container.props.children
  return plot.props.children.find((child:React.ReactElement<{dataKey:string;name:string}>)=>child&&child.props?.dataKey==='share')
 }
 assert.equal(series('solar_mw').props.name,'Aggregate renewable share (%)')
 assert.equal(series('gas_mw').props.name,'Aggregate renewable share (%)')
})

const event={timestamp:marketRow(1).timestamp,price_eur_mwh:-20,load_mw:90}
function anomalyResponse(c:Call,options:{truncated?:boolean;empty?:boolean;updated?:boolean}={}):Response{
 const rows=options.empty?[]:[{...event,price_eur_mwh:options.updated?-30:event.price_eur_mwh}]
 if(c.path==='/api/anomalies/summary')return Response.json({report_status:rows.length?'available':'empty',count:rows.length,total_report_rows:rows.length,first_event:rows[0]?.timestamp??null,last_event:rows[0]?.timestamp??null,minimum_price:rows[0]?.price_eur_mwh??null,maximum_price:rows[0]?.price_eur_mwh??null,average_load_mw:rows.length?90:null,method:'Isolation Forest',provenance:'Fixture persisted historical report',limitation:'Not a forecast error'})
 if(c.path==='/api/anomalies/events')return Response.json({matched_rows:options.truncated?1001:rows.length,row_count:rows.length,offset:Number(c.query.get('offset')??0),limit:Number(c.query.get('limit')),next_offset:options.truncated?1:null,order:c.query.get('order'),events:rows})
 if(c.path==='/api/market/chart')return Response.json({coverage,matched_rows:3,row_count:2,sampling:'Fixture sampled background excludes the anomaly timestamp',points:[point(0),point(2)]})
 throw Error('Unexpected anomaly fixture endpoint')
}

test('Anomaly Detection renders independent markers, retains methodology and exports historical classifications',async()=>{
 chartDimensions();const poll=clockPolls();let held=false;const done:Array<()=>void>=[]
 const calls=apiFixture(c=>held?new Promise<Response>(resolve=>done.push(()=>resolve(anomalyResponse(c,{updated:true})))):anomalyResponse(c));const download=captureDownload();const view=render(<AnomaliesPage/>)
 await waitFor(()=>assert.ok(view.container.querySelector('.recharts-scatter-symbol')))
 assert.equal(view.container.querySelectorAll('.recharts-scatter-symbol').length,1)
 assert.ok(view.getByText(/1 anomaly markers are included independently of background sampling/))
 fireEvent.mouseOver(view.container.querySelector('.recharts-scatter-symbol')!)
 await waitFor(()=>assert.ok(view.container.querySelector('.chart-tooltip')?.textContent?.includes('-20')))
 const details=view.getByText('Detection method and limitations').closest('details')!;details.open=true
 held=true;await poll();assert.equal(details.open,true);assert.ok(view.getByRole('button',{name:'Export displayed events'}))
 await act(async()=>{for(const finish of done)finish()});assert.equal(details.open,true)
 assert.ok(within(panel(view.container,'Exact anomaly records')).getByRole('cell',{name:'-30'}))
 assert.ok(view.container.querySelector('.chart-tooltip')?.textContent?.includes('-30'))
 assert.ok(!view.container.querySelector('.chart-tooltip')?.textContent?.includes('-20'))
 fireEvent.click(view.getByRole('button',{name:'Export displayed events'}));const csv=await download.blobs[0].text()
 assert.ok(csv.includes('"-30"')&&csv.includes('not a forecast error'));assert.ok(!calls.some(c=>c.path.includes('/forecast/')))
 fireEvent.change(view.getByLabelText('From (UTC)'),{target:{value:'2026-09-01'}});fireEvent.change(view.getByLabelText('Through (UTC)'),{target:{value:'2026-09-02'}})
 held=false;fireEvent.click(view.getByRole('button',{name:'Apply dates'}))
 await waitFor(()=>assert.ok(calls.some(c=>c.path==='/api/anomalies/events'&&c.query.get('start')==='2026-09-01T00:00:00Z')))
})

for(const mode of ['empty','truncated']as const)test(`anomaly ${mode} state does not invent events or show a partial overlay`,async()=>{
 apiFixture(c=>anomalyResponse(c,{empty:mode==='empty',truncated:mode==='truncated'}));const view=render(<AnomaliesPage/>)
 await waitFor(()=>assert.ok(view.getByText(mode==='empty'?'Valid report contains zero anomalies':/no truncated overlay is shown/)))
 assert.equal(view.container.querySelectorAll('.recharts-scatter-symbol').length,0)
})

function modelCatalog(){return {models:(['next24h','one_hour']as const).map(key=>({key,name:key==='next24h'?'Histogram Gradient Boosting (24 direct outputs)':'Ordinary Linear Regression',version:key==='next24h'?'frozen_hgb':null,release_kind:key==='next24h'?'next24h_production':'final_2025_holdout_evaluation',purpose:key==='next24h'?'Operational 24-hour forecasting':'Historical one-hour baseline',horizons_hours:key==='next24h'?Array.from({length:24},(_,i)=>i+1):[1],metadata_status:'available',metadata_provenance:'release_manifest',metadata_sha256:digest,released_at_utc:timestamp,feature_count:31,artifact_status:'integrity_verified',evaluations:[{split:key==='next24h'?'test':'final_holdout',mae:2,rmse:3,r2:.8,observations:24,observation_basis:key==='next24h'?'issue_horizon_pairs':'target_hours',period_start:timestamp,period_end:null,period_basis:key==='next24h'?'issue_time':'target_time',persistence_rmse:4}],notes:['Fixture metadata, not proof of a live forecast']}))}}
function influence(){return {model:'Ordinary Linear Regression',horizon_hours:1,feature_count:31,metadata_sha256:digest,report_sha256:digest,provenance:'Historical one-hour coefficients',limitation:'Not HGB importance',features:Array.from({length:31},(_,i)=>({feature:`feature_${i}`,importance:i+1,signed_coefficient:i%2?i+1:-(i+1)}))}}

test('Model Insights Analyst sees release evidence, no direct ranking and no Admin requests',async()=>{
 const poll=clockPolls();let held=false;let finish:()=>void=()=>undefined
 const calls=apiFixture(c=>{assert.equal(c.path,'/api/models/summary');return held?new Promise<Response>(resolve=>{finish=()=>resolve(Response.json(modelCatalog()))}):Response.json(modelCatalog())})
 const view=render(<ServerAccountContext.Provider value={role('Analyst')}><ModelsPage/></ServerAccountContext.Provider>)
 await waitFor(()=>assert.ok(view.getByText('Histogram Gradient Boosting (24 direct outputs)')))
 assert.ok(within(panel(view.container,'Production 24-hour model')).getByText('issue horizon pairs'));assert.ok(within(panel(view.container,'Historical one-hour baseline')).getByText('target hours'));assert.ok(view.getByText('Ordinary Linear Regression'));assert.ok(view.getByText(/do not support a direct ranking/))
 assert.ok(view.getByText('Admin permission required to view coefficient reports.'))
 assert.ok(!calls.some(c=>c.path.startsWith('/api/admin/')))
 const fingerprint=view.getAllByText('Metadata fingerprint (SHA-256)')[0].closest('details')!;fingerprint.open=true
 held=true;await poll();assert.equal(fingerprint.open,true);await act(async()=>finish());assert.equal(fingerprint.open,true)
})

test('Model Insights Admin can sort/export the actual 31 coefficients and safe denial never falls back',async()=>{
 const calls=apiFixture(c=>c.path==='/api/models/summary'?Response.json(modelCatalog()):c.path==='/api/admin/models/linear-feature-influence'?Response.json(influence()):Promise.reject(Error('Unexpected fixture endpoint')))
 const download=captureDownload();const view=render(<ServerAccountContext.Provider value={role('Admin')}><ModelsPage/></ServerAccountContext.Provider>)
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Export all coefficients'})))
 const table=view.getByRole('table',{name:'All persisted coefficients · one-hour model'})
 assert.equal(within(table).getAllByRole('row').length,32)
 fireEvent.change(view.getByLabelText('Sort coefficients'),{target:{value:'name'}})
 assert.equal(within(table).getAllByRole('row')[1].textContent?.startsWith('feature_0'),true)
 fireEvent.click(view.getByRole('button',{name:'Export all coefficients'}));assert.equal((await download.blobs[0].text()).trim().split('\r\n').length,32)
 assert.ok(view.getByText(/not feature importances for the operational 24-hour HGB model/));assert.ok(calls.some(c=>c.path==='/api/admin/models/linear-feature-influence'))
})

test('Model Insights handles missing metadata and Admin HTTP403 without exposing raw details',async()=>{
 const catalog=modelCatalog();catalog.models[0]={...catalog.models[0],metadata_status:'missing',name:null,version:null,release_kind:null,metadata_provenance:null,metadata_sha256:null,released_at_utc:null,feature_count:null,artifact_status:'missing',evaluations:[],notes:['Release metadata is unavailable']}
 apiFixture(c=>c.path==='/api/models/summary'?Response.json(catalog):new Response('private provider diagnostics',{status:403}))
 const view=render(<ServerAccountContext.Provider value={role('Admin')}><ModelsPage/></ServerAccountContext.Provider>)
 await waitFor(()=>assert.ok(view.getByText('Access denied')))
 assert.ok(view.getByText('Release metadata is unavailable'));assert.ok(!view.container.textContent?.includes('private provider'))
})

test('My Profile validates and saves only edited own attributes, then refreshes displayed identity',async()=>{
 let saved=false;const calls=apiFixture(c=>{
  assert.equal(c.path,'/api/account/profile')
  if(c.method==='PATCH'){saved=true;assert.deepEqual(c.body,{name:'Updated Fixture'});return Response.json({status:'updated'})}
  return Response.json({...profile,name:saved?'Updated Fixture':profile.name})
 })
 const silent=mock.fn(async()=>undefined);const view=profileView(silent)
 await waitFor(()=>assert.ok(view.getByRole('button',{name:'Edit personal information'})))
 fireEvent.click(view.getByRole('button',{name:'Edit personal information'}))
 const form=view.getByRole('form',{name:'Edit personal information'})
 fireEvent.change(within(form).getByLabelText('Display name'),{target:{value:'   '}});fireEvent.submit(form)
 assert.match(view.getByRole('alert').textContent??'',/1 and 128 characters/);assert.ok(!calls.some(c=>c.method==='PATCH'))
 fireEvent.change(within(form).getByLabelText('Display name'),{target:{value:'Updated Fixture'}});fireEvent.submit(form)
 await waitFor(()=>assert.ok(view.getByText('Your personal information has been saved.')))
 await waitFor(()=>assert.ok(view.getByRole('heading',{name:'Updated Fixture'})));assert.equal(silent.mock.callCount(),1)
 fireEvent.click(view.getByRole('button',{name:'Edit personal information'}));fireEvent.click(view.getByRole('button',{name:'Cancel'}))
 assert.equal(calls.filter(c=>c.method==='PATCH').length,1)
})

test('My Profile Google capabilities hide password/name editing; safe save errors cannot expose response bodies',async()=>{
 const calls=apiFixture(c=>c.method==='PATCH'?Response.json({detail:{code:'ATTRIBUTE_NOT_WRITABLE',message:'private provider body'}},{status:403}):Response.json({...profile,connected_providers:['Google'],name_editable:false,password_configured:false,mfa_management:'provider_managed'}))
 const view=profileView();await waitFor(()=>assert.ok(view.getByRole('button',{name:'Edit personal information'})))
 assert.equal(view.queryByRole('button',{name:'Change password'}),null)
 fireEvent.click(view.getByRole('button',{name:'Edit personal information'}));const form=view.getByRole('form',{name:'Edit personal information'})
 assert.equal(within(form).queryByLabelText('Display name'),null)
 fireEvent.change(within(form).getByLabelText(/^Preferred username/),{target:{value:'new_label'}});fireEvent.submit(form)
 await waitFor(()=>assert.match(view.getByRole('alert').textContent??'',/does not permit/))
 assert.deepEqual(calls.find(c=>c.method==='PATCH')?.body,{preferred_username:'new_label'})
 assert.ok(!view.container.textContent?.includes('private provider body'))
})

test('My Profile password validation prevents requests; provider failure clears inputs; retry can succeed',async()=>{
 let changed=0;const calls=apiFixture(c=>{
  if(c.path==='/api/account/profile')return Response.json(profile)
  assert.equal(c.path,'/api/account/password');assert.equal(c.method,'POST');changed++
  return changed===1?Response.json({detail:{code:'INCORRECT_PASSWORD',message:'private submitted secret'}},{status:400}):Response.json({status:'password_changed'})
 })
 const view=profileView();await waitFor(()=>assert.ok(view.getByRole('button',{name:'Change password'})))
 fireEvent.click(view.getByRole('button',{name:'Change password'}));const form=view.getByRole('form',{name:'Change Cognito password'})
 const fill=(confirmation:string)=>{
  fireEvent.change(within(form).getByLabelText('Current password'),{target:{value:'FixtureOld!1'}})
  fireEvent.change(within(form).getByLabelText(/^New password/),{target:{value:'FixtureNew!2'}})
  fireEvent.change(within(form).getByLabelText('Confirm new password'),{target:{value:confirmation}})
 }
 fill('mismatch');fireEvent.submit(form);assert.match(view.getByRole('alert').textContent??'',/do not match/)
 assert.equal(calls.filter(c=>c.path==='/api/account/password').length,0)
 fill('FixtureNew!2');fireEvent.submit(form);await waitFor(()=>assert.match(view.getByRole('alert').textContent??'',/current password was not accepted/))
 assert.equal((within(form).getByLabelText('Current password')as HTMLInputElement).value,'')
 assert.equal((within(form).getByLabelText(/^New password/)as HTMLInputElement).value,'')
 assert.ok(!view.container.textContent?.includes('private submitted secret'))
 fill('FixtureNew!2');fireEvent.submit(form);await waitFor(()=>assert.ok(view.getByText('Your password has been changed.')))
 assert.equal(view.queryByRole('form',{name:'Change Cognito password'}),null)
})

test('a new historical query removes prior-query values while the replacement is pending',async()=>{
 let finish:(value:string)=>void=()=>undefined
 const initial=async()=> 'previous date range'
 const next=()=>new Promise<string>(resolve=>{finish=resolve})
 const view=renderHook(({load})=>useHistoricalApi(load),{initialProps:{load:initial}})
 await waitFor(()=>assert.equal(view.result.current.data,'previous date range'))
 view.rerender({load:next});assert.equal(view.result.current.data,null);assert.equal(view.result.current.loading,true)
 await act(async()=>finish('new date range'));assert.equal(view.result.current.data,'new date range')
})

test('Admin historical report denial on poll removes previously displayed coefficients without disclosure',async()=>{
 const poll=clockPolls();let denied=false
 const calls=apiFixture(c=>c.path==='/api/models/summary'?Response.json(modelCatalog()):c.path==='/api/admin/models/linear-feature-influence'?denied?new Response('private diagnostic',{status:403}):Response.json(influence()):Promise.reject(Error('Unexpected fixture endpoint')))
 const view=render(<ServerAccountContext.Provider value={role('Admin')}><ModelsPage/></ServerAccountContext.Provider>)
 await waitFor(()=>assert.ok(view.getByRole('table',{name:'All persisted coefficients · one-hour model'})))
 denied=true;await poll();await waitFor(()=>assert.ok(view.getByText('Access denied')))
 assert.equal(view.queryByRole('table',{name:'All persisted coefficients · one-hour model'}),null)
 assert.ok(!view.container.textContent?.includes('private diagnostic'))
 assert.ok(calls.every(c=>['/api/models/summary','/api/admin/models/linear-feature-influence'].includes(c.path)))
})

test('Profile pending save blocks duplicate submission and failed input remains editable without raw errors',async()=>{
 let finish:(response:Response)=>void=()=>undefined
 const calls=apiFixture(c=>c.method==='PATCH'?new Promise<Response>(resolve=>{finish=resolve}):Response.json(profile))
 const view=profileView();await waitFor(()=>assert.ok(view.getByRole('button',{name:'Edit personal information'})))
 fireEvent.click(view.getByRole('button',{name:'Edit personal information'}));const form=view.getByRole('form',{name:'Edit personal information'})
 fireEvent.change(within(form).getByLabelText('Display name'),{target:{value:'Edited Name'}})
 fireEvent.submit(form);fireEvent.submit(form)
 assert.equal(calls.filter(c=>c.method==='PATCH').length,1)
 assert.equal((view.getByRole('button',{name:'Saving…'})as HTMLButtonElement).disabled,true)
 await act(async()=>finish(new Response('private database message',{status:503})))
 assert.match(view.getByRole('alert').textContent??'',/could not be saved/)
 assert.equal((within(form).getByLabelText('Display name')as HTMLInputElement).value,'Edited Name')
 assert.equal((view.getByRole('button',{name:'Save changes'})as HTMLButtonElement).disabled,false)
 assert.ok(!view.container.textContent?.includes('private database message'))
})
