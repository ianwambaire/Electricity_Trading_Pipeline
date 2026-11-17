"""Manifest-bound one-attempt transport; --local-check NEVER invokes SSH.
Remote preflight/apply/rollback/accept each require separate owner authorization.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent

def read(p,limit=4*1024*1024):
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_size>limit:raise ValueError('local_file')
        return f.read(limit+1)

def sha(raw):return hashlib.sha256(raw).hexdigest()
def module(raw,name,path=None):
    import types
    m=types.ModuleType(name)
    if path:m.__file__=str(path)
    exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m


def verify(expected,action):
    raw=read(HERE/'MANIFEST.json');
    if sha(raw)!=expected:raise ValueError('manifest_hash')
    m=json.loads(raw)
    if m['version']!=1 or m['execution_authorized']is not False or m['release']!='phase-operational-evidence-20261107-v5' or m['transaction']!='4f6cf4afa15647b0b14d904b50379ef1':raise ValueError('manifest_identity')
    entry=m['artifacts']['deploy/staging/operational-evidence-release-v5/build.py']
    b=read(HERE/'build.py')
    if sha(b)!=entry['sha256'] or len(b)!=entry['bytes']:raise ValueError('builder_hash')
    build=module(b,'verified_builder',HERE/'build.py')
    if set(m['artifacts'])!=build.ARTIFACTS or set(m['payloads'])!={'preflight','apply','rollback','accept'}:raise ValueError('artifact_scope')
    blobs={}
    for name,item in m['artifacts'].items():
        p=Path(name)
        if p.is_absolute() or '..'in p.parts:raise ValueError('dependency_path')
        content=read(ROOT/p)
        if sha(content)!=item['sha256'] or len(content)!=item['bytes']:raise ValueError('dependency_hash')
        blobs[name]=content
    config,data=build.build_config(False)
    if config!=m['config']:raise ValueError('release_inventory_drift')
    payload=build.assemble(action,config,blobs,data);item=m['payloads'][action]
    if len(payload)!=item['bytes'] or sha(payload)!=item['sha256'] or payload!=read(HERE/(action+'.payload.py')):raise ValueError('payload_hash')
    wrapper=module(blobs[build.WRAPPER],'verified_wrapper',ROOT/build.WRAPPER)
    wrapper.profile()  # original pinned identity/destination/known-host validation
    base=module(blobs[build.BASE],'verified_supervisor')
    return payload,wrapper,base


def validate_report(report):
    fields={'status','phase','changed','reason','errno','path_id','forecast_enabled','operational_enabled','root_access','baseline_sha256',
            'forecast_preserved','authenticated_admin','natural_run_acceptance','retained_immutable_releases_and_store','operational_status',
            'retained_infrastructure_verified','nginx_routing_verified','nginx_restored','http_endpoint','http_status','http_content_type','http_measured_bytes','nginx_syntax',
            'evidence_sha256','natural_run','execution','inference','forecast_delivery','forecast_http','forecast_status',
            'admin_projection_same_source','observed_at','fresh_until','historical_fallback','browser'}
    statuses={'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS','PARTIAL','BLOCKED'}
    if type(report)is not dict or not set(report)<=fields or report.get('status')not in statuses:raise ValueError('report_schema')
    if any(type(v)not in (str,int,bool,type(None)) or isinstance(v,str) and len(v)>200 for v in report.values()):raise ValueError('report_bound')
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['preflight','apply','rollback','accept']);p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');args=p.parse_args()
    attempts=0;folder=None
    try:
        payload,wrapper,base=verify(args.manifest_sha256,args.action)
        if args.local_check:print('{"status":"LOCAL_PASS","ssh_attempts":0}');return 0
        profile=wrapper.profile();argv=wrapper.ssh_argv(profile)
        seconds=90 if args.action in {'preflight','accept'} else 120
        argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s '+str(seconds)+'s /usr/bin/python3 -I -S -B -'
        os.umask(0o077)
        folder=Path(tempfile.mkdtemp(prefix='operational-release-'+args.action+'-',dir=wrapper.PRIVATE/'preflight'))
        attempts=1
        result=base.bounded_run(argv,input=payload,timeout=seconds+60,limit=65536,grace=5)
        for name in ['stdout','stderr']:
            with os.fdopen(os.open(folder/(name+'.private'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(result[name])
        summary={'exit_status':result['returncode'],'failure':result['failure'],'report':None,'ssh_attempts':1}
        if not result['failure']:
            try:
                report=validate_report(json.loads(result['stdout']))
                if len(result['stdout'])>32768:raise ValueError()
                if (result['returncode']==0)!=(report['status'] in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK','PASS'}):raise ValueError('report_exit_status')
                summary['report']=report
            except Exception:summary['failure']='UNVERIFIED_OUTPUT'
        with (folder/'assessment.json').open('x') as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return result['returncode'] or (1 if summary['failure'] else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED' if attempts==0 else 'FAILED','reason':'LOCAL_INTEGRITY_OR_PINNED_IDENTITY' if attempts==0 else 'TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1

if __name__=='__main__':raise SystemExit(main())
