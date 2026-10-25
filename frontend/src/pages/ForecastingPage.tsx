import { useServerAccount } from '../auth/serverAccountContext'
import { rmseImprovement } from '../api/parity'
import { ForecastInputContext, RealizedForecastEvaluation, ObservedPriceComparison, ForecastProvenanceEvidence } from '../components/data/ForecastEvidence'
import { downloadCsv } from '../api/csv'
import { Facts as ModelFacts } from '../components/data/ApiPanel'
import { api } from '../api/client'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { ForecastSummary } from '../components/data/ForecastSummary'
import { lazy, Suspense } from 'react'
import { PageHeading } from '../components/ui/PageHeading'
import { EmptyState, LoadingState } from '../components/ui/States'

const ForecastChart = lazy(() => import('../components/data/ForecastChart').then(module => ({ default: module.ForecastChart })))

export function ForecastingPage() {
  const server = useServerAccount()
  const observed = useApi(api.marketSummary)
  const operations = useApi(api.operations)
  const models = useApi(api.models)
  const next24 = useApi(api.next24)
  const pipeline = useApi(api.pipeline)
  const oneHour = useApi(api.oneHour, 0)
  return <><PageHeading title="Forecast Intelligence" description="Inspect persisted model predictions, target times, and availability evidence." />
    <p className="data-note">No model is run in this browser. Forecast reports are persisted evidence, not a browser model run. Exact issue-hour context and realized evaluation are separate read-only reports; missing evidence is never substituted. Frozen release evaluation is also available in Model Insights.</p>
    {operations.data?.forecast_reason && <div className="notice notice-warning"><strong>Recorded forecast availability</strong><p>{operations.data.forecast_reason}</p><p>{operations.data.forecast_reason_provenance}</p></div>}
    {observed.data?.coverage.latest_observation && <div className="mt-6"><ForecastInputContext observed issue={observed.data.coverage.latest_observation}/></div>}
    <ForecastSummary report={next24.data} pipeline={pipeline} />
    {pipeline.error && <button className="secondary-button mb-4" onClick={pipeline.retry}>Retry availability check</button>}
    <ApiPanel title="24-hour forecast report" description="Report issue time and target hours determine whether values are recent, stale, or historical." state={next24}>{data => <Suspense fallback={<LoadingState label="Loading chart…" />}><ForecastChart rows={data.forecasts} issueTime={data.forecasts[0].issue_time} observed={observed.data?.latest_observation?.price_eur_mwh != null ? {timestamp:observed.data.latest_observation.timestamp,price:observed.data.latest_observation.price_eur_mwh} : null} /></Suspense>}</ApiPanel>
    <div className="mt-6"><ObservedPriceComparison forecastAverage={next24.data?next24.data.forecasts.reduce((sum,r)=>sum+r.predicted_price_eur_mwh,0)/next24.data.row_count:null}/></div>
    <div className="mt-6">{next24.data ? <ForecastInputContext issue={next24.data.forecasts[0].issue_time}/> : <EmptyState awaitingIntegration={false} title="Issue-hour context unavailable" description="A valid forecast issue time is required. No latest-hour input vector is substituted."/>}</div>
    {server.account?.role==='Admin' && next24.data && <div className="mt-6"><ForecastProvenanceEvidence/></div>}
    <div className="mt-6"><RealizedForecastEvaluation/></div>
    <div className="mt-6"><ApiPanel title="Historical one-hour actual vs predicted" description="Recorded predictions with observed outcomes; this is not a live one-hour forecast." state={oneHour}>{data => data.row_count ? <><Facts items={[["Available records", data.row_count], ['First target', formatTime(data.forecasts[0].target_time)], ['Last target', formatTime(data.forecasts.at(-1)!.target_time)]]} /><p className="data-note">The API does not identify the one-hour model release or its evaluation period. No evaluation metrics are inferred from this report.</p><button className="secondary-button" onClick={()=>downloadCsv('powerflow_historical_one_hour_predictions.csv',[['target_time_utc','actual_price_eur_mwh','predicted_price_eur_mwh','classification'],...data.forecasts.map(row=>[row.target_time,row.actual_price_eur_mwh,row.predicted_price_eur_mwh,'Historical one-hour predictions; release not identified by this report'])])}>Export all available historical one-hour records</button><Suspense fallback={<LoadingState label="Loading chart…" />}><ForecastChart historical rows={data.forecasts.slice(-500)} /></Suspense></> : <EmptyState awaitingIntegration={false} title="No one-hour records" description="The report contains no forecast records." />}</ApiPanel></div>
    <div className="mt-6"><ApiPanel title="Separate one-hour Linear Regression — frozen holdout evaluation" state={models}>{data=>{const model=data.models.find(item=>item.key==='one_hour');return model?.evaluations.length?<><p className="data-note">This evaluation covers the frozen holdout period, not every historical record above and not the next24h production model. The original evaluation notes weaker performance during extreme price events at or above 200 EUR/MWh.</p>{model.evaluations.map(e=><ModelFacts key={e.split} items={[["Model",model.name ?? 'Unavailable'],['MAE (EUR/MWh)',e.mae.toFixed(2)],['RMSE (EUR/MWh)',e.rmse.toFixed(2)],['R²',e.r2.toFixed(3)],['RMSE improvement versus same-period persistence · %',rmseImprovement(e.rmse,e.persistence_rmse)?.toFixed(2)??'Unavailable'],['Evaluation starts',formatTime(e.period_start)],['Evaluation ends',formatTime(e.period_end)]]}/>)}</>:<EmptyState awaitingIntegration={false} title="Evaluation evidence unavailable" description="No metrics are invented or substituted from another model."/>}}</ApiPanel></div>
  </>
}
