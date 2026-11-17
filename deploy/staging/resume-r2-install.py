#!/usr/bin/env python3
"""PROPOSED ONLY: guarded five-parent repair and remaining R2 install steps. No activation."""
import hashlib,importlib.util,json,os,stat,sys,time
from pathlib import Path
ID='phase-staging-https-ready-20261026'
C=Path('/var/lib/powerflow-staging-install')/ID
EXPECTED_BUNDLE='1a716274b69348a204cbc2300400b65a4485d33505ea4518c4bf7df4d5e815d8'

def need(x,code):
 if not x:raise RuntimeError(code)

def repair_parent_modes(paths,reader_gid):
 """Check ALL five exact parents before any chmod; caller approves these five paths."""
 expected=[(Path('/opt/powerflow'),0,0o755),(Path('/opt/powerflow/releases'),0,0o755),
           (Path('/var/www/powerflow-staging'),0,0o755),(Path('/var/www/powerflow-staging/releases'),0,0o755),
           (Path('/srv/powerflow'),reader_gid,0o750)]
 need(paths==expected,'unexpected_repair_paths')
 for p,gid,mode in paths:
  for a in (p,*p.parents):need(not a.is_symlink(),'repair_symlink')
  s=p.stat();need(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and s.st_gid==gid and stat.S_IMODE(s.st_mode)==0o700,'repair_parent_metadata_changed')
 for p,gid,mode in paths:
  p.chmod(mode);need(stat.S_IMODE(p.stat().st_mode)==mode,'repair_mode_verification')

def main():
 os.umask(0o077);report={'status':'failed','activation':False,'publication_retried':False,'dependencies_reinstalled':False}
 try:
  need(os.geteuid()==0,'root_required')
  for p in (C,*C.parents):need(not p.is_symlink(),'control_symlink')
  s=C.stat();need(s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o700,'control_permissions')
  raw=(C/'bundle.json').read_bytes();need(hashlib.sha256(raw).hexdigest()==EXPECTED_BUNDLE,'bundle_changed');b=json.loads(raw)
  for name,h in b['control_hashes'].items():need(hashlib.sha256((C/name).read_bytes()).hexdigest()==h,'original_R2_code_changed')
  for item in b['artifacts']:need(hashlib.sha256((C/item['name']).read_bytes()).hexdigest()==item['sha256'],'original_R2_artifact_changed')
  sys.path.insert(0,str(C));spec=importlib.util.spec_from_file_location('original_R2',C/'install.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  before=m.read(C/'production-services.before');m.preservation(b,before);m.verify_installed(b)
  need(m.sha(m.HTTPS)==m.PLACEHOLDER,'staging_routing_changed')
  for p in (m.CURRENT,m.WWW,m.UNIT,m.ENVFILE,C/'installed.ok',C/'activation.started',C/'resume-r2.started'):
   need(not os.path.lexists(p),'unexpected_resume_state')
  state=m.run('candidate-state',['/usr/bin/systemctl','show',m.SERVICE,'--property=LoadState','--value']).strip()
  need(state==b'not-found','candidate_unit_present')
  m.capacity(0);u,g=m.assert_isolated_identity()
  python=str(m.BACKEND/'.venv-api/bin/python')
  expected_probe=m.read(C/'linux-regression-unittest.py').replace(b"'/candidate/src'",repr(str(m.BACKEND/'src')).encode()).replace(b"'/candidate/requirements/api.lock'",repr(str(m.BACKEND/'requirements/api.lock')).encode())
  need(m.read(m.BACKEND/'linux-regression.py')==expected_probe,'regression_probe_changed')
  paths=[(Path('/opt/powerflow'),0,0o755),(Path('/opt/powerflow/releases'),0,0o755),(Path('/var/www/powerflow-staging'),0,0o755),(Path('/var/www/powerflow-staging/releases'),0,0o755),(Path('/srv/powerflow'),g.gr_gid,0o750)]
  # Marker first for audit; no service, file-content, identity or owner changes.
  m.create_file(C/'resume-r2.started',b'Explicitly approved single guarded continuation.\n',0o600)
  repair_parent_modes(paths,g.gr_gid)
  m.run('resume-pip-check',[python,'-m','pip','--isolated','check'],seconds=30)
  m.run('resume-offline-regressions',[python,'-B',str(m.BACKEND/'linux-regression.py')],seconds=120,uid=u.pw_uid,gid=g.gr_gid,env={**m.ENV,'HOME':'/nonexistent','PYTHONPATH':str(m.BACKEND/'src')})
  m.run('resume-published-access',[python,'-I','-S','-B','-c','import os,pathlib; root=pathlib.Path("/srv/powerflow/published"); files=[p for p in root.rglob("*") if p.is_file()]; assert len(files)==14; assert all(os.access(p,os.R_OK) and not os.access(p,os.W_OK) for p in [root,*files])'],seconds=15,uid=u.pw_uid,gid=g.gr_gid)
  m.CURRENT.symlink_to(m.BACKEND);m.WWW.symlink_to(m.STATIC)
  m.mkdir_new_or_safe(Path('/etc/powerflow'),0o700)
  m.create_file(m.ENVFILE,m.read(C/'release/proposals/api.env.example'),0o600)
  m.create_file(m.UNIT,m.read(C/'release/proposals/powerflow-candidate-api.service'),0o644)
  m.run('resume-systemd-syntax',['/usr/bin/systemd-analyze','verify',str(m.UNIT)],seconds=20)
  m.preservation(b,before)
  m.create_file(C/'installation-measurements.json',json.dumps({'venv_bytes':sum(p.stat().st_size for p in (m.BACKEND/'.venv-api').rglob('*') if p.is_file() and not p.is_symlink()),'publication_bytes':json.loads(m.read(C/'publication-result.json'))['total_file_bytes'],'interpreter':'/usr/bin/python3.14','port':8010}).encode(),0o600)
  m.create_file(C/'installed.ok',b'R2 continuation completed; candidate NOT started or enabled.\n',0o600)
  report['status']='passed';report['candidate_started']=False
 except Exception as e:
  report['error_type']=type(e).__name__;report['errno']=getattr(e,'errno',None)
  report['safe_error']=str(e) if isinstance(e,RuntimeError) and str(e).replace('_','').isalnum() else 'details_withheld'
 print(json.dumps(report,indent=2));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
