"""One explicitly authorized read-only attempt; --local-check never connects."""
import argparse
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import types

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
V4='4b129e8b7d8790d6fbb883e5043ce9cf7f34e75c3b5c5468d13a06bf87f10f95'
TRANSPORT='6fb6cd73259c8c6961cc954cc636603abb90a2fcae7983ade15578d7d166fcbe'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path,limit=4*1024**2):
    path=Path(path);assert not any(p.is_symlink()for p in(path,*path.parents))
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb')as f:
        st=os.fstat(f.fileno());assert stat.S_ISREG(st.st_mode)and st.st_size<=limit
        raw=f.read(limit+1);assert len(raw)==st.st_size;return raw

def module(path,name):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(read(path),'<bound-'+name+'>','exec'),m.__dict__);return m

def components():
    r=module(ROOT/'deploy/staging/realized-performance-release-v4/run.py','reporting_v4')
    payload,_,_=r.verify(V4,'accept');marker=b'try:\n report=R.accept_report()';assert payload.count(marker)==1
    prefix=payload.split(marker)[0]
    i=module(HERE/'inspect.py','inspection');c=module(HERE/'context.py','context')
    # Only approved project-relative frame/function identifiers may leave remote.
    tree={};ns={};exec(compile(prefix,'<verified-reporting-read-only>','exec'),ns);frozen=ns['R']
    for key in frozen.C['files']:
        if key.startswith('worker/src/')and key.endswith('.py'):
            rel=key[len('worker/'):];raw=frozen.raw_file(key)
            tree[rel]=sorted({n.name for n in ast.walk(ast.parse(raw))if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))})
    i.APPROVED_GATES=set(frozen.C['failure_gates'])
    return prefix,i,c,tree

def assemble():
    prefix,i,c,symbols=components()
    source_id=sha(prefix+read(HERE/'inspect.py')+read(HERE/'context.py')+json.dumps(symbols,sort_keys=True).encode())
    tail="\nINSPECTOR=types.ModuleType('readonly_inspector')\nexec(compile("+repr(read(HERE/'inspect.py'))+",'<readonly-inspector>','exec'),INSPECTOR.__dict__)\n"
    tail+="CONTEXT=types.ModuleType('readonly_context')\nexec(compile("+repr(read(HERE/'context.py'))+",'<readonly-context>','exec'),CONTEXT.__dict__)\n"
    tail+="INSPECTOR.APPROVED_GATES="+'set('+repr(sorted(i.APPROVED_GATES))+')'+"\n"
    tail+="result=INSPECTOR.Inspection(CONTEXT.Context(R,INSPECTOR),INSPECTOR.HTTP(),"+repr(symbols)+").execute()\n"
    tail+="result['inspection_source_sha256']="+repr(source_id)+"\nprint(json.dumps(result,sort_keys=True,allow_nan=False))\nraise SystemExit(0 if result['status']=='PASS' else 1)\n"
    return prefix+tail.encode(),source_id,i,symbols

def command(t,parent,values):
    transport,wrapper,_,_,_,_,_=values;argv=t.command(parent,transport,wrapper)
    assert argv[-1]=='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 20s /usr/bin/python3 -I -S -B -'
    argv[-1]='sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 90s /usr/bin/python3 -I -S -B -'
    assert argv.count('StdinNull=no')==1 and '-n'not in argv and '-f'not in argv
    return argv

def verify(expected):
    raw=read(HERE/'BINDINGS.json');assert sha(raw)==expected;m=json.loads(raw)
    assert set(m)=={'version','purpose','execution_authorized','reporting_v4_manifest','transport_manifest','artifacts','payload_sha256','payload_bytes','source_sha256'}
    assert m['version']==1 and m['purpose']=='FIXED_RUN_READ_ONLY_ACCEPTANCE'and m['execution_authorized']is False
    assert m['reporting_v4_manifest']==V4 and m['transport_manifest']==TRANSPORT
    required={str((HERE/name).relative_to(ROOT))for name in ['run.py','inspect.py','context.py','REVIEW.md']}
    required|={'tests/test_realized_performance_acceptance_inspection.py','deploy/staging/operational-evidence-release-v5/PREFECT-REFERENCE.json'}
    assert set(m['artifacts'])==required
    for rel,digest in m['artifacts'].items():assert sha(read(ROOT/rel))==digest
    payload,source,i,symbols=assemble();assert sha(payload)==m['payload_sha256']and len(payload)==m['payload_bytes']and source==m['source_sha256']
    t=module(ROOT/'deploy/staging/realized-parent-traversal-diagnostic-v3/run.py','stdin_transport');parent,values=t.verify(TRANSPORT)
    argv=command(t,parent,values)
    return payload,source,i,symbols,argv,values

