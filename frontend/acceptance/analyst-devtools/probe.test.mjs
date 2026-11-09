import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {createProbe,USED,PROBE} from './probe.mjs';
import {instrument,sha,BUNDLE_HASH,MANIFEST,BUNDLE} from './build.mjs';
const url='https://staging.powerflowenergy.dev/api/admin/operations/current';
function response(status=403,body={detail:'Administrator permission is required.'},options={}){
  const r=new Response(typeof body==='string'?body:JSON.stringify(body),{status});
  return {status,url:options.url??url,redirected:options.redirected??false,body:r.body,
    get headers(){throw Error('RESPONSE_HEADERS_NOT_NEEDED')}};
}
function fixture({status=403,body,options={},role='Analyst',origin='https://staging.powerflowenergy.dev',pathname='/pipeline',used=null,expired=false,storageFailure=false}={}){
  let calls=0,removed=0;
  const state=new Map(used===null?[]:[[USED,used]]);
  const marker={getItem:k=>{assert.equal(k,USED);if(storageFailure)throw Error();return state.get(k)??null},setItem:(k,v)=>{assert.equal(k,USED);assert.equal(v,'1');state.set(k,v)}};
  let probe;
  probe=createProbe({client:async()=>{calls++;await probe.observe('/admin/operations/current',response(status,body,options));throw Error('PRIVATE_NEVER_PRINTED')},origin:()=>origin,pathname:()=>pathname,role:()=>role,marker,now:()=>100,expiresAt:expired?99:200,schedule:()=>{},remove:()=>removed++});
  return {probe,state,marker,calls:()=>calls,removed:()=>removed};
}
test('403 exact safe body: only the three approved output fields',async()=>{
  const f=fixture();assert.deepEqual(await f.probe.run(),{httpStatus:403,adminDataDisclosed:false,result:'PASS'});
  assert.equal(f.calls(),1);assert.equal(f.state.get(USED),'1');assert.ok(f.removed()>0);
});
test('one-shot duplicate concurrent calls do not duplicate requests',async()=>{
  const f=fixture();const r=await Promise.all([f.probe.run(),f.probe.run()]);assert.equal(f.calls(),1);assert.equal(r[1].result,'FAIL');
});
test('consumed flag prevents reuse after a reload',async()=>{
  const f=fixture({used:'1'});assert.equal((await f.probe.run()).result,'FAIL');assert.equal(f.calls(),0);
});
for(const args of [{role:'Admin'},{role:'Verifying role…'},{pathname:'/'},{origin:'https://other.invalid'},{expired:true},{storageFailure:true}]){
  test('precondition fails closed '+JSON.stringify(args),async()=>{const f=fixture(args);assert.equal((await f.probe.run()).result,'FAIL');assert.equal(f.calls(),0)});
}
for(const [label,args] of [
 ['admin data',{status:200,body:{admin:{execution_identity:'PRIVATE'}}}],
 ['leak in denial',{body:{detail:'Administrator permission is required.',admin:{}}}],
 ['wrong error',{status:401,body:{detail:'Not authenticated'}}],
 ['malformed',{body:'PRIVATE_NOT_JSON'}],
 ['oversized',{body:'x'.repeat(4097)}],
 ['redirected',{options:{redirected:true}}],
 ['unexpected URL',{options:{url:url+'?unexpected=1'}}],
 ['array',{body:[{detail:'Administrator permission is required.'}]}]
])test(label+' never reports PASS or prints payload',async()=>{const f=fixture(args),r=await f.probe.run();assert.equal(r.result,'FAIL');assert.equal(JSON.stringify(r).includes('PRIVATE'),false)});
test('ordinary calls are not inspected',async()=>{const f=fixture();const r={get status(){throw Error('DO_NOT_INSPECT')}};await f.probe.observe('/admin/operations/current',r);await f.probe.observe('/operations/current',r);assert.equal(f.calls(),0)});
test('missing response and client exception fail safely',async()=>{
  const p=createProbe({client:async()=>{throw Error('PRIVATE')},origin:()=> 'https://staging.powerflowenergy.dev',pathname:()=>'/pipeline',role:()=> 'Analyst',marker:{getItem:()=>null,setItem:()=>{}},now:()=>1,expiresAt:2,schedule:()=>{},remove:()=>{}});
  assert.deepEqual(await p.run(),{httpStatus:null,adminDataDisclosed:null,result:'FAIL'});
});
test('duplicate observed responses cannot pass',async()=>{
  let p;p=createProbe({client:async()=>{await p.observe('/admin/operations/current',response());await p.observe('/admin/operations/current',response())},origin:()=> 'https://staging.powerflowenergy.dev',pathname:()=>'/pipeline',role:()=> 'Analyst',marker:{getItem:()=>null,setItem:()=>{}},now:()=>1,expiresAt:2,schedule:()=>{},remove:()=>{}});
  assert.equal((await p.run()).result,'FAIL');
});
const fixtureSource='async function request(path){let response=await fetch(`/api${path}`),assertCurrent=()=>{if(globalThis.sessionChanged)throw Error("Session changed")};if(assertCurrent(),response.status===403)throw Error("Denied");return response.json()}const api={currentAdminOperations:()=>request(`/admin/operations/current`)};';
test('assembled override invokes the existing module client once without auth inspection',async()=>{
  let calls=0;const state=new Map();
  const c={fetch:async path=>{assert.equal(path,'/api/admin/operations/current');calls++;return response()},TextDecoder,setTimeout:()=>0,clearTimeout:()=>{},Date,
    location:{origin:'https://staging.powerflowenergy.dev',pathname:'/pipeline'},document:{querySelector:()=>({textContent:'Analyst'})},sessionStorage:{getItem:k=>state.get(k)??null,setItem:(k,v)=>state.set(k,v)}};
  vm.createContext(c);vm.runInContext(instrument(fixtureSource,Date.now()+10000),c);
  const call=c[PROBE];assert.equal((await call()).result,'PASS');assert.equal(c[PROBE],undefined);assert.equal((await call()).result,'FAIL');assert.equal(calls,1);
});
test('missing, ambiguous, malformed and already instrumented sources are rejected',()=>{
  for(const s of ['const x={};',fixtureSource+'const other={currentAdminOperations:()=>request(`/admin/operations/current`)};','const =',instrument(fixtureSource,200)])assert.throws(()=>instrument(s,300));
});
test('exact V5 bundle and manifest bindings remain intact; full assembled bundle parses',async()=>{
  const raw=await fs.readFile(new URL('../../../deploy/staging/operational-evidence-release-v5/MANIFEST.json',import.meta.url));
  assert.equal(sha(raw),MANIFEST);
  const m=JSON.parse(raw),binding=m.config.files['static'+BUNDLE];
  const root=new URL('../../../',import.meta.url).pathname;
  const source=await fs.readFile(root+'/'+binding.source);
  assert.equal(sha(source),BUNDLE_HASH);const patched=instrument(source.toString('utf8'),Date.now()+10000);
  assert.ok(patched.length>source.length);assert.equal(sha(source),BUNDLE_HASH);
});
test('instrumentation contains no credential readers, logging, direct fetch or persistence of response data',()=>{
  const helper=createProbe.toString().replace(/\/\/[^\n]*/g,'');
  for(const forbidden of ['Authorization','access_token','id_token','refresh_token','localStorage','cookie','console.','fetch(','headers','JSON.stringify'])assert.equal(helper.includes(forbidden),false);
});
test('originating-session assertion is retained before observing the response',async()=>{
  const c={sessionChanged:true,fetch:async()=>response(),TextDecoder,setTimeout:()=>0,clearTimeout:()=>{},Date,
    location:{origin:'https://staging.powerflowenergy.dev',pathname:'/pipeline'},document:{querySelector:()=>({textContent:'Analyst'})},sessionStorage:{getItem:()=>null,setItem:()=>{}}};
  vm.createContext(c);vm.runInContext(instrument(fixtureSource,Date.now()+10000),c);
  assert.deepEqual(JSON.parse(JSON.stringify(await c[PROBE]())),{httpStatus:null,adminDataDisclosed:null,result:'FAIL'});
});
test('stalled response is bounded and cancelled',async()=>{
  let cancelled=false,p;
  const body=new ReadableStream({cancel(){cancelled=true}});
  p=createProbe({client:async()=>{await p.observe('/admin/operations/current',{status:403,url,redirected:false,body})},origin:()=> 'https://staging.powerflowenergy.dev',pathname:()=>'/pipeline',role:()=> 'Analyst',marker:{getItem:()=>null,setItem:()=>{}},now:()=>1,expiresAt:2,schedule:()=>{},remove:()=>{}});
  const r=await p.run();assert.equal(r.result,'FAIL');assert.equal(r.httpStatus,403);assert.equal(cancelled,true);
});
