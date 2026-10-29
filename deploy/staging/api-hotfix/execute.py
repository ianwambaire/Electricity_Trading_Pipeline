"""Hash-bound one-connection runner. DO NOT EXECUTE without separate approval."""
import hashlib,json,os,pathlib,runpy,subprocess,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parent

def main():
    action=sys.argv[1];assert action in ['apply','rollback']
    manifest=json.loads((ROOT/'MANIFEST.json').read_text())
    for name,digest in manifest['artifacts'].items():
        p=ROOT/name;assert not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==digest,name
    repo=ROOT.parents[2];supervisor=repo/'deploy/remediation/a3-bounded-local.py';runner=repo/'deploy/staging/install-package/execute-approved.py'
    assert hashlib.sha256(supervisor.read_bytes()).hexdigest()=='9651828740e242181ef9cd3409ff266f14391f966290eccdb591611faf500f40'
    assert hashlib.sha256(runner.read_bytes()).hexdigest()=='89c9621ff8cce664fc5f59993c4ae7f60bd74ac38b6bf99c87aeca8aab43ddd4'
    options=runpy.run_path(str(runner))['OPTIONS'];os.umask(0o077)
    capture=pathlib.Path(tempfile.mkdtemp(prefix='powerflow-context-hotfix-',dir='/private/tmp'))
    command=['ssh',*options,'ec2-user@3.228.243.164','sudo -n /usr/bin/timeout --signal=TERM --kill-after=5s 180s /usr/bin/python3 -I -S -B - '+action]
    code='import runpy,sys; m=runpy.run_path(sys.argv[1]); raise SystemExit(m["run"](sys.argv[2:],seconds=210,grace=5))'
    with (ROOT/'hotfix.py').open('rb') as source,(capture/'stdout.json').open('xb') as out,(capture/'stderr.private').open('xb') as err:
        p=subprocess.run([sys.executable,'-I','-B','-c',code,str(supervisor),*command],stdin=source,stdout=out,stderr=err)
    print(json.dumps({'exit_status':p.returncode,'capture':str(capture),'automatic_retry':False,'automatic_rollback':False}));return p.returncode
if __name__=='__main__':raise SystemExit(main())
