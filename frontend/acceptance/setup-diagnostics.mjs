// Setup diagnostics only: fixed enums, no raw errors, request data or URLs retained.
export const SETUP_STEPS=new Set(['LOAD_PLAYWRIGHT','LAUNCH_BROWSER','INSTALL_BROWSER_MONITOR','CREATE_CONTEXT','CONFIGURE_TIMEOUTS','CREATE_PAGE',
  'INSTALL_REQUEST_GUARD','INSTALL_WEBSOCKET_GUARD','INSTALL_EVENT_MONITOR','INITIAL_NAVIGATION','OWNER_SIGN_IN','VERIFY_ANALYST','VERIFY_ROLE','ACCEPTANCE_CHECKS','COMPLETE']);
export const SETUP_CATEGORIES=new Set(['PLAYWRIGHT_IMPORT_FAILURE','EXECUTABLE_LAUNCH_FAILURE','BROWSER_CONFIGURATION_FAILURE','CONTEXT_CREATION_FAILURE','PAGE_CREATION_FAILURE',
  'REQUEST_INTERCEPTION_FAILURE','EVENT_MONITORING_FAILURE','NAVIGATION_TIMEOUT','NETWORK_DNS_FAILURE','NETWORK_CONNECTION_FAILURE',
  'TLS_CERTIFICATE_FAILURE','UNEXPECTED_REDIRECT','REQUEST_POLICY_REJECTED','STAGING_HTTP_FAILURE','AUTHENTICATION_HTTP_FAILURE',
  'BROWSER_OR_PAGE_CLOSED','PLAYWRIGHT_TIMEOUT','UNEXPECTED_PLAYWRIGHT_EXCEPTION','SETUP_PREREQUISITE_REJECTED']);
const NETWORK=new Map([
  ['ERR_NAME_NOT_RESOLVED','NETWORK_DNS_FAILURE'],['ERR_DNS_TIMED_OUT','NETWORK_DNS_FAILURE'],
  ['ERR_CONNECTION_TIMED_OUT','NETWORK_CONNECTION_FAILURE'],['ERR_CONNECTION_REFUSED','NETWORK_CONNECTION_FAILURE'],
  ['ERR_CONNECTION_RESET','NETWORK_CONNECTION_FAILURE'],['ERR_CONNECTION_CLOSED','NETWORK_CONNECTION_FAILURE'],
  ['ERR_ADDRESS_UNREACHABLE','NETWORK_CONNECTION_FAILURE'],['ERR_NETWORK_CHANGED','NETWORK_CONNECTION_FAILURE'],
  ['ERR_INTERNET_DISCONNECTED','NETWORK_CONNECTION_FAILURE'],['ERR_TUNNEL_CONNECTION_FAILED','NETWORK_CONNECTION_FAILURE'],
  ['ERR_CERT_AUTHORITY_INVALID','TLS_CERTIFICATE_FAILURE'],['ERR_CERT_COMMON_NAME_INVALID','TLS_CERTIFICATE_FAILURE'],
  ['ERR_CERT_DATE_INVALID','TLS_CERTIFICATE_FAILURE'],['ERR_CERT_INVALID','TLS_CERTIFICATE_FAILURE'],['ERR_SSL_PROTOCOL_ERROR','TLS_CERTIFICATE_FAILURE'],
  ['ERR_TOO_MANY_REDIRECTS','UNEXPECTED_REDIRECT']]);
const POLICY_REASONS=new Set(['UNAPPROVED_RESOURCE','UNAPPROVED_ORIGIN','PATH_REJECTED','APPLICATION_MUTATION_BLOCKED','UNAPPROVED_API',
  'UNBOUNDED_HISTORY_BLOCKED','API_QUERY_REJECTED','UNAPPROVED_PAGE','WEBSOCKET_NOT_APPROVED','POPUP_NOT_APPROVED','DOWNLOAD_NOT_APPROVED']);
const RESOURCES=new Set(['STAGING_FORECAST','STAGING_HOME','STAGING_CALLBACK','STAGING_OTHER','STAGING_API','STAGING_ASSET',
  'APPROVED_AUTH','APPROVED_AUTH_OTHER','PUBLIC_OIDC_METADATA','UNKNOWN']);
