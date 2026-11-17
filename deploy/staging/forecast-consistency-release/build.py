"""Local staging-origin build wrapper for the existing supported npm release build."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent


def build(out):
    out=Path(out)
    if not out.is_absolute() or out.parent.resolve(strict=True)!=out.parent or ROOT==out or ROOT in out.parents:
        raise ValueError('new_private_output_outside_repository_required')
    info=out.parent.stat()
    if info.st_uid!=os.geteuid() or info.st_mode & 0o022 or os.path.lexists(out):
        raise ValueError('unsafe_or_existing_output')
    settings=json.loads((HERE/'release-settings.json').read_text())
    if settings['origin']!='https://staging.powerflowenergy.dev':raise ValueError('staging_only')
    env={**os.environ,'VITE_COGNITO_AUTHORITY':settings['cognito_issuer'],
         'VITE_COGNITO_DOMAIN':settings['cognito_domain'],'VITE_COGNITO_CLIENT_ID':settings['cognito_client_id']}
    os.umask(0o077)
    result=subprocess.run(['npm','run','build:release','--','--origin',settings['origin'],'--out-dir',str(out)],
                          cwd=ROOT/'frontend',env=env,check=False)
    if result.returncode:raise SystemExit(result.returncode)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir',type=Path,required=True)
    build(parser.parse_args().out_dir)


if __name__=='__main__':main()
