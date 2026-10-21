import { useServerAccount } from '../../auth/serverAccountContext'
import { useAuth } from 'react-oidc-context'
import { identityFromProfile } from '../../auth/identity'
import { SignOutButton } from '../../auth/SignOutButton'
import { useEffect, useRef, useState } from 'react'
import { ChevronRight, CircleUserRound, Menu, PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { navigation } from '../../config/navigation'
import { Brand } from './Brand'
import { Navigation } from './Navigation'

export function AppLayout() {
  const auth = useAuth()
  const server = useServerAccount()
  const identity = identityFromProfile(auth.user?.profile ?? {})
  const [collapsed, setCollapsed] = useState(false)
  const mobileDialog = useRef<HTMLDialogElement>(null)
  const main = useRef<HTMLElement>(null)
  const location = useLocation()
  const current = navigation.find((item) => item.path === location.pathname)
  const title = current?.label ?? 'Page not found'

  useEffect(() => {
    document.title = `${title} · PowerFlow`
    main.current?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }, [location.pathname, title])

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)')
    const closeOnDesktop = () => { if (media.matches) mobileDialog.current?.close() }
    media.addEventListener('change', closeOnDesktop)
    return () => media.removeEventListener('change', closeOnDesktop)
  }, [])

  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="desktop-sidebar" aria-label="Workspace sidebar">
        <Brand compact={collapsed} />
        <Navigation compact={collapsed} />
        <div className="sidebar-bottom">

          <button className="collapse-button" onClick={() => setCollapsed(!collapsed)}
            aria-expanded={!collapsed} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {collapsed ? <PanelLeftOpen size={19} aria-hidden="true" /> : <><PanelLeftClose size={19} aria-hidden="true" /><span>Collapse sidebar</span></>}
          </button>
        </div>
      </aside>

      <dialog ref={mobileDialog} className="mobile-dialog" aria-labelledby="mobile-navigation-title" onClick={(event) => {
        if (event.target === event.currentTarget) mobileDialog.current?.close()
      }}>
        <div className="mobile-dialog-body">
          <div className="flex items-center justify-between gap-4"><Brand /><button className="icon-button" aria-label="Close navigation" onClick={() => mobileDialog.current?.close()}><X size={20} /></button></div>
          <h2 id="mobile-navigation-title" className="sr-only">Workspace navigation</h2>
          <Navigation onNavigate={() => mobileDialog.current?.close()} />
        </div>
      </dialog>

      <div className="workspace">
        <header className="topbar">
          <div className="flex min-w-0 items-center gap-3">
            <button className="icon-button mobile-menu-button" aria-label="Open navigation" aria-haspopup="dialog" onClick={() => mobileDialog.current?.showModal()}><Menu size={21} /></button>
            <span className="topbar-workspace">DE-LU</span><ChevronRight className="topbar-divider" size={15} aria-hidden="true" /><span className="truncate text-sm font-medium">{title}</span>
          </div>
          <div className="flex shrink-0 items-center gap-4">
            <span className="foundation-badge"><span aria-hidden="true" />Read-only workspace</span>
            <Link to="/profile" className="account-link" aria-label="My Profile"><CircleUserRound size={23} aria-hidden="true" /><span className="account-identity">{identity.name ?? identity.email ?? 'My account'}<small>{server.account?.role ?? (server.loading ? 'Verifying role…' : 'Role unavailable')}</small></span></Link>{location.pathname !== '/profile' && <div className="topbar-signout"><SignOutButton /></div>}
          </div>
        </header>
        <main id="main-content" ref={main} tabIndex={-1} className="main-content"><Outlet /></main>
        <footer className="app-footer"><span>PowerFlow <span aria-hidden="true">/</span> Electricity market intelligence</span><span>Authenticated workspace · Read-only data access</span></footer>
      </div>
    </div>
  )
}
