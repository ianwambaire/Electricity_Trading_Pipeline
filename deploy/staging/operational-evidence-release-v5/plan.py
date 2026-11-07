"""Pure bounded transaction policy. No filesystem, process or network operations."""
import copy
import hashlib
import json
import re

RELEASE='phase-operational-evidence-20261107-v5'
TRANSACTION='4f6cf4afa15647b0b14d904b50379ef1'
DEPLOYMENT='47e5ef51-26d0-44b6-b119-2c40d0e77397'
FLAG='POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED'
FORECAST_FLAG='POWERFLOW_AUTO_PUBLICATION_ENABLED'
ROOT='/srv/powerflow/operational-publications'
ENV_KEY=b'POWERFLOW_OPERATIONAL_PUBLICATION_ROOT'
OLD_RELEASE='phase-api-body-bound-20261102-v2'
UNIT='powerflow-candidate-api.service'
class Stop(ValueError):pass

def need(ok,code):
    if not ok:raise Stop(code)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def variables(old):
    need(type(old)is dict and len(json.dumps(old))<=16384,'VARIABLE_BOUND')
    need(set(old)<={'env','command','working_dir','stream_output','name','labels'},'VARIABLE_SCOPE')
    env=old.get('env',{})
    need(type(env)is dict and all(type(k)is str and type(v)is str for k,v in env.items()),'ENV_SHAPE')
    need(not any(re.search(r'PASSWORD|SECRET|TOKEN|CREDENTIAL|ACCESS_KEY|API_KEY',k,re.I) for k in env),'SECRET_ENV_UNSUPPORTED')
    need(env.get(FORECAST_FLAG)=='true' and FLAG not in env,'FEATURE_FLAG_DRIFT')
    need(old.get('command') in (None,'') and old.get('working_dir','/home/ec2-user/Electricity_Trading_Pipeline')=='/home/ec2-user/Electricity_Trading_Pipeline','PROCESS_OVERRIDE')
    new=copy.deepcopy(old);new.setdefault('env',{})[FLAG]='true'
    return new

def environment(raw,expected):
    need(sha(raw)==expected and len(raw)<=65536,'ENV_BASELINE')
    need(not any(line.strip().startswith(ENV_KEY+b'=') for line in raw.splitlines()),'ENV_ALREADY_CONFIGURED')
    return raw+(b'' if raw.endswith(b'\n') else b'\n')+ENV_KEY+b'='+ROOT.encode()+b'\n'

def projection(d):
    # Exact deployment fields excluding only job_variables and server timestamps.
    fields=['id','name','entrypoint','path','paused','parameters','work_pool_name','work_queue_name','concurrency_options','global_concurrency_limit','schedules','tags','description','version','version_info','storage_document_id','infrastructure_document_id','enforce_parameter_schema','pull_steps']
    return {k:copy.deepcopy(d.get(k)) for k in fields}

def stable_projection(d):
    p=projection(d)
    # Queue counters/server-updated timestamps are not writable deployment policy.
    g=p.get('global_concurrency_limit') or {}
    p['global_concurrency_limit']={k:g.get(k) for k in ['id','name','limit','active']}
    p['schedules']=[{k:s.get(k) for k in ['id','active','schedule','parameters','slug']} for s in d.get('schedules',[])]
    return p

def record_valid(r,config):
    need(type(r)is dict and r.get('transaction')==config['transaction'] and r.get('release')==config['release'],'TRANSACTION_IDENTITY')
    need(r.get('phase') in {'BACKED_UP','INSTALL','ROUTING','POINTERS','ACTIVATE','APPLIED','ROLLBACK','ROLLED_BACK'},'TRANSACTION_PHASE')
    need(r.get('old_variables')is not None and variables(r['old_variables'])==r.get('new_variables'),'VARIABLE_BACKUP')
    need(set(r['backups'])==set(config['worker'])|{'api_env'}|({'nginx_config'} if 'nginx_before'in config else set()),'BACKUP_SCOPE')
    for key,value in r['backups'].items():
        expected=config['env_before'] if key=='api_env' else config['nginx_before'] if key=='nginx_config' else config['worker'][key]['before']
        need((value is None and expected is None) or value is not None and value['sha256']==expected,'BACKUP_BASELINE')
        need(value is None or set(value)=={'sha256','uid','gid','mode','bytes'},'BACKUP_SCHEMA')
        if value is not None:
            uid=0 if key in {'api_env','nginx_config'} else 1000;mode=0o600 if key=='api_env' else 0o644
            need((value['uid'],value['gid'],value['mode'])==(uid,uid,mode) and type(value['bytes'])is int and 0<=value['bytes']<=2000000,'BACKUP_METADATA')
    need(r['old_backend']==config['old_backend'] and r['old_static']==config['old_static'],'BACKUP_POINTERS')
    if 'nginx_before'in config:
        need(type(r.get('nginx_attempted',False))is bool,'NGINX_JOURNAL')
        need(type(r.get('retained_infrastructure'))is dict and r['retained_infrastructure'].get('reuse')is True,'RETAINED_JOURNAL')
        need(type(r.get('nginx_binary_sha256'))is str and re.fullmatch('[0-9a-f]{64}',r['nginx_binary_sha256'])is not None,'NGINX_EXECUTABLE_JOURNAL')
    return r
