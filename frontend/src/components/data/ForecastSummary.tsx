import { useClock } from '../../hooks/useClock'
import type { ForecastReport, Next24Row, PipelineStatus } from '../../api/contracts'
import { classifyForecast, formatTime } from '../../api/forecastState'
import type { ApiState } from '../../hooks/useApi'
import { Facts } from './ApiPanel'

export function ForecastSummary({ report, pipeline }: { report: ForecastReport<Next24Row> | null; pipeline: ApiState<PipelineStatus> }) {
  const now = useClock()
  const state = classifyForecast(report, pipeline.data, now)
  const first = report?.forecasts[0]
  return <><div className="availability" role="status"><strong>{state.label}</strong><p>{state.description}</p></div>
    {pipeline.loading && <p className="data-note">Checking recorded pipeline availability…</p>}
    {pipeline.error && <p className="data-note">Pipeline availability could not be verified. Forecast report retrieval alone does not establish current availability.</p>}
    {pipeline.data && <p className="data-note">Availability source: latest recorded pipeline run, {formatTime(pipeline.data.latest_run_timestamp)}. Reported forecast status: {pipeline.data.forecast_status ?? 'Not provided'}. This status may itself be old.</p>}
    {first && <Facts items={[
      ['Model release', first.model_release], ['Issue time', formatTime(first.issue_time)],
      ['Target start', formatTime(first.target_time)], ['Target end', formatTime(report!.forecasts.at(-1)!.target_time)],
      ['Forecast rows', report!.row_count], ['Still future targets', report!.forecasts.filter(row => Date.parse(row.target_time) > now).length],
    ]} />}
  </>
}
