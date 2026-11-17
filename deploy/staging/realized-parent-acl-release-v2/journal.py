"""Pure shared journal contract, present in preflight without any mutation code."""
JOURNAL_PHASES={'BACKED_UP','CHANGING_ACL','APPLIED','ROLLING_BACK','ROLLED_BACK'}

def valid_record(record,config=None):
    config=C if config is None else config
    need(type(record)is dict and set(record)=={'version','release','transaction','journal_binding','phase','snapshot_sha256','planned_text','after_access_raw'},'JOURNAL_SCHEMA')
    need(type(record['version'])is int and record['version']==1,'JOURNAL_VERSION')
    need((record['release'],record['transaction'],record['journal_binding'])==(config['release'],config['transaction'],config['journal_binding'])and record['phase']in JOURNAL_PHASES,'JOURNAL_IDENTITY')
    need(type(record['snapshot_sha256'])is str and re.fullmatch('[0-9a-f]{64}',record['snapshot_sha256'])is not None,'JOURNAL_SNAPSHOT_HASH')
    parse(record['planned_text'])
    need(record['after_access_raw']is None or type(record['after_access_raw'])is str,'JOURNAL_AFTER_ACL')
    return record

def load_record(raw,config=None):
    def pairs(items):
        out={}
        for key,value in items:need(key not in out,'JOURNAL_DUPLICATE_FIELD');out[key]=value
        return out
    def invalid(_):raise Stop('JOURNAL_JSON_INVALID')
    need(type(raw)is bytes and 0<len(raw)<=256*1024,'JOURNAL_JSON_BOUND')
    try:value=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
    except (ValueError,UnicodeError)as error:
        if isinstance(error,Stop):raise
        raise Stop('JOURNAL_JSON_INVALID')from None
    return valid_record(value,config)

def make_record(before,proposed,config=None):
    config=C if config is None else config
    need(proposed==plan(before['parent']['access_text'],before['worker_groups']),'JOURNAL_PLAN_INCONSISTENT')
    value={'version':1,'release':config['release'],'transaction':config['transaction'],'journal_binding':config['journal_binding'],'phase':'BACKED_UP','snapshot_sha256':sha(encode(before)),'planned_text':proposed,'after_access_raw':None}
    return valid_record(value,config)

def verify_rollback_readiness(before,proposed):
    # Use the actual immutable apply/rollback configurations embedded by builder,
    # not a synthetic identity derived from the current action's response binding.
    apply_config=JOURNAL_APPLY_CONFIG;rollback_config=JOURNAL_ROLLBACK_CONFIG
    need(apply_config['action']=='apply'and rollback_config['action']=='rollback','JOURNAL_ACTION_CONTRACT')
    for key in ['release','transaction','journal_binding','control']:
        need(C[key]==apply_config[key]==rollback_config[key],'JOURNAL_COMPATIBILITY')
    need(apply_config['binding']!=rollback_config['binding'],'RESPONSE_ACTION_BINDING_COLLISION')
    generated=make_record(before,proposed,apply_config)
    for phase in ['BACKED_UP','CHANGING_ACL','APPLIED']:
        generated['phase']=phase
        accepted=load_record(encode(generated),rollback_config)
        need(accepted==generated,'JOURNAL_COMPATIBILITY')
    return True
