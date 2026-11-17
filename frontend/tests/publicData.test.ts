import { test } from 'node:test'
import assert from 'node:assert/strict'
import { generationKeys, parseCoverage, parseMarketHistory, parseModels } from '../src/api/publicData.ts'

// Contract fixtures only; not runtime data or demonstration responses.
const timestamp = '2026-09-01T00:00:00Z'
const coverage = { source:'Persisted hourly Silver market observations',market_area:'DE-LU',resolution:'hourly',snapshot_id:'silver-test',row_count:1,first_observation:timestamp,latest_observation:timestamp,missing_hours_in_span:0,renewable_definition:'Selected-source mix' }
const row = { timestamp,price_eur_mwh:-5,load_mw:null,generation:Object.fromEntries(generationKeys.map(k=>[k,null])),renewable_generation_mw:null,renewable_share:null }
const page = {coverage,start:timestamp,end:timestamp,matched_rows:1,row_count:1,limit:1000,offset:0,next_offset:null,observations:[row]}

test('public market parsing preserves missing values and negative observed prices',()=>{
  const data=parseMarketHistory(page)
  assert.equal(data.observations[0].price_eur_mwh,-5)
  assert.equal(data.observations[0].load_mw,null)
  assert.equal(data.observations[0].renewable_share,null)
  assert.throws(()=>parseMarketHistory({...page,row_count:2}))
  assert.throws(()=>parseMarketHistory({...page,limit:2001}))
  assert.throws(()=>parseMarketHistory({...page,next_offset:1}))
  assert.throws(()=>parseMarketHistory({...page,observations:[{...row,load_mw:Infinity}]}))
  assert.throws(()=>parseCoverage({...coverage,latest_observation:'not-a-time'}))
})
test('market empty ranges and unknown field filtering are explicit',()=>{
  assert.equal(parseMarketHistory({...page,matched_rows:0,row_count:0,observations:[]}).row_count,0)
  const data=parseMarketHistory({...page,secret:'private',coverage:{...coverage,local_path:'/private/value'}})
  assert.ok(!JSON.stringify(data).includes('private'))
})
const missingModel=(key:'next24h'|'one_hour')=>({key,name:null,version:null,release_kind:null,purpose:'Model metadata fixture',horizons_hours:key==='next24h'?Array.from({length:24},(_,i)=>i+1):[1],metadata_status:'missing',metadata_provenance:null,metadata_sha256:null,released_at_utc:null,feature_count:null,artifact_status:'missing',evaluations:[],notes:[]})
test('model identities cannot borrow another model horizon or evaluation basis',()=>{
  const next=missingModel('next24h'),one=missingModel('one_hour')
  assert.equal(parseModels({models:[next,one]}).models[1].version,null)
  assert.throws(()=>parseModels({models:[{...next,horizons_hours:[1]},one]}))
  assert.throws(()=>parseModels({models:[next,{...one,name:'Histogram Gradient Boosting (24 direct outputs)'}]}))
  assert.throws(()=>parseModels({models:[next,{...one,evaluations:[{split:'test'}]}]}))
  assert.throws(()=>parseModels({models:[next,next]}))
})
test('release-specific evaluation values and unknown fields are handled safely',()=>{
  const next=missingModel('next24h'),one=missingModel('one_hour')
  const evaluation={split:'final_holdout',mae:1,rmse:2,r2:.5,observations:20,observation_basis:'target_hours',period_start:timestamp,period_end:timestamp,period_basis:'target_time',persistence_rmse:3}
  const data=parseModels({models:[next,{...one,name:'Ordinary Linear Regression',metadata_status:'available',evaluations:[evaluation],local_path:'/private/path'}]})
  assert.equal(data.models[1].evaluations[0].rmse,2)
  assert.ok(!JSON.stringify(data).includes('private'))
  assert.throws(()=>parseModels({models:[next,{...one,evaluations:[{...evaluation,rmse:NaN}]}]}))
})
