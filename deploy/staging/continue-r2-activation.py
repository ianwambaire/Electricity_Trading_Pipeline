#!/usr/bin/env python3
"""Single explicitly authorized continuation: no config rewrite or FastAPI restart."""
import hashlib,http.client,importlib.util,json,os,re,socket,ssl,subprocess,sys,time,types
from pathlib import Path
C=Path('/var/lib/powerflow-staging-install/phase-staging-https-ready-20261026')
BUNDLE='1a716274b69348a204cbc2300400b65a4485d33505ea4518c4bf7df4d5e815d8'
OLD='9c9173cf3f8da0e004dd30e16ca320f19ab860fa0770fa6a87414869b3efa6d4'
FIXED='c6d735d231943d2e3e4042ede969f838262eb3be2cac165fcc683d4c46e82d74'
HOST='staging.powerflowenergy.dev'

def need(x,code):
 if not x:raise RuntimeError(code)

def corrected_source(body):
 need(hashlib.sha256(body).hexdigest()==OLD,'original_reviewer_changed')
 before=b"tokens[position[0]] not in '{};':";after=b"tokens[position[0]] not in ('{', '}', ';'):"
 need(body.count(before)==1,'parser_patch_not_exact')
 body=body.replace(before,after)
 need(hashlib.sha256(body).hexdigest()==FIXED,'corrected_parser_hash_mismatch')
 return body

def https_get(path,leaf,timeout=4):
 context=ssl.create_default_context(cafile='/etc/pki/tls/certs/ca-bundle.crt')
 raw=socket.create_connection(('127.0.0.1',443),timeout=timeout)
 try:sock=context.wrap_socket(raw,server_hostname=HOST)
 except Exception:raw.close();raise
 need(hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest()==leaf,'served_certificate_changed')
 connection=http.client.HTTPConnection(HOST,timeout=timeout);connection.sock=sock
 try:
  connection.request('GET',path);response=connection.getresponse();body=response.read(2*1024**2+1)
  need(len(body)<=2*1024**2,'HTTP_body_limit')
  return response.status,body
 finally:connection.close()

def wait_for_react_entry(leaf,expected_hash,request=None,clock=None,sleep=None):
 # Readiness probes only: never another reload/restart or altered expected content.
 request=request or https_get;clock=clock or time.monotonic;sleep=sleep or time.sleep
 deadline=clock()+10
 for attempt in range(21):
  remaining=deadline-clock();need(remaining>0,'React_entry_readiness_deadline')
  status,body=request('/',leaf,timeout=min(4,remaining))
  if status==200:
   need(hashlib.sha256(body).hexdigest()==expected_hash,'React_entry_content_hash')
   return status,body
  need(status==404,'React_entry_unexpected_HTTP_status')
  remaining=deadline-clock();need(remaining>0,'React_entry_readiness_deadline')
  sleep(min(0.5,remaining))
 raise RuntimeError('React_entry_readiness_deadline')


def runtime(m):
 m.health();props=m.limits_and_bpf()
 need(props.get('MainPID')=='1824094','candidate_PID_changed')
 events=dict(line.split() for line in m.read(Path('/sys/fs/cgroup/system.slice/powerflow-candidate-api.service/memory.events')).decode().splitlines())
 need(int(events.get('oom',0))==0 and int(events.get('oom_kill',0))==0,'candidate_OOM_event')
 return props

