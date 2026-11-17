"""Explicitly approved two-stage Prefect-only operation; no retries or run triggers."""
import datetime as D,hashlib,json,os,pathlib,subprocess,time,urllib.request,urllib.parse
UTC=D.timezone.utc;OLD='01a0c4e9-92ac-7772-8e1d-2ab939191545';TASK='01a0c58d-ece5-75b0-95fd-5230d239413f';DEP='47e5ef51-26d0-44b6-b119-2c40d0e77397';SCHEDULE='9319f665-9836-4120-9801-031e23ad2b4a';ROOT=pathlib.Path('/home/ec2-user/Electricity_Trading_Pipeline')
RESULT={'stage':'preflight','task_reconciled':False,'flow_reconciled':False,'schedule_updated':False,'concurrency_updated':False,'automatic_retry':False,'manual_run_triggered':False}
ACTIVE=['RUNNING','PENDING','CANCELLING','PAUSED']

def require(ok,why):
 if not ok:raise RuntimeError(why)
def ts(s):return D.datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(UTC)
def api(path,data=None,method=None):
 req=urllib.request.Request('http://127.0.0.1:4200/api'+path,data=json.dumps(data).encode() if data is not None else None,method=method,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as response:
  raw=response.read(2000001);require(len(raw)<2000001,'api_response_size');return json.loads(raw) if raw else None

def processes():
 found=[]
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   if p.stat().st_uid!=1000:continue
   args=(p/'cmdline').read_bytes().split(b'\0')
   if any(b'fetch_entsoe_data' in a or b'scheduled_pipeline' in a or b'prefect.engine' in a or OLD.encode() in a for a in args):found.append(int(p.name))
  except (FileNotFoundError,PermissionError,ProcessLookupError):pass
 return found

def active_runs():return api('/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':ACTIVE}}},'limit':50})
def queued_runs():return api('/flow_runs/filter',{'deployments':{'id':{'any_':[DEP]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}}},'sort':'EXPECTED_START_TIME_ASC','limit':100})
def state_type(r):return (r.get('state') or {}).get('type')
def blocks(runs):return any(state_type(r) in ACTIVE for r in runs)
def common_baseline():
 units=['powerflow-api.service','powerflow-streamlit.service','powerflow-candidate-api.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service']
 r=subprocess.run(['/usr/bin/systemctl','show',*units,'--property=Id,MainPID,ActiveState,SubState'],capture_output=True,text=True,timeout=8,check=True)
 files=['/etc/nginx/conf.d/powerflow.conf','/etc/nginx/conf.d/powerflow-staging-acme.conf','/etc/nginx/conf.d/powerflow-staging-https.conf','/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem','/etc/letsencrypt-powerflow-staging/live/staging.powerflowenergy.dev/fullchain.pem']
 # Staging lineage is verified elsewhere; only include its known existing path.
 files=files[:-1]
 fixed=[str(ROOT/'src/models/next24h_production.py'),str(ROOT/'src/models/next24h.py'),str(ROOT/'src/scheduled_pipeline.py'),str(ROOT/'data/raw/entsoe/load.csv'),str(ROOT/'data/raw/entsoe/generation.csv'),str(ROOT/'data/raw/entsoe/prices.csv'),str(ROOT/'data/reports/next24h_forecast.csv')]
 return {'services':r.stdout,'hashes':{p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in files+fixed},'staging_pointer':str(pathlib.Path('/opt/powerflow/react-current').resolve())}

