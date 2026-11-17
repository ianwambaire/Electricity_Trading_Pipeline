import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseNext24 } from '../src/api/contracts.ts'
import { forecastCsv, forecastStatistics } from '../src/api/forecastPresentation.ts'
import { parseAnomalyEvents, parseAnomalySummary } from '../src/api/restoration.ts'

// Synthetic contract evidence only. No fixture is imported by the application.
const issue=Date.parse('2026-09-01T00:00:00Z')
const report=parseNext24({row_count:24,forecasts:Array.from({length:24},(_,i)=>({issue_time:new Date(issue).toISOString(),target_time:new Date(issue+(i+1)*3600000).toISOString(),horizon_hours:i+1,predicted_price_eur_mwh:i===23?200:i-2,model_release:'test-release'}))})
test('24-hour statistics preserve negative values, exact target times and chronological ordering',()=>{
 const before=JSON.stringify(report)
 const s=forecastStatistics(report)
 assert.equal(s.minimum.predicted_price_eur_mwh,-2)
 assert.equal(s.maximum.target_time,report.forecasts[23].target_time)
 assert.equal(s.median,9.5)
 assert.equal(s.change,202)
 assert.equal(s.negative,2)
 assert.equal(s.elevated,1)
 assert.equal(JSON.stringify(report),before)
})
test('CSV has all 24 real rows, issue/target metadata, retained classification and numeric negative prices',()=>{
 const text=forecastCsv(report,'Withheld')
 assert.equal(text.trim().split('\r\n').length,25)
 assert.ok(text.includes('"-2"'))
 assert.ok(text.includes('"Withheld"'))
 assert.ok(text.includes('not current live forecasts'))
 assert.ok(text.includes(report.forecasts[0].target_time))
 assert.ok(forecastCsv(report,'=formula').includes('"\'=formula"'))
 assert.ok(forecastCsv(report,'-formula').includes('"\'-formula"'))
})
test('valid empty anomaly reports differ from missing or malformed reports',()=>{
 const empty={report_status:'empty',count:0,total_report_rows:0,first_event:null,last_event:null,minimum_price:null,maximum_price:null,average_load_mw:null,method:'Isolation Forest',provenance:'Persisted report',limitation:'No scores',private_path:'never include'}
 assert.equal(parseAnomalySummary(empty).count,0)
 assert.ok(!JSON.stringify(parseAnomalySummary(empty)).includes('never include'))
 assert.throws(()=>parseAnomalySummary({...empty,report_status:'missing'}))
 assert.throws(()=>parseAnomalySummary({...empty,count:-1}))
 assert.throws(()=>parseAnomalyEvents({matched_rows:1,row_count:1,offset:0,limit:100,next_offset:null,order:'time_desc',events:[]}))
 const page=parseAnomalyEvents({matched_rows:1,row_count:1,offset:0,limit:100,next_offset:null,order:'time_desc',events:[{timestamp:new Date(issue).toISOString(),price_eur_mwh:-5,load_mw:10,anomaly_score:999}]})
 assert.equal(page.events[0].price_eur_mwh,-5)
 assert.ok(!JSON.stringify(page).includes('anomaly_score'))
})
