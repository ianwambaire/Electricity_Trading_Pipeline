"""One approved read-only SSH execution; no retries, private captures."""
import hashlib,json,os,pathlib,runpy,subprocess,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[3]
p=ROOT/'deploy/staging/next24-review/verify-completed-offset-run.py'
s=ROOT/'deploy/remediation/a3-bounded-local.py'
r=ROOT/'deploy/staging/install-package/execute-approved.py'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='bff7a79196fdf761543a9b529e05e11504381a7d95b143ccfd7b980379c962f4'
assert hashlib.sha256(s.read_bytes()).hexdigest()=='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
assert hashlib.sha256(r.read_bytes()).hexdigest()=='89c9621ff8cce664fc5f59993c4ae7f60bd74ac38b6bf99c87aeca8aab43ddd4'
os.umask(0o077);capture=pathlib.Path(tempfile.mkdtemp(prefix='powerflow-completed-offset-',dir='/private/tmp'))
cmd=['ssh',*runpy.run_path(str(r))['OPTIONS'],'ec2-user@3.228.243.164','sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 90s /usr/bin/python3 -I -S -B -']
with p.open('rb') as source,(capture/'stdout.json').open('xb') as out,(capture/'stderr.private').open('xb') as err:
 result=subprocess.run([sys.executable,str(s),'--',*cmd],stdin=source,stdout=out,stderr=err,timeout=190)
print(json.dumps({'exit':result.returncode,'capture':str(capture),'retry':False}))
if (capture/'stdout.json').stat().st_size:
 data=json.loads((capture/'stdout.json').read_text())
 (ROOT/'deploy/staging/next24-review/COMPLETED-OFFSET-VERIFICATION.json').write_text(json.dumps(data,indent=2)+'\n')
 print(json.dumps(data,indent=2))
raise SystemExit(result.returncode)
