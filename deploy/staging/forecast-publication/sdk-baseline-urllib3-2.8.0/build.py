"""Build the separate candidate baseline offline; never replace V2 or install SDKs."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    spec = importlib.util.spec_from_file_location('local_reference', HERE / 'reference.py')
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    r.verify_sources()
    r.verify_provenance()
    value = r.baseline()
    path = HERE / 'SDK-LOCK.json'
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')
    names = ['reference.py', 'build.py', 'REVIEW.md', 'SDK-LOCK.json',
             'reference/' + r.WHEEL_NAME, 'reference/pypi-provenance.json']
    artifacts = {str((HERE / name).relative_to(r.ROOT)): {'bytes': len((HERE / name).read_bytes()),
                 'sha256': r.digest((HERE / name).read_bytes())} for name in names}
    for name in ['tests/test_urllib3_280_compatibility.py', 'tests/test_load_source_aws_adapter.py',
                 'deploy/staging/forecast-publication/load-source-check-aws-v2/sdk.py',
                 'deploy/staging/forecast-publication/load-source-check-aws-v2/SDK-LOCK.json',
                 'deploy/staging/forecast-publication/load-source-check-aws-v2/MANIFEST.json',
                 'src/powerflow_secrets.py']:
        raw = (r.ROOT / name).read_bytes()
        artifacts[name] = {'bytes': len(raw), 'sha256': r.digest(raw)}
    report = {'version': 1, 'purpose': 'local-compatibility-reference-only',
              'source': {'index': 'https://pypi.org/project/urllib3/2.8.0/',
                         'wheel_url': 'https://files.pythonhosted.org/packages/92/9d/c4e665119135114480843e7ab388fa94d8480650450e6f8e26b70d323a4c/' + r.WHEEL_NAME,
                         'wheel_sha256': r.WHEEL_SHA, 'base_sdk_lock_sha256': r.LOCK_SHA,
                         'provenance': 'PyPI TLS assertion and matching subject; no local Sigstore verification'},
              'artifacts': artifacts}
    (HERE / 'MANIFEST.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'sdk_lock_sha256': r.digest(path.read_bytes()),
                      'manifest_sha256': r.digest((HERE / 'MANIFEST.json').read_bytes()),
                      'sdk_files': len(value['files']), 'urllib3_files': len(r.wheel_files()), 'remote_attempts': 0}))


if __name__ == '__main__':
    main()
