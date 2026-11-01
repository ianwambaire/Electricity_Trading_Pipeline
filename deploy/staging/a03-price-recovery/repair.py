"""Offline, hash-bound repair preparation. Never replaces the source CSV.

The XML must be acquired separately from the authenticated ENTSO-E endpoint.
All artifacts are private and created exclusively; there is no overwrite flag.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
import pandas as pd
from ingestion.fetch_entsoe_data import parse_price_observations

ALLOWED = pd.to_datetime(['2026-10-24T11:45Z', '2026-10-24T12:15Z'], utc=True)
START = pd.Timestamp('2026-10-24T11:00Z')
END = pd.Timestamp('2026-10-24T13:00Z')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(source, xml, source_sha, xml_sha):
    if sha(source) != source_sha or sha(xml) != xml_sha:
        raise ValueError('source_hash_mismatch')
    old = pd.read_csv(io.BytesIO(source), float_precision='round_trip')
    if set(old.columns) != {'timestamp', 'price_eur_mwh', 'source_resolution'}:
        raise ValueError('unexpected_source_schema')
    old['timestamp'] = pd.to_datetime(old['timestamp'], utc=True, errors='raise')
    if old['timestamp'].duplicated().any() or old.isna().any().any():
        raise ValueError('invalid_existing_source')
    old = old.set_index('timestamp')
    fresh = parse_price_observations(xml.decode('utf-8'))
    fresh = fresh.loc[(fresh.index >= START) & (fresh.index < END)]
    expected = pd.date_range(START, END, freq='15min', inclusive='left')
    if not fresh.index.equals(expected) or not fresh.source_resolution.eq('PT15M').all():
        raise ValueError('upstream_interval_incomplete')
    overlap = old.index.intersection(fresh.index)
    if not old.loc[overlap, 'price_eur_mwh'].eq(fresh.loc[overlap, 'price_eur_mwh']).all() or not old.loc[overlap, 'source_resolution'].eq(fresh.loc[overlap, 'source_resolution']).all():
        raise ValueError('existing_value_conflict')
    missing = fresh.index.difference(old.index)
    if not set(missing).issubset(set(ALLOWED)):
        raise ValueError('unapproved_missing_timestamp')
    merged = pd.concat([old, fresh.loc[missing]]).sort_index()
    # Every old observation and column must survive unchanged.
    pd.testing.assert_frame_equal(merged.loc[old.index, old.columns], old, check_freq=False)
    # Keep every original byte, including numeric formatting, unchanged.
    # Existing ingestion/cleaning normalizes timestamp order on read.
    if len(missing):
        additions = fresh.loc[missing].reset_index()[['timestamp', 'price_eur_mwh', 'source_resolution']]
        additions = additions.loc[:, list(pd.read_csv(io.BytesIO(source), nrows=0).columns)]
        candidate = source + (b'' if source.endswith(b'\n') else b'\n') + additions.to_csv(index=False, header=False).encode()
    else:
        candidate = source
    report = {
        'schema_version': 1, 'source_sha256': source_sha, 'xml_sha256': xml_sha,
        'candidate_sha256': sha(candidate), 'source_bytes': len(source),
        'candidate_bytes': len(candidate), 'added_timestamps': [t.isoformat() for t in missing],
        'added_count': len(missing), 'unchanged_existing_rows': len(old),
        'idempotent_noop': len(missing) == 0,
        'decoder': fresh.attrs.get('price_decode_diagnostics', []),
        'production_modified': False,
    }
    return candidate, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--xml', type=Path, required=True)
    p.add_argument('--source-sha256', required=True)
    p.add_argument('--xml-sha256', required=True)
    p.add_argument('--output', type=Path, help='Omit for read-only dry-run; new private directory only')
    args = p.parse_args()
    for path in (args.source, args.xml):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('unsafe_or_oversized_input')
    source, xml = args.source.read_bytes(), args.xml.read_bytes()
    candidate, report = prepare(source, xml, args.source_sha256, args.xml_sha256)
    if args.output:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError('destination_conflict')
        import shutil
        if shutil.disk_usage(args.output.parent).free < 2 * 1024**3 + len(source) + len(candidate):
            raise ValueError('insufficient_disk')
        args.output.mkdir(mode=0o700)
        for name, data in [('original.csv', source), ('candidate.csv', candidate), ('report.json', json.dumps(report, indent=2).encode())]:
            fd = os.open(args.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        for name, expected in [('original.csv', sha(source)), ('candidate.csv', sha(candidate))]:
            if sha((args.output / name).read_bytes()) != expected:
                raise ValueError('artifact_hash_mismatch')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
