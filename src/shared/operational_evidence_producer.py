"""Read-only association adapter. No Prefect client, file scanning or publishing.

Caller supplies authenticated Prefect records and committed receipt bytes. SQL is
fixed/bounded on an already read-only snapshot connection owned by the producer;
API consumers must never import this module or receive that connection.
"""
import csv
import datetime as dt
import hashlib
import io
import json
import re
import sqlite3
import time

from . import forecast_publication as forecast
from .operational_evidence import (InvalidEvidence, canonical, identifier, require,
                                   timestamp, validate)

FORECAST_TASK = 'Generate next24h production forecast'
DELIVERY_TASK = 'Publish validated staging next24h forecast'
# Exact recognized persisted reasons, never raw operational free text.
REASONS = {
    'Required price history unavailable for a fresh issue hour.': ('INPUTS_INCOMPLETE', 'PRICE_HISTORY'),
    'Required load history unavailable for a fresh issue hour.': ('INPUTS_INCOMPLETE', 'LOAD_HISTORY'),
    'Required load history unavailable at fresh price issue hours.': ('INPUTS_UNAVAILABLE', 'JOINT_PRICE_LOAD_HOUR'),
    'Current generation unavailable at fresh issue hours.': ('INPUTS_UNAVAILABLE', 'GENERATION'),
    'No complete operational weather hour is available.': ('INPUTS_UNAVAILABLE', 'WEATHER'),
    'Operational weather unavailable at fresh market issue hours.': ('INPUTS_UNAVAILABLE', 'WEATHER'),
}


def bounded_json(raw):
    require(isinstance(raw, str) and len(raw.encode()) <= 262144, 'RECORD_BOUND')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'RECORD_SCHEMA')
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: require(False, 'RECORD_SCHEMA'))
    require(type(result) is dict, 'RECORD_SCHEMA')
    return result


def natural(flow, expected_deployment, observed_at):
    identifier(expected_deployment)
    identifier(flow['id'])
    require(flow['deployment_id'] == expected_deployment and flow.get('auto_scheduled') is True, 'NOT_NATURAL')
    scheduled = timestamp(flow['expected_start_time'])
    require(scheduled.minute == 45 and scheduled.second == scheduled.microsecond == 0 and scheduled <= observed_at, 'SCHEDULE')
    require(flow['state']['type'] in {'COMPLETED', 'FAILED', 'CANCELLED', 'CRASHED'}, 'NOT_TERMINAL')
    start, end = timestamp(flow['start_time']), timestamp(flow['end_time'])
    require(scheduled <= start <= end <= observed_at, 'TIMELINE')
    return start, end


def _latest_natural(flows, expected_deployment, observed_at):
    """Do not silently step back to an older completed run if the latest is pending."""
    require(type(flows) is list and len(flows) <= 20, 'FLOW_BOUND')
    found = [f for f in flows if f.get('deployment_id') == expected_deployment and f.get('auto_scheduled') is True
             and timestamp(f['expected_start_time']) <= observed_at]
    require(found, 'NO_NATURAL_RUN')
    latest = max(timestamp(f['expected_start_time']) for f in found)
    matches = [f for f in found if timestamp(f['expected_start_time']) == latest]
    require(len(matches) == 1, 'AMBIGUOUS_RUN')
    natural(matches[0], expected_deployment, observed_at)
    return matches[0]


def latest_natural(*args, **kwargs):
    try:
        return _latest_natural(*args, **kwargs)
    except InvalidEvidence:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise InvalidEvidence('NATURAL_RUN_UNVERIFIED') from None


def task(tasks, prefix, flow, start, end):
    matches = [t for t in tasks if isinstance(t.get('name'), str) and
               (t['name'] == prefix or t['name'].startswith(prefix + '-'))]
    require(len(matches) <= 1, 'AMBIGUOUS_TASK')
    if not matches:
        return None
    t = matches[0]
    identifier(t['id'])
    require(t['flow_run_id'] == flow['id'], 'TASK_FLOW')
    require(start <= timestamp(t['start_time']) <= timestamp(t['end_time']) <= end, 'TASK_INTERVAL')
    return t


