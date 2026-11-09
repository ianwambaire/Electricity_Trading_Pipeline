"""Receipt-verified realized performance producer; no inference or model loading."""
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import uuid
import pandas as pd
from shared import realized_report as contract
from shared.operational_evidence_producer import receipt_bundle
from shared.forecast_evaluation import REALIZED_COLUMNS

MAX_SOURCE=64*1024*1024

def read(path,limit):
    path=Path(path)
    # Resolve each component through an anchored directory descriptor, never a
    # check-then-open path that could be replaced by a symlink concurrently.
    path=path.absolute();contract.require('..'not in path.parts)
    parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=nxt
        descriptor=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    finally:os.close(parent)
    with os.fdopen(descriptor,'rb')as f:
        before=os.fstat(f.fileno());contract.require(stat.S_ISREG(before.st_mode) and before.st_size<=limit)
        raw=f.read(limit+1);after=os.fstat(f.fileno())
        contract.require(len(raw)==before.st_size and (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns))
        return raw

def build(history_path,prices_path,receipt_root,*,now=None):
    from models.next24h_monitoring import match_realized_forecasts
    from processing.build_silver_dataset import aggregate_hourly_prices
    now=now or dt.datetime.now(dt.timezone.utc)
    if not Path(history_path).exists():return contract.failure('MISSING_HISTORY',now)
    if not Path(prices_path).exists():return contract.failure('MISSING_OBSERVATIONS',now)
    history_raw=read(history_path,MAX_SOURCE);prices_raw=read(prices_path,MAX_SOURCE)
    history=pd.read_csv(io.BytesIO(history_raw),nrows=100001,float_precision='round_trip');contract.require(len(history)<=100000)
    required=set(REALIZED_COLUMNS[:6]);contract.require(required<=set(history))
    for key in ('forecast_issue_time','target_timestamp','issued_at_utc'):history[key]=pd.to_datetime(history[key],utc=True,errors='raise')
    # Bound this report explicitly to the last30 target days, never all history.
    history=history.loc[(history.target_timestamp>now-contract.WINDOW)&(history.target_timestamp<=now)].copy()
    contract.require(not history.duplicated(['model_release','forecast_issue_time','horizon_hours']).any())
    prices=pd.read_csv(io.BytesIO(prices_raw),nrows=400001,float_precision='round_trip');contract.require(len(prices)<=400000 and {'timestamp','price_eur_mwh'}<=set(prices))
    prices['timestamp']=pd.to_datetime(prices.timestamp,utc=True,errors='raise')
    hourly=aggregate_hourly_prices(prices.set_index('timestamp')).reset_index().rename(columns={'timestamp':'target_timestamp'})
    candidates={};receipts=[];root=Path(receipt_root)
    if not root.exists():return contract.failure('MISSING_RECEIPTS',now)
    if root.exists():
        contract.require(root.is_dir() and not root.is_symlink())
        folders=list(root.iterdir());contract.require(len(folders)<=10000)
        for folder in sorted(folders,key=lambda p:p.lstat().st_mtime_ns,reverse=True)[:1024]:
            contract.require(folder.is_dir() and not folder.is_symlink() and str(uuid.UUID(folder.name))==folder.name)
            # mtime only bounds discovery; every included receipt is independently
            # validated. Missing/unselected receipts cannot yield scored rows.
            if folder.stat().st_mtime<now.timestamp()-32*86400:continue
            files={name:read(folder/name,100000)for name in ('forecast.csv','provenance.json','model.json','evidence.json','integrity.json')}
            bundle,digest=receipt_bundle(files,now);proof=bundle['execution']
            contract.require(proof['run_id']==folder.name)
            issue=pd.Timestamp(bundle['forecasts'][0]['issue_time']);completed=pd.Timestamp(proof['completed_at'])
            if issue<now-dt.timedelta(days=31):continue
            for row in bundle['forecasts']:
                key=(row['model_release'],pd.Timestamp(row['issue_time']),row['horizon_hours'])
                candidates.setdefault(key,[]).append((pd.Timestamp(row['target_time']),row['predicted_price_eur_mwh'],completed,digest))
    verified=[]
    for _,row in history.iterrows():
        matches=[r for r in candidates.get((row.model_release,row.forecast_issue_time,int(row.horizon_hours)),[])if r[0]==row.target_timestamp and r[1]==row.predicted_price_eur_mwh and r[2]<=row.issued_at_utc<=r[2]+dt.timedelta(minutes=5)]
        contract.require(len(matches)<=1)
        if matches:verified.append(row.to_dict());receipts.append(matches[0][3])
    frame=pd.DataFrame(verified,columns=history.columns)
    eligible=frame.loc[(frame.forecast_issue_time<frame.target_timestamp)&(frame.issued_at_utc<frame.target_timestamp)]
    pairs=match_realized_forecasts(frame,hourly,now=pd.Timestamp(now))
    rows=[]
    for row in pairs.to_dict('records'):
        for k in ('forecast_issue_time','target_timestamp','issued_at_utc'):row[k]=row[k].isoformat()
        row['horizon_hours']=int(row['horizon_hours']);rows.append(row)
    document={'version':1,'generated_at':now.isoformat(),'state':'READY','reason':'NONE','scope_days':30,'observed_through':None if hourly.loc[hourly.target_timestamp+pd.Timedelta(hours=1)<=now].empty else hourly.loc[hourly.target_timestamp+pd.Timedelta(hours=1)<=now].target_timestamp.max().isoformat(),
              'sources':{'history_sha256':hashlib.sha256(history_raw).hexdigest(),'prices_sha256':hashlib.sha256(prices_raw).hexdigest(),'receipts_sha256':hashlib.sha256(json.dumps(sorted(set(receipts))).encode()).hexdigest()},
              'coverage':{'history_rows':len(history),'verified_rows':len(frame),'unverified_rows':len(history)-len(frame),'eligible_rows':len(eligible),'realized_pairs':len(rows)},'rows':rows}
    contract.validate(contract.encode(document),now)
    contract.require(read(history_path,MAX_SOURCE)==history_raw and read(prices_path,MAX_SOURCE)==prices_raw)
    return document
