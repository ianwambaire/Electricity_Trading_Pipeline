import { WebStorageStateStore, type UserManagerSettings } from 'oidc-client-ts'
import type { AuthConfig } from './config.ts'

export const ACCOUNT_SCOPES = 'openid email profile aws.cognito.signin.user.admin'

// A refresh of an older session cannot acquire additional scopes. Start an
// explicit code + PKCE interaction; retain library-owned state/nonce validation.
export function accountSigninRequest() {
  return { scope: ACCOUNT_SCOPES, prompt: 'login', nonce: crypto.randomUUID(), state: { returnTo: '/profile' } }
}

export function oidcSettings(config: AuthConfig, store: Storage): UserManagerSettings {
  return {
    authority: config.authority, client_id: config.clientId,
    redirect_uri: config.redirectUri, post_logout_redirect_uri: config.logoutUri,
    response_type: 'code', response_mode: 'query', scope: 'openid email profile',
    disablePKCE: false, loadUserInfo: false,
    automaticSilentRenew: true, monitorSession: false,
    accessTokenExpiringNotificationTimeInSeconds: 60,
    staleStateAgeInSeconds: 600, requestTimeoutInSeconds: 15,
    userStore: new WebStorageStateStore({ store, prefix: 'powerflow.user.' }),
    stateStore: new WebStorageStateStore({ store, prefix: 'powerflow.oidc.' }),
  }
}
