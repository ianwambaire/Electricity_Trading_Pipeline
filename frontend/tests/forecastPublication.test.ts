import test from 'node:test'
import assert from 'node:assert/strict'
import {parseNext24} from '../src/api/contracts.ts'
import {classifyForecast} from '../src/api/forecastState.ts'
import {publicationState} from '../src/api/publicationState.ts'
import {ApiError, request} from '../src/api/client.ts'

const issue=Date.parse('2026-01-05T08:00:00Z')
function fixture(){return {row_count:24,forecasts:Array.from({length:24},(_,i)=>({issue_time:new Date(issue).toISOString(),target_time:new Date(issue+(i+1)*3600000).toISOString(),horizon_hours:i+1,predicted_price_eur_mwh:100+i,model_release:'next24h-hgb-2026-09-21-v1'})),publication:{status:'VALID',issue_time:new Date(issue).toISOString(),expires_at:new Date(issue+3*3600000).toISOString(),completed_at:new Date(issue+1.5*3600000).toISOString()}}}

test('fresh publication uses its own evidence instead of frozen historical pipeline status',()=>{
 const report=parseNext24(fixture());const state=classifyForecast(report,{latest_run_status:'SUCCESS',latest_run_timestamp:'2025-01-01T00:00:00Z',forecast_status:'WITHHELD'},issue+2*3600000)
 assert.equal(state.label,'Valid published forecast');assert.match(state.description,/22 of 24/)
})
test('expiry masks retained values and reports WITHHELD without waiting for another API poll',()=>{
 const state={data:parseNext24(fixture()),loading:false,error:null,receivedAt:'2026-01-05T10:00:00Z'}
 assert.equal(publicationState(state,issue+3*3600000).data,state.data)
 const expired=publicationState(state,issue+3*3600000+1)
 assert.equal(expired.data,null);assert.equal(expired.error?.code,'FORECAST_WITHHELD')
 assert.equal(classifyForecast(null,null,issue+4*3600000,expired.error?.code).label,'WITHHELD')
})
test('invalid publication metadata or forecast rows never enter the UI',()=>{
 for(const mutate of [(v:ReturnType<typeof fixture>)=>{v.publication.expires_at=new Date(issue+4*3600000).toISOString()},(v:ReturnType<typeof fixture>)=>{v.forecasts.pop()},(v:ReturnType<typeof fixture>)=>{v.forecasts[0].predicted_price_eur_mwh=Infinity},(v:ReturnType<typeof fixture>)=>{v.forecasts[0].target_time=v.forecasts[1].target_time}]){
  const value=fixture();mutate(value);assert.throws(()=>parseNext24(value))
 }
})
test('safe API WITHHELD code is recognized without exposing response contents',async()=>{
 const original=globalThis.fetch
 try{
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:'FORECAST_WITHHELD',secret:'do not display'}}),{status:503})
  await assert.rejects(request('/forecast/next24',parseNext24),(e:unknown)=>e instanceof ApiError && e.code==='FORECAST_WITHHELD' && !e.message.includes('do not display'))
  globalThis.fetch=async()=>new Response(JSON.stringify({forecasts:[]}),{status:200})
  await assert.rejects(request('/forecast/next24',parseNext24),(e:unknown)=>e instanceof ApiError && e.code==='FORECAST_WITHHELD')
 }finally{globalThis.fetch=original}
})
