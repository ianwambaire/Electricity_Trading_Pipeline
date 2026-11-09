#!/usr/bin/env node
import {runOperationalChecks,operationalReport} from './operations.mjs';
import fs from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {pathToFileURL} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createInterface} from 'node:readline/promises';
import {AcceptanceError,requireThat,ORIGIN,START,LIMITS,safeReport,FAILURE_CODES} from './core.mjs';
import {checkTooling,PROJECT} from './tooling.mjs';
import {createMonitor,runChecks} from './browser.mjs';
import {assertCleanEnvironment,environmentKeyReport} from './environment.mjs';
import {createSetupDiagnostic} from './setup-diagnostics.mjs';
const exec=promisify(execFile);
export const EVIDENCE=path.join(PROJECT,'data/backups/private-staging-browser-acceptance');

export function sanitizedFailure(error) {return error instanceof AcceptanceError&&FAILURE_CODES.has(error.code)?error.code:'BROWSER_STEP_UNVERIFIED';}
export async function createEvidence() {
  await exec('git',['check-ignore','-q',EVIDENCE],{cwd:PROJECT,timeout:5000}).catch(()=>{throw new AcceptanceError('EVIDENCE_NOT_IGNORED');});
  process.umask(0o077);
  for(const parent of [PROJECT,path.join(PROJECT,'data'),path.join(PROJECT,'data/backups')]) {
    const info=await fs.lstat(parent);
    requireThat(info.isDirectory()&&!info.isSymbolicLink()&&await fs.realpath(parent)===parent,'UNSAFE_EVIDENCE_DIRECTORY');
  }
  await fs.mkdir(EVIDENCE,{recursive:true,mode:0o700});
  const stat=await fs.lstat(EVIDENCE);
  requireThat(stat.isDirectory()&&!stat.isSymbolicLink()&&stat.uid===process.getuid()&&(stat.mode&0o777)===0o700,'UNSAFE_EVIDENCE_DIRECTORY');
  requireThat(await fs.realpath(EVIDENCE)===EVIDENCE,'UNSAFE_EVIDENCE_DIRECTORY');
  return fs.mkdtemp(path.join(EVIDENCE,'acceptance-'));
}
export async function ownerReady(signal,role='Analyst') {
  const prompt=createInterface({input:process.stdin,output:process.stdout,terminal:true});
  try {
    const answer=await prompt.question(`In the isolated Chrome window, sign in manually as the approved ${role}. Do not change the account. After the application loads, type READY here (never credentials): `,{signal});
    requireThat(answer.trim()==='READY','OWNER_LOGIN_NOT_CONFIRMED');
  } finally {prompt.close();}
}
export function launchOptions(tool) {
  return {headless:false,executablePath:tool.executable,timeout:20_000,chromiumSandbox:true,
    env:{PATH:'/usr/bin:/bin',TMPDIR:os.tmpdir()},
    args:['--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions']};
}
export const CONTEXT={viewport:{width:1440,height:900},timezoneId:'UTC',locale:'en-GB',
  acceptDownloads:false,serviceWorkers:'block',ignoreHTTPSErrors:false,extraHTTPHeaders:{'Accept-Encoding':'identity'}};
