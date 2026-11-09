// One-shot same-origin GET retarget. Never inspect request authentication.
export const ORIGIN='https://staging.powerflowenergy.dev';
export const SOURCE=ORIGIN+'/api/operations/current';
export const TARGET=ORIGIN+'/api/admin/operations/current';
export const EMPTY=()=>({httpStatus:null,adminDataDisclosed:null,result:'FAIL'});
export function need(value){if(!value)throw Error('SECURITY_PROBE_BLOCKED');}
export async function boundedJson(response,limit){
  const size=await response.headerValue('content-length'),encoding=await response.headerValue('content-encoding');
  need(/^\d{1,6}$/.test(size??'')&&Number(size)<=limit&&(!encoding||encoding.toLowerCase()==='identity'));
  need((await response.headerValue('content-type')??'').split(';')[0]==='application/json');
  const raw=await response.body();need(raw.length<=limit&&raw.length===Number(size));
  return JSON.parse(raw.toString('utf8'));
}
export function createProbe({now=Date.now}={}){
  let verifiedAt=null,role=null,armed=false,used=false,selected=null,observed=false,failed=false,result=EMPTY();
  return {
    async identity(response){
      need(response.url()===ORIGIN+'/api/auth/me'&&response.status()===200&&response.request().method()==='GET');
      const data=await boundedJson(response,8192);role=data?.role;verifiedAt=now();
      // Only the fixed role is retained, never subject/email/body or headers.
      need(role==='Analyst');
    },
    arm(){need(!used&&!armed&&role==='Analyst'&&verifiedAt!==null&&now()-verifiedAt>=0&&now()-verifiedAt<=90000&&!failed);armed=true;},
    disarm(){armed=false;},
    fail(){failed=true;armed=false;},
    async route(route){
      const request=route.request(),url=request.url();
      if(url===TARGET){failed=true;await route.abort('blockedbyclient');return true;}
      if(url!==SOURCE)return false;
      if(used){failed=true;await route.abort('blockedbyclient');return true;}
      if(!armed)return false;
      need(request.method()==='GET'&&!request.redirectedFrom()&&request.isNavigationRequest()===false&&role==='Analyst'&&now()-verifiedAt<=90000&&!failed);
      used=true;armed=false;selected=request;
      await route.continue({url:TARGET});return true;
    },
    async observe(response){
      if(response.request()!==selected||selected===null)return false;
      need(!observed&&!failed);observed=true;
      const httpStatus=response.status();result={httpStatus:Number.isInteger(httpStatus)?httpStatus:null,adminDataDisclosed:null,result:'FAIL'};
      need(response.url()===TARGET&&!response.request().redirectedFrom());
      const body=await boundedJson(response,4096);
      const denied=body!==null&&typeof body==='object'&&!Array.isArray(body)&&Object.keys(body).length===1&&body.detail==='Administrator permission is required.';
      result={httpStatus,adminDataDisclosed:!denied,result:httpStatus===403&&denied?'PASS':'FAIL'};
      return true;
    },
    report(){return failed||!used||!observed?EMPTY():{...result};},
  };
}
