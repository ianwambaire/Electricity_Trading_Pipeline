import './dom-environment.ts'
import {afterEach,test,mock} from 'node:test'
import assert from 'node:assert/strict'
import React,{act} from 'react'
import {render,cleanup,waitFor,fireEvent} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {parseNext24} from '../src/api/contracts'
import {classifyForecast} from '../src/api/forecastState'
import {publicationState} from '../src/api/publicationState'
import {operationalForecastState} from '../src/api/operationalForecastState'
import {parseOperations} from '../src/api/restoration'
import {ForecastSummary} from '../src/components/data/ForecastSummary'
import {OperationsNotice} from '../src/components/data/OperationalSummary'
import {MarketOverview} from '../src/pages/MarketOverview'
import {ForecastingPage} from '../src/pages/ForecastingPage'
import {PipelinePage} from '../src/pages/PipelinePage'
import {ServerAccountContext} from '../src/auth/serverAccountContext'

const hour=3600000,issue=Date.parse('2026-11-07T14:00:00Z'),iso=(n:number)=>new Date(n).toISOString()
const original=globalThis.fetch
afterEach(()=>{cleanup();mock.restoreAll();globalThis.fetch=original})
function fixture(){return {row_count:24,forecasts:Array.from({length:24},(_,i)=>({issue_time:iso(issue),target_time:iso(issue+(i+1)*hour),horizon_hours:i+1,predicted_price_eur_mwh:100+i,model_release:'next24h-hgb-2026-09-21-v1'})),publication:{status:'VALID',issue_time:iso(issue),completed_at:iso(issue+2.8*hour),expires_at:iso(issue+24*hour),availability_policy:'ISSUE_HORIZON_V1',refresh_due_at:iso(issue+3*hour)}}}
function operations(){return {assessed_at:iso(issue+2.9*hour),health:'Historical snapshot',explanation:'Recorded snapshot is not current pipeline health.',health_rules:'Historical only',latest_run_status:'SUCCESS',latest_run_time:iso(issue-24*hour),latest_success_time:iso(issue-24*hour),latest_complete_market_hour:iso(issue-24*hour),forecast_status:'VALID',forecast_reason:'Valid published forecast within remaining horizon.',forecast_reason_provenance:'Controlled active publication',forecast_expires_at:iso(issue+24*hour),forecast_refresh_due_at:iso(issue+3*hour),s3_sync_status:null,recent_checks_passed:null,recent_checks_failed:null,recent_checks_warning:null,continuity_warning_sources:null,quality_history:[],sources:[],products:[{product:'24-hour predictions',status:'available'}],incident_evidence:'Unavailable',timing_evidence:'Unavailable',completeness_note:'Historical snapshot only'}}

test('new policy retains a timely admitted forecast after refresh is due, without calling it newly refreshed',()=>{
 const r=parseNext24(fixture());const state=classifyForecast(r,null,issue+4*hour)
 assert.equal(state.label,'Published forecast · refresh delayed');assert.match(state.description,/20 of 24/);assert.match(state.description,/not newly refreshed/)
 assert.equal(publicationState({data:r,loading:false,error:null,receivedAt:null},issue+23*hour).data,r)
 assert.equal(publicationState({data:r,loading:false,error:null,receivedAt:null},issue+24*hour).data,null)
})
test('new policy rejects unknown versions, stale inference, shifted expiry and partial metadata',()=>{
 for(const mutate of [
  (v:ReturnType<typeof fixture>)=>{v.publication.availability_policy='UNKNOWN'},
  (v:ReturnType<typeof fixture>)=>{v.publication.completed_at=iso(issue+4*hour)},
  (v:ReturnType<typeof fixture>)=>{v.publication.expires_at=iso(issue+25*hour)},
  (v:ReturnType<typeof fixture>)=>{v.publication.refresh_due_at=iso(issue+4*hour)},
  (v:ReturnType<typeof fixture>)=>{delete (v.publication as Partial<typeof v.publication>).availability_policy}
 ]){const v=fixture();mutate(v);assert.throws(()=>parseNext24(v))}
})
test('Operations status and product availability expire independently of successful historical execution',()=>{
 const data=parseOperations(operations());const delayed=operationalForecastState(data,issue+4*hour)!
 assert.equal(delayed.forecast_status,'VALID');assert.match(delayed.forecast_reason!,/Refresh delayed/)
 const expired=operationalForecastState(data,issue+24*hour)!
 assert.equal(expired.forecast_status,'EXPIRED');assert.equal(expired.products[0].status,'missing');assert.equal(expired.latest_run_status,'SUCCESS')
 assert.equal(data.forecast_status,'VALID')
})
test('returning to a suspended tab withholds expired forecast and Operations reason without an API poll',async()=>{
 let now=issue+23*hour;mock.method(Date,'now',()=>now)
 const pipeline={data:null,loading:false,error:null,receivedAt:null}
 const view=render(<><ForecastSummary report={parseNext24(fixture())} pipeline={pipeline}/><OperationsNotice data={parseOperations(operations())}/></>)
 assert.ok(view.getByText('Published forecast · refresh delayed'))
 now=issue+24*hour
 await act(async()=>{fireEvent(window,new window.Event('focus'))})
 assert.ok(view.getByText('WITHHELD'));assert.equal(view.queryByText('Average · EUR/MWh'),null)
 assert.ok(view.getByText(/The forecast horizon has expired/));assert.equal(view.queryByText(/Refresh delayed since/),null)
})

