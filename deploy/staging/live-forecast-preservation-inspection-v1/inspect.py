"""Read-only component comparison, never an acceptance-policy override."""
import datetime as dt
import json
from pathlib import Path
import re
import sys
import types

KEYS=('production','forecast','store','helper','policy','environment','nginx')
STAGE='INITIAL'
def compare(before,after):
    need(type(before)is dict and type(after)is dict and set(before)==set(after)==set(KEYS),'PRESERVATION_SCHEMA')
    return {k:'MATCH' if before[k]==after[k] else 'DIFFERENT' for k in KEYS}

def legacy_hashes(files,bundle,expected):
    # Existing receipt validator verifies model/features, artifacts and exact bundle
    # reconstruction at actual UTC; typed historical expiry is not backdated.
    producer=sys.modules['shared.operational_evidence_producer']
    reconstructed,digest=producer.receipt_bundle(files,dt.datetime.now(dt.timezone.utc))
    need(digest==expected and reconstructed==bundle,'BASELINE_RECEIPT_ASSOCIATION')
    provenance=json.loads(files['provenance.json']);need('inference_evidence'in provenance,'BASELINE_RECEIPT_SCHEMA')
    provenance.pop('inference_evidence')
    order=('forecast_issue_time','market_latest_complete_hour','weather_hour','weather_acquired_at_utc','weather_source','historical_weather_source','weather_endpoint','weather_note')
    need(set(provenance)==set(order),'BASELINE_LEGACY_PROVENANCE_SCHEMA')
    provenance={key:provenance[key] for key in order}
    return {'data/reports/next24h_forecast.csv':JOB.sha(files['forecast.csv']),
            'data/reports/next24h_forecast_provenance.json':JOB.sha((json.dumps(provenance,indent=2)+'\n').encode())}

def historical_output_hashes(fingerprint):
    need(type(fingerprint)is dict and re.fullmatch(r'releases/[0-9a-f]{64}',fingerprint.get('pointer','')or'')is not None,'BASELINE_FORECAST_POINTER')
    digest=fingerprint['pointer'].split('/')[1];need(fingerprint.get('bundle')==digest,'BASELINE_FORECAST_HASH')
    root=Path('/srv/powerflow/forecast-publications');folder=root/fingerprint['pointer']
    for path in [root,root/'releases',folder]:JOB.P.safe(path)
    raw=JOB.B['read'](folder/'bundle.json',100000);need(JOB.sha(raw)==digest,'BASELINE_FORECAST_HASH')
    bundle=json.loads(raw);run_id=bundle['execution']['run_id'];JOB.H.OP.identifier(run_id)
    capture=sys.modules['shared.operational_capture'];source=capture.Source()
    receipt=source.root/'data/reports/next24h_inference'/run_id
    files={name:source.file(receipt,name) for name in ('forecast.csv','provenance.json','model.json','evidence.json','integrity.json')}
    return legacy_hashes(files,bundle,digest)

def replay_production(expected_hash,outputs):
    need(set(outputs)=={'data/reports/next24h_forecast.csv','data/reports/next24h_forecast_provenance.json'} and all(re.fullmatch('[0-9a-f]{64}',v) for v in outputs.values()),'REPLAY_SCOPE')
    original=JOB.B['digest'];seen=set()
    prefix=Path('/home/ec2-user/Electricity_Trading_Pipeline')
    replacements={prefix/k:v for k,v in outputs.items()}
    def digest(path):
        actual=original(path) # Original bounded no-follow NOATIME read still runs.
        if path in replacements:
            seen.add(path);return replacements[path]
        return actual
    JOB.B['digest']=digest
    try:reconstructed=JOB.P.production()
    finally:JOB.B['digest']=original
    need(seen==set(replacements),'REPLAY_INCOMPLETE')
    return 'MATCH_EXCEPT_PIPELINE_OUTPUTS' if reconstructed==expected_hash else 'UNRESOLVED_PRODUCTION_DIFFERENCE'

