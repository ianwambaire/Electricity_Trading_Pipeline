// Local artifact checks, not a secret scanner or installed Nginx validation.
import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'
const root=resolve('dist')
async function files(dir) {
  const entries=await readdir(dir,{withFileTypes:true})
  return (await Promise.all(entries.map(e=>e.isDirectory()?files(resolve(dir,e.name)):resolve(dir,e.name)))).flat()
}
const paths=await files(root)
assert.ok(!paths.some(p=>p.endsWith('.map')),'Production source maps must not be published')
assert.ok(!paths.some(p=>/[/\\](tests|src|node_modules)[/\\]/.test(p)),'Publish dist only, without development/test sources')
const html=await readFile(resolve(root,'index.html'),'utf8')
const entry=html.match(/src="(\/assets\/index-[^"]+\.js)"/)
assert.ok(entry,'Expected hashed application entry')
for(const match of html.matchAll(/(?:src|href)="(\/[^"#]+)"/g)) await readFile(resolve(root,match[1].slice(1)))
const js=paths.filter(p=>p.endsWith('.js'))
const content=await Promise.all(js.map(p=>readFile(p)))
assert.ok(!content.some(b=>b.includes('preflight-fixture')||b.includes('LOCAL PREFLIGHT ONLY')||b.includes('visual-fixture')||b.includes('Isolated UI test — Analyst fixture')),'UI fixture must not ship')
const initial=await readFile(resolve(root,entry[1].slice(1)))
console.log(JSON.stringify({entryBytes:initial.length,entryGzipBytes:gzipSync(initial).length,totalJsBytes:content.reduce((n,b)=>n+b.length,0),jsChunks:js.length,sourceMaps:0,testSources:0},null,2))
