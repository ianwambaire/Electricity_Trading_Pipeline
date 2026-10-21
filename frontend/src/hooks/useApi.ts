import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'

export interface ApiState<T> { data: T | null; loading: boolean; error: ApiError | null; receivedAt: string | null }
export function useApi<T>(load: (signal: AbortSignal) => Promise<T>, refreshInterval = 60000) {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null, receivedAt: null })
  const [attempt, setAttempt] = useState(0)
  const retry = useCallback(() => setAttempt(n => n + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    async function refresh() {
      setState({ data: null, loading: true, error: null, receivedAt: null })
      try {
        const data = await load(controller.signal)
        if (!controller.signal.aborted) setState({ data, loading: false, error: null, receivedAt: new Date().toISOString() })
      } catch (error) {
        if (!controller.signal.aborted) setState({ data: null, loading: false, error: error instanceof ApiError ? error : new ApiError('Unable to read the API response.'), receivedAt: null })
      }
    }
    void refresh()
    const interval = refreshInterval > 0 ? window.setInterval(() => { void refresh() }, refreshInterval) : null
    return () => { controller.abort(); if (interval !== null) window.clearInterval(interval) }
  }, [load, attempt, refreshInterval])
  return { ...state, retry }
}
