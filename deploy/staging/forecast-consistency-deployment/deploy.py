"""Hash-bound proposed staging update/rollback. Executed only after approval.
CONFIG, BASE and ACTION are injected from independently verified retained bytes.
"""
import base64
import errno
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
LEGACY_CONTROL=Path('/var/lib/powerflow-staging/forecast-consistency-20261101-v1')
CONTROL=LEGACY_CONTROL
TRANSACTION_PARENT=Path('/var/lib/powerflow-staging/forecast-consistency-transactions')
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

def validate_missing_forecast(code,headers,raw):
    need(code==503,'STATUS_MISMATCH')
    try:payload=json.loads(raw)
    except Exception:raise Stop('BODY_MISMATCH') from None
    need(payload=={'detail':{'code':'FORECAST_WITHHELD'}},'BODY_MISMATCH')
    # HTTP field names and cache directives are case-insensitive. Match the
    # directive token, not a substring such as x-no-store or no-store-invalid.
    cache=','.join(value for key,value in headers.items() if key.lower()=='cache-control')
    need(any(token.strip().lower()=='no-store' for token in cache.split(',')),'CACHE_MISMATCH')

def missing_acceptance():
    need(not os.path.lexists(OVERLAY),'UNEXPECTED_PUBLICATION_ROOT')
    code,headers,raw=request_api('/forecast/next24')
    validate_missing_forecast(code,headers,raw)
    code,_,raw=request_api('/operations/summary');summary=json.loads(raw)
    need(code==200 and summary.get('forecast_status')=='MISSING_PUBLICATION' and summary.get('health') in ('Historical snapshot','Unavailable') and 'Historical' in summary.get('completeness_note',''),'HISTORICAL_SEPARATION')
    need(request_api('/admin/forecast/provenance')[0]==401,'ADMIN_AUTH_BOUNDARY')
    for path in ('/forecast/one-hour','/market/coverage','/pipeline/status','/models/summary'):need(request_api(path)[0]==200,'HISTORICAL_API')

def validate_inputs():
    need(set(CONFIG) in ({'files'},{'files','transaction_id'}) and len(CONFIG['files'])==63,'INPUT_SCOPE')
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
    if 'transaction_id' in CONFIG:
        validate_transaction_record(record);return
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
    need(digest(CONTROL/'previous-api.env')==sha(env),'BACKUP_ENV_VERIFY')
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
    runtime(old_backend);need(production()==before,'PRODUCTION_DRIFT')
    return activate(record,old_backend,old_static,env,installed_env,resources,before)

BACKEND_STEPS={'RECORD_SAVE','ENV_UPDATE','POINTER_SWITCH','RESTART','READINESS',
    'RUNTIME','FORECAST_CONTRACT','PRESERVATION','CAPACITY','RUNTIME_RECHECK',
    'PRESERVATION_RECHECK','RETAINED_RECHECK'}
ERROR_CAUSES={'PERMISSION_DENIED','MISSING_FILE','TIMEOUT','OS_ERROR','VALUE_ERROR',
    'MISSING_KEY','UNEXPECTED_EXCEPTION'}


def exception_cause(error):
    # Fixed labels only: never str(error), traceback, filename, body or stderr.
    if isinstance(error,TimeoutError):return 'TIMEOUT'
    if isinstance(error,OSError):
        if error.errno in (errno.EACCES,errno.EPERM):return 'PERMISSION_DENIED'
        if error.errno==errno.ENOENT:return 'MISSING_FILE'
        return 'OS_ERROR'
    if isinstance(error,ValueError):return 'VALUE_ERROR'
    if isinstance(error,KeyError):return 'MISSING_KEY'
    return 'UNEXPECTED_EXCEPTION'


def backend_step(label,function,*args):
    need(label in BACKEND_STEPS,'ACTION_SCOPE')
    try:return function(*args)
    except Stop:raise # Preserve existing explicit gate codes and fail-closed behavior.
    except Exception as error:raise Stop('BACKEND_'+label+'_'+exception_cause(error)) from None


