// Offline fixtures only. No browser, staging, credentials or dependency imports.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {AcceptanceError,ORIGIN,HOSTED,MODEL,VIEWPORTS,LIMITS,policy,safeId,formatTime,forecastEvidence,checkForecast,safeReport} from './core.mjs';
import {verifyTree,hashFile,checkTooling} from './tooling.mjs';
import {createMonitor,saveScreenshots,checkChartValues} from './browser.mjs';
import {accept,launchOptions,CONTEXT,sanitizedFailure} from './run.mjs';

const issue=Date.parse('2030-01-01T05:00:00Z'),now=issue+2*3600_000;
function fixture(state='VALID') {
  const iso=v=>new Date(v).toISOString();
  const rows=Array.from({length:24},(_,i)=>({issue_time:iso(issue),target_time:iso(issue+(i+1)*3600_000),
    horizon_hours:i+1,predicted_price_eur_mwh:i-5+0.123456,model_release:MODEL}));
  const p={status:'VALID',issue_time:iso(issue),expires_at:iso(issue+3*3600_000),completed_at:iso(issue+3600_000)};
  const forecast=state==='WITHHELD'?{status:503,headers:{cacheControl:'no-store'},body:{detail:{code:'FORECAST_WITHHELD'}},checkedAt:now}:
    {status:200,headers:{cacheControl:'no-store'},body:{row_count:24,forecasts:rows,publication:p},checkedAt:now};
  const dom={heading:'Forecast Intelligence',role:'Analyst',viewport:VIEWPORTS[0],historicalSeparated:true,availabilityCount:1,
    availability:state==='VALID'?'Valid published forecast':'WITHHELD',documentOverflow:false,essentialVisible:true,sensitiveVisible:false,
    livePanelCount:state==='VALID'?1:0,chartCount:state==='VALID'?1:0,chartDescriptionCorrect:true,chartValuesVerified:24,
    tableHeadersCorrect:true,tableScrollable:true,tableRows:state==='VALID'?rows.map(row=>[formatTime(row.target_time),String(row.predicted_price_eur_mwh)]):[],
    liveStatistics:state==='VALID',facts:{'Model release':MODEL,'Issue time':formatTime(p.issue_time),
      'Inference completed':formatTime(p.completed_at),'Freshness cutoff':formatTime(p.expires_at),'Target start':formatTime(rows[0].target_time),
      'Target end':formatTime(rows.at(-1).target_time),'Forecast rows':'24','Still future targets':'22'}};
  return {forecast,operations:{status:200,body:{forecast_status:state==='VALID'?'VALID':'EXPIRED'},checkedAt:now},dom,now};
}
function rejects(fn,code) {assert.throws(fn,error=>error instanceof AcceptanceError&&error.code===code);}

