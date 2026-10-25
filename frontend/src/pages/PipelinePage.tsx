import { AdminOperations } from '../components/data/AdminOperations'
import { useServerAccount } from '../auth/serverAccountContext'
import { OperationalSummary, OperationsNotice } from '../components/data/OperationalSummary'
import { useClock } from '../hooks/useClock'
import { api } from '../api/client'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { PageHeading } from '../components/ui/PageHeading'

export function PipelinePage() {
  const now = useClock()
  const operations = useApi(api.operations)
  const health = useApi(api.health)
  const pipeline = useApi(api.pipeline)
  const account = useServerAccount()
  return <><PageHeading category="Platform" title="Pipeline Operations" description="Separate service reachability, recorded execution, and forecast-data readiness." />
    <OperationsNotice data={operations.data}/><OperationalSummary state={operations}/>
    <div className="mt-6"><ApiPanel title="Observed source health and data products" state={operations}>{data=><><p className="data-note">{data.completeness_note}</p><div className="table-scroll" tabIndex={0}><table><thead><tr><th>Source</th><th>Availability</th><th>Rows</th><th>Latest observation (UTC)</th><th>Freshness</th></tr></thead><tbody>{data.sources.map(source=><tr key={source.source}><td>{source.source}</td><td>{source.availability}</td><td>{source.rows ?? 'Unavailable'}</td><td>{formatTime(source.latest_observation)}</td><td>{source.freshness}</td></tr>)}</tbody></table></div><h3 className="subheading">Available data products</h3><div className="table-scroll" tabIndex={0}><table><thead><tr><th>Product</th><th>State</th></tr></thead><tbody>{data.products.map(product=><tr key={product.product}><td>{product.product}</td><td>{product.status.replaceAll('_',' ')}</td></tr>)}</tbody></table></div><h3 className="subheading">Recent quality checks · latest 20</h3>{data.quality_history.length?<div className="table-scroll" tabIndex={0}><table><thead><tr><th>Check time (UTC)</th><th>Public label</th><th>Status</th></tr></thead><tbody>{data.quality_history.map((check,i)=><tr key={i}><td>{formatTime(check.timestamp)}</td><td>{check.check}</td><td>{check.status}</td></tr>)}</tbody></table></div>:<p className="data-note">No quality evidence is available. This does not establish that checks passed.</p>}<div className="notice notice-warning"><strong>Detailed operations require Admin permission</strong><p>Bounded execution history, structured incidents and measured timings are shown below for server-confirmed Admin accounts. Raw messages and configuration are excluded.</p><p>Incidents: {data.incident_evidence}. Timings: {data.timing_evidence}.</p></div></>}</ApiPanel></div>
    <p className="data-note">Monitoring report timestamps may lag behind the current time. Only selected summary fields are displayed; paths, raw incidents, credentials, and report bodies are not shown.</p>
    <div className="detail-grid"><ApiPanel title="API reachability" state={health}>{data => <Facts items={[["Service response", data.status], ['Server timestamp', formatTime(data.timestamp_utc)]]} />}</ApiPanel>
      <ApiPanel title="Latest pipeline execution" state={pipeline}>{data => <><Facts items={[["Recorded run status", data.latest_run_status], ['Run time', formatTime(data.latest_run_timestamp)], ['Forecast status', data.forecast_status ?? 'Not provided']]} /><p className="data-note">Run age: {Math.max(0, Math.floor((now - Date.parse(data.latest_run_timestamp)) / 3600000))} hours. Execution success and forecast availability are separate. Administrative history and measured stage timings are separate from forecast issuance.</p></>}</ApiPanel></div>
    {account.account?.role === 'Admin' ? <><div className="mt-6"><AdminOperations/></div><AdminMonitoring/></> : <section className="restricted-section"><h2>Administrative monitoring</h2><p>{account.loading ? 'Verifying server permissions…' : account.error ? 'Unable to verify permissions. Retry account verification from My Profile.' : 'Admin permission is required for detailed operations, forecast-vintage monitoring and exogenous readiness.'}</p></section>}
  </>
}

function AdminMonitoring() {
  const vintages = useApi(api.vintages)
  const readiness = useApi(api.readiness)
  return (
    <div className="detail-grid"><ApiPanel title="Forecast-vintage monitoring" state={vintages}>{data => <><Facts items={[["Recorded overall status", data.overall_status], ['Report generated', formatTime(data.generated_at_utc)]]} /><div className="table-scroll" tabIndex={0}><table><thead><tr><th>Source</th><th>Recorded status</th><th>Last acquired (UTC)</th><th>Expected / observed targets</th><th>Missing</th><th>Duplicates</th><th>Revisions</th><th>Consecutive failures</th><th>Sync</th></tr></thead><tbody>{data.sources.map((source,i) => <tr key={i}><td>{source.source}</td><td>{source.status}</td><td>{formatTime(source.latest_acquired_at_utc)}</td><td>{source.expected_target_count??'Unknown'} / {source.observed_target_count??'Unknown'}</td><td>{source.missing_target_count??'Unknown'}</td><td>{source.duplicate_identity_count??'Unknown'}</td><td>{source.revision_count??'Unknown'}</td><td>{source.consecutive_collection_failures??'Unknown'}</td><td>{source.s3_sync_status??'Not recorded'}</td></tr>)}</tbody></table></div>{!data.sources.length && <p className="data-note">No source entries were supplied.</p>}<p className="data-note">These statuses describe the report’s generation time, not necessarily current source health.</p></>}</ApiPanel>
      <ApiPanel title="Exogenous dataset readiness" state={readiness}>{data => <><Facts items={[["Dataset status", data.dataset_status], ['Report generated', formatTime(data.generated_at_utc)], ['Distinct issue cycles', data.distinct_issue_cycles], ['Calendar days', data.distinct_calendar_days], ['Complete cycles', data.complete_issue_cycles], ['Horizons covered', data.horizon_coverage_count], ['Output rows', data.output_rows], ['Duplicate keys',data.duplicate_key_count??'Not recorded'], ['Leakage audit',data.leakage_check_passed===null?'Not recorded':data.leakage_check_passed?'Passed':'Failed']]} /><p className="data-note">Engineering readiness for offline evaluation does not establish model quality or production forecast availability.</p></>}</ApiPanel></div>
  )
}