def safe_output(raw,source,i,symbols,started_at=None):
    i.need(type(raw)is bytes and 0<len(raw)<=65536)
    value=i.strict_json(raw);i.need(type(value)is dict and value.get('inspection_source_sha256')==source,'IDENTITY')
    i.need(set(value)=={'status','changed','inspected_at','target_flow_run_id','target_pipeline_run_id','sections','http_probes','browser_acceptance','analyst_authorization','inspection_source_sha256'})
    i.need(value['status']in{'PASS','BLOCKED'}and value['changed']is False and value['target_flow_run_id']==i.FLOW and value['target_pipeline_run_id']==i.PIPELINE,'IDENTITY')
    if started_at is not None:i.need(started_at-dt.timedelta(seconds=5)<=i.stamp(value.get('inspected_at'))<=dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=5),'TIMESTAMP')
    i.need(value['browser_acceptance']=='PENDING_OWNER'and value['analyst_authorization']=='PENDING_CLOSED')
    i.need(type(value['sections'])is dict and set(value['sections'])<=i.STAGES)
    for key,section in value['sections'].items():
        i.need(type(section)is dict and section.get('status')in{'VERIFIED','UNVERIFIED','NOT_CHECKED'})
        if section['status']=='VERIFIED':i.need(set(section)=={'status','evidence'})
        else:i.need({'status','reason'}<=set(section)<={'status','reason','operation','gate','exception_class'}and section['reason']in i.ERRORS)
    allowed_keys=set('report_delivery_enabled operational_public_projection admin_fields_disclosed forecast_api_consistency freshness role related_tasks operation gate exception_class inspected_at status changed target_flow_run_id target_pipeline_run_id sections http_probes browser_acceptance analyst_authorization inspection_source_sha256 evidence reason release transaction installed_inventory read_only run_id state scheduled_at started_at completed_at received_rows task_id state_name state_timestamp diagnosis exception_classes errno_codes recognized_reasons approved_frames module function line denied_component upstream_not_completed entries timestamp limit_reached window_basis window_start window_end sha256 target_association observed_at execution_outcome inference_outcome delivery_outcome summary present generated_at observed_through source_sha256 history_sha256 prices_sha256 receipts_sha256 coverage history_rows verified_rows unverified_rows eligible_rows realized_pairs endpoint method http_status response_bytes error validation location category cache_no_store error_code prediction_count operational_status forecast_status report_status data_status publication_matches_api target_time_association data_state metric_evaluator receipt_source_and_metrics completed_hours_only late_issue_excluded complete_observations_required protected_state forecast_configuration operational_retention publication_pointers'.split())|i.STAGES
    constants=i.ERRORS|i.STATES|i.CLASSES|set(i.REASONS.values())|i.CODES|i.STAGES|{
        'PASS','BLOCKED','VERIFIED','UNVERIFIED','NOT_CHECKED','PENDING_OWNER','PENDING_CLOSED','INFERENCE','AUTOMATIC_PUBLICATION','GET','POST','PREFECT_AND_PERSISTED_PIPELINE','NATURAL_SCHEDULE','READY','MISSING_INPUTS','FAILED','NONE','MISSING_HISTORY','MISSING_OBSERVATIONS','MISSING_RECEIPTS','INVALID_INPUT','VALID','STALE','MISSING','INVALID','EXPIRED','MISSING_PUBLICATION','WITHHELD','AVAILABLE','INSUFFICIENT_DATA','GENERATED','UNCHANGED','UNKNOWN','UNAVAILABLE','NOT_RUN','DISABLED','REJECTED_INFERENCE','PUBLISHED','SKIPPED_WITHHELD','SKIPPED_DUPLICATE','SKIPPED_EXPIRED','REJECTED_OLDER_ISSUE','EXACT_MATCH','MATCH','CURRENT_RECORD_ADVANCED_OR_DIFFERENT','EXACT_INSTALLED_CONSUMER','RECONSTRUCTED_MATCH','PRESERVED','STABLE','REPORT_PARENT','REPORT_ROOT','PUBLICATION_LOCK','REPORT_DOCUMENT','TASK_TIMES','FLOW_TIMES_NOT_TASK_TIMES','UNRECOGNIZED','Completed','Failed','Crashed','Cancelled','NotReady','Pending','Running','Scheduled','AwaitingRetry','Retrying','Cached','RolledBack','phase-realized-next24h-performance-20261108-v4','8415154bdaf94746a93adf6e380667a8',i.FLOW,i.PIPELINE,
        'body','path','sort','limit','offset','flow_runs','id','any_','logs','flow_run_id','task_run_id','after_','before_','missing','enum','extra_forbidden','uuid_parsing','json_invalid','literal_error','int_parsing','greater_than_equal','less_than_equal','value_error'}
    constants|=i.APPROVED_GATES|i.OPERATIONS
    constants|=set(symbols)|{fn for funcs in symbols.values()for fn in funcs}
    def scan(x,depth=0):
        i.need(depth<15)
        if type(x)is dict:
            i.need(set(x)<=allowed_keys)
            for v in x.values():scan(v,depth+1)
        elif type(x)is list:
            i.need(len(x)<=100)
            for v in x:scan(v,depth+1)
        elif type(x)is str:
            if x in constants:return
            if re.fullmatch('[0-9a-f]{64}',x):return
            try:i.uuid_text(x);return
            except i.Rejected:pass
            i.need(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)',x)is not None);i.stamp(x)
        else:i.need(x is None or type(x)is bool or type(x)is int and 0<=x<=16777216)
    scan(value)
    probes=value['http_probes'];i.need(type(probes)is list and len(probes)<=7)
    seen=set()
    for probe in probes:
        i.need(set(probe)=={'endpoint','method','http_status','response_bytes','error','validation'})
        operation=probe['endpoint'];i.need(operation in{'FLOW','TASKS','LOGS','FORECAST_API','OPERATIONS_API','OPERATIONS_SUMMARY','REALIZED_API'}and operation not in seen);seen.add(operation)
        i.need(probe['method']==('POST'if operation in{'TASKS','LOGS'}else'GET'))
        i.need(probe['http_status']is None or type(probe['http_status'])is int and 100<=probe['http_status']<=599)
        i.need(probe['error']is None or probe['error']in i.ERRORS)
    if value['status']=='PASS':
        required=i.STAGES-{'RECEIPT_RECONSTRUCTION'}
        i.need(set(value['sections'])==i.STAGES and all(value['sections'][k]['status']=='VERIFIED'for k in required))
        publication=value['sections']['REPORT_PUBLICATION']['evidence'];i.need(publication.get('present')is True and publication.get('state')in{'READY','MISSING_INPUTS'})
        if publication['state']=='READY':i.need(value['sections']['RECEIPT_RECONSTRUCTION']['status']=='VERIFIED')
        i.need(value['sections']['MONITORING']['evidence'].get('state')=='COMPLETED')
        i.need(value['sections']['LOGS']['evidence'].get('limit_reached')is False)
        i.need(value['sections']['OPERATIONAL_PUBLICATION']['evidence'].get('target_association')=='MATCH')
    return value

