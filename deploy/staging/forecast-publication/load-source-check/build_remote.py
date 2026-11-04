"""Local assembly only; creates the NEW remote manifest, never contacts a host."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    spec = importlib.util.spec_from_file_location('local_load_source_builder', HERE / 'run.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    blobs = {name: runner.read(runner.ROOT / name) for name in runner.ARTIFACTS}
    manifest = {'version': 1, 'action': 'fixed-load-source-check',
        'authentication': 'existing-env-provider-only-aws-fail-closed',
        'limits': {'remote_seconds': 60, 'local_seconds': 90, 'escalation_seconds': 5, 'attempts': 1, 'capture_bytes': 16384},
        'artifacts': {name: {'bytes': len(raw), 'sha256': runner.sha(raw)} for name, raw in blobs.items()},
        'payload_sha256': runner.sha(runner.assemble(blobs))}
    # Original local-only MANIFEST.json and historical evidence stay untouched.
    (HERE / 'REMOTE-MANIFEST.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'manifest_sha256': runner.sha((HERE / 'REMOTE-MANIFEST.json').read_bytes()),
                      'payload_sha256': manifest['payload_sha256'], 'remote_attempts': 0}))


if __name__ == '__main__':
    main()
