"""Offline wheel verification and candidate baseline. No fetching or installation."""
import base64
import csv
import email.parser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
V2 = ROOT / 'deploy/staging/forecast-publication/load-source-check-aws-v2'
WHEEL_NAME = 'urllib3-2.8.0-py3-none-any.whl'
WHEEL_SHA = '0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3'
LOCK_SHA = 'da19f5a81c7741d19333e7bfcc25004c50fe2c83e31642c9f39c828518de35c4'
V2_MANIFEST_SHA = 'caafdcadedaa3fc899cd63e5005bd0f803990bea05ddba477c4f56815011c0e2'
DIST = 'urllib3-2.8.0.dist-info/'


def need(ok):
    if not ok:
        raise ValueError('independent_sdk_reference_rejected')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def old_lock():
    raw = (V2 / 'SDK-LOCK.json').read_bytes()
    need(digest(raw) == LOCK_SHA)
    return json.loads(raw)


def verify_sources():
    raw = (V2 / 'MANIFEST.json').read_bytes()
    need(digest(raw) == V2_MANIFEST_SHA)
    manifest = json.loads(raw)
    for name in ['deploy/staging/forecast-publication/load-source-check-aws-v2/sdk.py',
                 'src/powerflow_secrets.py', 'tests/test_load_source_aws_adapter.py']:
        content = (ROOT / name).read_bytes()
        need(manifest['artifacts'][name] == {'bytes': len(content), 'sha256': digest(content)})


def wheel_files(raw=None):
    raw = (HERE / 'reference' / WHEEL_NAME).read_bytes() if raw is None else raw
    need(len(raw) == 135717 and digest(raw) == WHEEL_SHA)
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
        need(len(wheel.infolist()) <= 100)
        total = 0
        for entry in wheel.infolist():
            path = PurePosixPath(entry.filename)
            need(not path.is_absolute() and '..' not in path.parts and '\\' not in entry.filename
                 and str(path) == entry.filename and entry.filename not in files
                 and (entry.filename.startswith('urllib3/') or entry.filename.startswith(DIST)))
            need(not entry.is_dir() and not stat.S_ISLNK(entry.external_attr >> 16))
            need(entry.file_size <= 1_000_000)
            total += entry.file_size
            need(total <= 2_000_000)
            files[entry.filename] = wheel.read(entry)
    record = DIST + 'RECORD'
    need(record in files)
    records = list(csv.reader(io.StringIO(files[record].decode('utf-8'))))
    need(len(records) == len(files) and all(len(row) == 3 for row in records))
    need(len({row[0] for row in records}) == len(files) and {row[0] for row in records} == set(files))
    for name, check, size in records:
        if name == record:
            need(check == size == '')
        else:
            encoded = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b'=').decode('ascii')
            need(check == 'sha256=' + encoded and size == str(len(files[name])))
    metadata = email.parser.BytesParser().parsebytes(files[DIST + 'METADATA'], headersonly=True)
    need(metadata.get_all('Name') == ['urllib3'] and metadata.get_all('Version') == ['2.8.0']
         and metadata['Requires-Python'] == '>=3.10')
    need('Programming Language :: Python :: 3.14' in metadata.get_all('Classifier', []))
    need(files['urllib3/_version.py'].find(b'2.8.0') >= 0)
    selected = {name: value for name, value in files.items() if name.startswith('urllib3/') and name.endswith('.py')}
    need(len(selected) == 36 and 'urllib3/__init__.py' in selected)
    selected[DIST + 'METADATA'] = files[DIST + 'METADATA']
    return selected


def baseline():
    old = old_lock()
    new = json.loads(json.dumps(old))
    # Carry forward the existing approved baseline; do not learn anything from EC2.
    new['files'] = {name: entry for name, entry in old['files'].items()
                    if not name.startswith(('urllib3/', 'urllib3-'))}
    for name, raw in wheel_files().items():
        new['files'][name] = {'bytes': len(raw), 'sha256': digest(raw)}
    new['versions']['urllib3'] = '2.8.0'
    need(len(new['files']) == 215)
    return new


def held_reference(site):
    """Reuse only local bytes already matching the unchanged approved V2 lock."""
    verify_sources()
    old = old_lock()
    held = wheel_files()
    for name, entry in old['files'].items():
        if name.startswith(('urllib3/', 'urllib3-')):
            continue
        path = site / name
        need(not any(parent.is_symlink() for parent in [path] + list(path.parents)))
        raw = path.read_bytes()
        need(entry == {'bytes': len(raw), 'sha256': digest(raw)})
        held[name] = raw
    need(set(held) == set(baseline()['files']))
    return held


def verify_provenance():
    value = json.loads((HERE / 'reference/pypi-provenance.json').read_bytes())
    need(value['version'] == 1 and len(value['attestation_bundles']) == 1)
    bundle = value['attestation_bundles'][0]
    need(bundle['publisher'] == {'environment': 'publish', 'kind': 'GitHub', 'repository': 'urllib3/urllib3', 'workflow': 'publish.yml'})
    statement = json.loads(base64.b64decode(bundle['attestations'][0]['envelope']['statement'], validate=True))
    need(statement['_type'] == 'https://in-toto.io/Statement/v1'
         and statement['predicateType'] == 'https://docs.pypi.org/attestations/publish/v1'
         and statement['subject'] == [{'name': WHEEL_NAME, 'digest': {'sha256': WHEEL_SHA}}])
    # This checks the subject against the TLS-fetched PyPI assertion. It is NOT
    # an independent local Sigstore signature/transparency-log verification.
    return {'publisher': bundle['publisher'], 'subject_sha256': WHEEL_SHA,
            'local_sigstore_signature_verification': False}
