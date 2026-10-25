import { downloadCsvText } from '../../api/csv'
import { numberLabel } from '../../api/numberLabel'
import { forecastStatistics, forecastCsv } from '../../api/forecastPresentation'
import { KpiGrid } from '../ui/KpiGrid'
import { useClock } from '../../hooks/useClock'
import type { ForecastReport, Next24Row, PipelineStatus } from '../../api/contracts'
import { classifyForecast, formatTime } from '../../api/forecastState'
import type { ApiState } from '../../hooks/useApi'
import { Facts } from './ApiPanel'

export function ForecastSummary({ report, pipeline }: { report: ForecastReport<Next24Row> | null; pipeline: ApiState<PipelineStatus> }) {
  const now = useClock()
  const state = classifyForecast(report, pipeline.data, now)
  const statistics = report ? forecastStatistics(report) : null
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
    {statistics && report && <><KpiGrid items={[
      {label:'Average · EUR/MWh',value:numberLabel(statistics.average)}, {label:'Median · EUR/MWh',value:numberLabel(statistics.median)},
      {label:'Minimum · EUR/MWh',value:numberLabel(statistics.minimum.predicted_price_eur_mwh),note:formatTime(statistics.minimum.target_time)},
      {label:'Maximum · EUR/MWh',value:numberLabel(statistics.maximum.predicted_price_eur_mwh),note:formatTime(statistics.maximum.target_time)},
      {label:'First-to-last change · EUR/MWh',value:numberLabel(statistics.change)}, {label:'Negative-price hours',value:String(statistics.negative)},
      {label:'Hours ≥ 200 EUR/MWh',value:String(statistics.elevated)}, {label:'Horizon',value:'h+1 to h+24'},
    ]}/>{(statistics.negative>0||statistics.elevated>0)&&<p className="notice notice-warning">This retained report includes {statistics.negative} negative-price hours and {statistics.elevated} hours at or above 200 EUR/MWh. Interpret these values with the availability label above.</p>}
    <button className="secondary-button" onClick={()=>downloadCsvText(`powerflow_${state.label.toLowerCase().replace(/[^a-z0-9]+/g,'_')}_${first!.issue_time.slice(0,10)}.csv`,forecastCsv(report,state.label))}>Download displayed report — {state.label}</button></>}
  </>
}
