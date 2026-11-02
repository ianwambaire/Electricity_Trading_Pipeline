"""Hash-bound proposed staging update/rollback. Executed only after approval.
CONFIG, BASE and ACTION are injected from independently verified retained bytes.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

ID='phase-forecast-consistency-20261101-v1'
API=Path('/opt/powerflow/releases')/ID
STATIC=Path('/var/www/powerflow-staging/releases')/ID
CONTROL=Path('/var/lib/powerflow-staging/forecast-consistency-20261101-v1')
BACKEND_LINK=Path('/opt/powerflow/react-current')
STATIC_LINK=Path('/var/www/powerflow-staging/current')
ENV=Path('/etc/powerflow/react-api.env')
OVERLAY=Path('/srv/powerflow/forecast-publications')
UNIT='powerflow-candidate-api.service'
BACKEND_TARGET_SHA='dd81b1ae0779ac861ff937bd34b7650e492b5049bde8aa940ef84bcdb8cd954c'
STATIC_TARGET_SHA='4d9590d765bc745f120412525ed0d117d251236d278234aada2433d0f97ad374'
KEY=b'POWERFLOW_FORECAST_PUBLICATION_ROOT'
ENV_BASELINE='ee1ea96ebd2aa9b1c15891fd4cb9adf1c6ee7d06d6177b99bb1f375419b36704'
PHASE='PREFLIGHT'
CHANGED=False

class Stop(ValueError):pass

def need(value,label):
    if not value:raise Stop(label)

def sha(raw):return hashlib.sha256(raw).hexdigest()
def read(path,limit=64*1024*1024):return BASE['read'](path,limit)
def digest(path):return sha(read(path))

def safe(path):
    for node in (path,)+tuple(path.parents):
        st=node.lstat()
        need(not stat.S_ISLNK(st.st_mode) and st.st_uid==0 and not st.st_mode&0o022,'UNSAFE_PATH')

def target(link,parent):
    need(link.is_symlink(),'POINTER_REQUIRED')
    value=BASE['canonical'](link,parent)
    need(value.parent==parent,'POINTER_LAYOUT')
    return value

def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def create(path,raw,mode=0o600):
    safe(path.parent)
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode),'wb') as stream:
        os.fchmod(stream.fileno(),mode);os.fchown(stream.fileno(),0,0);stream.write(raw);stream.flush();os.fsync(stream.fileno())
    sync_dir(path.parent)

def atomic_file(path,raw,mode):
    temporary=path.parent/('.forecast-consistency-'+uuid.uuid4().hex)
    create(temporary,raw,mode);os.replace(temporary,path);sync_dir(path.parent)
    need(digest(path)==sha(raw),'ATOMIC_FILE_VERIFY')

def pointer(link,value):
    safe(link.parent);temporary=link.parent/('.forecast-consistency-'+uuid.uuid4().hex)
    os.symlink(str(value),temporary);os.replace(temporary,link);sync_dir(link.parent)
    need(link.resolve(strict=True)==value,'POINTER_VERIFY')

def run(command,seconds=45):
    allowed=command[:2]==['/usr/bin/systemctl','restart'] and command[2:]==[UNIT]
    need(allowed,'COMMAND_SCOPE')
    result=BASE['bounded_run'](command,timeout=seconds,limit=32768,grace=5)
    need(not result['failure'] and result['returncode']==0,'CANDIDATE_RESTART_FAILED')

def inventory(root):
    safe(root);result={};total=0
    for parent,dirs,files in os.walk(root,followlinks=False):
        need(len(dirs)+len(files)<200,'STATIC_INVENTORY_BOUND')
        for name in dirs:safe(Path(parent)/name)
        for name in files:
            p=Path(parent)/name;safe(p);raw=read(p,2_000_000);total+=len(raw)
            need(len(result)<160 and total<8*1024**2,'STATIC_SIZE_BOUND')
            result[str(p.relative_to(root))]=sha(raw)
    need('index.html' in result,'STATIC_INDEX_MISSING')
    return result

def production():
    units=BASE['services']()
    need(all(v.get('ActiveState')=='active' and v.get('SubState')=='running' for k,v in units.items() if k!=UNIT),'PRODUCTION_SERVICE_STATE')
    return BASE['fingerprints']({k:v for k,v in units.items() if k!=UNIT})

def idle_capacity(extra):
    facts,ok=BASE['pipeline']();need(ok,'PIPELINE_OR_WINDOW_GATE')
    m={line.split(':')[0]:int(line.split()[1])*1024 for line in read('/proc/meminfo').decode().splitlines() if line.startswith(('MemAvailable:','SwapTotal:','SwapFree:'))}
    need(m['MemAvailable']>=768*1024**2,'RAM_GATE')
    for p in ('/opt/powerflow','/var/www/powerflow-staging','/var/lib'):
        fs=os.statvfs(p);need(fs.f_bavail*fs.f_frsize>=2*1024**3+extra,'DISK_GATE')
    return {'available_bytes':m['MemAvailable'],'swap_used_bytes':m['SwapTotal']-m['SwapFree']}

def runtime(expected_backend):
    c=BASE['services']()[UNIT];need(c.get('ActiveState')=='active' and c.get('SubState')=='running','CANDIDATE_NOT_RUNNING')
    required={'User':'powerflow-api','Group':'powerflow-api','MemoryHigh':str(384*1024**2),'MemoryMax':str(512*1024**2),'MemorySwapMax':'0','ProtectSystem':'strict','ProtectHome':'yes','NoNewPrivileges':'yes','PrivateTmp':'yes','PrivateDevices':'yes','ProtectKernelTunables':'yes','ProtectKernelModules':'yes','ProtectControlGroups':'yes','RestrictSUIDSGID':'yes','CapabilityBoundingSet':'','AmbientCapabilities':'','TasksMax':'64'}
    need(all(c.get(k)==v for k,v in required.items()),'SANDBOX_PROPERTIES')
    need(set(c.get('RestrictAddressFamilies','').split())=={'AF_UNIX','AF_INET','AF_INET6'},'ADDRESS_FAMILIES')
    need(all(a in c.get('IPAddressDeny','') for a in ('169.254.169.254','fd00:ec2::254')),'IMDS_DENY')
    pid=int(c['MainPID']);status=read('/proc/%d/status'%pid).decode()
    for field in ('Uid','Gid'):
        match=re.search(r'^'+field+r':\s+(\d+)\s+(\d+)',status,re.M)
        need(match and match.group(1)==match.group(2)=='992','CANDIDATE_IDENTITY')
    need('NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status and re.search(r'^CapEff:\s+0+$',status,re.M),'PROCESS_SECURITY')
    need(Path('/proc/%d/cwd'%pid).resolve(strict=True)==expected_backend,'RUNNING_CODE_TARGET')
    args=read('/proc/%d/cmdline'%pid,65536).split(b'\0')
    need(args.count(b'--workers')==1 and args[args.index(b'--workers')+1]==b'1','SINGLE_WORKER')
    inodes={}
    for family in ('tcp','tcp6'):
        for line in read('/proc/net/'+family).decode().splitlines()[1:]:
            f=line.split()
            if f[3]=='0A' and f[1].endswith(':1F4A'):inodes[f[9]]=f[1]
    sockets=set()
    for fd in Path('/proc/%d/fd'%pid).iterdir():
        try:sockets.add(os.readlink(fd))
        except FileNotFoundError:continue
    need(len(inodes)==1 and list(inodes.values())==['0100007F:1F4A'] and 'socket:['+next(iter(inodes))+']' in sockets,'LISTENER_OWNERSHIP')
    need(c.get('ControlGroup')=='/system.slice/'+UNIT,'CGROUP_LAYOUT')
    for name,value in [('memory.high',384*1024**2),('memory.max',512*1024**2),('memory.swap.max',0)]:need(int(read(Path('/sys/fs/cgroup')/c['ControlGroup'].lstrip('/')/name,100))==value,'CGROUP_LIMITS')
    _,ok=BASE['bpf'](c);need(ok,'BPF_ATTACHMENTS')
    cg=Path('/sys/fs/cgroup')/c['ControlGroup'].lstrip('/')
    need(int(read(cg/'memory.swap.current',100))==0,'CANDIDATE_SWAP_ACTIVITY')

def probe(port,path,status):
    code,raw=BASE['request'](port,path,tls=port==443);need(code==status,'HTTP_ACCEPTANCE');return raw

def candidate_ready():
    # Explicit bounded startup observations, not a deployment retry.
    for _ in range(10):
        try:
            if BASE['request'](8010,'/health')[0]==200 and BASE['request'](8010,'/ready')[0]==200:return
        except Exception:pass
        time.sleep(1)
    raise Stop('STARTUP_READINESS')

def request_api(path):
    # Fixed extra public API paths only. Same no-proxy loopback transport.
    import http.client
    need(path in ('/forecast/next24','/operations/summary','/forecast/one-hour','/market/coverage','/pipeline/status','/models/summary','/admin/forecast/provenance'),'API_PROBE_SCOPE')
    connection=http.client.HTTPConnection('127.0.0.1',8010,timeout=3)
    try:
        connection.request('GET',path);r=connection.getresponse();raw=r.read(1_000_001)
        need(len(raw)<=1_000_000,'API_BODY_BOUND');return r.status,dict(r.getheaders()),raw
    finally:connection.close()

def missing_acceptance():
    need(not os.path.lexists(OVERLAY),'UNEXPECTED_PUBLICATION_ROOT')
    code,headers,raw=request_api('/forecast/next24')
    need(code==503 and json.loads(raw)=={'detail':{'code':'FORECAST_WITHHELD'}} and 'no-store' in headers.get('Cache-Control',''),'MISSING_FORECAST_CONTRACT')
    code,_,raw=request_api('/operations/summary');summary=json.loads(raw)
    need(code==200 and summary.get('forecast_status')=='MISSING_PUBLICATION' and summary.get('health') in ('Historical snapshot','Unavailable') and 'Historical' in summary.get('completeness_note',''),'HISTORICAL_SEPARATION')
    need(request_api('/admin/forecast/provenance')[0]==401,'ADMIN_AUTH_BOUNDARY')
    for path in ('/forecast/one-hour','/market/coverage','/pipeline/status','/models/summary'):need(request_api(path)[0]==200,'HISTORICAL_API')

def validate_inputs():
    need(set(CONFIG)=={'files'} and len(CONFIG['files'])==63,'INPUT_SCOPE')
    for name,item in CONFIG['files'].items():
        path=Path(name)
        need(not path.is_absolute() and '..' not in path.parts and path.parts[0] in ('api','static'),'INPUT_PATH')
        raw=base64.b64decode(item['base64'],validate=True)
        need(len(raw)==item['bytes'] and sha(raw)==item['sha256'],'INPUT_HASH')
    need(sum(n.startswith('api/') for n in CONFIG['files'])==26 and sum(n.startswith('static/') for n in CONFIG['files'])==37,'INPUT_COUNTS')
    need('api/src/api/forecast_source.py' in CONFIG['files'] and 'static/index.html' in CONFIG['files'],'SELECTOR_MISSING')

def install_tree(root,prefix):
    root.mkdir(mode=0o755);os.chmod(root,0o755)
    for name,item in sorted(CONFIG['files'].items()):
        if not name.startswith(prefix):continue
        relative=name[len(prefix):];p=root/relative
        for directory in reversed(p.parent.relative_to(root).parents):
            q=root/directory
            if not q.exists():q.mkdir(mode=0o755);os.chmod(q,0o755)
        p.parent.mkdir(parents=True,exist_ok=True)
        for ancestor in (p.parent,)+tuple(p.parent.parents):
            if ancestor==root.parent:break
            os.chmod(ancestor,0o755)
        raw=base64.b64decode(item['base64'],validate=True)
        need(sha(raw)==item['sha256'] and len(raw)==item['bytes'],'INPUT_HASH')
        create(p,raw,0o644)
    for name,item in CONFIG['files'].items():
        if name.startswith(prefix):need(digest(root/name[len(prefix):])==item['sha256'],'INSTALLED_HASH')

def validate_rollback(record):
    ROLLBACK['validate']({'schema_version':1,'previous_backend':record['previous_backend'],'previous_static':record['previous_static'],
        'installed_backend':record['new_backend'],'installed_static':record['new_static'],
        'original_env_sha256':record['original_env_sha256'],'installed_env_sha256':record['installed_env_sha256'],
        'environment_backup':str(CONTROL/'previous-api.env'),'environment_uid':0,'environment_gid':0,'environment_mode':'0600'})

def state_save(record):atomic_file(CONTROL/'state.json',json.dumps(record,sort_keys=True).encode(),0o600)

def apply():
    global PHASE,CHANGED
    need(os.geteuid()==0,'ROOT_REQUIRED');validate_inputs()
    for p in (API,STATIC,CONTROL):need(not os.path.lexists(p),'DESTINATION_CONFLICT')
    safe(API.parent);safe(STATIC.parent)
    if CONTROL.parent.exists():safe(CONTROL.parent)
    else:safe(CONTROL.parent.parent)
    need(not os.path.lexists(OVERLAY),'UNEXPECTED_PUBLICATION_ROOT')
    old_backend=target(BACKEND_LINK,API.parent);old_static=target(STATIC_LINK,STATIC.parent)
    need(sha(str(old_backend).encode())==BACKEND_TARGET_SHA and sha(str(old_static).encode())==STATIC_TARGET_SHA,'INSTALLED_TARGET_DRIFT')
    safe(ENV);st=ENV.lstat();need(st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o600,'ENV_PERMISSIONS')
    env=read(ENV,65536);need(sha(env)==ENV_BASELINE,'ENV_BASELINE_DRIFT')
    need(not any(line.strip().startswith(KEY+b'=') for line in env.splitlines()),'ENV_KEY_ALREADY_PRESENT')
    for rel,value in BASE['INSTALLED_HASHES'].items():need(digest(old_backend/rel)==value,'BACKEND_BASELINE_DRIFT')
    _,ok=BASE['passive_installation']();need(ok,'DEPENDENCY_METADATA')
    runtime(old_backend)
    previous_static=inventory(old_static)
    need((old_backend/'.venv-api').resolve(strict=True).is_dir(),'VENV_TARGET')
    venv=BASE['canonical'](old_backend/'.venv-api',API.parent)
    retained={name:value for name,value in previous_static.items() if name.startswith('assets/') and re.fullmatch(r'assets/[A-Za-z0-9._-]+\.(js|css|woff2)',name)}
    installed_env=env+(b'' if env.endswith(b'\n') else b'\n')+KEY+b'=/srv/powerflow/forecast-publications\n'
    resources=idle_capacity(sum(x['bytes'] for x in CONFIG['files'].values())+8*1024**2)
    before=production()
    record={'version':1,'previous_backend':str(old_backend),'previous_static':str(old_static),'new_backend':str(API),'new_static':str(STATIC),'original_env_sha256':sha(env),'installed_env_sha256':sha(installed_env),'previous_service_state':'active','production_fingerprint':before,'old_static_files':previous_static,'retained_assets':retained,'phase':'BACKUPS'}
    validate_rollback(record)
    CHANGED=True
    if not CONTROL.parent.exists():CONTROL.parent.mkdir(mode=0o700);os.chown(CONTROL.parent,0,0)
    CONTROL.mkdir(mode=0o700);os.chmod(CONTROL,0o700);os.chown(CONTROL,0,0);sync_dir(CONTROL.parent);sync_dir(CONTROL.parent.parent)
    create(CONTROL/'previous-api.env',env);state_save(record)
    PHASE='INSTALL'
    install_tree(API,'api/');install_tree(STATIC,'static/')
    os.symlink(str(venv),API/'.venv-api')
    for name,value in retained.items():
        dest=STATIC/name
        if dest.exists():need(digest(dest)==value,'ASSET_COLLISION')
        else:
            if not dest.parent.exists():dest.parent.mkdir(mode=0o755);os.chmod(dest.parent,0o755)
            raw=read(old_static/name,2_000_000);need(sha(raw)==value,'OLD_ASSET_DRIFT');create(dest,raw,0o644)
    need(production()==before,'PRODUCTION_DRIFT')
    idle_capacity(0);need(digest(ENV)==sha(env),'ENV_DRIFT')
    need(target(BACKEND_LINK,API.parent)==old_backend and target(STATIC_LINK,STATIC.parent)==old_static,'POINTER_DRIFT')
    PHASE='BACKEND_ACTIVATION';record['phase']=PHASE;state_save(record)
    atomic_file(ENV,installed_env,0o600);pointer(BACKEND_LINK,API)
    run(['/usr/bin/systemctl','restart',UNIT]);candidate_ready();runtime(API);missing_acceptance()
    need(production()==before,'PRODUCTION_DRIFT')
    idle_capacity(0)
    PHASE='STATIC_ACTIVATION';record['phase']=PHASE;state_save(record);pointer(STATIC_LINK,STATIC)
    html=probe(443,'/',200);need(sha(html)==CONFIG['files']['static/index.html']['sha256'],'HTTPS_INDEX_HASH')
    assets=re.findall(rb'(?:src|href)="(/assets/[A-Za-z0-9_-]+\.(?:js|css))"',html);need(0<len(assets)<=16,'ENTRY_ASSETS')
    for path in assets:
        raw=probe(443,path.decode(),200);need(sha(raw)==digest(STATIC/path.decode().lstrip('/')),'HTTPS_ASSET_HASH')
    probe(443,'/api/health',200);probe(443,'/api/ready',404);probe(443,'/.well-known/acme-challenge/preflight-probe',200)
    need(production()==before,'PRODUCTION_DRIFT')
    record['phase']='COMPLETE';state_save(record);PHASE='COMPLETE'
    return {'status':'DEPLOYED','phase':PHASE,'production_preserved':True,'missing_publication_verified':True,'resources_before':resources}

def rollback():
    global CHANGED,PHASE
    need(os.geteuid()==0,'ROOT_REQUIRED');safe(CONTROL)
    need(stat.S_IMODE(CONTROL.stat().st_mode)==0o700,'CONTROL_PERMISSIONS')
    record=json.loads(read(CONTROL/'state.json',131072));validate_rollback(record);need(record['version']==1 and record['new_backend']==str(API) and record['new_static']==str(STATIC),'ROLLBACK_RECORD')
    old_backend=Path(record['previous_backend']);old_static=Path(record['previous_static'])
    need(old_backend.parent==API.parent and old_static.parent==STATIC.parent and old_backend!=API and old_static!=STATIC,'ROLLBACK_TARGET_SCOPE')
    safe(old_backend);safe(old_static)
    need(record['previous_service_state']=='active','ROLLBACK_STATE')
    for rel,value in BASE['INSTALLED_HASHES'].items():need(digest(old_backend/rel)==value,'ROLLBACK_BACKEND_HASH')
    need(inventory(old_static)==record['old_static_files'],'ROLLBACK_STATIC_HASH')
    env=read(CONTROL/'previous-api.env',65536);need(sha(env)==record['original_env_sha256'],'ROLLBACK_ENV_HASH')
    need(digest(ENV) in (record['original_env_sha256'],record['installed_env_sha256']),'ROLLBACK_ENV_DRIFT')
    need(target(BACKEND_LINK,API.parent) in (API,old_backend) and target(STATIC_LINK,STATIC.parent) in (STATIC,old_static),'ROLLBACK_POINTER_DRIFT')
    need(production()==record['production_fingerprint'],'PRODUCTION_DRIFT');idle_capacity(0)
    PHASE='ROLLBACK';CHANGED=True
    pointer(STATIC_LINK,old_static);pointer(BACKEND_LINK,old_backend);atomic_file(ENV,env,0o600)
    run(['/usr/bin/systemctl','restart',UNIT]);candidate_ready();runtime(old_backend)
    need(target(BACKEND_LINK,API.parent)==old_backend and target(STATIC_LINK,STATIC.parent)==old_static and digest(ENV)==record['original_env_sha256'],'ROLLBACK_POSTCHECK')
    html=probe(443,'/',200);need(sha(html)==record['old_static_files']['index.html'],'ROLLBACK_HTTPS')
    need(production()==record['production_fingerprint'],'PRODUCTION_DRIFT')
    PHASE='ROLLED_BACK';record['phase']=PHASE;state_save(record)
    return {'status':'ROLLED_BACK','phase':PHASE,'production_preserved':True}

if __name__=='__main__':
    try:
        result=apply() if ACTION=='apply' else rollback() if ACTION=='rollback' else (_ for _ in ()).throw(Stop('ACTION_SCOPE'))
        print(json.dumps(result,sort_keys=True))
    except Exception as error:
        reason=str(error) if type(error)is Stop and re.fullmatch('[A-Z_]+',str(error)) else 'INSPECTION_OR_INSTALLATION_FAILED'
        print(json.dumps({'status':'PARTIAL' if CHANGED else 'BLOCKED','phase':PHASE,'reason':reason,'automatic_rollback':False}));raise SystemExit(1)
