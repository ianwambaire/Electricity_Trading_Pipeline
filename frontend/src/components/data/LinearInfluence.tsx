import { lazy, Suspense, useState } from 'react'
import { api } from '../../api/client'
import { rankCoefficients } from '../../api/parity'
import { downloadCsv } from '../../api/csv'
import { useApi } from '../../hooks/useApi'
import { ApiPanel, Facts } from './ApiPanel'
import { LoadingState } from '../ui/States'
const Chart=lazy(()=>import('./CoefficientChart').then(m=>({default:m.CoefficientChart})))
export function LinearInfluence() {
  const report=useApi(api.influence)
  const [sort,setSort]=useState<'magnitude'|'name'>('magnitude')
  return <ApiPanel title="One-hour Linear Regression — Feature Influence" state={report}>{data=>{
    const ranked=rankCoefficients(data.features,sort)
    const top=rankCoefficients(data.features,'magnitude').slice(0,15)
    return <><Facts items={[["Model",data.model],['Horizon','h+1'],['Features',data.feature_count]]}/><p className="data-note">{data.provenance}</p><p className="notice notice-warning">Coefficients describe fitted associations, not causal effects. The existing writer extracts coefficients from the standardized frozen Linear Regression pipeline. Correlation and preprocessing matter; raw coefficients from differently scaled inputs are not directly comparable importance measures. This chart is not feature importance for the separate 24-hour Histogram Gradient Boosting model.</p><p className="data-note">Blue: positive coefficient. Amber: negative coefficient. The chart shows the 15 largest absolute coefficients; the table includes all 31.</p><Suspense fallback={<LoadingState label="Loading coefficient chart…"/>}><Chart rows={top}/></Suspense><p className="data-note">Largest absolute coefficients: {top.slice(0,5).map(r=>r.feature).join(', ')}. Signs describe the fitted model with other predictors held fixed, subject to correlated inputs.</p>
    <div className="filter-form"><label>Sort coefficients<select value={sort} onChange={e=>setSort(e.target.value as 'magnitude'|'name')}><option value="magnitude">Absolute magnitude, descending</option><option value="name">Feature name</option></select></label><button className="secondary-button" onClick={()=>downloadCsv('powerflow_one_hour_coefficients.csv', [['model','horizon_hours','feature','signed_coefficient','absolute_coefficient','report_sha256','metadata_sha256','provenance'],...ranked.map(r=>[data.model,1,r.feature,r.signed_coefficient,r.importance,data.report_sha256,data.metadata_sha256,data.provenance])])}>Export all coefficients</button></div>
    <div className="table-scroll"><table><caption>All persisted coefficients · one-hour model</caption><thead><tr><th scope="col">Feature</th><th scope="col">Signed coefficient</th><th scope="col">Sign</th><th scope="col">Absolute magnitude</th></tr></thead><tbody>{ranked.map(r=><tr key={r.feature}><th scope="row">{r.feature}</th><td>{r.signed_coefficient}</td><td>{r.signed_coefficient>0?'Positive':r.signed_coefficient<0?'Negative':'Zero'}</td><td>{r.importance}</td></tr>)}</tbody></table></div><details className="metadata-digest"><summary>Report and metadata fingerprints</summary><p>Coefficient report SHA-256</p><code>{data.report_sha256}</code><p>Release metadata SHA-256</p><code>{data.metadata_sha256}</code><p>{data.limitation}</p></details></>
  }}</ApiPanel>
}
