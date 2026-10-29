import csv,datetime as D,hashlib,json,math,os,pathlib,re,sqlite3,time,subprocess
ROOT=pathlib.Path("/home/ec2-user/Electricity_Trading_Pipeline");UTC=D.timezone.utc;NOW=D.datetime.now(UTC);H=NOW.replace(minute=0,second=0,microsecond=0)
GEN=['Biomass', 'Fossil Brown coal/Lignite', 'Fossil Gas', 'Fossil Hard coal', 'Hydro Run-of-river and poundage', 'Solar', 'Wind Offshore', 'Wind Onshore']
def read(p):return os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NOATIME),'r')

def ts(value):
 try:
  t=D.datetime.fromisoformat(value.replace('Z','+00:00'));return t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC)
 except:return None

def finite(x):
 try:return math.isfinite(float(x))
 except:return False

def iso(t):return t.isoformat() if t else None

def missing_features(issue,hourly):
 result={}
 for source,lags in [('prices',[0,1,24,168]),('load',[0,1,24])]:
  absent=[iso(issue-D.timedelta(hours=i)) for i in lags if issue-D.timedelta(hours=i) not in hourly[source]]
  window=[iso(issue-D.timedelta(hours=i)) for i in range(24) if issue-D.timedelta(hours=i) not in hourly[source]]
  if absent or window:result[source]={'missing_lag_hours':absent,'missing_rolling24_hours':window}
 if issue not in hourly['generation']:result['generation']='incomplete issue hour'
 return result

def require(ok,why):
 if not ok:raise RuntimeError(why)

