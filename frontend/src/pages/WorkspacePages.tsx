import { CircleUserRound, ShieldCheck } from 'lucide-react'
import { PageHeading } from '../components/ui/PageHeading'
import { Panel } from '../components/ui/Panel'
import { EmptyState } from '../components/ui/States'

export function ProfilePage() {
  return <><PageHeading category="Account" title="My Profile" description="Your identity, access, and workspace preferences in one place." /><div className="profile-grid"><Panel title="Account"><EmptyState icon={CircleUserRound} title="No account connected" description="Authentication is not enabled in this frontend. No user identity, email, or access role is assumed." /></Panel><Panel title="Account services"><div className="profile-info"><span className="state-icon"><ShieldCheck size={25} aria-hidden="true" /></span><h3>Your identity stays with your identity provider</h3><p>Profile details and account actions will be introduced after the authentication integration is approved.</p><dl><div><dt>Identity</dt><dd>Not connected</dd></div><div><dt>Access permissions</dt><dd>Not available</dd></div><div><dt>Account management</dt><dd>Planned</dd></div></dl></div></Panel></div></>
}
