import { parseProfile, parseAccountAction, accountErrorMessages } from './profile.ts'
import { parseMfaSetup, parseMfaAction } from './mfa.ts'
import { parseInfluence, parseContext, parseExploration, parseRealized, parseAdminOperations, parsePriceComparison, parseForecastProvenance } from './parity.ts'
import { parseAccount } from './account.ts'
import { captureApiSession } from './accessToken.ts'
import { parseAnomalySummary, parseAnomalyEvents, parseMarketSummary, parseMarketChart, parseOperations } from './restoration.ts'
import { parseCoverage, parseMarketHistory, parseModels } from './publicData.ts'
import { parseHealth, parseNext24, parseOneHour, parsePipeline, parseReadiness, parseVintages } from './contracts.ts'

export class ApiError extends Error {
  readonly code: string | null
  readonly status: number | null
  constructor(message: string, status: number | null = null, code: string | null = null) { super(message); this.code = code; this.name = 'ApiError'; this.status = status }
}

export async function request<T>(path: string, parse: (value: unknown) => T, signal?: AbortSignal, change?: { method: 'PATCH' | 'POST'; body?: unknown }): Promise<T> {
  try {
    const session = captureApiSession()
    const response = await fetch(`/api${path}`, { signal: AbortSignal.any([...(signal ? [signal] : []), AbortSignal.timeout(path.startsWith('/account/') ? 30000 : 15000)]), method: change?.method ?? 'GET', body: change?.body === undefined ? undefined : JSON.stringify(change.body), headers: { Accept: 'application/json', ...(change?.body === undefined ? {} : {'Content-Type':'application/json'}), ...session.headers }, cache: 'no-store', credentials: 'omit', redirect: 'error' })
    const assertCurrent = () => { if (!session.isCurrent()) throw new ApiError('Your session changed. Refresh this section to continue.') }
    assertCurrent()
    if (response.status === 401) { session.reject(); throw new ApiError('Your session is no longer accepted. Sign in again.', 401) }
    if (!response.ok && path.startsWith('/account/')) {
      let code: string | null = null
      try { const body = await response.json(); const candidate = body?.detail?.code; if (typeof candidate === 'string' && Object.hasOwn(accountErrorMessages,candidate)) code = candidate } catch { /* Never display a raw response body. */ }
      throw new ApiError(code ? accountErrorMessages[code] : 'This account action could not be completed. Please try again.', response.status, code)
    }
    if (path === '/forecast/next24' && response.status === 503) {
      let withheld = false
      try { const body = await response.json(); withheld = body?.detail?.code === 'FORECAST_WITHHELD' } catch { /* Never expose raw bodies. */ }
      if (withheld) throw new ApiError('Forecast withheld because the publication is expired, invalid, or unavailable.', 503, 'FORECAST_WITHHELD')
    }
    if (response.status === 403) throw new ApiError('Your account does not have permission for this information.', 403)
    // Do not surface raw server/proxy bodies: operational details may be sensitive.
    if (!response.ok) throw new ApiError(response.status === 404 ? 'This report is not available from the API.' : response.status === 503 ? 'The backend report is unavailable or invalid.' : `API request failed (HTTP ${response.status}).`, response.status)
    const value = await response.json().catch(() => { throw new ApiError('The API returned an unexpected or invalid response.', null, path === '/forecast/next24' ? 'FORECAST_WITHHELD' : null) })
    assertCurrent()
    try { return parse(value) } catch { throw new ApiError('The API returned an unexpected or invalid response.', null, path === '/forecast/next24' ? 'FORECAST_WITHHELD' : null) }
  } catch (error) {
    if (signal?.aborted) throw error
    if (error instanceof ApiError) throw error
    throw new ApiError('Could not reach the API, or the request timed out. Check your connection and try again.')
  }
}

export const api = {
  startMfa: (signal?: AbortSignal) => request('/account/mfa/setup', parseMfaSetup, signal, {method:'POST'}),
  verifyMfa: (setup_ticket:string, code:string, signal?: AbortSignal) => request('/account/mfa/verify', parseMfaAction, signal, {method:'POST',body:{setup_ticket,code}}),
  cancelMfa: (setup_ticket:string, signal?: AbortSignal) => request('/account/mfa/cancel', parseMfaAction, signal, {method:'POST',body:{setup_ticket}}),
  accountProfile: (signal?: AbortSignal) => request('/account/profile', parseProfile, signal),
  updateProfile: (body: {name?:string;preferred_username?:string}, signal?: AbortSignal) => request('/account/profile', parseAccountAction, signal, {method:'PATCH',body}),
  changePassword: (body: {current_password:string;new_password:string}, signal?: AbortSignal) => request('/account/password', parseAccountAction, signal, {method:'POST',body}),
  signOutAll: (signal?: AbortSignal) => request('/account/sign-out-all', parseAccountAction, signal, {method:'POST'}),
  forecastProvenance: (signal?: AbortSignal) => request('/admin/forecast/provenance', parseForecastProvenance, signal),
  influence: (signal?: AbortSignal) => request('/admin/models/linear-feature-influence', parseInfluence, signal),
  adminOperations: (signal?: AbortSignal) => request('/admin/operations', parseAdminOperations, signal),
  exploration: (query: string, signal?: AbortSignal) => request(`/market/exploration${query ? `?${query}` : ''}`, parseExploration, signal),
  forecastContext: (issue: string, signal?: AbortSignal) => request(`/forecast/context?${new URLSearchParams({issue_time: issue})}`, parseContext, signal),
  priceComparison: (signal?: AbortSignal) => request('/market/price-comparison', parsePriceComparison, signal),
  realized: (signal?: AbortSignal) => request('/forecast/realized-evaluation', parseRealized, signal),
  me: (signal?: AbortSignal) => request('/auth/me', parseAccount, signal),
  marketStatistics: (query: string, signal?: AbortSignal) => request(`/market/summary${query ? `?${query}` : ''}`, parseMarketSummary, signal),
  marketSummary: (signal?: AbortSignal) => request('/market/summary', parseMarketSummary, signal),
  marketChart: (query: string, signal?: AbortSignal) => request(`/market/chart${query ? `?${query}` : ''}`, parseMarketChart, signal),
  anomalySummary: (query: string, signal?: AbortSignal) => request(`/anomalies/summary${query ? `?${query}` : ''}`, parseAnomalySummary, signal),
  anomalyEvents: (query: string, signal?: AbortSignal) => request(`/anomalies/events?${query}`, parseAnomalyEvents, signal),
  operations: (signal?: AbortSignal) => request('/operations/summary', parseOperations, signal),
  marketCoverage: (signal?: AbortSignal) => request('/market/coverage', parseCoverage, signal),
  marketHistory: (query: string, signal?: AbortSignal) => request(`/market/history${query ? `?${query}` : ''}`, parseMarketHistory, signal),
  models: (signal?: AbortSignal) => request('/models/summary', parseModels, signal),
  health: (signal?: AbortSignal) => request('/health', parseHealth, signal),
  pipeline: (signal?: AbortSignal) => request('/pipeline/status', parsePipeline, signal),
  next24: (signal?: AbortSignal) => request('/forecast/next24', parseNext24, signal),
  oneHour: (signal?: AbortSignal) => request('/forecast/one-hour', parseOneHour, signal),
  vintages: (signal?: AbortSignal) => request('/admin/monitoring/forecast-vintages', parseVintages, signal),
  readiness: (signal?: AbortSignal) => request('/admin/monitoring/exogenous-readiness', parseReadiness, signal),
}
