import { useApi } from './useApi'

// Opt in only for historical panels. Live forecasts retain useApi's strict
// clear-on-refresh behavior and their independent expiry enforcement.
export function useHistoricalApi<T>(load: (signal: AbortSignal) => Promise<T>) {
  return useApi(load, 60000, true)
}