for(const method of ['POST','PUT','PATCH','DELETE','OPTIONS']) test(`blocks application ${method}`,()=>{
  for(const p of ['/api/account/password','/api/account/mfa/setup','/api/forecast/next24','/forecasting']) {
    assert.equal(policy(ORIGIN+p,method,'login').allow,false);
  }
});
test('fixed origins, routes, pagination and queries',()=>{
  for(const p of ['/forecasting','/pipeline','/api/forecast/next24','/api/auth/me','/api/forecast/one-hour?limit=500&offset=0'])assert.equal(policy(ORIGIN+p,'GET').allow,true);
  for(const p of ['/api/admin/operations','/api/forecast/one-hour','/api/forecast/one-hour?limit=1000000&offset=0','/api/forecast/next24?token=SECRET','/profile','/logout','/assets/%2e%2e/forecasting'])assert.equal(policy(ORIGIN+p,'GET').allow,false);
  assert.equal(policy('https://evil.invalid/api/forecast/next24','GET').allow,false);
  assert.equal(policy('http://staging.powerflowenergy.dev/forecasting','GET').allow,false);
});
test('Cognito exception is login only, no enrollment or account mutations',()=>{
  assert.equal(policy(HOSTED+'/login?redirect_uri=https%3A%2F%2Fstaging.powerflowenergy.dev%2Fauth%2Fcallback','GET','login').allow,true);
  for(const p of ['/login','/mfa','/oauth2/token'])assert.equal(policy(HOSTED+p,'POST','login').allow,true);
  for(const p of ['/signup','/logout','/forgotPassword','/mfa/register','/settings'])assert.equal(policy(HOSTED+p,'POST','login').allow,false);
  assert.equal(policy(HOSTED+'/oauth2/token','POST','acceptance').allow,false);
  assert.equal(policy('https://accounts.google.com/login','POST','login').allow,false);
});
test('resource identifiers never retain query strings or private hosts',()=>{
  assert.equal(safeId(ORIGIN+'/api/auth/me?SECRET=TOKEN'),'/api/auth/me');
  assert.equal(safeId('https://secret.invalid/?token=PRIVATE'),'REDACTED_RESOURCE');
});
test('24-row genuine-response validation rules',()=>{
  assert.equal(checkForecast(fixture()).liveRendering,'OBSERVED');
  assert.equal(checkForecast(fixture()).predictions,24);
  const f=fixture();f.dom.viewport=VIEWPORTS[1];assert.equal(checkForecast(f).crossLayer,'PASS');
});
test('withheld response never counts as live rendering',()=>{
  const value=checkForecast(fixture('WITHHELD'));
  assert.equal(value.state,'WITHHELD');assert.equal(value.liveRendering,'NOT_OBSERVED');assert.equal(value.predictions,0);
});
test('expired HTTP 200 is interpreted by actual current time',()=>{
  const f=fixture('EXPIRED');f.now=issue+4*3600_000;
  assert.equal(checkForecast(f).state,'EXPIRED');
  const stale=fixture();stale.now=issue+4*3600_000;stale.operations.body.forecast_status='EXPIRED';
  rejects(()=>checkForecast(stale),'STALE_OR_INVENTED_FORECAST_VISIBLE');
});
test('boundary crossing becomes an explicit acceptance gap',()=>{
  const f=fixture();f.now=issue+4*3600_000;
  rejects(()=>checkForecast(f),'FRESHNESS_BOUNDARY_DURING_CHECK');
});
for(const [name,mutate,code] of [
  ['model',f=>f.forecast.body.forecasts[0].model_release='other','FORECAST_ROWS_INVALID'],
  ['time',f=>f.forecast.body.forecasts[0].target_time='2030-01-01T05:15:00Z','FORECAST_ROWS_INVALID'],
  ['finite',f=>f.forecast.body.forecasts[0].predicted_price_eur_mwh=Infinity,'FORECAST_ROWS_INVALID'],
  ['count',f=>f.forecast.body.forecasts.pop(),'FORECAST_RESPONSE_INVALID'],
  ['no-store',f=>f.forecast.headers.cacheControl='public','API_NO_STORE_MISSING'],
  ['provenance',f=>delete f.forecast.body.publication,'PUBLICATION_PROVENANCE_MISSING'],
  ['value',f=>f.dom.tableRows[0][1]='9999','UI_API_VALUE_MISMATCH'],
  ['history',f=>f.dom.historicalSeparated=false,'HISTORICAL_LABEL_MISSING'],
  ['banner',f=>f.dom.availabilityCount=2,'DUPLICATE_FORECAST_STATUS'],
  ['chart',f=>f.dom.chartValuesVerified=23,'CHART_VALUES_UNVERIFIED'],
  ['mobile',f=>f.dom.documentOverflow=true,'RESPONSIVE_CONTENT_CLIPPED'],
  ['table scrolling',f=>f.dom.tableScrollable=false,'CHART_OR_TABLE_CONTRACT'],
  ['role',f=>f.dom.role='Admin','ANALYST_OR_RENDER_UNVERIFIED'],
  ['operations',f=>f.operations.body.forecast_status='EXPIRED','OPERATIONS_DISAGREEMENT'],
  ['sensitive UI',f=>f.dom.sensitiveVisible=true,'SENSITIVE_UI_DETECTED'],
])test(`rejects ${name} mismatch`,()=>{const f=fixture();mutate(f);rejects(()=>checkForecast(f),code);});