def main():
 out={'as_of':iso(NOW),'sources':{},'candidate_issue_gaps':{},'reports':{}};hourly={};recent_rows={}
 for source,path,required in [('prices','data/raw/entsoe/prices.csv',['price_eur_mwh']),('load','data/raw/entsoe/load.csv',['load_mw']),('generation','data/raw/entsoe/generation.csv',GEN)]:
  p=ROOT/path;info={'exists':p.exists()};out['sources'][source]=info
  if not p.exists():hourly[source]=set();continue
  before=p.stat();info['bytes']=before.st_size;require(before.st_size<150000000,'source_size_bound');buckets={};latest=None;lastfinite={};count=0
  with read(p) as f:
   r=csv.DictReader(f);info['missing_columns']=sorted(set(required)-set(r.fieldnames or []))
   for row in r:
    count+=1;require(count<1500000,'row_bound');t=ts(row.get('timestamp',''))
    if t is None:continue
    latest=max(latest,t) if latest else t
    for col in required:
     if finite(row.get(col)):lastfinite[col]=max(lastfinite.get(col,t),t)
    if t>=H-D.timedelta(hours=192):buckets.setdefault(t.replace(minute=0,second=0,microsecond=0),[]).append((t,row))
  good=set();bad={}
  for hour,rows in buckets.items():
   expected=1 if source=='weather_archive' else 4
   if source=='prices':
    res={row.get('source_resolution') or ('PT15M' if hour>=D.datetime(2025,9,30,22,tzinfo=UTC) else 'PT60M') for _,row in rows};expected=1 if res=={'PT60M'} else 4 if res=={'PT15M'} else -1
   missing={c:[iso(t) for t,row in rows if not finite(row.get(c))] for c in required};missing={k:v for k,v in missing.items() if v}
   unique={t for t,_ in rows};aligned=all(t.second==0 and t.microsecond==0 and t.minute in ([0] if expected==1 else [0,15,30,45]) for t in unique)
   if len(rows)==len(unique)==expected and aligned and not missing:good.add(hour)
   elif hour>=H-D.timedelta(hours=6):bad[iso(hour)]={'row_count':len(rows),'expected_count':expected,'missing_fields':missing,'missing_quarters':[iso(hour+D.timedelta(minutes=i)) for i in ([0] if expected==1 else [0,15,30,45]) if hour+D.timedelta(minutes=i) not in unique]}
  hourly[source]=good;recent_rows[source]=buckets
  info.update(rows=count,latest=iso(latest),latest_complete_hour=iso(max(good) if good else None),last_finite={k:iso(v) for k,v in lastfinite.items()},recent_incomplete=bad,stable=p.stat().st_mtime_ns==before.st_mtime_ns)
 for i in range(4):
  issue=H-D.timedelta(hours=i);out['candidate_issue_gaps'][iso(issue)]=missing_features(issue,hourly)
 # Required details_json, with no raw operational records or environment values.
 p=ROOT/'database/electricity_trading.db';before=p.stat();out['database']={}
 with open(p,'rb') as f:header=f.read(20)
 require(header[18:20]==b'\x01\x01' and not any(pathlib.Path(str(p)+s).exists() for s in ['-wal','-shm','-journal']),'database_journal_safety')
 db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True,timeout=.3);db.execute('PRAGMA query_only=ON');db.execute('BEGIN');deadline=time.monotonic()+5;db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
 pipeline=db.execute('SELECT run_time,status,message FROM pipeline_runs ORDER BY id DESC LIMIT 1').fetchone();msg=json.loads(pipeline[2]);out['database']['latest_pipeline']={'time':pipeline[0],'status':pipeline[1],'metadata':{k:v for k,v in msg.items() if k in ['next24h_forecast_status','next24h_forecast_reason','next24h_latest_complete_market_hours','next24h_model_verified','next24h_model_verification_status','model_verified','model_verification_status']}}
 rows=db.execute("SELECT timestamp_utc,component,event_type,details_json FROM operational_incidents WHERE event_type IN ('forecast_withheld','model_verification_failed','source_gap') ORDER BY id DESC LIMIT 6").fetchall();out['database']['incidents']=[]
 for when,component,event,details in rows:
  d=json.loads(details or '{}');safe={k:v for k,v in d.items() if k in ['reason','source','latest_complete_hours','forecast_freshness_status','timestamp','missing_columns','missing_hours']};out['database']['incidents'].append({'time':when,'component':component,'event':event,'details':safe})
 db.close();out['database']['stable']=p.stat().st_mtime_ns==before.st_mtime_ns

 original_hour=D.datetime(2026,10,29,5,tzinfo=UTC)
 loadrows=recent_rows['load'].get(original_hour,[])
 out['original_missing_quarters_present']={iso(original_hour+D.timedelta(minutes=m)):any(t==original_hour+D.timedelta(minutes=m) and finite(row.get('load_mw')) for t,row in loadrows) for m in [30,45]}
 eligible=[H-D.timedelta(hours=i) for i in range(1,5) if NOW-(H-D.timedelta(hours=i))<=D.timedelta(hours=3) and not missing_features(H-D.timedelta(hours=i),hourly)]
 out['fresh_complete_market_issues']=[iso(t) for t in eligible]
 p=ROOT/'data/reports/next24h_forecast.csv'
 with read(p) as f:rows=list(csv.DictReader(f))
 issue=ts(rows[0]['forecast_issue_time']) if rows else None
 out['forecast_report']={'rows':len(rows),'issue':iso(issue),'target_start':iso(min(ts(r['target_timestamp']) for r in rows)) if rows else None,'target_end':iso(max(ts(r['target_timestamp']) for r in rows)) if rows else None,'future_targets':sum(ts(r['target_timestamp'])>NOW for r in rows),'valid24':len(rows)==24 and [int(r['horizon_hours']) for r in rows]==list(range(1,25)) and all(ts(r['forecast_issue_time'])==issue and ts(r['target_timestamp'])==issue+D.timedelta(hours=int(r['horizon_hours'])) and finite(r['predicted_price_eur_mwh']) for r in rows)}
 # Only if market gates remain blocked: one normal authenticated provider read,
 # no ingestion, no response persistence, no credential/URL/error-body logging.
 if not eligible:
  provider_code=r'''
import sys,os,json,datetime as D,logging,math,xml.etree.ElementTree as E
logging.disable(logging.CRITICAL)
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'src'))
from dotenv import load_dotenv
load_dotenv(root/'.env',override=False)
from powerflow_secrets import get_secret
import requests
from entsoe.parsers import parse_loads
import pandas as pd
out={'attempts':0}
try:
 endpoint=os.environ.get('ENTSOE_ENDPOINT_URL') or 'https://web-api.tp.entsoe.eu/api'
 if endpoint!='https://web-api.tp.entsoe.eu/api':raise ValueError('unexpected_endpoint')
 secret=get_secret('ENTSOE_API_KEY')
 now=D.datetime.now(D.timezone.utc).replace(minute=0,second=0,microsecond=0);start=min(now-D.timedelta(hours=6),D.datetime(2026,10,29,5,tzinfo=D.timezone.utc))
 if now-start>D.timedelta(hours=24):raise ValueError('request_window_bound')
 params={'securityToken':secret,'documentType':'A65','processType':'A16','outBiddingZone_Domain':'10Y1001A1001A82H','out_Domain':'10Y1001A1001A82H','periodStart':start.strftime('%Y%m%d%H%M'),'periodEnd':now.strftime('%Y%m%d%H%M')}
 session=requests.Session();session.trust_env=False
 out['attempts']=1
 response=session.get(endpoint,params=params,timeout=(5,25),allow_redirects=False,stream=True)
 out['http']=response.status_code
 if response.status_code!=200:raise RuntimeError('provider_non_200')
 chunks=[];length=0
 for chunk in response.iter_content(16384):
  length+=len(chunk)
  if length>2000000:raise ValueError('response_size_bound')
  chunks.append(chunk)
 text=b''.join(chunks).decode('utf-8');response.close();del secret,params
 xml=E.fromstring(text);raw=set()
 def children(node,name):return [e for e in node.iter() if e.tag.split('}')[-1]==name]
 def first(node,name):
  es=children(node,name);return es[0].text if es else None
 for series in children(xml,'TimeSeries'):
  for period in children(series,'Period'):
   starttime=pd.Timestamp(first(period,'start'));resolution=first(period,'resolution');step={'PT15M':15,'PT60M':60}.get(resolution)
   if step is None:continue
   for point in children(period,'Point'):
    try:
     if math.isfinite(float(first(point,'quantity'))):raw.add(starttime+pd.Timedelta(minutes=(int(first(point,'position'))-1)*step))
    except (TypeError,ValueError):pass
 parsed=parse_loads(text,process_type='A16');good=parsed.apply(pd.to_numeric,errors='coerce').replace([float('inf'),-float('inf')],float('nan')).dropna();parsedtimes=set(good.index.tz_convert('UTC'))
 wanted=[pd.Timestamp('2026-10-29T05:30:00Z'),pd.Timestamp('2026-10-29T05:45:00Z')]
 out.update(tls_verified=True,query_start=start.isoformat(),query_end_exclusive=now.isoformat(),raw_latest=max(raw).isoformat() if raw else None,parsed_latest=max(parsedtimes).isoformat() if parsedtimes else None,original_quarters_raw={t.isoformat():t in raw for t in wanted},original_quarters_parsed={t.isoformat():t in parsedtimes for t in wanted},raw_and_parsed_timestamp_sets_equal=raw==parsedtimes,raw_times_missing_from_parser=[t.isoformat() for t in sorted(raw-parsedtimes)][:32])
except Exception as e:out['error_type']=type(e).__name__
print(json.dumps(out))
'''
  def drop():os.setgroups([1000]);os.setgid(1000);os.setuid(1000)
  try:
   run=subprocess.run([str(ROOT/'.venv-prod/bin/python'),'-I','-B','-c',provider_code,str(ROOT)],capture_output=True,text=True,timeout=65,preexec_fn=drop,cwd='/',env={'PATH':'/usr/bin:/bin','HOME':'/home/ec2-user','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','AWS_MAX_ATTEMPTS':'1'})
   out['upstream_load']={'child_exit':run.returncode,'result':json.loads(run.stdout) if run.returncode==0 else None}
  except Exception as e:out['upstream_load']={'error_type':type(e).__name__}
 else:out['upstream_load']={'skipped':'fresh complete market inputs already available'}
 return out


