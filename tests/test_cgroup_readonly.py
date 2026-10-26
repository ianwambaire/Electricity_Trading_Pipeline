"""Synthetic cgroup files only; no host cgroup/service/network operations."""
import ast
import importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('preflight',ROOT/'deploy/staging/preflight-react-readonly.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def layout(tmp_path):
    root=tmp_path/'cg';root.mkdir();child=root/'system.slice';child.mkdir()
    mount=tmp_path/'mountinfo';mount.write_text('29 23 0:26 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n')
    for directory in (root,child):
        (directory/'cgroup.controllers').write_text('cpu memory pids\n')
        (directory/'cgroup.subtree_control').write_text('cpu memory pids\n')
    for name in ('memory.high','memory.max','memory.swap.max'):
        (child/name).write_text('max\n')
    return root,mount


def test_v2_root_without_limit_files_is_explicit_and_child_support_is_not_enforcement(layout):
    root,mount=layout;r=m.cgroup_facts(root,mount)
    assert r['host_interface_evidence_complete'] is True
    assert r['nodes']['hierarchy_root']['files']['memory.max']=={'status':'missing'}
    assert r['candidate_effective_enforcement']=='UNVERIFIED'
    assert r['bpf_imds_enforcement']=='UNVERIFIED'


def test_reproduce_original_failure_identifies_first_bad_root_open(layout):
    root,_=layout
    with pytest.raises(FileNotFoundError) as error:
        dict(v2=(root/'cgroup.controllers').is_file(),
             memory_controller='memory' in (root/'cgroup.controllers').read_text().split(),
             root_memory_max=(root/'memory.max').read_text().strip(),
             root_memory_swap_max=(root/'memory.swap.max').read_text().strip())
    assert error.value.filename==str(root/'memory.max')


@pytest.mark.parametrize('name',['cgroup.controllers','cgroup.subtree_control','memory.max','memory.high','memory.swap.max'])
def test_missing_descendant_evidence_stays_incomplete(layout,name):
    root,mount=layout;(root/'system.slice'/name).unlink()
    r=m.cgroup_facts(root,mount)
    assert not r['host_interface_evidence_complete']
    assert r['nodes']['system_slice']['files'][name]['status']=='missing'


@pytest.mark.parametrize('content',['29 23 0:26 / /sys/fs/cgroup rw - cgroup cgroup rw\n',
    '29 23 0:26 / /other rw - cgroup2 cgroup rw\n','malformed mount record\n',''])
def test_v1_nonstandard_and_malformed_mounts_are_not_success(layout,content):
    root,mount=layout;mount.write_text(content)
    assert not m.cgroup_facts(root,mount)['host_interface_evidence_complete']


def test_unavailable_mountinfo_is_explicit(layout):
    root,mount=layout;mount.unlink();r=m.cgroup_facts(root,mount)
    assert r['mountinfo']['status']=='missing'
    assert not r['host_interface_evidence_complete']


@pytest.mark.parametrize('name',['cgroup.controllers','memory.max','memory.swap.max'])
def test_permission_errors_not_misreported_as_missing(layout,monkeypatch,name):
    root,mount=layout;original=m.os.open
    def denied(path,*args,**kwargs):
        if Path(path)==root/'system.slice'/name:raise PermissionError('PRIVATE detail')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(m.os,'open',denied)
    r=m.cgroup_facts(root,mount)
    assert r['nodes']['system_slice']['files'][name]['status']=='permission_denied'
    assert not r['host_interface_evidence_complete']
    assert 'PRIVATE' not in str(r)


def test_missing_memory_controller(layout):
    root,mount=layout;(root/'cgroup.controllers').write_text('cpu pids\n')
    r=m.cgroup_facts(root,mount)
    assert not r['root_memory_controller_advertised'] and not r['host_interface_evidence_complete']


def test_invalid_limit_and_symlink_do_not_pass(layout):
    root,mount=layout;p=root/'system.slice/memory.swap.max';p.write_text('unexpected confidential value')
    r=m.cgroup_facts(root,mount)
    assert r['nodes']['system_slice']['files']['memory.swap.max']['status']=='invalid_value'
    assert 'confidential' not in str(r)
    p.unlink();p.symlink_to(root/'system.slice/memory.max')
    r=m.cgroup_facts(root,mount)
    assert r['nodes']['system_slice']['files']['memory.swap.max']['status']=='os_error'
    assert not r['host_interface_evidence_complete']


def test_diagnostic_uses_identical_logic_and_no_subcommands():
    preflight=ast.parse((ROOT/'deploy/staging/preflight-react-readonly.py').read_text())
    payload=ROOT/'deploy/staging/diagnose-cgroup-readonly.py'
    diagnostic=ast.parse(payload.read_text())
    def function(tree):return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='cgroup_facts')
    assert ast.dump(function(preflight))==ast.dump(function(diagnostic))
    assert 'subprocess' not in payload.read_text()
    for p in (ROOT/'deploy/staging/preflight-react-readonly.py',payload):
        compile(p.read_bytes(),str(p),'exec');ast.parse(p.read_bytes(),feature_version=(3,9))
