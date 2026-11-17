import type { LucideIcon } from 'lucide-react'
import { AlertCircle, Inbox, LoaderCircle } from 'lucide-react'

export function EmptyState({ title, description, icon: Icon = Inbox, awaitingIntegration = true }: { title: string; description: string; icon?: LucideIcon; awaitingIntegration?: boolean }) {
  return <div className="empty-state"><span className="state-icon"><Icon size={24} strokeWidth={1.5} aria-hidden="true" /></span><h3>{title}</h3><p>{description}</p>{awaitingIntegration && <span className="empty-tag">Awaiting integration</span>}</div>
}

export function LoadingState({ label = 'Loading workspace data…' }: { label?: string }) {
  return <div role="status" className="feedback-state"><LoaderCircle size={23} className="loading-spinner" aria-hidden="true" /><p>{label}</p></div>
}

export function ErrorState({ title = 'Unable to load this section', description, onRetry }: { title?: string; description: string; onRetry?: () => void }) {
  return <div role="alert" className="feedback-state error-state"><AlertCircle size={24} aria-hidden="true" /><h3>{title}</h3><p>{description}</p>{onRetry && <button className="secondary-button" onClick={onRetry}>Try again</button>}</div>
}
