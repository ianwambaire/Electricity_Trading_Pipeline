"""Strict, read-only next24 publication contract. No model loading or inference."""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics

UTC = dt.timezone.utc
MAX_BYTES = 100_000
MAX_AGE = dt.timedelta(hours=3)
RELEASE = 'next24h-hgb-2026-09-21-v1'
MODEL_HASH = '69a3fa10f45c18c4733b3f8e12792e36ec9b209b7afd5e94a9932315e4dde0ed'
CONTRACT_HASH = '1d6554e469a869613dd91d820b0537b4562321ea69e8827ecb83137950078a88'
FEATURES = ('hour', 'day_of_week', 'month', 'is_weekend', 'price_eur_mwh', 'price_lag_1h', 'price_lag_24h', 'price_lag_168h', 'price_rolling_mean_24h', 'price_rolling_std_24h', 'load_mw', 'load_lag_1h', 'load_lag_24h', 'load_rolling_mean_24h', 'biomass_mw', 'lignite_mw', 'gas_mw', 'hard_coal_mw', 'hydro_mw', 'nuclear_mw', 'solar_mw', 'wind_offshore_mw', 'wind_onshore_mw', 'wind_total_mw', 'renewable_generation_mw', 'renewable_share', 'temperature_2m', 'relative_humidity_2m', 'wind_speed_10m', 'cloud_cover', 'shortwave_radiation')

class Withheld(ValueError):
    """A publication cannot be served or activated safely."""

def require(condition):
    if not condition:
        raise Withheld("Forecast publication is withheld.")

def time(value):
    require(isinstance(value, str))
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None)
        return result.astimezone(UTC)
    except (ValueError, TypeError, OverflowError) as error:
        raise Withheld("Forecast publication is withheld.") from error

def number(value):
    require(type(value) in (int, float) and math.isfinite(value))
    return float(value)

def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected))

def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    try:
        require(len(raw) <= MAX_BYTES)
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: require(False))
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        raise Withheld("Forecast publication is withheld.") from error

def _validate(raw, expected_hash, now=None):
    now = now or dt.datetime.now(UTC)
    require(now.tzinfo is not None and re.fullmatch(r"[0-9a-f]{64}", expected_hash or ""))
    require(hashlib.sha256(raw).hexdigest() == expected_hash)
    bundle = decode(raw)
    keys(bundle, ("version", "forecasts", "model", "provenance", "inputs", "execution"))
    require(type(bundle["version"]) is int and bundle["version"] == 1)
    model = bundle["model"]
    keys(model, ("release", "model_sha256", "feature_contract_sha256"))
    require(model == {"release": RELEASE, "model_sha256": MODEL_HASH, "feature_contract_sha256": CONTRACT_HASH})
    rows = bundle["forecasts"]
    require(isinstance(rows, list) and len(rows) == 24)
    issue = time(rows[0].get("issue_time")) if isinstance(rows[0], dict) else None
    require(issue is not None and issue.minute == issue.second == issue.microsecond == 0)
    require(dt.timedelta(0) <= now - issue <= MAX_AGE)
    for horizon, row in enumerate(rows, 1):
        keys(row, ("issue_time", "target_time", "horizon_hours", "predicted_price_eur_mwh", "model_release"))
        require(time(row["issue_time"]) == issue and type(row["horizon_hours"]) is int and row["horizon_hours"] == horizon)
        require(time(row["target_time"]) == issue + dt.timedelta(hours=horizon) and row["model_release"] == RELEASE)
        number(row["predicted_price_eur_mwh"])
    execution = bundle["execution"]
    keys(execution, ("run_id", "started_at", "completed_at", "issued_at", "status"))
    require(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", execution["run_id"]) is not None)
    started, issued, completed = (time(execution[k]) for k in ("started_at", "issued_at", "completed_at"))
    require(issue < started <= issued <= completed <= now and execution["status"] == "GENERATED")
    provenance = bundle["provenance"]
    keys(provenance, ("issue_time", "weather_hour", "weather_acquired_at", "weather_source"))
    require(time(provenance["issue_time"]) == time(provenance["weather_hour"]) == issue)
    require(started <= time(provenance["weather_acquired_at"]) <= issued)
    require(provenance["weather_source"] == "open_meteo_forecast_api_operational_model")
    inputs = bundle["inputs"]
    keys(inputs, ("features", "price_history", "load_history", "price_samples", "load_samples", "generation_quarters"))
    features = inputs["features"]
    keys(features, FEATURES)
    for value in features.values():
        number(value)
    require(features["hour"] == issue.hour and features["day_of_week"] == issue.weekday())
    require(features["month"] == issue.month and features["is_weekend"] == int(issue.weekday() >= 5))
    for source, lags in (("price", (1,24,168)), ("load", (1,24))):
        history = inputs[source+"_history"]
        require(isinstance(history, dict))
        required = {issue-dt.timedelta(hours=i) for i in range(24)} | {issue-dt.timedelta(hours=i) for i in lags}
        actual = {time(k): number(v) for k,v in history.items()}
        require(len(actual) == len(history) and set(actual) == required)
        samples = inputs[source+"_samples"]
        require(isinstance(samples, dict) and len(samples) == len(required) and {time(k) for k in samples} == required)
        for hour_text, sample in samples.items():
            hour = time(hour_text)
            keys(sample, ("resolution", "points") if source == "price" else ("points",))
            resolution = sample.get("resolution", "PT15M")
            require(resolution in ("PT15M", "PT60M"))
            count = 4 if resolution == "PT15M" else 1
            points = sample["points"]
            require(isinstance(points, list) and len(points) == count)
            field = "price_eur_mwh" if source == "price" else "load_mw"
            for index, point in enumerate(points):
                keys(point, ("timestamp", field))
                require(time(point["timestamp"]) == hour+dt.timedelta(minutes=15*index))
                number(point[field])
            require(math.isclose(actual[hour],statistics.mean(point[field] for point in points),rel_tol=1e-10,abs_tol=1e-10))
        value = features["price_eur_mwh" if source == "price" else "load_mw"]
        require(value == actual[issue])
        for lag in lags:
            require(features[f"{source}_lag_{lag}h"] == actual[issue-dt.timedelta(hours=lag)])
        values = [actual[issue-dt.timedelta(hours=i)] for i in range(24)]
        require(math.isclose(features[source+"_rolling_mean_24h"], statistics.mean(values), rel_tol=1e-10, abs_tol=1e-10))
        if source == "price":
            require(math.isclose(features["price_rolling_std_24h"], statistics.stdev(values), rel_tol=1e-10, abs_tol=1e-10))
    generation = inputs["generation_quarters"]
    fields = ("biomass_mw", "lignite_mw", "gas_mw", "hard_coal_mw", "hydro_mw", "solar_mw", "wind_offshore_mw", "wind_onshore_mw")
    require(isinstance(generation,list) and len(generation)==4)
    for index, row in enumerate(generation):
        keys(row, ("timestamp", *fields))
        require(time(row["timestamp"]) == issue+dt.timedelta(minutes=15*index))
        for field in fields:
            number(row[field])
    for field in fields:
        require(math.isclose(features[field], statistics.mean(row[field] for row in generation), rel_tol=1e-10))
    require(features["wind_total_mw"] == features["wind_offshore_mw"]+features["wind_onshore_mw"])
    renewable = sum(features[k] for k in ("solar_mw","wind_total_mw","biomass_mw","hydro_mw"))
    total = renewable+sum(features[k] for k in ("lignite_mw","gas_mw","hard_coal_mw","nuclear_mw"))
    require(total != 0 and math.isclose(features["renewable_generation_mw"],renewable) and math.isclose(features["renewable_share"],renewable/total))
    # The complete generation issue hour must have finished before issuance.
    require(issue+dt.timedelta(hours=1) <= started)
    return bundle

def validate(raw, expected_hash, now=None):
    try:
        return _validate(raw, expected_hash, now)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, IndexError) as error:
        raise Withheld("Forecast publication is withheld.") from error


