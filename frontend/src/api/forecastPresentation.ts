import type { ForecastReport,Next24Row } from './contracts.ts'
export function forecastStatistics(report:ForecastReport<Next24Row>){
 const rows=report.forecasts;const sorted=[...rows].sort((a,b)=>a.predicted_price_eur_mwh-b.predicted_price_eur_mwh)
 return {average:rows.reduce((n,row)=>n+row.predicted_price_eur_mwh,0)/rows.length,median:(sorted[11].predicted_price_eur_mwh+sorted[12].predicted_price_eur_mwh)/2,minimum:sorted[0],maximum:sorted.at(-1)!,change:rows.at(-1)!.predicted_price_eur_mwh-rows[0].predicted_price_eur_mwh,negative:rows.filter(row=>row.predicted_price_eur_mwh<0).length,elevated:rows.filter(row=>row.predicted_price_eur_mwh>=200).length}
}
function csvCell(value:string|number){const text=String(value);const safe=typeof value==='string' && /^[=+@\-\t\r]/.test(text)?`'${text}`:text;return `"${safe.replaceAll('"','""')}"`}
export function forecastCsv(report:ForecastReport<Next24Row>,status:string){
 return [['issue_time_utc','target_time_utc','horizon_hours','predicted_price_eur_mwh','model_release','display_classification','usage_note'],...report.forecasts.map(row=>[row.issue_time,row.target_time,row.horizon_hours,row.predicted_price_eur_mwh,row.model_release,status,'Persisted report. Historical, stale, withheld, or unverified values are not current live forecasts.'])].map(row=>row.map(csvCell).join(',')).join('\r\n')+'\r\n'
}
