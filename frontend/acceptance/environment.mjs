// Current-process KEY NAMES only. Never read, serialize or discard values.
import {requireThat} from './core.mjs';
export const BASE_ENV_KEYS = Object.freeze(['PATH','TMPDIR','LANG']);
export const DARWIN_RUNTIME_KEY = '__CF_USER_TEXT_ENCODING';
// Only public, fixed identifiers may be emitted. Unknown names may themselves
// contain secret data and are represented solely by a redacted count.
const PUBLIC_KEY_NAMES = new Set([...BASE_ENV_KEYS,DARWIN_RUNTIME_KEY,'HOME','PWD','SHLVL','_',
  'LC_CTYPE','LC_ALL','TERM','NODE_OPTIONS','NODE_PATH','NODE_V8_COVERAGE','NODE_CHANNEL_FD',
  'NODE_UNIQUE_ID','DEBUG','PWDEBUG','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','SSLKEYLOGFILE',
  'CHROME_LOG_FILE','AWS_PROFILE','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','ENTSOE_API_KEY']);
export function allowedEnvironmentKeys(platform=process.platform) {
  return [...BASE_ENV_KEYS,...(platform==='darwin'?[DARWIN_RUNTIME_KEY]:[])];
}
export function environmentKeyReport(environment=process.env,platform=process.platform) {
  const keys=Object.keys(environment),allowed=allowedEnvironmentKeys(platform);
  const unexpected=keys.filter(key=>!allowed.includes(key));
  return {allowedKeys:allowed,observedSafeKeys:keys.filter(key=>PUBLIC_KEY_NAMES.has(key)).sort(),
    unexpectedSafeKeys:unexpected.filter(key=>PUBLIC_KEY_NAMES.has(key)).sort(),
    redactedUnexpectedKeyCount:unexpected.filter(key=>!PUBLIC_KEY_NAMES.has(key)).length,
    legacyGuardAccepted:keys.every(key=>BASE_ENV_KEYS.includes(key)),
    accepted:unexpected.length===0};
}
export function assertCleanEnvironment(environment=process.env,platform=process.platform) {
  const allowed=allowedEnvironmentKeys(platform);
  requireThat(Object.keys(environment).every(key=>allowed.includes(key)),'CLEAN_ENV_REQUIRED');
}
