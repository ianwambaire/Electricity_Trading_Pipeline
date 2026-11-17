"""One diagnostic-only SSH invocation; no deployment actions or automatic retries."""
import argparse
import ast
import json
import os
from pathlib import Path
import tempfile
import types
import hashlib
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
REPORT_SCOPE=None
def read(p):
    import stat
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_size<=4*1024*1024
        return f.read(4*1024*1024+1)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def verify(expected):
    global REPORT_SCOPE
    raw=read(HERE/'MANIFEST.json');assert sha(raw)==expected;m=json.loads(raw)
    name=str((HERE/'build.py').relative_to(ROOT));builder=read(HERE/'build.py');assert sha(builder)==m['artifacts'][name]
    b=types.ModuleType('verified_import_builder');b.__file__=str(HERE/'build.py');exec(compile(builder,'<verified-import-builder>','exec'),b.__dict__)
    assert m['version']==1 and m['execution_authorized']is False and m['release']==b.RELEASE and m['parent_manifest']==b.PARENT_SHA and m['parent_preflight']==b.PREFLIGHT_SHA
    assert set(m['artifacts'])=={str((HERE/n).relative_to(ROOT)) for n in b.FILES}|{b.TEST}
    for rel,digest in m['artifacts'].items():
        assert not Path(rel).is_absolute() and '..'not in Path(rel).parts and sha(read(ROOT/rel))==digest
    prefix,wrapper,base,original=b.parent();payload,child=b.assemble(prefix,original,{n:read(HERE/n) for n in b.FILES})
    assert sha(original)==m['original_child_sha256'] and sha(payload)==m['payload_sha256'] and sha(child)==m['child_sha256']
    assert payload==read(HERE/'inspect.payload.py') and child==read(HERE/'child.payload.py')
    rules=b.module(read(HERE/'inspect.py'),'report_rules',HERE/'inspect.py')
    REPORT_SCOPE={'modules':set(ast.literal_eval(ast.parse(original).body[4].value)),'stdlib':set(sys.stdlib_module_names),
                  'dependencies':b.module(read(HERE/'child.py'),'report_child_rules',HERE/'child.py').DEPENDENCIES,
                  'exceptions':rules.EXCEPTIONS,'events':rules.EVENTS,'categories':rules.CATEGORIES,
                  'stages':rules.STAGES|{'CHILD_STARTUP','RELEASE_PREREQUISITE'},'release':b.RELEASE,'parent':b.PARENT_SHA}
    return payload,wrapper,base
def report_valid(r):
    scope=REPORT_SCOPE;assert scope is not None
    allowed={'status','stage','category','exception','candidate_module','module','import_name','line','audit_event','cause_exception','errno','changed','release','parent_manifest','child_status','child_exit_status'}
    assert type(r)is dict and set(r)==allowed and r['status']in {'PASS','BLOCKED'} and r['changed']is False
    assert all(type(v)in {str,int,bool,type(None)} and (type(v)is not str or len(v)<=120) for v in r.values())
    assert all(r[k]is None or type(r[k])is str and __import__('re').fullmatch('[A-Za-z0-9_.]+',r[k]) for k in ['exception','candidate_module','module','import_name','audit_event','cause_exception'])
    assert __import__('re').fullmatch('[A-Z0-9_]{1,80}',r['category']) and r['child_status']in {'PASS','BLOCKED','NOT_REACHED'}
    assert r['stage']in scope['stages'] and r['release']==scope['release'] and r['parent_manifest']==scope['parent']
    assert r['line']is None or type(r['line'])is int and 0<r['line']<100000
    assert r['errno']is None or type(r['errno'])is int and 0<r['errno']<256
    assert r['child_exit_status']is None or type(r['child_exit_status'])is int and -128<=r['child_exit_status']<=255
    assert all(r[k]is None or r[k]in scope['exceptions'] for k in ['exception','cause_exception'])
    assert r['audit_event']is None or r['audit_event']in scope['events']
    for key in ['candidate_module','module','import_name']:
        value=r[key]
        assert value is None or value=='REDACTED_MODULE' or value in scope['modules'] or value in scope['stdlib'] or __import__('re').fullmatch(r'[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*',value) and value.split('.')[0]in scope['dependencies'] and not __import__('re').search('token|password|credential|secret|private',value)
    assert r['candidate_module']is None or r['candidate_module']in scope['modules']
    if r['status']=='PASS':assert r['category']=='IMPORT_PASS' and r['stage']=='COMPLETE' and r['child_status']=='PASS'
    return r
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempts=0
    try:
        payload,wrapper,base=verify(a.manifest_sha256);profile=wrapper.profile()
        if a.local_check:print('{"status":"LOCAL_PASS","ssh_attempts":0}');return 0
        argv=wrapper.ssh_argv(profile);argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 90s /usr/bin/python3 -I -S -B -'
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='forecast-import-diagnostic-',dir=wrapper.PRIVATE/'preflight'))
        attempts=1;r=base.bounded_run(argv,input=payload,timeout=150,limit=16384,grace=5)
        report=None;failure=r['failure']
        if not failure:
            try:
                report=report_valid(json.loads(r['stdout']));assert (r['returncode']==0)==(report['status']=='PASS')
            except Exception:failure='SSH_FAILURE'if r['returncode']==255 else'UNVERIFIED_OUTPUT'
        # Retain only sanitized projection, never raw SSH/child stderr, exception
        # messages, traceback text, source contents or environment values.
        summary={'exit_status':r['returncode'],'failure':failure,'report':report,'ssh_attempts':1}
        with (folder/'assessment.json').open('x') as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));print(json.dumps({'private_evidence':str(folder)}));return r['returncode']or(1 if failure else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED','category':'LOCAL_BINDING_OR_IDENTITY_FAILURE'if attempts==0 else'DIAGNOSTIC_TRANSPORT_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
