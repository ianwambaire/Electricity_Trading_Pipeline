import type { AuthConfig } from './config.ts'
import { cognitoLogoutUrl } from './config.ts'

export async function logoutSession(config: AuthConfig, actions: {
  stopRenew: () => void
  removeUser: () => Promise<void>
  clearTransactions: () => Promise<void>
  redirect: (url: string) => void
}): Promise<void> {
  actions.stopRenew()
  await actions.removeUser()
  await actions.clearTransactions()
  actions.redirect(cognitoLogoutUrl(config))
}
