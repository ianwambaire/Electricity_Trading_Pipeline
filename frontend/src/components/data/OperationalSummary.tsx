import type { Operations } from '../../api/restoration'
import type { ApiState } from '../../hooks/useApi'
import { formatTime } from '../../api/forecastState'
import { ApiPanel, Facts } from './ApiPanel'
import {useClock} from '../../hooks/useClock'
import {operationalForecastState} from '../../api/operationalForecastState'

export function OperationsNotice({data}:{data:Operations|null}){
  const now=useClock(data?.forecast_expires_at?Date.parse(data.forecast_expires_at):undefined)
  data=operationalForecastState(data,now)
  if(!data)return null
  return <div className={`notice ${data.health==='Degraded'?'notice-error':data.health==='Healthy'?'notice-ok':'notice-warning'}`} role="status"><strong>Recorded operational health: {data.health}</strong><p>{data.explanation}</p>{data.forecast_reason&&<p>{data.forecast_reason}</p>}</div>
}
export function OperationalSummary({state}:{state:ApiState<Operations>&{retry:()=>void}}){
  const now=useClock(state.data?.forecast_expires_at?Date.parse(state.data.forecast_expires_at):undefined)
  state={...state,data:operationalForecastState(state.data,now)}
  return <ApiPanel title="Historical operational snapshot" description="Public-safe status only. Historical operational evidence; execution success does not establish current forecast issuance." state={state}>{data=><><Facts items={[
    ['Historical execution',data.latest_run_status??'Unavailable'],['Historical execution time',formatTime(data.latest_run_time)],['Historical successful run',formatTime(data.latest_success_time)],['Snapshot market hour',formatTime(data.latest_complete_market_hour)],['Current forecast publication',data.forecast_status??'Unavailable'],['S3 synchronization',data.s3_sync_status??'Unavailable'],['Passed checks · latest 20',data.recent_checks_passed??'Unavailable'],['Failed checks · latest 20',data.recent_checks_failed??'Unavailable'],['Warning checks · latest 20',data.recent_checks_warning??'Unavailable'],['Continuity warning sources',data.continuity_warning_sources??'Unavailable'],
  ]}/><p className="data-note">Assessed at {formatTime(data.assessed_at)}. {data.completeness_note}</p><details className="methodology"><summary>How health is assessed</summary><p>{data.health_rules}</p></details></>}</ApiPanel>
}
