import { authConfig, userManager } from './runtime'
import { logoutSession } from './logout'

export async function signOutCurrentSession(removeUser: () => Promise<void>): Promise<void> {
  if (!authConfig) throw new Error('Sign-out configuration unavailable')
  await logoutSession(authConfig, {
    stopRenew: () => userManager?.stopSilentRenew(),
    removeUser,
    clearTransactions: async () => {
      const store=userManager?.settings.stateStore
      if(store)await Promise.all((await store.getAllKeys()).map(key=>store.remove(key)))
    },
    redirect: url => window.location.assign(url),
  })
}
