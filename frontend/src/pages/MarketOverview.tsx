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
 return <><PageHeading title="Executive Overview" description="Germany–Luxembourg historical electricity market, forecast availability, and pipeline evidence."/><OperationsNotice data={operations.data}/>
 <ApiPanel title="Historical market overview" description="KPIs cover all persisted Silver history, not only the displayed chart range. Latest stored values are not presented as live." state={market}>{data=><><KpiGrid items={[
 {label:'Latest historical price · EUR/MWh',value:numberLabel(data.latest_observation?.price_eur_mwh)},
 {label:'Historical mean load · MW',value:numberLabel(data.mean_load_mw)},
 {label:'Hourly observations',value:numberLabel(data.matched_rows,0)},
 {label:'Historical anomalies',value:numberLabel(anomalies.data?.total_report_rows,0),note:anomalies.error?'Anomaly report unavailable':'Active persisted detector output'},
 ]}/><Facts items={[["Latest market observation",formatTime(data.coverage.latest_observation)],['Coverage begins',formatTime(data.coverage.first_observation)],['Missing hours within recorded span',data.coverage.missing_hours_in_span]]}/>{anomalies.error&&<button className="secondary-button" onClick={anomalies.retry}>Retry anomaly count</button>}<p className="data-note">Coverage refers to recorded timestamps; it does not establish complete recent forecast inputs.</p></>}</ApiPanel>
 <DateRangeFilter onApply={setQuery}/>
 <ApiPanel title="Historical electricity prices · EUR/MWh" state={chart}>{data=><Suspense fallback={<LoadingState label="Loading market history…"/>}><HistoricalChart report={data}/></Suspense>}</ApiPanel>
 <div className="mt-6"><ApiPanel title="Electricity load versus total wind + solar · MW" description="This reproduces the Streamlit comparison. Biomass and hydro are not added to wind + solar." state={chart}>{data=><Suspense fallback={<LoadingState label="Loading generation comparison…"/>}><HistoricalChart report={data} mode="load_wind"/></Suspense>}</ApiPanel></div>
 <div className="mt-6"><ApiPanel title="Latest 10 historical observations" description="Newest first across the full persisted Silver dataset." state={market}>{data=><div className="table-scroll"><table><thead><tr><th>Observation (UTC)</th><th>Price (EUR/MWh)</th><th>Load (MW)</th><th>Wind + solar (MW)</th></tr></thead><tbody>{data.recent.map(row=><tr key={row.timestamp}><td>{formatTime(row.timestamp)}</td><td>{numberLabel(row.price_eur_mwh,20)}</td><td>{numberLabel(row.load_mw,20)}</td><td>{numberLabel(row.wind_solar_mw,20)}</td></tr>)}</tbody></table></div>}</ApiPanel></div>
 <div className="detail-grid"><OperationalSummary state={operations}/><ApiPanel title="Forecast report availability" state={forecast}>{data=><ForecastSummary report={data} pipeline={pipeline}/>}</ApiPanel></div>{!forecast.loading&&!forecast.data&&<ForecastSummary report={null} pipeline={pipeline}/>}
 <div className="mt-6"><ApiPanel title="API service response" state={health}>{data=><Facts items={[["Service",data.application],['Response',data.status],['Server time',formatTime(data.timestamp_utc)]]}/>}</ApiPanel></div><p className="data-note"><Link className="text-link" to="/pipeline">Open Pipeline Operations for source and quality details</Link></p></>
}
