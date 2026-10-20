import { ChevronRight, Home } from 'lucide-react'
import { Link } from 'react-router-dom'

export function PageHeading({ title, description, category = 'Workspace' }: { title: string; description: string; category?: string }) {
  return (
    <div className="page-heading">
      <nav aria-label="Breadcrumb"><ol className="breadcrumbs"><li><Link to="/" aria-label="Market Overview home"><Home size={14} aria-hidden="true" /></Link></li><li aria-hidden="true"><ChevronRight size={13} /></li><li>{category}</li><li aria-hidden="true"><ChevronRight size={13} /></li><li aria-current="page">{title}</li></ol></nav>
      <div className="heading-row"><div><h1>{title}</h1><p>{description}</p></div><span className="outline-badge">Workspace preview</span></div>
    </div>
  )
}
