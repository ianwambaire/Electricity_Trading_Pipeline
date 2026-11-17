export interface AuthConfig {
  authority: string
  domain: string
  clientId: string
  redirectUri: string
  logoutUri: string
}

export function readAuthConfig(env: Record<string, unknown>): AuthConfig | null {
  try {
    const read = (key: string) => {
      const value = env[key]
      if (typeof value !== 'string' || !value.trim()) throw Error()
      return value.trim()
    }
    const authority = new URL(read('VITE_COGNITO_AUTHORITY'))
    const domain = new URL(read('VITE_COGNITO_DOMAIN'))
    const callback = new URL(read('VITE_COGNITO_REDIRECT_URI'))
    const logout = new URL(read('VITE_COGNITO_POST_LOGOUT_REDIRECT_URI'))
    const clientId = read('VITE_COGNITO_CLIENT_ID')
    if (!/^https:\/\/cognito-idp\.[a-z0-9-]+\.amazonaws\.com\/[a-z0-9-]+_[A-Za-z0-9]+$/.test(authority.href)
      || domain.protocol !== 'https:' || !domain.hostname.endsWith('.amazoncognito.com')
      || domain.pathname !== '/' || domain.search || domain.hash || domain.username || domain.password
      || !/^[a-z0-9]{1,128}$/.test(clientId)) return null
    for (const url of [callback, logout]) {
      if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && url.hostname === 'localhost'))
        || url.username || url.password || url.search || url.hash) return null
    }
    if (callback.origin !== logout.origin || callback.pathname !== '/auth/callback' || logout.pathname !== '/') return null
    return { authority: authority.href, domain: domain.origin, clientId, redirectUri: callback.href, logoutUri: logout.href }
  } catch { return null }
}

export function cognitoLogoutUrl(config: AuthConfig): string {
  const url = new URL('/logout', config.domain)
  url.search = new URLSearchParams({ client_id: config.clientId, logout_uri: config.logoutUri }).toString()
  return url.href
}

// Only workspace destinations are restored, never callback parameters or external URLs.
const destinations = new Set(['/', '/analytics', '/forecasting', '/anomalies', '/models', '/pipeline', '/profile'])
export function safeDestination(value: unknown): string {
  return typeof value === 'string' && destinations.has(value) ? value : '/'
}
