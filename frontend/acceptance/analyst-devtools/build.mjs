import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import ts from '../../node_modules/typescript/lib/typescript.js';
import {createProbe, PROBE} from './probe.mjs';
import {mountButton} from './button.mjs';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
export const MANIFEST='cdd828defc52ea258852b88aa852d1d470ca915d098021d6ff8fd2be9b05223b';
export const BUNDLE='/assets/index-B_Ifb4TY.js';
export const BUNDLE_HASH='e5c1053921f36b834a80bd7b73b3fb61f9a77c76de02922a1af877243c736e71';
export const sha=raw=>createHash('sha256').update(raw).digest('hex');
const need=v=>{if(!v)throw Error('OVERRIDE_BINDING_FAILED')};
export function instrument(source,expiresAt,{button=false}={}){
  need(Number.isSafeInteger(expiresAt)&&!source.includes(PROBE)&&!source.includes('__pfAnalystProbe'));
  const ast=ts.createSourceFile('v5.js',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
  need(ast.parseDiagnostics.length===0);
  const apis=[],functions=[];
  function visit(n){
    if(ts.isVariableDeclaration(n)&&ts.isIdentifier(n.name)&&n.initializer&&ts.isObjectLiteralExpression(n.initializer)){
      const props=n.initializer.properties.filter(p=>p.name?.getText(ast)==='currentAdminOperations');
      if(props.length===1){
        const p=props[0];need(ts.isPropertyAssignment(p)&&ts.isArrowFunction(p.initializer)&&ts.isCallExpression(p.initializer.body));
        const call=p.initializer.body;need(ts.isIdentifier(call.expression)&&call.arguments[0].text==='/admin/operations/current');
        apis.push({name:n.name.text,request:call.expression.text});
      }
    }
    if(ts.isFunctionDeclaration(n))functions.push(n);
    ts.forEachChild(n,visit);
  }
  visit(ast);need(apis.length===1);
  const api=apis[0],fn=functions.filter(n=>n.name?.text===api.request);need(fn.length===1);
  const calls=[],checks=[];
  function find(n){
    if(ts.isVariableDeclaration(n)&&ts.isIdentifier(n.name)&&n.initializer&&ts.isAwaitExpression(n.initializer)){
      const c=n.initializer.expression;
      if(ts.isCallExpression(c)&&c.expression.getText(ast)==='fetch')calls.push(n);
    }
    if(ts.isIfStatement(n)&&ts.isBinaryExpression(n.expression)&&n.expression.operatorToken.kind===ts.SyntaxKind.CommaToken
      &&ts.isCallExpression(n.expression.left)&&ts.isIdentifier(n.expression.left.expression)&&n.expression.left.arguments.length===0)checks.push(n.expression.left);
    ts.forEachChild(n,find);
  }
  find(fn[0]);need(calls.length===1&&ts.isIdentifier(fn[0].parameters[0].name));
  need(checks.length===1);
  const response=calls[0],pos=checks[0].end;
  need(pos>response.end);
  // Observe only after the existing originating-session assertion has succeeded.
  const tap=',await __pfAnalystProbe.observe('+fn[0].parameters[0].name.text+','+response.name.text+')';
  let helper='\nconst __pfAnalystProbe=('+createProbe.toString()+')({client:()=>'+api.name+'.currentAdminOperations(),origin:()=>location.origin,pathname:()=>location.pathname,role:()=>document.querySelector(".account-identity small")?.textContent.trim(),marker:{getItem:k=>sessionStorage.getItem(k),setItem:(k,v)=>sessionStorage.setItem(k,v)},now:()=>Date.now(),expiresAt:'+expiresAt+',schedule:(f,t)=>setTimeout(f,t),remove:()=>{delete globalThis.'+PROBE+'}});\n';
  if(button) helper+='if(location.origin==="https://staging.powerflowenergy.dev"&&location.pathname==="/pipeline")('+mountButton.toString()+')({document,run:__pfAnalystProbe.run,now:()=>Date.now(),expiresAt:'+expiresAt+',schedule:(f,t)=>setTimeout(f,t)});\n';
  else helper+='if(Date.now()<'+expiresAt+')Object.defineProperty(globalThis,"'+PROBE+'",{configurable:true,value:__pfAnalystProbe.run});\n';
  const output=source.slice(0,pos)+tap+source.slice(pos)+helper;
  need(ts.createSourceFile('override.js',output,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS).parseDiagnostics.length===0);
  return output;
}
export async function build({button=false}={}){
  const raw=await fs.readFile(path.join(ROOT,'deploy/staging/operational-evidence-release-v5/MANIFEST.json'));
  need(sha(raw)===MANIFEST);
  const m=JSON.parse(raw),binding=m.config.files['static'+BUNDLE];
  need(binding.sha256===BUNDLE_HASH&&binding.bytes===383151);
  const source=await fs.readFile(path.join(ROOT,binding.source));need(sha(source)===BUNDLE_HASH&&source.length===binding.bytes);
  const expiresAt=Date.now()+2*60*60*1000;
  const result=instrument(source.toString('utf8'),expiresAt,{button});
  const base=path.join(ROOT,'data/backups/private-staging-browser-acceptance');
  const info=await fs.lstat(base);need(info.isDirectory()&&!info.isSymbolicLink()&&(info.mode&0o777)===0o700);
  const folder=await fs.mkdtemp(path.join(base,button?'devtools-analyst-button-v5-':'devtools-analyst-v5-'));
  await fs.chmod(folder,0o700);
  const root=path.join(folder,'overrides'),destination=path.join(root,'staging.powerflowenergy.dev',BUNDLE.slice(1));
  await fs.mkdir(path.dirname(destination),{recursive:true,mode:0o700});
  await fs.writeFile(destination,result,{flag:'wx',mode:0o600});
  const summary={v5Manifest:MANIFEST,bundle:BUNDLE,originalSha256:BUNDLE_HASH,overrideSha256:sha(result),expiresAt:new Date(expiresAt).toISOString(),overrideRoot:root,overrideFile:destination};
  await fs.writeFile(path.join(folder,'bindings.json'),JSON.stringify(summary,null,2)+'\n',{flag:'wx',mode:0o600});
  return summary;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  need(process.argv.length===2||process.argv.length===3&&process.argv[2]==='--button');
  console.log(JSON.stringify(await build({button:process.argv[2]==='--button'}),null,2));
}