def validate_orphan():
 run=api('/flow_runs/'+OLD);task=api('/task_runs/'+TASK)
 require(run.get('id')==OLD and run.get('deployment_id')==DEP,'orphan_flow_identity')
 require(task.get('id')==TASK and task.get('flow_run_id')==OLD,'orphan_task_identity')
 require(state_type(run)=='RUNNING' and state_type(task)=='RUNNING','orphan_state_drift')
 require(run.get('start_time')=='2026-09-21T19:59:59.539764Z' and run.get('updated')=='2026-09-21T19:59:59.541364Z' and run.get('end_time') is None,'orphan_flow_timestamp_drift')
 require(task.get('start_time')=='2026-09-21T20:00:07.912134Z' and task.get('updated')=='2026-09-21T20:00:07.923021Z' and task.get('end_time') is None,'orphan_task_timestamp_drift')
 pid=str(run.get('infrastructure_pid') or '').rsplit(':',1)[-1];require(pid.isdigit() and not pathlib.Path('/proc/'+pid).exists(),'original_infrastructure_process_not_proven_absent')
 logs=api('/logs/filter',{'logs':{'flow_run_id':{'any_':[OLD]}},'sort':'TIMESTAMP_DESC','limit':1})
 require(len(logs)==1 and logs[0]['timestamp']=='2026-09-21T20:00:38.266371Z','old_run_activity_drift')
 tasks=api('/task_runs/filter',{'task_runs':{'flow_run_id':{'any_':[OLD]}},'limit':20});require({t['id'] for t in tasks}=={TASK},'orphan_task_inventory_drift')
 require(not processes(),'live_execution_process')
 require({r['id'] for r in active_runs()}=={OLD},'other_active_run')
 workers=api('/work_pools/electricity-pool/workers/filter',{'limit':10});online=[w for w in workers if w.get('name')=='powerflow-ec2' and w.get('status')=='ONLINE']
 require(len(online)==1 and (D.datetime.now(UTC)-ts(online[0]['last_heartbeat_time'])).total_seconds()<90,'worker_not_healthy')
 worker=subprocess.run(['/usr/bin/systemctl','show','powerflow-prefect-worker.service','--property=ActiveState,ExecMainStartTimestamp'],capture_output=True,text=True,timeout=8,check=True).stdout
 require('ActiveState=active' in worker and '2026' in worker,'worker_service')
 # A fresh worker heartbeat is not a heartbeat from the orphan execution.
 return run,task

def dep_summary(d):
 g=d.get('global_concurrency_limit')
 return {'id':d.get('id'),'name':d.get('name'),'status':d.get('status'),'paused':d.get('paused'),'schedules':d.get('schedules'),'legacy_concurrency_limit':d.get('concurrency_limit'),'global_concurrency_limit':{k:g.get(k) for k in ['id','limit','active_slots','active']} if g else None,'concurrency_options':d.get('concurrency_options')}
def static_settings(d):
 keys=['name','flow_id','version','description','paused','parameters','parameter_openapi_schema','tags','work_queue_name','work_queue_id','work_pool_name','path','entrypoint','job_variables','pull_steps','storage_document_id','infrastructure_document_id','enforce_parameter_schema','concurrency_options']
 return {k:d.get(k) for k in keys}
def schedule_invariants(s):return {k:v for k,v in s.items() if k not in ['updated','schedule']}

