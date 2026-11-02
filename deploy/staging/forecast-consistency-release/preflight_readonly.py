"""Bounded read-only Linux inspection; SSH stdin payload, Python >=3.9 stdlib only.
No installation, imports of application code, configuration tests or service actions.
"""
import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import sys

UNITS = ('powerflow-api.service', 'powerflow-streamlit.service',
         'powerflow-prefect-worker.service', 'powerflow-prefect-server.service',
         'postgresql.service', 'powerflow-candidate-api.service')
INSTALLED_HASHES = {'requirements/api.lock': 'b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3', 'src/api/__init__.py': 'd7842be76c9c978de666675161f35a3bd24c24e732682cb7d76e9401c5d36a85', 'src/api/account_routes.py': '4f74ca84be298f4848059cd8e15900cbd2c22bd7341594fc9bfefbdb4786a88c', 'src/api/account_service.py': '7aae6f7cb2397570bf0daa778f33af5bc19a95fc0b1f23053a8167a1e3da5343', 'src/api/admin_operations.py': '37c7f5dc1794d680580ff69165a3e64035c9282b202cdda141b67bbe106ee2f4', 'src/api/anomalies.py': '9f2957cbc733d61f80b36444033174e69cfe078cafa5d3b721b0f53eb809c7e3', 'src/api/app.py': 'ec2fabd38f91174ba2589a3831f824ee36151d5d622f313e796ded9226639a42', 'src/api/database.py': '962e07dd654cfb06017866a2c98bc553077239f98de9a0698f1eb83db4c6e906', 'src/api/feature_parity.py': '3a0f3c7c027229e4313f0a25e0fe46fde63834b24f712f49fc232892ab107699', 'src/api/market_data.py': '4c9b135d5f97b6e8381688c41fcd4e41047ea36423713c70a655ffa0b503752a', 'src/api/mfa_routes.py': '858b229be48baa668e5f816136db07c94c52310e01cdeac2803ccca4a8785470', 'src/api/mfa_service.py': '8ea67f55d36e4cd6e97fff1c5907ae83f3c48bbb74c948bd82fc424686942715', 'src/api/model_summaries.py': '9e57ce3de689f76e1036a901663c7cc7b7a49fe0f6188f113f203627e7bf2fd4', 'src/api/operations_summary.py': '5989120938501241c84d128c0e86897b3949668fde9d29421b4b79d4cc7a20f9', 'src/api/readiness.py': 'dd3bb8dda2bb3561212915aabdbc55e0a96430331e43e1f0ba0e277842167ff7', 'src/api/restricted_reports.py': '69ae92e3b888cde893946b49ec8acb6e5c117ce7987e27d7ac5cb1e33293c1b0', 'src/api/runtime.py': '8ef6206a373705bcccd06acf25de8cbc31e4e35a05bdb59a3366b630a617b030', 'src/api/security.py': '7e4d05cb476555fd18884212ecfd88357669f8cd9515edf6bcd17152a6175b61', 'src/shared/__init__.py': '4dacb653b07451745e1a3fede7a6901f964c82d90a130aff0d6f95d60994f110', 'src/shared/forecast_evaluation.py': 'f185ccf0c7b503eb529eb25fb95026937e4a8ddd9206bf6890b1d64ca010e28b', 'src/shared/market_context.py': '15e9746be365efabd4c3329d73553b7879c03c382e5b570349f757f19b968656', 'src/shared/operational_health.py': '4db26232cab02591c4d8bdd4adbe80694dffb44da7b57346cc17c50930c89108', 'src/shared/price_aggregation.py': 'cdb29ea521506babf568d9e8cdc656565b120d52b8b502cc48003550af172fbb'}
LOCKED_VERSIONS = {'annotated-doc': '0.0.5', 'annotated-types': '0.8.0', 'anyio': '4.15.1', 'certifi': '2026.10.19', 'cffi': '2.1.1', 'click': '8.5.0', 'cryptography': '46.0.7', 'fastapi': '0.136.3', 'h11': '0.16.0', 'httpcore': '1.0.9', 'httpx': '0.28.1', 'idna': '3.20', 'joserfc': '1.7.7', 'numpy': '2.4.6', 'pandas': '2.3.3', 'pycparser': '3.11', 'pydantic': '2.13.4', 'pydantic_core': '2.46.4', 'python-dateutil': '3.0.0', 'pytz': '2026.5', 'six': '1.17.0', 'starlette': '0.52.1', 'typing-inspection': '0.4.4', 'typing_extensions': '4.16.0', 'tzdata': '2026.5', 'uvicorn': '0.48.0'}
PROPERTIES = ('Id,ActiveState,SubState,MainPID,User,Group,ControlGroup,MemoryHigh,'
              'MemoryMax,MemorySwapMax,NoNewPrivileges,PrivateTmp,PrivateDevices,'
              'ProtectSystem,ProtectHome,ProtectKernelTunables,ProtectKernelModules,'
              'ProtectControlGroups,RestrictSUIDSGID,CapabilityBoundingSet,AmbientCapabilities,'
              'RestrictAddressFamilies,TasksMax,IPAddressDeny,ExecStart,EnvironmentFiles,WorkingDirectory')
