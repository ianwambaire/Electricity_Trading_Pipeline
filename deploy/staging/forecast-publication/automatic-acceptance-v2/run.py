"""One hash-bound read-only acceptance. Live mode needs separate authorization."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
PREFIX='deploy/staging/forecast-publication/'
OWN=PREFIX+'automatic-acceptance-v2/'
ORIGINAL=PREFIX+'automatic-acceptance/MANIFEST.json'
ORIGINAL_SHA='0da25e6276f0a2589fb61ed08820dabf7163323e5e2e3801f18cd1a7277ebf11'
CORE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
WRAPPER='deploy/staging/forecast-consistency-release/run_preflight.py'
DIAG='deploy/staging/forecast-consistency-release/publication_diagnostic.py'
CONTRACT='src/shared/forecast_publication.py'
AUTO=PREFIX+'automatic.py'
BUILDER=PREFIX+'prepare.py'
ACTIVATION=PREFIX+'automation-continuation-v2/MANIFEST.json'
ACTIVATION_SHA='53fcc9323a5bacf81ffb5bf067048df3403be4eeca3b7a2dd6e4e6f770f9907a'
ARTIFACTS={CORE,WRAPPER,DIAG,CONTRACT,AUTO,BUILDER,ACTIVATION,ORIGINAL,OWN+'inspect.py',OWN+'run.py',OWN+'build.py',OWN+'REVIEW.md','tests/test_automatic_acceptance_prefect.py','tests/test_automatic_acceptance.py','src/store_data.py','src/scheduled_pipeline.py','src/shared/forecast_delivery.py','database/schema.sql'}|{PREFIX+'automatic-acceptance/'+name for name in ['inspect.py','run.py','build.py','REVIEW.md']}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW),'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('file_type')
        raw=f.read(2000001)
    if len(raw)>2000000:raise ValueError('file_bound')
    return raw

def extract(raw,names):
    tree=ast.parse(raw);found={n.name for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names}
    if found!=set(names):raise ValueError('helper_scope')
    tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) or isinstance(n,ast.FunctionDef) and n.name in names]
    tree=ast.fix_missing_locations(tree);return ast.unparse(tree).encode()

def assemble(blobs):
    cfg=json.loads(blobs[ACTIVATION])['config']
    content="import sys,types\n"
    for name,key in [('BASE',CORE),('DIAGNOSTIC',DIAG)]:
        content+=name+"={'__name__':'verified_readonly'}\nexec(compile("+repr(blobs[key])+",'<verified-readonly>','exec'),"+name+")\n"
    content+="CONTRACT=types.ModuleType('shared.forecast_publication')\nexec(compile("+repr(blobs[CONTRACT])+",'<verified-contract>','exec'),CONTRACT.__dict__)\n"
    content+="previous={k:sys.modules.get(k) for k in ('shared','shared.forecast_publication')}\npackage=types.ModuleType('shared');package.__path__=[]\nsys.modules['shared']=package;sys.modules['shared.forecast_publication']=CONTRACT\n"
    content+="BUILDER=types.ModuleType('readonly_builder')\nexec(compile("+repr(extract(blobs[BUILDER],['build']))+",'<verified-readonly-builder>','exec'),BUILDER.__dict__)\n"
    content+="for k,v in previous.items():\n if v is None:sys.modules.pop(k,None)\n else:sys.modules[k]=v\n"
    content+="READ={'__name__':'verified_readonly_helpers','NAMES':{'forecast.csv','provenance.json','model.json','evidence.json','integrity.json'}}\nexec(compile("+repr(extract(blobs[AUTO],['require','stamp','capture','persisted']))+",'<verified-readonly-helpers>','exec'),READ)\n"
    hashes={name:cfg['files'][name]['sha256'] for name in ['pipeline','delivery']}
    content+="exec(compile("+repr(blobs[OWN+'inspect.py'])+",'<verified-acceptance>','exec'),{'__name__':'__main__','BASE':BASE,'DIAGNOSTIC':DIAGNOSTIC,'CONTRACT':CONTRACT,'BUILDER':BUILDER,'READ':READ,'SOURCE_HASHES':"+repr(hashes)+"})\n"
    return content.encode()

def namespace(raw,name,file=None):
    ns={'__name__':name}
    if file:ns['__file__']=str(file)
    exec(compile(raw,'<verified-'+name+'>','exec'),ns);return ns

def verify(expected):
    raw=read(HERE/'MANIFEST.json')
    if sha(raw)!=expected:raise ValueError('manifest_hash')
    m=json.loads(raw)
    if set(m)!={'version','artifacts','payload_sha256','activation_manifest_sha256','supersedes_manifest_sha256'} or m['version']!=2 or set(m['artifacts'])!=ARTIFACTS or m['activation_manifest_sha256']!=ACTIVATION_SHA or m['supersedes_manifest_sha256']!=ORIGINAL_SHA:raise ValueError('manifest_scope')
    blobs={}
    for name,item in m['artifacts'].items():
        raw=read(ROOT/name)
        if len(raw)!=item['bytes'] or sha(raw)!=item['sha256']:raise ValueError('dependency_hash')
        blobs[name]=raw
    if sha(blobs[ORIGINAL])!=ORIGINAL_SHA:raise ValueError('original_manifest_hash')
    for name,item in json.loads(blobs[ORIGINAL])['artifacts'].items():
        if name not in blobs or len(blobs[name])!=item['bytes'] or sha(blobs[name])!=item['sha256']:raise ValueError('original_dependency_hash')
    if sha(blobs[ACTIVATION])!=ACTIVATION_SHA:raise ValueError('activation_binding')
    cfg=json.loads(blobs[ACTIVATION])['config']
    for name,path in [('pipeline','src/scheduled_pipeline.py'),('delivery','src/shared/forecast_delivery.py')]:
        if sha(blobs[path])!=cfg['files'][name]['sha256']:raise ValueError('installed_source_binding')
    for name,path in [('automatic.py',AUTO),('prepare.py',BUILDER),('shared/forecast_publication.py',CONTRACT)]:
        if sha(blobs[path])!=cfg['installed_tools'][name]:raise ValueError('installed_validator_binding')
    payload=assemble(blobs)
    if len(payload)>1000000 or sha(payload)!=m['payload_sha256']:raise ValueError('payload_hash')
    wrapper=namespace(blobs[WRAPPER],'wrapper',ROOT/WRAPPER);wrapper['profile']()
    return payload,wrapper,namespace(blobs[CORE],'base'),namespace(blobs[OWN+'inspect.py'],'validator')

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args()
    folder=None;summary={'exit_status':None,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    try:
        payload,w,b,v=verify(a.manifest_sha256)
        if a.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        profile=w['profile']();argv=w['ssh_argv'](profile)
        argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 90s /usr/bin/python3 -I -S -B -'
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='automatic-acceptance-',dir=w['PRIVATE']/'preflight'))
        r=b['bounded_run'](argv,input=payload,timeout=150,limit=65536,grace=5)
        summary={'exit_status':r['returncode'],'failure_category':r['failure'],'report':None}
        for key in ['stdout','stderr']:
            with os.fdopen(os.open(folder/(key+'.private'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(r[key])
        if not r['failure']:
            try:
                report=v['validate_report'](json.loads(r['stdout']))
                if r['returncode']!=(0 if report['status']=='PASS' else 1):raise ValueError('exit_status')
                summary['report']=report
            except Exception:summary['failure_category']=w['failure_category'](r['returncode'],r['stderr']) if r['returncode'] else 'UNEXPECTED_OUTPUT'
    except Exception:
        if folder:summary['failure_category']='INSPECTION_OR_CAPTURE_FAILURE'
    if folder:
        with os.fdopen(os.open(folder/'assessment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as f:json.dump(summary,f,indent=2,allow_nan=False)
    print(json.dumps(summary,sort_keys=True));return 0 if summary['report'] and summary['report']['status']=='PASS' and summary['failure_category']is None else 1
if __name__=='__main__':raise SystemExit(main())
