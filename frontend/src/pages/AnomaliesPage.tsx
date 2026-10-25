import { downloadCsv } from '../api/csv'
import { numberLabel } from '../api/numberLabel'
import { lazy, Suspense, useCallback, useState } from 'react'
import { api } from '../api/client'
import type { AnomalyEvent } from '../api/restoration'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { PageHeading } from '../components/ui/PageHeading'
import { EmptyState, LoadingState } from '../components/ui/States'
import { DateRangeFilter } from '../components/ui/DateRangeFilter'
import { KpiGrid } from '../components/ui/KpiGrid'
const HistoricalChart=lazy(()=>import('../components/data/HistoricalChart').then(m=>({default:m.HistoricalChart})))
function EventsTable({rows}:{rows:AnomalyEvent[]}){return <div className="table-scroll" tabIndex={0}><table><thead><tr><th>Event time (UTC)</th><th>Price (EUR/MWh)</th><th>Load (MW)</th></tr></thead><tbody>{rows.map(row=><tr key={row.timestamp}><td>{formatTime(row.timestamp)}</td><td>{numberLabel(row.price_eur_mwh,20)}</td><td>{numberLabel(row.load_mw,20)}</td></tr>)}</tbody></table></div>}
export function AnomaliesPage(){
 const [query,setQuery]=useState('');const [offset,setOffset]=useState(0)
 const summary=useApi(useCallback(signal=>api.anomalySummary(query,signal),[query]))
 const markers=useApi(useCallback(signal=>api.anomalyEvents(`${query}&order=time_asc&limit=1000`,signal),[query]))
 const top=useApi(useCallback(signal=>api.anomalyEvents(`${query}&order=price_desc&limit=20`,signal),[query]))
 const page=useApi(useCallback(signal=>api.anomalyEvents(`${query}&order=time_desc&limit=100&offset=${offset}`,signal),[query,offset]))
 const chart=useApi(useCallback(signal=>api.marketChart(query,signal),[query]))
 return <><PageHeading title="Anomaly Detection" description="Historical statistical outliers detected from electricity price and load."/><p className="data-note">These are not verified faults, market manipulation, trading opportunities, or forecast errors. No numeric anomaly score is recorded.</p><DateRangeFilter onApply={q=>{setOffset(0);setQuery(q)}}/>
 <ApiPanel title="Detected anomaly summary" state={summary}>{data=><><KpiGrid items={[{label:'Detected events · selected range',value:numberLabel(data.count,0)},{label:'Maximum price · EUR/MWh',value:numberLabel(data.maximum_price)},{label:'Minimum price · EUR/MWh',value:numberLabel(data.minimum_price)},{label:'Mean anomalous load · MW',value:numberLabel(data.average_load_mw)}]}/><Facts items={[["Report state",data.report_status],['Total report events',data.total_report_rows],['First selected event',formatTime(data.first_event)],['Last selected event',formatTime(data.last_event)]]}/>{data.count===0&&<EmptyState awaitingIntegration={false} title={data.report_status==='empty'?'Valid report contains zero anomalies':'No anomaly events in the selected dates'} description="A valid zero-result report is distinct from a missing report. No events are fabricated."/>}<details className="methodology"><summary>Detection method and limitations</summary><p>{data.method}. {data.provenance}. {data.limitation} Contamination is a fitting parameter, not an event probability. Events ranked by price are not ranked by anomaly severity.</p></details></>}</ApiPanel>
 <div className="mt-6"><ApiPanel title="Electricity price history and detected events" state={chart}>{data=><><Facts items={[["Price history begins",formatTime(data.coverage.first_observation)],['Price history through',formatTime(data.coverage.latest_observation)]]}/><ApiPanel title="Anomaly overlay" state={markers}>{events=>events.next_offset!==null?<div className="notice notice-warning">More than 1,000 events match. Narrow the date range to display every marker; no truncated overlay is shown.</div>:data.row_count?<Suspense fallback={<LoadingState label="Loading anomaly chart…"/>}><HistoricalChart report={data} events={events.events}/></Suspense>:<EmptyState awaitingIntegration={false} title="No background price observations" description="Anomaly records remain available in the tables; no background prices are invented."/>}</ApiPanel></>}</ApiPanel></div>
 <div className="mt-6"><ApiPanel title="Top 20 events by electricity price" description="Descending price within the selected range; this is not an anomaly-severity score." state={top}>{data=><EventsTable rows={data.events}/>}</ApiPanel></div>
 <div className="mt-6"><ApiPanel title="Exact anomaly records" description="Newest first; up to 100 events per page." state={page}>{data=><><EventsTable rows={data.events}/><button className="secondary-button" onClick={()=>downloadCsv('powerflow_displayed_anomaly_events.csv',[['timestamp_utc','observed_price_eur_mwh','observed_load_mw','classification'],...data.events.map(row=>[row.timestamp,row.price_eur_mwh,row.load_mw,'Historical persisted Isolation Forest outlier; not a forecast error'])])}>Export displayed events</button><div className="pagination"><button className="secondary-button" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-100))}>Previous events</button><span>{data.row_count?offset+1:0}–{offset+data.row_count} of {data.matched_rows}</span><button className="secondary-button" disabled={data.next_offset===null} onClick={()=>setOffset(data.next_offset!)}>Next events</button></div></>}</ApiPanel></div></>
}
