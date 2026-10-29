import type { ForecastReport, Next24Row, PipelineStatus } from './contracts.ts'

// Display classification only. The backend's configurable issuance threshold is
// not exposed by this API. This never changes backend eligibility or publishes data.
export const DISPLAY_RECENCY_HOURS = 3
export function classifyForecast(report: ForecastReport<Next24Row> | null, pipeline: PipelineStatus | null, now: number, errorCode?: string | null) {
  if (errorCode === 'FORECAST_WITHHELD') return {label: 'WITHHELD', description: 'No valid, unexpired forecast publication is available.'}
  if (report?.publication) {
    const issue = Date.parse(report.publication.issue_time), expires = Date.parse(report.publication.expires_at)
    if (now < issue || now > expires) return {label: 'WITHHELD', description: 'This forecast publication has expired or is not yet eligible.'}
    const remaining = report.forecasts.filter(row => Date.parse(row.target_time) > now).length
    return {label: 'Valid published forecast', description: `${remaining} of 24 issue-relative target hours remain future. Expires ${formatTime(report.publication.expires_at)}. Historical pipeline status is separate.`}
  }
  const status = pipeline?.forecast_status?.toUpperCase()
  if (status === 'WITHHELD' || status === 'UNAVAILABLE') return { label: status === 'WITHHELD' ? 'Withheld' : 'Unavailable', description: 'The latest recorded pipeline status reports no new forecast. Any retained report is reference data only; the API does not provide the detailed cause.' }
  if (!report) return { label: 'Unavailable', description: 'No usable 24-hour forecast report has been retrieved.' }
  const issue = Date.parse(report.forecasts[0].issue_time)
  const targets = report.forecasts.map(row => Date.parse(row.target_time))
  if (issue > now) return { label: 'Unverified', description: 'The reported issue time is in the future. Do not treat this report as current.' }
  if (Math.max(...targets) <= now) return { label: 'Historical', description: 'All target hours have passed. This report is historical reference, not a live forecast.' }
  if (now - issue > DISPLAY_RECENCY_HOURS * 3600000) return { label: 'Stale', description: 'Issue time exceeds the frontend’s 3-hour display recency window. This report is reference only.' }
  if (Math.min(...targets) <= now) return { label: 'Partly elapsed', description: 'Some target hours have passed. Review target times; the report is not a fully forward-looking 24-hour window.' }
  return { label: 'Recent report · unverified', description: 'Targets are forward-looking, but the API does not expose the configured freshness rule or a current availability attestation. Recent does not establish live eligibility.' }
}
export function formatTime(value: string | null | undefined) { return value ? new Date(value).toISOString().replace('T', ' ').replace('.000Z', ' UTC').replace(/Z$/, ' UTC') : 'Not provided' }
