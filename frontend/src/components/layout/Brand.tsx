import { Link } from 'react-router-dom'

export function Brand({ compact = false, subtitle = true }: { compact?: boolean; subtitle?: boolean }) {
  return (
    <Link to="/" className="brand" aria-label="PowerFlow home" title="PowerFlow home">
      <span>{compact ? 'PF' : 'PowerFlow'}{!compact && subtitle && <span className="brand-caption">Electricity Trading Intelligence</span>}</span>
    </Link>
  )
}