def main():
 require(os.geteuid()==0,'root_required');before=common_baseline()
 run,task=validate_orphan();dep=api('/deployments/'+DEP)
 require(dep.get('name')=='powerflow-entsoe-pipeline' and dep.get('entrypoint')=='src/scheduled_pipeline.py:powerflow_entsoe_pipeline' and dep.get('work_pool_name')=='electricity-pool' and dep.get('paused') is False,'deployment_identity')
 RESULT['_private_before']={'flow':run,'task':task,'deployment':dep};RESULT['deployment_before']=dep_summary(dep)
 RESULT['stage']='stage1_task'
 for kind,rid in [('task_runs',TASK),('flow_runs',OLD)]:
  if kind=='flow_runs':
   require(not processes(),'execution_appeared_before_flow_transition')
   current=api('/flow_runs/'+OLD);require(state_type(current)=='RUNNING' and current.get('updated')==run.get('updated'),'flow_changed_before_transition')
  reply=api('/'+kind+'/'+rid+'/set_state',{'state':{'type':'CRASHED','name':'Crashed','message':'Operator-approved reconciliation: orphaned September21 execution; original process absent and no subsequent activity.'},'force':False},'POST')
  require(reply.get('status')=='ACCEPT' and state_type({'state':reply.get('state')})=='CRASHED','state_transition_not_accepted')
  current=api('/'+kind+'/'+rid);require(state_type(current)=='CRASHED','terminal_state_readback')
  RESULT['task_reconciled' if kind=='task_runs' else 'flow_reconciled']=True
  RESULT['stage']='stage1_flow' if kind=='task_runs' else 'stage1_complete'
 require(not active_runs() and not processes(),'non_overlap_gate_not_clear')
 require(all(blocks([{'state':{'type':t}}]) for t in ACTIVE) and not blocks([{'state':{'type':'CRASHED'}}]),'non_overlap_guard_regression')
 RESULT['non_overlap_gate']={'currently_clear':True,'genuine_active_states_still_block':True}
 require(common_baseline()==before,'production_changed_after_stage1')
 RESULT['stage']='stage2_preflight';live=api('/deployments/'+DEP)
 require(static_settings(live)==static_settings(dep),'deployment_static_drift')
 schedules=live.get('schedules',[]);require(len(schedules)==1 and schedules[0].get('id')==SCHEDULE and schedules[0].get('active') is True,'schedule_inventory_drift')
 old_schedule=schedules[0];require(old_schedule['schedule']=={'cron':'0 * * * *','timezone':'UTC','day_or':True},'schedule_drift')
 global_limit=live.get('global_concurrency_limit');require(global_limit is None or global_limit.get('limit')==1,'unexpected_concurrency_limit')
 if global_limit:require(global_limit.get('active') is True and global_limit.get('active_slots',0)==0,'concurrency_not_idle')
 queued=queued_runs();require(len(queued)<100,'queue_bound');now=D.datetime.now(UTC)
 require(all(r.get('auto_scheduled') is True and ts(r['expected_start_time'])>now+D.timedelta(minutes=5) for r in queued),'manual_late_or_imminent_queued_run')
 RESULT['queued_before']=[{'id':r['id'],'expected_start_time':r['expected_start_time'],'auto_scheduled':r.get('auto_scheduled')} for r in queued]
 # Preserve collision options by omitting that field entirely.
 if global_limit is None:
  RESULT['stage']='stage2_concurrency';api('/deployments/'+DEP,{'concurrency_limit':1},'PATCH');RESULT['concurrency_updated']=True
 live=api('/deployments/'+DEP);g=live.get('global_concurrency_limit') or {};require(g.get('limit')==1 and g.get('active') is True,'concurrency_readback')
 require(static_settings(live)==static_settings(dep),'settings_changed_with_concurrency')
 require(not active_runs() and not processes(),'execution_appeared_before_schedule_update')
 current_clock=D.datetime.now(UTC);next45=current_clock.replace(minute=45,second=0,microsecond=0)
 if next45<=current_clock:next45+=D.timedelta(hours=1)
 require((next45-current_clock).total_seconds()>300,'new_schedule_slot_too_imminent')
 require(live.get('schedules')==schedules,'schedule_changed_before_patch')
 RESULT['stage']='stage2_schedule';new_schema=dict(old_schedule['schedule']);new_schema['cron']='45 * * * *'
 api('/deployments/'+DEP+'/schedules/'+SCHEDULE,{'schedule':new_schema},'PATCH');RESULT['schedule_updated']=True
 live=api('/deployments/'+DEP);after_schedules=live.get('schedules',[])
 require(len(after_schedules)==1 and after_schedules[0]['id']==SCHEDULE and after_schedules[0]['schedule']==new_schema,'schedule_readback')
 require(schedule_invariants(after_schedules[0])==schedule_invariants(old_schedule),'unrelated_schedule_change')
 require(static_settings(live)==static_settings(dep),'unrelated_deployment_change')
 g=live.get('global_concurrency_limit') or {};require(g.get('limit')==1 and g.get('active') is True and live.get('concurrency_options')==dep.get('concurrency_options'),'final_concurrency')
 RESULT['deployment_after']=dep_summary(live);RESULT['stage']='queue_verification'
 # Read-only bounded observation of normal scheduler materialization; never
 # retry a mutation or create a run. Empty queue is reported explicitly.
 queued=[]
 for index in range(7):
  queued=queued_runs()
  if queued:break
  if index<6:time.sleep(5)
 times=[r['expected_start_time'] for r in queued];require(len(times)==len(set(times)),'duplicate_queued_occurrences')
 require(all(r.get('auto_scheduled') is True and ts(r['expected_start_time']).minute==45 and ts(r['expected_start_time']).second==0 and ts(r['expected_start_time'])>D.datetime.now(UTC) for r in queued),'unexpected_queued_run')
 require(not active_runs() and not processes(),'unexpected_execution_after_schedule_update')
 RESULT['queued_after']=[{'id':r['id'],'expected_start_time':r['expected_start_time'],'auto_scheduled':r.get('auto_scheduled')} for r in queued]
 RESULT['queue_materialization_verified']=bool(queued)
 RESULT['production_preserved']=common_baseline()==before;require(RESULT['production_preserved'],'production_preservation_failed')
 current=D.datetime.now(UTC);next_time=current.replace(minute=45,second=0,microsecond=0)
 if next_time<=current:next_time+=D.timedelta(hours=1)
 RESULT['next_configured_run']=next_time.isoformat();RESULT['stage']='complete'
 print(json.dumps(RESULT,indent=2));return 0
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:
  RESULT.update(error_type=type(e).__name__,http_status=getattr(e,'code',None),error=str(e) if isinstance(e,RuntimeError) else 'private_execution_error',automatic_rollback=False)
  print(json.dumps(RESULT,indent=2));raise SystemExit(1)
