import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { GenerationKey, MarketRow } from '../../api/publicData'
import { formatTime } from '../../api/forecastState'

export function MarketChart({ rows, kind, source = 'wind_total_mw' }: { rows: MarketRow[]; kind: 'price' | 'load' | 'generation' | 'renewable'; source?: GenerationKey }) {
  const points: { time: number; value: number | null; share: number | null }[] = []
  let previous: number | null = null
  for (const row of rows) {
    const time = Date.parse(row.timestamp)
    if (previous !== null && time - previous > 3600000) points.push({ time: previous + 3600000, value: null, share: null })
    const value = kind === 'price' ? row.price_eur_mwh : kind === 'load' ? row.load_mw : kind === 'generation' ? row.generation[source] : row.renewable_generation_mw
    points.push({time, value, share: row.renewable_share === null ? null : row.renewable_share * 100})
    previous = time
  }
  return <div className="forecast-chart" role="img" aria-label={`Historical ${kind} chart, with gaps for absent observations. Exact values in the data table.`}><ResponsiveContainer width="100%" height="100%"><LineChart data={points} margin={{top:15,right:15,bottom:10,left:5}}><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false}/><XAxis dataKey="time" type="number" domain={['dataMin','dataMax']} tickFormatter={n=>new Date(n).toISOString().slice(5,16).replace('T',' ')} minTickGap={55}/><YAxis yAxisId="value" width={70}/>{kind === 'renewable' && <YAxis yAxisId="share" orientation="right" unit="%" width={55}/>}<Tooltip labelFormatter={value=>formatTime(new Date(Number(value)).toISOString())}/><Line yAxisId="value" dataKey="value" name={kind === 'price' ? 'Price (EUR/MWh)' : 'Generation / load (MW)'} stroke={kind === 'price' ? 'var(--chart-price)' : kind === 'load' ? 'var(--chart-load)' : 'var(--chart-generation)'} dot={false} connectNulls={false} isAnimationActive={false}/>{kind === 'renewable' && <Line yAxisId="share" dataKey="share" name="Selected-source renewable share (%)" stroke="var(--chart-share)" dot={false} connectNulls={false} isAnimationActive={false}/>}</LineChart></ResponsiveContainer></div>
}
