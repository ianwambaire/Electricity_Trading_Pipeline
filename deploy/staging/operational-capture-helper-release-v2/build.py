"""Local immutable helper-only assembly. No SSH, install or activation."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import types
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
V5='cdd828defc52ea258852b88aa852d1d470ca915d098021d6ff8fd2be9b05223b'
CANDIDATE='435a85e89aaba277097d022ba640bc8195bd861121f0a58219669daff6d24298'
RELEASE='phase-operational-capture-helper-20261107-v2'
TRANSACTION='13ee1fecc7214ba789feb78af43f28b4'
NEW_ROOT='/opt/powerflow/operational-evidence-v2'
FILES={'build.py','run.py','preflight.py','transaction.py','REVIEW.md'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return json.dumps(value,sort_keys=True,indent=2).encode()+b'\n'
def read(path,limit=4*1024*1024):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK),'rb') as f:
        s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_size<=limit
        return f.read(limit+1)
def module(raw,name,path):
    m=types.ModuleType(name);m.__file__=str(path);exec(compile(raw,'<verified-'+name+'>','exec'),m.__dict__);return m

def baseline():
    folder=HERE.parent/'operational-evidence-release-v5';raw=read(folder/'MANIFEST.json');assert sha(raw)==V5
    old=json.loads(raw);runner=read(folder/'run.py');assert sha(runner)==old['artifacts']['deploy/staging/operational-evidence-release-v5/run.py']['sha256']
    v5=module(runner,'helper_baseline_runner',folder/'run.py');payload,wrapper,base=v5.verify(V5,'accept')
    return old,payload,wrapper,base

def config(old):
    folder=HERE.parent/'operational-capture-correction-v1';raw=read(folder/'MANIFEST.json');assert sha(raw)==CANDIDATE
    candidate=json.loads(raw)
    for rel,digest in candidate['files'].items():assert sha(read(ROOT/rel))==digest
    files={}
    for key,item in old['config']['files'].items():
        if key.startswith('helper/') and key!='helper/TOOLS.json':
            raw=read(ROOT/item['source']);assert sha(raw)==item['sha256'];files[key[7:]]=raw
    assert set(files)=={'bootstrap.py','shared/__init__.py','shared/forecast_publication.py','shared/operational_evidence.py','shared/operational_evidence_store.py','shared/operational_evidence_producer.py','shared/operational_capture.py'}
    before=files['bootstrap.py'];files['bootstrap.py']=before.replace(b'/opt/powerflow/operational-evidence-v1',NEW_ROOT.encode())
    assert before!=files['bootstrap.py'] and before.count(b'/opt/powerflow/operational-evidence-v1')==1
    files['shared/operational_evidence_producer.py']=read(folder/'operational_evidence_producer.py')
    files['TOOLS.json']=encode({k:sha(v) for k,v in files.items()})
    launcher=read(ROOT/old['config']['files']['launcher']['source']);rule=read(ROOT/old['config']['files']['sudoers']['source'])
    assert sha(launcher)==old['config']['files']['launcher']['sha256'] and sha(rule)==old['config']['files']['sudoers']['sha256']
    new_launcher=launcher.replace(b'/opt/powerflow/operational-evidence-v1',NEW_ROOT.encode());assert launcher.count(b'/opt/powerflow/operational-evidence-v1')==1
    new_rule=rule.replace(('sha256:'+sha(launcher)).encode(),('sha256:'+sha(new_launcher)).encode());assert new_rule!=rule
    assert new_rule.split(b' /usr/local/sbin/',1)[1]==rule.split(b' /usr/local/sbin/',1)[1]
    inventory={'helper/'+k:{'sha256':sha(v),'bytes':len(v),'base64':base64.b64encode(v).decode()} for k,v in files.items()}
    for k,v in [('launcher',new_launcher),('sudoers',new_rule)]:inventory[k]={'sha256':sha(v),'bytes':len(v),'base64':base64.b64encode(v).decode()}
    result={'release':RELEASE,'transaction':TRANSACTION,'new_root':NEW_ROOT,'old_root':'/opt/powerflow/operational-evidence-v1','control':'/var/lib/powerflow-staging/operational-helper-'+TRANSACTION,'v5_manifest':V5,'candidate_manifest':CANDIDATE,'old_files':{k:{a:old['config']['files'][k][a] for a in ['sha256','bytes','uid','gid','mode']} for k in ['launcher','sudoers']},'files':dict(sorted(inventory.items()))}
    result['binding']=sha(encode(result));return result

def assemble(action,old_payload,cfg,blobs):
    assert action in {'preflight','apply','rollback'}
    marker=b"ACCEPT=types.ModuleType('verified_accept');";assert old_payload.count(marker)==1
    text=old_payload.split(marker)[0]
    text+=b"HELPER=types.ModuleType('verified_helper_release')\nHELPER.__dict__.update(P=PREFLIGHT,OLD_PLAN=PLAN,OLD_CONFIG=CONFIG,BASE=BASE.__dict__,GUARD=GUARD.__dict__,OP=sys.modules['shared.operational_evidence'])\n"
    text+=b'HELPER.__dict__["C"]='+repr(cfg).encode()+b'\n'
    text+=b'exec(compile('+repr(blobs['preflight.py']).encode()+b",'<verified-helper-preflight>','exec'),HELPER.__dict__)\n"
    if action!='preflight':text+=b'exec(compile('+repr(blobs['transaction.py']).encode()+b",'<verified-helper-transaction>','exec'),HELPER.__dict__)\n"
    operation=b"HELPER.preflight_report()" if action=='preflight' else b'HELPER.'+action.encode()+b'()'
    text+=b"try:\n report="+operation+b"\nexcept Exception as error:\n reason=str(error) if isinstance(error,(PLAN.Stop,GUARD.Stop,HELPER.OP.InvalidEvidence)) else 'UNVERIFIED_HOST_OPERATION'\n if not __import__('re').fullmatch('[A-Z0-9_]{1,80}',reason):reason='UNVERIFIED_HOST_OPERATION'\n report={'status':'BLOCKED' if not getattr(HELPER,'CHANGED',False) else 'FAILED','phase':getattr(HELPER,'PHASE','READ_ONLY'),'changed':getattr(HELPER,'CHANGED',False),'reason':reason}\n report['error_class']=type(error).__name__ if type(error).__name__ in {'TypeError','AttributeError','NameError','OSError','FileNotFoundError','PermissionError','TimeoutError','ValueError','Stop','InvalidEvidence'} else 'UNCLASSIFIED'\n trace=error.__traceback__\n while trace:\n  if trace.tb_frame.f_code.co_filename in {'<verified-helper-preflight>','<verified-helper-transaction>'}:report.update(function=trace.tb_frame.f_code.co_name,line=trace.tb_lineno)\n  trace=trace.tb_next\nprint(json.dumps(report,sort_keys=True));raise SystemExit(0 if report['status']in {'PREFLIGHT_PASS','APPLIED','ROLLED_BACK'} else 1)\n"
    ast.parse(text,feature_version=(3,9));return text

def emit(outputs):
    # Check every existing output before creating any missing file. Never refresh
    # a changed immutable manifest or payload under an existing release identity.
    for path,raw in outputs.items():
        if os.path.lexists(path):assert read(path)==raw,'IMMUTABLE_RELEASE_DRIFT'
    for path,raw in outputs.items():
        if not os.path.lexists(path):
            with path.open('xb') as f:f.write(raw)

def main():
    old,payload,_,_=baseline();cfg=config(old);blobs={n:read(HERE/n) for n in FILES}
    artifacts={str((HERE/n).relative_to(ROOT)):sha(v) for n,v in blobs.items()}
    for rel in ['deploy/staging/operational-capture-correction-v1/MANIFEST.json','tests/test_operational_capture_helper_release_v2.py','tests/test_operational_capture_correction.py']:artifacts[rel]=sha(read(ROOT/rel))
    manifest={'version':1,'execution_authorized':False,'release':RELEASE,'transaction':TRANSACTION,'config':cfg,'artifacts':dict(sorted(artifacts.items())),'payloads':{}}
    outputs={}
    for action in ['preflight','apply','rollback']:
        raw=assemble(action,payload,cfg,blobs);assert len(raw)<4*1024*1024;outputs[HERE/(action+'.payload.py')]=raw;manifest['payloads'][action]={'sha256':sha(raw),'bytes':len(raw)}
    raw=encode(manifest);outputs[HERE/'MANIFEST.json']=raw;emit(outputs);print(json.dumps({'manifest_sha256':sha(raw),'release':RELEASE,'transaction':TRANSACTION,'files':len(cfg['files'])}))
if __name__=='__main__':main()
