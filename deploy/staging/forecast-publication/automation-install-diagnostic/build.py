"""Build this diagnostic manifest locally; original deployment remains unchanged."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def main():
    ns={'__name__':'build_library','__file__':str(HERE/'run.py')};exec(compile((HERE/'run.py').read_bytes(),'<local-build>','exec'),ns)
    config,_=ns['original']();blobs={n:ns['read'](ns['ROOT']/n) for n in ns['ARTIFACTS']}
    manifest={'version':1,'original_manifest_sha256':ns['ORIGINAL_SHA'],'transaction':ns['TRANSACTION'],'artifacts':{n:{'bytes':len(raw),'sha256':ns['sha'](raw)} for n,raw in blobs.items()},'remote_payload_sha256':ns['sha'](ns['assemble'](blobs[ns['PREFIX']+'inspect.py'],config))}
    raw=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode();(HERE/'MANIFEST.json').write_bytes(raw)
    print(json.dumps({'diagnostic_manifest_sha256':hashlib.sha256(raw).hexdigest(),'assembled_payload_sha256':manifest['remote_payload_sha256'],'runner_sha256':ns['sha'](blobs[ns['PREFIX']+'run.py'])},indent=2))
if __name__=='__main__':main()
