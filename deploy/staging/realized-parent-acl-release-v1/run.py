"""Pinned one-attempt ACL-only supervisor. Each remote action needs authorization."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-parent-acl-20261108-v1'
PARENT_SHA='6fb6cd73259c8c6961cc954cc636603abb90a2fcae7983ade15578d7d166fcbe'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    path=Path(path);assert not any(p.is_symlink()for p in(path,*path.parents))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode)and s.st_size<=4*1024**2
        raw=f.read(4*1024**2+1);assert len(raw)==s.st_size;return raw

def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def verify(expected,action):
    raw=read(HERE/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    assert set(m)=={'version','release','transaction','execution_authorized','parent_manifest','limits','artifacts','payloads'}
    assert m['version']==1 and m['release']==RELEASE and m['execution_authorized']is False and m['parent_manifest']==PARENT_SHA
    builder=read(HERE/'build.py');assert sha(builder)==m['artifacts'][str((HERE/'build.py').relative_to(ROOT))]
    b=module(builder,'acl_builder',HERE/'build.py');assert set(m['artifacts'])==b.artifact_paths()and m['transaction']==b.TRANSACTION
    assert m['limits']=={a:{'remote_seconds':v[0],'local_seconds':v[1],'escalation_seconds':5,'stream_bytes':8192,'ssh_attempts':1}for a,v in b.ACTIONS.items()}
    for p,digest in m['artifacts'].items():assert sha(read(ROOT/p))==digest
    assert set(m['payloads'])==set(b.ACTIONS)
    for a in b.ACTIONS:
        payload,c=b.assemble(a);assert payload==read(HERE/(a+'.payload.py'))and m['payloads'][a]=={'bytes':len(payload),'sha256':sha(payload),'binding':c['binding']}
    parent,runner,values=b.references();payload,c=b.assemble(action)
    protocol=module(read(HERE/'protocol.py'),'acl_protocol',HERE/'protocol.py')
    tree=ast.parse(payload);reason_node=next(n for n in tree.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='REASONS'for t in n.targets))
    return b,parent,runner,values,payload,c,protocol,set(ast.literal_eval(reason_node.value))

def command(parent,runner,values,action,seconds):
    transport,wrapper=values[:2];argv=parent.command(runner,transport,wrapper)
    assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s /usr/bin/python3 -I -S -B -'
    assert action in {'preflight','apply','rollback'}and seconds==({'preflight':30,'apply':45,'rollback':45}[action])
    argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
    assert argv.count('StdinNull=no')==1 and 'StdinNull=yes'not in argv
    return argv

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['preflight','apply','rollback']);p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempts=0
    try:
        b,parent,runner,values,payload,c,protocol,reasons=verify(a.manifest_sha256,a.action)
        argv=command(parent,runner,values,a.action,b.ACTIONS[a.action][0]);wrapper=values[1];supervisor=values[2]
        if a.local_check:print('{"local_integrity":"PASS","ssh_attempts":0}');return 0
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='realized-parent-acl-'+a.action+'-',dir=wrapper['PRIVATE']/'preflight'))
        attempts=1;r=supervisor(argv,input=payload,timeout=b.ACTIONS[a.action][1],limit=8192,grace=5)
        report=None;failure=r['failure']
        if failure is None and r['returncode']==255:failure=wrapper['failure_category'](255,r['stderr'])
        if failure is None:
            try:report=protocol.decode(r['stdout'],r['returncode'],c,reasons)
            except Exception:failure='RESPONSE_UNVERIFIED'
        summary={'status':report['status']if report else'BLOCKED','exit_status':r['returncode'],'report':report,'failure':failure,'ssh_attempts':1}
        with os.fdopen(os.open(folder/'assessment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return 0 if report and report['status']!='BLOCKED'and failure is None else 1
    except Exception:
        print(json.dumps({'status':'BLOCKED','reason':'LOCAL_INTEGRITY_OR_PINNED_IDENTITY'if not attempts else'TRANSPORT_OR_EVIDENCE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
