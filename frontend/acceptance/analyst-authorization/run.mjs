#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {checkTooling,PROJECT} from '../tooling.mjs';
import {assertCleanEnvironment} from '../environment.mjs';
import {operationsPolicy} from '../operations-core.mjs';
import {launchOptions,CONTEXT,ownerReady} from '../run.mjs';
import {createProbe,ORIGIN,SOURCE,TARGET,EMPTY,need} from './core.mjs';
const HERE=path.dirname(fileURLToPath(import.meta.url));
export async function verify(expected){
 const raw=await fs.readFile(path.join(HERE,'MANIFEST.json'));need(createHash('sha256').update(raw).digest('hex')===expected);
 const m=JSON.parse(raw);need(m.version===1&&m.target===TARGET&&m.remoteMutation===false);
 for(const [rel,sha]of Object.entries(m.files)){
  need(!path.isAbsolute(rel)&&!rel.split('/').some(p=>['','.','..'].includes(p)));
  const file=path.join(PROJECT,rel),s=await fs.lstat(file);need(s.isFile()&&!s.isSymbolicLink());
  need(createHash('sha256').update(await fs.readFile(file)).digest('hex')===sha);
 }
 return checkTooling();
}
export async function execute(tool){
 assertCleanEnvironment();need(process.stdin.isTTY&&process.stdout.isTTY);
 const {chromium}=await import(pathToFileURL(tool.library).href);
 let browser,context,handler,phase='login',count=0;const probe=createProbe();const abort=new AbortController();
 let resolveTarget;const target=new Promise(resolve=>{resolveTarget=resolve;});
 const fatal=()=>{probe.fail();abort.abort();resolveTarget();};
 const timer=setTimeout(fatal,420000);let loginTimer,requestTimer;
 try{
  browser=await chromium.launch(launchOptions(tool));context=await browser.newContext(CONTEXT);
  context.setDefaultTimeout(20000);context.setDefaultNavigationTimeout(20000);
  const page=await context.newPage();
  context.on('page',popup=>{if(popup!==page){fatal();void popup.close().catch(()=>{});}});
  handler=async route=>{
   try{
    need(++count<=500);
    const r=route.request();need(operationsPolicy(r.url(),r.method(),phase).allow);
    if(await probe.route(route))return;
    await route.continue();
   }catch{fatal();await route.abort('blockedbyclient').catch(()=>{});}
  };
  await context.route('**/*',handler);
  await context.routeWebSocket('**/*',ws=>{fatal();void ws.close().catch(()=>{});});
  page.on('response',response=>{void(async()=>{
   if(response.url()===ORIGIN+'/api/auth/me')await probe.identity(response);
   if(await probe.observe(response))resolveTarget();
  })().catch(fatal);});
  await page.goto(ORIGIN+'/pipeline',{waitUntil:'domcontentloaded'});
  loginTimer=setTimeout(fatal,300000);
  await ownerReady(abort.signal,'Analyst');clearTimeout(loginTimer);need(!abort.signal.aborted);
  need(page.url()===ORIGIN+'/pipeline');
  await page.getByRole('heading',{name:'Pipeline Operations',exact:true,level:1}).waitFor();
  const panel=page.getByRole('region',{name:'Current pipeline evidence',exact:true});
  const refresh=panel.getByRole('button',{name:'Refresh current execution',exact:true});
  await refresh.waitFor();need(await page.locator('.account-identity small').innerText()==='Analyst');probe.arm();phase='acceptance';
  requestTimer=setTimeout(fatal,20000);
  await refresh.click();await target;need(!abort.signal.aborted);
  return probe.report();
 }catch{probe.fail();return EMPTY();}
 finally{
  clearTimeout(timer);clearTimeout(loginTimer);clearTimeout(requestTimer);probe.disarm();
  // Restore normal routing before destruction. Never save storageState/HAR/trace.
  if(context&&handler)await context.unroute('**/*',handler).catch(()=>{});
  if(context)await context.close().catch(()=>{});
  if(browser)await browser.close().catch(()=>{});
 }
}
export async function main(args=process.argv.slice(2)){
 try{
  need(args.length===3&&['--run','--local-check'].includes(args[0])&&args[1]==='--manifest-sha256'&&/^[0-9a-f]{64}$/.test(args[2]));
  const tool=await verify(args[2]);
  if(args[0]==='--local-check'){console.log('{"localIntegrity":"PASS","browserLaunches":0}');return 0;}
  const report=await execute(tool);console.log(JSON.stringify(report));return report.result==='PASS'?0:1;
 }catch{console.log(JSON.stringify(EMPTY()));return 1;}
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url)process.exitCode=await main();
