"""Local reproducible assembly only. Does not execute the remote payload."""
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
    s=importlib.util.spec_from_file_location('local_acceptance_builder',HERE/'run.py');r=importlib.util.module_from_spec(s);s.loader.exec_module(r)
    blobs={name:(r.ROOT/name).read_bytes() for name in r.ARTIFACTS}
    if r.sha(blobs[r.ACTIVATION])!=r.ACTIVATION_SHA:raise ValueError('activation_binding')
    if r.sha(blobs[r.ORIGINAL])!=r.ORIGINAL_SHA:raise ValueError('original_manifest_hash')
    for name,item in json.loads(blobs[r.ORIGINAL])['artifacts'].items():
        if name not in blobs or len(blobs[name])!=item['bytes'] or r.sha(blobs[name])!=item['sha256']:raise ValueError('original_dependency_hash')
    m={'version':2,'supersedes_manifest_sha256':r.ORIGINAL_SHA,'activation_manifest_sha256':r.ACTIVATION_SHA,'artifacts':{name:{'bytes':len(raw),'sha256':r.sha(raw)} for name,raw in blobs.items()},'payload_sha256':r.sha(r.assemble(blobs))}
    raw=(json.dumps(m,sort_keys=True,indent=2)+'\n').encode();(HERE/'MANIFEST.json').write_bytes(raw)
    print(json.dumps({'manifest_sha256':r.sha(raw),'payload_sha256':m['payload_sha256'],'remote_attempts':0},indent=2))
if __name__=='__main__':main()
