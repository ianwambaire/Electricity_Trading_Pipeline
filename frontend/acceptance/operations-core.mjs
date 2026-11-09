// Operational acceptance only; reuse the application's strict response parser.
import {parseCurrentOperations} from '../src/api/currentOperations.ts';
import {AcceptanceError,requireThat,ORIGIN,HOSTED,READ_API,policy,formatTime} from './core.mjs';

export const CURRENT=['/api/operations/current','/api/pipeline/current','/api/admin/operations/current'];
export const LEGACY_ADMIN=['/api/admin/operations','/api/admin/monitoring/forecast-vintages','/api/admin/monitoring/exogenous-readiness'];
export const OPS_READ_API=new Set([...READ_API,...CURRENT,...LEGACY_ADMIN,'/api/market/chart','/api/anomalies/summary']);
export const OPS_OBSERVED=new Set(['/api/auth/me','/api/operations/summary','/api/forecast/next24',...CURRENT]);
export const roles=new Set(['Admin','Analyst']);
export function operationsPolicy(raw,method,phase='acceptance') {
 const base=policy(raw,method,phase);
 if(base.allow||['APPLICATION_MUTATION_BLOCKED','PATH_REJECTED','UNAPPROVED_ORIGIN'].includes(base.code))return base;
 let u;try{u=new URL(raw);}catch{return base;}
 if(u.protocol!=='https:'||u.username||u.password||u.port)return {allow:false,code:'UNAPPROVED_ORIGIN'};
 if(u.origin===ORIGIN&&['GET','HEAD'].includes(method)&&OPS_READ_API.has(u.pathname)&&!READ_API.has(u.pathname)){
  if(u.pathname==='/api/market/chart'){
   if(!['','?series=load_wind'].includes(u.search))return {allow:false,code:'API_QUERY_REJECTED'};
  }else if(u.search)return {allow:false,code:'API_QUERY_REJECTED'};
  return {allow:true,code:'READ_API'};
 }
 if(u.origin===ORIGIN&&method==='GET'&&u.pathname==='/favicon.svg'&&!u.search)return {allow:true,code:'APP_ASSET'};
 // Owner-only federated login, never inspect form bodies, auth queries or responses.
 if(phase==='login'){
  if(u.origin===HOSTED&&method==='GET'&&u.pathname==='/oauth2/idpresponse')return {allow:true,code:'OWNER_AUTH'};
  if(u.origin==='https://accounts.google.com'&&['GET','POST'].includes(method)){
   const p=u.pathname;
   if(/(?:signup|recover|passwordchange|manageaccount|settings|enroll)/i.test(p))return {allow:false,code:'UNAPPROVED_RESOURCE'};
   if(/^\/(?:v[0-9]+\/)?signin(?:\/|$)/.test(p)||/^\/_\/signin\//.test(p)||['/ServiceLogin','/AccountChooser','/o/oauth2/auth','/o/oauth2/v2/auth','/o/oauth2/approval','/o/oauth2/v2/approval'].includes(p))return {allow:true,code:'OWNER_AUTH'};
  }
  if(method==='GET'&&((u.origin==='https://www.gstatic.com'&&/^\/(?:_\/mss\/boq-identity|images|identity)\//.test(u.pathname))
   ||(u.origin==='https://ssl.gstatic.com'&&/^\/(?:accounts|ui|images)\//.test(u.pathname))
   ||(u.origin==='https://fonts.gstatic.com'&&/^\/s\/.+\.woff2$/.test(u.pathname))
   ||(u.origin==='https://lh3.googleusercontent.com'&&/^\/a(?:-|\/)/.test(u.pathname))))return {allow:true,code:'OWNER_AUTH_ASSET'};
 }
 return base;
}
export function operationsId(raw){try{const u=new URL(raw);return u.origin===ORIGIN&&OPS_READ_API.has(u.pathname)?u.pathname:'REDACTED_RESOURCE';}catch{return 'REDACTED_RESOURCE';}}
export function operationalResponse(status,headers,body,admin=false){
 requireThat(status===200,'CURRENT_RESPONSE_INVALID');
 requireThat(headers.cacheControl?.split(',').some(x=>x.trim().toLowerCase()==='no-store'),'API_NO_STORE_MISSING');
 try{return parseCurrentOperations(body,admin);}catch{throw new AcceptanceError('CURRENT_RESPONSE_INVALID');}
}
export function effectiveStatus(record,now){return record.status==='VALID'&&now>=Date.parse(record.fresh_until)?'STALE':record.status;}
export function currentDomCheck(record,dom,role,now){
 requireThat(roles.has(role)&&dom.role===role,'ROLE_UI_UNVERIFIED');
 requireThat(!dom.sensitiveVisible,'SENSITIVE_UI_DETECTED');
 requireThat(!dom.documentOverflow&&dom.panelFits,'RESPONSIVE_OPERATIONS_CLIPPED');
 const status=effectiveStatus(record,now);
 requireThat(dom.status===`Operational evidence: ${status}`,'OPERATIONS_UI_DISAGREEMENT');
 if(status==='VALID'){
  const e=record.current_execution;
  const expected={'Scheduled (UTC)':formatTime(e.scheduled_at),'Started (UTC)':e.started_at?formatTime(e.started_at):'Not provided','Completed (UTC)':e.completed_at?formatTime(e.completed_at):'Not provided','Execution':e.execution_outcome,'Inference':e.inference_outcome,'Automatic delivery':e.publication_outcome};
  requireThat(JSON.stringify(dom.facts)===JSON.stringify(expected),'UI_PROVENANCE_MISMATCH');

 }else requireThat(Object.keys(dom.facts).length===0&&dom.unavailable,'STALE_EXECUTION_VISIBLE');
 if(record.observed_at)requireThat(dom.note===`Evidence observed ${formatTime(record.observed_at)}. Operational freshness cutoff ${record.fresh_until?formatTime(record.fresh_until):'Not provided'}.`,'UI_PROVENANCE_MISMATCH');
 return {status,evidence:record.evidence_id,observedAt:record.observed_at,freshUntil:record.fresh_until,execution:status==='VALID'?record.current_execution.execution_outcome:null,inference:status==='VALID'?record.current_execution.inference_outcome:null,delivery:status==='VALID'?record.current_execution.publication_outcome:null};
}
export function matchingPublic(a,b){return JSON.stringify(a)===JSON.stringify(b);}
export function adminDomCheck(publicRecord,adminRecord,dom,now){
 requireThat(dom.role==='Admin','ROLE_UI_UNVERIFIED');
 requireThat(!dom.sensitiveVisible,'SENSITIVE_UI_DETECTED');
 requireThat(!dom.documentOverflow&&dom.panelFits,'RESPONSIVE_OPERATIONS_CLIPPED');
 requireThat(effectiveStatus(publicRecord,now)===effectiveStatus(adminRecord,now),'OPERATIONS_DISAGREEMENT');
 const {admin,...publicPart}=adminRecord;
 requireThat(matchingPublic(publicRecord,publicPart),'OPERATIONAL_VERSION_CHANGED');
 if(effectiveStatus(publicRecord,now)==='VALID'){
  requireThat(!!admin,'ADMIN_CURRENT_UNVERIFIED');
  const expected={'Prefect execution':admin.execution_identity.flow_run_id,'Internal execution':admin.execution_identity.pipeline_run_id??'Not recorded','Receipt':admin.inference.receipt_id??'Not recorded','Withholding category':admin.inference.withholding?.reason??'Not recorded','Failed prerequisite':admin.inference.withholding?.gate??'Not recorded','Exact publication time':admin.delivery.published_at?formatTime(admin.delivery.published_at):'Not provided'};
  requireThat(JSON.stringify(dom.facts)===JSON.stringify(expected),'UI_PROVENANCE_MISMATCH');
 }else requireThat(Object.keys(dom.facts).length===0&&dom.unavailable,'STALE_EXECUTION_VISIBLE');
 return true;
}
