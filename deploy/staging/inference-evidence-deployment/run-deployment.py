"""PROPOSED ONLY. Explicit separate approval required for apply OR rollback."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[3]
P=ROOT/'deploy/staging/inference-evidence-deployment/deploy-capture.py'
S=ROOT/'deploy/remediation/a3-bounded-local.py'
EXPECTED='842d3a0f222befb07221643159583ae307da853dfdcbb619138b5598305274f2'
assert len(sys.argv)==2 and sys.argv[1] in ['apply','rollback']
assert hashlib.sha256(P.read_bytes()).hexdigest()==EXPECTED
assert hashlib.sha256(S.read_bytes()).hexdigest()=='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
OPTIONS=['-i','/Users/iannganga/.ssh/powerflow-key.pem','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts','-o','ConnectTimeout=10','-o','ConnectionAttempts=1','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','-o','LogLevel=ERROR']
os.umask(0o077)
capture=Path(tempfile.mkdtemp(prefix='powerflow-inference-deployment-',dir='/private/tmp'))
command=['ssh',*OPTIONS,'ec2-user@3.228.243.164','/usr/bin/timeout --signal=TERM --kill-after=5s 90s /home/ec2-user/Electricity_Trading_Pipeline/.venv-prod/bin/python -I -B - '+sys.argv[1]]
with P.open('rb') as source,(capture/'stdout.json').open('xb') as out,(capture/'stderr.private').open('xb') as err:
    result=subprocess.run([sys.executable,str(S),'--',*command],stdin=source,stdout=out,stderr=err,timeout=190)
print(json.dumps({'exit':result.returncode,'capture':str(capture),'retry':False,'action':sys.argv[1]}))
raw=(capture/'stdout.json').read_bytes()
if raw:
    try:print(json.dumps(json.loads(raw),indent=2))
    except (ValueError,UnicodeError):print(json.dumps({'report_produced':False,'failure_category':'invalid_json'}))
else:print(json.dumps({'report_produced':False,'failure_category':'transport_or_remote_error_raw_capture_private'}))
raise SystemExit(result.returncode)
