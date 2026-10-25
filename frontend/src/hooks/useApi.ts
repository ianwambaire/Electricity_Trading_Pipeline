import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'

export interface ApiState<T> { data: T | null; loading: boolean; error: ApiError | null; receivedAt: string | null }
export function useApi<T>(load: (signal: AbortSignal) => Promise<T>, refreshInterval = 60000) {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null, receivedAt: null })
  const [attempt, setAttempt] = useState(0)
  const retry = useCallback(() => setAttempt(n => n + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    async function refresh() {
      setState({ data: null, loading: true, error: null, receivedAt: null })
      try {
        const data = await load(controller.signal)
        if (!controller.signal.aborted) setState({ data, loading: false, error: null, receivedAt: new Date().toISOString() })
      } catch (error) {
        if (!controller.signal.aborted) setState({ data: null, loading: false, error: error instanceof ApiError ? error : new ApiError('Unable to read the API response.'), receivedAt: null })
      } finally {
        // Schedule after completion: slow requests never overlap the next poll.
        if (!controller.signal.aborted && refreshInterval > 0) timer = window.setTimeout(() => { void refresh() }, refreshInterval)
      }
    }
    void refresh()
    return () => { controller.abort(); if (timer !== undefined) window.clearTimeout(timer) }
  }, [load, attempt, refreshInterval])
  return { ...state, retry, refreshInterval }
}
