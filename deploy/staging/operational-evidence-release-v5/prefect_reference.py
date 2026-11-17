"""Independent PyPI reference verification. No installation or SDK execution."""
import ast
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import zipfile

ROOT=Path(__file__).resolve().parents[3]
WHEEL=ROOT/'data/backups/private-staging-releases/phase-forecast-consistency-20261101-v1/preflight/prefect-implementation-wdw123f9/reference-prefect-3.7.5.whl'
WHEEL_SHA='214837b7cb1e10f8fec59018253cd8ef65c8b394b7df29c511b645b0ff5e4478'
FILES=['prefect/workers/base.py','prefect/flow_engine.py','prefect-3.7.5.dist-info/METADATA']
def sha(raw):return hashlib.sha256(raw).hexdigest()
def need(ok,code):
    if not ok:raise ValueError(code)
def sources():
    fd=os.open(WHEEL,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        need(stat.S_ISREG(os.fstat(f.fileno()).st_mode),'REFERENCE_FILE_TYPE');raw=f.read(32000001)
    need(len(raw)==14766992 and sha(raw)==WHEEL_SHA,'REFERENCE_WHEEL_HASH')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist();need(len(names)==len(set(names)),'REFERENCE_DUPLICATE_MEMBER')
        data={name:z.read(name) for name in FILES}
        entries={}
        for row in csv.reader(io.StringIO(z.read('prefect-3.7.5.dist-info/RECORD').decode())):
            if row and row[0] in FILES:
                need(len(row)==3 and row[0]not in entries,'REFERENCE_RECORD_SCHEMA');entries[row[0]]=row
        for name,content in data.items():
            row=entries[name];digest='sha256='+base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()
            need(row[1]==digest and row[2]==str(len(content)),'REFERENCE_RECORD_HASH')
    return data
def methods(raw):
    tree=ast.parse(raw);result={}
    for cls in tree.body:
        if isinstance(cls,ast.ClassDef) and cls.name in {'FlowRunEngine','AsyncFlowRunEngine'}:
            for node in cls.body:
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'set_state','call_hooks'}:
                    result[cls.name+'.'+node.name]=ast.dump(node,include_attributes=False)
                    if node.name=='set_state':
                        code=ast.unparse(node)
                        need(code.index('propose_state')<code.index('call_hooks'),'REFERENCE_TERMINAL_HOOK_ORDER')
                        need('self.flow_run.end_time ='not in code,'REFERENCE_HOOK_TIMESTAMP')
    need(len(result)==4,'REFERENCE_TERMINAL_METHODS')
    return result
def load():
    data=sources();methods(data['prefect/flow_engine.py'])
    expected={'version':'3.7.5','metadata_url':'https://pypi.org/pypi/prefect/3.7.5/json','wheel_sha256':WHEEL_SHA,'wheel_bytes':14766992,
              'requires_python':'<3.15,>=3.10','files':{k:sha(v) for k,v in data.items()}}
    need((Path(__file__).parent/'PREFECT-REFERENCE.json').read_bytes()==(json.dumps(expected,sort_keys=True,indent=2)+'\n').encode(),'REFERENCE_PROJECTION')
    return expected
