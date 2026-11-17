export interface CurrentExecution {
 scheduled_at:string; started_at:string|null; completed_at:string|null
 execution_outcome:string; inference_outcome:string; publication_outcome:string; source:'PREFECT_AND_PERSISTED_PIPELINE'
}
export interface CurrentOperations {
 status:'VALID'|'STALE'|'MISSING'|'INVALID'; evidence_id:string|null; observed_at:string|null
 scheduled_at:string|null; fresh_until:string|null; current_execution:CurrentExecution|null; forecast_eligibility:'NOT_ASSESSED'
 admin?: {execution_identity:{flow_run_id:string;deployment_id:string;pipeline_run_id:string|null}; inference:{outcome:string;task_run_id:string|null;receipt_id:string|null;issue_time:string|null;withholding:{reason:string;gate:string}|null}; delivery:{outcome:string;receipt_id:string|null;bundle_sha256:string|null;published_at:string|null}}
}
const executionStatuses=['SCHEDULED','PENDING','RUNNING','COMPLETED','FAILED','CANCELLED','CRASHED']
const inferenceStatuses=['NOT_RUN','GENERATED','UNCHANGED','WITHHELD','UNAVAILABLE','FAILED','UNKNOWN']
const deliveryStatuses=['NOT_RUN','PUBLISHED','SKIPPED_WITHHELD','SKIPPED_EXPIRED','SKIPPED_DUPLICATE','REJECTED_OLDER_ISSUE','DISABLED','REJECTED_INFERENCE','FAILED','UNKNOWN']
function object(v:unknown, keys:string[]):Record<string,unknown>{
 if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).sort().join(',')!==[...keys].sort().join(','))throw Error('Invalid operational schema')
 return v as Record<string,unknown>
}
function text(v:unknown,pattern:RegExp):string{if(typeof v!=='string'||!pattern.test(v))throw Error('Invalid operational value');return v}
function time(v:unknown):string{const s=text(v,/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$/);if(!Number.isFinite(Date.parse(s)))throw Error('Invalid operational timestamp');return s}
function nullable<T>(v:unknown,parse:(v:unknown)=>T):T|null{return v===null?null:parse(v)}
function status(v:unknown,allowed:readonly string[]):string{if(typeof v!=='string'||!allowed.includes(v))throw Error('Invalid operational status');return v}
const hash=(v:unknown)=>text(v,/^[0-9a-f]{64}$/)
const uuid=(v:unknown)=>text(v,/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/)
const fields=['status','evidence_id','observed_at','scheduled_at','fresh_until','current_execution','forecast_eligibility']
export function parseCurrentOperations(v:unknown, admin=false):CurrentOperations{
 const hasAdmin=!!v&&typeof v==='object'&&Object.hasOwn(v,'admin')
 if(hasAdmin&&!admin)throw Error('Unexpected private operational fields')
 const p=object(v,hasAdmin?[...fields,'admin']:fields)
 const result:CurrentOperations={status:status(p.status,['VALID','STALE','MISSING','INVALID']) as CurrentOperations['status'],evidence_id:nullable(p.evidence_id,hash),observed_at:nullable(p.observed_at,time),scheduled_at:nullable(p.scheduled_at,time),fresh_until:nullable(p.fresh_until,time),current_execution:null,forecast_eligibility:'NOT_ASSESSED'}
 if(p.forecast_eligibility!=='NOT_ASSESSED')throw Error('Execution cannot attest forecast eligibility')
 if(result.status==='VALID'){
  if(!result.evidence_id||!result.observed_at||!result.scheduled_at||!result.fresh_until)throw Error('Missing operational provenance')
  const e=object(p.current_execution,['scheduled_at','started_at','completed_at','execution_outcome','inference_outcome','publication_outcome','source'])
  if(e.source!=='PREFECT_AND_PERSISTED_PIPELINE')throw Error('Unknown operational source')
  result.current_execution={scheduled_at:time(e.scheduled_at),started_at:nullable(e.started_at,time),completed_at:nullable(e.completed_at,time),execution_outcome:status(e.execution_outcome,executionStatuses),inference_outcome:status(e.inference_outcome,inferenceStatuses),publication_outcome:status(e.publication_outcome,deliveryStatuses),source:e.source}
  if(result.current_execution.scheduled_at!==result.scheduled_at)throw Error('Conflicting execution times')
  const current=result.current_execution
  if(['PUBLISHED','SKIPPED_DUPLICATE','SKIPPED_EXPIRED','REJECTED_OLDER_ISSUE'].includes(current.publication_outcome)&&!['GENERATED','UNCHANGED'].includes(current.inference_outcome))throw Error('Conflicting inference and delivery')
  if(current.inference_outcome==='WITHHELD'&&!['SKIPPED_WITHHELD','DISABLED','UNKNOWN'].includes(current.publication_outcome))throw Error('Conflicting withholding')
  if(current.inference_outcome!=='WITHHELD'&&current.publication_outcome==='SKIPPED_WITHHELD')throw Error('Conflicting withholding')
  const scheduled=Date.parse(current.scheduled_at), observed=Date.parse(result.observed_at)
  if(scheduled>observed||Date.parse(result.fresh_until)<=scheduled||current.started_at&&Date.parse(current.started_at)<scheduled||current.completed_at&&(Date.parse(current.completed_at)<Date.parse(current.started_at??current.scheduled_at)||Date.parse(current.completed_at)>observed))throw Error('Conflicting operational chronology')

 }else if(p.current_execution!==null||hasAdmin)throw Error('Unavailable evidence cannot populate current fields')
 if(hasAdmin){
  const a=object(p.admin,['execution_identity','inference','delivery'])
  const e=object(a.execution_identity,['flow_run_id','deployment_id','pipeline_run_id'])
  const i=object(a.inference,['outcome','task_run_id','receipt_id','issue_time','withholding'])
  const d=object(a.delivery,['outcome','receipt_id','bundle_sha256','published_at'])
  let withholding:null|{reason:string;gate:string}=null
  if(i.withholding!==null){const w=object(i.withholding,['reason','gate']);withholding={reason:status(w.reason,['INPUTS_UNAVAILABLE','INPUTS_INCOMPLETE','INPUTS_STALE','MODEL_UNVERIFIED','FEATURES_UNVERIFIED','UNKNOWN']),gate:status(w.gate,['JOINT_PRICE_LOAD_HOUR','PRICE_HISTORY','LOAD_HISTORY','GENERATION','WEATHER','MODEL_INTEGRITY','FEATURE_CONTRACT','INPUT_FRESHNESS','UNKNOWN'])}}
  result.admin={execution_identity:{flow_run_id:uuid(e.flow_run_id),deployment_id:uuid(e.deployment_id),pipeline_run_id:nullable(e.pipeline_run_id,v=>text(v,/^[0-9a-f]{32}$/))},inference:{outcome:status(i.outcome,inferenceStatuses),task_run_id:nullable(i.task_run_id,uuid),receipt_id:nullable(i.receipt_id,uuid),issue_time:nullable(i.issue_time,time),withholding},delivery:{outcome:status(d.outcome,deliveryStatuses),receipt_id:nullable(d.receipt_id,uuid),bundle_sha256:nullable(d.bundle_sha256,hash),published_at:nullable(d.published_at,time)}}
  if(result.admin.inference.outcome!==result.current_execution?.inference_outcome||result.admin.delivery.outcome!==result.current_execution?.publication_outcome)throw Error('Conflicting operational outcomes')
 }
 return result
}
