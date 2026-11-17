import type { ReactNode } from 'react'

export function Panel({ title, description, children, className = '' }: { title: string; description?: string; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}><div className="panel-heading"><h2>{title}</h2>{description && <p>{description}</p>}</div>{children}</section>
}
