"""Local V3 binding assembly. Never refreshes SDK hashes or connects remotely."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    spec = importlib.util.spec_from_file_location('local_sdk_v3_builder', HERE / 'run.py')
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    raw = r.read(r.ROOT / (r.V2 + 'MANIFEST.json'))
    r.need(r.sha(raw) == r.V2_SHA)
    v2 = json.loads(raw)
    names = set(v2['artifacts']) | r.NEW_FILES | {r.V2 + 'MANIFEST.json'}
    blobs = {name: r.read(r.ROOT / name) for name in names}
    for name, item in v2['artifacts'].items():
        r.need(item == {'bytes': len(blobs[name]), 'sha256': r.sha(blobs[name])})
    m = {'version': 3, 'action': 'passive-sdk-verification-only', 'v2_manifest_sha256': r.V2_SHA,
         'sdk_lock_sha256': r.LOCK_SHA, 'limits': r.LIMITS,
         'artifacts': {name: {'bytes': len(raw), 'sha256': r.sha(raw)} for name, raw in blobs.items()},
         'payload_sha256': r.sha(r.assemble(blobs))}
    path = HERE / 'MANIFEST.json'
    path.write_text(json.dumps(m, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'manifest_sha256': r.sha(path.read_bytes()), 'payload_sha256': m['payload_sha256'],
                      'runner_sha256': r.sha(blobs[r.OWN + 'run.py']),
                      'inspector_sha256': r.sha(blobs[r.OWN + 'inspect.py']), 'remote_attempts': 0}))


if __name__ == '__main__':
    main()
