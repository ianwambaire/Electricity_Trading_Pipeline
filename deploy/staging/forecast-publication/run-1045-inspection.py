"""One read-only SSH operation; hash-bound payload, private captures, no retries."""
import hashlib,json,os,pathlib,runpy,subprocess,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[3]
p=ROOT/'deploy/staging/forecast-publication/inspect-1045.py';s=ROOT/'deploy/remediation/a3-bounded-local.py';r=ROOT/'deploy/staging/install-package/execute-approved.py'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='2b6996816642ca1bf2885e7ff49d073915cbe159bef830a98f7d60c9e82de2ea'
assert hashlib.sha256(s.read_bytes()).hexdigest()=='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
assert hashlib.sha256(r.read_bytes()).hexdigest()=='89c9621ff8cce664fc5f59993c4ae7f60bd74ac38b6bf99c87aeca8aab43ddd4'
os.umask(0o077);capture=pathlib.Path(tempfile.mkdtemp(prefix='powerflow-forecast-publication-preflight-',dir='/private/tmp'))
cmd=['ssh',*runpy.run_path(str(r))['OPTIONS'],'ec2-user@3.228.243.164','sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 45s /usr/bin/python3 -I -S -B -']
with p.open('rb') as source,(capture/'stdout.json').open('xb') as out,(capture/'stderr.private').open('xb') as err:
 result=subprocess.run([sys.executable,str(s),'--',*cmd],stdin=source,stdout=out,stderr=err,timeout=190)
print(json.dumps({'exit':result.returncode,'capture':str(capture),'retry':False}))
if (capture/'stdout.json').stat().st_size:
 data=json.loads((capture/'stdout.json').read_text());(ROOT/'deploy/staging/forecast-publication/RUN-1045-RESULTS.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data,indent=2))
raise SystemExit(result.returncode)
