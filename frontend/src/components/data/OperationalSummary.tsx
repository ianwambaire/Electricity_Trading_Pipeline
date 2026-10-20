import type { Operations } from '../../api/restoration'
import type { ApiState } from '../../hooks/useApi'
import { formatTime } from '../../api/forecastState'
import { ApiPanel, Facts } from './ApiPanel'

export function OperationsNotice({data}:{data:Operations|null}){
  if(!data)return null
  return <div className={`notice ${data.health==='Degraded'?'notice-error':data.health==='Healthy'?'notice-ok':'notice-warning'}`} role="status"><strong>System health: {data.health}</strong><p>{data.explanation}</p>{data.forecast_reason&&<p>{data.forecast_reason}</p>}</div>
}
export function OperationalSummary({state}:{state:ApiState<Operations>&{retry:()=>void}}){
  return <ApiPanel title="Operational summary" description="Public-safe status only. Execution success does not establish forecast issuance." state={state}>{data=><><Facts items={[
    ['Latest execution',data.latest_run_status??'Unavailable'],['Execution time',formatTime(data.latest_run_time)],['Latest successful run',formatTime(data.latest_success_time)],['Latest complete market hour',formatTime(data.latest_complete_market_hour)],['Recorded forecast status',data.forecast_status??'Unavailable'],['S3 synchronization',data.s3_sync_status??'Unavailable'],['Passed checks · latest 20',data.recent_checks_passed??'Unavailable'],['Failed checks · latest 20',data.recent_checks_failed??'Unavailable'],['Warning checks · latest 20',data.recent_checks_warning??'Unavailable'],['Continuity warning sources',data.continuity_warning_sources??'Unavailable'],
  ]}/><p className="data-note">Assessed at {formatTime(data.assessed_at)}. {data.completeness_note}</p><details className="methodology"><summary>How health is assessed</summary><p>{data.health_rules}</p></details></>}</ApiPanel>
}
