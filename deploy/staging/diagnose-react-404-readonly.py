#!/usr/bin/env python3
"""Read-only routing/static diagnostic: no nginx -t/-T, reload, or file changes."""
import hashlib,http.client,importlib.util,json,os,pwd,re,socket,ssl,stat,subprocess,sys,types
from pathlib import Path
from html.parser import HTMLParser
C=Path('/var/lib/powerflow-staging-install/phase-staging-https-ready-20261026')
STATIC=Path('/var/www/powerflow-staging/releases/phase-staging-https-ready-20261026')
CURRENT=Path('/var/www/powerflow-staging/current')
HOST='staging.powerflowenergy.dev'
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','PYTHONDONTWRITEBYTECODE':'1'}
KEEP=('powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service')

def read(p,limit=1024*1024):
 with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,'O_NOATIME',0)),'rb') as f:
  if os.fstat(f.fileno()).st_size>limit:raise RuntimeError('read_limit')
  return f.read(limit+1)

def meta(p):
 try:s=p.lstat()
 except FileNotFoundError:return {'exists':False}
 r={'exists':True,'uid':s.st_uid,'gid':s.st_gid,'mode':oct(stat.S_IMODE(s.st_mode)),'bytes':s.st_size,'symlink':p.is_symlink()}
 if p.is_symlink():r['target']=os.readlink(p)
 return r

def cmd(args):
 p=subprocess.run(args,capture_output=True,timeout=10,env=ENV);return p.returncode,p.stdout

def request(target,path,tls=True):
 connection=None
 try:
  if tls:
   context=ssl.create_default_context(cafile='/etc/pki/tls/certs/ca-bundle.crt');raw=socket.create_connection((target,443),timeout=5)
   try:sock=context.wrap_socket(raw,server_hostname=HOST)
   except Exception:raw.close();raise
   connection=http.client.HTTPConnection(HOST,timeout=5);connection.sock=sock
  else:connection=http.client.HTTPConnection(target,80,timeout=5)
  connection.request('GET',path,headers={'Host':HOST});response=connection.getresponse();body=response.read(2*1024**2+1)
  result={'status':response.status,'body_bytes':len(body),'body_sha256':hashlib.sha256(body).hexdigest(),
          'safe_headers':{name:response.getheader(name) for name in ('Content-Type','Cache-Control','Server')},
          'CSP_report_only_present':response.getheader('Content-Security-Policy-Report-Only') is not None}
  return result
 except Exception as e:return {'error_type':type(e).__name__,'errno':getattr(e,'errno',None)}
 finally:
  if connection:connection.close()

class References(HTMLParser):
 def __init__(self):super().__init__();self.refs=set()
 def handle_starttag(self,tag,attrs):
  for k,v in attrs:
   if k in ('src','href') and v and v.startswith('/assets/'):self.refs.add(v)