def POST_MAIN():
 out={'as_of':iso(NOW),'sources':{},'candidate_issue_gaps':{},'reports':{}};hourly={};recent_rows={}
 for source,path,required in [('prices','data/raw/entsoe/prices.csv',['price_eur_mwh']),('load','data/raw/entsoe/load.csv',['load_mw']),('generation','data/raw/entsoe/generation.csv',GEN)]:
  p=ROOT/path;info={'exists':p.exists()};out['sources'][source]=info
  if not p.exists():hourly[source]=set();continue
  before=p.stat();info['bytes']=before.st_size;require(before.st_size<150000000,'source_size_bound');buckets={};latest=None;lastfinite={};count=0
  with read(p) as f:
   r=csv.DictReader(f);info['missing_columns']=sorted(set(required)-set(r.fieldnames or []))
   for row in r:
    count+=1;require(count<1500000,'row_bound');t=ts(row.get('timestamp',''))
    if t is None:continue
    latest=max(latest,t) if latest else t
    for col in required:
     if finite(row.get(col)):lastfinite[col]=max(lastfinite.get(col,t),t)
    if t>=H-D.timedelta(hours=192):buckets.setdefault(t.replace(minute=0,second=0,microsecond=0),[]).append((t,row))
  good=set();bad={}
  for hour,rows in buckets.items():
   expected=1 if source=='weather_archive' else 4
   if source=='prices':
    res={row.get('source_resolution') or ('PT15M' if hour>=D.datetime(2025,9,30,22,tzinfo=UTC) else 'PT60M') for _,row in rows};expected=1 if res=={'PT60M'} else 4 if res=={'PT15M'} else -1
   missing={c:[iso(t) for t,row in rows if not finite(row.get(c))] for c in required};missing={k:v for k,v in missing.items() if v}
   unique={t for t,_ in rows};aligned=all(t.second==0 and t.microsecond==0 and t.minute in ([0] if expected==1 else [0,15,30,45]) for t in unique)
   if len(rows)==len(unique)==expected and aligned and not missing:good.add(hour)
   elif hour>=H-D.timedelta(hours=6):bad[iso(hour)]={'row_count':len(rows),'expected_count':expected,'missing_fields':missing,'missing_quarters':[iso(hour+D.timedelta(minutes=i)) for i in ([0] if expected==1 else [0,15,30,45]) if hour+D.timedelta(minutes=i) not in unique]}
  hourly[source]=good;recent_rows[source]=buckets
  info.update(rows=count,latest=iso(latest),latest_complete_hour=iso(max(good) if good else None),last_finite={k:iso(v) for k,v in lastfinite.items()},recent_incomplete=bad,stable=p.stat().st_mtime_ns==before.st_mtime_ns)
 for i in range(4):
  issue=H-D.timedelta(hours=i);out['candidate_issue_gaps'][iso(issue)]=missing_features(issue,hourly)
 # Required details_json, with no raw operational records or environment values.
 p=ROOT/'database/electricity_trading.db';before=p.stat();out['database']={}
 with open(p,'rb') as f:header=f.read(20)
 require(header[18:20]==b'\x01\x01' and not any(pathlib.Path(str(p)+s).exists() for s in ['-wal','-shm','-journal']),'database_journal_safety')
 db=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True,timeout=.3);db.execute('PRAGMA query_only=ON');db.execute('BEGIN');deadline=time.monotonic()+5;db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
 pipeline=db.execute('SELECT run_time,status,message FROM pipeline_runs ORDER BY id DESC LIMIT 1').fetchone();msg=json.loads(pipeline[2]);out['database']['latest_pipeline']={'time':pipeline[0],'status':pipeline[1],'metadata':{k:v for k,v in msg.items() if k in ['next24h_forecast_status','next24h_forecast_reason','next24h_latest_complete_market_hours','next24h_model_verified','next24h_model_verification_status','model_verified','model_verification_status']}}
 rows=db.execute("SELECT timestamp_utc,component,event_type,details_json FROM operational_incidents WHERE event_type IN ('forecast_withheld','model_verification_failed','source_gap') ORDER BY id DESC LIMIT 6").fetchall();out['database']['incidents']=[]
 for when,component,event,details in rows:
  d=json.loads(details or '{}');safe={k:v for k,v in d.items() if k in ['reason','source','latest_complete_hours','forecast_freshness_status','timestamp','missing_columns','missing_hours']};out['database']['incidents'].append({'time':when,'component':component,'event':event,'details':safe})
 db.close();out['database']['stable']=p.stat().st_mtime_ns==before.st_mtime_ns

 original_hour=D.datetime(2026,10,29,5,tzinfo=UTC)
 loadrows=recent_rows['load'].get(original_hour,[])
 out['original_missing_quarters_present']={iso(original_hour+D.timedelta(minutes=m)):any(t==original_hour+D.timedelta(minutes=m) and finite(row.get('load_mw')) for t,row in loadrows) for m in [30,45]}
 eligible=[H-D.timedelta(hours=i) for i in range(1,5) if NOW-(H-D.timedelta(hours=i))<=D.timedelta(hours=3) and not missing_features(H-D.timedelta(hours=i),hourly)]
 out['fresh_complete_market_issues']=[iso(t) for t in eligible]
 p=ROOT/'data/reports/next24h_forecast.csv'
 with read(p) as f:rows=list(csv.DictReader(f))
 issue=ts(rows[0]['forecast_issue_time']) if rows else None
 out['forecast_report']={'rows':len(rows),'issue':iso(issue),'target_start':iso(min(ts(r['target_timestamp']) for r in rows)) if rows else None,'target_end':iso(max(ts(r['target_timestamp']) for r in rows)) if rows else None,'future_targets':sum(ts(r['target_timestamp'])>NOW for r in rows),'valid24':len(rows)==24 and [int(r['horizon_hours']) for r in rows]==list(range(1,25)) and all(ts(r['forecast_issue_time'])==issue and ts(r['target_timestamp'])==issue+D.timedelta(hours=int(r['horizon_hours'])) and finite(r['predicted_price_eur_mwh']) for r in rows)}
 # Only if market gates remain blocked: one normal authenticated provider read,
 # no ingestion, no response persistence, no credential/URL/error-body logging.
 if False:
  provider_code=r'''
import sys,os,json,datetime as D,logging,math,xml.etree.ElementTree as E
logging.disable(logging.CRITICAL)
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'src'))
from dotenv import load_dotenv
load_dotenv(root/'.env',override=False)
from powerflow_secrets import get_secret
import requests
from entsoe.parsers import parse_loads
import pandas as pd
out={'attempts':0}
try:
 endpoint=os.environ.get('ENTSOE_ENDPOINT_URL') or 'https://web-api.tp.entsoe.eu/api'
 if endpoint!='https://web-api.tp.entsoe.eu/api':raise ValueError('unexpected_endpoint')
 secret=get_secret('ENTSOE_API_KEY')
 now=D.datetime.now(D.timezone.utc).replace(minute=0,second=0,microsecond=0);start=min(now-D.timedelta(hours=6),D.datetime(2026,10,29,5,tzinfo=D.timezone.utc))
 if now-start>D.timedelta(hours=24):raise ValueError('request_window_bound')
 params={'securityToken':secret,'documentType':'A65','processType':'A16','outBiddingZone_Domain':'10Y1001A1001A82H','out_Domain':'10Y1001A1001A82H','periodStart':start.strftime('%Y%m%d%H%M'),'periodEnd':now.strftime('%Y%m%d%H%M')}
 session=requests.Session();session.trust_env=False
 out['attempts']=1
 response=session.get(endpoint,params=params,timeout=(5,25),allow_redirects=False,stream=True)
 out['http']=response.status_code
 if response.status_code!=200:raise RuntimeError('provider_non_200')
 chunks=[];length=0
 for chunk in response.iter_content(16384):
  length+=len(chunk)
  if length>2000000:raise ValueError('response_size_bound')
  chunks.append(chunk)
 text=b''.join(chunks).decode('utf-8');response.close();del secret,params
 xml=E.fromstring(text);raw=set()
 def children(node,name):return [e for e in node.iter() if e.tag.split('}')[-1]==name]
 def first(node,name):
  es=children(node,name);return es[0].text if es else None
 for series in children(xml,'TimeSeries'):
  for period in children(series,'Period'):
   starttime=pd.Timestamp(first(period,'start'));resolution=first(period,'resolution');step={'PT15M':15,'PT60M':60}.get(resolution)
   if step is None:continue
   for point in children(period,'Point'):
    try:
     if math.isfinite(float(first(point,'quantity'))):raw.add(starttime+pd.Timedelta(minutes=(int(first(point,'position'))-1)*step))
    except (TypeError,ValueError):pass
 parsed=parse_loads(text,process_type='A16');good=parsed.apply(pd.to_numeric,errors='coerce').replace([float('inf'),-float('inf')],float('nan')).dropna();parsedtimes=set(good.index.tz_convert('UTC'))
 wanted=[pd.Timestamp('2026-10-29T05:30:00Z'),pd.Timestamp('2026-10-29T05:45:00Z')]
 out.update(tls_verified=True,query_start=start.isoformat(),query_end_exclusive=now.isoformat(),raw_latest=max(raw).isoformat() if raw else None,parsed_latest=max(parsedtimes).isoformat() if parsedtimes else None,original_quarters_raw={t.isoformat():t in raw for t in wanted},original_quarters_parsed={t.isoformat():t in parsedtimes for t in wanted},raw_and_parsed_timestamp_sets_equal=raw==parsedtimes,raw_times_missing_from_parser=[t.isoformat() for t in sorted(raw-parsedtimes)][:32])
except Exception as e:out['error_type']=type(e).__name__
print(json.dumps(out))
'''
  def drop():os.setgroups([1000]);os.setgid(1000);os.setuid(1000)
  try:
   run=subprocess.run([str(ROOT/'.venv-prod/bin/python'),'-I','-B','-c',provider_code,str(ROOT)],capture_output=True,text=True,timeout=65,preexec_fn=drop,cwd='/',env={'PATH':'/usr/bin:/bin','HOME':'/home/ec2-user','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','AWS_MAX_ATTEMPTS':'1'})
   out['upstream_load']={'child_exit':run.returncode,'result':json.loads(run.stdout) if run.returncode==0 else None}
  except Exception as e:out['upstream_load']={'error_type':type(e).__name__}
 else:out['upstream_load']={'skipped':'fresh complete market inputs already available'}
 return out



