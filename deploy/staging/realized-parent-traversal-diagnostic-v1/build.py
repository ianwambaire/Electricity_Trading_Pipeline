"""One-shot immutable local assembly; no connection or privileged execution."""
import ast
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def main():
    spec=importlib.util.spec_from_file_location('traversal_builder_runner',HERE/'run.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    blobs={path:r.read(r.ROOT/path)for path in r.ARTIFACTS};_,_,_,bounded=r.references(blobs)
    payload=r.assemble(blobs,bounded);ast.parse(payload,feature_version=(3,9));r.need(len(payload)<65536)
    m={'version':1,'release':r.RELEASE,'execution_authorized':False,'origin_manifest':r.ORIGIN_SHA,'connectivity_manifest':r.CONNECT_SHA,'limits':r.LIMITS,'remote_command':r.REMOTE,'artifacts':{p:{'bytes':len(raw),'sha256':r.sha(raw)}for p,raw in sorted(blobs.items())},'payload':{'bytes':len(payload),'sha256':r.sha(payload)}}
    raw=json.dumps(m,sort_keys=True,indent=2).encode()+b'\n';outputs={HERE/'MANIFEST.json':raw,HERE/'inspect.payload.py':payload}
    for p,value in outputs.items():
        if p.exists():r.need(r.read(p)==value)
    for p,value in outputs.items():
        if not p.exists():
            with p.open('xb')as f:f.write(value)
    print(json.dumps({'manifest_sha256':r.sha(raw),'payload_sha256':r.sha(payload),'runner_sha256':r.sha(blobs[str((HERE/'run.py').relative_to(r.ROOT))]),'ssh_attempts':0},sort_keys=True))
if __name__=='__main__':main()
