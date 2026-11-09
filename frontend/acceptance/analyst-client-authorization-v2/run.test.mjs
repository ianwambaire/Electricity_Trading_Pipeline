import{test}from'node:test';import assert from'node:assert/strict';import fs from'node:fs/promises';import vm from'node:vm';import{createHash}from'node:crypto';
import{session,verifyAsset}from'./run.mjs';import{ORIGIN,TARGET,MODULE}from'./core.mjs';
const hash=b=>createHash('sha256').update(b).digest('hex');
function req(url){return{url:()=>url,method:()=> 'GET',redirectedFrom:()=>null,isNavigationRequest:()=>false,get headers(){throw Error('FORBIDDEN')}};}
function response(url,raw,status=200,request=req(url)){return{url:()=>url,status:()=>status,request:()=>request,headerValue:async n=>({'content-length':String(raw.length),'content-type':'application/json','content-encoding':null}[n]),body:async()=>raw};}
function fixture({role='Analyst',badAsset=false,crash=false}={}){
 const html=Buffer.from('approved-html'),js=Buffer.from('approved-module');const calls=[],handlers={};let routeHandler;let emitted=[];
 const page={on:(name,fn)=>{handlers[name]=fn;},url:()=>ORIGIN+'/pipeline',goto:async()=>{
   for(const r of[response(ORIGIN+'/pipeline',html),response(MODULE,badAsset?Buffer.from('tampered'):js),response(ORIGIN+'/api/auth/me',Buffer.from(JSON.stringify({role})))])handlers.response(r);
  },getByRole:()=>({waitFor:async()=>{}}),locator:selector=>({innerText:async()=>role,evaluateAll:async()=>[MODULE]}),
  evaluate:async fn=>{
   class ApiError extends Error{constructor(){super();this.status=403;}}
   const api={currentAdminOperations:async()=>{const r=req(TARGET);let continued=false;await routeHandler({request:()=>r,continue:async(...args)=>{assert.equal(args.length,0);continued=true;calls.push('GET_ADMIN');},abort:async()=>{}});if(!continued)throw Error('BLOCKED');const result=response(TARGET,Buffer.from(JSON.stringify({detail:'Administrator permission is required.'})),403,r);handlers.response(result);throw new ApiError();}};
   const script=new vm.Script('('+fn.toString()+')()',{importModuleDynamically:async url=>{assert.equal(url,MODULE);const m=new vm.SyntheticModule(['g','h'],function(){this.setExport('g',api);this.setExport('h',ApiError)});await m.link(()=>{});await m.evaluate();return m;}});return script.runInThisContext();
  }};
 const context={setDefaultTimeout:()=>{},setDefaultNavigationTimeout:()=>{},newPage:async()=>page,on:()=>{},route:async(p,h)=>{routeHandler=h;},routeWebSocket:async()=>{},unroute:async()=>calls.push('UNROUTE'),close:async()=>calls.push('CONTEXT_CLOSED')};
 const browser={on:()=>{},newContext:async()=>context,close:async()=>calls.push('BROWSER_CLOSED')};
 const args={chromium:{launch:async()=>browser},tool:{executable:'/verified'},bindings:{indexSha256:hash(html),sha256:hash(js)},prompt:async()=>{await new Promise(resolve=>setImmediate(resolve));if(crash){handlers.crash();throw Error('SECRET_PRIVATE_ERROR');}},setTimer:()=>1,clearTimer:()=>{}};
 return{args,calls};
}
test('complete mocked isolated lifecycle, one GET, ordinary continue, close and no saved state',async()=>{const{args,calls}=fixture();const r=await session(args);assert.deepEqual(r,{status:'PASS',stage:'COMPLETE',httpStatus:403,adminDataDisclosed:false,result:'PASS'});assert.deepEqual(calls,['GET_ADMIN','UNROUTE','CONTEXT_CLOSED','BROWSER_CLOSED']);});
for(const options of[{role:'Admin'},{badAsset:true},{crash:true}])test('failed gate prevents request and always closes '+JSON.stringify(options),async()=>{const{args,calls}=fixture(options);const r=await session(args);assert.equal(r.status,'BLOCKED');assert(!calls.includes('GET_ADMIN'));assert.deepEqual(calls,['UNROUTE','CONTEXT_CLOSED','BROWSER_CLOSED']);assert(!JSON.stringify(r).includes('SECRET'));});
test('asset mismatch never grants execution authority',async()=>{const bytes=Buffer.from('wrong');await assert.rejects(verifyAsset(response(MODULE,bytes),{sha256:'a'.repeat(64)}));});
test('runner has no retarget, storage or credential APIs',async()=>{const s=await fs.readFile(new URL('./run.mjs',import.meta.url),'utf8');assert(!/\.headers\(|\.allHeaders\(|\.cookies\(|\.storageState\(|localStorage|sessionStorage|launchPersistentContext|connectOverCDP/.test(s));assert(s.includes('handler=createRequestGuard('));assert(!/route\.continue\(\{/.test(s));});
