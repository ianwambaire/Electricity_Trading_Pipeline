"""Assemble only a separate immutable candidate-bound local package."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    spec = importlib.util.spec_from_file_location('candidate_bound_builder', HERE / 'run.py')
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    reviewed = r.reviewed_artifacts()
    names = set(reviewed) | r.NEW_FILES
    blobs = {name: r.read(r.ROOT / name) for name in names}
    for name, item in reviewed.items():
        r.need(item == {'bytes': len(blobs[name]), 'sha256': r.sha(blobs[name])})
    m = {'version': 4, 'candidate_manifest_sha256': r.CANDIDATE_SHA, 'sdk_lock_sha256': r.LOCK_SHA,
         'wheel_sha256': r.WHEEL_SHA, 'limits': r.LIMITS,
         'artifacts': {name: {'bytes': len(raw), 'sha256': r.sha(raw)} for name, raw in blobs.items()},
         'payload_sha256': r.sha(r.assemble(blobs))}
    path = HERE / 'MANIFEST.json'
    path.write_text(json.dumps(m, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'manifest_sha256': r.sha(path.read_bytes()), 'payload_sha256': m['payload_sha256'],
                      'runner_sha256': r.sha(blobs[r.OWN + 'run.py']),
                      'inspector_sha256': r.sha(blobs[r.OWN + 'inspect.py']),
                      'bound_artifacts': len(blobs), 'remote_attempts': 0}))


if __name__ == '__main__':
    main()
