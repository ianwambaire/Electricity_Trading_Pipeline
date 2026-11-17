#!/usr/bin/env node
// Explicit --run only; no browser or network access during import/local check.
import fs from'node:fs/promises';import path from'node:path';import{fileURLToPath,pathToFileURL}from'node:url';import{createHash}from'node:crypto';
import{checkTooling,PROJECT}from'../tooling.mjs';import{assertCleanEnvironment}from'../environment.mjs';import{operationsPolicy}from'../operations-core.mjs';import{launchOptions,CONTEXT,ownerReady}from'../run.mjs';
import{createProbe,invokeExistingClient,ORIGIN,TARGET,MODULE,EMPTY,need}from'./core.mjs';
const HERE=path.dirname(fileURLToPath(import.meta.url));
export async function verify(expected){
 const raw=await fs.readFile(path.join(HERE,'MANIFEST.json'));need(createHash('sha256').update(raw).digest('hex')===expected);const m=JSON.parse(raw);
 need(m.version===1&&m.target===TARGET&&m.mode==='DIRECT_EXISTING_CLIENT'&&m.remoteMutation===false);
 for(const[rel,hash]of Object.entries(m.files)){need(!path.isAbsolute(rel)&&!rel.split('/').some(p=>['','.','..'].includes(p)));const p=path.join(PROJECT,rel),s=await fs.lstat(p);need(s.isFile()&&!s.isSymbolicLink()&&await fs.realpath(p)===p);need(createHash('sha256').update(await fs.readFile(p)).digest('hex')===hash);}
 const bindings=JSON.parse(await fs.readFile(path.join(HERE,'BINDINGS.json')));need(bindings.module===MODULE);
 return {tool:await checkTooling(),bindings};
}
export async function verifyAsset(response,bindings){
 const size=await response.headerValue('content-length'),encoding=await response.headerValue('content-encoding');
 need(response.status()===200&&/^\d{1,8}$/.test(size??'')&&Number(size)<=2000000&&(!encoding||encoding.toLowerCase()==='identity'));
 const raw=await response.body();need(raw.length===Number(size)&&raw.length<=2000000);
 const expected=response.url()===MODULE?bindings.sha256:response.url()===ORIGIN+'/pipeline'?bindings.indexSha256:null;
 need(expected&&createHash('sha256').update(raw).digest('hex')===expected);
 return response.url()===MODULE?'MODULE':'HTML';
}
// Session is separately injectable for offline lifecycle tests. CLI always performs
// integrity/environment/TTY checks before acquiring the verified Chromium loader.
export async function session({chromium,tool,bindings,prompt=ownerReady,setTimer=setTimeout,clearTimer=clearTimeout}){
 let browser,context,handler,page;let phase='login',stage='LAUNCH',failure=null,events=0,html=false,module=false;const probe=createProbe();const abort=new AbortController();
 let resolveTarget;const target=new Promise(resolve=>{resolveTarget=resolve;});let targetTimer,loginTimer;
 const fatal=code=>{failure??=code;probe.fail();abort.abort();resolveTarget();};
 const timer=setTimer(()=>fatal('DEADLINE'),420000);
 try{
  browser=await chromium.launch(launchOptions(tool));browser.on('disconnected',()=>fatal('BROWSER_CLOSED'));
  stage='CONTEXT';context=await browser.newContext(CONTEXT);context.setDefaultTimeout(20000);context.setDefaultNavigationTimeout(20000);page=await context.newPage();
  context.on('page',popup=>{if(popup!==page){fatal('UNEXPECTED_PAGE');void popup.close().catch(()=>{});}});
  page.on('close',()=>fatal('PAGE_CLOSED'));page.on('crash',()=>fatal('PAGE_CRASHED'));
  handler=async route=>{try{need(++events<=500);const r=route.request();need(operationsPolicy(r.url(),r.method(),phase).allow);probe.request(r);await route.continue();}catch{fatal('REQUEST_SCOPE');await route.abort('blockedbyclient').catch(()=>{});}};
  await context.route('**/*',handler);await context.routeWebSocket('**/*',ws=>{fatal('WEBSOCKET');void ws.close().catch(()=>{});});
  page.on('response',r=>{void(async()=>{
   if(r.url()===MODULE||r.url()===ORIGIN+'/pipeline'){const kind=await verifyAsset(r,bindings);if(kind==='MODULE')module=true;else html=true;}
   if(r.url()===ORIGIN+'/api/auth/me')await probe.identity(r);
   if(await probe.response(r))resolveTarget();
  })().catch(()=>fatal('RESPONSE_GUARD'));});
  stage='NAVIGATION';await page.goto(ORIGIN+'/pipeline',{waitUntil:'domcontentloaded'});need(!abort.signal.aborted);
  stage='OWNER_LOGIN';loginTimer=setTimer(()=>fatal('OWNER_TIMEOUT'),300000);await prompt(abort.signal,'Analyst');clearTimer(loginTimer);need(!abort.signal.aborted);
  stage='IDENTITY';need(html&&module&&page.url()===ORIGIN+'/pipeline');
  await page.getByRole('heading',{name:'Pipeline Operations',exact:true,level:1}).waitFor();need(await page.locator('.account-identity small').innerText()==='Analyst');
  const scripts=await page.locator('script[type="module"][src]').evaluateAll(nodes=>nodes.map(n=>n.src));need(scripts.length===1&&scripts[0]===MODULE);
  probe.arm();phase='acceptance';stage='SINGLE_REQUEST';targetTimer=setTimer(()=>fatal('REQUEST_TIMEOUT'),20000);
  const outcome=await invokeExistingClient(page);await target;need(!abort.signal.aborted);
  const result=probe.report();if(result.result==='PASS')need(outcome==='DENIED');
  return {status:result.result==='PASS'?'PASS':'FAILED',stage:'COMPLETE',...result};
 }catch{return {status:'BLOCKED',stage:failure??stage,...EMPTY()};}
 finally{
  clearTimer(timer);clearTimer(loginTimer);clearTimer(targetTimer);
  if(context&&handler)await context.unroute('**/*',handler).catch(()=>{});
  if(context)await context.close().catch(()=>{});
  if(browser)await browser.close().catch(()=>{});
 }
}
export async function main(args=process.argv.slice(2)){
 try{
  need(args.length===3&&['--run','--local-check'].includes(args[0])&&args[1]==='--manifest-sha256'&&/^[0-9a-f]{64}$/.test(args[2]));assertCleanEnvironment();const{tool,bindings}=await verify(args[2]);
  if(args[0]==='--local-check'){console.log('{"localIntegrity":"PASS","browserLaunches":0}');return 0;}
  need(process.stdin.isTTY&&process.stdout.isTTY);const{chromium}=await import(pathToFileURL(tool.library).href);
  const result=await session({chromium,tool,bindings});console.log(JSON.stringify(result));return result.status==='PASS'?0:1;
 }catch{console.log(JSON.stringify({status:'BLOCKED',stage:'LOCAL_PREREQUISITE',...EMPTY()}));return 1;}
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url)process.exitCode=await main();
