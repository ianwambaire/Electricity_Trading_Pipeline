import {sanitizeSetup} from './setup-diagnostics.mjs';
import {requireThat,ORIGIN,LIMITS,VIEWPORTS,FAILURE_CODES} from './core.mjs';
import {CURRENT,currentDomCheck,adminDomCheck,matchingPublic} from './operations-core.mjs';

export async function operationsDom(panel,page,role){
 return panel.evaluate((p,role)=>{
  const facts={};for(const item of p.querySelectorAll('dl.facts > div'))facts[item.querySelector('dt')?.textContent.trim()]=item.querySelector('dd')?.textContent.trim();
  const r=p.getBoundingClientRect();
  return {role:document.querySelector('.account-identity small')?.textContent.trim(),facts,
   status:p.querySelector('[role="status"]')?.textContent.trim(),note:p.querySelector('.data-note')?.textContent.trim(),
   unavailable:/Current execution cannot be established|No matching fresh Admin evidence/.test(p.innerText),
   documentOverflow:document.documentElement.scrollWidth>innerWidth+2,panelFits:r.width>0&&r.left>=-2&&r.right<=innerWidth+2,
   sensitiveVisible:/otpauth:\/\/|(?:access_token|id_token|refresh_token|secret_access_key)\s*[:=]|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/.test(p.innerText)};
 },role);
}
export async function runOperationalChecks(page,monitor,{writeImage,progress,role}){
 let first;
 for(const viewport of VIEWPORTS){
  await page.setViewportSize({width:viewport.width,height:viewport.height});
  for(const [route,title,label] of [['/','Executive Overview','overview'],['/pipeline','Pipeline Operations','pipeline']]){
   progress.phase='ACCEPTANCE_CHECKS';
   if(viewport.width<1024)await page.getByRole('button',{name:'Open navigation',exact:true}).click();
   await page.getByRole('link',{name:title,exact:true}).click();
   await page.getByRole('heading',{level:1,name:title,exact:true}).waitFor();
   requireThat(page.url()===ORIGIN+route,'UNEXPECTED_PAGE');
   requireThat(await page.locator('input[type="password"]').count()===0,'AUTHENTICATION_FORM_VISIBLE');
   const panel=page.getByRole('region',{name:'Current pipeline evidence',exact:true});
   monitor.reset([CURRENT[0],CURRENT[1]]);
   await panel.getByRole('button',{name:'Refresh current execution',exact:true}).click();
   // Public endpoint only. No session/header/storage/token extraction or replay.
   await page.evaluate(async()=>{await fetch('/api/pipeline/current',{method:'GET',credentials:'omit',cache:'no-store',redirect:'error'});});
   await monitor.waitRequired([CURRENT[0],CURRENT[1]]);
   await panel.getByRole('status').filter({hasText:/^Operational evidence: (VALID|STALE|MISSING|INVALID)$/}).waitFor();
   const record=monitor.records.get(CURRENT[0]).body;
   requireThat(matchingPublic(record,monitor.records.get(CURRENT[1]).body),'OPERATIONS_DISAGREEMENT');
   if(first)requireThat(matchingPublic(first,record),'OPERATIONAL_VERSION_CHANGED');else first=record;
   const evidence=currentDomCheck(record,await operationsDom(panel,page,role),role,Date.now());
   requireThat(await page.getByRole('heading',{name:'Historical operational snapshot',exact:true}).count()===1,'HISTORICAL_LABEL_MISSING');
   const item={viewport:viewport.name,page:label,...evidence,ui:'PASS',admin:'NOT_APPLICABLE'};
   const image=viewport.name+'-'+label+'-operations.png';await writeImage(panel,image);progress.screenshots.push(image);
   if(route==='/pipeline'){
    const admin=page.getByRole('region',{name:'Current Admin evidence',exact:true});
    if(role==='Admin'){
     await monitor.waitRequired([CURRENT[2]]);
     const adminRecord=monitor.records.get(CURRENT[2]);
     requireThat(adminRecord.status===200,'ADMIN_CURRENT_UNVERIFIED');
     if(record.status==='VALID')await admin.locator('dl.facts').waitFor();
     else await admin.getByRole('status').waitFor();
     adminDomCheck(record,adminRecord.body,await operationsDom(admin,page,role),Date.now());
     item.admin='AUTHENTICATED_200_MATCH';
     const image=viewport.name+'-admin-operations.png';await writeImage(admin,image,{mask:admin.locator('dd')});progress.screenshots.push(image);
    }else{
     requireThat(await admin.count()===0,'ANALYST_RESTRICTION_UI_MISSING');
     await page.getByRole('heading',{name:'Administrative monitoring',exact:true}).waitFor();
     item.admin='UI_RESTRICTED_HTTP_403_NOT_OBSERVED';
    }
   }
   monitor.assertSafe();progress.operations.push(item);
  }
 }
 requireThat(monitor.diagnostics.pageErrors===0,'BROWSER_ERRORS_OBSERVED');
 // Console/network counts are retained honestly; historical report failures are
 // separate from validation of the operational-current responses above.
 return {operations:progress.operations,screenshots:progress.screenshots};
}
export function operationalReport(result){
 const role=result.role;requireThat(['Admin','Analyst'].includes(role),'ROLE_SESSION_REQUIRED');
 requireThat(['PASS','PARTIAL','BLOCKED','FAIL'].includes(result.status)&&['UNVERIFIED','SERVER_VERIFIED_ADMIN','SERVER_VERIFIED_ANALYST'].includes(result.session)&&['BROWSER_LAUNCH','OWNER_SIGN_IN','ACCEPTANCE_CHECKS','COMPLETE'].includes(result.phase)&&(result.failure===null||FAILURE_CODES.has(result.failure)),'REPORT_SCHEMA');
 for(const t of [result.startedAt,result.finishedAt])requireThat(/^\d{4}-\d\d-\d\dT[\d:.]+Z$/.test(t),'REPORT_SCHEMA');
 const output={status:result.status,role,session:result.session,phase:result.phase,startedAt:result.startedAt,finishedAt:result.finishedAt,
  origin:ORIGIN,browser:'Chrome for Testing 149.0.7827.55',failure:result.failure,operations:[],screenshots:[],diagnostics:{},setup:sanitizeSetup(result.setup),
  analystAuthenticated403:'NOT_OBSERVED',forecastRendering:'NOT_TESTED_IN_OPERATIONAL_ACCEPTANCE'};
 for(const r of result.operations.slice(0,4)){
  requireThat(['desktop','mobile-responsive'].includes(r.viewport)&&['overview','pipeline'].includes(r.page)&&['VALID','STALE','MISSING','INVALID'].includes(r.status),'REPORT_SCHEMA');
  requireThat(r.ui==='PASS'&&['NOT_APPLICABLE','AUTHENTICATED_200_MATCH','UI_RESTRICTED_HTTP_403_NOT_OBSERVED'].includes(r.admin),'REPORT_SCHEMA');
  requireThat(r.evidence===null||/^[a-f0-9]{64}$/.test(r.evidence),'REPORT_SCHEMA');
  const safe={viewport:r.viewport,page:r.page,status:r.status,evidence:r.evidence,ui:r.ui,admin:r.admin};
  for(const k of ['observedAt','freshUntil']){requireThat(r[k]===null||/^\d{4}-\d\d-\d\dT[\d:.]+(?:Z|\+00:00)$/.test(r[k]),'REPORT_SCHEMA');safe[k]=r[k];}
  output.operations.push(safe);
 }
 output.screenshots=result.screenshots.filter(s=>/^(desktop|mobile-responsive)-(overview|pipeline|admin)-operations\.png$/.test(s)).slice(0,6);
 for(const [k,v] of Object.entries(result.diagnostics))if(/^(consoleErrors|pageErrors|unexpectedNetworkFailures|cancelledRequests|expectedWithheld|blockedRequests|blockedMutations|events)$/.test(k)&&Number.isInteger(v)&&v>=0)output.diagnostics[k]=v;
 return output;
}
