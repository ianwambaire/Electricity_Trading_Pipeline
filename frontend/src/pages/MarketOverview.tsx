import { ArrowDownToLine, ArrowRight, ChartNoAxesCombined, Network, Radio, TrendingUp, Waves, Wind } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeading } from '../components/ui/PageHeading'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/States'
import { IntegrationNotice } from '../components/ui/IntegrationNotice'

const metrics = [
  { label: 'Electricity price', unit: 'EUR / MWh', icon: TrendingUp },
  { label: 'System load', unit: 'MW', icon: Waves },
  { label: 'Renewable generation', unit: 'MW', icon: Wind },
  { label: 'Forecast availability', unit: 'Not connected', icon: Radio },
]

export function MarketOverview() {
  return <>
    <PageHeading title="Market Overview" description="A clearer perspective on electricity markets, forecasts, and operations." />
    <IntegrationNotice />
    <div className="metric-grid">{metrics.map(({ label, unit, icon: Icon }) => <section className="metric-card" key={label} aria-label={`${label}: unavailable`}><div className="flex items-center justify-between gap-3"><h2>{label}</h2><Icon size={18} aria-hidden="true" /></div><p className="metric-value" aria-label="No data">—</p><p className="metric-unit">{unit}</p><div className="metric-caption">{label === 'Forecast availability' ? 'No forecast status has been retrieved' : 'No market observations loaded'}</div></section>)}</div>
    <div className="overview-grid">
      <Panel title="Electricity price outlook" description="Observed market prices and forecast context, in one place."><EmptyState icon={ChartNoAxesCombined} title="The market view starts here" description="Price history and forecast series will appear here after the data connection is approved." /><div className="panel-footer"><span>Price history & forecast context</span><Link to="/forecasting">Explore forecasting <ArrowRight size={15} aria-hidden="true" /></Link></div></Panel>
      <Panel title="Workspace connections" description="A transparent view of what is available."><ul className="connection-list">{['Market observations', 'Forecast reports', 'Pipeline monitoring'].map((label) => <li key={label}><span className="connection-dot" aria-hidden="true" /><span>{label}</span><span className="connection-status">Not connected</span></li>)}</ul><div className="connection-note"><Network size={20} aria-hidden="true" /><p>Service health will be displayed once the backend is connected. No service status is assumed.</p></div><Link className="text-link px-6 pb-6" to="/pipeline">View pipeline workspace <ArrowRight size={15} aria-hidden="true" /></Link></Panel>
    </div>
    <section className="explore-section" aria-labelledby="explore-heading"><div className="section-heading"><h2 id="explore-heading">Explore your workspace</h2><span>From market context to model understanding</span></div><div className="explore-grid">{[
      { path: '/forecasting', title: 'Forecast Intelligence', text: 'Explore forecast horizons, availability, and reliability.', icon: TrendingUp },
      { path: '/analytics', title: 'Market Analytics', text: 'Understand price history, generation, and market patterns.', icon: ChartNoAxesCombined },
      { path: '/models', title: 'Model Insights', text: 'Understand model releases, evaluation, and limitations.', icon: ArrowDownToLine },
    ].map(({ path, title, text, icon: Icon }) => <Link to={path} className="explore-card" key={path}><span className="explore-icon"><Icon size={21} aria-hidden="true" /></span><h3>{title}</h3><p>{text}</p><ArrowRight size={17} className="explore-arrow" aria-hidden="true" /></Link>)}</div></section>
  </>
}
