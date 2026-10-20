import { useClock } from '../hooks/useClock'
import { api } from '../api/client'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { PageHeading } from '../components/ui/PageHeading'

export function PipelinePage() {
  const now = useClock()
  const health = useApi(api.health)
  const pipeline = useApi(api.pipeline)
  const vintages = useApi(api.vintages)
  const readiness = useApi(api.readiness)
  return <><PageHeading category="Platform" title="Pipeline Operations" description="Separate service reachability, recorded execution, and forecast-data readiness." />
    <p className="data-note">Monitoring report timestamps may lag behind the current time. Only selected summary fields are displayed; paths, raw incidents, credentials, and report bodies are not shown.</p>
    <div className="detail-grid"><ApiPanel title="API reachability" state={health}>{data => <Facts items={[["Service response", data.status], ['Server timestamp', formatTime(data.timestamp_utc)]]} />}</ApiPanel>
      <ApiPanel title="Latest pipeline execution" state={pipeline}>{data => <><Facts items={[["Recorded run status", data.latest_run_status], ['Run time', formatTime(data.latest_run_timestamp)], ['Forecast status', data.forecast_status ?? 'Not provided']]} /><p className="data-note">Run age: {Math.max(0, Math.floor((now - Date.parse(data.latest_run_timestamp)) / 3600000))} hours. Execution success and forecast availability are separate. No run history or stage timing endpoint is available.</p></>}</ApiPanel></div>
    <div className="detail-grid"><ApiPanel title="Forecast-vintage monitoring" state={vintages}>{data => <><Facts items={[["Recorded overall status", data.overall_status], ['Report generated', formatTime(data.generated_at_utc)]]} /><div className="table-scroll"><table><thead><tr><th>Source</th><th>Recorded status</th><th>Last acquired (UTC)</th></tr></thead><tbody>{data.sources.map((source,i) => <tr key={i}><td>{source.source}</td><td>{source.status}</td><td>{formatTime(source.latest_acquired_at_utc)}</td></tr>)}</tbody></table></div>{!data.sources.length && <p className="data-note">No source entries were supplied.</p>}<p className="data-note">These statuses describe the report’s generation time, not necessarily current source health.</p></>}</ApiPanel>
      <ApiPanel title="Exogenous dataset readiness" state={readiness}>{data => <><Facts items={[["Dataset status", data.dataset_status], ['Report generated', formatTime(data.generated_at_utc)], ['Distinct issue cycles', data.distinct_issue_cycles], ['Calendar days', data.distinct_calendar_days], ['Complete cycles', data.complete_issue_cycles], ['Horizons covered', data.horizon_coverage_count], ['Output rows', data.output_rows]]} /><p className="data-note">Engineering readiness for offline evaluation does not establish model quality or production forecast availability.</p></>}</ApiPanel></div>
  </>
}
