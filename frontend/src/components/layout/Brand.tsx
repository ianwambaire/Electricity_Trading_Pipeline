import { Zap } from 'lucide-react'
import { Link } from 'react-router-dom'

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className="brand" aria-label="PowerFlow home" title="PowerFlow home">
      <span className="brand-mark"><Zap size={23} fill="currentColor" aria-hidden="true" /></span>
      {!compact && <span>PowerFlow<span className="brand-caption">ENERGY INTELLIGENCE</span></span>}
    </Link>
  )
}