for(const [name,Page] of [['Overview',MarketOverview],['Forecast Intelligence',ForecastingPage],['Pipeline Operations',PipelinePage]] as const){
 for(const state of ['valid','delayed','expired','missing'] as const){
  test(`${name}: ${state} agrees with genuine-shape API contract, never substitutes historical data`,async()=>{
   mock.method(Date,'now',()=>issue+(state==='delayed'?4:state==='expired'?24:2.9)*hour)
   const calls:string[]=[]
   globalThis.fetch=async input=>{
    const path=String(input);calls.push(path)
    if(path==='/api/forecast/next24')return state==='missing'||state==='expired'?Response.json({detail:{code:'FORECAST_WITHHELD'}},{status:503}):Response.json(fixture())
    if(path==='/api/operations/summary')return Response.json({...operations(),...(state==='expired'?{forecast_status:'EXPIRED',forecast_reason:'The forecast horizon has expired.',forecast_expires_at:null,forecast_refresh_due_at:null}:state==='missing'?{forecast_status:'MISSING_PUBLICATION',forecast_reason:'No active publication is available.',forecast_expires_at:null,forecast_refresh_due_at:null}:{})})
    if(path==='/api/pipeline/status')return Response.json({latest_run_status:'SUCCESS',latest_run_timestamp:iso(issue-24*hour),forecast_status:'GENERATED'})
    return new Response('',{status:404})
   }
   const account={account:{subject:'fixture',role:'Analyst' as const,email:null,display_name:null},loading:false,error:null,retry(){}}
   const view=render(<ServerAccountContext.Provider value={account}><MemoryRouter><Page/></MemoryRouter></ServerAccountContext.Provider>)
   if(name==='Pipeline Operations'){
    await waitFor(()=>assert.ok(view.getByText(state==='expired'?'EXPIRED':state==='missing'?'MISSING_PUBLICATION':'VALID')))
   }else{
    await waitFor(()=>assert.ok(view.getByText(state==='expired'||state==='missing'?'WITHHELD':state==='delayed'?'Published forecast · refresh delayed':'Valid published forecast')))
    if(state==='expired'||state==='missing')assert.equal(view.queryByText('Average · EUR/MWh'),null)
   }
   if(state==='delayed')await waitFor(()=>assert.ok(view.getAllByText(/refresh delayed|Refresh delayed/i).length))
   if(name==='Forecast Intelligence'&&(state==='valid'||state==='delayed')){
    await waitFor(()=>assert.ok(view.getByText('Target availability')))
    const table=view.container.querySelector('.forecast-table table')!
    assert.equal(table.querySelectorAll('tbody tr').length,24)
    assert.ok(table.textContent?.includes('Elapsed · reference only'));assert.ok(table.textContent?.includes('Future target'))
    const predictions=[...table.querySelectorAll('tbody tr')].map(row=>row.children[1].textContent)
    assert.deepEqual(predictions,fixture().forecasts.map(r=>String(r.predicted_price_eur_mwh)))
   }
   assert.equal(calls.some(p=>p.startsWith('/api/admin/')),false)
   assert.equal(view.container.textContent?.includes('PRIVATE'),false)
  })
 }
}