function fakeSurface() {
  const handlers={},contextHandlers={};let routeHandler,ws;
  const page={on:(name,fn)=>{handlers[name]=fn;}};
  const context={route:async(pattern,fn)=>{routeHandler=fn;},routeWebSocket:async(pattern,fn)=>{ws=fn;},on:(name,fn)=>{contextHandlers[name]=fn;}};
  return {page,context,handlers,contextHandlers,route:()=>routeHandler,websocket:()=>ws};
}
function response(endpoint,body,status=200,headers={}) {
  const raw=Buffer.from(JSON.stringify(body));
  return {url:()=>ORIGIN+endpoint,status:()=>status,
    headerValue:async name=>Object.hasOwn(headers,name)?headers[name]:name==='content-length'?String(raw.length):name==='cache-control'?'no-store':null,
    body:async()=>raw};
}
async function monitoredResponse(r) {
  const surface=fakeSurface(),fatal=[];
  const monitor=createMonitor({onFatal:code=>fatal.push(code)});await monitor.install(surface.context,surface.page);
  surface.handlers.response(r);
  return {monitor,surface,fatal};
}
test('API observation projects only Analyst role, never identity or token fields',async()=>{
  const {monitor}=await monitoredResponse(response('/api/auth/me',{role:'Analyst',subject:'PRIVATE',email:'PRIVATE',token:'SECRET'}));
  await monitor.waitRequired(['/api/auth/me']);
  assert.deepEqual(monitor.records.get('/api/auth/me').body,{role:'Analyst'});
  assert.equal(JSON.stringify([...monitor.records]).includes('SECRET'),false);
});
test('token and credential responses are never read',async()=>{
  const r={url:()=>HOSTED+'/oauth2/token',status:()=>200,body:()=>{throw Error('SECRET_RESPONSE_READ');}};
  const {monitor}=await monitoredResponse(r);assert.equal(monitor.records.size,0);
});
for(const [name,body,status,headers,expected] of [
  ['Admin',{role:'Admin'},200,{},'ANALYST_SESSION_REQUIRED'],
  ['unbounded',{role:'Analyst'},200,{'content-length':null},'API_BODY_BOUND_UNVERIFIED'],
  ['oversized',{role:'Analyst'},200,{'content-length':'9999999'},'API_BODY_BOUND_UNVERIFIED'],
  ['compressed',{role:'Analyst'},200,{'content-encoding':'gzip'},'API_BODY_ENCODING_UNVERIFIED'],
])test(`response capture fails closed for ${name}`,async()=>{
  const {monitor}=await monitoredResponse(response('/api/auth/me',body,status,headers));
  await assert.rejects(monitor.waitRequired(['/api/auth/me']),error=>error.code===expected);
});
test('503 is an expected status and captured without raw fields',async()=>{
  const {monitor}=await monitoredResponse(response('/api/forecast/next24',{detail:{code:'FORECAST_WITHHELD'},rawSecret:'PRIVATE'},503));
  await monitor.waitRequired(['/api/forecast/next24']);
  assert.equal(monitor.diagnostics.expectedWithheld,1);
  assert.equal(JSON.stringify([...monitor.records]).includes('PRIVATE'),false);
});
test('route guard blocks writes without reading credentials or request bodies',async()=>{
  const s=fakeSurface(),m=createMonitor();await m.install(s.context,s.page);let aborted=0;
  const req={url:()=>ORIGIN+'/api/account/password',method:()=> 'POST',headers:()=>{throw Error('HEADERS_READ');},postData:()=>{throw Error('CREDENTIALS_READ');}};
  await s.route()({request:()=>req,abort:async()=>aborted++,continue:()=>assert.fail('write was allowed')});
  assert.equal(aborted,1);assert.equal(m.diagnostics.blockedMutations,1);
});
test('console and request errors retain counts only',async()=>{
  const s=fakeSurface(),m=createMonitor();await m.install(s.context,s.page);m.acceptance();
  s.handlers.console({type:()=> 'error',text:()=>{throw Error('PRIVATE_CONSOLE_READ');}});
  s.handlers.pageerror({get message(){throw Error('PRIVATE_ERROR_READ');}});
  assert.equal(m.diagnostics.consoleErrors,1);assert.equal(m.diagnostics.pageErrors,1);
});
test('screenshots are refused before authenticated workspace checks',async()=>{
  let images=0;
  await assert.rejects(saveScreenshots({url:()=>HOSTED+'/login'}, {assertSafe(){}},null,VIEWPORTS[0],'VALID',()=>images++));
  assert.equal(images,0);
});
test('all 24 tooltip values use the expected rounding tolerance',async()=>{
  const rows=fixture().forecast.body.forecasts;let at=0;
  const tooltip={locator:selector=>selector.includes('label')?{filter:()=>({waitFor:async()=>{}})}:{innerText:async()=>rows[at].predicted_price_eur_mwh.toLocaleString('en-GB',{maximumFractionDigits:3})}};
  const panel={locator:selector=>selector.includes('line-dots')?{count:async()=>24,nth:i=>({hover:async()=>{at=i;}})}:tooltip};
  assert.equal(await checkChartValues(panel,rows),24);
});
test('launch options use isolated Chrome and no inherited environment or profile',()=>{
  const o=launchOptions({executable:'/fixture/chrome'});
  assert.equal(o.chromiumSandbox,true);assert.equal(o.headless,false);
  assert.equal(Object.hasOwn(o,'userDataDir'),false);assert.equal(Object.hasOwn(o.env,'HOME'),false);
  assert.equal(Object.hasOwn(CONTEXT,'storageState'),false);assert.equal(CONTEXT.ignoreHTTPSErrors,false);
  assert.equal(CONTEXT.serviceWorkers,'block');assert.equal(CONTEXT.acceptDownloads,false);
});
test('raw exception strings never enter reports',()=>{
  assert.equal(sanitizedFailure(Error('PRIVATE_TOKEN_OR_URL')),'BROWSER_STEP_UNVERIFIED');
  assert.equal(sanitizedFailure(new AcceptanceError('SECRET')),'BROWSER_STEP_UNVERIFIED');
});
test('evidence serialization drops unapproved identity/network fields',()=>{
  const report={status:'PARTIAL',phase:'COMPLETE',startedAt:new Date(now).toISOString(),finishedAt:new Date(now).toISOString(),origin:ORIGIN,
    session:'SERVER_VERIFIED_ANALYST',results:[checkForecast(fixture())],operations:[],screenshots:[],diagnostics:{},failure:null,token:'SECRET'};
  const out=safeReport(report);assert.equal(JSON.stringify(out).includes('SECRET'),false);
  out.failure='PRIVATE_SECRET';rejects(()=>safeReport(out),'REPORT_SCHEMA');
});
test('local missing tooling is reported without importing Playwright',async t=>{
  const read=t.mock.method(fs,'readFile',async()=>{throw Object.assign(Error('PRIVATE_PATH'),{code:'ENOENT'});});
  await assert.rejects(checkTooling(),e=>e.code==='LOCAL_TOOLING_MISSING');read.mock.restore();
});
test('hash verification rejects changed files, extra files, unsafe modes and links',async t=>{
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'powerflow-harness-fixture-'));
  t.after(()=>fs.rm(folder,{recursive:true,force:true}));
  const file=path.join(folder,'fixture.js');await fs.writeFile(file,'// offline fixture\n',{mode:0o644});
  const expected={'fixture.js':await hashFile(file)};
  await verifyTree(folder,expected,{});
  await fs.writeFile(file,'// changed fixture\n');await assert.rejects(verifyTree(folder,expected,{}));
  await fs.writeFile(file,'// offline fixture\n');await fs.chmod(file,0o666);await assert.rejects(verifyTree(folder,expected,{}));
  await fs.chmod(file,0o644);await fs.writeFile(path.join(folder,'extra.js'),'x');await assert.rejects(verifyTree(folder,expected,{}));
  await fs.unlink(path.join(folder,'extra.js'));await fs.symlink('/outside-not-read',path.join(folder,'link'));
  await assert.rejects(verifyTree(folder,expected,{}));
});
for(const scenario of ['success','withheld','owner-not-ready','launch-fails','wrong-identity','incomplete'])test(`mock lifecycle ${scenario} never launches a real browser`,async t=>{
  const folder=await fs.mkdtemp(path.join(os.tmpdir(),'powerflow-browser-lifecycle-'));
  t.after(()=>fs.rm(folder,{recursive:true,force:true}));
  const env=process.env;process.env={PATH:'/usr/bin:/bin'};
  const descriptors=[process.stdin,process.stdout].map(s=>Object.getOwnPropertyDescriptor(s,'isTTY'));
  for(const s of [process.stdin,process.stdout])Object.defineProperty(s,'isTTY',{value:true,configurable:true});
  t.after(()=>{
    process.env=env;
    for(const [i,s] of [process.stdin,process.stdout].entries())descriptors[i]?Object.defineProperty(s,'isTTY',descriptors[i]):delete s.isTTY;
  });
  const surface=fakeSurface();let mockLaunches=0,closes=0;
  surface.page.goto=async()=>surface.handlers.response(response('/api/auth/me',{role:scenario==='wrong-identity'?'Admin':'Analyst'}));
  Object.assign(surface.context,{newPage:async()=>surface.page,setDefaultTimeout(){},setDefaultNavigationTimeout(){}});
  const browser={newContext:async options=>{assert.equal(options,CONTEXT);return surface.context;},close:async()=>closes++};
  const load=async()=>({chromium:{launch:async options=>{
    mockLaunches++;assert.equal(options.executablePath,'/fixture/not-real-chrome');
    if(scenario==='launch-fails')throw Error('PRIVATE_LAUNCH_DETAILS');return browser;
  }}});
  const result=await accept({tools:{executable:'/fixture/not-real-chrome',library:'/fixture/not-real-library'},load,
    evidence:async()=>folder,prompt:async()=>{if(scenario==='owner-not-ready')throw new AcceptanceError('OWNER_LOGIN_NOT_CONFIRMED');},
    checks:async()=>({results:scenario==='incomplete'?[]:VIEWPORTS.map(viewport=>{const f=fixture(scenario==='withheld'?'WITHHELD':'VALID');f.dom.viewport=viewport;return checkForecast(f);}),
      operations:scenario==='incomplete'?[]:VIEWPORTS.map(v=>({viewport:v.name,status:scenario==='withheld'?'EXPIRED':'VALID',ui:'PASS',analystRestriction:'OBSERVED'})),screenshots:[]})});
  assert.equal(mockLaunches,1);
  if(scenario==='success')assert.equal(result.report.status,'PASS');
  else if(scenario==='withheld')assert.equal(result.report.status,'PARTIAL');
  else assert.notEqual(result.report.status,'PASS');
  if(scenario!=='launch-fails')assert.equal(closes,1);
  const contents=await fs.readFile(path.join(folder,'assessment.json'),'utf8');
  assert.equal(contents.includes('PRIVATE_LAUNCH_DETAILS'),false);
  assert.equal(contents.includes('PRIVATE_TOKEN'),false);
});
test('malformed JSON capture fails without retaining raw content',async()=>{
  const r=response('/api/auth/me',{role:'Analyst'});r.body=async()=>Buffer.from('PRIVATE_RAW_BODY');
  const {monitor}=await monitoredResponse(r);
  await assert.rejects(monitor.waitRequired(['/api/auth/me']),e=>e.code==='API_JSON_INVALID');
  assert.equal(monitor.records.size,0);
});
test('actual bytes exceeding declared bound are rejected',async()=>{
  const {monitor}=await monitoredResponse(response('/api/auth/me',{role:'Analyst',padding:'x'.repeat(8193)},200,{'content-length':'1'}));
  await assert.rejects(monitor.waitRequired(['/api/auth/me']),e=>e.code==='API_BODY_BOUND_EXCEEDED');
});
test('missing session response times out instead of assuming Analyst',async()=>{
  const monitor=createMonitor();
  await assert.rejects(monitor.waitRequired(['/api/auth/me'],5),e=>e.code==='REQUIRED_API_RESPONSE_NOT_OBSERVED');
});
test('visible authentication form blocks every screenshot',async()=>{
  let images=0;
  const page={url:()=>ORIGIN+'/forecasting',getByRole:()=>({waitFor:async()=>{}}),locator:selector=>selector.includes('password')?{count:async()=>1}:{innerText:async()=> 'Analyst'}};
  await assert.rejects(saveScreenshots(page,{assertSafe(){}},null,VIEWPORTS[0],'VALID',()=>images++),e=>e.code==='AUTHENTICATION_FORM_VISIBLE');
  assert.equal(images,0);
});
