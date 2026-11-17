#!/usr/bin/env python3
"""Review/approval required: fixed PowerFlow staging installation, activation, rollback."""
import argparse
import ctypes
import grp
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import ssl
import stat
import subprocess
import tarfile
import time
import threading
import sys
sys.path.insert(0,str(Path(__file__).parent))
from cgroup_bpf import attachments

ID='phase-staging-https-ready-20261026'
CONTROL=Path('/var/lib/powerflow-staging-install')/ID
INCOMING=Path('/home/ec2-user/powerflow-staging-incoming-'+ID+'-r2')
BACKEND=Path('/opt/powerflow/releases')/ID
STATIC=Path('/var/www/powerflow-staging/releases')/ID
CURRENT=Path('/opt/powerflow/react-current')
WWW=Path('/var/www/powerflow-staging/current')
PUBLISHED=Path('/srv/powerflow/published')
TEMP=Path('/srv/powerflow/.published-'+ID)
UNIT=Path('/etc/systemd/system/powerflow-candidate-api.service')
ENVFILE=Path('/etc/powerflow/react-api.env')
HTTPS=Path('/etc/nginx/conf.d/powerflow-staging-https.conf')
HTTP_SUPPORT=Path('/etc/nginx/conf.d/00-powerflow-staging-support.conf')
HEADERS=Path('/etc/nginx/powerflow/security-headers.conf')
PLACEHOLDER='85ad4c7ec303b638033831cb7ebfd5b73b669c80b249926c8e1446ba70124396'
SERVICE='powerflow-candidate-api.service'
KEEP=('powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service')
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','PYTHONDONTWRITEBYTECODE':'1','AWS_EC2_METADATA_DISABLED':'true'}


def need(value,code):
    if not value:raise RuntimeError(code)


def safe(path):
    for p in (path,*path.parents):need(not p.is_symlink(),'symlink_path')


def read(path):
    safe(path);need(path.is_file(),'regular_file_required');return path.read_bytes()


def sha(path):return hashlib.sha256(read(path)).hexdigest()


def run(label,args,seconds=15,uid=None,gid=None,env=None):
    def drop():os.setgroups([]);os.setgid(gid);os.setuid(uid)
    try:
        p=subprocess.run(args,capture_output=True,timeout=seconds,env=env or ENV,
                         preexec_fn=drop if uid is not None else None)
    except subprocess.TimeoutExpired as error:
        if CONTROL.is_dir():
            stamp=str(time.time_ns())
            (CONTROL/(label+'-'+stamp+'.timeout.stdout')).write_bytes(error.stdout or b'')
            (CONTROL/(label+'-'+stamp+'.timeout.stderr')).write_bytes(error.stderr or b'')
        raise RuntimeError(label.replace('-','_')+'_timeout') from None
    except OSError as error:
        if CONTROL.is_dir():
            evidence={'operation':'subprocess_spawn','label':label,'errno':error.errno,
                      'executable':args[0],'requested_uid':uid,'requested_gid':gid}
            create_file(CONTROL/(label+'-'+str(time.time_ns())+'.spawn-error.json'),json.dumps(evidence).encode(),0o600)
        raise RuntimeError(label.replace('-','_')+'_spawn_errno_'+str(error.errno)) from None
    if CONTROL.is_dir():
        # Exclusive output captures; never echo arbitrary subprocess output.
        stamp=str(time.time_ns())
        (CONTROL/(label+'-'+stamp+'.stdout')).write_bytes(p.stdout)
        (CONTROL/(label+'-'+stamp+'.stderr')).write_bytes(p.stderr)
    missing_candidate=(label=='candidate-state' and p.returncode in (1,4) and p.stdout.strip()==b'not-found')
    need(p.returncode==0 or missing_candidate,label.replace('-','_')+'_failed')
    return p.stdout


def identities():
    data=run('production-identities',['/usr/bin/systemctl','show',*KEEP,'--property=Id,MainPID,ActiveState,SubState'])
    need(data.count(b'ActiveState=active')==len(KEEP),'production_service_not_active')
    return data


