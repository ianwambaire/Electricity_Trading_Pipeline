"""Verify local package only. No network or production operations."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[3]
manifest_path = Path(__file__).with_name('MANIFEST.json')
raw = manifest_path.read_bytes()
if len(sys.argv) != 2 or hashlib.sha256(raw).hexdigest() != sys.argv[1]:
    raise SystemExit('manifest_hash_mismatch')
manifest = json.loads(raw)
for item in manifest['artifacts']:
    path = root / item['path']
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise SystemExit('artifact_hash_mismatch: ' + item['path'])
print(json.dumps({'package_integrity':'PASS','files':len(manifest['artifacts']),'production_access':False}))