def main():
    p=argparse.ArgumentParser();p.add_argument('--bindings-sha256',required=True);p.add_argument('--local-check',action='store_true');a=p.parse_args();attempts=0
    try:
        payload,source,i,symbols,argv,values=verify(a.bindings_sha256)
        if a.local_check:print('{"status":"LOCAL_PASS","ssh_attempts":0}');return 0
        # Explicit remote authorization is required before this path is invoked.
        _,wrapper,supervisor,*_=values;os.umask(0o077)
        folder=Path(tempfile.mkdtemp(prefix='reporting-comprehensive-acceptance-',dir=wrapper['PRIVATE']/'preflight'))
        started_at=dt.datetime.now(dt.timezone.utc);attempts=1;result=supervisor(argv,input=payload,timeout=150,limit=65536,grace=5)
        accepted=None;failure=result['failure']
        if failure is None and result['returncode']==255:failure=wrapper['failure_category'](255,result['stderr'])
        if not failure:
            try:
                accepted=safe_output(result['stdout'],source,i,symbols,started_at);assert result['returncode']==(0 if accepted['status']=='PASS'else 1)
            except i.Rejected as error:failure='OUTPUT_UNVERIFIED_'+error.code;accepted=None
            except Exception:failure='OUTPUT_UNVERIFIED_SCHEMA';accepted=None
        summary={'exit_status':result['returncode'],'failure':failure,'report':accepted,'ssh_attempts':1}
        with os.fdopen(os.open(folder/'assessment.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'w')as f:json.dump(summary,f,sort_keys=True)
        print(json.dumps(summary,sort_keys=True));return 0 if accepted and accepted['status']=='PASS'else 1
    except Exception:
        print(json.dumps({'status':'BLOCKED','reason':'LOCAL_INTEGRITY_OR_PINNED_IDENTITY'if attempts==0 else'TRANSPORT_OR_CAPTURE_UNVERIFIED','ssh_attempts':attempts}));return 1
if __name__=='__main__':raise SystemExit(main())