def mkdir_new_or_safe(path,mode=0o755):
    safe(path)
    if path.exists():
        s=path.stat();need(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,'unsafe_existing_directory')
    else:
        path.mkdir(mode=mode)
        # mkdir's mode is filtered by umask077; apply the reviewed mode explicitly.
        # Existing directories are never chmodded by this helper.
        path.chmod(mode)


def create_file(path,data,mode):
    safe(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as h:h.write(data);h.flush();os.fsync(h.fileno())
    path.chmod(mode)


def archive_inventory(path,expected):
    with tarfile.open(path,'r:gz') as tar:
        seen=set()
        for member in tar:
            need(member.isfile() and member.name in expected and member.name not in seen,'unapproved_archive_member')
            need(member.size==expected[member.name]['bytes'],'archive_member_size')
            h=tar.extractfile(member);body=h.read(member.size+1)
            need(hashlib.sha256(body).hexdigest()==expected[member.name]['sha256'],'archive_member_hash')
            seen.add(member.name)
        need(seen==set(expected),'archive_inventory_missing')


def unpack(path,expected,destination):
    destination.mkdir(mode=0o700)
    with tarfile.open(path,'r:gz') as tar:
        for m in tar:
            need(m.isfile() and m.name in expected,'unapproved_archive_member')
            p=destination/m.name;need('..' not in Path(m.name).parts and not Path(m.name).is_absolute(),'archive_escape')
            p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            body=tar.extractfile(m).read();need(hashlib.sha256(body).hexdigest()==expected[m.name]['sha256'],'archive_member_hash')
            create_file(p,body,0o600)


def capacity(extra):
    mem=dict((k,int(v)*1024) for k,v in re.findall(r'(?m)^(MemAvailable):\s+(\d+) kB',Path('/proc/meminfo').read_text()))
    need(mem['MemAvailable']>=768*1024**2,'memory_below_768MiB')
    for p in ('/srv','/opt','/var'):
        s=os.statvfs(p);need(s.f_bavail*s.f_frsize>=extra+2*1024**3+1024**3,'disk_capacity_guard')


def check_runtime():
    facts=json.loads(run('base-interpreter',['/usr/bin/python3.14','-I','-S','-B','-c',
        'import sys,sysconfig,os,json,platform; print(json.dumps({"version":list(sys.version_info[:3]),"exe":os.path.realpath(sys.executable),"stdlib":sysconfig.get_path("stdlib"),"base":sys.base_prefix,"machine":platform.machine()}))']))
    need(facts['version']==[3,14,7] and facts['machine']=='x86_64','wrong_interpreter')
    for name in ('exe','stdlib','base'):
        p=Path(facts[name]);safe(p)
        need(not any(str(p)==x or str(p).startswith(x+'/') for x in ('/home','/root','/run/user')),'interpreter_hidden_by_ProtectHome')
        for ancestor in p.parents:need(ancestor.stat().st_mode&1,'interpreter_not_traversable')
        need(p.stat().st_mode&4,'interpreter_not_readable')


def assert_isolated_identity():
    u=pwd.getpwnam('powerflow-api');g=grp.getgrnam('powerflow-api')
    need(u.pw_uid!=0 and u.pw_gid==g.gr_gid and not g.gr_mem and
         u.pw_shell in ('/sbin/nologin','/usr/sbin/nologin') and u.pw_dir=='/nonexistent','unexpected_candidate_identity')
    need([p.pw_name for p in pwd.getpwall() if p.pw_gid==g.gr_gid]==['powerflow-api'],'shared_candidate_group')
    return u,g


def ownership_tree(path,gid=None):
    for p in (path,*path.rglob('*')):
        if p.is_symlink():
            # venv symlinks must target the approved non-home Python/base paths.
            real=p.resolve();need(str(real).startswith(('/usr/','/opt/powerflow/releases/'+ID+'/')),'venv_symlink_escape')
            continue
        os.chown(p,0,0 if gid is None else gid);p.chmod(0o755 if p.is_dir() or os.access(p,os.X_OK) else 0o644)


def certificate_baseline():
    path=Path('/var/lib/powerflow-staging-https-20261026/production-before.sha256')
    entries={}
    for line in read(path).decode().splitlines():
        match=re.fullmatch(r'([a-f0-9]{64})  (/.+)',line);need(match is not None,'production_baseline_format')
        need(match[2] not in entries,'duplicate_baseline');entries[match[2]]=match[1]
    need(set(entries)=={'/etc/nginx/conf.d/powerflow.conf','/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem'},'production_baseline_paths')
    for p,h in entries.items():need(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,'production_baseline_hash')


def preflight(bundle,publisher):
    need(os.geteuid()==0,'root_required');need(CONTROL.is_dir() and not (CONTROL/'install.started').exists(),'install_already_attempted_or_control_missing')
    need(bundle['release_id']==ID,'release_id')
    for item in bundle['artifacts']:
        path=INCOMING/item['name'];need(sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],'incoming_hash_mismatch')
    publisher.validate_sources(bundle['publication_plan'])
    need(not os.path.lexists('/srv/powerflow'),'publication_parent_already_exists_requires_review')
    for path in (PUBLISHED,TEMP,BACKEND,STATIC,CURRENT,WWW,UNIT,ENVFILE,HTTP_SUPPORT,HEADERS):
        # CURRENT/WWW are expected absent for this first candidate installation.
        need(not os.path.lexists(path),'installation_destination_exists');safe(path)
    for x in ('powerflow-api',):
        try:pwd.getpwnam(x)
        except KeyError:pass
        else:raise RuntimeError('candidate_user_exists_requires_review')
        try:grp.getgrnam(x)
        except KeyError:pass
        else:raise RuntimeError('candidate_group_exists_requires_review')
    need(sha(HTTPS)==PLACEHOLDER,'staging_placeholder_changed')
    certificate_baseline()
    for path,h in bundle['preserved_hashes'].items():
        # Public production Certbot certificate intentionally follows its managed symlink.
        need(hashlib.sha256(Path(path).read_bytes()).hexdigest()==h,'production_or_ACME_baseline_changed')
    for tool in ('/usr/sbin/groupadd','/usr/sbin/useradd','/usr/sbin/nginx','/usr/bin/systemctl','/usr/bin/systemd-analyze','/usr/bin/python3.14','/usr/bin/openssl'):
        need(os.access(tool,os.X_OK),'missing_required_tool')
    attachments(Path('/sys/fs/cgroup')) # Query-only capability gate, before any installation writes.
    ss=next((p for p in ('/usr/sbin/ss','/usr/bin/ss') if os.access(p,os.X_OK)),None);need(ss is not None,'ss_missing')
    need(not run('port8010',[ss,'-H','-ltn','sport = :8010']).strip(),'candidate_port_busy')
    state=run('candidate-state',['/usr/bin/systemctl','show',SERVICE,'--property=LoadState','--value']).strip()
    need(state in (b'not-found',b''),'candidate_unit_already_loaded')
    check_runtime();capacity(bundle['disk_budget_bytes'])
    archive_inventory(INCOMING/'release.tar.gz',bundle['release_archive_inventory'])
    archive_inventory(INCOMING/'wheels.tar.gz',bundle['wheel_archive_inventory'])
    need(hasattr(ctypes.CDLL(None),'renameat2'),'renameat2_required')