def activate(record,old_backend,old_static,env,installed_env,resources,before,recheck=None):
    global PHASE
    if recheck is not None:recheck()
    PHASE='BACKEND_ACTIVATION';record['phase']=PHASE
    backend_step('RECORD_SAVE',state_save,record)
    backend_step('ENV_UPDATE',atomic_file,ENV,installed_env,0o600)
    backend_step('POINTER_SWITCH',pointer,BACKEND_LINK,API)
    backend_step('RESTART',run,['/usr/bin/systemctl','restart',UNIT])
    backend_step('READINESS',candidate_ready)
    backend_step('RUNTIME',runtime,API)
    backend_step('FORECAST_CONTRACT',missing_acceptance)
    need(backend_step('PRESERVATION',production)==before,'PRODUCTION_DRIFT')
    backend_step('CAPACITY',idle_capacity,0)
    backend_step('RUNTIME_RECHECK',runtime,API)
    need(backend_step('PRESERVATION_RECHECK',production)==before,'PRODUCTION_DRIFT')
    if recheck is not None:backend_step('RETAINED_RECHECK',recheck)
    PHASE='STATIC_ACTIVATION';record['phase']=PHASE;state_save(record);pointer(STATIC_LINK,STATIC)
    html=probe(443,'/',200);need(sha(html)==CONFIG['files']['static/index.html']['sha256'],'HTTPS_INDEX_HASH')
    assets=re.findall(rb'(?:src|href)="(/assets/[A-Za-z0-9_-]+\.(?:js|css))"',html);need(0<len(assets)<=16,'ENTRY_ASSETS')
    for path in assets:
        raw=probe(443,path.decode(),200);need(sha(raw)==digest(STATIC/path.decode().lstrip('/')),'HTTPS_ASSET_HASH')
    probe(443,'/api/health',200);probe(443,'/api/ready',404);probe(443,'/.well-known/acme-challenge/preflight-probe',200)
    need(production()==before,'PRODUCTION_DRIFT')
    record['phase']='COMPLETE';state_save(record);PHASE='COMPLETE'
    return {'status':'DEPLOYED','phase':PHASE,'production_preserved':True,'missing_publication_verified':True,'resources_before':resources}

def select_transaction():
    global CONTROL
    tx=CONFIG.get('transaction_id')
    need(type(tx)is str and re.fullmatch('[0-9a-f]{32}',tx) is not None,'TRANSACTION_ID')
    CONTROL=TRANSACTION_PARENT/tx


def validate_transaction_record(record):
    fields={'version','transaction_id','legacy_record_sha256','previous_backend','previous_static','new_backend','new_static','original_env_sha256','installed_env_sha256','previous_service_state','production_fingerprint','old_static_files','retained_assets','phase'}
    need(type(record)is dict and set(record)==fields and record['phase'] in {'BACKUPS','BACKEND_ACTIVATION','STATIC_ACTIVATION','COMPLETE','ROLLED_BACK'},'TRANSACTION_RECORD_SCHEMA')
    for key in ('old_static_files','retained_assets'):
        values=record[key];need(type(values)is dict and len(values)<=160,'TRANSACTION_INVENTORY')
        for name,value in values.items():need(type(name)is str and not Path(name).is_absolute() and '..' not in Path(name).parts and type(value)is str and re.fullmatch('[0-9a-f]{64}',value) is not None,'TRANSACTION_INVENTORY')
    need(record.get('transaction_id')==CONFIG['transaction_id'] and CONTROL==TRANSACTION_PARENT/CONFIG['transaction_id'],'TRANSACTION_RECORD_MISMATCH')
    for key,prefix in [('previous_backend','/opt/powerflow/releases'),('new_backend','/opt/powerflow/releases'),('previous_static','/var/www/powerflow-staging/releases'),('new_static','/var/www/powerflow-staging/releases')]:
        ROLLBACK['valid_target'](record[key],prefix)
    need(record['new_backend']==str(API) and record['new_static']==str(STATIC),'TRANSACTION_TARGET_MISMATCH')
    need(record['previous_backend']!=str(API) and record['previous_static']!=str(STATIC) and record['previous_service_state']=='active','TRANSACTION_ORIGINAL_STATE')
    for key in ('original_env_sha256','installed_env_sha256','production_fingerprint','legacy_record_sha256'):
        need(type(record[key])is str and re.fullmatch('[0-9a-f]{64}',record[key]) is not None,'TRANSACTION_HASH')
    need(record['original_env_sha256']==ENV_BASELINE and record['version']==1,'TRANSACTION_BASELINE')