def receipt_bundle(files, observed_at):
    """Reuse frozen receipt/feature and forecast validators; expiry isn't op failure."""
    names = {'forecast.csv', 'provenance.json', 'model.json', 'evidence.json', 'integrity.json'}
    require(type(files) is dict and set(files) == names, 'RECEIPT_INVENTORY')
    require(all(isinstance(b, bytes) and len(b) <= forecast.MAX_BYTES for b in files.values()), 'RECEIPT_BOUND')
    proof, manifest, provenance, integrity = (forecast.decode(files[n]) for n in
                                             ('evidence.json', 'model.json', 'provenance.json', 'integrity.json'))
    require(integrity == {'version': 1, 'run_id': proof['execution']['run_id'],
                         'sha256': {n: hashlib.sha256(files[n]).hexdigest() for n in names - {'integrity.json'}}}, 'RECEIPT_INTEGRITY')
    reader = csv.DictReader(io.StringIO(files['forecast.csv'].decode('utf-8')))
    require(reader.fieldnames == ['forecast_issue_time', 'target_timestamp', 'horizon_hours', 'predicted_price_eur_mwh', 'model_release'], 'RECEIPT_SCHEMA')
    rows = []
    for row in reader:
        require(len(rows) < 24 and None not in row, 'RECEIPT_BOUND')
        rows.append(dict(issue_time=row['forecast_issue_time'], target_time=row['target_timestamp'],
                         horizon_hours=int(row['horizon_hours']), predicted_price_eur_mwh=float(row['predicted_price_eur_mwh']), model_release=row['model_release']))
    require(manifest.get('feature_count') == 31 and manifest.get('features') == list(forecast.FEATURES) and manifest.get('horizons_hours') == list(range(1, 25)), 'RECEIPT_SCHEMA')
    forecast.verify_inference_receipt(proof, files['forecast.csv'], files['provenance.json'], files['model.json'], rows, manifest)
    bundle = dict(version=1, forecasts=rows, execution=proof['execution'], inputs=proof['inputs'],
                  model=dict(release=manifest['release_id'], model_sha256=manifest['model_sha256'], feature_contract_sha256=manifest['feature_contract_sha256']),
                  provenance=dict(issue_time=provenance['forecast_issue_time'], weather_hour=provenance['weather_hour'],
                                  weather_acquired_at=provenance['weather_acquired_at_utc'], weather_source=provenance['weather_source']))
    raw = json.dumps(bundle, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        forecast.validate(raw, digest, observed_at)
    except forecast.ExpiredPublication:
        pass  # Structural/integrity checks completed at actual UTC, not backdated.
    return bundle, digest


def _associate(flow, tasks, records, stages, incidents, receipts, *, expected_deployment, observed_at):
    start, end = natural(flow, expected_deployment, observed_at)
    require(type(tasks) is list and len(tasks) < 100, 'TASK_BOUND')
    for item in tasks:identifier(item['id'])
    require(len({t['id'] for t in tasks}) == len(tasks) and all(t['flow_run_id'] == flow['id'] for t in tasks), 'TASK_FLOW')
    ft = task(tasks, FORECAST_TASK, flow, start, end)
    pt = task(tasks, DELIVERY_TASK, flow, start, end)
    require(type(stages) is list and len(stages) <= 200 and len(records) <= 12 and len(incidents) <= 12, 'RECORD_BOUND')
    if ft:
        # Existing reviewed association: unique internal forecast-stage interval
        # within two seconds of the exact Prefect task interval, not issue alone.
        matches = [s for s in stages if s['stage_name'] == 'Next24h forecast generation'
                   and abs((timestamp(s['start_timestamp_utc']) - timestamp(ft['start_time'])).total_seconds()) <= 2
                   and abs((timestamp(s['end_timestamp_utc']) - timestamp(ft['end_time'])).total_seconds()) <= 2]
    else:
        matches = [s for s in stages if s['stage_name'] == 'Total pipeline' and
                   start <= timestamp(s['start_timestamp_utc']) <= timestamp(s['end_timestamp_utc']) <= end]
    require(len(matches) == 1, 'INTERNAL_ASSOCIATION')
    stage = matches[0]; internal = stage['run_id']
    require(timestamp(stage['start_timestamp_utc']) <= timestamp(stage['end_timestamp_utc']), 'STAGE_INTERVAL')
    require(isinstance(internal, str) and re.fullmatch('[0-9a-f]{32}', internal) is not None, 'IDENTITY')
    summaries = [(r, bounded_json(r['message'])) for r in records]
    summaries = [(r, m) for r, m in summaries if m.get('run_id') == internal]
    require(len(summaries) == 1, 'SUMMARY_ASSOCIATION')
    record, summary = summaries[0]
    require(start <= timestamp(record['run_time']) <= min(end + dt.timedelta(seconds=5), observed_at), 'SUMMARY_TIME')
    pipeline_status = 'SUCCESS' if flow['state']['type'] == 'COMPLETED' else 'FAILED'
    require(record['status'] == summary.get('status') == pipeline_status, 'EXECUTION_OUTCOME')
    inference = summary.get('next24h_forecast_status', 'UNKNOWN')
    delivery = summary.get('next24h_publication_status', 'UNKNOWN')
    generated = inference in {'GENERATED', 'UNCHANGED'}
    require(ft is not None or inference in {'NOT_RUN', 'UNKNOWN'}, 'MISSING_TASK')
    require(ft is not None or pt is None, 'DELIVERY_TASK')
    if ft:
        require(ft['state']['type'] in {'COMPLETED', 'FAILED', 'CRASHED'}, 'TASK_STATE')
        if generated or inference == 'WITHHELD':require(ft['state']['type'] == 'COMPLETED', 'TASK_STATE')
    require(summary.get('next24h_forecast_generated') is (True if generated else False) or
            inference in {'UNKNOWN', 'NOT_RUN', 'FAILED', 'UNAVAILABLE'} and summary.get('next24h_forecast_generated') is None, 'INFERENCE_OUTCOME')
    if generated:require(stage['status'] == 'SUCCESS', 'STAGE_OUTCOME')
    if inference == 'WITHHELD':require(stage['status'] == 'WITHHELD', 'STAGE_OUTCOME')
    receipt_id = issue = bundle_hash = None
    require(type(receipts) is list and len(receipts) <= 4, 'RECEIPT_BOUND')
    if generated:
        require(len(receipts) == 1, 'RECEIPT_ASSOCIATION')
        bundle, digest = receipt_bundle(receipts[0], observed_at)
        execution = bundle['execution']; receipt_id = execution['run_id']; identifier(receipt_id)
        require(timestamp(ft['start_time']) <= timestamp(execution['started_at']) <= timestamp(execution['completed_at']) <= timestamp(ft['end_time']), 'RECEIPT_TASK')
        issue = bundle['forecasts'][0]['issue_time']
        require(timestamp(summary['next24h_forecast_issue_time']) == timestamp(issue), 'ISSUE_ASSOCIATION')
        if delivery == 'PUBLISHED':bundle_hash = digest
    else:
        require(not receipts, 'UNEXPECTED_RECEIPT')
    if delivery in {'PUBLISHED', 'SKIPPED_DUPLICATE', 'SKIPPED_EXPIRED', 'REJECTED_OLDER_ISSUE', 'SKIPPED_WITHHELD', 'FAILED'}:
        require(pt is not None and ft is not None and timestamp(pt['start_time']) >= timestamp(ft['end_time']), 'DELIVERY_TASK')
        require(pt['state']['type'] in ({'COMPLETED', 'FAILED', 'CRASHED'} if delivery == 'FAILED' else {'COMPLETED'}), 'DELIVERY_STATE')
    withholding = None
    if inference == 'WITHHELD':
        when = timestamp(summary['next24h_forecast_withheld_at_utc'])
        require(timestamp(ft['start_time']) <= when <= timestamp(ft['end_time']), 'WITHHELD_TIME')
        matched = []
        for row in incidents:
            if row['component'] != 'next24h forecast' or row['event_type'] != 'forecast_withheld':continue
            detail = bounded_json(row['details_json'])
            if detail.get('run_id') == internal:matched.append((row, detail))
        require(len(matched) <= 1, 'INCIDENT_ASSOCIATION')
        if matched:
            row, detail = matched[0]
            require(detail.get('forecast_freshness_status') == 'WITHHELD' and timestamp(detail['timestamp']) == when and
                    abs((timestamp(row['timestamp_utc']) - when).total_seconds()) <= 5 and
                    detail.get('latest_complete_hours') == summary.get('next24h_latest_complete_market_hours'), 'INCIDENT_BINDING')
            reason, gate = REASONS.get(detail.get('reason'), ('UNKNOWN', 'UNKNOWN'))
            withholding = dict(reason=reason, gate=gate)
    b = dict(version=1, observed_at=observed_at.isoformat(),
             execution=dict(flow_run_id=flow['id'], deployment_id=expected_deployment, pipeline_run_id=internal,
                            scheduled_at=flow['expected_start_time'], started_at=flow['start_time'], completed_at=flow['end_time'], outcome=flow['state']['type']),
             inference=dict(outcome=inference, task_run_id=ft['id'] if ft else None, receipt_id=receipt_id, issue_time=issue, withholding=withholding),
             delivery=dict(outcome=delivery, receipt_id=receipt_id if delivery in {'PUBLISHED', 'SKIPPED_DUPLICATE', 'SKIPPED_EXPIRED', 'REJECTED_OLDER_ISSUE'} else None,
                           bundle_sha256=bundle_hash, published_at=None),
             provenance=dict(source='PREFECT_AND_PERSISTED_PIPELINE', origin='NATURAL_SCHEDULE', flow_run_id=flow['id'], pipeline_run_id=internal, task_flow_run_id=flow['id'] if ft else None))
    raw = canonical(b); digest = hashlib.sha256(raw).hexdigest()
    validate(raw, digest, observed_at)
    return raw, digest


def associate(*args, **kwargs):
    try:
        return _associate(*args, **kwargs)
    except InvalidEvidence:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise InvalidEvidence('ASSOCIATION_UNVERIFIED') from None


def _from_snapshot(connection, flow, tasks, receipts, *, expected_deployment, observed_at):
    """SELECT-only reader; caller must own an existing consistent read-only snapshot.

    No path/credentials/network accepted. No PRAGMA write, migration or DB creation.
    Full publisher transport and scheduled hook are deliberately not activated.
    """
    require(connection.execute('PRAGMA query_only').fetchone()[0] == 1 and connection.in_transaction, 'READ_ONLY_SNAPSHOT_REQUIRED')
    start, end = natural(flow, expected_deployment, observed_at)
    def rows(sql, parameters, limit):
        cursor = connection.execute(sql, parameters)
        names = [c[0] for c in cursor.description]
        result = [dict(zip(names, r)) for r in cursor.fetchmany(limit+1)]
        require(len(result) <= limit, 'RECORD_BOUND')
        return result
    times = (start.isoformat(), (end+dt.timedelta(seconds=5)).isoformat())
    records = rows('SELECT run_time,status,substr(message,1,262145) AS message FROM pipeline_runs WHERE run_time>=? AND run_time<=? ORDER BY id DESC LIMIT 13', times, 12)
    stages = rows('SELECT run_id,stage_name,start_timestamp_utc,end_timestamp_utc,status FROM pipeline_stage_timings WHERE start_timestamp_utc>=? AND end_timestamp_utc<=? LIMIT 201', times, 200)
    incidents = rows('SELECT timestamp_utc,component,event_type,substr(details_json,1,262145) AS details_json FROM operational_incidents WHERE component=? AND event_type=? AND timestamp_utc>=? AND timestamp_utc<=? LIMIT 13', ('next24h forecast', 'forecast_withheld', *times), 12)
    return associate(flow, tasks, records, stages, incidents, receipts, expected_deployment=expected_deployment, observed_at=observed_at)


def from_snapshot(connection, flow, tasks, receipts, *, expected_deployment, observed_at):
    """Dedicated snapshot connection, with a two-second SQL execution budget."""
    deadline = time.monotonic() + 2
    ticks = [0]
    def budget():
        ticks[0] += 1
        return int(ticks[0] > 20000 or time.monotonic() >= deadline)
    connection.set_progress_handler(budget, 1000)
    try:
        return _from_snapshot(connection, flow, tasks, receipts,
                              expected_deployment=expected_deployment, observed_at=observed_at)
    except InvalidEvidence:
        raise
    except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise InvalidEvidence('SNAPSHOT_UNVERIFIED') from None
    finally:
        connection.set_progress_handler(None, 0)
