"""Version-one sanitized operational evidence. Standard library; no DB/network/ML.

A digest checks integrity, not producer authenticity. Only a trusted producer may
write the separately provisioned store. This module is not wired into live APIs.
"""
import datetime as dt
import hashlib
import json
import re
import uuid

UTC = dt.timezone.utc
MAX_BYTES = 16384
MAX_AGE = dt.timedelta(minutes=90)
EXECUTIONS = {'SCHEDULED', 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', 'CRASHED'}
INFERENCES = {'NOT_RUN', 'GENERATED', 'UNCHANGED', 'WITHHELD', 'UNAVAILABLE', 'FAILED', 'UNKNOWN'}
DELIVERIES = {'NOT_RUN', 'PUBLISHED', 'SKIPPED_WITHHELD', 'SKIPPED_EXPIRED',
              'SKIPPED_DUPLICATE', 'REJECTED_OLDER_ISSUE', 'DISABLED',
              'REJECTED_INFERENCE', 'FAILED', 'UNKNOWN'}
GATES = {'JOINT_PRICE_LOAD_HOUR', 'PRICE_HISTORY', 'LOAD_HISTORY', 'GENERATION',
         'WEATHER', 'MODEL_INTEGRITY', 'FEATURE_CONTRACT', 'INPUT_FRESHNESS', 'UNKNOWN'}
REASONS = {'INPUTS_UNAVAILABLE', 'INPUTS_INCOMPLETE', 'INPUTS_STALE',
           'MODEL_UNVERIFIED', 'FEATURES_UNVERIFIED', 'UNKNOWN'}


class InvalidEvidence(ValueError):
    """Only fixed, safe categories may leave the validator."""


def require(ok, code='INCONSISTENT'):
    if not ok:
        raise InvalidEvidence(code)


def keys(value, fields):
    require(type(value) is dict and set(value) == set(fields), 'SCHEMA')


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value) is not None, 'TIMESTAMP')
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise InvalidEvidence('TIMESTAMP') from None


def identifier(value):
    try:
        require(isinstance(value, str) and str(uuid.UUID(value)) == value, 'IDENTITY')
    except (ValueError, AttributeError, TypeError):
        raise InvalidEvidence('IDENTITY') from None


def canonical(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError):
        raise InvalidEvidence('SCHEMA') from None
    require(len(raw) <= MAX_BYTES, 'SIZE')
    return raw


def decode(raw):
    require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, 'SIZE')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'SCHEMA')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: require(False, 'SCHEMA'))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidEvidence('SCHEMA') from None


