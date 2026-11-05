import {api} from '../../api/client'
import {formatTime} from '../../api/forecastState'
import {useApi} from '../../hooks/useApi'
import {useClock} from '../../hooks/useClock'
import {useCurrentOperations} from '../../operations/currentContext'
import {Facts} from './ApiPanel'

export function CurrentOperations(){
 const state=useCurrentOperations()
 const data=state?.data
 const now=useClock(data?.fresh_until?Date.parse(data.fresh_until):undefined)
 const status=data?.status==='VALID'&&data.fresh_until&&now>=Date.parse(data.fresh_until)?'STALE':data?.status
 const execution=status==='VALID'&&!state?.loading&&!state?.error?data?.current_execution:null
 return <section className="panel" aria-label="Current pipeline evidence"><h2>Current pipeline execution</h2>
  <p role="status">{state?.loading?'Loading current execution…':state?.error?'Current execution unavailable':`Operational evidence: ${status??'MISSING'}`}</p>
  {execution?<Facts items={[["Scheduled (UTC)",formatTime(execution.scheduled_at)],['Started (UTC)',formatTime(execution.started_at)],['Completed (UTC)',formatTime(execution.completed_at)],['Execution',execution.execution_outcome],['Inference',execution.inference_outcome],['Automatic delivery',execution.publication_outcome]]}/>:<p>Current execution cannot be established. Historical snapshots are shown separately.</p>}
  {data?.observed_at&&<p className="data-note">Evidence observed {formatTime(data.observed_at)}. Operational freshness cutoff {formatTime(data.fresh_until)}.</p>}
  <p className="data-note">Execution, inference and delivery are separate outcomes. Current forecast availability is assessed independently from the active forecast publication.</p>
  {state&&<button className="secondary-button" onClick={state.retry}>Refresh current execution</button>}
 </section>
}

// Rendered only inside the existing server-confirmed Admin branch. API role
// enforcement remains mandatory; this component does not confer authorization.
export function CurrentAdminOperations(){
 const publicState=useCurrentOperations()
 const state=useApi(api.currentAdminOperations)
 const now=useClock(state.data?.fresh_until?Date.parse(state.data.fresh_until):undefined)
 const report=state.data
 const same=!state.loading&&!state.error&&!publicState?.loading&&!publicState?.error&&report?.status==='VALID'&&publicState?.data?.status==='VALID'&&report.evidence_id===publicState.data.evidence_id&&JSON.stringify(report.current_execution)===JSON.stringify(publicState.data.current_execution)&&!!report.fresh_until&&now<Date.parse(report.fresh_until)
 return <section className="panel" aria-label="Current Admin evidence"><h2>Current execution association</h2>
  {same&&report?.admin?<Facts items={[["Prefect execution",report.admin.execution_identity.flow_run_id],['Internal execution',report.admin.execution_identity.pipeline_run_id??'Not recorded'],['Receipt',report.admin.inference.receipt_id??'Not recorded'],['Withholding category',report.admin.inference.withholding?.reason??'Not recorded'],['Failed prerequisite',report.admin.inference.withholding?.gate??'Not recorded'],['Exact publication time',formatTime(report.admin.delivery.published_at)]]}/>:<p role="status">{state.error?'Administrative current evidence unavailable.':state.loading?'Loading current association…':'No matching fresh Admin evidence. Refresh to align the publication versions.'}</p>}
  <button className="secondary-button" onClick={()=>{state.retry();publicState?.retry()}}>Refresh association</button>
 </section>
}
