"""One bounded read-only SSH call, private captures, no automatic retries."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[3]
P=ROOT/'deploy/staging/inference-evidence-deployment/preflight.py'
S=ROOT/'deploy/remediation/a3-bounded-local.py'
assert hashlib.sha256(P.read_bytes()).hexdigest()=='ee10b11239f68fe75d37a8b073f118cdc6404fef663d3d2add7ff8be165255ae'
assert hashlib.sha256(S.read_bytes()).hexdigest()=='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
OPTIONS=['-i','/Users/iannganga/.ssh/powerflow-key.pem','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/Users/iannganga/.ssh/known_hosts','-o','ConnectTimeout=10','-o','ConnectionAttempts=1','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','-o','LogLevel=ERROR']
os.umask(0o077)
capture=Path(tempfile.mkdtemp(prefix='powerflow-inference-preflight-',dir='/private/tmp'))
cmd=['ssh',*OPTIONS,'ec2-user@3.228.243.164','sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 90s /usr/bin/python3 -I -S -B -']
with P.open('rb') as source,(capture/'stdout.json').open('xb') as out,(capture/'stderr.private').open('xb') as err:
    result=subprocess.run([sys.executable,str(S),'--',*cmd],stdin=source,stdout=out,stderr=err,timeout=190)
print(json.dumps({'exit':result.returncode,'capture':str(capture),'retry':False}))
raw=(capture/'stdout.json').read_bytes()
if raw:
    try:
        data=json.loads(raw)
        (ROOT/'deploy/staging/inference-evidence-deployment/PREFLIGHT-RESULTS.json').write_text(json.dumps(data,indent=2)+'\n')
        print(json.dumps(data,indent=2))
    except (ValueError,UnicodeError):print(json.dumps({'report_produced':False,'failure_category':'invalid_json'}))
else:
    error=(capture/'stderr.private').read_text(errors='replace').lower()
    category='ssh_timeout' if 'timed out' in error else 'ssh_host_key_failure' if 'host key' in error else 'transport_or_remote_failure'
    print(json.dumps({'report_produced':False,'failure_category':category}))
raise SystemExit(result.returncode)
