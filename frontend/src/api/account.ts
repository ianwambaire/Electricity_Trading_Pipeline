export interface ServerAccount {
  subject: string
  role: 'Admin' | 'Analyst'
  email: string | null
  display_name: string | null
}
export function parseAccount(value: unknown): ServerAccount {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('Invalid account response')
  const row = value as Record<string, unknown>
  if (typeof row.subject !== 'string' || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(row.subject)
    || (row.role !== 'Admin' && row.role !== 'Analyst')) throw Error('Invalid account response')
  const optional = (v: unknown) => {
    if (v === null) return null
    if (typeof v !== 'string' || v.length > 320 || [...v].some(char => char.charCodeAt(0) < 32)) throw Error('Invalid identity field')
    return v
  }
  return { subject: row.subject, role: row.role, email: optional(row.email), display_name: optional(row.display_name) }
}
