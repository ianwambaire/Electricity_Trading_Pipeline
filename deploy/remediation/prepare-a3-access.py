#!/usr/bin/env python3
"""Offline A3 policy proposal generator. Writes new files only; never calls AWS.

Role existence, trust and approved sign-in sessions must be established separately.
Output is a proposal, not an authorization or effective-IAM simulator.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ACCOUNT = '870755688674'
BUCKET = 'powerflow-data-ian-2026-870755688674-us-east-1-an'
BASE = 'arn:aws:s3:::' + BUCKET
PREFIX = 'recovery/phase5d2-a3/20261026T022230.137446Z/'
NAMES = ('electricity_trading.db', 'manifest.json')
OBJECTS = [BASE+'/'+PREFIX+name for name in NAMES]


def role(arn):
    if not re.fullmatch(r'arn:aws:iam::'+ACCOUNT+r':role/(?:[A-Za-z0-9+=,.@_-]+/)*[A-Za-z0-9+=,.@_-]+', arn):
        raise ValueError('invalid_role_arn')
    if any(token in arn.upper() for token in ('PLACEHOLDER','EXACT_','APPROVED_','TBD','<','>')):
        raise ValueError('role_placeholder')
    if arn.split('/')[-1] == 'PowerFlowEC2Role':
        raise ValueError('runtime_role_cannot_be_recovery_identity')
    return arn


def policies(uploader, reader, versions=None):
    uploader, reader = role(uploader), role(reader)
    if uploader == reader:
        raise ValueError('distinct_recovery_roles_required')
    if versions is not None and (set(versions) != set(NAMES) or any(not isinstance(v,str) or not 0 < len(v) <= 1024 or v=='null' or any(not 33 <= ord(c) <= 126 for c in v) or any(token in v.upper() for token in ('PLACEHOLDER','ACTUAL_APPROVED','EXACT_RETURNED','TBD')) for v in versions.values())):
        raise ValueError('two_real_versions_required')
    bucket = {'Version':'2012-10-17','Statement':[
        {'Sid':'A3DenyInsecureTransport','Effect':'Deny','Principal':'*','Action':'s3:*',
         'Resource':OBJECTS,'Condition':{'Bool':{'aws:SecureTransport':'false'}}},
        {'Sid':'A3DenyDeletion','Effect':'Deny','Principal':'*',
         'Action':['s3:DeleteObject','s3:DeleteObjectVersion'],'Resource':OBJECTS},
        {'Sid':'A3DenyUnexpectedWriter','Effect':'Deny','Principal':'*','Action':'s3:PutObject',
         'Resource':OBJECTS,'Condition':{'ArnNotEquals':{'aws:PrincipalArn':uploader}}},
        {'Sid':'A3DenyUnexpectedReader','Effect':'Deny','Principal':'*',
         'Action':['s3:GetObject','s3:GetObjectVersion'],'Resource':OBJECTS,
         'Condition':{'ArnNotEquals':{'aws:PrincipalArn':[uploader,reader]}}},
        {'Sid':'A3RequireAES256','Effect':'Deny','Principal':'*','Action':'s3:PutObject',
         'Resource':OBJECTS,'Condition':{'StringNotEquals':{'s3:x-amz-server-side-encryption':'AES256'}}},
        {'Sid':'A3RequireCreateOnly','Effect':'Deny','Principal':'*','Action':'s3:PutObject',
         'Resource':OBJECTS,'Condition':{'StringNotEquals':{'s3:if-none-match':'*'}}},
    ]}
    upload = {'Version':'2012-10-17','Statement':[
        {'Sid':'A3CreateTwoObjects','Effect':'Allow','Action':'s3:PutObject','Resource':OBJECTS,
         'Condition':{'StringEquals':{'s3:x-amz-server-side-encryption':'AES256','s3:if-none-match':'*'}}},
        {'Sid':'A3VerifyExactVersions','Effect':'Allow','Action':'s3:GetObjectVersion','Resource':OBJECTS},
        {'Sid':'A3ReadStorageGuardrails','Effect':'Allow','Action':[
            's3:GetBucketLocation','s3:GetBucketPublicAccessBlock','s3:GetBucketVersioning',
            's3:GetEncryptionConfiguration','s3:GetBucketOwnershipControls'],'Resource':BASE},
    ]}
    # Before actual upload versions exist, no read permission is granted at all.
    read = {'Version':'2012-10-17','Statement':[
        {'Sid':'A3NoWriteOrDelete','Effect':'Deny',
         'Action':['s3:PutObject','s3:DeleteObject','s3:DeleteObjectVersion'],'Resource':OBJECTS},
        {'Sid':'A3NeverReadLatest','Effect':'Deny','Action':'s3:GetObject','Resource':OBJECTS},
    ]}
    if not versions:
        read['Statement'].append({'Sid':'A3NoReadBeforeVersionApproval','Effect':'Deny','Action':'s3:GetObjectVersion','Resource':OBJECTS})
    if versions:
        read['Statement'] += [
            {'Sid':'A3DenyOtherVersion'+str(i),'Effect':'Deny','Action':'s3:GetObjectVersion',
             'Resource':resource,'Condition':{'StringNotEquals':{'s3:VersionId':versions[name]}}}
            for i,(name,resource) in enumerate(zip(NAMES,OBJECTS))
        ]
        read['Statement'] += [
            {'Sid':'A3ReadVersion'+str(i),'Effect':'Allow','Action':'s3:GetObjectVersion',
             'Resource':resource,'Condition':{'StringEquals':{'s3:VersionId':versions[name]}}}
            for i,(name,resource) in enumerate(zip(NAMES,OBJECTS))
        ]
    return {'bucket-policy.json':bucket,'uploader-policy.json':upload,'reader-policy.json':read}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uploader-role-arn',required=True)
    parser.add_argument('--reader-role-arn',required=True)
    parser.add_argument('--db-version')
    parser.add_argument('--manifest-version')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if bool(args.db_version) != bool(args.manifest_version):
        parser.error('both version IDs are required together')
    versions=dict(zip(NAMES,(args.db_version,args.manifest_version))) if args.db_version else None
    output=policies(args.uploader_role_arn,args.reader_role_arn,versions)
    parent=args.output.parent
    if not args.output.is_absolute() or parent.resolve(strict=True)!=parent or parent.stat().st_uid!=os.geteuid() or parent.stat().st_mode & 0o022:
        parser.error('output must be new under a canonical owned non-writable-by-others parent')
    os.umask(0o077)
    args.output.mkdir(mode=0o700,exist_ok=False)
    hashes = {}
    for name,document in output.items():
        fd=os.open(args.output/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        raw=(json.dumps(document,indent=2)+'\n').encode()
        with os.fdopen(fd,'wb') as out:
            out.write(raw);out.flush();os.fsync(out.fileno())
        hashes[name]=hashlib.sha256(raw).hexdigest()
    metadata={'status':'proposal_only_not_applied','account':ACCOUNT,'bucket':BUCKET,
              'uploader_role_arn':args.uploader_role_arn,'reader_role_arn':args.reader_role_arn,
              'object_arns':OBJECTS,'version_bound_reader':bool(versions),'versions':versions,
              'sha256':hashes,'runtime_role_preserved':'PowerFlowEC2Role',
              'requires':['named_role_existence_and_trust_review','effective_policy_review',
                          'current_bucket_policy_diff_and_private_backup','explicit_apply_approval',
                          'separate_upload_approval','separate_restore_approval'],
              'not_verified':['AWS_policy_validation','effective_IAM','live_access','encryption_readback'],
              'cleanup':'no_artifact_deletion_authorized'}
    fd=os.open(args.output/'approval-metadata.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as out:
        json.dump(metadata,out,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
    print(json.dumps({'status':'prepared_only','version_bound_reader':bool(versions),'files':list(output)+['approval-metadata.json']}))


if __name__=='__main__':
    main()
