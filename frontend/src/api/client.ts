import { parseAnomalySummary, parseAnomalyEvents, parseMarketSummary, parseMarketChart, parseOperations } from './restoration.ts'
import { parseCoverage, parseMarketHistory, parseModels } from './publicData.ts'
import { parseHealth, parseNext24, parseOneHour, parsePipeline, parseReadiness, parseVintages } from './contracts.ts'

export class ApiError extends Error {
  readonly status: number | null
  constructor(message: string, status: number | null = null) { super(message); this.name = 'ApiError'; this.status = status }
}

export async function request<T>(path: string, parse: (value: unknown) => T, signal?: AbortSignal): Promise<T> {
  try {
    const response = await fetch(`/api${path}`, { signal: AbortSignal.any([...(signal ? [signal] : []), AbortSignal.timeout(15000)]), headers: { Accept: 'application/json' }, cache: 'no-store', credentials: 'omit' })
    // Do not surface raw server/proxy bodies: operational details may be sensitive.
    if (!response.ok) throw new ApiError(response.status === 404 ? 'This report is not available from the API.' : response.status === 503 ? 'The backend report is unavailable or invalid.' : `API request failed (HTTP ${response.status}).`, response.status)
    try { return parse(await response.json()) } catch { throw new ApiError('The API returned an unexpected or invalid response.') }
  } catch (error) {
    if (signal?.aborted) throw error
    if (error instanceof ApiError) throw error
    throw new ApiError('Could not reach the API, or the request timed out. Check the local backend and try again.')
  }
}

export const api = {
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
  vintages: (signal?: AbortSignal) => request('/monitoring/forecast-vintages', parseVintages, signal),
  readiness: (signal?: AbortSignal) => request('/monitoring/exogenous-readiness', parseReadiness, signal),
}
