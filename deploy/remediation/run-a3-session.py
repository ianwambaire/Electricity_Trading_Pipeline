#!/usr/bin/env python3
"""PROPOSAL: MFA-gated in-memory A3 role session. No credential output/files.

The proposed operator/roles are NOT asserted to exist. Run only after explicit
AWS bootstrap, operator browser-login/MFA setup and transfer/restore approvals.
"""
import argparse
from contextlib import contextmanager
import getpass
import hashlib
import importlib.util
from pathlib import Path
import re
import sys

ACCOUNT='870755688674'
OPERATOR='arn:aws:iam::'+ACCOUNT+':user/PowerFlowA3Operator'
PAYLOAD_SHA256='4de44780530ecb6b5af422e54355ff4030a812ed9d65496a7d0d6ed385fe6a3f'
ROLES={'upload':'arn:aws:iam::'+ACCOUNT+':role/PowerFlowA3Uploader',
       'restore':'arn:aws:iam::'+ACCOUNT+':role/PowerFlowA3Reader'}


def assume(source, session_factory, action, serial, prompt=getpass.getpass):
    if action not in ROLES or not re.fullmatch(r'arn:aws:iam::'+ACCOUNT+r':mfa/[A-Za-z0-9+=,.@_/-]+',serial):
        raise ValueError('unapproved_action_or_mfa_device')
    identity=source.get_caller_identity()
    if identity.get('Account')!=ACCOUNT or identity.get('Arn')!=OPERATOR:
        raise ValueError('designated_nonroot_operator_required')
    code=prompt('Enter the AWS operator MFA code locally (never in chat): ')
    if not re.fullmatch(r'[0-9]{6}',code):raise ValueError('invalid_mfa_code')
    try:
        result=source.assume_role(RoleArn=ROLES[action],RoleSessionName='PowerFlowA3-'+action,
            DurationSeconds=900,SerialNumber=serial,TokenCode=code)
    finally:
        code=None
    credentials=result['Credentials']
    # Only in RAM. Do not put credentials into subprocess argv, environment or logs.
    return session_factory(aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],aws_session_token=credentials['SessionToken'],region_name='us-east-1')


@contextmanager
def arguments(values):
    previous=sys.argv
    try:sys.argv=values;yield
    finally:sys.argv=previous


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=ROLES)
    parser.add_argument('--source-profile',required=True)
    parser.add_argument('--authentication-only',action='store_true')
    parser.add_argument('--mfa-device-arn',required=True)
    options,payload=parser.parse_known_args()
    if options.authentication_only and payload:parser.error('authentication-only accepts no transfer arguments')
    if any(arg.startswith('--expected-role-arn') for arg in payload):parser.error('role is bound by action')
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print('{"status":"failed","detail":"Run this MFA step in your own interactive Terminal; no non-TTY code input."}')
        return 1
    try:
        path=Path(__file__).with_name('a3-offhost-recovery.py')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=PAYLOAD_SHA256:
            raise ValueError('payload_hash_changed')
        import logging
        logging.disable(logging.CRITICAL)  # SDK debug logs must never expose codes or temporary credentials.
        import boto3
        from botocore.config import Config
        source=boto3.Session(profile_name=options.source_profile,region_name='us-east-1')
        config=Config(connect_timeout=5,read_timeout=20,retries={'total_max_attempts':1})
        session=assume(source.client('sts',config=config),boto3.Session,options.action,options.mfa_device_arn)
        if options.authentication_only:
            if payload: raise ValueError('no_payload_arguments_in_authentication_only')
            identity=session.client('sts',config=config).get_caller_identity()
            expected='arn:aws:sts::'+ACCOUNT+':assumed-role/'+ROLES[options.action].rsplit('/',1)[1]+'/'
            if identity.get('Account')!=ACCOUNT or not identity.get('Arn','').startswith(expected):
                raise ValueError('unexpected_assumed_identity')
            print('{"status":"authenticated","scope":"STS only; no transfer"}')
            return 0
        path=Path(__file__).with_name('a3-offhost-recovery.py')
        spec=importlib.util.spec_from_file_location('a3_payload',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with arguments([str(path),options.action,*payload,'--expected-role-arn',ROLES[options.action]]):
            return module.main(session=session)
    except Exception:
        # No SDK exception bodies or temporary credentials escape to output.
        print('{"status":"failed","detail":"A3 operator/session verification failed; no automatic retry."}')
        return 1


if __name__=='__main__':raise SystemExit(main())
