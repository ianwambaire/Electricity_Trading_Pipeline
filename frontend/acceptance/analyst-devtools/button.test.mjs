import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {mountButton} from './button.mjs';
import {instrument} from './build.mjs';
import {verifySaved} from './verify-saved.mjs';
function dom(){
 const ids=new Map();
 function node(){return {children:[],events:{},disabled:false,textContent:'',setAttribute(){},append(...n){this.children.push(...n)},prepend(n){this.children.unshift(n)},addEventListener(name,fn){this.events[name]=fn}}}
 const body=node();return {body,createElement:()=>node(),getElementById:id=>ids.get(id),ids};
}
test('file-based UI performs no request until owner click and suppresses double click',async()=>{
 const document=dom();let calls=0;const timers=[];
 mountButton({document,run:async()=>{calls++;return {httpStatus:403,adminDataDisclosed:false,result:'PASS'}},now:()=>1,expiresAt:100,schedule:f=>timers.push(f)});
 assert.equal(calls,0);const [title,button,output]=document.body.children[0].children;
 assert.ok(title.textContent.includes('Local-only'));await Promise.all([button.events.click(),button.events.click()]);
 assert.equal(calls,1);assert.equal(button.disabled,true);assert.equal(output.textContent,'{"httpStatus":403,"adminDataDisclosed":false,"result":"PASS"}');
});
test('expired file exposes no test UI and makes no call',()=>{
 const document=dom();mountButton({document,run:()=>assert.fail(),now:()=>100,expiresAt:99,schedule:()=>assert.fail()});assert.equal(document.body.children.length,0);
});
test('expiry disables the button and exceptions never display raw errors',async()=>{
 const document=dom();let expire;mountButton({document,run:async()=>{throw Error('PRIVATE')},now:()=>1,expiresAt:100,schedule:f=>expire=f});
 const [,button,out]=document.body.children[0].children;expire();assert.equal(button.disabled,true);
 await button.events.click();assert.equal(out.textContent,'{"httpStatus":null,"adminDataDisclosed":null,"result":"FAIL"}');
});
test('exact V5 button override parses without a Console-callable global seam',async()=>{
 const raw=await fs.readFile(new URL('../../../data/backups/private-staging-releases/phase-operational-evidence-20261107-v5/release/static/assets/index-B_Ifb4TY.js',import.meta.url));
 const result=instrument(raw.toString('utf8'),Date.now()+1000,{button:true});
 assert.ok(result.includes('Run Analyst authorization check once'));assert.equal(result.includes('Object.defineProperty(globalThis,"powerflowAnalystAuthorizationCheck"'),false);
});
test('saved-public-asset verifier accepts exact bytes and rejects modifications and symlinks',async()=>{
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'powerflow-saved-asset-'));
 try{
  const target=path.join(dir,'index-B_Ifb4TY.js'),source=new URL('../../../data/backups/private-staging-releases/phase-operational-evidence-20261107-v5/release/static/assets/index-B_Ifb4TY.js',import.meta.url);
  await fs.copyFile(source,target);assert.equal(await verifySaved(target),true);
  await fs.appendFile(target,'x');assert.equal(await verifySaved(target),false);
  await fs.unlink(target);await fs.symlink(source,target);assert.equal(await verifySaved(target),false);
  assert.equal(await verifySaved(path.join(dir,'other.js')),false);
 }finally{await fs.rm(dir,{recursive:true,force:true})}
});
