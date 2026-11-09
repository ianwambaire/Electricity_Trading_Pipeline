"""Deterministic ACL-only assembly; imports verified tools without running them."""
import ast
import hashlib
import json
from pathlib import Path
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-parent-acl-20261108-v1'
TRANSACTION='6b59b34d211a4d7286e598137a512e8e'
PARENT='deploy/staging/realized-parent-traversal-diagnostic-v3'
PARENT_SHA='6fb6cd73259c8c6961cc954cc636603abb90a2fcae7983ade15578d7d166fcbe'
V1='deploy/staging/realized-parent-traversal-diagnostic-v1'
BASE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
BASE_SHA='bbd94119fbed5b7e0d6c154167fa44ec32e3a0733c3d49c02521c5bfbf126463'
OWN={'policy.py','acl_read.py','guards.py','probe.py','transaction.py','build.py','run.py','REVIEW.md','protocol.py'}
TEST='tests/test_realized_parent_acl_release.py'
ACTIONS={'preflight':(30,60),'apply':(45,75),'rollback':(45,75)}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    import os,stat
    path=Path(path);assert not any(p.is_symlink()for p in(path,*path.parents))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode)and s.st_size<=4*1024**2
        raw=f.read(4*1024**2+1);assert len(raw)==s.st_size;return raw

def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def artifact_paths():
    return {str((HERE/n).relative_to(ROOT))for n in OWN}|{TEST,PARENT+'/run.py',PARENT+'/MANIFEST.json',V1+'/inspect.py',V1+'/producer.py',BASE}

def references():
    raw=read(ROOT/PARENT/'MANIFEST.json');assert sha(raw)==PARENT_SHA;m=json.loads(raw)
    source=read(ROOT/PARENT/'run.py');assert sha(source)==m['artifacts'][PARENT+'/run.py']
    parent=module(source,'acl_parent_v3',ROOT/PARENT/'run.py');runner,values=parent.verify(PARENT_SHA)
    original=json.loads(read(ROOT/V1/'MANIFEST.json'))
    for name in ['inspect.py','producer.py']:
        assert sha(read(ROOT/V1/name))==original['artifacts'][V1+'/'+name]['sha256']
    assert sha(read(ROOT/BASE))==BASE_SHA
    return parent,runner,values

def subset(raw,names,imports=True):
    text=raw.decode();tree=ast.parse(text);nodes=[];seen=set()
    for n in tree.body:
        if imports and isinstance(n,(ast.Import,ast.ImportFrom)):nodes.append(n)
        elif isinstance(n,ast.FunctionDef)and n.name in names:nodes.append(n);seen.add(n.name)
    assert seen==set(names)
    return ('\n'.join(ast.get_source_segment(text,n)for n in nodes)+'\n').encode()

