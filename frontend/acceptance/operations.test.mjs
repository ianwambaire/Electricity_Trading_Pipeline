// Offline only. No browser, auth, SDK, network or production data.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {operationsPolicy,CURRENT,operationalResponse,currentDomCheck,adminDomCheck,effectiveStatus,operationsId} from './operations-core.mjs';
import {operationalReport} from './operations.mjs';
import {createMonitor} from './browser.mjs';
import {ORIGIN,HOSTED,formatTime} from './core.mjs';
const now=Date.parse('2030-01-01T08:00:00Z');
function fixture(status='VALID'){
 return {status,evidence_id:status==='MISSING'?null:'a'.repeat(64),observed_at:status==='MISSING'?null:'2030-01-01T07:50:00Z',scheduled_at:status==='MISSING'?null:'2030-01-01T07:45:00Z',fresh_until:status==='MISSING'?null:'2030-01-01T09:15:00Z',current_execution:status==='VALID'?{scheduled_at:'2030-01-01T07:45:00Z',started_at:'2030-01-01T07:45:01Z',completed_at:'2030-01-01T07:47:01Z',execution_outcome:'COMPLETED',inference_outcome:'WITHHELD',publication_outcome:'SKIPPED_WITHHELD',source:'PREFECT_AND_PERSISTED_PIPELINE'}:null,forecast_eligibility:'NOT_ASSESSED'};
}
function dom(r,role='Admin'){
 const e=r.current_execution;
 return {role,status:`Operational evidence: ${r.status}`,facts:e?{'Scheduled (UTC)':formatTime(e.scheduled_at),'Started (UTC)':formatTime(e.started_at),'Completed (UTC)':formatTime(e.completed_at),'Execution':e.execution_outcome,'Inference':e.inference_outcome,'Automatic delivery':e.publication_outcome}:{},note:r.observed_at?`Evidence observed ${formatTime(r.observed_at)}. Operational freshness cutoff ${formatTime(r.fresh_until)}.`:undefined,unavailable:!e,sensitiveVisible:false,documentOverflow:false,panelFits:true};
}
for(const role of ['Admin','Analyst'])for(const status of ['VALID','STALE','MISSING','INVALID'])test(`${role} renders ${status} honestly`,()=>{assert.equal(currentDomCheck(fixture(status),dom(fixture(status),role),role,now).status,status);});
for(const path of CURRENT)test(`fixed read-only ${path}`,()=>{
 assert.equal(operationsPolicy(ORIGIN+path,'GET').allow,true);
 for(const method of ['POST','PUT','PATCH','DELETE'])assert.equal(operationsPolicy(ORIGIN+path,method,'login').allow,false);
 assert.equal(operationsPolicy(ORIGIN+path+'?private=secret','GET').allow,false);
});
for(const path of ['/api/forecast/one-hour','/api/forecast/one-hour?limit=999&offset=0','/api/forecast/next24?token=x','/api/forecast/context','/api/operations/../account','/api/%2e%2e/operations/current','/api/account/mfa/setup'])test(`existing restrictions ${path}`,()=>assert.equal(operationsPolicy(ORIGIN+path,'GET').allow,false));
for(const path of ['/o/oauth2/v2/auth','/v3/signin/identifier','/_/signin/data/batchexecute'])test(`Google owner login ${path} only during login`,()=>{
 assert.equal(operationsPolicy('https://accounts.google.com'+path,'GET','login').allow,true);
 assert.equal(operationsPolicy('https://accounts.google.com'+path,'POST','login').allow,true);
 assert.equal(operationsPolicy('https://accounts.google.com'+path,'POST','acceptance').allow,false);
});
for(const path of ['/signup','/signin/recovery','/signin/enroll','/settings','/signin/passwordchange'])test(`Google account mutations blocked ${path}`,()=>assert.equal(operationsPolicy('https://accounts.google.com'+path,'POST','login').allow,false));
test('federated callback fixed Cognito host only',()=>{
 assert.equal(operationsPolicy(HOSTED+'/oauth2/idpresponse?code=PRIVATE','GET','login').allow,true);
 assert.equal(operationsPolicy('https://evil.invalid/oauth2/idpresponse','GET','login').allow,false);
 assert.equal(operationsId(HOSTED+'/oauth2/idpresponse?code=PRIVATE'),'REDACTED_RESOURCE');
});
test('favicon is actual deployed public asset, no arbitrary pages',()=>{assert.equal(operationsPolicy(ORIGIN+'/favicon.svg','GET').allow,true);assert.equal(operationsPolicy(ORIGIN+'/random.svg','GET').allow,false);});
test('public projection refuses private fields',()=>{assert.throws(()=>operationalResponse(200,{cacheControl:'no-store'},{...fixture(),admin:{}}),e=>e.code==='CURRENT_RESPONSE_INVALID');});
test('no-store required',()=>assert.throws(()=>operationalResponse(200,{cacheControl:'public'},fixture()),e=>e.code==='API_NO_STORE_MISSING'));
test('stale evidence cannot keep current execution',()=>{const r=fixture();const d=dom(r);assert.equal(effectiveStatus(r,now+7200000),'STALE');assert.throws(()=>currentDomCheck(r,d,'Admin',now+7200000));});
for(const field of ['sensitiveVisible','documentOverflow'])test(`rejects ${field}`,()=>{const r=fixture(),d=dom(r);d[field]=true;assert.throws(()=>currentDomCheck(r,d,'Admin',now));});
test('conflicting public/admin publication rejected',()=>{assert.throws(()=>adminDomCheck(fixture(),{...fixture(),evidence_id:'b'.repeat(64)},dom(fixture()),now),e=>e.code==='OPERATIONAL_VERSION_CHANGED');});
function surface(){const handlers={};return {handlers,page:{on:(n,f)=>{handlers[n]=f;}},context:{route:async()=>{},routeWebSocket:async()=>{},on:()=>{}}};}
function response(p,value){const bytes=Buffer.from(JSON.stringify(value));return {url:()=>ORIGIN+p,status:()=>200,headerValue:async n=>n==='content-length'?String(bytes.length):n==='cache-control'?'no-store':null,body:async()=>bytes};}
for(const role of ['Admin','Analyst'])test(`server verifies ${role}, drops identity fields`,async()=>{
 const s=surface(),m=createMonitor({operations:true,expectedRole:role});await m.install(s.context,s.page);
 s.handlers.response(response('/api/auth/me',{role,email:'DO_NOT_RETAIN',token:'DO_NOT_RETAIN'}));await m.waitRequired(['/api/auth/me']);assert.deepEqual(m.records.get('/api/auth/me').body,{role});
});
test('wrong server role fails closed',async()=>{const s=surface(),m=createMonitor({operations:true,expectedRole:'Analyst'});await m.install(s.context,s.page);s.handlers.response(response('/api/auth/me',{role:'Admin'}));await assert.rejects(m.waitRequired(['/api/auth/me']),e=>e.code==='ROLE_SESSION_REQUIRED');});
test('monitor validates actual public current response',async()=>{const s=surface(),m=createMonitor({operations:true});await m.install(s.context,s.page);s.handlers.response(response(CURRENT[0],fixture()));await m.waitRequired([CURRENT[0]]);assert.equal(m.records.get(CURRENT[0]).body.status,'VALID');});
test('authentication response bodies never read',async()=>{
 const s=surface(),m=createMonitor({operations:true});await m.install(s.context,s.page);
 s.handlers.response({url:()=>HOSTED+'/oauth2/token',status:()=>200,body:()=>assert.fail('secret read')});assert.equal(m.records.size,0);
});
test('safe report drops arbitrary strings and private IDs',()=>{
 const r=operationalReport({role:'Admin',status:'PARTIAL',session:'SERVER_VERIFIED_ADMIN',phase:'COMPLETE',startedAt:'2030-01-01T08:00:00Z',finishedAt:'2030-01-01T08:01:00Z',failure:null,operations:[{viewport:'desktop',page:'overview',status:'VALID',evidence:'a'.repeat(64),observedAt:'2030-01-01T07:50:00Z',freshUntil:'2030-01-01T09:15:00Z',ui:'PASS',admin:'NOT_APPLICABLE',private:'DO_NOT_RETAIN'}],screenshots:[],diagnostics:{},setup:null});
 assert.equal(JSON.stringify(r).includes('DO_NOT_RETAIN'),false);assert.equal(r.analystAuthenticated403,'NOT_OBSERVED');
});
test('browser code has no token replay or persistent session primitives',async()=>{
 const text=await fs.readFile(new URL('./operations.mjs',import.meta.url),'utf8');
 for(const call of ['storageState(','.cookies(','.allHeaders(','.headers(','.postData(','.localStorage','.sessionStorage'])assert.equal(text.includes(call),false);
 assert.match(text,/credentials:'omit'/);assert.match(text,/redirect:'error'/);
});

