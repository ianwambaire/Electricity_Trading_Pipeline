export interface Health { status: string; application: string; timestamp_utc: string }
export interface PipelineStatus { latest_run_status: string; latest_run_timestamp: string; forecast_status: string | null }
export interface Next24Row { issue_time: string; target_time: string; horizon_hours: number; predicted_price_eur_mwh: number; model_release: string }
export interface OneHourRow { target_time: string; actual_price_eur_mwh: number; predicted_price_eur_mwh: number }
export interface ForecastPublication { status: 'VALID'; issue_time: string; expires_at: string; completed_at: string }
export interface ForecastReport<T> { row_count: number; forecasts: T[]; publication?: ForecastPublication }
export interface VintageHealth { generated_at_utc: string; overall_status: string; sources: { source: string; status: string; latest_acquired_at_utc: string | null; expected_target_count: number|null; observed_target_count: number|null; missing_target_count: number|null; duplicate_identity_count: number|null; revision_count: number|null; consecutive_collection_failures: number|null; s3_sync_status: string|null }[] }
export interface Readiness { generated_at_utc: string; dataset_status: string; distinct_issue_cycles: number; distinct_calendar_days: number; complete_issue_cycles: number; horizon_coverage_count: number; output_rows: number; duplicate_key_count: number|null; leakage_check_passed: boolean|null }

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid response')
  return value as Record<string, unknown>
}
function text(value: unknown): string { if (typeof value !== 'string' || !value.trim()) throw new Error('Invalid text'); return value }
function number(value: unknown): number { if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Invalid number'); return value }
function count(value: unknown): number { const n = number(value); if (!Number.isInteger(n) || n < 0) throw new Error('Invalid count'); return n }
function time(value: unknown): string { const s = text(value); if (!/(Z|[+-]\d{2}:\d{2})$/.test(s) || !Number.isFinite(Date.parse(s))) throw new Error('Invalid timestamp'); return s }
function list(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error('Invalid list'); return value }
function status(value: unknown): string {
  const s = text(value)
  const known = ['OK', 'SUCCESS', 'FAILED', 'FAILURE', 'WARNING', 'RUNNING', 'PENDING', 'COMPLETED', 'HEALTHY', 'DEGRADED', 'STALE', 'WITHHELD', 'UNAVAILABLE', 'GENERATED', 'UNCHANGED', 'FRESH', 'NOT_READY', 'PARTIALLY_READY', 'READY_FOR_EVALUATION', 'UNKNOWN']
  return known.includes(s.toUpperCase()) ? s : 'Unrecognized status'
}
export function parseHealth(value: unknown): Health { const v = record(value); return { status: status(v.status), application: v.application === 'PowerFlow API' ? v.application : 'API service', timestamp_utc: time(v.timestamp_utc) } }
export function parsePipeline(value: unknown): PipelineStatus { const v = record(value); return { latest_run_status: status(v.latest_run_status), latest_run_timestamp: time(v.latest_run_timestamp), forecast_status: v.forecast_status == null ? null : status(v.forecast_status) } }
export function parseNext24(value: unknown): ForecastReport<Next24Row> {
  const v = record(value)
  const rows = list(v.forecasts).map((item, i) => {
    const r = record(item); const issue = time(r.issue_time); const target = time(r.target_time)
    const horizon = count(r.horizon_hours); const release = text(r.model_release)
    if (horizon !== i + 1 || Date.parse(target) !== Date.parse(issue) + horizon * 3600000 || !/^[a-zA-Z0-9._-]{1,120}$/.test(release)) throw new Error('Invalid forecast contract')
    return { issue_time: issue, target_time: target, horizon_hours: horizon, predicted_price_eur_mwh: number(r.predicted_price_eur_mwh), model_release: release }
  })
  if (count(v.row_count) !== 24 || rows.length !== 24 || new Set(rows.map(r => r.issue_time)).size !== 1 || new Set(rows.map(r => r.model_release)).size !== 1) throw new Error('Invalid forecast report')
  let publication: ForecastPublication | undefined
  if (v.publication != null) {
    const p = record(v.publication)
    const issue = time(p.issue_time), expires = time(p.expires_at), completed = time(p.completed_at)
    if (p.status !== 'VALID' || Date.parse(issue) !== Date.parse(rows[0].issue_time) || Date.parse(expires) !== Date.parse(issue) + 3 * 3600000 || Date.parse(completed) < Date.parse(issue)) throw new Error('Invalid publication')
    publication = {status: 'VALID', issue_time: issue, expires_at: expires, completed_at: completed}
  }
  return { row_count: 24, forecasts: rows, ...(publication ? {publication} : {}) }
}
export function parseOneHour(value: unknown): ForecastReport<OneHourRow> {
  const v = record(value)
  const rows = list(v.forecasts).map(item => { const r = record(item); return { target_time: time(r.target_time), actual_price_eur_mwh: number(r.actual_price_eur_mwh), predicted_price_eur_mwh: number(r.predicted_price_eur_mwh) } })
  if (count(v.row_count) !== rows.length) throw new Error('Invalid row count')
  return { row_count: rows.length, forecasts: rows.sort((a,b) => Date.parse(a.target_time) - Date.parse(b.target_time)) }
}
export function parseVintages(value: unknown): VintageHealth {
  const v = record(value)
  // Deliberately discard paths, document identifiers, raw reasons and unknown fields.
  const sources = list(v.sources).map(item => { const s = record(item); const name = text(s.source); return { source: ['ENTSOE_TOTAL_LOAD', 'ENTSOE_WIND_SOLAR_DAY_AHEAD', 'ENTSOE_WIND_SOLAR_INTRADAY', 'ENTSOE_TOTAL_GENERATION', 'OPEN_METEO'].includes(name) ? name : 'Forecast source', status: status(s.status), latest_acquired_at_utc: s.latest_acquired_at_utc == null ? null : time(s.latest_acquired_at_utc), expected_target_count: optionalCount(s.expected_target_count), observed_target_count: optionalCount(s.observed_target_count), missing_target_count: optionalCount(s.missing_target_count), duplicate_identity_count: optionalCount(s.duplicate_identity_count), revision_count: optionalCount(s.revision_count), consecutive_collection_failures: optionalCount(s.consecutive_collection_failures), s3_sync_status: s.s3_sync_status == null ? null : status(s.s3_sync_status) } })
  return { generated_at_utc: time(v.generated_at_utc), overall_status: status(v.overall_status), sources }
}
function optionalCount(value: unknown): number|null { return value == null ? null : count(value) }
export function parseReadiness(value: unknown): Readiness { const v = record(value); if(v.leakage_check_passed != null && typeof v.leakage_check_passed !== 'boolean')throw Error('Invalid leakage audit'); if(count(v.horizon_coverage_count)>24)throw Error('Invalid horizon coverage'); return { generated_at_utc: time(v.generated_at_utc), dataset_status: status(v.dataset_status), distinct_issue_cycles: count(v.distinct_issue_cycles), distinct_calendar_days: count(v.distinct_calendar_days), complete_issue_cycles: count(v.complete_issue_cycles), horizon_coverage_count: count(v.horizon_coverage_count), output_rows: count(v.output_rows), duplicate_key_count: optionalCount(v.duplicate_key_count), leakage_check_passed: v.leakage_check_passed == null ? null : v.leakage_check_passed as boolean } }
