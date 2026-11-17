import { createContext, useContext } from 'react'
import type { ServerAccount } from '../api/account'
import type { ApiError } from '../api/client'

export interface ServerAccountState {
  account: ServerAccount | null
  loading: boolean
  error: ApiError | null
  retry: () => void
}
export const ServerAccountContext = createContext<ServerAccountState>({ account: null, loading: true, error: null, retry: () => undefined })
export function useServerAccount() { return useContext(ServerAccountContext) }