def retained_tree(root,expected,venv=None):
    safe(root);expected_dirs={'.'}
    for name in expected:
        p=Path(name);need(not p.is_absolute() and '..' not in p.parts,'RETAINED_PATH_SCOPE')
        expected_dirs.update(str(q) for q in p.parents)
    seen=set();directories=set();count=0
    for parent,dirs,files in os.walk(root,followlinks=False):
        folder=Path(parent);safe(folder);directories.add(str(folder.relative_to(root)))
        st=folder.lstat();need(st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o755,'RETAINED_DIRECTORY_PERMISSIONS')
        need(len(dirs)+len(files)<=200,'RETAINED_SCAN_BOUND')
        for name in list(dirs)+list(files):
            path=folder/name;relative=str(path.relative_to(root));st=path.lstat()
            if relative=='.venv-api' and venv is not None:
                need(stat.S_ISLNK(st.st_mode) and st.st_uid==0 and path.resolve(strict=True)==venv,'RETAINED_VENV')
                if name in dirs:dirs.remove(name)
                continue
            need(not stat.S_ISLNK(st.st_mode),'RETAINED_SYMLINK')
            if name in dirs:
                need(relative in expected_dirs,'RETAINED_UNEXPECTED_DIRECTORY');continue
            need(relative in expected and stat.S_ISREG(st.st_mode),'RETAINED_UNEXPECTED_FILE')
            need(st.st_uid==0 and st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o644,'RETAINED_FILE_PERMISSIONS')
            need(digest(path)==expected[relative],'RETAINED_FILE_HASH');seen.add(relative);count+=1
            need(count<=256,'RETAINED_SCAN_BOUND')
    need(seen==set(expected) and directories==expected_dirs,'RETAINED_MISSING_FILE_OR_DIRECTORY')
    if venv is not None:need((root/'.venv-api').is_symlink(),'RETAINED_VENV')


def reactivate():
    global PHASE,CHANGED
    need(os.geteuid()==0,'ROOT_REQUIRED');validate_inputs();select_transaction()
    need(not os.path.lexists(CONTROL),'TRANSACTION_COLLISION')
    if os.path.lexists(TRANSACTION_PARENT):
        safe(TRANSACTION_PARENT);need(stat.S_ISDIR(TRANSACTION_PARENT.lstat().st_mode),'TRANSACTION_PARENT_PERMISSIONS');need(stat.S_IMODE(TRANSACTION_PARENT.stat().st_mode)==0o700,'TRANSACTION_PARENT_PERMISSIONS')
    else:safe(TRANSACTION_PARENT.parent)
    safe(LEGACY_CONTROL);need(stat.S_IMODE(LEGACY_CONTROL.stat().st_mode)==0o700,'LEGACY_CONTROL_PERMISSIONS')
    for file in ('state.json','previous-api.env'):
        st=(LEGACY_CONTROL/file).lstat();need(stat.S_ISREG(st.st_mode) and st.st_uid==st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o600,'LEGACY_FILE_PERMISSIONS')
    legacy_raw=read(LEGACY_CONTROL/'state.json',131072);legacy=json.loads(legacy_raw)
    need(legacy.get('phase')=='ROLLED_BACK' and legacy.get('version')==1 and legacy.get('new_backend')==str(API) and legacy.get('new_static')==str(STATIC) and legacy.get('previous_service_state')=='active','LEGACY_RECORD_MISMATCH')
    need(legacy.get('original_env_sha256')==ENV_BASELINE and digest(LEGACY_CONTROL/'previous-api.env')==ENV_BASELINE,'LEGACY_BACKUP_MISMATCH')
    old_backend=target(BACKEND_LINK,API.parent);old_static=target(STATIC_LINK,STATIC.parent)
    need(str(old_backend)==legacy['previous_backend'] and str(old_static)==legacy['previous_static'],'RESTORED_POINTER_MISMATCH')
    need(sha(str(old_backend).encode())==BACKEND_TARGET_SHA and sha(str(old_static).encode())==STATIC_TARGET_SHA,'INSTALLED_TARGET_DRIFT')
    safe(ENV);st=ENV.lstat();need(st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o600,'ENV_PERMISSIONS')
    env=read(ENV,65536);need(sha(env)==ENV_BASELINE,'ENV_BASELINE_DRIFT')
    need(not os.path.lexists(OVERLAY),'UNEXPECTED_PUBLICATION_ROOT')
    for rel,value in BASE['INSTALLED_HASHES'].items():need(digest(old_backend/rel)==value,'BACKEND_BASELINE_DRIFT')
    _,ok=BASE['passive_installation']();need(ok,'DEPENDENCY_METADATA');runtime(old_backend)
    previous_static=inventory(old_static);need(previous_static==legacy['old_static_files'],'LEGACY_STATIC_MISMATCH')
    retained={name:value for name,value in previous_static.items() if name.startswith('assets/') and re.fullmatch(r'assets/[A-Za-z0-9._-]+\.(js|css|woff2)',name)}
    need(retained==legacy['retained_assets'],'LEGACY_ASSET_MISMATCH')
    venv=BASE['canonical'](old_backend/'.venv-api',API.parent)
    expected_api={name[4:]:item['sha256'] for name,item in CONFIG['files'].items() if name.startswith('api/')}
    expected_static=dict(retained)
    for name,item in CONFIG['files'].items():
        if not name.startswith('static/'):continue
        relative=name[7:]
        need(relative not in expected_static or expected_static[relative]==item['sha256'],'ASSET_COLLISION')
        expected_static[relative]=item['sha256']
    def verify_retained():
        retained_tree(API,expected_api,venv);retained_tree(STATIC,expected_static)
        need(digest(LEGACY_CONTROL/'state.json')==sha(legacy_raw) and digest(LEGACY_CONTROL/'previous-api.env')==ENV_BASELINE,'LEGACY_RECORD_DRIFT')
    verify_retained()
    installed_env=env+(b'' if env.endswith(b'\n') else b'\n')+KEY+b'=/srv/powerflow/forecast-publications\n'
    resources=idle_capacity(1024**2);before=production()
    record={'version':1,'transaction_id':CONFIG['transaction_id'],'legacy_record_sha256':sha(legacy_raw),'previous_backend':str(old_backend),'previous_static':str(old_static),'new_backend':str(API),'new_static':str(STATIC),'original_env_sha256':sha(env),'installed_env_sha256':sha(installed_env),'previous_service_state':'active','production_fingerprint':before,'old_static_files':previous_static,'retained_assets':retained,'phase':'BACKUPS'}
    validate_rollback(record)
    CHANGED=True
    if not TRANSACTION_PARENT.exists():TRANSACTION_PARENT.mkdir(mode=0o700);os.chmod(TRANSACTION_PARENT,0o700);os.chown(TRANSACTION_PARENT,0,0)
    CONTROL.mkdir(mode=0o700);os.chmod(CONTROL,0o700);os.chown(CONTROL,0,0);sync_dir(CONTROL.parent);sync_dir(CONTROL.parent.parent)
    create(CONTROL/'previous-api.env',env);state_save(record)
    need(digest(CONTROL/'previous-api.env')==sha(env),'BACKUP_ENV_VERIFY')
    verify_retained();idle_capacity(0)
    need(digest(ENV)==sha(env),'ENV_DRIFT')
    need(target(BACKEND_LINK,API.parent)==old_backend and target(STATIC_LINK,STATIC.parent)==old_static,'POINTER_DRIFT')
    runtime(old_backend);need(production()==before,'PRODUCTION_DRIFT')
    return activate(record,old_backend,old_static,env,installed_env,resources,before,verify_retained)

