"""Read-only prerequisites; no install, restart, pointer or configuration writes."""
import base64
import datetime as dt
import json
import os
from pathlib import Path
import stat

PHASE='READ_ONLY';CHANGED=False
API=Path(C['api']);STATIC=Path(C['static']);CONTROL=Path(C['control'])
def need(v,code):H.need(v,code)
def sha(raw):return H.sha(raw)
def raw_file(key):
    need(key in C['files'],'FILE_SCOPE');item=C['files'][key]
    raw=P.read(item['copy_from']) if 'copy_from'in item else base64.b64decode(item['base64'],validate=True)
    need(len(raw)<=item.get('max_bytes',2000000) and (item['bytes']is None or len(raw)==item['bytes']) and sha(raw)==item['sha256'],'FILE_BINDING')
    return raw
def inventory(prefix):return {k[len(prefix):]:v['sha256'] for k,v in C['files'].items() if k.startswith(prefix)}
def helper_verified():
    r=HVIEW.load_record();need(r['phase']=='APPLIED','HELPER_V2_NOT_APPLIED');HVIEW.verified_backups(r);HVIEW.new_tree(r,complete=True)
    return sha(json.dumps(r,sort_keys=True).encode())
def baseline_preservation():
    d=P.deployment()
    env=d.get('job_variables',{}).get('env',{})
    need(env.get('POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED')==env.get('POWERFLOW_AUTO_PUBLICATION_ENABLED')=='true','DELIVERY_FLAG_DRIFT')
    return {'production':P.production(),'forecast':P.forecast_fingerprint(),'store':H.store_snapshot(),'helper':helper_verified(),
            'policy':sha(json.dumps({'variables':d.get('job_variables',{}),'projection':H.OLD_PLAN.stable_projection(d),'pool':P.pool()},sort_keys=True).encode()),
            'environment':P.snap(P.ENV,0,0,0o600)[0]['sha256'],'nginx':P.snap(P.NGINX,0,0,0o644)[0]['sha256']}
def same(before,after):need(before==after,'PRESERVATION_DRIFT')
def candidate_probe_script():
    # Source bytes only: no runtime arguments, tokens, real user data or files.
    sources={};locations={}
    for key in C['files']:
        if key.startswith('api/src/') and key.endswith('.py'):
            rel=key[len('api/src/'):];name=rel[:-3].replace('/','.')
            package=name.endswith('.__init__')
            if package:name=name[:-9]
            sources[name]=(raw_file(key).decode(),package)
            locations[name]=str(API/'src'/rel)
    return ("import sys,os,json,importlib.abc,importlib.util\n"
            "assert sys.version_info[:3]==(3,14,7) and os.getuid()==os.geteuid()==992 and os.getgid()==os.getegid()==992\n"
            "def audit(event,args):\n"
            " if event in {'socket.connect','socket.bind','subprocess.Popen','os.system','os.mkdir','os.remove','os.rename','os.chmod','os.chown','os.symlink','os.link'}:raise RuntimeError('IMPORT_SIDE_EFFECT')\n"
            " if event=='open' and args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):raise RuntimeError('IMPORT_WRITE')\n"
            "sys.addaudithook(audit)\nSOURCES="+repr(sources)+"\nLOCATIONS="+repr(locations)+"\n"
            "class Loader(importlib.abc.MetaPathFinder,importlib.abc.Loader):\n"
            " def find_spec(self,name,path=None,target=None):\n"
            "  if name not in SOURCES:return None\n"
            "  spec=importlib.util.spec_from_loader(name,self,origin=LOCATIONS[name],is_package=SOURCES[name][1]);spec.has_location=True\n"
            "  if SOURCES[name][1]:spec.submodule_search_locations=[os.path.dirname(LOCATIONS[name])]\n"
            "  return spec\n"
            " def create_module(self,spec):return None\n"
            " def exec_module(self,module):\n"
            "  module.__file__=LOCATIONS[module.__name__]\n"
            "  if SOURCES[module.__name__][1]:module.__path__=[os.path.dirname(module.__file__)]\n"
            "  exec(compile(SOURCES[module.__name__][0],module.__file__,'exec'),module.__dict__)\n"
            "sys.meta_path.insert(0,Loader())\n"
            "import api.app,shared.forecast_availability as a,shared.forecast_publication as p\n"
            "assert str(api.app.PROJECT_ROOT)=="+repr(str(API))+"\n"
            "assert api.app.__file__==api.app.__spec__.origin==LOCATIONS['api.app'] and api.__file__==LOCATIONS['api']\n"
            "assert api.__path__==[os.path.dirname(LOCATIONS['api'])] and api.__spec__.submodule_search_locations==api.__path__\n"
            "assert a.AVAILABILITY_POLICY=='ISSUE_HORIZON_V1' and a.SERVING_HORIZON.total_seconds()==86400 and p.MAX_AGE.total_seconds()==10800\n"
            "assert {'availability_policy','refresh_due_at'}<=set(api.app.ForecastPublication.model_fields)\n"
            "assert {'/forecast/next24','/operations/current','/pipeline/current','/admin/operations/current'}<={r.path for r in api.app.app.routes}\n"
            "print('CANDIDATE_IMPORT_PASS')\n").encode()
