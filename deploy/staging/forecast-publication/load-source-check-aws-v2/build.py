"""Local immutable-package assembly; no connections and no SDK refresh."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    spec = importlib.util.spec_from_file_location('local_aws_source_builder', HERE / 'run.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    original = runner.original_manifest(runner.read(runner.ROOT / runner.ORIGINAL))
    names = set(original['artifacts']) | runner.NEW_FILES | {runner.ORIGINAL}
    blobs = {name: runner.read(runner.ROOT / name) for name in names}
    for name, item in original['artifacts'].items():
        runner.need(item == {'bytes': len(blobs[name]), 'sha256': runner.sha(blobs[name])})
    m = {'version': 2, 'supersedes_manifest_sha256': runner.ORIGINAL_SHA, 'limits': runner.LIMITS,
        'artifacts': {name: {'bytes': len(raw), 'sha256': runner.sha(raw)} for name, raw in blobs.items()},
        'payload_sha256': runner.sha(runner.assemble(blobs))}
    path = HERE / 'MANIFEST.json'
    path.write_text(json.dumps(m, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'manifest_sha256': runner.sha(path.read_bytes()), 'payload_sha256': m['payload_sha256'],
                      'runner_sha256': runner.sha(blobs[runner.OWN + 'run.py']),
                      'inspector_sha256': runner.sha(blobs[runner.OWN + 'inspect.py']), 'remote_attempts': 0}))


if __name__ == '__main__':
    main()