DEPLOYMENT = '47e5ef51-26d0-44b6-b119-2c40d0e77397'
BACKEND = Path('/opt/powerflow/react-current')
STATIC = Path('/var/www/powerflow-staging/current')
DATA = Path('/srv/powerflow/published')
PUBLICATION = Path('/srv/powerflow/forecast-publications')
ENV = Path('/etc/powerflow/react-api.env')
FIELDS = {
 'identity': {'root','linux'}, 'capacity': {'available_bytes','swap_used_bytes','disk_free_bytes'},
 'pointers': {'backend_sha256','static_sha256','index_sha256','backend_safe','static_safe'},
 'environment': {'sha256','safe_permissions','data_root_match','publication_configured','publication_match','authentication_match'},
 'services': {'identity_sha256','all_running'},
 'sandbox': {'configured','uid_match','gid_match','single_worker','loopback_only'},
 'cgroup': {'memory_high','memory_max','swap_max'},
 'bpf': {'ingress_attached','egress_attached'},
 'runtime': {'python_match','lock_match','dependencies_match','imports','namespace_access'},
 'publication': {'present','candidate_readable','candidate_nonwritable'},
 'pipeline': {'schedule_match','concurrency_match','active_runs','scheduled_runs','ingestion_processes','safe_window'},
 'health': {'api','ready','production_api','streamlit','https','asset','api_https','private_ready','admin_unauthorized','acme'},
 'preservation': {'before_sha256','after_sha256','unchanged'},
}
STATES = {'PASS','FAIL','UNVERIFIED','NOT_RUN'}

def validate_report(report):
    if set(report) != {'schema_version','status','checks'} or report['schema_version'] != 1:
        raise ValueError('report_schema')
    if report['status'] not in {'PASS','BLOCKED'} or set(report['checks']) != set(FIELDS):
        raise ValueError('report_schema')
    for name, item in report['checks'].items():
        if set(item) != {'status','facts'} or item['status'] not in STATES or not isinstance(item['facts'],dict):
            raise ValueError('report_schema')
        if not set(item['facts']) <= FIELDS[name] or (item['status']=='PASS' and set(item['facts'])!=FIELDS[name]): raise ValueError('report_fields')
        for key,value in item['facts'].items():
            if key.endswith('sha256'):
                if not isinstance(value,str) or re.fullmatch('[0-9a-f]{64}',value) is None: raise ValueError('report_hash')
            elif type(value) not in (bool,int) or (type(value) is int and not 0 <= value < 2**63):
                raise ValueError('report_value')
    expected = 'PASS' if all(x['status']=='PASS' for x in report['checks'].values()) else 'BLOCKED'
    if report['status'] != expected: raise ValueError('report_status')
    return report