def rollback():
    global CHANGED,PHASE
    need(os.geteuid()==0,'ROOT_REQUIRED')
    if 'transaction_id' in CONFIG:select_transaction()
    safe(CONTROL)
    need(stat.S_IMODE(CONTROL.stat().st_mode)==0o700,'CONTROL_PERMISSIONS')
    record=json.loads(read(CONTROL/'state.json',131072));validate_rollback(record);need(record.get('phase')!='ROLLED_BACK','ROLLBACK_ALREADY_COMPLETE');need(record['version']==1 and record['new_backend']==str(API) and record['new_static']==str(STATIC),'ROLLBACK_RECORD')
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

DIAGNOSTIC_STEPS={'SERVICE_METADATA','TRANSACTION','POINTERS','ENVIRONMENT','PERMISSIONS'}
SERVICE_PROPERTIES='Id,User,Group,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,StatusErrno,NRestarts'
DIAGNOSTIC_BOOLS={'candidate_active','candidate_running','unit_identity_match',
    'transaction_record_valid','transaction_rolled_back','backup_hash_valid',
    'backend_original','backend_release','static_original','env_original','env_installed',
    'env_safe','parent_permissions_safe'}
DIAGNOSTIC_INTS={'exec_main_code','exec_main_status','status_errno','restart_count'}
UNIT_RESULTS={'success','exit-code','signal','core-dump','timeout','watchdog',
    'start-limit-hit','resources','protocol','oom-kill','OTHER'}