import urllib.request,urllib.parse,signal
EXPECTED_CODE={'src/ingestion/fetch_entsoe_data.py': 'ee1d225895fbf929127a577ca4f85a6855643186a7590cda5eaa27ac6aa21a2a', 'src/ingestion/incremental_utils.py': '9fb9892c67808f6e7a0e7618776afd836e28133d4ac7be37e2cddd27e03a1a33', 'src/powerflow_secrets.py': '4d67eff1ea532d6c6855160018cde95b01bed3b591a78e23d455bba2885a87f0'}
PRODUCTION_UNITS=['powerflow-api.service','powerflow-streamlit.service','powerflow-prefect-worker.service','powerflow-prefect-server.service','postgresql.service']
def request(path,payload=None):
 data=json.dumps(payload).encode() if payload is not None else None
 req=urllib.request.Request('http://127.0.0.1:4200/api'+path,data=data,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=8) as response:
  body=response.read(1500001);require(len(body)<1500001,'prefect_response_bound');return json.loads(body)
def processes():
 found=[]
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit() or p.name==str(os.getpid()):continue
  try:
   if p.stat().st_uid!=1000:continue
   args=(p/'cmdline').read_bytes().split(b'\0')
   if any(b'fetch_entsoe_data' in a or b'scheduled_pipeline' in a for a in args):found.append(int(p.name))
  except (FileNotFoundError,PermissionError,ProcessLookupError):pass
 return found