def install(bundle,publisher):
    preflight(bundle,publisher)
    # All source/hash/destination/tool/capacity checks precede first server write.
    create_file(CONTROL/'install.started',b'One installation attempt.\n',0o600)
    before=identities();create_file(CONTROL/'production-services.before',before,0o600)
    for item in bundle['artifacts']:
        if not (CONTROL/item['name']).exists():create_file(CONTROL/item['name'],read(INCOMING/item['name']),0o600)
        need(sha(CONTROL/item['name'])==item['sha256'],'private_control_artifact_changed')
    run('create-group',['/usr/sbin/groupadd','--system','powerflow-api'])
    run('create-user',['/usr/sbin/useradd','--system','--no-log-init','--no-create-home','--no-user-group','--gid','powerflow-api','--home-dir','/nonexistent','--shell','/sbin/nologin','powerflow-api'])
    u,g=assert_isolated_identity()
    mkdir_new_or_safe(Path('/srv/powerflow'),0o750);os.chown('/srv/powerflow',0,g.gr_gid)
    publication=publisher.publish(bundle['publication_plan'],PUBLISHED,TEMP,g.gr_gid,bundle['publication_provenance'])
    create_file(CONTROL/'publication-result.json',json.dumps(publication,indent=2).encode(),0o600)
    unpack(CONTROL/'release.tar.gz',bundle['release_archive_inventory'],CONTROL/'release')
    unpack(CONTROL/'wheels.tar.gz',bundle['wheel_archive_inventory'],CONTROL/'wheels')
    for p in (Path('/opt/powerflow'),Path('/opt/powerflow/releases'),Path('/var/www/powerflow-staging'),Path('/var/www/powerflow-staging/releases')):mkdir_new_or_safe(p)
    shutil.copytree(CONTROL/'release/api',BACKEND);shutil.copytree(CONTROL/'release/static',STATIC)
    ownership_tree(BACKEND);ownership_tree(STATIC)
    run('create-isolated-venv',['/usr/bin/python3.14','-I','-S','-B','-m','venv',str(BACKEND/'.venv-api')],seconds=40)
    python=str(BACKEND/'.venv-api/bin/python')
    install_env={**ENV,'HOME':str(CONTROL),'PIP_CONFIG_FILE':'/dev/null','PIP_NO_CACHE_DIR':'1'}
    run('offline-api-install',[python,'-m','pip','--isolated','--disable-pip-version-check','install','--no-index','--find-links='+str(CONTROL/'wheels'),'--only-binary=:all:','--no-cache-dir','-r',str(BACKEND/'requirements/api.lock')],seconds=180,env=install_env)
    run('pip-check',[python,'-m','pip','--isolated','check'],seconds=30)
    ownership_tree(BACKEND)
    # Only the probe creates synthetic data in its own temporary directory; no published-data writes.
    create_file(BACKEND/'linux-regression.py',read(CONTROL/'linux-regression-unittest.py').replace(b"'/candidate/src'",repr(str(BACKEND/'src')).encode()).replace(b"'/candidate/requirements/api.lock'",repr(str(BACKEND/'requirements/api.lock')).encode()),0o644)
    run('candidate-offline-regressions',[python,'-B',str(BACKEND/'linux-regression.py')],seconds=120,uid=u.pw_uid,gid=g.gr_gid,env={**ENV,'HOME':'/nonexistent','PYTHONPATH':str(BACKEND/'src')})
    run('published-access-as-candidate',[python,'-I','-S','-B','-c',
        'import os,pathlib; root=pathlib.Path("/srv/powerflow/published"); files=[p for p in root.rglob("*") if p.is_file()]; assert len(files)==14; assert all(os.access(p,os.R_OK) and not os.access(p,os.W_OK) for p in [root,*files])'],seconds=15,uid=u.pw_uid,gid=g.gr_gid)
    CURRENT.symlink_to(BACKEND);WWW.symlink_to(STATIC)
    mkdir_new_or_safe(Path('/etc/powerflow'),0o700)
    create_file(ENVFILE,read(CONTROL/'release/proposals/api.env.example'),0o600)
    create_file(UNIT,read(CONTROL/'release/proposals/powerflow-candidate-api.service'),0o644)
    run('systemd-syntax',['/usr/bin/systemd-analyze','verify',str(UNIT)],seconds=20)
    need(identities()==before,'production_service_identity_changed')
    for p,h in bundle['preserved_hashes'].items():need(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,'preserved_hash_changed')
    create_file(CONTROL/'installation-measurements.json',json.dumps({'venv_bytes':sum(p.stat().st_size for p in (BACKEND/'.venv-api').rglob('*') if p.is_file() and not p.is_symlink()),'publication_bytes':publication['total_file_bytes'],'interpreter':'/usr/bin/python3.14','port':8010}).encode(),0o600)
    create_file(CONTROL/'installed.ok',b'Candidate installed, NOT started or enabled.\n',0o600)
    return {'publication':publication,'candidate_started':False,'next':'separate activate action approval'}


