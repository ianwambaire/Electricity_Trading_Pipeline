// Presentation only: these verified OIDC profile attributes never authorize API access.
export interface ProfileDetails {
  name: string | null
  email: string | null
  emailVerified: boolean | null
  preferredUsername: string | null
  googleConnected: boolean
  initials: string | null
}
function attribute(value: unknown, limit = 320): string | null {
  if (typeof value !== 'string' || !value.trim() || value.length > limit || [...value].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) return null
  return value.trim()
}
export function profileDetails(profile: Record<string, unknown>): ProfileDetails {
  const name = attribute(profile.name)
  const email = attribute(profile.email)
  let googleConnected = false
  try {
    const raw: unknown = typeof profile.identities === 'string' && profile.identities.length <= 4096 ? JSON.parse(profile.identities) : profile.identities
    googleConnected = Array.isArray(raw) && raw.length <= 10 && raw.some(row => row && typeof row === 'object' && row.providerName === 'Google')
  } catch { /* Unavailable linkage is not evidence of a native password account. */ }
  const parts = name?.split(/\s+/).filter(Boolean) ?? []
  const initials = parts.length ? [parts[0], ...(parts.length > 1 ? [parts.at(-1)!] : [])].map(part => Array.from(part)[0]).join('').toLocaleUpperCase() : null
  return {
    name, email, emailVerified: typeof profile.email_verified === 'boolean' ? profile.email_verified : null,
    preferredUsername: attribute(profile.preferred_username, 128), googleConnected, initials,
  }
}