def idle_window():
 name='/deployments/name/'+urllib.parse.quote('PowerFlow ENTSO-E Pipeline',safe='')+'/powerflow-entsoe-pipeline'
 dep=request(name);require(dep.get('name')=='powerflow-entsoe-pipeline' and dep.get('entrypoint')=='src/scheduled_pipeline.py:powerflow_entsoe_pipeline','deployment_identity')
 filt={'deployments':{'id':{'any_':[dep['id']]}},'flow_runs':{'state':{'type':{'any_':['RUNNING','PENDING','CANCELLING','PAUSED']}}},'limit':20}
 active=request('/flow_runs/filter',filt);require(not active,'active_prefect_run')
 deadline=D.datetime.now(UTC)+D.timedelta(seconds=420)
 upcoming=request('/flow_runs/filter',{'deployments':{'id':{'any_':[dep['id']]}},'flow_runs':{'state':{'type':{'any_':['SCHEDULED']}},'expected_start_time':{'before_':deadline.isoformat()}},'limit':20})
 require(not upcoming,'scheduled_run_inside_execution_window')
 require(not processes(),'manual_or_scheduled_ingestion_process')
 # Independently enforce separation from the hourly deployment even if queue empty.
 current=D.datetime.now(UTC);next_hour=current.replace(minute=0,second=0,microsecond=0)+D.timedelta(hours=1)
 require((next_hour-current).total_seconds()>420,'insufficient_time_before_hourly_schedule')
 return {'prefect_idle':True,'process_scan_idle':True,'next_hourly_slot':next_hour.isoformat()}
