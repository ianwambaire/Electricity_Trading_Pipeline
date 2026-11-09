// Fixed reporting only; approved request policy and one-shot guard are unchanged.
import{operationsPolicy}from'../operations-core.mjs';import{ORIGIN,MODULE,TARGET}from'./core.mjs';import{HOSTED}from'../core.mjs';
const CODES=new Set(['UNAPPROVED_RESOURCE','UNAPPROVED_ORIGIN','PATH_REJECTED','APPLICATION_MUTATION_BLOCKED','UNAPPROVED_API','UNBOUNDED_HISTORY_BLOCKED','API_QUERY_REJECTED','UNAPPROVED_PAGE']);
export function resourceId(raw){
 try{const u=new URL(raw);
  if(u.origin===ORIGIN){if(raw===MODULE)return'BOUND_MODULE';if(u.pathname==='/pipeline')return'STAGING_PAGE';if(u.pathname==='/api/admin/operations/current')return'ADMIN_CURRENT';if(u.pathname==='/api/auth/me')return'SERVER_IDENTITY';if(u.pathname.startsWith('/api/'))return'OTHER_STAGING_API';if(u.pathname.startsWith('/assets/')||u.pathname.startsWith('/fonts/'))return'STAGING_ASSET';return'OTHER_STAGING_RESOURCE';}
  if(u.origin===HOSTED)return'COGNITO_RESOURCE';
  if(u.origin==='https://accounts.google.com')return'GOOGLE_AUTH_RESOURCE';
  if(['https://www.gstatic.com','https://ssl.gstatic.com','https://fonts.gstatic.com','https://lh3.googleusercontent.com'].includes(u.origin))return'GOOGLE_ASSET';
 }catch{}return'REDACTED_RESOURCE';
}
export function createRequestGuard({probe,phase,onFailure,policy=operationsPolicy}){
 let events=0;
 return async route=>{
  let step='REQUEST_COUNT',id='REDACTED_RESOURCE',policyCode='NOT_APPLICABLE';
  try{
   if(++events>500)throw Error();
   step='REQUEST_POLICY';const request=route.request();id=resourceId(request.url());
   const decision=policy(request.url(),request.method(),phase());
   if(!decision.allow){policyCode=CODES.has(decision.code)?decision.code:'UNVERIFIED_POLICY_CODE';throw Error();}
   step='ONE_SHOT_GUARD';probe.request(request);
   step='REQUEST_CONTINUE';await route.continue();
  }catch{
   onFailure({step,resourceId:id,policyCode});
   await route.abort('blockedbyclient').catch(()=>{});
  }
 };
}
