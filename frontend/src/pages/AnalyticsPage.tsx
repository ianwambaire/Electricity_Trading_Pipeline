import { MarketExploration } from '../components/data/MarketExploration'
import { downloadCsv } from '../api/csv'
import { lazy, Suspense, useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../api/client'
import { generationKeys } from '../api/publicData'
import type { GenerationKey } from '../api/publicData'
import { formatTime } from '../api/forecastState'
import { useApi } from '../hooks/useApi'
import { ApiPanel, Facts } from '../components/data/ApiPanel'
import { PageHeading } from '../components/ui/PageHeading'
import { Panel } from '../components/ui/Panel'
import { EmptyState, LoadingState } from '../components/ui/States'

const MarketChart = lazy(()=>import('../components/data/MarketChart').then(module=>({default:module.MarketChart})))
const label = (key: string) => key.replace(/_mw$/, '').replaceAll('_', ' ')
const value = (n: number | null) => n === null ? 'Missing' : n.toLocaleString(undefined,{maximumFractionDigits:2})

export function AnalyticsPage() {
  const coverage = useApi(api.marketCoverage)
  const [range,setRange] = useState({start:'',end:''})
  const [offset,setOffset] = useState(0)
  const [formError,setFormError] = useState('')
  const [source,setSource] = useState<GenerationKey>('wind_total_mw')
  const load = useCallback((signal: AbortSignal) => {
    const params = new URLSearchParams({limit:'1000',offset:String(offset)})
    if (range.start) params.set('start',range.start)
    if (range.end) params.set('end',range.end)
    return api.marketHistory(params.toString(),signal)
  },[range,offset])
  const history = useApi(load)
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const start = String(form.get('start') || '')
    const end = String(form.get('end') || '')
    if (!!start !== !!end) { setFormError('Choose both dates, or clear both to use the latest available week.'); return }
    const a = start ? `${start}T00:00:00Z` : ''
    const b = end ? `${end}T23:59:59.999Z` : ''
    if (a && (Date.parse(a)>Date.parse(b) || Date.parse(b)-Date.parse(a)>366*86400000)) { setFormError('Choose an ordered range of at most 366 days.'); return }
    setFormError(''); setOffset(0); setRange({start:a,end:b})
  }
  return <><PageHeading title="Market Intelligence" description="Historical DE-LU price, load, and generation observations from the persisted Silver dataset."/>
    <p className="data-note">These observations are historical, not live market readings or forecasts. Missing values remain missing. All date filters and chart times use UTC.</p>
    <ApiPanel title="Dataset coverage" state={coverage}>{data=><><Facts items={[["Source",data.source],['Market',data.market_area],['Available hourly rows',data.row_count],['First observation',formatTime(data.first_observation)],['Latest observation',formatTime(data.latest_observation)],['Missing hours within span',data.missing_hours_in_span]]}/><p className="data-note">{data.renewable_definition}</p></>}</ApiPanel>
    <form className="filter-form" onSubmit={apply}><label>From date (UTC)<input name="start" type="date" min="1970-01-01" max="2100-12-31"/></label><label>Through date (UTC)<input name="end" type="date" min="1970-01-01" max="2100-12-31"/></label><button className="secondary-button" type="submit">Apply date range</button><p>Leave both blank for the seven-day window ending at the latest persisted hour.</p>{formError && <p role="alert">{formError}</p>}</form>
    <MarketExploration query={new URLSearchParams(range.start ? {start:range.start,end:range.end} : {}).toString()}/>
    <div className="mt-6"/>
    <ApiPanel title="Historical observations" description="Up to 1,000 exact hourly records per page; charts describe only the displayed page." state={history}>{data=><>
      <Facts items={[["Filtered start",formatTime(data.start)],['Filtered end',formatTime(data.end)],['Matching records',data.matched_rows],['Displayed records',data.row_count],['Page offset',data.offset]]}/>
      {coverage.data && data.coverage.snapshot_id !== coverage.data.snapshot_id && <p className="data-note">The dataset changed since coverage was fetched. The history response uses the newer snapshot; refresh coverage to match.</p>}
      {!data.row_count ? <EmptyState awaitingIntegration={false} title="No observations in this range" description="No values are substituted. Choose another date range or return to an earlier page."/> : <><div className="detail-grid">{(['price','load','generation','renewable'] as const).map(kind=><Panel key={kind} title={{price:'Electricity price · EUR/MWh',load:'Electricity load · MW',generation:'Generation by source · MW',renewable:'Renewable generation · MW & share · %'}[kind]}>{kind==='generation' && <label className="generation-select">Source<select value={source} onChange={event=>setSource(event.target.value as GenerationKey)}>{generationKeys.map(key=><option key={key} value={key}>{label(key)}</option>)}</select></label>}<Suspense fallback={<LoadingState label="Loading chart…"/>}><MarketChart rows={data.observations} kind={kind} source={source}/></Suspense></Panel>)}</div>
      <button className="secondary-button" onClick={()=>downloadCsv('powerflow_displayed_market_page.csv', [['timestamp_utc','price_eur_mwh','load_mw',...generationKeys,'renewable_generation_mw','renewable_share_fraction','snapshot'],...data.observations.map(row=>[row.timestamp,row.price_eur_mwh,row.load_mw,...generationKeys.map(key=>row.generation[key]),row.renewable_generation_mw,row.renewable_share,data.coverage.snapshot_id])])}>Export displayed page (up to 1,000 rows)</button><details className="forecast-table"><summary>Exact observations for this page (UTC · EUR/MWh · MW)</summary><div className="table-scroll"><table><thead><tr><th>Timestamp</th><th>Price</th><th>Load</th>{generationKeys.map(key=><th key={key}>{label(key)}</th>)}<th>Renewables</th><th>Renewable share</th></tr></thead><tbody>{data.observations.map(row=><tr key={row.timestamp}><td>{formatTime(row.timestamp)}</td><td>{value(row.price_eur_mwh)}</td><td>{value(row.load_mw)}</td>{generationKeys.map(key=><td key={key}>{value(row.generation[key])}</td>)}<td>{value(row.renewable_generation_mw)}</td><td>{row.renewable_share===null?'Missing':`${(row.renewable_share*100).toFixed(2)}%`}</td></tr>)}</tbody></table></div></details></>}
      <div className="pagination" aria-label="History pagination"><button className="secondary-button" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-data.limit))}>Previous page</button><span>Records {data.row_count ? data.offset+1 : 0}–{data.offset+data.row_count} of {data.matched_rows}</span><button className="secondary-button" disabled={data.next_offset===null} onClick={()=>setOffset(data.next_offset!)}>Next page</button></div>
    </>}</ApiPanel>
  </>
}
