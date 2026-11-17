"""Bounded read-only deployment and genuine-run report acceptance; no publication."""
import http.client as http_client
import socket
import ssl
import types


def report_metadata(record=None,empty=False,partial=False):
    if not os.path.lexists(REPORT):
        need(partial and(record is None or 'report'not in record['roots']),'REPORT_ROOT_MISSING');return None
    for label,path in [('report',REPORT),('report_releases',REPORT/'releases')]:
        if not os.path.lexists(path):need(partial and record is not None and label not in record['roots'],'REPORT_DIRECTORY_MISSING');continue
        s=path.lstat();need(stat.S_ISDIR(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(1000,992,0o2750),'REPORT_DIRECTORY_METADATA')
        if record is not None:need(record['roots'].get(label)==[s.st_dev,s.st_ino],'REPORT_ROOT_IDENTITY')
    names={p.name for p in H.entries(REPORT,4)};need(names<={'contract','releases','current','.publication.lock'},'REPORT_ENTRY_SCOPE')
    if 'contract'not in names:need(partial,'REPORT_MARKER_MISSING')
    else:
        s=(REPORT/'contract').lstat();need(stat.S_ISREG(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)==(1000,992,0o640,1)and B['read'](REPORT/'contract',100)==MARKER,'REPORT_MARKER')
    digests=[]
    if (REPORT/'releases').exists():
        for folder in H.entries(REPORT/'releases',2048):
            need(re.fullmatch('[0-9a-f]{64}',folder.name)is not None,'REPORT_RELEASE_ID')
            s=folder.lstat();need(stat.S_ISDIR(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(1000,992,0o2750),'REPORT_RELEASE_DIRECTORY')
            need({p.name for p in H.entries(folder,1)}=={'report.json'},'REPORT_RELEASE_INVENTORY')
            s=(folder/'report.json').lstat();need(stat.S_ISREG(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)==(1000,992,0o640,1)and s.st_size<=16*1024**2,'REPORT_FILE_METADATA');digests.append(folder.name)
    if empty:need(not digests and names<={'contract','releases'},'REPORT_NOT_EMPTY')
    current=None
    if 'current'in names:
        path=REPORT/'current';s=path.lstat();need(stat.S_ISREG(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)==(1000,992,0o640,1),'REPORT_POINTER_METADATA')
        raw=B['read'](path,65);need(re.fullmatch(b'[0-9a-f]{64}\n',raw)is not None,'REPORT_POINTER');current=raw.decode().strip();need(current in digests,'REPORT_POINTER_TARGET')
    if '.publication.lock'in names:
        s=(REPORT/'.publication.lock').lstat();need(stat.S_ISREG(s.st_mode)and(s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)==(1000,992,0o600,1),'REPORT_LOCK_METADATA')
    return current

def access_probe():
    # Effective read-only check from candidate mount namespace; no trial writes.
    pid=report_environment(True)
    script="import os;from pathlib import Path; r=Path("+repr(C['root'])+");assert os.getuid()==os.geteuid()==992;assert all(os.access(p,os.R_OK|os.X_OK)and not os.access(p,os.W_OK)for p in [r,r/'releases']);assert os.access(r/'contract',os.R_OK)and not os.access(r/'contract',os.W_OK);print('READ_ONLY_PASS')"
    r=B['bounded_run'](['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--','/usr/bin/setpriv','--no-new-privs','--reuid=992','--regid=992','--clear-groups','/usr/bin/python3','-I','-S','-B','-c',script],timeout=10,limit=1024,grace=5)
    need(r['returncode']==0 and not r['failure']and r['stdout']==b'READ_ONLY_PASS\n','REPORT_API_READONLY_ACCESS')
    script="import os;from pathlib import Path;r=Path("+repr(C['root'])+");assert os.getuid()==os.geteuid()==1000;assert all(os.access(p,os.R_OK|os.W_OK|os.X_OK)for p in [r,r/'releases']);assert os.access(r/'contract',os.R_OK);print('PRODUCER_ACCESS_PASS')"
    r=B['bounded_run'](['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups','/usr/bin/python3','-I','-S','-B','-c',script],timeout=10,limit=1024,grace=5)
    need(r['returncode']==0 and not r['failure']and r['stdout']==b'PRODUCER_ACCESS_PASS\n','REPORT_PRODUCER_ACCESS')

def protected(r,allow_advance=False):
    P.forecast_configuration()
    before=r['before'];current=snapshot();old=before['snapshot']
    need(not C.get('worker_optional_packages')or('worker_packages'in old and 'worker_packages'in current),'PRESERVATION_WORKER_PACKAGES')
    need(current.get('worker_packages',{})==old.get('worker_packages',{}),'PRESERVATION_WORKER_PACKAGES')
    for key in ['helper','nginx','pool']:need(current[key]==old[key],'PRESERVATION_'+key.upper())
    need(P.runtime_closure(Path(before['venv']))==before['runtime'],'PRESERVATION_RUNTIME')
    if allow_advance:
        if current['production']!=old['production']:
            outputs=OLD.PRES.historical_output_hashes(old['forecast'])
            need(OLD.PRES.replay_production(old['production'],outputs)=='MATCH_EXCEPT_PIPELINE_OUTPUTS','PRESERVATION_PRODUCTION')
        if current['store']!=old['store']:
            need(OLD.PRES.store_history(old['store'],r['activated_at']or r['created_at'])=='BASELINE_RECONSTRUCTED_SUBSET','PRESERVATION_OPERATIONAL_RETENTION')
        need({k:v for k,v in current['forecast'].items()if k not in {'pointer','bundle'}}=={k:v for k,v in old['forecast'].items()if k not in {'pointer','bundle'}},'PRESERVATION_FORECAST_METADATA')
        OLD.forecast_checks() # actual active bundle integrity/eligibility, stable pointer
    else:
        for key in ['production','forecast','store']:need(current[key]==old[key],'PRESERVATION_'+key.upper())
    return current

def deployment_checks(r,enabled):
    before=r['before'];new_trees(r,True);worker_state(True);report_metadata(r,empty=True);access_probe()
    need(P.BACKEND_LINK.resolve(strict=True)==API and P.STATIC_LINK.resolve(strict=True)==STATIC,'ACTIVE_POINTERS')
    need(P.snap(ENV,0,0,0o600)[0]['sha256']==before['env_after'],'REPORT_ENV_HASH')
    d=P.deployment();need(d.get('job_variables',{})==before['new_variables'if enabled else'old_variables']and H.OLD_PLAN.stable_projection(d)==before['projection'],'REPORT_ACTIVATION_STATE')
    G['runtime'](API);P.candidate_environment(True)
    need(B['request'](8010,'/health')[0]==B['request'](8010,'/ready')[0]==200,'CANDIDATE_HEALTH')
    code,body=B['request'](443,'/',tls=True);need(code==200 and sha(body)==C['files']['static/index.html']['sha256'],'STATIC_ROUTING')
    OLD.public_operations();OLD.forecast_checks()
    code,body=report_http();need(code==404 and body=={'detail':{'code':'REALIZED_REPORT_MISSING'}},'EMPTY_REPORT_NO_HISTORICAL_FALLBACK')
    protected(r)

def inspected_report_script():
    # Exact installed consumer, no producer call. Source bytes have passed static
    # inventory checks. Integrity and metric calculations stay unprivileged.
    script=probe_script('api').decode().replace("print('REPORT_IMPORT_PASS')\n",'')
    script+="from shared.realized_report_store import read_active\nfrom api.realized_reporting import evaluation\nimport datetime as dt\nnow=dt.datetime.now(dt.timezone.utc)\ndoc,digest=read_active("+repr(C['root'])+",now)\nassert doc['state']=='READY'\nresponse=evaluation("+repr(C['root'])+",now).model_dump(mode='json')\nprint(json.dumps({'digest':digest,'document_generated_at':doc['generated_at'],'response':response},sort_keys=True))\n"
    return script.encode()

def reconstructed_report_script(generated):
    # Re-evaluate the recorded report instant, not live forecast availability.
    # The timestamp itself and freshness have already been verified at actual UTC.
    # Pure producer build only: write/publish/inference/network audit stays closed.
    script=probe_script('worker').decode().replace("print('REPORT_IMPORT_PASS')\n",'')
    script+="from shared.realized_report import encode,stamp\nfrom models.realized_reporting import build\nimport hashlib\ndoc=build("+repr(str(WORKER/'data/reports/next24h_forecast_history.csv'))+","+repr(str(WORKER/'data/raw/entsoe/prices.csv'))+","+repr(str(WORKER/'data/reports/next24h_inference'))+",now=stamp("+repr(generated)+"))\nprint(json.dumps({'sha256':hashlib.sha256(encode(doc)).hexdigest()}))\n"
    return script.encode()


def accept_report():
    r=load_record();need(r['phase']=='APPLIED'and r['activated_at'],'TRANSACTION_NOT_APPLIED');P.idle(0);verify_backups(r)
    new_trees(r,True);worker_state(True);access_probe();protected(r,True)
    need(P.snap(ENV,0,0,0o600)[0]['sha256']==r['before']['env_after'],'REPORT_ENV_DRIFT')
    d=P.deployment();need(d.get('job_variables',{})==r['before']['new_variables']and H.OLD_PLAN.stable_projection(d)==r['before']['projection'],'REPORT_POLICY_DRIFT')
    flows=B['api']('/flow_runs/filter',{'deployments':{'id':{'any_':[H.OLD_PLAN.DEPLOYMENT]}},'flow_runs':{'start_time':{'after_':r['activated_at'],'is_null_':False}},'sort':'START_TIME_DESC','limit':20})
    need(type(flows)is list and len(flows)<=20 and len({f['id']for f in flows})==len(flows),'NATURAL_QUERY_BOUND')
    natural=OLD.started_natural(flows);need(natural or len(flows)<20,'NATURAL_SELECTION_TRUNCATED')
    common={'phase':'READ_ONLY','changed':False,'browser':'PENDING_OWNER','analyst_authorization':'PENDING_CLOSED'}
    if not natural:return {'status':'WAITING',**common,'reason':'NO_POST_ACTIVATION_NATURAL_RUN'}
    flow=max(natural,key=lambda f:H.OP.timestamp(f['start_time']));need(H.OP.timestamp(flow['start_time'])>H.OP.timestamp(r['activated_at']),'RUN_BEFORE_ACTIVATION')
    if flow.get('state_type')not in {'COMPLETED','FAILED','CRASHED','CANCELLED'}:return {'status':'WAITING',**common,'reason':'NATURAL_RUN_NOT_TERMINAL','run_id':flow['id']}
    # Reconstruct the accepted operational association to bind the terminal state
    # to the actual pipeline UUID; no terminal-hook or publication invocation.
    producer=types.ModuleType('shared.realized_acceptance_producer');producer.__package__='shared'
    exec(compile(H.artifact('helper/shared/operational_evidence_producer.py'),'<verified-capture-association>','exec'),producer.__dict__)
    capture=sys.modules['shared.operational_capture'];capture.from_snapshot=producer.from_snapshot
    opraw,_=capture.capture_terminal(flow['id'],flow['state']['id']);evidence=H.OP.decode(opraw)
    commit=P.snap(P.STORE/'current',0,992,0o640)[1].decode().strip();need(re.fullmatch('[0-9a-f]{64}',commit)is not None,'OPERATIONAL_POINTER')
    committed=H.OP.validate(P.snap(P.STORE/'releases'/commit/'evidence.json',0,992,0o640)[1],commit,dt.datetime.now(dt.timezone.utc))
    need(all(committed[k]==evidence[k]for k in ['execution','inference','delivery','provenance','version']),'OPERATIONAL_NATURAL_ASSOCIATION')
    # Exactly one read-only task query; Prefect task read is POST filter, never GET.
    tasks=capture.query(flow['id'],tasks=True)
    need(type(tasks)is list and len(tasks)<100,'MONITORING_TASK_BOUND')
    found=[t for t in tasks if t.get('flow_run_id')==flow['id']and str(t.get('name','')).startswith('Monitor next24h realized forecast errors')]
    need(len(found)==1,'MONITORING_TASK_ASSOCIATION');task=found[0]
    if task.get('state',{}).get('type')!='COMPLETED'and task.get('state_type')!='COMPLETED':return {'status':'PARTIAL',**common,'reason':'MONITORING_TASK_NOT_COMPLETED','run_id':flow['id'],'pipeline_run_id':evidence['execution']['pipeline_run_id']}
    start,end=H.OP.timestamp(task['start_time']),H.OP.timestamp(task['end_time']);need(start<=end<=H.OP.timestamp(flow['end_time']),'MONITORING_TASK_TIMES')
    current=report_metadata(r);code,body=report_http()
    if current is None:return {'status':'PARTIAL',**common,'reason':'NO_REALIZED_PUBLICATION','run_id':flow['id'],'report_http':code}
    if code!=200:
        reason=body.get('detail',{}).get('code')
        need(code in {404,503}and reason in {'REALIZED_REPORT_MISSING','REALIZED_INPUTS_MISSING','REALIZED_REPORT_FAILED','REALIZED_REPORT_INVALID'},'REALIZED_HTTP_STATUS')
        return {'status':'PARTIAL',**common,'reason':reason,'run_id':flow['id'],'pipeline_run_id':evidence['execution']['pipeline_run_id'],'report_http':code,'report_sha256':current}
    pid=report_environment(True);result=B['bounded_run'](['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--','/usr/bin/setpriv','--no-new-privs','--reuid=992','--regid=992','--clear-groups',str(Path(r['before']['venv'])/'bin/python'),'-I','-B','-'],input=inspected_report_script(),timeout=20,limit=65536,grace=5)
    need(result['returncode']==0 and not result['failure'],'REALIZED_READBACK_VALIDATION')
    validated=json.loads(result['stdout']);need(validated['digest']==current,'REALIZED_POINTER_ASSOCIATION')
    need(start<=H.OP.timestamp(validated['document_generated_at'])<=end,'REALIZED_MONITORING_TIME_ASSOCIATION')
    expected=validated['response'];need(code==200,'REALIZED_HTTP_STATUS')
    for key,rel in [('history_sha256','data/reports/next24h_forecast_history.csv'),('prices_sha256','data/raw/entsoe/prices.csv')]:
        path=WORKER/rel;P.safe(path,(0,1000));need(sha(P.read(path,64*1024**2))==expected['source_sha256'][key],'REALIZED_SOURCE_CHANGED')
    need(set(body)==set(expected)and all(body[k]==expected[k]for k in expected if k not in {'assessed_at','windows'}),'REALIZED_API_VALUES')
    need(abs((H.OP.timestamp(body['assessed_at'])-H.OP.timestamp(expected['assessed_at'])).total_seconds())<30,'REALIZED_ASSESSMENT_TIME')
    # Threshold windows may cross a boundary between requests: equality is still
    # required (fail closed rather than substituting a different assessment).
    need(body['releases']==expected['releases'],'REALIZED_METRICS')
    need(body['report_status']=='VALID','REALIZED_REPORT_STALE')
    reconstruction=B['bounded_run'](['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups',str(WORKER/'.venv-prod/bin/python'),'-I','-B','-'],input=reconstructed_report_script(validated['document_generated_at']),timeout=35,limit=1024,grace=5)
    need(reconstruction['returncode']==0 and not reconstruction['failure'],'REALIZED_RECEIPT_RECONSTRUCTION')
    need(json.loads(reconstruction['stdout'])=={'sha256':current},'REALIZED_RECEIPT_METRIC_ASSOCIATION')
    need(report_metadata(r)==current and P.snap(P.STORE/'current',0,992,0o640)[1].decode().strip()==commit,'PUBLICATION_CHANGED_DURING_ACCEPTANCE')
    P.idle(0)
    return {'status':'PARTIAL',**common,'reason':'OWNER_REACT_ACCEPTANCE_PENDING','run_id':flow['id'],'pipeline_run_id':evidence['execution']['pipeline_run_id'],'report_sha256':current,'report_http':code,'report_status':body['report_status'],'data_status':body['data_status'],'pair_count':body['coverage']['realized_pairs'],'generated_at':body['generated_at'],'fresh_until':body['fresh_until'],'backend_status':'PASS'}
