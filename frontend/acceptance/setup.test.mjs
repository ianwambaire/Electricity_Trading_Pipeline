// Offline setup failures only. All browser objects are fakes; no staging calls.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {AcceptanceError,ORIGIN,HOSTED,START,VIEWPORTS,policy} from './core.mjs';
import {accept} from './run.mjs';
import {createMonitor} from './browser.mjs';
import {createSetupDiagnostic,classifySetupError,resourceClass,networkCode,sanitizeSetup} from './setup-diagnostics.mjs';

function exception(name='Error',message='UNTRUSTED_PRIVATE_TEXT https://private.invalid/?code=SECRET') {
  return Object.assign(new Error(message),{name});
}
async function runFixture(t,{failStep,thrown=exception(),http=200,target=START,gotoHook,role='Analyst'}={}) {
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'powerflow-setup-fixture-'));
  t.after(()=>fs.rm(folder,{recursive:true,force:true}));
  const env=process.env;process.env={PATH:'/usr/bin:/bin'};
  const io=[process.stdin,process.stdout],descriptors=io.map(s=>Object.getOwnPropertyDescriptor(s,'isTTY'));
  for(const s of io)Object.defineProperty(s,'isTTY',{value:true,configurable:true});
  t.after(()=>{process.env=env;io.forEach((s,i)=>descriptors[i]?Object.defineProperty(s,'isTTY',descriptors[i]):delete s.isTTY);});
  const events={},calls=[],frame={};let routeHandler;
  const hit=step=>{calls.push(step);if(failStep===step)throw thrown;};
  const page={on:(name,fn)=>{events[name]=fn;},mainFrame:()=>frame,url:()=>target,
    goto:async()=>{hit('INITIAL_NAVIGATION');if(gotoHook)await gotoHook({page,events,route:routeHandler,frame});return {status:()=>http};}};
  const context={setDefaultTimeout:()=>hit('CONFIGURE_TIMEOUTS'),setDefaultNavigationTimeout:()=>{},
    newPage:async()=>{hit('CREATE_PAGE');return page;},
    route:async(p,fn)=>{hit('INSTALL_REQUEST_GUARD');routeHandler=fn;},routeWebSocket:async()=>hit('INSTALL_WEBSOCKET_GUARD'),
    on:()=>hit('INSTALL_EVENT_MONITOR')};
  let launches=0,closes=0;
  const browser={on:()=>hit('INSTALL_BROWSER_MONITOR'),newContext:async()=>{hit('CREATE_CONTEXT');return context;},close:async()=>{closes++;events.close?.();}};
  const load=async()=>{hit('LOAD_PLAYWRIGHT');return {chromium:{launch:async()=>{launches++;hit('LAUNCH_BROWSER');return browser;}}};};
  const result=await accept({tools:{library:'/fixture/unused.mjs',executable:'/fixture/not-a-browser'},load,evidence:async()=>folder,
    prompt:async()=>{
      hit('OWNER_SIGN_IN');
      const raw=Buffer.from(JSON.stringify({role}));
      events.response({url:()=>ORIGIN+'/api/auth/me',status:()=>200,
        headerValue:async key=>key==='content-length'?String(raw.length):key==='cache-control'?'no-store':null,body:async()=>raw});
    },
    checks:async()=>({results:VIEWPORTS.map(viewport=>({state:'WITHHELD',predictions:0,liveRendering:'NOT_OBSERVED',operations:'EXPIRED',issue:null,expiry:null,
      checkedAt:new Date().toISOString(),viewport,crossLayer:'PASS'})),operations:VIEWPORTS.map(v=>({viewport:v.name,status:'EXPIRED',ui:'PASS',analystRestriction:'OBSERVED'})),screenshots:[]})});
  const persisted=await fs.readFile(path.join(folder,'assessment.json'),'utf8');
  for(const forbidden of ['UNTRUSTED_PRIVATE_TEXT','SECRET','private.invalid','stack','authorization'])assert.equal(persisted.includes(forbidden),false);
  assert.equal(launches,failStep==='LOAD_PLAYWRIGHT'?0:1);
  assert.equal(closes,['LOAD_PLAYWRIGHT','LAUNCH_BROWSER'].includes(failStep)?0:1);
  return {...result,calls};
}
for(const [step,last,category] of [
  ['LOAD_PLAYWRIGHT',null,'PLAYWRIGHT_IMPORT_FAILURE'],
  ['LAUNCH_BROWSER','LOAD_PLAYWRIGHT','EXECUTABLE_LAUNCH_FAILURE'],
  ['INSTALL_BROWSER_MONITOR','LAUNCH_BROWSER','EVENT_MONITORING_FAILURE'],
  ['CREATE_CONTEXT','INSTALL_BROWSER_MONITOR','CONTEXT_CREATION_FAILURE'],
  ['CONFIGURE_TIMEOUTS','CREATE_CONTEXT','BROWSER_CONFIGURATION_FAILURE'],
  ['CREATE_PAGE','CONFIGURE_TIMEOUTS','PAGE_CREATION_FAILURE'],
  ['INSTALL_REQUEST_GUARD','CREATE_PAGE','REQUEST_INTERCEPTION_FAILURE'],
  ['INSTALL_WEBSOCKET_GUARD','INSTALL_REQUEST_GUARD','REQUEST_INTERCEPTION_FAILURE'],
  ['INSTALL_EVENT_MONITOR','INSTALL_WEBSOCKET_GUARD','EVENT_MONITORING_FAILURE'],
  ['INITIAL_NAVIGATION','INSTALL_EVENT_MONITOR','UNEXPECTED_PLAYWRIGHT_EXCEPTION'],
  ['OWNER_SIGN_IN','INITIAL_NAVIGATION','UNEXPECTED_PLAYWRIGHT_EXCEPTION'],
])test(`retains exact failing setup operation ${step}`,async t=>{
  const {report,calls}=await runFixture(t,{failStep:step});
  assert.equal(report.status,'BLOCKED');assert.equal(report.setup.step,step);
  assert.equal(report.setup.lastCompleted,last);assert.equal(report.setup.category,category);
  assert.equal(report.failure,category);assert.equal(calls.filter(x=>x===step).length,1);
});
test('navigation timeout retains initial operation and last completed monitor',async t=>{
  const {report}=await runFixture(t,{failStep:'INITIAL_NAVIGATION',thrown:exception('TimeoutError')});
  assert.equal(report.failure,'NAVIGATION_TIMEOUT');assert.equal(report.setup.lastCompleted,'INSTALL_EVENT_MONITOR');
  assert.equal(report.setup.resource,'STAGING_FORECAST');
});
for(const [token,category] of [
  ['ERR_NAME_NOT_RESOLVED','NETWORK_DNS_FAILURE'],['ERR_DNS_TIMED_OUT','NETWORK_DNS_FAILURE'],
  ['ERR_CONNECTION_TIMED_OUT','NETWORK_CONNECTION_FAILURE'],['ERR_CONNECTION_REFUSED','NETWORK_CONNECTION_FAILURE'],
  ['ERR_CONNECTION_RESET','NETWORK_CONNECTION_FAILURE'],['ERR_INTERNET_DISCONNECTED','NETWORK_CONNECTION_FAILURE'],
  ['ERR_CERT_AUTHORITY_INVALID','TLS_CERTIFICATE_FAILURE'],['ERR_CERT_DATE_INVALID','TLS_CERTIFICATE_FAILURE'],
  ['ERR_CERT_COMMON_NAME_INVALID','TLS_CERTIFICATE_FAILURE'],['ERR_SSL_PROTOCOL_ERROR','TLS_CERTIFICATE_FAILURE'],
  ['ERR_TOO_MANY_REDIRECTS','UNEXPECTED_REDIRECT'],
])test(`sanitizes fixed Chromium transport token ${token}`,async t=>{
  const {report}=await runFixture(t,{failStep:'INITIAL_NAVIGATION',thrown:exception('Error',`page.goto: net::${token} at https://private.invalid/?code=SECRET`)});
  assert.equal(report.setup.category,category);assert.equal(report.setup.networkCode,token);
});
for(const name of ['TargetClosedError','Error'])test(`recognizes browser/page closure ${name}`,async t=>{
  const {report}=await runFixture(t,{failStep:'INITIAL_NAVIGATION',thrown:exception(name,'Target page, context or browser has been closed PRIVATE')});
  assert.equal(report.failure,'BROWSER_OR_PAGE_CLOSED');
});
test('records closure event but ignores deliberate cleanup closure',async t=>{
  const {report}=await runFixture(t,{gotoHook:async({events})=>{events.close();throw exception();}});
  assert.equal(report.setup.category,'BROWSER_OR_PAGE_CLOSED');assert.equal(report.setup.closed,true);
  const d=createSetupDiagnostic();d.cleanup();d.closed();assert.equal(d.snapshot().closed,false);
});
test('HTTP 503 on initial staging document is not a forecast-withheld result',async t=>{
  const {report}=await runFixture(t,{http:503});
  assert.equal(report.failure,'STAGING_HTTP_FAILURE');assert.equal(report.setup.httpStatus,503);
  assert.equal(report.setup.step,'INITIAL_NAVIGATION');
});
test('unexpected final navigation location is identified without retaining URL',async t=>{
  const {report}=await runFixture(t,{target:'https://private.invalid/unknown?token=SECRET'});
  assert.equal(report.failure,'UNEXPECTED_REDIRECT');assert.equal(report.setup.resource,'UNKNOWN');
});
test('approved Cognito redirect uses unchanged reviewed origin, without auth payload capture',async t=>{
  const {report}=await runFixture(t,{target:HOSTED+'/login?client_id=public&state=PRIVATE_QUERY'});
  assert.equal(report.status,'PARTIAL');assert.equal(report.setup.category,null);
  assert.equal(JSON.stringify(report).includes('PRIVATE_QUERY'),false);
});
test('request policy rejection survives a later navigation timeout',async t=>{
  const {report}=await runFixture(t,{gotoHook:async({route})=>{
    const raw=ORIGIN+'/assets/app.js?private=SECRET';
    await route({request:()=>({url:()=>raw,method:()=> 'GET',redirectedFrom:()=>null}),abort:async()=>{},continue:async()=>assert.fail('unapproved request continued')});
    throw exception('TimeoutError');
  }});
  assert.equal(report.failure,'UNAPPROVED_PAGE');assert.equal(report.setup.category,'REQUEST_POLICY_REJECTED');
  assert.equal(report.setup.policy,'UNAPPROVED_PAGE');assert.equal(report.setup.resource,'STAGING_ASSET');
});
test('blocked external redirect is distinct from a transport problem',async t=>{
  const {report}=await runFixture(t,{gotoHook:async({route})=>{
    await route({request:()=>({url:()=> 'https://private.invalid/?code=SECRET',method:()=> 'GET',redirectedFrom:()=>({})}),abort:async()=>{},continue:async()=>assert.fail('redirect continued')});
    throw exception('Error','page.goto: net::ERR_FAILED PRIVATE');
  }});
  assert.equal(report.setup.category,'REQUEST_POLICY_REJECTED');assert.equal(report.setup.redirected,true);
  assert.equal(report.setup.resource,'UNKNOWN');
});
test('dynamic interception failure is retained rather than its eventual timeout',async t=>{
  const {report}=await runFixture(t,{gotoHook:async({route})=>{
    await route({request:()=>({url:()=>START,method:()=> 'GET'}),continue:async()=>{throw exception();}});
    throw exception('TimeoutError');
  }});
  assert.equal(report.failure,'REQUEST_GUARD_FAILED');assert.equal(report.setup.category,'REQUEST_INTERCEPTION_FAILURE');
});
test('event observer exceptions have a fixed sanitized category',async t=>{
  const {report}=await runFixture(t,{gotoHook:async({events})=>{
    events.response({request:()=>{throw exception();},url:()=>HOSTED+'/oauth2/token',status:()=>200});
    throw exception('TimeoutError');
  }});
  assert.equal(report.failure,'BROWSER_EVENT_MONITOR_FAILED');assert.equal(report.setup.category,'EVENT_MONITORING_FAILURE');
});
test('failed server role association retains VERIFY_ANALYST substep',async t=>{
  const {report}=await runFixture(t,{role:'Admin'});
  assert.equal(report.setup.step,'VERIFY_ANALYST');assert.equal(report.failure,'ANALYST_SESSION_REQUIRED');
  assert.equal(report.setup.category,'SETUP_PREREQUISITE_REJECTED');
});
test('monitor records bounded navigation metadata during login without raw bodies',async()=>{
  const d=createSetupDiagnostic(),handlers={},frame={};
  const page={mainFrame:()=>frame,on:(name,fn)=>{handlers[name]=fn;}};
  const c={route:async()=>{},routeWebSocket:async()=>{},on:()=>{}};
  const monitor=createMonitor();await monitor.install(c,page,{setup:d});
  await d.run('INITIAL_NAVIGATION',async()=>{
    const request={isNavigationRequest:()=>true,frame:()=>frame,redirectedFrom:()=>null,url:()=>START+'?code=SECRET',failure:()=>({errorText:'net::ERR_NAME_NOT_RESOLVED PRIVATE'})};
    handlers.requestfailed(request);
    handlers.response({request:()=>request,status:()=>200,url:()=>START+'?code=SECRET',body:()=>assert.fail('HTML body was read')});
    throw exception('TimeoutError');
  }).catch(error=>d.failure(error));
  assert.equal(d.snapshot().networkCode,'ERR_NAME_NOT_RESOLVED');assert.equal(d.snapshot().httpStatus,200);
  assert.equal(JSON.stringify(d.snapshot()).includes('SECRET'),false);
  assert.equal(JSON.stringify(d.snapshot()).includes('PRIVATE'),false);
});
test('unknown errors and code injection are sanitized',()=>{
  const d=createSetupDiagnostic();d.state.step='INITIAL_NAVIGATION';
  const error={name:'SECRET_TYPE',message:'PRIVATE https://private.invalid/?token=SECRET',stack:'PRIVATE_STACK',headers:{Authorization:'PRIVATE'}};
  const out=d.failure(error);
  assert.equal(out.category,'UNEXPECTED_PLAYWRIGHT_EXCEPTION');assert.equal(out.networkCode,null);
  assert.equal(JSON.stringify(out).includes('PRIVATE'),false);assert.equal(JSON.stringify(out).includes('SECRET'),false);
  assert.equal(networkCode('net::ERR_UNAPPROVED_PRIVATE_TOKEN'),null);
  assert.throws(()=>sanitizeSetup({...out,step:'PRIVATE'}));
  assert.throws(()=>sanitizeSetup({...out,networkCode:'PRIVATE'}));
});
test('existing legitimate staging and auth navigation policies remain compatible',async()=>{
  const cfg=await fs.readFile(path.join(path.dirname(new URL(import.meta.url).pathname),'../.env.example'),'utf8');
  const publicDomain=cfg.split('\n').find(line=>line.startsWith('VITE_COGNITO_DOMAIN=')).split('=')[1];
  assert.equal(publicDomain,HOSTED);
  for(const raw of [START,ORIGIN+'/assets/index-ABC123.js',ORIGIN+'/fonts/SourceSans3VF-Upright.woff2',HOSTED+'/login?redirect_uri=https%3A%2F%2Fstaging.powerflowenergy.dev%2Fauth%2Fcallback'])assert.equal(policy(raw,'GET','login').allow,true);
  for(const phase of ['login','acceptance'])assert.equal(policy(ORIGIN+'/api/account/profile','PATCH',phase).allow,false);
  assert.equal(policy('https://unapproved.example/login','GET','login').allow,false);
  assert.equal(resourceClass('https://unapproved.example/login?code=SECRET'),'UNKNOWN');
});
test('successful setup records completion without cleanup creating a closure fault',async t=>{
  const {report,calls}=await runFixture(t);
  assert.equal(report.status,'PARTIAL');assert.equal(report.setup.step,'COMPLETE');
  assert.equal(report.setup.lastCompleted,'COMPLETE');assert.equal(report.setup.category,null);assert.equal(report.setup.closed,false);
  assert.deepEqual(calls,['LOAD_PLAYWRIGHT','LAUNCH_BROWSER','INSTALL_BROWSER_MONITOR','CREATE_CONTEXT','CONFIGURE_TIMEOUTS','CREATE_PAGE',
    'INSTALL_REQUEST_GUARD','INSTALL_WEBSOCKET_GUARD','INSTALL_EVENT_MONITOR','INITIAL_NAVIGATION','OWNER_SIGN_IN']);
});
test('auth document HTTP failure is distinct from staging response failure',async t=>{
  const {report}=await runFixture(t,{http:403,target:HOSTED+'/login?state=SECRET'});
  assert.equal(report.setup.category,'AUTHENTICATION_HTTP_FAILURE');assert.equal(report.setup.resource,'APPROVED_AUTH');
  assert.equal(report.setup.httpStatus,403);
});
test('blocked unapproved action at the known auth origin is not treated as networking',async t=>{
  const {report}=await runFixture(t,{gotoHook:async({route})=>{
    await route({request:()=>({url:()=>HOSTED+'/mfa/register?state=SECRET',method:()=> 'GET',redirectedFrom:()=>({})}),abort:async()=>{},continue:async()=>assert.fail('auth scope broadened')});
    throw exception('TimeoutError');
  }});
  assert.equal(report.setup.category,'REQUEST_POLICY_REJECTED');assert.equal(report.setup.resource,'APPROVED_AUTH_OTHER');
  assert.equal(report.setup.policy,'UNAPPROVED_RESOURCE');
});
