import type { ReactNode } from 'react'
import type { ApiState } from '../../hooks/useApi'
import { formatTime } from '../../api/forecastState'
import { Panel } from '../ui/Panel'
import { EmptyState, ErrorState, LoadingState } from '../ui/States'

export function ApiPanel<T>({ title, description, state, children }: { title: string; description?: string; state: ApiState<T> & { retry: () => void; refreshInterval?: number }; children: (data: T) => ReactNode }) {
  return <Panel title={title} description={description}>
    {state.loading ? <LoadingState /> : state.error ? <><ErrorState title={state.error.code === 'FORECAST_WITHHELD' ? 'WITHHELD' : state.error.status === 403 ? 'Access denied' : state.error.status === 404 ? 'Report unavailable' : 'Unable to load data'} description={state.error.message} onRetry={state.retry} /></> : state.data ? <div className="api-content">{children(state.data)}</div> : <EmptyState awaitingIntegration={false} title="No data returned" description="The API has not supplied usable data for this section." />}
    <div className="panel-footer"><span>Last fetched: {formatTime(state.receivedAt)} · Auto-refresh: {state.refreshInterval === 0 ? 'off' : `${(state.refreshInterval ?? 60000) / 1000}s after completion`}</span><button className="text-link" onClick={state.retry} disabled={state.loading}>Refresh</button></div>
  </Panel>
}
export function Facts({ items }: { items: [string, string | number][] }) { return <dl className="facts">{items.map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> }
