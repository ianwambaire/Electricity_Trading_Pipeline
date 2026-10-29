"""Local-only continuation hash/scope regression tests; never production commands."""
import hashlib,runpy
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
m=runpy.run_path(str(ROOT/'deploy/staging/continue-r2-activation.py'))

def test_exact_in_memory_patch_preserves_remote_artifact_binding():
 fixed=(ROOT/'deploy/staging/activate-staging-https.py').read_bytes()
 original=fixed.replace(b"tokens[position[0]] not in ('{', '}', ';'):",b"tokens[position[0]] not in '{};':")
 assert hashlib.sha256(original).hexdigest()==m['OLD']
 assert m['corrected_source'](original)==fixed
 assert hashlib.sha256(fixed).hexdigest()==m['FIXED']
 with pytest.raises(RuntimeError,match='original_reviewer_changed'):m['corrected_source'](original+b'\n')

def test_continuation_never_restarts_reinstalls_or_rewrites_configuration():
 source=(ROOT/'deploy/staging/continue-r2-activation.py').read_text()
 assert "['/usr/bin/systemctl','reload','nginx']" in source
 assert source.count("['/usr/bin/systemctl','reload','nginx']")==1
 assert 'm.activate(' not in source and 'm.install(' not in source
 assert 'write_bytes(' not in source and 'os.replace(' not in source
 assert "'restart'" not in source and "'start'" not in source and "'stop'" not in source
 compile(source,'continue-r2-activation.py','exec')


def probe_clock():
    now=[0.0]
    def sleep(seconds):now[0]+=seconds
    return lambda:now[0],sleep


def test_bounded_post_reload_readiness_accepts_old_worker_404_then_exact_react():
    import hashlib
    clock,sleep=probe_clock();responses=iter([(404,b'old worker'),(200,b'approved React')]);calls=[]
    def request(path,leaf,timeout):calls.append((path,timeout));return next(responses)
    result=m['wait_for_react_entry']('leaf',hashlib.sha256(b'approved React').hexdigest(),request=request,clock=clock,sleep=sleep)
    assert result==(200,b'approved React') and len(calls)==2


def test_post_reload_404_has_finite_deadline_without_reload_retry():
    clock,sleep=probe_clock();calls=[]
    def request(*a,**k):calls.append(True);return 404,b'not ready'
    with pytest.raises(RuntimeError,match='readiness_deadline'):
        m['wait_for_react_entry']('leaf','0'*64,request=request,clock=clock,sleep=sleep)
    assert len(calls)<=21 and clock()==10


@pytest.mark.parametrize('response,code',[(500,'unexpected_HTTP_status'),(200,'content_hash')])
def test_readiness_does_not_mask_server_errors_or_wrong_200_content(response,code):
    clock,sleep=probe_clock();calls=[]
    def request(*a,**k):calls.append(True);return response,b'wrong content'
    with pytest.raises(RuntimeError,match=code):m['wait_for_react_entry']('leaf','0'*64,request=request,clock=clock,sleep=sleep)
    assert len(calls)==1
