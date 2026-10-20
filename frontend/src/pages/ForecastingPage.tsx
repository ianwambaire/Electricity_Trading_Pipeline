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
  const next24 = useApi(api.next24)
  const pipeline = useApi(api.pipeline)
  const oneHour = useApi(api.oneHour)
  return <><PageHeading title="Forecast Intelligence" description="Inspect persisted model predictions, target times, and availability evidence." />
    <p className="data-note">No model is run in this browser. These forecast endpoints supply stored reports without actual generation time, evaluation metrics, detailed withholding causes, or the configured freshness threshold. Release-specific evaluation is available in Model Insights.</p>
    <ForecastSummary report={next24.data} pipeline={pipeline} />
    {pipeline.error && <button className="secondary-button mb-4" onClick={pipeline.retry}>Retry availability check</button>}
    <ApiPanel title="24-hour forecast report" description="Report issue time and target hours determine whether values are recent, stale, or historical." state={next24}>{data => <Suspense fallback={<LoadingState label="Loading chart…" />}><ForecastChart rows={data.forecasts} /></Suspense>}</ApiPanel>
    <div className="mt-6"><ApiPanel title="Historical one-hour actual vs predicted" description="Recorded predictions with observed outcomes; this is not a live one-hour forecast." state={oneHour}>{data => data.row_count ? <><Facts items={[["Available records", data.row_count], ['First target', formatTime(data.forecasts[0].target_time)], ['Last target', formatTime(data.forecasts.at(-1)!.target_time)]]} /><p className="data-note">The API does not identify the one-hour model release or its evaluation period. No evaluation metrics are inferred from this report.</p><Suspense fallback={<LoadingState label="Loading chart…" />}><ForecastChart historical rows={data.forecasts.slice(-168)} /></Suspense></> : <EmptyState awaitingIntegration={false} title="No one-hour records" description="The report contains no forecast records." />}</ApiPanel></div>
  </>
}
