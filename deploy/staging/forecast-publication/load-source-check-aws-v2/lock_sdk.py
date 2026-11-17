"""Local dependency inventory, NOT SDK vendoring or remote discovery."""
import hashlib
import importlib.metadata
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSIONS = {'boto3': '1.43.98', 'botocore': '1.43.98', 's3transfer': '0.19.2',
            'jmespath': '1.1.0', 'python-dateutil': '2.9.0.post0', 'urllib3': '2.7.0', 'six': '1.17.0'}
ROOTS = ['boto3', 'botocore', 's3transfer', 'jmespath', 'dateutil', 'urllib3', 'six.py']


def main():
    site = Path(importlib.metadata.distribution('boto3').locate_file('')).resolve()
    paths = []
    for root in ROOTS:
        path = site / root
        paths.extend([path] if path.is_file() else path.rglob('*.py'))
    for name, version in VERSIONS.items():
        dist = importlib.metadata.distribution(name)
        if dist.version != version:
            raise ValueError('sdk_version_mismatch')
        paths.append(dist.locate_file(next(p for p in dist.files if str(p).endswith('.dist-info/METADATA'))))
    data = site / 'botocore/data'
    paths.extend(data.glob('*.json'))
    for service, version in [('ssm', '2014-11-06'), ('secretsmanager', '2017-10-17')]:
        paths.extend(p for p in (data / service / version).iterdir() if p.name.endswith(('.json', '.json.gz')))
    files = {}
    for path in sorted(set(paths)):
        if path.is_symlink() or not path.is_file():
            raise ValueError('sdk_file_type')
        raw = path.read_bytes()
        files[str(path.relative_to(site))] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    value = {'version': 1, 'runtime': [3, 14], 'versions': VERSIONS, 'code_roots': ROOTS, 'files': files}
    (HERE / 'SDK-LOCK.json').write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'sdk_files': len(files), 'sdk_bytes': sum(v['bytes'] for v in files.values()),
                      'sdk_lock_sha256': hashlib.sha256((HERE / 'SDK-LOCK.json').read_bytes()).hexdigest(), 'remote_attempts': 0}))


if __name__ == '__main__':
    main()
