import { Activity, SearchCheck, ChartNoAxesCombined, CircleUserRound, LayoutDashboard, Network, ScanLine } from 'lucide-react'

export const navigation = [
  { path: '/', label: 'Executive Overview', icon: LayoutDashboard, section: 'Workspace' },
  { path: '/analytics', label: 'Market Intelligence', icon: ChartNoAxesCombined, section: 'Workspace' },
  { path: '/forecasting', label: 'Forecast Intelligence', icon: Activity, section: 'Workspace' },
  { path: '/anomalies', label: 'Anomaly Detection', icon: SearchCheck, section: 'Workspace' },
  { path: '/models', label: 'Model Insights', icon: ScanLine, section: 'Platform' },
  { path: '/pipeline', label: 'Pipeline Operations', icon: Network, section: 'Platform' },
  { path: '/profile', label: 'My Profile', icon: CircleUserRound, section: 'Account' },
]
