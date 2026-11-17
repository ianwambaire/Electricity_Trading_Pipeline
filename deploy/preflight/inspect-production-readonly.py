#!/usr/bin/env python3
"""PROPOSAL ONLY: bounded fixed-scope host metadata via SSH stdin; no writes.

Never runs nginx -T/-t, sudo, Certbot, restarts, SQL, environment/argv/log reads,
IMDS or external HTTP. Raw config/command errors are never emitted.
"""
import http.client
import json
from pathlib import Path
import re
import signal
import ssl
import subprocess
import time

CHECKOUT=Path('/home/ec2-user/Electricity_Trading_Pipeline')
UNITS=('nginx.service','powerflow-api.service','powerflow-streamlit.service',
       'powerflow-prefect-worker.service','powerflow-prefect-server.service',
       'postgresql.service','certbot.timer','certbot-renew.timer')
PROPERTIES='Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,WorkingDirectory,MainPID,User,Group,MemoryCurrent,MemoryPeak,MemorySwapCurrent,MemoryMax,TasksCurrent,NextElapseUSecRealtime,LastTriggerUSec'


def bounded(command):
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=4)
        return result.returncode,result.stdout[:32768]
    except (OSError,subprocess.TimeoutExpired):return None,''


def safe_nginx(text):
    """Allowlisted observations only; never print config lines or secret headers."""
    text=re.sub(r'#.*','',text)
    directives=re.findall(r'(?:^|[;{}])\s*([a-z_]+)\s+([^;{}]*);',text,re.M)
    summary={'listeners':[],'server_names':[],'upstream_loopback_ports':[],
             'spa_fallback':False,'api_locations':False,'certificate_directive':False,
             'private_key_directive_present':False,'security_header_names':[], 'unclassified_upstream_count':0,
             'acme_challenge_location':'.well-known/acme-challenge' in text}
    for name,value in directives:
        value=value.strip()
        if name=='listen':
            match=re.fullmatch(r'(?:127\.0\.0\.1:|\[::\]:)?(80|443|8000|8010|8501)(?:\s+(?:ssl|http2|default_server|ipv6only=on))*',value)
            if match:summary['listeners'].append(value)
        elif name=='server_name':
            summary['server_names'] += [v for v in value.split() if v in {'powerflowenergy.dev','www.powerflowenergy.dev','staging.powerflowenergy.dev'}]
        elif name=='proxy_pass':
            match=re.fullmatch(r'http://127\.0\.0\.1:(8000|8010|8501)/?',value)
            if match:summary['upstream_loopback_ports'].append(int(match[1]))
            else:summary['unclassified_upstream_count']+=1
        elif name=='try_files' and re.search(r'(^|\s)/index\.html($|\s)',value):summary['spa_fallback']=True
        elif name=='ssl_certificate':summary['certificate_directive']=True
        elif name=='ssl_certificate_key':summary['private_key_directive_present']=True
        elif name=='add_header':
            header=value.split()[0] if value else ''
            if header in {'Cache-Control','Strict-Transport-Security','Content-Security-Policy','Content-Security-Policy-Report-Only','X-Content-Type-Options','Referrer-Policy','X-Frame-Options'}:summary['security_header_names'].append(header)
    summary['api_locations']=bool(re.search(r'location\s+(?:\^~\s+)?/api/',text))
    return summary


