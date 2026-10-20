import { Activity, ChartNoAxesCombined, CircleUserRound, LayoutDashboard, Network, ScanLine } from 'lucide-react'

export const navigation = [
  { path: '/', label: 'Market Overview', icon: LayoutDashboard, section: 'Workspace' },
  { path: '/forecasting', label: 'Forecast Intelligence', icon: Activity, section: 'Workspace' },
  { path: '/analytics', label: 'Market Analytics', icon: ChartNoAxesCombined, section: 'Workspace' },
  { path: '/pipeline', label: 'Pipeline Operations', icon: Network, section: 'Platform' },
  { path: '/models', label: 'Model Insights', icon: ScanLine, section: 'Platform' },
  { path: '/profile', label: 'My Profile', icon: CircleUserRound, section: 'Account' },
]