const STAGING='https://staging.powerflowenergy.dev';
const COGNITO='https://us-east-1nloyfrvex.auth.us-east-1.amazoncognito.com';
export function resourceClass(raw) {
  try {
    const u=new URL(raw);
    if(u.origin===STAGING) {
      if(u.pathname==='/forecasting')return 'STAGING_FORECAST';
      if(u.pathname==='/')return 'STAGING_HOME';
      if(u.pathname==='/auth/callback')return 'STAGING_CALLBACK';
      if(u.pathname.startsWith('/api/'))return 'STAGING_API';
      if(/^\/(assets|fonts)\//.test(u.pathname))return 'STAGING_ASSET';
      return 'STAGING_OTHER';
    }
    if(u.origin===COGNITO)return ['/oauth2/authorize','/login','/mfa','/selectMfa'].includes(u.pathname)?'APPROVED_AUTH':'APPROVED_AUTH_OTHER';
    if(u.origin==='https://cognito-idp.us-east-1.amazonaws.com' && /^\/us-east-1_NLoYFRvex\/\.well-known\/(openid-configuration|jwks.json)$/.test(u.pathname))return 'PUBLIC_OIDC_METADATA';
  } catch { /* Never return a parser exception or input. */ }
  return 'UNKNOWN';
}
export function networkCode(text) {
  if(typeof text!=='string')return null;
  // Extract only exact public Chromium tokens. Never slice/retain other text.
  const found=text.match(/\bnet::(ERR_[A-Z_]+)\b/);
  return found&&NETWORK.has(found[1])?found[1]:null;
}
export function classifySetupError(error,state,ruleFailure=false) {
  if(state.policy)return 'REQUEST_POLICY_REJECTED';
  if(state.httpStatus>=400&&state.resource?.startsWith('STAGING_'))return 'STAGING_HTTP_FAILURE';
  if(state.httpStatus>=400&&state.resource?.startsWith('APPROVED_AUTH'))return 'AUTHENTICATION_HTTP_FAILURE';
  let name='',code='',text='';
  try {name=typeof error?.name==='string'?error.name:'';code=typeof error?.code==='string'?error.code:'';text=typeof error?.message==='string'?error.message:'';} catch { /* Unknown accessor failure is generic. */ }
  if(code==='UNEXPECTED_NAVIGATION_REDIRECT')return 'UNEXPECTED_REDIRECT';
  if(code==='REQUEST_GUARD_FAILED')return 'REQUEST_INTERCEPTION_FAILURE';
  if(code==='BROWSER_EVENT_MONITOR_FAILED')return 'EVENT_MONITORING_FAILURE';
  if(state.closed||name==='TargetClosedError'||/\b(?:Target page, context or browser|Page|Browser|Target|Connection) (?:has been |was )?closed\b/i.test(text))return 'BROWSER_OR_PAGE_CLOSED';
  const transport=state.networkCode??networkCode(text);
  if(transport)return NETWORK.get(transport);
  if(name==='TimeoutError')return state.step==='INITIAL_NAVIGATION'?'NAVIGATION_TIMEOUT':'PLAYWRIGHT_TIMEOUT';
  if(code==='INITIAL_NAVIGATION_HTTP_FAILURE')return state.resource==='APPROVED_AUTH'?'AUTHENTICATION_HTTP_FAILURE':'STAGING_HTTP_FAILURE';
  if(name==='Error'&&POLICY_REASONS.has(code))return 'REQUEST_POLICY_REJECTED';
  if(ruleFailure||code==='INITIAL_NAVIGATION_NO_RESPONSE')return 'SETUP_PREREQUISITE_REJECTED';
  return ({LOAD_PLAYWRIGHT:'PLAYWRIGHT_IMPORT_FAILURE',LAUNCH_BROWSER:'EXECUTABLE_LAUNCH_FAILURE',INSTALL_BROWSER_MONITOR:'EVENT_MONITORING_FAILURE',
    CREATE_CONTEXT:'CONTEXT_CREATION_FAILURE',CONFIGURE_TIMEOUTS:'BROWSER_CONFIGURATION_FAILURE',CREATE_PAGE:'PAGE_CREATION_FAILURE',
    INSTALL_REQUEST_GUARD:'REQUEST_INTERCEPTION_FAILURE',INSTALL_WEBSOCKET_GUARD:'REQUEST_INTERCEPTION_FAILURE',
    INSTALL_EVENT_MONITOR:'EVENT_MONITORING_FAILURE'})[state.step]??'UNEXPECTED_PLAYWRIGHT_EXCEPTION';
}
export function sanitizeSetup(state) {
  if(state==null)return null;
  const valid=SETUP_STEPS.has(state.step)&&(state.lastCompleted===null||SETUP_STEPS.has(state.lastCompleted))
    &&(state.category===null||SETUP_CATEGORIES.has(state.category))&&(state.networkCode===null||NETWORK.has(state.networkCode))
    &&(state.resource===null||RESOURCES.has(state.resource))&&(state.httpStatus===null||Number.isInteger(state.httpStatus)&&state.httpStatus>=100&&state.httpStatus<=599)
    &&typeof state.closed==='boolean'&&typeof state.redirected==='boolean'
    &&(state.policy===null||POLICY_REASONS.has(state.policy));
  if(!valid)throw Error('SETUP_REPORT_REJECTED');
  return {step:state.step,lastCompleted:state.lastCompleted,category:state.category,networkCode:state.networkCode,
    resource:state.resource,httpStatus:state.httpStatus,redirected:state.redirected,closed:state.closed,policy:state.policy};
}
export function createSetupDiagnostic() {
  const state={step:'LOAD_PLAYWRIGHT',lastCompleted:null,category:null,networkCode:null,resource:null,httpStatus:null,redirected:false,closed:false,policy:null};
  let cleanup=false;
  return {state,
    async run(step,operation) {
      if(!SETUP_STEPS.has(step))throw Error('SETUP_STEP_REJECTED');
      state.step=step;
      const value=await operation();state.lastCompleted=step;return value;
    },
    rejectPolicy(code,url,redirected=false) {
      if(cleanup)return;
      if(!POLICY_REASONS.has(code))return;
      state.policy??=code;state.resource=resourceClass(url);state.redirected||=Boolean(redirected);
    },
    requestFailed(text,url) {
      if(cleanup||state.step!=='INITIAL_NAVIGATION')return;
      state.networkCode??=networkCode(text);state.resource=resourceClass(url);
    },
    navigationResponse(status,url,redirected=false) {
      if(cleanup||state.step!=='INITIAL_NAVIGATION')return;
      if(Number.isInteger(status)&&status>=100&&status<=599)state.httpStatus=status;
      state.resource=resourceClass(url);state.redirected||=Boolean(redirected);
    },
    finishNavigation(response,url) {
      if(!response)throw Object.assign(Error('INITIAL_NAVIGATION_NO_RESPONSE'),{code:'INITIAL_NAVIGATION_NO_RESPONSE'});
      const target=resourceClass(url);state.resource=target;
      const status=response.status();state.httpStatus=Number.isInteger(status)&&status>=100&&status<=599?status:null;
      if(!['STAGING_FORECAST','STAGING_HOME','STAGING_CALLBACK','APPROVED_AUTH'].includes(target))throw Object.assign(Error('UNEXPECTED_NAVIGATION_REDIRECT'),{code:'UNEXPECTED_NAVIGATION_REDIRECT'});
      if(state.httpStatus===null||state.httpStatus>=400)throw Object.assign(Error('INITIAL_NAVIGATION_HTTP_FAILURE'),{code:'INITIAL_NAVIGATION_HTTP_FAILURE'});
    },
    closed(){if(!cleanup)state.closed=true;},cleanup(){cleanup=true;},
    failure(error,ruleFailure=false){state.category=classifySetupError(error,state,ruleFailure);if(!state.networkCode){try{state.networkCode=networkCode(error?.message);}catch{}}return sanitizeSetup(state);},
    snapshot(){return sanitizeSetup(state);}
  };
}
