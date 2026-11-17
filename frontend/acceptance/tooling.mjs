import fs from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {AcceptanceError,requireThat} from './core.mjs';
export const HERE = path.dirname(new URL(import.meta.url).pathname);
export const PROJECT = path.resolve(HERE,'../..');
export const BINDINGS_SHA = '78e8305b92e8ec338f6dc330456ca427b12c5cbeccce9eabfc7e78549ebfaccc';
export async function hashFile(file) {
  const fd = await fs.open(file, constants.O_RDONLY|constants.O_NOFOLLOW);
  try {
    const before=await fd.stat();
    requireThat(before.isFile() && before.size<=512*1024*1024,'TOOL_FILE_INVALID');
    const hash=createHash('sha256');
    for await (const data of fd.createReadStream({autoClose:false})) hash.update(data);
    const after=await fd.stat();
    requireThat(before.ino===after.ino && before.size===after.size && before.mtimeMs===after.mtimeMs,'TOOL_CHANGED_DURING_CHECK');
    return {bytes:after.size,sha256:hash.digest('hex')};
  } finally { await fd.close(); }
}
export async function verifyTree(root, expected, links) {
  const actual=new Set(),actualLinks=new Set();
  async function walk(dir) {
    const info=await fs.lstat(dir);
    requireThat(info.isDirectory()&&!info.isSymbolicLink() && !(info.mode&0o022)
      && [0,process.getuid()].includes(info.uid),'UNSAFE_TOOL_DIRECTORY');
    for (const item of await fs.readdir(dir,{withFileTypes:true})) {
      const file=path.join(dir,item.name),rel=path.relative(root,file);
      requireThat(!rel.startsWith('..') && actual.size+actualLinks.size<2000,'TOOL_INVENTORY_REJECTED');
      if(item.isSymbolicLink()) {
        requireThat(links[rel]===await fs.readlink(file),'TOOL_LINK_MISMATCH');
        const target=await fs.realpath(file);
        requireThat(target.startsWith(root+path.sep),'TOOL_LINK_ESCAPE');actualLinks.add(rel);
      } else if(item.isDirectory()) await walk(file);
      else {
        const info=await fs.lstat(file);
        requireThat(info.isFile() && !(info.mode&0o022) && [0,process.getuid()].includes(info.uid),'UNSAFE_TOOL_FILE');
        requireThat(Object.hasOwn(expected,rel),'TOOL_INVENTORY_MISMATCH');
        requireThat(JSON.stringify(await hashFile(file))===JSON.stringify({bytes:expected[rel].bytes,sha256:expected[rel].sha256}),'TOOL_HASH_MISMATCH');
        actual.add(rel);
      }
    }
  }
  await walk(root);
  requireThat(actual.size===Object.keys(expected).length && actualLinks.size===Object.keys(links).length,'TOOL_INVENTORY_MISMATCH');
}
export async function checkTooling() {
  try {
    const raw=await fs.readFile(path.join(HERE,'bindings.json'));
    requireThat(createHash('sha256').update(raw).digest('hex')===BINDINGS_SHA,'BINDINGS_MISMATCH');
    const b=JSON.parse(raw);
    requireThat(process.versions.node===b.node && process.platform==='darwin' && process.arch==='arm64','LOCAL_RUNTIME_MISMATCH');
    for (const item of [b.playwright,b.browser]) {
      let current=path.parse(item.root).root;
      for(const part of item.root.split(path.sep).filter(Boolean)) {
        current=path.join(current,part);
        const stat=await fs.lstat(current);requireThat(stat.isDirectory()&&!stat.isSymbolicLink(),'TOOL_PARENT_SYMLINK');
      }
      await verifyTree(item.root,item.files,item.links);
    }
    const p=JSON.parse(await fs.readFile(path.join(b.playwright.root,'package.json')));
    const browsers=JSON.parse(await fs.readFile(path.join(b.playwright.root,'browsers.json')));
    requireThat(p.name==='playwright-core' && p.version==='1.61.1'
      && browsers.browsers.some(x=>x.name==='chromium' && x.revision==='1228' && x.browserVersion==='149.0.7827.55'),'TOOL_VERSION_MISMATCH');
    const executable=path.join(b.browser.root,b.browser.executable);
    await fs.access(executable,constants.X_OK);
    return {library:path.join(b.playwright.root,'index.mjs'),executable,version:b.browser.version};
  } catch(error) {
    if(error instanceof AcceptanceError) throw error;
    throw new AcceptanceError(error?.code==='ENOENT'?'LOCAL_TOOLING_MISSING':'LOCAL_TOOLING_UNVERIFIED');
  }
}
