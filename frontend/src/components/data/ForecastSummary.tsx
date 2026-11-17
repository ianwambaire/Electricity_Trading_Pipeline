import type { ReactNode } from 'react'
import { Download } from 'lucide-react'
import { downloadCsvText } from '../../api/csv'
import { numberLabel } from '../../api/numberLabel'
import { forecastStatistics, forecastCsv } from '../../api/forecastPresentation'
import { KpiGrid } from '../ui/KpiGrid'
import { useClock } from '../../hooks/useClock'
import type { ForecastReport, Next24Row, PipelineStatus } from '../../api/contracts'
import { classifyForecast, formatTime, PRICE_ONLY_FALLBACK_RELEASE } from '../../api/forecastState'
import type { ApiState } from '../../hooks/useApi'
import { Facts } from './ApiPanel'

export function ForecastSummary({ report, pipeline, errorCode, children }: { errorCode?: string | null; report: ForecastReport<Next24Row> | null; pipeline: ApiState<PipelineStatus>; children?: ReactNode }) {
  const now = useClock(report?.publication ? Date.parse(report.publication.expires_at) : undefined)
  const state = classifyForecast(report, pipeline.data, now, errorCode)
  const visibleReport = state.label === 'WITHHELD' ? null : report
  const statistics = visibleReport ? forecastStatistics(visibleReport) : null
  const first = visibleReport?.forecasts[0]
  const future = visibleReport?.forecasts.filter(row => Date.parse(row.target_time) > now).length
  return <><section className="availability forecast-status">
    <div role="status"><strong>{state.label}</strong><p>{state.description}</p></div>
    {first && visibleReport && <button className="secondary-button" onClick={() => downloadCsvText(
      `powerflow_forecast_${first.issue_time.slice(0, 10)}.csv`, forecastCsv(visibleReport, state.label)
    )}><Download size={16} aria-hidden="true" /> Download CSV</button>}
  </section>
    {children}
    {first && visibleReport && <details className="methodology forecast-issue-details">
      <summary>Forecast details · {future} of {visibleReport.row_count} hours ahead</summary>
      <Facts items={[
      ['Model release', first.model_release], ['Issue time', formatTime(first.issue_time)],
      ...(visibleReport?.publication ? [
        [first.model_release === PRICE_ONLY_FALLBACK_RELEASE ? 'Forecast completed' : 'Inference completed', formatTime(visibleReport.publication.completed_at)],
        [visibleReport.publication.availability_policy === 'ISSUE_HORIZON_V1' ? 'Forecast horizon expiry' : 'Freshness cutoff', formatTime(visibleReport.publication.expires_at)],
        ...(visibleReport.publication.refresh_due_at ? [['Refresh expected by',formatTime(visibleReport.publication.refresh_due_at)]] : []),
      ] as [string,string][] : []),
      ['Target start', formatTime(first.target_time)], ['Target end', formatTime(visibleReport.forecasts.at(-1)!.target_time)],
      ['Forecast rows · full issued horizon', visibleReport.row_count], ['Future targets', future ?? 0],
      ]} />
    </details>}
    {statistics && <div className="forecast-metrics"><h2>Issued forecast statistics</h2><p className="data-note">All target hours, including elapsed hours.</p><KpiGrid items={[
      {label:'Average · EUR/MWh',value:numberLabel(statistics.average)}, {label:'Median · EUR/MWh',value:numberLabel(statistics.median)},
      {label:'Minimum · EUR/MWh',value:numberLabel(statistics.minimum.predicted_price_eur_mwh),note:formatTime(statistics.minimum.target_time)},
      {label:'Maximum · EUR/MWh',value:numberLabel(statistics.maximum.predicted_price_eur_mwh),note:formatTime(statistics.maximum.target_time)},
    ]}/></div>}
    {!report?.publication && pipeline.loading && <p className="data-note">Loading pipeline status…</p>}
    {!report?.publication && pipeline.error && <p className="data-note">Pipeline history unavailable.</p>}
    {pipeline.data && <details className="methodology">
      <summary>Pipeline history</summary>
      <p>Historical pipeline snapshot (not current publication availability): {formatTime(pipeline.data.latest_run_timestamp)}. Forecast status: {pipeline.data.forecast_status ?? 'Unknown'}.</p>
    </details>}
  </>
}
