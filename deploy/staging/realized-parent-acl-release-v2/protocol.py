"""Strict source-bound sanitized result schema; no raw diagnostics retained."""
import json
import re

SUCCESS={'preflight':'PREFLIGHT_PASS','apply':'APPLIED','rollback':'ROLLED_BACK'}
PHASES={'READ_ONLY','BACKED_UP','CHANGING_ACL','APPLIED','ROLLING_BACK','ROLLED_BACK'}

def decode(raw,code,config,reasons):
    def require(ok):
        if not ok:raise ValueError('RESPONSE_UNVERIFIED')
    def pairs(rows):
        out={}
        for key,value in rows:require(key not in out);out[key]=value
        return out
    require(type(raw)is bytes and 0<len(raw)<=8192 and type(code)is int)
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False))
    require(type(value)is dict and set(value)=={'version','release','transaction','binding','action','report'})
    require(type(value['version'])is int and value['version']==1)
    for key in ['release','transaction','binding','action']:require(value[key]==config[key])
    report=value['report'];require(type(report)is dict)
    if report.get('status')=='BLOCKED':
        require(set(report)=={'status','phase','changed','reason','exception_category','errno'})
        require(report['phase']in PHASES and type(report['changed'])is bool)
        require(type(report['reason'])is str and report['reason']in reasons|{'FILESYSTEM_OPERATION_FAILED','UNVERIFIED_OPERATION'})
        require(report['exception_category']in{'OS_ERROR','VALIDATION_ERROR','OTHER_ERROR'})
        require(report['errno']is None or type(report['errno'])is int and report['errno']in {1,2,13,20,38,40,61,95})
        require(code==1)
    else:
        require(set(report)=={'status','phase','changed','reason','target_uid','owner_group_mode_preserved','mask_preserved','protected_boundaries_denied','rollback_ready'})
        action=config['action'];require(report['status']==SUCCESS[action]and code==0)
        require(report['phase']==('READ_ONLY'if action=='preflight'else SUCCESS[action]))
        require(type(report['changed'])is bool and report['changed']==(action!='preflight'))
        require(type(report['target_uid'])is int and report['target_uid']==1000)
        require(report['reason']=={'preflight':'ACL_SEARCH_ONLY_PLAN_VERIFIED','apply':'UID_SEARCH_ONLY_GRANTED','rollback':'EXACT_ORIGINAL_ACL_RESTORED'}[action])
        for key in ['owner_group_mode_preserved','mask_preserved','protected_boundaries_denied','rollback_ready']:require(report[key]is True)
    if config['action']=='preflight':require(report['changed']is False and report['phase']=='READ_ONLY')
    return report
