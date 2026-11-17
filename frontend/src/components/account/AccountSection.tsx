import { useId, type ReactNode } from 'react'

export function AccountSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  const id = useId()
  return <section className="account-section" aria-labelledby={id}>
    <div className="account-section-heading"><h2 id={id}>{title}</h2>{description && <p>{description}</p>}</div>
    <div className="account-section-content">{children}</div>
  </section>
}

export function AccountField({ label, value, status }: { label: string; value: ReactNode; status?: ReactNode }) {
  return <div className="account-field"><dt>{label}</dt><dd><span>{value}</span>{status}</dd></div>
}
