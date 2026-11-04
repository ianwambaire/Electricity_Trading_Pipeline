import {AcceptanceError,requireThat,ORIGIN,START,LIMITS,OBSERVED_API,VIEWPORTS,policy,safeId,checkForecast,forecastEvidence,stamp,formatTime} from './core.mjs';

export function createMonitor({onFatal=()=>{}}={}) {
  const records=new Map(),listeners=new Set();
  let phase='login',fatal=null;
  const diagnostics={consoleErrors:0,pageErrors:0,unexpectedNetworkFailures:0,cancelledRequests:0,expectedWithheld:0,blockedRequests:0,blockedMutations:0,events:0};
  function fail(code) { if(!fatal) {fatal=code;onFatal(code);} for(const fn of listeners) fn(); }
  function event() { if(++diagnostics.events>LIMITS.events) fail('EVENT_BOUND_EXCEEDED'); }
  async function response(r) {
    event();const id=safeId(r.url());
    if(!OBSERVED_API.has(id)) {
      if(phase==='acceptance' && id!=='REDACTED_RESOURCE' && r.status()>=400) diagnostics.unexpectedNetworkFailures++;
      return;
    }
    if(r.status()===401 && phase==='login') return;
    const limit=id==='/api/auth/me'?8192:LIMITS.bodyBytes;
    const length=await r.headerValue('content-length'),encoding=await r.headerValue('content-encoding');
    requireThat(/^\d{1,8}$/.test(length??'') && Number(length)<=limit,'API_BODY_BOUND_UNVERIFIED');
    requireThat(!encoding || encoding.toLowerCase()==='identity','API_BODY_ENCODING_UNVERIFIED');
    const raw=await r.body();requireThat(raw.length<=limit,'API_BODY_BOUND_EXCEEDED');
    let value;
    try {value=JSON.parse(raw.toString('utf8'));} catch {throw new AcceptanceError('API_JSON_INVALID');}
    const checkedAt=Date.now(),status=r.status();
    const headers={cacheControl:await r.headerValue('cache-control')};
    if(id==='/api/auth/me') {
      requireThat(status===200 && value?.role==='Analyst','ANALYST_SESSION_REQUIRED');
      value={role:'Analyst'}; // Never retain subject, email, display name or headers.
    } else if(id==='/api/operations/summary') {
      requireThat(['VALID','EXPIRED','WITHHELD','INVALID','MISSING_PUBLICATION','UNVERIFIED'].includes(value?.forecast_status),'OPERATIONS_STATUS_INVALID');
      value={forecast_status:value.forecast_status};
    } else {
      if(status===503 && value?.detail?.code==='FORECAST_WITHHELD') {diagnostics.expectedWithheld++;value={detail:{code:'FORECAST_WITHHELD'}};}
      else {
        requireThat(status===200 && Array.isArray(value?.forecasts) && value.forecasts.length===24,'FORECAST_RESPONSE_INVALID');
        const p=value.publication;
        value={row_count:value.row_count,forecasts:value.forecasts.map(row=>({issue_time:row.issue_time,target_time:row.target_time,
          horizon_hours:row.horizon_hours,predicted_price_eur_mwh:row.predicted_price_eur_mwh,model_release:row.model_release})),
          publication:p?{status:p.status,issue_time:p.issue_time,expires_at:p.expires_at,completed_at:p.completed_at}:null};
      }
    }
    records.set(id,{status,headers,body:value,checkedAt});for(const fn of listeners) fn();
  }
  function waitRequired(ids,timeout=LIMITS.actionMs) {
    return new Promise((resolve,reject)=>{
      const check=()=>{if(fatal) {cleanup();reject(new AcceptanceError(fatal));}
        else if(ids.every(id=>records.has(id))) {cleanup();resolve();}};
      const timer=setTimeout(()=>{cleanup();reject(new AcceptanceError('REQUIRED_API_RESPONSE_NOT_OBSERVED'));},timeout);
      function cleanup(){clearTimeout(timer);listeners.delete(check);}
      listeners.add(check);check();
    });
  }
  return {diagnostics,records,fail,
    assertSafe(){requireThat(!fatal,fatal??'BROWSER_GUARD_FAILED');},
    acceptance(){phase='acceptance';records.clear();},
    reset(ids){for(const id of ids) records.delete(id);},
    waitRequired,
    async install(context,page) {
      await context.route('**/*',route=>(async()=>{
        event();const request=route.request(),decision=policy(request.url(),request.method(),phase);
        if(!decision.allow) {
          diagnostics.blockedRequests++;if(decision.code==='APPLICATION_MUTATION_BLOCKED') diagnostics.blockedMutations++;
          fail(decision.code);await route.abort('blockedbyclient');return;
        }
        // No headers(), postData(), credentials, URLs or bodies are logged.
        await route.continue();
      })().catch(()=>fail('REQUEST_GUARD_FAILED')));
      await context.routeWebSocket('**/*',ws=>{fail('WEBSOCKET_NOT_APPROVED');void ws.close().catch(()=>{});});
      context.on('page',popup=>{if(popup!==page){fail('POPUP_NOT_APPROVED');void popup.close().catch(()=>{});}});
      page.on('response',r=>{void response(r).catch(error=>fail(error instanceof AcceptanceError?error.code:'API_CAPTURE_FAILED'));});
      page.on('console',msg=>{event();if(msg.type()==='error' && phase==='acceptance') diagnostics.consoleErrors++;});
      page.on('pageerror',()=>{event();if(phase==='acceptance') diagnostics.pageErrors++;});
      page.on('requestfailed',request=>{
        event();if(phase!=='acceptance' || safeId(request.url())==='REDACTED_RESOURCE')return;
        if(request.failure()?.errorText==='net::ERR_ABORTED')diagnostics.cancelledRequests++;
        else diagnostics.unexpectedNetworkFailures++;
      });
      page.on('download',d=>{fail('DOWNLOAD_NOT_APPROVED');void d.cancel().catch(()=>{});});
    }
  };
}

