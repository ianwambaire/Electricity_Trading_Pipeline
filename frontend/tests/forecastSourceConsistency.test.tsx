import './dom-environment.ts'
import {afterEach,test} from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {cleanup,render,waitFor} from '@testing-library/react'
import {api,ApiError} from '../src/api/client'
import {ForecastProvenanceEvidence} from '../src/components/data/ForecastEvidence'
import {OperationsNotice} from '../src/components/data/OperationalSummary'
import type {Operations} from '../src/api/restoration'

const originalFetch=globalThis.fetch
const issue='2026-01-05T08:00:00Z'
const completed='2026-01-05T09:21:00Z'
function evidence(hour=issue){return {issue_time:hour,issued_at_utc:'2026-01-05T09:20:00Z',issuance_evidence:'available',provenance_evidence:'available',market_latest_complete_hour:null,weather_acquired_at_utc:'2026-01-05T09:10:00Z',weather_source:'open_meteo_forecast_api_operational_model',note:'Synthetic hash-bound publication evidence'}}
afterEach(()=>{cleanup();globalThis.fetch=originalFetch})

test('provenance request pins displayed issue and publication completion',async()=>{
 let requested=''
 globalThis.fetch=async input=>{requested=String(input);return new Response(JSON.stringify(evidence()),{status:200})}
 const data=await api.forecastProvenance(issue,completed)
 const url=new URL(requested,'https://synthetic.invalid')
 assert.equal(url.pathname,'/api/admin/forecast/provenance')
 assert.equal(url.searchParams.get('issue_time'),issue)
 assert.equal(url.searchParams.get('completed_at'),completed)
 assert.equal(data.market_latest_complete_hour,null)
})

test('mismatched provenance and changed-publication errors never enter UI',async()=>{
 globalThis.fetch=async()=>new Response(JSON.stringify(evidence('2026-01-05T09:00:00Z')),{status:200})
 await assert.rejects(api.forecastProvenance(issue,completed),ApiError)
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:'private raw details'}),{status:409})
 const view=render(<ForecastProvenanceEvidence issue={issue} completed={completed}/>)
 await waitFor(()=>assert.ok(view.getByRole('alert')))
 assert.equal(view.queryByText('Synthetic hash-bound publication evidence'),null)
 assert.equal(view.queryByText('private raw details'),null)
})

test('publication expiry hides provenance rather than substituting a frozen report',async()=>{
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:'FORECAST_WITHHELD'}}),{status:503})
 const view=render(<ForecastProvenanceEvidence issue={issue} completed={completed}/>)
 await waitFor(()=>assert.ok(view.getByRole('alert')))
 assert.equal(view.queryByText('Synthetic hash-bound publication evidence'),null)
})

test('operational notice identifies historical evidence instead of live system health',()=>{
 const data={health:'Historical snapshot',explanation:'Recorded snapshot only, not live pipeline health.',forecast_reason:'Valid published forecast; synthetic issue and cutoff.'} as Operations
 const view=render(<OperationsNotice data={data}/>)
 assert.ok(view.getByText('Recorded operational health: Historical snapshot'))
 assert.ok(view.getByText(/not live pipeline health/))
 assert.ok(view.getByText(/Valid published forecast/))
 assert.equal(view.queryByText('System health: Healthy'),null)
})
