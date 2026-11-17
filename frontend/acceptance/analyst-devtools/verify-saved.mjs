// Hash only a user-saved public JS asset. No browser, auth or network access.
import fs from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {sha,BUNDLE_HASH} from './build.mjs';
export async function verifySaved(file){
  if(path.basename(file)!=='index-B_Ifb4TY.js')return false;
  let fd;
  try{
    fd=await fs.open(file,constants.O_RDONLY|constants.O_NOFOLLOW);
    const s=await fd.stat();
    if(!s.isFile()||s.size!==383151||s.uid!==process.getuid()||s.nlink!==1)return false;
    return sha(await fd.readFile())===BUNDLE_HASH;
  }catch{return false}finally{if(fd)await fd.close()}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  console.log(process.argv.length===3&&await verifySaved(process.argv[2])?'V5_BUNDLE_MATCH':'STOP_BUNDLE_MISMATCH');
}