def read(path, maximum=2_000_000):
    # NOATIME avoids metadata writes; absent permissions are not silently retried.
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_NOATIME)
    with os.fdopen(fd,'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError('not_regular')
        raw=stream.read(maximum+1)
    if len(raw)>maximum: raise ValueError('read_bound')
    return raw

def sha(raw): return hashlib.sha256(raw).hexdigest()
def digest(path): return sha(read(path,64*1024*1024))
def canonical(path,root):
    target=path.resolve(strict=True)
    if root not in target.parents: raise ValueError('pointer_outside_root')
    for p in (target,)+tuple(target.parents):
        s=p.stat()
        if s.st_uid != 0 or s.st_mode & 0o022: raise ValueError('unsafe_ancestry')
    return target

def command(argv):
    # Only this exact systemctl metadata query is accepted. No shell.
    if argv != ['/usr/bin/systemctl','show',*UNITS,'--property='+PROPERTIES]:
        raise ValueError('unapproved_command')
    result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8,
                          check=True,env={'PATH':'/usr/bin:/bin','LANG':'C'},cwd='/')
    if len(result.stdout)>131072: raise ValueError('command_output_bound')
    return result.stdout.decode('utf-8')

def services():
    raw=command(['/usr/bin/systemctl','show',*UNITS,'--property='+PROPERTIES])
    units={}
    for block in raw.strip().split('\n\n'):
        values=dict(line.split('=',1) for line in block.splitlines() if '=' in line)
        if values.get('Id') not in UNITS or values['Id'] in units: raise ValueError('unexpected_unit')
        units[values['Id']]=values
    if set(units)!=set(UNITS): raise ValueError('missing_units')
    return units

