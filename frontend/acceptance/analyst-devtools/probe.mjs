// Temporary, client-only instrumentation. No session/header/storage enumeration.
export const PROBE = 'powerflowAnalystAuthorizationCheck';
export const USED = 'powerflow.devtools.analyst-auth-v5.used';
export const TARGET = '/admin/operations/current';
export const ORIGIN = 'https://staging.powerflowenergy.dev';

export function createProbe({client, origin, pathname, role, marker, now, expiresAt, schedule, remove}) {
  let used = false, active = false, observed = false;
  const failure = () => ({httpStatus:null, adminDataDisclosed:null, result:'FAIL'});
  let result = failure();
  schedule(remove, Math.max(0, expiresAt-now()));
  async function observe(path, response) {
    if (!active || path !== '/admin/operations/current') return;
    if (observed) { result=failure(); return; }
    observed=true;
    const status=response.status;
    result={httpStatus:Number.isInteger(status)?status:null,adminDataDisclosed:null,result:'FAIL'};
    // Consume only this probe's response. Never inspect requests or headers.
    // Normal UI calls never enter this branch. The client still handles 403.
    let reader, timer;
    try {
      if (response.url !== 'https://staging.powerflowenergy.dev/api/admin/operations/current' || response.redirected) return;
      reader=response.body.getReader();
      let raw='', bytes=0;
      const decoder=new TextDecoder('utf-8',{fatal:true});
      const read=async()=>{
        for (;;) {
          const part=await reader.read();
          if (part.done) break;
          bytes+=part.value.byteLength;
          if (bytes>4096) throw Error();
          raw+=decoder.decode(part.value,{stream:true});
        }
        raw+=decoder.decode();
        const body=JSON.parse(raw);
        const denied=body!==null && typeof body==='object' && !Array.isArray(body)
          && Object.keys(body).length===1 && body.detail==='Administrator permission is required.';
        result={httpStatus:status,adminDataDisclosed:!denied,result:status===403&&denied?'PASS':'FAIL'};
        raw='';
      };
      await Promise.race([read(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error()),3000);})]);
    } catch { result={httpStatus:result.httpStatus,adminDataDisclosed:null,result:'FAIL'}; }
    finally {
      clearTimeout(timer);
      // Cancellation is intentionally not awaited: a stalled stream must not hang.
      if(reader){void reader.cancel().catch(()=>{});try{reader.releaseLock();}catch{}}
    }
  }
  async function run() {
    if (used) return failure();
    used=true; remove();
    try {
      if (now()>=expiresAt || origin()!=='https://staging.powerflowenergy.dev' || pathname()!=='/pipeline' || role()!=='Analyst') return failure();
      if (marker.getItem('powerflow.devtools.analyst-auth-v5.used')!==null) return failure();
      // A fixed non-secret consumed flag prevents reuse after reload. No other
      // sessionStorage keys or values are accessed. Never remove it automatically.
      marker.setItem('powerflow.devtools.analyst-auth-v5.used','1');
      active=true;
      try { await client(); } catch { /* Existing ApiError is never printed. */ }
      return observed ? {...result} : failure();
    } catch { return failure(); }
    finally { active=false; remove(); }
  }
  return {run, observe};
}
