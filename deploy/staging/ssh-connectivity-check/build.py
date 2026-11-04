"""Local connectivity-manifest assembly only; never invokes SSH."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    spec = importlib.util.spec_from_file_location('local_connectivity_builder', HERE / 'run.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    blobs = {name: runner.read(runner.ROOT / name) for name in runner.ARTIFACTS}
    for name, expected in runner.PINNED_SOURCES.items():
        runner.need(runner.sha(blobs[name]) == expected)
    manifest = {'version': 1, 'action': 'connectivity-only', 'limits': runner.LIMITS,
        'remote_command': runner.REMOTE,
        'artifacts': {name: {'bytes': len(raw), 'sha256': runner.sha(raw)} for name, raw in blobs.items()},
        'supervisor_sha256': runner.sha(runner.bounded_source(blobs[runner.BASE]))}
    path = HERE / 'MANIFEST.json'
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'manifest_sha256': runner.sha(path.read_bytes()),
                      'runner_sha256': runner.sha(blobs[runner.OWN + 'run.py']),
                      'supervisor_sha256': manifest['supervisor_sha256'], 'remote_attempts': 0}))


if __name__ == '__main__':
    main()
