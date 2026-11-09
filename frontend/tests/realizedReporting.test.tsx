import './dom-environment.ts'
import {test,afterEach} from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {render,cleanup,waitFor} from '@testing-library/react'
import {parseRealized} from '../src/api/parity'
import {RealizedForecastEvaluation} from '../src/components/data/ForecastEvidence'
const original=globalThis.fetch
const digest='a'.repeat(64)
function report(){return {assessed_at:'2026-11-08T10:00:00Z',generated_at:'2026-11-08T09:45:00Z',fresh_until:'2026-11-08T11:15:00Z',observed_through:'2026-11-08T08:00:00Z',report_status:'VALID',data_status:'INSUFFICIENT_DATA',coverage:{history_rows:24,verified_rows:24,unverified_rows:0,eligible_rows:22,realized_pairs:0},source_sha256:{history_sha256:digest,prices_sha256:digest,receipts_sha256:digest},report_sha256:digest,provenance:'Receipt-verified synthetic test fixture',releases:[]}}
afterEach(()=>{cleanup();globalThis.fetch=original})
test('verified metadata preserves coverage and rejects malformed freshness/provenance',()=>{
 assert.equal(parseRealized(report()).report_status,'VALID')
 for(const change of [{report_status:'UNKNOWN'},{fresh_until:'2026-11-09T11:15:00Z'},{generated_at:'2026-11-09T09:45:00Z'},{source_sha256:{}},{coverage:{...report().coverage,realized_pairs:30}},{observed_through:'2026-11-08T09:30:00Z'}])assert.throws(()=>parseRealized({...report(),...change}))
 assert.equal(parseRealized({...report(),report_status:undefined}).report_status,'LEGACY_UNVERIFIED')
})
for(const state of ['VALID','STALE','LEGACY_UNVERIFIED'])test(`${state}: report freshness never becomes zero-error success`,async()=>{
 const r={...report(),report_status:state,...(state==='STALE'?{assessed_at:'2026-11-08T12:00:00Z'}:{})}
 globalThis.fetch=async()=>Response.json(r)
 const view=render(<RealizedForecastEvaluation/>);
 await waitFor(()=>assert.ok(view.getByText('Valid report contains no realized pairs')))
 assert.ok(view.getByText(/Minimum sample: 20/))
 if(state==='STALE')assert.ok(view.getByText(/Reporting refresh is overdue/))
 if(state==='LEGACY_UNVERIFIED')assert.ok(view.getByText(/Historical snapshot: receipt verification/))
 assert.equal(view.queryByText('0.00'),null)
})
for(const [code,message,status]of [['REALIZED_REPORT_MISSING','No realized performance report',404],['REALIZED_INPUTS_MISSING','waiting for forecast history',503],['REALIZED_REPORT_FAILED','could not be generated',503],['REALIZED_REPORT_INVALID','failed integrity validation',503]]as const)test(`${code}: no substituted metrics or sensitive errors`,async()=>{
 globalThis.fetch=async()=>Response.json({detail:{code,private:'NEVER_DISPLAY'}},{status})
 const view=render(<RealizedForecastEvaluation/>);await waitFor(()=>assert.ok(view.getByText(new RegExp(message))))
 assert.ok(!view.container.textContent?.includes('NEVER_DISPLAY'))
 assert.equal(view.queryByText('Verified report sample'),null)
})

test('genuine-shape sufficient sample renders dated metrics and per-horizon insufficiency',async()=>{
 const available={status:'Available',pair_count:23,mae:2,rmse:2,bias:2}
 const insufficient={status:'Insufficient data',pair_count:1,mae:null,rmse:null,bias:null}
 const r={...report(),data_status:'AVAILABLE',releases:[{model_release:'next24h-hgb-2026-09-21-v1',overall:available,windows:{'24h':available,'7d':available,'30d':available},horizons:Array.from({length:24},(_,i)=>({...insufficient,horizon_hours:i+1})),target_dates:2,first_target:'2026-11-07T01:00:00Z',last_target:'2026-11-08T08:00:00Z',performance_status:'Available',performance_reason:'Receipt-verified fixture'}]}
 assert.equal(parseRealized(r).releases[0].overall.rmse,2)
 for(const overall of [{...available,pair_count:19},{...available,mae:-1},{...available,rmse:1},{...available,bias:3},{...available,mae:null}])assert.throws(()=>parseRealized({...r,releases:[{...r.releases[0],overall}]}))
 globalThis.fetch=async()=>Response.json(r)
 const view=render(<RealizedForecastEvaluation/>);await waitFor(()=>assert.ok(view.getByText('Verified report sample')))
 assert.equal(view.getAllByText('MAE · EUR/MWh').length,2);assert.ok(view.getByText('Export this release’s evaluation'))
 assert.ok(view.getByText('Complete observations through'))
 assert.equal(view.queryByText('All realized history'),null)
})
