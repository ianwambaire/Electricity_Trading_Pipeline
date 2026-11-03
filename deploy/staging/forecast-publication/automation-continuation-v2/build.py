"""Explicit local manifest generation; no network, execution or existing-release edits."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
def digest(raw):return hashlib.sha256(raw).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--transaction',required=True);a=p.parse_args()
    if not re.fullmatch('[0-9a-f]{32}',a.transaction):raise ValueError('transaction')
    ns={'__name__':'local_package_builder','__file__':str(HERE/'run.py')};exec(compile((HERE/'run.py').read_bytes(),'<local-runner>','exec'),ns)
    root=ns['ROOT'];source=Path(root/'deploy/staging/forecast-publication/AUTOMATION-SOURCE-MANIFEST.json')
    meta=json.loads(source.read_bytes())
    for name,item in meta['sources'].items():
        raw=(root/name).read_bytes()
        if digest(raw)!=item['sha256'] or len(raw)!=item['bytes']:raise ValueError('automation_source_hash')
    blobs={n:(root/n).read_bytes() for n in ns['ARTIFACTS']}
    files={key:{'base64':base64.b64encode(blobs[name]).decode(),'bytes':len(blobs[name]),'sha256':digest(blobs[name])} for key,name in ns['SOURCES'].items()}
    original_config=ns['verify_original']()
    if a.transaction in {ns['ORIGINAL_TRANSACTION'],ns['PRIOR_TRANSACTION']}:raise ValueError('consumed_transaction')
    config={'transaction':a.transaction,'files':files,'installed_tools':meta['installed_tools'],'pipeline_before':'571e3b56c34bc17a38dc13bad066def40c9c711bf51f74aff466014b9afcce8b','worker_base_sha256':original_config['worker_base_sha256'],'original_manifest_sha256':ns['ORIGINAL_SHA'],'original_transaction':ns['ORIGINAL_TRANSACTION'],'prior_manifest_sha256':ns['PRIOR_SHA'],'prior_transaction':ns['PRIOR_TRANSACTION'],'original_packet':meta['unchanged_first_tools_archive_sha256'],'original_tools':original_config['original_tools']}
    m={'version':1,'artifacts':{n:{'bytes':len(raw),'sha256':digest(raw)} for n,raw in blobs.items()},'config':config,'payload_sha256':{action:digest(ns['assemble'](blobs,config,action)) for action in ['preflight','apply','rollback']}}
    (HERE/'MANIFEST.json').write_text(json.dumps(m,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'manifest_sha256':digest((HERE/'MANIFEST.json').read_bytes()),'payload_sha256':m['payload_sha256'],'transaction':a.transaction},indent=2))
if __name__=='__main__':main()
