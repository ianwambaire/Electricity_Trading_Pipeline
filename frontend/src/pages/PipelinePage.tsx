import {CurrentOperations,CurrentAdminOperations} from '../components/data/CurrentOperations'
import { AdminOperations } from '../components/data/AdminOperations'
import { useServerAccount } from '../auth/serverAccountContext'
import { OperationalSummary, OperationsNotice } from '../components/data/OperationalSummary'
import { useClock } from '../hooks/useClock'
import { api } from '../api/client'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { PageHeading } from '../components/ui/PageHeading'
import {operationalForecastState} from '../api/operationalForecastState'

export function PipelinePage() {
  const fetchedOperations = useApi(api.operations)
  const now = useClock(fetchedOperations.data?.forecast_expires_at?Date.parse(fetchedOperations.data.forecast_expires_at):undefined)
  const operations = {...fetchedOperations,data:operationalForecastState(fetchedOperations.data,now)}
  const health = useApi(api.health)
  const pipeline = useApi(api.pipeline)
  const account = useServerAccount()
  return <><PageHeading category="Platform" title="Pipeline Operations" description="Review data coverage, recorded pipeline activity and forecast readiness." />
    <CurrentOperations/><OperationsNotice data={operations.data}/><OperationalSummary state={operations}/>
    <div className="mt-6"><ApiPanel title="Observed source health and data products" state={operations}>{data=><><p className="data-note">{data.completeness_note}</p><div className="table-scroll" tabIndex={0}><table><thead><tr><th>Source</th><th>Availability</th><th>Rows</th><th>Latest observation (UTC)</th><th>Freshness</th></tr></thead><tbody>{data.sources.map(source=><tr key={source.source}><td>{source.source}</td><td>{source.availability}</td><td>{source.rows ?? 'Unavailable'}</td><td>{formatTime(source.latest_observation)}</td><td>{source.freshness}</td></tr>)}</tbody></table></div><h3 className="subheading">Available data products</h3><div className="table-scroll" tabIndex={0}><table><thead><tr><th>Product</th><th>State</th></tr></thead><tbody>{data.products.map(product=><tr key={product.product}><td>{product.product === '24-hour predictions' ? 'Primary 24-hour predictions' : product.product}</td><td>{product.status.replaceAll('_',' ')}</td></tr>)}</tbody></table></div><h3 className="subheading">Recent quality checks · latest 20</h3>{data.quality_history.length?<div className="table-scroll" tabIndex={0}><table><thead><tr><th>Check time (UTC)</th><th>Public label</th><th>Status</th></tr></thead><tbody>{data.quality_history.map((check,i)=><tr key={i}><td>{formatTime(check.timestamp)}</td><td>{check.check}</td><td>{check.status}</td></tr>)}</tbody></table></div>:<p className="data-note">No quality evidence is available. This does not establish that checks passed.</p>}<div className="notice notice-warning"><strong>Detailed operations require Admin permission</strong><p>Bounded execution history, structured incidents and measured timings are shown below for server-confirmed Admin accounts. Raw messages and configuration are excluded.</p><p>Incidents: {data.incident_evidence}. Timings: {data.timing_evidence}.</p></div></>}</ApiPanel></div>
    <div className="detail-grid"><ApiPanel title="API reachability" state={health}>{data => <Facts items={[["Service response", data.status], ['Server timestamp', formatTime(data.timestamp_utc)]]} />}</ApiPanel>
      <ApiPanel title="Historical pipeline execution" state={pipeline}>{data => <><Facts items={[["Recorded run status", data.latest_run_status], ['Run time', formatTime(data.latest_run_timestamp)], ['Historical inference status', data.forecast_status ?? 'Not provided']]} /><p className="data-note">Run age: {Math.max(0, Math.floor((now - Date.parse(data.latest_run_timestamp)) / 3600000))} hours. Execution success and forecast availability are separate. Stage timings describe recorded executions, not forecast availability.</p></>}</ApiPanel></div>
    {account.account?.role === 'Admin' ? <div className="mt-6"><CurrentAdminOperations/><AdminOperations/></div> : <section className="restricted-section"><h2>Administrative monitoring</h2><p>{account.loading ? 'Verifying server permissions…' : account.error ? 'Unable to verify permissions. Retry account verification from My Profile.' : 'Admin permission is required for detailed operations.'}</p></section>}
  </>
}