function livePanel(page) {return page.locator('section.panel').filter({has:page.getByRole('heading',{name:'24-hour forecast report',exact:true})});}
function operationsPanel(page) {return page.locator('section.panel').filter({has:page.getByRole('heading',{name:'Operational summary',exact:true})});}
export async function checkChartValues(panel,rows) {
  const dots=panel.locator('.recharts-line-dots circle.recharts-dot');
  requireThat(await dots.count()===24,'CHART_VALUES_UNVERIFIED');
  for(const [i,row] of rows.entries()) {
    await dots.nth(i).hover();
    const tooltip=panel.locator('.recharts-tooltip-wrapper');
    await tooltip.locator('.recharts-tooltip-label').filter({hasText:formatTime(row.target_time)}).waitFor({state:'visible'});
    const value=await tooltip.locator('.recharts-tooltip-item-value').innerText();
    requireThat(Math.abs(Number(value.replaceAll(',',''))-row.predicted_price_eur_mwh)<=0.000500001,'CHART_VALUES_UNVERIFIED');
  }
  return 24;
}
export async function assertWorkspace(page,heading) {
  requireThat(page.url()===ORIGIN+(heading==='Forecast Intelligence'?'/forecasting':'/pipeline'),'UNEXPECTED_PAGE');
  await page.getByRole('heading',{level:1,name:heading,exact:true}).waitFor({timeout:LIMITS.actionMs});
  requireThat((await page.locator('.account-identity small').innerText()).trim()==='Analyst','ANALYST_UI_UNVERIFIED');
  requireThat(await page.locator('input[type="password"]').count()===0,'AUTHENTICATION_FORM_VISIBLE');
}
export async function navigate(page,to,viewport) {
  const title=to==='/forecasting'?'Forecast Intelligence':'Pipeline Operations';
  if(viewport.width<1024) await page.getByRole('button',{name:'Open navigation',exact:true}).click();
  await page.getByRole('link',{name:title,exact:true}).click();
  await page.getByRole('heading',{level:1,name:title,exact:true}).waitFor();
  requireThat(page.url()===ORIGIN+to,'NAVIGATION_FAILED');
}
export async function forecastDom(page,viewport) {
  const panel=livePanel(page);
  if(await panel.count()===1) {
    const summary=panel.locator('details.forecast-table > summary');
    if(await summary.count()===1 && !(await panel.locator('details.forecast-table').getAttribute('open')!==null)) await summary.click();
  }
  return page.locator('#main-content').evaluate((main,viewport)=>{
    const panels=[...main.querySelectorAll('section.panel')];
    const live=panels.filter(p=>p.querySelector('h2')?.textContent.trim()==='24-hour forecast report');
    const panel=live[0],status=[...main.querySelectorAll('.availability')];
    const facts={};const keys=['Model release','Issue time','Inference completed','Freshness cutoff','Target start','Target end','Forecast rows','Still future targets'];
    for(const item of main.querySelectorAll('dl.facts > div')) {
      const label=item.querySelector('dt')?.textContent.trim();
      if(keys.includes(label)) facts[label]=item.querySelector('dd')?.textContent.trim();
    }
    const visible=element=>{const r=element.getBoundingClientRect();return r.width>0&&r.height>0&&r.left>=-2&&r.right<=innerWidth+2;};
    const text=main.innerText;
    const history=panels.find(p=>p.querySelector('h2')?.textContent.trim()==='Historical one-hour actual vs predicted');
    const legends=[...panel?.querySelectorAll('.recharts-legend-item-text')??[]].map(x=>x.textContent);
    return {heading:main.querySelector('h1')?.textContent.trim(),role:document.querySelector('.account-identity small')?.textContent.trim(),
      viewport,availabilityCount:status.length,availability:status[0]?.querySelector('strong')?.textContent.trim(),facts,
      livePanelCount:live.length,chartCount:panel?.querySelectorAll('.historical-chart[role="img"]').length??0,
      chartDescriptionCorrect:!!panel&&panel.querySelector('.chart-description')?.textContent.includes('All target times are UTC; prices are EUR/MWh.')
        && legends.includes('Prediction · elapsed target')&&legends.includes('Prediction · future target')
        && !!panel.querySelector('svg.recharts-surface') && [...panel.querySelectorAll('path.recharts-line-curve')].some(p=>p.getAttribute('d')),
      tableHeadersCorrect:JSON.stringify([...panel?.querySelectorAll('details.forecast-table th')??[]].map(x=>x.textContent.trim()))===JSON.stringify(['Target time (UTC)','Predicted (EUR/MWh)']),
      tableScrollable:!!panel&&[...panel.querySelectorAll('.table-scroll')].every(el=>el.clientWidth>0
        &&(el.scrollWidth<=el.clientWidth+2||['auto','scroll'].includes(getComputedStyle(el).overflowX)&&el.tabIndex>=0)),
      tableRows:[...panel?.querySelectorAll('details.forecast-table tbody tr')??[]].slice(0,25).map(tr=>[...tr.querySelectorAll('td')].slice(0,3).map(td=>td.textContent.trim().slice(0,100))),
      liveStatistics:[...main.querySelectorAll('.metric-grid')].some(x=>x.textContent.includes('Average · EUR/MWh')),
      historicalSeparated:!!history&&history.textContent.includes('not a live one-hour forecast'),
      documentOverflow:document.documentElement.scrollWidth>innerWidth+2,
      essentialVisible:!!main.querySelector('h1')&&visible(main.querySelector('h1'))&&status.length===1&&visible(status[0])&&(!panel||visible(panel)),
      sensitiveVisible:/otpauth:\/\/|(?:access_token|id_token|refresh_token|secret_access_key)\s*[:=]|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/.test(text)};
  },viewport);
}
export async function saveScreenshots(page,monitor,folder,viewport,state,writeImage) {
  monitor.assertSafe();await assertWorkspace(page,'Forecast Intelligence');
  const names=[];
  const status=page.locator('#main-content .availability');
  const name=viewport.name+'-availability.png';await writeImage(status,name);names.push(name);
  if(state==='VALID') {
    const name=viewport.name+'-forecast.png';await writeImage(livePanel(page),name);names.push(name);
  }
  return names;
}
export async function runChecks(page,monitor,{writeImage,progress={results:[],operations:[],screenshots:[]}}) {
  const {results,operations,screenshots}=progress;
  for(const viewport of VIEWPORTS) {
    progress.phase=viewport.name==='desktop'?'DESKTOP_FORECAST':'MOBILE_FORECAST';
    await page.setViewportSize({width:viewport.width,height:viewport.height});
    monitor.reset(['/api/forecast/next24','/api/operations/summary']);
    if(page.url()===START) await page.reload({waitUntil:'domcontentloaded'});
    else await navigate(page,'/forecasting',viewport);
    await monitor.waitRequired(['/api/auth/me','/api/forecast/next24','/api/operations/summary']);
    await assertWorkspace(page,'Forecast Intelligence');
    // Wait for a terminal UI state, not a backend poll or synthetic clock.
    await page.locator('#main-content .availability strong').filter({hasText:/^(Valid published forecast|WITHHELD)$/}).waitFor();
    const record=monitor.records.get('/api/forecast/next24');
    if(forecastEvidence(record.status,record.headers,record.body,Date.now()).state==='VALID') {
      await livePanel(page).locator('.historical-chart svg.recharts-surface').waitFor({state:'visible'});
    }
    let dom=await forecastDom(page,viewport);
    dom.chartValuesVerified=record.status===200&&forecastEvidence(record.status,record.headers,record.body,Date.now()).state==='VALID'
      ?await checkChartValues(livePanel(page),record.body.forecasts):0;
    const result=checkForecast({forecast:monitor.records.get('/api/forecast/next24'),operations:monitor.records.get('/api/operations/summary'),dom,now:Date.now()});
    monitor.assertSafe();results.push(result);
    screenshots.push(...await saveScreenshots(page,monitor,null,viewport,result.state,writeImage));
    if(result.state==='VALID'&&Date.now()>stamp(record.body.publication.expires_at))throw new AcceptanceError('FRESHNESS_BOUNDARY_DURING_CHECK');
    monitor.reset(['/api/operations/summary']);
    progress.phase=viewport.name==='desktop'?'DESKTOP_OPERATIONS':'MOBILE_OPERATIONS';
    await navigate(page,'/pipeline',viewport);
    await monitor.waitRequired(['/api/operations/summary']);await assertWorkspace(page,'Pipeline Operations');
    const value=monitor.records.get('/api/operations/summary'),status=value.body.forecast_status;
    const panel=operationsPanel(page);
    const shown=await panel.locator('dl.facts > div').filter({has:page.locator('dt').filter({hasText:/^Forecast availability evidence$/})}).locator('dd').innerText();
    requireThat(shown.trim()===status,'OPERATIONS_UI_DISAGREEMENT');
    requireThat(await page.getByRole('heading',{name:'Administrative monitoring',exact:true}).count()===1,'ANALYST_RESTRICTION_UI_MISSING');
    const geometry=await panel.evaluate(p=>({overflow:document.documentElement.scrollWidth>innerWidth+2,
      fits:p.getBoundingClientRect().left>=-2&&p.getBoundingClientRect().right<=innerWidth+2,
      sensitive:/otpauth:\/\/|(?:access_token|id_token|refresh_token|secret_access_key)\s*[:=]|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/.test(p.innerText)}));
    requireThat(!geometry.sensitive,'SENSITIVE_UI_DETECTED');
    requireThat(!geometry.overflow&&geometry.fits,'RESPONSIVE_OPERATIONS_CLIPPED');
    const evidence=forecastEvidence(monitor.records.get('/api/forecast/next24').status,monitor.records.get('/api/forecast/next24').headers,monitor.records.get('/api/forecast/next24').body,Date.now());
    if(evidence.state==='VALID')requireThat(status==='VALID','OPERATIONS_DISAGREEMENT');
    else if(status==='VALID')throw new AcceptanceError('FRESHNESS_BOUNDARY_DURING_CHECK');
    monitor.assertSafe();operations.push({viewport:viewport.name,status,ui:'PASS',analystRestriction:'OBSERVED'});
    const name=viewport.name+'-operations.png';await writeImage(panel,name,{mask:panel.locator('p, details')});screenshots.push(name);
  }
  monitor.assertSafe();
  requireThat(monitor.diagnostics.consoleErrors===0&&monitor.diagnostics.pageErrors===0,'BROWSER_ERRORS_OBSERVED');
  requireThat(monitor.diagnostics.unexpectedNetworkFailures===0,'NETWORK_FAILURES_OBSERVED');
  return {results,operations,screenshots};
}
