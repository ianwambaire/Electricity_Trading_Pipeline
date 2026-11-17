#!/usr/bin/env python3
"""One read-only inspection: retained activation evidence, strict parse, candidate state."""
import hashlib,http.client,importlib.util,json,os,re,subprocess,sys
from pathlib import Path
C=Path('/var/lib/powerflow-staging-install/phase-staging-https-ready-20261026')
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','PYTHONDONTWRITEBYTECODE':'1'}
KEEP=('powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service')
PROPS='User,Group,MainPID,LoadState,ActiveState,SubState,MemoryCurrent,MemoryHigh,MemoryMax,MemorySwapMax,NRestarts,ControlGroup,IPAddressDeny,ProtectHome,ProtectSystem,NoNewPrivileges,PrivateTmp,PrivateDevices,CapabilityBoundingSet'

def read(p,limit=1024*1024):
 for a in (p,*p.parents):
  if a.is_symlink():raise RuntimeError('symlink_read_not_approved')
 with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,'O_NOATIME',0)),'rb') as f:
  if os.fstat(f.fileno()).st_size>limit:raise RuntimeError('read_limit')
  return f.read(limit+1)

def sha(p):return hashlib.sha256(read(p)).hexdigest()
def cmd(args):
 p=subprocess.run(args,capture_output=True,timeout=10,env=ENV);return p.returncode,p.stdout

def main():
 r={'read_only':True,'errors':[]}
 try:
  assert os.geteuid()==0
  raw=read(C/'bundle.json');assert hashlib.sha256(raw).hexdigest()=='1a716274b69348a204cbc2300400b65a4485d33505ea4518c4bf7df4d5e815d8';bundle=json.loads(raw)
  reviewer=C/'activate-staging-https.py';assert sha(reviewer)=='9c9173cf3f8da0e004dd30e16ca320f19ab860fa0770fa6a87414869b3efa6d4'
  r['markers']={name:(C/name).is_file() for name in ('installed.ok','activation.started','activated.ok','previous-https.conf','rollback.started')}
  captures=[];security=[];evidence=[]
  for p in C.iterdir():
   if re.fullmatch(r'[a-z-]+-\d+\.(stdout|stderr)',p.name):
    captures.append({'name':p.name,'bytes':p.stat().st_size})
    if p.name.startswith('effective-unit-properties-') and p.name.endswith('.stdout'):
     security.append(dict(line.split('=',1) for line in read(p).decode().splitlines() if '=' in line))
    if p.name.startswith(('nginx-baseline-','nginx-installed-','reload-staging-routing-')):
     body=read(p);evidence.append({'name':p.name,'syntax_success_message':b'syntax is ok' in body,'test_success_message':b'test is successful' in body,'warning_present':bool(re.search(rb'\[(warn|error|emerg|alert|crit)\]',body,re.I))})
  r['captures']=sorted(captures,key=lambda x:x['name']);r['nginx_capture_summary']=evidence;r['retained_runtime_security']=security
  https=Path('/etc/nginx/conf.d/powerflow-staging-https.conf');actual=sha(https)
  r['staging_https']={'sha256':actual,'matches_placeholder':actual=='85ad4c7ec303b638033831cb7ebfd5b73b669c80b249926c8e1446ba70124396','matches_candidate':actual==bundle['candidate_nginx_sha256']}
  spec=importlib.util.spec_from_file_location('retained_reviewer',reviewer);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  fault=[]
  def trace(frame,event,arg):
   if event=='exception' and frame.f_code.co_filename==str(reviewer) and frame.f_code.co_name=='parse' and not fault:
    exc=arg[1];loc=frame.f_locals
    if str(exc)=='invalid_directive_end' and loc.get('end') not in (';','{'):
     source=loc.get('real');words=loc.get('words',[])
     detail={'error':str(exc),'source':str(source),'context':list(loc.get('ctx',())),'parser_line':frame.f_lineno,'terminator_repr':repr(loc.get('end')),'directive_name':words[0] if words else None}
     if words==['proxy_set_header','Connection']:
      lines=[(i,line.strip()) for i,line in enumerate(read(source).decode().splitlines(),1) if re.fullmatch(r'\s*proxy_set_header\s+Connection\s+(?:""|\'\')\s*;\s*',line)]
      detail['matching_source_lines']=[{'line':i,'directive':line} for i,line in lines]
     fault.append(detail)
   return trace
  sys.settrace(trace)
  try:hashes,summary=m.review_config(True);r['strict_review']={'passed':True,'config_count':len(hashes)}
  except Exception as e:r['strict_review']={'passed':False,'error_type':type(e).__name__,'safe_error':str(e) if isinstance(e,RuntimeError) else 'details_withheld'}
  finally:sys.settrace(None)
  r['parser_fault']=fault
  code,data=cmd(['/usr/bin/systemctl','show','powerflow-candidate-api.service','--property='+PROPS]);r['candidate']={'exit_status':code,'properties':dict(line.split('=',1) for line in data.decode().splitlines() if '=' in line)}
  cg=r['candidate']['properties'].get('ControlGroup')
  if cg=='/system.slice/powerflow-candidate-api.service':
   root=Path('/sys/fs/cgroup')/cg.lstrip('/')
   r['cgroup']={name:read(root/name).decode().strip() for name in ('memory.high','memory.max','memory.swap.max','memory.current','memory.events')}
  ss=next((p for p in ('/usr/sbin/ss','/usr/bin/ss') if os.access(p,os.X_OK)),None)
  if ss:
   code,data=cmd([ss,'-H','-ltnp','sport = :8010']);r['candidate_listener']={'exit_status':code,'output':data.decode().strip()}
  r['retained_BPF_evidence']=[json.loads(read(p)) for p in C.glob('bpf-evidence-*.json')][:4]
  r['candidate_HTTP']={}
  for path in ('/health','/ready'):
   connection=http.client.HTTPConnection('127.0.0.1',8010,timeout=3)
   try:connection.request('GET',path);response=connection.getresponse();response.read(4096);r['candidate_HTTP'][path]=response.status
   except OSError as e:r['candidate_HTTP'][path]={'error_type':type(e).__name__,'errno':e.errno}
   finally:connection.close()
  code,data=cmd(['/usr/bin/systemctl','show',*KEEP,'--property=Id,MainPID,ActiveState,SubState'])
  r['production_services_match']=code==0 and data==read(C/'production-services.before')
  r['production_config_and_ACME']={p:sha(Path(p))==h for p,h in bundle['preserved_hashes'].items()}
  baseline=read(Path('/var/lib/powerflow-staging-https-20261026/production-before.sha256')).decode()
  for line in baseline.splitlines():
   match=re.fullmatch(r'([a-f0-9]{64})  (/.+)',line)
   if match and match[2]=='/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem':r['production_certificate_match']=hashlib.sha256(Path(match[2]).read_bytes()).hexdigest()==match[1]
  r['status']='complete'
 except Exception as e:r['status']='incomplete';r['errors'].append({'type':type(e).__name__,'errno':getattr(e,'errno',None)})
 print(json.dumps(r,indent=2));return 0 if r['status']=='complete' else 1

if __name__=='__main__':raise SystemExit(main())