def reconstruct_store(expected_hash,activated_at,inventory,records):
    cutoff=JOB.H.OP.timestamp(activated_at)
    need(set(inventory)=={'contract','current','releases'} and set(records)==set(inventory['releases']),'STORE_REPLAY_SCHEMA')
    old={k:v for k,v in inventory['releases'].items() if JOB.H.OP.timestamp(records[k]['observed_at'])<=cutoff}
    for pointer in [None]+sorted(old):
        candidate={'contract':inventory['contract'],'current':pointer,'releases':old}
        if JOB.sha(json.dumps(candidate,sort_keys=True).encode())==expected_hash:
            return 'BASELINE_RECONSTRUCTED_SUBSET'
    return 'UNRESOLVED_STORE_DIFFERENCE'

def store_history(expected,activated_at):
    # store_snapshot has already verified exact inventory, ownership, permissions,
    # file hashes, contract and each evidence record; retain those same checks.
    root=JOB.P.STORE;_,raw=JOB.P.snap(root/'contract',0,992,0o640)
    inventory={'contract':JOB.sha(raw),'current':None,'releases':{}};records={}
    entries=JOB.H.entries(root/'releases',256)
    for folder in entries:
        need(re.fullmatch('[0-9a-f]{64}',folder.name)is not None,'STORE_RELEASE_ID')
        meta,raw=JOB.P.snap(folder/'evidence.json',0,992,0o640)
        record=JOB.H.OP.validate(raw,folder.name,dt.datetime.now(dt.timezone.utc))
        inventory['releases'][folder.name]=meta['sha256'];records[folder.name]=record
    if (root/'current').exists():
        _,raw=JOB.P.snap(root/'current',0,992,0o640);need(re.fullmatch(b'[0-9a-f]{64}\n',raw)is not None,'STORE_POINTER')
        inventory['current']=raw.decode().strip();need(inventory['current']in records,'STORE_POINTER_TARGET')
    need(JOB.sha(json.dumps(inventory,sort_keys=True).encode())==JOB.H.store_snapshot(),'STORE_SNAPSHOT_CHANGED')
    return reconstruct_store(expected,activated_at,inventory,records)

def inspect():
    global STAGE
    STAGE='IDLE_WINDOW';JOB.P.idle(0)
    STAGE='JOURNAL';r=JOB.load_record();need(r['phase']=='APPLIED' and r['activated_at'],'TRANSACTION_NOT_APPLIED');JOB.verified_backups(r)
    STAGE='IMMUTABLE_ASSETS';JOB.old_trees();JOB.tree_state(r,complete=True);JOB.G['runtime'](JOB.API);JOB.P.candidate_environment(True)
    need(JOB.P.BACKEND_LINK.resolve(strict=True)==JOB.API and JOB.P.STATIC_LINK.resolve(strict=True)==JOB.STATIC,'ACTIVE_POINTERS')
    need(JOB.P.runtime_closure(Path(r['baseline']['venv']))==r['baseline']['runtime'],'RUNTIME_CHANGED')
    STAGE='COMPONENTS';before={k:v for k,v in r['baseline'].items()if k not in {'venv','runtime'}};after=JOB.baseline_preservation();result=compare(before,after)
    report={'status':'PASS','changed':False,'stage':STAGE,'protected_assets':'MATCH','runtime':'MATCH',**result,
            'production_resolution':'MATCH' if result['production']=='MATCH' else 'UNRESOLVED_PRODUCTION_DIFFERENCE',
            'store_resolution':'MATCH' if result['store']=='MATCH' else 'UNRESOLVED_STORE_DIFFERENCE'}
    if result['production']=='DIFFERENT':
        STAGE='PRODUCTION_REPLAY';outputs=historical_output_hashes(before['forecast']);report['production_resolution']=replay_production(before['production'],outputs)
    if result['store']=='DIFFERENT':
        STAGE='STORE_REPLAY';report['store_resolution']=store_history(before['store'],r['activated_at'])
    STAGE='STABILITY';need(after==JOB.baseline_preservation(),'SNAPSHOT_CHANGED');JOB.P.idle(0)
    report['stage']='COMPLETE';return report
