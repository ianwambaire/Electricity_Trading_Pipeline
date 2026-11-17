"""Publication-only inspection. BASE/CONTRACT are injected verified stdlib code.
No application imports, model loading, inference, SQL, network or child processes.
"""
import json


def inspect(base,contract):
    result={'schema_version':1,'publication_state':'UNVERIFIED','chain':'UNVERIFIED',
            'contract':'UNVERIFIED','effective_candidate_access':'UNVERIFIED',
            'phase':'NONE','cause':'NONE','prediction_count':0}
    try:
        base['publication_metadata']()
        initial_target=base['os'].readlink(base['PUBLICATION']/'current')
        # Validate again before reading a selected artifact: a pointer switch
        # must never make the second target an unchecked traversal.
        base['publication_metadata']()
    except base['PublicationInspectionError'] as error:
        result.update(phase=error.phase,cause=error.cause)
        if error.cause=='MISSING_PATH':result['publication_state']='MISSING'
        elif error.cause in {'UNSAFE_METADATA','POINTER_ESCAPE','HASH_MISMATCH','MALFORMED_BUNDLE','POINTER_DRIFT'}:result['publication_state']='INVALID'
        return result
    except OSError:
        result.update(phase='POINTER_RECHECK',cause='IO_ERROR');return result
    result['chain']='PASS'
    try:
        root=base['PUBLICATION'];target=base['os'].readlink(root/'current')
        if initial_target is None or target!=initial_target:
            result.update(phase='POINTER_RECHECK',cause='POINTER_DRIFT');return result
        if base['re'].fullmatch(r'releases/[0-9a-f]{64}',target) is None:raise ValueError('pointer')
        raw=base['read'](root/target/'bundle.json',contract['MAX_BYTES'])
        digest=target.split('/')[1]
        # Validate at actual UTC, never backdate an expired forecast. The contract
        # checks structure, identity and all feature completeness before expiry.
        try:contract['validate'](raw,digest)
        except contract['ExpiredPublication']:
            result.update(publication_state='EXPIRED',contract='PASS',prediction_count=24)
        else:result.update(publication_state='VALID',contract='PASS',prediction_count=24)
        if base['os'].readlink(root/'current')!=target:
            result.update(publication_state='UNVERIFIED',contract='UNVERIFIED',prediction_count=0,phase='POINTER_RECHECK',cause='POINTER_DRIFT')
    except contract['Withheld']:
        result.update(publication_state='INVALID',contract='FAIL',phase='BUNDLE_FORMAT',cause='CONTRACT_REJECTED')
    except Exception:
        result.update(publication_state='UNVERIFIED',contract='UNVERIFIED',phase='BUNDLE_READ',cause='READ_OR_VALIDATION_UNVERIFIED')
    return result


def validate_report(value):
    keys={'schema_version','publication_state','chain','contract','effective_candidate_access','phase','cause','prediction_count'}
    if type(value)is not dict or set(value)!=keys or type(value['schema_version'])is not int or value['schema_version']!=1:raise ValueError('report_schema')
    if value['publication_state'] not in {'VALID','EXPIRED','MISSING','INVALID','UNVERIFIED'}:raise ValueError('state')
    if value['chain'] not in {'PASS','UNVERIFIED'} or value['contract'] not in {'PASS','FAIL','UNVERIFIED'} or value['effective_candidate_access']!='UNVERIFIED':raise ValueError('evidence')
    phases={'NONE','ANCESTRY','ROOT','RELEASES','POINTER','TARGET','BUNDLE_METADATA','BUNDLE_READ','BUNDLE_HASH','BUNDLE_FORMAT','POINTER_RECHECK'}
    causes={'NONE','MISSING_PATH','PERMISSION_DENIED','IO_ERROR','UNSAFE_METADATA','POINTER_ESCAPE','HASH_MISMATCH','MALFORMED_BUNDLE','POINTER_DRIFT','UNEXPECTED_ERROR','CONTRACT_REJECTED','READ_OR_VALIDATION_UNVERIFIED'}
    if value['phase'] not in phases or value['cause'] not in causes or type(value['prediction_count'])is not int or value['prediction_count'] not in (0,24):raise ValueError('diagnostic')
    if value['publication_state'] in {'VALID','EXPIRED'}:
        if (value['chain'],value['contract'],value['prediction_count'],value['cause'])!=('PASS','PASS',24,'NONE'):raise ValueError('contradiction')
    elif value['contract']=='PASS' or value['prediction_count']!=0:raise ValueError('contradiction')
    return value


if __name__=='__main__':
    try:
        report=validate_report(inspect(BASE,CONTRACT))
        print(json.dumps(report,sort_keys=True))
        raise SystemExit(0 if report['publication_state']=='VALID' else 1)
    except Exception:
        print('{"diagnostic_failed":true}')
        raise SystemExit(1)
