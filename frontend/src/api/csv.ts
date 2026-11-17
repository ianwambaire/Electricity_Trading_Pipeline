// Numeric negatives remain numeric. Untrusted text cannot become spreadsheet formulae.
export function csv(rows: (string|number|null)[][]): string {
  return rows.map(row=>row.map(value=>{const text=value===null?'':String(value);const safe=typeof value==='string' && /^[\s]*[=+@\-\t\r]/.test(text)?`'${text}`:text;return `"${safe.replaceAll('"','""')}"`}).join(',')).join('\r\n')+'\r\n'
}
export const DOWNLOAD_STATUS_EVENT = 'powerflow-download-error'
export function downloadCsv(filename: string, rows: (string|number|null)[][]): boolean {
  return startCsvDownload(filename, () => csv(rows))
}
export function downloadCsvText(filename: string, content: string): boolean {
  return startCsvDownload(filename, () => content)
}
function startCsvDownload(filename: string, content: () => string): boolean {
  let url: string | undefined
  let link: HTMLAnchorElement | undefined
  try {
    url = URL.createObjectURL(new Blob([content()], {type:'text/csv;charset=utf-8'}))
    link = document.createElement('a'); link.href = url; link.download = filename
    document.body.append(link); link.click()
    // Browsers do not expose whether the user ultimately saved the file.
    return true
  } catch {
    window.dispatchEvent(new window.Event(DOWNLOAD_STATUS_EVENT))
    return false
  } finally {
    link?.remove()
    if (url) { const created = url; window.setTimeout(() => URL.revokeObjectURL(created), 1000) }
  }
}
