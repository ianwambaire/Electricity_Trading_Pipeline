import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { spawnSync } from 'node:child_process'
function check(content:string,metadata:Record<string,unknown>,extraFile?:string){
 const root=mkdtempSync(join(tmpdir(),'powerflow-artifact-test-'))
 try{
  mkdirSync(join(root,'assets'))
  writeFileSync(join(root,'index.html'),'<script type="module" src="/assets/index-test.js"></script>')
  writeFileSync(join(root,'assets/index-test.js'),content)
  writeFileSync(join(root,'build-config.json'),JSON.stringify(metadata))
  if(extraFile)writeFileSync(join(root,extraFile),'test-only')
  return spawnSync(process.execPath,['scripts/check-build.mjs','--dist',root,'--release','--origin','https://candidate.example.test'],{encoding:'utf8'})
 }finally{rmSync(root,{recursive:true,force:true})}
}
const metadata={schemaVersion:1,apiBase:'/api',releaseEligible:true,origin:'https://candidate.example.test'}
test('release artifact guard rejects dev origins, fixtures, maps and local/inconsistent metadata',()=>{
 assert.equal(check('export const ok=true',metadata).status,0)
 for(const content of ['const callback="http://localhost:5175/auth/callback"','const logout="http://localhost:5175/"','const fixture="preflight-fixture"']) assert.notEqual(check(content,metadata).status,0)
 assert.notEqual(check('',metadata,'assets/index-test.js.map').status,0)
 assert.notEqual(check('',{...metadata,releaseEligible:false}).status,0)
 assert.notEqual(check('',{...metadata,origin:'https://other.example.test'}).status,0)
})

test('release artifact guard refuses symlinks without reading outside files',async()=>{
 const { symlinkSync }=await import('node:fs')
 const root=mkdtempSync(join(tmpdir(),'powerflow-artifact-link-test-'))
 try{
  mkdirSync(join(root,'assets'))
  writeFileSync(join(root,'index.html'),'<script src="/assets/index-test.js"></script>')
  symlinkSync('/nonexistent-outside-file',join(root,'assets/index-test.js'))
  const result=spawnSync(process.execPath,['scripts/check-build.mjs','--dist',root],{encoding:'utf8'})
  assert.notEqual(result.status,0)
  assert.match(result.stderr,/Symlinked release assets/)
 }finally{rmSync(root,{recursive:true,force:true})}
})