def import_probe(venv):
    pid=int(B['services']()[H.OLD_PLAN.UNIT]['MainPID']);need(pid>1,'CANDIDATE_PID')
    argv=['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--','/usr/bin/setpriv','--no-new-privs','--reuid=992','--regid=992','--clear-groups',str(venv/'bin/python'),'-I','-B','-']
    result=B['bounded_run'](argv,input=candidate_probe_script(),timeout=20,limit=8192,grace=5)
    need(result['returncode']==0 and not result['failure'] and result['stdout']==b'CANDIDATE_IMPORT_PASS\n','CANDIDATE_IMPORT_COMPATIBILITY')
def fresh():
    need(os.getgid()==os.getegid()==0,'ROOT_GROUP')
    need(not any(os.path.lexists(p) for p in [API,STATIC,CONTROL]),'TRANSACTION_OR_DESTINATION_EXISTS')
    for p in [API.parent,STATIC.parent,CONTROL.parent]:P.safe(p)
    # Reviewed V5+helper guards include >600s window, actual idleness, capacity,
    # frozen model, source/hash baselines, SDK semantics, routing and preservation.
    H.common('new');helper_verified()
    P.idle(sum(v['bytes'] if v['bytes']is not None else v['max_bytes'] for v in C['files'].values())*3)
    for link,target in [(P.BACKEND_LINK,P.API),(P.STATIC_LINK,P.STATIC)]:
        s=link.lstat();need(stat.S_ISLNK(s.st_mode) and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(0,0,0o777) and os.readlink(link)==str(target),'POINTER_METADATA')
    _,raw=P.snap(P.CONTROL/'record.json',0,0,0o600);record=json.loads(raw)
    H.OLD_PLAN.record_valid(record,OLD);need(record['phase']=='APPLIED','V5_NOT_APPLIED')
    venv=B['canonical'](P.API/'.venv-api',Path('/opt/powerflow/releases'))
    closure=P.runtime_closure(venv)
    need(closure==record['runtime']['executable_closure'],'API_RUNTIME_CLOSURE_DRIFT')
    # Verify all payloads/copy sources before the first transaction mutation.
    for key in C['files']:raw_file(key)
    import_probe(venv)
    result=baseline_preservation();result['venv']=str(venv);result['runtime']=closure
    return result
def preflight_report():
    fresh()
    return {'status':'PREFLIGHT_PASS','phase':'READ_ONLY','changed':False,'release':C['release'],'transaction':C['transaction'],
            'linux_imports':'PASS','forecast_enabled':True,'operational_enabled':True,'rollback_ready':True,'deployment_authorized':False}
