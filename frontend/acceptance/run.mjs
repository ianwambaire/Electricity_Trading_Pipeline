#!/usr/bin/env node
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
export async function ownerReady(signal) {
  const prompt=createInterface({input:process.stdin,output:process.stdout,terminal:true});
  try {
    const answer=await prompt.question('In the new isolated Chrome window, sign in as the approved Analyst using the browser only. Do not enroll MFA or change the account. After Forecast Intelligence loads, type READY here (never credentials): ',{signal});
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
export async function accept({tools,load=spec=>import(spec),prompt=ownerReady,evidence=createEvidence,checks=runChecks}={}) {
  assertCleanEnvironment();
  requireThat(process.stdin.isTTY&&process.stdout.isTTY,'TTY_REQUIRED');
  const tool=tools??await checkTooling();
  const folder=await evidence();
  const result={status:'BLOCKED',phase:'BROWSER_LAUNCH',startedAt:new Date().toISOString(),finishedAt:null,origin:ORIGIN,
    browser:'Chrome for Testing 149.0.7827.55',session:'UNVERIFIED',results:[],operations:[],screenshots:[],diagnostics:{},failure:null};
  let browser,context,timer,monitor;
  const abort=new AbortController();
  try {
    const {chromium}=await load(pathToFileURL(tool.library).href);
    try {browser=await chromium.launch(launchOptions(tool));} catch {throw new AcceptanceError('BROWSER_LAUNCH_FAILED');}
    timer=setTimeout(()=>{abort.abort(new AcceptanceError('RUN_DEADLINE'));void browser.close();},LIMITS.runMs);
    context=await browser.newContext(CONTEXT);
    context.setDefaultTimeout(LIMITS.actionMs);context.setDefaultNavigationTimeout(LIMITS.actionMs);
    const page=await context.newPage();
    monitor=createMonitor({onFatal:code=>abort.abort(new AcceptanceError(code))});
    await monitor.install(context,page);
    await page.goto(START,{waitUntil:'domcontentloaded'});
    result.phase='OWNER_SIGN_IN';
    const loginTimer=setTimeout(()=>abort.abort(new AcceptanceError('OWNER_LOGIN_TIMEOUT')),LIMITS.loginMs);
    try {await prompt(abort.signal);} catch(error) {throw abort.signal.aborted?abort.signal.reason:error;}
    finally {clearTimeout(loginTimer);}
    await monitor.waitRequired(['/api/auth/me']);monitor.assertSafe();
    requireThat(monitor.records.get('/api/auth/me').body.role==='Analyst','ANALYST_SESSION_REQUIRED');
    result.session='SERVER_VERIFIED_ANALYST';monitor.acceptance();
    const writeImage=async(locator,name,options={})=>{
      requireThat(/^(desktop|mobile-responsive)-(availability|forecast|operations)\.png$/.test(name),'UNEXPECTED_PAGE');
      monitor.assertSafe();
      const image=await locator.screenshot({timeout:10_000,animations:'disabled',
        ...(options.mask?{mask:[options.mask]}:{})});
      requireThat(image.length<=5_000_000,'BROWSER_STEP_UNVERIFIED');
      await fs.writeFile(path.join(folder,name),image,{flag:'wx',mode:0o600});
    };
    Object.assign(result,await checks(page,monitor,{writeImage,progress:result}));
    requireThat(['desktop','mobile-responsive'].every(name=>result.results.some(r=>r.viewport.name===name)
      &&result.operations.some(r=>r.viewport===name)),'INCOMPLETE_VIEWPORT_ACCEPTANCE');
    result.status=result.results.every(x=>x.liveRendering==='OBSERVED')?'PASS':'PARTIAL';
    result.phase='COMPLETE';
  } catch(error) {
    result.failure=sanitizedFailure(error);
    result.status=result.failure==='FRESHNESS_BOUNDARY_DURING_CHECK'?'PARTIAL':result.session==='UNVERIFIED'?'BLOCKED':
      /(?:SESSION|OWNER_LOGIN|LAUNCH|TOOL|EVIDENCE|TTY|ENV|UNAPPROVED|BODY_BOUND_UNVERIFIED|BODY_ENCODING_UNVERIFIED)/.test(result.failure)?'BLOCKED':'FAIL';
  } finally {
    clearTimeout(timer);
    // No storageState(), tracing, HAR, video, cookie API, token reads or profile reuse.
    if(browser)await browser.close().catch(()=>{});
    result.finishedAt=new Date().toISOString();
    result.diagnostics=monitor?.diagnostics??{};
    await fs.writeFile(path.join(folder,'assessment.json'),JSON.stringify(safeReport(result),null,2)+'\n',{flag:'wx',mode:0o600});
  }
  return {report:safeReport(result),evidence:folder};
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
    requireThat(args.join(' ')==='--run --owner-assisted-analyst','OWNER_LOGIN_NOT_CONFIRMED');
    const result=await accept();console.log(JSON.stringify(result));return result.report.status==='PASS'?0:1;
  } catch(error) {console.log(JSON.stringify({status:'BLOCKED',failure:sanitizedFailure(error),browserAcceptance:'NOT_OBSERVED'}));return 1;}
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url)process.exitCode=await main();