def preservation():
 services=subprocess.run(['/usr/bin/systemctl','show',*PRODUCTION_UNITS,'--property=Id,MainPID,ActiveState,SubState'],capture_output=True,text=True,check=True,timeout=8).stdout
 files=['/etc/nginx/conf.d/powerflow.conf','/etc/nginx/conf.d/powerflow-staging-https.conf','/etc/nginx/conf.d/powerflow-staging-acme.conf','/etc/letsencrypt/live/powerflowenergy.dev/fullchain.pem']
 return {'services':services,'hashes':{p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in files}}
def validate_sources():
 result={}
 for name in ['prices','load','generation']:
  p=ROOT/('data/raw/entsoe/'+name+'.csv');require(p.is_file() and not p.is_symlink(),'source_path');require(not pathlib.Path(str(p)+'.tmp').exists(),'source_temp_conflict');st=p.stat();require(st.st_uid==1000 and st.st_size<150000000,'source_owner_or_size')
  seen=set();previous=None;count=0
  with read(p) as f:
   reader=csv.DictReader(f);require('timestamp' in reader.fieldnames,'timestamp_column')
   for row in reader:
    count+=1;t=ts(row['timestamp']);require(t is not None and t not in seen and (previous is None or previous<t),'invalid_duplicate_unsorted_source');seen.add(t);previous=t
  require(count>0 and st.st_mtime_ns==p.stat().st_mtime_ns,'empty_or_changing_source')
  result[name]={'rows':count,'bytes':st.st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'unique_sorted_timestamps':True}
 return result