import os from 'node:os';
import path from 'node:path';
import {accept} from './run.mjs';
for(const role of ['Admin','Analyst'])test(`isolated ${role} lifecycle uses one fresh context and closes it`,async t=>{
 const folder=await fs.mkdtemp(path.join(os.tmpdir(),'pf-role-fixture-'));t.after(()=>fs.rm(folder,{recursive:true,force:true}));
 const env=process.env;process.env={PATH:'/usr/bin:/bin'};
 const descriptors=[process.stdin,process.stdout].map(s=>Object.getOwnPropertyDescriptor(s,'isTTY'));
 for(const s of [process.stdin,process.stdout])Object.defineProperty(s,'isTTY',{value:true,configurable:true});
 t.after(()=>{process.env=env;for(const [i,s] of [process.stdin,process.stdout].entries())descriptors[i]?Object.defineProperty(s,'isTTY',descriptors[i]):delete s.isTTY;});
 const s=surface();let launches=0,contexts=0,closed=0;
 s.page.url=()=>ORIGIN+'/forecasting';s.page.goto=async()=>{s.handlers.response(response('/api/auth/me',{role}));return {status:()=>200};};
 Object.assign(s.context,{newPage:async()=>s.page,setDefaultTimeout(){},setDefaultNavigationTimeout(){}});
 const browser={on(){},newContext:async config=>{contexts++;assert.equal(Object.hasOwn(config,'storageState'),false);return s.context;},close:async()=>{closed++;}};
 const value=await accept({operations:true,role,tools:{library:'/fixture/playwright.mjs',executable:'/fixture/chrome'},evidence:async()=>folder,
  load:async()=>({chromium:{launch:async()=>{launches++;return browser;}}}),prompt:async(signal,expected)=>assert.equal(expected,role),
  checks:async(page,monitor,{progress,role:expected})=>{
   assert.equal(expected,role);
   for(const viewport of ['desktop','mobile-responsive'])for(const page of ['overview','pipeline'])progress.operations.push({viewport,page,status:'MISSING',evidence:null,observedAt:null,freshUntil:null,ui:'PASS',admin:'NOT_APPLICABLE'});
   return {operations:progress.operations};
  }});
 assert.equal(value.report.status,'PARTIAL');assert.equal(value.report.session,'SERVER_VERIFIED_'+role.toUpperCase());assert.equal(launches,1);assert.equal(contexts,1);assert.equal(closed,1);
 assert.equal(JSON.stringify(value.report).includes('DO_NOT_RETAIN'),false);
});
for(const field of ['phase','session','status','failure'])test(`sanitized report rejects arbitrary ${field}`,()=>{
 const r={role:'Admin',status:'BLOCKED',session:'UNVERIFIED',phase:'BROWSER_LAUNCH',startedAt:'2030-01-01T08:00:00Z',finishedAt:'2030-01-01T08:00:01Z',failure:null,operations:[],screenshots:[],diagnostics:{},setup:null};r[field]='SECRET';assert.throws(()=>operationalReport(r));
});