def health():
    for path in ('/health','/ready'):
        c=http.client.HTTPConnection('127.0.0.1',8010,timeout=2)
        try:
            c.request('GET',path,headers={'Host':'127.0.0.1'});r=c.getresponse();body=r.read(4096)
            need(r.status==200,'candidate_health_or_ready_failed')
        finally:c.close()


def limits_and_bpf():
    props=dict(line.split('=',1) for line in run('effective-unit-properties',['/usr/bin/systemctl','show',SERVICE,'--property=User,Group,MainPID,ActiveState,SubState,MemoryHigh,MemoryMax,MemorySwapMax,NRestarts,ControlGroup,IPAddressDeny,ProtectHome,ProtectSystem,NoNewPrivileges,PrivateTmp,PrivateDevices,CapabilityBoundingSet']).decode().splitlines() if '=' in line)
    need(props.get('ActiveState')=='active' and props.get('NRestarts')=='0','candidate_state_or_restarts')
    need(props.get('User')=='powerflow-api' and props.get('Group')=='powerflow-api','candidate_user_mismatch')
    need(props.get('MemoryHigh')==str(384*1024**2) and props.get('MemoryMax')==str(512*1024**2) and props.get('MemorySwapMax')=='0','unit_resource_limits')
    need(props.get('ProtectHome') in ('yes','true'),'ProtectHome_not_active')
    need(props.get('ProtectSystem')=='strict' and props.get('CapabilityBoundingSet')=='','effective_sandbox_mismatch')
    for name in ('NoNewPrivileges','PrivateTmp','PrivateDevices'):
        need(props.get(name) in ('yes','true'),'effective_sandbox_mismatch')
    for address in ('169.254.169.254','fd00:ec2::254'):need(address in props.get('IPAddressDeny',''),'IMDS_deny_configuration_missing')
    cg=props.get('ControlGroup');need(cg=='/system.slice/'+SERVICE,'unexpected_candidate_cgroup')
    base=Path('/sys/fs/cgroup')/cg.lstrip('/')
    for name,value in (('memory.high',384*1024**2),('memory.max',512*1024**2),('memory.swap.max',0)):
        need(read(base/name).decode().strip()==str(value),'effective_cgroup_limit_mismatch')
    ss=next((p for p in ('/usr/sbin/ss','/usr/bin/ss') if os.access(p,os.X_OK)),None);need(ss is not None,'ss_missing')
    listeners=run('candidate-listener',[ss,'-H','-ltnp','sport = :8010']).decode().splitlines()
    need(len(listeners)==1 and '127.0.0.1:8010' in listeners[0] and ('pid='+props.get('MainPID','MISSING')+',') in listeners[0],'candidate_listener_identity')
    programs=attachments(base)
    need(programs['ingress'] and programs['egress'],'IMDS_bpf_attachment_missing')
    create_file(CONTROL/('bpf-evidence-'+str(time.time_ns())+'.json'),json.dumps(programs).encode(),0o600)
    # Attachment + configured deny proof; not formal bytecode or live IMDS testing.
    return props


