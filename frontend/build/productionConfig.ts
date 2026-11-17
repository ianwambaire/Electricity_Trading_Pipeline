import { createHash } from 'node:crypto'
import { readAuthConfig } from '../src/auth/config.ts'

export function productionConfig(env: Record<string, string>, expectedOrigin?: string) {
  const keys = Object.keys(env).filter(key => key.startsWith('VITE_'))
  if (keys.some(key => /SECRET|PASSWORD|TOKEN|PRIVATE_KEY|ACCESS_KEY/i.test(key))) throw new Error('Sensitive frontend environment key is forbidden')
  const config = readAuthConfig(env)
  let releaseEligible = false
  if (expectedOrigin) {
    const origin = new URL(expectedOrigin)
    if (origin.protocol !== 'https:' || origin.origin !== expectedOrigin || origin.hostname === 'localhost' || origin.hostname.endsWith('.localhost') || origin.hostname === '127.0.0.1' || origin.hostname === '[::1]') throw new Error('Release origin must be an explicit HTTPS origin')
    if (!config || config.redirectUri !== `${origin.origin}/auth/callback` || config.logoutUri !== `${origin.origin}/`) throw new Error('Release authentication URLs must match the explicit origin')
    releaseEligible = true
  }
  const publicConfig = config ? { ...config, apiBase: '/api' } : { apiBase: '/api' }
  return {
    schemaVersion: 1, apiBase: '/api', releaseEligible,
    origin: expectedOrigin ?? null,
    // Public config digest binds artifact to reviewed values, without a build timestamp.
    publicConfigSha256: createHash('sha256').update(JSON.stringify(publicConfig)).digest('hex'),
  }
}
