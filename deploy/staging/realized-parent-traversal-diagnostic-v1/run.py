"""One immutable metadata-only diagnostic. Requires separate remote authorization."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
RELEASE='phase-realized-parent-traversal-diagnostic-20261108-v1'
ORIGIN='deploy/staging/realized-performance-release-v1'
ORIGIN_SHA='a3dceba7641ceaa9030709b1b7d4ce59460b54f5123b7e89f15d95bba39b0a83'
CONNECT='deploy/staging/ssh-connectivity-check'
CONNECT_SHA='89c54b9b34a25dde2325659bebc0d7b5c29e2c5b5f472ef07bdd15a6c56a48e3'
CONNECT_RUNNER_SHA='1d02edc366ac6ae0c4828daf9607637ebf2b27daf523dd00a61138b636678efa'
LIMITS={'remote_seconds':20,'local_seconds':40,'escalation_seconds':5,'stream_bytes':8192,'ssh_attempts':1}
REMOTE='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s /usr/bin/python3 -I -S -B -'
OWN={'run.py','build.py','inspect.py','producer.py','REVIEW.md'}
TEST='tests/test_realized_parent_traversal_diagnostic.py'
CONNECTION_ARTIFACTS={CONNECT+'/'+x for x in ['run.py','build.py','REVIEW.md','MANIFEST.json']}|{'tests/test_ssh_connectivity_check.py','deploy/staging/forecast-consistency-release/run_preflight.py','deploy/staging/forecast-consistency-release/preflight_readonly.py'}
ARTIFACTS={str((HERE/x).relative_to(ROOT))for x in OWN}|{TEST,ORIGIN+'/MANIFEST.json',ORIGIN+'/guards.py'}|CONNECTION_ARTIFACTS


def need(ok):
    if not ok:raise ValueError('DIAGNOSTIC_BINDING_REJECTED')
def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path):
    path=Path(path);need(not any(p.is_symlink()for p in(path,*path.parents)))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        s=os.fstat(f.fileno());need(stat.S_ISREG(s.st_mode)and s.st_size<=4*1024**2)
        raw=f.read(4*1024**2+1);need(len(raw)==s.st_size);return raw

def namespace(raw,name,path=None):
    m=types.ModuleType(name)
    if path is not None:m.__file__=str(path)
    exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def references(blobs):
    need(sha(blobs[ORIGIN+'/MANIFEST.json'])==ORIGIN_SHA)
    original=json.loads(blobs[ORIGIN+'/MANIFEST.json'])
    need(original['config']['root']=='/srv/powerflow/realized-performance')
    need(sha(blobs[ORIGIN+'/guards.py'])==original['artifacts'][ORIGIN+'/guards.py'])
    need(sha(blobs[CONNECT+'/MANIFEST.json'])==CONNECT_SHA and sha(blobs[CONNECT+'/run.py'])==CONNECT_RUNNER_SHA)
    # Existing immutable verifier extracts only bounded_run, never inspections or
    # its execute()/main(). It verifies the original private pinned profile locally.
    transport=namespace(blobs[CONNECT+'/run.py'],'traversal_transport',ROOT/CONNECT/'run.py')
    wrapper,supervisor,_,_=transport.verify(CONNECT_SHA)
    bounded=transport.bounded_source(blobs[transport.BASE])
    return transport,wrapper,supervisor,bounded

def assemble(blobs,bounded):
    producer=blobs[str((HERE/'producer.py').relative_to(ROOT))]
    inspector=blobs[str((HERE/'inspect.py').relative_to(ROOT))]
    text=bounded+b'\n_supervisor=bounded_run\nPRODUCER='+repr(producer).encode()+b'\n'
    text+=b'exec(compile('+repr(inspector).encode()+b",'<verified-traversal-inspection>','exec'))\n"
    text+=b"_calls={'service':0,'producer':0}\ndef bounded_run(argv,input=b'',timeout=5,limit=4096,grace=5):\n key='service'if argv==SERVICE_ARGV else'producer'if argv==CHILD_ARGV else'NONE'\n need(key!='NONE','DIAGNOSTIC_COMMAND_SCOPE')\n need((key=='service'and input==b''and limit==4096)or(key=='producer'and input==PRODUCER and limit==2048),'DIAGNOSTIC_INPUT_SCOPE')\n need(timeout==5 and grace==5 and _calls[key]==0,'DIAGNOSTIC_EXECUTION_BOUND')\n _calls[key]+=1\n return _supervisor(argv,input=input,timeout=timeout,limit=limit,grace=grace)\n"
    text+=b"try:\n report=inspect()\nexcept Exception as error:\n report=failure_report(error)\nprint(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']=='PASS'else 1)\n"
    return text

def verify(expected):
    raw=read(HERE/'MANIFEST.json');need(sha(raw)==expected);m=json.loads(raw)
    need(set(m)=={'version','release','execution_authorized','origin_manifest','connectivity_manifest','limits','remote_command','artifacts','payload'})
    need(m['version']==1 and m['release']==RELEASE and m['execution_authorized']is False and m['origin_manifest']==ORIGIN_SHA and m['connectivity_manifest']==CONNECT_SHA and m['limits']==LIMITS and m['remote_command']==REMOTE)
    need(set(m['artifacts'])==ARTIFACTS);blobs={}
    for rel,item in m['artifacts'].items():
        raw=read(ROOT/rel);need(item=={'sha256':sha(raw),'bytes':len(raw)});blobs[rel]=raw
    transport,wrapper,supervisor,bounded=references(blobs);payload=assemble(blobs,bounded)
    need(payload==read(HERE/'inspect.payload.py')and m['payload']=={'sha256':sha(payload),'bytes':len(payload)})
    inspector=namespace(blobs[str((HERE/'inspect.py').relative_to(ROOT))],'traversal_schema')
    return transport,wrapper,supervisor,payload,inspector

def argv(transport,wrapper):
    profile=wrapper['profile']();original=wrapper['ssh_argv'](profile)
    return original[:-2]+[part for option in transport.EXTRA_OPTIONS for part in ['-o',option]]+[profile['target'],REMOTE]

def validate_report(report,inspector):
    base={'status','changed','reason','stage','errno'}
    normal={'status','changed','reason','producer_probe','failed_path_id','errno','worker_primary_identity','worker_groups_match_cleared_probe','worker_api_reader_group_present','directories','stage'}
    need(type(report)is dict and set(report)in[base,normal]and report.get('status')in{'PASS','BLOCKED'}and report.get('changed')is False)
    need(report['reason']in inspector.REASONS and report['stage']in inspector.STAGES)
    need(report['errno']is None or type(report['errno'])is int and report['errno']in {1,2,13,20,40,95})
    if set(report)==normal:
        need(report['producer_probe']in inspector.CHILD_CODES and report['failed_path_id']in {*inspector.LABELS,'NONE'}and report['worker_primary_identity']=='MATCH')
        need(type(report['worker_groups_match_cleared_probe'])is bool and type(report['worker_api_reader_group_present'])is bool)
        dirs=report['directories'];need(type(dirs)is list and len(dirs)==3)
        for label,row in zip(inspector.LABELS,dirs):
            need(set(row)=={'path_id','owner','group','mode','cleared_producer_mode_allows_search'}and row['path_id']==label and row['owner']in{'ROOT','OTHER'}and row['group']in{'ROOT_GROUP','PRODUCER_GROUP','API_READER_GROUP','OTHER'})
            need(type(row['mode'])is str and len(row['mode'])==4 and all(x in'01234567'for x in row['mode'])and type(row['cleared_producer_mode_allows_search'])is bool)
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest-sha256',required=True);p.add_argument('--local-check',action='store_true');args=p.parse_args();attempts=0
    try:
        transport,wrapper,supervisor,payload,inspector=verify(args.manifest_sha256)
        command=argv(transport,wrapper)
        if args.local_check:print('{"local_integrity":"PASS","ssh_attempts":0}');return 0
        os.umask(0o077);folder=Path(tempfile.mkdtemp(prefix='realized-parent-traversal-',dir=wrapper['PRIVATE']/'preflight'))
        attempts=1;result=supervisor(command,input=payload,timeout=40,limit=8192,grace=5)
        report=None;failure=result['failure']
        if not failure and result['returncode']==255:failure=wrapper['failure_category'](255,result['stderr'])
        if not failure:
            try:
                report=validate_report(json.loads(result['stdout']),inspector)
                need((result['returncode']==0)==(report['status']=='PASS'))
            except Exception:failure='DIAGNOSTIC_OUTPUT_UNVERIFIED';report=None
        summary={'exit_status':result['returncode'],'failure':failure,'report':report,'ssh_attempts':1}
        with os.fdopen(os.open(folder/'assessment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return result['returncode']or(1 if failure else 0)
    except Exception:
        print(json.dumps({'status':'BLOCKED','reason':'LOCAL_IMMUTABLE_OR_PINNED_IDENTITY'if attempts==0 else'DIAGNOSTIC_TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
