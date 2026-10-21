import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useAuth } from 'react-oidc-context'
import type { User } from 'oidc-client-ts'
import { api, ApiError } from '../api/client'
import type { ServerAccount } from '../api/account'
import { ServerAccountContext } from './serverAccountContext'

export function ServerAccountProvider({ children }: { children: ReactNode }) {
  const { user, isAuthenticated } = useAuth()
  const [attempt, setAttempt] = useState(0)
  const [snapshot, setSnapshot] = useState<{ owner: User | null | undefined; account: ServerAccount | null; loading: boolean; error: ApiError | null }>({ owner: null, account: null, loading: false, error: null })
  const retry = useCallback(() => setAttempt(n => n + 1), [])
  useEffect(() => {
    if (!isAuthenticated || !user) return
    const controller = new AbortController()
    async function refresh() {
      setSnapshot({ owner: user, account: null, loading: true, error: null })
      try {
        const account = await api.me(controller.signal)
        if (account.subject !== user!.profile.sub) throw new ApiError('The server account could not be matched to this session.')
        if (!controller.signal.aborted) setSnapshot({ owner: user, account, loading: false, error: null })
      } catch (error) {
        if (!controller.signal.aborted) setSnapshot({ owner: user, account: null, loading: false, error: error instanceof ApiError ? error : new ApiError('Server account verification is unavailable.') })
      }
    }
    void refresh()
    const interval = window.setInterval(() => { void refresh() }, 60000)
    return () => { controller.abort(); window.clearInterval(interval) }
  }, [user, isAuthenticated, attempt])
  // A previous user's role never survives a session/refresh-token change or error.
  const current = isAuthenticated && snapshot.owner === user
  return <ServerAccountContext.Provider value={{ account: current ? snapshot.account : null, error: current ? snapshot.error : null, loading: isAuthenticated && (!current || snapshot.loading), retry }}>{children}</ServerAccountContext.Provider>
}
