import type { AuthConfig } from './config.ts'

export interface SessionEvidence {
  profile: Record<string, unknown>
  access_token: string
  expires_at?: number
  expired?: boolean
}
export interface Identity {
  name: string | null
  email: string | null
  emailVerified: boolean | null
  role: 'Admin' | 'Analyst'
  accountReference: string
  provider: string
  federatedProvider: string | null
}
const text = (value: unknown, max = 320): string | null => typeof value === 'string' && value.trim() && value.length <= max ? value : null

// Additional presentation checks on the OIDC library's session, not server authorization.
// Never construct this evidence by decoding a user-supplied token.
export function sessionUsable(user: SessionEvidence | null | undefined, config: AuthConfig, now = Date.now()): boolean {
  if (!user || user.expired || !user.access_token || !Number.isFinite(user.expires_at) || user.expires_at! * 1000 <= now) return false
  const p = user.profile
  // Cognito user-pool ID tokens bind aud to one app client.
  const audience = p.aud === config.clientId
  return p.iss === config.authority && audience && p.token_use === 'id' && !!text(p.sub, 128)
    && typeof p.exp === 'number' && Number.isFinite(p.exp) && p.exp * 1000 > now
}

export function identityFromProfile(profile: Record<string, unknown>): Identity {
  const groups = profile['cognito:groups']
  const role = Array.isArray(groups) && groups.every(group => typeof group === 'string') && groups.includes('powerflow-admins') ? 'Admin' : 'Analyst'
  let federatedProvider: string | null = null
  try {
    const raw = profile.identities
    const identities: unknown = typeof raw === 'string' && raw.length < 4096 ? JSON.parse(raw) : raw
    if (Array.isArray(identities) && identities.length === 1 && identities[0]?.providerName === 'Google') federatedProvider = 'Google identity reported by Cognito'
  } catch { /* Omit ambiguous provider claims. */ }
  const sub = text(profile.sub, 128)
  return {
    name: text(profile.name), email: text(profile.email),
    emailVerified: typeof profile.email_verified === 'boolean' ? profile.email_verified : null,
    role, accountReference: sub ? `${sub.slice(0, 8)}…${sub.slice(-4)}` : 'Not supplied', provider: 'Amazon Cognito', federatedProvider,
  }
}

export type GateState = 'loading' | 'error' | 'authenticated' | 'signed-out'
export function authGateState(loading: boolean, error: boolean, authenticated: boolean, usable: boolean): GateState {
  return loading ? 'loading' : error ? 'error' : authenticated && usable ? 'authenticated' : 'signed-out'
}