def preservation(bundle,before):
    certificate_baseline()
    need(identities()==before,'production_service_identity_changed')
    for p,h in bundle['preserved_hashes'].items():need(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,'production_or_ACME_hash_changed')


def verify_installed(bundle):
    u,g=assert_isolated_identity()
    for name,item in bundle['release_archive_inventory'].items():
        if name.startswith('api/'):
            path=BACKEND/name[4:]
        elif name.startswith('static/'):
            path=STATIC/name[7:]
        else:continue
        need(sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],'installed_release_hash_changed')
    expected={x['relative_path'] for x in bundle['publication_plan']}|{'_publication.json'}
    actual={str(p.relative_to(PUBLISHED)) for p in PUBLISHED.rglob('*') if p.is_file()}
    need(actual==expected,'publication_inventory_changed')
    for path in (PUBLISHED,*PUBLISHED.rglob('*')):
        safe(path);s=path.stat()
        need(s.st_uid==0 and s.st_gid==g.gr_gid and (s.st_mode&0o777)==(0o750 if path.is_dir() else 0o640),'publication_permissions_changed')
    for item in bundle['publication_plan']:need(sha(PUBLISHED/item['relative_path'])==item['sha256'],'published_hash_changed')
    saved=json.loads(read(CONTROL/'publication-result.json'))
    need(sha(PUBLISHED/'_publication.json')==saved['publication_manifest_sha256'],'publication_provenance_changed')


