import { useClock } from '../hooks/useClock'
import { publicationState } from '../api/publicationState'
import { useServerAccount } from '../auth/serverAccountContext'
import { rmseImprovement } from '../api/parity'
import { ForecastInputContext, RealizedForecastEvaluation, ObservedPriceComparison, ForecastProvenanceEvidence } from '../components/data/ForecastEvidence'
import { downloadCsv } from '../api/csv'
import { Facts as ModelFacts } from '../components/data/ApiPanel'
import { api } from '../api/client'
import { formatTime, PRICE_ONLY_FALLBACK_RELEASE } from '../api/forecastState'
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
  const fetchedNext24 = useApi(api.next24)
  const now = useClock(fetchedNext24.data?.publication ? Date.parse(fetchedNext24.data.publication.expires_at) : undefined)
  const next24 = publicationState(fetchedNext24, now)
  const priceOnly = next24.data?.forecasts[0].model_release === PRICE_ONLY_FALLBACK_RELEASE
  const pipeline = useApi(api.pipeline)
  const oneHour = useApi(api.oneHour, 0)
  return <><PageHeading title="Forecast Intelligence" description="Hourly DE–LU electricity price forecasts and model performance." />
    <ForecastSummary report={next24.data} pipeline={pipeline} errorCode={next24.error?.code}>
    {next24.error?.code!=='FORECAST_WITHHELD'&&<ApiPanel title="24-hour forecast report" state={next24}>{data => <Suspense fallback={<LoadingState label="Loading chart…" />}><ForecastChart rows={data.forecasts} issueTime={data.forecasts[0].issue_time} observed={observed.data?.latest_observation?.price_eur_mwh != null ? {timestamp:observed.data.latest_observation.timestamp,price:observed.data.latest_observation.price_eur_mwh} : null} /></Suspense>}</ApiPanel>}
    </ForecastSummary>
    {next24.error?.code==='FORECAST_WITHHELD'&&<button className="secondary-button" onClick={next24.retry}>Refresh forecast</button>}
    {next24.error?.code==='FORECAST_WITHHELD'&&operations.data?.forecast_reason&&<details className="methodology"><summary>Why a forecast is unavailable</summary><p>{operations.data.forecast_reason}</p></details>}
    {pipeline.error && <button className="secondary-button mb-4" onClick={pipeline.retry}>Retry availability check</button>}

    {observed.data?.coverage.latest_observation && <div className="mt-6"><ForecastInputContext observed issue={observed.data.coverage.latest_observation}/></div>}
    <div className="mt-6"><ObservedPriceComparison forecastAverage={next24.data?next24.data.forecasts.reduce((sum,r)=>sum+r.predicted_price_eur_mwh,0)/next24.data.row_count:null}/></div>
    {!priceOnly && <div className="mt-6">{next24.data ? <ForecastInputContext issue={next24.data.forecasts[0].issue_time}/> : <EmptyState awaitingIntegration={false} title="Issue-hour context unavailable" description="Issue-hour context is available with a valid forecast."/>}</div>}
    {server.account?.role==='Admin' && next24.data && !priceOnly && <div className="mt-6"><ForecastProvenanceEvidence key={`${next24.data.forecasts[0].issue_time}-${next24.data.publication?.completed_at ?? "snapshot"}`} issue={next24.data.forecasts[0].issue_time} completed={next24.data.publication?.completed_at}/></div>}
    <div className="mt-6"><RealizedForecastEvaluation/></div>
    <div className="mt-6"><ApiPanel title="Historical one-hour actual vs predicted" description="Up to 500 recent predictions with observed prices." state={oneHour}>{data => data.row_count ? <><Facts items={[["Displayed recent records", data.row_count], ['First target', formatTime(data.forecasts[0].target_time)], ['Last target', formatTime(data.forecasts.at(-1)!.target_time)]]} /><button className="secondary-button" onClick={()=>downloadCsv('powerflow_historical_one_hour_predictions.csv',[['target_time_utc','actual_price_eur_mwh','predicted_price_eur_mwh','classification'],...data.forecasts.map(row=>[row.target_time,row.actual_price_eur_mwh,row.predicted_price_eur_mwh,'Historical one-hour predictions; release not identified by this report'])])}>Export displayed historical one-hour records</button><Suspense fallback={<LoadingState label="Loading chart…" />}><ForecastChart historical rows={data.forecasts.slice(-500)} /></Suspense></> : <EmptyState awaitingIntegration={false} title="No one-hour records" description="The report contains no forecast records." />}</ApiPanel></div>
    <div className="mt-6"><ApiPanel title="One-hour model holdout results" state={models}>{data=>{const model=data.models.find(item=>item.key==='one_hour');return model?.evaluations.length?<><p className="data-note">Linear regression errors increased during price spikes of €200/MWh or more.</p>{model.evaluations.map(e=><ModelFacts key={e.split} items={[["Model",model.name ?? 'Unavailable'],['MAE (EUR/MWh)',e.mae.toFixed(2)],['RMSE (EUR/MWh)',e.rmse.toFixed(2)],['R²',e.r2.toFixed(3)],['RMSE improvement versus same-period persistence · %',rmseImprovement(e.rmse,e.persistence_rmse)?.toFixed(2)??'Unavailable'],['Evaluation starts',formatTime(e.period_start)],['Evaluation ends',formatTime(e.period_end)]]}/>)}</>:<EmptyState awaitingIntegration={false} title="Evaluation evidence unavailable" description="No evaluation report is available for this model."/>}}</ApiPanel></div>
  </>
}
