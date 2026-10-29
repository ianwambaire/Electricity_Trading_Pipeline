import { useEffect, useState } from 'react'

export function useClock(deadline?: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    if (deadline === undefined || !Number.isFinite(deadline)) return
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, deadline - Date.now() + 1))
    return () => window.clearTimeout(timer)
  }, [deadline])
  return now
}
