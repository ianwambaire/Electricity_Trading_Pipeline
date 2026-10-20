import { Link } from 'react-router-dom'
import { PageHeading } from '../components/ui/PageHeading'
import { EmptyState } from '../components/ui/States'
import { Panel } from '../components/ui/Panel'

export function NotFoundPage() {
  return <><PageHeading title="Page not found" description="This address does not match a PowerFlow workspace page." /><Panel title="Find your way back"><EmptyState awaitingIntegration={false} title="We couldn’t find that page" description="Use the navigation to open a workspace, or return to Market Overview." /><div className="flex justify-center pb-8"><Link className="secondary-button" to="/">Return to Market Overview</Link></div></Panel></>
}
