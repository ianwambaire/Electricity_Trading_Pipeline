// Direct invocation of the application's existing, verified ESM API client.
// No fetch replacement, route rewrite, token/header/storage access or role mock.
export const ORIGIN='https://staging.powerflowenergy.dev';
export const TARGET=ORIGIN+'/api/admin/operations/current';
export const MODULE=ORIGIN+'/assets/index-Ch74TTBm.js';
export const EMPTY=()=>({httpStatus:null,adminDataDisclosed:null,result:'FAIL'});
export function need(ok){if(!ok)throw Error('AUTHORIZATION_CHECK_BLOCKED');}
export async function boundedJson(response,limit){
 const size=await response.headerValue('content-length'),encoding=await response.headerValue('content-encoding');
 need(/^\d{1,6}$/.test(size??'')&&Number(size)<=limit&&(!encoding||encoding.toLowerCase()==='identity'));
 need((await response.headerValue('content-type')??'').split(';')[0]==='application/json');
 const raw=await response.body();need(raw.length<=limit&&raw.length===Number(size));return JSON.parse(raw.toString('utf8'));
}
export function createProbe({now=Date.now}={}){
 let phase='IDENTITY',identityAt=null,requests=0,observed=false,result=EMPTY();
 const guard=ok=>{if(!ok){phase='BLOCKED';need(false);}};
 return {
  async identity(response){
   guard(response.url()===ORIGIN+'/api/auth/me'&&response.status()===200&&response.request().method()==='GET');
   const value=await boundedJson(response,8192);guard(value?.role==='Analyst');identityAt=now();
  },
  arm(){guard(phase==='IDENTITY'&&identityAt!==null&&now()>=identityAt&&now()-identityAt<=90000);phase='ARMED';},
  request(request){
   if(request.url()!==TARGET)return;
   guard(phase==='ARMED'&&requests===0&&request.method()==='GET'&&!request.redirectedFrom()&&!request.isNavigationRequest());requests++;phase='SENT';
  },
  async response(response){
   if(response.url()!==TARGET)return false;
   guard(phase==='SENT'&&requests===1&&!observed&&!response.request().redirectedFrom());observed=true;
   const httpStatus=response.status();guard(Number.isInteger(httpStatus));result={httpStatus,adminDataDisclosed:null,result:'FAIL'};
   const body=await boundedJson(response,4096);
   const denied=body!==null&&typeof body==='object'&&!Array.isArray(body)&&Object.keys(body).length===1&&body.detail==='Administrator permission is required.';
   result={httpStatus,adminDataDisclosed:!denied,result:httpStatus===403&&denied?'PASS':'FAIL'};phase='COMPLETE';return true;
  },
  fail(){phase='BLOCKED';},
  report(){return phase==='COMPLETE'?{...result}:EMPTY();},
 };
}
export async function invokeExistingClient(page){
 need(page.url()===ORIGIN+'/pipeline');
 return page.evaluate(async()=>{
  // Identical module URL is served by this release and already evaluated by the
  // page. ESM returns that same singleton session binding; no cache-busting URL.
  const {g:api,h:ApiError}=await import('https://staging.powerflowenergy.dev/assets/index-Ch74TTBm.js');
  if(!api||typeof api.currentAdminOperations!=='function'||typeof ApiError!=='function')return 'BLOCKED';
  try{await api.currentAdminOperations();return 'UNEXPECTED_SUCCESS';}
  catch(error){return error instanceof ApiError&&error.status===403?'DENIED':'BLOCKED';}
 });
}
