// Numeric negatives remain numeric. Untrusted text cannot become spreadsheet formulae.
export function csv(rows: (string|number|null)[][]): string {
  return rows.map(row=>row.map(value=>{const text=value===null?'':String(value);const safe=typeof value==='string' && /^[\s]*[=+@\-\t\r]/.test(text)?`'${text}`:text;return `"${safe.replaceAll('"','""')}"`}).join(',')).join('\r\n')+'\r\n'
}
export function downloadCsv(filename: string, rows: (string|number|null)[][]) {
  const url=URL.createObjectURL(new Blob([csv(rows)],{type:'text/csv;charset=utf-8'}))
  const link=document.createElement('a');link.href=url;link.download=filename;link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000)
}
