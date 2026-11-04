// Pure acceptance rules. No browser launch, credential access, network or files.
export const ORIGIN = 'https://staging.powerflowenergy.dev';
export const START = `${ORIGIN}/forecasting`;
export const MODEL = 'next24h-hgb-2026-09-21-v1';
export const HOSTED = 'https://us-east-1nloyfrvex.auth.us-east-1.amazoncognito.com';
const ISSUER = 'https://cognito-idp.us-east-1.amazonaws.com';
const POOL = '/us-east-1_NLoYFRvex';
export const VIEWPORTS = [{name:'desktop',width:1440,height:900},{name:'mobile-responsive',width:390,height:844}];
export const LIMITS = {loginMs:300_000,runMs:450_000,actionMs:20_000,bodyBytes:262_144,events:500};
export class AcceptanceError extends Error {
  constructor(code) { super(code); this.code = code; }
}
export function requireThat(ok, code) { if (!ok) throw new AcceptanceError(code); }
export const READ_API = new Set(['/api/auth/me','/api/forecast/next24','/api/operations/summary',
  '/api/market/summary','/api/models/summary','/api/pipeline/status','/api/forecast/one-hour',
  '/api/forecast/context','/api/market/price-comparison','/api/forecast/realized-evaluation','/api/health']);
export const OBSERVED_API = new Set(['/api/auth/me','/api/forecast/next24','/api/operations/summary']);
export function safeId(value) {
  try {
    const u = new URL(value);
    return u.origin===ORIGIN && READ_API.has(u.pathname) ? u.pathname : 'REDACTED_RESOURCE';
  } catch { return 'REDACTED_RESOURCE'; }
}
export function policy(raw, method, phase='acceptance') {
  let u;
  try { u = new URL(raw); } catch { return {allow:false,code:'UNAPPROVED_RESOURCE'}; }
  if (u.protocol!=='https:' || u.username || u.password || u.port) return {allow:false,code:'UNAPPROVED_ORIGIN'};
  const clean = u.pathname;
  const rawPath=raw.slice(raw.indexOf('://')+3).replace(/^[^/]+/,'').split(/[?#]/)[0];
  if (/%(?:2e|2f|5c)/i.test(rawPath) || /\\|\/\.\.?\//.test(rawPath)) return {allow:false,code:'PATH_REJECTED'};
  if (u.origin===ORIGIN) {
    if (!['GET','HEAD'].includes(method)) return {allow:false,code:'APPLICATION_MUTATION_BLOCKED'};
    if (clean.startsWith('/api/')) {
      if (!READ_API.has(clean)) return {allow:false,code:'UNAPPROVED_API'};
      if (clean==='/api/forecast/one-hour' && u.search!=='?limit=500&offset=0') return {allow:false,code:'UNBOUNDED_HISTORY_BLOCKED'};
      if (clean==='/api/forecast/context') {
        if ([...u.searchParams.keys()].join(',')!=='issue_time' || !Number.isFinite(Date.parse(u.searchParams.get('issue_time')))) return {allow:false,code:'API_QUERY_REJECTED'};
      } else if (clean!=='/api/forecast/one-hour' && u.search) return {allow:false,code:'API_QUERY_REJECTED'};
      return {allow:true,code:'READ_API'};
    }
    const page = ['/', '/forecasting','/pipeline'].includes(clean);
    if (page && !u.search || clean==='/auth/callback' && phase==='login') return {allow:true,code:'APP_PAGE'};
    if (/^\/(?:assets|fonts)\/[A-Za-z0-9_./-]+\.(?:js|css|woff2|png|svg|ico)$/.test(clean) && !u.search) return {allow:true,code:'APP_ASSET'};
    if (['/favicon.ico','/vite.svg'].includes(clean) && !u.search) return {allow:true,code:'APP_ASSET'};
    return {allow:false,code:'UNAPPROVED_PAGE'};
  }
  if (u.origin===ISSUER && method==='GET' && !u.search && [POOL+'/.well-known/openid-configuration',POOL+'/.well-known/jwks.json'].includes(clean)) return {allow:true,code:'PUBLIC_OIDC_METADATA'};
  // Owner-driven native Cognito login only. Never inspect query fields, headers,
  // form values, token responses, storage or passwords. Enrollment/logout denied.
  if (u.origin===HOSTED && phase==='login') {
    if (method==='GET' && ['/oauth2/authorize','/login','/mfa','/selectMfa'].includes(clean)) return {allow:true,code:'OWNER_AUTH'};
    if (method==='POST' && ['/login','/mfa','/selectMfa','/oauth2/token'].includes(clean)) return {allow:true,code:'OWNER_AUTH'};
    if (method==='GET' && /^\/(?:assets|static)\/[A-Za-z0-9_./-]+\.(?:js|css|woff2|png|svg|ico)$/.test(clean)) return {allow:true,code:'OWNER_AUTH_ASSET'};
  }
  return {allow:false,code:'UNAPPROVED_RESOURCE'};
}
export function stamp(value) {
  requireThat(typeof value==='string' && /(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value)), 'INVALID_UTC');
  return Date.parse(value);
}
export function formatTime(value) { return new Date(stamp(value)).toISOString().replace('T',' ').replace('.000Z',' UTC').replace(/Z$/,' UTC'); }
export function forecastEvidence(code, headers, body, now) {
  requireThat(headers.cacheControl?.split(',').some(x=>x.trim().toLowerCase()==='no-store'), 'API_NO_STORE_MISSING');
  if (code===503) {
    requireThat(body?.detail?.code==='FORECAST_WITHHELD', 'WITHHELD_CONTRACT');
    return {state:'WITHHELD',rows:[],publication:null};
  }
  requireThat(code===200 && body?.row_count===24 && Array.isArray(body.forecasts) && body.forecasts.length===24, 'FORECAST_RESPONSE_INVALID');
  const p = body.publication;
  requireThat(p?.status==='VALID', 'PUBLICATION_PROVENANCE_MISSING');
  const issue=stamp(p.issue_time), expiry=stamp(p.expires_at), completed=stamp(p.completed_at);
  requireThat(expiry===issue+3*3600_000 && completed>=issue && completed<=now, 'PUBLICATION_TIMING_INVALID');
  for (const [i,row] of body.forecasts.entries()) {
    requireThat(row.model_release===MODEL && row.horizon_hours===i+1 && stamp(row.issue_time)===issue
      && stamp(row.target_time)===issue+(i+1)*3600_000 && Number.isFinite(row.predicted_price_eur_mwh), 'FORECAST_ROWS_INVALID');
  }
  return {state:now>expiry || now<issue ? 'EXPIRED':'VALID',rows:body.forecasts,publication:p};
}
export function checkForecast({forecast,operations,dom,now}) {
  const evidence=forecastEvidence(forecast.status,forecast.headers,forecast.body,now);
  requireThat(operations.status===200, 'OPERATIONS_UNAVAILABLE');
  const status=operations.body.forecast_status;
  if (evidence.state==='EXPIRED' && status==='VALID' && operations.checkedAt<=stamp(evidence.publication.expires_at)) {
    throw new AcceptanceError('FRESHNESS_BOUNDARY_DURING_CHECK');
  }
  requireThat(evidence.state==='VALID' ? status==='VALID' : ['EXPIRED','WITHHELD','MISSING_PUBLICATION','INVALID','UNVERIFIED'].includes(status), 'OPERATIONS_DISAGREEMENT');
  requireThat(dom.heading==='Forecast Intelligence' && dom.role==='Analyst', 'ANALYST_OR_RENDER_UNVERIFIED');
  requireThat(dom.historicalSeparated, 'HISTORICAL_LABEL_MISSING');
  requireThat(dom.availabilityCount===1, 'DUPLICATE_FORECAST_STATUS');
  requireThat(!dom.documentOverflow && dom.essentialVisible, 'RESPONSIVE_CONTENT_CLIPPED');
  requireThat(!dom.sensitiveVisible, 'SENSITIVE_UI_DETECTED');
  if (evidence.state==='VALID') {
    requireThat(dom.availability==='Valid published forecast' && dom.livePanelCount===1 && dom.chartCount===1, 'LIVE_FORECAST_NOT_RENDERED');
    requireThat(dom.chartDescriptionCorrect && dom.tableHeadersCorrect && dom.tableScrollable && dom.tableRows.length===24, 'CHART_OR_TABLE_CONTRACT');
    requireThat(dom.chartValuesVerified===24,'CHART_VALUES_UNVERIFIED');
    for (const [i,row] of dom.tableRows.entries()) {
      requireThat(row[0]===formatTime(evidence.rows[i].target_time) && row.length===2
        && row[1].trim()!=='' && Number(row[1])===evidence.rows[i].predicted_price_eur_mwh, 'UI_API_VALUE_MISMATCH');
    }
    const facts=dom.facts;
    for (const [key,value] of Object.entries({'Model release':MODEL,'Issue time':formatTime(evidence.publication.issue_time),
      'Inference completed':formatTime(evidence.publication.completed_at),'Freshness cutoff':formatTime(evidence.publication.expires_at),
      'Target start':formatTime(evidence.rows[0].target_time),'Target end':formatTime(evidence.rows.at(-1).target_time),'Forecast rows':'24'})) {
      requireThat(facts[key]===value, 'UI_PROVENANCE_MISMATCH');
    }
    const before=Number(facts['Still future targets']);
    const future=evidence.rows.filter(row=>stamp(row.target_time)>now).length;
    requireThat(before===future || evidence.rows.some(row=>Math.abs(stamp(row.target_time)-now)<2000) && Math.abs(before-future)<=1, 'FUTURE_TARGET_COUNT_MISMATCH');
  } else {
    requireThat(dom.availability==='WITHHELD' && dom.livePanelCount===0 && dom.chartCount===0
      && dom.tableRows.length===0 && !dom.liveStatistics, 'STALE_OR_INVENTED_FORECAST_VISIBLE');
  }
  return {state:evidence.state,liveRendering:evidence.state==='VALID'?'OBSERVED':'NOT_OBSERVED',
    predictions:evidence.state==='VALID'?24:0,operations:status,issue:evidence.publication?.issue_time??null,
    expiry:evidence.publication?.expires_at??null,checkedAt:new Date(now).toISOString(),viewport:dom.viewport,crossLayer:'PASS'};
}
export function safeReport(report) {
  // No raw bodies, console strings, URLs, identity values or error messages.
  requireThat(['PASS','PARTIAL','FAIL','BLOCKED'].includes(report.status),'REPORT_SCHEMA');
  requireThat(['BROWSER_LAUNCH','OWNER_SIGN_IN','DESKTOP_FORECAST','DESKTOP_OPERATIONS','MOBILE_FORECAST','MOBILE_OPERATIONS','COMPLETE'].includes(report.phase),'REPORT_SCHEMA');
  requireThat(report.origin===ORIGIN && ['UNVERIFIED','SERVER_VERIFIED_ANALYST'].includes(report.session)
    && (report.failure===null||FAILURE_CODES.has(report.failure)),'REPORT_SCHEMA');
  stamp(report.startedAt);stamp(report.finishedAt);
  requireThat(report.results.length<=2 && report.operations.length<=2 && report.screenshots.length<=6,'REPORT_SCHEMA');
  const results=report.results.map(r=>{
    const viewport=VIEWPORTS.find(v=>JSON.stringify(v)===JSON.stringify(r.viewport));
    requireThat(viewport && ['VALID','EXPIRED','WITHHELD'].includes(r.state) && [0,24].includes(r.predictions)
      && ['OBSERVED','NOT_OBSERVED'].includes(r.liveRendering) && r.crossLayer==='PASS','REPORT_SCHEMA');
    requireThat(['VALID','EXPIRED','WITHHELD','INVALID','MISSING_PUBLICATION','UNVERIFIED'].includes(r.operations),'REPORT_SCHEMA');
    if(r.issue!==null)stamp(r.issue);if(r.expiry!==null)stamp(r.expiry);stamp(r.checkedAt);
    return {state:r.state,predictions:r.predictions,liveRendering:r.liveRendering,operations:r.operations,
      issue:r.issue,expiry:r.expiry,checkedAt:r.checkedAt,viewport,crossLayer:'PASS'};
  });
  const operations=report.operations.map(r=>{
    requireThat(VIEWPORTS.some(v=>v.name===r.viewport)&&['VALID','EXPIRED','WITHHELD','INVALID','MISSING_PUBLICATION','UNVERIFIED'].includes(r.status)
      && r.ui==='PASS'&&r.analystRestriction==='OBSERVED','REPORT_SCHEMA');
    return {viewport:r.viewport,status:r.status,ui:'PASS',analystRestriction:'OBSERVED'};
  });
  requireThat(report.screenshots.every(s=>/^(desktop|mobile-responsive)-(availability|forecast|operations)\.png$/.test(s)),'REPORT_SCHEMA');
  const diagnostics={};
  for(const key of ['consoleErrors','pageErrors','unexpectedNetworkFailures','cancelledRequests','expectedWithheld','blockedRequests','blockedMutations','events']) {
    const value=report.diagnostics[key]??0;requireThat(Number.isInteger(value)&&value>=0&&value<=10_000,'REPORT_SCHEMA');diagnostics[key]=value;
  }
  return {status:report.status,phase:report.phase,startedAt:report.startedAt,finishedAt:report.finishedAt,origin:ORIGIN,
    browser:'Chrome for Testing 149.0.7827.55',session:report.session,results,operations,
    screenshots:report.screenshots,diagnostics,failure:report.failure};
}

export const FAILURE_CODES=new Set(['CLEAN_ENV_REQUIRED','ANALYST_SESSION_REQUIRED','ANALYST_UI_UNVERIFIED','OWNER_LOGIN_NOT_CONFIRMED','OWNER_LOGIN_TIMEOUT',
 'TTY_REQUIRED','BINDINGS_MISMATCH','LOCAL_RUNTIME_MISMATCH','TOOL_PARENT_SYMLINK','TOOL_FILE_INVALID','TOOL_CHANGED_DURING_CHECK',
 'UNSAFE_TOOL_DIRECTORY','UNSAFE_TOOL_FILE','TOOL_LINK_MISMATCH','TOOL_LINK_ESCAPE','TOOL_INVENTORY_REJECTED','TOOL_INVENTORY_MISMATCH','TOOL_HASH_MISMATCH',
 'TOOL_VERSION_MISMATCH','LOCAL_TOOLING_MISSING','LOCAL_TOOLING_UNVERIFIED','EVIDENCE_NOT_IGNORED','UNSAFE_EVIDENCE_DIRECTORY',
 'REQUEST_GUARD_FAILED','UNAPPROVED_RESOURCE','UNAPPROVED_ORIGIN','PATH_REJECTED','APPLICATION_MUTATION_BLOCKED','UNAPPROVED_API','UNBOUNDED_HISTORY_BLOCKED',
 'API_QUERY_REJECTED','UNAPPROVED_PAGE','WEBSOCKET_NOT_APPROVED','POPUP_NOT_APPROVED','DOWNLOAD_NOT_APPROVED','EVENT_BOUND_EXCEEDED',
 'API_BODY_BOUND_UNVERIFIED','API_BODY_ENCODING_UNVERIFIED','API_BODY_BOUND_EXCEEDED','API_JSON_INVALID','OPERATIONS_STATUS_INVALID',
 'FORECAST_RESPONSE_INVALID','API_CAPTURE_FAILED','REQUIRED_API_RESPONSE_NOT_OBSERVED','UNEXPECTED_PAGE','AUTHENTICATION_FORM_VISIBLE',
 'NAVIGATION_FAILED','API_NO_STORE_MISSING','WITHHELD_CONTRACT','PUBLICATION_PROVENANCE_MISSING','INVALID_UTC','PUBLICATION_TIMING_INVALID',
 'FORECAST_ROWS_INVALID','OPERATIONS_UNAVAILABLE','OPERATIONS_DISAGREEMENT','ANALYST_OR_RENDER_UNVERIFIED','HISTORICAL_LABEL_MISSING',
 'DUPLICATE_FORECAST_STATUS','RESPONSIVE_CONTENT_CLIPPED','SENSITIVE_UI_DETECTED','LIVE_FORECAST_NOT_RENDERED','CHART_OR_TABLE_CONTRACT',
 'CHART_VALUES_UNVERIFIED','UI_API_VALUE_MISMATCH','UI_PROVENANCE_MISMATCH','FUTURE_TARGET_COUNT_MISMATCH','STALE_OR_INVENTED_FORECAST_VISIBLE',
 'OPERATIONS_UI_DISAGREEMENT','ANALYST_RESTRICTION_UI_MISSING','RESPONSIVE_OPERATIONS_CLIPPED','BROWSER_ERRORS_OBSERVED',
 'INCOMPLETE_VIEWPORT_ACCEPTANCE','NETWORK_FAILURES_OBSERVED','FRESHNESS_BOUNDARY_DURING_CHECK','RUN_DEADLINE','BROWSER_LAUNCH_FAILED','BROWSER_STEP_UNVERIFIED']);
