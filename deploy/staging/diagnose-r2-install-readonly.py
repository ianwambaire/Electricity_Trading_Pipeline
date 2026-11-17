#!/usr/bin/env python3
"""One read-only R2 partial-state inspection; never imports/runs candidate code."""
import hashlib,json,os,pwd,grp,re,stat,subprocess,time
from pathlib import Path
ID='phase-staging-https-ready-20261026'
C=Path('/var/lib/powerflow-staging-install')/ID
B=Path('/opt/powerflow/releases')/ID
S=Path('/var/www/powerflow-staging/releases')/ID
P=Path('/srv/powerflow/published')
U=Path('/etc/systemd/system/powerflow-candidate-api.service')
E=Path('/etc/powerflow/react-api.env')
KEEP=('powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service')
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','PYTHONDONTWRITEBYTECODE':'1'}

def meta(p):
 try:s=p.lstat()
 except FileNotFoundError:return {'exists':False}
 r={'exists':True,'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode)),'bytes':s.st_size,'symlink':stat.S_ISLNK(s.st_mode),'directory':stat.S_ISDIR(s.st_mode)}
 if p.is_symlink():r['link_target']=os.readlink(p)
 return r

def read(p,limit=4*1024**2):
 for a in (p,*p.parents):
  if a.is_symlink():raise RuntimeError('unexpected_symlink_read')
 with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,'O_NOATIME',0)),'rb') as f:
  s=os.fstat(f.fileno())
  if not stat.S_ISREG(s.st_mode) or s.st_size>limit:raise RuntimeError('file_limit')
  return f.read(limit+1)

def sha(p):return hashlib.sha256(read(p,128*1024**2)).hexdigest()

def command(args):
 p=subprocess.run(args,capture_output=True,timeout=10,env=ENV)
 return p.returncode,p.stdout

