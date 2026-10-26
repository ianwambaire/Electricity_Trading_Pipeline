#!/usr/bin/env python3
"""Fixed-path read-only staging inspection. No Nginx tests, HTTP, writes or service changes."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess

UNITS = ('nginx.service', 'powerflow-api.service', 'powerflow-streamlit.service',
         'powerflow-prefect-worker.service', 'powerflow-prefect-server.service',
         'postgresql.service', 'powerflow-candidate-api.service')
PROPERTIES = 'Id,LoadState,ActiveState,SubState,MainPID,User,Group,MemoryCurrent,MemoryHigh,MemoryMax,MemorySwapMax,ControlGroup,NRestarts'
ROOT = '/home/ec2-user/Electricity_Trading_Pipeline'
CERT = '/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev'
STATE = '/var/lib/powerflow-staging-https-20261026'
RELEASE = 'phase-staging-https-ready-20261026'
PATHS = ('/opt', '/opt/powerflow', '/opt/powerflow/releases',
         '/opt/powerflow/releases/' + RELEASE, '/opt/powerflow/react-current',
         '/var/www', '/var/www/powerflow-staging', '/var/www/powerflow-staging/releases',
         '/var/www/powerflow-staging/releases/' + RELEASE, '/var/www/powerflow-staging/current',
         '/srv', '/srv/powerflow', '/srv/powerflow/published', '/etc/powerflow',
         '/etc/powerflow/react-api.env', '/var/lib/powerflow-staging',
         '/var/lib/powerflow-staging/' + RELEASE,
         '/etc/systemd/system/powerflow-candidate-api.service',
         '/etc/nginx/powerflow', '/etc/nginx/powerflow/security-headers.conf',
         '/etc/nginx/conf.d/powerflow-staging.conf', '/var/www/powerflow-staging-acme')
CONFIGS = ('/etc/nginx/nginx.conf', '/etc/nginx/conf.d/powerflow.conf',
           '/etc/nginx/conf.d/powerflow-staging-acme.conf',
           '/etc/nginx/conf.d/powerflow-staging-https.conf',
           '/etc/nginx/snippets/powerflow-api-location.conf',
           '/etc/letsencrypt/options-ssl-nginx.conf')
TOOLS = ('/usr/bin/timeout', '/usr/sbin/nginx', '/usr/bin/openssl',
         '/usr/bin/systemctl', '/usr/bin/systemd-analyze', '/usr/sbin/ss',
         '/usr/bin/ss', '/usr/bin/python3', ROOT + '/.venv-prod/bin/python')


def run(args):
    p = subprocess.run(args, capture_output=True, timeout=8,
                       env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin', 'LANG':'C',
                            'PYTHONDONTWRITEBYTECODE':'1'})
    text = p.stdout.decode('utf-8', errors='strict')
    expected_missing = (args == ['/usr/bin/systemctl','show','powerflow-candidate-api.service',
                                  '--property='+PROPERTIES] and
                        p.returncode in (1,4) and 'LoadState=not-found' in text.splitlines())
    if p.returncode and not expected_missing: raise RuntimeError('subcommand_failed')
    return text


def metadata(path):
    try: s = os.lstat(path)
    except FileNotFoundError: return {'exists':False}
    return {'exists':True, 'uid':s.st_uid, 'gid':s.st_gid,
            'mode':oct(stat.S_IMODE(s.st_mode)), 'bytes':s.st_size,
            'symlink':stat.S_ISLNK(s.st_mode), 'regular':stat.S_ISREG(s.st_mode),
            'directory':stat.S_ISDIR(s.st_mode)}


def read(path, limit=262144):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as h:
        s = os.fstat(h.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_size > limit: raise ValueError('unsafe_or_large_file')
        b = h.read(limit+1)
        if len(b) > limit: raise ValueError('file_limit')
        return b


def digest(path): return hashlib.sha256(read(path)).hexdigest()


def config(path):
    b = read(path)
    # Output fixed operational facts only. Never emit directive text/values.
    lines = b.decode().splitlines()
    return {'sha256':hashlib.sha256(b).hexdigest(), 'bytes':len(b),
            'include_count':sum(bool(re.match(r'\s*include\s', x)) for x in lines),
            'staging_name_present':b'server_name staging.powerflowenergy.dev;' in b,
            'acme_location_present':b'/.well-known/acme-challenge/' in b,
            'isolated_staging_certificate_reference':(CERT+'/fullchain.pem').encode() in b,
            'safe_log_format_definition':bool(re.search(rb'\blog_format\s+powerflow_safe\b',b)),
            'api_rate_zone_definition':bool(re.search(rb'\blimit_req_zone\s+[^;]*zone=powerflow_api:',b))}


def main():
    result = {'scope':'fixed-path read-only preflight', 'checks':{}, 'errors':[],
              'limitations':['No nginx -t/-T, HTTP requests or dynamic include expansion',
                'Memory/controller presence does not prove candidate cgroup limits or BPF enforcement',
                'No dependency installation, provider calls, package import or data publication',
                'No runtime argv, environments, secrets, logs or private keys inspected']}
    def collect(name, operation):
        try: result['checks'][name] = operation()
        except Exception as e: result['errors'].append({'check':name,'exception_type':type(e).__name__})
    collect('sudo_effective_uid', lambda: os.geteuid())
    if os.geteuid() != 0:
        result['errors'].append({'check':'noninteractive_sudo','exception_type':'RootRequired'})
        print(json.dumps(result)); return 1
    def memory():
        values = {m[1]:int(m[2])*1024 for m in re.finditer(r'(?m)^(MemTotal|MemAvailable|SwapTotal|SwapFree):\s+(\d+) kB',Path('/proc/meminfo').read_text())}
        values['swap_used_bytes'] = values['SwapTotal']-values['SwapFree']
        values['meets_768MiB_start_threshold'] = values['MemAvailable'] >= 768*1024**2
        return values
    collect('memory', memory)
    def disk():
        s = os.statvfs('/')
        return {'available_bytes':s.f_bavail*s.f_frsize, 'total_bytes':s.f_blocks*s.f_frsize,
                'minimum_reserve_bytes':2*1024**3, 'post_install_pass':'not_measured'}
    collect('root_filesystem', disk)
    def filesystems():
        result = {}
        for path in ('/opt', '/srv', '/var', '/home/ec2-user'):
            fs = os.statvfs(path)
            result[path] = {'device':os.stat(path).st_dev,
                            'available_bytes':fs.f_bavail*fs.f_frsize}
        return result
    collect('installation_filesystems', filesystems)
    collect('paths', lambda:{str(p):metadata(p) for p in sorted(
        {Path(p) for p in PATHS} | {parent for p in PATHS for parent in Path(p).parents}, key=str)})
    collect('tools', lambda:{p:{**metadata(p),'executable':os.access(p,os.X_OK)} for p in TOOLS})
    def user():
        try: u = pwd.getpwnam('powerflow-api')
        except KeyError: return {'exists':False}
        return {'exists':True,'uid':u.pw_uid,'gid':u.pw_gid,
                'nonlogin_shell':u.pw_shell in ('/sbin/nologin','/usr/sbin/nologin','/bin/false')}
    collect('candidate_user', user)
    for unit in UNITS:
        collect(unit, lambda unit=unit:dict(line.split('=',1) for line in run(
            ['/usr/bin/systemctl','show',unit,'--property='+PROPERTIES]).splitlines() if '=' in line))
    def listeners():
        ss = next(p for p in ('/usr/sbin/ss','/usr/bin/ss') if os.access(p,os.X_OK))
        out = run([ss,'-H','-ltnp','( sport = :8000 or sport = :8501 or sport = :8010 )'])
        records=[]
        for line in out.splitlines():
            fields=line.split()
            if len(fields)<5: raise ValueError('listener_format')
            address=fields[3]
            port=address.rsplit(':',1)[-1]
            if port not in ('8000','8501','8010'): raise ValueError('unexpected_listener')
            records.append({'local_address':address,'pids':[int(x) for x in re.findall(r'pid=(\d+)',line)]})
        return records
    collect('listeners', listeners)
    def original_services():
        text = read(STATE+'/services-before',4096).decode()
        previous = {}
        for block in text.strip().split('\n\n'):
            values = dict(line.split('=',1) for line in block.splitlines() if '=' in line)
            if set(values) != {'Id','MainPID','ActiveState','SubState'}:
                raise ValueError('service_baseline_format')
            if values['Id'] in previous: raise ValueError('duplicate_service_baseline')
            previous[values['Id']] = values
        expected = {'powerflow-api.service','powerflow-streamlit.service'}
        if set(previous) != expected: raise ValueError('service_baseline_inventory')
        return {name:all(result['checks'].get(name,{}).get(key)==value
                         for key,value in values.items()) for name,values in previous.items()}
    collect('original_service_identity_comparison', original_services)
    for p in CONFIGS: collect(p, lambda p=p:config(p))
    collect('configuration_metadata', lambda:{str(p):metadata(p) for p in sorted(
        {Path(p) for p in CONFIGS} | {parent for p in CONFIGS for parent in Path(p).parents}, key=str)})
    collect('staging_certificate_metadata', lambda:{str(p):metadata(p) for p in
        (Path(CERT), Path(CERT)/'cert.pem', Path(CERT)/'chain.pem', Path(CERT)/'fullchain.pem')})
    for baseline in ('production-before.sha256','staging-http.sha256'):
        def compare(baseline=baseline):
            expected = ('/etc/nginx/conf.d/powerflow.conf','/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem') if baseline.startswith('production') else ('/etc/nginx/conf.d/powerflow-staging-acme.conf',)
            entries={}
            for line in read(STATE+'/'+baseline,4096).decode().splitlines():
                m=re.fullmatch(r'([a-f0-9]{64})  (/.+)',line)
                if not m or m[2] not in expected: raise ValueError('baseline_format')
                if m[2] in entries: raise ValueError('duplicate_baseline')
                entries[m[2]]=m[1]
            if set(entries)!=set(expected): raise ValueError('baseline_inventory')
            # Public production certificate may legitimately be a Certbot symlink.
            return {p:hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in entries.items()}
        collect(baseline, compare)
    def certificate():
        out=run(['/usr/bin/openssl','x509','-in',CERT+'/cert.pem','-noout','-dates','-ext','subjectAltName'])
        dates=dict(re.findall(r'(?m)^(notBefore|notAfter)=(.+)$',out))
        names=re.findall(r'DNS:([^,\s]+)',out)
        if names != ['staging.powerflowenergy.dev']: raise ValueError('certificate_hostname')
        run(['/usr/bin/openssl','verify','-CAfile','/etc/pki/tls/certs/ca-bundle.crt','-untrusted',CERT+'/chain.pem',CERT+'/cert.pem'])
        return {'dates':dates,'SAN':names,'chain':'verified'}
    collect('staging_certificate', certificate)
    collect('acme_probe', lambda:{'metadata':metadata('/var/www/powerflow-staging-acme/.well-known/acme-challenge/preflight-probe'),
        'expected_body':read('/var/www/powerflow-staging-acme/.well-known/acme-challenge/preflight-probe',256)==b'powerflow-staging-acme-preflight\n'})
    collect('systemd_version', lambda:run(['/usr/bin/systemctl','--version']).splitlines()[0])
    collect('cgroup', lambda:{'v2':Path('/sys/fs/cgroup/cgroup.controllers').is_file(),
        'memory_controller': 'memory' in Path('/sys/fs/cgroup/cgroup.controllers').read_text().split(),
        'root_memory_max':Path('/sys/fs/cgroup/memory.max').read_text().strip(),
        'root_memory_swap_max':Path('/sys/fs/cgroup/memory.swap.max').read_text().strip()})
    for interpreter in ('/usr/bin/python3',ROOT+'/.venv-prod/bin/python'):
        collect(interpreter, lambda interpreter=interpreter:json.loads(run([interpreter,'-I','-S','-B','-c',
            'import sys,sysconfig,json; print(json.dumps({"version":list(sys.version_info[:3]),"platform":sysconfig.get_platform(),"soabi":sysconfig.get_config_var("SOABI")}))'])))
    result['deployment_authorized']=False
    result['readiness_assessment']='manual_gate_review_required; complete inspection is not installation approval'
    result['report_produced']=True
    result['status']='complete' if not result['errors'] else 'incomplete'
    print(json.dumps(result,indent=2))
    return 0 if not result['errors'] else 1

if __name__=='__main__': raise SystemExit(main())