export async function accept({tools,load=spec=>import(spec),prompt=ownerReady,evidence=createEvidence,checks,operations=false,role='Analyst'}={}) {
  requireThat(['Admin','Analyst'].includes(role)&& (operations||role==='Analyst'),'ROLE_SESSION_REQUIRED');
  checks??=operations?runOperationalChecks:runChecks;
  const report=operations?operationalReport:safeReport;
  assertCleanEnvironment();
  requireThat(process.stdin.isTTY&&process.stdout.isTTY,'TTY_REQUIRED');
  const tool=tools??await checkTooling();
  const folder=await evidence();
  const result={status:'BLOCKED',phase:'BROWSER_LAUNCH',startedAt:new Date().toISOString(),finishedAt:null,origin:ORIGIN,
    role,browser:'Chrome for Testing 149.0.7827.55',session:'UNVERIFIED',results:[],operations:[],screenshots:[],diagnostics:{},failure:null};
  const setup=createSetupDiagnostic();
  let browser,context,timer,monitor;
  const abort=new AbortController();
  try {
    const {chromium}=await setup.run('LOAD_PLAYWRIGHT',()=>load(pathToFileURL(tool.library).href));
    browser=await setup.run('LAUNCH_BROWSER',()=>chromium.launch(launchOptions(tool)));
    await setup.run('INSTALL_BROWSER_MONITOR',async()=>{browser.on?.('disconnected',()=>setup.closed());});
    timer=setTimeout(()=>{abort.abort(new AcceptanceError('RUN_DEADLINE'));void browser.close();},LIMITS.runMs);
    context=await setup.run('CREATE_CONTEXT',()=>browser.newContext(CONTEXT));
    await setup.run('CONFIGURE_TIMEOUTS',async()=>{context.setDefaultTimeout(LIMITS.actionMs);context.setDefaultNavigationTimeout(LIMITS.actionMs);});
    const page=await setup.run('CREATE_PAGE',()=>context.newPage());
    monitor=createMonitor({operations,expectedRole:role,onFatal:code=>abort.abort(new AcceptanceError(code))});
    await monitor.install(context,page,{setup});
    await setup.run('INITIAL_NAVIGATION',async()=>{
      setup.navigationResponse(null,START);
      const response=await page.goto(START,{waitUntil:'domcontentloaded'});
      monitor.assertSafe();setup.finishNavigation(response,page.url());
    });
    result.phase='OWNER_SIGN_IN';
    const loginTimer=setTimeout(()=>abort.abort(new AcceptanceError('OWNER_LOGIN_TIMEOUT')),LIMITS.loginMs);
    try {await setup.run('OWNER_SIGN_IN',()=>prompt(abort.signal,role));} catch(error) {throw abort.signal.aborted?abort.signal.reason:error;}
    finally {clearTimeout(loginTimer);}
    await setup.run(operations?'VERIFY_ROLE':'VERIFY_ANALYST',async()=>{
      await monitor.waitRequired(['/api/auth/me']);monitor.assertSafe();
      requireThat(monitor.records.get('/api/auth/me').body.role===role,operations?'ROLE_SESSION_REQUIRED':'ANALYST_SESSION_REQUIRED');
    });
    result.session=role==='Admin'?'SERVER_VERIFIED_ADMIN':'SERVER_VERIFIED_ANALYST';monitor.acceptance();
    const writeImage=async(locator,name,options={})=>{
      requireThat((operations?/^(desktop|mobile-responsive)-(overview|pipeline|admin)-operations\.png$/:/^(desktop|mobile-responsive)-(availability|forecast|operations)\.png$/).test(name),'UNEXPECTED_PAGE');
      monitor.assertSafe();
      const image=await locator.screenshot({timeout:10_000,animations:'disabled',
        ...(options.mask?{mask:[options.mask]}:{})});
      requireThat(image.length<=5_000_000,'BROWSER_STEP_UNVERIFIED');
      await fs.writeFile(path.join(folder,name),image,{flag:'wx',mode:0o600});
    };
    Object.assign(result,await setup.run('ACCEPTANCE_CHECKS',()=>checks(page,monitor,{writeImage,progress:result,role})));
    if(operations){
      requireThat(result.operations.length===4,'INCOMPLETE_VIEWPORT_ACCEPTANCE');
      result.status=result.operations.every(r=>r.status==='VALID')&&role==='Admin'&&monitor.diagnostics.consoleErrors===0&&monitor.diagnostics.unexpectedNetworkFailures===0?'PASS':'PARTIAL';
    }else{
    requireThat(['desktop','mobile-responsive'].every(name=>result.results.some(r=>r.viewport.name===name)
      &&result.operations.some(r=>r.viewport===name)),'INCOMPLETE_VIEWPORT_ACCEPTANCE');
    result.status=result.results.every(x=>x.liveRendering==='OBSERVED')?'PASS':'PARTIAL';
    }
    result.phase='COMPLETE';
    await setup.run('COMPLETE',async()=>{});
  } catch(error) {
    // Prefer an already observed fixed guard cause over its later abort/timeout.
    try {monitor?.assertSafe();} catch(guardError) {error=guardError;}
    result.setup=setup.failure(error,error instanceof AcceptanceError);
    result.failure=sanitizedFailure(error);
    if(result.failure==='BROWSER_STEP_UNVERIFIED')result.failure=result.setup.category;
    result.status=result.failure==='FRESHNESS_BOUNDARY_DURING_CHECK'?'PARTIAL':result.session==='UNVERIFIED'?'BLOCKED':
      /(?:SESSION|OWNER_LOGIN|LAUNCH|TOOL|EVIDENCE|TTY|ENV|UNAPPROVED|BODY_BOUND_UNVERIFIED|BODY_ENCODING_UNVERIFIED)/.test(result.failure)?'BLOCKED':'FAIL';
  } finally {
    clearTimeout(timer);
    setup.cleanup();
    // No storageState(), tracing, HAR, video, cookie API, token reads or profile reuse.
    if(browser)await browser.close().catch(()=>{});
    result.finishedAt=new Date().toISOString();
    result.diagnostics=monitor?.diagnostics??{};
    result.setup=setup.snapshot();
    await fs.writeFile(path.join(folder,'assessment.json'),JSON.stringify(report(result),null,2)+'\n',{flag:'wx',mode:0o600});
  }
  return {report:report(result),evidence:folder};
}
export async function main(args=process.argv.slice(2)) {
  try {
    if(args.length===1&&args[0]==='--inspect-environment') {
      const report=environmentKeyReport();
      console.log(JSON.stringify({mode:'ENVIRONMENT_KEYS_ONLY',boundary:'harness-node-entry',exactArguments:process.execArgv.length===0,
        nodeVersion:process.versions.node,nodeExecutableMatchesBinding:process.execPath==='/Users/iannganga/.nvm/versions/node/v22.22.0/bin/node',
        ...report,browserLaunches:0,stagingRequests:0}));return report.accepted?0:1;
    }
    if(args.length===0||args.join(' ')==='--check') {
      await checkTooling();console.log(JSON.stringify({localTooling:'PASS',browserLaunches:0,stagingRequests:0}));return 0;
    }
    const ops=args.length===3&&args[0]==='--run'&&args[1]==='--operations'&&['--owner-assisted-admin','--owner-assisted-analyst'].includes(args[2]);
    requireThat(ops||args.join(' ')==='--run --owner-assisted-analyst','OWNER_LOGIN_NOT_CONFIRMED');
    const result=await accept({operations:ops,role:ops&&args[2]==='--owner-assisted-admin'?'Admin':'Analyst'});console.log(JSON.stringify(result));return result.report.status==='PASS'?0:1;
  } catch(error) {console.log(JSON.stringify({status:'BLOCKED',failure:sanitizedFailure(error),browserAcceptance:'NOT_OBSERVED'}));return 1;}
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url)process.exitCode=await main();
