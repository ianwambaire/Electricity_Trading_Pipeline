import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseInfluence, rankCoefficients, parseContext, contextFields, parseAdminOperations, parseRealized } from '../src/api/parity.ts'
import { csv } from '../src/api/csv.ts'
import { api, ApiError } from '../src/api/client.ts'
import { bindApiSession } from '../src/api/accessToken.ts'
import { parseVintages, parseReadiness } from '../src/api/contracts.ts'
const digest='a'.repeat(64)
const features=Array.from({length:31},(_,i)=>({feature:`fixture_feature_${i}`,importance:i+.5,signed_coefficient:i%2?i+.5:-(i+.5)}))
const report={model:'Ordinary Linear Regression',horizon_hours:1,feature_count:31,metadata_sha256:digest,report_sha256:digest,provenance:'Fixture-only provenance',limitation:'Not causal; separate from HGB',features}
test('31 coefficient values, signs, provenance and independent stable sorting',()=>{
 const data=parseInfluence({...report,access_token:'never-display'})
 assert.deepEqual(data.features,features)
 assert.equal(rankCoefficients(data.features,'magnitude')[0].signed_coefficient,-30.5)
 assert.equal(data.features[0].feature,'fixture_feature_0')
 assert.equal(rankCoefficients(data.features,'name')[1].feature,'fixture_feature_1')
 assert.ok(!JSON.stringify(data).includes('never-display'))
 for(const invalid of [{...report,model:'HistogramGradientBoostingRegressor'},{...report,horizon_hours:24},{...report,features:features.slice(1)},{...report,features:[...features.slice(1),features[1]]},{...report,report_sha256:'private-path'},{...report,features:[{...features[0],signed_coefficient:NaN},...features.slice(1)]},{...report,features:[{...features[0],importance:99},...features.slice(1)]}])assert.throws(()=>parseInfluence(invalid))
})
test('CSV preserves numeric negatives, null missingness, quotes, newlines and formula safety',()=>{
 const result=csv([['feature','value','missing','text'],['price',-5,null,' =WEBSERVICE("bad")'],['with,comma',2,null,'two\nlines']])
 assert.ok(result.includes('"-5","","\' =WEBSERVICE(""bad"")"'))
 assert.ok(result.includes('"with,comma"'))
 assert.ok(result.endsWith('\r\n'))
 assert.ok(!result.includes('"null"'))
})
test('exact context keeps unavailable fields null and discards unexpected values',()=>{
 const input={available:false,issue_time:'2026-09-01T00:00:00Z',provenance:'Exact hour',...Object.fromEntries(contextFields.map(k=>[k,null])),internal_path:'/private'}
 const result=parseContext(input)
 assert.equal(result.price_rolling_mean_24h,null)
 assert.ok(!JSON.stringify(result).includes('/private'))
 assert.throws(()=>parseContext({...input,issue_time:'2026-09-01'}))
 assert.throws(()=>parseContext({...input,load_mw:Infinity}))
})
test('Admin operations distinguishes missing tables, valid emptiness and measured zero',()=>{
 const input={run_evidence:'empty',incident_evidence:'missing',timing_evidence:'available',runs:[],incidents:[],latest_timings:[{stage:'Total pipeline',started_at:null,ended_at:null,seconds:0,status:'SUCCESS'}],timing_summary:null,provenance:'Fixture'}
 assert.equal(parseAdminOperations(input).incident_evidence,'missing')
 assert.equal(parseAdminOperations(input).latest_timings[0].seconds,0)
 assert.throws(()=>parseAdminOperations({...input,incident_evidence:'healthy'}))
 assert.throws(()=>parseAdminOperations({...input,latest_timings:[{...input.latest_timings[0],seconds:-1}]}))
})
test('readiness and vintage optional diagnostics preserve zero/false versus missing',()=>{
 const r=parseReadiness({generated_at_utc:'2026-09-01T00:00:00Z',dataset_status:'NOT_READY',distinct_issue_cycles:0,distinct_calendar_days:0,complete_issue_cycles:0,horizon_coverage_count:0,output_rows:0,duplicate_key_count:0,leakage_check_passed:false})
 assert.equal(r.duplicate_key_count,0);assert.equal(r.leakage_check_passed,false)
 const v=parseVintages({generated_at_utc:r.generated_at_utc,overall_status:'STALE',sources:[{source:'OPEN_METEO',status:'STALE',missing_target_count:0,revision_count:2}]})
 assert.equal(v.sources[0].missing_target_count,0);assert.equal(v.sources[0].consecutive_collection_failures,null)
 assert.throws(()=>parseReadiness({...r,horizon_coverage_count:25}))
})
test('valid empty realized report is different from malformed metrics and unknown fields',()=>{
 assert.deepEqual(parseRealized({assessed_at:'2026-09-01T00:00:00Z',report_sha256:digest,provenance:'Fixture',releases:[]}).releases,[])
 assert.throws(()=>parseRealized({assessed_at:'bad',report_sha256:digest,releases:[]}))
})
test('Admin-only clients send access token and never try alternate public routes on failure',async()=>{
 const original=globalThis.fetch;const cleanup=bindApiSession(()=>'fixture-access',()=>undefined)
 const calls:string[]=[]
 try {
  globalThis.fetch=async(url,opts)=>{calls.push(String(url));assert.equal((opts?.headers as Record<string,string>).Authorization,'Bearer fixture-access');return new Response('private backend text',{status:403})}
  for(const load of [api.influence,api.adminOperations])await assert.rejects(load(),(e:unknown)=>e instanceof ApiError&&e.status===403&&!e.message.includes('private'))
  assert.deepEqual(calls,['/api/admin/models/linear-feature-influence','/api/admin/operations'])
 } finally {cleanup();globalThis.fetch=original}
})

test('source-backed exploration validates bounded rows and missing weather values',async()=>{
 const { parseExploration, parsePriceComparison }=await import('../src/api/parity.ts')
 const input={matched_rows:1,coverage:{snapshot_id:'silver-fixture'},generation:[{source:'gas_mw',average_mw:null,observations:0}],weather:[{timestamp:'2026-09-01T00:00:00Z',temperature_2m:null,wind_speed_10m:2,gap_before:false}],sampling:'Fixture-only sampling'}
 assert.equal(parseExploration(input).weather[0].temperature_2m,null)
 assert.throws(()=>parseExploration({...input,weather:Array(2001).fill(input.weather[0])}))
 const p=parsePriceComparison({latest_timestamp:null,latest_price:null,previous_24h_average:null,seven_day_average:null,provenance:'Missing complete windows'})
 assert.equal(p.previous_24h_average,null)
})

test('same-evaluation persistence improvement and forecast issuance provenance are explicit',async()=>{
 const {rmseImprovement,parseForecastProvenance}=await import('../src/api/parity.ts')
 assert.equal(rmseImprovement(5,10),50);assert.equal(rmseImprovement(15,10),-50)
 assert.equal(rmseImprovement(5,null),null);assert.equal(rmseImprovement(5,0),null)
 const result=parseForecastProvenance({issue_time:'2026-09-01T00:00:00Z',issued_at_utc:null,issuance_evidence:'missing',provenance_evidence:'missing',market_latest_complete_hour:null,weather_acquired_at_utc:null,weather_source:'private-hostname',note:'Fixture',token:'never-display'})
 assert.equal(result.issued_at_utc,null);assert.equal(result.weather_source,null)
 assert.ok(!JSON.stringify(result).includes('never-display'))
})
