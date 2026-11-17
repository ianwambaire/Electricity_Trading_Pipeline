"""Root-owned fixed-path receipt delivery entrypoint; separately deployed only.
No production application imports, inference, source mutation or arbitrary paths.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import sys
import types
import urllib.request
import uuid

RECEIPTS=Path('/home/ec2-user/Electricity_Trading_Pipeline/data/reports/next24h_inference')
HISTORY=RECEIPTS.parent/'next24h_forecast_history.csv'
PUBLICATION=Path('/srv/powerflow/forecast-publications')
DEPLOYMENT='47e5ef51-26d0-44b6-b119-2c40d0e77397'
NAMES={'forecast.csv','provenance.json','model.json','evidence.json','integrity.json'}

def require(value):
    if not value:raise ValueError('publication_evidence_rejected')

def uid(value):
    require(isinstance(value,str) and str(uuid.UUID(value))==value);return value

def stamp(value):
    v=dt.datetime.fromisoformat(value.replace('Z','+00:00'));require(v.tzinfo is not None);return v.astimezone(dt.timezone.utc)

def capture(directory,name,owner,limit=100000):
    # Anchor every ancestor and file with no-follow descriptors; never reopen verified data.
    path=Path(directory);require(path.is_absolute() and Path(name).name==name and name not in {'.','..'})
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=new
        info=os.fstat(fd)
        if name in NAMES:require(info.st_uid==owner and stat.S_IMODE(info.st_mode)==0o700)
        file=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        with os.fdopen(file,'rb') as stream:
            before=os.fstat(stream.fileno());require(stat.S_ISREG(before.st_mode) and before.st_uid==owner and not before.st_mode&(0o077 if name in NAMES else 0o022) and before.st_size<=limit)
            raw=stream.read(limit+1);after=os.fstat(stream.fileno())
            require(len(raw)<=limit and (before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns))
        return raw
    finally:os.close(fd)

def query(path,body=None):
    require(path=='/task_runs/filter' or path.startswith('/flow_runs/') and len(path)==len('/flow_runs/')+36)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ValueError('redirect_rejected')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    request=urllib.request.Request('http://127.0.0.1:4200/api'+path,
        data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with opener.open(request,timeout=5) as response:
        raw=response.read(100001);require(len(raw)<=100000);return json.loads(raw)

def association(flow_id,proof,now,api=query):
    flow=api('/flow_runs/'+uid(flow_id));require(flow.get('id')==flow_id and flow.get('deployment_id')==DEPLOYMENT and flow.get('auto_scheduled') is True)
    require((flow.get('state') or {}).get('type') in {'RUNNING','COMPLETED'})
    scheduled=stamp(flow['expected_start_time']);require(scheduled.minute==45 and scheduled.second==scheduled.microsecond==0 and scheduled<=now and stamp(flow['start_time'])<=now)
    tasks=api('/task_runs/filter',{'task_runs':{'flow_run_id':{'any_':[flow_id]}},'limit':100})
    require(isinstance(tasks,list) and len(tasks)<100)
    tasks=[t for t in tasks if t.get('name','').startswith('Generate next24h production forecast')]
    require(len(tasks)==1);task=tasks[0];require(task.get('flow_run_id')==flow_id and (task.get('state') or {}).get('type')=='COMPLETED')
    e=proof['execution'];require(stamp(flow['start_time'])<=stamp(task['start_time'])<=stamp(e['started_at'])<=stamp(e['issued_at'])<=stamp(e['completed_at'])<=stamp(task['end_time'])<=now)

def persisted(raw,bundle):
    issue=stamp(bundle['forecasts'][0]['issue_time']);rows=[]
    for count,row in enumerate(csv.DictReader(io.TextIOWrapper(io.BytesIO(raw),encoding='utf-8')),1):
        require(count<=1000000)
        if stamp(row['forecast_issue_time'])==issue and row['model_release']==bundle['model']['release']:
            rows.append(row);require(len(rows)<=24)
    rows.sort(key=lambda r:int(r['horizon_hours']));require(len(rows)==24)
    for old,new in zip(rows,bundle['forecasts']):
        require(int(old['horizon_hours'])==new['horizon_hours'] and stamp(old['target_timestamp'])==stamp(new['target_time']))
        v=float(old['predicted_price_eur_mwh']);require(math.isfinite(v) and math.isclose(v,new['predicted_price_eur_mwh'],rel_tol=0,abs_tol=1e-12))

def deliver(receipt_id,flow_id,contract,builder,publisher,*,owner=1000,api=query,now=None):
    uid(receipt_id);uid(flow_id);now=now or dt.datetime.now(dt.timezone.utc)
    directory=RECEIPTS/receipt_id
    files={n:capture(directory,n,owner) for n in NAMES}
    integrity=contract.decode(files['integrity.json'])
    require(set(integrity)=={'version','run_id','sha256'} and type(integrity['version'])is int and integrity['version']==1 and integrity['run_id']==receipt_id)
    hashes={n:hashlib.sha256(files[n]).hexdigest() for n in NAMES-{'integrity.json'}}
    require(integrity['sha256']==hashes)
    proof=contract.decode(files['evidence.json']);require(proof['execution']['run_id']==receipt_id)
    association(flow_id,proof,now,api)
    paths=[directory/n for n in ('forecast.csv','provenance.json','model.json','evidence.json')]
    original=builder.safe_file;builder.safe_file=lambda p:files[Path(p).name] if Path(p) in paths else (_ for _ in ()).throw(ValueError())
    try:
        try:raw,digest=builder.build(*paths,[hashes[p.name] for p in paths],now)
        except contract.ExpiredPublication:return {'status':'SKIPPED_EXPIRED'}
    finally:builder.safe_file=original
    bundle=contract.validate(raw,digest,now)
    persisted(capture(HISTORY.parent,HISTORY.name,owner,64000000),bundle)
    # Publisher uses a NEW actual clock inside the lock and immediately before switch.
    result=publisher.publish_automatic(PUBLICATION,raw,digest)
    return {'status':result['status']}

def tools():
    # Installed root-only code and manifest, independent of the worker's checkout/env.
    folder=Path(__file__).absolute();require(folder==folder.resolve(strict=True))
    for p in (folder,)+tuple(folder.parents):
        s=p.lstat();require(s.st_uid==0 and not s.st_mode&0o022 and not stat.S_ISLNK(s.st_mode))
    parent=folder.parent;raw=capture(parent,'automation-manifest.json',0);meta=json.loads(raw)
    shared=parent/'shared';info=shared.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022)
    expected={'automatic.py','publish.py','prepare.py','shared/__init__.py','shared/forecast_publication.py'}
    require(set(meta)==expected)
    blobs={n:capture(parent/Path(n).parent,Path(n).name,0) for n in expected}
    require(all(hashlib.sha256(b).hexdigest()==meta[n] for n,b in blobs.items()))
    package=types.ModuleType('shared');package.__path__=[];sys.modules['shared']=package
    modules={}
    for label,name in (('contract','shared/forecast_publication.py'),('builder','prepare.py'),('publisher','publish.py')):
        module=types.ModuleType('shared.forecast_publication' if label=='contract' else 'verified_'+label)
        sys.modules[module.__name__]=module;exec(compile(blobs[name],'<verified-publication-tool>','exec'),module.__dict__);modules[label]=module
    return modules

if __name__=='__main__':
    try:
        require(os.getuid()==os.geteuid()==0)
        require(len(sys.argv)==5 and sys.argv[1]=='--receipt' and sys.argv[3]=='--flow-run')
        for parent in (PUBLICATION,)+tuple(PUBLICATION.parents):
            info=parent.lstat();require(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022)
        for folder in (PUBLICATION,PUBLICATION/'releases'):
            info=folder.lstat();require(info.st_uid==0 and info.st_gid==992 and stat.S_IMODE(info.st_mode)==0o750)
        m=tools();print(json.dumps(deliver(sys.argv[2],sys.argv[4],m['contract'],m['builder'],m['publisher'])))
    except Exception:
        print('{"status":"FAILED"}');raise SystemExit(1)
