import { test } from 'node:test'
import assert from 'node:assert/strict'
import { classifyForecast } from '../src/api/forecastState.ts'
import { parseHealth, parseNext24, parseOneHour, parsePipeline, parseReadiness, parseVintages } from '../src/api/contracts.ts'
import { ApiError, request } from '../src/api/client.ts'

// Synthetic contract fixtures are test-only and are never imported by the UI.
const issue = Date.parse('2026-10-01T10:00:00Z')
const fixture = { row_count: 24, forecasts: Array.from({ length: 24 }, (_,i) => ({ issue_time: new Date(issue).toISOString(), target_time: new Date(issue + (i+1)*3600000).toISOString(), horizon_hours: i+1, predicted_price_eur_mwh: i - 10, model_release: 'contract-test' })) }
const pipeline = parsePipeline({ latest_run_status: 'SUCCESS', latest_run_timestamp: new Date(issue).toISOString(), forecast_status: 'WITHHELD' })

test('next24 contract preserves negative prices and rejects malformed horizons, timestamps and nonfinite values', () => {
  assert.equal(parseNext24(fixture).forecasts[0].predicted_price_eur_mwh, -10)
  assert.throws(() => parseNext24({ ...fixture, row_count: 23 }))
  for (const replacement of [{ horizon_hours: 5 }, { target_time: 'bad' }, { predicted_price_eur_mwh: Infinity }, { model_release: 'secret/path' }, { issue_time: '2026-10-01T10:00:00' }]) {
    assert.throws(() => parseNext24({ ...fixture, forecasts: fixture.forecasts.map((r,i) => i ? r : { ...r, ...replacement }) }))
  }
})
test('withholding overrides retained data or missing data; historical/stale/recent remain distinct', () => {
  const report = parseNext24(fixture)
  assert.equal(classifyForecast(report, pipeline, issue).label, 'Withheld')
  assert.equal(classifyForecast(null, pipeline, issue).label, 'Withheld')
  assert.equal(classifyForecast(null, null, issue).label, 'Unavailable')
  assert.equal(classifyForecast(report, null, issue+25*3600000).label, 'Historical')
  assert.equal(classifyForecast(report, null, issue+4*3600000).label, 'Stale')
  assert.equal(classifyForecast(report, null, issue+2*3600000).label, 'Partly elapsed')
  assert.equal(classifyForecast(report, null, issue).label, 'Recent report · unverified')
  assert.equal(classifyForecast(report, null, issue-1).label, 'Unverified')
})
test('one-hour count and numeric validation; empty report is explicit', () => {
  assert.equal(parseOneHour({ row_count: 0, forecasts: [] }).row_count, 0)
  assert.throws(() => parseOneHour({ row_count: 1, forecasts: [] }))
  assert.throws(() => parseOneHour({ row_count: 1, forecasts: [{ target_time: new Date(issue).toISOString(), actual_price_eur_mwh: null, predicted_price_eur_mwh: 1 }] }))
})
test('monitoring parsers discard operational details and unknown fields', () => {
  const parsed = parseVintages({ generated_at_utc: new Date(issue).toISOString(), overall_status: 'STALE', local_path: '/secret', token: 'private', sources: [{ source: 'OPEN_METEO', status: 'STALE', latest_acquired_at_utc: null, reasons: ['private'], local_path: '/private' }] })
  assert.ok(!JSON.stringify(parsed).includes('private'))
  assert.ok(!JSON.stringify(parsed).includes('secret'))
  assert.throws(() => parseReadiness({ generated_at_utc: 'bad' }))
})
test('client uses /api, omits credentials, and does not display server errors; retry can succeed', async () => {
  const original = globalThis.fetch
  try {
    let calls = 0
    globalThis.fetch = async (input, options) => {
      assert.equal(input, '/api/health'); assert.equal(options?.credentials, 'omit'); calls++
      return calls === 1 ? new Response('{"detail":"private operational path"}', { status: 503 }) : Response.json({ status: 'ok', application: 'PowerFlow API', timestamp_utc: new Date(issue).toISOString() })
    }
    await assert.rejects(request('/health', parseHealth), error => error instanceof ApiError && error.status === 503 && !error.message.includes('private'))
    assert.equal((await request('/health', parseHealth)).status, 'ok')
    globalThis.fetch = async () => new Response('', { status: 404 })
    await assert.rejects(request('/health', parseHealth), error => error instanceof ApiError && error.status === 404)
    globalThis.fetch = async () => { throw new TypeError('private network detail') }
    await assert.rejects(request('/health', parseHealth), /Could not reach the API/)
    globalThis.fetch = async () => new Response('<html>proxy error</html>')
    await assert.rejects(request('/health', parseHealth), /unexpected or invalid/)
  } finally { globalThis.fetch = original }
})

test('monitoring success is parsed without unsafe unknown fields', () => {
  const r = parseReadiness({ generated_at_utc: new Date(issue).toISOString(), dataset_status: 'NOT_READY', distinct_issue_cycles: 0, distinct_calendar_days: 0, complete_issue_cycles: 0, horizon_coverage_count: 0, output_rows: 0, dataset: '/private/path' })
  assert.equal(r.output_rows, 0)
  assert.ok(!JSON.stringify(r).includes('private'))
  assert.equal(parsePipeline({ ...pipeline, latest_run_status: 'credential-like-unexpected-value' }).latest_run_status, 'Unrecognized status')
})