def request(port,path,body=None,tls=False):
    # All endpoints and the sole POST are readonly queries. No ambient proxies.
    allowed={8000:{'/health'},8010:{'/health','/ready'},8501:{'/_stcore/health'},
             4200:{'/api/deployments/'+DEPLOYMENT,'/api/flow_runs/filter'},
             443:{'/','/api/health','/api/ready','/api/admin/forecast/provenance',
                  '/.well-known/acme-challenge/preflight-probe'}}
    if port==443 and re.fullmatch(r'/assets/[A-Za-z0-9_-]+\.(js|css)',path): pass
    elif path not in allowed.get(port,set()): raise ValueError('unapproved_probe')
    if body is not None and not (port==4200 and path=='/api/flow_runs/filter'):
        raise ValueError('unapproved_post')
    if tls:
        connection=http.client.HTTPSConnection('staging.powerflowenergy.dev',timeout=3,context=ssl.create_default_context())
        # Connect loopback, preserve original HTTPS host/SNI and chain verification.
        import socket
        connection._create_connection=lambda address, timeout, source_address=None: socket.create_connection(('127.0.0.1',443),timeout)
    else: connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
    try:
        connection.request('GET' if body is None else 'POST',path,
            body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json'})
        response=connection.getresponse(); raw=response.read(1_000_001)
        if len(raw)>1_000_000: raise ValueError('http_bound')
        return response.status,raw
    finally: connection.close()

def api(path,body=None):
    status,raw=request(4200,'/api'+path,body)
    if status!=200: raise ValueError('prefect_unavailable')
    return json.loads(raw)

def pipeline():
    d=api('/deployments/'+DEPLOYMENT); schedules=d.get('schedules',[]); g=d.get('global_concurrency_limit') or {}
    match=(d.get('id')==DEPLOYMENT and d.get('paused') is False and len(schedules)==1
           and schedules[0].get('active') is True and schedules[0].get('schedule')==
           {'cron':'45 * * * *','timezone':'UTC','day_or':True})
    concurrency=g.get('limit')==1 and g.get('active') is True and d.get('concurrency_options') is None
    body={'deployments':{'id':{'any_':[DEPLOYMENT]}},'flow_runs':{'state':{'type':{'any_':['RUNNING','PENDING','CANCELLING','PAUSED']}}},'limit':100}
    active=api('/flow_runs/filter',body)
    queued=api('/flow_runs/filter',dict(body,flow_runs={'state':{'type':{'any_':['SCHEDULED']}}},limit=10))
    if not isinstance(active,list) or not isinstance(queued,list): raise ValueError('prefect_shape')
    mount=read('/proc/self/mountinfo').decode()
    if not any(' /proc ' in line and ' - proc ' in line and 'hidepid=' not in line for line in mount.splitlines()):
        raise ValueError('process_visibility')
    count=0; entries=list(Path('/proc').iterdir())
    if len(entries)>32768: raise ValueError('process_bound')
    for p in entries:
        if not p.name.isdigit() or int(p.name)==os.getpid(): continue
        try: raw=read(p/'cmdline',65536)
        except FileNotFoundError: continue
        if any(x in raw for x in (b'fetch_entsoe_data',b'scheduled_pipeline',b'prefect.engine',b'prefect.flow_engine')): count+=1
    now=datetime.datetime.now(datetime.timezone.utc)
    next_slot=now.replace(minute=45,second=0,microsecond=0)
    if next_slot<=now:next_slot+=datetime.timedelta(hours=1)
    window=(next_slot-now).total_seconds()>600 and all(datetime.datetime.fromisoformat(x['expected_start_time'].replace('Z','+00:00'))>now+datetime.timedelta(minutes=10) for x in queued)
    facts={'schedule_match':match,'concurrency_match':concurrency,'active_runs':len(active),'scheduled_runs':len(queued),'ingestion_processes':count,'safe_window':window}
    return facts,match and concurrency and not active and not count and window and g.get('active_slots')==0

def fingerprints(units):
    paths=[Path('/etc/nginx/conf.d/powerflow.conf'),Path('/etc/nginx/conf.d/powerflow-staging-https.conf'),
           Path('/etc/nginx/conf.d/powerflow-staging-acme.conf'),Path('/etc/systemd/system/powerflow-candidate-api.service')]
    values={str(p):digest(p) for p in paths}
    # Resolve only the known public certificate; never read private-key material.
    cert=Path('/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem').resolve(strict=True)
    if not str(cert).startswith('/etc/letsencrypt/archive/powerflowenergy.dev/'): raise ValueError('certificate_target')
    values['public_certificate']=digest(cert)
    for relative in ['data/processed/silver_electricity_market_data.csv', 'data/features/gold_model_features.csv', 'data/raw/entsoe/prices.csv', 'data/raw/entsoe/load.csv', 'data/raw/entsoe/generation.csv', 'data/raw/weather/open_meteo_weather.csv', 'data/reports/actual_vs_predicted.csv', 'data/reports/detected_anomalies.csv', 'data/reports/final_holdout_metrics.csv', 'data/reports/feature_importance.csv', 'artifacts/models/final_model_release_manifest.json', 'artifacts/models/releases/next24h/next24h_release_manifest.json']:
        values['published/'+relative]=digest(DATA/relative)
    for relative in ('artifacts/models/releases/next24h/next24h_release_manifest.json','data/reports/next24h_forecast.csv','data/reports/next24h_forecast_provenance.json'):
        values['production/'+relative]=digest(Path('/home/ec2-user/Electricity_Trading_Pipeline')/relative)
    values['services']={k:{f:v.get(f) for f in ('MainPID','ActiveState','SubState')} for k,v in units.items()}
    return sha(json.dumps(values,sort_keys=True).encode())

import ctypes
import os
import platform
from pathlib import Path


class Query(ctypes.Structure):
    _fields_=[('target_fd',ctypes.c_uint32),('attach_type',ctypes.c_uint32),
              ('query_flags',ctypes.c_uint32),('attach_flags',ctypes.c_uint32),
              ('prog_ids',ctypes.c_uint64),('prog_cnt',ctypes.c_uint32),
              ('prog_attach_flags',ctypes.c_uint64)]


def attachments(path,call=None):
    if platform.system()!='Linux' or platform.machine()!='x86_64':raise RuntimeError('BPF_query_requires_Linux_x86_64')
    assert ctypes.sizeof(Query)==40
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        invoke=call or ctypes.CDLL(None,use_errno=True).syscall
        result={}
        for name,attach in (('ingress',0),('egress',1)):
            ids=(ctypes.c_uint32*64)()
            # query_flags1 requests effective attachments, including ancestors.
            attr=Query(target_fd=fd,attach_type=attach,query_flags=1,
                       prog_ids=ctypes.addressof(ids),prog_cnt=64)
            code=invoke(321,16,ctypes.byref(attr),ctypes.sizeof(attr))
            if code!=0:raise RuntimeError('BPF_query_not_available_errno_'+str(ctypes.get_errno()))
            if attr.prog_cnt>64:raise RuntimeError('BPF_query_result_limit')
            result[name]=list(ids[:attr.prog_cnt])
        return result
    finally:os.close(fd)


def bpf(c):
    if c.get('ControlGroup')!='/system.slice/powerflow-candidate-api.service': raise ValueError('cgroup_layout')
    programs=attachments('/sys/fs/cgroup'+c['ControlGroup'])
    facts={'ingress_attached':bool(programs['ingress']),'egress_attached':bool(programs['egress'])}
    return facts,all(facts.values())

RUNTIME_CHILD = r"""
import importlib.metadata as m,json,os,sys,socket
from pathlib import Path
def blocked(*a,**kw): raise RuntimeError('network_forbidden')
socket.socket=blocked; socket.create_connection=blocked
assert os.getuid()==992 and os.getgid()==992 and not os.getgroups()
import numpy,pandas,pydantic_core,cryptography.hazmat.bindings._rust,_cffi_backend
versions={name:m.version(name) for name in json.loads(sys.argv[1])}
p=Path('/srv/powerflow/forecast-publications')
# Metadata/access checks only. Missing publication is not a functioning overlay.
publication={'present':p.is_dir(),'candidate_readable':p.is_dir() and os.access(p,os.R_OK|os.X_OK),'candidate_nonwritable':p.is_dir() and not os.access(p,os.W_OK)}
assert os.access('/srv/powerflow/published',os.R_OK|os.X_OK) and not os.access('/srv/powerflow/published',os.W_OK)
print(json.dumps({'python':sys.version.split()[0],'versions':versions,'publication':publication}))
"""

def namespace_runtime(c):
    b=canonical(BACKEND,Path('/opt/powerflow/releases'))
    if any(digest(b/rel)!=value for rel,value in INSTALLED_HASHES.items()): raise ValueError('installed_code_drift')
    # The original hotfix reuses the old isolated venv; resolve only under releases.
    executable=(b/'.venv-api/bin/python').resolve(strict=True)
    if executable != Path('/usr/bin/python3.14'): raise ValueError('interpreter_drift')
    venv=b/'.venv-api/bin/python'
    pid=int(c['MainPID'])
    def groups(): os.setgroups([])
    argv=['/usr/bin/nsenter','--target',str(pid),'--mount','--setgid','992','--setuid','992','--',str(venv),'-I','-B','-c',RUNTIME_CHILD,json.dumps(sorted(LOCKED_VERSIONS))]
    result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=True,
        cwd='/',env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','AWS_EC2_METADATA_DISABLED':'true'},preexec_fn=groups)
    if len(result.stdout)>16384: raise ValueError('runtime_bound')
    data=json.loads(result.stdout)
    if set(data)!={'python','versions','publication'} or set(data['publication'])!={'present','candidate_readable','candidate_nonwritable'} or any(type(v)is not bool for v in data['publication'].values()): raise ValueError('runtime_output')
    facts={'python_match':data['python']=='3.14.7','lock_match':True,'dependencies_match':data['versions']==LOCKED_VERSIONS,'imports':True,'namespace_access':True}
    return facts,data['publication']

def main():
    checks={name:{'status':'NOT_RUN','facts':{}} for name in FIELDS}
    def check(name,fn):
        try:
            facts,ok=fn(); checks[name]={'status':'PASS' if ok else 'FAIL','facts':facts}
        except Exception:
            # Deliberately no exception text, traceback, paths or command output.
            checks[name]={'status':'UNVERIFIED','facts':{}}
        return checks[name]['status']=='PASS'
    if not check('identity',lambda:({'root':os.geteuid()==0,'linux':sys.platform=='linux'},os.geteuid()==0 and sys.platform=='linux')):
        return finish(checks)
    units=None; before=None
    try: units=services(); before=fingerprints(units)
    except Exception: checks['preservation']={'status':'UNVERIFIED','facts':{}}; return finish(checks)
    def capacity():
        m={line.split(':')[0]:int(line.split()[1])*1024 for line in read('/proc/meminfo').decode().splitlines() if line.startswith(('MemAvailable:','SwapTotal:','SwapFree:'))}
        disk=os.statvfs('/opt/powerflow'); free=disk.f_bavail*disk.f_frsize
        facts={'available_bytes':m['MemAvailable'],'swap_used_bytes':m['SwapTotal']-m['SwapFree'],'disk_free_bytes':free}
        return facts,m['MemAvailable']>=768*1024**2 and free>=2*1024**3+2*1_310_633
    check('capacity',capacity)
    def pointers():
        if not BACKEND.is_symlink() or not STATIC.is_symlink(): raise ValueError('not_pointers')
        b=canonical(BACKEND,Path('/opt/powerflow/releases')); s=canonical(STATIC,Path('/var/www/powerflow-staging/releases'))
        return {'backend_sha256':sha(str(b).encode()),'static_sha256':sha(str(s).encode()),'index_sha256':digest(s/'index.html'),'backend_safe':True,'static_safe':True},True
    check('pointers',pointers)
    def environment():
        st=ENV.lstat(); safe=stat.S_ISREG(st.st_mode) and st.st_uid==0 and st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o600
        raw=read(ENV); values={}
        for line in raw.decode().splitlines():
            if not line or line.startswith('#'): continue
            k,v=line.split('=',1)
            if k in values: raise ValueError('duplicate_environment')
            values[k]=v.strip('"\'')
        configured='POWERFLOW_FORECAST_PUBLICATION_ROOT' in values
        data=values.get('POWERFLOW_API_DATA_ROOT')==str(DATA)
        publication=not configured or values['POWERFLOW_FORECAST_PUBLICATION_ROOT']==str(PUBLICATION)
        auth=values.get('POWERFLOW_API_ENV')=='staging' and values.get('POWERFLOW_API_COGNITO_ISSUER')=='https://cognito-idp.us-east-1.amazonaws.com/us-east-1_NLoYFRvex' and values.get('POWERFLOW_API_COGNITO_CLIENT_IDS')=='4t8s6a673a18qhbauqac8rhdcf' and values.get('POWERFLOW_ACCOUNT_TOTP_ENABLED','false')=='false' and not values.get('POWERFLOW_ACCOUNT_TOTP_TEST_SUBJECT','')
        return {'sha256':sha(raw),'safe_permissions':safe,'data_root_match':data,'publication_configured':configured,'publication_match':publication,'authentication_match':auth},safe and data and publication and auth
    check('environment',environment)
    running=all(x.get('ActiveState')=='active' and x.get('SubState')=='running' and int(x.get('MainPID','0'))>0 for x in units.values())
    checks['services']={'status':'PASS' if running else 'FAIL','facts':{'identity_sha256':sha(json.dumps({k:v.get('MainPID') for k,v in units.items()},sort_keys=True).encode()),'all_running':running}}
    c=units[UNITS[-1]]
    def sandbox():
        expected={'User':'powerflow-api','NoNewPrivileges':'yes','PrivateTmp':'yes','PrivateDevices':'yes','ProtectSystem':'strict','ProtectHome':'yes','ProtectKernelTunables':'yes','ProtectKernelModules':'yes','ProtectControlGroups':'yes','RestrictSUIDSGID':'yes','CapabilityBoundingSet':'','AmbientCapabilities':'','TasksMax':'64'}
        configured=all(c.get(k)==v for k,v in expected.items())
        pid=int(c['MainPID']); status=read('/proc/%d/status'%pid).decode()
        uid=re.search(r'^Uid:\s+(\d+)\s+(\d+)',status,re.M); gid=re.search(r'^Gid:\s+(\d+)\s+(\d+)',status,re.M)
        effective=all(x in status for x in ('NoNewPrivs:\t1','Seccomp:\t2')) and re.search(r'^CapEff:\s+0+$',status,re.M) is not None
        configured=configured and effective
        uid_match=bool(uid and uid.group(1)==uid.group(2)=='992'); gid_match=bool(gid and gid.group(1)==gid.group(2)=='992')
        argv=read('/proc/%d/cmdline'%pid,65536).split(b'\0'); worker=argv.count(b'--workers')==1 and argv[argv.index(b'--workers')+1]==b'1'
        inodes={}
        for family in ('tcp','tcp6'):
            for line in read('/proc/net/'+family).decode().splitlines()[1:]:
                fields=line.split()
                if fields[3]=='0A' and fields[1].endswith(':1F4A'):
                    inodes[fields[9]]=fields[1]
        own=set()
        for fd in Path('/proc/%d/fd'%pid).iterdir():
            try: own.add(os.readlink(fd))
            except FileNotFoundError: continue
        loopback=len(inodes)==1 and list(inodes.values())==['0100007F:1F4A'] and 'socket:['+next(iter(inodes))+']' in own
        configured=configured and set(c.get('RestrictAddressFamilies','').split())=={'AF_UNIX','AF_INET','AF_INET6'} and all(a in c.get('IPAddressDeny','') for a in ('169.254.169.254','fd00:ec2::254'))
        return {'configured':configured,'uid_match':uid_match,'gid_match':gid_match,'single_worker':worker,'loopback_only':loopback},configured and uid_match and gid_match and worker and loopback
    check('sandbox',sandbox)
    def cgroup():
        if c.get('ControlGroup')!='/system.slice/powerflow-candidate-api.service': raise ValueError('cgroup_layout')
        p=Path('/sys/fs/cgroup')/c['ControlGroup'].lstrip('/')
        values=[int(read(p/x,100).strip()) for x in ('memory.high','memory.max','memory.swap.max')]
        return dict(zip(('memory_high','memory_max','swap_max'),values)),values==[384*1024**2,512*1024**2,0]
    check('cgroup',cgroup)
    check('bpf',lambda: bpf(c))
    if checks['sandbox']['status']=='PASS' and checks['pointers']['status']=='PASS' and checks['environment']['status']=='PASS':
        try:
            runtime,publication=namespace_runtime(c)
            check('runtime',lambda: (runtime,all(runtime.values())))
            check('publication',lambda: (publication,all(publication.values())))
        except Exception:
            checks['runtime']={'status':'UNVERIFIED','facts':{}}
            checks['publication']={'status':'UNVERIFIED','facts':{}}
    else:
        checks['runtime']={'status':'UNVERIFIED','facts':{}}
        checks['publication']={'status':'UNVERIFIED','facts':{}}
    check('pipeline',pipeline)
    def health():
        facts={}
        for key,port,path in [('api',8010,'/health'),('ready',8010,'/ready'),('production_api',8000,'/health'),('streamlit',8501,'/_stcore/health')]:
            facts[key]=request(port,path)[0]
        status,html=request(443,'/',tls=True); facts['https']=status
        assets=re.findall(rb'(?:src|href)="(/assets/[A-Za-z0-9_-]+\.(?:js|css))"',html)
        if not assets: raise ValueError('asset_missing')
        facts['asset']=request(443,assets[0].decode(),tls=True)[0]
        for key,path in [('api_https','/api/health'),('private_ready','/api/ready'),('admin_unauthorized','/api/admin/forecast/provenance'),('acme','/.well-known/acme-challenge/preflight-probe')]: facts[key]=request(443,path,tls=True)[0]
        return facts,all(v==(404 if k=='private_ready' else 401 if k=='admin_unauthorized' else 200) for k,v in facts.items())
    check('health',health)
    def preservation():
        after=fingerprints(services())
        return {'before_sha256':before,'after_sha256':after,'unchanged':before==after},before==after
    check('preservation',preservation)
    return finish(checks)

def finish(checks):
    report={'schema_version':1,'status':'PASS' if all(x['status']=='PASS' for x in checks.values()) else 'BLOCKED','checks':checks}
    validate_report(report); print(json.dumps(report,sort_keys=True)); return 0 if report['status']=='PASS' else 1

if __name__=='__main__': raise SystemExit(main())
