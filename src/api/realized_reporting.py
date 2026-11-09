"""Read-only selector for separately published receipt-verified reporting."""
import datetime as dt
from pathlib import Path
import pandas as pd
from fastapi import HTTPException
from shared import realized_report as contract
from shared.realized_report_store import read_active
from shared.forecast_evaluation import summarize_realized_performance,REALIZED_COLUMNS
from .feature_parity import RealizedEvaluation,ReleaseEvaluation

def evaluation(root,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    try:
        document,digest=read_active(Path(root),now)
        if document['state']!='READY':
            code='REALIZED_INPUTS_MISSING'if document['state']=='MISSING_INPUTS'else'REALIZED_REPORT_FAILED'
            raise HTTPException(503,detail={'code':code})
        rows=document['rows'];releases=[]
        if rows:
            frame=pd.DataFrame(rows,columns=REALIZED_COLUMNS)
            for key in ('forecast_issue_time','target_timestamp','issued_at_utc'):frame[key]=pd.to_datetime(frame[key],utc=True)
            result=summarize_realized_performance(frame,now=pd.Timestamp(now))
            releases=[ReleaseEvaluation(model_release=rows[0]['model_release'],overall=result['overall'],windows=result['windows'],horizons=result['horizons'].astype(object).where(pd.notna(result['horizons']),None).to_dict('records'),target_dates=result['target_dates'],first_target=frame.target_timestamp.min().to_pydatetime(),last_target=frame.target_timestamp.max().to_pydatetime(),performance_status=result['overall']['status'],performance_reason='Receipt-verified realized sample; current windows use target times. No automatic retraining or comparison with unrelated holdout periods.')]
        generated=contract.stamp(document['generated_at']);stale=now>=generated+contract.MAX_AGE
        return RealizedEvaluation(assessed_at=now,report_sha256=digest,releases=releases,
            report_status='STALE'if stale else'VALID',data_status='AVAILABLE'if rows and releases[0].overall.status=='Available'else'INSUFFICIENT_DATA',
            generated_at=generated,fresh_until=generated+contract.MAX_AGE,observed_through=document['observed_through'],coverage=document['coverage'],source_sha256=document['sources'],
            provenance='Committed, integrity-verified frozen HGB inference receipts matched by exact UTC target to complete genuine ENTSO-E price hours. Only forecasts issued before target and completed target hours are scored. Sample covers at most30 target days at report generation; 20 pairs overall/window, 5 per horizon. Bias is predicted minus observed. Generated forecasts are not proof of web publication; historical one-hour evaluations are separate.')
    except FileNotFoundError:raise HTTPException(404,detail={'code':'REALIZED_REPORT_MISSING'})from None
    except HTTPException:raise
    except (OSError,ValueError,TypeError,KeyError,OverflowError):raise HTTPException(503,detail={'code':'REALIZED_REPORT_INVALID'})from None
