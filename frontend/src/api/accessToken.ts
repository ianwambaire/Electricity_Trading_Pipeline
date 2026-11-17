// Bound to the originating OIDC session; never persisted or included in errors.
type Binding = { read: () => string | null; expire: () => void; rejected: boolean }
let current: Binding | undefined
export function bindApiSession(read: () => string | null, expire: () => void): () => void {
  const binding = { read, expire, rejected: false }
  current = binding
  return () => { if (current === binding) current = undefined }
}
export function captureApiSession() {
  const binding = current
  const rejected = binding?.rejected
  const token = binding && !binding.rejected ? binding.read() : null
  return {
    headers: token ? { Authorization: `Bearer ${token}` } : {} as Record<string, string>,
    isCurrent() { return current === binding && (!binding || (binding.rejected === rejected && (binding.rejected ? null : binding.read()) === token)) },
    reject() {
      // Late responses and renewed tokens must never invalidate a newer session.
      if (binding && current === binding && !binding.rejected && binding.read() === token) {
        binding.rejected = true
        binding.expire()
      }
    },
  }
}
export function apiAuthorization(): Record<string, string> { return captureApiSession().headers }
export function rejectApiSession(): void { captureApiSession().reject() }
