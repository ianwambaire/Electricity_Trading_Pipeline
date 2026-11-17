"""Private, immutable inference receipts. No inference, network or source writes."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import uuid

import pandas as pd
from processing.build_silver_dataset import QUARTER_HOURLY_PRICE_START_UTC


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def snapshot(path):
    """Use exactly these bytes for both cleaning and completeness evidence."""
    path = Path(path)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ) or len(raw) != after.st_size:
        raise ValueError('Inference source changed during read.')
    return raw


def inputs_from_sources(raw_sources, issue_time, prices, load):
    """Project only necessary observations from the same bytes used by cleaners."""
    result = {}
    for source, hourly, lags in [('price', prices, (1, 24, 168)), ('load', load, (1, 24))]:
        raw = pd.read_csv(io.BytesIO(raw_sources[source]))
        raw['timestamp'] = pd.to_datetime(raw['timestamp'], utc=True, errors='raise')
        required = sorted({issue_time-pd.Timedelta(hours=i) for i in (*range(24), *lags)})
        field = 'price_eur_mwh' if source == 'price' else 'load_mw'
        result[source+'_history'] = {hour.isoformat(): float(hourly.loc[hour, field]) for hour in required}
        samples = {}
        for hour in required:
            points = raw.loc[raw['timestamp'].dt.floor('h') == hour].sort_values('timestamp')
            sample = {'points': [{'timestamp': row['timestamp'].isoformat(), field: float(row[field])}
                                 for _, row in points.iterrows()]}
            if source == 'price':
                resolutions = points.get('source_resolution', pd.Series(index=points.index, dtype=object)).fillna(
                    'PT15M' if hour >= QUARTER_HOURLY_PRICE_START_UTC else 'PT60M')
                if resolutions.nunique() != 1:
                    raise ValueError('Ambiguous price resolution in inference evidence.')
                sample['resolution'] = resolutions.iloc[0]
            samples[hour.isoformat()] = sample
        result[source+'_samples'] = samples
    generation = pd.read_csv(io.BytesIO(raw_sources['generation']))
    generation['timestamp'] = pd.to_datetime(generation['timestamp'], utc=True, errors='raise')
    fields = {'Biomass':'biomass_mw', 'Fossil Brown coal/Lignite':'lignite_mw',
              'Fossil Gas':'gas_mw', 'Fossil Hard coal':'hard_coal_mw',
              'Hydro Run-of-river and poundage':'hydro_mw', 'Solar':'solar_mw',
              'Wind Offshore':'wind_offshore_mw', 'Wind Onshore':'wind_onshore_mw'}
    points = generation.loc[generation['timestamp'].dt.floor('h') == issue_time].sort_values('timestamp')
    result['generation_quarters'] = [{'timestamp': row['timestamp'].isoformat(),
                                      **{new: float(row[old]) for old,new in fields.items()}}
                                     for _,row in points.iterrows()]
    return result


def receipt(forecast, provenance, manifest_raw, matrix, inputs, source_hashes, execution):
    """Bind the exact pre-predict matrix and all output files to one invocation."""
    manifest = json.loads(manifest_raw)
    names = list(matrix.columns)
    values = [float(value) for value in matrix.iloc[0]]
    if len(matrix) != 1 or names != manifest['features']:
        raise ValueError('Inference evidence feature order mismatch.')
    release_manifest_sha256 = digest(manifest_raw)
    manifest_raw = canonical({key: manifest[key] for key in (
        'release_id','model_sha256','feature_contract_sha256','feature_count','features','horizons_hours')})
    inputs = {**inputs, 'features': dict(zip(names, values))}
    forecast_raw = forecast.to_csv(index=False).encode()
    proof = {'version': 1, 'execution': execution, 'inputs': inputs,
             'inference': {'feature_names': names, 'feature_values': values,
                           'issue_time': pd.Timestamp(forecast.iloc[0]['forecast_issue_time']).isoformat(),
                           'target_times': [pd.Timestamp(t).isoformat() for t in forecast['target_timestamp']],
                           'model': {key: manifest[key] for key in ('release_id','model_sha256','feature_contract_sha256')},
                           'source_sha256': source_hashes,
                           'release_manifest_sha256': release_manifest_sha256},
             }
    provenance_raw = canonical({**provenance, 'inference_evidence': {
        'schema_version': 1, 'run_id': execution['run_id'], 'payload_sha256': digest(canonical(proof))}})
    proof['artifacts'] = {'forecast_sha256': digest(forecast_raw), 'provenance_sha256': digest(provenance_raw),
                          'model_manifest_sha256': digest(manifest_raw)}
    files = {'forecast.csv': forecast_raw, 'provenance.json': provenance_raw,
             'model.json': manifest_raw, 'evidence.json': canonical(proof)}
    files['integrity.json'] = canonical({'version': 1, 'run_id': execution['run_id'],
                                       'sha256': {name: digest(raw) for name,raw in files.items()}})
    return files


def persist(root, files, run_id):
    """Only a fully fsynced directory becomes visible as a completed receipt."""
    if str(uuid.UUID(run_id)) != run_id:
        raise ValueError('Invalid inference identity.')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise ValueError('Inference receipt directory must be private.')
    destination = root/run_id
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Inference receipt already exists.')
    temporary = Path(tempfile.mkdtemp(prefix='.partial-', dir=root))
    # Partial artifacts are retained, never selected as complete receipts.
    for name,raw in files.items():
        with (temporary/name).open('xb') as stream:
            os.chmod(temporary/name, 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(temporary, os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    temporary.rename(destination)
    fd = os.open(root, os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return destination
