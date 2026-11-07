"""Reconstruct only the approved historical static baseline; no host observations."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROOT=Path(__file__).resolve().parents[3]
RECORD=ROOT/'data/backups/private-staging-releases/phase-forecast-consistency-20261101-v1/preflight/historical-record-nd87_fm9/transaction-record.json'
RECORD_SHA='b37d5e173ab58a1690f9fee22c3a40d4dbb346427326772934617771fbac3e11'
APPROVED=ROOT/'data/backups/private-staging-releases/phase-api-body-bound-20261102-v2/release/release-manifest.json'
APPROVED_SHA='dc2fd9aa9cb0e961fd3859aa63b946a307c43f8a31ed6d8ac0ef4529c32f2045'
TRANSACTION='f2f195174eda43daa8e5593087fbe1d3'
STATIC='/var/www/powerflow-staging/releases/phase-api-body-bound-20261102-v2'
REMOTE_RECORD='/var/lib/powerflow-staging/forecast-consistency-transactions/'+TRANSACTION+'/state.json'

def need(ok,reason):
    if not ok:raise ValueError(reason)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def unique(pairs):
    result={}
    for k,v in pairs:
        need(k not in result,'DUPLICATE_KEY');result[k]=v
    return result
def parse(raw):return json.loads(raw,object_pairs_hook=unique)
def path_ok(name):
    return type(name)is str and len(name)<=200 and re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',name)is not None and all(p not in {'.','..'} for p in name.split('/'))
def inventory(value):
    need(type(value)is dict and len(value)<=160,'INVENTORY_BOUND')
    need(all(path_ok(k) and type(v)is str and re.fullmatch('[0-9a-f]{64}',v) for k,v in value.items()),'INVENTORY_SCHEMA')
    return dict(sorted(value.items()))
def merge(approved,retained):
    approved=inventory(approved);retained=inventory(retained)
    need(all(k not in approved or approved[k]==v for k,v in retained.items()),'RETAINED_HASH_CONFLICT')
    return dict(sorted({**retained,**approved}.items()))
def reconstruct(record_raw,approved_raw):
    need(sha(record_raw)==RECORD_SHA,'HISTORICAL_RECORD_HASH')
    need(sha(approved_raw)==APPROVED_SHA,'APPROVED_MANIFEST_HASH')
    record=parse(record_raw);release=parse(approved_raw)
    need(record.get('transaction_id')==TRANSACTION and record.get('phase')=='COMPLETE' and record.get('new_static')==STATIC and record.get('version')==1,'HISTORICAL_IDENTITY')
    need(type(record.get('previous_static'))is str and sha(record['previous_static'].encode())=='4d9590d765bc745f120412525ed0d117d251236d278234aada2433d0f97ad374','HISTORICAL_PREDECESSOR')
    approved=inventory({k[7:]:v['sha256'] for k,v in release['files'].items() if k.startswith('static/')})
    retained=inventory(record.get('retained_assets'));previous=inventory(record.get('old_static_files'))
    derived={k:v for k,v in previous.items() if re.fullmatch(r'assets/[A-Za-z0-9._-]+\.(js|css|woff2)',k)}
    need(derived==retained and len(retained)==31 and len(approved)==37,'RETAINED_MAPPING')
    need(len(approved.keys()&retained.keys())==6,'RETAINED_OVERLAPS')
    combined=merge(approved,retained);need(len(combined)==62,'BASELINE_COUNT')
    return {'version':1,'historical_transaction':TRANSACTION,'historical_record_sha256':RECORD_SHA,'approved_release_manifest_sha256':APPROVED_SHA,'static_root':STATIC,'retained_assets':retained,'static_inventory':combined}
def load():
    s=RECORD.lstat();parent=RECORD.parent.stat()
    need(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o600 and stat.S_IMODE(parent.st_mode)==0o700,'PRIVATE_RECORD_METADATA')
    fd=os.open(RECORD,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:raw=f.read(131073)
    need(len(raw)<=131072,'HISTORICAL_RECORD_BOUND')
    return reconstruct(raw,APPROVED.read_bytes())
def validate_copies(config):
    base=inventory(config['old_static_inventory']);destinations=set()
    for key,item in config['files'].items():
        need(path_ok(key),'RELEASE_PATH');need(item['destination']not in destinations,'DUPLICATE_DESTINATION');destinations.add(item['destination'])
        if 'copy_from' not in item:continue
        need(key.startswith('static/'),'COPY_SCOPE');rel=key[7:]
        need(item['copy_from']==STATIC+'/'+rel and base.get(rel)==item['sha256'],'COPY_BINDING')
        need(item['uid']==item['gid']==0 and item['mode']==0o644,'COPY_METADATA')
        if item['bytes'] is None:need(item.get('max_bytes')==2000000,'COPY_SIZE_BOUND')
