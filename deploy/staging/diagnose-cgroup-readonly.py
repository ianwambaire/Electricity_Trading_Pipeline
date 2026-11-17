#!/usr/bin/env python3
"""Approval required: only cgroup mount/root/system.slice facts; no writes/subcommands."""
import json
import os
from pathlib import Path
import re
import stat

def cgroup_facts(root=Path('/sys/fs/cgroup'), mountinfo=Path('/proc/self/mountinfo')):
    """Fixed mount/root/system.slice facts; never create or alter a cgroup."""
    def probe(path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    return {'status':'unexpected_file_type'}
                data = handle.read(65537)
            if len(data) > 65536: return {'status':'size_limit'}
            return {'status':'readable', 'text':data.decode('ascii')}
        except FileNotFoundError: return {'status':'missing'}
        except PermissionError: return {'status':'permission_denied'}
        except UnicodeError: return {'status':'invalid_encoding'}
        except OSError as error: return {'status':'os_error', 'errno':error.errno}
    mount = probe(mountinfo)
    mounts = []
    malformed = False
    if mount['status'] == 'readable':
        for line in mount['text'].splitlines():
            try:
                before, after = line.split(' - ',1)
                left, right = before.split(), after.split()
                if right[0] in ('cgroup','cgroup2'):
                    if len(left) < 6 or len(right) < 3: raise ValueError()
                    mounts.append({'mountpoint':left[4], 'filesystem':right[0]})
            except (ValueError, IndexError): malformed = True
    mount_report = {'status':'invalid_format' if malformed else mount['status'], 'cgroup_mounts':mounts}
    nodes = {}
    for label, path in [('hierarchy_root',root), ('system_slice',root/'system.slice')]:
        files = {}
        for filename in ('cgroup.controllers','cgroup.subtree_control','memory.high','memory.max','memory.swap.max'):
            entry = probe(path/filename)
            if entry['status'] == 'readable':
                text = entry.pop('text').strip()
                if filename.startswith('cgroup.'):
                    tokens = text.split()
                    if any(not re.fullmatch(r'[a-z0-9_]+', token) for token in tokens):
                        entry['status']='invalid_value'
                    else: entry['controllers']=tokens
                elif text == 'max' or re.fullmatch(r'[0-9]+',text):
                    entry['value']=text
                else: entry['status']='invalid_value'
            files[filename] = entry
        nodes[label] = {'path':str(path),'files':files}
    layout = (not malformed and mount['status']=='readable' and
              any(x=={'mountpoint':'/sys/fs/cgroup','filesystem':'cgroup2'} for x in mounts))
    root_files = nodes['hierarchy_root']['files']
    slice_files = nodes['system_slice']['files']
    memory = 'memory' in root_files['cgroup.controllers'].get('controllers',[])
    descendant = ('memory' in slice_files['cgroup.controllers'].get('controllers',[]) and
                  'memory' in slice_files['cgroup.subtree_control'].get('controllers',[]) and
                  all(slice_files[k]['status']=='readable' for k in ('memory.high','memory.max','memory.swap.max')))
    evidence = layout and memory and descendant
    return {'status':'host_interfaces_observed' if evidence else 'incomplete_or_unsupported',
            'mountinfo':mount_report,'standard_cgroup_v2_mount_observed':layout,
            'nodes':nodes,'root_memory_controller_advertised':memory,
            'system_slice_child_memory_interfaces_observed':descendant,
            'host_interface_evidence_complete':evidence,
            'candidate_effective_enforcement':'UNVERIFIED',
            'bpf_imds_enforcement':'UNVERIFIED',
            'notes':['Root memory limit files are not required for descendant limit interfaces; every probe status is retained',
                     'Host interface availability does not verify candidate limits, ancestor effective caps or BPF enforcement',
                     'Only the standard mount and existing system.slice are inspected; no alternate mounts are followed']}


if __name__ == '__main__':
    report = cgroup_facts()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['host_interface_evidence_complete'] else 1)
