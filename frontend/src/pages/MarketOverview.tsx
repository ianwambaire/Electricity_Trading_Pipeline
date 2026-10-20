import { useClock } from '../hooks/useClock'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { ForecastSummary } from '../components/data/ForecastSummary'
import { PageHeading } from '../components/ui/PageHeading'

export function MarketOverview() {
  const now = useClock()
  const health = useApi(api.health)
  const pipeline = useApi(api.pipeline)
  const forecast = useApi(api.next24)
  return <>
    <PageHeading title="Market Overview" description="Recorded system activity and forecast availability, sourced from the PowerFlow API." />
    <p className="data-note">Live API responses can contain historical reports. Fetch time and source time are shown separately. All times are UTC.</p>
    <div className="metric-grid">{['Electricity price · EUR/MWh', 'System load · MW', 'Renewable generation · MW'].map(label => <section className="metric-card" key={label}><h2>{label}</h2><p className="metric-value" aria-label="Unavailable">—</p><p className="metric-caption">Not exposed by the existing API</p></section>)}</div>
    <div className="detail-grid"><ApiPanel title="API service" state={health}>{data => <><Facts items={[["Application", data.application], ['Service response', data.status], ['Server timestamp', formatTime(data.timestamp_utc)]]} /><p className="data-note">Service reachability does not establish pipeline health or forecast freshness.</p></>}</ApiPanel>
      <ApiPanel title="Latest recorded pipeline run" state={pipeline}>{data => <><Facts items={[["Execution status", data.latest_run_status], ['Run timestamp', formatTime(data.latest_run_timestamp)], ['Forecast status', data.forecast_status ?? 'Not provided']]} /><p className="data-note">Age of latest run: {Math.max(0, Math.floor((now - Date.parse(data.latest_run_timestamp)) / 3600000))} hours. A successful old run is not current health.</p><Link className="text-link" to="/pipeline">Inspect operations <ArrowRight size={15} /></Link></>}</ApiPanel></div>
    <div className="mt-6"><ApiPanel title="24-hour forecast report" description="Availability and issue context; retained data is never silently treated as live." state={forecast}>{data => <><ForecastSummary report={data} pipeline={pipeline} /><Facts items={[["Report average (EUR/MWh)", (data.forecasts.reduce((sum,row) => sum + row.predicted_price_eur_mwh, 0) / data.row_count).toFixed(2)]]} /><Link className="text-link" to="/forecasting">Inspect forecast targets <ArrowRight size={15} /></Link></>}</ApiPanel></div>
    {!forecast.loading && !forecast.data && <ForecastSummary report={null} pipeline={pipeline} />}
  </>
}