def safe_file(path):
    import stat
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid in (0,os.geteuid()) and not info.st_mode & 0o022 and info.st_size <= MAX_BYTES)
    with os.fdopen(os.open(path, os.O_RDONLY|os.O_NOFOLLOW), "rb") as stream:
        return stream.read(MAX_BYTES+1)

def read_active(root, now=None):
    """Resolve current exactly once; concurrent publications cannot mix files."""
    root = Path(root)
    try:
        for directory in (root, root/"releases"):
            require(directory.is_dir() and not directory.is_symlink() and directory.stat().st_uid in (0,os.geteuid()) and not directory.stat().st_mode & 0o022)
        target = os.readlink(root/"current")
        require(re.fullmatch(r"releases/[0-9a-f]{64}", target) is not None)
        directory = root/target
        require(directory.is_dir() and not directory.is_symlink() and directory.stat().st_uid in (0,os.geteuid()) and not directory.stat().st_mode & 0o022)
        raw = safe_file(directory/"bundle.json")
        return validate(raw,target.split("/")[1],now)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        raise Withheld("Forecast publication is withheld.") from error


def verify_inference_receipt(proof, forecast_raw, provenance_raw, model_raw, rows, manifest):
    """Require a versioned, cross-file receipt before building a publication."""
    keys(proof, ('version', 'execution', 'inputs', 'inference', 'artifacts'))
    require(type(proof['version']) is int and proof['version'] == 1)
    keys(proof['artifacts'], ('forecast_sha256','provenance_sha256','model_manifest_sha256'))
    require(proof['artifacts'] == dict(zip(
        ('forecast_sha256','provenance_sha256','model_manifest_sha256'),
        (hashlib.sha256(raw).hexdigest() for raw in (forecast_raw,provenance_raw,model_raw)))))
    payload = {key: value for key,value in proof.items() if key != 'artifacts'}
    binding = decode(provenance_raw).get('inference_evidence')
    require(binding == {'schema_version':1, 'run_id':proof['execution']['run_id'],
                        'payload_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()).hexdigest()})
    inference = proof['inference']
    keys(inference, ('feature_names','feature_values','issue_time','target_times','model','source_sha256','release_manifest_sha256'))
    require(inference['feature_names'] == list(FEATURES))
    values = inference['feature_values']
    require(isinstance(values,list) and len(values) == len(FEATURES))
    for value in values: number(value)
    require(proof['inputs']['features'] == dict(zip(FEATURES,values)))
    require(len(rows) == 24 and time(inference['issue_time']) == time(rows[0]['issue_time']))
    require(isinstance(inference['target_times'],list) and len(inference['target_times']) == 24)
    require([time(t) for t in inference['target_times']] == [time(row['target_time']) for row in rows])
    require(inference['model'] == {key: manifest[key] for key in ('release_id','model_sha256','feature_contract_sha256')})
    require(isinstance(inference['release_manifest_sha256'],str) and re.fullmatch('[0-9a-f]{64}',inference['release_manifest_sha256']))
    keys(inference['source_sha256'], ('price','load','generation'))
    require(all(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) for value in inference['source_sha256'].values()))
