// Local manifest assembly only. Does not import or execute browser tooling.
import fs from'node:fs/promises';import path from'node:path';import{createHash}from'node:crypto';import{fileURLToPath}from'node:url';
const HERE=path.dirname(fileURLToPath(import.meta.url)),ROOT=path.resolve(HERE,'../../..');
const names=['run.mjs','core.mjs','core.test.mjs','run.test.mjs','build.mjs','README.md','BINDINGS.json'].map(n=>'frontend/acceptance/analyst-client-authorization/'+n);
for(const n of['run.mjs','core.mjs','browser.mjs','operations.mjs','operations-core.mjs','environment.mjs','tooling.mjs','setup-diagnostics.mjs','bindings.json'])names.push('frontend/acceptance/'+n);
names.push('frontend/src/api/currentOperations.ts','deploy/staging/live-forecast-reliability-release-v2/MANIFEST.json');
const bindings=JSON.parse(await fs.readFile(path.join(HERE,'BINDINGS.json'),'utf8'));names.push(bindings.source);
if(createHash('sha256').update(await fs.readFile(path.join(ROOT,'deploy/staging/live-forecast-reliability-release-v2/MANIFEST.json'))).digest('hex')!==bindings.release_manifest)throw Error('RELEASE_BINDING');
const files={};for(const name of names.sort()){const p=path.join(ROOT,name),s=await fs.lstat(p);if(!s.isFile()||s.isSymbolicLink())throw Error('LOCAL_FILE_REJECTED');files[name]=createHash('sha256').update(await fs.readFile(p)).digest('hex');}
const raw=JSON.stringify({version:1,mode:'DIRECT_EXISTING_CLIENT',target:'https://staging.powerflowenergy.dev/api/admin/operations/current',remoteMutation:false,files},null,2)+'\n';
const dest=path.join(HERE,'MANIFEST.json');try{if(await fs.readFile(dest,'utf8')!==raw)throw Error('IMMUTABLE_MANIFEST_DRIFT');}catch(e){if(e.code!=='ENOENT')throw e;await fs.writeFile(dest,raw,{flag:'wx'});}
console.log(createHash('sha256').update(raw).digest('hex'));