def main():
 r={'read_only':True,'errors':[]}
 try:
  assert os.geteuid()==0
  bundle=json.loads(read(C/'bundle.json'));r['control_bundle_sha256']=sha(C/'bundle.json')
  assert r['control_bundle_sha256']=='1a716274b69348a204cbc2300400b65a4485d33505ea4518c4bf7df4d5e815d8'
  paths=[C,B,S,P,P.parent,P.parent/('.published-'+ID),B/'.venv-api',B/'.venv-api/bin',B/'.venv-api/bin/python',B/'.venv-api/bin/python3',B/'.venv-api/bin/python3.14',B/'linux-regression.py',Path('/opt/powerflow/react-current'),Path('/var/www/powerflow-staging/current'),U,E]
  r['paths']={str(p):meta(p) for p in paths}
  r['markers']={name:meta(C/name) for name in ('install.started','publication-result.json','installed.ok','activation.started','activated.ok','rollback.started','installation-measurements.json')}
  captures=[];traces=[]
  for p in sorted(C.iterdir(),key=lambda p:p.name):
   if not re.fullmatch(r'[a-z-]+-\d+\.(?:timeout\.)?(?:stdout|stderr)',p.name):continue
   info={'name':p.name,'bytes':p.stat().st_size};captures.append(info)
   data=read(p).decode('utf-8',errors='replace')
   # Extract only exception/frame metadata, never raw lines or arbitrary output.
   for line in data.splitlines():
    frame=re.match(r'\s*File "([^"]+)", line (\d+), in ([A-Za-z0-9_<>]+)',line)
    if frame:traces.append({'capture':p.name,'frame_file':frame[1],'line':int(frame[2]),'function':frame[3]})
    failure=re.search(r'(PermissionError|OSError): \[Errno (\d+)\]',line)
    if failure:
     match=re.search(r"'([^']+)'",line)
     path=match[1] if match and any(match[1].startswith(str(x)) for x in (C,B,S,P,Path('/usr/'))) else None
     traces.append({'capture':p.name,'exception':failure[1],'errno':int(failure[2]),'approved_path':path})
  r['retained_captures']=captures;r['sanitized_traceback_frames']=traces
  r['traceback_present']=bool(traces)
  if (C/'production-services.before').exists():
   before=read(C/'production-services.before');code,current=command(['/usr/bin/systemctl','show',*KEEP,'--property=Id,MainPID,ActiveState,SubState'])
   r['production_services']={'exit_status':code,'identities_match_before':code==0 and current==before,'states':[dict(line.split('=',1) for line in block.splitlines() if '=' in line) for block in current.decode().strip().split('\n\n')]}
  code,data=command(['/usr/bin/systemctl','show','powerflow-candidate-api.service','--property=LoadState,ActiveState,SubState,MainPID,User,Group'])
  r['candidate_unit']={'exit_status':code,'properties':dict(line.split('=',1) for line in data.decode().splitlines() if '=' in line)}
  try:
   user=pwd.getpwnam('powerflow-api');group=grp.getgrnam('powerflow-api')
   r['identity']={'exists':True,'uid':user.pw_uid,'gid':user.pw_gid,'group_gid':group.gr_gid,'shell':user.pw_shell,'home':user.pw_dir,'supplementary_members':group.gr_mem}
  except KeyError:r['identity']={'exists':False};user=None
  r['release_hashes']={}
  for name,item in bundle['release_archive_inventory'].items():
   if name.startswith('api/'):path=B/name[4:]
   elif name.startswith('static/'):path=S/name[7:]
   else:continue
   r['release_hashes'][name]={'exists':path.is_file(),'matches':sha(path)==item['sha256'] if path.is_file() else False}
  r['publication_hashes']={item['relative_path']:{'exists':(P/item['relative_path']).is_file(),'matches':sha(P/item['relative_path'])==item['sha256'] if (P/item['relative_path']).is_file() else False} for item in bundle['publication_plan']}
  if (C/'publication-result.json').is_file():
   result=json.loads(read(C/'publication-result.json'));r['publication_result']={k:result.get(k) for k in ('data_bytes','total_file_bytes','files','metadata_files','file_mode','directory_mode','owner_uid','reader_gid','publication_manifest_sha256')}
   r['publication_metadata_matches']=sha(P/'_publication.json')==result['publication_manifest_sha256']
  r['production_config_hashes']={path:sha(Path(path))==h for path,h in bundle['preserved_hashes'].items()}
  r['staging_https_placeholder_matches']=sha(Path('/etc/nginx/conf.d/powerflow-staging-https.conf'))=='85ad4c7ec303b638033831cb7ebfd5b73b669c80b249926c8e1446ba70124396'
  baseline=read(Path('/var/lib/powerflow-staging-https-20261026/production-before.sha256')).decode()
  r['production_certificate_baseline']=False
  for line in baseline.splitlines():
   match=re.fullmatch(r'([a-f0-9]{64})  (/.+)',line)
   if match and match[2]=='/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem':
    # Public certificate's managed symlink intentionally followed; no key read.
    r['production_certificate_baseline']=hashlib.sha256(Path(match[2]).read_bytes()).hexdigest()==match[1]
  # Read-only effective-access probe: fork a stdlib-only child, change only its UID/GID.
  if user:
   rd,wr=os.pipe();pid=os.fork()
   if pid==0:
    os.close(rd)
    try:
     os.setgroups([]);os.setgid(user.pw_gid);os.setuid(user.pw_uid)
     checks={}
     for p in (B,B/'.venv-api',B/'.venv-api/bin',B/'.venv-api/bin/python',B/'linux-regression.py',P,C,Path('/usr/bin/python3.14')):
      try:checks[str(p)]={'R_OK':os.access(p,os.R_OK),'X_OK':os.access(p,os.X_OK),'W_OK':os.access(p,os.W_OK),'stat':meta(p)}
      except OSError as e:checks[str(p)]={'errno':e.errno}
     checks['inherited_cwd']=os.getcwd()
     os.write(wr,json.dumps(checks).encode())
    except Exception as e:os.write(wr,json.dumps({'error_type':type(e).__name__,'errno':getattr(e,'errno',None)}).encode())
    finally:os._exit(0)
   os.close(wr);body=b''
   while True:
    b=os.read(rd,16384)
    if not b:break
    body+=b
   os.close(rd);os.waitpid(pid,0);r['candidate_effective_access']=json.loads(body)
  r['status']='complete'
 except Exception as e:r['status']='incomplete';r['errors'].append({'type':type(e).__name__,'errno':getattr(e,'errno',None)})
 print(json.dumps(r,indent=2));return 0 if r['status']=='complete' else 1

if __name__=='__main__':raise SystemExit(main())
