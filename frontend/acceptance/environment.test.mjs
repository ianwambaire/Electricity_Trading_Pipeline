// Local process-boundary fixtures only. No browser/acceptance run or network.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {BASE_ENV_KEYS,DARWIN_RUNTIME_KEY,allowedEnvironmentKeys,environmentKeyReport,assertCleanEnvironment} from './environment.mjs';
import {HERE,PROJECT} from './tooling.mjs';

const NODE='/Users/iannganga/.nvm/versions/node/v22.22.0/bin/node';
const RUN=path.join(HERE,'run.mjs');
function opaque(keys) {
  const value={};
  for(const key of keys)Object.defineProperty(value,key,{enumerable:true,get(){throw Error('ENVIRONMENT_VALUE_MUST_NOT_BE_READ');}});
  return value;
}
for(const platform of ['darwin','linux','win32'])test(`base clean environment on ${platform}`,()=>{
  assert.doesNotThrow(()=>assertCleanEnvironment(opaque(BASE_ENV_KEYS),platform));
});
test('only macOS permits the proven CoreFoundation startup key',()=>{
  const value=opaque(['PATH',DARWIN_RUNTIME_KEY]);
  assert.doesNotThrow(()=>assertCleanEnvironment(value,'darwin'));
  for(const platform of ['linux','win32'])assert.throws(()=>assertCleanEnvironment(value,platform),e=>e.code==='CLEAN_ENV_REQUIRED');
  assert.deepEqual(allowedEnvironmentKeys('darwin'),[...BASE_ENV_KEYS,DARWIN_RUNTIME_KEY]);
});
for(const key of ['NODE_OPTIONS','DEBUG','PWDEBUG','HOME','HTTP_PROXY','AWS_SECRET_ACCESS_KEY','UNAPPROVED_KEY'])test(`still rejects ${key} without reading its value`,()=>{
  const env=opaque(['PATH',DARWIN_RUNTIME_KEY,key]);
  assert.throws(()=>assertCleanEnvironment(env,'darwin'),e=>e.code==='CLEAN_ENV_REQUIRED');
});
test('key-name-only report redacts unknown names and leaves environment intact',()=>{
  const value=opaque(['PATH',DARWIN_RUNTIME_KEY,'NODE_OPTIONS','NAME_CONTAINING_PRIVATE_INFORMATION']);
  const before=Object.getOwnPropertyDescriptors(value);
  const report=environmentKeyReport(value,'darwin');
  assert.deepEqual(report.unexpectedSafeKeys,['NODE_OPTIONS']);assert.equal(report.redactedUnexpectedKeyCount,1);
  assert.equal(report.accepted,false);assert.equal(JSON.stringify(report).includes('PRIVATE_INFORMATION'),false);
  assert.deepEqual(Object.getOwnPropertyDescriptors(value),before);
});
test('legacy guard fails but corrected guard accepts the exactly reproduced set',()=>{
  const report=environmentKeyReport(opaque(['PATH',DARWIN_RUNTIME_KEY]),'darwin');
  assert.equal(report.legacyGuardAccepted,false);assert.equal(report.accepted,true);
});
function execute(command,args,options={}) {
  const result=spawnSync(command,args,{env:{PATH:'/usr/bin:/bin'},timeout:10_000,maxBuffer:4096,...options});
  assert.equal(result.error,undefined,'bounded local fixture failed');
  return result;
}
test('env -i reaches Node with exact diagnostic arguments and no values in output',{skip:process.platform!=='darwin'},()=>{
  const result=execute('/usr/bin/env',['-i','PATH=/usr/bin:/bin',NODE,RUN,'--inspect-environment']);
  assert.equal(result.status,0);
  const report=JSON.parse(result.stdout);
  assert.equal(report.boundary,'harness-node-entry');assert.equal(report.exactArguments,true);
  assert.equal(report.nodeVersion,'22.22.0');assert.equal(report.nodeExecutableMatchesBinding,true);
  assert.deepEqual(report.observedSafeKeys,['PATH',DARWIN_RUNTIME_KEY].sort());
  assert.equal(report.redactedUnexpectedKeyCount,0);assert.equal(report.accepted,true);
  assert.equal(report.browserLaunches,0);assert.equal(report.stagingRequests,0);
  assert.equal(result.stderr.length,0);
});
test('explicit empty child environment reproduces the same Node startup addition',{skip:process.platform!=='darwin'},()=>{
  const result=execute(NODE,[RUN,'--inspect-environment']);
  assert.equal(result.status,0);
  assert.deepEqual(JSON.parse(result.stdout).observedSafeKeys,['PATH',DARWIN_RUNTIME_KEY].sort());
});
test('unrecognized keys remain rejected by the actual diagnostic CLI',{skip:process.platform!=='darwin'},()=>{
  const result=execute('/usr/bin/env',['-i','PATH=/usr/bin:/bin','PRIVATE_NAME_METADATA=TEST_VALUE_NOT_TO_LOG',NODE,RUN,'--inspect-environment']);
  assert.equal(result.status,1);
  const report=JSON.parse(result.stdout);
  assert.equal(report.redactedUnexpectedKeyCount,1);assert.equal(report.accepted,false);
  assert.equal(result.stdout.includes('TEST_VALUE'),false);assert.equal(result.stdout.includes('PRIVATE_NAME'),false);
});
test('extra or malformed diagnostic arguments do not enter acceptance',()=>{
  for(const args of [['--inspect-environment','extra'],['--inspect-environment=extra'],['--unknown']]) {
    const result=execute(NODE,[RUN,...args]);
    assert.equal(result.status,1);
    assert.deepEqual(JSON.parse(result.stdout),{status:'BLOCKED',failure:'OWNER_LOGIN_NOT_CONFIRMED',browserAcceptance:'NOT_OBSERVED'});
  }
});
test('native startup isolates the CoreFoundation boundary',{skip:process.platform!=='darwin'},async t=>{
  const dir=await fs.mkdtemp(path.join('/private/tmp','powerflow-env-boundary-'));
  t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const compiler='/Library/Developer/CommandLineTools/usr/bin/clang';
  const source=path.join(HERE,'environment-probe.c');
  const flags=['-isysroot','/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk','-Wall','-Wextra','-Werror'];
  const plain=path.join(dir,'native'),linked=path.join(dir,'corefoundation');
  const env={PATH:'/usr/bin:/bin',TMPDIR:dir};
  assert.equal(execute(compiler,[...flags,source,'-o',plain],{env}).status,0);
  assert.equal(execute(compiler,[...flags,'-DPROBE_COREFOUNDATION',source,'-framework','CoreFoundation','-o',linked],{env}).status,0);
  const before=execute('/usr/bin/env',['-i','PATH=/usr/bin:/bin',plain]);
  const after=execute('/usr/bin/env',['-i','PATH=/usr/bin:/bin',linked]);
  assert.deepEqual(JSON.parse(before.stdout).observedSafeKeys,['PATH']);
  assert.deepEqual(JSON.parse(after.stdout).observedSafeKeys,['PATH',DARWIN_RUNTIME_KEY]);
  assert.equal(JSON.parse(before.stdout).redactedKeyCount,0);assert.equal(JSON.parse(after.stdout).redactedKeyCount,0);
  const redacted=execute('/usr/bin/env',['-i','PATH=/usr/bin:/bin','SENSITIVE_KEY_NAME=TEST_VALUE_NOT_TO_LOG',plain]);
  assert.equal(JSON.parse(redacted.stdout).redactedKeyCount,1);
  assert.equal(redacted.stdout.includes('TEST_VALUE'),false);assert.equal(redacted.stdout.includes('SENSITIVE_KEY_NAME'),false);
});
test('existing browser guard and tool bindings are unchanged',async()=>{
  const expected={'core.mjs':'b78f13cd29bd7ef183d09c9b1b52266fbafdd607685adb25b503770514a525a8',
    'browser.mjs':'747bb74dea866d49009abfe7ca2f4b773915caa3d342919b71aabfe5432d6940',
    'tooling.mjs':'ef63956a15569bafa1bb40760ca3b793f20b63c90698b3a0c8206057492b646c',
    'bindings.json':'78e8305b92e8ec338f6dc330456ca427b12c5cbeccce9eabfc7e78549ebfaccc',
    'acceptance.test.mjs':'1e82fb0c97e0a5c92ec5aa8f1f8c7031b681ee71463106f3ed72f61a93f91d37'};
  for(const [name,digest] of Object.entries(expected))assert.equal(createHash('sha256').update(await fs.readFile(path.join(HERE,name))).digest('hex'),digest);
});
