"""Separate publication-only runner. No connection without fresh authorization."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PREFIX='deploy/staging/forecast-consistency-release/'
CORE=PREFIX+'preflight_readonly.py'
WRAPPER=PREFIX+'run_preflight.py'
CONTRACT='src/shared/forecast_publication.py'
DIAGNOSTIC=PREFIX+'publication_diagnostic.py'
ARTIFACTS={CORE,WRAPPER,CONTRACT,DIAGNOSTIC,PREFIX+'run_publication_diagnostic.py',PREFIX+'PUBLICATION-DIAGNOSTIC.md','tests/test_publication_diagnostic.py',PREFIX+'PREFLIGHT-REVIEW.json',PREFIX+'PREFLIGHT-REVIEW.md','tests/test_forecast_consistency_preflight.py','deploy/remediation/a3-bounded-local.py'}


def read(path,limit=2_000_000):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('file_type')
        raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('file_bound')
    return raw


def namespace(raw,name,file=None):
    value={'__name__':name}
    if file is not None:value['__file__']=str(file)
    exec(compile(raw,'<verified-'+name+'>','exec'),value)
    return value


def assemble(blobs):
    return ("BASE={'__name__':'verified_base'}\nexec(compile("+repr(blobs[CORE])+",'<verified-base>','exec'),BASE)\n"+
            "CONTRACT={'__name__':'verified_contract'}\nexec(compile("+repr(blobs[CONTRACT])+",'<verified-contract>','exec'),CONTRACT)\n"+
            "exec(compile("+repr(blobs[DIAGNOSTIC])+",'<verified-diagnostic>','exec'),{'__name__':'__main__','BASE':BASE,'CONTRACT':CONTRACT})\n").encode()


def verify(expected):
    raw=read(HERE/'PUBLICATION-DIAGNOSTIC.json')
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('manifest_hash')
    manifest=json.loads(raw)
    if manifest['schema_version']!=1 or set(manifest['artifacts'])!=ARTIFACTS:raise ValueError('manifest_scope')
    blobs={}
    for name,meta in manifest['artifacts'].items():
        data=read(ROOT/name)
        if len(data)!=meta['bytes'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:raise ValueError('artifact_hash')
        blobs[name]=data
    payload=assemble(blobs)
    if hashlib.sha256(payload).hexdigest()!=manifest['remote_payload_sha256']:raise ValueError('assembled_payload_hash')
    wrapper=namespace(blobs[WRAPPER],'wrapper',ROOT/WRAPPER)
    wrapper['profile']() # pin profile/target/known-hosts; metadata-only private key check
    base=namespace(blobs[CORE],'base')
    validator=namespace(blobs[DIAGNOSTIC],'diagnostic')
    return payload,wrapper,base,validator


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256',required=True);parser.add_argument('--local-check',action='store_true')
    args=parser.parse_args();capture=None;summary={'exit_status':None,'failure_category':'LOCAL_VERIFICATION_FAILURE','report':None}
    try:
        payload,wrapper,base,validator=verify(args.manifest_sha256)
        if args.local_check:print('{"local_integrity":"PASS","remote_attempts":0}');return 0
        profile=wrapper['profile']();command=wrapper['ssh_argv'](profile)
        # Same strict SSH options and fixed root Python command. New payload is
        # independently hash-bound and calls ONLY publication functions.
        capture=Path(tempfile.mkdtemp(prefix='publication-only-',dir=wrapper['PRIVATE']/'preflight'));capture.chmod(0o700)
        result=base['bounded_run'](command,input=payload,timeout=180,limit=131072,grace=5)
        summary={'exit_status':result['returncode'],'failure_category':result['failure'],'report':None}
        try:
            for name in ('stdout','stderr'):
                with os.fdopen(os.open(capture/(name+'.private'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as stream:stream.write(result[name])
        except Exception:summary['failure_category']='CAPTURE_FAILURE'
        if summary['failure_category'] is None:
            try:
                report=validator['validate_report'](json.loads(result['stdout']))
                if result['returncode']!=(0 if report['publication_state']=='VALID' else 1):raise ValueError('status')
                summary['report']=report
            except Exception:summary['failure_category']=wrapper['failure_category'](result['returncode'],result['stderr']) if result['returncode'] else 'UNEXPECTED_OUTPUT'
    except Exception:
        if capture is not None:summary['failure_category']='INSPECTION_OR_CAPTURE_FAILURE'
    if capture is not None:
        try:
            with os.fdopen(os.open(capture/'sanitized.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w') as stream:json.dump(summary,stream,indent=2)
        except Exception:summary['failure_category']='REPORT_WRITE_FAILURE'
    try:print(json.dumps(summary,sort_keys=True))
    except OSError:return 1
    return 0 if summary['exit_status']==0 and summary['failure_category'] is None and summary['report'] is not None else 1


if __name__=='__main__':raise SystemExit(main())
