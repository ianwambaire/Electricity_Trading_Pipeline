import './dom-environment.ts'
import {afterEach,test} from 'node:test'
import assert from 'node:assert/strict'
import React from 'react'
import {cleanup,render} from '@testing-library/react'
import {ForecastSummary} from '../src/components/data/ForecastSummary'
import {parseNext24} from '../src/api/contracts'
import {ApiPanel} from '../src/components/data/ApiPanel'
import {ApiError} from '../src/api/client'

afterEach(cleanup)
function report(expired=false){
 const issue=Date.now()-(expired?4:2)*3600000
 return parseNext24({row_count:24,forecasts:Array.from({length:24},(_,i)=>({issue_time:new Date(issue).toISOString(),target_time:new Date(issue+(i+1)*3600000).toISOString(),horizon_hours:i+1,predicted_price_eur_mwh:100+i,model_release:'next24h-hgb-2026-09-21-v1'})),publication:{status:'VALID',issue_time:new Date(issue).toISOString(),expires_at:new Date(issue+3*3600000).toISOString(),completed_at:new Date(issue+3600000).toISOString()}})
}
const pipeline={data:{latest_run_status:'SUCCESS',latest_run_timestamp:'2026-01-01T00:00:00Z',forecast_status:'WITHHELD'},loading:false,error:null,receivedAt:null}
test('fresh publication renders actual synthetic values despite historical withholding',()=>{
 const view=render(<ForecastSummary report={report()} pipeline={pipeline}/>)
 assert.ok(view.getByText('Valid published forecast'))
 assert.ok(view.getByText('Average · EUR/MWh'))
 assert.ok(view.getByText(/Historical snapshot/))
})
test('expired publication renders WITHHELD and removes statistics and download',()=>{
 const view=render(<ForecastSummary report={report(true)} pipeline={pipeline}/>)
 assert.ok(view.getByText('WITHHELD'))
 assert.equal(view.queryByText('Average · EUR/MWh'),null)
 assert.equal(view.queryByRole('button',{name:/Download/}),null)
})
test('withheld API state never renders chart/content children',()=>{
 const state={data:null,loading:false,error:new ApiError('Safe withheld message',503,'FORECAST_WITHHELD'),receivedAt:null,retry(){}}
 const view=render(<ApiPanel title="24-hour forecast report" state={state}>{()=> <p>Do not display predictions</p>}</ApiPanel>)
 assert.ok(view.getByText('WITHHELD'))
 assert.equal(view.queryByText('Do not display predictions'),null)
})