def _validate(raw, digest, now):
    require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) is not None, 'HASH')
    require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, 'SIZE')
    require(hashlib.sha256(raw).hexdigest() == digest, 'HASH')
    require(isinstance(now, dt.datetime) and now.tzinfo is not None, 'TIMESTAMP')
    b = decode(raw)
    keys(b, ('version', 'observed_at', 'execution', 'inference', 'delivery', 'provenance'))
    require(type(b['version']) is int and b['version'] == 1, 'SCHEMA')
    e, i, d, p = (b[k] for k in ('execution', 'inference', 'delivery', 'provenance'))
    keys(e, ('flow_run_id', 'deployment_id', 'pipeline_run_id', 'scheduled_at', 'started_at', 'completed_at', 'outcome'))
    keys(i, ('outcome', 'task_run_id', 'receipt_id', 'issue_time', 'withholding'))
    keys(d, ('outcome', 'receipt_id', 'bundle_sha256', 'published_at'))
    keys(p, ('source', 'origin', 'flow_run_id', 'pipeline_run_id', 'task_flow_run_id'))
    require(all(isinstance(v, str) and v in choices for v, choices in
                ((e['outcome'], EXECUTIONS), (i['outcome'], INFERENCES), (d['outcome'], DELIVERIES))), 'STATUS')
    for k in ('flow_run_id', 'deployment_id'):
        identifier(e[k])
    require(e['pipeline_run_id'] is None or isinstance(e['pipeline_run_id'], str) and
            re.fullmatch('[0-9a-f]{32}', e['pipeline_run_id']) is not None, 'IDENTITY')
    require(p['source'] == 'PREFECT_AND_PERSISTED_PIPELINE' and p['origin'] == 'NATURAL_SCHEDULE', 'PROVENANCE')
    require(p['flow_run_id'] == e['flow_run_id'] and p['pipeline_run_id'] == e['pipeline_run_id'], 'IDENTITY')
    if i['task_run_id'] is not None:
        identifier(i['task_run_id'])
        require(p['task_flow_run_id'] == e['flow_run_id'] and e['pipeline_run_id'] is not None, 'IDENTITY')
    else:
        require(p['task_flow_run_id'] is None and i['outcome'] in {'NOT_RUN', 'UNKNOWN'}, 'IDENTITY')
    for value in (i['receipt_id'], d['receipt_id']):
        if value is not None:
            identifier(value)
    observed, scheduled = timestamp(b['observed_at']), timestamp(e['scheduled_at'])
    started = timestamp(e['started_at']) if e['started_at'] is not None else None
    completed = timestamp(e['completed_at']) if e['completed_at'] is not None else None
    require(scheduled <= observed <= now, 'TIMELINE')
    if started is not None:
        require(scheduled <= started <= observed, 'TIMELINE')
    if completed is not None:
        require((started or scheduled) <= completed <= observed, 'TIMELINE')
    if e['outcome'] in {'SCHEDULED', 'PENDING'}:
        require(started is None and completed is None and i['outcome'] == d['outcome'] == 'NOT_RUN', 'TIMELINE')
    elif e['outcome'] == 'RUNNING':
        require(started is not None and completed is None, 'TIMELINE')
    else:
        require(completed is not None and (started is not None or e['outcome'] in {'CANCELLED', 'CRASHED'}), 'TIMELINE')
    generated = i['outcome'] in {'GENERATED', 'UNCHANGED'}
    if generated:
        require(i['receipt_id'] is not None and i['issue_time'] is not None, 'RECEIPT')
        issue = timestamp(i['issue_time'])
        require(started is not None and issue <= started and
                issue.minute == issue.second == issue.microsecond == 0 and i['withholding'] is None, 'RECEIPT')
    else:
        require(i['receipt_id'] is None and i['issue_time'] is None, 'RECEIPT')
    if i['outcome'] == 'WITHHELD':
        if i['withholding'] is not None:
            keys(i['withholding'], ('reason', 'gate'))
            require(isinstance(i['withholding']['reason'], str) and i['withholding']['reason'] in REASONS and
                    isinstance(i['withholding']['gate'], str) and i['withholding']['gate'] in GATES, 'WITHHOLDING')
        require(d['outcome'] in {'SKIPPED_WITHHELD', 'DISABLED', 'UNKNOWN'}, 'STATUS')
    else:
        require(i['withholding'] is None, 'WITHHOLDING')
        require(d['outcome'] != 'SKIPPED_WITHHELD', 'STATUS')
    if d['outcome'] in {'PUBLISHED', 'SKIPPED_DUPLICATE', 'SKIPPED_EXPIRED', 'REJECTED_OLDER_ISSUE'}:
        require(generated and d['receipt_id'] == i['receipt_id'], 'RECEIPT')
    else:
        require(d['receipt_id'] is None, 'RECEIPT')
    if d['outcome'] == 'PUBLISHED':
        require(isinstance(d['bundle_sha256'], str) and re.fullmatch('[0-9a-f]{64}', d['bundle_sha256']) is not None, 'HASH')
    else:
        require(d['bundle_sha256'] is None and d['published_at'] is None, 'STATUS')
    if d['published_at'] is not None:
        # Optional only when an authentic timestamp was persisted. Task bounds
        # must never be substituted for an exact publication timestamp.
        require(started is not None and started <= timestamp(d['published_at']) <= observed, 'TIMELINE')
    require(i['outcome'] in {'NOT_RUN', 'UNKNOWN'} or started is not None, 'TIMELINE')
    if i['outcome'] in {'NOT_RUN', 'UNKNOWN'}:
        require(d['outcome'] in {'NOT_RUN', 'DISABLED', 'REJECTED_INFERENCE', 'UNKNOWN'}, 'STATUS')
    elif not generated and i['outcome'] != 'WITHHELD':
        require(d['outcome'] in {'NOT_RUN', 'DISABLED', 'REJECTED_INFERENCE', 'FAILED', 'UNKNOWN'}, 'STATUS')
    return b


def validate(raw, digest, now):
    try:
        return _validate(raw, digest, now)
    except InvalidEvidence:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        raise InvalidEvidence('SCHEMA') from None


def view(raw=None, digest=None, *, now, admin=False):
    """One selection shared by API projections. No historic DB fallback argument.

    Public summaries deliberately exclude UUIDs, detailed gates and receipt hashes.
    Stale content is never placed in current_execution, including for Admins.
    Live forecast eligibility MUST be supplied by the existing forecast selector.
    """
    result = {'status': 'MISSING', 'evidence_id': None, 'observed_at': None,
              'scheduled_at': None, 'fresh_until': None, 'current_execution': None,
              'forecast_eligibility': 'NOT_ASSESSED'}
    if raw is None:
        return result
    try:
        b = validate(raw, digest, now)
        e, i, d = (b[k] for k in ('execution', 'inference', 'delivery'))
        expiry = min(timestamp(b['observed_at']), timestamp(e['scheduled_at'])) + MAX_AGE
        result.update(evidence_id=digest, observed_at=b['observed_at'], scheduled_at=e['scheduled_at'], fresh_until=expiry.isoformat())
        if now >= expiry:
            result['status'] = 'STALE'
            return result
        result['status'] = 'VALID'
        result['current_execution'] = {
            'scheduled_at': e['scheduled_at'], 'started_at': e['started_at'], 'completed_at': e['completed_at'],
            'execution_outcome': e['outcome'], 'inference_outcome': i['outcome'],
            'publication_outcome': d['outcome'], 'source': b['provenance']['source']}
        if admin:
            result['admin'] = {'execution_identity': {k: e[k] for k in ('flow_run_id', 'deployment_id', 'pipeline_run_id')},
                               'inference': i, 'delivery': d}
        return result
    except (InvalidEvidence, TypeError, KeyError, OverflowError):
        result.update(status='INVALID', evidence_id=None, observed_at=None, scheduled_at=None, fresh_until=None)
        return result
