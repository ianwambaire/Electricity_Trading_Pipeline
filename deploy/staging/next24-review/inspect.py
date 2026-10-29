"""Bounded read-only evidence inspection. No inference, persistence or pipeline calls."""
import ast,csv,datetime as D,hashlib,json,math,os,pathlib,re,sqlite3,time,urllib.request,urllib.parse
ROOT=pathlib.Path('/home/ec2-user/Electricity_Trading_Pipeline');UTC=D.timezone.utc;NOW=D.datetime.now(UTC);H=NOW.replace(minute=0,second=0,microsecond=0)
WEATHER=['temperature_2m','relative_humidity_2m','wind_speed_10m','cloud_cover','shortwave_radiation']
GEN=['Biomass','Fossil Brown coal/Lignite','Fossil Gas','Fossil Hard coal','Hydro Run-of-river and poundage','Solar','Wind Offshore','Wind Onshore']
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

def main():
 out={'as_of':iso(NOW),'sources':{},'candidate_issue_gaps':{},'reports':{}};hourly={};recent_rows={}
 for source,path,required in [('prices','data/raw/entsoe/prices.csv',['price_eur_mwh']),('load','data/raw/entsoe/load.csv',['load_mw']),('generation','data/raw/entsoe/generation.csv',GEN),('weather_archive','data/raw/weather/open_meteo_weather.csv',WEATHER)]:
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
 release=ROOT/'artifacts/models/releases/next24h'
 with read(release/'next24h_release_manifest.json') as f:m=json.load(f)
 out['model']={k:m.get(k) for k in ['release_id','release_type','model_type','feature_count','features','horizons_hours','known_limitations']}
 for key,sha in [('model_file','model_sha256'),('feature_contract_file','feature_contract_sha256')]:
  require(m[key] in ['next24h_model.joblib','next24h_feature_contract.joblib'],'artifact_filename');p=release/m[key];require(p.stat().st_size<20000000,'artifact_size');out['model'][key+'_hash_matches']=hashlib.sha256(p.read_bytes()).hexdigest()==m[sha]
 # Prove inspected code equals the local workflow before inferring feature semantics.
 out['code_matches_local']={}
 for rel,digest in CODE_HASHES.items():out['code_matches_local'][rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest
 for rel in ['data/reports/next24h_forecast.csv','data/reports/next24h_forecast_history.csv']:
  p=ROOT/rel;info={'exists':p.exists()};out['reports'][rel]=info
  if not p.exists():continue
  require(p.stat().st_size<16000000,'report_size');before=p.stat()
  with read(p) as f:rows=list(csv.DictReader(f))
  issues=[ts(r.get('forecast_issue_time','')) for r in rows];validissues=[t for t in issues if t];newest=max(validissues) if validissues else None;latest=[r for r,t in zip(rows,issues) if t==newest];horizons=sorted(int(r['horizon_hours']) for r in latest)
  info.update(rows=len(rows),latest_issue=iso(newest),target_start=iso(min(ts(r['target_timestamp']) for r in latest)) if latest else None,target_end=iso(max(ts(r['target_timestamp']) for r in latest)) if latest else None,horizons=horizons,complete_valid_24=len(latest)==24 and horizons==list(range(1,25)) and all(finite(r['predicted_price_eur_mwh']) and ts(r['target_timestamp'])==newest+D.timedelta(hours=int(r['horizon_hours'])) for r in latest),future_targets=sum(ts(r['target_timestamp'])>NOW for r in latest),stable=before.st_mtime_ns==p.stat().st_mtime_ns)
 for rel in ['data/reports/next24h_forecast_provenance.json','data/reports/monitoring/forecast_vintage_health.json','data/reports/monitoring/next24h_exogenous_silver_quality.json']:
  p=ROOT/rel;info={'exists':p.exists()};out['reports'][rel]=info
  if p.exists():
   require(p.stat().st_size<100000,'json_size')
   with read(p) as f:d=json.load(f)
   info['keys']=list(d);info['summary']={k:v for k,v in d.items() if k in ['forecast_issue_time','issued_at_utc','status','generated_at_utc','as_of_utc','operationally_ready','engineering_ready','latest_timestamp','market_latest_complete_hour','weather_acquired_at_utc']}
 # Single in-memory TLS-verified provider GET, no inference and no persistence.
 p=ROOT/'src/ingestion/fetch_weather_data.py';tree=ast.parse(p.read_text());constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='OPERATIONAL_OPEN_METEO_URL'}
 url=constants.get('OPERATIONAL_OPEN_METEO_URL');require(url=='https://api.open-meteo.com/v1/forecast','unexpected_weather_provider')
 params={'latitude':52.52,'longitude':13.41,'hourly':','.join(WEATHER),'timezone':'UTC','start_hour':(H-D.timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),'end_hour':(H+D.timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M')}
 try:
  with urllib.request.urlopen(url+'?'+urllib.parse.urlencode(params),timeout=25) as response:
   body=response.read(200001);require(len(body)<200001,'weather_body_bound');d=json.loads(body);hours=d.get('hourly',{});times=[ts(t) for t in hours.get('time',[])];good={t for i,t in enumerate(times) if t and all(i<len(hours.get(c,[])) and finite(hours[c][i]) for c in WEATHER)}
   out['weather_provider']={'http':response.status,'tls_verified':True,'utc':d.get('utc_offset_seconds')==0 and d.get('timezone') in ['GMT','UTC'],'valid_hours':len(good),'issue_coverage':{iso(H-D.timedelta(hours=i)):H-D.timedelta(hours=i) in good for i in range(4)},'next24_missing':[iso(H+D.timedelta(hours=i)) for i in range(1,25) if H+D.timedelta(hours=i) not in good]}
 except Exception as e:out['weather_provider']={'error':type(e).__name__,'http':getattr(e,'code',None),'tls_bypassed':False}
 print(json.dumps(out,indent=2))

def require(ok,why):
 if not ok:raise RuntimeError(why)
CODE_HASHES={'src/models/next24h_production.py': '403b20f8ad0d167848931a08117c4e6aea11455c2b39a10b258eab8799532419', 'src/models/next24h.py': '6708af30d05d8f3f22cd7af0ad52de160c905fc40c25e586bcacded58a8fb4fd', 'src/models/final_evaluation.py': '2b9403ef20f4373bbf5f1d1ab42df18b74ea5e07aca645190b34b132118950c6', 'src/processing/build_silver_dataset.py': '91103a3435949b2341adc35d30dec17881040f0ca728b7a9bdb8273b35276cc4', 'src/ingestion/fetch_weather_data.py': 'f802b3b6436393a2f33168dcf31658189ba97a7c3fdeb86cfc92419b21804f2f', 'src/scheduled_pipeline.py': '571e3b56c34bc17a38dc13bad066def40c9c711bf51f74aff466014b9afcce8b'}
if __name__=='__main__':main()