def diagnose_backend():
    # No application imports/probes, journals, process environments or service action.
    need(os.geteuid()==0,'ROOT_REQUIRED');select_transaction()
    facts={key:None for key in DIAGNOSTIC_BOOLS|DIAGNOSTIC_INTS|{'last_unit_result'}}
    causes=[];record=None
    def observe(label,function):
        try:function()
        except Exception as error:causes.append(label+'_'+exception_cause(error))
    def service():
        command=['/usr/bin/systemctl','show',UNIT,'--property='+SERVICE_PROPERTIES]
        result=BASE['bounded_run'](command,timeout=8,limit=16384,grace=5)
        if result['failure']=='TIMEOUT':raise TimeoutError()
        if result['failure'] or result['returncode']!=0:raise ValueError()
        values={}
        for line in result['stdout'].decode('utf-8').splitlines():
            key,separator,value=line.partition('=')
            if not separator or key not in SERVICE_PROPERTIES.split(',') or key in values:raise ValueError()
            values[key]=value
        if set(values)!=set(SERVICE_PROPERTIES.split(',')) or values['Id']!=UNIT:raise ValueError()
        observed={'unit_identity_match':values['User']==values['Group']=='powerflow-api','candidate_active':values['ActiveState']=='active',
            'candidate_running':values['SubState']=='running',
            'last_unit_result':values['Result'] if values['Result'] in UNIT_RESULTS else 'OTHER'}
        for key,source in [('exec_main_code','ExecMainCode'),('exec_main_status','ExecMainStatus'),
                           ('status_errno','StatusErrno'),('restart_count','NRestarts')]:
            value=int(values[source])
            if not 0<=value<2**63:raise ValueError()
            observed[key]=value
        facts.update(observed)
    def transaction():
        nonlocal record
        safe(CONTROL)
        for directory in (TRANSACTION_PARENT,CONTROL):
            st=directory.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_gid!=0 or stat.S_IMODE(st.st_mode)!=0o700:raise ValueError()
        for path in (CONTROL/'state.json',CONTROL/'previous-api.env'):
            st=path.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or st.st_gid!=0 or stat.S_IMODE(st.st_mode)!=0o600:raise ValueError()
        item=json.loads(read(CONTROL/'state.json',131072));validate_transaction_record(item)
        facts['transaction_record_valid']=True;facts['transaction_rolled_back']=item['phase']=='ROLLED_BACK'
        facts['backup_hash_valid']=digest(CONTROL/'previous-api.env')==item['original_env_sha256']
        record=item
    def pointers():
        if record is None:raise KeyError()
        backend=target(BACKEND_LINK,API.parent);static=target(STATIC_LINK,STATIC.parent)
        facts.update(backend_original=str(backend)==record['previous_backend'],backend_release=backend==API,
                     static_original=str(static)==record['previous_static'])
    def environment():
        safe(ENV);st=ENV.lstat()
        facts['env_safe']=stat.S_ISREG(st.st_mode) and st.st_gid==0 and stat.S_IMODE(st.st_mode)==0o600
        if record is None:raise KeyError()
        value=digest(ENV);facts['env_original']=value==record['original_env_sha256'];facts['env_installed']=value==record['installed_env_sha256']
    def permissions():
        for path in (ENV.parent,BACKEND_LINK.parent,STATIC_LINK.parent,API,API/'src',TRANSACTION_PARENT,CONTROL):
            safe(path)
            if not stat.S_ISDIR(path.lstat().st_mode):raise ValueError()
        facts['parent_permissions_safe']=True
    for label,function in [('SERVICE_METADATA',service),('TRANSACTION',transaction),('POINTERS',pointers),
                           ('ENVIRONMENT',environment),('PERMISSIONS',permissions)]:observe(label,function)
    return {'status':'UNVERIFIED' if causes else 'DIAGNOSTIC_COMPLETE','phase':'DIAGNOSTIC',
        'facts':facts,'cause_codes':causes,'historical_failure_proven':False}

if __name__=='__main__':
    try:
        result=diagnose_backend() if ACTION=='diagnose-backend' else reactivate() if ACTION=='reactivate' else apply() if ACTION=='apply' else rollback() if ACTION=='rollback' else (_ for _ in ()).throw(Stop('ACTION_SCOPE'))
        print(json.dumps(result,sort_keys=True))
    except Exception as error:
        reason=str(error) if type(error)is Stop and re.fullmatch('[A-Z_]+',str(error)) else 'INSPECTION_OR_INSTALLATION_FAILED'
        print(json.dumps({'status':'PARTIAL' if CHANGED else 'BLOCKED','phase':PHASE,'reason':reason,'automatic_rollback':False}));raise SystemExit(1)