def main():
 os.umask(0o077);report={'status':'failed','phase':'preflight','reload_invocations':0,'production_preservation':'not_checked','HTTP':{},'static_assets':{}}
 m=None
 try:
  need(os.geteuid()==0,'root_required')
  for p in (C,*C.parents):need(not p.is_symlink(),'control_symlink')
  need(C.stat().st_uid==0 and C.stat().st_mode&0o777==0o700,'control_permissions')
  raw=(C/'bundle.json').read_bytes();need(hashlib.sha256(raw).hexdigest()==BUNDLE,'bundle_changed');b=json.loads(raw)
  for name,h in b['control_hashes'].items():need(hashlib.sha256((C/name).read_bytes()).hexdigest()==h,'R2_control_hash_changed')
  for item in b['artifacts']:need(hashlib.sha256((C/item['name']).read_bytes()).hexdigest()==item['sha256'],'R2_artifact_hash_changed')
  sys.path.insert(0,str(C));spec=importlib.util.spec_from_file_location('retained_R2_installer',C/'install.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  need((C/'installed.ok').is_file() and (C/'activation.started').is_file(),'partial_state_not_expected')
  for name in ('activated.ok','routing-continuation.started','routing-continuation.ok','rollback.started'):need(not os.path.lexists(C/name),'continuation_already_attempted_or_unexpected_state')
  m.verify_installed(b)
  need(m.CURRENT.is_symlink() and m.CURRENT.resolve()==m.BACKEND and m.WWW.is_symlink() and m.WWW.resolve()==m.STATIC,'release_link_changed')
  for path,h in ((m.UNIT,b['candidate_unit_sha256']),(m.ENVFILE,b['candidate_env_sha256']),(m.HTTPS,b['candidate_nginx_sha256']),(m.HTTP_SUPPORT,next(x['sha256'] for x in b['artifacts'] if x['name']=='staging-support.conf')),(m.HEADERS,b['release_archive_inventory']['proposals/security-headers.conf']['sha256'])):
   need(m.sha(path)==h,'installed_configuration_hash_changed')
  need(m.sha(C/'previous-https.conf')==m.PLACEHOLDER,'saved_placeholder_changed')
  before=m.read(C/'production-services.before');m.preservation(b,before);report['production_preservation']='preflight_passed'
  m.capacity(0);report['candidate_security']=runtime(m)
  reviewer=types.ModuleType('corrected_reviewer');reviewer.__file__=str(C/'activate-staging-https.py')
  exec(compile(corrected_source(m.read(C/'activate-staging-https.py')),reviewer.__file__,'exec'),reviewer.__dict__)
  leaf,public=reviewer.certificate_checks();hashes,_=reviewer.review_config(True)
  report['corrected_parser']='passed';report['certificate']='trusted_hostname_SAN_and_expiry_verified'
  report['phase']='native_nginx_validation'
  native=subprocess.run(['/usr/sbin/nginx','-t'],capture_output=True,timeout=5,env=m.ENV)
  m.create_file(C/'routing-continuation.nginx.stdout',native.stdout,0o600);m.create_file(C/'routing-continuation.nginx.stderr',native.stderr,0o600)
  need(native.returncode==0,'native_nginx_validation_failed')
  need(not re.search(rb'\[(warn|error|emerg|alert|crit)\]',native.stderr,re.I),'native_nginx_warning')
  report['native_nginx_validation']='passed'
  after,_=reviewer.review_config(True);need(after==hashes,'Nginx_configuration_drift')
  m.preservation(b,before);report['candidate_security']=runtime(m)
  m.create_file(C/'routing-continuation.started',b'One approved parser-corrected routing continuation.\n',0o600)
  report['phase']='graceful_reload';report['reload_invocations']=1
  m.run('routing-continuation-reload',['/usr/bin/systemctl','reload','nginx'],seconds=15)
  report['phase']='HTTPS_verification'
  for path,expected in (('/',200),('/analytics',200),('/forecasting',200),('/anomalies',200),('/models',200),('/pipeline',200),('/profile',200),('/auth/callback',200),('/api/health',200),('/api/ready',404),('/api/market/coverage',200),('/api/models/summary',200),('/api/forecast/next24',404),('/.well-known/acme-challenge/preflight-probe',200)):
   status,body=wait_for_react_entry(leaf,b['release_archive_inventory']['static/index.html']['sha256']) if path=='/' else https_get(path,leaf)
   report['HTTP'][path]=status;need(status==expected,'staging_HTTP_status_failed')
   if path in ('/','/analytics','/forecasting','/anomalies','/models','/pipeline','/profile','/auth/callback'):
    need(hashlib.sha256(body).hexdigest()==b['release_archive_inventory']['static/index.html']['sha256'],'React_entry_content_hash')
   if path.endswith('/preflight-probe'):need(body==b'powerflow-staging-acme-preflight\n','HTTPS_ACME_body')
  for name,item in sorted(b['release_archive_inventory'].items()):
   if not name.startswith('static/') or name=='static/index.html':continue
   path='/'+name[7:];status,body=https_get(path,leaf);report['static_assets'][path]=status
   need(status==200 and hashlib.sha256(body).hexdigest()==item['sha256'],'static_asset_status_or_hash')
  connection=http.client.HTTPConnection('127.0.0.1',80,timeout=4)
  try:
   connection.request('GET','/.well-known/acme-challenge/preflight-probe',headers={'Host':HOST});response=connection.getresponse()
   need(response.status==200 and response.read(4096)==b'powerflow-staging-acme-preflight\n','HTTP_ACME_failed')
  finally:connection.close()
  report['phase']='final_preservation';m.preservation(b,before);report['candidate_security']=runtime(m)
  final_hashes,_=reviewer.review_config(True);need(final_hashes==hashes,'configuration_changed_after_reload')
  report['production_preservation']='passed';report['status']='passed';report['phase']='complete';report['remaining']='Cognito staging URL configuration and real-account browser acceptance'
  m.create_file(C/'routing-continuation.ok',b'Staging HTTPS/static/API and preservation verified.\n',0o600)
  m.create_file(C/'activated.ok',b'Corrected-parser continuation successful; browser authentication acceptance pending.\n',0o600)
 except Exception as e:
  report['error_type']=type(e).__name__;report['errno']=getattr(e,'errno',None)
  report['safe_error']=str(e) if isinstance(e,RuntimeError) and re.fullmatch('[A-Za-z0-9_]+',str(e)) else 'details_withheld'
 if m is not None:
  try:m.create_file(C/'routing-continuation.report.json',json.dumps(report,indent=2).encode(),0o600)
  except Exception:report['private_report_write']='not_completed'
 print(json.dumps(report,indent=2));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
