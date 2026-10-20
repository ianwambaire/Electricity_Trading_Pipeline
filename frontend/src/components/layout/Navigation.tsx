import { NavLink } from 'react-router-dom'
import { navigation } from '../../config/navigation'

export function Navigation({ compact = false, onNavigate }: { compact?: boolean; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main navigation" className="workspace-nav">
      {['Workspace', 'Platform', 'Account'].map((section) => (
        <div key={section} className="nav-group">
          {!compact && <p className="nav-label">{section}</p>}
          <ul>
            {navigation.filter((item) => item.section === section).map(({ path, label, icon: Icon }) => (
              <li key={path}>
                <NavLink to={path} end={path === '/'} onClick={onNavigate} title={compact ? label : undefined}
                  aria-label={compact ? label : undefined} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                  <Icon size={19} aria-hidden="true" />
                  {!compact && <span>{label}</span>}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}
