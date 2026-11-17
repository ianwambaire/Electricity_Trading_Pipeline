#!/usr/bin/env python3
"""Local-only proposal builder. A successful inspection is evidence, not upload approval."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
COUNTS={'pipeline_runs':891,'data_quality_results':16525,'operational_incidents':1485,'pipeline_stage_timings':11561}

def prepare(inspection,approved,previous):
    assert inspection['status']=='complete' and not inspection['errors'] and inspection['read_only']
    rows=inspection['files'];plan=approved['publication_plan']
    assert len(rows)==len(plan)==13
    by_name={r['relative_path']:r for r in rows}
    assert len(by_name)==13 and set(by_name)=={x['relative_path'] for x in plan}
    old_summaries={r['relative_path']:r.get('summary',{}) for r in previous['sources']}
    result={'status':'verified_remote_observations_PROPOSED_not_approved','source_root':previous['source_root'],
            'as_of_utc':inspection['as_of_utc'],'sources':[],'publication_authorized':False,'changes':[]}
    for item in plan:
        row=by_name[item['relative_path']];metadata=row['metadata']
        assert row['source']==item['source'] and row['previous_sha256']==item['sha256']
        assert row['stable_during_hash'] and row['stable_across_inspection'] and row['recheck']['stable_during_hash']
        assert row['recheck']['sha256']==row['sha256'] and row['bytes_hashed']==metadata['bytes']
        assert re.fullmatch('[a-f0-9]{64}',row['sha256']) and 0<metadata['bytes']<=128*1024**2
        assert metadata['regular'] and not metadata['symlink']
        assert (metadata['uid'],metadata['gid'],int(metadata['mode'],8))==(item['uid'],item['gid'],item['mode'])
        if item['relative_path']=='database/electricity_trading.db':
            assert row['sha256']==item['sha256'] and metadata['bytes']==item['bytes']
            db=row['sqlite'];assert db['integrity_ok'] and db['foreign_key_violation_count']==0
            assert db['required_tables_present'] and db['counts']==COUNTS and db['counts_match_A1']
            assert not any(x['exists'] for x in db['sidecars'].values())
            result['snapshot_metadata']=metadata
            result['snapshot_hash']={'sha256':row['sha256'],'stable_during_hash':True,'bytes_hashed':metadata['bytes']}
            result['snapshot_read']=db
        else:
            summary=row['summary'];assert summary['stable_during_summary'] and not summary['sensitivity_review_required']
            assert summary['status'] in ('aggregate_only','parsed_metadata_only')
            assert summary.get('invalid_timestamp_rows',0)==0
            result['sources'].append({'relative_path':item['relative_path'],'metadata':metadata,'sha256':row['sha256'],
                                     'stable_during_hash':True,'bytes_hashed':metadata['bytes'],'summary':summary})
        if row['sha256']!=item['sha256']:
            result['changes'].append({'relative_path':item['relative_path'],'previous_sha256':item['sha256'],
                'current_sha256':row['sha256'],'previous_metadata':row['previous_metadata'],'current_metadata':metadata,
                'previous_summary':old_summaries.get(item['relative_path']),'current_summary':row.get('summary'),
                'interpretation':'Consistent with scheduled pipeline rewrite; exact historic value differences and production execution causality unverified'})
    result['limitations']=['No simultaneous cross-file producer transaction established','Silver value changes and anomaly reclassification inferred, not independently reproduced','These hashes are verified observations, not authorization to publish them; source drift guards remain mandatory']
    return result

if __name__=='__main__':
    source=Path(sys.argv[1]);approved=json.loads((ROOT/'deploy/staging/install-package/BUNDLE-MANIFEST.json').read_bytes())
    previous=json.loads((ROOT/'deploy/staging/PUBLICATION-PREFLIGHT-RESULTS.json').read_bytes())
    result=prepare(json.loads(source.read_bytes()),approved,previous)
    result['inspection_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    with Path(sys.argv[2]).open('x') as h:json.dump(result,h,indent=2);h.write('\n')
