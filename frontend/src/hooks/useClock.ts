import { useEffect, useState } from 'react'

export function useClock(deadline?: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const sync = () => setNow(Date.now())
    const timer = window.setInterval(sync, 15000)
    window.addEventListener('focus',sync)
    document.addEventListener('visibilitychange',sync)
    return () => { window.clearInterval(timer);window.removeEventListener('focus',sync);document.removeEventListener('visibilitychange',sync) }
  }, [])
  useEffect(() => {
    if (deadline === undefined || !Number.isFinite(deadline)) return
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, deadline - Date.now()))
    return () => window.clearTimeout(timer)
  }, [deadline])
  return now
}