def activate(bundle):
    need((CONTROL/'installed.ok').is_file() and not (CONTROL/'activation.started').exists(),'install_missing_or_activation_attempted')
    verify_installed(bundle);capacity(0)
    need(sha(HTTPS)==PLACEHOLDER,'placeholder_changed')
    need(sha(UNIT)==bundle['candidate_unit_sha256'],'candidate_unit_changed')
    need(sha(ENVFILE)==bundle['candidate_env_sha256'],'candidate_env_changed')
    before=identities();preservation(bundle,before)
    run('certificate-hostname',['/usr/bin/openssl','x509','-in','/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/cert.pem','-noout','-checkhost','staging.powerflowenergy.dev'])
    run('certificate-expiry',['/usr/bin/openssl','x509','-in','/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/cert.pem','-noout','-checkend','2592000'])
    run('certificate-chain',['/usr/bin/openssl','verify','-CAfile','/etc/pki/tls/certs/ca-bundle.crt','-untrusted','/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/chain.pem','/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/cert.pem'])
    public=run('certificate-public-metadata',['/usr/bin/openssl','x509','-in','/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/cert.pem','-noout','-dates','-ext','subjectAltName']).decode()
    need(re.findall(r'DNS:([^,\s]+)',public)==['staging.powerflowenergy.dev'],'certificate_SAN_mismatch')
    need('notAfter=Jan 24 07:38:12 2027 GMT' in public,'certificate_expiry_changed')
    # Existing corrected strict include reviewer is loaded from the verified bundle.
    spec=importlib.util.spec_from_file_location('review',CONTROL/'activate-staging-https.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    hashes,_=module.review_config(True)
    for p in hashes:
        text=Path(p).read_bytes()
        need(not re.search(rb'log_format\s+powerflow_safe\b|zone=powerflow_api:',text),'proxy_support_names_conflict')
    need(not HTTP_SUPPORT.exists() and not HEADERS.exists(),'proxy_support_destination_conflict')
    run('nginx-baseline',['/usr/sbin/nginx','-t'])
    create_file(CONTROL/'activation.started',b'One activation attempt.\n',0o600)
    create_file(CONTROL/'previous-https.conf',read(HTTPS),0o600)
    run('daemon-reload',['/usr/bin/systemctl','daemon-reload'])
    # Parent process keeps a resource watcher alive during cold startup/verification.
    guard_stop=threading.Event();guard_failure=[]
    def watch():
        while not guard_stop.wait(1):
            try:
                available=int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text())[1])*1024
                need(available>=256*1024**2,'candidate_low_host_memory')
                need(identities()==before,'production_identity_changed_during_candidate')
                restarts=run('guard-restarts',['/usr/bin/systemctl','show',SERVICE,'--property=NRestarts','--value']).strip()
                need(restarts==b'0','candidate_restart_detected')
                event=Path('/sys/fs/cgroup/system.slice')/SERVICE/'memory.events'
                if event.is_file():
                    counters=dict(line.split() for line in event.read_text().splitlines())
                    need(int(counters.get('oom_kill','0'))==0,'candidate_oom_detected')
            except Exception:
                guard_failure.append('candidate_safety_guard_failed')
                try:run('guard-stop-candidate',['/usr/bin/systemctl','stop',SERVICE],seconds=35)
                except Exception:pass
                return
    guard=threading.Thread(target=watch,daemon=True);guard.start()
    try:
        run('start-candidate',['/usr/bin/systemctl','start',SERVICE],seconds=35)
    except Exception:
        guard_stop.set();guard.join(timeout=2);raise
    need(not guard_failure,'candidate_safety_guard_failed')
    ready=False
    for _ in range(20):
        try:health();ready=True;break
        except (RuntimeError,OSError):time.sleep(1)
    need(ready,'candidate_not_ready')
    props=limits_and_bpf()
    for path,expected in (('/market/coverage',200),('/models/summary',200),('/anomalies/summary',200),('/forecast/one-hour',200),('/forecast/next24',404),('/admin/operations',401),('/admin/forecast/provenance',401),('/admin/models/linear-feature-influence',401),('/admin/monitoring/forecast-vintages',401),('/admin/monitoring/exogenous-readiness',401),('/monitoring/forecast-vintages',401),('/monitoring/exogenous-readiness',401)):
        connection=http.client.HTTPConnection('127.0.0.1',8010,timeout=5)
        try:
            connection.request('GET',path);response=connection.getresponse();response.read(4096);need(response.status==expected,'candidate_API_smoke_failed')
        finally:connection.close()
    need(not guard_failure,'candidate_safety_guard_failed')
    # A low-overhead60-second acceptance watch; no load tests or service retries.
    for _ in range(12):
        mem=int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text())[1])*1024
        if mem<256*1024**2:
            run('stop-candidate-low-memory',['/usr/bin/systemctl','stop',SERVICE],seconds=35)
            raise RuntimeError('candidate_stopped_low_host_memory')
        need(run('candidate-restarts',['/usr/bin/systemctl','show',SERVICE,'--property=NRestarts','--value']).strip()==b'0','candidate_restart_detected')
        preservation(bundle,before);time.sleep(5)
    mkdir_new_or_safe(Path('/etc/nginx/powerflow'),0o755)
    create_file(HEADERS,read(CONTROL/'release/proposals/security-headers.conf'),0o644)
    create_file(HTTP_SUPPORT,read(CONTROL/'staging-support.conf'),0o644)
    # Exclusive saved placeholder means only this staging vhost is replaced.
    data=read(CONTROL/'release/proposals/staging.powerflowenergy.dev.conf')
    need(sha(HTTPS)==PLACEHOLDER,'placeholder_drift_before_replace')
    tmp=HTTPS.with_name('powerflow-staging-https.conf.'+ID+'.new')
    create_file(tmp,data,0o644);os.replace(tmp,HTTPS)
    run('nginx-installed',['/usr/sbin/nginx','-t'])
    module.review_config(True)
    preservation(bundle,before);health();limits_and_bpf()
    run('reload-staging-routing',['/usr/bin/systemctl','reload','nginx'],seconds=15)
    # Real CA/hostname verification, no -k and no OAuth query logging.
    context=ssl.create_default_context(cafile='/etc/pki/tls/certs/ca-bundle.crt')
    for path,expected in (('/',200),('/analytics',200),('/forecasting',200),('/anomalies',200),('/models',200),('/pipeline',200),('/profile',200),('/auth/callback',200),('/api/health',200),('/api/ready',404),('/.well-known/acme-challenge/preflight-probe',200)):
        raw=socket.create_connection(('127.0.0.1',443),timeout=3)
        sock=context.wrap_socket(raw,server_hostname='staging.powerflowenergy.dev')
        c=http.client.HTTPConnection('staging.powerflowenergy.dev',timeout=3);c.sock=sock
        try:
            c.request('GET',path);r=c.getresponse();body=r.read(4096);need(r.status==expected,'staging_HTTPS_response')
            if path.endswith('/preflight-probe'):need(body==b'powerflow-staging-acme-preflight\n','HTTPS_ACME_body')
        finally:c.close()
    connection=http.client.HTTPConnection('127.0.0.1',80,timeout=3)
    try:
        connection.request('GET','/.well-known/acme-challenge/preflight-probe',headers={'Host':'staging.powerflowenergy.dev'})
        response=connection.getresponse();need(response.status==200 and response.read(4096)==b'powerflow-staging-acme-preflight\n','HTTP_ACME_response')
    finally:connection.close()
    preservation(bundle,before)
    need(not guard_failure,'candidate_safety_guard_failed')
    guard_stop.set();guard.join(timeout=2)
    create_file(CONTROL/'activated.ok',b'Staging routing active; real-account browser acceptance required.\n',0o600)
    return {'candidate_properties':props,'nginx_reload_count':1,'real_account_acceptance':'required'}


