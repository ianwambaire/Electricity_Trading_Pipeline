"""One-time staging directory/tool setup; NO forecast publication or service change.
CONFIG and BASE are retained hash-verified bytes supplied by the local runner.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile

PACKET_SHA='faeec014b4cde838fcffb3c285eef1995f38547d443162e529fa90ec7209a6b3'
TOOLS_PARENT=Path('/opt/powerflow/forecast-publication-tools')
TOOLS=TOOLS_PARENT/PACKET_SHA
ROOT=Path('/srv/powerflow/forecast-publications')
UNIT='powerflow-candidate-api.service'
CHANGED=False
PHASE='PREFLIGHT'
HASHES={'prepare.py':'1f24db3f7ea3069a70b71939fd9e90984c4d2a63f8347c44e8a7a17c9c877d14',
 'publish.py':'cacc6116944269bed260af5034c8e1bd4066ea126850a2a94c45c465f94a053a',
 'shared/__init__.py':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
 'shared/forecast_publication.py':'264f3e33be1b2887174899473b7f955cc6fa8206ce1e0d7b0961da958eea5395'}

class Stop(ValueError):pass

def need(value,code):
    if not value:raise Stop(code)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def read(path,limit=100000):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        need(stat.S_ISREG(os.fstat(f.fileno()).st_mode),'FILE_TYPE')
        raw=f.read(limit+1)
    need(len(raw)<=limit,'READ_BOUND');return raw

def directory(path,mode=None,gid=None):
    for node in (path,)+tuple(path.parents):
        info=node.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'UNSAFE_DIRECTORY')
    info=path.lstat()
    if mode is not None:need(stat.S_IMODE(info.st_mode)==mode,'DIRECTORY_MODE')
    if gid is not None:need(info.st_gid==gid,'DIRECTORY_GROUP')

def packet(raw):
    need(len(raw)==6470 and sha(raw)==PACKET_SHA,'PACKET_HASH')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        members=archive.getmembers();expected=set(HASHES)|{'tools-manifest.json'}
        need(len(members)==5 and {m.name for m in members}==expected and all(m.isfile() and m.size<=100000 for m in members),'PACKET_INVENTORY')
        files={m.name:archive.extractfile(m).read(100001) for m in members}
    need(all(sha(files[name])==value for name,value in HASHES.items()),'PACKET_SOURCE_HASH')
    need(json.loads(files['tools-manifest.json'])==HASHES,'PACKET_MANIFEST')
    return files

def verify_tools(files):
    directory(TOOLS,0o700,0);seen=set()
    for parent,dirs,names in os.walk(TOOLS,followlinks=False):
        need(len(dirs)+len(names)<=8,'TOOLS_INVENTORY')
        directory(Path(parent),0o700,0)
        for name in dirs:need(Path(parent)/name==TOOLS/'shared','TOOLS_INVENTORY')
        for name in names:
            p=Path(parent)/name;rel=str(p.relative_to(TOOLS));info=p.lstat()
            need(rel in files and stat.S_ISREG(info.st_mode) and info.st_uid==info.st_gid==0 and stat.S_IMODE(info.st_mode)==0o600,'TOOLS_METADATA')
            need(read(p)==files[rel],'TOOLS_HASH');seen.add(rel)
    need(seen==set(files),'TOOLS_INVENTORY')

def command(argv):
    result=BASE['bounded_run'](argv,timeout=8,limit=16384,grace=5)
    need(result['failure'] is None and result['returncode']==0,'INSPECTION_COMMAND_FAILED')
    return result['stdout']

def candidate():
    raw=command(['/usr/bin/systemctl','show',UNIT,'--property=User,Group,ActiveState,SubState,MainPID'])
    values=dict(line.split('=',1) for line in raw.decode().splitlines() if '=' in line)
    need(all(values.get(k)==v for k,v in {'User':'powerflow-api','Group':'powerflow-api','ActiveState':'active','SubState':'running'}.items()),'CANDIDATE_IDENTITY')
    value=values.get('MainPID','');need(value.isdigit() and int(value)>1,'CANDIDATE_IDENTITY');pid=int(value)
    status=read(Path('/proc')/str(pid)/'status',16384).decode()
    for label in ('Uid','Gid'):
        match=re.search(r'^'+label+r':\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)',status,re.M)
        need(match and set(match.groups())=={'992'},'CANDIDATE_IDENTITY')
    return pid

PROBE=r"""import json,os,sys,re
assert os.getuid()==os.geteuid()==992 and os.getgid()==os.getegid()==992 and os.getgroups()==[]
with open('/proc/self/status') as stream: status=stream.read(16384)
assert re.search(r'^CapEff:\s+0+$',status,re.M) and 'NoNewPrivs:\t1' in status
paths=('/srv/powerflow',) if sys.argv[1]=='parent' else ('/srv/powerflow/forecast-publications','/srv/powerflow/forecast-publications/releases')
mode=os.X_OK if sys.argv[1]=='parent' else os.R_OK|os.X_OK
print(json.dumps({'read_traverse':all(os.access(p,mode) for p in paths),'write':any(os.access(p,os.W_OK) for p in paths)}))
"""

def access(pid,phase):
    need(phase in ('parent','directories'),'ACCESS_SCOPE')
    raw=command(['/usr/bin/nsenter','--target',str(pid),'--mount','--','/usr/bin/setpriv','--reuid=992','--regid=992','--clear-groups','--no-new-privs','/usr/bin/python3','-I','-S','-B','-c',PROBE,phase])
    value=json.loads(raw)
    need(type(value)is dict and set(value)=={'read_traverse','write'} and value['read_traverse'] is True and value['write'] is False,'CANDIDATE_DIRECTORY_ACCESS')
    need(candidate()==pid,'CANDIDATE_CHANGED')

def create_directory(path,mode,gid):
    global CHANGED
    need(path in {TOOLS_PARENT,TOOLS,TOOLS/'shared',ROOT,ROOT/'releases'},'WRITE_SCOPE')
    directory(path.parent)
    path.mkdir(mode=mode);CHANGED=True
    os.chown(path,0,gid,follow_symlinks=False);os.chmod(path,mode)
    directory(path,mode,gid);sync(path);sync(path.parent)

def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def system_executables():
    for binary in ('/usr/bin/systemctl','/usr/bin/nsenter','/usr/bin/setpriv','/usr/bin/python3'):
        p=Path(binary).resolve(strict=True);directory(p.parent);info=p.lstat()
        need(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'SYSTEM_EXECUTABLE')

def setup():
    global PHASE
    need(os.getuid()==os.geteuid()==0 and os.getgid()==os.getegid()==0,'ROOT_REQUIRED')
    need(set(CONFIG)=={'packet'},'CONFIG_SCOPE');files=packet(base64.b64decode(CONFIG['packet'],validate=True))
    directory(ROOT.parent);directory(TOOLS_PARENT.parent)
    system_executables()
    for p,mode,gid in ((TOOLS_PARENT,0o700,0),(ROOT,0o750,992),(ROOT/'releases',0o750,992)):
        if os.path.lexists(p):directory(p,mode,gid)
    if os.path.lexists(ROOT):need({p.name for p in ROOT.iterdir()}<= {'releases'},'NOT_FIRST_PUBLICATION')
    if os.path.lexists(ROOT/'releases'):need(not any((ROOT/'releases').iterdir()),'NOT_FIRST_PUBLICATION')
    reused=os.path.lexists(TOOLS)
    if reused:verify_tools(files)
    pid=candidate();access(pid,'parent') # Must pass before ANY creation.
    PHASE='SETUP'
    if not os.path.lexists(TOOLS_PARENT):create_directory(TOOLS_PARENT,0o700,0)
    if not reused:
        create_directory(TOOLS,0o700,0);create_directory(TOOLS/'shared',0o700,0)
        for name,raw in files.items():
            p=TOOLS/name;directory(p.parent,0o700,0)
            with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:
                os.fchmod(f.fileno(),0o600);f.write(raw);f.flush();os.fsync(f.fileno())
            need(read(p)==raw,'TOOLS_WRITE_VERIFY')
        sync(TOOLS/'shared');sync(TOOLS)
    verify_tools(files)
    for p in (ROOT,ROOT/'releases'):
        if not os.path.lexists(p):create_directory(p,0o750,992)
        directory(p,0o750,992)
    need(all(os.access(p,os.W_OK|os.X_OK) for p in (ROOT,ROOT/'releases')),'PUBLISHER_DIRECTORY_ACCESS')
    PHASE='ACCESS';access(pid,'directories')
    need(not os.path.lexists(ROOT/'current') and not any((ROOT/'releases').iterdir()),'NOT_FIRST_PUBLICATION')
    PHASE='COMPLETE'
    return {'status':'SETUP_READY','phase':PHASE,'changed':CHANGED,'tools':'REUSED' if reused else 'INSTALLED',
        'candidate_directory_access':'PASS','candidate_bundle_access':'UNVERIFIED_NO_BUNDLE',
        'publisher_directory_access':'PASS','active_pointer_absent':True,'publication_performed':False}

if __name__=='__main__':
    try:print(json.dumps(setup(),sort_keys=True))
    except Exception as e:
        reason=str(e) if type(e)is Stop else 'SETUP_CHECK_FAILED'
        print(json.dumps({'status':'PARTIAL' if CHANGED else 'BLOCKED','phase':PHASE,'changed':CHANGED,'reason':reason,'publication_performed':False}));raise SystemExit(1)
