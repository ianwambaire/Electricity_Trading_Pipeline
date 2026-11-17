"""Sanitized realized-performance document. No model execution or source access."""
import datetime as dt
import hashlib
import json
import math
import re
from . import forecast_publication as forecast
from .forecast_evaluation import REALIZED_COLUMNS
UTC=dt.timezone.utc
MAX_BYTES=16*1024*1024
MAX_ROWS=25000
MAX_AGE=dt.timedelta(minutes=90)
WINDOW=dt.timedelta(days=30)
COVERAGE=('history_rows','verified_rows','unverified_rows','eligible_rows','realized_pairs')
class InvalidReport(ValueError):pass

def require(ok):
    if not ok:raise InvalidReport('REALIZED_REPORT_INVALID')
def stamp(value):
    require(type(value)is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)',value)is not None)
    return dt.datetime.fromisoformat(value.replace('Z','+00:00'))
def encode(value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode();require(len(raw)<=MAX_BYTES);return raw

def validate(raw,now):
    try:
        require(type(raw)is bytes and len(raw)<=MAX_BYTES)
        def unique(items):
            out={}
            for key,value in items:require(key not in out);out[key]=value
            return out
        b=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:require(False))
        require(set(b)=={'version','generated_at','state','reason','scope_days','sources','coverage','rows','observed_through'})
        require(type(b['version'])is int and b['version']==1 and b['scope_days']==30)
        generated=stamp(b['generated_at']);require(generated<=now)
        require(b['observed_through']is None or stamp(b['observed_through'])+dt.timedelta(hours=1)<=generated)
        require(b['state']in {'READY','MISSING_INPUTS','FAILED'})
        require(b['reason']in {'NONE','MISSING_HISTORY','MISSING_OBSERVATIONS','MISSING_RECEIPTS','INVALID_INPUT'})
        require(set(b['sources'])=={'history_sha256','prices_sha256','receipts_sha256'})
        require(all(v is None or type(v)is str and re.fullmatch('[0-9a-f]{64}',v) for v in b['sources'].values()))
        c=b['coverage'];require(set(c)==set(COVERAGE) and all(type(n)is int and 0<=n<=100000 for n in c.values()))
        require(c['verified_rows']+c['unverified_rows']==c['history_rows'] and c['realized_pairs']<=c['eligible_rows']<=c['verified_rows'])
        require(type(b['rows'])is list and len(b['rows'])<=MAX_ROWS and len(b['rows'])==c['realized_pairs'])
        if b['state']!='READY':require(not b['rows'] and b['reason']!='NONE');return b
        require(b['reason']=='NONE' and all(b['sources'].values()))
        seen=set()
        for r in b['rows']:
            require(type(r)is dict and set(r)==set(REALIZED_COLUMNS))
            issue,target,issued=(stamp(r[k])for k in ('forecast_issue_time','target_timestamp','issued_at_utc'))
            h=r['horizon_hours'];require(type(h)is int and 1<=h<=24 and target==issue+dt.timedelta(hours=h))
            require(issue.minute==issue.second==issue.microsecond==0 and issue<=issued<target and issued-issue<=forecast.MAX_AGE)
            require(target+dt.timedelta(hours=1)<=generated and generated-WINDOW<target)
            require(r['model_release']==forecast.RELEASE)
            key=(r['model_release'],issue,h);require(key not in seen);seen.add(key)
            nums=[r[k]for k in ('predicted_price_eur_mwh','actual_price_eur_mwh','absolute_error','squared_error','signed_error')]
            require(all(type(x)in (int,float) and math.isfinite(x)for x in nums))
            error=nums[0]-nums[1]
            require(all(math.isclose(a,e,rel_tol=1e-10,abs_tol=1e-10)for a,e in zip(nums[2:],[abs(error),error**2,error])))
        return b
    except InvalidReport:raise
    except (ValueError,TypeError,KeyError,OverflowError,AttributeError):raise InvalidReport('REALIZED_REPORT_INVALID')from None

def failure(reason,now):
    return {'version':1,'generated_at':now.isoformat(),'state':'MISSING_INPUTS'if reason.startswith('MISSING_')else'FAILED','reason':reason,'scope_days':30,'observed_through':None,'sources':dict.fromkeys(['history_sha256','prices_sha256','receipts_sha256']),'coverage':dict.fromkeys(COVERAGE,0),'rows':[]}
