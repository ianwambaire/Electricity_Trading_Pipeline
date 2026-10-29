"""Proposed staging-only atomic release-pointer hotfix; separate approval required."""
import base64,hashlib,json,os,pathlib,stat,subprocess,sys,time,urllib.request
BASE=pathlib.Path('/opt/powerflow/releases/phase-staging-https-ready-20261026')
NEW=pathlib.Path(str(BASE)+'-context-hotfix-20261029')
LINK=pathlib.Path('/opt/powerflow/react-current')
UNIT='powerflow-candidate-api.service'
SERVICES=['powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service']
PRESERVED=['/etc/nginx/conf.d/powerflow.conf','/etc/nginx/conf.d/powerflow-staging-http.conf','/etc/nginx/conf.d/powerflow-staging-https.conf','/etc/systemd/system/powerflow-candidate-api.service','/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem']
# Generated exact immutable inputs; no data, credentials or dependency wheels.
INPUTS = None

def require(ok,reason):
    if not ok:raise RuntimeError(reason)
def digest(data):return hashlib.sha256(data).hexdigest()
def regular(path):
    st=path.lstat();require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and not(st.st_mode&0o022),'unsafe_file');return path.read_bytes()
def command(args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=35).stdout
def baseline():
    return {'services':command(['/usr/bin/systemctl','show',*SERVICES,'--property=Id,MainPID,ActiveState,SubState']), 'hashes':{p:digest(pathlib.Path(p).read_bytes()) for p in PRESERVED}}
def verify_base():
    for rel,expected in INPUTS['original'].items():require(digest(regular(BASE/rel))==expected,'original_release_drift')
    require(not os.path.lexists(BASE/'src/shared/price_aggregation.py'),'unexpected_original_helper')
def verify_new():
    for rel,old in INPUTS['original'].items():
        expected=INPUTS['patches'].get(rel,{}).get('sha256',old)
        require(digest(regular(NEW/rel))==expected,'hotfix_release_drift')
    for rel,item in INPUTS['patches'].items():require(digest(regular(NEW/rel))==item['sha256'],'patch_drift')
    require((NEW/'.venv-api').is_symlink() and (NEW/'.venv-api').readlink()==BASE/'.venv-api','venv_binding')
def pointer(expected,target):
    require(LINK.is_symlink() and LINK.resolve()==expected,'current_pointer_changed')
    temp=LINK.with_name('react-current.context-hotfix-pending')
    require(not os.path.lexists(temp),'pointer_temp_conflict')
    os.symlink(str(target),temp);os.replace(temp,LINK)
def smoke(directory):
    code="""import sys,datetime,pathlib
sys.path.insert(0,sys.argv[1]+'/src')
from api.feature_parity import forecast_context,price_comparison
from api.market_data import MarketStore
store=MarketStore(pathlib.Path('/srv/powerflow/published/data/processed/silver_electricity_market_data.csv'))
try:
 forecast_context(store,datetime.datetime(2026,10,25,21,tzinfo=datetime.timezone.utc))
 price_comparison(pathlib.Path('/srv/powerflow/published'))
finally:store.close()
print('both_routes_passed')
"""
    def drop():os.setgroups([]);os.setgid(992);os.setuid(992)
    p=subprocess.run([str(BASE/'.venv-api/bin/python'),'-I','-B','-c',code,str(directory)],capture_output=True,text=True,timeout=35,cwd='/',env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'},preexec_fn=drop)
    require(p.returncode==0 and p.stdout.strip()=='both_routes_passed','offline_route_smoke_failed')
def runtime(patched):
    values=dict(x.split('=',1) for x in command(['/usr/bin/systemctl','show',UNIT,'--property=ActiveState,MemoryMax,MemorySwapMax,ControlGroup']).splitlines() if '=' in x)
    require(values.get('ActiveState')=='active' and values.get('MemoryMax')=='536870912' and values.get('MemorySwapMax')=='0','unit_limits')
    cg=pathlib.Path('/sys/fs/cgroup')/values['ControlGroup'].lstrip('/')
    require((cg/'memory.max').read_text().strip()=='536870912' and (cg/'memory.swap.max').read_text().strip()=='0','effective_limits')
    routes=['/health','/ready']+(['/forecast/context?issue_time=2026-10-25T21:00:00Z','/market/price-comparison'] if patched else [])
    statuses={}
    for route in routes:
        with urllib.request.urlopen('http://127.0.0.1:8010'+route,timeout=12) as r:statuses[route]=r.status;require(r.status==200,'http_gate')
    return statuses

def main(action):
    global INPUTS
    require(os.geteuid()==0 and action in ['apply','rollback'],'identity_or_action')
    INPUTS=json.loads(INPUTS_JSON)
    for parent in [BASE,BASE.parent,BASE.parent.parent]:require(parent.is_dir() and not parent.is_symlink() and parent.stat().st_uid==0 and not(parent.stat().st_mode&0o022),'unsafe_parent')
    verify_base();before=baseline();result={'action':action,'stage':'preflight','pointer_switched':False,'candidate_restarted':False}
    try:
        if action=='apply':
            require(LINK.is_symlink() and LINK.resolve()==BASE,'current_release');require(not os.path.lexists(NEW),'destination_conflict')
            require(os.statvfs(BASE.parent).f_bavail*os.statvfs(BASE.parent).f_frsize>2*1024**3,'disk_guard')
            require(int(next(l.split()[1] for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))>128*1024,'memory_guard')
            os.umask(0o077);NEW.mkdir(mode=0o755);os.chmod(NEW,0o755)
            for rel in sorted(set(INPUTS['original'])|set(INPUTS['patches'])):
                p=NEW/rel;p.parent.mkdir(parents=True,exist_ok=True)
                for parent in p.parents:
                    if parent==NEW:break
                    os.chmod(parent,0o755)
                data=base64.b64decode(INPUTS['patches'][rel]['base64']) if rel in INPUTS['patches'] else regular(BASE/rel)
                with p.open('xb') as f:f.write(data)
                os.chmod(p,0o644)
            os.symlink(str(BASE/'.venv-api'),NEW/'.venv-api')
            with (NEW/'.preservation.json').open('x') as f:json.dump(before,f)
            os.chmod(NEW/'.preservation.json',0o600)
            verify_new();result['stage']='offline_smoke';smoke(NEW)
            require(baseline()==before,'production_changed_before_switch')
            pointer(BASE,NEW)
        else:
            verify_new();saved=json.loads(regular(NEW/'.preservation.json'))
            require(before==saved,'preservation_baseline_changed');pointer(NEW,BASE)
        result['pointer_switched']=True;result['stage']='candidate_restart'
        command(['/usr/bin/systemctl','restart',UNIT]);result['candidate_restarted']=True
        time.sleep(3);result['stage']='runtime';result['http']=runtime(action=='apply')
        require(baseline()==before,'production_preservation_failed');result['production_preserved']=True;result['stage']='complete'
        print(json.dumps(result));return 0
    except Exception as e:
        result.update(error_type=type(e).__name__,error=str(e) if isinstance(e,RuntimeError) else 'private_execution_failure',automatic_rollback=False)
        print(json.dumps(result));return 1
if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
