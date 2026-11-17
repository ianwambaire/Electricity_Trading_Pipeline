"""Fixed urllib3 metadata observations; never imports SDK or executes Python 3.14."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat

SITE = H['ROOT'] / '.venv-prod/lib/python3.14/site-packages'
VERSION = r'[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}(?:(?:a|b|rc)[0-9]{1,4}|\.(?:post|dev)[0-9]{1,4})?'
PATTERN = r'urllib3-(' + VERSION + r')\.dist-info'
EXPECTED = 'urllib3-2.7.0.dist-info'
SENTINEL = 'URLLIB3_METADATA'
CATEGORIES = {'FILE_MISSING', 'FILE_TYPE_MISMATCH', 'PERMISSION_MISMATCH', 'OWNER_MISMATCH',
              'HASH_MISMATCH', 'SYMLINK_OR_PATH_VIOLATION', 'SDK_VERSION_OR_LAYOUT_MISMATCH',
              'OTHER_VERIFICATION_FAILURE', 'MALFORMED_METADATA', 'BOUND_EXCEEDED', 'UNEXPECTED_LAYOUT'}
STAGES = {'RUNTIME', 'SITE_ANCHOR', 'ENUMERATION', 'DIRECTORY', 'METADATA', 'STABILITY', 'COMPLETE'}
CLASSIFICATIONS = {'LOCK_MATCH', 'HASH_MISMATCH', 'VERSION_MISMATCH', 'METADATA_MISSING'}
LAYOUTS = {'EXPECTED', 'MISSING', 'DIFFERENT_VERSION', 'MULTIPLE', 'INCOMPLETE', 'HASH_MISMATCH', 'UNVERIFIED'}
STATE = {'dependency_id': SENTINEL, 'category': None, 'stage': 'RUNTIME', 'verified_files': 0}
ALLOWED = {SENTINEL, 'PYTHON_RUNTIME'}


class Blocked(ValueError):
    pass


def stop(category):
    STATE['category'] = category if category in CATEGORIES else 'OTHER_VERIFICATION_FAILURE'
    raise Blocked('metadata_observation_blocked')


def need(ok, category):
    if not ok:
        stop(category)


def at(stage, identifier):
    STATE.update(stage=stage, dependency_id=identifier if identifier in ALLOWED else SENTINEL)


def identifier_ok(value):
    return type(value) is str and (value in {SENTINEL, 'PYTHON_RUNTIME'} or re.fullmatch(PATTERN + r'(?:/METADATA)?', value) is not None)


def validate_report(value):
    # Local evidence gate: no exception messages, raw names or arbitrary metadata.
    keys = {'status', 'runtime_verified', 'layout', 'expected_directory', 'expected_metadata', 'entries', 'failure'}
    if type(value) is not dict or set(value) != keys:
        raise ValueError('sanitized_report_rejected')
    ok = value['status'] in {'PASS', 'BLOCKED'} and type(value['runtime_verified']) is bool
    ok = ok and value['layout'] in LAYOUTS
    ok = ok and all(type(value[k]) is bool or value[k] is None for k in ['expected_directory', 'expected_metadata'])
    ok = ok and type(value['entries']) is list and len(value['entries']) <= 8
    if not ok:
        raise ValueError('sanitized_report_rejected')
    seen = set()
    for entry in value['entries']:
        if type(entry) is not dict or set(entry) != {'identifier', 'version', 'classification'}:
            raise ValueError('sanitized_report_rejected')
        name, version = entry['identifier'], entry['version']
        if not (type(name) is str and type(version) is str and re.fullmatch(VERSION, version)
                and name == 'urllib3-' + version + '.dist-info/METADATA'
                and entry['classification'] in CLASSIFICATIONS and name not in seen):
            raise ValueError('sanitized_report_rejected')
        seen.add(name)
    failure = value['failure']
    if value['status'] == 'PASS':
        if not value['runtime_verified'] or failure is not None or value['layout'] == 'UNVERIFIED':
            raise ValueError('sanitized_report_rejected')
        if not all(type(value[k]) is bool for k in ['expected_directory', 'expected_metadata']):
            raise ValueError('sanitized_report_rejected')
    elif not (type(failure) is dict and set(failure) == {'dependency_id', 'category', 'stage'}
              and identifier_ok(failure['dependency_id']) and failure['category'] in CATEGORIES
              and failure['stage'] in STAGES - {'COMPLETE'} and value['layout'] == 'UNVERIFIED'
              and value['expected_directory'] is None and value['expected_metadata'] is None
              and value['entries'] == []):
        raise ValueError('sanitized_report_rejected')
    return value


def metadata_bytes(directory, name):
    at('METADATA', name + '/METADATA')
    try:
        initial = os.stat('METADATA', dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    F['metadata'](initial)
    need(initial.st_size <= 65536, 'BOUND_EXCEEDED')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_NOATIME', 0)
    descriptor = os.open('METADATA', flags, dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        F['metadata'](before)
        need(F['identity'](initial) == F['identity'](before), 'SYMLINK_OR_PATH_VIOLATION')
        raw = stream.read(65537)
        need(len(raw) <= 65536, 'BOUND_EXCEEDED')
        after = os.fstat(stream.fileno())
    at('STABILITY', name + '/METADATA')
    named = os.stat('METADATA', dir_fd=directory, follow_symlinks=False)
    need(F['identity'](before) == F['identity'](after) == F['identity'](named), 'SYMLINK_OR_PATH_VIOLATION')
    return raw


def observe():
    # Reuse only V3's bound no-follow metadata primitives, never its SDK dispatcher.
    F.update(STATE=STATE, approved_ids=lambda: ALLOWED)
    ALLOWED.clear()
    ALLOWED.update({SENTINEL, 'PYTHON_RUNTIME'})
    site = F['directory_fd'](SITE, 'SITE_ANCHOR', SENTINEL)
    try:
        F['metadata'](os.fstat(site), directory=True)
        baseline = F['identity'](os.fstat(site))
        at('ENUMERATION', SENTINEL)
        names = []
        with os.scandir(site) as scan:
            for count, entry in enumerate(scan, 1):
                need(count <= 8192, 'BOUND_EXCEEDED')
                if entry.name.startswith('urllib3-') or entry.name.startswith('urllib3.') or entry.name == 'urllib3.dist-info':
                    need(re.fullmatch(PATTERN, entry.name) is not None, 'UNEXPECTED_LAYOUT')
                    names.append(entry.name)
                    need(len(names) <= 8, 'BOUND_EXCEEDED')
        result = []
        expected_metadata = False
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, 'O_NOATIME', 0)
        for name in sorted(names):
            ALLOWED.update({name, name + '/METADATA'})
            at('DIRECTORY', name)
            initial = os.stat(name, dir_fd=site, follow_symlinks=False)
            F['metadata'](initial, directory=True)
            directory = os.open(name, flags, dir_fd=site)
            try:
                before = os.fstat(directory)
                F['metadata'](before, directory=True)
                need(F['identity'](initial) == F['identity'](before), 'SYMLINK_OR_PATH_VIOLATION')
                raw = metadata_bytes(directory, name)
                version = re.fullmatch(PATTERN, name).group(1)
                classification = 'METADATA_MISSING'
                if raw is not None:
                    # Parse only headers, never descriptions or arbitrary fields.
                    headers = re.split(rb'\r?\n\r?\n', raw, maxsplit=1)[0]
                    dist = re.findall(rb'^Name:[ \t]*([^\r\n]*)\r?$', headers, re.M)
                    versions = re.findall(rb'^Version:[ \t]*([^\r\n]*)\r?$', headers, re.M)
                    need(dist == [b'urllib3'] and versions == [version.encode('ascii')], 'MALFORMED_METADATA')
                    record = SDK_LOCK['files'][EXPECTED + '/METADATA']
                    classification = 'VERSION_MISMATCH' if name != EXPECTED else (
                        'LOCK_MATCH' if record == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} else 'HASH_MISMATCH')
                    if name == EXPECTED:
                        expected_metadata = True
                at('STABILITY', name)
                after = os.fstat(directory)
                named = os.stat(name, dir_fd=site, follow_symlinks=False)
                need(F['identity'](before) == F['identity'](after) == F['identity'](named), 'SYMLINK_OR_PATH_VIOLATION')
                result.append({'identifier': name + '/METADATA', 'version': version, 'classification': classification})
            finally:
                os.close(directory)
        at('STABILITY', SENTINEL)
        need(baseline == F['identity'](os.fstat(site)), 'SYMLINK_OR_PATH_VIOLATION')
        current = F['directory_fd'](SITE, 'STABILITY', SENTINEL)
        try:
            need(baseline == F['identity'](os.fstat(current)), 'SYMLINK_OR_PATH_VIOLATION')
        finally:
            os.close(current)
        layout = 'MISSING' if not names else 'MULTIPLE' if len(names) > 1 else (
            'INCOMPLETE' if result[0]['classification'] == 'METADATA_MISSING' else
            'EXPECTED' if result[0]['classification'] == 'LOCK_MATCH' else
            'DIFFERENT_VERSION' if result[0]['classification'] == 'VERSION_MISMATCH' else 'HASH_MISMATCH')
        return layout, EXPECTED in names, expected_metadata, result
    finally:
        os.close(site)


def main():
    runtime = False
    report = {'status': 'BLOCKED', 'runtime_verified': False, 'layout': 'UNVERIFIED',
              'expected_directory': None, 'expected_metadata': None, 'entries': [], 'failure': None}
    STATE.update(stage='RUNTIME', dependency_id='PYTHON_RUNTIME', category=None)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        RUNTIME_CHECK()
        runtime = True
        layout, directory, metadata, entries = observe()
        report.update(status='PASS', layout=layout, expected_directory=directory, expected_metadata=metadata, entries=entries)
    except Exception as error:
        if isinstance(error, OSError):
            try:
                F['filesystem_failure'](error)
            except Exception:
                pass
        report['failure'] = {'dependency_id': STATE['dependency_id'] if identifier_ok(STATE['dependency_id']) else SENTINEL,
                             'stage': STATE['stage'], 'category': STATE['category'] or 'OTHER_VERIFICATION_FAILURE'}
    report['runtime_verified'] = runtime
    print(json.dumps(validate_report(report), sort_keys=True, allow_nan=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