def rollback(bundle):
    need(CONTROL.is_dir() and not (CONTROL/'rollback.started').exists(),'rollback_already_attempted_or_state_missing')
    before=identities();create_file(CONTROL/'rollback.started',b'Explicit approved rollback.\n',0o600)
    if (CONTROL/'previous-https.conf').exists():
        need(sha(CONTROL/'previous-https.conf')==PLACEHOLDER,'saved_placeholder_changed')
        need(sha(HTTPS) in (PLACEHOLDER,bundle['candidate_nginx_sha256']),'staging_config_changed')
        if sha(HTTPS)!=PLACEHOLDER:
            shutil.copyfile(HTTPS,CONTROL/'disabled-staging-https.conf')
            tmp=HTTPS.with_name('powerflow-staging-https.conf.'+ID+'.rollback')
            create_file(tmp,read(CONTROL/'previous-https.conf'),0o644);os.replace(tmp,HTTPS)
            run('rollback-nginx-test',['/usr/sbin/nginx','-t'])
            run('rollback-nginx-reload',['/usr/bin/systemctl','reload','nginx'],seconds=15)
    if UNIT.exists():
        loaded=run('candidate-state',['/usr/bin/systemctl','show',SERVICE,'--property=LoadState','--value']).strip()
        if loaded==b'loaded':run('stop-candidate',['/usr/bin/systemctl','stop',SERVICE],seconds=35)
    preservation(bundle,before)
    # Preserve identity, files, environment, unit, support includes, publication and audit.
    return {'candidate_stopped':True,'publication_retained':True,'placeholder_restored':(CONTROL/'previous-https.conf').exists(),'cleanup':'separate approval'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('install','activate','rollback'));args=parser.parse_args()
    os.umask(0o077);report={'action':args.action,'status':'failed','automatic_retry':False,'automatic_rollback':False}
    try:
        safe(CONTROL);control_stat=CONTROL.stat()
        need(os.geteuid()==0 and control_stat.st_uid==0 and stat.S_IMODE(control_stat.st_mode)==0o700,'unsafe_private_control')
        bundle=json.loads(read(Path(__file__).parent/'bundle.json'))
        for name,expected in bundle['control_hashes'].items():need(sha(Path(__file__).parent/name)==expected,'control_payload_hash')
        for item in bundle['artifacts']:
            need(sha(CONTROL/item['name'])==item['sha256'],'private_artifact_hash_changed')
        spec=importlib.util.spec_from_file_location('publisher',Path(__file__).parent/'publisher.py');publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
        report['result']=install(bundle,publisher) if args.action=='install' else activate(bundle) if args.action=='activate' else rollback(bundle)
        report['status']='passed'
    except Exception as error:
        report['error_type']=type(error).__name__
        report['safe_error']=str(error) if isinstance(error,RuntimeError) and re.fullmatch('[A-Za-z0-9_]+',str(error)) else 'details_in_private_capture'
    print(json.dumps(report,indent=2));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
