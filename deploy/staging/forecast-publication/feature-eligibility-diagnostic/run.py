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
OWN=PREFIX+'feature-eligibility-diagnostic/'
ORIGINAL=PREFIX+'withholding-diagnostic/MANIFEST.json'
ORIGINAL_SHA='0c7c781aec0d017097488872508e6ed94f6c74ee1f8e4e30f8a384b2a0eed26e'
CORE='deploy/staging/forecast-consistency-release/preflight_readonly.py'
WRAPPER='deploy/staging/forecast-consistency-release/run_preflight.py'
DIAG='deploy/staging/forecast-consistency-release/publication_diagnostic.py'
CONTRACT='src/shared/forecast_publication.py'
AUTO=PREFIX+'automatic.py'
BUILDER=PREFIX+'prepare.py'
ACTIVATION=PREFIX+'automation-continuation-v2/MANIFEST.json'
ACTIVATION_SHA='53fcc9323a5bacf81ffb5bf067048df3403be4eeca3b7a2dd6e4e6f770f9907a'
PREFECT_SOURCE=PREFIX+'automatic-acceptance-v2/inspect.py'
WITHHOLDING=PREFIX+'withholding-diagnostic/inspect.py'
ARTIFACTS={WITHHOLDING,PREFIX+'automatic-acceptance-v2/MANIFEST.json','src/processing/build_silver_dataset.py','src/ingestion/fetch_entsoe_data.py','tests/test_feature_eligibility_diagnostic.py',PREFECT_SOURCE,PREFIX+'automatic-acceptance/MANIFEST.json','src/models/next24h_production.py','tests/test_withholding_diagnostic.py',CORE,WRAPPER,DIAG,CONTRACT,AUTO,BUILDER,ACTIVATION,ORIGINAL,OWN+'inspect.py',OWN+'run.py',OWN+'build.py',OWN+'REVIEW.md','tests/test_automatic_acceptance_prefect.py','tests/test_automatic_acceptance.py','src/store_data.py','src/scheduled_pipeline.py','src/shared/forecast_delivery.py','database/schema.sql'}|{PREFIX+'withholding-diagnostic/'+name for name in ['inspect.py','run.py','build.py','REVIEW.md']}|{PREFIX+'automatic-acceptance-v2/'+name for name in ['inspect.py','run.py','build.py','REVIEW.md']}|{PREFIX+'automatic-acceptance/'+name for name in ['inspect.py','run.py','build.py','REVIEW.md']}

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

def reader_source(raw):
    tree=ast.parse(raw)
    names={'need','stamp','uid','state','task','prefect_request','directory','database_outcome'}
    tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) or isinstance(n,ast.ClassDef) and n.name=='Stop' or isinstance(n,ast.FunctionDef) and n.name in names]
    counts=[0,0]
    class Narrow(ast.NodeTransformer):
        def visit_Set(self,node):
            if {getattr(n,'value',None) for n in node.elts}=={'pipeline_runs','pipeline_stage_timings'}:
                node.elts.append(ast.Constant(value='operational_incidents'));counts[0]+=1
            return node
        def visit_Return(self,node):
            if isinstance(node.value,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='internal_run_id' for k in node.value.keys):
                counts[1]+=1;return ast.parse('return detail(c,flow,t,value,internal,rows[0])').body[0]
            return node
    tree=Narrow().visit(tree)
    if counts!=[1,1]:raise ValueError('reader_extraction_scope')
    return ast.unparse(ast.fix_missing_locations(tree)).encode()

def assemble(blobs):
    code=reader_source(blobs[PREFECT_SOURCE])
    text="from pathlib import Path\nR={'__name__':'readonly_reader','ROOT':Path('/home/ec2-user/Electricity_Trading_Pipeline'),'DEP':'47e5ef51-26d0-44b6-b119-2c40d0e77397'}\n"
    text+="exec(compile("+repr(code)+",'<verified-readonly-reader>','exec'),R)\n"
    text+="W={'__name__':'verified_withholding','R':R}\nexec(compile("+repr(blobs[WITHHOLDING])+",'<verified-withholding>','exec'),W)\nR['detail']=W['detail']\n"
    text+="READ={'__name__':'readonly_capture','NAMES':set()}\nexec(compile("+repr(extract(blobs[AUTO],['require','capture']))+",'<verified-capture>','exec'),READ)\n"
    hashes={name:sha(blobs[name]) for name in ['src/models/next24h_production.py','src/processing/build_silver_dataset.py','src/ingestion/fetch_entsoe_data.py']}
    text+="exec(compile("+repr(blobs[OWN+'inspect.py'])+",'<verified-feature-diagnostic>','exec'),{'__name__':'__main__','R':R,'W':W,'READ':READ,'SOURCE_HASHES':"+repr(hashes)+"})\n"
    return text.encode()

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
    reader=namespace(reader_source(blobs[PREFECT_SOURCE]),'readonly_validator'); validator=namespace(blobs[OWN+'inspect.py'],'validator');validator['R']=reader; validator['W']=namespace(blobs[WITHHOLDING],'withholding_validator');validator['W']['R']=reader
    return payload,wrapper,namespace(blobs[CORE],'base'),validator

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