def main():
 r={'read_only':True,'errors':[]}
 try:
  assert os.geteuid()==0
  raw=read(C/'bundle.json');assert hashlib.sha256(raw).hexdigest()=='1a716274b69348a204cbc2300400b65a4485d33505ea4518c4bf7df4d5e815d8';b=json.loads(raw)
  source=read(C/'activate-staging-https.py');assert hashlib.sha256(source).hexdigest()=='9c9173cf3f8da0e004dd30e16ca320f19ab860fa0770fa6a87414869b3efa6d4'
  source=source.replace(b"tokens[position[0]] not in '{};':",b"tokens[position[0]] not in ('{', '}', ';'):")
  assert hashlib.sha256(source).hexdigest()=='c6d735d231943d2e3e4042ede969f838262eb3be2cac165fcc683d4c46e82d74'
  m=types.ModuleType('fixed_readonly_reviewer');m.__file__=str(C/'activate-staging-https.py');exec(compile(source,m.__file__,'exec'),m.__dict__)
  hashes,servers=m.review_config(True);r['reviewed_server_blocks']=servers;r['strict_review']='passed'
  target=Path('/etc/nginx/conf.d/powerflow-staging-https.conf');body=read(target)
  r['staging_config_hash_matches']=hashlib.sha256(body).hexdigest()==b['candidate_nginx_sha256']
  safe=[]
  for i,line in enumerate(body.decode().splitlines(),1):
   if re.match(r'\s*(server_name|listen|root|index|location|try_files|proxy_pass)\b',line):safe.append({'line':i,'directive':line.strip()})
  r['staging_routing_directives']=safe
  r['static_path_metadata']={str(p):meta(p) for p in (Path('/var'),Path('/var/www'),Path('/var/www/powerflow-staging'),Path('/var/www/powerflow-staging/releases'),STATIC,CURRENT,STATIC/'index.html')}
  assert CURRENT.is_symlink() and CURRENT.resolve()==STATIC,'unexpected_static_link'
  index=read(STATIC/'index.html');r['index_hash_matches']=hashlib.sha256(index).hexdigest()==b['release_archive_inventory']['static/index.html']['sha256']
  parser=References();parser.feed(index.decode());r['referenced_assets']={}
  for name in sorted(parser.refs):
   assert 'static'+name in b['release_archive_inventory'],'unexpected_index_asset'
   path=STATIC/name.lstrip('/');r['referenced_assets'][name]={'metadata':meta(path),'hash_matches':hashlib.sha256(read(path,2*1024**2)).hexdigest()==b['release_archive_inventory']['static'+name]['sha256']}
  code,data=cmd(['/usr/bin/systemctl','show','nginx.service','--property=MainPID,ActiveState,SubState,ExecMainStartTimestamp'])
  # Only PID, state and start time; no command arguments, environment or logs.
  nginx=dict(line.split('=',1) for line in data.decode().splitlines() if '=' in line)
  r['nginx_state']={k:nginx.get(k) for k in ('MainPID','ActiveState','SubState','ExecMainStartTimestamp')}
  master=int(nginx['MainPID']);children=read(Path('/proc')/str(master)/'task'/str(master)/'children',4096).decode().split()
  workers=[]
  for pid in children[:16]:
   status=read(Path('/proc')/pid/'status',16384).decode();fields=dict(line.split(':',1) for line in status.splitlines() if ':' in line)
   if fields.get('Name','').strip()!='nginx':continue
   workers.append({'pid':int(pid),'uid':int(fields['Uid'].split()[1]),'gid':int(fields['Gid'].split()[1]),'groups':[int(x) for x in fields.get('Groups','').split()]})
  r['nginx_children']=workers
  worker=next((x for x in workers if x['uid']!=0),None)
  if worker:
   rd,wr=os.pipe();pid=os.fork()
   if pid==0:
    os.close(rd)
    try:
     os.setgroups(worker['groups']);os.setgid(worker['gid']);os.setuid(worker['uid'])
     paths=[Path('/var/www/powerflow-staging'),Path('/var/www/powerflow-staging/releases'),STATIC,STATIC/'index.html',*[STATIC/name.lstrip('/') for name in parser.refs]]
     values={str(p):{'readable':os.access(p,os.R_OK),'traversable':os.access(p,os.X_OK) if p.is_dir() else None} for p in paths}
     os.write(wr,json.dumps(values).encode())
    except Exception as e:os.write(wr,json.dumps({'error_type':type(e).__name__,'errno':getattr(e,'errno',None)}).encode())
    finally:os._exit(0)
   os.close(wr);payload=b''
   while True:
    data=os.read(rd,16384)
    if not data:break
    payload+=data
   os.close(rd);os.waitpid(pid,0);r['worker_effective_file_access']=json.loads(payload)
  r['HTTP']={'loopback_HTTPS_root':request('127.0.0.1','/'),'public_HTTPS_root':request(HOST,'/'),'loopback_HTTP_root':request('127.0.0.1','/',False),'loopback_HTTPS_index':request('127.0.0.1','/index.html'),'loopback_HTTPS_API':request('127.0.0.1','/api/health')}
  for asset in sorted(parser.refs):r['HTTP']['asset '+asset]=request('127.0.0.1',asset)
  r['candidate_HTTP']={}
  for path in ('/health','/ready'):
   c=http.client.HTTPConnection('127.0.0.1',8010,timeout=3)
   try:c.request('GET',path);response=c.getresponse();response.read(4096);r['candidate_HTTP'][path]=response.status
   except OSError as e:r['candidate_HTTP'][path]={'error_type':type(e).__name__,'errno':e.errno}
   finally:c.close()
  code,data=cmd(['/usr/bin/systemctl','show',*KEEP,'--property=Id,MainPID,ActiveState,SubState']);r['production_services_match']=code==0 and data==read(C/'production-services.before')
  r['production_config_ACME_match']={p:hashlib.sha256(read(Path(p))).hexdigest()==h for p,h in b['preserved_hashes'].items()}
  baseline=read(Path('/var/lib/powerflow-staging-https-20261026/production-before.sha256')).decode()
  for line in baseline.splitlines():
   match=re.fullmatch(r'([a-f0-9]{64})  (/.+)',line)
   if match and match[2]=='/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem':r['production_certificate_match']=hashlib.sha256(Path(match[2]).read_bytes()).hexdigest()==match[1]
  r['status']='complete'
 except Exception as e:r['status']='incomplete';r['errors'].append({'type':type(e).__name__,'errno':getattr(e,'errno',None)})
 print(json.dumps(r,indent=2));return 0 if r['status']=='complete' else 1

if __name__=='__main__':raise SystemExit(main())
