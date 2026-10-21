// Set by the OIDC lifecycle only. Never persisted here or returned by API errors.
let readAccessToken: (() => string | null) | undefined
let onUnauthorized: (() => void) | undefined
export function bindApiSession(read: () => string | null, expire: () => void): () => void {
  readAccessToken = read
  onUnauthorized = expire
  return () => { if (readAccessToken === read) { readAccessToken = undefined; onUnauthorized = undefined } }
}
export function apiAuthorization(): Record<string, string> {
  const token = readAccessToken?.()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
export function rejectApiSession(): void { onUnauthorized?.() }
