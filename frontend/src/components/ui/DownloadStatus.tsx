import { useEffect, useState } from 'react'
import { DOWNLOAD_STATUS_EVENT } from '../../api/csv'

export function DownloadStatus() {
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const show = () => setFailed(true)
    window.addEventListener(DOWNLOAD_STATUS_EVENT, show)
    return () => window.removeEventListener(DOWNLOAD_STATUS_EVENT, show)
  }, [])
  return failed ? <div className="notice notice-error" role="alert"><p>The CSV download could not be started. Check browser download permissions and try again.</p><button className="secondary-button" onClick={() => setFailed(false)}>Dismiss download message</button></div> : null
}
