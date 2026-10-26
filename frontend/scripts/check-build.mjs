// Local artifact checks, not a secret scanner or installed Nginx validation.
import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'
const option=(name,fallback)=>{const i=process.argv.indexOf(name);return i<0?fallback:process.argv[i+1]}
const root=resolve(option('--dist','dist'))
const release=process.argv.includes('--release')
const expectedOrigin=option('--origin',null)
async function files(dir) {
  const entries=await readdir(dir,{withFileTypes:true})
  assert.ok(!entries.some(e=>e.isSymbolicLink()),'Symlinked release assets are forbidden')
  return (await Promise.all(entries.map(e=>e.isDirectory()?files(resolve(dir,e.name)):resolve(dir,e.name)))).flat()
}
const paths=await files(root)
assert.ok(!paths.some(p=>p.endsWith('.map')),'Production source maps must not be published')
assert.ok(!paths.some(p=>/[/\\](tests|src|node_modules)[/\\]/.test(p)),'Publish dist only, without development/test sources')
const html=await readFile(resolve(root,'index.html'),'utf8')
const entry=html.match(/src="(\/assets\/index-[^"]+\.js)"/)
assert.ok(entry,'Expected hashed application entry')
for(const match of html.matchAll(/(?:src|href)="(\/[^"#]+)"/g)) {
 const resource=resolve(root,match[1].slice(1))
 assert.ok(paths.includes(resource),'HTML resource must be an included regular release file')
 await readFile(resource)
}
const js=paths.filter(p=>p.endsWith('.js'))
const content=await Promise.all(js.map(p=>readFile(p)))
assert.ok(!content.some(b=>b.includes('preflight-fixture')||b.includes('LOCAL PREFLIGHT ONLY')||b.includes('visual-fixture')||b.includes('Isolated UI test — Analyst fixture')),'UI fixture must not ship')
const metadata=JSON.parse(await readFile(resolve(root,'build-config.json'),'utf8'))
assert.equal(metadata.apiBase,'/api','API must remain same-origin')
if(release){
 assert.ok(expectedOrigin,'Release asset guard requires an explicit origin')
 assert.equal(metadata.releaseEligible,true,'A local build is not a deployable release')
 assert.equal(metadata.origin,expectedOrigin,'Artifact origin mismatch')
 assert.ok(!content.some(b=>/https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\]):\d+/i.test(b.toString())),'Development origin embedded in release assets')
 assert.ok(!content.some(b=>/https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?\/(?:auth\/callback|(?:[^\s"']*)auth)/i.test(b.toString())),'Development callback embedded in release assets')
}
const initial=await readFile(resolve(root,entry[1].slice(1)))
console.log(JSON.stringify({entryBytes:initial.length,entryGzipBytes:gzipSync(initial).length,totalJsBytes:content.reduce((n,b)=>n+b.length,0),jsChunks:js.length,sourceMaps:0,testSources:0,releaseEligible:metadata.releaseEligible,origin:metadata.origin},null,2))
