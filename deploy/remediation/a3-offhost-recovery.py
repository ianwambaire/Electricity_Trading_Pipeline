#!/usr/bin/env python3
"""A3 proposal. No network action without an explicit upload/restore subcommand.

Requires existing boto3; uses ordinary SDK credential chain, never root.
All destinations are new/private. Never deletes artifacts or retries requests.
"""
import argparse
import base64
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

ACCOUNT = '870755688674'
REGION = 'us-east-1'
BUCKET = 'powerflow-data-ian-2026-870755688674-us-east-1-an'
BACKUP_ID = '20261026T022230.137446Z'
PREFIX = 'recovery/phase5d2-a3/' + BACKUP_ID + '/'
SHA = '21fcb0e920ffaf13f214e39720e1176e012086d6ffa7b8a7ed736b6e4ab79690'
SIZE = 12115968
A2_SHA = 'e0144438075b5219a2b03a7dad982bab14bde81d92d6c79cf11253c91284262c'
NAMES = ('electricity_trading.db', 'manifest.json')


def require(ok, code):
    if not ok:
        raise ValueError(code)


def validator():
    path = Path(__file__).with_name('restore-operational-sqlite.py')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == A2_SHA, 'validator_hash')
    spec = importlib.util.spec_from_file_location('a3_a2', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def validate(directory, a2, expected_sha=SHA, expected_size=SIZE):
    require(directory.is_absolute() and directory.resolve(strict=True) == directory, 'canonical_source')
    require(directory.stat().st_uid == os.geteuid() and directory.stat().st_mode & 0o077 == 0, 'private_directory')
    with ExitStack() as stack:
        streams = {name: a2.open_private_input(directory / name, stack)[0] for name in NAMES}
        db, mf = streams[NAMES[0]], streams[NAMES[1]]
        require(os.fstat(db.fileno()).st_size == expected_size, 'database_size')
        require(0 < os.fstat(mf.fileno()).st_size <= 1024*1024, 'manifest_size')
        data = {name: stream.read() for name, stream in streams.items()}
        require(hashlib.sha256(data[NAMES[0]]).hexdigest() == expected_sha, 'database_hash')
        manifest = json.loads(data[NAMES[1]])
        require(manifest.get('backup_db') == NAMES[0] and manifest.get('sha256') == expected_sha
                and type(manifest.get('file_size_bytes')) is int
                and manifest['file_size_bytes'] == expected_size, 'manifest_identity')
        a2.no_sidecars(directory / NAMES[0])
        conn = a2.readonly(directory / NAMES[0], time.monotonic()+90, stack)
        objects = a2.schema(conn)
        tables = a2.core_contract(conn, objects)
        require(manifest.get('schema_objects') == objects and manifest.get('tables') == tables, 'manifest_schema')
        require(conn.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'integrity')
        require(sum(1 for _ in conn.execute('PRAGMA foreign_key_check')) == 0, 'foreign_keys')
        counts = {t: conn.execute('SELECT COUNT(*) FROM '+a2.identifier(t)).fetchone()[0] for t in a2.EXPECTED_COUNTS}
        require(counts == a2.EXPECTED_COUNTS, 'counts')
    return data


def checksum(data):
    return base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')


def guard_identity(sts, expected_role_arn):
    identity = sts.get_caller_identity()
    require(identity['Account'] == ACCOUNT and not identity['Arn'].endswith(':root'), 'account_or_root_identity')
    prefix = 'arn:aws:iam::'+ACCOUNT+':role/'
    require(expected_role_arn.startswith(prefix), 'expected_role_account')
    role_name = expected_role_arn[len(prefix):].split('/')[-1]
    require(bool(role_name), 'expected_role_name')
    # IAM role names are unique within an account, including across paths.
    # STS assumed-role ARNs omit IAM role paths; the session name is not fixed.
    assumed_prefix = 'arn:aws:sts::'+ACCOUNT+':assumed-role/'+role_name+'/'
    require(identity['Arn'].startswith(assumed_prefix)
            and bool(identity['Arn'][len(assumed_prefix):]), 'unapproved_role_identity')


def guard_bucket(s3, bucket):
    args = dict(Bucket=bucket, ExpectedBucketOwner=ACCOUNT)
    require(s3.get_bucket_location(**args).get('LocationConstraint') in (None, REGION), 'region')
    flags = s3.get_public_access_block(**args)['PublicAccessBlockConfiguration']
    require(all(flags.get(k) is True for k in ('BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets')), 'public_access_block')
    require(s3.get_bucket_versioning(**args).get('Status') == 'Enabled', 'versioning')
    rules = s3.get_bucket_encryption(**args)['ServerSideEncryptionConfiguration']['Rules']
    require(len(rules) == 1 and rules[0]['ApplyServerSideEncryptionByDefault']['SSEAlgorithm'] == 'AES256', 'encryption')
    require(s3.get_bucket_ownership_controls(**args)['OwnershipControls']['Rules'] == [{'ObjectOwnership':'BucketOwnerEnforced'}], 'ownership')


def upload(s3, bucket, data):
    require(bucket == BUCKET, 'unapproved_bucket')
    receipt = {'backup_id': BACKUP_ID, 'account': ACCOUNT, 'region': REGION, 'bucket': bucket, 'objects': {}}
    for name in NAMES:
        body = data[name]
        key = PREFIX + name
        put = s3.put_object(Bucket=bucket, Key=key, ExpectedBucketOwner=ACCOUNT,
                            Body=body, ContentLength=len(body), ServerSideEncryption='AES256',
                            ChecksumSHA256=checksum(body), IfNoneMatch='*')
        version = put.get('VersionId')
        require(version and version != 'null', 'missing_version')
        # Emit each successful version immediately: an interrupted pair is not a valid recovery set.
        item = dict(key=key, version=version, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        receipt['objects'][name] = item
        print(json.dumps({'uploaded_object': name, **item}), flush=True)
        head = s3.head_object(Bucket=bucket, Key=key, VersionId=version,
                              ExpectedBucketOwner=ACCOUNT, ChecksumMode='ENABLED')
        require(head['ContentLength'] == len(body) and head.get('ChecksumSHA256') == checksum(body)
                and head.get('ServerSideEncryption') == 'AES256' and head.get('VersionId') == version, 'uploaded_verification')
    return receipt


def download(s3, receipt, destination):
    require(receipt['bucket'] == BUCKET, 'unapproved_bucket')
    require(receipt['account'] == ACCOUNT and receipt['region'] == REGION and receipt['backup_id'] == BACKUP_ID, 'receipt_identity')
    require(set(receipt['objects']) == set(NAMES), 'receipt_objects')
    for name in NAMES:
        item = receipt['objects'][name]
        require(item['key'] == PREFIX+name and item['version'] and item['version'] != 'null', 'receipt_key_version')
        require(type(item['bytes']) is int and 0 < item['bytes'] <= (SIZE if name == NAMES[0] else 1024*1024), 'receipt_size')
        if name == NAMES[0]:
            require(item['sha256'] == SHA and item['bytes'] == SIZE, 'receipt_database')
        obj = s3.get_object(Bucket=receipt['bucket'], Key=item['key'], VersionId=item['version'],
                            ExpectedBucketOwner=ACCOUNT, ChecksumMode='ENABLED')
        try:
            body = obj['Body'].read(item['bytes']+1)
        finally:
            obj['Body'].close()
        require(len(body) == item['bytes'] and hashlib.sha256(body).hexdigest() == item['sha256']
                and obj.get('ChecksumSHA256') == checksum(body) and obj.get('ServerSideEncryption') == 'AES256'
                and obj.get('VersionId') == item['version'], 'download_verification')
        write_new(destination/name, body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    up = sub.add_parser('upload'); up.add_argument('--source', type=Path, required=True); up.add_argument('--bucket', required=True)
    up.add_argument('--receipt', type=Path, required=True)
    down = sub.add_parser('restore'); down.add_argument('--receipt', type=Path, required=True)
    down.add_argument('--receipt-sha256', required=True); down.add_argument('--workspace', type=Path, required=True)
    for child in (up, down):
        child.add_argument('--expected-role-arn', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    started = time.monotonic()
    try:
        a2 = validator()
        import boto3
        from botocore.config import Config
        session = boto3.Session(region_name=REGION)
        config = Config(connect_timeout=5, read_timeout=20, retries={'total_max_attempts':1})
        guard_identity(session.client('sts', config=config), args.expected_role_arn)
        s3 = session.client('s3', config=config)
        if args.action == 'upload':
            require(args.bucket == BUCKET, 'unapproved_bucket')
            require(args.receipt.is_absolute() and args.receipt.parent.resolve(strict=True) == args.receipt.parent, 'receipt_parent_canonical')
            parent = args.receipt.parent.stat()
            require(parent.st_uid == os.geteuid() and parent.st_mode & 0o077 == 0, 'receipt_parent_private')
            require(not os.path.lexists(args.receipt), 'receipt_exists')
            data = validate(args.source, a2)
            guard_bucket(s3, args.bucket)
            receipt = upload(s3, args.bucket, data)
            raw = json.dumps(receipt, indent=2).encode()
            write_new(args.receipt, raw)
            print(json.dumps({'status':'passed','receipt_sha256':hashlib.sha256(raw).hexdigest()}))
        else:
            raw = args.receipt.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == args.receipt_sha256, 'receipt_hash')
            receipt = json.loads(raw)
            workspace = args.workspace
            require(workspace.is_absolute() and workspace.parent.resolve(strict=True) == workspace.parent, 'canonical_workspace')
            require(workspace.parent.stat().st_uid == os.geteuid() and workspace.parent.stat().st_mode & 0o022 == 0, 'workspace_parent')
            fs = os.statvfs(workspace.parent)
            require(fs.f_bavail*fs.f_frsize >= 3*SIZE+256*1024*1024, 'free_space')
            workspace.mkdir(mode=0o700, exist_ok=False)
            inputs = workspace/'download'; inputs.mkdir(mode=0o700)
            download(s3, receipt, inputs)
            validate(inputs, a2)
            result = a2.run_restore(inputs, workspace/'restored', SHA, a2.EXPECTED_COUNTS)
            require(result['status'] == 'passed', 'isolated_restore_failed')
            print(json.dumps({'status':'passed','off_host_restoration_verified':True,'total_seconds':round(time.monotonic()-started,6),'restore':result}))
        return 0
    except Exception:
        # No exception strings/SDK payloads, credentials, raw records or raw SQL.
        print(json.dumps({'status':'failed','action':args.action,'partial_artifacts_retained':True}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
