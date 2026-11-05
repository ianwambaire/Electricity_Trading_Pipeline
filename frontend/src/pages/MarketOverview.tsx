import {CurrentOperations} from '../components/data/CurrentOperations'
import { numberLabel } from '../api/numberLabel'
import { lazy, Suspense, useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { ForecastSummary } from '../components/data/ForecastSummary'
import { OperationsNotice, OperationalSummary } from '../components/data/OperationalSummary'
import { PageHeading } from '../components/ui/PageHeading'
import { LoadingState } from '../components/ui/States'
import { KpiGrid } from '../components/ui/KpiGrid'
import { DateRangeFilter } from '../components/ui/DateRangeFilter'
const HistoricalChart=lazy(()=>import('../components/data/HistoricalChart').then(m=>({default:m.HistoricalChart})))
const allAnomalies=(signal:AbortSignal)=>api.anomalySummary('',signal)
export function MarketOverview(){
 const [query,setQuery]=useState('')
 const market=useApi(api.marketSummary);const anomalies=useApi(allAnomalies);const operations=useApi(api.operations)
 const pipeline=useApi(api.pipeline);const forecast=useApi(api.next24);const health=useApi(api.health)
 const chart=useApi(useCallback((signal:AbortSignal)=>api.marketChart(query,signal),[query]))
 const demand=useApi(useCallback((signal:AbortSignal)=>api.marketChart(`${query}${query?'&':''}series=load_wind`,signal),[query]))
 return <><PageHeading title="Executive Overview" description="Germany–Luxembourg historical electricity market, forecast availability, and pipeline evidence."/><OperationsNotice data={operations.data}/>
 <ApiPanel title="Historical market overview" description="Historical market indicators across the full recorded period." state={market}>{data=><><KpiGrid items={[
 {label:'Latest historical price · EUR/MWh',value:numberLabel(data.latest_observation?.price_eur_mwh)},
 {label:'Historical mean load · MW',value:numberLabel(data.mean_load_mw)},
 {label:'Hourly observations',value:numberLabel(data.matched_rows,0)},
 {label:'Historical anomalies',value:numberLabel(anomalies.data?.total_report_rows,0),note:anomalies.error?'Anomaly report unavailable':'Recorded statistical outliers'},
 ]}/><Facts items={[["Latest market observation",formatTime(data.coverage.latest_observation)],['Coverage begins',formatTime(data.coverage.first_observation)],['Missing hours within recorded span',data.coverage.missing_hours_in_span]]}/>{anomalies.error&&<button className="secondary-button" onClick={anomalies.retry}>Retry anomaly count</button>}<p className="data-note">Coverage refers to recorded timestamps; it does not establish complete recent forecast inputs.</p></>}</ApiPanel>
 <DateRangeFilter onApply={setQuery}/>
 <ApiPanel title="Historical electricity prices · EUR/MWh" state={chart}>{data=><Suspense fallback={<LoadingState label="Loading market history…"/>}><HistoricalChart report={data}/></Suspense>}</ApiPanel>
 <div className="mt-6"><ApiPanel title="Electricity Demand vs. Wind and Solar Generation" description="Compare electricity demand with wind and solar generation across the Germany–Luxembourg electricity market." state={demand}>{data=><Suspense fallback={<LoadingState label="Loading generation comparison…"/>}><HistoricalChart report={data} mode="load_wind"/></Suspense>}</ApiPanel></div>
 <div className="mt-6"><ApiPanel title="Latest 10 historical observations" description="Newest first across the full persisted Silver dataset." state={market}>{data=><div className="table-scroll" tabIndex={0}><table><thead><tr><th>Observation (UTC)</th><th>Price (EUR/MWh)</th><th>Load (MW)</th><th>Wind + solar (MW)</th></tr></thead><tbody>{data.recent.map(row=><tr key={row.timestamp}><td>{formatTime(row.timestamp)}</td><td>{numberLabel(row.price_eur_mwh,20)}</td><td>{numberLabel(row.load_mw,20)}</td><td>{numberLabel(row.wind_solar_mw,20)}</td></tr>)}</tbody></table></div>}</ApiPanel></div>
 <div className="mt-6"><CurrentOperations/></div><div className="detail-grid"><OperationalSummary state={operations}/><div>{forecast.error?.code==='FORECAST_WITHHELD'?<><ForecastSummary report={null} pipeline={pipeline} errorCode={forecast.error.code}/><button className="secondary-button" onClick={forecast.retry}>Refresh forecast</button></>:<ApiPanel title="Forecast availability" state={forecast}>{data=><ForecastSummary report={data} pipeline={pipeline}/>}</ApiPanel>}</div></div>
 <div className="mt-6"><ApiPanel title="API service response" state={health}>{data=><Facts items={[["Service",data.application],['Response',data.status],['Server time',formatTime(data.timestamp_utc)]]}/>}</ApiPanel></div><p className="data-note"><Link className="text-link" to="/pipeline">Open Pipeline Operations for source and quality details</Link></p></>
}