def inspect():
    result={'scope':'fixed read-only metadata; no configuration validation/changes','services':{},'nginx':{},'health':{}}
    # No config include expansion beyond these approved names/pattern/limits.
    conf=Path('/etc/nginx/conf.d')
    if conf.is_symlink():raise ValueError('unexpected_nginx_directory')
    candidates=[Path('/etc/nginx/nginx.conf')]
    if conf.is_dir():
        files=sorted(conf.glob('*.conf'))
        if len(files)>16:raise ValueError('nginx_config_count_limit')
        candidates+=files
    for path in candidates:
        if path.is_symlink() or path.parent not in {Path('/etc/nginx'),conf} or path.exists() and path.resolve()!=path:raise ValueError('unexpected_config_path')
        try:
            if path.stat().st_size>65536:raise ValueError('nginx_config_size_limit')
            result['nginx'][str(path)]=safe_nginx(path.read_text())
        except (OSError,UnicodeError):result['nginx'][str(path)]={'status':'unreadable_or_missing'}
    rc,output=bounded(['/usr/bin/systemctl','show',*UNITS,'--property='+PROPERTIES])
    result['services']={'exit_code':rc,'metadata':output if rc==0 else None}
    rc,output=bounded(['/usr/sbin/ss','-ltnp','( sport = :8000 or sport = :8010 or sport = :8501 )'])
    result['listeners']={'exit_code':rc,'metadata':output if rc==0 else None}
    try:
        memory={}
        for line in Path('/proc/meminfo').read_text().splitlines():
            name,_,value=line.partition(':')
            if name in {'MemTotal','MemAvailable','SwapTotal','SwapFree'}:memory[name]=int(value.split()[0])*1024
        result['memory_bytes']=memory
        import os
        fs=os.statvfs(CHECKOUT)
        result['filesystem_bytes']={'total':fs.f_blocks*fs.f_frsize,'available':fs.f_bavail*fs.f_frsize}
    except OSError:result['capacity']='unverified'
    certificate=Path('/etc/letsencrypt/live/powerflowenergy.dev/cert.pem')
    try:
        resolved=certificate.resolve(strict=True)
        if not re.fullmatch(r'/etc/letsencrypt/archive/powerflowenergy\.dev/cert[0-9]+\.pem',str(resolved)):
            raise ValueError('unexpected_public_certificate_path')
        parsed=ssl._ssl._test_decode_cert(str(resolved))
        result['public_certificate']={'expires':parsed.get('notAfter'),'not_before':parsed.get('notBefore'),
            'expected_names':[v for kind,v in parsed.get('subjectAltName',[]) if kind=='DNS' and v in {'powerflowenergy.dev','www.powerflowenergy.dev'}],
            'chain_trust':'not_assessed'}
    except (OSError,ssl.SSLError):result['public_certificate']={'status':'unreadable_or_missing'}
    result['cron_renewal_references']={}
    for path in ('/etc/crontab','/etc/cron.d/certbot','/etc/cron.d/certbot-renew'):
        try:
            file=Path(path)
            if file.is_symlink() or file.stat().st_size>32768:raise ValueError('cron_path_or_size')
            result['cron_renewal_references'][path]=bool(re.search(r'certbot[^\n]*\brenew\b',file.read_text()))
        except (OSError,UnicodeError):result['cron_renewal_references'][path]=None
    for port in (8000,8010):
        for path in ('/health','/ready'):
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
            try:
                connection.request('GET',path,headers={'Host':'localhost'})
                response=connection.getresponse()
                # Do not follow redirects or read arbitrary response bodies.
                result['health'][str(port)+path]={'status':response.status}
                response.close()
            except (OSError,http.client.HTTPException):result['health'][str(port)+path]={'status':'unavailable'}
            finally:connection.close()
    result['limitations']=['point_in_time_capacity_not_peak','nginx_syntax_and_effective_includes_not_verified',
        'unreadable_paths_not_absence','no_other_cron_or_user_timer_search','no_JWT_or_live_Cognito_test']
    return result


if __name__=='__main__':
    started=time.monotonic()
    def expire(*_):raise TimeoutError('deadline')
    signal.signal(signal.SIGALRM,expire);signal.setitimer(signal.ITIMER_REAL,60)
    try:
        output=inspect();output['elapsed_seconds']=round(time.monotonic()-started,3)
        print(json.dumps(output,indent=2))
    except Exception:
        print('{"status":"stopped","detail":"Inspection limit or unexpected condition; no retry or changes."}')
        raise SystemExit(1)
    finally:signal.setitimer(signal.ITIMER_REAL,0)
