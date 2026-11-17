import './dom-environment.ts'
import {afterEach,test} from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {cleanup,fireEvent,render,waitFor} from '@testing-library/react'
import {CurrentOperations,CurrentAdminOperations} from '../src/components/data/CurrentOperations'
import {CurrentOperationsProvider} from '../src/operations/CurrentOperationsProvider'
import {CurrentOperationsContext} from '../src/operations/currentContext'
import {parseCurrentOperations} from '../src/api/currentOperations'
import type {CurrentOperations as Report} from '../src/api/currentOperations'
import {api} from '../src/api/client'

const original=globalThis.fetch
const future='2099-11-05T06:45:00Z'
const view=()=>({status:'VALID',evidence_id:'a'.repeat(64),observed_at:'2099-11-05T06:48:00Z',scheduled_at:future,fresh_until:'2099-11-05T08:15:00Z',forecast_eligibility:'NOT_ASSESSED',current_execution:{scheduled_at:future,started_at:'2099-11-05T06:45:01Z',completed_at:'2099-11-05T06:47:00Z',execution_outcome:'COMPLETED',inference_outcome:'WITHHELD',publication_outcome:'SKIPPED_WITHHELD',source:'PREFECT_AND_PERSISTED_PIPELINE'}})
function report(status='VALID'):Report{
 const value=view()
 return parseCurrentOperations(status==='VALID'?value:{...value,status,current_execution:null,...(status==='STALE'?{}:{evidence_id:null,observed_at:null,scheduled_at:null,fresh_until:null})})
}
function context(data:Report|null,children:React.ReactNode){return <CurrentOperationsContext.Provider value={{data,loading:false,error:null,receivedAt:null,retry:()=>{}}}>{children}</CurrentOperationsContext.Provider>}
function admin(){return {...view(),admin:{execution_identity:{flow_run_id:'11111111-1111-4111-8111-111111111111',deployment_id:'33333333-3333-4333-8333-333333333333',pipeline_run_id:'b'.repeat(32)},inference:{outcome:'WITHHELD',task_run_id:'44444444-4444-4444-8444-444444444444',receipt_id:null,issue_time:null,withholding:{reason:'INPUTS_UNAVAILABLE',gate:'JOINT_PRICE_LOAD_HOUR'}},delivery:{outcome:'SKIPPED_WITHHELD',receipt_id:null,bundle_sha256:null,published_at:null}}}}
afterEach(()=>{cleanup();globalThis.fetch=original})

test('VALID keeps execution inference delivery and live eligibility separate',()=>{
 const screen=render(context(report(),<CurrentOperations/>))
 assert.ok(screen.getByText('Operational evidence: VALID'))
 for(const text of ['COMPLETED','WITHHELD','SKIPPED_WITHHELD'])assert.ok(screen.getByText(text))
 assert.ok(screen.getByText(/Current forecast availability is assessed independently/))
 assert.equal(screen.queryByText('October 26'),null)
})
for(const status of ['STALE','MISSING','INVALID'])test(`${status} has no current execution or historical fallback`,()=>{
 const screen=render(context(report(status),<CurrentOperations/>))
 assert.ok(screen.getByText(`Operational evidence: ${status}`))
 assert.ok(screen.getByText(/Current execution cannot be established/))
 assert.equal(screen.queryByText('COMPLETED'),null)
 assert.equal(screen.queryByText('SKIPPED_WITHHELD'),null)
})

test('local expiry removes previously valid current fields without waiting for a new response',()=>{
 const data=report();data.fresh_until='2000-01-01T00:00:00Z'
 const screen=render(context(data,<CurrentOperations/>))
 assert.ok(screen.getByText('Operational evidence: STALE'))
 assert.equal(screen.queryByText('COMPLETED'),null)
})

test('public parser rejects Admin fields, unknown statuses and stale populated records',()=>{
 assert.throws(()=>parseCurrentOperations(admin()))
 assert.throws(()=>parseCurrentOperations({...view(),status:'SUCCESS'}))
 assert.throws(()=>parseCurrentOperations({...view(),status:'STALE'}))
 assert.throws(()=>parseCurrentOperations({...view(),forecast_eligibility:'VALID'}))
 assert.throws(()=>parseCurrentOperations({...view(),scheduled_at:'October 26'}))
 const bad=admin();bad.admin.inference.outcome='GENERATED'
 assert.throws(()=>parseCurrentOperations(bad,true))
})

test('matching Admin evidence displays recognized gates, without inventing publication timestamps',async()=>{
 globalThis.fetch=async()=>new Response(JSON.stringify(admin()),{status:200})
 const screen=render(context(report(),<CurrentAdminOperations/>))
 await waitFor(()=>assert.ok(screen.getByText('JOINT_PRICE_LOAD_HOUR')))
 assert.ok(screen.getByText('11111111-1111-4111-8111-111111111111'))
 assert.ok(screen.getByText('Exact publication time'))
})

test('different publication versions never combine public current execution with Admin identities',async()=>{
 const other=admin();other.evidence_id='b'.repeat(64)
 globalThis.fetch=async()=>new Response(JSON.stringify(other),{status:200})
 const screen=render(context(report(),<CurrentAdminOperations/>))
 await waitFor(()=>assert.ok(screen.getByText(/No matching fresh Admin evidence/)))
 assert.equal(screen.queryByText('JOINT_PRICE_LOAD_HOUR'),null)
 assert.equal(screen.queryByText('11111111-1111-4111-8111-111111111111'),null)
})

test('API client uses new GET-only routes and preserves authorization failure',async()=>{
 const calls:string[]=[]
 globalThis.fetch=async(input,init)=>{calls.push(String(input));assert.equal(init?.method,'GET');return new Response(JSON.stringify(view()),{status:200})}
 await api.currentOperations()
 assert.deepEqual(calls,['/api/operations/current'])
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:'private raw content'}),{status:403})
 await assert.rejects(api.currentAdminOperations(),error=>error instanceof Error&&!error.message.includes('private raw content'))
})

test('one provider selection is shared by Overview and Pipeline views and manual refresh',async()=>{
 let calls=0
 globalThis.fetch=async()=>{calls++;return new Response(JSON.stringify(view()),{status:200})}
 const screen=render(<CurrentOperationsProvider><CurrentOperations/><CurrentOperations/></CurrentOperationsProvider>)
 await waitFor(()=>assert.equal(screen.getAllByText('Operational evidence: VALID').length,2))
 assert.equal(calls,1)
 fireEvent.click(screen.getAllByText('Refresh current execution')[0])
 await waitFor(()=>assert.equal(calls,2))
 await waitFor(()=>assert.equal(screen.getAllByText('Operational evidence: VALID').length,2))
})

test('contradictory inference and delivery or execution chronology are rejected',()=>{
 const inconsistent=view();inconsistent.current_execution.publication_outcome='PUBLISHED'
 assert.throws(()=>parseCurrentOperations(inconsistent))
 const backwards=view();backwards.current_execution.completed_at='2099-11-05T06:44:00Z'
 assert.throws(()=>parseCurrentOperations(backwards))
})