def recover():
 result={'ingestion_executed':False,'stage':'preflight'}
 try:
  require(ROOT.is_dir() and not ROOT.is_symlink() and os.geteuid()==0,'working_directory_or_identity')
  for rel,digest in EXPECTED_CODE.items():require(hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest,'reviewed_code_drift')
  before=preservation();result['overlap_guards']=idle_window()
  result['sources_before']=validate_sources()
  free=os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize;available=int(next(line.split()[1] for line in pathlib.Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
  require(free>2*1024**3 and available>768*1024**2,'capacity_guard')
  result['recovery_safeguards']={'per_file_atomic_replacement':True,'protected_history_revision_policy':True,'three_file_transaction':False,'new_backup_created':False,'rollback_authorized':False,'existing_A1_covers_operational_database_only':True}
  # No new raw-data backup is silently created. Ordinary approved ingestion uses
  # its reviewed atomic replacement/revision policy; fail if raw recovery beyond
  # that policy is required. No rollback/restoration is performed here.
  evidence=main();result['before']={k:evidence[k] for k in ['as_of','original_missing_quarters_present','fresh_complete_market_issues','database','forecast_report','upstream_load']}
  present=evidence['original_missing_quarters_present']
  if not all(present.values()):
   provider=evidence['upstream_load'].get('result') or {};require(provider.get('http')==200 and all(provider.get('original_quarters_raw',{}).values()) and len(provider.get('original_quarters_raw',{}))==2 and all(provider.get('original_quarters_parsed',{}).values()),'upstream_observations_not_verified')
  # Final race/stability check immediately before the authorized command.
  require(validate_sources()==result['sources_before'],'sources_changed_during_preflight')
  idle_window();require(preservation()==before,'production_changed_before_ingestion')
  result['stage']='ingestion'
  def drop():os.setgroups([1000]);os.setgid(1000);os.setuid(1000)
  cmd=['/usr/bin/timeout','--signal=TERM','--kill-after=5s','300s','.venv-prod/bin/python','-B','src/ingestion/fetch_entsoe_data.py','--mode','incremental']
  result['ingestion_executed']=True
  run=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=310,preexec_fn=drop,env={'PATH':'/usr/bin:/bin','HOME':'/home/ec2-user','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'},start_new_session=True)
  result['command_exit']=run.returncode;require(run.returncode==0,'ingestion_command_failed')
  result['stage']='postcheck';result['sources_after']=validate_sources()
  # Read-only postchecks; disable provider GET here, never retry ingestion.
  global NOW,H
  NOW=D.datetime.now(UTC);H=NOW.replace(minute=0,second=0,microsecond=0)
  # main() would repeat provider access if still blocked. Use its same local-only
  # evidence collection with the conditional provider branch disabled in memory.
  post=POST_MAIN();result['after']={k:post[k] for k in ['as_of','sources','original_missing_quarters_present','fresh_complete_market_issues','database','forecast_report']}
  require(all(post['original_missing_quarters_present'].values()),'missing_quarters_not_recovered')
  require(preservation()==before,'production_preservation_failed');result['production_preserved']=True;result['stage']='complete'
  print(json.dumps(result,indent=2));return 0
 except Exception as e:
  result['error_type']=type(e).__name__;result['error']=str(e) if isinstance(e,RuntimeError) else 'private_execution_error';result['automatic_retry']=False
  print(json.dumps(result,indent=2));return 1
if __name__=='__main__':raise SystemExit(recover())