def assemble(action):
    assert action in ACTIONS
    parent,runner,values=references();transport,wrapper,supervisor,_,_,_,_=values
    sources={n:read(HERE/n)for n in ['policy.py','acl_read.py','guards.py','probe.py','transaction.py','protocol.py']}
    binding=sha(b'ACL-V1\0'+action.encode()+b'\0'+b''.join(sources[n]for n in sorted(sources)))
    config={'release':RELEASE,'transaction':TRANSACTION,'binding':binding,'action':action,'control':'/var/lib/powerflow-staging/realized-parent-acl-'+TRANSACTION}
    helper=subset(read(ROOT/V1/'producer.py'),{'security_context'})
    probes={flag:b'EXPECT_SEARCH='+str(flag).encode()+b'\n'+helper+sources['probe.py']for flag in [False,True]}
    # AST copies reviewed functions only; no application code is imported.
    meta=subset(read(ROOT/V1/'inspect.py'),{'identities','read_proc','trusted_commands','need'})
    meta+=b"\nclass Stop(ValueError):pass\nSERVICE_ARGV=['/usr/bin/systemctl','show','powerflow-prefect-worker.service','--no-pager','--property=User,Group,MainPID']\n"
    base=subset(read(ROOT/BASE),{'read','request','api','pipeline'})
    base+=b"\nDEPLOYMENT='47e5ef51-26d0-44b6-b119-2c40d0e77397'\n"
    text=transport.bounded_source(read(ROOT/BASE))+b'\n_supervise=bounded_run\nimport types\n'
    text+=b'C='+repr(config).encode()+b'\n'
    for name,raw in [('META',meta),('BASE',base)]:
        text+=name.encode()+b'=types.ModuleType('+repr(name).encode()+b')\nexec(compile('+repr(raw).encode()+b",'<verified-read-only-support>','exec'),"+name.encode()+b'.__dict__)\n'
    for name in ['policy.py','acl_read.py','guards.py']:
        text+=b'exec(compile('+repr(sources[name]).encode()+b",'<verified-"+name.encode()+b">','exec'))\n"
    text+=b'PROBE_DENIED='+repr(probes[False]).encode()+b'\nPROBE_GRANTED='+repr(probes[True]).encode()+b'\n'
    counts={'preflight':(2,1),'apply':(7,3),'rollback':(3,2)}[action]
    text+=b'_counts={"service":0,"probe":0}\n_limits='+repr(dict(zip(['service','probe'],counts))).encode()+b'\n'
    text+=b'''def process(argv,input=b'',timeout=5,limit=4096,grace=5):
 key='service'if argv==META.SERVICE_ARGV else'probe'if argv==CHILD_ARGV else'NONE'
 need(key!='NONE','COMMAND_SCOPE')
 need((key=='service'and input==b'')or(key=='probe'and input in[PROBE_DENIED,PROBE_GRANTED]),'COMMAND_INPUT_SCOPE')
 need(timeout==5 and limit==4096 and grace==5 and _counts[key]<_limits[key],'COMMAND_BOUND')
 _counts[key]+=1
 return _supervise(argv,input=input,timeout=timeout,limit=limit,grace=grace)
META.bounded_run=process
'''
    if action!='preflight':text+=b'exec(compile('+repr(sources['transaction.py']).encode()+b",'<verified-acl-transaction>','exec'))\n"
    # Class names/errno only. Fixed allowlist prevents exception payload disclosure.
    reasons=set()
    for raw in [*sources.values(),meta]:
        reasons.update(n.value for n in ast.walk(ast.parse(raw))if isinstance(n,ast.Constant)and type(n.value)is str and n.value.isupper()and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789'for c in n.value))
    text+=b'REASONS='+repr(sorted(reasons)).encode()+b'\n'
    text+=b'''try:
 META.trusted_commands()
 report=globals()[C['action']]()
except Exception as error:
 reason=str(error)if isinstance(error,(Stop,META.Stop))else''
 if reason not in REASONS:reason='FILESYSTEM_OPERATION_FAILED'if isinstance(error,OSError)else'UNVERIFIED_OPERATION'
 report={'status':'BLOCKED','phase':PHASE,'changed':CHANGED,'reason':reason,'exception_category':'OS_ERROR'if isinstance(error,OSError)else'VALIDATION_ERROR'if isinstance(error,(Stop,META.Stop))else'OTHER_ERROR','errno':getattr(error,'errno',None)if getattr(error,'errno',None)in{1,2,13,20,38,40,61,95}else None}
print(json.dumps({'version':1,'release':C['release'],'transaction':C['transaction'],'binding':C['binding'],'action':C['action'],'report':report},sort_keys=True,separators=(',',':')))
raise SystemExit(0 if report['status']!='BLOCKED'else 1)
'''
    ast.parse(text,feature_version=(3,9));assert len(text)<100000
    return text,config

def main():
    outputs={};payloads={}
    for action in ACTIONS:
        raw,c=assemble(action);outputs[HERE/(action+'.payload.py')]=raw;payloads[action]={'bytes':len(raw),'sha256':sha(raw),'binding':c['binding']}
    m={'version':1,'release':RELEASE,'transaction':TRANSACTION,'execution_authorized':False,'parent_manifest':PARENT_SHA,'limits':{a:{'remote_seconds':v[0],'local_seconds':v[1],'escalation_seconds':5,'stream_bytes':8192,'ssh_attempts':1}for a,v in ACTIONS.items()},'artifacts':{p:sha(read(ROOT/p))for p in sorted(artifact_paths())},'payloads':payloads}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n';outputs[HERE/'MANIFEST.json']=raw
    for p,v in outputs.items():
        if p.exists():assert read(p)==v,'IMMUTABLE_RELEASE_DRIFT'
    for p,v in outputs.items():
        if not p.exists():
            with p.open('xb')as f:f.write(v)
    print(json.dumps({'release':RELEASE,'manifest_sha256':sha(raw),'payloads':payloads,'ssh_attempts':0},sort_keys=True))
if __name__=='__main__':main()
