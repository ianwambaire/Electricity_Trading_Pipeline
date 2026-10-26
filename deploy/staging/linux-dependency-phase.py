"""Disposable-container phases. No production data/providers; binary wheels only."""
import email.parser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import sysconfig
import threading
import time
import zipfile

PHASE=sys.argv[1]
WHEELS=Path('/wheelhouse');LOCK=Path('/candidate/requirements/api.lock')
EXPECTED='b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3'
assert hashlib.sha256(LOCK.read_bytes()).hexdigest()==EXPECTED
assert sys.version_info[:3]==(3,14,7) and platform.machine()=='x86_64'
ENV={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/tmp/home','AWS_EC2_METADATA_DISABLED':'true',
     'PIP_CONFIG_FILE':'/dev/null','PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1',
     'PYTHONPATH':'/candidate/src'}
started=time.monotonic();peak=[0];finished=threading.Event()
def disk():
    tmp=0
    for directory in ('/tmp','/venv'):
        if Path(directory).exists():
            fs=os.statvfs(directory);tmp+=(fs.f_blocks-fs.f_bfree)*fs.f_frsize
    wheel=sum(p.stat().st_blocks*512 for p in WHEELS.iterdir() if p.is_file())
    return tmp+wheel

def sample():
    while not finished.is_set():
        peak[0]=max(peak[0],disk());finished.wait(0.5)
thread=threading.Thread(target=sample,daemon=True);thread.start()
report={'phase':PHASE,'python':platform.python_version(),'machine':platform.machine(),
        'abi':sysconfig.get_config_var('SOABI'),'libc':platform.libc_ver(),
        'lock_sha256':EXPECTED,'status':'failed','last_completed_operation':None}

def operation(label,args):
    report['current_operation']=label
    print('OPERATION_START='+label,flush=True)
    p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=ENV)
    for line in p.stdout:print(line.rstrip('\n'),flush=True)
    code=p.wait();print('OPERATION_EXIT='+label+':'+str(code),flush=True)
    report.setdefault('operations',{})[label]=code
    if code:raise RuntimeError('operation_failed:'+label)
    report['last_completed_operation']=label


def inventory():
    pins={re.sub(r'[-_.]+','-',line.split('==')[0]).lower():line.split('==')[1]
          for line in LOCK.read_text().splitlines() if '==' in line}
    assert len(pins)==26
    records=[]
    for p in sorted(WHEELS.iterdir()):
        if p.name=='manifest.json':continue
        assert p.is_file() and not p.is_symlink() and p.suffix=='.whl'
        with zipfile.ZipFile(p) as z:
            names=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')];assert len(names)==1
            metadata=email.parser.BytesParser().parsebytes(z.read(names[0]))
            wheel=[n for n in z.namelist() if n.endswith('.dist-info/WHEEL')];assert len(wheel)==1
            tags=[line[5:] for line in z.read(wheel[0]).decode().splitlines() if line.startswith('Tag: ')]
        name=re.sub(r'[-_.]+','-',metadata['Name']).lower();version=metadata['Version']
        assert pins.get(name)==version,(name,version)
        records.append({'filename':p.name,'name':name,'version':version,'tags':tags,
                        'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    assert len(records)==26 and {x['name'] for x in records}==set(pins)
    return records

try:
    if PHASE=='acquire':
        os.umask(0o022)
        operation('binary_wheel_acquisition',[sys.executable,'-m','pip','--isolated','--disable-pip-version-check',
            'download','--index-url','https://pypi.org/simple','--only-binary=:all:','--no-cache-dir',
            '--retries','0','--timeout','15','--progress-bar','off','--dest',str(WHEELS),'-r',str(LOCK)])
        records=inventory();manifest={'lock_sha256':EXPECTED,'source':'https://pypi.org/simple','wheels':records}
        data=(json.dumps(manifest,indent=2)+'\n').encode();(WHEELS/'manifest.json').write_bytes(data)
        report.update(wheels=records,wheel_manifest_sha256=hashlib.sha256(data).hexdigest())
    elif PHASE=='offline':
        expected=json.loads((WHEELS/'manifest.json').read_bytes());records=inventory()
        assert records==expected['wheels'] and expected['lock_sha256']==EXPECTED
        report.update(wheel_manifest_sha256=hashlib.sha256((WHEELS/'manifest.json').read_bytes()).hexdigest(),wheels=records)
        operation('clean_venv_creation',[sys.executable,'-I','-S','-B','-m','venv','/venv/api-verify'])
        python='/venv/api-verify/bin/python'
        operation('offline_exact_install',[python,'-m','pip','--isolated','--disable-pip-version-check','install',
            '--no-index','--find-links='+str(WHEELS),'--only-binary=:all:','--no-cache-dir','--progress-bar','off',
            '-r',str(LOCK)])
        operation('pip_check',[python,'-m','pip','--isolated','check'])
        operation('linux_regressions_compiled_and_lifecycle',[python,'-B','/regression.py'])
        paths=json.loads(subprocess.check_output([python,'-B','-c',
            'import sys,sysconfig,json,os; print(json.dumps({"executable":sys.executable,"real_executable":os.path.realpath(sys.executable),"base_prefix":sys.base_prefix,"stdlib":sysconfig.get_path("stdlib")}))'],env=ENV))
        report['container_interpreter_paths']=paths
        report['container_paths_outside_protected_homes']=all(not any(v==p or v.startswith(p+'/') for p in ('/home','/root','/run/user')) for v in paths.values())
        unit=Path('/candidate-unit.service').read_text()
        assert 'ProtectHome=true' in unit and 'MemoryMax=512M' in unit and 'MemorySwapMax=0' in unit
        assert 'ExecStart=/opt/powerflow/react-current/.venv-api/bin/uvicorn api.app:app --host 127.0.0.1 --port 8010 --workers 1' in unit
        report['unit_static_checks']='passed; EC2 base interpreter and effective systemd enforcement UNVERIFIED'
        report['venv_allocated_kib']=int(subprocess.check_output(['/usr/bin/du','-sk','/venv/api-verify']).split()[0])
    else:raise ValueError('unknown_phase')
    report['wheelhouse_allocated_kib']=int(subprocess.check_output(['/usr/bin/du','-sk',str(WHEELS)]).split()[0])
    report['wheelhouse_file_bytes']=sum(p.stat().st_size for p in WHEELS.iterdir() if p.is_file())
    report['status']='passed'
except Exception as error:
    report['error_type']=type(error).__name__
    if isinstance(error,RuntimeError) and str(error).startswith('operation_failed:'):report['failed_operation']=str(error).split(':',1)[1]
finally:
    if Path('/venv/api-verify').is_dir():
        report['venv_allocated_kib']=int(subprocess.check_output(['/usr/bin/du','-sk','/venv/api-verify']).split()[0])
    finished.set();thread.join(timeout=1);peak[0]=max(peak[0],disk())
    report['sampled_peak_workspace_allocated_bytes']=peak[0]
    report['peak_scope']='sampled0.5s: scratch+venv tmpfs usage plus wheel files; excludes image layers/host logs; not instantaneous peak'
    report['elapsed_seconds']=round(time.monotonic()-started,3)
    print('RESULT_JSON='+json.dumps(report),flush=True)
raise SystemExit(0 if report['status']=='passed' else 1)
